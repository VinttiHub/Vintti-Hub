import os
import ssl
from flask import request, jsonify, make_response
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import socket 

print("🌍 Can resolve DNS?", socket.gethostbyname("sendgrid.com"))
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

        try:
            data = request.get_json()
            to_emails = data.get('to')
            cc_emails = data.get('cc', [])
            subject = data.get('subject')
            body = data.get('body')

            if not to_emails or not subject or not body:
                return jsonify({"error": "Missing required fields"}), 400

            message = Mail(
                from_email='angie@vintti.com',
                to_emails=to_emails,
                subject=subject,
                html_content=body
            )

            for email in cc_emails:
                message.add_cc(email)

            sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            response = sg.send(message)

            resp = jsonify({"status": "Email sent", "code": response.status_code})
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp

        except Exception as e:
            resp = jsonify({"error": str(e)})
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp, 500