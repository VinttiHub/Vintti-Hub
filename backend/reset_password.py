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
            raw = request.data
            app.logger.info("📦 Raw body en reset_request: %r", raw)

            data = request.get_json(silent=True) or {}
            app.logger.info("📦 JSON recibido en reset_request (parsed): %s", data)
        except Exception as e:
            app.logger.error("❌ Error leyendo JSON en /password_reset_request")
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

        # --- Email en HTML (incluye botón, link y el token como texto) ---
        html_body = f"""
<div style="font-family:Inter, Arial, sans-serif; font-size:14px; color:#222; line-height:1.5;">
  <p>Hi there 🌸</p>
  <p>We received a request to reset your password for <strong>Vintti HUB</strong>.</p>
  <p>You can reset it by clicking this button:</p>
  <p style="margin:16px 0;">
    <a href="{reset_link}"
       style="display:inline-block;padding:10px 18px;border-radius:999px;
              background:#6c5ce7;color:white;text-decoration:none;font-weight:600;">
      Reset your password
    </a>
  </p>
  <p>If the button doesn’t work, copy and paste this link in your browser:</p>
  <p style="word-break:break-all;font-size:12px;color:#555;">{reset_link}</p>
  <p>Reset token (for support):</p>
  <p style="font-family:monospace;font-size:12px;background:#f5f5f5;padding:8px;border-radius:6px;">
    {token}
  </p>
  <p style="margin-top:16px;font-size:12px;color:#777;">
    If you did not request this, you can safely ignore this email.
  </p>
  <p style="margin-top:16px">— Vintti HUB</p>
</div>
""".strip()

        # --- Enviar correo de reset DIRECTO con SendGrid (sin pasar por /send_email) ---
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail, Email

            # Versión texto plano simple (para el preview del email)
            plain_body = f"""
Hi there,

We received a request to reset your password for Vintti HUB.

You can reset it using this link:
{reset_link}

If you did not request this, you can safely ignore this email.

— Vintti HUB
""".strip()

            api_key = os.environ.get("SENDGRID_API_KEY")
            if not api_key:
                app.logger.error("🛑 No se encontró SENDGRID_API_KEY; no se puede enviar el reset email")
            else:
                message = Mail(
                    from_email=Email("hub@vintti-hub.com", name="Vintti HUB"),
                    to_emails=[email],
                    subject="Reset your Vintti HUB password",
                    plain_text_content=plain_body,
                    html_content=html_body,  # el HTML lindo que ya armaste arriba
                )

                sg = SendGridAPIClient(api_key)
                sg_resp = sg.send(message)
                app.logger.info("✅ Reset email enviado. Status=%s", sg_resp.status_code)

        except Exception as e:
            app.logger.error("❌ Failed to send password reset email")
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
            raw = request.data
            app.logger.info("📦 Raw body en reset_confirm: %r", raw)

            data = request.get_json(silent=True) or {}
            app.logger.info("📦 JSON recibido en reset_confirm (parsed): %s", data)
        except Exception as e:
            app.logger.error("❌ Error leyendo JSON en /password_reset_confirm")
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
