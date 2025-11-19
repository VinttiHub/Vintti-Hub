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

from flask import request, jsonify, make_response
import os, secrets, logging, traceback
from datetime import datetime, timedelta, timezone
from db import get_connection  

BOGOTA_TZ = timezone(timedelta(hours=-5))
FRONT_BASE_URL = os.environ.get("FRONT_BASE_URL", "https://vinttihub.vintti.com")

ALLOWED_ORIGIN = "https://vinttihub.vintti.com"

def _cors_response(resp, status=200):
    """Añade headers CORS básicos a cualquier respuesta."""
    resp.status_code = status
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp

def _cors_preflight():
    """Respuesta estándar para OPTIONS."""
    resp = make_response("", 204)
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp

def register_password_reset_routes(app):

    @app.route("/password_reset_request", methods=["POST", "OPTIONS"])
    def password_reset_request():
        app.logger.info("🔐 /password_reset_request hit. method=%s", request.method)

        # ---- PRE-FLIGHT CORS ----
        if request.method == "OPTIONS":
            app.logger.info("🟡 /password_reset_request OPTIONS (preflight)")
            return _cors_preflight()

        # ---- POST normal ----
        try:
            data = request.get_json(force=True)
            app.logger.info("📦 JSON recibido en reset_request: %s", data)
        except Exception as e:
            app.logger.error("❌ Invalid JSON in /password_reset_request")
            app.logger.exception(e)
            return _cors_response(jsonify({"success": False, "message": "Invalid JSON"}), 400)

        email = (data.get("email") or "").strip().lower()
        app.logger.info("👤 Email para reset: %s", email)

        if not email:
            return _cors_response(jsonify({"success": False, "message": "Email required"}), 400)

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(BOGOTA_TZ) + timedelta(hours=1)
        app.logger.info("🧬 Token generado: %s (expira %s)", token, expires_at.isoformat())

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE users
                           SET reset_token = %s,
                               reset_token_expires_at = %s
                         WHERE LOWER(email_vintti) = %s
                        """,
                        (token, expires_at, email),
                    )
                    updated = cur.rowcount
                conn.commit()
            app.logger.info("📝 Filas actualizadas en users para reset: %s", updated)
        except Exception as db_err:
            app.logger.error("💥 Error guardando token de reset en DB")
            app.logger.exception(db_err)
            # igual devolvemos success para no filtrar si existe o no
            return _cors_response(jsonify({"success": True}), 200)

        reset_link = f"{FRONT_BASE_URL.rstrip('/')}/reset_password.html?token={token}"
        app.logger.info("🔗 Reset link: %s", reset_link)

        body = (
            "Hello,\n\n"
            "You (or someone else) requested to reset your Vintti HUB password.\n\n"
            f"Use this link to reset your password (valid for 1 hour):\n{reset_link}\n\n"
            "If you did not request this, you can safely ignore this email.\n\n"
            "— Vintti HUB"
        )

        # Llamar a /send_email
        try:
            base = request.host_url.rstrip("/")
            app.logger.info("📨 Llamando a %s/send_email ...", base)
            resp = requests.post(
                f"{base}/send_email",
                json={
                    "to": [email],
                    "subject": "Reset your Vintti HUB password",
                    "body": body,
                },
                timeout=15,
            )
            app.logger.info(
                "📧 /send_email respuesta: %s %s",
                resp.status_code,
                resp.text[:300],
            )
        except Exception as e:
            app.logger.error("❌ Failed to call /send_email for password reset")
            app.logger.exception(e)

        # Nunca revelamos si el email existe o no
        return _cors_response(jsonify({"success": True}), 200)

    @app.route("/password_reset_confirm", methods=["POST", "OPTIONS"])
    def password_reset_confirm():
        app.logger.info("🔐 /password_reset_confirm hit. method=%s", request.method)

        if request.method == "OPTIONS":
            app.logger.info("🟡 /password_reset_confirm OPTIONS (preflight)")
            return _cors_preflight()

        try:
            data = request.get_json(force=True)
            app.logger.info("📦 JSON recibido en reset_confirm: %s", data)
        except Exception as e:
            app.logger.error("❌ Invalid JSON in /password_reset_confirm")
            app.logger.exception(e)
            return _cors_response(jsonify({"success": False, "message": "Invalid JSON"}), 400)

        token = data.get("token")
        new_password = data.get("new_password")
        app.logger.info("🔑 Token recibido: %s", token)

        if not token or not new_password:
            return _cors_response(
                jsonify({"success": False, "message": "Missing token or password"}), 400
            )

        now = datetime.now(BOGOTA_TZ)

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT user_id, reset_token_expires_at
                          FROM users
                         WHERE reset_token = %s
                        """,
                        (token,),
                    )
                    row = cur.fetchone()

                    if not row:
                        app.logger.warning("⚠️ Token no encontrado")
                        return _cors_response(
                            jsonify({"success": False, "message": "Invalid token"}), 400
                        )

                    user_id, expires_at = row
                    app.logger.info(
                        "👤 user_id=%s, token_exp=%s", user_id, expires_at
                    )

                    if not expires_at or expires_at < now:
                        app.logger.warning("⏰ Token expirado")
                        return _cors_response(
                            jsonify({"success": False, "message": "Token expired"}), 400
                        )

                    hashed = new_password  # aquí luego metes tu hash real

                    cur.execute(
                        """
                        UPDATE users
                           SET password = %s,
                               reset_token = NULL,
                               reset_token_expires_at = NULL
                         WHERE user_id = %s
                        """,
                        (hashed, user_id),
                    )
                conn.commit()
        except Exception as db_err:
            app.logger.error("💥 Error actualizando password en DB")
            app.logger.exception(db_err)
            return _cors_response(
                jsonify({"success": False, "message": "Internal error"}), 500
            )

        return _cors_response(jsonify({"success": True}), 200)
