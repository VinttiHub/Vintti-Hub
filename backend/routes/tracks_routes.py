from flask import Blueprint, jsonify, request

from db import get_connection

bp = Blueprint('tracks', __name__)


@bp.route('/tracks', methods=['POST', 'OPTIONS'])
def create_track():
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    button = data.get('button')

    if user_id is None or button is None:
        return jsonify({'error': 'user_id and button are required'}), 400

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'user_id must be an integer'}), 400

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO tracks (user_id, button, updated_at)
            VALUES (%s, %s, NOW())
            """,
            (user_id, str(button)),
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500
