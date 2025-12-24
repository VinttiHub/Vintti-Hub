from flask import Blueprint, jsonify, request

from admin_access import ensure_admin_user_access_table
from db import get_connection

bp = Blueprint('auth', __name__)

ensure_admin_user_access_table()


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
            SELECT u.nickname
            FROM users u
            LEFT JOIN admin_user_access aua ON aua.user_id = u.user_id
            WHERE LOWER(u.email_vintti) = LOWER(%s)
              AND u.password = %s
              AND COALESCE(aua.is_active, TRUE)
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
