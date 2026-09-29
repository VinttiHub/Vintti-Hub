"""Recordatorio de perfil incompleto (docs/profile.html).

Cada persona activa a la que le falte alguno de los campos de REQUIRED_FIELDS
recibe un mail cada 24 h (lunes a viernes, hora Argentina) hasta completarlos.

El corte es por construcción: el runner elige a quién mandarle mirando `users`
en cada corrida, así que apenas la persona guarda los 4 campos desde su perfil
(`PATCH /users/<id>`) deja de salir en la query. No hay flag que alguien tenga
que apagar. Si después borra un campo, vuelve a entrar sola.

"Vacío" incluye el string vacío: profile.js guarda Emergency Contact en blanco
como '' (no NULL), así que se compara con NULLIF(TRIM(col), '').

Sin CC: el mail va sólo a `users.email_vintti` (no hay mail personal en la base).
"""
from __future__ import annotations

import html
import logging
from typing import Any, Dict, List, Optional

from psycopg2.extras import RealDictCursor

from db import get_connection
from utils.hubspot_waiting_alert import alerta_en_pausa
from utils.transactional_email import post_transactional_email

# (columna de users, etiqueta que ve la persona). Única definición: la query y
# el mail salen de acá.
REQUIRED_FIELDS = [
    ("address", "Address"),
    ("emergency_contact", "Emergency Contact"),
    ("fecha_nacimiento", "Date of Birth"),
    ("ingreso_vintti_date", "Vintti Start Date"),
]
_TEXT_FIELDS = {"address", "emergency_contact"}

# Modo prueba: con un email acá, TODOS los mails van sólo a esa dirección, con
# [TEST] en el asunto y un aviso de a quién habrían ido. None = producción.
# Salió de prueba el 2026-09-29 a pedido de la owner. Hardcodeado a propósito,
# sin env var, mismo criterio que RECIPIENTS del auditor.
TEST_ONLY_RECIPIENT: Optional[str] = None
PROFILE_URL = "https://vinttihub.vintti.com/profile.html"

_schema_ready = False


