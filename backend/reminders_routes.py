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


def _fetch_opportunity_type(opportunity_id: int, cur) -> str:
    """
    Intenta detectar el tipo de oportunidad.
    Devuelve 'recruiting', 'staffing' o 'unknown' (cae a 'staffing' después).
    """
    cur.execute("""
        SELECT
          COALESCE(o.opp_model) AS raw_type
        FROM opportunity o
        WHERE o.opportunity_id = %s
        LIMIT 1
    """, (opportunity_id,))
    row = cur.fetchone() or {}
    raw = (row.get("raw_type") or "").strip().lower()

    if raw in {"recruiting", "Recruiting"}:
        return "recruiting"
    if raw in {"staffing", "Staffing"}:
        return "staffing"
    return "unknown"


def _format_money(n) -> str:
    try:
        return f"{float(n or 0):,.0f}"
    except Exception:
        return "0"


# ===============================
# Plantillas de correo
# ===============================

def _initial_email_html_staffing(  # NEW (misma copia que tu plantilla actual)
    candidate_id:int, start_date, salary, fee, setup_fee, references, client_mail,
    candidate_name:str, client_name:str, opp_position_name:str
):
    link = _anchor("Open candidate in Vintti Hub", _candidate_link(candidate_id))
    return f"""
    <div style="font-family:Inter,Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.6">
      <p>Hey team — new <b>Close-Win</b> 🎉</p>
      <p>We’ve just closed <b>{html.escape(client_name or 'Client')}</b>’s <b>{html.escape(opp_position_name or 'role')}</b> with
         <b>{html.escape(candidate_name or 'the candidate')}</b>.</p>

      <ul>
        <li><b>Start date:</b> {html.escape(str(start_date or '—'))}</li>
        <li><b>Salary:</b> ${html.escape(_format_money(salary))}</li>
        <li><b>Fee:</b> ${html.escape(_format_money(fee))}</li>
        <li><b>Set-up fee:</b> ${html.escape(_format_money(setup_fee))}</li>
        <li><b>Client email:</b> {html.escape(client_mail or '—')}</li>
      </ul>

      <p><b>References / notes:</b><br>{references or '—'}</p>

      <p>Please complete your Close-Win tasks and then tick your checkbox on this page:<br>
        {link}
      </p>

      <p>Also, don’t forget to request any <b>equipment</b> needed for the new hire. 💻🖥️</p>

      <p>Thanks! — Vintti Hub</p>
    </div>
    """


def _initial_email_html_recruiting(  
    candidate_id:int, start_date, salary, revenue, references, client_mail,
    candidate_name:str, client_name:str, opp_position_name:str
):
    link = _anchor("Open candidate in Vintti Hub", _candidate_link(candidate_id))
    return f"""
    <div style="font-family:Inter,Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.6">
      <p>Hey team — new <b>Close-Win</b> 🎉</p>

      <p>We’ve just closed <b>{html.escape(client_name or 'Client')}</b>’s <b>{html.escape(opp_position_name or 'role')}</b> with
         <b>{html.escape(candidate_name or 'the candidate')}</b>.</p>

      <p><b>Start date:</b> {html.escape(str(start_date or '—'))}<br>
         <b>Salary:</b> ${html.escape(_format_money(salary))}<br>
         <b>Revenue :</b> ${html.escape(_format_money(revenue))}<br>
         <b>Client email:</b> {html.escape(client_mail or '—')}<br>
         <b>References / notes:</b> {references or '—'}
      </p>

      <p>—</p>

      <p>Please complete your Close-Win tasks and then tick your checkbox on this page:<br>
        {link}
      </p>

      <p>Also, don’t forget to request any equipment needed for the new hire. 💻🖥️</p>

      <p>Thanks! — Vintti Hub</p>
    </div>
    """

