import os
import ssl
import socket
import traceback
import logging
from flask import request, jsonify, make_response
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email
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

def register_send_email_route(app):
    @app.route("/send_email", methods=["POST", "OPTIONS"])
    def send_email():
        logging.info("📨 Entrando a /send_email")
        logging.info(f"🔍 Método recibido: {request.method}")

        if request.method == "OPTIONS":
            logging.info("🟡 OPTIONS request recibida")
            response = make_response('', 204)
            response.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Max-Age'] = '86400'
            return response

        try:
            # Verificar DNS
            ip = socket.gethostbyname("sendgrid.com")
            logging.info(f"🌍 DNS OK: sendgrid.com => {ip}")
        except Exception as dns_error:
            logging.error("🛑 Error de DNS")
            traceback.print_exc()
            return jsonify({"error": "DNS resolution failed", "detail": str(dns_error)}), 500

        try:
            # Leer y validar JSON
            data = request.get_json(force=True)
            logging.info("📦 JSON recibido: %s", data)
        except Exception as json_error:
            logging.error("❌ Error al leer JSON")
            traceback.print_exc()
            return jsonify({"error": "Invalid JSON", "detail": str(json_error)}), 400

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

            # Asegura HTML aunque te envíen texto plano (e.g., desde <textarea>)
            if _looks_like_html(body):
                html_body = body
            else:
                html_body = _text_to_html(body)

            plain_body = _html_to_plain(html_body)

            message = Mail(
                from_email=Email('hub@vintti-hub.com', name='Vintti HUB'),
                to_emails=to_emails,
                subject=subject,
                plain_text_content=plain_body,  # 👈 versión texto (mejora entregabilidad y preview)
                html_content=html_body          # 👈 versión HTML con saltos y formato
            )

            for email in cc_emails:
                message.add_cc(Email(email))  

            api_key = os.environ.get('SENDGRID_API_KEY')
            if not api_key:
                logging.error("🛑 No se encontró SENDGRID_API_KEY en las variables de entorno")
                return jsonify({"error": "SendGrid API Key not configured"}), 500
            logging.info(f"🔐 API Key detectada (comienza con {api_key[:5]}...)")

            # ENVÍO REAL (descomenta esta línea para pruebas reales)
            sg = SendGridAPIClient(api_key)
            logging.info("🚀 Enviando correo con SendGrid...")
            try:
                logging.info("🌐 Probing SendGrid API connectivity...")
                r = requests.get("https://api.sendgrid.com/v3", timeout=10)
                logging.info(f"🌐 SendGrid connectivity status: {r.status_code}")
            except Exception as e:
                logging.error("❌ Fallo al conectar a SendGrid directamente")
                logging.exception(e)

            response = sg.send(message)
            logging.info("✅ Envío exitoso. Status: %s", response.status_code)
            logging.info("📨 Headers de SendGrid: %s", dict(response.headers))

            resp = jsonify({"status": "Email sent", "code": response.status_code})
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

BOGOTA_TZ = timezone(timedelta(hours=-5))

# URL base del frontend que contiene reset_password.html
FRONT_BASE_URL = os.environ.get("FRONT_BASE_URL", "https://vinttihub.vintti.com")


def register_password_reset_routes(app):
    @app.post("/password_reset_request")
    def password_reset_request():
        """
        Recibe { "email": "..." } y:
        - genera token
        - lo guarda en users.reset_token + reset_token_expires_at
        - envía un email usando /send_email con el link de reset
        """
        try:
            data = request.get_json(force=True)
        except Exception as e:
            app.logger.error("❌ Invalid JSON in /password_reset_request")
            return jsonify({"success": False, "message": "Invalid JSON"}), 400

        email = (data.get("email") or "").strip().lower()
        if not email:
            return jsonify({"success": False, "message": "Email required"}), 400

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(BOGOTA_TZ) + timedelta(hours=1)

        # Guardar token (solo si el usuario existe)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE users
                       SET reset_token = %s,
                           reset_token_expires_at = %s
                     WHERE LOWER(email_vintti) = %s
                """, (token, expires_at, email))
            conn.commit()

        reset_link = f"{FRONT_BASE_URL.rstrip('/')}/reset_password.html?token={token}"

        # Construir payload para tu /send_email ya existente
        body = (
            "Hello,\n\n"
            "You (or someone else) requested to reset your Vintti HUB password.\n\n"
            f"Use this link to reset your password (valid for 1 hour):\n{reset_link}\n\n"
            "If you did not request this, you can safely ignore this email.\n\n"
            "— Vintti HUB"
        )

        try:
            # Llamar a tu propio endpoint /send_email del mismo backend
            base = request.host_url.rstrip("/")  # ej: https://7m6mw95m8y.us-east-2.awsapprunner.com
            resp = requests.post(
                f"{base}/send_email",
                json={
                    "to": [email],
                    "subject": "Reset your Vintti HUB password",
                    "body": body,
                },
                timeout=15,
            )
            app.logger.info("📧 /send_email for reset: %s %s", resp.status_code, resp.text[:200])
        except Exception as e:
            app.logger.error("❌ Failed to call /send_email for password reset")
            app.logger.exception(e)

        # Siempre respondemos success (para no filtrar si el email existe o no)
        return jsonify({"success": True}), 200

    @app.post("/password_reset_confirm")
    def password_reset_confirm():
        """
        Recibe { "token": "...", "new_password": "..." } y:
        - valida token + expiración
        - actualiza password en users
        - borra reset_token + reset_token_expires_at
        """
        try:
            data = request.get_json(force=True)
        except Exception:
            return jsonify({"success": False, "message": "Invalid JSON"}), 400

        token = data.get("token")
        new_password = data.get("new_password")

        if not token or not new_password:
            return jsonify({"success": False, "message": "Missing token or password"}), 400

        now = datetime.now(BOGOTA_TZ)

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT user_id, reset_token_expires_at
                      FROM users
                     WHERE reset_token = %s
                """, (token,))
                row = cur.fetchone()

                if not row:
                    return jsonify({"success": False, "message": "Invalid token"}), 400

                user_id, expires_at = row
                if not expires_at or expires_at < now:
                    return jsonify({"success": False, "message": "Token expired"}), 400

                # ⚠️ IMPORTANTE:
                # Si ya guardas la contraseña hasheada, aquí usa el mismo método de hash
                # por ejemplo:
                # from werkzeug.security import generate_password_hash
                # hashed = generate_password_hash(new_password)
                #
                # Si hoy la guardas plano (columna password tal cual), sería:
                hashed = new_password

                cur.execute("""
                    UPDATE users
                       SET password = %s,
                           reset_token = NULL,
                           reset_token_expires_at = NULL
                     WHERE user_id = %s
                """, (hashed, user_id))
            conn.commit()

        return jsonify({"success": True}), 200
