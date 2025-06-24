
import os
import ssl
from flask import request, jsonify
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

ssl._create_default_https_context = ssl._create_unverified_context

def register_send_email_route(app):
    @app.route("/send_email", methods=["POST"])
    def send_email():
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

            if cc_emails:
                for email in cc_emails:
                    message.add_cc(email)

            sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            response = sg.send(message)
            return jsonify({"status": "Email sent", "code": response.status_code}), 200

        except Exception as e:
            return jsonify({"error": str(e)}), 500