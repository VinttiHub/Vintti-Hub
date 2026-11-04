"""Contactos que llegan de Calendly (vía Zapier) y su asociación a empresas.

Zapier no se consulta: empuja. El Zap "Calendly · Invitee Created" → "Webhooks by
Zapier · POST" pega a `POST /prospecting/zapier/calendly` en el momento en que
alguien agenda. Cada llegada queda registrada en `prospect_inbound_contacts`
(autocreada) y se resuelve así:

  1. Ya hay un contacto con ese email → se actualiza. Meeting Date & Time se pisa
     (es la reunión nueva); todo lo demás, UTMs incluidas, sólo se rellena si está
     vacío: el primer canal que lo trajo no se pierde (decisión de la owner,
     2026-10-28).
  2. El dominio (del website que mande el form, si no del email) coincide con UNA
     sola empresa de Prospecting → se crea el contacto ahí.
  3. Si no (gmail/hotmail, ninguna empresa o más de una) → contacto SIN empresa
     (desde el 2026-11-04, como en HubSpot). Cuando llega después una empresa con ese
     dominio se le asocia sola (`store.attach_contacts_for_company`); si no, a mano desde
     su ficha.

Hasta el 2026-11-04 el caso 3 quedaba `pending` en una bandeja «Unassigned» porque un
contacto exigía empresa. Esa bandeja ya no recibe nada: lo que quedó pendiente lo pasa a
contactos `scripts/migrate_inbound_to_contacts.py`. La tabla sigue como registro de cada
llegada (status `linked`).
"""
from __future__ import annotations

import re

from psycopg2.extras import Json

from prospecting import store
from prospecting.contact_fields import CONTACT_FIELDS_BY_KEY

# Dominios de mail personales: nunca identifican a una empresa.
FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.es", "outlook.com", "outlook.es",
    "live.com", "msn.com", "yahoo.com", "yahoo.com.ar", "yahoo.es", "icloud.com", "me.com",
    "mac.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "mail.com", "zoho.com",
    "yandex.com", "comcast.net", "att.net", "verizon.net", "sbcglobal.net",
}

# Clave normalizada (store._norm_key) de lo que manda Zapier -> propiedad del contacto.
# Acepta los nombres con los que Zapier muestra los campos de Calendly y también la
# clave exacta de contact_fields.py, así cualquier pregunta del form se puede mapear
# directo a su propiedad (role_to_hire, hiring_situation…).
_ALIASES = {
    "email": ["email", "invitee_email"],
    "first_name": ["first_name", "invitee_first_name"],
    "last_name": ["last_name", "invitee_last_name"],
    "phone_number": ["phone_number", "phone", "text_reminder_number", "invitee_text_reminder_number"],
    "meeting_datetime": ["meeting_datetime", "event_start_time", "start_time", "scheduled_event_start_time",
                         "event_start_time_pretty"],
    "company_name": ["company_name", "company"],
    **{f"utm_{k}": [f"utm_{k}", f"tracking_utm_{k}", f"invitee_tracking_utm_{k}"]
       for k in ("source", "medium", "campaign", "term", "content")},
}
_ALIAS_TO_FIELD = {a: f for f, aliases in _ALIASES.items() for a in aliases}
_FULL_NAME = {"name", "invitee_name", "full_name"}
_WEBSITE = {"website", "company_website", "domain", "company_domain"}
_EVENT_NAME = {"event_name", "event_type_name", "event_type"}
_QA = {"questions_and_answers", "questions", "answers"}

# Formatter "Extract Email Address" de Zapier devuelve ", ana@acme.io, ," (una lista
# con huecos aplanada): se toma el primer mail que aparezca.
_EMAIL_IN_TEXT = re.compile(r"[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[^@\s,;<>\"']+")


def _first_email(v):
    if isinstance(v, (list, tuple)):
        v = " ".join(str(x) for x in v if x not in (None, ""))
    m = _EMAIL_IN_TEXT.search(str(v or ""))
    return m.group(0) if m else v


# Lo único que una re-agenda pisa; el resto sólo se rellena si está vacío.
OVERWRITE_FIELDS = {"meeting_datetime"}

