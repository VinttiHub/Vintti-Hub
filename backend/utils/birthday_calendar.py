"""Cumpleaños del equipo → calendario "Birthdays/ Team Personal Stuff".

Hasta 2026-09 los eventos los creaba Jazmín a mano ("Cumple Agos <3", anual,
invitando a team@vintti.com) y un cumple se pasó porque esa persona no tenía la
fecha cargada en su perfil. Ahora:

- Al guardar Date of Birth en docs/profile.html, `update_user` dispara
  `sync_birthday_event_async()` y el hub crea (o mueve) el evento anual.
- `birthday_overview()` alimenta el panel "Team birthdays" de profile.html y el
  mail semanal a Jazmín: quién no tiene fecha y qué cumple de los próximos 30
  días no tiene evento.

Decisiones de la owner (2026-09-29):

- Los eventos salen con el Google de Jazmín (el OAuth por usuario que ya existe,
  `google_calendar_tokens`), no con una cuenta de servicio: es la dueña del
  calendario y así el organizador sigue siendo ella.
- Se RESPETAN los eventos manuales. Antes de crear se busca un evento de
  cumpleaños en ese mismo día del año; si el título tiene un prefijo del nombre
  ("Agos" ⊂ "Agostina") se ADOPTA sin tocarlo. Si hay uno ese día pero el nombre
  no coincide (apodo raro, dos cumples el mismo día) NO se crea nada: queda "a
  revisar" en el panel. Duplicar un cumple es peor que pedir un click.
- Se invita a team@vintti.com, como el manual. Título "Cumple <nombre> :)" para
  todos (el hub no guarda género y adivinarlo por el nombre falla).

Nada de acá levanta hacia el guardado del perfil: una llamada a Google no puede
romper ni demorar el PATCH.
"""
from __future__ import annotations

import html
import logging
import re
import threading
import unicodedata
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from psycopg2.extras import RealDictCursor

from db import get_connection
from utils.google_calendar import build_calendar_service, get_google_oauth_config
from utils.hubspot_waiting_alert import today_ar
from utils.transactional_email import post_transactional_email

# Hardcodeado a propósito (mismo criterio que RECIPIENTS del auditor).
CALENDAR_OWNER_EMAIL = "jazmin@vintti.com"
CALENDAR_NAME = "Birthdays/ Team Personal Stuff"
INVITE_EMAIL = "team@vintti.com"
# Quién ve el panel y puede sincronizar / correr el backfill. Tiene que quedar
# igual a BIRTHDAY_PANEL_EMAILS de docs/assets/js/profile.js.
PANEL_EMAILS = {"jazmin@vintti.com", "pgonzales@vintti.com"}
RECIPIENTS = ["jazmin@vintti.com"]
# Modo prueba: con un email acá, el mail semanal va sólo a esa dirección con
# [TEST] en el asunto. None = producción.
TEST_ONLY_RECIPIENT: Optional[str] = None
UPCOMING_DAYS = 30
PROFILE_URL = "https://vinttihub.vintti.com/profile.html"

# Qué eventos del calendario cuentan como "un cumpleaños" al buscar manuales. El
# calendario es "Team Personal Stuff": puede tener otras cosas el mismo día.
_BIRTHDAY_RE = re.compile(r"cumple|birthday|b-?day|🎂|🎉", re.IGNORECASE)
_STOPWORDS = {"cumple", "cumpleanos", "cumpleaños", "birthday", "bday", "de", "del", "la", "el", "happy", "feliz"}

_schema_ready = False
_calendar_id_cache: Optional[str] = None


class NotConnected(Exception):
    """No se puede escribir en el calendario. `kind` le dice al panel qué ofrecer:

    - server_config: faltan las env GOOGLE_OAUTH_* en ESTE backend (pasa en local).
      Reconectar no arregla nada, así que el panel no ofrece el botón.
    - no_token / token_invalid: Jazmín tiene que (re)conectar su Google.
    - no_calendar: conectó, pero no se encuentra el calendario por nombre.
    """

    def __init__(self, message: str, kind: str):
        super().__init__(message)
        self.kind = kind


