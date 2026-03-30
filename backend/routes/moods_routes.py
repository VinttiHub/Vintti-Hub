from __future__ import annotations

from datetime import date, timedelta
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


def _month_start_for(year: int, month: int) -> date:
    return date(year, month, 1)


def _month_end_for(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def _count_weekdays_inclusive(start: date, end: date) -> int:
    if end < start:
        return 0
    total = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            total += 1
        current += timedelta(days=1)
    return total


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


@bp.get("/moods/monthly-recap")
def get_monthly_recap():
    user_id = _current_user_id()
    if not user_id:
        return jsonify({"error": "user_id required"}), 400

    try:
        today = date.today()
        year = _int_or_none(request.args.get("year")) or today.year
        month = _int_or_none(request.args.get("month")) or today.month
        if month < 1 or month > 12:
            return jsonify({"error": "month must be between 1 and 12"}), 400

        month_start = _month_start_for(year, month)
        month_end = _month_end_for(year, month)
        effective_end = min(today, month_end)
        days_elapsed = _count_weekdays_inclusive(month_start, effective_end)

        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                WITH month_window AS (
                    SELECT
                        %s::date AS month_start,
                        %s::date AS effective_end,
                        %s::date AS month_end,
                        %s::int AS days_elapsed
                ),
                monthly_rows AS (
                    SELECT
                        m.mood,
                        m.clicked_at,
                        m.clicked_at::date AS mood_day
                    FROM moods m
                    CROSS JOIN month_window mw
                    WHERE m.user_id = %s
                      AND m.clicked_at::date BETWEEN mw.month_start AND mw.effective_end
                ),
                totals AS (
                    SELECT
                        COUNT(*)::int AS total_entries,
                        COUNT(DISTINCT CASE WHEN EXTRACT(ISODOW FROM mood_day) < 6 THEN mood_day END)::int AS days_with_mood,
                        MAX(clicked_at) AS last_entry_at
                    FROM monthly_rows
                ),
                grouped AS (
                    SELECT
                        mood,
                        COUNT(*)::int AS total
                    FROM monthly_rows
                    GROUP BY mood
                )
                SELECT
                    %s::int AS month,
                    %s::int AS year,
                    mw.month_start,
                    mw.effective_end AS today,
                    mw.month_end,
                    mw.days_elapsed AS days_elapsed,
                    EXTRACT(DAY FROM mw.month_end)::int AS days_in_month,
                    COALESCE(t.total_entries, 0) AS total_entries,
                    COALESCE(t.days_with_mood, 0) AS days_with_mood,
                    CASE
                        WHEN mw.days_elapsed > 0
                            THEN ROUND((COALESCE(t.days_with_mood, 0)::numeric / mw.days_elapsed::numeric) * 100, 1)
                        ELSE 0
                    END AS completion_rate,
                    t.last_entry_at,
                    (
                        SELECT g.mood
                        FROM grouped g
                        ORDER BY g.total DESC, g.mood ASC
                        LIMIT 1
                    ) AS top_mood,
                    COALESCE((
                        SELECT g.total
                        FROM grouped g
                        ORDER BY g.total DESC, g.mood ASC
                        LIMIT 1
                    ), 0) AS top_mood_count,
                    COALESCE((
                        SELECT JSON_AGG(
                            JSON_BUILD_OBJECT('mood', g.mood, 'count', g.total)
                            ORDER BY g.total DESC, g.mood ASC
                        )
                        FROM grouped g
                    ), '[]'::json) AS mood_counts
                FROM month_window mw
                CROSS JOIN totals t
                """,
                (month_start, effective_end, month_end, days_elapsed, user_id, month, year),
            )
            row = cur.fetchone() or {}
        conn.close()

        last_entry_at = row.get("last_entry_at")
        if hasattr(last_entry_at, "isoformat"):
            row["last_entry_at"] = last_entry_at.isoformat()
        return jsonify(row)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
