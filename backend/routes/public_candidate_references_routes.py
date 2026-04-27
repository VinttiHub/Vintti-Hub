import re
import requests

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


def _is_reference_complete(data, idx):
    fields = [
        f'reference_{idx}_name',
        f'reference_{idx}_position',
        f'reference_{idx}_phone',
        f'reference_{idx}_email',
        f'reference_{idx}_linkedin',
    ]
    return all(str(data.get(field) or '').strip() for field in fields)


def _merge_reference_payload(existing, incoming):
    merged = dict(existing or {})
    submitted_refs = []
    for idx in (1, 2):
        fields = [
            f'reference_{idx}_name',
            f'reference_{idx}_position',
            f'reference_{idx}_phone',
            f'reference_{idx}_email',
            f'reference_{idx}_linkedin',
        ]
        provided = {field: str(incoming.get(field) or '').strip() for field in fields}
        any_value = any(provided.values())
        if any_value and not all(provided.values()):
            missing = [field for field, value in provided.items() if not value]
            return None, None, {'reference_number': idx, 'missing_fields': missing}
        if any_value:
            merged.update(provided)
            submitted_refs.append(idx)
        else:
            for field in fields:
                merged[field] = str(merged.get(field) or '').strip()
    return merged, submitted_refs, None


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
            "https://7m6mw95m8y.us-east-2.awsapprunner.com/send_email",
            json=payload,
            timeout=30,
        )
        return resp.ok
    except Exception:
        return False


def _fetch_reference_email_context(cur, candidate_id, opportunity_id=None):
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


def _reference_email_html(ctx, merged, refs_to_include):
    sections = []
    for idx in refs_to_include:
        sections.append(
            f"""
            <div style="margin:16px 0;padding:16px;border:1px solid #dbe6ff;border-radius:16px;background:#f8fbff;">
              <div style="font-weight:700;font-size:16px;margin-bottom:10px;">Reference {idx}</div>
              <div><b>Name:</b> {_escape_html(merged.get(f'reference_{idx}_name') or '—')}</div>
              <div><b>Position:</b> {_escape_html(merged.get(f'reference_{idx}_position') or '—')}</div>
              <div><b>Phone:</b> {_escape_html(merged.get(f'reference_{idx}_phone') or '—')}</div>
              <div><b>Email:</b> {_escape_html(merged.get(f'reference_{idx}_email') or '—')}</div>
              <div><b>LinkedIn:</b> {_escape_html(merged.get(f'reference_{idx}_linkedin') or '—')}</div>
            </div>
            """
        )
    return f"""
    <div style="font-family:Arial,sans-serif;color:#172036;line-height:1.5;">
      <h2 style="margin:0 0 12px;">Candidate reference update</h2>
      <p style="margin:0 0 10px;"><b>Candidate:</b> {_escape_html(ctx.get('candidate_name') or 'Candidate')}</p>
      <p style="margin:0 0 10px;"><b>Opportunity:</b> {_escape_html(ctx.get('opp_position_name') or '—')}</p>
      <p style="margin:0 0 10px;"><b>Account:</b> {_escape_html(ctx.get('account_name') or '—')}</p>
      {''.join(sections)}
    </div>
    """


