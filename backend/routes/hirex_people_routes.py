"""Hirex ATS — add someone we already know to a job.

Two kinds of "already know":
  * they're already in Hirex (in another job's pipeline, or the directory)
  * they're in the legacy Vintti `candidates` table

Both are searched together, because from the recruiter's side it's one question:
"do we already have this person?"

Legacy candidates are COPIED into hirex_candidates, never joined live. Hirex keeps
its own snapshot so editing a profile in Vintti can't change the CV that an AI
rubric already scored mid-process; `legacy_candidate_id` records where they came
from so the UI can link back.

We also carry over whatever text we have on them (their parsed CV, their LinkedIn
profile, their Vintti resume), so the AI rubric works the moment they're added —
without a new upload and without spending a Coresignal credit.

Depends on backend/sql/20260729_add_hirex_legacy_link.sql being applied to RDS.
"""
import json
import logging

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor, Json

from db import get_connection

bp = Blueprint("hirex_people", __name__, url_prefix="/hirex")

VALID_STAGES = {"applied", "screening", "interview", "offer", "hired", "rejected"}
MIN_TEXT = 200          # below this a "CV text" is a scrap, not something to score

# Legacy english_level is free text ("Very Good", "Awesome"…); Hirex uses a fixed
# ladder. Anything we can't place confidently is left empty rather than guessed.
ENGLISH_LEVELS = [
    (("native", "bilingual", "mother"), "Native"),
    (("excellent", "awesome", "fluent", "c2", "c1"), "Fluent"),
    (("very good", "advanced", "high"), "Advanced"),
    (("good", "intermediate", "medium", "regular", "b1", "b2"), "Intermediate"),
    (("basic", "beginner", "low", "elementary", "a1", "a2"), "Beginner"),
]


def _actor_email():
    data = request.get_json(silent=True) or {}
    return (data.get("actor_email")
            or request.headers.get("X-User-Email")
            or "").strip().lower() or None


def _clean(value, limit=500):
    text = str(value or "").strip()
    return text[:limit] or None


def _split_name(full):
    parts = str(full or "").split()
    if not parts:
        return None, None
    return parts[0], (" ".join(parts[1:]) or None)


def _english_level(raw):
    text = str(raw or "").strip().lower()
    if not text:
        return None
    for needles, label in ENGLISH_LEVELS:
        if any(n in text for n in needles):
            return label
    return None


def _resume_to_text(resume):
    """The Vintti resume (structured JSON) rendered as plain text for the rubric."""
    if not resume:
        return None

    def arr(value):
        if isinstance(value, list):
            return value
        try:
            parsed = json.loads(value or "[]")
            return parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            return []

    lines = []
    about = _clean(resume.get("about"), 4000)
    if about:
        lines += ["SUMMARY", about]

    jobs = arr(resume.get("work_experience"))
    if jobs:
        lines += ["", "EXPERIENCE"]
        for item in jobs[:15]:
            if not isinstance(item, dict):
                continue
            head = " — ".join(p for p in (item.get("position") or item.get("title"),
                                          item.get("company")) if p) or "Role"
            period = " – ".join(p for p in (item.get("start_date"), item.get("end_date")) if p)
            lines.append(f"- {head}" + (f" ({period})" if period else ""))
            desc = _clean(item.get("description"), 1200)
            if desc:
                lines.append("  " + desc.replace("\n", " "))

    studies = arr(resume.get("education"))
    if studies:
        lines += ["", "EDUCATION"]
        for item in studies[:10]:
            if not isinstance(item, dict):
                continue
            head = " — ".join(p for p in (item.get("institution") or item.get("school"),
                                          item.get("degree") or item.get("program")) if p)
            if head:
                lines.append(f"- {head}")

    tools = [t.get("tool") if isinstance(t, dict) else t for t in arr(resume.get("tools"))]
    tools = [t for t in tools if t]
    if tools:
        lines += ["", "SKILLS", ", ".join(str(t) for t in tools[:60])]

    langs = arr(resume.get("languages"))
    entries = []
    for item in langs:
        if isinstance(item, dict) and item.get("language"):
            entries.append(f"{item['language']} ({item['level']})" if item.get("level") else item["language"])
    if entries:
        lines += ["", "LANGUAGES", ", ".join(entries)]

    text = "\n".join(lines).strip()
    return text if len(text) > MIN_TEXT else None


