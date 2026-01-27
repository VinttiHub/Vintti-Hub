from __future__ import annotations

from typing import Optional

from flask import Blueprint, jsonify, request, g

from db import get_connection

bp = Blueprint("moods", __name__)


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _current_user_id() -> Optional[int]:
    uid = getattr(g, "user_id", None)
    if isinstance(uid, int):
        return uid
    cookie_val = _int_or_none(request.cookies.get("user_id"))
    if cookie_val:
        return cookie_val
    query_val = _int_or_none(request.args.get("user_id"))
    if query_val:
        return query_val
    header_val = _int_or_none(request.headers.get("X-User-Id") or request.headers.get("x-user-id"))
    if header_val:
        return header_val
    return None


@bp.get("/moods/today")
def get_today_mood():
    user_id = _current_user_id()
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT mood, clicked_at
            FROM moods
            WHERE user_id = %s
              AND clicked_at::date = CURRENT_DATE
            ORDER BY clicked_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return jsonify({"mood": None, "clicked_at": None})
        return jsonify({"mood": row[0], "clicked_at": row[1].isoformat() if row[1] else None})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.post("/moods")
def save_mood():
    data = request.get_json(silent=True) or {}
    mood = (data.get("mood") or "").strip()
    if not mood:
        return jsonify({"error": "mood required"}), 400
    user_id = _int_or_none(data.get("user_id")) or _current_user_id()
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM moods
            WHERE user_id = %s
              AND clicked_at::date = CURRENT_DATE
            """,
            (user_id,),
        )
        cur.execute(
            """
            INSERT INTO moods (user_id, clicked_at, mood)
            VALUES (%s, NOW(), %s)
            RETURNING clicked_at
            """,
            (user_id, mood),
        )
        clicked_at = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"mood": mood, "clicked_at": clicked_at.isoformat() if clicked_at else None})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
