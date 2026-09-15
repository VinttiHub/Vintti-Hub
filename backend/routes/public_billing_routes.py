"""Formulario publico de facturacion: a que correo se manda la factura.

Mismo molde que `public_bonus_routes.py`: la pagina vive en `docs/billing-form.html`,
se abre con `?account_id=<id>` desde Account Details y no pide login. Como sale del
mismo origen que ya permite el CORS de `app.py`, no hay nada que tocar ahi.

El correo vigente se guarda en `account.billing_email` (lo que se ve en el hub) y cada
envio queda ademas en `billing_email_requests`: el valor de la cuenta se pisa, el
historial se acumula, asi que una carga equivocada nunca borra la anterior.
"""

from flask import Blueprint, request, jsonify
from psycopg2.extras import RealDictCursor
from db import get_connection
import logging
import os
import re
from html import escape
from typing import List
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email

from utils import slack

bp = Blueprint("public_billing", __name__, url_prefix="/public/billing_email")

# Canal de Slack del aviso. Hardcodeado a proposito, igual que los destinatarios
# de mail: una env var mal seteada mandaria el dato de facturacion de un cliente
# a un canal equivocado, y nadie se enteraria.
# Definitivo desde el 2026-09-15 (antes apuntaba al canal de prueba C0C0UQ7SYBW).
BILLING_SLACK_CHANNEL_ID = "C0AN42AANTD"

FRONT_BASE_URL = os.environ.get("FRONT_BASE_URL", "https://vinttihub.vintti.com")

# Mismo criterio que el bonus request: destinatarios hardcodeados, sin env var de por
# medio. Se duplican las constantes a proposito en vez de importarlas de
# public_bonus_routes: cada flujo publico tiene su propia lista, para que cambiar una
# no mueva la otra sin querer.
BILLING_EMAIL_FALLBACK_RECIPIENTS = [
    "agustin@vintti.com",
    "lara@vintti.com",
    "jazmin@vintti.com",
    "pgonzales@vintti.com",
]
BILLING_EMAIL_RECIPIENT_USER_IDS = [1, 2, 6, 12]

# Deliberadamente laxo: valida la forma, no la existencia del buzon. Un regex estricto
# de RFC rechaza direcciones validas y este formulario lo completa un cliente.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

_SCHEMA_READY = False


def _ensure_schema(cur):
    """Crea la columna y la tabla la primera vez, como staffing_routes._ensure_schema.

    Hay un archivo versionado en backend/sql/20260915_add_billing_email.sql con el
    mismo DDL, pero no hay migration runner: esto es lo que hace que el endpoint
    funcione en local y en un entorno nuevo sin correr nada a mano.
    """
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    cur.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS billing_email TEXT")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS billing_email_requests (
            billing_email_request_id SERIAL PRIMARY KEY,
            account_id INTEGER NOT NULL,
            billing_email TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_billing_email_requests_account
            ON billing_email_requests (account_id, created_at DESC)
    """)
    _SCHEMA_READY = True


def _safe_account_id(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _clean_email(raw):
    clean = str(raw or "").strip().lower()
    return clean if EMAIL_RE.match(clean) else None


def _resolve_billing_email_recipients(cur) -> List[str]:
    recipients = []
    seen = set()

    for user_id in BILLING_EMAIL_RECIPIENT_USER_IDS:
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
            logging.exception(
                "Failed resolving billing email recipient for user_id=%s", user_id
            )

    for email in BILLING_EMAIL_FALLBACK_RECIPIENTS:
        clean = str(email or "").strip().lower()
        if clean and clean not in seen:
            seen.add(clean)
            recipients.append(clean)

    return recipients


def _send_billing_email_notification(
    to_emails: List[str],
    account_name: str,
    billing_email: str,
):
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        raise RuntimeError("SENDGRID_API_KEY not configured")
    if not to_emails:
        raise RuntimeError("No billing email recipients configured")

    subject = f"Billing email | {account_name or 'N/A'}"

    html_body = f"""
    <p>Hi team,</p>
    <p>A client submitted the email address where invoices should be sent.</p>
    <ul>
      <li><strong>Account:</strong> {escape(account_name or "N/A")}</li>
      <li><strong>Billing email:</strong> {escape(billing_email or "N/A")}</li>
    </ul>
    <p>It is already saved on the account and visible in the Invoice tab.</p>
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


def _post_billing_email_to_slack(
    account_id: int,
    account_name: str,
    billing_email: str,
) -> dict:
    """Avisa al canal. Nunca levanta: `post_blocks` ya devuelve el error en vez
    de tirarlo, asi que un Slack caido no puede romper el submit del cliente."""
    account_url = f"{FRONT_BASE_URL}/account-details.html?id={account_id}"

    lineas = [
        f"*{slack.esc(account_name or 'Cuenta sin nombre')}* ya cargo su mail de facturacion.",
        f":envelope: *Mail de facturacion:* `{slack.esc(billing_email)}`",
        slack.link(account_url, "Ver la cuenta en el hub"),
    ]

    blocks = [
        {"type": "header",
         "text": {"type": "plain_text", "text": "Nuevo mail de facturacion", "emoji": True}},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": "\n".join(lineas)}},
    ]
    # El `text` es el fallback de la notificacion del celular, donde los blocks
    # no se ven.
    fallback = f"Mail de facturacion de {account_name or 'una cuenta'}: {billing_email}"

    return slack.post_blocks(blocks, fallback, channel_override=BILLING_SLACK_CHANNEL_ID)


