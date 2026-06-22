# profile_routes.py  (extracto limpio y consolidado)
import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional, Dict, Any, Set, Tuple
from flask import Blueprint, request, jsonify, g
from psycopg2.extras import RealDictCursor
from db import get_connection
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email
from calendar import monthrange
from urllib.parse import urlparse

BOGOTA_TZ = timezone(timedelta(hours=-5))
LEADER_ACCESS_EMAILS = {
    "agustin@vintti.com",
    "lara@vintti.com",
    "jazmin@vintti.com",
    "agostina@vintti.com",
    "bahia@vintti.com",
    "lucia@vintti.com",
    "camila@vintti.com",
    "mia@vintti.com",
}
VACATION_ROLLOVER_CAP_DAYS = 7
VACATION_ROLLOVER_AUTO_START_YEAR = 2027
VACATION_ROLLOVER_LOCK_KEY = 2026061801

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

def _is_allowed_leader(cur, user_id: int) -> bool:
    cur.execute("SELECT LOWER(TRIM(email_vintti)) AS email FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    return bool(row and row.get("email") in LEADER_ACCESS_EMAILS)

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

_TIMEOFF_HALF_DAY_TOKEN = "[[vhub:half_day]]"

def _parse_timeoff_reason_meta(raw_reason: Optional[Any]) -> Tuple[Optional[str], bool]:
    text = "" if raw_reason is None else str(raw_reason)
    is_half_day = False
    kept_lines = []
    for line in text.splitlines():
        if line.strip() == _TIMEOFF_HALF_DAY_TOKEN:
            is_half_day = True
            continue
        kept_lines.append(line)
    clean_reason = "\n".join(kept_lines).strip() or None
    return clean_reason, is_half_day

def _encode_timeoff_reason(reason: Optional[Any], is_half_day: bool) -> Optional[str]:
    clean = (str(reason).strip() if reason is not None else "").strip() or None
    if not is_half_day:
        return clean
    return f"{_TIMEOFF_HALF_DAY_TOKEN}\n{clean}" if clean else _TIMEOFF_HALF_DAY_TOKEN

def _normalize_timeoff_row(row: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(row, dict):
        return row
    clean_reason, is_half_day = _parse_timeoff_reason_meta(row.get("reason"))
    row["reason"] = clean_reason
    row["is_half_day"] = bool(is_half_day and str(row.get("kind") or "").lower() == "vacation")
    return row

def _timeoff_total_days(kind: str, start_value: Any, end_value: Any, *, is_half_day: bool = False) -> float:
    sd = start_value
    ed = end_value
    if isinstance(sd, str):
        sd = datetime.strptime(sd, "%Y-%m-%d").date()
    if isinstance(ed, str):
        ed = datetime.strptime(ed, "%Y-%m-%d").date()

    kind_lower = str(kind or "").lower()
    if kind_lower == "vacation":
        base = float(business_days_us(sd, ed))
        if is_half_day and sd == ed and base >= 1:
            return 0.5
        return base
    return float(max(0, (ed - sd).days) + 1)

def _as_day_number(value: float):
    try:
        n = float(value)
    except Exception:
        return value
    return int(n) if n.is_integer() else n

def _prorated_vacation_days_for_year(start_value: Optional[Any], annual_days: float = 15) -> float:
    if not start_value:
        return annual_days
    try:
        start = start_value
        if isinstance(start, str):
            start = datetime.strptime(start[:10], "%Y-%m-%d").date()
        elif hasattr(start, "date"):
            start = start.date()
    except Exception:
        return annual_days

    current_year = datetime.now(BOGOTA_TZ).year
    if start.year < current_year:
        return annual_days
    if start.year > current_year:
        return 0

    months_worked = max(0, 12 - start.month + 1)
    return int((months_worked * annual_days * 2) / 12) / 2

def _prorated_holiday_days_for_year(start_value: Optional[Any]) -> float:
    if not start_value:
        return 4
    try:
        start = start_value
        if isinstance(start, str):
            start = datetime.strptime(start[:10], "%Y-%m-%d").date()
        elif hasattr(start, "date"):
            start = start.date()
    except Exception:
        return 4

    current_year = datetime.now(BOGOTA_TZ).year
    if start.year < current_year:
        return 4
    if start.year > current_year:
        return 0

    quarter = ((start.month - 1) // 3) + 1
    return max(0, 5 - quarter)

def _timeoff_usage_for_year(cur, user_id: int, year: int, statuses=("approved",)) -> Dict[str, float]:
    year = int(year)
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    cur.execute("""
        SELECT kind, start_date, end_date, reason, status
        FROM time_off_requests
        WHERE user_id = %s
          AND LOWER(status) = ANY(%s)
          AND end_date >= %s
          AND start_date <= %s
    """, (int(user_id), [str(s).lower() for s in statuses], year_start, year_end))
    totals = {"vacation": 0.0, "vintti_day": 0.0, "holiday": 0.0}
    for rec in cur.fetchall():
        if isinstance(rec, dict):
            row = dict(rec)
        else:
            row = dict(zip([desc[0] for desc in cur.description], rec))
        kind = str(row.get("kind") or "").lower()
        if kind not in totals:
            continue
        clean_reason, is_half_day = _parse_timeoff_reason_meta(row.get("reason"))
        row["reason"] = clean_reason
        sd = row.get("start_date")
        ed = row.get("end_date")
        if isinstance(sd, str):
            sd = datetime.strptime(sd, "%Y-%m-%d").date()
        if isinstance(ed, str):
            ed = datetime.strptime(ed, "%Y-%m-%d").date()
        clipped_start = max(sd, year_start)
        clipped_end = min(ed, year_end)
        if clipped_end < clipped_start:
            continue
        totals[kind] += float(_timeoff_total_days(
            kind,
            clipped_start,
            clipped_end,
            is_half_day=is_half_day and sd == clipped_start and ed == clipped_end,
        ))
    return totals

def _timeoff_usage_for_user(cur, user_id: int, statuses=("approved",)) -> Dict[str, float]:
    current_year = datetime.now(BOGOTA_TZ).year
    return _timeoff_usage_for_year(cur, user_id, current_year, statuses=statuses)

def _apply_computed_timeoff_usage(cur, row: Dict[str, Any]) -> Dict[str, Any]:
    if not row or row.get("user_id") is None:
        return row
    usage = _timeoff_usage_for_user(cur, int(row["user_id"]), statuses=("approved",))
    manual_vacation_used = float(row.get("vacaciones_consumidas") or 0)
    row["vacaciones_consumidas"] = _as_day_number(max(manual_vacation_used, usage["vacation"]))
    row["vintti_days_consumidos"] = _as_day_number(usage["vintti_day"])
    row["feriados_consumidos"] = _as_day_number(usage["holiday"])
    return row

def _timeoff_available_for_kind(user_row: Dict[str, Any], kind: str, usage: Dict[str, float]) -> float:
    kind = str(kind or "").lower()
    if kind == "vacation":
        accrued = float(user_row.get("vacaciones_acumuladas") or 0)
        annual = _prorated_vacation_days_for_year(user_row.get("ingreso_vintti_date"), 15)
        return accrued + annual - usage.get("vacation", 0)
    if kind == "vintti_day":
        return 2 - usage.get("vintti_day", 0)
    if kind == "holiday":
        return _prorated_holiday_days_for_year(user_row.get("ingreso_vintti_date")) - usage.get("holiday", 0)
    return 0

def _ensure_vacation_rollover_column(cur):
    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS vacation_rollover_year INTEGER
    """)

def _ensure_user_address_column(cur):
    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS address TEXT
    """)

def _prorated_vacation_days_for_specific_year(start_value: Optional[Any], year: int, annual_days: float = 15) -> float:
    if not start_value:
        return annual_days
    try:
        start = start_value
        if isinstance(start, str):
            start = datetime.strptime(start[:10], "%Y-%m-%d").date()
        elif hasattr(start, "date"):
            start = start.date()
    except Exception:
        return annual_days

    if start.year < year:
        return annual_days
    if start.year > year:
        return 0

    months_worked = max(0, 12 - start.month + 1)
    return int((months_worked * annual_days * 2) / 12) / 2

def _vacation_rollover_amount(previous_available: float) -> float:
    if previous_available < 0:
        return previous_available
    return min(previous_available, VACATION_ROLLOVER_CAP_DAYS)

def _build_vacation_rollover_rows(cur, target_year: int, user_id: Optional[int] = None):
    target_year = int(target_year)
    source_year = target_year - 1
    params = []
    where = ""
    if user_id is not None:
        where = "WHERE user_id = %s"
        params.append(int(user_id))

    cur.execute(f"""
        SELECT user_id, user_name, email_vintti, ingreso_vintti_date,
               COALESCE(vacaciones_acumuladas, 0) AS vacaciones_acumuladas,
               COALESCE(vacaciones_habiles, 15) AS vacaciones_habiles,
               COALESCE(vacation_rollover_year, 0) AS vacation_rollover_year
        FROM users
        {where}
        ORDER BY user_id
    """, tuple(params))

    rows = []
    for user in cur.fetchall():
        user = dict(user)
        uid = int(user["user_id"])
        previous_usage = _timeoff_usage_for_year(cur, uid, source_year, statuses=("approved",))
        current_usage = _timeoff_usage_for_year(cur, uid, target_year, statuses=("approved",))
        previous_accrued = float(user.get("vacaciones_acumuladas") or 0)
        previous_entitlement = _prorated_vacation_days_for_specific_year(
            user.get("ingreso_vintti_date"),
            source_year,
            15,
        )
        previous_used = float(previous_usage.get("vacation", 0))
        previous_available = previous_accrued + previous_entitlement - previous_used
        rollover = _vacation_rollover_amount(previous_available)
        current_entitlement = _prorated_vacation_days_for_specific_year(
            user.get("ingreso_vintti_date"),
            target_year,
            15,
        )
        rows.append({
            "user_id": uid,
            "user_name": user.get("user_name"),
            "email_vintti": user.get("email_vintti"),
            "target_year": target_year,
            "source_year": source_year,
            "already_applied": int(user.get("vacation_rollover_year") or 0) >= target_year,
            "vacation_rollover_year": int(user.get("vacation_rollover_year") or 0),
            "previous_accrued": _as_day_number(previous_accrued),
            "previous_entitlement": _as_day_number(previous_entitlement),
            "previous_used": _as_day_number(previous_used),
            "previous_available": _as_day_number(previous_available),
            "rollover_days": _as_day_number(rollover),
            "current_entitlement": _as_day_number(current_entitlement),
            "current_used": _as_day_number(float(current_usage.get("vacation", 0))),
            "current_vintti_used": _as_day_number(float(current_usage.get("vintti_day", 0))),
            "current_holidays_used": _as_day_number(float(current_usage.get("holiday", 0))),
        })
    return rows

def _apply_vacation_rollover_rows(cur, rows, target_year: int, *, force: bool = False):
    applied = []
    skipped = []
    for row in rows:
        if row["already_applied"] and not force:
            skipped.append(row)
            continue
        cur.execute("""
            UPDATE users
               SET vacaciones_acumuladas = %s,
                   vacaciones_habiles = %s,
                   vacaciones_consumidas = %s,
                   vintti_days_consumidos = %s,
                   feriados_consumidos = %s,
                   vacation_rollover_year = %s,
                   updated_at = NOW() AT TIME ZONE 'UTC'
             WHERE user_id = %s
        """, (
            row["rollover_days"],
            row["current_entitlement"],
            row["current_used"],
            row["current_vintti_used"],
            row["current_holidays_used"],
            int(target_year),
            row["user_id"],
        ))
        applied.append(row)
    return applied, skipped

def _maybe_apply_current_year_vacation_rollover(cur):
    current_year = datetime.now(BOGOTA_TZ).year
    if current_year < VACATION_ROLLOVER_AUTO_START_YEAR:
        return {"applied": [], "skipped": [], "ran": False}

    _ensure_vacation_rollover_column(cur)
    cur.execute("SELECT pg_try_advisory_xact_lock(%s) AS locked", (VACATION_ROLLOVER_LOCK_KEY,))
    lock_row = cur.fetchone()
    locked = lock_row.get("locked") if isinstance(lock_row, dict) else bool(lock_row and lock_row[0])
    if not locked:
        return {"applied": [], "skipped": [], "ran": False}

    rows = _build_vacation_rollover_rows(cur, current_year)
    applied, skipped = _apply_vacation_rollover_rows(cur, rows, current_year)
    return {"applied": applied, "skipped": skipped, "ran": bool(applied)}

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

def _initials_from_name(name: Optional[Any]) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    parts = [p for p in text.split() if p]
    if not parts:
        return ""
    first = parts[0][0] if parts[0] else ""
    if len(parts) > 1 and parts[-1]:
        second = parts[-1][0]
    else:
        second = parts[0][1] if len(parts[0]) > 1 else ""
    return (first + (second or "")).upper()

def _add_initials(row: Dict[str, Any], name_key: str = "user_name") -> Dict[str, Any]:
    if isinstance(row, dict):
        row["initials"] = _initials_from_name(row.get(name_key))
    return row

# ---------- USERS ----------
@users_bp.get("/users/<int:user_id>")
def get_user(user_id: int):
    q = """
    SELECT
      user_id, user_name, nickname, email_vintti, role, emergency_contact,
      ingreso_vintti_date, fecha_nacimiento, avatar_url,
      country, city, address, about_me, hobbies, favorite_food, fun_fact,
      team, lider,
      COALESCE(vacaciones_acumuladas, 0)    AS vacaciones_acumuladas,
      COALESCE(vacaciones_habiles, 0)       AS vacaciones_habiles,
      COALESCE(vacaciones_consumidas, 0)    AS vacaciones_consumidas,
      COALESCE(vintti_days_consumidos, 0)   AS vintti_days_consumidos,
      COALESCE(feriados_consumidos, 0)      AS feriados_consumidos
    FROM users
    WHERE user_id = %s
    """
    conn = get_connection()
    should_commit = False
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        _ensure_user_address_column(cur)
        should_commit = bool(_maybe_apply_current_year_vacation_rollover(cur).get("ran"))
        cur.execute(q, (user_id,))
        row = cur.fetchone()
        if row:
            row = _apply_computed_timeoff_usage(cur, dict(row))
    if should_commit:
        conn.commit()
    conn.close()
    if not row: return jsonify({"error":"user not found"}), 404
    return jsonify(_add_initials(_row_to_json(dict(row))))

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

    editable_fields = (
        "user_name",
        "email_vintti",
        "role",
        "emergency_contact",
        "ingreso_vintti_date",
        "fecha_nacimiento",
        "country",
        "city",
        "address",
        "about_me",
        "hobbies",
        "favorite_food",
        "fun_fact",
    )
    fields = {field: data.get(field) for field in editable_fields if field in data}

    avatar_specified = "avatar_url" in data
    avatar_value: Optional[str] = None
    if avatar_specified:
        try:
            avatar_value = _normalize_avatar_url(data.get("avatar_url"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    sets, vals = [], []
    for col, val in fields.items():
        sets.append(f"{col} = %s"); vals.append(val)

    if "ingreso_vintti_date" in fields and fields.get("ingreso_vintti_date") is not None:
        sets.append("vacaciones_habiles = %s")
        vals.append(_prorated_vacation_days_for_year(fields["ingreso_vintti_date"]))

    if avatar_specified:
        if avatar_value is None:
            sets.append("avatar_url = NULL")
        else:
            sets.append("avatar_url = %s"); vals.append(avatar_value)

    if not sets: return jsonify({"ok": True})

    vals.append(user_id)
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        _ensure_user_address_column(cur)
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
        _ensure_user_address_column(cur)
        cur.execute("""
            SELECT user_id, user_name, email_vintti, role, emergency_contact,
                ingreso_vintti_date, fecha_nacimiento, avatar_url,
                country, city, address, about_me, hobbies, favorite_food, fun_fact,
                team
            FROM users WHERE user_id = %s
        """, (user_id,))
        row = cur.fetchone()
    conn.close()
    if not row: return jsonify({"error":"not found"}), 404
    return jsonify(_add_initials(_row_to_json(dict(row))))

@bp.route("/admin/vacation_rollover", methods=["GET", "POST"])
def admin_vacation_rollover():
    caller = _current_user_id()
    if not caller:
        return jsonify({"error": "forbidden"}), 403

    today = datetime.now(BOGOTA_TZ).date()
    data = request.get_json(silent=True) or {}
    target_year = _int_or_none(request.args.get("target_year") or data.get("target_year")) or today.year
    user_id = _int_or_none(request.args.get("user_id") or data.get("user_id"))
    force = str(request.args.get("force") or data.get("force") or "").lower() in {"1", "true", "yes"}
    dry_run = request.method == "GET" or str(request.args.get("dry_run") or data.get("dry_run") or "").lower() in {"1", "true", "yes"}

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if not _is_allowed_leader(cur, caller):
                conn.rollback()
                return jsonify({"error": "forbidden"}), 403

            _ensure_vacation_rollover_column(cur)
            rows = _build_vacation_rollover_rows(cur, target_year, user_id=user_id)
            applied, skipped = ([], [])
            if not dry_run:
                applied, skipped = _apply_vacation_rollover_rows(cur, rows, target_year, force=force)

            conn.commit()
            return jsonify({
                "ok": True,
                "dry_run": dry_run,
                "target_year": target_year,
                "source_year": target_year - 1,
                "cap_days": VACATION_ROLLOVER_CAP_DAYS,
                "applied_count": len(applied),
                "skipped_count": len(skipped),
                "rows": rows if dry_run else applied,
                "skipped": skipped,
            })
    except Exception as exc:
        conn.rollback()
        return jsonify({"error": "db error", "detail": str(exc)}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass

@bp.get("/leader/time_off_requests")
def leader_list_timeoff():
    """Return requests for users whose 'lider' == current leader."""
    leader_id = _current_user_id()
    if not leader_id:
        return jsonify({"error": "unauthorized"}), 401

    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if not _is_allowed_leader(cur, leader_id):
            return jsonify({"error":"forbidden"}), 403

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
    payload = []
    for r in rows:
        payload.append(_add_initials(_normalize_timeoff_row(_row_to_json(dict(r)))))
    return jsonify(payload)


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
            if not _is_allowed_leader(cur, leader_id):
                return jsonify({"error":"forbidden"}), 403

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
            rec = dict(rec)
            clean_reason, is_half_day = _parse_timeoff_reason_meta(rec.get("reason"))
            rec["reason"] = clean_reason
            rec["is_half_day"] = bool(is_half_day and str(rec.get("kind") or "").lower() == "vacation")

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
                k = str(rec["kind"] or "").lower()
                total_days = _timeoff_total_days(
                    k,
                    rec["start_date"],
                    rec["end_date"],
                    is_half_day=bool(rec.get("is_half_day"))
                )

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
            kind_lower = str(rec["kind"] or "").lower()
            total_days = _timeoff_total_days(
                kind_lower,
                rec["start_date"],
                rec["end_date"],
                is_half_day=bool(rec.get("is_half_day"))
            )
            total_days_label = "Business days" if kind_lower == "vacation" else "Days"
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
            parts.append(f"<li><strong>{total_days_label}:</strong> {_as_day_number(total_days)}</li>")
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

    return jsonify([_normalize_timeoff_row(_row_to_json(dict(r))) for r in rows])

@bp.get("/users")
def list_users():
    email = request.args.get("email")
    conn = get_connection()
    should_commit = False
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        _ensure_user_address_column(cur)
        should_commit = bool(_maybe_apply_current_year_vacation_rollover(cur).get("ran"))
        if email:
            cur.execute("SELECT * FROM users WHERE LOWER(email_vintti) = LOWER(%s)", (email,))
        else:
            cur.execute("SELECT * FROM users")
        rows = cur.fetchall()
        rows = [_apply_computed_timeoff_usage(cur, dict(row)) for row in rows]
    if should_commit:
        conn.commit()
    conn.close()
    payload = []
    for row in rows:
        payload.append(_add_initials(_row_to_json(dict(row))))
    return jsonify(payload)

@bp.post("/time_off_requests")
def create_time_off():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    kind_raw = (data.get("kind") or "").strip().lower()
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    reason = (data.get("reason") or "").strip() or None
    is_half_day_raw = data.get("is_half_day", False)
    if isinstance(is_half_day_raw, bool):
        is_half_day = is_half_day_raw
    else:
        is_half_day = str(is_half_day_raw).strip().lower() in {"1", "true", "yes", "on"}

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
    if is_half_day:
        if kind_raw != "vacation":
            return jsonify({"error":"half day is only available for vacation"}), 400
        if start_date != end_date:
            return jsonify({"error":"half day vacation must use the same start and end date"}), 400
        try:
            d = datetime.strptime(start_date, "%Y-%m-%d").date()
            if business_days_us(d, d) != 1:
                return jsonify({"error":"half day vacation must be on a business day"}), 400
        except Exception:
            return jsonify({"error":"invalid date for half day vacation"}), 400

    stored_reason = _encode_timeoff_reason(reason, is_half_day)

    # Insert + fetch requester + leader in one go
    conn = get_connection()
    new_id = None
    requester = None
    leader_email = None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _maybe_apply_current_year_vacation_rollover(cur)
            cur.execute("""
                SELECT u.user_id, u.user_name, u.email_vintti, u.lider,
                       u.ingreso_vintti_date,
                       COALESCE(u.vacaciones_acumuladas, 0) AS vacaciones_acumuladas,
                       l.email_vintti AS leader_email
                FROM users u
                LEFT JOIN users l ON l.user_id = u.lider
                WHERE u.user_id = %s
            """, (int(user_id),))
            requester = cur.fetchone()
            if not requester:
                conn.rollback()
                return jsonify({"error": "user not found"}), 404

            try:
                requested_days = float(_timeoff_total_days(
                    kind_raw,
                    start_date,
                    end_date,
                    is_half_day=is_half_day,
                ))
            except Exception:
                conn.rollback()
                return jsonify({"error": "invalid dates"}), 400

            reserved_usage = _timeoff_usage_for_user(cur, int(user_id), statuses=("approved", "pending"))
            available_days = _timeoff_available_for_kind(dict(requester), kind_raw, reserved_usage)
            if kind_raw in {"vintti_day", "holiday"} and requested_days > available_days:
                conn.rollback()
                return jsonify({
                    "error": "not enough time off available",
                    "kind": kind_raw,
                    "requested_days": _as_day_number(requested_days),
                    "available_days": _as_day_number(max(0, available_days)),
                }), 409

            # 1) insert
            cur.execute("""
                INSERT INTO time_off_requests (user_id, kind, start_date, end_date, reason, status, created_at)
                VALUES (%s, %s, %s, %s, %s, 'pending', NOW() AT TIME ZONE 'UTC')
                RETURNING id
            """, (int(user_id), kind_raw, start_date, end_date, stored_reason))
            row = cur.fetchone()
            new_id = row["id"]

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
        num_days = _timeoff_total_days(kind_raw, start_date, end_date, is_half_day=is_half_day)
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
    if num_days is not None:
        pretty_num_days = _as_day_number(num_days)
        html_parts.append(f"<li><strong>Total days:</strong> {pretty_num_days} day{'s' if num_days != 1 else ''}</li>")
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

    # Targets: direct leader (if any) + PTO watchers
    to_list = []
    if leader_email:
        to_list.append(leader_email)
    to_list.extend([
        "jazmin@vintti.com",
        "pgonzales@vintti.com",
        "lara@vintti.com",
    ])
    to_list = list(dict.fromkeys(email.strip().lower() for email in to_list if email))

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
