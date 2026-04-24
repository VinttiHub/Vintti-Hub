import uuid
from datetime import datetime
import re

from flask import Blueprint, jsonify, request
from psycopg2.extras import Json, RealDictCursor

from db import get_connection


bp = Blueprint('public_reference_feedback', __name__, url_prefix='/public/reference_feedback')
_REFERENCE_FEEDBACK_NOTES_RE = re.compile(
    r'<div[^>]*data-reference-feedback-notes="true"[^>]*>.*?</div>',
    flags=re.I | re.S,
)


def _clean_text(value):
    text = str(value or '').strip()
    return text or None


def _clean_list(items):
    cleaned = []
    for item in items or []:
        text = _clean_text(item)
        if text:
            cleaned.append(text)
    return cleaned


def _serialize_row(row):
    if not row:
        return None
    return {
        'request_id': row['request_id'],
        'public_token': str(row['public_token']),
        'candidate_id': row['candidate_id'],
        'opportunity_id': row['opportunity_id'],
        'reference_number': row['reference_number'],
        'reference_name': row.get('reference_name'),
        'reference_position': row.get('reference_position'),
        'reference_email': row.get('reference_email'),
        'reference_phone': row.get('reference_phone'),
        'reference_linkedin': row.get('reference_linkedin'),
        'candidate_name': row.get('candidate_name'),
        'questions': row.get('questions') or [],
        'answers': row.get('answers') or [],
        'submitted_at': row['submitted_at'].isoformat() if row.get('submitted_at') else None,
        'created_at': row['created_at'].isoformat() if row.get('created_at') else None,
        'updated_at': row['updated_at'].isoformat() if row.get('updated_at') else None,
    }


def _escape_html(value):
    return (
        str(value or '')
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&#39;')
    )


def _strip_feedback_notes(html):
    return _REFERENCE_FEEDBACK_NOTES_RE.sub('', html or '').strip()


def _build_feedback_notes_html(rows):
    sections = []
    for row in rows or []:
        questions = row.get('questions') or []
        answers = row.get('answers') or []
        if not questions or not answers:
            continue
        qa_lines = []
        for index, question in enumerate(questions):
            answer = answers[index] if index < len(answers) else ''
            qa_lines.append(
                (
                    f'<div data-reference-feedback-item="{row["reference_number"]}-{index + 1}">'
                    f'<strong>Question -</strong> {_escape_html(question)}<br>'
                    f'<strong>Feedback -</strong> {_escape_html(answer)}'
                    f'</div>'
                )
            )
        sections.append(
            (
                f'<section data-reference-feedback-section="{row["reference_number"]}">'
                f'<p>----------------------------------------</p>'
                f'<p><strong>Reference {row["reference_number"]}'
                f'{f" - {_escape_html(row.get("reference_name"))}" if row.get("reference_name") else ""}'
                f'</strong></p>'
                f'{"<br>".join(qa_lines)}'
                f'</section>'
            )
        )
    if not sections:
        return ''
    return f'<div data-reference-feedback-notes="true">{"<br>".join(sections)}</div>'


@bp.route('/request', methods=['POST', 'OPTIONS'])
def upsert_reference_feedback_request():
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}

    try:
        candidate_id = int(data.get('candidate_id'))
        reference_number = int(data.get('reference_number'))
    except (TypeError, ValueError):
        return jsonify({'error': 'candidate_id and reference_number must be valid integers'}), 400

    opportunity_raw = data.get('opportunity_id')
    if opportunity_raw in (None, ''):
        opportunity_id = None
    else:
        try:
            opportunity_id = int(opportunity_raw)
        except (TypeError, ValueError):
            return jsonify({'error': 'opportunity_id must be a valid integer'}), 400

    if reference_number not in (1, 2):
        return jsonify({'error': 'reference_number must be 1 or 2'}), 400

    questions = _clean_list(data.get('questions'))
    if not questions:
        return jsonify({'error': 'At least one question is required'}), 400

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        public_token = uuid.uuid4()
        cur.execute(
            """
            INSERT INTO reference_feedback_requests (
                public_token,
                candidate_id,
                opportunity_id,
                reference_number,
                reference_name,
                reference_position,
                reference_email,
                reference_phone,
                reference_linkedin,
                candidate_name,
                questions,
                answers,
                submitted_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '[]'::jsonb, NULL, NOW())
            ON CONFLICT (candidate_id, opportunity_id, reference_number)
            DO UPDATE SET
                public_token = EXCLUDED.public_token,
                reference_name = EXCLUDED.reference_name,
                reference_position = EXCLUDED.reference_position,
                reference_email = EXCLUDED.reference_email,
                reference_phone = EXCLUDED.reference_phone,
                reference_linkedin = EXCLUDED.reference_linkedin,
                candidate_name = EXCLUDED.candidate_name,
                questions = EXCLUDED.questions,
                answers = '[]'::jsonb,
                submitted_at = NULL,
                updated_at = NOW()
            RETURNING *
            """,
            (
                public_token,
                candidate_id,
                opportunity_id,
                reference_number,
                _clean_text(data.get('reference_name')),
                _clean_text(data.get('reference_position')),
                _clean_text(data.get('reference_email')),
                _clean_text(data.get('reference_phone')),
                _clean_text(data.get('reference_linkedin')),
                _clean_text(data.get('candidate_name')),
                Json(questions),
            ),
        )
        row = cur.fetchone()

        if row.get('opportunity_id'):
            cur.execute(
                """
                SELECT references_notes
                FROM hire_opportunity
                WHERE candidate_id = %s
                  AND opportunity_id = %s
                LIMIT 1
                """,
                (row['candidate_id'], row['opportunity_id']),
            )
            hire_row = cur.fetchone() or {}
            base_notes = _strip_feedback_notes(hire_row.get('references_notes') or '')

            cur.execute(
                """
                SELECT reference_number, reference_name, questions, answers
                FROM reference_feedback_requests
                WHERE candidate_id = %s
                  AND opportunity_id = %s
                  AND submitted_at IS NOT NULL
                ORDER BY reference_number ASC, updated_at ASC
                """,
                (row['candidate_id'], row['opportunity_id']),
            )
            feedback_rows = cur.fetchall()
            feedback_html = _build_feedback_notes_html(feedback_rows)
            merged_notes = '<br>'.join(part for part in [base_notes, feedback_html] if part)

            cur.execute(
                """
                UPDATE hire_opportunity
                SET references_notes = %s
                WHERE candidate_id = %s
                  AND opportunity_id = %s
                """,
                (merged_notes, row['candidate_id'], row['opportunity_id']),
            )

        conn.commit()

        payload = _serialize_row(row)
        payload['public_url'] = f"https://vinttihub.vintti.com/reference-feedback-form.html?t={payload['public_token']}"
        return jsonify(payload)
    except Exception as exc:
        conn.rollback()
        return jsonify({'error': str(exc)}), 500
    finally:
        cur.close()
        conn.close()


