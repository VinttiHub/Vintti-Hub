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


def _list_users_by_role(role_type: str):
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    u.user_id,
                    u.user_name,
                    u.email_vintti,
                    ur.role_type
                FROM user_roles ur
                JOIN users u ON u.user_id = ur.user_id
                LEFT JOIN admin_user_access aua ON aua.user_id = u.user_id
                WHERE ur.role_type = %s
                  AND COALESCE(aua.is_active, TRUE)
                ORDER BY LOWER(u.user_name), LOWER(u.email_vintti)
                """,
                (role_type,),
            )
            rows = cur.fetchall()
        conn.close()
        return jsonify(rows)
    except Exception as exc:
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(exc)}), 500


@bp.route('/users/recruiters')
def list_recruiters():
    return _list_users_by_role('recruiter')


@bp.route('/users/sales-leads')
def list_sales_leads():
    """
    Returns the distinct Sales Leads detected in the CRM accounts table.
    The list is derived from accounts so filters always show active owners.
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                WITH normalized AS (
                  SELECT
                    LOWER(TRIM(a.account_manager)) AS email,
                    MAX(NULLIF(TRIM(a.account_manager_name), '')) AS fallback_name
                  FROM account a
                  WHERE a.account_manager IS NOT NULL
                    AND TRIM(a.account_manager) <> ''
                  GROUP BY 1
                )
                SELECT
                  n.email,
                  COALESCE(NULLIF(u.user_name, ''), n.fallback_name, n.email) AS user_name
                FROM normalized n
                LEFT JOIN users u ON LOWER(TRIM(u.email_vintti)) = n.email
                ORDER BY COALESCE(NULLIF(u.user_name, ''), n.fallback_name, n.email) ASC;
            """)
            rows = cur.fetchall() or []
        return jsonify(rows), 200
    except Exception as exc:
        print("Error fetching sales leads:", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        if conn:
            conn.close()
