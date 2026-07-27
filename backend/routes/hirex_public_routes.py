"""Hirex ATS — Slice 5: public application form (careers page).

No authentication: these endpoints are hit by candidates arriving from a LinkedIn
job post. A job is reachable only through its unguessable `public_token`, and only
while `status = 'open'` and `published_at IS NOT NULL`.

Deliberately NOT exposed publicly: salary range, recruiter/hiring-manager emails,
created_by, internal tags, pipeline, activity.

Cost safety: CV text is extracted LOCALLY only (PyPDF2). Public submissions never
trigger an OpenAI call — a stranger (or a bot) must not be able to spend money.
AI scoring stays manual, from the pipeline.

Depends on backend/sql/20260727_add_hirex_apply.sql being applied to RDS.
"""
import io
import logging
import re
import uuid

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor, Json

from db import get_connection
from utils import services

bp = Blueprint("hirex_public", __name__, url_prefix="/public/hirex")

# --- Apply-form contract -----------------------------------------------------
ENGLISH_LEVELS = ["Beginner", "Intermediate", "Advanced", "Fluent", "Native"]
FOUND_VIA = ["LinkedIn", "Referral", "Website", "Social Media", "Other"]

# Where Vintti actually recruits, first — then the rest, so the common case is
# one scroll away instead of thirty.
COUNTRIES = (
    "Argentina|Bolivia|Brazil|Chile|Colombia|Costa Rica|Cuba|Dominican Republic|Ecuador|"
    "El Salvador|Guatemala|Honduras|Mexico|Nicaragua|Panama|Paraguay|Peru|Puerto Rico|"
    "Uruguay|Venezuela|United States|Canada|Spain|Portugal|"
    "Albania|Algeria|Angola|Australia|Austria|Bangladesh|Belgium|Bulgaria|Cameroon|China|"
    "Croatia|Czechia|Denmark|Egypt|Estonia|Ethiopia|Finland|France|Germany|Ghana|Greece|"
    "Hungary|India|Indonesia|Ireland|Israel|Italy|Jamaica|Japan|Kenya|Latvia|Lithuania|"
    "Malaysia|Morocco|Netherlands|New Zealand|Nigeria|Norway|Pakistan|Philippines|Poland|"
    "Romania|Serbia|Singapore|Slovakia|Slovenia|South Africa|South Korea|Sweden|Switzerland|"
    "Thailand|Trinidad and Tobago|Tunisia|Turkey|Ukraine|United Kingdom|Vietnam|Other"
).split("|")

# Standard fields the recruiter can switch required/optional/off in the builder.
# `column` is the hirex_candidates column the answer lands in (None = handled
# specially). Order here is the order they appear on the apply page.
STANDARD_FIELDS = [
    {"key": "first_name",      "label": "First name",       "column": "first_name",     "locked": True,  "input": "text"},
    {"key": "last_name",       "label": "Last name",        "column": "last_name",      "locked": True,  "input": "text"},
    {"key": "email",           "label": "Email address",    "column": "email",          "locked": True,  "input": "email"},
    {"key": "phone",           "label": "Phone number",     "column": "phone",          "input": "tel"},
    {"key": "country",         "label": "Location",         "column": "country",        "input": "select", "options": COUNTRIES},
    {"key": "cv",              "label": "CV / Resume",      "column": None,             "input": "file"},
    {"key": "role_position",   "label": "Role / position",  "column": "headline",       "input": "text"},
    {"key": "area",            "label": "Area",             "column": "area",           "input": "text"},
    {"key": "english_level",   "label": "English level",    "column": "english_level",  "input": "select", "options": ENGLISH_LEVELS},
    {"key": "found_via",       "label": "How did you find out about this position?",
                               "column": "source",          "input": "select", "options": FOUND_VIA},
    {"key": "linkedin",        "label": "LinkedIn profile", "column": "linkedin_url",   "input": "text"},
    {"key": "current_company", "label": "Current company",  "column": "current_company", "input": "text"},
    {"key": "desired_salary",  "label": "Desired salary",   "column": "desired_salary", "input": "text"},
]
FIELD_BY_KEY = {f["key"]: f for f in STANDARD_FIELDS}
LOCKED_KEYS = {f["key"] for f in STANDARD_FIELDS if f.get("locked")}
VALID_MODES = {"required", "optional", "off"}

# Default when a job has never been configured in the builder — matches the
# application form Vintti already uses.
DEFAULT_FORM = {
    "first_name": "required", "last_name": "required", "email": "required",
    "phone": "required", "country": "required", "cv": "required",
    "role_position": "optional", "area": "optional", "english_level": "required",
    "found_via": "optional", "linkedin": "optional",
    "current_company": "off", "desired_salary": "off",
}

