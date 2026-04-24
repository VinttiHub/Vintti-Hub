import re

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_connection


bp = Blueprint('public_candidate_references', __name__, url_prefix='/public/candidate_references')

_STRUCTURED_REFS_RE = re.compile(
    r'<div[^>]*data-structured-references="true"[^>]*>.*?</div>',
    flags=re.I | re.S,
)


def _escape_html(value):
    return (
        str(value or '')
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&#39;')
    )


def _strip_structured_references_html(html):
    return _STRUCTURED_REFS_RE.sub('', html or '').strip()


def _build_structured_references_html(data):
    refs = []
    for idx in (1, 2):
        fields = [
            ('Name', f'reference_{idx}_name'),
            ('Position', f'reference_{idx}_position'),
            ('Phone', f'reference_{idx}_phone'),
            ('Email', f'reference_{idx}_email'),
            ('LinkedIn', f'reference_{idx}_linkedin'),
        ]
        if not any((data.get(field) or '').strip() for _, field in fields):
            continue
        lines = '<br>'.join(
            f'<span data-reference-field="{field}"><strong>{label}:</strong> {_escape_html((data.get(field) or "").strip() or "-")}</span>'
            for label, field in fields
        )
        refs.append(f'<p><strong>Reference {idx}</strong><br>{lines}</p>')
    if not refs:
        return ''
    return f'<div data-structured-references="true">{"".join(refs)}</div>'


def _resolve_candidate_hire(cur, candidate_id, opportunity_id=None):
    if opportunity_id:
        cur.execute(
            """
            SELECT
                ho.candidate_id,
                ho.opportunity_id,
                ho.account_id,
                c.name AS candidate_name,
                a.client_name AS account_name
            FROM hire_opportunity ho
            JOIN candidates c ON c.candidate_id = ho.candidate_id
            LEFT JOIN account a ON a.account_id = ho.account_id
            WHERE ho.candidate_id = %s
              AND ho.opportunity_id = %s
            LIMIT 1
            """,
            (candidate_id, opportunity_id),
        )
        row = cur.fetchone()
        if row:
            return row

    cur.execute(
        """
        SELECT
            ho.candidate_id,
            ho.opportunity_id,
            ho.account_id,
            c.name AS candidate_name,
            a.client_name AS account_name
        FROM hire_opportunity ho
        JOIN candidates c ON c.candidate_id = ho.candidate_id
        LEFT JOIN account a ON a.account_id = ho.account_id
        WHERE ho.candidate_id = %s
        ORDER BY ho.start_date DESC NULLS LAST, ho.hire_opp_id DESC
        LIMIT 1
        """,
        (candidate_id,),
    )
    row = cur.fetchone()
    if row:
        return row

    cur.execute(
        """
        SELECT c.candidate_id, c.name AS candidate_name
        FROM candidates c
        WHERE c.candidate_id = %s
        LIMIT 1
        """,
        (candidate_id,),
    )
    candidate_row = cur.fetchone()
    if not candidate_row:
        return None

    return {
        'candidate_id': candidate_row['candidate_id'],
        'candidate_name': candidate_row['candidate_name'],
        'opportunity_id': None,
        'account_id': None,
        'account_name': None,
    }


@bp.route('/context', methods=['GET'])
def public_candidate_references_context():
    candidate_id = request.args.get('candidate_id', type=int)
    opportunity_id = request.args.get('opportunity_id', type=int)
    if not candidate_id:
        return jsonify({'error': 'candidate_id is required'}), 400

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        hire = _resolve_candidate_hire(cur, candidate_id, opportunity_id)
        if not hire:
            return jsonify({'error': 'candidate not found'}), 404

        if hire.get('opportunity_id'):
            cur.execute(
                """
                SELECT
                    reference_1_name,
                    reference_1_phone,
                    reference_1_email,
                    reference_1_linkedin,
                    reference_1_position,
                    reference_2_name,
                    reference_2_phone,
                    reference_2_email,
                    reference_2_linkedin,
                    reference_2_position
                FROM hire_opportunity
                WHERE candidate_id = %s
                  AND opportunity_id = %s
                LIMIT 1
                """,
                (candidate_id, hire['opportunity_id']),
            )
            refs = cur.fetchone() or {}
        else:
            refs = {}

        return jsonify({
            'candidate_id': hire['candidate_id'],
            'candidate_name': hire.get('candidate_name'),
            'opportunity_id': hire.get('opportunity_id'),
            'account_id': hire.get('account_id'),
            'account_name': hire.get('account_name'),
            'references': refs,
        })
    finally:
        cur.close()
        conn.close()


