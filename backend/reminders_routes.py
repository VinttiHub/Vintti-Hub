# reminders_routes.py
import logging
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify
from psycopg2.extras import RealDictCursor
from db import get_connection   # ya lo tienes
import requests
import html
from typing import List, Optional, Dict, Any

bp = Blueprint("reminders", __name__)

BOGOTA_TZ = timezone(timedelta(hours=-5))
JAZ_EMAIL  = "jazmin@vintti.com"
LAR_EMAIL  = "lara@vintti.com"
AGUS_EMAIL = "agustin@vintti.com"
ANGIE_EMAIL = "angie@vintti.com"

def _serialize_reminder(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    for k in ("press_date", "last_jaz_sent_at", "last_lar_sent_at", "last_agus_sent_at"):
        v = row.get(k)
        if v is not None:
            try:
                row[k] = v.isoformat()
            except Exception:
                row[k] = str(v)
    return row

def _anchor(text, url):
    return f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(text)}</a>'

def _candidate_link(candidate_id:int):
    return f"https://vinttihub.vintti.com/candidate-details.html?id={candidate_id}"


def _send_email(subject: str, html_body: str, to: List[str]):
    payload = {"to": to, "subject": subject, "body": html_body}
    r = requests.post(
        "https://7m6mw95m8y.us-east-2.awsapprunner.com/send_email",
        json=payload,
        timeout=30
    )
    if not r.ok:
        logging.error("Send email failed: %s %s", r.status_code, r.text)
    return r.ok


def _fetch_hire_core(candidate_id:int, cur):
    # start_date, references_notes, setup_fee, salary, fee y opportunity_id (del hire en el que fue contratado)
    cur.execute("""
      SELECT h.start_date::date                            AS start_date,
             COALESCE(h.references_notes,'')               AS references_notes,
             COALESCE(h.setup_fee,0)                       AS setup_fee,
             COALESCE(h.employee_salary,0)                 AS salary,
             COALESCE(h.employee_fee,0)                    AS fee,
             ho.opportunity_id                             AS opportunity_id
        FROM hire h
        JOIN hire_opportunity ho ON ho.candidate_id = h.candidate_id
       WHERE h.candidate_id = %s
       ORDER BY h.start_date DESC NULLS LAST
       LIMIT 1
    """, (candidate_id,))
    return cur.fetchone()

def _fetch_client_email(opportunity_id:int, cur):
    # opportunity -> account_id -> account.mail
    cur.execute("""
      SELECT a.mail
        FROM opportunity o
        JOIN account a ON a.account_id = o.account_id
       WHERE o.opportunity_id = %s
       LIMIT 1
    """, (opportunity_id,))
    row = cur.fetchone()
    return (row or {}).get("mail") if row else None

def _initial_email_html(candidate_id:int, start_date, salary, fee, setup_fee, references, client_mail):
    link = _anchor("Open candidate in Vintti Hub", _candidate_link(candidate_id))
    return f"""
    <div style="font-family:Inter,Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.6">
      <p>Hey team — new <b>Close Win</b> 🎉</p>
      <ul>
        <li><b>Start date:</b> {html.escape(str(start_date or '—'))}</li>
        <li><b>Salary:</b> ${html.escape(f"{salary:,.0f}")}</li>
        <li><b>Fee:</b> ${html.escape(f"{fee:,.0f}")}</li>
        <li><b>Set up fee:</b> ${html.escape(f"{setup_fee:,.0f}")}</li>
        <li><b>Client email:</b> {html.escape(client_mail or '—')}</li>
      </ul>
      <p><b>References:</b><br>{references or '—'}</p>

      <p>Please complete your Close-Win tasks and then tick your checkbox in this page:<br>
        {link}
      </p>

      <p>Also, don’t forget to request the necessary <b>equipment</b> for the new hire if applicable. 💻🖥️</p>

      <p>Thanks! — Vintti Hub</p>
    </div>
    """

def _reminder_email_html(candidate_id:int):
    link = _anchor("Complete your checkbox here", _candidate_link(candidate_id))
    return f"""
    <div style="font-family:Inter,Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.6">
      <p>Quick reminder ⏰</p>
      <p>You still haven’t completed your checkbox for this Close-Win. When you finish your tasks, please mark it here:</p>
      <p>{link}</p>
      <p>Thank you! — Vintti Hub</p>
    </div>
    """
@bp.route("/candidates/<int:candidate_id>/hire_reminders/ensure", methods=["POST","GET"])
def ensure_reminder_row(candidate_id):
    """Crea una fila en hire_reminders si no existe todavía (por candidato).
       No envía correos. Deja press_date = NULL hasta que el usuario presione el botón."""
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # ¿Ya existe alguna fila para este candidato?
        cur.execute("""
            SELECT * FROM hire_reminders
             WHERE candidate_id = %s
             ORDER BY reminder_id DESC
             LIMIT 1
        """, (candidate_id,))
        row = cur.fetchone()
        if row:
            conn.commit()
            return jsonify({"row": _serialize_reminder(row), "created": False})

        # Necesitamos el opportunity_id en el que fue contratado
        cur.execute("""
            SELECT ho.opportunity_id
              FROM hire_opportunity ho
             WHERE ho.candidate_id = %s
             ORDER BY ho.opportunity_id DESC
             LIMIT 1
        """, (candidate_id,))
        ho = cur.fetchone()
        opportunity_id = ho["opportunity_id"] if ho else None
        if not opportunity_id:
            conn.commit()
            return jsonify({"error":"hire_opportunity not found for candidate"}), 404

        # Crea la fila con press_date = NULL y flags en FALSE
        cur.execute("""
            INSERT INTO hire_reminders (candidate_id, opportunity_id, press_date, jaz, lar, agus)
            VALUES (%s, %s, NULL, FALSE, FALSE, FALSE)
            RETURNING *
        """, (candidate_id, opportunity_id))
        row = cur.fetchone()
        conn.commit()
        return jsonify({"row": _serialize_reminder(row), "created": True})

