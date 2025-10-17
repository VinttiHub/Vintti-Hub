# profile_routes.py  (extracto limpio y consolidado)
import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional, Dict, Any
from flask import Blueprint, request, jsonify, g
from psycopg2.extras import RealDictCursor
from db import get_connection

BOGOTA_TZ = timezone(timedelta(hours=-5))

# ✅ declarar UNA sola vez
bp = Blueprint("profile", __name__, url_prefix="")
users_bp = Blueprint("users", __name__)

def _int_or_none(x):
    try: return int(x)
    except Exception: return None

def _current_user_id() -> Optional[int]:
    uid = getattr(g, "user_id", None)
    if isinstance(uid, int): return uid
    c = _int_or_none(request.cookies.get("user_id"))
    if c: return c
    q = _int_or_none(request.args.get("user_id"))
    if q: return q
    h = _int_or_none(request.headers.get("X-User-Id") or request.headers.get("x-user-id"))
    if h: return h
    return None

@bp.before_app_request
def _inject_user_from_cookie_or_query():
    if getattr(g, "user_id", None) is None:
        g.user_id = _current_user_id()

def _row_to_json(row: Dict[str, Any]) -> Dict[str, Any]:
    for k in ("ingreso_vintti_date","fecha_nacimiento","start_date","end_date","created_at","updated_at"):
        if k in row and row[k] is not None:
            v = row[k]
            try:
                if hasattr(v, "isoformat"): row[k] = v.date().isoformat() if hasattr(v, "date") else v.isoformat()
            except Exception: pass
    return row

# ---------- USERS ----------
@users_bp.get("/users/<int:user_id>")
def get_user(user_id: int):
    q = """
    SELECT
      user_id, user_name, email_vintti, role, emergency_contact,
      ingreso_vintti_date, fecha_nacimiento, avatar_url,
      COALESCE(vacaciones_acumuladas, 0) AS vacaciones_acumuladas,
      COALESCE(vacaciones_habiles, 0)    AS vacaciones_habiles,
      COALESCE(vacaciones_consumidas, 0) AS vacaciones_consumidas,
      COALESCE(vintti_days, 0)           AS vintti_days,
      COALESCE(vintti_days_consumidos,0) AS vintti_days_consumidos,
      COALESCE(feriados_totales, 0)        AS feriados_totales,      -- NEW
      COALESCE(feriados_consumidos, 0)     AS feriados_consumidos 
    FROM users
    WHERE user_id = %s
    """
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(q, (user_id,))
        row = cur.fetchone()
    conn.close()
    if not row: return jsonify({"error":"user not found"}), 404
    return jsonify(_row_to_json(dict(row)))

@users_bp.put("/users/<int:user_id>")
def update_user(user_id: int):
    data = request.get_json(silent=True) or {}
    caller = _current_user_id()
    ok = (caller == user_id)
    if not ok:
        q = _int_or_none(request.args.get("user_id"))
        b = _int_or_none(data.get("user_id"))
        ok = (q == user_id) or (b == user_id)
    if not ok:
        return jsonify({"error":"forbidden"}), 403

    fields = {
        "user_name": data.get("user_name"),
        "email_vintti": data.get("email_vintti"),
        "role": data.get("role"),
        "emergency_contact": data.get("emergency_contact"),
        "ingreso_vintti_date": data.get("ingreso_vintti_date"),
        "fecha_nacimiento": data.get("fecha_nacimiento"),
    }
    sets, vals = [], []
    for col, val in fields.items():
        if val is not None:
            sets.append(f"{col} = %s"); vals.append(val)
    if not sets: return jsonify({"ok": True})

    vals.append(user_id)
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"""
            UPDATE users
            SET {", ".join(sets)}, updated_at = NOW() AT TIME ZONE 'UTC'
            WHERE user_id = %s
            RETURNING user_id
        """, tuple(vals))
        updated = cur.fetchone()
        conn.commit()
    conn.close()
    if not updated: return jsonify({"error":"not found"}), 404
    return jsonify({"ok": True})

