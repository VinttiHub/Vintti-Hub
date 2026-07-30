"""Hirex ATS — Slice 3: CV upload + AI analysis.

- CV stored in S3 (key on hirex_candidates), text extracted for AI.
- AI analysis compares the candidate CV against a job's JD and is stored on the
  application (ai_score + ai_analysis), so the same person can score differently
  per job.

Reuses existing helpers: ai_routes._extract_pdf_text_with_openai (CV parsing,
local-first then OpenAI fallback) and ai_routes.call_openai_with_retry (LLM).
Depends on backend/sql/20260724_add_hirex_cv_ai.sql being applied to RDS.
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
                       cv_size_bytes=%s, cv_text=%s, cv_text_source='the uploaded CV',
                       cv_uploaded_at=NOW(), updated_at=NOW()
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


def _weighted_score(criteria, weights):
    """Deterministic weighted score from the LLM's per-criterion scores.

    WE do the arithmetic, not the model, so the same inputs always produce the
    same number and it can be explained. Criteria the interview or CV never
    touched are dropped from both sides of the average rather than counted as 0.
    """
    total_w, acc = 0, 0
    for c in criteria or []:
        key = c.get("key")
        if key not in weights or c.get("not_applicable"):
            continue
        try:
            s = max(0, min(100, int(round(float(c.get("score"))))))
        except (TypeError, ValueError):
            continue
        w = weights[key]
        total_w += w
        acc += s * w
    return int(round(acc / total_w)) if total_w else None


def _composite_score(criteria):
    """The CV rubric's score. Kept as its own name — it's referenced elsewhere."""
    return _weighted_score(criteria, RUBRIC_WEIGHTS)


@bp.route("/applications/<int:app_id>/analyze", methods=["POST"])
def analyze_application(app_id):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT a.application_id, a.job_id, a.candidate_id,
                      NULLIF(TRIM(CONCAT_WS(' ', c.first_name, c.last_name)), '') AS full_name,
                      c.cv_text,
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


# =============================================================================
# Interview — transcript + its own score
#
# Scored apart from the CV deliberately. A CV states what someone claims; the
# interview shows whether they can explain it. Two numbers make the gap between
# paper and person visible, which is the part worth looking at.
# =============================================================================
MAX_TRANSCRIPT = 60000     # ~15k tokens; a long interview still fits


@bp.route("/applications/<int:app_id>/interview", methods=["POST"])
def set_interview(app_id):
    """Attach an interview: a Grain link we fetch, or a transcript pasted by hand."""
    data = request.get_json(silent=True) or {}
    link = (data.get("link") or "").strip()
    pasted = (data.get("transcript") or "").strip()
    if not link and not pasted:
        return jsonify({"error": "Paste a Grain link or the transcript itself."}), 400

    transcript, source = pasted, "pasted"
    if link:
        try:
            from ai_routes import _fetch_grain_transcript_from_link
            transcript, source = _fetch_grain_transcript_from_link(link), "grain"
        except ValueError:
            return jsonify({"error": "That doesn't look like a Grain recording link."}), 400
        except RuntimeError as e:
            # Missing token, Grain rejected us, or the recording has no transcript.
            logging.exception("Hirex interview: Grain fetch failed")
            return jsonify({"error": str(e)}), 502
        except Exception:
            logging.exception("Hirex interview: Grain fetch failed")
            return jsonify({"error": "Couldn't reach Grain. Try again in a moment."}), 502

    transcript = (transcript or "").strip()[:MAX_TRANSCRIPT]
    if len(transcript) < 100:
        return jsonify({"error": "That transcript is too short to be worth scoring."}), 400

    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '5s';")
            cur.execute(
                """UPDATE hirex_applications
                   SET interview_link = %s, interview_transcript = %s,
                       interview_source = %s, interview_fetched_at = NOW(),
                       -- a new recording invalidates the old score
                       interview_score = NULL, interview_analysis = NULL,
                       interview_analyzed_at = NULL, updated_at = NOW()
                   WHERE application_id = %s RETURNING job_id;""",
                (link or None, transcript, source, app_id),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return jsonify({"error": "application not found"}), 404
            conn.commit()
        return jsonify({"ok": True, "source": source, "chars": len(transcript)}), 201
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


@bp.route("/applications/<int:app_id>/interview", methods=["DELETE"])
def clear_interview(app_id):
    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """UPDATE hirex_applications
                   SET interview_link = NULL, interview_transcript = NULL,
                       interview_source = NULL, interview_fetched_at = NULL,
                       interview_score = NULL, interview_analysis = NULL,
                       interview_analyzed_at = NULL, updated_at = NOW()
                   WHERE application_id = %s RETURNING application_id;""",
                (app_id,),
            )
            if not cur.fetchone():
                conn.rollback()
                return jsonify({"error": "application not found"}), 404
            conn.commit()
        return jsonify({"deleted": True})
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


# What an interview can show that a CV cannot. Same deterministic-composite
# approach as the CV rubric: the model scores each criterion, WE do the maths.
#
# Note on "english": we only ever see a transcript, never the audio, and Grain's
# ASR already normalises punctuation and smooths over a lot of speech. So this
# criterion is scoped to what written words can actually evidence — grammar,
# vocabulary, sentence construction — and the prompt below forbids the model from
# pretending to hear an accent. Renaming it here only affects new analyses; old
# ones render from the "_rubric" snapshot stored alongside their scores.
INTERVIEW_RUBRIC = [
    ("skill_depth",   "Depth on the must-have skills",   30),
    ("communication", "Communication & structure",       20),
    ("english",       "English (grammar & vocabulary)",  20),
    ("motivation",    "Motivation & role fit",           15),
    ("consistency",   "Consistency with their CV",       15),
]
INTERVIEW_WEIGHTS = {k: w for k, _, w in INTERVIEW_RUBRIC}

INTERVIEW_SCHEMA_HINT = """You MUST return ONLY a JSON object with EXACTLY these keys:
{
  "summary": string,                        // 2-3 sentences on how they came across
  "recommendation": "advance" | "hold" | "reject",
  "recommendation_reason": string,
  "criteria": [                             // EXACTLY one per rubric key
    {
      "key": "skill_depth" | "communication" | "english" | "motivation" | "consistency",
      "score": integer,                     // 0-100 for THIS criterion only
      "not_applicable": boolean,            // true ONLY if the interview never touched it
      "evidence": string,                   // SHORT verbatim quote from the TRANSCRIPT
      "verdict": string
    }
  ],
  "strengths":  [ { "point": string, "evidence": string } ],
  "concerns":   [ { "point": string, "evidence": string } ],
  "cv_contradictions": [ { "claim": string, "said": string } ],  // [] if none
  "english_level": string,                  // CEFR-style band from their WRITTEN words only
  "unanswered": string[],                   // JD requirements the interview never probed
  "follow_up_questions": string[]           // 3-5 for the next round
}