@bp.route('/candidate', methods=['GET'])
def list_reference_feedback_requests():
    candidate_id = request.args.get('candidate_id', type=int)
    if not candidate_id:
        return jsonify({'error': 'candidate_id is required'}), 400

    opportunity_id = request.args.get('opportunity_id', type=int)

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if opportunity_id:
            cur.execute(
                """
                SELECT *
                FROM reference_feedback_requests
                WHERE candidate_id = %s
                  AND opportunity_id = %s
                ORDER BY reference_number ASC
                """,
                (candidate_id, opportunity_id),
            )
        else:
            cur.execute(
                """
                SELECT DISTINCT ON (reference_number) *
                FROM reference_feedback_requests
                WHERE candidate_id = %s
                ORDER BY reference_number ASC, updated_at DESC
                """,
                (candidate_id,),
            )
        rows = cur.fetchall()
        items = [_serialize_row(row) for row in rows]
        for item in items:
            item['public_url'] = f"https://vinttihub.vintti.com/reference-feedback-form.html?t={item['public_token']}"
        return jsonify({'items': items})
    finally:
        cur.close()
        conn.close()


@bp.route('/context', methods=['GET'])
def get_reference_feedback_context():
    token = request.args.get('t')
    if not token:
        return jsonify({'error': 'token is required'}), 400

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """
            SELECT *
            FROM reference_feedback_requests
            WHERE public_token = %s
            LIMIT 1
            """,
            (token,),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({'error': 'request not found'}), 404
        return jsonify(_serialize_row(row))
    finally:
        cur.close()
        conn.close()


@bp.route('/submit', methods=['POST', 'OPTIONS'])
def submit_reference_feedback():
    if request.method == 'OPTIONS':
        return ('', 204)

    token = request.args.get('t')
    if not token:
        return jsonify({'error': 'token is required'}), 400

    data = request.get_json(silent=True) or {}
    answers = _clean_list(data.get('answers'))

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """
            SELECT request_id, candidate_id, opportunity_id, questions
            FROM reference_feedback_requests
            WHERE public_token = %s
            LIMIT 1
            """,
            (token,),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({'error': 'request not found'}), 404

        questions = row.get('questions') or []
        if len(answers) != len(questions):
            return jsonify({'error': 'answers count must match questions count'}), 400

        submitted_at = datetime.utcnow()
        cur.execute(
            """
            UPDATE reference_feedback_requests
            SET answers = %s,
                submitted_at = %s,
                updated_at = NOW()
            WHERE request_id = %s
            RETURNING *
            """,
            (Json(answers), submitted_at, row['request_id']),
        )
        updated = cur.fetchone()

        if updated.get('opportunity_id'):
            cur.execute(
                """
                SELECT references_notes
                FROM hire_opportunity
                WHERE candidate_id = %s
                  AND opportunity_id = %s
                LIMIT 1
                """,
                (updated['candidate_id'], updated['opportunity_id']),
            )
            hire_row = cur.fetchone() or {}
            base_notes = _strip_feedback_notes(hire_row.get('references_notes') or '')

            cur.execute(
                """
                SELECT reference_number, reference_name, questions, answers
                FROM reference_feedback_requests
                WHERE candidate_id = %s
                  AND opportunity_id = %s
                  AND submitted_at IS NOT NULL
                ORDER BY reference_number ASC, updated_at ASC
                """,
                (updated['candidate_id'], updated['opportunity_id']),
            )
            feedback_rows = cur.fetchall()
            feedback_html = _build_feedback_notes_html(feedback_rows)
            merged_notes = '<br>'.join(part for part in [base_notes, feedback_html] if part)

            cur.execute(
                """
                UPDATE hire_opportunity
                SET references_notes = %s
                WHERE candidate_id = %s
                  AND opportunity_id = %s
                """,
                (merged_notes, updated['candidate_id'], updated['opportunity_id']),
            )

        conn.commit()
        return jsonify(_serialize_row(updated))
    except Exception as exc:
        conn.rollback()
        return jsonify({'error': str(exc)}), 500
    finally:
        cur.close()
        conn.close()
