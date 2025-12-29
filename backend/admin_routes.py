from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from admin_access import (
    ADMIN_ALLOWED_EMAILS,
    ensure_admin_user_access_table,
    normalize_email,
)
from db import get_connection
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Email, Mail

bp = Blueprint("admin_users", __name__, url_prefix="/admin")

BOGOTA_TZ = timezone(timedelta(hours=-5))
FRONT_BASE_URL = os.environ.get("FRONT_BASE_URL", "https://vinttihub.vintti.com")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

ensure_admin_user_access_table()

DEFAULT_VACACIONES_ACUMULADAS = 0
DEFAULT_VACACIONES_HABILES = 15
DEFAULT_VACACIONES_CONSUMIDAS = 0
DEFAULT_VINTTI_DAYS_CONSUMIDOS = 0
DEFAULT_FERIADOS_CONSUMIDOS = 0


def _int_or_none(value: Optional[str]) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _current_user_id() -> Optional[int]:
    value = getattr(request, "user_id", None)
    if isinstance(value, int):
        return value
    from_cookie = _int_or_none(request.cookies.get("user_id"))
    if from_cookie:
        return from_cookie
    from_query = _int_or_none(request.args.get("user_id"))
    if from_query:
        return from_query
    from_header = _int_or_none(request.headers.get("X-User-Id") or request.headers.get("x-user-id"))
    if from_header:
        return from_header
    return None


def _as_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _friendly_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


@bp.post("/users")
def create_hub_user():
    requester_id = _current_user_id()
    if not requester_id:
        return _friendly_error("Please log in again to continue.", 401)

    payload = request.get_json(silent=True) or {}
    full_name = (payload.get("full_name") or payload.get("name") or "").strip()
    raw_email = payload.get("email") or payload.get("email_vintti") or ""
    candidate_email = normalize_email(raw_email)
    role = (payload.get("role") or "").strip() or None
    send_invite = _as_bool(payload.get("send_invite"), True)
    is_active = _as_bool(payload.get("is_active"), True)
    leader_value = payload.get("leader_user_id") or payload.get("leader_id") or payload.get("lider")
    leader_user_id = _int_or_none(leader_value)

    if not full_name:
        return _friendly_error("Full name is required.")
    if not candidate_email or not EMAIL_RE.match(candidate_email):
        return _friendly_error("Please enter a valid email address.")

    conn = get_connection()
    requester = None
    new_user = None
    invite_token = None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT user_id, user_name, email_vintti FROM users WHERE user_id = %s",
                (requester_id,),
            )
            requester = cur.fetchone()
            if not requester:
                return _friendly_error("You need an active Hub session to continue.", 401)

            requester_email = normalize_email(requester.get("email_vintti"))
            if requester_email not in ADMIN_ALLOWED_EMAILS:
                return _friendly_error("You do not have access to this tool.", 403)

            cur.execute(
                "SELECT user_id FROM users WHERE LOWER(email_vintti) = %s",
                (candidate_email,),
            )
            duplicate = cur.fetchone()
            if duplicate:
                return _friendly_error("That email is already linked to a Vintti Hub profile.", 409)

            leader_row = None
            if leader_user_id:
                cur.execute(
                    "SELECT user_id, user_name FROM users WHERE user_id = %s",
                    (leader_user_id,),
                )
                leader_row = cur.fetchone()
                if not leader_row:
                    return _friendly_error("The selected leader no longer exists. Refresh and try again.")

            nickname = (full_name.split() or [""])[0] or candidate_email.split("@")[0]
            cur.execute("SELECT COALESCE(MAX(user_id), 0) + 1 AS next_id FROM users")
            row = cur.fetchone()
            next_user_id = row["next_id"] if row and row.get("next_id") else 1
            cur.execute(
                """
                INSERT INTO users (
                    user_id,
                    user_name,
                    email_vintti,
                    role,
                    nickname,
                    password,
                    updated_at,
                    lider,
                    vacaciones_acumuladas,
                    vacaciones_habiles,
                    vacaciones_consumidas,
                    vintti_days_consumidos,
                    feriados_consumidos
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    NULL,
                    NOW()::date,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                RETURNING user_id, user_name, email_vintti, role
                """,
                (
                    next_user_id,
                    full_name,
                    candidate_email,
                    role,
                    nickname,
                    leader_row["user_id"] if leader_row else None,
                    DEFAULT_VACACIONES_ACUMULADAS,
                    DEFAULT_VACACIONES_HABILES,
                    DEFAULT_VACACIONES_CONSUMIDAS,
                    DEFAULT_VINTTI_DAYS_CONSUMIDOS,
                    DEFAULT_FERIADOS_CONSUMIDOS
                ),
            )
            new_user = cur.fetchone()
            if not new_user:
                raise RuntimeError("User insert returned no data")

            cur.execute(
                """
                INSERT INTO admin_user_access (user_id, is_active, created_by_email)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET
                    is_active = EXCLUDED.is_active,
                    updated_at = NOW()
                """,
                (new_user["user_id"], is_active, requester.get("email_vintti")),
            )

            if send_invite and is_active:
                invite_token = secrets.token_urlsafe(32)
                expires_at = datetime.now(BOGOTA_TZ) + timedelta(hours=48)
                cur.execute(
                    """
                    UPDATE users
                       SET reset_token = %s,
                           reset_token_expires_at = %s
                     WHERE user_id = %s
                    """,
                    (invite_token, expires_at, new_user["user_id"]),
                )

        conn.commit()
    except Exception as exc:
        conn.rollback()
        logging.exception("Failed to create Hub user via admin route")
        return _friendly_error("We could not create that user right now. Please try again later.", 500)
    finally:
        conn.close()

    invite_sent = False
    if invite_token:
        invite_sent = _send_invite_email(
            target_email=candidate_email,
            full_name=full_name,
            token=invite_token,
            invited_by=requester.get("user_name") if requester else None,
        )

    return (
        jsonify(
            {
                "ok": True,
                "user": {
                    "user_id": new_user["user_id"],
                    "user_name": new_user["user_name"],
                    "email_vintti": new_user["email_vintti"],
                    "role": new_user.get("role"),
                    "is_active": is_active,
                },
                "invite_sent": bool(invite_sent),
                "message": "User created. Invite email sent." if invite_sent else "User created.",
            }
        ),
        201,
    )


