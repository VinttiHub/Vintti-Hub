# profile_routes.py  (extracto limpio y consolidado)
import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional, Dict, Any, Set
from flask import Blueprint, request, jsonify, g
from psycopg2.extras import RealDictCursor
from db import get_connection
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email
from calendar import monthrange
from urllib.parse import urlparse

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

# ----- US Federal Holidays (observed) helpers -----
def _nth_weekday(year, month, weekday, n):
    """weekday: 0=Mon..6=Sun; n: 1..5 (5 -> 'last' if it exists, manejar aparte)"""
    # primer día del mes: (1..7)
    first_weekday = date(year, month, 1).weekday()  # 0=Mon..6=Sun
    # offset hasta el primer 'weekday' del mes
    offset = (weekday - first_weekday) % 7
    day = 1 + offset + (n - 1) * 7
    last_day = monthrange(year, month)[1]
    return date(year, month, min(day, last_day))

def _last_weekday(year, month, weekday):
    last_day = monthrange(year, month)[1]
    d = date(year, month, last_day)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d

def _observed(d: date) -> date:
    """Regla de observancia estándar en EE.UU.: 
       si cae sábado → se observa viernes previo; si domingo → lunes siguiente."""
    if d.weekday() == 5:   # Saturday
        return d - timedelta(days=1)
    if d.weekday() == 6:   # Sunday
        return d + timedelta(days=1)
    return d

def us_federal_holidays_observed_for_year(year: int) -> Set[date]:
    """Conjunto de feriados federales de EE.UU. (observados) para un año."""
    # Fijos (con observancia):
    new_years      = _observed(date(year, 1, 1))
    juneteenth     = _observed(date(year, 6, 19))
    independence   = _observed(date(year, 7, 4))
    veterans       = _observed(date(year, 11, 11))
    christmas      = _observed(date(year, 12, 25))

    # Móviles:
    mlk            = _nth_weekday(year, 1, 0, 3)   # 3er lunes de enero
    presidents     = _nth_weekday(year, 2, 0, 3)   # 3er lunes de febrero
    memorial       = _last_weekday(year, 5, 0)     # último lunes de mayo
    labor          = _nth_weekday(year, 9, 0, 1)   # 1er lunes de septiembre
    columbus       = _nth_weekday(year,10, 0, 2)   # 2do lunes de octubre
    thanksgiving   = _nth_weekday(year,11, 3, 4)   # 4to jueves de noviembre (3=Thu)

    return {
        new_years, mlk, presidents, memorial, juneteenth, independence,
        labor, columbus, veterans, thanksgiving, christmas
    }

def business_days_us(start: date, end: date) -> int:
    """Cuenta días hábiles (lun-vie) excluyendo feriados federales de EE.UU. observados."""
    if end < start:
        return 0
    # Prepara set de feriados para todos los años tocados por el rango
    years = range(start.year, end.year + 1)
    hols = set()
    for y in years:
        hols |= us_federal_holidays_observed_for_year(y)

    count = 0
    cur = start
    one = timedelta(days=1)
    while cur <= end:
        if cur.weekday() < 5 and cur not in hols:  # 0..4 = Mon..Fri
            count += 1
        cur += one
    return count

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

def _normalize_avatar_url(raw: Optional[Any]) -> Optional[str]:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    parsed = urlparse(value)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("avatar_url must be an http(s) URL")
    return value

# ---------- USERS ----------
@users_bp.get("/users/<int:user_id>")
def get_user(user_id: int):
    q = """
    SELECT
      user_id, user_name, email_vintti, role, emergency_contact,
      ingreso_vintti_date, fecha_nacimiento, avatar_url,
      COALESCE(vacaciones_acumuladas, 0)    AS vacaciones_acumuladas,
      COALESCE(vacaciones_habiles, 0)       AS vacaciones_habiles,
      COALESCE(vacaciones_consumidas, 0)    AS vacaciones_consumidas,
      COALESCE(vintti_days_consumidos, 0)   AS vintti_days_consumidos,
      COALESCE(feriados_consumidos, 0)      AS feriados_consumidos
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

@users_bp.patch("/users/<int:user_id>")
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

    avatar_specified = "avatar_url" in data
    avatar_value: Optional[str] = None
    if avatar_specified:
        try:
            avatar_value = _normalize_avatar_url(data.get("avatar_url"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    sets, vals = [], []
    for col, val in fields.items():
        if val is not None:
            sets.append(f"{col} = %s"); vals.append(val)

    if avatar_specified:
        if avatar_value is None:
            sets.append("avatar_url = NULL")
        else:
            sets.append("avatar_url = %s"); vals.append(avatar_value)

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
                ingreso_vintti_date, fecha_nacimiento, avatar_url,
                team
            FROM users WHERE user_id = %s
        """, (user_id,))
        row = cur.fetchone()
    conn.close()
    if not row: return jsonify({"error":"not found"}), 404
    return jsonify(_row_to_json(dict(row)))

