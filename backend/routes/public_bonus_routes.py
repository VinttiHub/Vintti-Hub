from flask import Blueprint, request, jsonify
from psycopg2.extras import RealDictCursor
from db import get_connection
from datetime import date

bp = Blueprint("public_bonus", __name__, url_prefix="/public/bonus_request")

def _safe_date(s):
    if not s: return None
    try:
        return date.fromisoformat(str(s)[:10])  # toma YYYY-MM-DD
    except Exception:
        return None

@bp.route("/submit", methods=["POST", "OPTIONS"])
def submit_bonus_request():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}

    account_id = data.get("account_id")
    
    if not account_id:
        return jsonify({"error": "account_id is required"}), 400

    candidate_id = data.get("candidate_id")
    employee_name_manual = (data.get("employee_name_manual") or "").strip()
    if not candidate_id and not employee_name_manual:
        return jsonify({"error": "candidate_id or employee_name_manual is required"}), 400

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
    "candidate_id": int(candidate_id) if candidate_id else None,
    "employee_name_manual": "" if candidate_id else employee_name_manual,
    "currency": data.get("currency"),
    "amount": data.get("amount"),
    "payout_date": data.get("payout_date"),
    "bonus_type": data.get("bonus_type"),
    "invoice_target": data.get("invoice_target"),
    "target_month": data.get("target_month") or None,
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
    except:
        amount = None

    currency = (data.get("currency") or "").upper()
    candidate_label = f"Candidate #{candidate_id}" if candidate_id else employee_name_manual
    account_id_int = int(account_id)

    cur.execute("""
        SELECT client_name
        FROM account
        WHERE account_id = %s
    """, (account_id_int,))

    acc_row = cur.fetchone()
    account_name = acc_row["client_name"] if acc_row and acc_row.get("client_name") else f"Account #{account_id_int}"


    TODO_OWNER_USER_ID = 1

    if payout_date:
        todo_desc = f"[AUTO:bonus_request:{bonus_request_id}] Pagar bono {currency} {amount} a {candidate_label} ({account_name})"

        cur.execute("""
        SELECT COALESCE(MAX(orden), 0) + 1 AS next_order
        FROM to_do
        WHERE user_id = %s
        """, (TODO_OWNER_USER_ID,))

        row_order = cur.fetchone()
        next_order = row_order["next_order"] if row_order and row_order.get("next_order") else 1


        cur.execute("""
        INSERT INTO to_do (user_id, description, due_date, "check", orden, subtask)
        VALUES (%s, %s, %s, false, %s, NULL)
        """, (TODO_OWNER_USER_ID, todo_desc, payout_date, next_order))

    conn.commit()
    cur.close(); conn.close()

    return jsonify({"ok": True, "bonus_request_id": bonus_request_id})



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

    # ✅ AJUSTA SQL a tus tablas reales
    cur.execute("""
    SELECT DISTINCT
        c.candidate_id,
        c.name AS full_name
    FROM hire_opportunity ho
    JOIN candidates c ON c.candidate_id = ho.candidate_id
    WHERE ho.account_id = %s
        AND ho.carga_inactive IS NULL
    ORDER BY c.name ASC
    """, (account_id,))
    rows = cur.fetchall()

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
