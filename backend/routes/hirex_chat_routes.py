"""Hirex ATS — Ask: a natural-language chat over the Hirex pool.

An OpenAI tool-calling agent loop. The model gets a question, picks which tools
to call (each one a read-only query over the hirex_* tables), reads the rows and
writes the answer in Markdown. Multi-step by design: "who has retail experience"
takes a filter query first and a CV read second.

Read-only on purpose — every tool issues SELECTs and nothing else. There is no
write path in this module, so a hallucinated or adversarial instruction has
nothing to reach for.

Two things worth knowing before editing:
  * There is no full-text index, pg_trgm or embedding column anywhere in this
    repo, so semantic questions ("retail sector") cannot be answered by SQL.
    That is what `screen_cvs` is for: it reads a *bounded* shortlist of CVs and
    makes one extra model call. It is the only tool whose cost isn't capped by
    SQL, hence SCREEN_MAX.
  * Tool arguments come from the model, so they are untrusted input. Every value
    goes through a %s placeholder and every identifier (sort column, direction)
    is looked up in a whitelist. Never interpolate an argument into SQL.
"""
import json
import logging
import re
from datetime import datetime

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_connection
from routes.hirex_pipeline_routes import APP_JOIN_SELECT, VALID_STAGES, _nest
from routes.hirex_scorecards_routes import _summary as scorecard_summary

bp = Blueprint("hirex_chat", __name__, url_prefix="/hirex")

MODEL = "gpt-4o"
MAX_STEPS = 6              # tool rounds before we stop and answer with what we have
MAX_HISTORY_TURNS = 10     # prior turns replayed to the model
ROW_LIMIT = 60             # hard cap on rows any one tool returns
SCREEN_MAX = 25            # CVs one screen_cvs call may read
SCREEN_CV_CHARS = 3000     # per-CV truncation inside screen_cvs
TOOL_RESULT_CHARS = 14000  # truncation of a serialized tool result

# Two columns the UI never needed but an answer does: how long the application
# has sat still, and the job's title — without it the model has no name for the
# role and reaches for the candidate's headline instead. Injected with the same
# .replace() trick get_application() already uses, so the column list stays in
# one place (hirex_pipeline_routes.APP_JOIN_SELECT).
APP_SELECT = APP_JOIN_SELECT.replace(
    "c.cv_s3_key",
    "c.cv_s3_key, EXTRACT(DAY FROM (NOW() - a.updated_at))::int AS days_in_stage, "
    "(SELECT title FROM hirex_jobs jj WHERE jj.job_id = a.job_id) AS job_title",
)

SORTABLE = {
    "ai_score": "a.ai_score",
    "interview_score": "a.interview_score",
    "rating": "a.rating",
    "applied_at": "a.applied_at",
    "updated_at": "a.updated_at",
}

ACTIVE_STAGES = [s for s in VALID_STAGES if s not in ("hired", "rejected")]