ANCHOR EVERYTHING TO THE JOB DESCRIPTION:
- You are judging fit for THE JOB DESCRIPTION ABOVE, not for the candidate's own career.
  If the interview is mostly about a different field than the JD, that is a FIT FAILURE,
  not a neutral fact. Say so in the summary, and name the JD's actual role in it.
- Competence in an unrelated domain earns NO partial credit. A brilliant answer about a
  subject the JD never asks for is worth zero on the criteria that measure fit.
- Communication and English are TABLE STAKES, not fit. Never let a strong showing there
  stand in for the ability to do this job.

HOW TO SCORE EACH CRITERION (use the whole 0-100 range; do NOT default to 70-85):
- "skill_depth" — ONLY the must-have skills and technologies named in the JD.
    0-15   : never demonstrated a single must-have skill.
    16-40  : touched one peripherally, or only adjacent/transferable experience.
    41-65  : solid on some must-haves, clear gaps on others.
    66-85  : solid on most, with concrete specifics.
    86-100 : deep and specific, including trade-offs and failure cases.
- "motivation" — motivation for THIS role, as described in the JD.
    Enthusiasm for a DIFFERENT career path scores 0-15. It is not partial credit; it is
    evidence they want another job. Only wanting THIS kind of work scores above 50.
- "communication" — clarity and structure of their reasoning. Generic; not job fit.
- "consistency" — do their spoken claims match their CV? Generic; not job fit.
  A candidate can be perfectly consistent AND completely wrong for the role.