@bp.route("/candidates/<int:candidate_id>/hire_reminders", methods=["GET"])
def get_latest_reminder(candidate_id):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT * FROM hire_reminders
             WHERE candidate_id = %s
             ORDER BY press_date DESC
             LIMIT 1
        """, (candidate_id,))
        row = cur.fetchone()
        return jsonify(_serialize_reminder(row) or {})

@bp.route("/candidates/<int:candidate_id>/hire_reminders/press", methods=["POST"])
def press_and_send(candidate_id):
    """Al presionar el botón: setea press_date=now() y envía el correo inicial.
       No crea filas nuevas: asume que ya existen (ensure en el load)."""
    data = request.get_json(silent=True) or {}

    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Tomamos la fila más reciente (la que creó el ensure)
        cur.execute("""
            SELECT * FROM hire_reminders
             WHERE candidate_id = %s
             ORDER BY reminder_id DESC
             LIMIT 1
        """, (candidate_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error":"hire_reminder row not found for candidate"}), 404

        reminder_id = row["reminder_id"]

        # Actualizamos press_date a ahora (TIMESTAMPTZ)
        cur.execute("""
            UPDATE hire_reminders
               SET press_date = now()
             WHERE reminder_id = %s
         RETURNING *
        """, (reminder_id,))
        row = cur.fetchone()

        # Datos para armar el correo
        hire = _fetch_hire_core(candidate_id, cur)
        if not hire:
            conn.commit()
            return jsonify({"row": _serialize_reminder(row), "email_sent": False, "warning":"hire not found for candidate"}), 404

        client_mail = _fetch_client_email(hire["opportunity_id"], cur) or ""
        html_body = _initial_email_html(
            candidate_id=candidate_id,
            start_date=hire.get("start_date"),
            salary=float(hire.get("salary") or 0),
            fee=float(hire.get("fee") or 0),
            setup_fee=float(hire.get("setup_fee") or 0),
            references=hire.get("references_notes") or "",
            client_mail=client_mail
        )

        ok = _send_email(
            subject="New Close-Win 🎉 — Action needed",
            html_body=html_body,
            to=[JAZ_EMAIL, LAR_EMAIL, AGUS_EMAIL, ANGIE_EMAIL]
        )

        conn.commit()
        return jsonify({"row": _serialize_reminder(row), "email_sent": bool(ok)})

@bp.route("/hire_reminders/<int:reminder_id>", methods=["PATCH"])
def update_checks(reminder_id):
    data = request.get_json() or {}
    fields = []
    vals = []
    for k in ("jaz","lar","agus"):
        if k in data:
            fields.append(f"{k} = %s")
            vals.append(bool(data[k]))
    if not fields:
        return jsonify({"error":"no fields to update"}), 400

    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        sql = f"UPDATE hire_reminders SET {', '.join(fields)} WHERE reminder_id = %s RETURNING *"
        vals.append(reminder_id)
        cur.execute(sql, tuple(vals))
        row = cur.fetchone()
        conn.commit()
        return jsonify(row or {})

def _should_send(now, press_date, last_sent_at):
    # primera vez: 24h desde press_date; siguientes: 24h desde last_sent_at
    base = last_sent_at or press_date
    return (now - base) >= timedelta(hours=24)

@bp.route("/reminders/due", methods=["POST"])
def send_due_reminders():
    """Idempotente para correr en un cron externo: envía recordatorios por cada persona con flag = false
       si han pasado 24h desde press_date o desde su último envío."""
    now = datetime.now(tz=BOGOTA_TZ)

    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
          SELECT *
            FROM hire_reminders
           WHERE (NOT jaz OR NOT lar OR NOT agus)
        """)
        rows = cur.fetchall() or []

        sent = []

        for r in rows:
            cid = r["candidate_id"]
            rid = r["reminder_id"]
            press = r["press_date"].astimezone(BOGOTA_TZ) if r["press_date"] else now

            # por persona
            plan = []
            if not r["jaz"] and _should_send(now, press, r["last_jaz_sent_at"]): plan.append(("jaz", JAZ_EMAIL))
            if not r["lar"] and _should_send(now, press, r["last_lar_sent_at"]): plan.append(("lar", LAR_EMAIL))
            if not r["agus"] and _should_send(now, press, r["last_agus_sent_at"]): plan.append(("agus", AGUS_EMAIL))

            if not plan:
                continue

            html_body = _reminder_email_html(cid)
            for key, email in plan:
                ok = _send_email(subject="Quick reminder — please tick your Close-Win checkbox",
                                 html_body=html_body, to=[email])
                if ok:
                    sent.append({"reminder_id": rid, "who": key, "to": email})
                    col = f"last_{key}_sent_at"
                    cur.execute(f"UPDATE hire_reminders SET {col} = now() WHERE reminder_id = %s", (rid,))

        conn.commit()
        return jsonify({"sent": sent})
