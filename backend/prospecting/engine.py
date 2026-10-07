"""Motor de workflows con estado — cada empresa avanza paso a paso, como en HubSpot.

Un workflow es disparador + grafo de pasos (ver rules.py). Cada empresa que entra
tiene una fila en `prospect_wf_enrollments` que dice en qué paso está y cuándo
sigue (`wake_at`). Así funcionan las esperas ("esperar 3 días") y las ramas.

`tick()` es la única puerta de entrada al procesamiento:
  1. inscribe — filtro (sólo en la transición no cumple -> cumple, con la memoria
     de `prospect_wf_match_state`), horario;
  2. cierra las inscripciones que cumplen la meta o la desinscripción;
  3. avanza las que ya les toca, nodo por nodo, hasta una espera o el final.

Lo llaman: el PATCH de una empresa y el webhook de Clay (acotado a esa empresa,
"al instante"), el cron, y "Avanzar el reloj" del Test panel (con una hora
simulada). Los disparadores por evento entran por `emit_event()`.

Freno de la fase de prueba: con AUTOMATION_REAL_DATA = False, todo lo
automático (`automatic=True`) sólo toca empresas dummy. Y aparte, SIEMPRE: un
efecto hacia afuera (mail, Slack, To-Do, webhook) sobre una empresa dummy va a
un destino de prueba con [TEST] — una dummy nunca le escribe a una persona real.
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
    FIELDS_BY_KEY,
    MAX_STEPS_PER_RUN,
    OPERATORS,
    TEST_EMAIL,
    TEST_SLACK_CHANNEL,
    TIMEZONE,
    WEEKDAYS,
)
from prospecting.rules import (
    HISTORY_FIELDS,
    compile_conditions,
    has_conditions,
    matches,
    number_nodes,
    parse_date,
    parse_int,
    parse_number,
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


def field_label(key: str) -> str:
    f = FIELDS_BY_KEY.get(key)
    return f["label"] if f else key


# --------------------------------------------------------------------------- #
# Lectura de empresas e historial
# --------------------------------------------------------------------------- #
def load_company(cur, company_id: int, lock: bool = False) -> dict | None:
    cur.execute(
        "SELECT * FROM prospect_companies WHERE id = %s" + (" FOR UPDATE" if lock else ""),
        (company_id,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def load_history(cur, company_ids) -> dict:
    """{company_id: {field: [{"new", "at"}]}} para los operadores de historial."""
    ids = list(company_ids)
    if not ids:
        return {}
    cur.execute(
        """
        SELECT company_id, field, new_value, at FROM prospect_company_events
         WHERE company_id = ANY(%s) AND field = ANY(%s)
        """,
        (ids, list(HISTORY_FIELDS)),
    )
    out: dict = {}
    for r in cur.fetchall():
        out.setdefault(r["company_id"], {}).setdefault(r["field"], []).append({"new": r["new_value"], "at": r["at"]})
    return out


def _row_matches(cur, conditions, row: dict, now: datetime, history: dict | None = None) -> bool:
    if not has_conditions(conditions):
        return True
    if history is None and any(
        OPERATORS[r["op"]].get("history") for g in conditions["groups"] for r in g["rules"]
    ):
        history = load_history(cur, [row["id"]]).get(row["id"], {})
    return matches(conditions, row, as_of_of(now), now, history or {})


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


def enroll(cur, wf: dict, company_id: int, source: str, now: datetime, actor: str | None) -> int | None:
    """Inscribe si corresponde. Devuelve el id de la inscripción, o None si no entró."""
    cur.execute(
        """
        SELECT status FROM prospect_wf_enrollments
         WHERE workflow_id = %s AND company_id = %s
        """,
        (wf["id"], company_id),
    )
    statuses = [r["status"] for r in cur.fetchall()]
    if any(s in OPEN_STATUSES for s in statuses):
        return None  # ya está adentro
    if statuses and not wf.get("reenroll", True):
        return None  # reinscripción apagada: una sola vez
    start = (wf.get("steps") or {}).get("start")
    cur.execute(
        """
        INSERT INTO prospect_wf_enrollments
            (workflow_id, company_id, status, current_node, wake_at, source, enrolled_by, enrolled_at)
        VALUES (%s, %s, 'active', %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (wf["id"], company_id, start, now, source, actor, now),
    )
    eid = cur.fetchone()["id"]
    _log(cur, eid, None, "enrolled", _source_text(source, actor), now)
    return eid