# --- helpers -----------------------------------------------------------------
def _limit(n, default=25):
    """Clamp a model-supplied limit into something the DB and context can take."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return default
    return max(1, min(n, ROW_LIMIT))


def _like(value):
    return f"%{(value or '').strip()}%"


def _app_brief(row):
    """Compact one joined application row for the model.

    _nest() is the shape the UI reads; it is far more verbose than the model
    needs, and every extra key is multiplied by up to 60 rows. So we reuse
    _nest for the (tested) unpacking and project a flat subset out of it.
    """
    n = _nest(row)
    c = n["candidate"]
    return {
        "application_id": n["application_id"],
        "job_id": n["job_id"],
        "job_title": row.get("job_title"),
        "candidate_id": n["candidate_id"],
        "name": c["full_name"],
        "email": c["email"],
        "stage": n["stage"],
        "rating": n["rating"],
        "ai_score": n["ai_score"],
        "interview_score": n["interview_score"],
        "headline": c["headline"],
        "current_company": c["current_company"],
        "country": c["country"] or c["location"],
        "english_level": c["english_level"],
        "source": n["source"] or c["source"],
        "has_cv_text": bool(c["has_cv"] or c["has_text"]),
        "knockout_flags": n["knockout_flags"],
        "scorecard_consensus": n["scorecards"]["consensus"],
        "applied_at": str(n["applied_at"])[:10] if n["applied_at"] else None,
        "days_since_last_move": row.get("days_in_stage"),
    }


# --- tools -------------------------------------------------------------------
def t_search_jobs(cur, a):
    where, params = [], []
    if a.get("q"):
        where.append("(title ILIKE %s OR department ILIKE %s OR description ILIKE %s)")
        params += [_like(a["q"])] * 3
    if a.get("status"):
        where.append("status = %s")
        params.append(str(a["status"]).lower())
    else:
        where.append("status <> 'archived'")
    if a.get("department"):
        where.append("department ILIKE %s")
        params.append(_like(a["department"]))
    if a.get("recruiter"):
        where.append("(recruiter_email ILIKE %s OR hiring_manager_email ILIKE %s)")
        params += [_like(a["recruiter"])] * 2
    if a.get("priority"):
        where.append("priority = %s")
        params.append(str(a["priority"]).lower())

    cur.execute(
        """SELECT j.job_id, j.title, j.department, j.status, j.priority, j.seniority,
                  j.location, j.work_mode, j.employment_type, j.openings,
                  j.recruiter_email, j.hiring_manager_email, j.created_at::date AS created_at,
                  (SELECT COUNT(*) FROM hirex_applications x WHERE x.job_id = j.job_id) AS candidates
           FROM hirex_jobs j
           WHERE """ + " AND ".join(where) + """
           ORDER BY j.created_at DESC LIMIT %s;""",
        params + [_limit(a.get("limit"), 30)],
    )
    return {"jobs": [dict(r) for r in cur.fetchall()]}


def t_get_job(cur, a):
    cur.execute(
        """SELECT job_id, title, department, status, priority, seniority, location,
                  work_mode, employment_type, language, openings, salary_min, salary_max,
                  salary_currency, salary_period, skills, tags, description, requirements,
                  benefits, recruiter_email, hiring_manager_email, created_at::date AS created_at
           FROM hirex_jobs WHERE job_id = %s;""",
        (a.get("job_id"),),
    )
    row = cur.fetchone()
    if not row:
        return {"error": "job not found"}
    job = dict(row)
    cur.execute(
        "SELECT stage, COUNT(*) AS n FROM hirex_applications WHERE job_id = %s GROUP BY stage;",
        (a.get("job_id"),),
    )
    job["pipeline_counts"] = {r["stage"]: r["n"] for r in cur.fetchall()}
    return {"job": job}


def t_list_applications(cur, a):
    where, params = [], []
    if a.get("job_id"):
        where.append("a.job_id = %s")
        params.append(a["job_id"])
    if a.get("candidate_id"):
        where.append("a.candidate_id = %s")
        params.append(a["candidate_id"])

    stage = a.get("stage")
    if stage == "active":
        where.append("a.stage <> ALL(%s)")
        params.append(["hired", "rejected"])
    elif stage in VALID_STAGES:
        where.append("a.stage = %s")
        params.append(stage)

    if a.get("min_ai_score") is not None:
        where.append("a.ai_score >= %s")
        params.append(a["min_ai_score"])
    if a.get("min_rating") is not None:
        where.append("a.rating >= %s")
        params.append(a["min_rating"])
    if a.get("has_cv_text"):
        where.append("(c.cv_text IS NOT NULL AND c.cv_text <> '')")
    if a.get("has_interview"):
        where.append("a.interview_transcript IS NOT NULL")
    if a.get("has_knockout"):
        where.append("jsonb_array_length(COALESCE(a.knockout_flags, '[]'::jsonb)) > 0")
    if a.get("country"):
        where.append("(c.country ILIKE %s OR c.location ILIKE %s)")
        params += [_like(a["country"])] * 2
    if a.get("english_level"):
        where.append("c.english_level ILIKE %s")
        params.append(_like(a["english_level"]))
    if a.get("q"):
        where.append("(c.first_name ILIKE %s OR c.last_name ILIKE %s OR c.email ILIKE %s "
                     "OR c.headline ILIKE %s OR c.current_company ILIKE %s)")
        params += [_like(a["q"])] * 5
    if a.get("stalled_days") is not None:
        where.append("a.updated_at < NOW() - (%s || ' days')::interval")
        params.append(str(int(a["stalled_days"])))

    # Identifiers can never come from the model verbatim.
    col = SORTABLE.get(a.get("sort_by"), "a.ai_score")
    direction = "ASC" if str(a.get("sort_dir", "desc")).lower() == "asc" else "DESC"

    cur.execute(
        APP_SELECT
        + (" WHERE " + " AND ".join(where) if where else "")
        + f" ORDER BY {col} {direction} NULLS LAST, a.applied_at DESC LIMIT %s;",
        params + [_limit(a.get("limit"), 30)],
    )
    rows = [_app_brief(r) for r in cur.fetchall()]
    return {"count": len(rows), "applications": rows}


def t_search_candidates(cur, a):
    where, params = [], []
    if a.get("q"):
        where.append("(c.first_name ILIKE %s OR c.last_name ILIKE %s OR c.email ILIKE %s "
                     "OR c.headline ILIKE %s OR c.current_company ILIKE %s OR c.location ILIKE %s "
                     "OR c.area ILIKE %s OR c.profile_summary ILIKE %s)")
        params += [_like(a["q"])] * 8
    if a.get("country"):
        where.append("(c.country ILIKE %s OR c.location ILIKE %s)")
        params += [_like(a["country"])] * 2
    if a.get("english_level"):
        where.append("c.english_level ILIKE %s")
        params.append(_like(a["english_level"]))
    if a.get("current_company"):
        where.append("c.current_company ILIKE %s")
        params.append(_like(a["current_company"]))
    if a.get("has_cv_text"):
        where.append("(c.cv_text IS NOT NULL AND c.cv_text <> '')")

    cur.execute(
        """SELECT c.candidate_id, c.first_name, c.last_name, c.email, c.headline,
                  c.current_company, c.country, c.location, c.area, c.english_level,
                  c.source, c.linkedin_url,
                  (c.cv_text IS NOT NULL AND c.cv_text <> '') AS has_cv_text,
                  COALESCE(j.jobs, '[]'::json) AS applications
           FROM hirex_candidates c
           LEFT JOIN LATERAL (
               SELECT json_agg(json_build_object(
                        'job_id', a.job_id, 'application_id', a.application_id,
                        'title', jb.title, 'stage', a.stage, 'ai_score', a.ai_score)) AS jobs
               FROM hirex_applications a JOIN hirex_jobs jb ON jb.job_id = a.job_id
               WHERE a.candidate_id = c.candidate_id
           ) j ON TRUE
           """ + (" WHERE " + " AND ".join(where) if where else "") + """
           ORDER BY c.created_at DESC LIMIT %s;""",
        params + [_limit(a.get("limit"), 30)],
    )
    out = []
    for r in cur.fetchall():
        d = dict(r)
        d["name"] = " ".join(p for p in (d.pop("first_name"), d.pop("last_name")) if p)
        out.append(d)
    return {"count": len(out), "candidates": out}


def t_get_candidate(cur, a):
    cur.execute(
        """SELECT candidate_id, first_name, last_name, email, phone, headline, location,
                  country, area, english_level, current_company, desired_salary,
                  linkedin_url, source, notes, profile_summary, cv_text_source,
                  cv_file_name, (cv_text IS NOT NULL AND cv_text <> '') AS has_cv_text,
                  created_at::date AS created_at
           FROM hirex_candidates WHERE candidate_id = %s;""",
        (a.get("candidate_id"),),
    )
    row = cur.fetchone()
    if not row:
        return {"error": "candidate not found"}
    cand = dict(row)
    cand["name"] = " ".join(p for p in (cand.pop("first_name"), cand.pop("last_name")) if p)

    cur.execute(
        """SELECT a.application_id, a.job_id, j.title, a.stage, a.rating, a.ai_score,
                  a.interview_score, a.applied_at::date AS applied_at
           FROM hirex_applications a JOIN hirex_jobs j ON j.job_id = a.job_id
           WHERE a.candidate_id = %s ORDER BY a.applied_at DESC;""",
        (a.get("candidate_id"),),
    )
    cand["applications"] = [dict(r) for r in cur.fetchall()]
    return {"candidate": cand}


def t_get_application_detail(cur, a):
    app_id = a.get("application_id")
    cur.execute(
        APP_SELECT.replace(
            "c.cv_s3_key",
            "c.cv_s3_key, a.ai_analysis, a.answers, a.interview_analysis")
        + " WHERE a.application_id = %s;",
        (app_id,),
    )
    row = cur.fetchone()
    if not row:
        return {"error": "application not found"}

    out = _app_brief(row)
    out["ai_analysis"] = row.get("ai_analysis")
    out["interview_analysis"] = row.get("interview_analysis")
    out["screening_answers"] = row.get("answers") or []

    cur.execute(
        """SELECT scorecard_id, reviewer_email, recommendation, overall_comment, ratings
           FROM hirex_scorecards WHERE application_id = %s ORDER BY created_at;""",
        (app_id,),
    )
    cards = [dict(r) for r in cur.fetchall()]
    out["scorecards"] = cards
    out["scorecard_summary"] = scorecard_summary(cards)
    return out


def t_pipeline_stats(cur, a):
    stalled_days = a.get("stalled_days")
    stalled_days = str(int(stalled_days)) if stalled_days is not None else "7"

    if a.get("job_id"):
        job_id = a["job_id"]
        cur.execute(
            """SELECT COUNT(*) AS total,
                      COUNT(*) FILTER (WHERE applied_at >= NOW() - INTERVAL '7 days') AS last_7_days,
                      COUNT(ai_score) AS ai_analyzed,
                      ROUND(AVG(ai_score))::int AS avg_ai_score
               FROM hirex_applications WHERE job_id = %s;""",
            (job_id,),
        )
        totals = dict(cur.fetchone())
        cur.execute(
            "SELECT stage, COUNT(*) AS n FROM hirex_applications WHERE job_id = %s GROUP BY stage;",
            (job_id,),
        )
        by_stage = {r["stage"]: r["n"] for r in cur.fetchall()}
        cur.execute(
            """SELECT LOWER(COALESCE(NULLIF(TRIM(c.source), ''), 'unknown')) AS source,
                      COUNT(*) AS n
               FROM hirex_applications a JOIN hirex_candidates c ON c.candidate_id = a.candidate_id
               WHERE a.job_id = %s GROUP BY 1 ORDER BY n DESC;""",
            (job_id,),
        )
        by_source = {r["source"]: r["n"] for r in cur.fetchall()}
        cur.execute(
            """SELECT COUNT(*) AS n FROM hirex_applications
               WHERE job_id = %s AND stage <> ALL(%s)
                 AND updated_at < NOW() - (%s || ' days')::interval;""",
            (job_id, ["hired", "rejected"], stalled_days),
        )
        stalled = cur.fetchone()["n"]
        return {"job_id": job_id, "totals": totals, "by_stage": by_stage,
                "by_source": by_source,
                "stalled": {"days": int(stalled_days), "count": stalled}}

    # No job_id: a cross-job rollup, which is what "where is the pipeline stuck"
    # actually needs.
    where, params = ["j.status <> 'archived'"], []
    if a.get("status"):
        where = ["j.status = %s"]
        params.append(str(a["status"]).lower())

    cur.execute(
        """SELECT j.job_id, j.title, j.status, j.department,
                  COUNT(a.application_id) AS total,
                  COUNT(a.application_id) FILTER (WHERE a.stage <> ALL(%s)) AS active,
                  COUNT(a.application_id) FILTER (WHERE a.stage = 'hired') AS hired,
                  ROUND(AVG(a.ai_score))::int AS avg_ai_score,
                  MAX(EXTRACT(DAY FROM (NOW() - a.updated_at))::int)
                      FILTER (WHERE a.stage <> ALL(%s)) AS max_days_since_move,
                  COUNT(a.application_id) FILTER (
                      WHERE a.stage <> ALL(%s)
                        AND a.updated_at < NOW() - (%s || ' days')::interval) AS stalled
           FROM hirex_jobs j
           LEFT JOIN hirex_applications a ON a.job_id = j.job_id
           WHERE """ + " AND ".join(where) + """
           GROUP BY j.job_id, j.title, j.status, j.department
           ORDER BY stalled DESC, total DESC LIMIT %s;""",
        [["hired", "rejected"], ["hired", "rejected"], ["hired", "rejected"], stalled_days]
        + params + [_limit(a.get("limit"), 30)],
    )
    return {"stalled_threshold_days": int(stalled_days),
            "jobs": [dict(r) for r in cur.fetchall()]}


def t_list_activity(cur, a):
    """The audit trail: who did what, to whom, when.

    `detail` is free-form JSONB per action; the keys that matter are flattened
    out (candidate / from / to) so the model doesn't have to guess the shape.
    """
    where, params = [], []
    if a.get("job_id"):
        where.append("v.job_id = %s")
        params.append(a["job_id"])
    if a.get("action"):
        where.append("v.action = %s")
        params.append(str(a["action"]).strip().lower())
    if a.get("actor"):
        where.append("v.actor_email ILIKE %s")
        params.append(_like(a["actor"]))
    if a.get("candidate"):
        where.append("v.detail->>'candidate' ILIKE %s")
        params.append(_like(a["candidate"]))
    if a.get("since_days") is not None:
        where.append("v.created_at >= NOW() - (%s || ' days')::interval")
        params.append(str(int(a["since_days"])))

    cur.execute(
        """SELECT v.id, v.job_id, j.title AS job_title, v.actor_email, v.action,
                  v.detail, v.created_at
           FROM hirex_job_activity v
           LEFT JOIN hirex_jobs j ON j.job_id = v.job_id
           """ + (" WHERE " + " AND ".join(where) if where else "") + """
           ORDER BY v.created_at DESC, v.id DESC LIMIT %s;""",
        params + [_limit(a.get("limit"), 30)],
    )
    events = []
    for r in cur.fetchall():
        d = r["detail"] or {}
        events.append({
            "job_id": r["job_id"],
            "job_title": r["job_title"],
            # NULL actor means the public apply page — nobody on the team did it.
            "actor": r["actor_email"] or "public application",
            "action": r["action"],
            "candidate": d.get("candidate"),
            "from_stage": d.get("from"),
            "to_stage": d.get("to"),
            "detail": d,
            "at": r["created_at"],
        })
    return {"count": len(events), "events": events}


# date_trunc/to_char arguments are values, not identifiers, but they still come
# from the model — so they are chosen from this map, never passed through.
GRAINS = {
    "month": ("month", "YYYY-MM"),
    "week": ("week", 'IYYY-"W"IW'),
    "day": ("day", "YYYY-MM-DD"),
}


def t_application_trends(cur, a):
    """Volume over time: applications in, hires and rejections out.

    Intake comes from applied_at. Outcomes come from the activity log rather
    than the current stage, because `stage` only tells you where someone is
    now — it cannot say when they got there, and updated_at moves on any edit.
    """
    grain, fmt = GRAINS.get(str(a.get("granularity", "month")).lower(), GRAINS["month"])
    try:
        months = max(1, min(int(a.get("months_back", 12)), 60))
    except (TypeError, ValueError):
        months = 12
    span = f"{months} months"

    where, params = ["applied_at >= NOW() - %s::interval"], [span]
    if a.get("job_id"):
        where.append("job_id = %s")
        params.append(a["job_id"])
    cur.execute(
        f"""SELECT to_char(date_trunc(%s, applied_at), %s) AS bucket, COUNT(*) AS applications
            FROM hirex_applications
            WHERE {' AND '.join(where)}
            GROUP BY 1 ORDER BY 1;""",
        [grain, fmt] + params,
    )
    buckets = {r["bucket"]: {"period": r["bucket"], "applications": r["applications"],
                             "hired": 0, "rejected": 0} for r in cur.fetchall()}

    where2, params2 = ["action = 'candidate_moved'", "created_at >= NOW() - %s::interval"], [span]
    if a.get("job_id"):
        where2.append("job_id = %s")
        params2.append(a["job_id"])
    cur.execute(
        # DISTINCT candidate, not COUNT(*): a stage move that gets reverted and
        # redone logs two events for one person, and "2 rejections in July" then
        # reads as two people when it was one. Verified against real rows.
        f"""SELECT to_char(date_trunc(%s, created_at), %s) AS bucket,
                   COUNT(DISTINCT detail->>'candidate')
                       FILTER (WHERE detail->>'to' = 'hired')    AS hired,
                   COUNT(DISTINCT detail->>'candidate')
                       FILTER (WHERE detail->>'to' = 'rejected') AS rejected
            FROM hirex_job_activity
            WHERE {' AND '.join(where2)}
            GROUP BY 1 ORDER BY 1;""",
        [grain, fmt] + params2,
    )
    for r in cur.fetchall():
        b = buckets.setdefault(r["bucket"], {"period": r["bucket"], "applications": 0,
                                             "hired": 0, "rejected": 0})
        b["hired"], b["rejected"] = r["hired"], r["rejected"]

    series = [buckets[k] for k in sorted(buckets)]
    return {
        "granularity": grain,
        "window": span,
        "job_id": a.get("job_id"),
        "series": series,
        "totals": {
            "applications": sum(b["applications"] for b in series),
            "hired": sum(b["hired"] for b in series),
            "rejected": sum(b["rejected"] for b in series),
        },
        "note": ("Periods with no activity are omitted. Hires and rejections count distinct "
                 "people (a reverted-then-redone move is one person, not two) and are read "
                 "from stage-change events, so they only exist from the day the job started "
                 "being tracked in Hirex."),
    }


def t_screen_cvs(cur, a):
    """Read a bounded set of CVs and judge each against a free-text criterion.

    The escape hatch for everything SQL can't express. One extra model call for
    the whole shortlist, never one per candidate.
    """
    ids = a.get("candidate_ids") or []
    criterion = (a.get("criterion") or "").strip()
    if not criterion:
        return {"error": "criterion is required"}
    try:
        ids = [int(i) for i in ids][:SCREEN_MAX]
    except (TypeError, ValueError):
        return {"error": "candidate_ids must be integers"}
    if not ids:
        return {"error": "candidate_ids is empty — narrow the pool with "
                         "list_applications or search_candidates first"}

    cur.execute(
        """SELECT candidate_id, TRIM(CONCAT_WS(' ', first_name, last_name)) AS name,
                  cv_text, cv_text_source
           FROM hirex_candidates
           WHERE candidate_id = ANY(%s) AND cv_text IS NOT NULL AND cv_text <> '';""",
        (ids,),
    )
    rows = cur.fetchall()
    if not rows:
        return {"criterion": criterion, "results": [],
                "note": "None of those candidates have CV or profile text on file."}

    blocks = []
    for r in rows:
        blocks.append(
            f"### candidate_id {r['candidate_id']} — {r['name']}\n"
            f"{(r['cv_text'] or '')[:SCREEN_CV_CHARS]}"
        )
    prompt = (
        "You are screening resumes. For EACH candidate below, decide whether they "
        f"meet this criterion:\n\n{criterion}\n\n"
        "Rules:\n"
        "- Judge only on what the text actually says. Never infer or invent.\n"
        "- `evidence` MUST be a short verbatim quote copied from that candidate's "
        "text. If you cannot quote it, matches is false and evidence is null.\n"
        "- Return every candidate_id you were given.\n\n"
        'Return JSON: {"results":[{"candidate_id":int,"matches":bool,'
        '"evidence":string|null,"reason":string}]}\n\n'
        "=== CANDIDATES ===\n" + "\n\n".join(blocks)
    )

    from ai_routes import call_openai_with_retry  # after init_services()
    resp = call_openai_with_retry(
        MODEL, [{"role": "user", "content": prompt}],
        temperature=0, max_tokens=1600, response_format={"type": "json_object"},
    )
    try:
        parsed = json.loads(resp.choices[0].message.content or "{}")
    except (ValueError, TypeError):
        return {"error": "screening returned unreadable output"}

    names = {r["candidate_id"]: r["name"] for r in rows}
    sources = {r["candidate_id"]: r["cv_text_source"] for r in rows}
    results = []
    for item in (parsed.get("results") or []):
        cid = item.get("candidate_id")
        if cid not in names:
            continue  # the model made up an id
        results.append({
            "candidate_id": cid,
            "name": names[cid],
            "matches": bool(item.get("matches")),
            "evidence": item.get("evidence"),
            "reason": item.get("reason"),
            "text_source": sources.get(cid),
        })
    skipped = [i for i in ids if i not in names]
    return {"criterion": criterion, "screened": len(results), "results": results,
            "skipped_no_text": skipped}


TOOL_IMPL = {
    "search_jobs": t_search_jobs,
    "get_job": t_get_job,
    "list_applications": t_list_applications,
    "search_candidates": t_search_candidates,
    "get_candidate": t_get_candidate,
    "get_application_detail": t_get_application_detail,
    "pipeline_stats": t_pipeline_stats,
    "list_activity": t_list_activity,
    "application_trends": t_application_trends,
    "screen_cvs": t_screen_cvs,
}

# Short human labels for the "thinking" line in the UI.
TOOL_LABELS = {
    "search_jobs": "Buscando vacantes",
    "get_job": "Leyendo la vacante",
    "list_applications": "Revisando el pipeline",
    "search_candidates": "Buscando candidatos",
    "get_candidate": "Abriendo el perfil",
    "get_application_detail": "Leyendo la evaluación",
    "pipeline_stats": "Calculando métricas",
    "list_activity": "Revisando el historial",
    "application_trends": "Midiendo la evolución",
    "screen_cvs": "Leyendo CVs",
}

TOOLS = [
    {"type": "function", "function": {
        "name": "search_jobs",
        "description": "Find jobs (openings/vacancies). Use to resolve a job title mentioned by the user into a job_id.",
        "parameters": {"type": "object", "properties": {
            "q": {"type": "string", "description": "Free text matched against title, department and description."},
            "status": {"type": "string", "enum": ["draft", "open", "on_hold", "closed", "archived"]},
            "department": {"type": "string"},
            "recruiter": {"type": "string", "description": "Recruiter or hiring-manager email fragment."},
            "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
            "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "get_job",
        "description": "Full detail of one job: description, requirements, skills, salary and pipeline counts.",
        "parameters": {"type": "object", "properties": {"job_id": {"type": "integer"}},
                       "required": ["job_id"]}}},
    {"type": "function", "function": {
        "name": "list_applications",
        "description": ("The main tool. Candidates who applied to / were sourced for a job, with stage, "
                        "AI score, interview score and scorecard consensus. Filter, then sort."),
        "parameters": {"type": "object", "properties": {
            "job_id": {"type": "integer"},
            "candidate_id": {"type": "integer"},
            "stage": {"type": "string", "description": "One of applied, screening, interview, offer, hired, rejected, or 'active' for everyone not hired/rejected."},
            "min_ai_score": {"type": "integer"},
            "min_rating": {"type": "integer"},
            "has_cv_text": {"type": "boolean", "description": "Only people whose CV/profile text is on file (required before screen_cvs)."},
            "has_interview": {"type": "boolean"},
            "has_knockout": {"type": "boolean", "description": "Only applicants flagged by a knockout question."},
            "country": {"type": "string"},
            "english_level": {"type": "string"},
            "q": {"type": "string", "description": "Name, email, headline or current company."},
            "stalled_days": {"type": "integer", "description": "Only applications untouched for more than N days."},
            "sort_by": {"type": "string", "enum": ["ai_score", "interview_score", "rating", "applied_at", "updated_at"]},
            "sort_dir": {"type": "string", "enum": ["asc", "desc"]},
            "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "search_candidates",
        "description": ("Search the whole candidate pool across jobs, by structured fields and exact text. "
                        "Cannot answer conceptual questions like 'retail sector' — use screen_cvs for those."),
        "parameters": {"type": "object", "properties": {
            "q": {"type": "string"},
            "country": {"type": "string"},
            "english_level": {"type": "string"},
            "current_company": {"type": "string"},
            "has_cv_text": {"type": "boolean"},
            "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "get_candidate",
        "description": "One candidate's profile plus every job they applied to.",
        "parameters": {"type": "object", "properties": {"candidate_id": {"type": "integer"}},
                       "required": ["candidate_id"]}}},
    {"type": "function", "function": {
        "name": "get_application_detail",
        "description": ("Everything recorded about one application: the AI rubric with its cited evidence, "
                        "the interview analysis, screening answers and all scorecards. Use this to compare candidates."),
        "parameters": {"type": "object", "properties": {"application_id": {"type": "integer"}},
                       "required": ["application_id"]}}},
    {"type": "function", "function": {
        "name": "pipeline_stats",
        "description": ("Aggregates. With job_id: that job's funnel, sources and AI average. Without it: a "
                        "per-job rollup including how many applications are stalled — use for 'where is the pipeline stuck'."),
        "parameters": {"type": "object", "properties": {
            "job_id": {"type": "integer"},
            "status": {"type": "string"},
            "stalled_days": {"type": "integer", "description": "Days without movement to count as stalled. Default 7."},
            "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "list_activity",
        "description": ("The audit trail of who did what and when: stage moves (with from/to and the "
                        "person who made them), candidates added or sourced, jobs published, scorecards "
                        "submitted, AI analyses run. Use for 'who moved X', 'what changed this week'."),
        "parameters": {"type": "object", "properties": {
            "job_id": {"type": "integer"},
            "action": {"type": "string", "description": (
                "Exact event type: candidate_moved, candidate_added, candidate_applied, "
                "candidate_sourced, candidate_removed, candidate_analyzed, interview_analyzed, "
                "scorecard_submitted, created, created_from_opportunity, updated, status_changed, "
                "published, unpublished, duplicated.")},
            "actor": {"type": "string", "description": "Email fragment of the person who did it."},
            "candidate": {"type": "string", "description": "Candidate name the event is about."},
            "since_days": {"type": "integer"},
            "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "application_trends",
        "description": ("Volume over time: applications received per period, plus hires and rejections "
                        "from stage-change events. Use for 'how many applied per month', 'is intake "
                        "growing', 'hires this quarter'."),
        "parameters": {"type": "object", "properties": {
            "job_id": {"type": "integer", "description": "Omit for all jobs combined."},
            "granularity": {"type": "string", "enum": ["month", "week", "day"]},
            "months_back": {"type": "integer", "description": "How far back to look. Default 12."}}}}},
    {"type": "function", "function": {
        "name": "screen_cvs",
        "description": (
            "Read the actual CV/profile text of specific candidates and judge each against a free-text "
            "criterion, returning a verbatim quote as evidence. This is the ONLY way to answer conceptual "
            f"questions (industry, seniority, leadership, domain). Max {SCREEN_MAX} candidates per call, so "
            "narrow the pool with list_applications or search_candidates first."),
        "parameters": {"type": "object", "properties": {
            "candidate_ids": {"type": "array", "items": {"type": "integer"},
                              "description": f"Up to {SCREEN_MAX} candidate ids."},
            "criterion": {"type": "string",
                          "description": "What to look for, e.g. 'has worked in the retail industry'."}},
            "required": ["candidate_ids", "criterion"]}}},
]


SYSTEM_PROMPT = """You are Hirex AI, the assistant inside Vintti's Hirex applicant tracking system.
You answer questions about the recruiting pool by calling the tools available to you.

