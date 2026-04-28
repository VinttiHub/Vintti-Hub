import uuid
from datetime import datetime
import re
import requests

from flask import Blueprint, jsonify, request
from psycopg2.extras import Json, RealDictCursor

from db import get_connection


bp = Blueprint('public_reference_feedback', __name__, url_prefix='/public/reference_feedback')
_DIV_TAG_RE = re.compile(r'</?div\b[^>]*>', flags=re.I)


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


def _strip_tagged_div(html, marker):
    content = html or ''
    marker = (marker or '').lower()
    while True:
        match = None
        for tag_match in _DIV_TAG_RE.finditer(content):
            tag_text = tag_match.group(0).lower()
            if tag_text.startswith('<div') and marker in tag_text:
                match = tag_match
                break
        if not match:
            return content.strip()

        depth = 1
        end_index = None
        for tag_match in _DIV_TAG_RE.finditer(content, match.end()):
            tag_text = tag_match.group(0).lower()
            if tag_text.startswith('</div'):
                depth -= 1
                if depth == 0:
                    end_index = tag_match.end()
                    break
            else:
                depth += 1

        if end_index is None:
            content = content[:match.start()]
            continue

        content = (content[:match.start()] + content[end_index:]).strip()


def _strip_feedback_notes(html):
    return _strip_tagged_div(html, 'data-reference-feedback-notes="true"')


def _build_feedback_notes_html(rows):
    sections = []
    for row in rows or []:
        questions = row.get('questions') or []
        answers = row.get('answers') or []
        if not questions or not answers:
            continue
        reference_name = _escape_html(row.get('reference_name')) if row.get('reference_name') else ''
        reference_title = f'Reference {row["reference_number"]}'
        if reference_name:
            reference_title = f'{reference_title} - {reference_name}'
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
                f'<p><strong>{reference_title}</strong></p>'
                f'{"<br>".join(qa_lines)}'
                f'</section>'
            )
        )
    if not sections:
        return ''
    return f'<div data-reference-feedback-notes="true">{"<br>".join(sections)}</div>'


def _merge_feedback_into_notes(existing_notes, feedback_rows):
    base_notes = _strip_feedback_notes(existing_notes or '')
    feedback_html = _build_feedback_notes_html(feedback_rows)
    return '<br>'.join(part for part in [base_notes, feedback_html] if part)


def _send_email(subject, html_body, recipients):
    clean_recipients = []
    seen = set()
    for value in recipients or []:
        email = str(value or '').strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        clean_recipients.append(email)
    if not clean_recipients:
        return False
    payload = {'to': clean_recipients, 'subject': subject, 'body': html_body}
    try:
        resp = requests.post(
            'https://7m6mw95m8y.us-east-2.awsapprunner.com/send_email',
            json=payload,
            timeout=30,
        )
        return resp.ok
    except Exception:
        return False


def _fetch_reference_feedback_email_context(cur, candidate_id, opportunity_id=None):
    if opportunity_id:
        cur.execute(
            """
            SELECT
                c.name AS candidate_name,
                o.opportunity_id,
                o.opp_position_name,
                o.opp_hr_lead,
                COALESCE(a.client_name, 'Client') AS account_name
            FROM candidates c
            LEFT JOIN opportunity o ON o.opportunity_id = %s
            LEFT JOIN account a ON a.account_id = o.account_id
            WHERE c.candidate_id = %s
            LIMIT 1
            """,
            (opportunity_id, candidate_id),
        )
        row = cur.fetchone()
        if row:
            return row

    cur.execute(
        """
        SELECT
            c.name AS candidate_name,
            o.opportunity_id,
            o.opp_position_name,
            o.opp_hr_lead,
            COALESCE(a.client_name, 'Client') AS account_name
        FROM candidates c
        LEFT JOIN hire_opportunity ho ON ho.candidate_id = c.candidate_id
        LEFT JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
        LEFT JOIN account a ON a.account_id = o.account_id
        WHERE c.candidate_id = %s
        ORDER BY ho.start_date DESC NULLS LAST, ho.hire_opp_id DESC
        LIMIT 1
        """,
        (candidate_id,),
    )
    return cur.fetchone()


