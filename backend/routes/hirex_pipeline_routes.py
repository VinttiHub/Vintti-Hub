"""Hirex ATS — Slice 2: candidate pipeline.

Applications (candidate ↔ job at a stage) + candidate records.
Depends on backend/sql/20260724_add_hirex_pipeline.sql being applied to RDS.
Stage moves are logged into hirex_job_activity so the job Activity tab is live.
"""
from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor, Json

from db import get_connection

bp = Blueprint("hirex_pipeline", __name__, url_prefix="/hirex")

VALID_STAGES = ["applied", "screening", "interview", "offer", "hired", "rejected"]
STAGE_SET = set(VALID_STAGES)

CAND_FIELDS = ["full_name", "email", "phone", "headline", "location",
               "linkedin_url", "source", "notes"]


def _actor_email():
    data = request.get_json(silent=True) or {}
    return (data.get("actor_email")
            or request.headers.get("X-User-Email")
            or "").strip().lower() or None


def _log_activity(cur, job_id, actor, action, detail=None):
    cur.execute(
        "INSERT INTO hirex_job_activity (job_id, actor_email, action, detail) "
        "VALUES (%s, %s, %s, %s);",
        (job_id, actor, action, Json(detail or {})),
    )


def _nest(row, with_analysis=False):
    """Split a joined application+candidate row into a nested dict."""
    out = {
        "application_id": row["application_id"],
        "job_id": row["job_id"],
        "candidate_id": row["candidate_id"],
        "stage": row["stage"],
        "rating": row["rating"],
        "applied_at": row["applied_at"],
        "updated_at": row["updated_at"],
        "ai_score": row.get("ai_score"),
        "ai_analyzed_at": row.get("ai_analyzed_at"),
        "candidate": {
            "candidate_id": row["candidate_id"],
            "full_name": row["full_name"],
            "email": row["email"],
            "phone": row["phone"],
            "headline": row["headline"],
            "location": row["location"],
            "linkedin_url": row["linkedin_url"],
            "source": row["cand_source"],
            "notes": row["notes"],
            "cv_file_name": row.get("cv_file_name"),
            "has_cv": bool(row.get("cv_s3_key")),
        },
    }
    if with_analysis:
        out["ai_analysis"] = row.get("ai_analysis")
    return out


APP_JOIN_SELECT = """
    SELECT a.application_id, a.job_id, a.candidate_id, a.stage, a.rating,
           a.applied_at, a.updated_at, a.ai_score, a.ai_analyzed_at,
           c.full_name, c.email, c.phone, c.headline, c.location,
           c.linkedin_url, c.source AS cand_source, c.notes,
           c.cv_file_name, c.cv_s3_key
    FROM hirex_applications a
    JOIN hirex_candidates c ON c.candidate_id = a.candidate_id
"""


