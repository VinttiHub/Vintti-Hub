from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, redirect, request
from psycopg2.extras import RealDictCursor

from db import get_connection
from utils.google_calendar import (
    build_auth_url,
    build_calendar_service,
    exchange_code_for_tokens,
    new_state_token,
    token_expiry_from_seconds,
)

bp = Blueprint("google_calendar", __name__)


def _insert_oauth_state(user_id: int, state: str, redirect_to: str | None) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO google_calendar_oauth_states (state, user_id, redirect_to, expires_at)
                VALUES (%s, %s, %s, NOW() + INTERVAL '15 minutes')
                """,
                (state, user_id, redirect_to),
            )
        conn.commit()
    finally:
        conn.close()


def _consume_oauth_state(state: str) -> dict | None:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT state, user_id, redirect_to, expires_at
                FROM google_calendar_oauth_states
                WHERE state = %s
                  AND expires_at > NOW()
                """,
                (state,),
            )
            row = cur.fetchone()
            cur.execute("DELETE FROM google_calendar_oauth_states WHERE state = %s", (state,))
        conn.commit()
        return dict(row) if row else None
    finally:
        conn.close()


def _upsert_tokens(user_id: int, payload: dict) -> None:
    conn = get_connection()
    try:
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
        conn.commit()
    finally:
        conn.close()


def _get_tokens(user_id: int) -> dict | None:
    conn = get_connection()
    try:
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
    finally:
        conn.close()


def _delete_tokens(user_id: int) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM google_calendar_tokens WHERE user_id = %s", (user_id,))
        conn.commit()
    finally:
        conn.close()


def _parse_date(date_str: str | None, tz: ZoneInfo) -> datetime:
    if date_str:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    return datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)


@bp.route("/google-calendar/auth-url", methods=["POST"])
def google_calendar_auth_url():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400

    redirect_to = data.get("redirect_to")
    state = new_state_token()
    _insert_oauth_state(int(user_id), state, redirect_to)
    auth_url = build_auth_url(state)
    return jsonify({"auth_url": auth_url})


@bp.route("/google-calendar/callback")
def google_calendar_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    if not code or not state:
        return jsonify({"error": "Missing code or state"}), 400

    state_row = _consume_oauth_state(state)
    if not state_row:
        return jsonify({"error": "Invalid or expired state"}), 400

    try:
        token_payload = exchange_code_for_tokens(code)
    except Exception as exc:
        return jsonify({"error": f"Token exchange failed: {exc}"}), 400

    expiry = token_expiry_from_seconds(token_payload.get("expires_in"))
    _upsert_tokens(
        state_row["user_id"],
        {
            "access_token": token_payload.get("access_token"),
            "refresh_token": token_payload.get("refresh_token"),
            "token_expiry": expiry,
            "scope": token_payload.get("scope"),
            "token_type": token_payload.get("token_type"),
        },
    )

    target = state_row.get("redirect_to") or "https://vinttihub.vintti.com/calendar.html?connected=1"
    return redirect(target)


@bp.route("/google-calendar/status")
def google_calendar_status():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400

    tokens = _get_tokens(int(user_id))
    return jsonify(
        {
            "connected": bool(tokens),
            "token_expiry": tokens.get("token_expiry").isoformat() if tokens and tokens.get("token_expiry") else None,
        },
    )


@bp.route("/google-calendar/disconnect", methods=["POST"])
def google_calendar_disconnect():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400

    _delete_tokens(int(user_id))
    return jsonify({"success": True})


@bp.route("/google-calendar/events", methods=["GET", "POST"])
def google_calendar_events():
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
    else:
        payload = request.args or {}

    user_id = payload.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400

    tokens = _get_tokens(int(user_id))
    if not tokens:
        return jsonify({"error": "Calendar not connected"}), 404

    try:
        creds, service = build_calendar_service(tokens)
    except Exception as exc:
        return jsonify({"error": f"Failed to build calendar service: {exc}"}), 400

    if creds and creds.token != tokens.get("access_token"):
        _upsert_tokens(
            int(user_id),
            {
                "access_token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_expiry": creds.expiry,
                "scope": tokens.get("scope"),
                "token_type": tokens.get("token_type"),
            },
        )

    if request.method == "POST":
        summary = payload.get("summary")
        start_raw = payload.get("start")
        end_raw = payload.get("end")
        timezone_name = payload.get("timezone") or "UTC"
        if not summary or not start_raw or not end_raw:
            return jsonify({"error": "summary, start, and end are required"}), 400

        try:
            tzinfo = ZoneInfo(timezone_name)
        except Exception:
            return jsonify({"error": f"Invalid timezone: {timezone_name}"}), 400

        try:
            start_dt = datetime.fromisoformat(start_raw).replace(tzinfo=tzinfo)
            end_dt = datetime.fromisoformat(end_raw).replace(tzinfo=tzinfo)
        except ValueError:
            return jsonify({"error": "start/end must be ISO format (YYYY-MM-DDTHH:MM)"}), 400

        event = {
            "summary": summary,
            "location": payload.get("location"),
            "description": payload.get("description"),
            "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone_name},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone_name},
        }

        attendees = payload.get("attendees") or []
        if attendees:
            event["attendees"] = [{"email": email} for email in attendees if email]

        if payload.get("create_meet"):
            event["conferenceData"] = {
                "createRequest": {
                    "requestId": new_state_token(),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }

        created = (
            service.events()
            .insert(calendarId="primary", body=event, conferenceDataVersion=1)
            .execute()
        )
        return jsonify(created)

    timezone_name = payload.get("timezone") or "UTC"
    try:
        tzinfo = ZoneInfo(timezone_name)
    except Exception:
        return jsonify({"error": f"Invalid timezone: {timezone_name}"}), 400

    day_start = _parse_date(payload.get("date"), tzinfo)
    day_end = day_start + timedelta(days=1)

    events = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    items = []
    for item in events.get("items", []):
        items.append(
            {
                "id": item.get("id"),
                "summary": item.get("summary"),
                "start": item.get("start"),
                "end": item.get("end"),
                "location": item.get("location"),
                "description": item.get("description"),
                "htmlLink": item.get("htmlLink"),
                "hangoutLink": item.get("hangoutLink"),
                "conferenceData": item.get("conferenceData"),
            },
        )

    return jsonify({"date": day_start.date().isoformat(), "events": items})