Today is {today}.

## The data
- A **job** is an opening. A **candidate** is a person. An **application** links a candidate to a job at a stage.
- Stages, in order: applied → screening → interview → offer → hired. Plus rejected. A candidate can have several applications across different jobs.
- `ai_score` (0-100) scores the CV against that job's description using a fixed weighted rubric with quoted evidence.
- `interview_score` (0-100) is a separate score from the interview transcript. They are not interchangeable.
- `scorecard_consensus` (strong_no / no / yes / strong_yes) is the *human* verdict from interviewers. It outranks the AI scores when they disagree — say so if they do.
- CV text may come from an uploaded CV or from a sourced LinkedIn profile; `text_source` tells you which. A missing score means nobody ran the analysis, not a bad candidate.
- `knockout_flags` mean the applicant failed a screening question. They are flags only, never automatic rejections.
- The activity log is the only record of *who* did something and *when*. A stage tells you where a candidate is now; only `list_activity` says who put them there. Never guess an actor, and never use `applied_at` as the date of a stage move.
- Hires and rejections over time come from stage-change events, so they start the day the job began being tracked in Hirex — not from the company's history.

## How to work
- Resolve names to ids first: a job title with `search_jobs`, a person with `search_candidates`.
- For conceptual questions — industry, domain, leadership, "has startup experience" — structured filters are not enough. Narrow the pool first (`list_applications` with `has_cv_text: true`, or `search_candidates`), then call `screen_cvs` on those ids. Never claim someone has a background without having read it.
- If a filter returns nothing, try one sensible broader search before concluding. Then say plainly that there are no matches and suggest how to widen it.
- You may call several tools before answering. Prefer few, well-targeted calls.

