from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_connection

bp = Blueprint('to_do', __name__)


@bp.route('/to_do', methods=['GET', 'POST', 'OPTIONS'])
def to_do_collection():
    if request.method == 'OPTIONS':
        return ('', 204)

    if request.method == 'GET':
        user_id = request.args.get('user_id', type=int)
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        try:
            conn = get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT to_do_id, user_id, description, due_date::text AS due_date, "check"
                FROM to_do
                WHERE user_id = %s
                ORDER BY due_date NULLS LAST, to_do_id ASC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return jsonify(rows)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    description = (data.get('description') or '').strip()
    due_date = data.get('due_date')

    if not user_id or not description or not due_date:
        return jsonify({"error": "user_id, description, and due_date are required"}), 400

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT COALESCE(MAX(to_do_id), 0) + 1 AS next_id FROM to_do")
        next_id = cur.fetchone()['next_id']

        cur.execute(
            """
            INSERT INTO to_do (to_do_id, user_id, description, due_date, "check")
            VALUES (%s, %s, %s, %s, %s)
            RETURNING to_do_id, user_id, description, due_date::text AS due_date, "check"
            """,
            (next_id, user_id, description, due_date, False),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return jsonify(row), 201
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route('/to_do/<int:to_do_id>', methods=['PATCH', 'OPTIONS'])
def to_do_item(to_do_id: int):
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    check_value = data.get('check')

    if user_id is None or check_value is None:
        return jsonify({"error": "user_id and check are required"}), 400

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            UPDATE to_do
            SET "check" = %s
            WHERE to_do_id = %s AND user_id = %s
            RETURNING to_do_id, user_id, description, due_date::text AS due_date, "check"
            """,
            (bool(check_value), to_do_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return jsonify({"error": "to_do item not found"}), 404

        conn.commit()
        cur.close()
        conn.close()
        return jsonify(row)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route('/to_do/team', methods=['GET', 'OPTIONS'])
def to_do_team():
    if request.method == 'OPTIONS':
        return ('', 204)

    leader_id = request.args.get('leader_id', type=int) or request.args.get('user_id', type=int)
    if not leader_id:
        return jsonify({"error": "leader_id is required"}), 400

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT COUNT(*) AS cnt FROM users WHERE lider = %s", (leader_id,))
        if cur.fetchone()['cnt'] == 0:
            cur.close()
            conn.close()
            return jsonify({"error": "forbidden (not a leader of anyone)"}), 403

        cur.execute(
            """
            SELECT
              u.user_id,
              u.user_name,
              u.team,
              t.to_do_id,
              t.description,
              t.due_date::text AS due_date,
              t."check"
            FROM users u
            LEFT JOIN to_do t ON t.user_id = u.user_id
            WHERE u.lider = %s
            ORDER BY LOWER(u.user_name) ASC, t.due_date NULLS LAST, t.to_do_id ASC
            """,
            (leader_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(rows)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
