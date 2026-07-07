"""Offboarding / soft-delete de empleados.

Reemplaza el hard-delete por una desactivación (admin_user_access.is_active=FALSE, que
el login ya bloquea) + un proceso de offboarding con formulario y emails recordatorios
cada 24h. Visible solo para Jazmín (todo) y el Hiring Manager del empleado (users.lider).

Reutiliza `reminders_routes._send_email` para el envío. El esquema se crea en runtime con
`_ensure_offboarding_schema` (patrón `_ensure_*` del proyecto, sin migration runner).
"""
from __future__ import annotations

import html
import logging
from typing import Optional

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from admin_access import normalize_email
from db import get_connection

bp = Blueprint("offboarding", __name__)

JAZ_EMAIL = "jazmin@vintti.com"
AGUS_EMAIL = "agustin@vintti.com"
PGONZALES_EMAIL = "pgonzales@vintti.com"
LAR_EMAIL = "lara@vintti.com"
INACTIVE_VIEWER_EMAILS = {JAZ_EMAIL, AGUS_EMAIL}

VALID_REASONS = {
    "Received a better offer",
    "Poor performance",
    "Employee decided to leave",
    "Layoff",
}


# --------------------------------------------------------------------------- #
# Schema (lazy, sin migration runner — igual que admin_access / reminders)
# --------------------------------------------------------------------------- #
def _ensure_offboarding_schema(cur) -> None:
    cur.execute("ALTER TABLE admin_user_access ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ")
    cur.execute("ALTER TABLE admin_user_access ADD COLUMN IF NOT EXISTS deactivated_by_email TEXT")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS offboarding (
            offboarding_id           BIGSERIAL PRIMARY KEY,
            user_id                  INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            hiring_manager_id        INTEGER REFERENCES users(user_id),
            end_date                 DATE,
            reason                   TEXT,
            computer_pickup          BOOLEAN NOT NULL DEFAULT FALSE,
            address                  TEXT,
            comments                 TEXT,
            status                   TEXT NOT NULL DEFAULT 'pending',
            computer_pickup_done     BOOLEAN NOT NULL DEFAULT FALSE,
            form_submitted_at        TIMESTAMPTZ,
            offboarding_last_sent_at TIMESTAMPTZ,
            pickup_last_sent_at      TIMESTAMPTZ,
            created_by_email         TEXT,
            completed_at             TIMESTAMPTZ,
            completed_by_email       TEXT,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_offboarding_user ON offboarding (user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_offboarding_status ON offboarding (status)")


# --------------------------------------------------------------------------- #
# Identidad + permisos (autoritativos en server)
# --------------------------------------------------------------------------- #
def _current_user_id() -> Optional[int]:
    for src in (
        request.args.get("user_id"),
        request.cookies.get("user_id"),
        request.headers.get("X-User-Id"),
        request.headers.get("x-user-id"),
    ):
        try:
            if src is not None and str(src).strip() != "":
                return int(src)
        except (TypeError, ValueError):
            continue
    return None


def _requester(cur) -> Optional[dict]:
    uid = _current_user_id()
    if not uid:
        return None
    cur.execute("SELECT user_id, email_vintti FROM users WHERE user_id = %s", (uid,))
    row = cur.fetchone()
    if not row:
        return None
    return {"user_id": int(row["user_id"]), "email": normalize_email(row.get("email_vintti"))}


def _manager_id(row: dict):
    """Manager autoritativo del offboarding: snapshot hiring_manager_id, si no, users.lider."""
    hm = row.get("hiring_manager_id")
    return hm if hm is not None else row.get("lider")


def _can_view_pending(requester: Optional[dict], row: dict) -> bool:
    if not requester:
        return False
    if requester["email"] == JAZ_EMAIL:
        return True
    mgr = _manager_id(row)
    return mgr is not None and int(requester["user_id"]) == int(mgr)


def _can_view_inactive(requester: Optional[dict]) -> bool:
    return bool(requester and requester["email"] in INACTIVE_VIEWER_EMAILS)


def _can_submit(requester: Optional[dict], row: dict) -> bool:
    if not requester:
        return False
    mgr = _manager_id(row)
    if mgr is None:
        return False
    return int(requester["user_id"]) == int(mgr)


def _can_act(requester: Optional[dict], row: dict) -> bool:
    if not requester:
        return False
    if requester["email"] == JAZ_EMAIL:
        return True
    return _can_submit(requester, row)


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _serialize(row: dict) -> dict:
    return {
        "user_id": row.get("user_id"),
        "user_name": row.get("user_name"),
        "role": row.get("role"),
        "email_vintti": row.get("email_vintti"),
        "hiring_manager_id": _manager_id(row),
        "manager_name": row.get("manager_name"),
        "end_date": str(row["end_date"]) if row.get("end_date") else None,
        "reason": row.get("reason"),
        "computer_pickup": bool(row.get("computer_pickup")),
        "address": row.get("address"),
        "employee_address": row.get("employee_address"),  # users.address, para autollenar
        "comments": row.get("comments"),
        "status": row.get("status") or "pending",
        "computer_pickup_done": bool(row.get("computer_pickup_done")),
        "form_submitted": row.get("form_submitted_at") is not None,
    }


_SELECT_JOIN = """
    SELECT o.*, u.user_name, u.role, u.email_vintti, u.lider,
           u.address AS employee_address,
           m.user_name AS manager_name
    FROM offboarding o
    JOIN users u ON u.user_id = o.user_id
    LEFT JOIN users m ON m.user_id = COALESCE(o.hiring_manager_id, u.lider)
"""


# --------------------------------------------------------------------------- #
# Emails
# --------------------------------------------------------------------------- #
def _main_email_html(employee_name, manager_name, end_date, reason, computer_pickup, comments) -> str:
    pk = "Yes" if computer_pickup else "No"
    rows = [
        ("Employee", employee_name),
        ("Hiring Manager", manager_name or "—"),
        ("End date", str(end_date) if end_date else "—"),
        ("Reason", reason or "—"),
        ("Computer pick up", pk),
        ("Comments", comments or "—"),
    ]
    items = "".join(
        f"<li style='margin:0 0 6px'><b>{html.escape(str(k))}:</b> {html.escape(str(v))}</li>"
        for k, v in rows
    )
    return f"""
    <div style="font-family:Inter,Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.6;color:#0f172a">
      <p>Hi,</p>
      <p>An employee has been <b>deactivated</b> and their offboarding was submitted. Details:</p>
      <ul style="padding-left:20px;margin:12px 0">{items}</ul>
      <p>This reminder repeats every 24h until the offboarding is marked <b>Completed</b>.</p>
      <p>— Vintti Hub</p>
    </div>
    """


def _pickup_email_html(employee_name, end_date, address, comments) -> str:
    rows = [
        ("Employee", employee_name),
        ("End date", str(end_date) if end_date else "—"),
        ("Address", address or "—"),
        ("Comments", comments or "—"),
    ]
    items = "".join(
        f"<li style='margin:0 0 6px'><b>{html.escape(str(k))}:</b> {html.escape(str(v))}</li>"
        for k, v in rows
    )
    return f"""
    <div style="font-family:Inter,Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.6;color:#0f172a">
      <p>Hi,</p>
      <p>A <b>computer pick up</b> is required for a deactivated employee:</p>
      <ul style="padding-left:20px;margin:12px 0">{items}</ul>
      <p>This reminder repeats every 24h until the pick up is marked done.</p>
      <p>— Vintti Hub</p>
    </div>
    """


def _send_offboarding_emails(cur, row: dict, *, main: bool, pickup: bool) -> list:
    """Envía los emails y actualiza los *_last_sent_at. Reutiliza reminders_routes._send_email."""
    from reminders_routes import _send_email  # import diferido: evita ciclo en load-time

    sent = []
    name = row.get("user_name") or "Employee"
    if main:
        ok = _send_email(
            subject=f"Offboarding submitted — {name}",
            html_body=_main_email_html(
                name, row.get("manager_name"), row.get("end_date"),
                row.get("reason"), bool(row.get("computer_pickup")), row.get("comments"),
            ),
            to=[JAZ_EMAIL, PGONZALES_EMAIL],
        )
        if ok:
            cur.execute(
                "UPDATE offboarding SET offboarding_last_sent_at = now(), updated_at = now() WHERE offboarding_id = %s",
                (row["offboarding_id"],),
            )
            sent.append({"stream": "main", "to": [JAZ_EMAIL, PGONZALES_EMAIL], "user_id": row["user_id"]})
    if pickup and bool(row.get("computer_pickup")) and not bool(row.get("computer_pickup_done")):
        ok = _send_email(
            subject=f"Computer pick up needed — {name}",
            html_body=_pickup_email_html(name, row.get("end_date"), row.get("address"), row.get("comments")),
            to=[LAR_EMAIL, PGONZALES_EMAIL],
        )
        if ok:
            cur.execute(
                "UPDATE offboarding SET pickup_last_sent_at = now(), updated_at = now() WHERE offboarding_id = %s",
                (row["offboarding_id"],),
            )
            sent.append({"stream": "pickup", "to": [LAR_EMAIL, PGONZALES_EMAIL], "user_id": row["user_id"]})
    return sent


def run_due_offboarding_reminders(cur) -> list:
    """Reenvía cada 24h hasta que se marque Completed (main) / pickup done (pickup).
    Recibe un cursor (RealDictCursor); NO hace commit (lo hace el orquestador /reminders/due)."""
    _ensure_offboarding_schema(cur)
    sent = []

    # Stream main → jazmin + pgonzales
    cur.execute(
        _SELECT_JOIN
        + """
        WHERE o.form_submitted_at IS NOT NULL
          AND o.status = 'pending'
          AND (o.offboarding_last_sent_at IS NULL
               OR now() - o.offboarding_last_sent_at >= interval '24 hours')
        """
    )
    for r in (cur.fetchall() or []):
        sent += _send_offboarding_emails(cur, dict(r), main=True, pickup=False)

    # Stream pickup → lara + pgonzales
    cur.execute(
        _SELECT_JOIN
        + """
        WHERE o.form_submitted_at IS NOT NULL
          AND o.computer_pickup = TRUE
          AND o.computer_pickup_done = FALSE
          AND (o.pickup_last_sent_at IS NULL
               OR now() - o.pickup_last_sent_at >= interval '24 hours')
        """
    )
    for r in (cur.fetchall() or []):
        sent += _send_offboarding_emails(cur, dict(r), main=False, pickup=True)

    return sent


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
def _err(msg, code):
    return jsonify({"ok": False, "error": msg}), code


@bp.get("/offboarding/pending")
def offboarding_pending():
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_offboarding_schema(cur)
            requester = _requester(cur)
            if not requester:
                return _err("Please log in again.", 401)
            cur.execute(_SELECT_JOIN + " WHERE o.status = 'pending' ORDER BY u.user_name")
            rows = [dict(r) for r in (cur.fetchall() or [])]
        conn.commit()
    finally:
        conn.close()
    out = [_serialize(r) for r in rows if _can_view_pending(requester, r)]
    return jsonify(out)


@bp.get("/offboarding/inactive")
def offboarding_inactive():
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_offboarding_schema(cur)
            requester = _requester(cur)
            if not requester:
                return _err("Please log in again.", 401)
            if not _can_view_inactive(requester):
                return _err("You do not have access to inactive employees.", 403)
            cur.execute(_SELECT_JOIN + " ORDER BY (o.status='completed'), u.user_name")
            rows = [dict(r) for r in (cur.fetchall() or [])]
        conn.commit()
    finally:
        conn.close()
    out = []
    for r in rows:
        item = _serialize(r)
        item["can_act"] = _can_act(requester, r)
        item["can_submit"] = _can_submit(requester, r)
        out.append(item)
    return jsonify(out)


@bp.get("/offboarding/<int:user_id>")
def offboarding_get(user_id: int):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_offboarding_schema(cur)
            requester = _requester(cur)
            if not requester:
                return _err("Please log in again.", 401)
            cur.execute(_SELECT_JOIN + " WHERE o.user_id = %s", (user_id,))
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()
    if not row:
        return _err("Offboarding not found.", 404)
    row = dict(row)
    if not _can_view_pending(requester, row):
        return _err("You do not have access to this offboarding.", 403)
    item = _serialize(row)
    item["can_act"] = _can_act(requester, row)
    item["can_submit"] = _can_submit(requester, row)
    return jsonify(item)


@bp.post("/offboarding/<int:user_id>/submit")
def offboarding_submit(user_id: int):
    data = request.get_json(silent=True) or {}
    end_date = (data.get("end_date") or "").strip() or None
    reason = (data.get("reason") or "").strip()
    computer_pickup = _bool(data.get("computer_pickup"))
    address = (data.get("address") or "").strip() or None
    comments = (data.get("comments") or "").strip() or None

    if reason not in VALID_REASONS:
        return _err("Please pick a valid reason.", 400)
    if computer_pickup and not address:
        return _err("Address is required when Computer Pick Up is Yes.", 400)

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_offboarding_schema(cur)
            requester = _requester(cur)
            if not requester:
                return _err("Please log in again.", 401)
            cur.execute(_SELECT_JOIN + " WHERE o.user_id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                return _err("Offboarding not found.", 404)
            row = dict(row)
            if not _can_submit(requester, row):
                return _err("Only the Hiring Manager can submit this offboarding.", 403)

            cur.execute(
                """
                UPDATE offboarding
                   SET end_date = %s, reason = %s, computer_pickup = %s, address = %s,
                       comments = %s, form_submitted_at = COALESCE(form_submitted_at, now()),
                       created_by_email = COALESCE(created_by_email, %s), updated_at = now()
                 WHERE user_id = %s
                """,
                (end_date, reason, computer_pickup, address, comments, requester["email"], user_id),
            )
            # Releer con los datos nuevos para armar el email.
            cur.execute(_SELECT_JOIN + " WHERE o.user_id = %s", (user_id,))
            fresh = dict(cur.fetchone())
            emailed = _send_offboarding_emails(cur, fresh, main=True, pickup=True)
            cur.execute(_SELECT_JOIN + " WHERE o.user_id = %s", (user_id,))
            out = dict(cur.fetchone())
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception("offboarding submit failed")
        return _err("Could not submit the offboarding right now.", 500)
    finally:
        conn.close()
    result = _serialize(out)
    result["emailed"] = emailed
    return jsonify(result)


def _mark(user_id: int, sql: str):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_offboarding_schema(cur)
            requester = _requester(cur)
            if not requester:
                return _err("Please log in again.", 401)
            cur.execute(_SELECT_JOIN + " WHERE o.user_id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                return _err("Offboarding not found.", 404)
            row = dict(row)
            if not _can_act(requester, row):
                return _err("Only the Hiring Manager can update this offboarding.", 403)
            cur.execute(sql, (requester["email"], user_id))
            cur.execute(_SELECT_JOIN + " WHERE o.user_id = %s", (user_id,))
            out = dict(cur.fetchone())
        conn.commit()
    finally:
        conn.close()
    return jsonify(_serialize(out))


@bp.post("/offboarding/<int:user_id>/complete")
def offboarding_complete(user_id: int):
    return _mark(
        user_id,
        """
        UPDATE offboarding
           SET status = 'completed', completed_at = now(),
               completed_by_email = %s, updated_at = now()
         WHERE user_id = %s
        """,
    )


@bp.post("/offboarding/<int:user_id>/pickup_done")
def offboarding_pickup_done(user_id: int):
    return _mark(
        user_id,
        """
        UPDATE offboarding
           SET computer_pickup_done = TRUE, updated_at = now(),
               completed_by_email = COALESCE(completed_by_email, %s)
         WHERE user_id = %s
        """,
    )


@bp.post("/reminders/offboarding/due")
def reminders_offboarding_due():
    """Test manual (el cron real llama a /reminders/due que también corre esto)."""
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        sent = run_due_offboarding_reminders(cur)
        conn.commit()
        return jsonify({"sent": sent})
