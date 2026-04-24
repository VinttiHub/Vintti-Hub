from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request
from flask_cors import CORS

from admin_routes import bp as admin_bp
from ai_candidate_search_routes import bp_candidate_search
from ai_routes import register_ai_routes
from coresignal_routes import bp as coresignal_bp
from interviewing_routes import register_interviewing_routes
from profile_routes import bp as profile_bp, users_bp as profile_users_bp
from recruiter_metrics_routes import register_recruiter_metrics_routes
from reminders_routes import bp as reminders_bp
from reset_password import register_password_reset_routes
from send_email_endpoint import register_send_email_route
from utils.services import init_services
from hunter import bp as hunter_bp

from routes.accounts_routes import bp as accounts_bp
from routes.auth_routes import bp as auth_bp
from routes.candidates_routes import bp as candidates_bp
from routes.careers_routes import bp as careers_bp
from routes.applicants_routes import bp as applicants_bp
from routes.metrics_routes import bp as metrics_bp
from routes.system_routes import bp as system_bp
from routes.tracks_routes import bp as tracks_bp
from routes.users_routes import bp as users_api_bp
from routes.moods_routes import bp as moods_bp
from routes.to_do_routes import bp as to_do_bp
from routes.public_bonus_routes import bp as public_bonus_bp
from routes.public_candidate_references_routes import bp as public_candidate_references_bp
from routes.public_reference_feedback_routes import bp as public_reference_feedback_bp
from routes.google_calendar_routes import bp as google_calendar_bp
from routes.hubspot_routes import bp as hubspot_bp
from routes.turvo_routes import bp as turvo_bp
from routes.dashboards_routes import bp as dashboards_bp




def create_app() -> Flask:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    init_services()

    app = Flask(__name__)
    register_ai_routes(app)
    register_password_reset_routes(app)
    register_send_email_route(app)
    register_recruiter_metrics_routes(app)
    register_interviewing_routes(app)

    CORS(
        app,
        resources={
            r"/*": {
                "origins": ["https://vinttihub.vintti.com"],
                "supports_credentials": True,
                "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                "expose_headers": ["Content-Type"],
            }
        },
    )

    app.register_blueprint(system_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(users_api_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(candidates_bp)
    app.register_blueprint(metrics_bp)
    app.register_blueprint(moods_bp)
    app.register_blueprint(tracks_bp)
    app.register_blueprint(careers_bp)
    app.register_blueprint(applicants_bp)
    app.register_blueprint(to_do_bp)
    app.register_blueprint(reminders_bp)
    app.register_blueprint(coresignal_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(profile_users_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(google_calendar_bp)
    app.register_blueprint(hubspot_bp)
    app.register_blueprint(turvo_bp)
    app.register_blueprint(bp_candidate_search, url_prefix="")
    app.register_blueprint(hunter_bp)
    app.register_blueprint(public_bonus_bp)
    app.register_blueprint(public_candidate_references_bp)
    app.register_blueprint(public_reference_feedback_bp)
    app.register_blueprint(dashboards_bp)

    @app.after_request
    def apply_cors_headers(response):
        origin = request.headers.get('Origin')
        allowed_origins = ['https://vinttihub.vintti.com', 'http://localhost:5500', 'http://127.0.0.1:5500']

        if origin in allowed_origins:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'

        response.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,OPTIONS,PATCH,DELETE'

        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization,X-User-Email,X-User-Id'
        return response

    return app


app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
