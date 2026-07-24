"""Hirex ATS — Slice 1: Jobs module.

Fresh, decoupled hirex_* schema. Depends on the migration
backend/sql/20260724_add_hirex_jobs.sql being applied to RDS.
"""
from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor, Json

from db import get_connection

bp = Blueprint("hirex", __name__, url_prefix="/hirex")

# --- Domain enums (kept loose; validated softly) -----------------------------
VALID_STATUSES = {"draft", "open", "on_hold", "closed", "archived"}
VALID_PRIORITIES = {"low", "medium", "high", "urgent"}

# Columns a client may set on create/edit (whitelist — never trust the body).
TEXT_FIELDS = {
    "title", "department", "location", "work_mode", "employment_type",
    "salary_currency", "salary_period", "recruiter_email", "hiring_manager_email",
    "priority", "status", "description", "benefits", "requirements",
    "language", "seniority",
}
NUMERIC_FIELDS = {"salary_min", "salary_max"}
INT_FIELDS = {"openings"}
JSON_FIELDS = {
    "tags", "skills", "workflow", "scorecard_config",
    "custom_form", "knockout_questions",
}
EDITABLE_FIELDS = TEXT_FIELDS | NUMERIC_FIELDS | INT_FIELDS | JSON_FIELDS

# Columns returned to the client.
SELECT_COLS = """
    job_id, title, department, location, work_mode, employment_type,
    salary_min, salary_max, salary_currency, salary_period,
    recruiter_email, hiring_manager_email, priority, status, openings,
    tags, description, benefits, requirements, skills, language, seniority,
    workflow, scorecard_config, custom_form, knockout_questions,
    created_by, created_at, updated_at
"""


def _actor_email():
    """Best-effort identity: body actor_email, then X-User-Email header."""
    data = request.get_json(silent=True) or {}
    return (data.get("actor_email")
            or request.headers.get("X-User-Email")
            or "").strip().lower() or None


def _coerce_value(field, value):
    """Coerce/validate a single incoming field value. Returns (ok, coerced_or_error)."""
    if value is None:
        return True, None
    if field in NUMERIC_FIELDS:
        try:
            return True, float(value)
        except (TypeError, ValueError):
            return False, f"{field} must be a number"
    if field in INT_FIELDS:
        try:
            return True, int(value)
        except (TypeError, ValueError):
            return False, f"{field} must be an integer"
    if field in JSON_FIELDS:
        return True, Json(value)
    # text
    return True, str(value)


def _clean_payload(data):
    """Build (columns, values) from a request body. Returns (cols, vals, error)."""
    cols, vals = [], []
    for field in EDITABLE_FIELDS:
        if field not in data:
            continue
        ok, coerced = _coerce_value(field, data[field])
        if not ok:
            return None, None, coerced
        cols.append(field)
        vals.append(coerced)
    return cols, vals, None


def _validate_business_rules(data):
    """Cross-field validation shared by create/edit. Returns error str or None."""
    smin, smax = data.get("salary_min"), data.get("salary_max")
    if smin is not None and smax is not None:
        try:
            if float(smin) > float(smax):
                return "salary_min cannot be greater than salary_max"
        except (TypeError, ValueError):
            return "salary_min/salary_max must be numbers"
    if "openings" in data and data["openings"] is not None:
        try:
            if int(data["openings"]) < 1:
                return "openings must be at least 1"
        except (TypeError, ValueError):
            return "openings must be an integer"
    status = data.get("status")
    if status is not None and status not in VALID_STATUSES:
        return f"invalid status '{status}'"
    priority = data.get("priority")
    if priority is not None and priority not in VALID_PRIORITIES:
        return f"invalid priority '{priority}'"
    return None


def _log_activity(cur, job_id, actor_email, action, detail=None):
    cur.execute(
        "INSERT INTO hirex_job_activity (job_id, actor_email, action, detail) "
        "VALUES (%s, %s, %s, %s);",
        (job_id, actor_email, action, Json(detail or {})),
    )


# --- Routes ------------------------------------------------------------------
@bp.route("/jobs", methods=["GET"])
def list_jobs():
    """List jobs with optional filters: status, priority, department, recruiter, q."""
    args = request.args
    where, params = [], []
    if args.get("status"):
        where.append("status = %s")
        params.append(args["status"])
    if args.get("priority"):
        where.append("priority = %s")
        params.append(args["priority"])
    if args.get("department"):
        where.append("LOWER(department) = LOWER(%s)")
        params.append(args["department"])
    if args.get("recruiter"):
        where.append("LOWER(recruiter_email) = LOWER(%s)")
        params.append(args["recruiter"])
    if args.get("q"):
        where.append("(LOWER(title) LIKE %s OR LOWER(COALESCE(department,'')) LIKE %s "
                     "OR LOWER(COALESCE(location,'')) LIKE %s)")
        like = f"%{args['q'].lower()}%"
        params.extend([like, like, like])

    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            f"SELECT {SELECT_COLS} FROM hirex_jobs {clause} "
            f"ORDER BY updated_at DESC, job_id DESC;",
            tuple(params),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/jobs/<int:job_id>", methods=["GET"])
