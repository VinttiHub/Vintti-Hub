"""Hirex ATS — bridge to the CRM opportunities.

A Hirex job can be created from scratch or lifted from an opportunity we're
already working in Opportunities. When it's lifted, `hirex_jobs.opportunity_id`
keeps the link so the job and the deal stay connected.

This is the ONLY place Hirex reads the legacy `opportunity` / `account` tables.
Nothing here writes to them.
"""
import logging

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor, Json

from db import get_connection
from routes.hirex_routes import SELECT_COLS
from utils.html_utils import html_to_plain_text, looks_like_html

bp = Blueprint("hirex_opportunities", __name__, url_prefix="/hirex")

# Deals worth staffing. Everything else (Close Win, Closed Lost, Stop) is only
# reachable with ?all=1 — you occasionally reopen an old one.
ACTIVE_STAGES = ["Sourcing", "Interviewing", "Deep Dive", "NDA Sent", "Signed", "Negotiating"]

# opportunity column -> hirex_jobs column, for the straight copies.
DIRECT_MAP = {
    "opp_position_name": "title",
    "career_seniority": "seniority",
    "opp_hr_lead": "recruiter_email",
    "opp_sales_lead": "hiring_manager_email",
}
# Long-text fields that arrive as rich-text HTML and land as plain text.
RICH_TEXT_MAP = {
    "career_requirements": "requirements",
    "career_additional_info": "benefits",
}

# career_modality / career_job_type come from the careers site as free text.
WORK_MODE_MAP = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite",
                 "onsite": "onsite", "on site": "onsite", "presencial": "onsite"}
EMPLOYMENT_MAP = {"full-time": "full_time", "full time": "full_time", "fulltime": "full_time",
                  "part-time": "part_time", "part time": "part_time",
                  "contractor": "contract", "contract": "contract", "freelance": "contract"}
SENIORITY_MAP = {"entry-level": "entry", "entry level": "entry", "junior": "junior",
                 "semi-senior": "semi_senior", "semi senior": "semi_senior",
                 "senior": "senior", "manager": "manager", "lead": "lead"}


def _actor_email():
    data = request.get_json(silent=True) or {}
    return (data.get("actor_email")
            or request.headers.get("X-User-Email")
            or "").strip().lower() or None


def _norm(value, mapping):
    key = str(value or "").strip().lower()
    return mapping.get(key)


def _clean(value):
    text = str(value or "").strip()
    return text or None


def _rich_text(value):
    """CRM long-text fields are rich-text HTML; Hirex stores them as plain text."""
    text = _clean(value)
    if not text or not looks_like_html(text):
        return text
    return html_to_plain_text(text) or None


@bp.route("/opportunities", methods=["GET"])
def list_opportunities():
    """Opportunities available to turn into a job, for the picker."""
    q = (request.args.get("q") or "").strip().lower()
    include_all = request.args.get("all") == "1"

    where, params = [], []
    if not include_all:
        where.append("o.opp_stage = ANY(%s)")
        params.append(ACTIVE_STAGES)
    if q:
        where.append("(LOWER(COALESCE(o.opp_position_name,'')) LIKE %s "
                     "OR LOWER(COALESCE(a.client_name,'')) LIKE %s)")
        params += [f"%{q}%", f"%{q}%"]
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            f"""SELECT o.opportunity_id, o.opp_position_name, o.opp_stage,
                       o.opp_hr_lead, o.opp_sales_lead, o.opp_model,
                       o.min_salary, o.max_salary, o.since_sourcing,
                       a.client_name,
                       hr.user_name AS recruiter_name,
                       sl.user_name AS sales_lead_name,
                       j.job_id AS existing_job_id
                FROM opportunity o
                LEFT JOIN account a ON a.account_id = o.account_id
                LEFT JOIN users hr  ON LOWER(hr.email_vintti) = LOWER(o.opp_hr_lead)
                LEFT JOIN users sl  ON LOWER(sl.email_vintti) = LOWER(o.opp_sales_lead)
                LEFT JOIN LATERAL (
                    SELECT job_id FROM hirex_jobs
                    WHERE opportunity_id = o.opportunity_id
                    ORDER BY job_id LIMIT 1
                ) j ON TRUE
                {clause}
                ORDER BY o.since_sourcing DESC NULLS LAST, o.opportunity_id DESC
                LIMIT 200;""",
            tuple(params),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(rows)
    except Exception as e:
        logging.exception("Hirex opportunity list failed")
        return jsonify({"error": str(e)}), 500