# ---------------------------------------------------------------- esquema ----

def ensure_birthday_schema(cur) -> None:
    global _schema_ready
    if _schema_ready:
        return
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS birthday_calendar_events (
            user_id BIGINT PRIMARY KEY,
            calendar_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            birth_md TEXT NOT NULL,          -- 'MM-DD' con el que se creó/adoptó
            source TEXT NOT NULL,            -- 'hub' | 'adopted'
            summary TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS birthday_report_log (
            week_start DATE PRIMARY KEY,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    _schema_ready = True


# ---------------------------------------------------------------- helpers ----

def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def _tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z]+", _norm(text)) if t not in _STOPWORDS]


def _as_date(value) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _md(d: date) -> str:
    return f"{d.month:02d}-{d.day:02d}"


def _first_name(user: Dict[str, Any]) -> str:
    nick = (user.get("nickname") or "").strip()
    if nick:
        return nick
    parts = (user.get("user_name") or "").split()
    return parts[0] if parts else "?"


def _given_names(user: Dict[str, Any]) -> set:
    """Nickname y primer nombre real, normalizados."""
    parts = (user.get("user_name") or "").split()
    return {k for k in (_norm(_first_name(user)).strip(), _norm(parts[0]).strip() if parts else "") if k}


def _display_name(user: Dict[str, Any], repeated: set) -> str:
    """Nombre del título. Si otra persona activa se llama igual —por nickname o por
    primer nombre real—, va con apellido: "Valentina Cadirola" aunque las otras
    Valentinas usen "Vale" y "Valen" (pedido de la owner, 2026-09-29).
    """
    first = _first_name(user)
    if not (_given_names(user) & repeated):
        return first
    parts = (user.get("user_name") or "").split()
    return f"{first} {parts[-1]}" if len(parts) > 1 else first


def _repeated_first_names(users: List[Dict[str, Any]]) -> set:
    seen, repeated = set(), set()
    for u in users:
        for key in _given_names(u):
            (repeated if key in seen else seen).add(key)
    return repeated


def _name_matches(summary: str, user: Dict[str, Any]) -> bool:
    """¿El título del evento nombra a esta persona?

    Prefijo de ≥3 letras en cualquier dirección: "Agos" ⊂ "Agostina", y también
    un título con el nombre completo contra un nickname corto.
    """
    ev = [t for t in _tokens(summary) if len(t) >= 3]
    names = [t for t in _tokens(f"{user.get('user_name') or ''} {user.get('nickname') or ''}") if len(t) >= 3]
    return any(e.startswith(n) or n.startswith(e) for e in ev for n in names)


def _next_occurrence(birth: date, today: date) -> date:
    for year in (today.year, today.year + 1):
        try:
            d = date(year, birth.month, birth.day)
        except ValueError:  # 29-feb en año no bisiesto
            d = date(year, 2, 28)
        if d >= today:
            return d
    return date(today.year + 1, birth.month, min(birth.day, 28))


def _event_body(user: Dict[str, Any], birth: date, today: date, repeated: set = frozenset()) -> Dict[str, Any]:
    """Evento de día completo, anual, que no bloquea la agenda."""
    if birth.month == 2 and birth.day == 29:
        start = date(today.year, 2, 28 if today.year % 4 else 29)
        rrule = "RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1"
    else:
        start = date(today.year, birth.month, birth.day)
        rrule = "RRULE:FREQ=YEARLY"
    return {
        "summary": f"Cumple {_display_name(user, repeated)} :)",
        "start": {"date": start.isoformat()},
        "end": {"date": (start + timedelta(days=1)).isoformat()},
        "recurrence": [rrule],
        "transparency": "transparent",
        "attendees": [{"email": INVITE_EMAIL}],
        "reminders": {"useDefault": False, "overrides": []},
    }


# ------------------------------------------------------------------ Google ----

def _owner_tokens(cur) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT t.user_id, t.access_token, t.refresh_token
          FROM google_calendar_tokens t
          JOIN users u ON u.user_id = t.user_id
         WHERE LOWER(TRIM(u.email_vintti)) = %s
         LIMIT 1
        """,
        (CALENDAR_OWNER_EMAIL,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def _service_and_calendar(cur):
    """(service, calendar_id) con el token de Jazmín. Levanta NotConnected."""
    global _calendar_id_cache
    try:
        get_google_oauth_config()
    except RuntimeError as exc:
        raise NotConnected(
            "This backend is missing the Google OAuth settings "
            "(GOOGLE_OAUTH_CLIENT_ID / _SECRET / _REDIRECT_URI). "
            "Production has them; locally they must be added to backend/.env.",
            "server_config",
        ) from exc
    tokens = _owner_tokens(cur)
    if not tokens or not tokens.get("refresh_token"):
        raise NotConnected(f"{CALENDAR_OWNER_EMAIL} has not connected Google Calendar", "no_token")
    try:
        _, service = build_calendar_service(tokens)
    except Exception as exc:  # refresh_token revocado, etc.
        raise NotConnected(f"Google token for {CALENDAR_OWNER_EMAIL} is not valid: {exc}", "token_invalid") from exc

    if _calendar_id_cache:
        return service, _calendar_id_cache
    wanted = _norm(CALENDAR_NAME).strip()
    page = None
    while True:
        resp = service.calendarList().list(pageToken=page, maxResults=250).execute()
        for cal in resp.get("items", []):
            if _norm(cal.get("summaryOverride") or cal.get("summary") or "").strip() == wanted:
                _calendar_id_cache = cal["id"]
                return service, _calendar_id_cache
        page = resp.get("nextPageToken")
        if not page:
            break
    raise NotConnected(f'Calendar "{CALENDAR_NAME}" not found in {CALENDAR_OWNER_EMAIL}\'s calendar list', "no_calendar")


def _birthday_events(service, calendar_id: str) -> List[Dict[str, Any]]:
    """Eventos de cumpleaños del calendario, uno por serie.

    Con singleEvents=False Google devuelve la serie Y sus excepciones (una
    ocurrencia modificada, p. ej. cuando alguien responde a un solo año) como
    items aparte, con `recurringEventId`. Contarlas hacía que cada cumple manual
    pareciera duplicado ("Cumple Agos <3, Cumple Agos <3") y cayera en review.
    """
    # Dos series con el mismo título el mismo día (duplicado real en el calendario)
    # cuentan como UN evento; `ids` guarda todas para reconocer cuál se adoptó.
    out, by_key, page = [], {}, None
    while True:
        resp = service.events().list(
            calendarId=calendar_id, singleEvents=False, showDeleted=False,
            maxResults=2500, pageToken=page,
        ).execute()
        for ev in resp.get("items", []):
            if ev.get("status") == "cancelled" or ev.get("recurringEventId"):
                continue
            start = ev.get("start") or {}
            d = _as_date(start.get("date") or (start.get("dateTime") or "")[:10])
            summary = ev.get("summary") or ""
            if not (d and _BIRTHDAY_RE.search(summary)):
                continue
            key = (" ".join(_tokens(summary)), _md(d))
            if key in by_key:
                by_key[key]["ids"].add(ev["id"])
                continue
            by_key[key] = {"id": ev["id"], "ids": {ev["id"]}, "summary": summary, "md": _md(d)}
            out.append(by_key[key])
        page = resp.get("nextPageToken")
        if not page:
            return out


def _event_alive(service, calendar_id: str, event_id: str) -> bool:
    try:
        ev = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        return ev.get("status") != "cancelled"
    except Exception as exc:
        if getattr(getattr(exc, "resp", None), "status", None) in (404, 410):
            return False
        raise


# ------------------------------------------------------------- decisiones ----

def _active_users(cur, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    cur.execute(
        f"""
        SELECT u.user_id, u.user_name, u.nickname, LOWER(TRIM(u.email_vintti)) AS email,
               u.fecha_nacimiento
          FROM users u
          LEFT JOIN admin_user_access aua ON aua.user_id = u.user_id
         WHERE COALESCE(aua.is_active, TRUE) = TRUE
           {"AND u.user_id = %s" if user_id else ""}
         ORDER BY u.user_name
        """,
        (user_id,) if user_id else None,
    )
    return [dict(r) for r in cur.fetchall()]


def _mapped(cur) -> Dict[int, Dict[str, Any]]:
    cur.execute("SELECT * FROM birthday_calendar_events")
    return {int(r["user_id"]): dict(r) for r in cur.fetchall()}


def _all_birthdays(cur) -> List[Dict[str, Any]]:
    """Todas las personas de users con fecha (activas o no), con su día del año.

    Sirve para saber de quién es un evento: "Cumple Vale" del 18-ago es de otra
    Valentina, y "Cumple Mia" del 7-mar es de Mia aunque Benjamin cumpla ese día.
    """
    cur.execute("SELECT user_id, user_name, nickname, fecha_nacimiento FROM users WHERE fecha_nacimiento IS NOT NULL")
    out = []
    for r in cur.fetchall():
        d = _as_date(r["fecha_nacimiento"])
        if d:
            out.append({"user_id": r["user_id"], "user_name": r["user_name"], "nickname": r["nickname"], "md": _md(d)})
    return out


def _belongs_to_other(event, user, people) -> bool:
    return any(p["user_id"] != user["user_id"] and p["md"] == event["md"] and _name_matches(event["summary"], p)
               for p in people)


def _classify(user, birth: date, row, events, taken_ids, people=()) -> Dict[str, Any]:
    """Qué habría que hacer con esta persona, sin escribir nada.

    action: ok | move | adopt | create | review
    """
    md = _md(birth)
    if row:
        if row["birth_md"] == md:
            return {"action": "ok", "event_id": row["event_id"], "source": row["source"]}
        if row["source"] == "hub":
            return {"action": "move", "event_id": row["event_id"]}
        # Un evento manual adoptado es de Jazmín: no se le cambia la fecha solo.
        return {"action": "review", "reason": "adopted_event_other_date", "event_id": row["event_id"]}
    same_day = [e for e in events if e["md"] == md and not (e["ids"] & taken_ids)]
    named = [e for e in same_day if _name_matches(e["summary"], user)]
    # Un evento de ese día que nombra a OTRA persona del hub que cumple ese mismo
    # día es suyo, no una duda: no frena la creación.
    same_day = [e for e in same_day if e in named or not _belongs_to_other(e, user, people)]
    if named:
        return {"action": "adopt", "event_id": named[0]["id"], "summary": named[0]["summary"]}
    if same_day:
        return {"action": "review", "reason": "same_day_event_other_name",
                "summaries": [e["summary"] for e in same_day]}
    # ¿Hay un evento con su nombre en OTRO día que no es el cumple de nadie del
    # hub? Probablemente la fecha del perfil o la del evento está mal: no crear un
    # segundo. Los días en que cumple otra persona se descartan (nombres repetidos).
    known_mds = {p["md"] for p in people if p["user_id"] != user["user_id"]}
    elsewhere = [e for e in events if not (e["ids"] & taken_ids) and e["md"] not in known_mds
                 and _name_matches(e["summary"], user)]
    if elsewhere:
        return {"action": "review", "reason": "named_event_other_day",
                "summaries": [f'{e["summary"]} ({e["md"]})' for e in elsewhere]}
    return {"action": "create"}


def _apply(cur, service, calendar_id, user, birth: date, plan, repeated: set = frozenset()) -> Dict[str, Any]:
    today = today_ar()
    uid = user["user_id"]
    if plan["action"] == "create":
        body = _event_body(user, birth, today, repeated)
        ev = service.events().insert(calendarId=calendar_id, body=body, sendUpdates="all").execute()
        cur.execute(
            """
            INSERT INTO birthday_calendar_events (user_id, calendar_id, event_id, birth_md, source, summary)
            VALUES (%s, %s, %s, %s, 'hub', %s)
            ON CONFLICT (user_id) DO UPDATE SET calendar_id = EXCLUDED.calendar_id,
                event_id = EXCLUDED.event_id, birth_md = EXCLUDED.birth_md,
                source = 'hub', summary = EXCLUDED.summary, updated_at = now()
            """,
            (uid, calendar_id, ev["id"], _md(birth), body["summary"]),
        )
        return {**plan, "done": True, "event_id": ev["id"]}
    if plan["action"] == "adopt":
        cur.execute(
            """
            INSERT INTO birthday_calendar_events (user_id, calendar_id, event_id, birth_md, source, summary)
            VALUES (%s, %s, %s, %s, 'adopted', %s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (uid, calendar_id, plan["event_id"], _md(birth), plan.get("summary")),
        )
        return {**plan, "done": True}
    if plan["action"] == "move":
        body = _event_body(user, birth, today)
        service.events().patch(
            calendarId=calendar_id, eventId=plan["event_id"], sendUpdates="all",
            body={k: body[k] for k in ("start", "end", "recurrence")},
        ).execute()
        cur.execute(
            "UPDATE birthday_calendar_events SET birth_md = %s, updated_at = now() WHERE user_id = %s",
            (_md(birth), uid),
        )
        return {**plan, "done": True}
    return {**plan, "done": False}


def _forget_dead_rows(cur, service, calendar_id, mapped, users) -> None:
    """Si Jazmín borró un evento en Google, la fila apunta a la nada: se suelta."""
    for u in users:
        row = mapped.get(u["user_id"])
        if row and not _event_alive(service, row["calendar_id"], row["event_id"]):
            cur.execute("DELETE FROM birthday_calendar_events WHERE user_id = %s", (u["user_id"],))
            mapped.pop(u["user_id"], None)


# ------------------------------------------------------------------ público ----

FORCEABLE_REVIEWS = {"same_day_event_other_name", "named_event_other_day"}


def sync_users(user_id: Optional[int] = None, dry_run: bool = False, force: bool = False) -> Dict[str, Any]:
    """Sincroniza una persona (user_id) o todas las activas con fecha (backfill).

    force (sólo con user_id): una persona decidió que el evento parecido NO es de
    esta persona, así que se crea igual ("Create anyway" del panel).
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            ensure_birthday_schema(cur)
            conn.commit()
            try:
                service, calendar_id = _service_and_calendar(cur)
            except NotConnected as exc:
                return {"connected": False, "error": str(exc), "error_kind": exc.kind, "results": []}
            users = [u for u in _active_users(cur, user_id) if _as_date(u["fecha_nacimiento"])]
            mapped = _mapped(cur)
            _forget_dead_rows(cur, service, calendar_id, mapped, users)
            if not dry_run:
                conn.commit()
            events = _birthday_events(service, calendar_id)
            taken = {r["event_id"] for r in mapped.values()}
            people = _all_birthdays(cur)
            repeated = _repeated_first_names(_active_users(cur))
            results = []
            for u in users:
                birth = _as_date(u["fecha_nacimiento"])
                plan = _classify(u, birth, mapped.get(u["user_id"]), events, taken, people)
                if plan["action"] == "create":
                    plan["title"] = _event_body(u, birth, today_ar(), repeated)["summary"]
                if force and user_id and plan.get("reason") in FORCEABLE_REVIEWS:
                    plan = {"action": "create", "forced": True}
                base = {"user_id": u["user_id"], "name": u["user_name"], "birthday": _md(birth)}
                if plan.get("event_id"):
                    taken.add(plan["event_id"])
                if dry_run or plan["action"] in ("ok", "review"):
                    results.append({**base, **plan})
                    continue
                try:
                    results.append({**base, **_apply(cur, service, calendar_id, u, birth, plan, repeated)})
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    logging.exception("birthday sync: failed user_id=%s", u["user_id"])
                    results.append({**base, **plan, "done": False, "error": str(exc)})
            return {"connected": True, "dry_run": dry_run, "calendar_id": calendar_id, "results": results}
    finally:
        conn.close()


def sync_birthday_event_async(user_id: int) -> None:
    """Lo llama update_user después del commit. Nunca levanta."""
    def _run():
        try:
            out = sync_users(user_id=user_id)
            logging.info("birthday sync user_id=%s → %s", user_id, out.get("results") or out.get("error"))
        except Exception:
            logging.exception("birthday sync crashed user_id=%s", user_id)

    threading.Thread(target=_run, daemon=True).start()


# ------------------------------------------------------------------- bajas ----
#
# Cuando se da de baja a alguien en el hub (admin_user_access.is_active = FALSE),
# su cumple sale del calendario (pedido de la owner, 2026-09-30). Se borra la
# serie entera con sendUpdates="none": el evento desaparece de los calendarios
# del equipo igual, pero sin mandar a 35 personas un "Canceled event: Cumple X"
# que anuncie la baja. Aplica también a los eventos hechos a mano.

def _inactive_users(cur, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    cur.execute(
        f"""
        SELECT u.user_id, u.user_name, u.nickname, u.fecha_nacimiento
          FROM users u
          JOIN admin_user_access aua ON aua.user_id = u.user_id
         WHERE aua.is_active = FALSE
           {"AND u.user_id = %s" if user_id else ""}
         ORDER BY u.user_name
        """,
        (user_id,) if user_id else None,
    )
    return [dict(r) for r in cur.fetchall()]


def _events_of_inactive(user, row, events, active_people, active_event_ids) -> List[Dict[str, Any]]:
    """Qué eventos del calendario son el cumple de esta persona dada de baja.

    El que el hub tiene registrado (creado o adoptado) y, si no, los de su día con
    su nombre. Nunca uno registrado a nombre de alguien activo, ni uno que nombre
    a una persona activa que cumple ese mismo día (Benjamin y Mia, el 7-mar).
    """
    birth = _as_date(user["fecha_nacimiento"])
    found = []
    for e in events:
        if e["ids"] & active_event_ids:
            continue
        if row and row["event_id"] in e["ids"]:
            found.append(e)
        elif birth and e["md"] == _md(birth) and _name_matches(e["summary"], user) \
                and not _belongs_to_other(e, user, active_people):
            found.append(e)
    return found


def remove_birthday_event(user_id: int, dry_run: bool = False) -> Dict[str, Any]:
    """Borra del calendario el cumple de una persona dada de baja. Si está activa, no toca nada."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            ensure_birthday_schema(cur)
            conn.commit()
            users = _inactive_users(cur, user_id)
            if not users:
                return {"removed": [], "reason": "user_is_active"}
            try:
                service, calendar_id = _service_and_calendar(cur)
            except NotConnected as exc:
                return {"connected": False, "error": str(exc), "error_kind": exc.kind, "removed": []}
            mapped = _mapped(cur)
            active_ids = {u["user_id"] for u in _active_users(cur)}
            active_people = [p for p in _all_birthdays(cur) if p["user_id"] in active_ids]
            active_event_ids = {r["event_id"] for uid, r in mapped.items() if uid in active_ids}
            targets = _events_of_inactive(users[0], mapped.get(user_id), _birthday_events(service, calendar_id),
                                          active_people, active_event_ids)
            removed = []
            if not dry_run:
                for e in targets:
                    for eid in e["ids"]:
                        try:
                            service.events().delete(calendarId=calendar_id, eventId=eid, sendUpdates="none").execute()
                        except Exception as exc:
                            if getattr(getattr(exc, "resp", None), "status", None) not in (404, 410):
                                raise
                    removed.append(e["summary"])
                cur.execute("DELETE FROM birthday_calendar_events WHERE user_id = %s", (user_id,))
                conn.commit()
            return {"connected": True, "dry_run": dry_run, "removed": removed,
                    "would_remove": [e["summary"] for e in targets] if dry_run else None}
    finally:
        conn.close()


def remove_birthday_event_async(user_id: int) -> None:
    """Lo llama la baja de usuario (admin_routes) después del commit. Nunca levanta."""
    def _run():
        try:
            out = remove_birthday_event(user_id)
            logging.info("birthday removal user_id=%s → %s", user_id, out)
        except Exception:
            logging.exception("birthday removal crashed user_id=%s", user_id)

    threading.Thread(target=_run, daemon=True).start()


def birthday_overview() -> Dict[str, Any]:
    """Panel + mail semanal: sin fecha, próximos 30 días y su estado."""
    today = today_ar()
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            ensure_birthday_schema(cur)
            conn.commit()
            users = _active_users(cur)
            mapped = _mapped(cur)
            connected, error, error_kind, events = True, None, None, []
            try:
                service, calendar_id = _service_and_calendar(cur)
                events = _birthday_events(service, calendar_id)
            except NotConnected as exc:
                connected, error, error_kind = False, str(exc), exc.kind
            except Exception as exc:
                connected, error, error_kind = False, f"Google error: {exc}", "google_error"
            alive = set().union(*(e["ids"] for e in events)) if events else set()
            people = _all_birthdays(cur)
            taken = {r["event_id"] for r in mapped.values() if not connected or r["event_id"] in alive}

            missing, upcoming = [], []
            for u in users:
                birth = _as_date(u["fecha_nacimiento"])
                who = {"user_id": u["user_id"], "name": u["user_name"], "email": u["email"]}
                if not birth:
                    missing.append(who)
                    continue
                nxt = _next_occurrence(birth, today)
                days = (nxt - today).days
                if days > UPCOMING_DAYS:
                    continue
                row = mapped.get(u["user_id"])
                if row and connected and row["event_id"] not in alive:
                    row = None  # lo borraron en Google
                if connected:
                    plan = _classify(u, birth, row, events, taken - ({row["event_id"]} if row else set()), people)
                else:
                    plan = {"action": "ok" if row else "unknown"}
                status = {"ok": "ok", "adopt": "manual_event", "create": "no_event",
                          "move": "wrong_date", "review": "review"}.get(plan["action"], "unknown")
                upcoming.append({**who, "birthday": nxt.isoformat(), "in_days": days,
                                 "status": status, "detail": plan})
            upcoming.sort(key=lambda r: r["in_days"])

            # Gente dada de baja cuyo cumple sigue en el calendario (bajas previas a
            # que esto existiera, o una baja en la que Google falló).
            inactive_in_calendar = []
            if connected:
                active_ids = {u["user_id"] for u in users}
                active_people = [p for p in people if p["user_id"] in active_ids]
                active_event_ids = {r["event_id"] for uid, r in mapped.items() if uid in active_ids}
                for u in _inactive_users(cur):
                    evs = _events_of_inactive(u, mapped.get(u["user_id"]), events, active_people, active_event_ids)
                    if evs:
                        inactive_in_calendar.append({"user_id": u["user_id"], "name": u["user_name"],
                                                     "summaries": [e["summary"] for e in evs]})
            return {
                "today": today.isoformat(), "connected": connected, "error": error, "error_kind": error_kind,
                "calendar_owner": CALENDAR_OWNER_EMAIL, "calendar_name": CALENDAR_NAME,
                "missing_birthday": missing, "upcoming": upcoming,
                "inactive_in_calendar": inactive_in_calendar,
            }
    finally:
        conn.close()


# ------------------------------------------------------------- mail semanal ----

_STATUS_LABEL = {
    "no_event": "No event in the calendar",
    "review": "Needs review (possible duplicate)",
    "wrong_date": "Event on a different date",
    "unknown": "Unknown (Google not connected)",
}


def _report_email(ov: Dict[str, Any]) -> tuple[str, str]:
    li = 'style="margin:0 0 6px;"'
    parts = []
    if not ov["connected"]:
        parts.append(
            f'<p style="margin:0 0 16px;color:#b45309;"><strong>Google Calendar is not connected</strong> '
            f"— birthday events can't be created until you connect it from the Birthdays tab. "
            f"({html.escape(ov['error'] or '')})</p>"
        )
    pending = [u for u in ov["upcoming"] if u["status"] not in ("ok", "manual_event")]
    if pending:
        items = "".join(
            f"<li {li}><strong>{html.escape(u['name'] or '')}</strong> — {html.escape(u['birthday'])} "
            f"(in {u['in_days']} days): {html.escape(_STATUS_LABEL.get(u['status'], u['status']))}</li>"
            for u in pending
        )
        parts.append(f'<p style="margin:0 0 8px;">Upcoming birthdays (next {UPCOMING_DAYS} days) without a confirmed event:</p>'
                     f'<ul style="margin:0 0 18px;padding-left:20px;">{items}</ul>')
    if ov.get("inactive_in_calendar"):
        items = "".join(
            f"<li {li}>{html.escape(u['name'] or '')} — {html.escape(', '.join(u['summaries']))}</li>"
            for u in ov["inactive_in_calendar"]
        )
        parts.append(f'<p style="margin:0 0 8px;">No longer at Vintti but still in the birthday calendar '
                     f'(remove them from the Birthdays tab):</p>'
                     f'<ul style="margin:0 0 18px;padding-left:20px;">{items}</ul>')
    if ov["missing_birthday"]:
        items = "".join(
            f"<li {li}>{html.escape(u['name'] or '')} <span style=\"color:#52606d;\">({html.escape(u['email'] or '')})</span></li>"
            for u in ov["missing_birthday"]
        )
        parts.append(f'<p style="margin:0 0 8px;">Active teammates with no Date of Birth in their profile '
                     f'(they already get a daily reminder to fill it in):</p>'
                     f'<ul style="margin:0 0 18px;padding-left:20px;">{items}</ul>')
    body = f"""
    <div style="font-family:'Inter','Segoe UI',Arial,sans-serif;font-size:15px;line-height:1.65;color:#243B53;">
      <p style="margin:0 0 18px;font-size:16px;">Hi Jaz,</p>
      {''.join(parts)}
      <p style="margin:0 0 22px;">
        <a href="{PROFILE_URL}" style="display:inline-block;background:#003bff;color:#fff;text-decoration:none;
           padding:10px 18px;border-radius:10px;font-weight:600;">Open Team birthdays</a>
      </p>
      <p style="margin:0;font-size:14px;color:#52606d;">Thanks,<br/><strong>Vintti Hub</strong></p>
    </div>
    """.strip()
    return "Team birthdays: weekly check", body


def run_weekly_birthday_report(dry_run: bool = False) -> Dict[str, Any]:
    """Un mail por semana (el cron pega varias veces el lunes; la tabla corta el doble envío)."""
    today = today_ar()
    week_start = today - timedelta(days=today.weekday())
    ov = birthday_overview()
    pending = [u for u in ov["upcoming"] if u["status"] not in ("ok", "manual_event")]
    has_news = bool(pending or ov["missing_birthday"] or ov.get("inactive_in_calendar") or not ov["connected"])
    if dry_run:
        return {"dry_run": True, "would_send": has_news, "overview": ov}
    if not has_news:
        return {"sent": False, "reason": "nothing_to_report"}

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            ensure_birthday_schema(cur)
            cur.execute(
                "INSERT INTO birthday_report_log (week_start) VALUES (%s) ON CONFLICT DO NOTHING RETURNING week_start",
                (week_start,),
            )
            if not cur.fetchone():
                conn.commit()
                return {"sent": False, "reason": "already_sent_this_week"}
            subject, body = _report_email(ov)
            to = list(RECIPIENTS)
            if TEST_ONLY_RECIPIENT:
                to, subject = [TEST_ONLY_RECIPIENT], f"[TEST] {subject}"
            result = post_transactional_email(to, subject, body, "Weekly birthday report")
            if not result.get("sent"):
                conn.rollback()  # se reintenta en la próxima corrida del lunes
                return {"sent": False, "reason": "send_failed"}
            conn.commit()
            return {"sent": True, "to": to, "pending": len(pending), "missing": len(ov["missing_birthday"])}
    finally:
        conn.close()
