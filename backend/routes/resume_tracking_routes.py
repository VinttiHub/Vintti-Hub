"""Resume view tracking.

Logs every open of a candidate's read-only CV link
(`resume-readonly.html?id=<candidate_id>`). The link itself is unchanged — tracking
keys off the candidate id, so the team can see whether a shared CV was opened by the
client, how many times, and when.

Opens by logged-in Hub users (the team previewing the CV) are flagged is_internal and
excluded from the client-facing counts.
"""

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_connection


bp = Blueprint('resume_tracking', __name__, url_prefix='/resume-tracking')


def _client_ip():
    # Behind App Runner the real client IP is in X-Forwarded-For (first hop).
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr


@bp.route('/view', methods=['POST', 'OPTIONS'])
def log_view():
    """Public beacon fired when a read-only CV link is opened."""
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    try:
        candidate_id = int(data.get('candidate_id'))
    except (TypeError, ValueError):
        # Nothing to attribute — accept silently so the beacon never errors client-side.
        return ('', 204)

    is_internal = bool(data.get('internal'))

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO resume_view_events
                (candidate_id, is_internal, ip_address, user_agent, referrer)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                candidate_id,
                is_internal,
                _client_ip(),
                request.headers.get('User-Agent'),
                request.headers.get('Referer'),
            ),
        )
        conn.commit()
        return ('', 204)
    except Exception:
        conn.rollback()
        # Tracking must never break the client experience.
        return ('', 204)
    finally:
        cur.close()
        conn.close()


def _summarize(cur, candidate_ids):
    """Return {candidate_id(str): {view_count, first_viewed_at, last_viewed_at}} for
    external (client) views only."""
    if not candidate_ids:
        return {}
    cur.execute(
        """
        SELECT
            candidate_id,
            COUNT(*)       AS view_count,
            MIN(viewed_at) AS first_viewed_at,
            MAX(viewed_at) AS last_viewed_at
        FROM resume_view_events
        WHERE candidate_id = ANY(%s)
          AND is_internal = FALSE
        GROUP BY candidate_id
        """,
        (candidate_ids,),
    )
    out = {}
    for row in cur.fetchall() or []:
        out[str(row['candidate_id'])] = {
            'candidate_id': row['candidate_id'],
            'view_count': row['view_count'],
            'first_viewed_at': row['first_viewed_at'].isoformat() if row['first_viewed_at'] else None,
            'last_viewed_at': row['last_viewed_at'].isoformat() if row['last_viewed_at'] else None,
        }
    return out


@bp.route('/candidate/<int:candidate_id>', methods=['GET'])
def candidate_views(candidate_id):
    """View summary for a single candidate (drives the candidate-page indicator)."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        summary = _summarize(cur, [candidate_id])
        return jsonify(summary.get(str(candidate_id)) or {
            'candidate_id': candidate_id,
            'view_count': 0,
            'first_viewed_at': None,
            'last_viewed_at': None,
        })
    finally:
        cur.close()
        conn.close()


@bp.route('/candidates', methods=['GET'])
def candidates_views():
    """Batch view summary for many candidates (drives the opportunity-page badges).

    Query: /resume-tracking/candidates?ids=1,2,3
    """
    raw = request.args.get('ids', '')
    ids = []
    for part in raw.split(','):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        return jsonify({'candidates': _summarize(cur, ids)})
    finally:
        cur.close()
        conn.close()