def _best_profile_text(row, resume):
    """Best available text about this person, most faithful source first.

    Returns (text, where_it_came_from) so the UI can be honest about what the
    AI actually read.
    """
    cv = _clean(row.get("cv_pdf_scrapper"), 40000)
    if cv and len(cv) > MIN_TEXT:
        return cv, "their CV"

    linkedin = _clean(row.get("linkedin_scrapper"), 40000)
    if linkedin and len(linkedin) > MIN_TEXT:
        return linkedin, "their LinkedIn profile"

    from_resume = _resume_to_text(resume)
    if from_resume:
        return from_resume, "their Vintti resume"

    raw = row.get("coresignal_scrapper")
    if raw:
        try:
            from routes.hirex_sourcing_routes import profile_to_text
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            text = profile_to_text(parsed)
            if text and len(text) > MIN_TEXT:
                return text, "their LinkedIn data"
        except Exception:
            logging.exception("Hirex import: coresignal payload wasn't usable")

    return None, None


# --- Search ------------------------------------------------------------------
@bp.route("/people", methods=["GET"])
def search_people():
    """People we already have, from Hirex and from Vintti, in one list."""
    q = (request.args.get("q") or "").strip().lower()
    if len(q) < 2:
        return jsonify([])
    job_id = request.args.get("job_id", type=int)
    like = f"%{q}%"

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Already in Hirex. `in_this_job` lets the UI grey them out instead of
        # letting someone click and get an error.
        cur.execute(
            """SELECT c.candidate_id, c.first_name, c.last_name, c.email, c.headline,
                      c.linkedin_url, c.legacy_candidate_id,
                      (c.cv_text IS NOT NULL AND length(c.cv_text) > %s) AS has_text,
                      (SELECT COUNT(*) FROM hirex_applications a
                        WHERE a.candidate_id = c.candidate_id) AS pipelines,
                      EXISTS (SELECT 1 FROM hirex_applications a
                               WHERE a.candidate_id = c.candidate_id AND a.job_id = %s) AS in_this_job
               FROM hirex_candidates c
               WHERE LOWER(CONCAT_WS(' ', c.first_name, c.last_name)) LIKE %s
                  OR LOWER(COALESCE(c.email, '')) LIKE %s
               ORDER BY c.updated_at DESC
               LIMIT 15;""",
            (MIN_TEXT, job_id or 0, like, like),
        )
        hirex_rows = cur.fetchall()

        # Everyone already copied across, so the same person can't show up twice.
        imported_ids = {r["legacy_candidate_id"] for r in hirex_rows if r["legacy_candidate_id"]}
        known_emails = {(r["email"] or "").lower() for r in hirex_rows if r["email"]}

        cur.execute(
            """SELECT c.candidate_id, c.name, c.email, c.linkedin, c.country,
                      c.english_level, c.candidate_source,
                      (length(COALESCE(c.cv_pdf_scrapper, '')) > %s
                       OR length(COALESCE(c.linkedin_scrapper, '')) > %s
                       OR c.coresignal_scrapper IS NOT NULL
                       OR EXISTS (SELECT 1 FROM resume r
                                   WHERE r.candidate_id = c.candidate_id
                                     AND length(COALESCE(r.about, '')) > 100)) AS has_text
               FROM candidates c
               WHERE LOWER(COALESCE(c.name, '')) LIKE %s
                  OR LOWER(COALESCE(c.email, '')) LIKE %s
               -- Relevance before recency: on a common name the 20 newest records
               -- are rarely the one being looked for.
               ORDER BY CASE
                          WHEN LOWER(COALESCE(c.name, ''))  LIKE %s THEN 0   -- name starts with it
                          WHEN LOWER(COALESCE(c.name, ''))  LIKE %s THEN 1   -- name contains it
                          WHEN LOWER(COALESCE(c.email, '')) LIKE %s THEN 2   -- email starts with it
                          ELSE 3
                        END,
                        c.created_at DESC NULLS LAST
               LIMIT 20;""",
            (MIN_TEXT, MIN_TEXT, like, like, f"{q}%", like, f"{q}%"),
        )
        legacy_rows = cur.fetchall()

        # The same person can be recorded under different names in each system
        # (a Vintti test row called "PRUEBA" is the Hirex candidate "Yeison
        # Granda"). Hiding the Vintti row makes the search look broken, so keep
        # one row per person and say what they're called on the other side.
        aka = {}
        if known_emails or imported_ids:
            cur.execute(
                """SELECT candidate_id, name, LOWER(email) AS email
                   FROM candidates
                   WHERE LOWER(email) = ANY(%s) OR candidate_id = ANY(%s);""",
                (list(known_emails) or [""], list(imported_ids) or [0]),
            )
            for row in cur.fetchall():
                if row["email"]:
                    aka[row["email"]] = row["name"]
                aka[row["candidate_id"]] = row["name"]

        cur.close()
        conn.close()
    except Exception as e:
        logging.exception("Hirex people search failed")
        return jsonify({"error": str(e)}), 500

    out = []
    for r in hirex_rows:
        name = " ".join(p for p in (r["first_name"], r["last_name"]) if p)
        vintti_name = aka.get((r["email"] or "").lower()) or aka.get(r["legacy_candidate_id"])
        out.append({
            "source": "hirex",
            "id": r["candidate_id"],
            "full_name": name,
            "email": r["email"],
            "headline": r["headline"],
            "has_text": bool(r["has_text"]),
            "pipelines": r["pipelines"],
            "in_this_job": bool(r["in_this_job"]),
            # Only worth showing when the two systems disagree on the name.
            "also_in_vintti_as": vintti_name if vintti_name and
                                 vintti_name.strip().lower() != name.strip().lower() else None,
            "also_in_vintti": bool(vintti_name),
        })

    for r in legacy_rows:
        email = (r["email"] or "").lower()
        if r["candidate_id"] in imported_ids or (email and email in known_emails):
            continue        # already in Hirex; the entry above is the live one
        out.append({
            "source": "vintti",
            "id": r["candidate_id"],
            "full_name": r["name"] or "—",
            "email": r["email"],
            "headline": r["country"] or None,
            "has_text": bool(r["has_text"]),
            "pipelines": 0,
            "in_this_job": False,
        })

    return jsonify(out[:25])


