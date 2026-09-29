"""Panel "Team birthdays" de docs/profile.html (utils/birthday_calendar.py).

Sólo PANEL_EMAILS (Jazmín + la owner). La identidad sale del user_id que manda
el helper api() de profile.js, con el mismo nivel de chequeo que el resto del
perfil: alcanza para que el panel no le aparezca a cualquiera, no es auth real.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_connection
from utils.birthday_calendar import PANEL_EMAILS, birthday_overview, sync_users

bp = Blueprint("birthdays", __name__)


def _caller_email():
    raw = request.args.get("user_id") or request.cookies.get("user_id") or request.headers.get("X-User-Id")
    try:
        uid = int(raw)
    except (TypeError, ValueError):
        return None
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT LOWER(TRIM(email_vintti)) AS email FROM users WHERE user_id = %s", (uid,))
            row = cur.fetchone()
            return row["email"] if row else None
    finally:
        conn.close()


def _deny():
    if _caller_email() not in PANEL_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    return None


@bp.get("/birthdays/overview")
def overview():
    denied = _deny()
    if denied:
        return denied
    return jsonify(birthday_overview())


@bp.post("/birthdays/sync/<int:user_id>")
def sync_one(user_id: int):
    denied = _deny()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    return jsonify(sync_users(user_id=user_id, force=data.get("force") is True))


@bp.post("/birthdays/backfill")
def backfill():
    """Todas las personas activas con fecha. dry_run por defecto: hay que pedir false."""
    denied = _deny()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    dry = data.get("dry_run", True) is not False
    return jsonify(sync_users(dry_run=dry))
