"""Motor de workflows con estado — cada registro avanza paso a paso, como en HubSpot.

Un workflow corre sobre empresas o contactos (`wf["object"]`, ver objects.py) y es
disparador + grafo de pasos (ver rules.py). Cada registro que entra tiene una fila
en `prospect_wf_enrollments` (company_id siempre; contact_id si es de contactos)
que dice en qué paso está y cuándo sigue (`wake_at`).

`tick()` es la única puerta de entrada al procesamiento:
  1. inscribe — filtro (sólo en la transición no cumple -> cumple, con la memoria
     de `prospect_wf_match`), horario;
  2. cierra las inscripciones que cumplen la meta o la desinscripción;
  3. avanza las que ya les toca, nodo por nodo, hasta una espera o el final.

Lo llaman: el PATCH de una empresa o de un contacto y el webhook de Clay
(acotado a esa empresa, "al instante"), el cron, y "Avanzar el reloj" del Test
panel (hora simulada). Los disparadores por evento entran por `emit_event()`.

"Acotado a una empresa" vale para los dos objetos: los workflows de empresa miran
esa empresa y los de contacto, sus contactos. Así un cambio en la empresa
re-evalúa las condiciones `company.*` de sus contactos y viceversa.

Freno de la fase de prueba: con AUTOMATION_REAL_DATA = False, todo lo
automático (`automatic=True`) sólo toca dummies. Y aparte, SIEMPRE: un efecto
hacia afuera (mail, Slack, To-Do, webhook) sobre un registro dummy va a un
destino de prueba con [TEST] — una dummy nunca le escribe a una persona real.
"""
from __future__ import annotations

import html
import logging
import random
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from prospecting import store
from prospecting.constants import (
    ACTIONS,
    AUTOMATION_REAL_DATA,
    DELAYS,
    MAX_STEPS_PER_RUN,
    TEST_EMAIL,
    TEST_SLACK_CHANNEL,
    TIMEZONE,
    WEEKDAYS,
)
from prospecting.objects import OBJECTS, resolve
from prospecting.rules import (
    compile_conditions,
    has_conditions,
    matches,
    number_nodes,
    parse_date,
    parse_datetime,
    parse_int,
    parse_number,
    uses_cross,
    uses_history,
)

TZ = ZoneInfo(TIMEZONE)
PAGE_URL = "https://vinttihub.vintti.com/prospecting.html"
OPEN_STATUSES = ("active", "waiting")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def local(now: datetime) -> datetime:
    return now.astimezone(TZ)


def as_of_of(now: datetime) -> date:
    return local(now).date()


def _at_local(d: date, hhmm: str | None) -> datetime:
    h, m = (int(x) for x in (hhmm or "00:00").split(":"))
    return datetime.combine(d, time(h, m), tzinfo=TZ).astimezone(timezone.utc)


