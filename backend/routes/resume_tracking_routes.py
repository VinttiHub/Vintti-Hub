"""Resume view tracking.

Logs every open of a candidate's read-only CV link
(`resume-readonly.html?id=<candidate_id>`). The link itself is unchanged — tracking
keys off the candidate id, so the team can see whether a shared CV was opened by the
client, how many times, and when.

Opens by logged-in Hub users (the team previewing the CV) are flagged is_internal and
excluded from the client-facing counts.
"""

import requests
from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_connection


bp = Blueprint('resume_tracking', __name__, url_prefix='/resume-tracking')

# Cap geo lookups per detail request so a slow provider can't stall the popover.
_MAX_GEO_LOOKUPS_PER_REQUEST = 12


def _client_ip():
    # Behind App Runner the real client IP is in X-Forwarded-For (first hop).
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr


def _is_public_ip(ip):
    ip = (ip or '').strip()
    if not ip or ip in ('127.0.0.1', '::1', 'localhost'):
        return False
    # Skip obvious private ranges (dev / internal).
    if ip.startswith(('10.', '192.168.', '172.16.', '172.17.', '172.18.', '172.19.',
                      '172.20.', '172.21.', '172.22.', '172.23.', '172.24.', '172.25.',
                      '172.26.', '172.27.', '172.28.', '172.29.', '172.30.', '172.31.',
                      '169.254.', 'fc', 'fd', 'fe80')):
        return False
    return True


def _geo_lookup(ip):
    """Best-effort city/region/country from an IP. Returns a dict (possibly empty)."""
    if not _is_public_ip(ip):
        return {}
    try:
        resp = requests.get(
            f'http://ip-api.com/json/{ip}',
            params={'fields': 'status,country,regionName,city'},
            timeout=3,
        )
        data = resp.json()
        if data.get('status') == 'success':
            return {
                'city': data.get('city') or None,
                'region': data.get('regionName') or None,
                'country': data.get('country') or None,
            }
    except Exception:
        pass
    return {}


def _parse_device(user_agent):
    """Friendly 'OS · Browser' string from a User-Agent."""
    ua = user_agent or ''
    low = ua.lower()
    if 'iphone' in low:
        os_name = 'iPhone'
    elif 'ipad' in low:
        os_name = 'iPad'
    elif 'android' in low:
        os_name = 'Android'
    elif 'windows' in low:
        os_name = 'Windows'
    elif 'mac os' in low or 'macintosh' in low:
        os_name = 'Mac'
    elif 'linux' in low:
        os_name = 'Linux'
    else:
        os_name = None

    if 'edg' in low:
        browser = 'Edge'
    elif 'chrome' in low and 'chromium' not in low:
        browser = 'Chrome'
    elif 'firefox' in low:
        browser = 'Firefox'
    elif 'safari' in low:
        browser = 'Safari'
    else:
        browser = None

    parts = [p for p in (os_name, browser) if p]
    return ' · '.join(parts) if parts else None


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


def _location_str(row):
    parts = [p for p in (row.get('city'), row.get('region'), row.get('country')) if p]
    return ', '.join(parts) if parts else None


@bp.route('/candidate/<int:candidate_id>/events', methods=['GET'])
def candidate_events(candidate_id):
    """Individual external (client) opens for a candidate: time, location, device.

    Resolves any not-yet-checked IPs to a location on the fly and caches the result.
    """
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """
            SELECT id, viewed_at, ip_address, user_agent, city, region, country, geo_checked
            FROM resume_view_events
            WHERE candidate_id = %s
              AND is_internal = FALSE
            ORDER BY viewed_at DESC
            LIMIT 100
            """,
            (candidate_id,),
        )
        rows = cur.fetchall() or []

        # Lazily resolve geolocation for rows we haven't looked up yet (bounded).
        lookups = 0
        for row in rows:
            if row['geo_checked'] or lookups >= _MAX_GEO_LOOKUPS_PER_REQUEST:
                continue
            lookups += 1
            geo = _geo_lookup(row['ip_address'])
            row['city'] = geo.get('city')
            row['region'] = geo.get('region')
            row['country'] = geo.get('country')
            cur.execute(
                """
                UPDATE resume_view_events
                SET city = %s, region = %s, country = %s, geo_checked = TRUE
                WHERE id = %s
                """,
                (row['city'], row['region'], row['country'], row['id']),
            )
        if lookups:
            conn.commit()

        events = [
            {
                'viewed_at': row['viewed_at'].isoformat() if row['viewed_at'] else None,
                'location': _location_str(row),
                'device': _parse_device(row['user_agent']),
            }
            for row in rows
        ]
        return jsonify({'candidate_id': candidate_id, 'events': events})
    finally:
        cur.close()
        conn.close()