## Answering
- Reply in the SAME LANGUAGE the user wrote in.
- Use a Markdown table when listing people. Good columns: Candidate, Job, Stage, AI score, and whatever the question was about.
- Always link so the user can click through:
  - a candidate: [Full Name](hirex-job-detail.html?id=JOB_ID&app=APPLICATION_ID)
  - a job: [Job Title](hirex-job-detail.html?id=JOB_ID)
  Use real ids. If you do not have an application_id — activity events, for instance, carry only a name — link the job, or write the person's name as plain text. NEVER put a placeholder like `undefined` or `0` in a link.
- Quote the CV evidence when the answer rests on what a CV says.
- End with a short takeaway or a useful follow-up question, not a summary of what you did.

## Hard rules
- Only ever state what a tool returned. Never invent a candidate, a score, an email or a quote. If you don't have it, say you don't have it.
- You have read-only access. If asked to move, reject, email, edit or delete anything, explain that Ask can only read, and tell them where in Hirex to do it themselves.
- You only cover the Hirex recruiting data. Politely decline unrelated questions.
"""


# --- the agent loop ----------------------------------------------------------
def _clean_links(text):
    """Strip placeholder ids the model sometimes emits in links.

    Activity events carry a candidate's name but no application_id, and the
    model occasionally writes `&app=undefined` anyway. Telling it not to in the
    prompt helps but is not reliable, so the fix is deterministic: drop the
    broken parameter and the link still opens the right job.
    """
    if not text:
        return text
    return re.sub(r"&app=(?!\d+(?:\D|$))[^)\s&]*", "", text)


def _clean_history(raw):
    """Keep only well-formed user/assistant turns from the client."""
    out = []
    if not isinstance(raw, list):
        return out
    for m in raw[-(MAX_HISTORY_TURNS * 2):]:
        if not isinstance(m, dict):
            continue
        role, content = m.get("role"), m.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content[:6000]})
    return out


@bp.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    messages = [{"role": "system",
                 "content": SYSTEM_PROMPT.format(today=datetime.now().strftime("%Y-%m-%d"))}]
    messages += _clean_history(data.get("history"))
    if data.get("job_id"):
        message += f"\n\n(The user is currently looking at job_id {int(data['job_id'])}.)"
    messages.append({"role": "user", "content": message})

    from ai_routes import call_openai_with_retry  # deferred: init_services() must run first

    steps = []
    conn = None
    try:
        conn = get_connection()
        # Read-only at the connection level, so even a bug in a tool cannot write.
        # This must run before any statement opens a transaction — issuing
        # "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY" from a cursor
        # instead does NOT work: psycopg2 has already begun a read-write
        # transaction by then and the UPDATE goes through (verified).
        conn.set_session(readonly=True)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET statement_timeout = '20s';")

            for _ in range(MAX_STEPS):
                resp = call_openai_with_retry(
                    MODEL, messages, temperature=0.2, max_tokens=2500,
                    tools=TOOLS, tool_choice="auto",
                )
                msg = resp.choices[0].message

                if not msg.tool_calls:
                    return jsonify({"reply": _clean_links(msg.content or ""), "steps": steps})

                messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [{"id": tc.id, "type": "function",
                                    "function": {"name": tc.function.name,
                                                 "arguments": tc.function.arguments}}
                                   for tc in msg.tool_calls],
                })

                for tc in msg.tool_calls:
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except ValueError:
                        args = {}
                    steps.append({"tool": name, "label": TOOL_LABELS.get(name, name)})

                    fn = TOOL_IMPL.get(name)
                    if fn is None:
                        result = {"error": f"unknown tool {name}"}
                    else:
                        try:
                            result = fn(cur, args)
                        except Exception as e:
                            # Hand the failure back to the model so it can adapt,
                            # instead of 500-ing the whole conversation.
                            logging.exception("Hirex Ask tool %s failed", name)
                            conn.rollback()
                            result = {"error": f"{name} failed: {e}"}

                    payload = json.dumps(result, default=str)[:TOOL_RESULT_CHARS]
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "name": name, "content": payload})

            # Ran out of steps: ask for a final answer with what we already have.
            messages.append({"role": "user", "content":
                             "Stop searching and answer now with what you already found."})
            final = call_openai_with_retry(MODEL, messages, temperature=0.2, max_tokens=2000)
            return jsonify({"reply": _clean_links(final.choices[0].message.content or ""), "steps": steps})

    except RuntimeError as e:
        # Raised by call_openai_with_retry when the OpenAI budget is spent.
        return jsonify({"error": str(e), "steps": steps}), 503
    except Exception as e:
        logging.exception("Hirex Ask failed")
        return jsonify({"error": str(e), "steps": steps}), 500
    finally:
        if conn is not None:
            conn.close()