- "summary" and "recommendation_reason" must state plainly whether they can do THIS job.

WHO YOU ARE JUDGING:
- The transcript has several speakers. You are judging ONE person: THE CANDIDATE,
  named at the top of the transcript block. Everyone else is an interviewer.
- Every "evidence" and "said" quote MUST come from a line SPOKEN BY THE CANDIDATE.
  An interviewer's question is NEVER evidence about the candidate. If the only thing
  you can quote for a criterion is an interviewer's line, that criterion has no
  evidence: set "not_applicable": true and do not invent a score from it.

THE "english" CRITERION — READ THIS CAREFULLY:
- You are reading a TEXT TRANSCRIPT produced by speech recognition. You did NOT hear
  the audio. You therefore CANNOT judge accent, pronunciation, fluency, hesitation,
  pace or confidence, and you must NOT claim to. Never write anything about how they
  "sound".
- Score ONLY what the written words can prove: grammatical accuracy, verb tenses,
  range and precision of vocabulary, sentence complexity, idiomatic usage, and whether
  they can carry a nuanced idea in English rather than short flat answers.
- The evidence quote for this criterion must be a candidate line that actually
  DEMONSTRATES their command of the language — a long or complex sentence, a precise
  word choice, or a clear grammatical error. A quote whose interest is its CONTENT
  (a degree, a job title, a company name) is NOT evidence about English and must not
  be used. Do not reuse the same quote you used for another criterion.
- Speech recognition silently corrects many spoken errors, so absence of errors is
  weak evidence. Anchor high scores on demonstrated RANGE, not on a clean surface.
  If the candidate only ever gave short simple answers, say so and score in the
  50-70 band instead of assuming fluency.
- "english_level" must state the band AND that it was inferred from the transcript
  alone, e.g. "B2+ based on transcript wording only — audio not assessed".

HARD RULES:
- Every "evidence" and "said" must be a SHORT VERBATIM quote from the transcript.
  If you can't find a real quote, write "Not covered in the interview" and lower that score.
- Judge only what the transcript shows. Do NOT infer skills that were never discussed.
- A transcript is speech: ignore filler, false starts and transcription noise when
  judging communication. Judge the thinking, not the typos.