# El Zap del formulario (Routing Form Submission → Delay → POST) manda este Origin detail
# para quien llenó el form y no agendó. Esa llegada nunca trae una reunión: la fecha que
# viene es la del formulario, y como meeting_datetime se pisa siempre, le borraría la
# reunión real a quien sí agendó. Y si el mail ya tiene reunión, no abandonó.
ABANDONED_ORIGIN_DETAIL = "Abandoned Calendar"


def _settle_abandoned(data: dict, has_meeting: bool) -> bool | None:
    """None si no es una llegada del formulario; si no, si quedó marcada."""
    if data.get("origin_detail") != ABANDONED_ORIGIN_DETAIL:
        return None
    if has_meeting:
        data.pop("origin_detail")
    return not has_meeting


def ensure_schema(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_inbound_contacts (
            id                BIGSERIAL PRIMARY KEY,
            source            TEXT NOT NULL DEFAULT 'calendly',
            email             TEXT,
            first_name        TEXT,
            last_name         TEXT,
            domain            TEXT,
            meeting_datetime  TIMESTAMPTZ,
            event_name        TEXT,
            contact_data      JSONB NOT NULL DEFAULT '{}'::jsonb,
            extra             JSONB NOT NULL DEFAULT '{}'::jsonb,
            raw_payload       JSONB,
            status            TEXT NOT NULL DEFAULT 'pending',
            reason            TEXT,
            contact_id        BIGINT,
            company_id        BIGINT,
            is_dummy          BOOLEAN NOT NULL DEFAULT FALSE,
            received_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at       TIMESTAMPTZ,
            resolved_by       TEXT
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_prospect_inbound_pending ON prospect_inbound_contacts (domain) "
        "WHERE status = 'pending'"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS ix_prospect_inbound_email ON prospect_inbound_contacts (LOWER(email))")
    # Contactos de HubSpot sin empresa (prospecting/hubspot_contacts.py, 2026-11-04): la
    # misma bandeja, `source = 'hubspot'`. El id evita duplicarlos al re-correr.
    cur.execute("ALTER TABLE prospect_inbound_contacts ADD COLUMN IF NOT EXISTS hubspot_contact_id TEXT")
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_prospect_inbound_hubspot ON prospect_inbound_contacts (hubspot_contact_id) "
        "WHERE hubspot_contact_id IS NOT NULL"
    )


# --------------------------------------------------------------------------- #
# Payload de Zapier
# --------------------------------------------------------------------------- #
def _qa_text(v) -> str | None:
    """Preguntas del form de Calendly: Zapier las manda como texto o como lista."""
    if isinstance(v, list):
        parts = []
        for x in v:
            if isinstance(x, dict):
                q, a = x.get("question"), x.get("answer")
                if a not in (None, ""):
                    parts.append(f"{q}: {a}" if q else str(a))
            elif x not in (None, ""):
                parts.append(str(x))
        return "\n".join(parts) or None
    return store._clean_text(v)


def map_payload(payload: dict) -> tuple[dict, dict]:
    """(propiedades del contacto ya validadas, extra). Un valor inválido no frena la
    llegada: se descarta y queda en extra["warnings"]."""
    data: dict = {}
    extra: dict = {"warnings": []}
    full_name = None
    for k, v in (payload or {}).items():
        nk = store._norm_key(k)
        if nk in _FULL_NAME:
            full_name = store._clean_text(v)
            continue
        if nk in _WEBSITE:
            extra["website"] = store._clean_text(v)
            continue
        if nk in _EVENT_NAME:
            extra["event_name"] = store._clean_text(v)
            continue
        if nk in _QA:
            extra["questions_and_answers"] = _qa_text(v)
            continue
        key = _ALIAS_TO_FIELD.get(nk) or (nk if nk in CONTACT_FIELDS_BY_KEY else None)
        if not key or key in data or key == "owner_email":
            continue
        if CONTACT_FIELDS_BY_KEY[key]["type"] == "email":
            v = _first_email(v)
        try:
            val = store.clean_contact_value(CONTACT_FIELDS_BY_KEY[key], v)
        except ValueError as exc:
            extra["warnings"].append(str(exc))
            continue
        if val is not None:
            data[key] = val
    if full_name and not (data.get("first_name") or data.get("last_name")):
        first, _, rest = full_name.partition(" ")
        data["first_name"] = first
        if rest.strip():
            data["last_name"] = rest.strip()
    if not extra["warnings"]:
        extra.pop("warnings")
    return data, {k: v for k, v in extra.items() if v not in (None, "")}


def company_domain(email: str | None, website: str | None) -> str | None:
    """Dominio que identifica a la empresa: el website del form; si no, el del mail
    (nunca uno personal)."""
    d = store.normalize_domain(website)
    if d:
        return d
    if email and "@" in email:
        d = email.rsplit("@", 1)[1].strip().lower()
        if d and d not in FREE_EMAIL_DOMAINS:
            return d
    return None


# --------------------------------------------------------------------------- #
# Escrituras
# --------------------------------------------------------------------------- #
def _find_contact(cur, email: str):
    cur.execute(
        "SELECT id, company_id, is_dummy FROM prospect_contacts WHERE LOWER(email) = LOWER(%s) ORDER BY id LIMIT 1",
        (email,),
    )
    return cur.fetchone()


def _merge_patch(existing: dict, data: dict) -> dict:
    return {k: v for k, v in data.items()
            if k in OVERWRITE_FIELDS or existing.get(k) in (None, "", [])}


def _record(cur, data: dict, extra: dict, payload: dict, domain: str | None, is_dummy: bool,
            status: str, reason: str | None = None, contact_id=None, company_id=None) -> int:
    cur.execute(
        """
        INSERT INTO prospect_inbound_contacts
            (email, first_name, last_name, domain, meeting_datetime, event_name, contact_data, extra,
             raw_payload, status, reason, contact_id, company_id, is_dummy, resolved_at, resolved_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                CASE WHEN %s = 'pending' THEN NULL ELSE NOW() END,
                CASE WHEN %s = 'pending' THEN NULL ELSE 'calendly' END)
        RETURNING id
        """,
        (data.get("email"), data.get("first_name"), data.get("last_name"), domain, data.get("meeting_datetime"),
         extra.get("event_name"), Json(data), Json(extra), Json(payload), status, reason, contact_id,
         company_id, is_dummy, status, status),
    )
    return cur.fetchone()["id"]


def ingest(cur, payload: dict, is_dummy: bool = False) -> dict:
    """Una llegada de Calendly. Devuelve qué pasó y, si se creó o actualizó un
    contacto, `changes` para que la ruta corra los workflows al instante."""
    data, extra = map_payload(payload)
    email = data.get("email")
    if not email:
        raise ValueError("Falta el email del invitado (email / invitee_email).")
    domain = company_domain(email, extra.get("website"))
    if data.get("origin_detail") == ABANDONED_ORIGIN_DETAIL:
        data.pop("meeting_datetime", None)
    abandoned = None

    # 1. Ya existe: re-agenda.
    found = _find_contact(cur, email)
    if found is not None:
        if bool(found["is_dummy"]) != bool(is_dummy):
            raise ValueError(
                "Ese email ya es un contacto de prueba (dummy)." if found["is_dummy"]
                else "Ese email ya es un contacto real: no se puede mandar como prueba (is_dummy)."
            )
        current = store.get_contact(cur, found["id"]) or {}
        abandoned = _settle_abandoned(data, bool(current.get("meeting_datetime")))
        row = store.update_contact(cur, found["id"], _merge_patch(current, data), None, source="calendly")
        changes = row.pop("_changes")
        inbound_id = _record(cur, data, extra, payload, domain, is_dummy, "linked", "existing_contact",
                             found["id"], found["company_id"])
        return {"action": "updated", "inbound_id": inbound_id, "contact_id": found["id"],
                "company_id": found["company_id"], "changes": changes, **_warn(extra), **_abandoned(abandoned)}

    # Ya estaba esperando en la bandeja: se actualiza esa fila en vez de sumar otra.
    cur.execute(
        """
        SELECT * FROM prospect_inbound_contacts
         WHERE status = 'pending' AND LOWER(email) = LOWER(%s) AND is_dummy = %s
         ORDER BY id LIMIT 1 FOR UPDATE
        """,
        (email, bool(is_dummy)),
    )
    waiting = cur.fetchone()
    abandoned = _settle_abandoned(data, bool(waiting and waiting["meeting_datetime"]))
    if waiting is not None:
        before = waiting["contact_data"] or {}
        data = {**before, **_merge_patch(before, data)}
        extra = {**(waiting["extra"] or {}), **extra}
        domain = domain or waiting["domain"]

    # 2. Dominio de una sola empresa.
    company_id, reason = None, None
    if not domain:
        reason = "free_email"
    else:
        cur.execute(
            "SELECT id FROM prospect_companies WHERE domain = %s AND is_dummy = %s ORDER BY id LIMIT 2",
            (domain, bool(is_dummy)),
        )
        ids = [r["id"] for r in cur.fetchall()]
        if len(ids) == 1:
            company_id = ids[0]
        else:
            reason = "multiple_companies" if ids else "no_company"

    # 3. Sin empresa: desde el 2026-11-04 es un contacto SIN empresa (como en HubSpot), no
    # una fila pendiente de la bandeja. Se le asocia sola cuando llega su empresa.
    row = store.create_contact(cur, company_id, data, None, source="calendly", is_dummy=is_dummy)
    changes = row.pop("_changes")
    if waiting is not None:
        _resolve(cur, waiting["id"], row["id"], company_id, "calendly")
        inbound_id = waiting["id"]
    else:
        inbound_id = _record(cur, data, extra, payload, domain, is_dummy, "linked",
                             "domain_match" if company_id is not None else (reason or "no_company"),
                             row["id"], company_id)
    return {"action": "created", "inbound_id": inbound_id, "contact_id": row["id"],
            "company_id": company_id, "changes": changes, **_warn(extra), **_abandoned(abandoned)}


def _warn(extra: dict) -> dict:
    return {"warnings": extra["warnings"]} if extra.get("warnings") else {}


def _abandoned(flag: bool | None) -> dict:
    return {} if flag is None else {"abandoned": flag}


def _resolve(cur, inbound_id: int, contact_id, company_id, actor: str | None, status: str = "linked") -> None:
    cur.execute(
        """
        UPDATE prospect_inbound_contacts
           SET status = %s, contact_id = %s, company_id = %s, resolved_at = NOW(), resolved_by = %s
         WHERE id = %s
        """,
        (status, contact_id, company_id, actor, inbound_id),
    )


def link(cur, inbound_id: int, company_id: int, actor: str) -> dict:
    """Asociación a mano desde la bandeja. Si mientras tanto alguien ya cargó un
    contacto con ese email, se completa ése en vez de duplicarlo."""
    cur.execute("SELECT * FROM prospect_inbound_contacts WHERE id = %s FOR UPDATE", (inbound_id,))
    row = cur.fetchone()
    if row is None:
        raise LookupError("inbound")
    if row["status"] != "pending":
        raise ValueError("Ese contacto ya se resolvió.")
    cur.execute("SELECT id, is_dummy FROM prospect_companies WHERE id = %s", (company_id,))
    comp = cur.fetchone()
    if comp is None:
        raise LookupError("company")
    if bool(comp["is_dummy"]) != bool(row["is_dummy"]):
        raise ValueError("Un contacto de prueba sólo se asocia a una empresa de prueba (y al revés).")
    data = row["contact_data"] or {}
    source = row.get("source") or "calendly"
    found = _find_contact(cur, row["email"]) if row["email"] else None
    if found is not None:
        current = store.get_contact(cur, found["id"]) or {}
        saved = store.update_contact(cur, found["id"], _merge_patch(current, data), actor, source=source)
        if found["company_id"] is None:
            store.set_contact_company(cur, found["id"], company_id, actor, source=source)
        result = {"action": "updated", "contact_id": found["id"], "company_id": found["company_id"] or company_id}
    else:
        saved = store.create_contact(cur, company_id, data, actor, source=source)
        result = {"action": "created", "contact_id": saved["id"], "company_id": company_id}
    result["changes"] = saved.pop("_changes")
    if row.get("hubspot_contact_id"):
        # Vino de HubSpot: el contacto queda atado a su id y con la foto que usa el sync.
        cur.execute(
            """
            UPDATE prospect_contacts
               SET hubspot_contact_id = COALESCE(hubspot_contact_id, %s),
                   hubspot_seen = COALESCE(hubspot_seen, %s), raw_payload = COALESCE(raw_payload, %s)
             WHERE id = %s
            """,
            (row["hubspot_contact_id"], Json((row.get("extra") or {}).get("hubspot_seen") or {}),
             Json(row.get("raw_payload")) if row.get("raw_payload") is not None else None, result["contact_id"]),
        )
    _resolve(cur, inbound_id, result["contact_id"], result["company_id"], actor)
    return result


def discard(cur, inbound_id: int, actor: str) -> bool:
    cur.execute(
        """
        UPDATE prospect_inbound_contacts SET status = 'discarded', resolved_at = NOW(), resolved_by = %s
         WHERE id = %s AND status = 'pending'
        """,
        (actor, inbound_id),
    )
    return cur.rowcount > 0


def attach_pending_for_company(cur, company_id: int) -> list[dict]:
    """Clay acaba de cargar (o completar) una empresa: los pendientes de su dominio
    se asocian solos. Sólo si el dominio es de esa única empresa."""
    cur.execute("SELECT domain, is_dummy FROM prospect_companies WHERE id = %s", (company_id,))
    comp = cur.fetchone()
    if comp is None or not comp["domain"]:
        return []
    cur.execute(
        "SELECT COUNT(*) AS n FROM prospect_companies WHERE domain = %s AND is_dummy = %s",
        (comp["domain"], comp["is_dummy"]),
    )
    if cur.fetchone()["n"] != 1:
        return []
    cur.execute(
        "SELECT id FROM prospect_inbound_contacts WHERE status = 'pending' AND domain = %s AND is_dummy = %s",
        (comp["domain"], comp["is_dummy"]),
    )
    out = []
    for r in cur.fetchall():
        try:
            cur.execute("SAVEPOINT inbound_attach")
            out.append(link(cur, r["id"], company_id, "calendly"))
            cur.execute("RELEASE SAVEPOINT inbound_attach")
        except ValueError:
            cur.execute("ROLLBACK TO SAVEPOINT inbound_attach")
    return out


# --------------------------------------------------------------------------- #
# Lectura
# --------------------------------------------------------------------------- #
def list_inbound(cur, status: str = "pending", dummy: str = "exclude", limit: int = 200,
                 source: str | None = None, q: str | None = None) -> dict:
    where, params = ["status = %s"], [status]
    if source in ("calendly", "hubspot"):
        where.append("source = %s")
        params.append(source)
    if q and q.strip():
        like = "%" + q.strip() + "%"
        where.append("(email ILIKE %s OR first_name ILIKE %s OR last_name ILIKE %s OR domain ILIKE %s "
                     "OR contact_data->>'company_name' ILIKE %s)")
        params += [like] * 5
    if dummy == "only":
        where.append("is_dummy")
    elif dummy != "include":
        where.append("NOT is_dummy")
    cur.execute(
        f"""
        SELECT id, source, email, first_name, last_name, domain, meeting_datetime, event_name,
               contact_data, extra, status, reason, contact_id, company_id, is_dummy, received_at,
               resolved_at, resolved_by
          FROM prospect_inbound_contacts WHERE {' AND '.join(where)}
         ORDER BY received_at DESC, id DESC LIMIT %s
        """,
        params + [limit],
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.execute(
        "SELECT COUNT(*) AS n FROM prospect_inbound_contacts WHERE " + " AND ".join(where), params
    )
    return {"total": cur.fetchone()["n"], "rows": rows}