# ===============================
# Cambios en press_and_send
# ===============================
@bp.route("/candidates/<int:candidate_id>/hire_reminders/press", methods=["POST"])
def press_and_send(candidate_id):
    data = request.get_json(silent=True) or {}

    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # igual que antes ...
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

        cur.execute("""
            UPDATE hire_reminders
               SET press_date = now()
             WHERE reminder_id = %s
         RETURNING *
        """, (reminder_id,))
        row = cur.fetchone()

        # Datos
        hire = _fetch_hire_core(candidate_id, cur)
        if not hire:
            conn.commit()
            return jsonify({"row": _serialize_reminder(row), "email_sent": False, "warning":"hire not found for candidate"}), 404

        opportunity_id = hire["opportunity_id"]
        ctx = _fetch_email_context(candidate_id, opportunity_id, cur)
        candidate_name    = ctx.get("candidate_name") or ""
        client_name       = ctx.get("client_name") or ""
        opp_position_name = ctx.get("opp_position_name") or ""
        client_mail       = ctx.get("client_mail") or (_fetch_client_email(opportunity_id, cur) or "")

        # Detectar tipo de opp
        opp_type = _fetch_opportunity_type(opportunity_id, cur)  # NEW
        if opp_type == "unknown":
            opp_type = "staffing"  # fallback conservador

        # Elegir plantilla
        if opp_type == "recruiting":
            html_body = _initial_email_html_recruiting(
                candidate_id=candidate_id,
                start_date=hire.get("start_date"),
                salary=hire.get("salary"),
                revenue=hire.get("revenue"),  # ← antes decía hire.get("fee")
                references=hire.get("references_notes") or "",
                client_mail=client_mail,
                candidate_name=candidate_name,
                client_name=client_name,
                opp_position_name=opp_position_name
            )
        else:
            html_body = _initial_email_html_staffing(
                candidate_id=candidate_id,
                start_date=hire.get("start_date"),
                salary=hire.get("salary"),
                fee=hire.get("fee"),
                setup_fee=hire.get("setup_fee"),
                references=hire.get("references_notes") or "",
                client_mail=client_mail,
                candidate_name=candidate_name,
                client_name=client_name,
                opp_position_name=opp_position_name
            )


        to_list = [JAZ_EMAIL, LAR_EMAIL, AGUS_EMAIL, ANGIE_EMAIL]

        ok = _send_email(
            subject="New Close-Win 🎉 — Action needed",
            html_body=html_body,
            to=to_list
        )

        conn.commit()
        return jsonify({
            "row": _serialize_reminder(row),
            "email_sent": bool(ok),
            "opp_model": opp_type  # útil para debug en el front
        })

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


