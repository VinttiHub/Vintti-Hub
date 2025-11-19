from flask import request, jsonify, make_response
import os, secrets, logging, traceback
from datetime import datetime, timedelta, timezone
from db import get_connection  
import requests
import json

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
            url = f"{base}/send_email"
            payload = {
                "to": [email],
                "subject": "Reset your Vintti HUB password",
                "body": body,
            }

            app.logger.info("📨 Llamando a %s con payload: %s", url, payload)

            resp = requests.post(
                url,
                data=json.dumps(payload),                    # 👈 cuerpo JSON explícito
                headers={"Content-Type": "application/json"},# 👈 igual que tu fetch
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
