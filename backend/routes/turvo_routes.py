from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_connection
from utils.google_calendar import build_calendar_service


bp = Blueprint("turvo", __name__)

RECRUITER_EMAILS = [
    "paz@vintti.com",
    "constanza@vintti.com",
    "valentina@vintti.com",
    "pilar@vintti.com",
    "julieta@vintti.com",
    "pilar.fernandez@vintti.com",
]


def _normalize_dt(value: datetime | None) -> datetime | None:
    if not value:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_event_start(event: dict) -> datetime | None:
    start = event.get("start") or {}
    raw = start.get("dateTime") or start.get("date")
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _extract_opportunity_id(summary: str | None) -> int | None:
    if not summary:
        return None
    match = re.search(r"\bid\s*[:#-]?\s*(\d+)\b", summary, re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _get_tokens(conn, user_id: int) -> dict | None:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT user_id, access_token, refresh_token, token_expiry, scope, token_type
            FROM google_calendar_tokens
            WHERE user_id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def _upsert_tokens(conn, user_id: int, payload: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO google_calendar_tokens (
                user_id,
                access_token,
                refresh_token,
                token_expiry,
                scope,
                token_type,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                access_token = EXCLUDED.access_token,
                refresh_token = COALESCE(EXCLUDED.refresh_token, google_calendar_tokens.refresh_token),
                token_expiry = EXCLUDED.token_expiry,
                scope = EXCLUDED.scope,
                token_type = EXCLUDED.token_type,
                updated_at = NOW()
            """,
            (
                user_id,
                payload.get("access_token"),
                payload.get("refresh_token"),
                payload.get("token_expiry"),
                payload.get("scope"),
                payload.get("token_type"),
            ),
        )


def _fetch_events(service, start: datetime, end: datetime) -> list[dict]:
    events = []
    page_token = None
    while True:
        resp = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                pageToken=page_token,
                maxResults=2500,
            )
            .execute()
        )
        events.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return events


def _serialize_rows(rows: list[dict]) -> list[dict]:
    serialized = []
    for row in rows:
        item = dict(row)
        for key in ("meeting_date", "last_refresh_date"):
            value = item.get(key)
            if hasattr(value, "isoformat"):
                item[key] = value.isoformat()
        serialized.append(item)
    return serialized


@bp.route("/turvo", methods=["GET"])
def list_turvo_meetings():
    opportunity_id = request.args.get("opportunity_id")
    if not opportunity_id:
        return jsonify({"error": "opportunity_id is required"}), 400

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT turvo_id,
                       opportunity_id,
                       meeting_name,
                       hr_lead,
                       meeting_date,
                       candidates,
                       last_refresh_date
                FROM turvo
                WHERE opportunity_id = %s
                ORDER BY meeting_date DESC, turvo_id DESC
                """,
                (opportunity_id,),
            )
            rows = cur.fetchall() or []
        return jsonify(_serialize_rows(rows))
    finally:
        conn.close()


@bp.route("/turvo/refresh", methods=["POST"])
def refresh_turvo_meetings():
    payload = request.get_json(silent=True) or {}
    opportunity_id = payload.get("opportunity_id")
    if not opportunity_id:
        return jsonify({"error": "opportunity_id is required"}), 400

    try:
        opp_id = int(opportunity_id)
    except ValueError:
        return jsonify({"error": "opportunity_id must be numeric"}), 400

    now = datetime.now(timezone.utc)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(meeting_date) FROM turvo WHERE opportunity_id = %s",
                (opp_id,),
            )
            last_meeting = _normalize_dt(cur.fetchone()[0])
            start = last_meeting if last_meeting else now - timedelta(days=2)
            cur.execute(
                "UPDATE turvo SET last_refresh_date = %s WHERE opportunity_id = %s",
                (now, opp_id),
            )
        conn.commit()

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT user_id, LOWER(email_vintti) AS email
                FROM users
                WHERE LOWER(email_vintti) = ANY(%s)
                """,
                ([email.lower() for email in RECRUITER_EMAILS],),
            )
            recruiters = cur.fetchall() or []

        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(turvo_id), 0) FROM turvo")
            next_id = int(cur.fetchone()[0] or 0)

        for recruiter in recruiters:
            user_id = recruiter["user_id"]
            email = recruiter["email"]
            tokens = _get_tokens(conn, user_id)
            if not tokens:
                continue
            try:
                creds, service = build_calendar_service(tokens)
            except Exception:
                continue

            if creds and creds.token != tokens.get("access_token"):
                _upsert_tokens(
                    conn,
                    user_id,
                    {
                        "access_token": creds.token,
                        "refresh_token": creds.refresh_token,
                        "token_expiry": creds.expiry,
                        "scope": tokens.get("scope"),
                        "token_type": tokens.get("token_type"),
                    },
                )

            events = _fetch_events(service, start, now)
            for event in events:
                summary = (event.get("summary") or "").strip()
                if not summary:
                    continue
                if _extract_opportunity_id(summary) != opp_id:
                    continue
                meeting_date = _parse_event_start(event)
                if not meeting_date:
                    continue

                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT 1
                        FROM turvo
                        WHERE opportunity_id = %s
                          AND meeting_name = %s
                          AND hr_lead = %s
                          AND meeting_date = %s
                        """,
                        (opp_id, summary, email, meeting_date),
                    )
                    if cur.fetchone():
                        continue
                    next_id += 1
                    cur.execute(
                        """
                        INSERT INTO turvo (
                            turvo_id,
                            opportunity_id,
                            meeting_name,
                            hr_lead,
                            meeting_date,
                            candidates,
                            last_refresh_date
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (next_id, opp_id, summary, email, meeting_date, 0, now),
                    )

        conn.commit()

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT turvo_id,
                       opportunity_id,
                       meeting_name,
                       hr_lead,
                       meeting_date,
                       candidates,
                       last_refresh_date
                FROM turvo
                WHERE opportunity_id = %s
                ORDER BY meeting_date DESC, turvo_id DESC
                """,
                (opp_id,),
            )
            rows = cur.fetchall() or []

        return jsonify({"rows": _serialize_rows(rows), "last_refresh_date": now.isoformat()})
    finally:
        conn.close()


@bp.route("/turvo/<int:turvo_id>/candidates", methods=["PATCH"])
def update_turvo_candidates(turvo_id: int):
    payload = request.get_json(silent=True) or {}
    candidates = payload.get("candidates")
    if candidates is None:
        return jsonify({"error": "candidates is required"}), 400

    try:
        candidates_value = int(candidates)
    except (TypeError, ValueError):
        return jsonify({"error": "candidates must be numeric"}), 400

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE turvo
                SET candidates = %s
                WHERE turvo_id = %s
                """,
                (candidates_value, turvo_id),
            )
            if cur.rowcount == 0:
                return jsonify({"error": "turvo_id not found"}), 404
        conn.commit()
        return jsonify({"success": True, "turvo_id": turvo_id, "candidates": candidates_value})
    finally:
        conn.close()
