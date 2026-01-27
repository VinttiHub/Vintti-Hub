import json
import logging
import os
import re
import openai
from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from ai_routes import call_openai_with_retry
from db import get_connection

openai.api_key = os.getenv("OPENAI_API_KEY")

bp = Blueprint("hunter", __name__)

INDUSTRY_OPTIONS = [
    "Finance & Accounting",
    "Sales & Business Development",
    "Customer Support",
    "Marketing",
    "Legal",
    "Human Resources",
    "Virtual & Executive Assistant",
    "Design & Project Management",
    "IT, Engineering & Software Development",
]

_COMPANY_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _normalize_company(value: str) -> str:
    if not value:
        return ""
    clean = value.strip().lower()
    clean = _COMPANY_NORMALIZE_RE.sub("", clean)
    return clean


def _parse_json_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        return [item.strip() for item in raw.split(",") if item.strip()]
    return []


def _normalize_candidate_ids(value):
    ids = []
    for item in _parse_json_list(value):
        try:
            ids.append(int(item))
        except Exception:
            continue
    return ids


def _extract_companies(work_experience):
    if not work_experience:
        return []
    try:
        parsed = json.loads(work_experience) if isinstance(work_experience, str) else work_experience
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    companies = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        company = (item.get("company") or "").strip()
        if not company:
            continue
        norm = _normalize_company(company)
        if norm and norm not in companies:
            companies[norm] = company
    return list(companies.values())


def _strip_code_fences(text: str) -> str:
    if not text:
        return ""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*", "", stripped).strip()
        stripped = stripped.rstrip("`").strip()
    return stripped


def _classify_company(company):
    if not getattr(openai, "api_key", None):
        return None

    options = "\n".join([f"- {opt}" for opt in INDUSTRY_OPTIONS])
    messages = [
        {
            "role": "system",
            "content": (
                "You classify companies into one of the provided industries. "
                "Return JSON only, with keys: industry, company_linkedin. "
                "company_linkedin should be the official LinkedIn company URL if known, "
                "otherwise null."
            ),
        },
        {
            "role": "user",
            "content": (
                "Pick the closest industry from this list and provide the LinkedIn company URL "
                "if you know it from general knowledge. If unsure about LinkedIn, return null.\n\n"
                f"Industries:\n{options}\n\n"
                f"Company: {company}"
            ),
        },
    ]
    try:
        response = call_openai_with_retry(
            model="gpt-4o",
            messages=messages,
            temperature=0.2,
            max_tokens=200,
        )
        content = _strip_code_fences(response.choices[0].message.content or "")
        payload = json.loads(content)
    except Exception:
        logging.exception("OpenAI classification failed for company=%r", company)
        return None

    industry = payload.get("industry")
    if industry not in INDUSTRY_OPTIONS:
        industry = None

    linkedin = payload.get("company_linkedin")
    if isinstance(linkedin, str):
        linkedin = linkedin.strip()
        if linkedin:
            if not re.match(r"^https?://", linkedin, flags=re.I):
                linkedin = f"https://{linkedin.lstrip('/')}"
            if "linkedin.com" not in linkedin.lower():
                linkedin = None
        else:
            linkedin = None
    else:
        linkedin = None

    if not industry and not linkedin:
        return None

    return {"industry": industry, "company_linkedin": linkedin}


def _serialize_hunter_rows(rows):
    serialized = []
    for row in rows:
        candidates = _normalize_candidate_ids(row.get("candidates"))
        accounts = _parse_json_list(row.get("accounts"))
        serialized.append(
            {
                "hunter_id": row.get("hunter_id"),
                "company": row.get("company"),
                "industry": row.get("industry"),
                "amount_candidates": row.get("amount_candidates") or len(candidates),
                "candidates": candidates,
                "accounts": accounts,
                "company_linkedin": row.get("company_linkedin"),
            }
        )
    return serialized


@bp.route("/hunter", methods=["GET", "OPTIONS"])
def get_hunter():
    if request.method == "OPTIONS":
        return ("", 204)
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """
            SELECT hunter_id, company, industry, amount_candidates, candidates,
                   accounts, company_linkedin
            FROM hunter
            ORDER BY hunter_id ASC
            """
        )
        rows = cur.fetchall()
        return jsonify({"rows": _serialize_hunter_rows(rows)})
    except Exception:
        logging.exception("Failed to fetch hunter rows")
        return jsonify({"error": "Failed to fetch hunter rows"}), 500
    finally:
        cur.close()
        conn.close()