def _source_text(source: str, actor: str | None) -> str:
    if source == "manual":
        return f"Inscripta a mano por {actor or 'alguien'}"
    if source == "schedule":
        return "Inscripta por el horario del workflow"
    if source == "event":
        return "Inscripta por un evento"
    if source and source.startswith("workflow:"):
        return f"Inscripta por el workflow #{source.split(':', 1)[1]}"
    return "Inscripta porque cumplió las condiciones"


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


def unenroll_company(cur, workflow_id: int, company_id: int, now: datetime, why: str) -> int:
    cur.execute(
        """
        SELECT id FROM prospect_wf_enrollments
         WHERE workflow_id = %s AND company_id = %s AND status IN ('active', 'waiting')
        """,
        (workflow_id, company_id),
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


def _scope_sql(dummy_only: bool, company_id: int | None, alias: str = "") -> tuple[str, list]:
    p = f"{alias}." if alias else ""
    parts, params = [], []
    if dummy_only:
        parts.append(f"{p}is_dummy")
    if company_id is not None:
        parts.append(f"{p}id = %s")
        params.append(company_id)
    return "".join(" AND " + x for x in parts), params


# --------------------------------------------------------------------------- #
# Disparadores
# --------------------------------------------------------------------------- #
def matching_ids(cur, conditions: dict, now: datetime, dummy_only: bool, company_id: int | None = None) -> list[int]:
    cond_sql, params = compile_conditions(conditions, as_of_of(now), now)
    scope, sp = _scope_sql(dummy_only, company_id)
    cur.execute(f"SELECT id FROM prospect_companies WHERE {cond_sql} {scope} ORDER BY id", params + sp)
    return [r["id"] for r in cur.fetchall()]


def snapshot_matches(cur, wf: dict, now: datetime, dummy_only: bool, matching: list[int]) -> None:
    """Anota como "ya cumplía" a las que cumplen hoy, sin inscribirlas (al activar
    sin "inscribir también las que ya cumplen", como HubSpot)."""
    for cid in matching:
        cur.execute(
            """
            INSERT INTO prospect_wf_match_state (workflow_id, company_id, matching, changed_at)
            VALUES (%s, %s, TRUE, %s)
            ON CONFLICT (workflow_id, company_id) DO UPDATE SET matching = TRUE, changed_at = EXCLUDED.changed_at
            """,
            (wf["id"], cid, now),
        )


def _sync_filter(cur, wf: dict, now: datetime, dummy_only: bool, company_id: int | None, actor) -> int:
    matching = set(matching_ids(cur, wf["trigger"]["conditions"], now, dummy_only, company_id))
    scope = ""
    params = [wf["id"]]
    if company_id is not None:
        scope += " AND s.company_id = %s"
        params.append(company_id)
    if dummy_only:
        scope += " AND c.is_dummy"
    cur.execute(
        f"""
        SELECT s.company_id, s.matching FROM prospect_wf_match_state s
          JOIN prospect_companies c ON c.id = s.company_id
         WHERE s.workflow_id = %s {scope}
        """,
        params,
    )
    prev = {r["company_id"]: r["matching"] for r in cur.fetchall()}
    newly = sorted(c for c in matching if not prev.get(c))
    gone = [c for c, m in prev.items() if m and c not in matching]
    for c in gone:
        cur.execute(
            "UPDATE prospect_wf_match_state SET matching = FALSE, changed_at = %s WHERE workflow_id = %s AND company_id = %s",
            (now, wf["id"], c),
        )
    snapshot_matches(cur, wf, now, dummy_only, newly)
    enrolled = 0
    for c in newly:
        if enroll(cur, wf, c, "trigger", now, actor):
            enrolled += 1
    return enrolled


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
        ids = matching_ids(cur, conds, now, dummy_only)
    else:
        scope, sp = _scope_sql(dummy_only, None)
        cur.execute(f"SELECT id FROM prospect_companies WHERE TRUE {scope} ORDER BY id", sp)
        ids = [r["id"] for r in cur.fetchall()]
    return sum(1 for c in ids if enroll(cur, wf, c, "schedule", now, actor))


def emit_event(cur, company_id: int, kind: str, changes: list[dict], now: datetime | None = None,
               actor: str | None = None, automatic: bool = True) -> int:
    """Disparadores por evento. kind: 'created' | 'updated'. `changes` = [{field, old, new}]."""
    from prospecting.workflows import list_enabled

    now = now or utcnow()
    row = load_company(cur, company_id)
    if row is None:
        return 0
    if _dummy_only(automatic, False) and not row["is_dummy"]:
        return 0
    enrolled = 0
    for wf in list_enabled(cur):
        t = wf["trigger"]
        if t.get("type") != "event":
            continue
        hit = False
        if t.get("event") == "created":
            hit = kind == "created"
        elif t.get("event") == "property_changed" and kind == "updated":
            to = [str(x) for x in (t.get("to_values") or [])]
            for ch in changes:
                if ch["field"] != t.get("field"):
                    continue
                new = ch["new"]
                if not to or (new is not None and str(_plain(new)) in to):
                    hit = True
        if hit and _row_matches(cur, t.get("conditions"), row, now):
            if enroll(cur, wf, company_id, "event", now, actor):
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
def _owner_name(cur, email: str | None) -> str:
    if not email:
        return "sin owner"
    cur.execute("SELECT user_name FROM users WHERE LOWER(TRIM(email_vintti)) = %s LIMIT 1", (email.lower(),))
    r = cur.fetchone()
    return (r["user_name"] if r and r.get("user_name") else email)


def render_tokens(cur, text: str, row: dict) -> str:
    vals = {
        "{empresa}": row.get("name") or "",
        "{dominio}": row.get("domain") or "",
        "{owner}": _owner_name(cur, row.get("prospecting_owner_email")),
        "{status}": row.get("prospecting_status") or "—",
        "{semana}": row.get("week_label") or "—",
        "{not_icp}": row.get("not_icp_reason") or "—",
        "{link}": PAGE_URL,
    }
    for k, v in vals.items():
        text = text.replace(k, str(v))
    return text


def _edit_value(a: dict, row: dict, as_of: date):
    """Valor nuevo de una acción de "Editar registro" (ya tipado)."""
    t, key = a["type"], a["field"]
    ftype = FIELDS_BY_KEY[key]["type"]
    if t == "clear":
        return None
    if t == "set_today":
        return as_of
    if t == "set_date_offset":
        return as_of + timedelta(days=parse_int(a.get("days")) or 0)
    if t == "increment":
        return int(round((parse_number(row.get(key)) or 0) + parse_number(a.get("amount"))))
    if t == "copy":
        v = row.get(a["from_field"])
        if v is None:
            return None
        if ftype in ("text", "longtext", "url"):
            return str(_plain(v))
        return v
    v = a.get("value")  # set
    if ftype == "date":
        return parse_date(v)
    if ftype == "number":
        return int(parse_number(v))
    if ftype == "owner":
        return str(v).strip().lower()
    return str(v).strip() if isinstance(v, str) else v


class Ctx:
    def __init__(self, wf: dict, node_id: str, now: datetime, actor: str | None, dry: bool):
        self.wf, self.node_id, self.now, self.actor, self.dry = wf, node_id, now, actor, dry
        self.as_of = as_of_of(now)

    @property
    def source(self) -> str:
        return f"workflow:{self.wf.get('id') or 'prueba'}"


def describe_action(cur, a: dict) -> str:
    t = a.get("type")
    if ACTIONS.get(t, {}).get("field"):
        f = field_label(a.get("field"))
        if t == "clear":
            return f"Borra {f}"
        if t == "set_today":
            return f"Pone la fecha de hoy en {f}"
        if t == "set_date_offset":
            return f"Pone en {f} hoy {'+' if (parse_int(a.get('days')) or 0) >= 0 else '−'} {abs(parse_int(a.get('days')) or 0)} días"
        if t == "increment":
            n = parse_number(a.get("amount")) or 0
            return f"{'Suma' if n > 0 else 'Resta'} {abs(n):g} a {f}"
        if t == "copy":
            return f"Copia {field_label(a.get('from_field'))} en {f}"
        return f"Define {f} como {a.get('value')}"
    return ACTIONS.get(t, {}).get("label", t)


def run_action(cur, a: dict, row: dict, ctx: Ctx) -> dict:
    """Ejecuta (o, con ctx.dry, sólo describe) una acción. Devuelve
    {"summary", "changes"?, "detail"?}. Con dry=True actualiza `row` en memoria
    para que las ramas siguientes de la prueba lo vean."""
    t = a["type"]
    test = bool(row.get("is_dummy"))

    # ---- Editar registro ------------------------------------------------- #
    if ACTIONS[t].get("field") or t == "rotate_owner":
        if t == "rotate_owner":
            key = "prospecting_owner_email"
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
        else:
            key = a["field"]
            new = _edit_value(a, row, ctx.as_of)
            summary = describe_action(cur, a)
        old = row.get(key)
        if old == new or (old in (None, "") and new in (None, "")):
            return {"summary": summary + " — ya estaba así, sin cambios."}
        changes = {key: {"from": _plain(old), "to": _plain(new)}}
        if ctx.dry:
            row[key] = new
            return {"summary": summary, "changes": changes}
        updated = store.update_company(cur, row["id"], {key: new}, actor=ctx.actor, source=ctx.source)
        row.update({k: v for k, v in updated.items() if not k.startswith("_")})
        emit_event(cur, row["id"], "updated", updated["_changes"], ctx.now, ctx.actor)
        return {"summary": summary, "changes": changes}

    # ---- Comunicación ---------------------------------------------------- #
    if t == "add_note":
        text = render_tokens(cur, a["text"], row)
        if not ctx.dry:
            store.log_event(cur, row["id"], ctx.source, ctx.actor, "__note__", None, text)
        return {"summary": f"Nota: {text}"}

    if t == "create_todo":
        assignee = row.get("prospecting_owner_email") if (a.get("assignee") or "owner") == "owner" else a["assignee"]
        if not assignee:
            return {"summary": "Crear To-Do: la empresa no tiene owner, no se crea."}
        text = render_tokens(cur, a["text"], row)
        due = ctx.as_of + timedelta(days=parse_int(a.get("due_days")) or 0)
        target = TEST_EMAIL if test else assignee
        if test:
            text = f"[TEST] (para {assignee}) {text}"
        summary = f"To-Do para {target} (vence {due.isoformat()}): {text}"
        if ctx.dry:
            return {"summary": summary}
        cur.execute(
            "SELECT user_id FROM users WHERE LOWER(TRIM(email_vintti)) = %s LIMIT 1", (target.lower(),)
        )
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
        to = []
        for x in a["to"]:
            if x == "owner":
                if row.get("prospecting_owner_email"):
                    to.append(row["prospecting_owner_email"])
            else:
                to.append(x.lower())
        to = sorted(set(to))
        if not to:
            return {"summary": "Mail: la empresa no tiene owner y no hay otro destinatario, no se manda."}
        subject = render_tokens(cur, a["subject"], row)
        body = html.escape(render_tokens(cur, a["body"], row)).replace("\n", "<br>")
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
        text = render_tokens(cur, a["text"], row)
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
            return {"summary": f"Webhook a {url}" + (" — simulado (empresa dummy), no se mandó." if test else "")}
        payload = {
            "workflow": {"id": ctx.wf.get("id"), "name": ctx.wf.get("name")},
            "company": {k: _plain(v) for k, v in row.items() if k != "raw_payload"},
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
        if t == "enroll_workflow":
            if ctx.dry:
                return {"summary": f"Inscribe en «{other['name']}»."}
            eid = enroll(cur, other, row["id"], ctx.source, ctx.now, ctx.actor)
            return {"summary": f"Inscripta en «{other['name']}»." if eid else f"Ya estaba en «{other['name']}» (o no se reinscribe)."}
        if ctx.dry:
            return {"summary": f"Saca de «{other['name']}»."}
        n = unenroll_company(cur, other["id"], row["id"], ctx.now, f"Sacada por el workflow #{ctx.wf.get('id')}")
        return {"summary": f"Sacada de «{other['name']}»." if n else f"No estaba en «{other['name']}»."}

    raise RuntimeError(f"Acción desconocida: {t}")


# --------------------------------------------------------------------------- #
# Esperas y ramas
# --------------------------------------------------------------------------- #
def describe_delay(d: dict) -> str:
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
        return f"Espera hasta {field_label(d.get('field'))}{rel}" + (f" a las {d['time']}" if d.get("time") else "")
    if k == "until_weekday":
        names = ", ".join(WEEKDAYS[parse_int(x)] for x in sorted(d.get("days") or []))
        return f"Espera hasta el próximo {names} a las {d.get('time')}"
    if k == "until_time":
        return f"Espera hasta las {d.get('time')}"
    if k == "until_condition":
        return f"Espera hasta que se cumpla la condición (máximo {d.get('max_days')} días)"
    return DELAYS.get(k, {}).get("label", "Espera")


def compute_wake(d: dict, now: datetime, row: dict) -> datetime | None:
    k = d["kind"]
    loc = local(now)
    if k == "duration":
        return now + timedelta(days=parse_int(d.get("days") or 0), hours=parse_int(d.get("hours") or 0),
                               minutes=parse_int(d.get("minutes") or 0))
    if k == "until_date":
        return _at_local(parse_date(d["date"]), d.get("time"))
    if k == "until_property":
        base = parse_date(row.get(d["field"]))
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


def describe_branch(b: dict) -> list[str]:
    """Etiqueta de cada salida: [rama1, rama2, ..., "si no"]."""
    k = b.get("kind")
    labels = []
    for p in b.get("paths") or []:
        if k == "value":
            labels.append(f"{field_label(b.get('field'))} es {' o '.join(map(str, p.get('values') or []))}")
        elif k == "random":
            labels.append(f"{p.get('pct')}%")
        else:
            labels.append(p.get("label") or "Rama")
    if k != "random":
        labels.append("Ninguna de las anteriores")
    return labels


def choose_branch(cur, b: dict, row: dict, now: datetime, history=None) -> tuple:
    """(índice, next) de la rama que toma la empresa. El índice len(paths) = "si no"."""
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
            if row.get(b["field"]) in (p.get("values") or []):
                return i, p.get("next")
        elif _row_matches(cur, p.get("conditions"), row, now, history):
            return i, p.get("next")
    return len(paths), b.get("else_next")


# --------------------------------------------------------------------------- #
# Avance de una inscripción
# --------------------------------------------------------------------------- #
def _set_waiting(cur, enr_id: int, node, wake: datetime, now: datetime, deadline=None) -> None:
    cur.execute(
        """
        UPDATE prospect_wf_enrollments
           SET status = 'waiting', current_node = %s, wake_at = %s, wait_deadline = %s
         WHERE id = %s
        """,
        (node, wake, deadline, enr_id),
    )


def run_enrollment(cur, enr: dict, wf: dict, now: datetime, actor: str | None) -> str:
    """Avanza una inscripción hasta una espera o el final. Devuelve el estado final."""
    nodes = wf["steps"].get("nodes") or {}
    order = number_nodes(wf["steps"])
    settings = wf.get("settings") or {}
    node_id = enr["current_node"]
    deadline = enr.get("wait_deadline")
    eid = enr["id"]
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
                _set_waiting(cur, eid, node_id, allowed, now)
                _log(cur, eid, node_id, "paused",
                     f"Paso {n}: fuera de horario, sigue el {local(allowed).strftime('%d/%m %H:%M')}", now)
                return "waiting"
            row = load_company(cur, enr["company_id"], lock=True)
            if row is None:
                _close(cur, eid, "unenrolled", "La empresa se borró", now)
                return "unenrolled"
            res = run_action(cur, node["action"], row, Ctx(wf, node_id, now, actor, dry=False))
            _log(cur, eid, node_id, "action", f"Paso {n}: {res['summary']}", now, detail=res.get("changes"))
            node_id = node.get("next")
            continue
        if t == "delay":
            d = node["delay"]
            if d["kind"] == "until_condition":
                row = load_company(cur, enr["company_id"])
                if deadline is None:
                    deadline = now + timedelta(days=parse_int(d.get("max_days")) or 1)
                    _log(cur, eid, node_id, "delay", f"Paso {n}: {describe_delay(d)}", now)
                if _row_matches(cur, d.get("conditions"), row, now):
                    _log(cur, eid, node_id, "wake", f"Paso {n}: se cumplió la condición, sigue", now)
                elif now >= deadline:
                    _log(cur, eid, node_id, "wake", f"Paso {n}: se venció la espera sin cumplirse, sigue", now)
                else:
                    _set_waiting(cur, eid, node_id, min(deadline, now + timedelta(hours=1)), now, deadline)
                    return "waiting"
                deadline = None
                cur.execute("UPDATE prospect_wf_enrollments SET wait_deadline = NULL WHERE id = %s", (eid,))
                node_id = node.get("next")
                continue
            row = load_company(cur, enr["company_id"])
            wake = compute_wake(d, now, row or {})
            if wake is None or wake <= now:
                why = "la propiedad está vacía" if wake is None else "la fecha ya pasó"
                _log(cur, eid, node_id, "delay", f"Paso {n}: {describe_delay(d)} — no espera ({why})", now)
                node_id = node.get("next")
                continue
            _set_waiting(cur, eid, node.get("next"), wake, now)
            _log(cur, eid, node_id, "delay",
                 f"Paso {n}: {describe_delay(d)} — sigue el {local(wake).strftime('%d/%m/%Y %H:%M')}", now)
            return "waiting"
        if t == "branch":
            row = load_company(cur, enr["company_id"])
            b = node["branch"]
            idx, nxt = choose_branch(cur, b, row, now)
            label = describe_branch(b)[idx]
            _log(cur, eid, node_id, "branch", f"Paso {n}: va por la rama «{label}»", now)
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
    scope, params = _scope_sql(dummy_only, company_id, alias="c")
    cur.execute(
        f"""
        SELECT e.id, e.workflow_id, e.company_id FROM prospect_wf_enrollments e
          JOIN prospect_companies c ON c.id = e.company_id
         WHERE e.status IN ('active', 'waiting') AND e.workflow_id = ANY(%s) {scope}
        """,
        [list(wfs.keys())] + params,
    )
    rows = cur.fetchall()
    if not rows:
        return 0
    history = load_history(cur, {r["company_id"] for r in rows})
    closed = 0
    for r in rows:
        wf = wfs[r["workflow_id"]]
        goal, unen = wf.get("goal"), wf.get("unenroll")
        by_trigger = (wf.get("settings") or {}).get("unenroll_if_not_matching") and wf["trigger"]["type"] == "filter"
        if not (has_conditions(goal) or has_conditions(unen) or by_trigger):
            continue
        row = load_company(cur, r["company_id"])
        h = history.get(r["company_id"], {})
        if has_conditions(goal) and _row_matches(cur, goal, row, now, h):
            _close(cur, r["id"], "goal_met", "Cumplió la meta", now)
        elif has_conditions(unen) and _row_matches(cur, unen, row, now, h):
            _close(cur, r["id"], "unenrolled", "Cumplió el criterio de desinscripción", now)
        elif by_trigger and not _row_matches(cur, wf["trigger"]["conditions"], row, now, h):
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
        scope, params = _scope_sql(dummy_only, company_id, alias="c")
        # Al instante (una empresa recién editada): las esperas "hasta que se cumpla
        # algo" se revisan ya, sin aguardar a su próxima revisión horaria.
        wait_cond = "OR e.wait_deadline IS NOT NULL" if company_id is not None else ""
        extra, ep = "", []
        if workflow_ids:
            extra = " AND e.workflow_id = ANY(%s)"
            ep = [list(workflow_ids)]
        cur.execute(
            f"""
            SELECT e.* FROM prospect_wf_enrollments e
              JOIN prospect_companies c ON c.id = e.company_id
              JOIN prospect_workflows w ON w.id = e.workflow_id
             WHERE e.status IN ('active', 'waiting')
               AND (e.wake_at IS NULL OR e.wake_at <= %s {wait_cond})
               {'' if include_disabled else 'AND w.enabled'} {scope} {extra}
             ORDER BY e.id
             FOR UPDATE OF e SKIP LOCKED
            """,
            [now] + params + ep,
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


def enroll_now(cur, wf: dict, now: datetime, actor: str | None, dummy_only: bool, company_ids=None) -> dict:
    """«Aplicar ahora» / inscripción manual: inscribe y avanza en el momento, aunque el
    workflow esté apagado (lo pide una persona)."""
    if company_ids is None:
        conds = wf["trigger"].get("conditions")
        if has_conditions(conds):
            ids = matching_ids(cur, conds, now, dummy_only)
        else:
            ids = []
        source = "trigger"
    else:
        ids = [int(c) for c in company_ids]
        source = "manual"
    new = [eid for eid in (enroll(cur, wf, c, source, now, actor) for c in ids) if eid]
    if wf["trigger"].get("type") == "filter" and company_ids is None:
        snapshot_matches(cur, wf, now, dummy_only, ids)
    stats = advance(cur, now, False, workflow_ids=[wf["id"]], actor=actor, include_disabled=True) if new else {}
    return {"enrolled": len(new), "candidates": len(ids), **stats}


# --------------------------------------------------------------------------- #
# Prueba con una empresa (no escribe nada)
# --------------------------------------------------------------------------- #
def simulate(cur, wf: dict, company_id: int, now: datetime | None = None) -> dict:
    now = now or utcnow()
    row = load_company(cur, company_id)
    if row is None:
        raise LookupError("company")
    history = load_history(cur, [company_id]).get(company_id, {})
    t = wf["trigger"]
    tt = t.get("type")
    if tt == "filter":
        enters = matches(t["conditions"], row, as_of_of(now), now, history)
        trigger_note = "Cumple las condiciones de inscripción." if enters else "Hoy NO cumple las condiciones de inscripción: no entraría sola."
    elif tt == "manual":
        enters, trigger_note = True, "Inscripción manual: entra cuando alguien la inscribe."
    elif tt == "event":
        ok = matches(t.get("conditions"), row, as_of_of(now), now, history)
        enters = ok
        trigger_note = ("Entraría cuando ocurra el evento." if ok
                        else "Aunque ocurra el evento, hoy no cumple el filtro extra.")
    else:
        ok = matches(t.get("conditions"), row, as_of_of(now), now, history)
        enters = ok
        trigger_note = "Entraría en el próximo horario." if ok else "Hoy no cumple el filtro del horario."

    path = []
    order = number_nodes(wf["steps"])
    nodes = wf["steps"].get("nodes") or {}
    node_id = wf["steps"].get("start")
    sim_row = dict(row)
    for _ in range(MAX_STEPS_PER_RUN):
        if node_id is None or node_id not in nodes:
            path.append({"kind": "end", "summary": "Fin del workflow"})
            break
        node = nodes[node_id]
        n = order.get(node_id, "?")
        if node["type"] == "action":
            res = run_action(cur, node["action"], sim_row, Ctx(wf, node_id, now, None, dry=True))
            path.append({"node": node_id, "n": n, "kind": "action", "summary": res["summary"], "changes": res.get("changes")})
            node_id = node.get("next")
        elif node["type"] == "delay":
            path.append({"node": node_id, "n": n, "kind": "delay",
                         "summary": describe_delay(node["delay"]) + " (en la prueba se saltea)"})
            node_id = node.get("next")
        else:
            b = node["branch"]
            idx, nxt = choose_branch(cur, b, sim_row, now, history)
            label = describe_branch(b)[idx]
            extra = " (al azar: en la corrida real puede tocar otra)" if b["kind"] == "random" else ""
            path.append({"node": node_id, "n": n, "kind": "branch", "summary": f"Va por la rama «{label}»{extra}"})
            node_id = nxt
    else:
        path.append({"kind": "error", "summary": f"Más de {MAX_STEPS_PER_RUN} pasos: hay un loop sin espera."})
    return {"company": {"id": row["id"], "name": row["name"], "is_dummy": row["is_dummy"]},
            "enters": enters, "trigger_note": trigger_note, "path": path}