@bp.get("/leader/time_off_requests")
def leader_list_timeoff():
    """Return requests for users whose 'lider' == current leader."""
    leader_id = _current_user_id()
    if not leader_id:
        return jsonify({"error": "unauthorized"}), 401

    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Are you leader of anyone?
        cur.execute("""
            SELECT COUNT(*) AS cnt FROM users WHERE lider = %s
        """, (leader_id,))
        cnt = cur.fetchone()["cnt"]
        if cnt == 0:
            return jsonify({"error":"forbidden (not a leader of anyone)"}), 403

        # Pull requests from your direct reports
        cur.execute("""
            SELECT
              r.id,
              r.user_id,
              u.user_name,
              u.email_vintti AS user_email,
              u.avatar_url,
              u.team,
              r.kind,
              r.start_date,
              r.end_date,
              r.reason,
              r.status,
              r.created_at
            FROM time_off_requests r
            JOIN users u ON u.user_id = r.user_id
            WHERE u.lider = %s
            ORDER BY
              CASE r.status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END,
              r.created_at DESC
            LIMIT 500
        """, (leader_id,))
        rows = cur.fetchall()
    conn.close()
    return jsonify([_row_to_json(dict(r)) for r in rows])


@bp.patch("/leader/time_off_requests/<int:req_id>")
def leader_update_timeoff(req_id: int):
    """Approve or reject a request that belongs to one of my direct reports.
       When approving (first time), deduct balances according to kind."""
    leader_id = _current_user_id()
    if not leader_id:
        return jsonify({"error":"unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    new_status = (data.get("status") or "").strip().lower()
    if new_status not in {"approved", "rejected"}:
        return jsonify({"error":"status must be 'approved' or 'rejected'"}), 400

    conn = get_connection()
    rec = None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1) Traer la request + usuario y chequear ownership
            cur.execute("""
                SELECT
                  r.id, r.user_id, r.kind, r.start_date, r.end_date, r.reason, r.status,
                  u.user_name, u.email_vintti AS user_email, u.lider, u.team
                FROM time_off_requests r
                JOIN users u ON u.user_id = r.user_id
                WHERE r.id = %s
            """, (req_id,))
            rec = cur.fetchone()
            if not rec:
                return jsonify({"error":"not found"}), 404
            if int(rec["lider"] or 0) != int(leader_id):
                return jsonify({"error":"forbidden (not your report)"}), 403

            old_status = str(rec["status"] or "").lower()

            # 2) Actualizar el estado (idempotente si no cambia)
            if old_status == new_status:
                return jsonify({"ok": True, "status": new_status})

            cur.execute("""
                UPDATE time_off_requests
                   SET status = %s, updated_at = NOW() AT TIME ZONE 'UTC'
                 WHERE id = %s
            """, (new_status, req_id))

            # 3) Si pasa a APPROVED por primera vez -> descontar saldos
            if new_status == "approved" and old_status != "approved":
                # días inclusivos: (end - start) + 1
                from datetime import date as _date, datetime as _dt
                sd = rec["start_date"]; ed = rec["end_date"]
                if isinstance(sd, str):
                    sd = datetime.strptime(sd, "%Y-%m-%d").date()
                if isinstance(ed, str):
                    ed = datetime.strptime(ed, "%Y-%m-%d").date()

                k = str(rec["kind"] or "").lower()
                if k == "vacation":
                    total_days = business_days_us(sd, ed)  # <-- SOLO vacaciones: días hábiles US
                else:
                    # Para VD/Holiday mantenemos conteo inclusivo calendario
                    total_days = max(0, (ed - sd).days) + 1

                total_days = int(total_days)

                if total_days > 0:
                    k = str(rec["kind"] or "").lower()
                    uid = int(rec["user_id"])

                    if k == "vacation":
                        # ✅ Nueva regla vacaciones:
                        #   - SOLO sumar a vacaciones_consumidas
                        #   - vacations_available será derivado en el frontend
                        cur.execute("""
                            UPDATE users
                            SET
                                vacaciones_consumidas = COALESCE(vacaciones_consumidas, 0) + %s,
                                updated_at = NOW() AT TIME ZONE 'UTC'
                            WHERE user_id = %s
                        """, (total_days, uid))

                    elif k == "vintti_day":
                        # ✅ Nueva regla Vintti Day:
                        #   - NO tocar vintti_days
                        #   - SOLO sumar a vintti_days_consumidos
                        cur.execute("""
                            UPDATE users
                               SET
                                 vintti_days_consumidos = COALESCE(vintti_days_consumidos,0) + %s,
                                 updated_at = NOW() AT TIME ZONE 'UTC'
                             WHERE user_id = %s
                        """, (total_days, uid))

                    elif k == "holiday":
                        # ✅ Nueva regla Holiday:
                        #   - NO tocar feriados_totales
                        #   - SOLO sumar a feriados_consumidos
                        cur.execute("""
                            UPDATE users
                               SET
                                 feriados_consumidos = COALESCE(feriados_consumidos,0) + %s,
                                 updated_at = NOW() AT TIME ZONE 'UTC'
                             WHERE user_id = %s
                        """, (total_days, uid))
                    else:
                        # Kinds desconocidos no descuentan
                        pass

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"error":"db error", "detail": str(e)}), 500
    finally:
        try: conn.close()
        except: pass

    # --- Email amistoso al solicitante (se mantiene tu lógica) ---
    try:
        api_key = os.environ.get('SENDGRID_API_KEY')
        if not api_key:
            raise RuntimeError("SENDGRID_API_KEY not configured")

        from datetime import datetime
        def fmt_date(s):
            try:
                # aceptar date o str
                if hasattr(s, "strftime"):
                    return s.strftime("%B %d, %Y")
                d = datetime.strptime(str(s), "%Y-%m-%d")
                return d.strftime("%B %d, %Y")
            except Exception:
                return str(s)

        start_fmt = fmt_date(rec["start_date"])
        end_fmt   = fmt_date(rec["end_date"])
        try:
            d1 = datetime.strptime(str(rec["start_date"]), "%Y-%m-%d").date()
            d2 = datetime.strptime(str(rec["end_date"]), "%Y-%m-%d").date()
            kind_lower = str(rec["kind"] or "").lower()
            if kind_lower == "vacation":
                total_days = business_days_us(d1, d2)
                total_days_label = "Business days"
            else:
                total_days = (d2 - d1).days + 1
                total_days_label = "Days"
        except Exception:
            total_days = None
            total_days_label = "Days"

        kind_label = str(rec["kind"]).replace("_"," ").title()
        user_name  = rec["user_name"] or "there"

        if new_status == "approved":
            subj = f"Your time off was approved ✅"
            intro = f"Good news, {user_name}! Your time off request was approved."
            closing = "Enjoy your time away—everything’s set on our side."
        else:
            subj = f"Your time off was not approved ❌"
            intro = f"Hi {user_name}, we reviewed your time off request."
            closing = "If you have questions or want to propose new dates, just reply to this email."

        parts = [
            f"<p>{intro}</p>",
            "<ul>",
            f"<li><strong>Type:</strong> {kind_label}</li>",
            f"<li><strong>Dates:</strong> {start_fmt} → {end_fmt}</li>",
        ]
        if total_days is not None:
            parts.append(f"<li><strong>{total_days_label}:</strong> {total_days}</li>")
        if rec.get("reason"):
            parts.append(f"<li><strong>Note:</strong> {rec['reason']}</li>")
        parts.append("</ul>")
        parts.append(f"<p>{closing}</p>")
        parts.append("<p>— Vintti HUB</p>")
        html = "\n".join(parts)

        msg = Mail(
            from_email=Email('hub@vintti-hub.com', name='Vintti HUB'),
            to_emails=[rec["user_email"]],
            subject=subj,
            html_content=html
        )
        sg = SendGridAPIClient(api_key)
        sg.send(msg)
    except Exception as e:
        logging.exception("leader decision email failed")
        return jsonify({"ok": True, "status": new_status, "email_warning": str(e)})

    return jsonify({"ok": True, "status": new_status})

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
    from datetime import datetime

    # 🏝️ pick an emoji for the kind
    emoji_map = {
        "vacation": "🏖️",
        "holiday": "🎉",
        "vintti_day": "💙"
    }
    kind_label = kind_raw.replace('_', ' ').title()
    emoji = emoji_map.get(kind_raw, "🌴")

    # Format dates nicely
    def fmt_date(iso_str):
        try:
            d = datetime.strptime(iso_str, "%Y-%m-%d")
            return d.strftime("%B %d, %Y")  # e.g., October 16, 2025
        except Exception:
            return iso_str

    start_fmt = fmt_date(start_date)
    end_fmt = fmt_date(end_date)

    # Calculate number of days requested
    try:
        d1 = datetime.strptime(start_date, "%Y-%m-%d")
        d2 = datetime.strptime(end_date, "%Y-%m-%d")
        num_days = (d2 - d1).days + 1
    except Exception:
        num_days = None

    subj = f"Time off request • {requester_name} • {kind_label} {emoji}"

    # Build friendly HTML body
    html_parts = [
        f"<p>Hi there 👋,</p>",
        f"<p><strong>{requester_name}</strong> just requested some time off. Here are the details:</p>",
        "<ul>",
        f"<li><strong>Type:</strong> {kind_label}</li>",
        f"<li><strong>Dates:</strong> {start_fmt} → {end_fmt}</li>",
    ]
    if num_days:
        html_parts.append(f"<li><strong>Total days:</strong> {num_days} day{'s' if num_days != 1 else ''}</li>")
    if reason:
        html_parts.append(f"<li><strong>Note:</strong> {reason}</li>")
    html_parts.append("</ul>")
    html_parts.append(
        "<p>Please go to the "
        "<a href='https://vinttihub.vintti.com' target='_blank' rel='noopener' "
        "style='color:#2563eb;text-decoration:none;font-weight:500;'>Vacations page</a> "
        "to approve or reject this request.</p>"
    )
    html_parts.append("<p>Have a great day ☀️<br>— The Vintti HUB Team</p>")
    html = "\n".join(html_parts)

    # Targets: leader (if any) + Jaz
    to_list = []
    if leader_email:
        to_list.append(leader_email)
    # Always add Jaz
    to_list.append("jazmin@vintti.com")
    to_list.append("angie@vintti.com")

    # ——— Send the email (SendGrid) ———
    try:
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
    except Exception as e:
        # We keep the request but report the email error
        logging.exception("time_off email failed")
        return jsonify({"ok": True, "id": new_id, "email_warning": str(e)}), 201

    return jsonify({"ok": True, "id": new_id}), 201
@bp.delete("/time_off_requests/<int:req_id>")
def delete_time_off_request(req_id: int):
    """Requester can delete ONLY their own pending request."""
    user_id = _current_user_id()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, user_id, status
                FROM time_off_requests
                WHERE id = %s
            """, (req_id,))
            row = cur.fetchone()

            if not row:
                return jsonify({"error": "not found"}), 404

            if int(row["user_id"]) != int(user_id):
                return jsonify({"error": "forbidden"}), 403

            status = str(row["status"] or "").lower()
            if status != "pending":
                # 409 = conflicto de estado (ya aprobado/rechazado)
                return jsonify({"error": "cannot delete (not pending)"}), 409

            cur.execute("""
                DELETE FROM time_off_requests
                WHERE id = %s AND status = 'pending'
            """, (req_id,))

        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": "db error", "detail": str(e)}), 500
    finally:
        try: conn.close()
        except: pass
