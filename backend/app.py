from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from flask import Flask, request
from flask_cors import CORS

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

from routes.accounts_routes import bp as accounts_bp
from routes.auth_routes import bp as auth_bp
from routes.candidates_routes import bp as candidates_bp
from routes.careers_routes import bp as careers_bp
from routes.metrics_routes import bp as metrics_bp
from routes.system_routes import bp as system_bp
from routes.users_routes import bp as users_api_bp


def create_app() -> Flask:
    load_dotenv()
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
    app.register_blueprint(careers_bp)
    app.register_blueprint(reminders_bp)
    app.register_blueprint(coresignal_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(profile_users_bp)
    app.register_blueprint(bp_candidate_search, url_prefix="")

    @app.after_request
    def apply_cors_headers(response):
        origin = request.headers.get('Origin')
        allowed_origins = ['https://vinttihub.vintti.com', 'http://localhost:5500', 'http://127.0.0.1:5500']

        if origin in allowed_origins:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'

        response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS,PATCH,DELETE'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        return response

    return app


app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
