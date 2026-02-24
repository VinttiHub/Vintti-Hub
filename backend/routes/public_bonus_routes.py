from flask import Blueprint, request, jsonify
from psycopg2.extras import RealDictCursor
from db import get_connection
from datetime import date
import logging
import os
import re
from html import escape
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email

bp = Blueprint("public_bonus", __name__, url_prefix="/public/bonus_request")

BONUS_EMAIL_FALLBACK_RECIPIENTS = ["agustin@vintti.com", "lara@vintti.com", "pgonzales@vintti.com"]
BONUS_EMAIL_RECIPIENT_USER_IDS = [1, 2, 12]

def _safe_date(s):
    if not s: return None
    try:
        return date.fromisoformat(str(s)[:10])  # toma YYYY-MM-DD
    except Exception:
        return None

def _safe_target_month(s):
    if not s:
        return None
    raw = str(s).strip()
    try:
        if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", raw):
            return date.fromisoformat(f"{raw}-01")
        return date.fromisoformat(raw[:10])
    except Exception:
        return None

def _send_bonus_request_email(
    to_emails: list[str],
    bonus_request_id: int,
    account_name: str,
    candidate_label: str,
    currency: str,
    amount,
    payout_date,
    approver_name: str,
    reason: str,
):
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        raise RuntimeError("SENDGRID_API_KEY not configured")
    if not to_emails:
        raise RuntimeError("No bonus email recipients configured")

    amount_num = float(amount) if amount not in (None, "") else 0.0
    amount_text = f"{currency} {amount_num:,.2f}".strip()
    payout_text = payout_date.isoformat() if hasattr(payout_date, "isoformat") else (str(payout_date or "N/A"))
    subject = f"Bonus Request #{bonus_request_id} | {candidate_label} | {account_name}"

    html_body = f"""
    <p>Hi team,</p>
    <p>A new bonus request was submitted and is pending review.</p>
    <ul>
      <li><strong>Bonus request ID:</strong> {bonus_request_id}</li>
      <li><strong>Account:</strong> {escape(account_name or "N/A")}</li>
      <li><strong>Candidate / Employee:</strong> {escape(candidate_label or "N/A")}</li>
      <li><strong>Amount:</strong> {escape(amount_text)}</li>
      <li><strong>Payout date:</strong> {escape(payout_text)}</li>
      <li><strong>Approved by:</strong> {escape(approver_name or "N/A")}</li>
      <li><strong>Reason:</strong> {escape(reason or "N/A")}</li>
    </ul>
    <p>This request was also created in ToDo automatically.</p>
    <p>— Vintti HUB</p>
    """

    msg = Mail(
        from_email=Email("hub@vintti-hub.com", name="Vintti HUB"),
        to_emails=to_emails,
        subject=subject,
        html_content=html_body,
    )
    sg = SendGridAPIClient(api_key)
    sg.send(msg)


