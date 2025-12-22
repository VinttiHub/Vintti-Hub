from flask import Blueprint, jsonify, request

from db import get_connection

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    email = data.get("email")
    password = data.get("password")

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT nickname FROM users
            WHERE email_vintti = %s AND password = %s
            """,
            (email, password)
        )
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            return jsonify({"success": True, "nickname": result[0]})
        return jsonify({"success": False, "message": "Correo o contraseña incorrectos"}), 401
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