@bp.route("/hunter/refresh", methods=["POST", "OPTIONS"])
def refresh_hunter():
    if request.method == "OPTIONS":
        return ("", 204)

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    inserted = 0
    updated = 0
    classified = 0

    try:
        cur.execute("SELECT COALESCE(MAX(hunter_id), 0) AS max_id FROM hunter")
        next_id = (cur.fetchone() or {}).get("max_id", 0) + 1

        cur.execute(
            """
            SELECT hunter_id, company, industry, amount_candidates, candidates,
                   accounts, company_linkedin
            FROM hunter
            """
        )
        existing_rows = cur.fetchall()
        by_company = {}
        for row in existing_rows:
            norm = _normalize_company(row.get("company"))
            if norm:
                row["candidates"] = _normalize_candidate_ids(row.get("candidates"))
                by_company[norm] = row

        cur.execute(
            """
            SELECT candidate_id, work_experience
            FROM resume
            WHERE work_experience IS NOT NULL
            """
        )
        resume_rows = cur.fetchall()

        for resume in resume_rows:
            candidate_id = resume.get("candidate_id")
            if candidate_id is None:
                continue
            companies = _extract_companies(resume.get("work_experience"))
            for company in companies:
                norm = _normalize_company(company)
                if not norm:
                    continue
                if norm in by_company:
                    row = by_company[norm]
                    if candidate_id in row["candidates"]:
                        continue
                    row["candidates"].append(candidate_id)
                    current_count = row.get("amount_candidates")
                    try:
                        current_count = int(current_count)
                    except Exception:
                        current_count = len(row["candidates"]) - 1
                    row["amount_candidates"] = current_count + 1
                    cur.execute(
                        """
                        UPDATE hunter
                        SET amount_candidates = %s,
                            candidates = %s
                        WHERE hunter_id = %s
                        """,
                        (row["amount_candidates"], json.dumps(row["candidates"]), row["hunter_id"]),
                    )
                    updated += 1
                else:
                    candidates_list = [candidate_id]
                    cur.execute(
                        """
                        INSERT INTO hunter (
                            company, industry, amount_candidates,
                            candidates, accounts, hunter_id, company_linkedin
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            company.strip(),
                            None,
                            1,
                            json.dumps(candidates_list),
                            None,
                            next_id,
                            None,
                        ),
                    )
                    by_company[norm] = {
                        "hunter_id": next_id,
                        "company": company.strip(),
                        "industry": None,
                        "amount_candidates": 1,
                        "candidates": candidates_list,
                        "accounts": None,
                        "company_linkedin": None,
                    }
                    next_id += 1
                    inserted += 1

        conn.commit()

        for row in by_company.values():
            if row.get("industry") and row.get("company_linkedin"):
                continue
            try:
                result = _classify_company(row.get("company") or "")
            except Exception:
                logging.exception("Hunter classification failed for company=%r", row.get("company"))
                result = None
            if not result:
                continue
            industry = row.get("industry") or result.get("industry")
            company_linkedin = row.get("company_linkedin") or result.get("company_linkedin")
            cur.execute(
                """
                UPDATE hunter
                SET industry = %s,
                    company_linkedin = %s
                WHERE hunter_id = %s
                """,
                (industry, company_linkedin, row.get("hunter_id")),
            )
            if cur.rowcount:
                classified += 1

        conn.commit()

        cur.execute(
            """
            SELECT hunter_id, company, industry, amount_candidates, candidates,
                   accounts, company_linkedin
            FROM hunter
            ORDER BY hunter_id ASC
            """
        )
        rows = cur.fetchall()
        return jsonify(
            {
                "inserted": inserted,
                "updated": updated,
                "classified": classified,
                "rows": _serialize_hunter_rows(rows),
            }
        )
    except Exception:
        logging.exception("Hunter refresh failed")
        conn.rollback()
        return jsonify({"error": "Hunter refresh failed"}), 500
    finally:
        cur.close()
        conn.close()