QUESTION_TYPES = {"short_answer", "paragraph", "dropdown", "single_select",
                  "multi_select", "yes_no", "number"}
CHOICE_TYPES = {"dropdown", "single_select", "multi_select"}

ALLOWED_CV_EXTS = {"pdf", "doc", "docx"}
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_CV_BYTES = 8 * 1024 * 1024  # 8 MB — stricter than the internal upload
MAX_TEXT_LEN = 2000             # per free-text answer

PUBLIC_JOB_COLS = """
    job_id, title, department, location, work_mode, employment_type,
    seniority, language, description, requirements, benefits, skills,
    custom_form, knockout_questions, published_at
"""


# --- Shared helpers (also imported by the authenticated publish endpoints) ----
def normalize_form(raw):
    """Coerce a stored/incoming custom_form into a complete, valid mode map."""
    out = dict(DEFAULT_FORM)
    if isinstance(raw, dict):
        for key, mode in raw.items():
            if key in FIELD_BY_KEY and mode in VALID_MODES:
                out[key] = mode
    for key in LOCKED_KEYS:
        out[key] = "required"
    return out


def normalize_questions(raw):
    """Keep only well-formed screening questions; assign ids to new ones."""
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = (item.get("label") or "").strip()
        qtype = item.get("type")
        if not label or qtype not in QUESTION_TYPES:
            continue
        q = {
            "id": (item.get("id") or "").strip() or uuid.uuid4().hex[:12],
            "type": qtype,
            "label": label[:300],
            "help": (item.get("help") or "").strip()[:300] or None,
            "required": bool(item.get("required")),
        }
        if qtype in CHOICE_TYPES:
            opts = [str(o).strip()[:200] for o in (item.get("options") or []) if str(o).strip()]
            if not opts:
                continue                      # a choice question with no options is unusable
            q["options"] = opts[:30]
        ko = item.get("knockout")
        if isinstance(ko, dict) and ko.get("op"):
            q["knockout"] = {"op": str(ko["op"]), "value": ko.get("value")}
        out.append(q)
    return out[:25]


def _public_question(q):
    """Strip the knockout rule — the candidate must not see what disqualifies them."""
    return {k: v for k, v in q.items() if k != "knockout"}


# --- Public: read the job ----------------------------------------------------
@bp.route("/jobs/<token>", methods=["GET", "OPTIONS"])
def public_job(token):
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        uuid.UUID(str(token))
    except (ValueError, AttributeError, TypeError):
        return jsonify({"error": "not found"}), 404

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            f"SELECT {PUBLIC_JOB_COLS}, status FROM hirex_jobs "
            f"WHERE public_token = %s AND published_at IS NOT NULL;",
            (str(token),),
        )
        job = cur.fetchone()
        cur.close()
        conn.close()
    except Exception as e:
        logging.exception("Hirex public job fetch failed")
        return jsonify({"error": str(e)}), 500

    if not job:
        return jsonify({"error": "not found"}), 404
    if job["status"] != "open":
        # Published once, since paused/closed. Tell the page so it can say so.
        return jsonify({"closed": True, "title": job["title"]}), 410

    questions = normalize_questions(job.get("knockout_questions"))
    return jsonify({
        "title": job["title"],
        "department": job["department"],
        "location": job["location"],
        "work_mode": job["work_mode"],
        "employment_type": job["employment_type"],
        "seniority": job["seniority"],
        "language": job["language"],
        "description": job["description"],
        "requirements": job["requirements"],
        "benefits": job["benefits"],
        "skills": job["skills"] if isinstance(job["skills"], list) else [],
        "form": normalize_form(job.get("custom_form")),
        "fields": STANDARD_FIELDS,
        "questions": [_public_question(q) for q in questions],
    })


# --- Public: submit an application -------------------------------------------
def _extract_pdf_text_local(pdf_bytes):
    """Local-only PDF text extraction. Never calls OpenAI (public endpoint)."""
    try:
        from PyPDF2 import PdfReader
        with io.BytesIO(pdf_bytes) as bio:
            pages = []
            for page in PdfReader(bio).pages:
                text = (page.extract_text() or "").strip()
                if text:
                    pages.append(re.sub(r"[ \t]+", " ", text))
            return "\n\n".join(pages).strip() or None
    except Exception:
        logging.exception("Hirex public CV local text extraction failed")
        return None


