import os
import ssl
import socket
import logging
import traceback
from flask import request, jsonify, make_response
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email

ssl._create_default_https_context = ssl._create_unverified_context

def register_send_email_route(app):
    @app.route("/send_email", methods=["POST", "OPTIONS"])
    def send_email():
        logging.info(f"🔍 Método recibido: {request.method}")
        logging.info("📨 Entrando a /send_email")

        if request.method == "OPTIONS":
            print("🟡 [CORS] OPTIONS request recibida")
            response = make_response('', 204)
            response.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Max-Age'] = '86400'
            return response

        # 🌐 Verificar DNS
        try:
            ip = socket.gethostbyname("sendgrid.com")
            print(f"🌍 [DNS] sendgrid.com resuelve a {ip}")
            logging.info(f"[DNS] sendgrid.com resolved to {ip}")
        except Exception as dns_error:
            print("🛑 [ERROR DNS] No se pudo resolver sendgrid.com")
            logging.error("DNS resolution failed", exc_info=True)
            return jsonify({"error": "DNS resolution failed", "detail": str(dns_error)}), 500

        # 📥 Obtener datos del request
        try:
            data = request.get_json(force=True)
            print("📦 [DATA] JSON recibido:", data)
            logging.info(f"[DATA] Payload: {data}")
        except Exception as json_error:
            print("❌ [ERROR JSON] Error al leer JSON")
            logging.error("Invalid JSON payload", exc_info=True)
            return jsonify({"error": "Invalid JSON", "detail": str(json_error)}), 400

        # ✅ Validar campos requeridos
        to_emails = data.get('to')
        cc_emails = data.get('cc', [])
        subject = data.get('subject')
        body = data.get('body')

        if not to_emails or not subject or not body:
            print("⚠️ [VALIDACIÓN] Campos obligatorios faltantes")
            logging.warning("Missing required fields in payload")
            return jsonify({"error": "Missing required fields"}), 400

        # 📤 Preparar envío
        try:
            print("✉️ [EMAIL] Construyendo mensaje...")
            logging.info("Construyendo correo...")

            message = Mail(
                from_email=Email('angie@vintti.com', name='Angie Vintti'),
                to_emails=to_emails,
                subject=subject,
                html_content=body
            )
            for email in cc_emails:
                message.add_cc(email)

            api_key = os.environ.get('SENDGRID_API_KEY')
            if not api_key:
                print("🛑 [CONFIG] Faltante SENDGRID_API_KEY")
                logging.critical("SENDGRID_API_KEY no está configurada")
                return jsonify({"error": "SendGrid API Key not configured"}), 500

            print("🚀 [ENVÍO] Enviando correo...")
            logging.info("Llamando a SendGrid API")

            sg = SendGridAPIClient(api_key)
            response = sg.send(message)

            print("✅ [ENVÍO OK] Código:", response.status_code)
            logging.info(f"[SendGrid] Código de respuesta: {response.status_code}")
            logging.debug(f"[SendGrid] Headers: {response.headers}")

            resp = jsonify({"status": "Email sent", "code": response.status_code})
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp

        except Exception as e:
            print("🧨 [ERROR ENVÍO] Falló el envío del correo")
            traceback.print_exc()
            logging.error("Exception during email sending", exc_info=True)
            resp = jsonify({"error": "Email sending failed", "detail": str(e)})
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp, 500