# --- Pipeline ----------------------------------------------------------------
@bp.route("/jobs/<int:job_id>/pipeline", methods=["GET"])
def get_pipeline(job_id):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            APP_JOIN_SELECT + " WHERE a.job_id = %s "
            "ORDER BY a.rating DESC NULLS LAST, a.applied_at ASC;",
            (job_id,),
        )
        rows = [_nest(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify({"stages": VALID_STAGES, "applications": rows})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/jobs/<int:job_id>/overview", methods=["GET"])
def job_overview(job_id):
    """Aggregated stats for the job's Overview tab — one connection, real data only."""
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT status, created_at, openings FROM hirex_jobs WHERE job_id = %s;", (job_id,))
        job = cur.fetchone()
        if not job:
            cur.close(); conn.close()
            return jsonify({"error": "job not found"}), 404

        cur.execute(
            """SELECT COUNT(*) AS total,
                      COUNT(*) FILTER (WHERE applied_at::date = CURRENT_DATE) AS today,
                      COUNT(*) FILTER (WHERE applied_at >= NOW() - INTERVAL '7 days') AS week
               FROM hirex_applications WHERE job_id = %s;""",
            (job_id,),
        )
        totals = cur.fetchone()

        cur.execute("SELECT stage, COUNT(*) AS n FROM hirex_applications WHERE job_id = %s GROUP BY stage;", (job_id,))
        by_stage = {r["stage"]: r["n"] for r in cur.fetchall()}

        cur.execute(
            """SELECT COALESCE(NULLIF(TRIM(c.source), ''), 'unknown') AS source, COUNT(*) AS n
               FROM hirex_applications a JOIN hirex_candidates c ON c.candidate_id = a.candidate_id
               WHERE a.job_id = %s GROUP BY 1 ORDER BY n DESC;""",
            (job_id,),
        )
        by_source = [{"source": r["source"], "count": r["n"]} for r in cur.fetchall()]

        cur.execute(
            "SELECT COUNT(ai_score) AS analyzed, ROUND(AVG(ai_score))::int AS avg_score "
            "FROM hirex_applications WHERE job_id = %s;",
            (job_id,),
        )
        ai = cur.fetchone()

        cur.execute(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT reviewer_email) AS reviewers "
            "FROM hirex_scorecards WHERE job_id = %s;",
            (job_id,),
        )
        sc = cur.fetchone()

        cur.execute(
            """SELECT applied_at::date AS d, COUNT(*) AS n
               FROM hirex_applications
               WHERE job_id = %s AND applied_at >= (CURRENT_DATE - INTERVAL '6 days')
               GROUP BY 1 ORDER BY 1;""",
            (job_id,),
        )
        daily = [{"date": str(r["d"]), "count": r["n"]} for r in cur.fetchall()]

        cur.close()
        conn.close()
        return jsonify({
            "job": {"status": job["status"], "created_at": job["created_at"], "openings": job["openings"]},
            "totals": {"total": totals["total"], "today": totals["today"], "week": totals["week"]},
            "by_stage": by_stage,
            "by_source": by_source,
            "ai": {"analyzed": ai["analyzed"], "avg_score": ai["avg_score"]},
            "scorecards": {"count": sc["n"], "reviewers": sc["reviewers"]},
            "daily": daily,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/applications/<int:app_id>", methods=["GET"])
def get_application(app_id):
    """Full application incl. stored AI analysis (used by the candidate drawer)."""
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            APP_JOIN_SELECT.replace("c.cv_s3_key", "c.cv_s3_key, a.ai_analysis")
            + " WHERE a.application_id = %s;",
            (app_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return jsonify({"error": "application not found"}), 404
        return jsonify(_nest(row, with_analysis=True))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/jobs/<int:job_id>/candidates", methods=["POST"])
def add_candidate(job_id):
    data = request.get_json(silent=True) or {}
    name = (data.get("full_name") or "").strip()
    if not name:
        return jsonify({"error": "full_name is required"}), 400

    stage = (data.get("stage") or "applied").strip()
    if stage not in STAGE_SET:
        return jsonify({"error": f"invalid stage '{stage}'"}), 400

    email = (data.get("email") or "").strip() or None
    actor = _actor_email()

    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '5s';")
            cur.execute("SET LOCAL statement_timeout = '10s';")

            # Confirm the job exists.
            cur.execute("SELECT 1 FROM hirex_jobs WHERE job_id = %s;", (job_id,))
            if not cur.fetchone():
                conn.rollback()
                return jsonify({"error": "job not found"}), 404

            # Soft dedup: reuse an existing candidate with the same email.
            candidate_id = None
            if email:
                cur.execute(
                    "SELECT candidate_id FROM hirex_candidates "
                    "WHERE LOWER(email) = LOWER(%s) ORDER BY candidate_id LIMIT 1;",
                    (email,),
                )
                hit = cur.fetchone()
                if hit:
                    candidate_id = hit["candidate_id"]

            if candidate_id is None:
                cur.execute(
                    """INSERT INTO hirex_candidates
                       (full_name, email, phone, headline, location, linkedin_url, source, notes, created_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING candidate_id;""",
                    (name, email, data.get("phone"), data.get("headline"),
                     data.get("location"), data.get("linkedin_url"),
                     data.get("source"), data.get("notes"), actor),
                )
                candidate_id = cur.fetchone()["candidate_id"]

            # Prevent the same person appearing twice in one job's pipeline.
            cur.execute(
                "SELECT 1 FROM hirex_applications WHERE job_id = %s AND candidate_id = %s;",
                (job_id, candidate_id),
            )
            if cur.fetchone():
                conn.rollback()
                return jsonify({"error": "This candidate is already in this pipeline."}), 409

            cur.execute(
                "INSERT INTO hirex_applications (job_id, candidate_id, stage, source) "
                "VALUES (%s,%s,%s,%s) RETURNING application_id;",
                (job_id, candidate_id, stage, data.get("source")),
            )
            app_id = cur.fetchone()["application_id"]
            _log_activity(cur, job_id, actor, "candidate_added",
                          {"candidate": name, "stage": stage})

            cur.execute(APP_JOIN_SELECT + " WHERE a.application_id = %s;", (app_id,))
            row = _nest(cur.fetchone())
            conn.commit()
        return jsonify(row), 201
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


@bp.route("/applications/<int:app_id>", methods=["PATCH"])
def update_application(app_id):
    data = request.get_json(silent=True) or {}
    actor = _actor_email()

    sets, vals = [], []
    if "stage" in data:
        stage = (data.get("stage") or "").strip()
        if stage not in STAGE_SET:
            return jsonify({"error": f"invalid stage '{stage}'"}), 400
        sets.append("stage = %s"); vals.append(stage)
    if "rating" in data:
        r = data.get("rating")
        if r is not None:
            try:
                r = int(r)
                if r < 0 or r > 5:
                    return jsonify({"error": "rating must be 0..5"}), 400
            except (TypeError, ValueError):
                return jsonify({"error": "rating must be an integer"}), 400
        sets.append("rating = %s"); vals.append(r)
    if "source" in data:
        sets.append("source = %s"); vals.append(data.get("source"))

    if not sets:
        return jsonify({"error": "no editable fields provided"}), 400

    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '5s';")
            cur.execute("SET LOCAL statement_timeout = '10s';")
            cur.execute(
                "SELECT a.job_id, a.stage, c.full_name "
                "FROM hirex_applications a JOIN hirex_candidates c "
                "ON c.candidate_id = a.candidate_id WHERE a.application_id = %s FOR UPDATE OF a;",
                (app_id,),
            )
            before = cur.fetchone()
            if not before:
                conn.rollback()
                return jsonify({"error": "application not found"}), 404

            cur.execute(
                f"UPDATE hirex_applications SET {', '.join(sets)}, updated_at = NOW() "
                f"WHERE application_id = %s;",
                tuple(vals) + (app_id,),
            )
            if "stage" in data and data["stage"] != before["stage"]:
                _log_activity(cur, before["job_id"], actor, "candidate_moved",
                              {"candidate": before["full_name"],
                               "from": before["stage"], "to": data["stage"]})

            cur.execute(APP_JOIN_SELECT + " WHERE a.application_id = %s;", (app_id,))
            row = _nest(cur.fetchone())
            conn.commit()
        return jsonify(row)
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


@bp.route("/applications/<int:app_id>", methods=["DELETE"])
def delete_application(app_id):
    actor = _actor_email()
    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '5s';")
            cur.execute("SET LOCAL statement_timeout = '10s';")
            cur.execute(
                "SELECT a.job_id, c.full_name FROM hirex_applications a "
                "JOIN hirex_candidates c ON c.candidate_id = a.candidate_id "
                "WHERE a.application_id = %s;",
                (app_id,),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return jsonify({"error": "application not found"}), 404
            cur.execute("DELETE FROM hirex_applications WHERE application_id = %s;", (app_id,))
            _log_activity(cur, row["job_id"], actor, "candidate_removed",
                          {"candidate": row["full_name"]})
            conn.commit()
        return jsonify({"deleted": True, "application_id": app_id})
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


# --- Candidate directory -----------------------------------------------------
@bp.route("/candidates", methods=["GET"])
def list_candidates():
    """Global candidate directory with per-person aggregates (all jobs)."""
    q = (request.args.get("q") or "").strip().lower()
    where, params = [], []
    if q:
        where.append("(LOWER(c.full_name) LIKE %s OR LOWER(COALESCE(c.email,'')) LIKE %s "
                     "OR LOWER(COALESCE(c.headline,'')) LIKE %s)")
        like = f"%{q}%"
        params += [like, like, like]
    if request.args.get("has_cv") == "1":
        where.append("c.cv_s3_key IS NOT NULL")
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            f"""SELECT c.candidate_id, c.full_name, c.email, c.phone, c.headline, c.location,
                       c.linkedin_url, c.source, c.cv_file_name,
                       (c.cv_s3_key IS NOT NULL) AS has_cv,
                       COUNT(a.application_id) AS applications,
                       MAX(a.applied_at) AS last_applied,
                       COALESCE(
                         json_agg(json_build_object('job_id', j.job_id, 'title', j.title,
                                                    'stage', a.stage, 'ai_score', a.ai_score,
                                                    'applied_at', a.applied_at)
                                  ORDER BY a.applied_at DESC)
                         FILTER (WHERE a.application_id IS NOT NULL), '[]'
                       ) AS jobs
                FROM hirex_candidates c
                LEFT JOIN hirex_applications a ON a.candidate_id = c.candidate_id
                LEFT JOIN hirex_jobs j        ON j.job_id = a.job_id
                {clause}
                GROUP BY c.candidate_id
                ORDER BY c.updated_at DESC, c.candidate_id DESC;""",
            tuple(params),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- Candidate record --------------------------------------------------------
@bp.route("/candidates/<int:candidate_id>", methods=["GET"])
def get_candidate(candidate_id):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT candidate_id, full_name, email, phone, headline, location, "
            "linkedin_url, source, notes, created_at, updated_at "
            "FROM hirex_candidates WHERE candidate_id = %s;",
            (candidate_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return jsonify({"error": "candidate not found"}), 404
        return jsonify(row)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/candidates/<int:candidate_id>", methods=["PATCH"])
def update_candidate(candidate_id):
    data = request.get_json(silent=True) or {}
    if "full_name" in data and not (data.get("full_name") or "").strip():
        return jsonify({"error": "full_name cannot be empty"}), 400

    sets, vals = [], []
    for f in CAND_FIELDS:
        if f in data:
            sets.append(f"{f} = %s")
            vals.append((data.get(f) or None) if f != "full_name" else data.get(f).strip())
    if not sets:
        return jsonify({"error": "no editable fields provided"}), 400

    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '5s';")
            cur.execute("SET LOCAL statement_timeout = '10s';")
            cur.execute(
                f"UPDATE hirex_candidates SET {', '.join(sets)}, updated_at = NOW() "
                f"WHERE candidate_id = %s "
                f"RETURNING candidate_id, full_name, email, phone, headline, location, "
                f"linkedin_url, source, notes, created_at, updated_at;",
                tuple(vals) + (candidate_id,),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return jsonify({"error": "candidate not found"}), 404
            conn.commit()
        return jsonify(row)
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()