def _plain(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def obj_of(wf: dict) -> str:
    return wf.get("object") or "company"


def field_label(obj: str, key: str) -> str:
    target, f, cross = resolve(obj, key)
    if not f:
        return key
    return ("Empresa · " if cross and target == "company" else "") + f["label"]


# --------------------------------------------------------------------------- #
# Registros, historial y relacionados
# --------------------------------------------------------------------------- #
def load_company(cur, company_id: int, lock: bool = False) -> dict | None:
    cur.execute(
        "SELECT * FROM prospect_companies WHERE id = %s" + (" FOR UPDATE" if lock else ""),
        (company_id,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def load_contact(cur, contact_id: int, lock: bool = False) -> dict | None:
    cur.execute(
        """
        SELECT ct.*, c.name AS company_name FROM prospect_contacts ct
          JOIN prospect_companies c ON c.id = ct.company_id WHERE ct.id = %s
        """ + (" FOR UPDATE OF ct" if lock else ""),
        (contact_id,),
    )
    row = cur.fetchone()
    return store._flatten_contact(row) if row else None


def load_record(cur, obj: str, record_id: int, lock: bool = False) -> dict | None:
    return load_contact(cur, record_id, lock) if obj == "contact" else load_company(cur, record_id, lock)


def load_history(cur, record_ids, obj: str = "company") -> dict:
    """{id: {field: [{"new", "at"}]}} para los operadores de historial."""
    ids = list(record_ids)
    if not ids:
        return {}
    if obj == "contact":
        cur.execute(
            "SELECT contact_id AS rid, field, new_value, at FROM prospect_company_events WHERE contact_id = ANY(%s)",
            (ids,),
        )
    else:
        cur.execute(
            """
            SELECT company_id AS rid, field, new_value, at FROM prospect_company_events
             WHERE company_id = ANY(%s) AND contact_id IS NULL AND field = ANY(%s)
            """,
            (ids, list(OBJECTS["company"]["history"])),
        )
    out: dict = {}
    for r in cur.fetchall():
        out.setdefault(r["rid"], {}).setdefault(r["field"], []).append({"new": r["new_value"], "at": r["at"]})
    return out


def related_of(cur, obj: str, row: dict) -> dict:
    """Lo que necesita una condición cruzada: la empresa de un contacto, o los contactos
    de una empresa (con su historial)."""
    if obj == "contact":
        comp = load_company(cur, row["company_id"])
        h = load_history(cur, [row["company_id"]], "company").get(row["company_id"], {})
        return {"company": {"row": comp, "history": h}} if comp else {}
    contacts = store.company_contacts(cur, row["id"])
    hist = load_history(cur, [c["id"] for c in contacts], "contact")
    return {"contacts": [{"row": c, "history": hist.get(c["id"], {})} for c in contacts]}


def _row_matches(cur, conditions, row: dict, now: datetime, obj: str = "company",
                 history: dict | None = None) -> bool:
    if not has_conditions(conditions):
        return True
    if history is None and uses_history(conditions):
        history = load_history(cur, [row["id"]], obj).get(row["id"], {})
    rel = related_of(cur, obj, row) if uses_cross(conditions) else {}
    return matches(conditions, row, as_of_of(now), now, history or {}, obj=obj, related=rel)


def _company_id_of(obj: str, row: dict) -> int:
    return row["company_id"] if obj == "contact" else row["id"]


# --------------------------------------------------------------------------- #
# Inscripciones
# --------------------------------------------------------------------------- #
def _log(cur, enrollment_id: int, node_id, kind: str, summary: str, now: datetime,
         detail=None, ok: bool = True) -> None:
    from psycopg2.extras import Json

    cur.execute(
        """
        INSERT INTO prospect_wf_step_log (enrollment_id, node_id, kind, summary, detail, ok, at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (enrollment_id, node_id, kind, summary, Json(detail) if detail is not None else None, ok, now),
    )


def _rec_col(obj: str) -> str:
    return "contact_id" if obj == "contact" else "company_id"


def enroll(cur, wf: dict, record_id: int, source: str, now: datetime, actor: str | None) -> int | None:
    """Inscribe si corresponde. Devuelve el id de la inscripción, o None si no entró."""
    obj = obj_of(wf)
    col = _rec_col(obj)
    cur.execute(
        f"SELECT status FROM prospect_wf_enrollments WHERE workflow_id = %s AND {col} = %s",
        (wf["id"], record_id),
    )
    statuses = [r["status"] for r in cur.fetchall()]
    if any(s in OPEN_STATUSES for s in statuses):
        return None  # ya está adentro
    if statuses and not wf.get("reenroll", True):
        return None  # reinscripción apagada: una sola vez
    if obj == "contact":
        cur.execute("SELECT company_id FROM prospect_contacts WHERE id = %s", (record_id,))
        r = cur.fetchone()
        if r is None:
            return None
        company_id, contact_id = r["company_id"], record_id
    else:
        company_id, contact_id = record_id, None
    start = (wf.get("steps") or {}).get("start")
    cur.execute(
        """
        INSERT INTO prospect_wf_enrollments
            (workflow_id, company_id, contact_id, status, current_node, wake_at, source, enrolled_by, enrolled_at)
        VALUES (%s, %s, %s, 'active', %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (wf["id"], company_id, contact_id, start, now, source, actor, now),
    )
    eid = cur.fetchone()["id"]
    _log(cur, eid, None, "enrolled", _source_text(source, actor), now)
    return eid


def _source_text(source: str, actor: str | None) -> str:
    if source == "manual":
        return f"Inscripto a mano por {actor or 'alguien'}"
    if source == "schedule":
        return "Inscripto por el horario del workflow"
    if source == "event":
        return "Inscripto por un evento"
    if source and source.startswith("workflow:"):
        return f"Inscripto por el workflow #{source.split(':', 1)[1]}"
    return "Inscripto porque cumplió las condiciones"


def _close(cur, enr_id: int, status: str, summary: str, now: datetime, error: str | None = None) -> None:
    cur.execute(
        """
        UPDATE prospect_wf_enrollments
           SET status = %s, finished_at = %s, wake_at = NULL, wait_deadline = NULL, last_error = %s
         WHERE id = %s
        """,
        (status, now, error, enr_id),
    )
    _log(cur, enr_id, None, status, summary, now, ok=status != "failed")


def unenroll_record(cur, wf: dict, record_id: int, now: datetime, why: str) -> int:
    col = _rec_col(obj_of(wf))
    cur.execute(
        f"""
        SELECT id FROM prospect_wf_enrollments
         WHERE workflow_id = %s AND {col} = %s AND status IN ('active', 'waiting')
        """,
        (wf["id"], record_id),
    )
    ids = [r["id"] for r in cur.fetchall()]
    for eid in ids:
        _close(cur, eid, "unenrolled", why, now)
    return len(ids)


# --------------------------------------------------------------------------- #
# Alcance (freno de la fase de prueba)
# --------------------------------------------------------------------------- #
def _dummy_only(automatic: bool, dummy_only: bool) -> bool:
    return dummy_only or (automatic and not AUTOMATION_REAL_DATA)


def _scope_sql(obj: str, dummy_only: bool, company_id: int | None) -> tuple[str, list]:
    """Filtro sobre la tabla del objeto: sólo dummies y/o sólo una empresa (para un
    contacto, "los de esa empresa")."""
    t = OBJECTS[obj]["table"]
    parts, params = [], []
    if dummy_only:
        parts.append(f"{t}.is_dummy")
    if company_id is not None:
        parts.append(f"{t}.{'company_id' if obj == 'contact' else 'id'} = %s")
        params.append(company_id)
    return "".join(" AND " + x for x in parts), params


# --------------------------------------------------------------------------- #
# Disparadores
# --------------------------------------------------------------------------- #
def matching_ids(cur, conditions: dict, now: datetime, dummy_only: bool, company_id: int | None = None,
                 obj: str = "company") -> list[int]:
    t = OBJECTS[obj]["table"]
    cond_sql, params = compile_conditions(conditions, as_of_of(now), now, obj)
    scope, sp = _scope_sql(obj, dummy_only, company_id)
    cur.execute(f"SELECT {t}.id FROM {t} WHERE {cond_sql} {scope} ORDER BY {t}.id", params + sp)
    return [r["id"] for r in cur.fetchall()]


def snapshot_matches(cur, wf: dict, now: datetime, matching: list[int]) -> None:
    """Anota como "ya cumplía" a los que cumplen hoy, sin inscribirlos (al activar
    sin "inscribir también los que ya cumplen", como HubSpot)."""
    for rid in matching:
        cur.execute(
            """
            INSERT INTO prospect_wf_match (workflow_id, record_id, matching, changed_at)
            VALUES (%s, %s, TRUE, %s)
            ON CONFLICT (workflow_id, record_id) DO UPDATE SET matching = TRUE, changed_at = EXCLUDED.changed_at
            """,
            (wf["id"], rid, now),
        )


def _sync_filter(cur, wf: dict, now: datetime, dummy_only: bool, company_id: int | None, actor) -> int:
    obj = obj_of(wf)
    t = OBJECTS[obj]["table"]
    matching = set(matching_ids(cur, wf["trigger"]["conditions"], now, dummy_only, company_id, obj))
    scope, sp = _scope_sql(obj, dummy_only, company_id)
    cur.execute(
        f"""
        SELECT s.record_id, s.matching FROM prospect_wf_match s
          JOIN {t} ON {t}.id = s.record_id
         WHERE s.workflow_id = %s {scope}
        """,
        [wf["id"]] + sp,
    )
    prev = {r["record_id"]: r["matching"] for r in cur.fetchall()}
    newly = sorted(c for c in matching if not prev.get(c))
    gone = [c for c, m in prev.items() if m and c not in matching]
    for c in gone:
        cur.execute(
            "UPDATE prospect_wf_match SET matching = FALSE, changed_at = %s WHERE workflow_id = %s AND record_id = %s",
            (now, wf["id"], c),
        )
    snapshot_matches(cur, wf, now, newly)
    return sum(1 for c in newly if enroll(cur, wf, c, "trigger", now, actor))


def last_schedule_slot(sch: dict, now: datetime) -> datetime | None:
    """El último momento programado <= now (o None si no hubo ninguno)."""
    loc = local(now)
    kind = sch.get("kind")
    if kind == "date":
        slot = _at_local(parse_date(sch.get("date")), sch.get("time"))
        return slot if slot <= now else None
    days = None if kind == "daily" else {parse_int(d) for d in sch.get("days") or []}
    for back in range(0, 8):
        d = loc.date() - timedelta(days=back)
        if days is not None and d.weekday() not in days:
            continue
        slot = _at_local(d, sch.get("time"))
        if slot <= now:
            return slot
    return None


def _fire_schedule(cur, wf: dict, now: datetime, dummy_only: bool, actor) -> int:
    obj = obj_of(wf)
    slot = last_schedule_slot(wf["trigger"].get("schedule") or {}, now)
    if slot is None:
        return 0
    cur.execute("SELECT last_fired FROM prospect_wf_schedule_state WHERE workflow_id = %s", (wf["id"],))
    row = cur.fetchone()
    if row and row["last_fired"] >= slot:
        return 0
    cur.execute(
        """
        INSERT INTO prospect_wf_schedule_state (workflow_id, last_fired) VALUES (%s, %s)
        ON CONFLICT (workflow_id) DO UPDATE SET last_fired = EXCLUDED.last_fired
        """,
        (wf["id"], now),
    )
    conds = wf["trigger"].get("conditions")
    if has_conditions(conds):
        ids = matching_ids(cur, conds, now, dummy_only, None, obj)
    else:
        t = OBJECTS[obj]["table"]
        scope, sp = _scope_sql(obj, dummy_only, None)
        cur.execute(f"SELECT {t}.id FROM {t} WHERE TRUE {scope} ORDER BY {t}.id", sp)
        ids = [r["id"] for r in cur.fetchall()]
    return sum(1 for c in ids if enroll(cur, wf, c, "schedule", now, actor))


def emit_event(cur, obj: str, record_id: int, kind: str, changes: list[dict], now: datetime | None = None,
               actor: str | None = None, automatic: bool = True) -> int:
    """Disparadores por evento del objeto. kind: 'created' | 'updated'. `changes` = [{field, old, new}]."""
    from prospecting.workflows import list_enabled

    now = now or utcnow()
    row = load_record(cur, obj, record_id)
    if row is None:
        return 0
    if _dummy_only(automatic, False) and not row["is_dummy"]:
        return 0
    enrolled = 0
    for wf in list_enabled(cur):
        if obj_of(wf) != obj:
            continue
        t = wf["trigger"]
        if t.get("type") != "event":
            continue
        hit = False
        if t.get("event") == "created":
            hit = kind == "created"
        elif t.get("event") == "property_changed" and kind in ("updated", "created"):
            to = [str(x) for x in (t.get("to_values") or [])]
            for ch in changes:
                if ch["field"] != t.get("field") or kind == "created" and ch["new"] is None:
                    continue
                new = ch["new"]
                if not to or (new is not None and str(_plain(new)) in to):
                    hit = True
        if hit and _row_matches(cur, t.get("conditions"), row, now, obj):
            if enroll(cur, wf, record_id, "event", now, actor):
                enrolled += 1
    return enrolled


# --------------------------------------------------------------------------- #
# Días hábiles y franja horaria
# --------------------------------------------------------------------------- #
def next_allowed(settings: dict, now: datetime) -> datetime:
    """`now` si se puede ejecutar ya; si no, el próximo momento permitido (hora AR)."""
    settings = settings or {}
    weekdays_only = bool(settings.get("business_days"))
    window = settings.get("window") or None
    loc = local(now)
    for add in range(0, 9):
        d = loc.date() + timedelta(days=add)
        if weekdays_only and d.weekday() >= 5:
            continue
        if not window:
            return now if add == 0 else _at_local(d, "00:00")
        start, end = _at_local(d, window["from"]), _at_local(d, window["to"])
        if add == 0:
            if now < start:
                return start
            if now < end:
                return now
            continue
        return start
    return now


# --------------------------------------------------------------------------- #
# Acciones
# --------------------------------------------------------------------------- #
def _user_name(cur, email: str | None) -> str:
    if not email:
        return "sin owner"
    cur.execute("SELECT user_name FROM users WHERE LOWER(TRIM(email_vintti)) = %s LIMIT 1", (email.lower(),))
    r = cur.fetchone()
    return (r["user_name"] if r and r.get("user_name") else email)


def render_tokens(cur, text: str, row: dict, obj: str = "company") -> str:
    owner = row.get(OBJECTS[obj]["owner_field"])
    vals = {
        "{empresa}": (row.get("company_name") if obj == "contact" else row.get("name")) or "",
        "{dominio}": row.get("domain") or "",
        "{owner}": _user_name(cur, owner),
        "{status}": row.get("prospecting_status") or row.get("lead_life") or "—",
        "{semana}": row.get("week_label") or "—",
        "{not_icp}": row.get("not_icp_reason") or "—",
        "{contacto}": row.get("name") if obj == "contact" else "",
        "{email_contacto}": row.get("email") if obj == "contact" else "",
        "{link}": PAGE_URL,
    }
    for k, v in vals.items():
        text = text.replace(k, str(v or ""))
    return text


def _edit_value(a: dict, field: dict, source_row: dict, cur_value, as_of: date, now: datetime):
    """Valor nuevo de una acción de "Editar registro" (ya tipado)."""
    t = a["type"]
    ftype = field["type"]
    if t == "clear":
        return None
    if t == "set_today":
        return now.isoformat() if ftype == "datetime" else as_of
    if t == "set_date_offset":
        days = parse_int(a.get("days")) or 0
        return (now + timedelta(days=days)).isoformat() if ftype == "datetime" else as_of + timedelta(days=days)
    if t == "increment":
        return int(round((parse_number(cur_value) or 0) + parse_number(a.get("amount"))))
    if t == "copy":
        v = source_row.get(a["from_field"].split(".", 1)[-1]) if source_row else None
        if v is None:
            return None
        if ftype in ("text", "longtext", "url", "email", "phone"):
            return str(_plain(v))
        if ftype == "date":
            return parse_date(v)
        if ftype == "datetime":
            dt = parse_datetime(v)
            return dt.isoformat() if dt else None
        return v
    v = a.get("value")  # set
    if ftype == "date":
        return parse_date(v)
    if ftype == "datetime":
        dt = parse_datetime(v)
        return dt.isoformat() if dt else None
    if ftype == "number":
        return int(parse_number(v)) if parse_number(v) == int(parse_number(v)) else parse_number(v)
    if ftype in ("owner", "user", "email"):
        return str(v).strip().lower()
    if ftype == "bool":
        return v if isinstance(v, bool) else str(v).lower() == "true"
    return str(v).strip() if isinstance(v, str) else v


def _same(a, b) -> bool:
    if a in (None, "", []) and b in (None, "", []):
        return True
    return str(_plain(a)) == str(_plain(b))


class Ctx:
    def __init__(self, wf: dict, node_id: str, now: datetime, actor: str | None, dry: bool):
        self.wf, self.node_id, self.now, self.actor, self.dry = wf, node_id, now, actor, dry
        self.as_of = as_of_of(now)
        self.obj = obj_of(wf)

    @property
    def source(self) -> str:
        return f"workflow:{self.wf.get('id') or 'prueba'}"


def describe_action(obj: str, a: dict) -> str:
    t = a.get("type")
    if ACTIONS.get(t, {}).get("field"):
        f = field_label(obj, a.get("field"))
        if t == "clear":
            return f"Borra {f}"
        if t == "set_today":
            return f"Define {f} como la fecha en que se ejecutó esta acción"
        if t == "set_date_offset":
            d = parse_int(a.get("days")) or 0
            return f"Define {f} como la fecha de ejecución {'+' if d >= 0 else '−'} {abs(d)} días"
        if t == "increment":
            n = parse_number(a.get("amount")) or 0
            return f"{'Suma' if n > 0 else 'Resta'} {abs(n):g} a {f}"
        if t == "copy":
            return f"Copia {field_label(obj, a.get('from_field'))} en {f}"
        return f"Define {f} como {a.get('value')}"
    return ACTIONS.get(t, {}).get("label", t)


def _apply_edit(cur, ctx: Ctx, row: dict, target: str, key: str, new) -> dict:
    """Escribe el cambio en el registro (o en la empresa asociada) y dispara sus eventos."""
    if target == "company":
        cid = _company_id_of(ctx.obj, row)
        updated = store.update_company(cur, cid, {key: new}, actor=ctx.actor, source=ctx.source)
        emit_event(cur, "company", cid, "updated", updated["_changes"], ctx.now, ctx.actor)
        if ctx.obj == "company":
            row.update({k: v for k, v in updated.items() if not k.startswith("_")})
    else:
        updated = store.update_contact(cur, row["id"], {key: new}, actor=ctx.actor, source=ctx.source)
        emit_event(cur, "contact", row["id"], "updated", updated["_changes"], ctx.now, ctx.actor)
        row.update({k: v for k, v in updated.items() if not k.startswith("_")})
    return updated


def run_action(cur, a: dict, row: dict, ctx: Ctx) -> dict:
    """Ejecuta (o, con ctx.dry, sólo describe) una acción. Devuelve
    {"summary", "changes"?}. Con dry=True actualiza `row` (y `ctx.sim_company`) en
    memoria para que los pasos siguientes de la prueba lo vean."""
    t = a["type"]
    obj = ctx.obj
    test = bool(row.get("is_dummy"))

    # ---- Editar registro (propio o de la empresa asociada) ---------------- #
    if ACTIONS[t].get("field") or t == "rotate_owner":
        if t == "rotate_owner":
            target, key = obj, OBJECTS[obj]["owner_field"]
            field = OBJECTS[obj]["fields"][key]
            owners = list(a.get("owners") or [])
            if a.get("only_if_empty") and row.get(key):
                return {"summary": f"Ya tiene owner ({row[key]}): no se reparte."}
            cur.execute(
                "SELECT last_index FROM prospect_wf_rotation WHERE workflow_id = %s AND node_id = %s",
                (ctx.wf.get("id") or 0, ctx.node_id),
            )
            r = cur.fetchone()
            idx = ((r["last_index"] if r else -1) + 1) % len(owners)
            new = owners[idx]
            if not ctx.dry and ctx.wf.get("id"):
                cur.execute(
                    """
                    INSERT INTO prospect_wf_rotation (workflow_id, node_id, last_index) VALUES (%s, %s, %s)
                    ON CONFLICT (workflow_id, node_id) DO UPDATE SET last_index = EXCLUDED.last_index
                    """,
                    (ctx.wf["id"], ctx.node_id, idx),
                )
            summary = f"Le toca a {new} (turno {idx + 1} de {len(owners)})"
            old = row.get(key)
        else:
            target, field, _cross = resolve(obj, a["field"])
            key = field["key"]
            # Valor actual y fila de origen (para "copiar"), propios o de la empresa.
            company_row = None
            if target != obj or (a.get("from_field") or "").startswith("company."):
                company_row = getattr(ctx, "sim_company", None) or load_company(cur, _company_id_of(obj, row))
            holder = company_row if target != obj else row
            src_row = company_row if (a.get("from_field") or "").startswith("company.") else row
            old = holder.get(key) if holder else None
            new = _edit_value(a, field, src_row, old, ctx.as_of, ctx.now)
            summary = describe_action(obj, a)
        if _same(old, new):
            return {"summary": summary + " — ya estaba así, sin cambios."}
        label_key = key if target == obj else f"company.{key}"
        changes = {label_key: {"from": _plain(old), "to": _plain(new)}}
        if ctx.dry:
            if target == obj:
                row[key] = new
            else:
                ctx.sim_company = dict(company_row or {})
                ctx.sim_company[key] = new
            return {"summary": summary, "changes": changes}
        _apply_edit(cur, ctx, row, target, key, new)
        return {"summary": summary, "changes": changes}

    # ---- Asociaciones (contactos) ------------------------------------------ #
    if t == "associate_company":
        email = (row.get("email") or "").lower()
        domain = email.split("@", 1)[1] if "@" in email else ""
        if not domain:
            return {"summary": "Crear asociación: el contacto no tiene email, queda como está."}
        cur.execute(
            """
            SELECT id, name FROM prospect_companies
             WHERE domain = %s AND is_dummy = %s
             ORDER BY id LIMIT 1
            """,
            (store.normalize_domain(domain), bool(row.get("is_dummy"))),
        )
        target = cur.fetchone()
        current = row.get("company_name") or f"#{row.get('company_id')}"
        if target is None:
            return {"summary": f"Crear asociación: no hay una empresa con el dominio {domain}; sigue asociado a {current}."}
        if target["id"] == row["company_id"]:
            return {"summary": f"Crear asociación: ya estaba asociado a {target['name']}."}
        summary = f"Asocia el contacto a {target['name']} (antes: {current})"
        if ctx.dry:
            return {"summary": summary}
        old_company = row["company_id"]
        cur.execute("UPDATE prospect_contacts SET company_id = %s, is_primary = FALSE, updated_at = NOW() WHERE id = %s",
                    (target["id"], row["id"]))
        cur.execute(
            "UPDATE prospect_wf_enrollments SET company_id = %s WHERE contact_id = %s AND status IN ('active', 'waiting')",
            (target["id"], row["id"]),
        )
        store.log_event(cur, old_company, ctx.source, ctx.actor, None, None,
                        f"contact_moved_to:{target['name']}", contact_id=row["id"])
        store.log_event(cur, target["id"], ctx.source, ctx.actor, None, None,
                        f"contact_moved_from:{current}", contact_id=row["id"])
        store.recompute_contact_incomplete(cur, old_company)
        store.recompute_contact_incomplete(cur, target["id"])
        row["company_id"], row["company_name"] = target["id"], target["name"]
        return {"summary": summary}

    # ---- Comunicación ---------------------------------------------------- #
    owner = row.get(OBJECTS[obj]["owner_field"])
    if t == "add_note":
        text = render_tokens(cur, a["text"], row, obj)
        if not ctx.dry:
            store.log_event(cur, _company_id_of(obj, row), ctx.source, ctx.actor, "__note__", None, text,
                            contact_id=row["id"] if obj == "contact" else None)
        return {"summary": f"Nota: {text}"}

    if t == "create_todo":
        assignee = owner if (a.get("assignee") or "owner") == "owner" else a["assignee"]
        if not assignee:
            return {"summary": "Crear To-Do: no tiene owner, no se crea."}
        text = render_tokens(cur, a["text"], row, obj)
        due = ctx.as_of + timedelta(days=parse_int(a.get("due_days")) or 0)
        target = TEST_EMAIL if test else assignee
        if test:
            text = f"[TEST] (para {assignee}) {text}"
        summary = f"To-Do para {target} (vence {due.isoformat()}): {text}"
        if ctx.dry:
            return {"summary": summary}
        cur.execute("SELECT user_id FROM users WHERE LOWER(TRIM(email_vintti)) = %s LIMIT 1", (target.lower(),))
        u = cur.fetchone()
        if not u:
            raise RuntimeError(f"No hay un usuario del Hub con el mail {target}.")
        from routes.to_do_routes import _next_todo_id

        cur.execute(
            "SELECT COALESCE(MAX(orden), 0) + 1 AS o FROM to_do WHERE user_id = %s AND subtask IS NULL",
            (u["user_id"],),
        )
        orden = cur.fetchone()["o"]
        cur.execute(
            """
            INSERT INTO to_do (to_do_id, user_id, description, due_date, "check", orden, subtask)
            VALUES (%s, %s, %s, %s, FALSE, %s, NULL)
            """,
            (_next_todo_id(cur), u["user_id"], text[:1000], due, orden),
        )
        return {"summary": summary}

    if t == "send_email":
        to = sorted({(owner if x == "owner" else x.lower()) for x in a["to"] if (x != "owner" or owner)})
        if not to:
            return {"summary": "Mail: no tiene owner y no hay otro destinatario, no se manda."}
        subject = render_tokens(cur, a["subject"], row, obj)
        body = html.escape(render_tokens(cur, a["body"], row, obj)).replace("\n", "<br>")
        if test:
            body = f"<p><em>[TEST] Habría ido a: {html.escape(', '.join(to))}</em></p>" + body
            subject, to = f"[TEST] {subject}", [TEST_EMAIL]
        summary = f"Mail a {', '.join(to)}: {subject}"
        if ctx.dry:
            return {"summary": summary}
        from utils.transactional_email import post_transactional_email

        res = post_transactional_email(to, subject, body, "prospecting workflow")
        if not res.get("sent"):
            raise RuntimeError(f"No se pudo mandar el mail (HTTP {res.get('status_code')}).")
        return {"summary": summary}

    if t == "send_slack":
        text = render_tokens(cur, a["text"], row, obj)
        channel = (a.get("channel") or "").strip() or None
        if test:
            text = f"[TEST] {text}"
            channel = TEST_SLACK_CHANNEL
        summary = f"Slack{(' a ' + channel) if channel else ''}: {text}"
        if ctx.dry:
            return {"summary": summary}
        from utils import slack

        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": slack.esc(text)}}]
        res = slack.post_blocks(blocks, text, channel_override=channel)
        if not res.get("sent"):
            raise RuntimeError(f"Slack no lo aceptó: {res.get('error')}")
        return {"summary": summary}

    if t == "webhook":
        url = a["url"].strip()
        if test or ctx.dry:
            return {"summary": f"Webhook a {url}" + (" — simulado (registro dummy), no se mandó." if test else "")}
        payload = {
            "workflow": {"id": ctx.wf.get("id"), "name": ctx.wf.get("name"), "object": obj},
            obj: {k: _plain(v) for k, v in row.items() if k != "raw_payload"},
        }
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code >= 400:
            raise RuntimeError(f"El webhook respondió {r.status_code}.")
        return {"summary": f"Webhook a {url}: respondió {r.status_code}."}

    # ---- Otros workflows -------------------------------------------------- #
    if t in ("enroll_workflow", "unenroll_workflow"):
        from prospecting.workflows import get_workflow

        other = get_workflow(cur, parse_int(a["workflow_id"]))
        if other is None:
            raise RuntimeError("El workflow de destino ya no existe.")
        oobj = obj_of(other)
        # Entre objetos distintos: un contacto lleva a su empresa; una empresa, a sus contactos.
        if oobj == obj:
            targets = [row["id"]]
        elif oobj == "company":
            targets = [row["company_id"]]
        else:
            targets = [c["id"] for c in store.company_contacts(cur, row["id"])]
        if t == "enroll_workflow":
            if ctx.dry:
                return {"summary": f"Inscribe en «{other['name']}»."}
            n = sum(1 for rid in targets if enroll(cur, other, rid, ctx.source, ctx.now, ctx.actor))
            return {"summary": f"Inscripto en «{other['name']}»." if n else f"Ya estaba en «{other['name']}» (o no se reinscribe)."}
        if ctx.dry:
            return {"summary": f"Saca de «{other['name']}»."}
        n = sum(unenroll_record(cur, other, rid, ctx.now, f"Sacado por el workflow #{ctx.wf.get('id')}") for rid in targets)
        return {"summary": f"Sacado de «{other['name']}»." if n else f"No estaba en «{other['name']}»."}

    raise RuntimeError(f"Acción desconocida: {t}")


# --------------------------------------------------------------------------- #
# Esperas y ramas
# --------------------------------------------------------------------------- #
def describe_delay(obj: str, d: dict) -> str:
    k = d.get("kind")
    if k == "duration":
        parts = [(parse_int(d.get("days") or 0), "día"), (parse_int(d.get("hours") or 0), "hora"),
                 (parse_int(d.get("minutes") or 0), "minuto")]
        return "Espera " + " y ".join(f"{n} {w}{'s' if n != 1 else ''}" for n, w in parts if n)
    if k == "until_date":
        return f"Espera hasta el {d.get('date')}" + (f" a las {d['time']}" if d.get("time") else "")
    if k == "until_property":
        off = parse_int(d.get("offset_days") or 0)
        rel = f" {'+' if off >= 0 else '−'} {abs(off)} días" if off else ""
        return f"Espera hasta {field_label(obj, d.get('field'))}{rel}" + (f" a las {d['time']}" if d.get("time") else "")
    if k == "until_weekday":
        names = ", ".join(WEEKDAYS[parse_int(x)] for x in sorted(d.get("days") or []))
        return f"Espera hasta el próximo {names} a las {d.get('time')}"
    if k == "until_time":
        return f"Espera hasta las {d.get('time')}"
    if k == "until_condition":
        return f"Espera hasta que se cumpla la condición (máximo {d.get('max_days')} días)"
    return DELAYS.get(k, {}).get("label", "Espera")


def _value_of(cur, obj: str, row: dict, key: str):
    target, field, cross = resolve(obj, key)
    if not field:
        return None
    if cross and target == "company":
        comp = load_company(cur, row["company_id"])
        return comp.get(field["key"]) if comp else None
    return row.get(field["key"])


def compute_wake(cur, obj: str, d: dict, now: datetime, row: dict) -> datetime | None:
    k = d["kind"]
    loc = local(now)
    if k == "duration":
        return now + timedelta(days=parse_int(d.get("days") or 0), hours=parse_int(d.get("hours") or 0),
                               minutes=parse_int(d.get("minutes") or 0))
    if k == "until_date":
        return _at_local(parse_date(d["date"]), d.get("time"))
    if k == "until_property":
        raw = _value_of(cur, obj, row, d["field"])
        base = parse_datetime(raw).astimezone(TZ).date() if isinstance(raw, str) and "T" in raw else parse_date(raw)
        if base is None:
            return None
        return _at_local(base + timedelta(days=parse_int(d.get("offset_days") or 0)), d.get("time") or "09:00")
    if k == "until_weekday":
        days = {parse_int(x) for x in d["days"]}
        for add in range(0, 8):
            day = loc.date() + timedelta(days=add)
            if day.weekday() in days:
                slot = _at_local(day, d["time"])
                if slot > now:
                    return slot
        return None
    if k == "until_time":
        slot = _at_local(loc.date(), d["time"])
        return slot if slot > now else _at_local(loc.date() + timedelta(days=1), d["time"])
    return None


def describe_branch(obj: str, b: dict) -> list[str]:
    """Etiqueta de cada salida: [rama1, rama2, ..., "si no"]."""
    k = b.get("kind")
    labels = []
    for p in b.get("paths") or []:
        if k == "value":
            labels.append(f"{field_label(obj, b.get('field'))} es {' o '.join(map(str, p.get('values') or []))}")
        elif k == "random":
            labels.append(f"{p.get('pct')}%")
        else:
            labels.append(p.get("label") or "Rama")
    if k != "random":
        labels.append("Ninguna de las anteriores")
    return labels


def choose_branch(cur, obj: str, b: dict, row: dict, now: datetime, history=None, sim_company=None) -> tuple:
    """(índice, next) de la rama que toma el registro. El índice len(paths) = "si no"."""
    paths = b.get("paths") or []
    k = b["kind"]
    if k == "random":
        roll = random.uniform(0, 100)
        acc = 0
        for i, p in enumerate(paths):
            acc += parse_int(p.get("pct")) or 0
            if roll < acc:
                return i, p.get("next")
        return len(paths) - 1, paths[-1].get("next")
    for i, p in enumerate(paths):
        if k == "value":
            target, field, cross = resolve(obj, b["field"])
            val = (sim_company or {}).get(field["key"]) if (cross and sim_company) else _value_of(cur, obj, row, b["field"])
            if val in (p.get("values") or []):
                return i, p.get("next")
        elif _row_matches(cur, p.get("conditions"), row, now, obj, history):
            return i, p.get("next")
    return len(paths), b.get("else_next")


# --------------------------------------------------------------------------- #
# Avance de una inscripción
# --------------------------------------------------------------------------- #
def _set_waiting(cur, enr_id: int, node, wake: datetime, deadline=None) -> None:
    cur.execute(
        """
        UPDATE prospect_wf_enrollments
           SET status = 'waiting', current_node = %s, wake_at = %s, wait_deadline = %s
         WHERE id = %s
        """,
        (node, wake, deadline, enr_id),
    )


def _record_id(obj: str, enr: dict) -> int:
    return enr["contact_id"] if obj == "contact" else enr["company_id"]


def run_enrollment(cur, enr: dict, wf: dict, now: datetime, actor: str | None) -> str:
    """Avanza una inscripción hasta una espera o el final. Devuelve el estado final."""
    obj = obj_of(wf)
    nodes = wf["steps"].get("nodes") or {}
    order = number_nodes(wf["steps"])
    settings = wf.get("settings") or {}
    node_id = enr["current_node"]
    deadline = enr.get("wait_deadline")
    eid = enr["id"]
    rid = _record_id(obj, enr)
    cur.execute("UPDATE prospect_wf_enrollments SET status = 'active' WHERE id = %s", (eid,))
    for _ in range(MAX_STEPS_PER_RUN):
        if node_id is None or node_id not in nodes:
            _close(cur, eid, "completed", "Terminó el workflow", now)
            return "completed"
        node = nodes[node_id]
        n = order.get(node_id, "?")
        t = node["type"]
        if t == "action":
            allowed = next_allowed(settings, now)
            if allowed > now:
                _set_waiting(cur, eid, node_id, allowed)
                _log(cur, eid, node_id, "paused",
                     f"Paso {n}: fuera de horario, sigue el {local(allowed).strftime('%d/%m %H:%M')}", now)
                return "waiting"
            row = load_record(cur, obj, rid, lock=True)
            if row is None:
                _close(cur, eid, "unenrolled", "El registro se borró", now)
                return "unenrolled"
            res = run_action(cur, node["action"], row, Ctx(wf, node_id, now, actor, dry=False))
            _log(cur, eid, node_id, "action", f"Paso {n}: {res['summary']}", now, detail=res.get("changes"))
            node_id = node.get("next")
            continue
        if t == "delay":
            d = node["delay"]
            row = load_record(cur, obj, rid)
            if row is None:
                _close(cur, eid, "unenrolled", "El registro se borró", now)
                return "unenrolled"
            if d["kind"] == "until_condition":
                if deadline is None:
                    deadline = now + timedelta(days=parse_int(d.get("max_days")) or 1)
                    _log(cur, eid, node_id, "delay", f"Paso {n}: {describe_delay(obj, d)}", now)
                if _row_matches(cur, d.get("conditions"), row, now, obj):
                    _log(cur, eid, node_id, "wake", f"Paso {n}: se cumplió la condición, sigue", now)
                elif now >= deadline:
                    _log(cur, eid, node_id, "wake", f"Paso {n}: se venció la espera sin cumplirse, sigue", now)
                else:
                    _set_waiting(cur, eid, node_id, min(deadline, now + timedelta(hours=1)), deadline)
                    return "waiting"
                deadline = None
                cur.execute("UPDATE prospect_wf_enrollments SET wait_deadline = NULL WHERE id = %s", (eid,))
                node_id = node.get("next")
                continue
            wake = compute_wake(cur, obj, d, now, row)
            if wake is None or wake <= now:
                why = "la propiedad está vacía" if wake is None else "la fecha ya pasó"
                _log(cur, eid, node_id, "delay", f"Paso {n}: {describe_delay(obj, d)} — no espera ({why})", now)
                node_id = node.get("next")
                continue
            _set_waiting(cur, eid, node.get("next"), wake)
            _log(cur, eid, node_id, "delay",
                 f"Paso {n}: {describe_delay(obj, d)} — sigue el {local(wake).strftime('%d/%m/%Y %H:%M')}", now)
            return "waiting"
        if t == "branch":
            row = load_record(cur, obj, rid)
            if row is None:
                _close(cur, eid, "unenrolled", "El registro se borró", now)
                return "unenrolled"
            b = node["branch"]
            idx, nxt = choose_branch(cur, obj, b, row, now)
            _log(cur, eid, node_id, "branch", f"Paso {n}: va por la rama «{describe_branch(obj, b)[idx]}»", now)
            node_id = nxt
            continue
        raise RuntimeError(f"Paso {n}: tipo desconocido")
    _close(cur, eid, "failed",
           f"Se cortó: más de {MAX_STEPS_PER_RUN} pasos seguidos (¿un «ir a» que vuelve sin espera?)", now,
           error="loop")
    return "failed"


# --------------------------------------------------------------------------- #
# tick
# --------------------------------------------------------------------------- #
def _close_by_conditions(cur, wfs: dict, now: datetime, dummy_only: bool, company_id) -> int:
    closed = 0
    for wf in wfs.values():
        goal, unen = wf.get("goal"), wf.get("unenroll")
        by_trigger = (wf.get("settings") or {}).get("unenroll_if_not_matching") and wf["trigger"]["type"] == "filter"
        if not (has_conditions(goal) or has_conditions(unen) or by_trigger):
            continue
        obj = obj_of(wf)
        col = _rec_col(obj)
        params = [wf["id"]]
        extra = ""
        if dummy_only:
            extra += " AND c.is_dummy"
        if company_id is not None:
            extra += " AND e.company_id = %s"
            params.append(company_id)
        cur.execute(
            f"""
            SELECT e.id, e.{col} AS rid FROM prospect_wf_enrollments e
              JOIN prospect_companies c ON c.id = e.company_id
             WHERE e.status IN ('active', 'waiting') AND e.workflow_id = %s {extra}
            """,
            params,
        )
        rows = cur.fetchall()
        if not rows:
            continue
        history = load_history(cur, {r["rid"] for r in rows}, obj)
        for r in rows:
            row = load_record(cur, obj, r["rid"])
            if row is None:
                continue
            h = history.get(r["rid"], {})
            if has_conditions(goal) and _row_matches(cur, goal, row, now, obj, h):
                _close(cur, r["id"], "goal_met", "Cumplió la meta", now)
            elif has_conditions(unen) and _row_matches(cur, unen, row, now, obj, h):
                _close(cur, r["id"], "unenrolled", "Cumplió el criterio de desinscripción", now)
            elif by_trigger and not _row_matches(cur, wf["trigger"]["conditions"], row, now, obj, h):
                _close(cur, r["id"], "unenrolled", "Dejó de cumplir el disparador", now)
            else:
                continue
            closed += 1
    return closed


def advance(cur, now: datetime, dummy_only: bool, company_id=None, workflow_ids=None, actor=None,
            include_disabled: bool = False) -> dict:
    from prospecting.workflows import get_workflow

    stats = {"advanced": 0, "completed": 0, "failed": 0}
    for _ in range(3):  # una acción puede inscribir en otro workflow: otra pasada
        where, params = [], [now]
        if dummy_only:
            where.append("c.is_dummy")
        if company_id is not None:
            where.append("e.company_id = %s")
            params.append(company_id)
        if workflow_ids:
            where.append("e.workflow_id = ANY(%s)")
            params.append(list(workflow_ids))
        if not include_disabled:
            where.append("w.enabled")
        # Al instante (una empresa recién editada): las esperas "hasta que se cumpla
        # algo" se revisan ya, sin aguardar a su próxima revisión horaria.
        wait_cond = "OR e.wait_deadline IS NOT NULL" if company_id is not None else ""
        cur.execute(
            f"""
            SELECT e.* FROM prospect_wf_enrollments e
              JOIN prospect_companies c ON c.id = e.company_id
              JOIN prospect_workflows w ON w.id = e.workflow_id
             WHERE e.status IN ('active', 'waiting')
               AND (e.wake_at IS NULL OR e.wake_at <= %s {wait_cond})
               {''.join(' AND ' + x for x in where)}
             ORDER BY e.id
             FOR UPDATE OF e SKIP LOCKED
            """,
            params,
        )
        due = [dict(r) for r in cur.fetchall()]
        if not due:
            break
        cache: dict = {}
        for enr in due:
            wf = cache.get(enr["workflow_id"]) or get_workflow(cur, enr["workflow_id"])
            cache[enr["workflow_id"]] = wf
            cur.execute("SAVEPOINT wf_enr")
            try:
                status = run_enrollment(cur, enr, wf, now, actor)
                cur.execute("RELEASE SAVEPOINT wf_enr")
            except Exception as exc:  # una inscripción rota no frena a las demás
                logging.exception("prospecting workflow %s, inscripción %s", enr["workflow_id"], enr["id"])
                cur.execute("ROLLBACK TO SAVEPOINT wf_enr")
                _close(cur, enr["id"], "failed", f"Error: {exc}", now, error=str(exc)[:500])
                status = "failed"
            stats["advanced"] += 1
            if status in stats:
                stats[status] += 1
    return stats


def tick(cur, now: datetime | None = None, automatic: bool = True, company_id: int | None = None,
         dummy_only: bool = False, actor: str | None = None) -> dict:
    from prospecting.workflows import list_enabled

    now = now or utcnow()
    dummy_only = _dummy_only(automatic, dummy_only)
    wfs = {w["id"]: w for w in list_enabled(cur)}
    enrolled = 0
    for wf in wfs.values():
        t = wf["trigger"].get("type")
        if t == "filter":
            enrolled += _sync_filter(cur, wf, now, dummy_only, company_id, actor)
        elif t == "schedule" and company_id is None:
            enrolled += _fire_schedule(cur, wf, now, dummy_only, actor)
    closed = _close_by_conditions(cur, wfs, now, dummy_only, company_id) if wfs else 0
    stats = advance(cur, now, dummy_only, company_id, actor=actor)
    return {"now": now.isoformat(), "dummy_only": dummy_only, "enrolled": enrolled, "closed": closed, **stats}


def enroll_now(cur, wf: dict, now: datetime, actor: str | None, dummy_only: bool, record_ids=None) -> dict:
    """«Inscribir las que cumplen ahora» / inscripción manual: inscribe y avanza en el
    momento, aunque el workflow esté apagado (lo pide una persona)."""
    obj = obj_of(wf)
    if record_ids is None:
        conds = wf["trigger"].get("conditions")
        ids = matching_ids(cur, conds, now, dummy_only, None, obj) if has_conditions(conds) else []
        source = "trigger"
    else:
        ids = [int(c) for c in record_ids]
        source = "manual"
    new = [eid for eid in (enroll(cur, wf, c, source, now, actor) for c in ids) if eid]
    if wf["trigger"].get("type") == "filter" and record_ids is None:
        snapshot_matches(cur, wf, now, ids)
    stats = advance(cur, now, False, workflow_ids=[wf["id"]], actor=actor, include_disabled=True) if new else {}
    return {"enrolled": len(new), "candidates": len(ids), **stats}


# --------------------------------------------------------------------------- #
# Prueba con un registro (no escribe nada)
# --------------------------------------------------------------------------- #
def simulate(cur, wf: dict, record_id: int, now: datetime | None = None) -> dict:
    now = now or utcnow()
    obj = obj_of(wf)
    row = load_record(cur, obj, record_id)
    if row is None:
        raise LookupError(obj)
    history = load_history(cur, [record_id], obj).get(record_id, {})
    rel = related_of(cur, obj, row)
    t = wf["trigger"]
    tt = t.get("type")
    noun = "el contacto" if obj == "contact" else "la empresa"
    cond_ok = matches(t.get("conditions"), row, as_of_of(now), now, history, obj=obj, related=rel)
    if tt == "filter":
        enters = cond_ok
        trigger_note = "Cumple las condiciones de inscripción." if enters else f"Hoy {noun} NO cumple las condiciones de inscripción: no entraría sola."
    elif tt == "manual":
        enters, trigger_note = True, "Inscripción manual: entra cuando alguien la inscribe."
    elif tt == "event":
        enters = cond_ok
        trigger_note = "Entraría cuando ocurra el evento." if cond_ok else "Aunque ocurra el evento, hoy no cumple el filtro extra."
    else:
        enters = cond_ok
        trigger_note = "Entraría en el próximo horario." if cond_ok else "Hoy no cumple el filtro del horario."

    path = []
    order = number_nodes(wf["steps"])
    nodes = wf["steps"].get("nodes") or {}
    node_id = wf["steps"].get("start")
    sim_row = dict(row)
    ctx_holder = {"sim_company": None}
    for _ in range(MAX_STEPS_PER_RUN):
        if node_id is None or node_id not in nodes:
            path.append({"kind": "end", "summary": "Fin del workflow"})
            break
        node = nodes[node_id]
        n = order.get(node_id, "?")
        if node["type"] == "action":
            ctx = Ctx(wf, node_id, now, None, dry=True)
            ctx.sim_company = ctx_holder["sim_company"]
            res = run_action(cur, node["action"], sim_row, ctx)
            ctx_holder["sim_company"] = getattr(ctx, "sim_company", None)
            path.append({"node": node_id, "n": n, "kind": "action", "summary": res["summary"], "changes": res.get("changes")})
            node_id = node.get("next")
        elif node["type"] == "delay":
            path.append({"node": node_id, "n": n, "kind": "delay",
                         "summary": describe_delay(obj, node["delay"]) + " (en la prueba se saltea)"})
            node_id = node.get("next")
        else:
            b = node["branch"]
            idx, nxt = choose_branch(cur, obj, b, sim_row, now, history, ctx_holder["sim_company"])
            label = describe_branch(obj, b)[idx]
            extra = " (al azar: en la corrida real puede tocar otra)" if b["kind"] == "random" else ""
            path.append({"node": node_id, "n": n, "kind": "branch", "summary": f"Va por la rama «{label}»{extra}"})
            node_id = nxt
    else:
        path.append({"kind": "error", "summary": f"Más de {MAX_STEPS_PER_RUN} pasos: hay un loop sin espera."})
    name = row.get("name") if obj == "company" else f"{row.get('name')} ({row.get('company_name')})"
    return {"object": obj, "company": {"id": row["id"], "name": name, "is_dummy": row["is_dummy"]},
            "enters": enters, "trigger_note": trigger_note, "path": path}