# --- Add ---------------------------------------------------------------------
@bp.route("/jobs/<int:job_id>/candidates/existing", methods=["POST"])
def add_existing_candidate(job_id):
    """From a job's pipeline: the destination is the job you're standing in."""
    return _add_existing(job_id)


@bp.route("/candidates/existing", methods=["POST"])
def add_existing_from_directory():
    """From the Candidates directory: the job is optional — importing someone
    into the directory without assigning them anywhere is a valid outcome."""
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    if job_id in ("", None):
        job_id = None
    else:
        try:
            job_id = int(job_id)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid job"}), 400
    return _add_existing(job_id)


def _add_existing(job_id):
    data = request.get_json(silent=True) or {}
    source = (data.get("source") or "").strip()
    stage = (data.get("stage") or "applied").strip()
    if source not in ("hirex", "vintti"):
        return jsonify({"error": "invalid source"}), 400
    if stage not in VALID_STAGES:
        return jsonify({"error": f"invalid stage '{stage}'"}), 400
    try:
        person_id = int(data.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "id is required"}), 400

    actor = _actor_email()
    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '5s';")
            cur.execute("SET LOCAL statement_timeout = '20s';")

            if job_id is not None:
                cur.execute("SELECT 1 FROM hirex_jobs WHERE job_id = %s;", (job_id,))
                if not cur.fetchone():
                    conn.rollback()
                    return jsonify({"error": "job not found"}), 404

            text_from = None
            if source == "hirex":
                cur.execute(
                    "SELECT candidate_id, TRIM(CONCAT_WS(' ', first_name, last_name)) AS full_name "
                    "FROM hirex_candidates WHERE candidate_id = %s;",
                    (person_id,),
                )
                person = cur.fetchone()
                if not person:
                    conn.rollback()
                    return jsonify({"error": "candidate not found"}), 404
                candidate_id, full_name = person["candidate_id"], person["full_name"]
            else:
                cur.execute("SELECT * FROM candidates WHERE candidate_id = %s;", (person_id,))
                legacy = cur.fetchone()
                if not legacy:
                    conn.rollback()
                    return jsonify({"error": "candidate not found in Vintti"}), 404
                cur.execute("SELECT * FROM resume WHERE candidate_id = %s;", (person_id,))
                resume = cur.fetchone()

                first, last = _split_name(legacy.get("name"))
                if not first:
                    conn.rollback()
                    return jsonify({"error": "That Vintti record has no name."}), 422
                email = (_clean(legacy.get("email")) or "").lower() or None
                full_name = " ".join(p for p in (first, last) if p)
                profile_text, text_from = _best_profile_text(legacy, resume)

                # Same person may already be in Hirex under that email.
                candidate_id = None
                if email:
                    cur.execute(
                        "SELECT candidate_id FROM hirex_candidates "
                        "WHERE LOWER(email) = LOWER(%s) ORDER BY candidate_id LIMIT 1;",
                        (email,),
                    )
                    hit = cur.fetchone()
                    candidate_id = hit["candidate_id"] if hit else None

                cols = {
                    "first_name": first, "last_name": last, "email": email,
                    "phone": _clean(legacy.get("phone")),
                    "country": _clean(legacy.get("country")),
                    "english_level": _english_level(legacy.get("english_level")),
                    "linkedin_url": _clean(legacy.get("linkedin")),
                    "source": _clean(legacy.get("candidate_source")) or "vintti",
                    "legacy_candidate_id": person_id,
                }
                if profile_text:
                    cols["cv_text"] = profile_text
                    cols["cv_text_source"] = text_from
                cols = {k: v for k, v in cols.items() if v is not None}

                if candidate_id:
                    # Known to Hirex already: fill the gaps, never overwrite what
                    # a recruiter typed here.
                    keep = {"first_name", "last_name", "email", "phone", "country",
                            "english_level", "linkedin_url", "source", "cv_text",
                            "cv_text_source"}
                    sets = [f"{c} = COALESCE(NULLIF({c}, ''), %s)" if c in keep else f"{c} = %s"
                            for c in cols]
                    cur.execute(
                        f"UPDATE hirex_candidates SET {', '.join(sets)}, "
                        f"imported_at = NOW(), updated_at = NOW() WHERE candidate_id = %s;",
                        tuple(cols.values()) + (candidate_id,),
                    )
                else:
                    cols["created_by"] = actor
                    names = list(cols)
                    cur.execute(
                        f"INSERT INTO hirex_candidates ({', '.join(names)}, imported_at) "
                        f"VALUES ({', '.join(['%s'] * len(names))}, NOW()) RETURNING candidate_id;",
                        tuple(cols[c] for c in names),
                    )
                    candidate_id = cur.fetchone()["candidate_id"]

            app_id = None
            if job_id is not None:
                cur.execute(
                    "SELECT application_id FROM hirex_applications WHERE job_id = %s AND candidate_id = %s;",
                    (job_id, candidate_id),
                )
                existing_app = cur.fetchone()
                if existing_app:
                    conn.rollback()
                    return jsonify({"error": f"{full_name} is already in this pipeline.",
                                    "application_id": existing_app["application_id"]}), 409

                cur.execute(
                    "INSERT INTO hirex_applications (job_id, candidate_id, stage, source) "
                    "VALUES (%s, %s, %s, %s) RETURNING application_id;",
                    (job_id, candidate_id, stage, "hirex" if source == "hirex" else "vintti"),
                )
                app_id = cur.fetchone()["application_id"]
                cur.execute(
                    "INSERT INTO hirex_job_activity (job_id, actor_email, action, detail) "
                    "VALUES (%s,%s,%s,%s);",
                    (job_id, actor, "candidate_added",
                     Json({"candidate": full_name, "stage": stage,
                           "from": "Hirex" if source == "hirex" else "Vintti"})),
                )
            elif source == "hirex":
                # Already in Hirex and no job picked — nothing would happen.
                conn.rollback()
                return jsonify({"error": f"{full_name} is already in Hirex. "
                                         f"Pick a job to add them to one.",
                                "candidate_id": candidate_id}), 409

            cur.execute(
                "SELECT (cv_text IS NOT NULL AND length(cv_text) > %s) AS has_text "
                "FROM hirex_candidates WHERE candidate_id = %s;",
                (MIN_TEXT, candidate_id),
            )
            has_text = bool(cur.fetchone()["has_text"])
            conn.commit()

        return jsonify({
            "application_id": app_id,
            "job_id": job_id,
            "candidate_id": candidate_id,
            "full_name": full_name,
            "has_text": has_text,
            "text_from": text_from,
        }), 201
    except Exception as e:
        if conn:
            conn.rollback()
        logging.exception("Hirex add-existing failed")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()
