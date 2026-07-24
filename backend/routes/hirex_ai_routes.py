"""Hirex ATS — Slice 3: CV upload + AI analysis.

- CV stored in S3 (key on hirex_candidates), text extracted for AI.
- AI analysis compares the candidate CV against a job's JD and is stored on the
  application (ai_score + ai_analysis), so the same person can score differently
  per job.

Reuses existing helpers: ai_routes._extract_pdf_text_with_openai (CV parsing,
local-first then OpenAI fallback) and ai_routes.call_openai_with_retry (LLM).
Depends on 20260724_add_hirex_cv_ai.sql (auto-applied on startup).
"""
import json
import logging
import uuid

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor, Json

from db import get_connection
from utils import services

bp = Blueprint("hirex_ai", __name__, url_prefix="/hirex")

ALLOWED_CV_EXTS = {"pdf", "doc", "docx"}
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_CV_BYTES = 12 * 1024 * 1024  # 12 MB


def _actor_email():
    data = request.get_json(silent=True) or {}
    return (data.get("actor_email")
            or request.headers.get("X-User-Email")
            or "").strip().lower() or None


# --- CV ----------------------------------------------------------------------
@bp.route("/candidates/<int:candidate_id>/cv", methods=["POST"])
def upload_cv(candidate_id):
    if services.s3_client is None or not services.S3_BUCKET:
        return jsonify({"error": "File storage is not configured on the server."}), 503

    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "No file provided"}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_CV_EXTS:
        return jsonify({"error": f"Unsupported file type '.{ext}'. Use PDF, DOC or DOCX."}), 400

    data = file.read()
    if not data:
        return jsonify({"error": "Empty file"}), 400
    if len(data) > MAX_CV_BYTES:
        return jsonify({"error": "File too large (max 12 MB)."}), 400

    key = f"hirex/cvs/{uuid.uuid4().hex}.{ext}"
    ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
    try:
        services.s3_client.put_object(Bucket=services.S3_BUCKET, Key=key, Body=data, ContentType=ctype)
    except Exception as e:
        logging.exception("Hirex CV upload to S3 failed")
        return jsonify({"error": f"Upload failed: {e}"}), 500

    # Extract text so AI analysis can run (PDF only for now; DOC/DOCX stored as-is).
    cv_text = None
    if ext == "pdf":
        try:
            from ai_routes import _extract_pdf_text_with_openai
            cv_text = _extract_pdf_text_with_openai(data) or None
        except Exception:
            logging.exception("Hirex CV text extraction failed")
            cv_text = None

    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '5s';")
            cur.execute(
                """UPDATE hirex_candidates
                   SET cv_s3_key=%s, cv_file_name=%s, cv_content_type=%s,
                       cv_size_bytes=%s, cv_text=%s, cv_uploaded_at=NOW(), updated_at=NOW()
                   WHERE candidate_id=%s
                   RETURNING candidate_id, cv_file_name, cv_uploaded_at;""",
                (key, file.filename, ctype, len(data), cv_text, candidate_id),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return jsonify({"error": "candidate not found"}), 404
            conn.commit()
        return jsonify({
            "candidate_id": row["candidate_id"],
            "cv_file_name": row["cv_file_name"],
            "cv_uploaded_at": row["cv_uploaded_at"],
            "has_text": bool(cv_text),
        }), 201
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


@bp.route("/candidates/<int:candidate_id>/cv", methods=["GET"])
def get_cv(candidate_id):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT cv_s3_key, cv_file_name FROM hirex_candidates WHERE candidate_id=%s;", (candidate_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return jsonify({"error": "candidate not found"}), 404
        if not row["cv_s3_key"]:
            return jsonify({"error": "no CV on file"}), 404
        url = services.s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": services.S3_BUCKET, "Key": row["cv_s3_key"]},
            ExpiresIn=3600,
        )
        return jsonify({"url": url, "cv_file_name": row["cv_file_name"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- AI analysis -------------------------------------------------------------
def _build_jd_text(job):
    parts = [f"Job title: {job.get('title') or ''}"]
    for label, key in [("Seniority", "seniority"), ("Department", "department"),
                       ("Location", "location"), ("Work mode", "work_mode"),
                       ("Employment type", "employment_type"), ("Language", "language")]:
        if job.get(key):
            parts.append(f"{label}: {job[key]}")
    skills = job.get("skills")
    if isinstance(skills, list) and skills:
        parts.append("Required skills: " + ", ".join(str(s) for s in skills))
    if job.get("description"):
        parts.append("Description:\n" + job["description"])
    if job.get("requirements"):
        parts.append("Requirements:\n" + job["requirements"])
    return "\n".join(parts)


# Fixed rubric — the composite score is computed by US from these weights, so the
# final number is reproducible and explainable (not a raw LLM guess).
RUBRIC = [
    ("must_have_skills", "Must-have skills",            30),
    ("experience",       "Experience & seniority",      25),
    ("role_relevance",   "Role relevance",              20),
    ("education",        "Education & requirements",     10),
    ("language",         "Language / English",           8),
    ("soft_skills",      "Soft skills & communication",  7),
]
RUBRIC_WEIGHTS = {k: w for k, _, w in RUBRIC}

ANALYSIS_SCHEMA_HINT = """You MUST return ONLY a JSON object with EXACTLY these keys and shapes:
{
  "summary": string,                       // 2-3 sentences, factual
  "recommendation": "advance" | "hold" | "reject",
  "recommendation_reason": string,
  "criteria": [                            // EXACTLY one object per rubric key
    {
      "key": "must_have_skills" | "experience" | "role_relevance" | "education" | "language" | "soft_skills",
      "score": integer,                    // 0-100 for THIS criterion only
      "not_applicable": boolean,           // true ONLY if the JD gives no signal for it
      "evidence": string,                  // SHORT verbatim quote from the CV, or "Not found in CV"
      "verdict": string                    // one short line
    }
  ],
  "strengths":  [ { "point": string, "evidence": string } ],   // evidence = verbatim CV quote
  "weaknesses": [ { "point": string, "evidence": string } ],
  "gaps": string[],                        // JD requirements not evidenced in the CV
  "matched_skills": string[],
  "missing_skills": string[],
  "red_flags":  [ { "flag": string, "evidence": string } ],    // [] if none
  "seniority": string,
  "english_level": string,
  "years_experience": string,
  "job_hopping": { "detected": boolean, "evidence": string },
  "leadership": string,
  "suggested_questions": string[]          // 4-6 targeted questions
}

HARD RULES:
- EVERY "evidence" field must be a SHORT VERBATIM quote copied from the CV text. If you
  cannot find a real supporting quote, write "Not found in CV" and lower that score.
- Do NOT invent facts, employers, dates, degrees, or skills not present in the CV.
- Be strict and consistent: identical inputs must yield identical scores."""


def _composite_score(criteria):
    """Deterministic weighted score from the LLM's per-criterion scores + fixed weights."""
    total_w, acc = 0, 0
    for c in criteria or []:
        key = c.get("key")
        if key not in RUBRIC_WEIGHTS or c.get("not_applicable"):
            continue
        try:
            s = max(0, min(100, int(round(float(c.get("score"))))))
        except (TypeError, ValueError):
            continue
        w = RUBRIC_WEIGHTS[key]
        total_w += w
        acc += s * w
    return int(round(acc / total_w)) if total_w else None


@bp.route("/applications/<int:app_id>/analyze", methods=["POST"])
def analyze_application(app_id):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT a.application_id, a.job_id, a.candidate_id,
                      c.full_name, c.cv_text,
                      j.title, j.seniority, j.department, j.location, j.work_mode,
                      j.employment_type, j.language, j.skills, j.description, j.requirements
               FROM hirex_applications a
               JOIN hirex_candidates c ON c.candidate_id = a.candidate_id
               JOIN hirex_jobs j       ON j.job_id = a.job_id
               WHERE a.application_id = %s;""",
            (app_id,),
        )
        ctx = cur.fetchone()
        cur.close()
        conn.close()
        conn = None
        if not ctx:
            return jsonify({"error": "application not found"}), 404
        if not (ctx.get("cv_text") or "").strip():
            return jsonify({"error": "No CV text available. Upload a PDF CV first."}), 400
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"error": str(e)}), 500

    jd_text = _build_jd_text(ctx)
    rubric_desc = "\n".join(f"- {k} ({label}), weight {w}" for k, label, w in RUBRIC)
    messages = [
        {"role": "system", "content":
            "You are a rigorous senior technical recruiter scoring a candidate CV against a "
            "specific job description using a fixed rubric. " + ANALYSIS_SCHEMA_HINT},
        {"role": "user", "content":
            f"Rubric criteria (score each 0-100, one 'criteria' entry per key):\n{rubric_desc}\n\n"
            f"=== JOB DESCRIPTION ===\n{jd_text}\n\n"
            f"=== CANDIDATE CV ({ctx['full_name']}) ===\n{ctx['cv_text'][:16000]}"},
    ]

    try:
        from ai_routes import call_openai_with_retry
        resp = call_openai_with_retry(
            "gpt-4o", messages, temperature=0, max_tokens=2200,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or ""
    except Exception as e:
        logging.exception("Hirex AI analyze call failed")
        return jsonify({"error": f"AI analysis failed: {e}"}), 502

    analysis = _parse_json(content)
    if not isinstance(analysis, dict):
        return jsonify({"error": "AI returned an unparseable response. Try again."}), 502

    # Deterministic score = WE compute it from the rubric criteria + fixed weights.
    composite = _composite_score(analysis.get("criteria"))
    analysis["match_score"] = composite            # keep key for backward compat
    analysis["_composite_score"] = composite
    analysis["_rubric"] = [{"key": k, "label": label, "weight": w} for k, label, w in RUBRIC]

    score = composite

    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "UPDATE hirex_applications SET ai_score=%s, ai_analysis=%s, ai_analyzed_at=NOW() "
                "WHERE application_id=%s RETURNING ai_analyzed_at;",
                (score, Json(analysis), app_id),
            )
            row = cur.fetchone()
            cur.execute(
                "INSERT INTO hirex_job_activity (job_id, actor_email, action, detail) VALUES (%s,%s,%s,%s);",
                (ctx["job_id"], _actor_email(), "candidate_analyzed",
                 Json({"candidate": ctx["full_name"], "score": score})),
            )
            conn.commit()
        return jsonify({"ai_score": score, "ai_analysis": analysis,
                        "ai_analyzed_at": row["ai_analyzed_at"] if row else None})
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


def _parse_json(content):
    """Extract a JSON object from an LLM response that may wrap it in fences."""
    if not content:
        return None
    s = content.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if "```" in s[3:] else s[3:]
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        return None