def ensure_profile_reminder_schema(cur) -> None:
    global _schema_ready
    if _schema_ready:
        return
    # Se mira el catálogo antes: ALTER TABLE toma ACCESS EXCLUSIVE sobre `users`
    # aunque la columna ya exista (la crea _ensure_user_address_column de profile_routes).
    cur.execute(
        """
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'users' AND column_name = 'address'
        """
    )
    if not cur.fetchone():
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS address TEXT")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS profile_completion_reminders (
            user_id BIGINT PRIMARY KEY,
            first_sent_at TIMESTAMPTZ,
            last_sent_at TIMESTAMPTZ,
            send_count INTEGER NOT NULL DEFAULT 0,
            completed_at TIMESTAMPTZ
        )
        """
    )
    _schema_ready = True


def _missing_expr(col: str) -> str:
    if col in _TEXT_FIELDS:
        return f"NULLIF(TRIM(u.{col}), '') IS NULL"
    return f"u.{col} IS NULL"


def _any_missing_sql() -> str:
    return " OR ".join(f"({_missing_expr(c)})" for c, _ in REQUIRED_FIELDS)


def _mark_completed(cur) -> None:
    """Sólo registro: sella a quien tenía recordatorios y ya completó todo."""
    cur.execute(
        f"""
        UPDATE profile_completion_reminders r
           SET completed_at = now()
          FROM users u
         WHERE u.user_id = r.user_id
           AND r.completed_at IS NULL
           AND NOT ({_any_missing_sql()})
        """
    )


def _due_users(cur) -> List[Dict[str, Any]]:
    flags = ", ".join(f"({_missing_expr(c)}) AS missing_{c}" for c, _ in REQUIRED_FIELDS)
    cur.execute(
        f"""
        SELECT u.user_id, u.user_name, u.email_vintti, r.first_sent_at, {flags}
          FROM users u
          LEFT JOIN admin_user_access aua ON aua.user_id = u.user_id
          LEFT JOIN profile_completion_reminders r ON r.user_id = u.user_id
         WHERE COALESCE(aua.is_active, TRUE) = TRUE
           AND NULLIF(TRIM(u.email_vintti), '') IS NOT NULL
           AND ({_any_missing_sql()})
           AND (r.last_sent_at IS NULL OR now() - r.last_sent_at >= interval '24 hours')
         ORDER BY r.last_sent_at NULLS FIRST, u.user_id
        """
    )
    out = []
    for row in cur.fetchall() or []:
        missing = [label for col, label in REQUIRED_FIELDS if row.get(f"missing_{col}")]
        out.append({
            "user_id": row["user_id"],
            "name": row.get("user_name"),
            "email": (row.get("email_vintti") or "").strip().lower(),
            "missing": missing,
            "is_first": row.get("first_sent_at") is None,
        })
    return out


def _email(person: Dict[str, Any]):
    first_name = (person.get("name") or "").strip().split(" ")[0] or "there"
    prefix = "" if person["is_first"] else "Reminder: "
    subject = f"{prefix}Please complete your Vintti Hub profile"
    items = "".join(
        f'<li style="margin:0 0 6px;">{html.escape(label)}</li>' for label in person["missing"]
    )
    body = f"""
    <div style="font-family:'Inter','Segoe UI',Arial,sans-serif;font-size:15px;line-height:1.65;color:#243B53;">
      <p style="margin:0 0 18px;font-size:16px;">Hi {html.escape(first_name)},</p>
      <p style="margin:0 0 12px;">Your Vintti Hub profile is missing some information we need to have on file:</p>
      <ul style="margin:0 0 18px;padding-left:20px;font-weight:600;color:#111927;">{items}</ul>
      <p style="margin:0 0 22px;">
        <a href="{PROFILE_URL}" style="display:inline-block;background:#003bff;color:#fff;text-decoration:none;
           padding:10px 18px;border-radius:10px;font-weight:600;">Complete my profile</a>
      </p>
      <p style="margin:0 0 18px;font-size:14px;color:#52606d;">
        Open your profile, click <strong>Edit</strong> and save the missing fields.
        This reminder repeats every weekday until they're filled in.
      </p>
      <p style="margin:0;font-size:14px;color:#52606d;">Thanks,<br/><strong>Vintti Hub</strong></p>
    </div>
    """.strip()
    return subject, body


def _send(cur, person: Dict[str, Any]) -> Dict[str, Any]:
    subject, body = _email(person)
    to = [person["email"]]
    if TEST_ONLY_RECIPIENT:
        to = [TEST_ONLY_RECIPIENT]
        subject = f"[TEST] {subject}"
        body = (
            '<p style="font-family:Arial,sans-serif;font-size:13px;color:#b45309;'
            'background:#fffbeb;padding:8px 12px;border-radius:8px;">'
            f"Test mode — in production this would go to: {html.escape(person['email'])}</p>"
        ) + body
    base = {"user_id": person["user_id"], "email": person["email"], "missing": person["missing"]}
    result = post_transactional_email(to, subject, body, "Profile completion reminder")
    if not result.get("sent"):
        # last_sent_at queda como estaba: se reintenta en la próxima corrida.
        return {**base, "sent": False, "reason": "send_failed"}
    cur.execute(
        """
        INSERT INTO profile_completion_reminders (user_id, first_sent_at, last_sent_at, send_count)
        VALUES (%s, now(), now(), 1)
        ON CONFLICT (user_id) DO UPDATE
           SET first_sent_at = COALESCE(profile_completion_reminders.first_sent_at, now()),
               last_sent_at = now(),
               send_count = profile_completion_reminders.send_count + 1,
               completed_at = NULL
        """,
        (person["user_id"],),
    )
    return {**base, "sent": True, "to": to}


def run_due_profile_reminders(dry_run: bool = False) -> Dict[str, Any]:
    if alerta_en_pausa() and not dry_run:
        return {"skipped": True, "reason": "weekend", "results": []}

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            ensure_profile_reminder_schema(cur)
            if not dry_run:
                _mark_completed(cur)
            due = _due_users(cur)
            conn.commit()
            if dry_run:
                return {"dry_run": True, "test_mode": bool(TEST_ONLY_RECIPIENT), "count": len(due), "due": due}
            results = []
            for person in due:
                # Commit por persona: un error no deshace el last_sent_at de las
                # que ya salieron (se les volvería a mandar en una hora).
                try:
                    results.append(_send(cur, person))
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    logging.exception("profile reminder: failed user_id=%s", person.get("user_id"))
                    results.append({"user_id": person.get("user_id"), "sent": False, "reason": f"error: {exc}"})
            return {"test_mode": bool(TEST_ONLY_RECIPIENT), "results": results}
    finally:
        conn.close()
