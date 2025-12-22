from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_connection

bp = Blueprint('users_basic', __name__)


@bp.route('/users')
def users_list_or_by_email():
    """
    GET /users
    - sin params -> lista usuarios (campos clave, incluye user_id)
    - ?email=foo@bar.com -> filtra por email exacto (case-insensitive)
    """
    email = request.args.get("email")

    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            base_select = """
                SELECT
                  user_id,
                  user_name,
                  email_vintti,
                  role,
                  emergency_contact,
                  ingreso_vintti_date,
                  fecha_nacimiento,
                  avatar_url
                FROM users
            """

            if email:
                cur.execute(base_select + " WHERE LOWER(email_vintti) = LOWER(%s)", (email,))
            else:
                cur.execute(base_select)

            rows = cur.fetchall()

        conn.close()

        def _normalize_dates(row):
            for key in ("ingreso_vintti_date", "fecha_nacimiento"):
                value = row.get(key)
                if hasattr(value, "isoformat"):
                    row[key] = value.isoformat()
                elif isinstance(value, str) and len(value) >= 10:
                    row[key] = value[:10]
            return row

        return jsonify([_normalize_dates(dict(row)) for row in rows])

    except Exception as exc:
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(exc)}), 500