def _render_feedback_reference_card(row):
    questions = row.get('questions') or []
    answers = row.get('answers') or []
    qa_items = []
    for index, question in enumerate(questions):
        answer = answers[index] if index < len(answers) else ''
        qa_items.append(
            f"""
            <div style="margin-top:12px;padding-top:12px;border-top:1px solid #e4ebfb;">
              <div style="font-weight:700;color:#50607f;margin-bottom:4px;">Question {index + 1}</div>
              <div style="margin-bottom:8px;">{_escape_html(question)}</div>
              <div style="font-weight:700;color:#50607f;margin-bottom:4px;">Feedback</div>
              <div>{_escape_html(answer) or '—'}</div>
            </div>
            """
        )
    return f"""
    <div style="margin:16px 0;padding:18px;border:1px solid #dbe6ff;border-radius:18px;background:#f8fbff;">
      <div style="font-weight:800;font-size:18px;margin-bottom:12px;">Reference {row.get('reference_number') or '—'}</div>
      <div><b>Name:</b> {_escape_html(row.get('reference_name') or '—')}</div>
      <div><b>Position:</b> {_escape_html(row.get('reference_position') or '—')}</div>
      <div><b>Phone:</b> {_escape_html(row.get('reference_phone') or '—')}</div>
      <div><b>Email:</b> {_escape_html(row.get('reference_email') or '—')}</div>
      <div><b>LinkedIn:</b> {_escape_html(row.get('reference_linkedin') or '—')}</div>
      {''.join(qa_items)}
    </div>
    """


def _reference_feedback_email_html(ctx, feedback_rows):
    sections = ''.join(_render_feedback_reference_card(row) for row in feedback_rows or [])
    return f"""
    <div style="font-family:Arial,sans-serif;color:#172036;line-height:1.5;">
      <h2 style="margin:0 0 12px;">Reference feedback received</h2>
      <p style="margin:0 0 10px;"><b>Candidate:</b> {_escape_html(ctx.get('candidate_name') or 'Candidate')}</p>
      <p style="margin:0 0 10px;"><b>Opportunity:</b> {_escape_html(ctx.get('opp_position_name') or '—')}</p>
      <p style="margin:0 0 10px;"><b>Account:</b> {_escape_html(ctx.get('account_name') or '—')}</p>
      {sections}
    </div>
    """


def _send_reference_feedback_notifications(cur, candidate_id, opportunity_id, submitted_reference_number):
    ctx = _fetch_reference_feedback_email_context(cur, candidate_id, opportunity_id)
    if not ctx:
        return

    hr_lead = str(ctx.get('opp_hr_lead') or '').strip().lower()
    recipients = ['pgonzales@vintti.com']
    if hr_lead:
        recipients.insert(0, hr_lead)

    cur.execute(
        """
        SELECT
            reference_number,
            reference_name,
            reference_position,
            reference_email,
            reference_phone,
            reference_linkedin,
            questions,
            answers,
            submitted_at,
            updated_at
        FROM reference_feedback_requests
        WHERE candidate_id = %s
          AND submitted_at IS NOT NULL
        ORDER BY reference_number ASC, updated_at DESC
        """,
        (candidate_id,),
    )
    submitted_rows = cur.fetchall() or []
    latest_by_reference = {}
    for row in submitted_rows:
        latest_by_reference.setdefault(row['reference_number'], row)

    if submitted_reference_number not in latest_by_reference:
        return

    candidate_name = ctx.get('candidate_name') or 'Candidate'
    opportunity_name = ctx.get('opp_position_name') or 'Opportunity'

    if len(latest_by_reference) >= 2:
        subject = f"Reference feedback completed for {candidate_name} • {opportunity_name}"
        rows_for_email = [latest_by_reference[idx] for idx in (1, 2) if idx in latest_by_reference]
    else:
        subject = f"Reference {submitted_reference_number} feedback completed for {candidate_name} • {opportunity_name}"
        rows_for_email = [latest_by_reference[submitted_reference_number]]

    _send_email(subject, _reference_feedback_email_html(ctx, rows_for_email), recipients)