# ---------- PROFILE / ME ----------
@bp.get("/profile/me")
def me():
    user_id = _current_user_id()
    if not user_id:
        return jsonify({"error":"unauthorized"}), 401
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT user_id, user_name, email_vintti, role, emergency_contact,
                   ingreso_vintti_date, fecha_nacimiento, avatar_url
            FROM users WHERE user_id = %s
        """, (user_id,))
        row = cur.fetchone()
    conn.close()
    if not row: return jsonify({"error":"not found"}), 404
    return jsonify(_row_to_json(dict(row)))

# --- TIME OFF REQUESTS ---

@bp.get("/time_off_requests")
def list_time_off():
    # ✅ toma primero sesión/header/query (igual que /profile/me)
    user_id = _current_user_id()
    if not user_id:
        # último recurso: query param legacy
        q = request.args.get("user_id")
        if q and q.isdigit():
            user_id = int(q)

    if not user_id:
        return jsonify({"error":"user_id required"}), 400

    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, user_id, kind, start_date, end_date, reason, status, created_at
            FROM time_off_requests
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 100
        """, (int(user_id),))
        rows = cur.fetchall()
    conn.close()

    return jsonify([_row_to_json(r) for r in rows])

@bp.get("/users")
def list_users():
    email = request.args.get("email")
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if email:
            cur.execute("SELECT * FROM users WHERE LOWER(email_vintti) = LOWER(%s)", (email,))
        else:
            cur.execute("SELECT * FROM users")
        rows = cur.fetchall()
    conn.close()
    return jsonify(rows)

@bp.post("/time_off_requests")
def create_time_off():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    kind_raw = (data.get("kind") or "").strip().lower()
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    reason = (data.get("reason") or "").strip() or None

    if not user_id or not str(user_id).isdigit():
        return jsonify({"error":"user_id required"}), 400

    # allow exactly these 3
    ALLOWED = {"vacation","holiday","vintti_day"}
    if kind_raw not in ALLOWED:
        return jsonify({"error":"invalid kind (use 'vacation', 'holiday', or 'vintti_day')"}), 400

    if not start_date or not end_date:
        return jsonify({"error":"start_date and end_date required"}), 400
    if end_date < start_date:
        return jsonify({"error":"end_date before start_date"}), 400

    # Insert + fetch requester + leader in one go
    conn = get_connection()
    new_id = None
    requester = None
    leader_email = None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1) insert
            cur.execute("""
                INSERT INTO time_off_requests (user_id, kind, start_date, end_date, reason, status, created_at)
                VALUES (%s, %s, %s, %s, %s, 'pending', NOW() AT TIME ZONE 'UTC')
                RETURNING id
            """, (int(user_id), kind_raw, start_date, end_date, reason))
            row = cur.fetchone()
            new_id = row["id"]

            # 2) requester & leader email
            cur.execute("""
                SELECT u.user_name, u.email_vintti, u.lider,
                       l.email_vintti AS leader_email
                FROM users u
                LEFT JOIN users l ON l.user_id = u.lider
                WHERE u.user_id = %s
            """, (int(user_id),))
            requester = cur.fetchone()

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"error": "db insert failed", "detail": str(e)}), 500
    finally:
        try: conn.close()
        except: pass

    requester_name = (requester or {}).get("user_name") or "Someone"
    leader_email = (requester or {}).get("leader_email")

    # Compose email
    subj = f"Time off request • {requester_name} • {kind_raw.replace('_',' ').title()} • {start_date} → {end_date}"
    html = f"""
      <h2>New time off request</h2>
      <p><strong>Requester:</strong> {requester_name}</p>
      <p><strong>Type:</strong> {kind_raw.replace('_',' ').title()}</p>
      <p><strong>Dates:</strong> {start_date} → {end_date}</p>
      {"<p><strong>Note:</strong> " + reason + "</p>" if reason else ""}
      <p>Status: <strong>Pending</strong></p>
    """.strip()

    # Targets: leader (if any) + Jaz
    to_list = []
    #if leader_email:
    #    to_list.append(leader_email)
    # Always add Jaz
    #to_list.append("jazmin@vintti.com")
    to_list.append("angie@vintti.com")

    # ——— Send the email (SendGrid) ———
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Email

        api_key = os.environ.get('SENDGRID_API_KEY')
        if not api_key:
            raise RuntimeError("SENDGRID_API_KEY not configured")

        msg = Mail(
            from_email=Email('hub@vintti-hub.com', name='Vintti HUB'),
            to_emails=to_list,
            subject=subj,
            html_content=html
        )
        sg = SendGridAPIClient(api_key)
        sg.send(msg)

        # If you prefer calling your /send_email route instead:
        # import requests as _rq
        # _rq.post(request.url_root.rstrip('/') + '/send_email', json={
        #   "to": to_list, "subject": subj, "body": html
        # }, timeout=10)
    except Exception as e:
        # We keep the request but report the email error
        logging.exception("time_off email failed")
        return jsonify({"ok": True, "id": new_id, "email_warning": str(e)}), 201

    return jsonify({"ok": True, "id": new_id}), 201