def _fails_knockout(question, answer):
    """True when the answer trips this question's knockout rule."""
    rule = question.get("knockout")
    if not rule:
        return False
    op, expected = rule.get("op"), rule.get("value")
    if answer in (None, "", []):
        return True                                   # no answer can't satisfy a rule
    if op == "equals":
        return _norm(answer) != _norm(expected)
    if op == "not_equals":
        return _norm(answer) == _norm(expected)
    if op == "includes":
        given = {_norm(a) for a in (answer if isinstance(answer, list) else [answer])}
        wanted = {_norm(v) for v in (expected if isinstance(expected, list) else [expected])}
        return not (given & wanted)
    if op in ("min", "max"):
        try:
            n, limit = float(answer), float(expected)
        except (TypeError, ValueError):
            return True
        return n < limit if op == "min" else n > limit
    return False


def _norm(v):
    return str(v if v is not None else "").strip().lower()


def _collect_answers(questions):
    """Read screening answers off the multipart body. Returns (answers, flags, error)."""
    answers, flags = [], []
    for q in questions:
        raw = (request.form.getlist(f"q_{q['id']}")
               if q["type"] == "multi_select"
               else [request.form.get(f"q_{q['id']}", "")])
        values = [v.strip() for v in raw if str(v).strip()]

        if q["type"] == "multi_select":
            answer = values
        else:
            answer = values[0][:MAX_TEXT_LEN] if values else None

        if q["required"] and not answer:
            return None, None, f"Please answer: {q['label']}"

        # Answers to a fixed-choice question must be one of the choices — the page
        # only renders valid ones, so anything else is a hand-crafted POST.
        allowed = set(q.get("options") or []) if q["type"] in CHOICE_TYPES else (
            {"Yes", "No"} if q["type"] == "yes_no" else None)
        if allowed is not None:
            picked = answer if isinstance(answer, list) else ([answer] if answer else [])
            if any(p not in allowed for p in picked):
                return None, None, f"Invalid option for: {q['label']}"
        if q["type"] == "number" and answer is not None:
            try:
                float(answer)
            except ValueError:
                return None, None, f"{q['label']} must be a number"

        answers.append({"id": q["id"], "label": q["label"], "type": q["type"], "answer": answer})
        if _fails_knockout(q, answer):
            flags.append(q["label"])
    return answers, flags, None


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


