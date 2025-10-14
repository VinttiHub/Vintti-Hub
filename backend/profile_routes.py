# profile_routes.py
import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional, Dict, Any

from flask import Blueprint, request, jsonify, g
from psycopg2.extras import RealDictCursor

from db import get_connection  # your existing helper

bp = Blueprint("profile", __name__, url_prefix="")

BOGOTA_TZ = timezone(timedelta(hours=-5))

# --- helper: how we identify the current user ---
def _current_user_id() -> Optional[int]:
    """
    Replace this with your real auth. For now:
    - First try session (Flask login)
    - Else try a header X-User-Id
    - Else query param (for local testing only)
    """
    uid = getattr(g, "user_id", None)
    if uid: return uid
    h = request.headers.get("X-User-Id")
    if h and h.isdigit(): return int(h)
    q = request.args.get("user_id")
    if q and q.isdigit(): return int(q)
    return None

def _row_to_json(row: Dict[str, Any]) -> Dict[str, Any]:
    # Normalize date fields to YYYY-MM-DD
    for k in ("ingreso_vintti_date", "fecha_nacimiento", "start_date", "end_date", "created_at", "updated_at"):
        if k in row and row[k] is not None:
            v = row[k]
            if isinstance(v, (datetime, date)):
                row[k] = v.date().isoformat() if isinstance(v, datetime) else v.isoformat()
            else:
                try:
                    dt = datetime.fromisoformat(str(v))
                    row[k] = dt.date().isoformat()
                except Exception:
                    pass
    return row

# --- USERS ---

@bp.get("/profile/me")
def me():
    user_id = _current_user_id()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401

    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT user_id, user_name, email_vintti, role, emergency_contact,
                   ingreso_vintti_date, fecha_nacimiento, avatar_url
            FROM users
            WHERE user_id = %s
        """, (user_id,))
        row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"error":"not found"}), 404
    return jsonify(_row_to_json(row))

@bp.put("/users/<int:user_id>")
def update_user(user_id: int):
    if _current_user_id() != user_id:
        # Allow editing only your own profile (adjust if admins can edit others)
        return jsonify({"error":"forbidden"}), 403

    data = request.get_json(silent=True) or {}
    fields = {
        "user_name": data.get("user_name"),
        "email_vintti": data.get("email_vintti"),
        "role": data.get("role"),
        "emergency_contact": data.get("emergency_contact"),
        "ingreso_vintti_date": data.get("ingreso_vintti_date"),
        "fecha_nacimiento": data.get("fecha_nacimiento"),
    }

    sets = []
    vals = []
    for col, val in fields.items():
        if val is not None:
            sets.append(f"{col} = %s")
            vals.append(val)

    if not sets:
        return jsonify({"ok": True})  # nothing to update

    vals.append(user_id)

    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"""
            UPDATE users
            SET {", ".join(sets)}, updated_at = NOW() AT TIME ZONE 'UTC'
            WHERE user_id = %s
            RETURNING user_id
        """, tuple(vals))
        updated = cur.fetchone()
        conn.commit()
    conn.close()
    if not updated:
        return jsonify({"error":"not found"}), 404
    return jsonify({"ok": True})

# --- TIME OFF REQUESTS ---

@bp.get("/time_off_requests")
def list_time_off():
    user_id = request.args.get("user_id")
    if not user_id or not user_id.isdigit():
        return jsonify({"error":"user_id required"}), 400

    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, user_id, kind, start_date, end_date, reason, status, created_at
            FROM time_off_requests
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 100
        """, (int(user_id),))
        rows = cur.fetchall()
    conn.close()

    return jsonify([_row_to_json(r) for r in rows])

@bp.post("/time_off_requests")
def create_time_off():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    kind = (data.get("kind") or "").lower().strip()
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    reason = data.get("reason")

    if not user_id or not str(user_id).isdigit():
        return jsonify({"error":"user_id required"}), 400
    if kind not in ("vacation","personal","medical","other"):
        return jsonify({"error":"invalid kind"}), 400
    if not start_date or not end_date:
        return jsonify({"error":"start_date and end_date required"}), 400
    if end_date < start_date:
        return jsonify({"error":"end_date before start_date"}), 400

    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            INSERT INTO time_off_requests (user_id, kind, start_date, end_date, reason, status, created_at)
            VALUES (%s, %s, %s, %s, %s, 'pending', NOW() AT TIME ZONE 'UTC')
            RETURNING id
        """, (int(user_id), kind, start_date, end_date, reason))
        row = cur.fetchone()
        conn.commit()
    conn.close()

    return jsonify({"ok": True, "id": row["id"]}), 201