def _send_reference_notifications(cur, candidate_id, opportunity_id, merged, submitted_refs, before_complete, after_complete):
    if not submitted_refs:
        return
    ctx = _fetch_reference_email_context(cur, candidate_id, opportunity_id)
    if not ctx:
        return
    hr_lead = str(ctx.get('opp_hr_lead') or '').strip().lower()
    recipients = ['pgonzales@vintti.com']
    if hr_lead:
        recipients.insert(0, hr_lead)
    if not recipients:
        return

    candidate_name = ctx.get('candidate_name') or 'Candidate'
    opportunity_name = ctx.get('opp_position_name') or 'Opportunity'

    if len(submitted_refs) == 1:
        ref_idx = submitted_refs[0]
        subject = f"Reference {ref_idx} received for {candidate_name} • {opportunity_name}"
        _send_email(subject, _reference_email_html(ctx, merged, [ref_idx]), recipients)

    if after_complete and not before_complete:
        subject = f"Both references received for {candidate_name} • {opportunity_name}"
        _send_email(subject, _reference_email_html(ctx, merged, [1, 2]), recipients)


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
                c.candidate_id,
                c.name AS candidate_name,
                o.opportunity_id,
                o.account_id,
                a.client_name AS account_name
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

        cur.execute(
            """
            SELECT
                references_notes,
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
            FROM candidates
            WHERE candidate_id = %s
            LIMIT 1
            """,
            (candidate_id,),
        )
        refs = cur.fetchone() or {}

        return jsonify({
            'candidate_id': hire['candidate_id'],
            'candidate_name': hire.get('candidate_name'),
            'opportunity_id': hire.get('opportunity_id'),
            'account_id': hire.get('account_id'),
            'account_name': hire.get('account_name'),
            'next_reference_slot': 1 if not _is_reference_complete(refs, 1) else (2 if not _is_reference_complete(refs, 2) else 1),
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

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        hire = _resolve_candidate_hire(cur, candidate_id, opportunity_id)
        if not hire:
            return jsonify({'error': 'candidate not found'}), 404

        cur.execute(
            """
            SELECT
                references_notes,
                reference_1_name,
                reference_1_position,
                reference_1_phone,
                reference_1_email,
                reference_1_linkedin,
                reference_2_name,
                reference_2_position,
                reference_2_phone,
                reference_2_email,
                reference_2_linkedin
            FROM candidates
            WHERE candidate_id = %s
            LIMIT 1
            """,
            (candidate_id,),
        )
        existing = cur.fetchone() or {}
        merged, submitted_refs, merge_error = _merge_reference_payload(existing, data)
        if merge_error:
            return jsonify({
                'error': f"Reference {merge_error['reference_number']} is incomplete",
                'missing_fields': merge_error['missing_fields'],
            }), 400
        if not submitted_refs:
            return jsonify({'error': 'Please complete at least one full reference'}), 400

        before_complete = _is_reference_complete(existing, 1) and _is_reference_complete(existing, 2)
        after_complete = _is_reference_complete(merged, 1) and _is_reference_complete(merged, 2)

        manual_notes = _strip_structured_references_html(existing.get('references_notes') or '')
        structured_html = _build_structured_references_html(merged)
        merged_notes = '<br>'.join(part for part in [structured_html, manual_notes] if part)

        cur.execute(
            """
            UPDATE candidates
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
            """,
            (
                merged['reference_1_name'],
                merged['reference_1_position'],
                merged['reference_1_phone'],
                merged['reference_1_email'],
                merged['reference_1_linkedin'],
                merged['reference_2_name'],
                merged['reference_2_position'],
                merged['reference_2_phone'],
                merged['reference_2_email'],
                merged['reference_2_linkedin'],
                merged_notes,
                candidate_id,
            ),
        )

        if hire.get('opportunity_id'):
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
                    merged['reference_1_name'],
                    merged['reference_1_position'],
                    merged['reference_1_phone'],
                    merged['reference_1_email'],
                    merged['reference_1_linkedin'],
                    merged['reference_2_name'],
                    merged['reference_2_position'],
                    merged['reference_2_phone'],
                    merged['reference_2_email'],
                    merged['reference_2_linkedin'],
                    merged_notes,
                    candidate_id,
                    hire['opportunity_id'],
                ),
            )

        _send_reference_notifications(
            cur,
            candidate_id=candidate_id,
            opportunity_id=hire.get('opportunity_id') or opportunity_id,
            merged=merged,
            submitted_refs=submitted_refs,
            before_complete=before_complete,
            after_complete=after_complete,
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