- Be strict and consistent: identical inputs must yield identical scores."""


# The rubric is compensatory: 70 of its 100 weight points sit on criteria that any
# articulate professional scores 70-90 on regardless of the role. Left alone, that gives
# a candidate with ZERO relevant skill a floor of ~51. So technical fit is not just a
# summand — it is the CEILING. A great interview can lift you 20 points above your fit
# with the must-haves, never more, and below FIT_REJECT_BELOW there is no fit to discuss.
FIT_GATE_KEY     = "skill_depth"
FIT_GATE_MARGIN  = 20
FIT_REJECT_BELOW = 30


def _fit_gate(criteria):
    """The must-have-skills score, or None if the interview genuinely never probed it."""
    for c in criteria or []:
        if c.get("key") == FIT_GATE_KEY and not c.get("not_applicable"):
            try:
                return max(0, min(100, int(round(float(c.get("score"))))))
            except (TypeError, ValueError):
                return None
    return None


@bp.route("/applications/<int:app_id>/analyze-interview", methods=["POST"])
def analyze_interview(app_id):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT a.application_id, a.job_id, a.interview_transcript, a.ai_score,
                      TRIM(CONCAT_WS(' ', c.first_name, c.last_name)) AS full_name,
                      c.cv_text,
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
        if not (ctx.get("interview_transcript") or "").strip():
            return jsonify({"error": "Add the interview first."}), 400
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"error": str(e)}), 500

    jd_text = _build_jd_text(ctx)
    rubric_desc = "\n".join(f"- {k} ({label}), weight {w}" for k, label, w in INTERVIEW_RUBRIC)
    # The CV goes in only so contradictions can be spotted — it is NOT scored here.
    cv_note = (f"\n\n=== THEIR CV (context only, for the consistency criterion) ===\n"
               f"{ctx['cv_text'][:6000]}" if (ctx.get("cv_text") or "").strip() else "")

    messages = [
        {"role": "system", "content":
            "You are a rigorous senior technical recruiter judging an interview "
            "transcript against a specific job description, using a fixed rubric. "
            "You are reading text only — you have no access to the audio or video. "
            + INTERVIEW_SCHEMA_HINT},
        {"role": "user", "content":
            f"Rubric criteria (score each 0-100, one 'criteria' entry per key):\n{rubric_desc}\n\n"
            f"=== JOB DESCRIPTION ===\n{jd_text}{cv_note}\n\n"
            f"=== THE CANDIDATE BEING JUDGED ===\n{ctx['full_name']}\n"
            f"Every other speaker below is an interviewer. Quote only lines spoken "
            f"by {ctx['full_name']}. If the speaker labels are missing or ambiguous, "
            f"work out who the candidate is from context (the one ANSWERING, not asking).\n\n"
            f"=== INTERVIEW TRANSCRIPT ===\n"
            f"{ctx['interview_transcript'][:MAX_TRANSCRIPT]}"},
    ]

    try:
        from ai_routes import call_openai_with_retry
        resp = call_openai_with_retry(
            "gpt-4o", messages, temperature=0, max_tokens=2400,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or ""
    except Exception as e:
        logging.exception("Hirex interview analysis failed")
        return jsonify({"error": f"AI analysis failed: {e}"}), 502

    analysis = _parse_json(content)
    if not isinstance(analysis, dict):
        return jsonify({"error": "AI returned an unparseable response. Try again."}), 502

    score = _weighted_score(analysis.get("criteria"), INTERVIEW_WEIGHTS)

    # Technical fit caps the total — see FIT_GATE_* above.
    fit = _fit_gate(analysis.get("criteria"))
    if fit is not None:
        if score is not None and score > fit + FIT_GATE_MARGIN:
            analysis["_uncapped_score"] = score
            analysis["_fit_cap"] = fit + FIT_GATE_MARGIN
            score = fit + FIT_GATE_MARGIN
        if fit < FIT_REJECT_BELOW:
            analysis["_forced_reject"] = True
            analysis["recommendation"] = "reject"
            analysis["recommendation_reason"] = (
                f"No demonstrated fit with the must-have skills (scored {fit}/100). "
                + (analysis.get("recommendation_reason") or "")
            ).strip()

    analysis["_composite_score"] = score
    analysis["_rubric"] = [{"key": k, "label": label, "weight": w}
                           for k, label, w in INTERVIEW_RUBRIC]
    # The gap between paper and person is the point of scoring these apart.
    if score is not None and ctx.get("ai_score") is not None:
        analysis["_vs_cv"] = score - ctx["ai_score"]

    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "UPDATE hirex_applications SET interview_score=%s, interview_analysis=%s, "
                "interview_analyzed_at=NOW() WHERE application_id=%s "
                "RETURNING interview_analyzed_at;",
                (score, Json(analysis), app_id),
            )
            row = cur.fetchone()
            cur.execute(
                "INSERT INTO hirex_job_activity (job_id, actor_email, action, detail) VALUES (%s,%s,%s,%s);",
                (ctx["job_id"], _actor_email(), "interview_analyzed",
                 Json({"candidate": ctx["full_name"], "score": score,
                       "vs_cv": analysis.get("_vs_cv")})),
            )
            conn.commit()
        return jsonify({"interview_score": score, "interview_analysis": analysis,
                        "interview_analyzed_at": row["interview_analyzed_at"] if row else None})
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()
