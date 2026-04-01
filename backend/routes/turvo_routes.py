from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import re

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_connection
from utils.google_calendar import build_calendar_service


bp = Blueprint("turvo", __name__)
logger = logging.getLogger(__name__)

RECRUITER_EMAILS = [
    "paz@vintti.com",
    "constanza@vintti.com",
    "valentina@vintti.com",
    "pilar@vintti.com",
    "julieta@vintti.com",
    "pilar.fernandez@vintti.com",
]

INITIAL_SYNC_LOOKBACK_DAYS = 90
REFRESH_OVERLAP_MINUTES = 5


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
    patterns = (
        r"\bid\s*[:#-]?\s*(\d+)\b",
        r"\bopportunity\s*[:#-]?\s*(\d+)\b",
        r"\bopp\s*[:#-]?\s*(\d+)\b",
        r"\bjob\s*[:#-]?\s*(\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, summary, re.IGNORECASE)
        if not match:
            continue
        try:
            return int(match.group(1))
        except ValueError:
            continue
    return None


def _event_matches_opportunity(event: dict, opp_id: int) -> bool:
    for field in ("summary", "description"):
        raw_value = event.get(field)
        if not raw_value:
            continue
        extracted = _extract_opportunity_id(str(raw_value))
        if extracted == opp_id:
            return True
        # Fallback: accept the exact opportunity id as a standalone token.
        if re.search(rf"(?<!\d){opp_id}(?!\d)", str(raw_value)):
            return True
    return False


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


def _get_opportunity_hr_lead(conn, opportunity_id: int) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT LOWER(COALESCE(opp_hr_lead, ''))
            FROM opportunity
            WHERE opportunity_id = %s
            """,
            (opportunity_id,),
        )
        row = cur.fetchone()
    return (row[0] or "").strip().lower() if row else ""


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


def _extract_event_owner_email(event: dict, recruiter_emails: set[str]) -> str:
    candidates = [
        ((event.get("organizer") or {}).get("email") or "").strip().lower(),
        ((event.get("creator") or {}).get("email") or "").strip().lower(),
    ]
    for email in candidates:
        if email and email in recruiter_emails:
            return email
    return ""


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
                WITH ranked AS (
                    SELECT t.turvo_id,
                           t.opportunity_id,
                           t.meeting_name,
                           t.hr_lead,
                           t.meeting_date,
                           t.candidates,
                           t.last_refresh_date,
                           ROW_NUMBER() OVER (
                               PARTITION BY t.opportunity_id, t.meeting_name, t.meeting_date
                               ORDER BY
                                   CASE
                                       WHEN LOWER(t.hr_lead) = LOWER(COALESCE(o.opp_hr_lead, '')) THEN 0
                                       ELSE 1
                                   END,
                                   t.turvo_id DESC
                           ) AS rn
                    FROM turvo t
                    LEFT JOIN opportunity o
                      ON o.opportunity_id = t.opportunity_id
                    WHERE t.opportunity_id = %s
                )
                SELECT turvo_id,
                       opportunity_id,
                       meeting_name,
                       hr_lead,
                       meeting_date,
                       candidates,
                       last_refresh_date
                FROM ranked
                WHERE rn = 1
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
        opportunity_hr_lead = _get_opportunity_hr_lead(conn, opp_id)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(meeting_date) FROM turvo WHERE opportunity_id = %s",
                (opp_id,),
            )
            last_meeting = _normalize_dt(cur.fetchone()[0])
            if last_meeting:
                start = last_meeting - timedelta(minutes=REFRESH_OVERLAP_MINUTES)
            else:
                start = now - timedelta(days=INITIAL_SYNC_LOOKBACK_DAYS)
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
        recruiter_email_set = {str(item["email"]).strip().lower() for item in recruiters if item.get("email")}

        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(turvo_id), 0) FROM turvo")
            next_id = int(cur.fetchone()[0] or 0)

        stats = {
            "recruiters_found": len(recruiters),
            "recruiters_with_tokens": 0,
            "events_scanned": 0,
            "events_matched": 0,
            "inserted": 0,
            "duplicates": 0,
            "reassigned": 0,
            "deleted_duplicates": 0,
        }

        for recruiter in recruiters:
            user_id = recruiter["user_id"]
            email = recruiter["email"]
            tokens = _get_tokens(conn, user_id)
            if not tokens:
                logger.info("Turvo refresh skipping recruiter without tokens: opp_id=%s email=%s", opp_id, email)
                continue
            stats["recruiters_with_tokens"] += 1
            try:
                creds, service = build_calendar_service(tokens)
            except Exception:
                logger.exception("Turvo refresh failed to build calendar service: opp_id=%s email=%s", opp_id, email)
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
            stats["events_scanned"] += len(events)
            for event in events:
                summary = (event.get("summary") or "").strip()
                if not summary:
                    continue
                if not _event_matches_opportunity(event, opp_id):
                    continue
                stats["events_matched"] += 1
                meeting_date = _parse_event_start(event)
                if not meeting_date:
                    continue
                event_owner_email = _extract_event_owner_email(event, recruiter_email_set)
                canonical_hr_lead = opportunity_hr_lead or event_owner_email or email

                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM turvo
                        WHERE opportunity_id = %s
                          AND meeting_name = %s
                          AND meeting_date = %s
                          AND hr_lead <> %s
                        """,
                        (opp_id, summary, meeting_date, canonical_hr_lead),
                    )
                    stats["deleted_duplicates"] += cur.rowcount or 0

                    cur.execute(
                        """
                        SELECT turvo_id, hr_lead
                        FROM turvo
                        WHERE opportunity_id = %s
                          AND meeting_name = %s
                          AND meeting_date = %s
                        """,
                        (opp_id, summary, meeting_date),
                    )
                    existing = cur.fetchone()
                    if existing and existing[1] == canonical_hr_lead:
                        stats["duplicates"] += 1
                        continue
                    if existing:
                        cur.execute(
                            """
                            UPDATE turvo
                            SET hr_lead = %s,
                                last_refresh_date = %s
                            WHERE turvo_id = %s
                            """,
                            (canonical_hr_lead, now, existing[0]),
                        )
                        stats["reassigned"] += 1
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
                        (next_id, opp_id, summary, canonical_hr_lead, meeting_date, 0, now),
                    )
                    stats["inserted"] += 1

        conn.commit()

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                WITH ranked AS (
                    SELECT t.turvo_id,
                           t.opportunity_id,
                           t.meeting_name,
                           t.hr_lead,
                           t.meeting_date,
                           t.candidates,
                           t.last_refresh_date,
                           ROW_NUMBER() OVER (
                               PARTITION BY t.opportunity_id, t.meeting_name, t.meeting_date
                               ORDER BY
                                   CASE
                                       WHEN LOWER(t.hr_lead) = LOWER(COALESCE(o.opp_hr_lead, '')) THEN 0
                                       ELSE 1
                                   END,
                                   t.turvo_id DESC
                           ) AS rn
                    FROM turvo t
                    LEFT JOIN opportunity o
                      ON o.opportunity_id = t.opportunity_id
                    WHERE t.opportunity_id = %s
                )
                SELECT turvo_id,
                       opportunity_id,
                       meeting_name,
                       hr_lead,
                       meeting_date,
                       candidates,
                       last_refresh_date
                FROM ranked
                WHERE rn = 1
                ORDER BY meeting_date DESC, turvo_id DESC
                """,
                (opp_id,),
            )
            rows = cur.fetchall() or []

        return jsonify(
            {
                "rows": _serialize_rows(rows),
                "last_refresh_date": now.isoformat(),
                "stats": stats,
                "window_start": start.isoformat(),
                "window_end": now.isoformat(),
            }
        )
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