def get_job(job_id):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(f"SELECT {SELECT_COLS} FROM hirex_jobs WHERE job_id = %s;", (job_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return jsonify({"error": "job not found"}), 404
        return jsonify(row)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/jobs", methods=["POST"])
def create_job():
    data = request.get_json(silent=True) or {}
    if not (data.get("title") or "").strip():
        return jsonify({"error": "title is required"}), 400
    err = _validate_business_rules(data)
    if err:
        return jsonify({"error": err}), 400

    cols, vals, err = _clean_payload(data)
    if err:
        return jsonify({"error": err}), 400

    actor = _actor_email()
    if "created_by" not in cols and actor:
        cols.append("created_by")
        vals.append(actor)

    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)

    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '5s';")
            cur.execute("SET LOCAL statement_timeout = '10s';")
            cur.execute(
                f"INSERT INTO hirex_jobs ({col_list}) VALUES ({placeholders}) "
                f"RETURNING {SELECT_COLS};",
                tuple(vals),
            )
            row = cur.fetchone()
            _log_activity(cur, row["job_id"], actor, "created",
                          {"title": row["title"], "status": row["status"]})
            conn.commit()
        return jsonify(row), 201
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


@bp.route("/jobs/<int:job_id>", methods=["PATCH", "PUT"])
def update_job(job_id):
    data = request.get_json(silent=True) or {}
    if "title" in data and not (data.get("title") or "").strip():
        return jsonify({"error": "title cannot be empty"}), 400
    err = _validate_business_rules(data)
    if err:
        return jsonify({"error": err}), 400

    cols, vals, err = _clean_payload(data)
    if err:
        return jsonify({"error": err}), 400
    if not cols:
        return jsonify({"error": "no editable fields provided"}), 400

    assignments = ", ".join([f"{c} = %s" for c in cols]) + ", updated_at = NOW()"
    actor = _actor_email()

    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '5s';")
            cur.execute("SET LOCAL statement_timeout = '10s';")
            cur.execute(
                f"UPDATE hirex_jobs SET {assignments} WHERE job_id = %s "
                f"RETURNING {SELECT_COLS};",
                tuple(vals) + (job_id,),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return jsonify({"error": "job not found"}), 404
            _log_activity(cur, job_id, actor, "updated", {"fields": cols})
            conn.commit()
        return jsonify(row)
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


@bp.route("/jobs/<int:job_id>/status", methods=["POST"])
def set_job_status(job_id):
    data = request.get_json(silent=True) or {}
    status = (data.get("status") or "").strip()
    if status not in VALID_STATUSES:
        return jsonify({"error": f"invalid status '{status}'"}), 400
    actor = _actor_email()

    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '5s';")
            cur.execute("SET LOCAL statement_timeout = '10s';")
            cur.execute("SELECT status FROM hirex_jobs WHERE job_id = %s FOR UPDATE;", (job_id,))
            existing = cur.fetchone()
            if not existing:
                conn.rollback()
                return jsonify({"error": "job not found"}), 404
            cur.execute(
                f"UPDATE hirex_jobs SET status = %s, updated_at = NOW() "
                f"WHERE job_id = %s RETURNING {SELECT_COLS};",
                (status, job_id),
            )
            row = cur.fetchone()
            _log_activity(cur, job_id, actor, "status_changed",
                          {"from": existing["status"], "to": status})
            conn.commit()
        return jsonify(row)
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


@bp.route("/jobs/<int:job_id>/duplicate", methods=["POST"])
def duplicate_job(job_id):
    actor = _actor_email()
    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '5s';")
            cur.execute("SET LOCAL statement_timeout = '10s';")
            # Copy every field except identity/timestamps; reset status to draft,
            # append " (Copy)" to the title, and stamp the duplicating user.
            cur.execute(
                f"""
                INSERT INTO hirex_jobs (
                    title, department, location, work_mode, employment_type,
                    salary_min, salary_max, salary_currency, salary_period,
                    recruiter_email, hiring_manager_email, priority, status, openings,
                    tags, description, benefits, requirements, skills, language, seniority,
                    workflow, scorecard_config, custom_form, knockout_questions, created_by
                )
                SELECT
                    title || ' (Copy)', department, location, work_mode, employment_type,
                    salary_min, salary_max, salary_currency, salary_period,
                    recruiter_email, hiring_manager_email, priority, 'draft', openings,
                    tags, description, benefits, requirements, skills, language, seniority,
                    workflow, scorecard_config, custom_form, knockout_questions,
                    COALESCE(%s, created_by)
                FROM hirex_jobs WHERE job_id = %s
                RETURNING {SELECT_COLS};
                """,
                (actor, job_id),
            )
            new_row = cur.fetchone()
            if not new_row:
                conn.rollback()
                return jsonify({"error": "job not found"}), 404
            _log_activity(cur, new_row["job_id"], actor, "duplicated",
                          {"source_job_id": job_id})
            conn.commit()
        return jsonify(new_row), 201
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


@bp.route("/jobs/<int:job_id>", methods=["DELETE"])
def delete_job(job_id):
    """Hard-delete a job and its activity trail. Irreversible."""
    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '5s';")
            cur.execute("SET LOCAL statement_timeout = '10s';")
            cur.execute("DELETE FROM hirex_jobs WHERE job_id = %s RETURNING job_id;", (job_id,))
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return jsonify({"error": "job not found"}), 404
            cur.execute("DELETE FROM hirex_job_activity WHERE job_id = %s;", (job_id,))
            conn.commit()
        return jsonify({"deleted": True, "job_id": job_id})
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


@bp.route("/jobs/<int:job_id>/activity", methods=["GET"])
def job_activity(job_id):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT id, job_id, actor_email, action, detail, created_at "
            "FROM hirex_job_activity WHERE job_id = %s "
            "ORDER BY created_at DESC, id DESC;",
            (job_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
