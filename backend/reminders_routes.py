# reminders_routes.py
import logging
import re
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify
from psycopg2.extras import RealDictCursor
from db import get_connection   # ya lo tienes
from utils.credit_loop import run_due_credit_loop_reminders
from utils.hr_lead_todo import run_scheduled_todos
import requests
import html
from typing import List, Optional, Dict, Any

bp = Blueprint("reminders", __name__)

BOGOTA_TZ = timezone(timedelta(hours=-5))
JAZ_EMAIL  = "jazmin@vintti.com"
LAR_EMAIL  = "lara@vintti.com"
AGUS_EMAIL = "agustin@vintti.com"
# LUCIA_EMAIL = "lucia@vintti.com"  # Hire reminders desactivado: solo Jazmin y Lara.
ANGIE_EMAIL = "angie@vintti.com"
PGONZALES_EMAIL = "pgonzales@vintti.com"


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


def _format_computer_need(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"

    text = str(value).strip()
    if not text:
        return "—"

    low = text.lower()
    if low in {"1", "true", "t", "yes", "y", "si", "sí"}:
        return "Yes"
    if low in {"0", "false", "f", "no", "n"}:
        return "No"
    return text


def _format_price_type(value) -> str:
    if value is None:
        return "—"

    text = str(value).strip()
    if not text:
        return "—"

    low = text.lower()
    if low == "close":
        return "Close"
    if low == "transparent":
        return "Transparent"
    return text


def _has_reference_details(reference_details: Optional[Dict[str, Any]]) -> bool:
    if not reference_details:
        return False
    return any(str(reference_details.get(key) or "").strip() for key in (
        "reference_1_name", "reference_1_phone", "reference_1_email", "reference_1_linkedin",
        "reference_2_name", "reference_2_phone", "reference_2_email", "reference_2_linkedin",
    ))


def _reference_linkedin_html(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    safe_text = html.escape(text)
    if re.match(r"^https?://", text, flags=re.IGNORECASE):
        return f'<a href="{safe_text}" target="_blank" rel="noopener noreferrer">{safe_text}</a>'
    return safe_text


def _reference_details_html(reference_details: Optional[Dict[str, Any]]) -> str:
    if not _has_reference_details(reference_details):
        return ""

    cards = []
    for idx in (1, 2):
        prefix = f"reference_{idx}"
        values = {
            "Name": str(reference_details.get(f"{prefix}_name") or "").strip(),
            "Phone": str(reference_details.get(f"{prefix}_phone") or "").strip(),
            "Email": str(reference_details.get(f"{prefix}_email") or "").strip(),
            "LinkedIn": str(reference_details.get(f"{prefix}_linkedin") or "").strip(),
        }
        if not any(values.values()):
            continue
        cards.append(f"""
          <div style="margin:10px 0">
            <div style="font-weight:600">Reference {idx}</div>
            <ul style="margin:6px 0 0 18px;padding:0">
              <li><b>Name:</b> {html.escape(values["Name"]) if values["Name"] else "—"}</li>
              <li><b>Phone:</b> {html.escape(values["Phone"]) if values["Phone"] else "—"}</li>
              <li><b>Email:</b> {html.escape(values["Email"]) if values["Email"] else "—"}</li>
              <li><b>LinkedIn:</b> {_reference_linkedin_html(values["LinkedIn"])}</li>
            </ul>
          </div>
        """)
    return "".join(cards)


def _strip_structured_reference_notes(references: Optional[str]) -> Optional[str]:
    if not references:
        return references
    return re.sub(
        r'<div\b[^>]*data-structured-references=["\']true["\'][^>]*>.*?</div>',
        '',
        str(references),
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()


def _references_card_html(references: Optional[str], reference_details: Optional[Dict[str, Any]] = None) -> str:
    """Render References / notes inside a simple card to improve readability."""
    has_reference_details = _has_reference_details(reference_details)
    safe_body = _format_references_block(
        _strip_structured_reference_notes(references) if has_reference_details else references
    )
    details_html = _reference_details_html(reference_details)
    notes_html = ""
    if safe_body != "—":
        notes_html = f"""
          <div style="margin-top:12px">
            <div style="font-weight:600">Notes</div>
            <div style="margin-top:6px">{safe_body}</div>
          </div>
        """
    body = details_html + notes_html if details_html or notes_html else "—"

    return f"""
      <div style="margin:16px 0;padding:12px 16px;border:1px solid #dfe5f2;border-radius:10px;background:#f6f8fc">
        <div style="font-weight:600;margin-bottom:6px">References</div>
        <div style="white-space:normal">{body}</div>
      </div>
    """


def _format_references_block(references: Optional[str]) -> str:
    """
    Converts stored HTML-ish references into safe inline HTML without raw tags.
    Keeps simple line breaks to avoid rendering literal <div>...</div>.
    """
    if not references:
        return "—"

    raw = html.unescape(str(references))
    raw = re.sub(r'<\s*br\s*/?>', '\n', raw, flags=re.IGNORECASE)
    raw = re.sub(r'<\s*/?\s*(div|p|li|ul|ol)[^>]*>', '\n', raw, flags=re.IGNORECASE)
    raw = re.sub(r'<[^>]+>', '', raw)  # drop any remaining tags
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r'\n{3,}', '\n\n', raw)
    raw = raw.strip()
    if not raw:
        return "—"

    escaped = html.escape(raw)
    escaped = escaped.replace("\n\n", "<br><br>").replace("\n", "<br>")
    return escaped


# ===============================
# Plantillas de correo
# ===============================

def _initial_email_html_staffing(  # NEW (misma copia que tu plantilla actual)
    candidate_id:int, start_date, salary, fee, setup_fee, references, client_mail,
    candidate_name:str, client_name:str, opp_position_name:str,
    price_type=None,
    computer=None,
    referal_source: Optional[str] = None,
    lead_source: Optional[str] = None,
    credit_loop=None,
    reference_details: Optional[Dict[str, Any]] = None
):
    link = _anchor("Open candidate in Vintti Hub", _candidate_link(candidate_id))
    referral_value = html.escape(referal_source) if referal_source else "—"
    referral_html = f'<li><b>Referral source:</b> {referral_value}</li>'
    lead_value = html.escape(lead_source) if lead_source else "—"
    lead_source_html = f'<li><b>Lead source:</b> {lead_value}</li>'
    notes_card = _references_card_html(references, reference_details)
    credit_loop = credit_loop or {}
    credit_applied = bool(credit_loop.get("applied_discount_amount"))
    fee_html = (
        f"""
        <li><b>Fee:</b> ${html.escape(_format_money(fee))}</li>
        """
        if not credit_applied else
        ""
    )
    credit_loop_html = (
        f"""
        <li><b>Credit Loop applied:</b> Yes</li>
        <li><b>Previous fee:</b> ${html.escape(_format_money(credit_loop.get('applied_original_value')))}</li>
        <li><b>Credit Loop discount:</b> ${html.escape(_format_money(credit_loop.get('applied_discount_amount')))}</li>
        <li><b>New fee:</b> ${html.escape(_format_money(credit_loop.get('applied_adjusted_value')))}</li>
        """
        if credit_applied else
        "<li><b>Credit Loop applied:</b> No</li>"
    )
    return f"""
    <div style="font-family:Inter,Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.6">
      <p>Hey team — new <b>Signed</b> 🎉</p>
      <p>We’ve just closed <b>{html.escape(client_name or 'Client')}</b>’s <b>{html.escape(opp_position_name or 'role')}</b> with
         <b>{html.escape(candidate_name or 'the candidate')}</b>.</p>

      <ul>
        <li><b>Start date:</b> {html.escape(str(start_date or '—'))}</li>
        <li><b>Salary:</b> ${html.escape(_format_money(salary))}</li>
        {fee_html}
        {credit_loop_html}
        <li><b>Set-up fee:</b> ${html.escape(_format_money(setup_fee))}</li>
        <li><b>Price type:</b> {html.escape(_format_price_type(price_type))}</li>
        <li><b>Needs computer:</b> {html.escape(_format_computer_need(computer))}</li>
        <li><b>Client email:</b> {html.escape(client_mail or '—')}</li>
        {referral_html}
        {lead_source_html}
      </ul>

      {notes_card}

      <p>Please complete your Signed tasks and then tick your checkbox on this page:<br>
        {link}
      </p>

      <p>Also, don’t forget to request any <b>equipment</b> needed for the new hire. 💻🖥️</p>

      <p>Thanks! — Vintti Hub</p>
    </div>
    """


def _initial_email_html_recruiting(  
    candidate_id:int, start_date, salary, revenue, references, client_mail,
    candidate_name:str, client_name:str, opp_position_name:str,
    price_type=None,
    computer=None,
    referal_source: Optional[str] = None,
    lead_source: Optional[str] = None,
    credit_loop=None,
    reference_details: Optional[Dict[str, Any]] = None
):
    link = _anchor("Open candidate in Vintti Hub", _candidate_link(candidate_id))
    referral_value = html.escape(referal_source) if referal_source else "—"
    lead_value = html.escape(lead_source) if lead_source else "—"
    referral_line = f"<b>Referral source:</b> {referral_value}<br>"
    lead_source_line = f"<b>Lead source:</b> {lead_value}<br>"
    notes_card = _references_card_html(references, reference_details)
    credit_loop = credit_loop or {}
    credit_applied = bool(credit_loop.get("applied_discount_amount"))
    credit_loop_lines = (
        f"""
         <b>Credit Loop applied:</b> Yes<br>
         <b>Previous revenue:</b> ${html.escape(_format_money(credit_loop.get('applied_original_value')))}<br>
         <b>Credit Loop discount:</b> ${html.escape(_format_money(credit_loop.get('applied_discount_amount')))}<br>
         <b>New revenue:</b> ${html.escape(_format_money(credit_loop.get('applied_adjusted_value')))}<br>
        """
        if credit_applied else
        "<b>Credit Loop applied:</b> No<br>"
    )
    return f"""
    <div style="font-family:Inter,Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.6">
      <p>Hey team — new <b>Signed</b> 🎉</p>

      <p>We’ve just closed <b>{html.escape(client_name or 'Client')}</b>’s <b>{html.escape(opp_position_name or 'role')}</b> with
         <b>{html.escape(candidate_name or 'the candidate')}</b>.</p>

      <p><b>Start date:</b> {html.escape(str(start_date or '—'))}<br>
         <b>Salary:</b> ${html.escape(_format_money(salary))}<br>
         <b>Revenue :</b> ${html.escape(_format_money(revenue))}<br>
         {credit_loop_lines}
         <b>Price type:</b> {html.escape(_format_price_type(price_type))}<br>
         <b>Needs computer:</b> {html.escape(_format_computer_need(computer))}<br>
         <b>Client email:</b> {html.escape(client_mail or '—')}<br>
         {referral_line}
         {lead_source_line}
      </p>

      {notes_card}

      <p>—</p>

      <p>Please complete your Signed tasks and then tick your checkbox on this page:<br>
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
        credit_loop = _fetch_credit_loop_application(opportunity_id, cur)
        candidate_name    = ctx.get("candidate_name") or ""
        client_name       = ctx.get("client_name") or ""
        opp_position_name = ctx.get("opp_position_name") or ""
        client_mail       = ctx.get("client_mail") or (_fetch_client_email(opportunity_id, cur) or "")
        referal_source    = ctx.get("referal_source") or ""
        lead_source       = ctx.get("where_come_from") or ""

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
                revenue=hire.get("revenue"),
                references=hire.get("references_notes") or "",
                client_mail=client_mail,
                candidate_name=candidate_name,
                client_name=client_name,
                opp_position_name=opp_position_name,
                price_type=hire.get("price_type"),
                computer=hire.get("computer"),
                referal_source=referal_source,
                lead_source=lead_source,
                credit_loop=credit_loop,
                reference_details=hire
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
                opp_position_name=opp_position_name,
                price_type=hire.get("price_type"),
                computer=hire.get("computer"),
                referal_source=referal_source,
                lead_source=lead_source,
                credit_loop=credit_loop,
                reference_details=hire
            )


        to_list = [JAZ_EMAIL, LAR_EMAIL, PGONZALES_EMAIL]  # hire reminders activos
        # Lucia desactivada para hire reminders.
        # to_list = [JAZ_EMAIL, LAR_EMAIL, LUCIA_EMAIL, PGONZALES_EMAIL]

        # Nuevo subject dinámico
        subject = f"🎉 Signed: {client_name or 'Client'} — {opp_position_name or 'Role'}"

        # O si quieres un formato más limpio y consistente
        # subject = f"New Close-Win 🎉 | {client_name} — {opp_position_name}"

        # Limitar longitud para evitar subjects demasiado largos
        if len(subject) > 120:
            subject = subject[:117] + "..."

        ok = _send_email(
            subject=subject,
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


def _is_stage_close_win(value) -> bool:
    return str(value or "").strip().lower() == "close win"


def _close_win_email_html(client_name: str, candidate_name: str, start_date, price_type=None, computer=None) -> str:
    return f"""
<div style="font-family:Inter, Arial, sans-serif; font-size:14px; color:#222; line-height:1.5;">
  <p>Hey team — new <b>Close Win</b> 🎉</p>
  <p>
    <b>Client:</b> {html.escape(str(client_name or 'Client'))}<br>
    <b>Candidate:</b> {html.escape(str(candidate_name or 'the candidate'))}<br>
    <b>Start date:</b> {html.escape(str(start_date or '—'))}<br>
    <b>Price type:</b> {html.escape(_format_price_type(price_type))}<br>
    <b>Computer:</b> {html.escape(_format_computer_need(computer))}
  </p>
  <p style="margin-top:16px">— Vintti HUB</p>
</div>
    """.strip()


def _fetch_close_win_context(cur, opportunity_id: int) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT
            o.opportunity_id,
            o.opp_stage,
            o.opp_position_name,
            o.opp_close_date::date AS opp_close_date,
            o.candidato_contratado AS candidate_id,
            a.client_name,
            c.name AS candidate_name
        FROM opportunity o
        LEFT JOIN account a ON a.account_id = o.account_id
        LEFT JOIN candidates c ON c.candidate_id = o.candidato_contratado
        WHERE o.opportunity_id = %s
        LIMIT 1
        """,
        (opportunity_id,),
    )
    return cur.fetchone()


def _send_close_win_email(cur, opportunity_id: int) -> Dict[str, Any]:
    ctx = _fetch_close_win_context(cur, opportunity_id)
    if not ctx:
        return {"sent": False, "reason": "opportunity_not_found", "opportunity_id": opportunity_id}

    if not _is_stage_close_win(ctx.get("opp_stage")):
        return {"sent": False, "reason": "stage_not_close_win", "opportunity_id": opportunity_id}

    candidate_id = ctx.get("candidate_id")
    if not candidate_id:
        return {"sent": False, "reason": "missing_candidate", "opportunity_id": opportunity_id}

    hire = _fetch_hire_core(int(candidate_id), cur)
    hire_for_opp = hire if hire and int(hire.get("opportunity_id") or 0) == int(opportunity_id) else None

    start_date = (
        (hire_for_opp or {}).get("start_date")
        or ctx.get("opp_close_date")
        or "—"
    )
    price_type = (hire_for_opp or {}).get("price_type")
    computer = (hire_for_opp or {}).get("computer")

    to_list = _dedupe_emails([AGUS_EMAIL, LAR_EMAIL, JAZ_EMAIL, PGONZALES_EMAIL])
    ok = _send_email(
        subject=f"🎉 Close Win: {ctx.get('candidate_name') or f'Candidate #{candidate_id}'} — Start {start_date or '—'}",
        html_body=_close_win_email_html(
            ctx.get("client_name"),
            ctx.get("candidate_name") or f"Candidate #{candidate_id}",
            start_date,
            price_type=price_type,
            computer=computer,
        ),
        to=to_list,
    )
    if not ok:
        return {"sent": False, "reason": "send_failed", "opportunity_id": opportunity_id, "to": to_list}

    return {
        "sent": True,
        "opportunity_id": opportunity_id,
        "candidate_id": candidate_id,
        "to": to_list,
    }


def _ensure_hr_lead_signed_resig_ref_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS hr_lead_signed_resig_ref_reminders (
            reminder_id BIGSERIAL PRIMARY KEY,
            opportunity_id BIGINT NOT NULL UNIQUE,
            candidate_id BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            first_sent_at TIMESTAMPTZ,
            last_sent_at TIMESTAMPTZ,
            stopped_at TIMESTAMPTZ,
            stop_reason TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hr_lead_signed_resig_ref_due
        ON hr_lead_signed_resig_ref_reminders (last_sent_at)
        """
    )


def _normalize_bool(raw) -> bool:
    if isinstance(raw, bool):
        return raw
    return bool(re.match(r"^(1|y|yes|true|t|on|✓|\[v\])$", str(raw or "").strip(), flags=re.I))


def _is_stage_signed(stage: Optional[str]) -> bool:
    return (stage or "").strip().lower() == "signed"


def _hr_lead_resig_ref_subject(client_name: str, role_name: str) -> str:
    subject = f"Heads up: {client_name or 'Client'} — {role_name or 'the role'} moved to Signed ✨"
    return subject if len(subject) <= 120 else (subject[:117] + "...")


def _hr_lead_resig_ref_email_html(client_name: str, role_name: str) -> str:
    return f"""
<div style="font-family:Inter, Arial, sans-serif; font-size:14px; color:#222; line-height:1.5;">
  <p>Hi there! 🌸</p>
  <p>
    Quick note to share that the opportunity
    <strong>{html.escape(str(client_name or 'Client'))} — {html.escape(str(role_name or 'the role'))}</strong>
    has just moved to <strong>Signed</strong>. 🎉
  </p>
  <p>This is a reminder to:</p>
  <ul>
    <li>Request and upload the <strong>resignation letter</strong> 📝</li>
    <li>Collect and upload the <strong>references</strong> 📎</li>
  </ul>
  <p>Once both are in the hub, please check the box in the candidate overview page. 💕</p>
  <p style="margin-top:16px">— Vintti HUB</p>
</div>
    """.strip()


def _fetch_hr_lead_signed_resig_ref_context(cur, opportunity_id: int) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT
            o.opportunity_id,
            o.opp_stage,
            o.opp_position_name,
            o.opp_hr_lead,
            o.candidato_contratado AS candidate_id,
            a.client_name,
            c.check_hr_lead
        FROM opportunity o
        LEFT JOIN account a ON a.account_id = o.account_id
        LEFT JOIN candidates c ON c.candidate_id = o.candidato_contratado
        WHERE o.opportunity_id = %s
        LIMIT 1
        """,
        (opportunity_id,),
    )
    return cur.fetchone()


def _dedupe_emails(values: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for v in values:
        e = str(v or "").strip().lower()
        if not e or e in seen:
            continue
        seen.add(e)
        out.append(e)
    return out


def _send_hr_lead_signed_resig_ref_email(cur, opportunity_id: int, *, force: bool = False) -> Dict[str, Any]:
    _ensure_hr_lead_signed_resig_ref_table(cur)

    ctx = _fetch_hr_lead_signed_resig_ref_context(cur, opportunity_id)
    if not ctx:
        return {"sent": False, "reason": "opportunity_not_found", "opportunity_id": opportunity_id}

    cur.execute(
        """
        INSERT INTO hr_lead_signed_resig_ref_reminders (opportunity_id, candidate_id)
        VALUES (%s, %s)
        ON CONFLICT (opportunity_id) DO UPDATE
          SET candidate_id = EXCLUDED.candidate_id
        RETURNING reminder_id, first_sent_at, last_sent_at
        """,
        (opportunity_id, ctx.get("candidate_id")),
    )
    reminder = cur.fetchone() or {}

    if not _is_stage_signed(ctx.get("opp_stage")):
        cur.execute(
            """
            UPDATE hr_lead_signed_resig_ref_reminders
               SET stopped_at = COALESCE(stopped_at, now()),
                   stop_reason = COALESCE(stop_reason, 'stage_not_signed')
             WHERE opportunity_id = %s
            """,
            (opportunity_id,),
        )
        return {"sent": False, "reason": "stage_not_signed", "opportunity_id": opportunity_id}

    hr_email = str(ctx.get("opp_hr_lead") or "").strip().lower()
    if not hr_email:
        return {"sent": False, "reason": "missing_hr_lead", "opportunity_id": opportunity_id}

    candidate_id = ctx.get("candidate_id")
    if not candidate_id:
        return {"sent": False, "reason": "missing_candidate", "opportunity_id": opportunity_id}

    if _normalize_bool(ctx.get("check_hr_lead")):
        cur.execute(
            """
            UPDATE hr_lead_signed_resig_ref_reminders
               SET stopped_at = COALESCE(stopped_at, now()),
                   stop_reason = COALESCE(stop_reason, 'check_hr_lead_checked')
             WHERE opportunity_id = %s
            """,
            (opportunity_id,),
        )
        return {"sent": False, "reason": "already_checked", "opportunity_id": opportunity_id}

    last_sent_at = reminder.get("last_sent_at")
    if (not force) and last_sent_at is not None:
        try:
            elapsed = datetime.now(tz=BOGOTA_TZ) - last_sent_at.astimezone(BOGOTA_TZ)
            if elapsed < timedelta(hours=24):
                return {"sent": False, "reason": "not_due", "opportunity_id": opportunity_id}
        except Exception:
            pass

    to_list = _dedupe_emails([hr_email, PGONZALES_EMAIL])
    ok = _send_email(
        subject=_hr_lead_resig_ref_subject(ctx.get("client_name"), ctx.get("opp_position_name")),
        html_body=_hr_lead_resig_ref_email_html(ctx.get("client_name"), ctx.get("opp_position_name")),
        to=to_list,
    )
    if not ok:
        return {"sent": False, "reason": "send_failed", "opportunity_id": opportunity_id, "to": to_list}

    cur.execute(
        """
        UPDATE hr_lead_signed_resig_ref_reminders
           SET first_sent_at = COALESCE(first_sent_at, now()),
               last_sent_at = now(),
               stopped_at = NULL,
               stop_reason = NULL,
               candidate_id = %s
         WHERE opportunity_id = %s
        """,
        (candidate_id, opportunity_id),
    )
    return {
        "sent": True,
        "opportunity_id": opportunity_id,
        "candidate_id": candidate_id,
        "to": to_list,
    }


def _run_due_hr_lead_signed_resig_ref_reminders(cur) -> List[Dict[str, Any]]:
    _ensure_hr_lead_signed_resig_ref_table(cur)
    cur.execute(
        """
        SELECT opportunity_id
        FROM hr_lead_signed_resig_ref_reminders
        WHERE last_sent_at IS NOT NULL
          AND stopped_at IS NULL
          AND (now() - last_sent_at) >= interval '24 hours'
        ORDER BY last_sent_at ASC
        """
    )
    rows = cur.fetchall() or []
    sent = []
    for row in rows:
        result = _send_hr_lead_signed_resig_ref_email(cur, int(row["opportunity_id"]), force=True)
        if result.get("sent"):
            sent.append(result)
    return sent


def _fetch_hire_core(candidate_id: int, cur):
    """
    Devuelve los datos del hire más reciente para el candidato desde hire_opportunity.
    Campos esperados por el correo:
      start_date, references_notes, reference fields, setup_fee, salary, fee, revenue, price_type, computer, opportunity_id
    """
    cur.execute("""
        SELECT
            ho.start_date::date                           AS start_date,
            COALESCE(ho.references_notes, '')             AS references_notes,
            COALESCE(ho.reference_1_name, '')             AS reference_1_name,
            COALESCE(ho.reference_1_phone, '')            AS reference_1_phone,
            COALESCE(ho.reference_1_email, '')            AS reference_1_email,
            COALESCE(ho.reference_1_linkedin, '')         AS reference_1_linkedin,
            COALESCE(ho.reference_2_name, '')             AS reference_2_name,
            COALESCE(ho.reference_2_phone, '')            AS reference_2_phone,
            COALESCE(ho.reference_2_email, '')            AS reference_2_email,
            COALESCE(ho.reference_2_linkedin, '')         AS reference_2_linkedin,
            COALESCE(ho.setup_fee, 0)                     AS setup_fee,
            COALESCE(ho.salary, 0)                        AS salary,
            COALESCE(ho.fee, 0)                           AS fee,       -- usado por staffing
            COALESCE(ho.revenue, 0)                       AS revenue,   -- usado por recruiting
            ho.price_type                                 AS price_type,
            ho.computer                                   AS computer,
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
      - referal_source      (account.referal_source)
      - where_come_from     (account.where_come_from)
    """
    cur.execute("""
        SELECT
            c.name                         AS candidate_name,
            a.client_name                  AS client_name,
            a.mail                         AS client_mail,
            o.opp_position_name            AS opp_position_name,
            a.referal_source               AS referal_source,
            a.where_come_from              AS where_come_from
        FROM opportunity o
        JOIN account a   ON a.account_id = o.account_id
        JOIN candidates c ON c.candidate_id = %s
       WHERE o.opportunity_id = %s
       LIMIT 1
    """, (candidate_id, opportunity_id))
    return cur.fetchone() or {}


def _fetch_credit_loop_application(opportunity_id: int, cur):
    cur.execute(
        """
        SELECT
            applied_target_field,
            applied_original_value,
            applied_adjusted_value,
            applied_discount_amount
        FROM account_credit_loop
        WHERE used_by_opportunity_id = %s
          AND status = 'used'
        ORDER BY used_at DESC NULLS LAST, credit_id DESC
        LIMIT 1
        """,
        (opportunity_id,),
    )
    return cur.fetchone() or {}

def _initial_email_html(candidate_id:int, start_date, salary, fee, setup_fee, references, client_mail,
                        candidate_name:str, client_name:str, opp_position_name:str,
                        referal_source: Optional[str] = None,
                        lead_source: Optional[str] = None):
    link = _anchor("Open candidate in Vintti Hub", _candidate_link(candidate_id))
    referral_value = html.escape(referal_source) if referal_source else "—"
    referral_html = f'<li><b>Referral source:</b> {referral_value}</li>'
    lead_value = html.escape(lead_source) if lead_source else "—"
    lead_source_html = f'<li><b>Lead source:</b> {lead_value}</li>'
    notes_card = _references_card_html(references)
    # Copys en inglés, tono casual/fluido
    return f"""
    <div style="font-family:Inter,Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.6">
      <p>Hey team — new <b>Signed</b> 🎉</p>
      <p>We’ve just closed <b>{html.escape(client_name or 'Client')}</b>’s <b>{html.escape(opp_position_name or 'role')}</b> with
         <b>{html.escape(candidate_name or 'the candidate')}</b>.</p>

      <ul>
        <li><b>Start date:</b> {html.escape(str(start_date or '—'))}</li>
        <li><b>Salary:</b> ${html.escape(f"{salary:,.0f}")}</li>
        <li><b>Fee:</b> ${html.escape(f"{fee:,.0f}")}</li>
        <li><b>Set-up fee:</b> ${html.escape(f"{setup_fee:,.0f}")}</li>
        <li><b>Client email:</b> {html.escape(client_mail or '—')}</li>
        {referral_html}
        {lead_source_html}
      </ul>

      {notes_card}

      <p>Please complete your Signed tasks and then tick your checkbox on this page:<br>
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
      <p>You still haven’t checked your box for this Signed:
         <b>{html.escape(client_name or 'Client')}</b> — <b>{html.escape(opp_position_name or 'role')}</b>
         with <b>{html.escape(candidate_name or 'the candidate')}</b>.</p>
      <p>When you’re done, please mark it here:<br>{link}</p>
      <p>Thank you! — Vintti Hub</p>
    </div>
    """


@bp.route("/reminders/hr_lead_signed_resig_ref/trigger", methods=["POST"])
def trigger_hr_lead_signed_resig_ref_reminder():
    data = request.get_json(silent=True) or {}
    try:
        opportunity_id = int(data.get("opportunity_id"))
    except Exception:
        return jsonify({"error": "opportunity_id is required"}), 400

    force = _normalize_bool(data.get("force"))

    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        result = _send_hr_lead_signed_resig_ref_email(cur, opportunity_id, force=force)
        conn.commit()
        return jsonify(result), 200


@bp.route("/reminders/close_win/trigger", methods=["POST"])
def trigger_close_win_email():
    data = request.get_json(silent=True) or {}
    try:
        opportunity_id = int(data.get("opportunity_id"))
    except Exception:
        return jsonify({"error": "opportunity_id is required"}), 400

    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        result = _send_close_win_email(cur, opportunity_id)
        conn.commit()
        return jsonify(result), 200


@bp.route("/reminders/hr_lead_signed_resig_ref/due", methods=["POST"])
def send_due_hr_lead_signed_resig_ref_reminders():
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        sent = _run_due_hr_lead_signed_resig_ref_reminders(cur)
        conn.commit()
        return jsonify({"sent": sent}), 200


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
           WHERE (NOT jaz OR NOT lar)
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
            # Lucia desactivada para hire reminders.
            # if not r["agus"] and _should_send(now, press, r["last_agus_sent_at"]): plan.append(("agus", LUCIA_EMAIL))
            
            if not plan:
                continue

            html_body = _reminder_email_html(
                candidate_id=cid,
                candidate_name=candidate_name,
                client_name=client_name,
                opp_position_name=opp_position_name
            )

            for key, email in plan:
                ok = _send_email(subject="Quick reminder — please tick your Signed checkbox",
                                 html_body=html_body, to=[email])
                if ok:
                    sent.append({"reminder_id": rid, "who": key, "to": email})
                    col = f"last_{key}_sent_at"
                    cur.execute(f"UPDATE hire_reminders SET {col} = now() WHERE reminder_id = %s", (rid,))

        hr_lead_signed_resig_ref_sent = _run_due_hr_lead_signed_resig_ref_reminders(cur)
        credit_loop_sent = run_due_credit_loop_reminders(cur)

        conn.commit()
        return jsonify({
            "sent": sent,
            "hr_lead_signed_resig_ref_sent": hr_lead_signed_resig_ref_sent,
            "credit_loop_sent": credit_loop_sent,
        })


@bp.route("/reminders/credit_loop/due", methods=["POST"])
def send_due_credit_loop_reminders():
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        sent = run_due_credit_loop_reminders(cur)
        conn.commit()
        return jsonify({"sent": sent}), 200


@bp.route("/reminders/hr_lead_todos/run", methods=["POST"])
def run_hr_lead_todos():
    try:
        with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            report = run_scheduled_todos(cur)
            conn.commit()
        return jsonify(report), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
