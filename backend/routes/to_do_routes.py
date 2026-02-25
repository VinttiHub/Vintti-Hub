import html
import logging
import os
import re
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_connection

bp = Blueprint('to_do', __name__)
APP_BASE_URL = os.environ.get('APP_BASE_URL', 'https://7m6mw95m8y.us-east-2.awsapprunner.com').rstrip('/')
BONUS_TODO_MARKER_RE = re.compile(r'\[AUTO:bonus_request:(\d+)(?::assignee:\d+)?\]')


def _extract_bonus_request_id(description: Optional[str]) -> Optional[int]:
    text = str(description or '')
    match = BONUS_TODO_MARKER_RE.search(text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _todo_reminder_email_html(user_name: str, groups: Dict[str, List[Dict]]) -> str:
    safe_name = html.escape(user_name or 'there')
    detail_url = 'https://vinttihub.vintti.com/to-do-details.html'

    sections = []
    labels = {
        'overdue': 'Overdue',
        'today': 'Due today',
        'soon': 'Due soon',
    }
    for key in ('overdue', 'today', 'soon'):
        items = groups.get(key) or []
        if not items:
            continue
        lis = []
        for task in items:
            due = html.escape(str(task.get('due_date') or ''))
            desc = html.escape(task.get('description') or '')
            suffix = ' (Subtask)' if task.get('subtask') else ''
            lis.append(f'<li><b>{due}</b> — {desc}{suffix}</li>')
        sections.append(
            f"""
            <div style="margin:14px 0">
              <div style="font-weight:600;margin-bottom:6px">{labels[key]} ({len(items)})</div>
              <ul style="margin:0;padding-left:18px">{''.join(lis)}</ul>
            </div>
            """
        )

    return f"""
    <div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.5;color:#1f2937">
      <p>Hi {safe_name},</p>
      <p>This is a reminder about tasks in your Vintti Hub ToDo that are due soon or overdue.</p>
      {''.join(sections)}
      <p style="margin-top:16px">
        <a href="{detail_url}" target="_blank" rel="noopener"
           style="display:inline-block;padding:10px 14px;border-radius:8px;background:#111827;color:#fff;text-decoration:none">
          Open ToDo
        </a>
      </p>
      <p style="color:#6b7280;font-size:12px">You received this because you have pending tasks assigned to your user.</p>
    </div>
    """


def _send_email_via_endpoint(subject: str, html_body: str, to: List[str], base_url: Optional[str] = None) -> bool:
    try:
        resolved_base = (base_url or APP_BASE_URL).rstrip('/')
        response = requests.post(
            f'{resolved_base}/send_email',
            json={'to': to, 'subject': subject, 'body': html_body},
            timeout=30,
        )
        if not response.ok:
            logging.error('ToDo reminder email failed: %s %s', response.status_code, response.text)
        return response.ok
    except Exception:
        logging.exception('ToDo reminder email exception')
        return False


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
                SELECT to_do_id, user_id, description, due_date::text AS due_date, "check", orden, subtask
                FROM to_do
                WHERE user_id = %s
                ORDER BY orden NULLS LAST, due_date NULLS LAST, to_do_id ASC
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
    subtask = data.get('subtask')
    orden = data.get('orden')

    if not user_id or not description or not due_date:
        return jsonify({"error": "user_id, description, and due_date are required"}), 400

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT COALESCE(MAX(to_do_id), 0) + 1 AS next_id FROM to_do")
        next_id = cur.fetchone()['next_id']

        if orden is None:
            cur.execute(
                """
                SELECT COALESCE(MAX(orden), 0) + 1 AS next_order
                FROM to_do
                WHERE user_id = %s AND (
                  (subtask IS NULL AND %s IS NULL)
                  OR subtask = %s
                )
                """,
                (user_id, subtask, subtask),
            )
            orden = cur.fetchone()['next_order']

        cur.execute(
            """
            INSERT INTO to_do (to_do_id, user_id, description, due_date, "check", orden, subtask)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING to_do_id, user_id, description, due_date::text AS due_date, "check", orden, subtask
            """,
            (next_id, user_id, description, due_date, False, orden, subtask),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return jsonify(row), 201
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route('/to_do/<int:to_do_id>', methods=['PATCH', 'DELETE', 'OPTIONS'])
def to_do_item(to_do_id: int):
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    if user_id is None:
        return jsonify({"error": "user_id is required"}), 400

    if request.method == 'DELETE':
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM to_do WHERE subtask = %s AND user_id = %s", (to_do_id, user_id))
            cur.execute("DELETE FROM to_do WHERE to_do_id = %s AND user_id = %s", (to_do_id, user_id))
            conn.commit()
            cur.close()
            conn.close()
            return jsonify({"ok": True})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    check_value = data.get('check')
    if check_value is None:
        return jsonify({"error": "check is required"}), 400

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        checked = bool(check_value)
        cur.execute(
            """
            UPDATE to_do
            SET "check" = %s
            WHERE to_do_id = %s AND user_id = %s
            RETURNING to_do_id, user_id, description, due_date::text AS due_date, "check", orden, subtask
            """,
            (checked, to_do_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return jsonify({"error": "to_do item not found"}), 404

        # Si es una tarea auto-generada desde bonus request y la marcan como hecha,
        # reflejamos el cambio en el CRM (pending -> approved).
        if checked:
            bonus_request_id = _extract_bonus_request_id(row.get('description'))
            if bonus_request_id:
                savepoint_created = False
                try:
                    # Aisla errores del sync para no romper el check del ToDo.
                    cur.execute("SAVEPOINT todo_bonus_sync")
                    savepoint_created = True
                    cur.execute(
                        """
                        UPDATE bonus_requests
                        SET status = 'approved',
                            updated_at = NOW()
                        WHERE bonus_request_id = %s
                          AND status = 'pending'
                        """,
                        (bonus_request_id,),
                    )
                except Exception:
                    if savepoint_created:
                        try:
                            cur.execute("ROLLBACK TO SAVEPOINT todo_bonus_sync")
                        except Exception:
                            logging.exception('Failed to rollback savepoint todo_bonus_sync')
                    logging.exception('Failed to sync bonus_request status from ToDo check (bonus_request_id=%s)', bonus_request_id)
                finally:
                    if savepoint_created:
                        try:
                            cur.execute("RELEASE SAVEPOINT todo_bonus_sync")
                        except Exception:
                            pass
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
              t."check",
              t.orden,
              t.subtask
            FROM users u
            LEFT JOIN to_do t ON t.user_id = u.user_id
            WHERE u.lider = %s
            ORDER BY LOWER(u.user_name) ASC, t.orden NULLS LAST, t.due_date NULLS LAST, t.to_do_id ASC
            """,
            (leader_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(rows)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route('/to_do/reorder', methods=['POST', 'OPTIONS'])
def to_do_reorder():
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    items = data.get('items') or []

    if not user_id or not isinstance(items, list) or not items:
        return jsonify({"error": "user_id and items are required"}), 400

    try:
        conn = get_connection()
        cur = conn.cursor()
        for item in items:
            to_do_id = item.get('to_do_id')
            orden = item.get('orden')
            if to_do_id is None or orden is None:
                continue
            cur.execute(
                """
                UPDATE to_do
                SET orden = %s
                WHERE to_do_id = %s AND user_id = %s
                """,
                (orden, to_do_id, user_id),
            )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route('/to_do/reminders/send', methods=['POST', 'OPTIONS'])
def to_do_send_reminders():
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    target_user_id = data.get('user_id')
    target_email = (data.get('email') or '').strip().lower() or None
    days_ahead = data.get('days_ahead', 2)
    include_overdue = bool(data.get('include_overdue', True))
    dry_run = bool(data.get('dry_run', False))
    email_api_base = (data.get('email_api_base') or '').strip().rstrip('/') or request.host_url.rstrip('/') or APP_BASE_URL

    try:
        days_ahead = int(days_ahead)
    except Exception:
        return jsonify({"error": "days_ahead must be an integer"}), 400

    if days_ahead < 0 or days_ahead > 14:
        return jsonify({"error": "days_ahead must be between 0 and 14"}), 400

    today = date.today()
    due_limit = today + timedelta(days=days_ahead)

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT
              u.user_id,
              COALESCE(NULLIF(u.user_name, ''), SPLIT_PART(u.email_vintti, '@', 1), 'User') AS user_name,
              LOWER(TRIM(u.email_vintti)) AS email_vintti,
              t.to_do_id,
              t.description,
              t.due_date::date AS due_date,
              t.subtask
            FROM to_do t
            JOIN users u ON u.user_id = t.user_id
            WHERE COALESCE(t."check", FALSE) = FALSE
              AND t.due_date IS NOT NULL
              AND t.due_date::date <= %s
              AND LOWER(TRIM(COALESCE(u.email_vintti, ''))) <> ''
        """
        params = [due_limit]

        if not include_overdue:
            query += ' AND t.due_date::date >= %s'
            params.append(today)
        if target_user_id is not None:
            query += ' AND u.user_id = %s'
            params.append(target_user_id)
        if target_email:
            query += ' AND LOWER(TRIM(u.email_vintti)) = %s'
            params.append(target_email)

        query += ' ORDER BY LOWER(TRIM(u.email_vintti)) ASC, t.due_date::date ASC, t.orden NULLS LAST, t.to_do_id ASC'
        cur.execute(query, tuple(params))
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    by_user: Dict[Tuple[int, str], Dict] = {}
    for row in rows:
        due = row.get('due_date')
        if due is None:
            continue
        key = (int(row['user_id']), row['email_vintti'])
        bucket = by_user.setdefault(
            key,
            {
                'user_id': int(row['user_id']),
                'user_name': row.get('user_name') or 'User',
                'email': row['email_vintti'],
                'overdue': [],
                'today': [],
                'soon': [],
            },
        )
        task = {
            'to_do_id': row.get('to_do_id'),
            'description': row.get('description') or '',
            'due_date': str(due),
            'subtask': row.get('subtask'),
        }
        if due < today:
            bucket['overdue'].append(task)
        elif due == today:
            bucket['today'].append(task)
        else:
            bucket['soon'].append(task)

    sent = []
    skipped = []

    for payload in by_user.values():
        total = len(payload['overdue']) + len(payload['today']) + len(payload['soon'])
        if total == 0:
            continue

        subject_bits = []
        if payload['overdue']:
            subject_bits.append(f"{len(payload['overdue'])} overdue")
        if payload['today']:
            subject_bits.append(f"{len(payload['today'])} due today")
        if payload['soon']:
            subject_bits.append(f"{len(payload['soon'])} due soon")
        subject = f"Vintti Hub ToDo reminder: {', '.join(subject_bits)}"

        html_body = _todo_reminder_email_html(payload['user_name'], {
            'overdue': payload['overdue'],
            'today': payload['today'],
            'soon': payload['soon'],
        })

        preview = {
            'user_id': payload['user_id'],
            'email': payload['email'],
            'counts': {
                'overdue': len(payload['overdue']),
                'today': len(payload['today']),
                'soon': len(payload['soon']),
            },
            'subject': subject,
        }

        if dry_run:
            skipped.append({**preview, 'reason': 'dry_run'})
            continue

        ok = _send_email_via_endpoint(subject, html_body, [payload['email']], base_url=email_api_base)
        if ok:
            sent.append(preview)
        else:
            skipped.append({**preview, 'reason': 'send_failed'})

    return jsonify({
        'ok': True,
        'filters': {
            'user_id': target_user_id,
            'email': target_email,
            'days_ahead': days_ahead,
            'include_overdue': include_overdue,
            'dry_run': dry_run,
            'email_api_base': email_api_base,
            'today': str(today),
            'due_limit': str(due_limit),
        },
        'users_found': len(by_user),
        'sent': sent,
        'skipped': skipped,
    }), 200