@bp.route("/jobs/<token>/apply", methods=["POST", "OPTIONS"])
def public_apply(token):
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        uuid.UUID(str(token))
    except (ValueError, AttributeError, TypeError):
        return jsonify({"error": "not found"}), 404

    # Honeypot: a real applicant never sees this input, bots fill everything.
    # Answer 200 so the bot believes it worked and doesn't retry.
    if (request.form.get("website") or "").strip():
        return jsonify({"ok": True}), 201

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT job_id, title, status, custom_form, knockout_questions FROM hirex_jobs "
            "WHERE public_token = %s AND published_at IS NOT NULL;",
            (str(token),),
        )
        job = cur.fetchone()
        cur.close()
        conn.close()
    except Exception as e:
        logging.exception("Hirex public apply job lookup failed")
        return jsonify({"error": str(e)}), 500

    if not job:
        return jsonify({"error": "not found"}), 404
    if job["status"] != "open":
        return jsonify({"error": "This job is no longer accepting applications."}), 410

    form = normalize_form(job.get("custom_form"))
    questions = normalize_questions(job.get("knockout_questions"))

    # --- standard fields ---
    values = {}
    for field in STANDARD_FIELDS:
        key, mode = field["key"], form.get(field["key"], "off")
        if key == "cv" or mode == "off":
            continue
        val = (request.form.get(key) or "").strip()[:500]
        if mode == "required" and not val:
            return jsonify({"error": f"{field['label']} is required."}), 400
        if val and field.get("options") and val not in field["options"]:
            return jsonify({"error": f"Pick one of the listed options for {field['label']}."}), 400
        values[key] = val or None

    # First + last are stored separately; the display name is composed on read.
    first_name = values.get("first_name")
    display_name = " ".join(p for p in (first_name, values.get("last_name")) if p) or None
    email = (values.get("email") or "").lower() or None
    if not first_name or not email:
        return jsonify({"error": "Name and email are required."}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"error": "That email address doesn't look valid."}), 400

    # --- screening answers ---
    answers, flags, err = _collect_answers(questions)
    if err:
        return jsonify({"error": err}), 400

    # --- CV ---
    cv_mode = form.get("cv", "off")
    cv_file = request.files.get("cv")
    cv_bytes = cv_ext = None
    if cv_file and cv_file.filename:
        cv_ext = cv_file.filename.rsplit(".", 1)[-1].lower() if "." in cv_file.filename else ""
        if cv_ext not in ALLOWED_CV_EXTS:
            return jsonify({"error": "Please upload a PDF, DOC or DOCX file."}), 400
        cv_bytes = cv_file.read()
        if len(cv_bytes) > MAX_CV_BYTES:
            return jsonify({"error": "That file is too large (max 8 MB)."}), 400
        if not cv_bytes:
            cv_bytes = None
    if cv_mode == "required" and not cv_bytes:
        return jsonify({"error": "A CV is required."}), 400
    if cv_bytes and (services.s3_client is None or not services.S3_BUCKET):
        return jsonify({"error": "Uploads are temporarily unavailable. Please try again later."}), 503

    # Upload before opening the transaction so a slow S3 call can't hold a DB lock.
    cv_key = cv_text = None
    if cv_bytes:
        cv_key = f"hirex/cvs/{uuid.uuid4().hex}.{cv_ext}"
        try:
            services.s3_client.put_object(
                Bucket=services.S3_BUCKET, Key=cv_key, Body=cv_bytes,
                ContentType=CONTENT_TYPES.get(cv_ext, "application/octet-stream"),
            )
        except Exception:
            logging.exception("Hirex public CV upload to S3 failed")
            return jsonify({"error": "We couldn't store your CV. Please try again."}), 502
        if cv_ext == "pdf":
            cv_text = _extract_pdf_text_local(cv_bytes)

    source = (request.args.get("src") or request.form.get("src") or "careers").strip().lower()[:40]

    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '5s';")
            cur.execute("SET LOCAL statement_timeout = '15s';")

            cur.execute(
                "SELECT candidate_id FROM hirex_candidates WHERE LOWER(email) = LOWER(%s) "
                "ORDER BY candidate_id LIMIT 1;",
                (email,),
            )
            hit = cur.fetchone()

            # Map form keys onto candidate columns.
            cols = {}
            for field in STANDARD_FIELDS:
                col, key = field["column"], field["key"]
                if col and values.get(key):
                    cols[col] = values[key]
            if cv_key:
                cols.update({
                    "cv_s3_key": cv_key, "cv_file_name": cv_file.filename[:255],
                    "cv_content_type": CONTENT_TYPES.get(cv_ext), "cv_size_bytes": len(cv_bytes),
                    "cv_text": cv_text,
                })

            if hit:
                candidate_id = hit["candidate_id"]
                # Returning applicant: fill blanks, never overwrite what we already know,
                # except the CV — the newest one they sent us is the current one.
                sets = [f"{c} = COALESCE(NULLIF({c}, ''), %s)" if c not in
                        ("cv_s3_key", "cv_file_name", "cv_content_type", "cv_size_bytes", "cv_text", "cv_uploaded_at")
                        else f"{c} = %s" for c in cols]
                if cv_key:
                    sets.append("cv_uploaded_at = NOW()")
                if sets:
                    cur.execute(
                        f"UPDATE hirex_candidates SET {', '.join(sets)}, updated_at = NOW() "
                        f"WHERE candidate_id = %s;",
                        tuple(cols.values()) + (candidate_id,),
                    )
            else:
                # "How did you find out about this position?" is the candidate's own
                # answer and outranks the ?src= tag we put on the link.
                cols.setdefault("source", source)
                col_names = list(cols)
                placeholders = ", ".join(["%s"] * len(col_names))
                extra_col, extra_val = (", cv_uploaded_at", ", NOW()") if cv_key else ("", "")
                cur.execute(
                    f"INSERT INTO hirex_candidates ({', '.join(col_names)}{extra_col}) "
                    f"VALUES ({placeholders}{extra_val}) RETURNING candidate_id;",
                    tuple(cols[c] for c in col_names),
                )
                candidate_id = cur.fetchone()["candidate_id"]

            cur.execute(
                "SELECT 1 FROM hirex_applications WHERE job_id = %s AND candidate_id = %s;",
                (job["job_id"], candidate_id),
            )
            if cur.fetchone():
                conn.rollback()
                return jsonify({"error": "You have already applied to this role. "
                                         "We have your application — no need to send it twice."}), 409

            cur.execute(
                "INSERT INTO hirex_applications (job_id, candidate_id, stage, source, answers, knockout_flags) "
                "VALUES (%s, %s, 'applied', %s, %s, %s) RETURNING application_id;",
                (job["job_id"], candidate_id, source, Json(answers), Json(flags)),
            )
            app_id = cur.fetchone()["application_id"]

            cur.execute(
                "INSERT INTO hirex_job_activity (job_id, actor_email, action, detail) VALUES (%s,%s,%s,%s);",
                (job["job_id"], None, "candidate_applied",
                 Json({"candidate": display_name, "source": source,
                       "knockout_flags": flags, "has_cv": bool(cv_key)})),
            )
            conn.commit()
        return jsonify({"ok": True, "application_id": app_id}), 201
    except Exception as e:
        if conn:
            conn.rollback()
        logging.exception("Hirex public apply failed")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()
