from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Set

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from admin_access import (
    ADMIN_ALLOWED_EMAILS,
    normalize_email,
)
from db import get_connection, mark_users_color_present, users_has_color
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Email, Mail

bp = Blueprint("admin_users", __name__, url_prefix="/admin")

BOGOTA_TZ = timezone(timedelta(hours=-5))
FRONT_BASE_URL = os.environ.get("FRONT_BASE_URL", "https://vinttihub.vintti.com")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# La tabla se crea en background desde create_app(); ver admin_access.py.

INVITE_TOKEN_TTL_HOURS = 48

DEFAULT_VACACIONES_ACUMULADAS = 0
DEFAULT_VACACIONES_HABILES = 15
DEFAULT_VACACIONES_CONSUMIDAS = 0
DEFAULT_VINTTI_DAYS_CONSUMIDOS = 0
DEFAULT_FERIADOS_CONSUMIDOS = 0


def _prorated_vacation_days_for_year(start_value: Optional[str], annual_days: float = DEFAULT_VACACIONES_HABILES) -> float:
    if not start_value:
        return annual_days
    try:
        start = datetime.strptime(str(start_value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return annual_days

    current_year = datetime.now(BOGOTA_TZ).year
    if start.year < current_year:
        return annual_days
    if start.year > current_year:
        return 0

    months_worked = max(0, 12 - start.month + 1)
    return int((months_worked * annual_days * 2) / 12) / 2


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


def _load_admin_requester(cur, requester_id: int):
    """Devuelve (requester_row, error_response). Mismo gate que create/deactivate."""
    cur.execute(
        "SELECT user_id, user_name, email_vintti FROM users WHERE user_id = %s",
        (requester_id,),
    )
    requester = cur.fetchone()
    if not requester:
        return None, _friendly_error("You need an active Hub session to continue.", 401)
    if normalize_email(requester.get("email_vintti")) not in ADMIN_ALLOWED_EMAILS:
        return None, _friendly_error("You do not have access to this tool.", 403)
    return requester, None


def _as_aware(value):
    """reset_token_expires_at puede volver naive según el driver/columna."""
    if value is None or getattr(value, "tzinfo", None) is not None:
        return value
    return value.replace(tzinfo=BOGOTA_TZ)


ROLE_KEYWORDS = {
    "recruiter": {"recruiter", "talent_acquisition", "talent_acquisition_recruiter", "hr_lead", "hrlead"},
    "sales_lead": {"sales_lead", "saleslead", "sales_lead_team"},
}


def _canonical_role_slug(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = (
        str(value)
        .strip()
        .lower()
        .replace("-", "_")
        .replace("/", "_")
    )
    cleaned = "_".join(piece for piece in cleaned.split())
    if not cleaned:
        return None
    for slug, keywords in ROLE_KEYWORDS.items():
        if cleaned in keywords:
            return slug
    if "recruit" in cleaned:
        return "recruiter"
    if "sales_lead" in cleaned or "saleslead" in cleaned:
        return "sales_lead"
    return None


TEAM_COLORS = {"azul", "rojo", "amarillo"}


def _ensure_user_color_column(cur):
    """Crea users.color si falta. Sólo desde los endpoints de escritura del admin.

    Un ADD COLUMN toma ACCESS EXCLUSIVE sobre `users`; corrido en cada request de
    lectura (que es como estaba) dos llamadas concurrentes se deadlockean contra
    admin_user_access. Acá se ejecuta a lo sumo una vez por proceso y sólo cuando
    la columna realmente no existe: lo normal es que ya la haya creado
    backend/sql/20260828_add_user_color.sql.
    """
    if users_has_color(cur):
        return
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS color TEXT")
    mark_users_color_present()


def _canonical_color(value) -> Optional[str]:
    """'Azul' / ' ROJO ' -> 'azul' / 'rojo'. Devuelve None si viene vacío."""
    if value is None:
        return None
    cleaned = str(value).strip().lower()
    if not cleaned:
        return None
    cleaned = (
        cleaned.replace("á", "a").replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ú", "u")
    )
    if cleaned.startswith("team "):
        cleaned = cleaned[5:].strip()
    return cleaned if cleaned in TEAM_COLORS else ""


def _detect_user_roles(payload: dict) -> Set[str]:
    detected: Set[str] = set()
    roles_field = payload.get("roles")
    if isinstance(roles_field, list):
        for value in roles_field:
            slug = _canonical_role_slug(value)
            if slug:
                detected.add(slug)

    if _as_bool(payload.get("is_recruiter"), False) or _as_bool(payload.get("is_hr_lead"), False):
        detected.add("recruiter")
    if _as_bool(payload.get("is_sales_lead"), False):
        detected.add("sales_lead")

    free_text_role = (payload.get("role") or "").lower()
    if free_text_role:
        if "recruit" in free_text_role or "talent acquisition" in free_text_role or "hr lead" in free_text_role:
            detected.add("recruiter")
        if "sales lead" in free_text_role or "saleslead" in free_text_role:
            detected.add("sales_lead")
    return detected


def _insert_user_roles(cur, user_id: int, roles: Iterable[str]) -> None:
    unique_roles = sorted({role for role in roles if role in {"recruiter", "sales_lead"}})
    if not unique_roles:
        return
    for role in unique_roles:
        cur.execute(
            """
            INSERT INTO user_roles (user_id, role_type)
            VALUES (%s, %s)
            ON CONFLICT (user_id, role_type) DO NOTHING
            """,
            (user_id, role),
        )


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
    role_flags = _detect_user_roles(payload)
    send_invite = _as_bool(payload.get("send_invite"), True)
    is_active = _as_bool(payload.get("is_active"), True)
    ingreso_vintti_date = payload.get("ingreso_vintti_date") or payload.get("start_date") or None
    team_color = _canonical_color(payload.get("color") or payload.get("team_color"))
    leader_value = payload.get("leader_user_id") or payload.get("leader_id") or payload.get("lider")
    leader_user_id = _int_or_none(leader_value)
    raw_reports = (
        payload.get("leader_of_user_ids")
        or payload.get("leader_of")
        or payload.get("leads_user_ids")
        or payload.get("reports")
    )

    def _parse_id_iter(values: Iterable) -> list[int]:
        parsed: list[int] = []
        for val in values:
            parsed_val = _int_or_none(val)
            if parsed_val:
                parsed.append(parsed_val)
        return parsed

    leader_of_ids: list[int] = []
    if isinstance(raw_reports, list):
        leader_of_ids = _parse_id_iter(raw_reports)
    elif isinstance(raw_reports, str) and raw_reports.strip():
        leader_of_ids = _parse_id_iter([piece.strip() for piece in raw_reports.split(",")])
    leader_of_ids = sorted(set(leader_of_ids))

    if not full_name:
        return _friendly_error("Full name is required.")
    if not candidate_email or not EMAIL_RE.match(candidate_email):
        return _friendly_error("Please enter a valid email address.")
    if team_color == "":
        return _friendly_error("Team color must be azul, rojo or amarillo.")

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

            _ensure_user_color_column(cur)

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

            if leader_of_ids:
                cur.execute(
                    "SELECT user_id FROM users WHERE user_id = ANY(%s)",
                    (leader_of_ids,),
                )
                existing_reports = {int(row["user_id"]) for row in cur.fetchall()}
                missing_reports = [str(i) for i in leader_of_ids if i not in existing_reports]
                if missing_reports:
                    return _friendly_error("Some selected reports are no longer available. Refresh the page.")

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
                    ingreso_vintti_date,
                    password,
                    updated_at,
                    lider,
                    vacaciones_acumuladas,
                    vacaciones_habiles,
                    vacaciones_consumidas,
                    vintti_days_consumidos,
                    feriados_consumidos,
                    color
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s,
                    NULL,
                    NOW()::date,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                RETURNING user_id, user_name, email_vintti, role, color
                """,
                (
                    next_user_id,
                    full_name,
                    candidate_email,
                    role,
                    nickname,
                    ingreso_vintti_date,
                    leader_row["user_id"] if leader_row else None,
                    DEFAULT_VACACIONES_ACUMULADAS,
                    _prorated_vacation_days_for_year(ingreso_vintti_date),
                    DEFAULT_VACACIONES_CONSUMIDAS,
                    DEFAULT_VINTTI_DAYS_CONSUMIDOS,
                    DEFAULT_FERIADOS_CONSUMIDOS,
                    team_color or None
                ),
            )
            new_user = cur.fetchone()
            if not new_user:
                raise RuntimeError("User insert returned no data")

            if role_flags:
                _insert_user_roles(cur, int(new_user["user_id"]), role_flags)

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

            if leader_of_ids:
                cur.execute(
                    """
                    UPDATE users
                       SET lider = %s,
                           updated_at = NOW() AT TIME ZONE 'UTC'
                     WHERE user_id = ANY(%s)
                    """,
                    (new_user["user_id"], leader_of_ids),
                )

            if send_invite and is_active:
                invite_token = secrets.token_urlsafe(32)
                expires_at = datetime.now(BOGOTA_TZ) + timedelta(hours=INVITE_TOKEN_TTL_HOURS)
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
                    "color": new_user.get("color"),
                    "is_active": is_active,
                },
                "invite_sent": bool(invite_sent),
                "message": "User created. Invite email sent." if invite_sent else "User created.",
            }
        ),
        201,
    )


def _soft_deactivate_user(cur, user_id: int, by_email: str) -> None:
    """Soft delete: marca al usuario Inactive (bloquea login) y crea/reinicia su
    fila de offboarding pendiente (snapshot del Hiring Manager = users.lider).
    NO borra nada de la base. Ver offboarding_routes."""
    from offboarding_routes import _ensure_offboarding_schema  # import diferido

    _ensure_offboarding_schema(cur)
    cur.execute(
        """
        INSERT INTO admin_user_access (user_id, is_active, deactivated_at, deactivated_by_email, created_by_email)
        VALUES (%s, FALSE, NOW(), %s, %s)
        ON CONFLICT (user_id) DO UPDATE
          SET is_active = FALSE, deactivated_at = NOW(),
              deactivated_by_email = EXCLUDED.deactivated_by_email, updated_at = NOW()
        """,
        (user_id, by_email, by_email),
    )
    cur.execute("SELECT lider FROM users WHERE user_id = %s", (user_id,))
    lider = (cur.fetchone() or {}).get("lider")
    cur.execute(
        """
        INSERT INTO offboarding (user_id, hiring_manager_id, created_by_email, status)
        VALUES (%s, %s, %s, 'pending')
        ON CONFLICT (user_id) DO UPDATE
          SET hiring_manager_id = EXCLUDED.hiring_manager_id,
              status = 'pending', computer_pickup_done = FALSE,
              form_submitted_at = NULL, offboarding_last_sent_at = NULL, pickup_last_sent_at = NULL,
              completed_at = NULL, completed_by_email = NULL, updated_at = NOW()
        """,
        (user_id, lider, by_email),
    )


def _deactivate_endpoint(user_id: int):
    requester_id = _current_user_id()
    if not requester_id:
        return _friendly_error("Please log in again to continue.", 401)

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT user_id, email_vintti FROM users WHERE user_id = %s",
                (requester_id,),
            )
            requester = cur.fetchone()
            if not requester:
                return _friendly_error("You need an active Hub session to continue.", 401)

            requester_email = normalize_email(requester.get("email_vintti"))
            if requester_email not in ADMIN_ALLOWED_EMAILS:
                return _friendly_error("You do not have access to this tool.", 403)

            if int(user_id) == int(requester_id):
                return _friendly_error("You cannot deactivate your own account.", 400)

            cur.execute(
                "SELECT user_id, user_name, email_vintti FROM users WHERE user_id = %s",
                (user_id,),
            )
            target = cur.fetchone()
            if not target:
                return _friendly_error("User not found.", 404)

            _soft_deactivate_user(cur, user_id, requester_email)
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception("Failed to deactivate Hub user via admin route")
        return _friendly_error("We could not deactivate that user right now. Please try again later.", 500)
    finally:
        conn.close()

    return jsonify({"ok": True, "deactivated_user_id": user_id}), 200


@bp.post("/users/<int:user_id>/deactivate")
def deactivate_hub_user(user_id: int):
    return _deactivate_endpoint(user_id)


@bp.delete("/users/<int:user_id>")
def delete_hub_user(user_id: int):
    # Ya NO hace hard delete: ahora es un soft delete (deactivate). Se mantiene el
    # verbo DELETE por compatibilidad, pero el efecto es desactivar, no borrar.
    return _deactivate_endpoint(user_id)


@bp.patch("/users/<int:user_id>/color")
def set_hub_user_color(user_id: int):
    """Asigna (o limpia) el color de equipo de un usuario. Sólo admins.

    Vive acá y no en el PATCH /users/<id> de profile_routes porque aquel se
    autentica con el user_id que declara el cliente: cualquiera podría cambiarse
    su propio equipo. El color lo asigna el admin.
    """
    requester_id = _current_user_id()
    if not requester_id:
        return _friendly_error("Please log in again to continue.", 401)

    payload = request.get_json(silent=True) or {}
    raw_color = payload.get("color", payload.get("team_color"))
    color = _canonical_color(raw_color)
    if color == "":
        return _friendly_error("Team color must be azul, rojo or amarillo.")

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _, error = _load_admin_requester(cur, requester_id)
            if error:
                return error

            _ensure_user_color_column(cur)

            cur.execute(
                """
                UPDATE users
                   SET color = %s,
                       updated_at = NOW()::date
                 WHERE user_id = %s
             RETURNING user_id, user_name, color
                """,
                (color, user_id),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return _friendly_error("That user no longer exists.", 404)
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception("Failed to update team color for user %s", user_id)
        return _friendly_error("We could not save that color right now.", 500)
    finally:
        conn.close()

    return jsonify({"ok": True, "user_id": int(row["user_id"]), "color": row.get("color")}), 200


@bp.get("/users/invite-status")
def hub_users_invite_status():
    """Usuarios que todavía no setearon contraseña (invitación pendiente) y si su
    link sigue vivo. Alimenta el badge + botón "Resend invite" del Access Manager."""
    requester_id = _current_user_id()
    if not requester_id:
        return _friendly_error("Please log in again to continue.", 401)

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _, error = _load_admin_requester(cur, requester_id)
            if error:
                return error

            cur.execute(
                """
                SELECT u.user_id, u.reset_token_expires_at
                  FROM users u
                  LEFT JOIN admin_user_access aua ON aua.user_id = u.user_id
                 WHERE u.password IS NULL
                   AND COALESCE(aua.is_active, TRUE)
                """
            )
            rows = cur.fetchall()
    except Exception:
        logging.exception("Failed to load Hub invite status")
        return _friendly_error("We could not load invite status right now.", 500)
    finally:
        conn.close()

    now = datetime.now(BOGOTA_TZ)
    users = []
    for row in rows:
        expires_at = _as_aware(row.get("reset_token_expires_at"))
        users.append(
            {
                "user_id": int(row["user_id"]),
                "invite_expires_at": expires_at.isoformat() if expires_at else None,
                "invite_valid": bool(expires_at and expires_at > now),
            }
        )

    return jsonify({"ok": True, "users": users}), 200


@bp.post("/users/<int:user_id>/resend-invite")
def resend_hub_user_invite(user_id: int):
    """Regenera el token de setup de contraseña (48h) y reenvía el mail de invitación.
    Sirve cuando el link original expiró: crear el usuario de nuevo da 409."""
    requester_id = _current_user_id()
    if not requester_id:
        return _friendly_error("Please log in again to continue.", 401)

    conn = get_connection()
    requester = None
    target = None
    invite_token = None
    expires_at = None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            requester, error = _load_admin_requester(cur, requester_id)
            if error:
                return error

            cur.execute(
                """
                SELECT u.user_id,
                       u.user_name,
                       u.email_vintti,
                       (u.password IS NOT NULL) AS has_password,
                       COALESCE(aua.is_active, TRUE) AS is_active
                  FROM users u
                  LEFT JOIN admin_user_access aua ON aua.user_id = u.user_id
                 WHERE u.user_id = %s
                """,
                (user_id,),
            )
            target = cur.fetchone()
            if not target:
                return _friendly_error("User not found.", 404)

            target_email = normalize_email(target.get("email_vintti"))
            if not target_email or not EMAIL_RE.match(target_email):
                return _friendly_error("That user has no valid email on file.", 400)
            if not target.get("is_active"):
                return _friendly_error(
                    "That user is deactivated. Reactivate them before resending the invite.", 409
                )
            if target.get("has_password"):
                return _friendly_error(
                    "That user already set a password. They can use "
                    "“Forgot / Change password?” on the login page.",
                    409,
                )

            invite_token = secrets.token_urlsafe(32)
            expires_at = datetime.now(BOGOTA_TZ) + timedelta(hours=INVITE_TOKEN_TTL_HOURS)
            cur.execute(
                """
                UPDATE users
                   SET reset_token = %s,
                       reset_token_expires_at = %s
                 WHERE user_id = %s
                """,
                (invite_token, expires_at, user_id),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception("Failed to regenerate invite token for Hub user")
        return _friendly_error("We could not resend that invite right now. Please try again later.", 500)
    finally:
        conn.close()

    invite_sent = _send_invite_email(
        target_email=target["email_vintti"],
        full_name=(target.get("user_name") or "").strip(),
        token=invite_token,
        invited_by=requester.get("user_name") if requester else None,
        resend=True,
    )
    if not invite_sent:
        # El token nuevo ya quedó guardado; reintentar simplemente lo regenera.
        return _friendly_error(
            "We created a new link but could not send the email. Please try again.", 502
        )

    return (
        jsonify(
            {
                "ok": True,
                "user_id": user_id,
                "invite_sent": True,
                "invite_expires_at": expires_at.isoformat(),
            }
        ),
        200,
    )


def _send_invite_email(
    target_email: str, full_name: str, token: str, invited_by: Optional[str], resend: bool = False
) -> bool:
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        logging.warning("SENDGRID_API_KEY is missing; invite email skipped")
        return False

    reset_link = f"{FRONT_BASE_URL.rstrip('/')}/reset_password.html?token={token}"
    greeter = invited_by or "The Vintti Team"
    subject = "Your new Vintti HUB access link" if resend else "You're invited to Vintti HUB"
    intro_plain = (
        "Here is a fresh link to set up your Vintti HUB account — the previous one expired."
        if resend
        else f"{greeter} just granted you access to Vintti HUB."
    )
    intro_html = (
        "Here is a fresh link to set up your <strong>Vintti HUB</strong> account — "
        "the previous one expired."
        if resend
        else f"<strong>{greeter}</strong> just granted you access to <strong>Vintti HUB</strong>."
    )
    plain_body = f"""Hi {full_name}!

{intro_plain}

Click the link below to set your password and log in:
{reset_link}

This link is valid for {INVITE_TOKEN_TTL_HOURS} hours.

If you weren't expecting this, you can ignore it."""

    html_body = f"""
<div style="font-family:Onest,Arial,sans-serif;color:#111;line-height:1.6;font-size:15px;">
  <p>Hi {full_name.split()[0] if full_name else ''} 👋</p>
  <p>{intro_html}</p>
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
  <p style="font-size:13px;color:#555;">This link is valid for {INVITE_TOKEN_TTL_HOURS} hours.</p>
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
