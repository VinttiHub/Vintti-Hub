"""Hirex ATS — sourcing: add a candidate from a LinkedIn profile URL.

The recruiter finds someone on LinkedIn who never applied. Instead of retyping
the profile, they paste the URL and Hirex builds the candidate from it.

Nothing is scraped from LinkedIn. The URL is only used to derive the public
slug; the profile data comes from Coresignal, which we already license and which
`coresignal_routes` already knows how to query. The same payload is then turned
into CV-like text by the existing extractor, which means a sourced candidate can
be scored with the AI rubric even though no CV was ever uploaded.

Depends on backend/sql/20260728_add_hirex_linkedin_raw.sql being applied to RDS.
"""
import logging
import re

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor, Json

from db import get_connection

bp = Blueprint("hirex_sourcing", __name__, url_prefix="/hirex")

VALID_STAGES = {"applied", "screening", "interview", "offer", "hired", "rejected"}


def _actor_email():
    data = request.get_json(silent=True) or {}
    return (data.get("actor_email")
            or request.headers.get("X-User-Email")
            or "").strip().lower() or None


def _pick(data, *keys):
    """First non-empty value among `keys`. Coresignal's shape varies by endpoint
    and by how complete a profile is, so every field is looked up defensively."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    return None


def _experiences(profile):
    for key in ("experience", "member_experience_collection", "experiences",
                "member_experience", "work_experience"):
        value = profile.get(key)
        if isinstance(value, list) and value:
            return value
    return []


def _active_experience(profile):
    """The role they hold today — the one with no end date, else the first."""
    items = _experiences(profile)
    for item in items:
        if not isinstance(item, dict):
            continue
        ongoing = (item.get("active_experience") in (1, True, "1")
                   or not _pick(item, "date_to", "end_date", "ends_at"))
        if ongoing:
            return item
    return items[0] if items and isinstance(items[0], dict) else {}


def _split_name(profile):
    first = _pick(profile, "first_name", "given_name")
    last = _pick(profile, "last_name", "family_name", "surname")
    if first:
        return first, last
    full = _pick(profile, "full_name", "name", "member_full_name") or ""
    parts = full.split()
    if not parts:
        return None, None
    return parts[0], (" ".join(parts[1:]) or None)


def _split_location(profile):
    """Coresignal gives 'Istanbul, Türkiye' style strings more often than parts."""
    country = _pick(profile, "country", "location_country")
    city = _pick(profile, "city", "location_city")
    raw = _pick(profile, "location", "location_full", "member_location")
    if raw and not (city and country):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if parts:
            city = city or parts[0]
            country = country or (parts[-1] if len(parts) > 1 else None)
    return city, country


def map_profile(profile, linkedin_url):
    """Coresignal payload -> hirex_candidates columns."""
    first, last = _split_name(profile)
    city, country = _split_location(profile)
    active = _active_experience(profile)

    headline = _pick(profile, "title", "headline", "job_title", "member_headline")
    if not headline and active:
        role = _pick(active, "title", "position", "job_title")
        company = _pick(active, "company_name", "company", "organization")
        headline = " at ".join(p for p in (role, company) if p) or None

    return {
        "first_name": first,
        "last_name": last,
        "headline": headline,
        "current_company": _pick(active, "company_name", "company", "organization")
                           or _pick(profile, "company_name", "current_company"),
        "location": city,
        "country": country,
        "email": (_pick(profile, "professional_email", "email", "primary_professional_email") or "").lower() or None,
        "linkedin_url": linkedin_url,
    }


def _alive(items):
    """Coresignal keeps tombstones; anything flagged deleted is history, not fact."""
    return [i for i in items if isinstance(i, dict) and not i.get("deleted")]


def _period(item):
    start = _pick(item, "date_from") or (str(item["date_from_year"]) if item.get("date_from_year") else None)
    end = _pick(item, "date_to") or (str(item["date_to_year"]) if item.get("date_to_year") else None)
    if item.get("is_current") in (1, True, "1") and not end:
        end = "Present"
    if start and end:
        return f"{start} – {end}"
    return start or end


def profile_to_text(profile):
    """Coresignal payload -> CV-like plain text for the AI rubric.

    Built by hand rather than by an LLM on purpose: this runs while the recruiter
    waits, once per sourced candidate. A model call here costs money, adds ~15s,
    and rate-limits — for the sake of reformatting facts we already have in
    structured form. The rubric reads text; it doesn't care who wrote it.
    """
    if not isinstance(profile, dict):
        return None

    first, last = _split_name(profile)
    city, country = _split_location(profile)
    lines = [" ".join(p for p in (first, last) if p)]

    where = ", ".join(p for p in (city, country) if p)
    if where:
        lines.append(where)

    headline = _pick(profile, "headline", "title")
    if headline:
        lines += ["", "HEADLINE", headline]

    summary = _pick(profile, "summary", "about", "description")
    if summary:
        lines += ["", "SUMMARY", summary]

    experience = _alive(_experiences(profile))
    if experience:
        lines += ["", "EXPERIENCE"]
        for item in experience[:15]:
            role = _pick(item, "title", "position")
            company = _pick(item, "company_name", "company")
            head = " — ".join(p for p in (role, company) if p) or "Role"
            period = _period(item)
            lines.append(f"- {head}" + (f" ({period})" if period else ""))
            for extra_key, prefix in (("location", ""), ("company_industry", "Industry: ")):
                extra = _pick(item, extra_key)
                if extra:
                    lines.append(f"  {prefix}{extra}")
            desc = _pick(item, "description")
            if desc:
                lines.append("  " + re.sub(r"\s+", " ", desc)[:1200])

    education = _alive(profile.get("education") or [])
    if education:
        lines += ["", "EDUCATION"]
        for item in education[:10]:
            school = _pick(item, "institution", "school", "title")
            program = _pick(item, "program", "degree", "field_of_study", "subtitle")
            head = " — ".join(p for p in (school, program) if p) or "Studies"
            period = _period(item)
            lines.append(f"- {head}" + (f" ({period})" if period else ""))

    for key, label in (("member_skills", "SKILLS"), ("skills", "SKILLS"),
                       ("inferred_skills", "SKILLS (inferred)")):
        raw = profile.get(key)
        if not isinstance(raw, list) or not raw:
            continue
        names = []
        for item in raw:
            name = item if isinstance(item, str) else (
                _pick(item, "skill", "name", "member_skill") if isinstance(item, dict) else None)
            if name and name not in names:
                names.append(name)
        if names:
            lines += ["", label, ", ".join(names[:60])]
            break

    languages = _alive(profile.get("languages") or [])
    if languages:
        entries = []
        for item in languages:
            name = _pick(item, "language", "name")
            level = _pick(item, "proficiency", "level")
            if name:
                entries.append(f"{name} ({level})" if level else name)
        if entries:
            lines += ["", "LANGUAGES", ", ".join(entries)]

    certifications = _alive(profile.get("certifications") or [])
    if certifications:
        names = [n for n in (_pick(c, "name", "title") for c in certifications) if n]
        if names:
            lines += ["", "CERTIFICATIONS", ", ".join(names[:25])]

    text = "\n".join(lines).strip()
    return text if len(text) > 40 else None


@bp.route("/jobs/<int:job_id>/candidates/from-linkedin", methods=["POST"])
def add_candidate_from_linkedin(job_id):
    data = request.get_json(silent=True) or {}
    linkedin_url = (data.get("linkedin_url") or "").strip()
    stage = (data.get("stage") or "applied").strip()
    if stage not in VALID_STAGES:
        return jsonify({"error": f"invalid stage '{stage}'"}), 400

    # Imported here so a missing CORESIGNAL_API_KEY doesn't break app startup.
    from coresignal_routes import _slug_from_linkedin, _collect_employee, API_KEY

    slug = _slug_from_linkedin(linkedin_url)
    if not slug:
        return jsonify({"error": "That doesn't look like a LinkedIn profile URL. "
                                 "It should look like linkedin.com/in/janedoe"}), 400
    if not API_KEY:
        return jsonify({"error": "Coresignal isn't configured on the server."}), 503

    canonical = f"https://www.linkedin.com/in/{slug}"
    actor = _actor_email()

    # Before spending a Coresignal credit, check we aren't re-adding someone who
    # is already in this job's pipeline.
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT c.candidate_id, a.application_id,
                      TRIM(CONCAT_WS(' ', c.first_name, c.last_name)) AS full_name
               FROM hirex_candidates c
               LEFT JOIN hirex_applications a
                 ON a.candidate_id = c.candidate_id AND a.job_id = %s
               WHERE LOWER(c.linkedin_url) LIKE %s
               ORDER BY c.candidate_id LIMIT 1;""",
            (job_id, f"%/in/{slug.lower()}%"),
        )
        existing = cur.fetchone()
        cur.execute("SELECT 1 FROM hirex_jobs WHERE job_id = %s;", (job_id,))
        job_exists = cur.fetchone()
        cur.close()
        conn.close()
        conn = None
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"error": str(e)}), 500

    if not job_exists:
        return jsonify({"error": "job not found"}), 404
    if existing and existing["application_id"]:
        return jsonify({"error": f"{existing['full_name']} is already in this pipeline.",
                        "application_id": existing["application_id"]}), 409

    profile, meta = _collect_employee(slug)
    if not profile:
        detail = (meta or {}).get("status")
        if detail == 404:
            return jsonify({"error": "Coresignal has no data for that profile."}), 404
        logging.error("Coresignal lookup failed for %s: %s", slug, meta)
        return jsonify({"error": "Couldn't fetch that profile. Try again in a moment."}), 502

    fields = map_profile(profile, canonical)
    if not fields.get("first_name"):
        return jsonify({"error": "That profile came back without a name."}), 422

    # CV-like text so the AI rubric works without an uploaded CV. Best-effort:
    # if it comes out empty we still add the person.
    summary = None
    try:
        summary = profile_to_text(profile)
    except Exception:
        logging.exception("Hirex sourcing: profile-to-text failed")

    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '5s';")
            cur.execute("SET LOCAL statement_timeout = '20s';")

            cols = {k: v for k, v in fields.items() if v}
            cols.update({
                "source": "sourced",
                "linkedin_raw": Json(profile),
                "profile_summary": summary,
                "sourced_at": None,       # set with NOW() below
                "created_by": actor,
            })
            if summary:
                cols["cv_text"] = summary
                cols["cv_text_source"] = "their LinkedIn profile"

            if existing:
                candidate_id = existing["candidate_id"]
                # Known person, new job: refresh the profile, keep what a human
                # typed (COALESCE keeps the existing value when it isn't blank).
                keep = {"first_name", "last_name", "email", "headline",
                        "current_company", "location", "country"}
                # cv_text/cv_text_source are refreshed, not preserved: the newest
                # profile we pulled is the current one.
                sets = [f"{c} = COALESCE(NULLIF({c}, ''), %s)" if c in keep else f"{c} = %s"
                        for c in cols if c != "sourced_at"]
                values = [cols[c] for c in cols if c != "sourced_at"]
                cur.execute(
                    f"UPDATE hirex_candidates SET {', '.join(sets)}, "
                    f"sourced_at = NOW(), updated_at = NOW() WHERE candidate_id = %s;",
                    tuple(values) + (candidate_id,),
                )
            else:
                names = [c for c in cols if c != "sourced_at"]
                cur.execute(
                    f"INSERT INTO hirex_candidates ({', '.join(names)}, sourced_at) "
                    f"VALUES ({', '.join(['%s'] * len(names))}, NOW()) RETURNING candidate_id;",
                    tuple(cols[c] for c in names),
                )
                candidate_id = cur.fetchone()["candidate_id"]

            cur.execute(
                "INSERT INTO hirex_applications (job_id, candidate_id, stage, source) "
                "VALUES (%s, %s, %s, 'sourced') RETURNING application_id;",
                (job_id, candidate_id, stage),
            )
            app_id = cur.fetchone()["application_id"]

            name = " ".join(p for p in (fields["first_name"], fields.get("last_name")) if p)
            cur.execute(
                "INSERT INTO hirex_job_activity (job_id, actor_email, action, detail) "
                "VALUES (%s,%s,%s,%s);",
                (job_id, actor, "candidate_sourced",
                 Json({"candidate": name, "linkedin": canonical,
                       "has_profile_text": bool(summary)})),
            )
            conn.commit()

        return jsonify({
            "application_id": app_id,
            "candidate_id": candidate_id,
            "full_name": name,
            "headline": fields.get("headline"),
            "linkedin_url": canonical,
            "has_profile_text": bool(summary),
            "credits_remaining": (meta or {}).get("credits"),
        }), 201
    except Exception as e:
        if conn:
            conn.rollback()
        logging.exception("Hirex sourcing insert failed")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()