@bp.route("/jobs/from-opportunity", methods=["POST"])
def create_job_from_opportunity():
    """Create a Hirex job pre-filled from an opportunity, linked by opportunity_id."""
    data = request.get_json(silent=True) or {}
    try:
        opportunity_id = int(data.get("opportunity_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "opportunity_id is required"}), 400

    actor = _actor_email()
    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '5s';")
            cur.execute("SET LOCAL statement_timeout = '10s';")
            cur.execute(
                """SELECT o.*, a.client_name
                   FROM opportunity o
                   LEFT JOIN account a ON a.account_id = o.account_id
                   WHERE o.opportunity_id = %s;""",
                (opportunity_id,),
            )
            opp = cur.fetchone()
            if not opp:
                conn.rollback()
                return jsonify({"error": "opportunity not found"}), 404

            # One job per opportunity, unless the caller insists.
            if not data.get("allow_duplicate"):
                cur.execute(
                    "SELECT job_id, title FROM hirex_jobs WHERE opportunity_id = %s "
                    "ORDER BY job_id LIMIT 1;",
                    (opportunity_id,),
                )
                existing = cur.fetchone()
                if existing:
                    conn.rollback()
                    return jsonify({
                        "error": "This opportunity already has a job in Hirex.",
                        "job_id": existing["job_id"], "title": existing["title"],
                    }), 409

            values = {"opportunity_id": opportunity_id, "created_by": actor, "status": "draft"}
            for src, dest in DIRECT_MAP.items():
                values[dest] = _clean(opp.get(src))
            for src, dest in RICH_TEXT_MAP.items():
                values[dest] = _rich_text(opp.get(src))
            if not values.get("title"):
                values["title"] = _clean(opp.get("career_job")) or f"Opportunity {opportunity_id}"

            # The client is the department here — a Hirex job belongs to a client,
            # not to an internal team.
            values["department"] = _clean(opp.get("client_name"))

            # The JD lives in one of two columns depending on where it was written.
            values["description"] = (_rich_text(opp.get("hr_job_description"))
                                     or _rich_text(opp.get("career_description")))

            city, country = _clean(opp.get("career_city")), _clean(opp.get("career_country"))
            values["location"] = " · ".join(p for p in (city, country) if p)

            values["work_mode"] = _norm(opp.get("career_modality"), WORK_MODE_MAP)
            values["employment_type"] = _norm(opp.get("career_job_type"), EMPLOYMENT_MAP)
            values["seniority"] = (_norm(opp.get("career_seniority"), SENIORITY_MAP)
                                   or _clean(opp.get("career_seniority")))

            # The candidate's salary, not the client's budget.
            values["salary_min"] = opp.get("min_salary")
            values["salary_max"] = opp.get("max_salary")
            if values["salary_min"] or values["salary_max"]:
                values["salary_currency"] = "USD"
                values["salary_period"] = "month"

            tools = _clean(opp.get("career_tools"))
            skills = [s.strip() for s in tools.replace(";", ",").split(",")] if tools else []
            values["skills"] = Json([s for s in skills if s])

            values = {k: v for k, v in values.items() if v not in (None, "")}
            cols = list(values)
            cur.execute(
                f"INSERT INTO hirex_jobs ({', '.join(cols)}) "
                f"VALUES ({', '.join(['%s'] * len(cols))}) RETURNING {SELECT_COLS};",
                tuple(values[c] for c in cols),
            )
            row = cur.fetchone()
            cur.execute(
                "INSERT INTO hirex_job_activity (job_id, actor_email, action, detail) "
                "VALUES (%s,%s,%s,%s);",
                (row["job_id"], actor, "created_from_opportunity",
                 Json({"opportunity_id": opportunity_id,
                       "client": opp.get("client_name"),
                       "stage": opp.get("opp_stage")})),
            )
            conn.commit()
        row["public_url"] = None
        return jsonify(row), 201
    except Exception as e:
        if conn:
            conn.rollback()
        logging.exception("Hirex create-from-opportunity failed")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


@bp.route("/jobs/<int:job_id>/opportunity", methods=["GET"])
def job_opportunity(job_id):
    """The deal a job came from, for the link shown on the job detail."""
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT o.opportunity_id, o.opp_position_name, o.opp_stage, o.opp_model,
                      o.min_salary, o.max_salary, o.fee, o.since_sourcing,
                      a.client_name, a.account_id
               FROM hirex_jobs j
               JOIN opportunity o ON o.opportunity_id = j.opportunity_id
               LEFT JOIN account a ON a.account_id = o.account_id
               WHERE j.job_id = %s;""",
            (job_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return jsonify({"linked": False}), 200
        return jsonify({"linked": True, **row})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
