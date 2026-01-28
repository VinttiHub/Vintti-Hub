from __future__ import annotations

from typing import Optional

from flask import Blueprint, jsonify, request, g
from psycopg2.extras import RealDictCursor

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


@bp.get("/moods/today/team")
def get_today_team_moods():
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    t.user_id,
                    t.nickname,
                    t.mood,
                    t.clicked_at
                FROM (
                    SELECT DISTINCT ON (m.user_id)
                        m.user_id,
                        COALESCE(NULLIF(u.nickname, ''), NULLIF(u.user_name, ''), u.email_vintti, CONCAT('User ', m.user_id)) AS nickname,
                        m.mood,
                        m.clicked_at
                    FROM moods m
                    JOIN users u ON u.user_id = m.user_id
                    LEFT JOIN admin_user_access aua ON aua.user_id = u.user_id
                    WHERE m.clicked_at::date = CURRENT_DATE
                      AND COALESCE(aua.is_active, TRUE)
                    ORDER BY m.user_id, m.clicked_at DESC
                ) t
                ORDER BY LOWER(t.nickname) ASC
                """
            )
            rows = cur.fetchall() or []
        conn.close()
        for row in rows:
            clicked_at = row.get("clicked_at")
            if hasattr(clicked_at, "isoformat"):
                row["clicked_at"] = clicked_at.isoformat()
        return jsonify(rows)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