def _fetch_hire_core(candidate_id: int, cur):
    """
    Devuelve los datos del hire más reciente para el candidato desde hire_opportunity.
    Campos esperados por el correo:
      start_date, references_notes, setup_fee, salary, fee, revenue, opportunity_id
    """
    cur.execute("""
        SELECT
            ho.start_date::date                           AS start_date,
            COALESCE(ho.references_notes, '')             AS references_notes,
            COALESCE(ho.setup_fee, 0)                     AS setup_fee,
            COALESCE(ho.salary, 0)                        AS salary,
            COALESCE(ho.fee, 0)                           AS fee,       -- usado por staffing
            COALESCE(ho.revenue, 0)                       AS revenue,   -- usado por recruiting
            ho.opportunity_id                             AS opportunity_id
        FROM hire_opportunity ho
        WHERE ho.candidate_id = %s
        ORDER BY ho.start_date DESC NULLS LAST, ho.opportunity_id DESC
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

def _fetch_email_context(candidate_id:int, opportunity_id:int, cur):
    """
    Devuelve:
      - candidate_name      (candidates.name)
      - client_name         (account.client_name)
      - client_mail         (account.mail)
      - opp_position_name   (opportunity.opp_position_name)
    """
    cur.execute("""
        SELECT
            c.name                         AS candidate_name,
            a.client_name                  AS client_name,
            a.mail                         AS client_mail,
            o.opp_position_name            AS opp_position_name
        FROM opportunity o
        JOIN account a   ON a.account_id = o.account_id
        JOIN candidates c ON c.candidate_id = %s
       WHERE o.opportunity_id = %s
       LIMIT 1
    """, (candidate_id, opportunity_id))
    return cur.fetchone() or {}

def _initial_email_html(candidate_id:int, start_date, salary, fee, setup_fee, references, client_mail,
                        candidate_name:str, client_name:str, opp_position_name:str):
    link = _anchor("Open candidate in Vintti Hub", _candidate_link(candidate_id))
    # Copys en inglés, tono casual/fluido
    return f"""
    <div style="font-family:Inter,Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.6">
      <p>Hey team — new <b>Close-Win</b> 🎉</p>
      <p>We’ve just closed <b>{html.escape(client_name or 'Client')}</b>’s <b>{html.escape(opp_position_name or 'role')}</b> with
         <b>{html.escape(candidate_name or 'the candidate')}</b>.</p>

      <ul>
        <li><b>Start date:</b> {html.escape(str(start_date or '—'))}</li>
        <li><b>Salary:</b> ${html.escape(f"{salary:,.0f}")}</li>
        <li><b>Fee:</b> ${html.escape(f"{fee:,.0f}")}</li>
        <li><b>Set-up fee:</b> ${html.escape(f"{setup_fee:,.0f}")}</li>
        <li><b>Client email:</b> {html.escape(client_mail or '—')}</li>
      </ul>

      <p><b>References / notes:</b><br>{references or '—'}</p>

      <p>Please complete your Close-Win tasks and then tick your checkbox on this page:<br>
        {link}
      </p>

      <p>Also, don’t forget to request any <b>equipment</b> needed for the new hire. 💻🖥️</p>

      <p>Thanks! — Vintti Hub</p>
    </div>
    """

def _reminder_email_html(candidate_id:int, candidate_name:str, client_name:str, opp_position_name:str):
    link = _anchor("Complete your checkbox here", _candidate_link(candidate_id))
    return f"""
    <div style="font-family:Inter,Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.6">
      <p>Quick reminder ⏰</p>
      <p>You still haven’t checked your box for this Close-Win:
         <b>{html.escape(client_name or 'Client')}</b> — <b>{html.escape(opp_position_name or 'role')}</b>
         with <b>{html.escape(candidate_name or 'the candidate')}</b>.</p>
      <p>When you’re done, please mark it here:<br>{link}</p>
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
            opportunity_id = r.get("opportunity_id")
            ctx = _fetch_email_context(cid, opportunity_id, cur) if opportunity_id else {}
            candidate_name    = ctx.get("candidate_name") or ""
            client_name       = ctx.get("client_name") or ""
            opp_position_name = ctx.get("opp_position_name") or ""

            # por persona
            plan = []
            if not r["jaz"] and _should_send(now, press, r["last_jaz_sent_at"]): plan.append(("jaz", JAZ_EMAIL))
            if not r["lar"] and _should_send(now, press, r["last_lar_sent_at"]): plan.append(("lar", LAR_EMAIL))
            if not r["agus"] and _should_send(now, press, r["last_agus_sent_at"]): plan.append(("agus", AGUS_EMAIL))

            if not plan:
                continue

            html_body = _reminder_email_html(
                candidate_id=cid,
                candidate_name=candidate_name,
                client_name=client_name,
                opp_position_name=opp_position_name
            )

            for key, email in plan:
                ok = _send_email(subject="Quick reminder — please tick your Close-Win checkbox",
                                 html_body=html_body, to=[email])
                if ok:
                    sent.append({"reminder_id": rid, "who": key, "to": email})
                    col = f"last_{key}_sent_at"
                    cur.execute(f"UPDATE hire_reminders SET {col} = now() WHERE reminder_id = %s", (rid,))

        conn.commit()
        return jsonify({"sent": sent})
