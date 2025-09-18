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

# ⚠️ IMPORTANTE: Quitar esto en producción, solo para pruebas de certificados locales
ssl._create_default_https_context = ssl._create_unverified_context

def register_send_email_route(app):
    @app.route("/send_email", methods=["POST", "OPTIONS"])
    def send_email():
        logging.info("📨 Entrando a /send_email")
        logging.info(f"🔍 Método recibido: {request.method}")

        if request.method == "OPTIONS":
            logging.info("🟡 OPTIONS request recibida")
            response = make_response('', 204)
            response.headers['Access-Control-Allow-Origin'] = 'https://vintti-hub.com'
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
            message = Mail(
                from_email=Email('notifications@vintti-hub.com', name='Vintti HUB'),
                to_emails=to_emails,
                subject=subject,
                html_content=body
            )
            for email in cc_emails:
                message.add_cc(email)
            logging.info("📬 Mensaje construido correctamente")

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
            resp.headers['Access-Control-Allow-Origin'] = 'https://vintti-hub.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp

        except Exception as e:
            logging.error("🧨 Excepción durante el envío")
            traceback.print_exc()
            resp = jsonify({"error": "Email sending failed", "detail": str(e)})
            resp.headers['Access-Control-Allow-Origin'] = 'https://vintti-hub.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp, 500
