import os
import ssl
import socket
import traceback
from flask import request, jsonify, make_response
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from sendgrid.helpers.mail import Email

ssl._create_default_https_context = ssl._create_unverified_context

def register_send_email_route(app):
    @app.route("/send_email", methods=["POST", "OPTIONS"])
    def send_email():
        if request.method == "OPTIONS":
            response = make_response('', 204)
            response.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            return response

        print("📥 [INICIO] POST recibido en /send_email")

        # ✅ Verificar resolución DNS (acceso a internet)
        try:
            ip = socket.gethostbyname("sendgrid.com")
            print(f"🌍 [DNS] sendgrid.com resuelve a {ip}")
        except Exception as dns_error:
            print("🛑 [ERROR DNS] No se pudo resolver sendgrid.com")
            traceback.print_exc()
            return jsonify({"error": "DNS resolution failed", "detail": str(dns_error)}), 500

        # ✅ Leer datos del frontend
        try:
            data = request.get_json(force=True)
            print("📦 [DATA] JSON recibido:", data)
        except Exception as json_error:
            print("❌ [ERROR JSON] Error al leer JSON:")
            traceback.print_exc()
            return jsonify({"error": "Invalid JSON", "detail": str(json_error)}), 400

        # ✅ Validar campos requeridos
        to_emails = data.get('to')
        cc_emails = data.get('cc', [])
        subject = data.get('subject')
        body = data.get('body')

        if not to_emails or not subject or not body:
            print("⚠️ [VALIDACIÓN] Faltan campos: to, subject o body")
            return jsonify({"error": "Missing required fields"}), 400

        try:
            # ✅ Preparar mensaje
            print("✉️ [EMAIL] Construyendo correo...")
            message = Mail(
                from_email=Email('angie@vintti.com', name='Angie Vintti'),
                to_emails=to_emails,
                subject=subject,
                html_content=body
            )
            for email in cc_emails:
                message.add_cc(email)

            # ✅ Enviar con SendGrid
            print("🚀 [ENVÍO] Enviando correo...")
            api_key = os.environ.get('SENDGRID_API_KEY')
            if not api_key:
                print("🛑 [CONFIG] Falta SENDGRID_API_KEY en entorno")
                return jsonify({"error": "SendGrid API Key not configured"}), 500

            sg = SendGridAPIClient(api_key)
            response = sg.send(message)

            print("✅ [ENVÍO OK] Código:", response.status_code)
            print("📬 [HEADERS] SendGrid:", dict(response.headers))

            resp = jsonify({"status": "Email sent", "code": response.status_code})
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp

        except Exception as e:
            print("🧨 [ERROR ENVÍO] Excepción general:")
            traceback.print_exc()
            resp = jsonify({"error": "Email sending failed", "detail": str(e)})
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp, 500