@bp.route('/submit', methods=['POST', 'OPTIONS'])
def submit_candidate_references():
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    candidate_id = data.get('candidate_id')
    opportunity_id = data.get('opportunity_id')

    try:
        candidate_id = int(candidate_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'candidate_id must be a valid integer'}), 400

    if opportunity_id not in (None, ''):
        try:
            opportunity_id = int(opportunity_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'opportunity_id must be a valid integer'}), 400
    else:
        opportunity_id = None

    required_fields = [
        'reference_1_name',
        'reference_1_position',
        'reference_1_phone',
        'reference_1_email',
        'reference_1_linkedin',
        'reference_2_name',
        'reference_2_position',
        'reference_2_phone',
        'reference_2_email',
        'reference_2_linkedin',
    ]
    cleaned = {field: str(data.get(field) or '').strip() for field in required_fields}
    missing = [field for field, value in cleaned.items() if not value]
    if missing:
        return jsonify({'error': 'All reference fields are required', 'missing_fields': missing}), 400

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        hire = _resolve_candidate_hire(cur, candidate_id, opportunity_id)
        if not hire:
            return jsonify({'error': 'candidate not found'}), 404
        if not hire.get('opportunity_id'):
            return jsonify({'error': 'No hired opportunity found for this candidate'}), 404

        cur.execute(
            """
            INSERT INTO hire_opportunity (candidate_id, opportunity_id, account_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (candidate_id, opportunity_id) DO NOTHING
            """,
            (candidate_id, hire['opportunity_id'], hire.get('account_id')),
        )

        cur.execute(
            """
            SELECT references_notes
            FROM hire_opportunity
            WHERE candidate_id = %s
              AND opportunity_id = %s
            LIMIT 1
            """,
            (candidate_id, hire['opportunity_id']),
        )
        existing = cur.fetchone() or {}
        manual_notes = _strip_structured_references_html(existing.get('references_notes') or '')
        structured_html = _build_structured_references_html(cleaned)
        merged_notes = '<br>'.join(part for part in [structured_html, manual_notes] if part)

        cur.execute(
            """
            UPDATE hire_opportunity
            SET
                reference_1_name = %s,
                reference_1_position = %s,
                reference_1_phone = %s,
                reference_1_email = %s,
                reference_1_linkedin = %s,
                reference_2_name = %s,
                reference_2_position = %s,
                reference_2_phone = %s,
                reference_2_email = %s,
                reference_2_linkedin = %s,
                references_notes = %s
            WHERE candidate_id = %s
              AND opportunity_id = %s
            """,
            (
                cleaned['reference_1_name'],
                cleaned['reference_1_position'],
                cleaned['reference_1_phone'],
                cleaned['reference_1_email'],
                cleaned['reference_1_linkedin'],
                cleaned['reference_2_name'],
                cleaned['reference_2_position'],
                cleaned['reference_2_phone'],
                cleaned['reference_2_email'],
                cleaned['reference_2_linkedin'],
                merged_notes,
                candidate_id,
                hire['opportunity_id'],
            ),
        )

        conn.commit()
        return jsonify({
            'ok': True,
            'candidate_id': candidate_id,
            'opportunity_id': hire['opportunity_id'],
        })
    except Exception as exc:
        conn.rollback()
        return jsonify({'error': str(exc)}), 500
    finally:
        cur.close()
        conn.close()