def _resolve_bonus_email_recipients(cur) -> list[str]:
    recipients = []
    seen = set()

    for user_id in BONUS_EMAIL_RECIPIENT_USER_IDS:
        try:
            cur.execute(
                """
                SELECT LOWER(TRIM(email_vintti)) AS email
                FROM users
                WHERE user_id = %s
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone() or {}
            email = (row.get("email") or "").strip().lower()
            if email and email not in seen:
                seen.add(email)
                recipients.append(email)
        except Exception:
            logging.exception("Failed resolving bonus email recipient for user_id=%s", user_id)

    for email in BONUS_EMAIL_FALLBACK_RECIPIENTS:
        clean = str(email or "").strip().lower()
        if clean and clean not in seen:
            seen.add(clean)
            recipients.append(clean)

    return recipients

@bp.route("/submit", methods=["POST", "OPTIONS"])
def submit_bonus_request():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}

    token = request.args.get("t") or data.get("t")
    account_id = data.get("account_id")

    if not account_id and token:
        link = _get_valid_link(token)
        if not link:
            return jsonify({"error": "invalid token"}), 403
        account_id = link["account_id"]

    if not account_id:
        return jsonify({"error": "account_id or token is required"}), 400

    employee_name_manual = (data.get("employee_name_manual") or "").strip()
    raw_candidate_id = data.get("candidate_id")
    candidate_id = None
    if raw_candidate_id not in (None, "", "__other__"):
        try:
            candidate_id = int(raw_candidate_id)
        except (TypeError, ValueError):
            return jsonify({"error": "candidate_id must be a valid integer"}), 400

    if not candidate_id and not employee_name_manual:
        return jsonify({"error": "candidate_id or employee_name_manual is required"}), 400

    invoice_target = (data.get("invoice_target") or "next_invoice").strip() or "next_invoice"
    if invoice_target not in ("next_invoice", "specific_month"):
        invoice_target = "next_invoice"

    target_month = _safe_target_month(data.get("target_month"))
    if invoice_target == "specific_month":
        if not target_month:
            return jsonify({"error": "target_month must use YYYY-MM or YYYY-MM-DD format"}), 400
    else:
        target_month = None

    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
    INSERT INTO bonus_requests (
        account_id,
        candidate_id,
        employee_name_manual,
        currency,
        amount,
        payout_date,
        bonus_type,
        invoice_target,
        target_month,
        reason,
        approver_name,
        priority,
        notes,
        status,
        created_at,
        updated_at
    )
    VALUES (
        %(account_id)s,
        %(candidate_id)s,
        %(employee_name_manual)s,
        %(currency)s,
        %(amount)s,
        %(payout_date)s,
        %(bonus_type)s,
        %(invoice_target)s,
        %(target_month)s,
        %(reason)s,
        %(approver_name)s,
        %(priority)s,
        %(notes)s,
        'pending',
        NOW(),
        NOW()
    )
    RETURNING bonus_request_id
    """, {
    "account_id": int(account_id),
    "candidate_id": candidate_id,
    "employee_name_manual": "" if candidate_id else employee_name_manual,
    "currency": data.get("currency"),
    "amount": data.get("amount"),
    "payout_date": data.get("payout_date"),
    "bonus_type": data.get("bonus_type"),
    "invoice_target": invoice_target,
    "target_month": target_month,
    "reason": data.get("reason"),
    "approver_name": data.get("approver_name"),
    "priority": data.get("priority") or "normal",
    "notes": data.get("notes") or "",
    })

        row = cur.fetchone()  # ✅ AQUÍ MISMO, antes de otro execute
        bonus_request_id = row["bonus_request_id"]

        # --- Crear To-Do basado en payout_date ---
        payout_date = _safe_date(data.get("payout_date"))
        amount = data.get("amount")
        try:
            amount = float(amount) if amount not in (None, "") else None
        except Exception:
            amount = None

        currency = (data.get("currency") or "").upper()
        candidate_label = employee_name_manual
        cur.execute(
            """
            SELECT
              br.candidate_id,
              br.employee_name_manual,
              c.name AS candidate_name
            FROM bonus_requests br
            LEFT JOIN candidates c
              ON c.candidate_id = br.candidate_id
            WHERE br.bonus_request_id = %s
            LIMIT 1
            """,
            (bonus_request_id,),
        )
        br_row = cur.fetchone() or {}
        if br_row.get("candidate_name"):
            candidate_label = br_row["candidate_name"]
        elif br_row.get("employee_name_manual"):
            candidate_label = br_row["employee_name_manual"]
        elif candidate_id:
            candidate_label = f"Candidate #{candidate_id}"
        account_id_int = int(account_id)

        cur.execute("""
        SELECT client_name
        FROM account
        WHERE account_id = %s
    """, (account_id_int,))

        acc_row = cur.fetchone()
        account_name = acc_row["client_name"] if acc_row and acc_row.get("client_name") else f"Account #{account_id_int}"
        bonus_email_recipients = _resolve_bonus_email_recipients(cur)


        TODO_OWNER_USER_IDS = [1, 2]

        if payout_date:
            auto_marker = f"[AUTO:bonus_request:{bonus_request_id}]"
            todo_desc = f"{auto_marker} Pagar bono {currency} {amount} a {candidate_label} ({account_name})"

            for owner_user_id in TODO_OWNER_USER_IDS:
                cur.execute(
                    """
                    SELECT to_do_id
                    FROM to_do
                    WHERE user_id = %s
                      AND description LIKE %s
                    LIMIT 1
                    """,
                    (owner_user_id, f"{auto_marker}%"),
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        """
                        UPDATE to_do
                        SET description = %s,
                            due_date = %s
                        WHERE to_do_id = %s
                        """,
                        (todo_desc, payout_date, existing["to_do_id"]),
                    )
                    continue

                cur.execute("""
            SELECT COALESCE(MAX(orden), 0) + 1 AS next_order
            FROM to_do
            WHERE user_id = %s
            """, (owner_user_id,))

                row_order = cur.fetchone()
                next_order = row_order["next_order"] if row_order and row_order.get("next_order") else 1

                cur.execute("""
            INSERT INTO to_do (user_id, description, due_date, "check", orden, subtask)
            VALUES (%s, %s, %s, false, %s, NULL)
            """, (owner_user_id, todo_desc, payout_date, next_order))

        conn.commit()

        email_warning = None
        try:
            _send_bonus_request_email(
                to_emails=bonus_email_recipients,
                bonus_request_id=bonus_request_id,
                account_name=account_name,
                candidate_label=candidate_label,
                currency=currency,
                amount=amount,
                payout_date=payout_date,
                approver_name=data.get("approver_name"),
                reason=data.get("reason"),
            )
        except Exception as email_exc:
            logging.exception("bonus request email failed")
            email_warning = str(email_exc)

        payload = {"ok": True, "bonus_request_id": bonus_request_id}
        if email_warning:
            payload["email_warning"] = email_warning
        return jsonify(payload)
    except Exception as exc:
        if conn:
            conn.rollback()
        return jsonify({"error": str(exc)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()



@bp.route("/account/<int:account_id>", methods=["GET"])
def list_bonus_requests_for_account(account_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
    SELECT
        br.bonus_request_id,
        br.account_id,
        a.client_name AS account_name,
        br.candidate_id,
        c.name AS candidate_name,
        br.employee_name_manual,
        br.amount,
        br.currency,
        br.invoice_target,
        br.target_month,
        br.status,
        br.approver_name,
        br.payout_date::text AS payout_date,
        br.created_at::date::text AS created_date
    FROM bonus_requests br
    LEFT JOIN candidates c
        ON c.candidate_id = br.candidate_id
    JOIN account a
        ON a.account_id = br.account_id
    WHERE br.account_id = %s
    ORDER BY br.created_at DESC
    """, (account_id,))


    rows = cur.fetchall()
    cur.close(); conn.close()

    return jsonify({"items": rows})

def _get_valid_link(token: str):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
      SELECT token, account_id, expires_at, revoked
      FROM public_links
      WHERE token = %s AND purpose = 'bonus_request'
      LIMIT 1
    """, (token,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row or row["revoked"]:
        return None
    return row

@bp.route("/context", methods=["GET"])
def public_context():
    token = request.args.get("t")
    account_id = request.args.get("account_id", type=int)

    # 1) si viene token, usamos account_id desde public_links (más seguro)
    if token:
        link = _get_valid_link(token)
        if not link:
            return jsonify({"error": "invalid token"}), 403
        account_id = link["account_id"]

    # 2) si no viene token, exigimos account_id
    if not account_id:
        return jsonify({"error": "missing account_id or token"}), 400

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Activos para el selector del bonus:
    # - hires activos (hire_opportunity)
    # - buyouts activos (tabla buyouts)
    # Dedupe por candidate_id para no repetir personas.
    cur.execute("""
    WITH hire_rows AS (
      SELECT
        ho.candidate_id,
        c.name AS full_name,
        CASE
          WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
          WHEN NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '') IS NOT NULL
            THEN NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '')::date
          ELSE NULL
        END AS start_d,
        CASE
          WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
          WHEN NULLIF(TRIM(CAST(ho.end_date AS TEXT)), '') IS NOT NULL
            THEN NULLIF(TRIM(CAST(ho.end_date AS TEXT)), '')::date
          ELSE NULL
        END AS end_d
      FROM hire_opportunity ho
      JOIN candidates c ON c.candidate_id = ho.candidate_id
      WHERE ho.account_id = %s
        AND ho.candidate_id IS NOT NULL
    ),
    buyout_rows AS (
      SELECT
        b.candidate_id,
        COALESCE(c.name, CONCAT('Candidate #', b.candidate_id::text)) AS full_name,
        CASE
          WHEN NULLIF(TRIM(CAST(b.start_date AS TEXT)), '') IS NOT NULL
            THEN NULLIF(TRIM(CAST(b.start_date AS TEXT)), '')::date
          ELSE NULL
        END AS start_d,
        CASE
          WHEN NULLIF(TRIM(CAST(b.end_date AS TEXT)), '') IS NOT NULL
            THEN NULLIF(TRIM(CAST(b.end_date AS TEXT)), '')::date
          ELSE NULL
        END AS end_d
      FROM buyouts b
      LEFT JOIN candidates c ON c.candidate_id = b.candidate_id
      WHERE b.account_id = %s
        AND b.candidate_id IS NOT NULL
    ),
    active_rows AS (
      SELECT candidate_id, full_name
      FROM hire_rows
      WHERE (start_d IS NULL OR start_d <= CURRENT_DATE)
        AND (end_d IS NULL OR end_d >= CURRENT_DATE)
      UNION
      SELECT candidate_id, full_name
      FROM buyout_rows
      WHERE (start_d IS NULL OR start_d <= CURRENT_DATE)
        AND (end_d IS NULL OR end_d >= CURRENT_DATE)
    )
    SELECT
      candidate_id,
      MIN(full_name) AS full_name
    FROM active_rows
    GROUP BY candidate_id
    ORDER BY LOWER(MIN(full_name)) ASC
    """, (account_id, account_id))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify({
        "account_id": account_id,
        "candidates": [
            {"candidate_id": r["candidate_id"], "full_name": r["full_name"], "status": "active"}
            for r in rows
        ]
    })


@bp.route("/<int:bonus_request_id>", methods=["PATCH", "OPTIONS"])
def update_bonus_request(bonus_request_id):
    if request.method == "OPTIONS":
        return ("", 204)

    payload = request.get_json(silent=True) or {}
    status = (payload.get("status") or "").strip().lower()
    if status not in ("pending", "approved", "rejected", "paid"):
        return jsonify({"error": "Invalid status"}), 400

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
      UPDATE bonus_requests
      SET status = %s
      WHERE bonus_request_id = %s
      RETURNING bonus_request_id, status
    """, (status, bonus_request_id))
    row = cur.fetchone()
    conn.commit()
    cur.close(); conn.close()

    if not row:
        return jsonify({"error": "Not found"}), 404

    return jsonify(row)
