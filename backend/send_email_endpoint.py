import os
import ssl
import socket
import traceback
import logging
from flask import request, jsonify, make_response
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, Cc
import requests
import logging
import re
from html import unescape, escape
import os
import secrets
from datetime import datetime, timedelta, timezone
from flask import request, jsonify
from db import get_connection  

def _looks_like_html(s: str) -> bool:
    # Heurística simple para detectar si ya viene con etiquetas
    return bool(s and '<' in s and '>' in s)

def _text_to_html(text: str) -> str:
    # Escapa y respeta saltos de línea básicos
    safe = escape(text or '')
    return safe.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br>')

def _html_to_plain(html: str) -> str:
    s = html or ''
    s = re.sub(r'(?i)<br\s*/?>', '\n', s)
    s = re.sub(r'(?i)</(p|div|li|h[1-6]|tr|section|article|header|footer)>', '\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = unescape(s)
    # normaliza saltos
    s = re.sub(r'[ \t]+\n', '\n', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()

def send_email_message(to_emails, subject, body, cc_emails=None):
    """Envia un mail por SendGrid y devuelve el status code.

    Extraido de /send_email para poder reusarlo desde otras rutas (p. ej. el
    envio individual de sign-off). Levanta excepcion si falla.
    """
    if not to_emails or not subject or not body:
        raise ValueError("Missing required fields (to/subject/body)")

    api_key = os.environ.get('SENDGRID_API_KEY')
    if not api_key:
        raise RuntimeError("SendGrid API Key not configured")

    # Asegura HTML aunque venga texto plano (e.g., desde un <textarea>)
    html_body = body if _looks_like_html(body) else _text_to_html(body)
    plain_body = _html_to_plain(html_body)

    message = Mail(
        from_email=Email('hub@vintti-hub.com', name='Vintti HUB'),
        to_emails=to_emails,
        subject=subject,
        plain_text_content=plain_body,
        html_content=html_body,
    )

    for email in (cc_emails or []):
        # Cc(), no Email(): sendgrid>=6 rechaza un Email genérico en add_cc.
        message.add_cc(Cc(email))

    response = SendGridAPIClient(api_key).send(message)
    return response.status_code


def register_send_email_route(app):
    @app.route("/send_email", methods=["POST", "OPTIONS"])
    def send_email():
        logging.info("📨 Entrando a /send_email")
        logging.info("🔍 Método recibido: %s", request.method)

        if request.method == "OPTIONS":
            logging.info("🟡 OPTIONS request recibida")
            response = make_response('', 204)
            response.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Max-Age'] = '86400'
            return response

        # Solo aceptamos POST reales con cuerpo JSON
        if request.method != "POST":
            logging.warning("⛔ Método no permitido en /send_email: %s", request.method)
            resp = jsonify({"error": "Method not allowed"})
            resp.status_code = 405
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp

        try:
            # Verificar DNS
            ip = socket.gethostbyname("sendgrid.com")
            logging.info(f"🌍 DNS OK: sendgrid.com => {ip}")
        except Exception as dns_error:
            logging.error("🛑 Error de DNS")
            traceback.print_exc()
            return jsonify({"error": "DNS resolution failed", "detail": str(dns_error)}), 500

        try:
            raw = request.data
            logging.info("📦 Raw body recibido en /send_email: %r", raw)

            # silent=True evita que lance BadRequest y nos deje manejarlo nosotros
            data = request.get_json(silent=True) or {}
            logging.info("📦 JSON parseado en /send_email: %s", data)
        except Exception as json_error:
            logging.error("❌ Error inesperado al leer JSON en /send_email. Raw data=%r", request.data)
            traceback.print_exc()
            resp = jsonify({"error": "Invalid JSON", "detail": str(json_error)})
            resp.status_code = 400
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp

        if not data:
            logging.warning("⚠️ /send_email llamado sin JSON o JSON vacío")
            resp = jsonify({"error": "Empty JSON body"})
            resp.status_code = 400
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp

        # Validar campos obligatorios
        to_emails = data.get('to')
        cc_emails = data.get('cc', [])
        subject = data.get('subject')
        body = data.get('body')

        if not to_emails or not subject or not body:
            logging.warning("⚠️ Faltan campos requeridos")
            return jsonify({"error": "Missing required fields"}), 400

        try:
            logging.info("✉️ Construyendo mensaje...")

            api_key = os.environ.get('SENDGRID_API_KEY')
            if not api_key:
                logging.error("🛑 No se encontró SENDGRID_API_KEY en las variables de entorno")
                return jsonify({"error": "SendGrid API Key not configured"}), 500
            logging.info(f"🔐 API Key detectada (comienza con {api_key[:5]}...)")

            logging.info("🚀 Enviando correo con SendGrid...")
            try:
                logging.info("🌐 Probing SendGrid API connectivity...")
                r = requests.get("https://api.sendgrid.com/v3", timeout=10)
                logging.info(f"🌐 SendGrid connectivity status: {r.status_code}")
            except Exception as e:
                logging.error("❌ Fallo al conectar a SendGrid directamente")
                logging.exception(e)

            status_code = send_email_message(to_emails, subject, body, cc_emails)
            logging.info("✅ Envío exitoso. Status: %s", status_code)

            resp = jsonify({"status": "Email sent", "code": status_code})
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp

        except Exception as e:
            logging.error("🧨 Excepción durante el envío")
            traceback.print_exc()
            resp = jsonify({"error": "Email sending failed", "detail": str(e)})
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp, 500