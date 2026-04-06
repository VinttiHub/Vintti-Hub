import html
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
from psycopg2.extras import RealDictCursor

BOGOTA_TZ = timezone(timedelta(hours=-5))
TEAM_EMAILS = [
    # "agustin@vintti.com",
    # "lara@vintti.com",
    "pgonzales@vintti.com",
]


def _dedupe_emails(values: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        email = str(value or "").strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        out.append(email)
    return out


def _send_email(subject: str, html_body: str, to: List[str]) -> bool:
    payload = {"to": _dedupe_emails(to), "subject": subject, "body": html_body}
    response = requests.post(
        "https://7m6mw95m8y.us-east-2.awsapprunner.com/send_email",
        json=payload,
        timeout=30,
    )
    if not response.ok:
        logging.error("Credit Loop email failed: %s %s", response.status_code, response.text)
    return response.ok


def is_close_win(value: Any) -> bool:
    return str(value or "").strip().lower() == "close win"


def add_months(base_date: date, months: int) -> date:
    month_index = (base_date.month - 1) + months
    year = base_date.year + month_index // 12
    month = month_index % 12 + 1
    month_lengths = [31, 29 if _is_leap_year(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(base_date.day, month_lengths[month - 1])
    return date(year, month, day)


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def ensure_credit_loop_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS account_credit_loop (
            credit_id BIGSERIAL PRIMARY KEY,
            account_id BIGINT NOT NULL,
            source_opportunity_id BIGINT NOT NULL,
            source_position_name TEXT,
            earned_date DATE NOT NULL,
            expires_at DATE NOT NULL,
            status TEXT NOT NULL DEFAULT 'available'
                CHECK (status IN ('available', 'used', 'expired', 'reversed')),
            used_by_opportunity_id BIGINT,
            used_at TIMESTAMPTZ,
            notes TEXT,
            last_reminder_month4_at TIMESTAMPTZ,
            last_reminder_month5_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_account_credit_loop_source_opp
            ON account_credit_loop (source_opportunity_id)
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_account_credit_loop_account_status
            ON account_credit_loop (account_id, status, expires_at)
        """
    )


def expire_due_credits(cur, *, today: Optional[date] = None) -> int:
    ensure_credit_loop_table(cur)
    today = today or date.today()
    cur.execute(
        """
        UPDATE account_credit_loop
           SET status = 'expired',
               updated_at = now()
         WHERE status = 'available'
           AND expires_at < %s
        """,
        (today,),
    )
    return cur.rowcount or 0


def _fetch_credit_context(cur, opportunity_id: int) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT
            o.opportunity_id,
            o.account_id,
            o.opp_stage,
            o.opp_position_name,
            o.opp_close_date::date AS opp_close_date,
            a.client_name
        FROM opportunity o
        LEFT JOIN account a ON a.account_id = o.account_id
        WHERE o.opportunity_id = %s
        LIMIT 1
        """,
        (opportunity_id,),
    )
    return cur.fetchone()


def get_available_credit_summary(
    cur,
    account_id: int,
    *,
    today: Optional[date] = None,
    exclude_source_opportunity_id: Optional[int] = None,
) -> Dict[str, Any]:
    ensure_credit_loop_table(cur)
    expire_due_credits(cur, today=today)
    today = today or date.today()

    params: List[Any] = [account_id]
    extra_sql = ""
    if exclude_source_opportunity_id is not None:
        extra_sql = "AND source_opportunity_id <> %s"
        params.append(exclude_source_opportunity_id)

    cur.execute(
        f"""
        SELECT
            COUNT(*)::int AS available_credits,
            MIN(expires_at) AS next_expiration
        FROM account_credit_loop
        WHERE account_id = %s
          AND status = 'available'
          {extra_sql}
        """,
        tuple(params),
    )
    row = cur.fetchone() or {}
    next_expiration = row.get("next_expiration")
    days_left = None
    months_left = None
    if next_expiration:
        days_left = max((next_expiration - today).days, 0)
        months_left = max(((next_expiration.year - today.year) * 12) + (next_expiration.month - today.month), 0)
    return {
        "available_credits": int(row.get("available_credits") or 0),
        "next_expiration": next_expiration,
        "days_left": days_left,
        "months_left": months_left,
    }


def create_credit_for_close_win(cur, opportunity_id: int) -> Dict[str, Any]:
    ensure_credit_loop_table(cur)
    ctx = _fetch_credit_context(cur, opportunity_id)
    if not ctx:
        return {"created": False, "reason": "opportunity_not_found", "opportunity_id": opportunity_id}
    if not is_close_win(ctx.get("opp_stage")):
        return {"created": False, "reason": "stage_not_close_win", "opportunity_id": opportunity_id}

    earned_date = ctx.get("opp_close_date") or date.today()
    expires_at = add_months(earned_date, 6)

    cur.execute(
        """
        INSERT INTO account_credit_loop (
            account_id,
            source_opportunity_id,
            source_position_name,
            earned_date,
            expires_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, now())
        ON CONFLICT (source_opportunity_id)
        DO UPDATE SET
            account_id = EXCLUDED.account_id,
            source_position_name = EXCLUDED.source_position_name,
            earned_date = EXCLUDED.earned_date,
            expires_at = EXCLUDED.expires_at,
            updated_at = now()
        RETURNING credit_id, account_id, source_opportunity_id, earned_date, expires_at, status
        """,
        (
            ctx["account_id"],
            opportunity_id,
            ctx.get("opp_position_name"),
            earned_date,
            expires_at,
        ),
    )
    row = cur.fetchone() or {}
    return {
        "created": True,
        "credit_id": row.get("credit_id"),
        "account_id": row.get("account_id"),
        "source_opportunity_id": row.get("source_opportunity_id"),
        "earned_date": row.get("earned_date"),
        "expires_at": row.get("expires_at"),
        "status": row.get("status"),
    }


def maybe_send_credit_available_email(cur, opportunity_id: int) -> Dict[str, Any]:
    ensure_credit_loop_table(cur)
    ctx = _fetch_credit_context(cur, opportunity_id)
    if not ctx:
        return {"sent": False, "reason": "opportunity_not_found", "opportunity_id": opportunity_id}

    account_id = ctx.get("account_id")
    if not account_id:
        return {"sent": False, "reason": "missing_account", "opportunity_id": opportunity_id}

    summary = get_available_credit_summary(cur, account_id, exclude_source_opportunity_id=opportunity_id)
    available_credits = summary["available_credits"]
    if available_credits <= 0:
        return {"sent": False, "reason": "no_available_credits", "opportunity_id": opportunity_id}

    months_left = summary.get("months_left")
    months_text = "less than 1 month"
    if months_left is not None:
        months_text = f"{max(months_left, 1)} month{'s' if max(months_left, 1) != 1 else ''}"

    subject = f"Credit Loop available: {ctx.get('client_name') or 'Client'} has {available_credits} credit{'s' if available_credits != 1 else ''}"
    html_body = f"""
    <div style="font-family:Inter, Arial, sans-serif; font-size:14px; color:#222; line-height:1.5;">
      <p>Hey team, this account already has <b>Credit Loop</b> credits available.</p>
      <p>
        <b>Client:</b> {html.escape(str(ctx.get('client_name') or 'Client'))}<br>
        <b>Opportunity:</b> {html.escape(str(ctx.get('opp_position_name') or 'Role'))}<br>
        <b>Available credits:</b> {available_credits}<br>
        <b>Next expiration:</b> {html.escape(str(summary.get('next_expiration') or '—'))}<br>
        <b>Estimated time left:</b> {html.escape(months_text)}
      </p>
      <p>Please review the account's Credit Loop tab before invoicing or closing the discount decision.</p>
      <p style="margin-top:16px">— Vintti HUB</p>
    </div>
    """.strip()

    ok = _send_email(subject=subject, html_body=html_body, to=TEAM_EMAILS)
    return {
        "sent": bool(ok),
        "reason": "sent" if ok else "send_failed",
        "opportunity_id": opportunity_id,
        "available_credits": available_credits,
    }


def list_account_credits(cur, account_id: int) -> Dict[str, Any]:
    ensure_credit_loop_table(cur)
    expire_due_credits(cur)
    cur.execute(
        """
        SELECT
            acl.credit_id,
            acl.account_id,
            acl.source_opportunity_id,
            acl.source_position_name,
            acl.earned_date,
            acl.expires_at,
            acl.status,
            acl.used_by_opportunity_id,
            acl.used_at,
            acl.notes,
            acl.last_reminder_month4_at,
            acl.last_reminder_month5_at,
            src.opp_position_name AS source_opportunity_name,
            used.opp_position_name AS used_by_opportunity_name
        FROM account_credit_loop acl
        LEFT JOIN opportunity src ON src.opportunity_id = acl.source_opportunity_id
        LEFT JOIN opportunity used ON used.opportunity_id = acl.used_by_opportunity_id
        WHERE acl.account_id = %s
        ORDER BY acl.earned_date DESC, acl.credit_id DESC
        """,
        (account_id,),
    )
    rows = cur.fetchall() or []
    today = date.today()
    normalized_rows = []
    for row in rows:
        expires_at = row.get("expires_at")
        days_left = (expires_at - today).days if expires_at else None
        normalized_rows.append(
            {
                **row,
                "days_left": max(days_left, 0) if days_left is not None else None,
                "is_expired": bool(expires_at and expires_at < today),
            }
        )

    return {
        "summary": get_available_credit_summary(cur, account_id, today=today),
        "items": normalized_rows,
    }


def update_credit_status(
    cur,
    account_id: int,
    credit_id: int,
    *,
    action: str,
    used_by_opportunity_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    ensure_credit_loop_table(cur)
    expire_due_credits(cur)
    cur.execute(
        """
        SELECT credit_id, account_id, status
        FROM account_credit_loop
        WHERE credit_id = %s AND account_id = %s
        LIMIT 1
        """,
        (credit_id, account_id),
    )
    current = cur.fetchone()
    if not current:
        raise ValueError("Credit not found")

    normalized_action = str(action or "").strip().lower()
    if normalized_action == "use":
        if current.get("status") != "available":
            raise ValueError("Only available credits can be marked as used")
        cur.execute(
            """
            UPDATE account_credit_loop
               SET status = 'used',
                   used_by_opportunity_id = %s,
                   used_at = now(),
                   notes = %s,
                   updated_at = now()
             WHERE credit_id = %s
             RETURNING *
            """,
            (used_by_opportunity_id, notes, credit_id),
        )
        return cur.fetchone() or {}

    if normalized_action == "restore":
        if current.get("status") not in {"used", "reversed"}:
            raise ValueError("Only used or reversed credits can be restored")
        cur.execute(
            """
            UPDATE account_credit_loop
               SET status = 'available',
                   used_by_opportunity_id = NULL,
                   used_at = NULL,
                   notes = %s,
                   updated_at = now()
             WHERE credit_id = %s
             RETURNING *
            """,
            (notes, credit_id),
        )
        return cur.fetchone() or {}

    if normalized_action == "reverse":
        if current.get("status") == "used":
            raise ValueError("Used credits cannot be reversed")
        cur.execute(
            """
            UPDATE account_credit_loop
               SET status = 'reversed',
                   used_by_opportunity_id = NULL,
                   used_at = NULL,
                   notes = %s,
                   updated_at = now()
             WHERE credit_id = %s
             RETURNING *
            """,
            (notes, credit_id),
        )
        return cur.fetchone() or {}

    raise ValueError("Unsupported credit action")


def run_due_credit_loop_reminders(cur, *, today: Optional[date] = None) -> List[Dict[str, Any]]:
    ensure_credit_loop_table(cur)
    today = today or date.today()
    expire_due_credits(cur, today=today)
    cur.execute(
        """
        SELECT
            acl.credit_id,
            acl.account_id,
            acl.source_position_name,
            acl.earned_date,
            acl.expires_at,
            acl.last_reminder_month4_at,
            acl.last_reminder_month5_at,
            a.client_name
        FROM account_credit_loop acl
        LEFT JOIN account a ON a.account_id = acl.account_id
        WHERE acl.status = 'available'
        ORDER BY acl.account_id, acl.earned_date ASC
        """
    )
    rows = cur.fetchall() or []

    grouped: Dict[tuple, Dict[str, Any]] = defaultdict(lambda: {"credits": [], "months_left": None, "account_id": None, "client_name": ""})

    for row in rows:
        earned_date = row.get("earned_date")
        if not earned_date:
            continue
        month4_due = add_months(earned_date, 4) <= today and row.get("last_reminder_month4_at") is None and today < add_months(earned_date, 5)
        month5_due = add_months(earned_date, 5) <= today and row.get("last_reminder_month5_at") is None and today <= row.get("expires_at")

        reminder_month = None
        months_left = None
        if month4_due:
            reminder_month = 4
            months_left = 2
        elif month5_due:
            reminder_month = 5
            months_left = 1

        if reminder_month is None:
            continue

        key = (row["account_id"], reminder_month)
        grouped[key]["credits"].append(row)
        grouped[key]["months_left"] = months_left
        grouped[key]["account_id"] = row["account_id"]
        grouped[key]["client_name"] = row.get("client_name") or "Client"

    sent: List[Dict[str, Any]] = []
    for (account_id, reminder_month), payload in grouped.items():
        summary = get_available_credit_summary(cur, account_id, today=today)
        available_credits = summary["available_credits"]
        months_left = payload["months_left"] or 0
        credit_lines = "".join(
            f"<li>{html.escape(str(item.get('source_position_name') or f'Opportunity #{item.get('credit_id')}'))} — expires {html.escape(str(item.get('expires_at') or '—'))}</li>"
            for item in payload["credits"]
        )
        subject = (
            f"Credit Loop reminder: {payload['client_name']} has {available_credits} credit"
            f"{'s' if available_credits != 1 else ''} left"
        )
        body = f"""
        <div style="font-family:Inter, Arial, sans-serif; font-size:14px; color:#222; line-height:1.5;">
          <p>Reminder: this client still has <b>{available_credits} Credit Loop credit{'s' if available_credits != 1 else ''}</b> available.</p>
          <p>
            <b>Client:</b> {html.escape(str(payload['client_name']))}<br>
            <b>Months left:</b> {months_left}<br>
            <b>Reminder window:</b> Month {reminder_month}
          </p>
          <p>Credits nearing expiration:</p>
          <ul>{credit_lines}</ul>
          <p>Please review whether these credits should be used before they expire.</p>
          <p style="margin-top:16px">— Vintti HUB</p>
        </div>
        """.strip()
        if not _send_email(subject=subject, html_body=body, to=TEAM_EMAILS):
            continue

        credit_ids = [int(item["credit_id"]) for item in payload["credits"]]
        column = "last_reminder_month4_at" if reminder_month == 4 else "last_reminder_month5_at"
        cur.execute(
            f"""
            UPDATE account_credit_loop
               SET {column} = now(),
                   updated_at = now()
             WHERE credit_id = ANY(%s)
            """,
            (credit_ids,),
        )
        sent.append(
            {
                "account_id": account_id,
                "client_name": payload["client_name"],
                "available_credits": available_credits,
                "months_left": months_left,
                "reminder_month": reminder_month,
                "credit_ids": credit_ids,
            }
        )

    return sent