def _send_invite_email(
    target_email: str, full_name: str, token: str, invited_by: Optional[str]
) -> bool:
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        logging.warning("SENDGRID_API_KEY is missing; invite email skipped")
        return False

    reset_link = f"{FRONT_BASE_URL.rstrip('/')}/reset_password.html?token={token}"
    greeter = invited_by or "The Vintti Team"
    plain_body = f"""Hi {full_name}!

{greeter} just granted you access to Vintti HUB.

Click the link below to set your password and log in:
{reset_link}

If you weren't expecting this, you can ignore it."""

    html_body = f"""
<div style="font-family:Onest,Arial,sans-serif;color:#111;line-height:1.6;font-size:15px;">
  <p>Hi {full_name.split()[0] if full_name else ''} 👋</p>
  <p><strong>{greeter}</strong> just granted you access to <strong>Vintti HUB</strong>.</p>
  <p>Set your password and get started by tapping the button:</p>
  <p style="margin:20px 0;">
    <a href="{reset_link}"
       style="background:#0f172a;color:#fff;padding:12px 22px;border-radius:999px;
              text-decoration:none;font-weight:600;display:inline-block;">
      Set your password
    </a>
  </p>
  <p>If the button does not work, copy this link:</p>
  <p style="font-size:13px;color:#555;word-break:break-all;">{reset_link}</p>
  <p style="margin-top:24px;font-size:12px;color:#94a3b8;">
    If you weren't expecting this invite you can safely ignore it.
  </p>
  <p style="margin-top:16px;">— Vintti HUB</p>
</div>
""".strip()

    try:
        message = Mail(
            from_email=Email("hub@vintti-hub.com", name="Vintti HUB"),
            to_emails=[target_email],
            subject="You're invited to Vintti HUB",
            plain_text_content=plain_body,
            html_content=html_body,
        )
        sg = SendGridAPIClient(api_key)
        sg.send(message)
        return True
    except Exception:
        logging.exception("Failed to send admin invite email")
        return False