@bp.route("/context", methods=["GET"])
def billing_email_context():
    """Datos de la cuenta para prellenar el formulario en modo lectura."""
    account_id = _safe_account_id(request.args.get("account_id") or request.args.get("id"))
    if not account_id:
        return jsonify({"error": "account_id is required"}), 400

    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_schema(cur)
        conn.commit()

        cur.execute(
            """
            SELECT client_name, state, timezone, industry,
                   name, surname, mail, website, contract, billing_email
            FROM account
            WHERE account_id = %s
            LIMIT 1
            """,
            (account_id,),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "account not found"}), 404

        contact_name = " ".join(
            part for part in [(row.get("name") or "").strip(), (row.get("surname") or "").strip()] if part
        )

        return jsonify({
            "account_id": account_id,
            "client_name": row.get("client_name") or "",
            "state": row.get("state") or "",
            "timezone": row.get("timezone") or "",
            "industry": row.get("industry") or "",
            "contact_name": contact_name,
            "contact_mail": row.get("mail") or "",
            "website": row.get("website") or "",
            "contract": row.get("contract") or "",
            "billing_email": row.get("billing_email") or "",
        })
    except Exception as exc:
        if conn:
            conn.rollback()
        logging.exception("billing email context failed")
        return jsonify({"error": str(exc)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@bp.route("/submit", methods=["POST", "OPTIONS"])
def submit_billing_email():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}

    account_id = _safe_account_id(data.get("account_id"))
    if not account_id:
        return jsonify({"error": "account_id is required"}), 400

    billing_email = _clean_email(data.get("billing_email"))
    if not billing_email:
        return jsonify({"error": "a valid billing_email is required"}), 400

    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_schema(cur)

        cur.execute(
            "SELECT client_name FROM account WHERE account_id = %s LIMIT 1",
            (account_id,),
        )
        account_row = cur.fetchone()
        if not account_row:
            conn.rollback()
            return jsonify({"error": "account not found"}), 404

        account_name = account_row.get("client_name") or ""

        cur.execute(
            """
            INSERT INTO billing_email_requests (account_id, billing_email)
            VALUES (%s, %s)
            RETURNING billing_email_request_id
            """,
            (account_id, billing_email),
        )
        billing_email_request_id = (cur.fetchone() or {}).get("billing_email_request_id")

        cur.execute(
            "UPDATE account SET billing_email = %s WHERE account_id = %s",
            (billing_email, account_id),
        )

        # Se resuelven antes del commit, mientras el cursor sigue en una transaccion
        # sana; el envio en si va despues.
        recipients = _resolve_billing_email_recipients(cur)

        conn.commit()

        # El mail va DESPUES del commit y envuelto: si SendGrid falla, el correo del
        # cliente ya quedo guardado igual.
        email_warning = None
        try:
            _send_billing_email_notification(
                to_emails=recipients,
                account_name=account_name,
                billing_email=billing_email,
            )
        except Exception as email_exc:
            logging.exception("billing email notification failed")
            email_warning = str(email_exc)

        # Slack va aparte del mail: son dos avisos independientes, y que falle uno
        # no puede tapar al otro.
        slack_result = _post_billing_email_to_slack(
            account_id=account_id,
            account_name=account_name,
            billing_email=billing_email,
        )

        payload = {"ok": True, "billing_email_request_id": billing_email_request_id}
        if email_warning:
            payload["email_warning"] = email_warning
        if not slack_result.get("sent"):
            payload["slack_warning"] = slack_result.get("error") or "unknown"
        return jsonify(payload)
    except Exception as exc:
        if conn:
            conn.rollback()
        logging.exception("billing email submit failed")
        return jsonify({"error": str(exc)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@bp.route("/account/<int:account_id>", methods=["GET"])
def billing_email_for_account(account_id):
    """Correo vigente + historial, para el panel del tab Invoice."""
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_schema(cur)
        conn.commit()

        cur.execute(
            "SELECT billing_email FROM account WHERE account_id = %s LIMIT 1",
            (account_id,),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "account not found"}), 404

        cur.execute(
            """
            SELECT billing_email_request_id,
                   billing_email,
                   created_at::date::text AS created_date
            FROM billing_email_requests
            WHERE account_id = %s
            ORDER BY created_at DESC
            """,
            (account_id,),
        )
        items = cur.fetchall()

        return jsonify({
            "account_id": account_id,
            "billing_email": row.get("billing_email") or "",
            "items": items,
        })
    except Exception as exc:
        if conn:
            conn.rollback()
        logging.exception("billing email listing failed")
        return jsonify({"error": str(exc)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