def _sync_feedback_notes_to_candidate_and_hire(cur, candidate_id, opportunity_id=None):
    cur.execute(
        """
        SELECT references_notes
        FROM candidates
        WHERE candidate_id = %s
        LIMIT 1
        """,
        (candidate_id,),
    )
    candidate_row = cur.fetchone() or {}

    cur.execute(
        """
        SELECT reference_number, reference_name, questions, answers
        FROM reference_feedback_requests
        WHERE candidate_id = %s
          AND submitted_at IS NOT NULL
        ORDER BY reference_number ASC, updated_at ASC
        """,
        (candidate_id,),
    )
    feedback_rows = cur.fetchall()
    merged_notes = _merge_feedback_into_notes(candidate_row.get('references_notes') or '', feedback_rows)

    cur.execute(
        """
        UPDATE candidates
        SET references_notes = %s
        WHERE candidate_id = %s
        """,
        (merged_notes, candidate_id),
    )

    if opportunity_id:
        cur.execute(
            """
            UPDATE hire_opportunity
            SET references_notes = %s
            WHERE candidate_id = %s
              AND opportunity_id = %s
            """,
            (merged_notes, candidate_id, opportunity_id),
        )
    else:
        cur.execute(
            """
            UPDATE hire_opportunity
            SET references_notes = %s
            WHERE candidate_id = %s
            """,
            (merged_notes, candidate_id),
        )


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
        public_token = str(uuid.uuid4())
        params = (
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
        )
        if opportunity_id is None:
            cur.execute(
                """
                WITH existing AS (
                    SELECT request_id
                    FROM reference_feedback_requests
                    WHERE candidate_id = %s
                      AND opportunity_id IS NULL
                      AND reference_number = %s
                    ORDER BY updated_at DESC
                    LIMIT 1
                ),
                updated AS (
                    UPDATE reference_feedback_requests
                    SET public_token = %s,
                        reference_name = %s,
                        reference_position = %s,
                        reference_email = %s,
                        reference_phone = %s,
                        reference_linkedin = %s,
                        candidate_name = %s,
                        questions = %s,
                        answers = '[]'::jsonb,
                        submitted_at = NULL,
                        updated_at = NOW()
                    WHERE request_id IN (SELECT request_id FROM existing)
                    RETURNING *
                ),
                inserted AS (
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
                    SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '[]'::jsonb, NULL, NOW()
                    WHERE NOT EXISTS (SELECT 1 FROM existing)
                    RETURNING *
                )
                SELECT * FROM updated
                UNION ALL
                SELECT * FROM inserted
                LIMIT 1
                """,
                (
                    candidate_id,
                    reference_number,
                    public_token,
                    params[4],
                    params[5],
                    params[6],
                    params[7],
                    params[8],
                    params[9],
                    params[10],
                    *params,
                ),
            )
        else:
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
                params,
            )
        row = cur.fetchone()

        _sync_feedback_notes_to_candidate_and_hire(
            cur,
            candidate_id=row['candidate_id'],
            opportunity_id=row.get('opportunity_id'),
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

        _sync_feedback_notes_to_candidate_and_hire(
            cur,
            candidate_id=updated['candidate_id'],
            opportunity_id=updated.get('opportunity_id'),
        )
        _send_reference_feedback_notifications(
            cur,
            candidate_id=updated['candidate_id'],
            opportunity_id=updated.get('opportunity_id'),
            submitted_reference_number=updated['reference_number'],
        )

        conn.commit()
        return jsonify(_serialize_row(updated))
    except Exception as exc:
        conn.rollback()
        return jsonify({'error': str(exc)}), 500
    finally:
        cur.close()
        conn.close()


@bp.route('/direct_submit', methods=['POST', 'OPTIONS'])
def direct_submit_reference_feedback():
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

    questions = _clean_list(data.get('questions'))
    answers = _clean_list(data.get('answers'))
    if not questions:
        return jsonify({'error': 'At least one question is required'}), 400
    if len(questions) != len(answers):
        return jsonify({'error': 'answers count must match questions count'}), 400

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        public_token = str(uuid.uuid4())
        submitted_at = datetime.utcnow()
        params = (
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
            Json(answers),
            submitted_at,
        )

        if opportunity_id is None:
            cur.execute(
                """
                WITH existing AS (
                    SELECT request_id
                    FROM reference_feedback_requests
                    WHERE candidate_id = %s
                      AND opportunity_id IS NULL
                      AND reference_number = %s
                    ORDER BY updated_at DESC
                    LIMIT 1
                ),
                updated AS (
                    UPDATE reference_feedback_requests
                    SET public_token = %s,
                        reference_name = %s,
                        reference_position = %s,
                        reference_email = %s,
                        reference_phone = %s,
                        reference_linkedin = %s,
                        candidate_name = %s,
                        questions = %s,
                        answers = %s,
                        submitted_at = %s,
                        updated_at = NOW()
                    WHERE request_id IN (SELECT request_id FROM existing)
                    RETURNING *
                ),
                inserted AS (
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
                    SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                    WHERE NOT EXISTS (SELECT 1 FROM existing)
                    RETURNING *
                )
                SELECT * FROM updated
                UNION ALL
                SELECT * FROM inserted
                LIMIT 1
                """,
                (
                    candidate_id,
                    reference_number,
                    public_token,
                    params[4],
                    params[5],
                    params[6],
                    params[7],
                    params[8],
                    params[9],
                    params[10],
                    params[11],
                    params[12],
                    *params,
                ),
            )
        else:
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
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
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
                    answers = EXCLUDED.answers,
                    submitted_at = EXCLUDED.submitted_at,
                    updated_at = NOW()
                RETURNING *
                """,
                params,
            )

        row = cur.fetchone()
        _sync_feedback_notes_to_candidate_and_hire(
            cur,
            candidate_id=row['candidate_id'],
            opportunity_id=row.get('opportunity_id'),
        )
        _send_reference_feedback_notifications(
            cur,
            candidate_id=row['candidate_id'],
            opportunity_id=row.get('opportunity_id'),
            submitted_reference_number=row['reference_number'],
        )
        conn.commit()
        return jsonify(_serialize_row(row))
    except Exception as exc:
        conn.rollback()
        return jsonify({'error': str(exc)}), 500
    finally:
        cur.close()
        conn.close()
