import json
import logging
import os
import re
import time
import threading
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


def _normalize_account_ids(value):
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


def _classify_companies_async(rows):
    if not rows:
        return
    logging.info("Hunter classification job start rows=%s", len(rows))
    conn = get_connection()
    cur = conn.cursor()
    try:
        classified = 0
        for row in rows:
            company = row.get("company") or ""
            try:
                logging.info(
                    "Hunter classify company=%r industry=%r linkedin=%r",
                    company,
                    row.get("industry"),
                    row.get("company_linkedin"),
                )
                result = _classify_company(company)
            except Exception:
                logging.exception("Hunter classification failed for company=%r", company)
                result = None
            if not result:
                logging.info("Hunter classify skip company=%r", company)
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
        logging.info("Hunter classification job done classified=%s", classified)
    except Exception:
        logging.exception("Hunter classification job failed")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


def _fetch_candidate_names(cur, rows):
    candidate_ids = set()
    for row in rows:
        candidate_ids.update(_normalize_candidate_ids(row.get("candidates")))
    if not candidate_ids:
        return {}
    cur.execute(
        """
        SELECT candidate_id, name
        FROM candidates
        WHERE candidate_id = ANY(%s)
        """,
        (list(candidate_ids),),
    )
    return {row.get("candidate_id"): row.get("name") for row in cur.fetchall()}


def _fetch_candidate_positions(cur, rows):
    candidate_ids = set()
    for row in rows:
        candidate_ids.update(_normalize_candidate_ids(row.get("candidates")))
    if not candidate_ids:
        return {}
    cur.execute(
        """
        WITH candidate_links AS (
            SELECT
                h.candidate_id,
                h.opportunity_id,
                1 AS priority,
                h.start_date,
                h.end_date
            FROM hire_opportunity h
            WHERE h.candidate_id = ANY(%s)
            UNION ALL
            SELECT
                oc.candidate_id,
                oc.opportunity_id,
                2 AS priority,
                NULL AS start_date,
                NULL AS end_date
            FROM opportunity_candidates oc
            WHERE oc.candidate_id = ANY(%s)
        ),
        ranked AS (
            SELECT
                candidate_id,
                opportunity_id,
                ROW_NUMBER() OVER (
                    PARTITION BY candidate_id
                    ORDER BY priority ASC,
                             (end_date IS NULL) DESC,
                             start_date DESC NULLS LAST,
                             opportunity_id DESC
                ) AS rn
            FROM candidate_links
        )
        SELECT r.candidate_id, o.opp_position_name
        FROM ranked r
        LEFT JOIN opportunity o ON o.opportunity_id = r.opportunity_id
        WHERE r.rn = 1
        """,
        (list(candidate_ids), list(candidate_ids)),
    )
    return {row.get("candidate_id"): row.get("opp_position_name") for row in cur.fetchall()}


def _fetch_account_names(cur, rows):
    account_ids = set()
    for row in rows:
        account_ids.update(_normalize_account_ids(row.get("accounts")))
    if not account_ids:
        return {}
    cur.execute(
        """
        SELECT account_id, client_name
        FROM account
        WHERE account_id = ANY(%s)
        """,
        (list(account_ids),),
    )
    return {row.get("account_id"): row.get("client_name") for row in cur.fetchall()}


def _serialize_hunter_rows(rows, candidate_names=None, candidate_positions=None, account_names=None):
    serialized = []
    for row in rows:
        candidates = _normalize_candidate_ids(row.get("candidates"))
        accounts = _normalize_account_ids(row.get("accounts"))
        candidate_details = []
        if candidate_names or candidate_positions:
            for candidate_id in candidates:
                candidate_details.append(
                    {
                        "id": candidate_id,
                        "name": candidate_names.get(candidate_id) if candidate_names else None,
                        "position": candidate_positions.get(candidate_id)
                        if candidate_positions
                        else None,
                    }
                )
        account_details = []
        if account_names:
            for account_id in accounts:
                account_details.append(
                    {"id": account_id, "name": account_names.get(account_id)}
                )
        serialized.append(
            {
                "hunter_id": row.get("hunter_id"),
                "company": row.get("company"),
                "industry": row.get("industry"),
                "amount_candidates": row.get("amount_candidates") or len(candidates),
                "candidates": candidates,
                "candidate_details": candidate_details,
                "accounts": accounts,
                "account_details": account_details,
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
        candidate_names = _fetch_candidate_names(cur, rows)
        candidate_positions = _fetch_candidate_positions(cur, rows)
        account_names = _fetch_account_names(cur, rows)
        return jsonify(
            {
                "rows": _serialize_hunter_rows(
                    rows, candidate_names, candidate_positions, account_names
                )
            }
        )
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

    started_at = time.time()
    logging.info("Hunter refresh start")

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    inserted = 0
    updated = 0
    classified = 0
    to_classify = []

    try:
        cur.execute("SELECT COALESCE(MAX(hunter_id), 0) AS max_id FROM hunter")
        next_id = (cur.fetchone() or {}).get("max_id", 0) + 1
        logging.info("Hunter refresh max_id=%s next_id=%s", next_id - 1, next_id)

        cur.execute(
            """
            SELECT candidate_id, account_id
            FROM hire_opportunity
            WHERE account_id IS NOT NULL
            """
        )
        hire_rows = cur.fetchall()
        candidate_accounts = {}
        hired_candidate_ids = set()
        for row in hire_rows:
            candidate_id = row.get("candidate_id")
            account_id = row.get("account_id")
            if candidate_id is None or account_id is None:
                continue
            candidate_accounts.setdefault(candidate_id, set()).add(int(account_id))
            hired_candidate_ids.add(candidate_id)

        cur.execute(
            """
            SELECT oc.candidate_id, o.account_id
            FROM opportunity_candidates oc
            JOIN opportunity o ON o.opportunity_id = oc.opportunity_id
            WHERE o.account_id IS NOT NULL
            """
        )
        opportunity_rows = cur.fetchall()
        for row in opportunity_rows:
            candidate_id = row.get("candidate_id")
            account_id = row.get("account_id")
            if candidate_id is None or account_id is None:
                continue
            candidate_accounts.setdefault(candidate_id, set()).add(int(account_id))

        cur.execute(
            """
            SELECT hunter_id, company, industry, amount_candidates, candidates,
                   accounts, company_linkedin
            FROM hunter
            """
        )
        existing_rows = cur.fetchall()
        logging.info("Hunter refresh existing_rows=%s", len(existing_rows))
        by_company = {}
        for row in existing_rows:
            norm = _normalize_company(row.get("company"))
            if norm:
                row["candidates"] = []
                row["accounts"] = []
                row["amount_candidates"] = 0
                by_company[norm] = row

        resume_rows = []
        if hired_candidate_ids:
            cur.execute(
                """
                SELECT candidate_id, work_experience
                FROM resume
                WHERE work_experience IS NOT NULL
                  AND candidate_id = ANY(%s)
                """,
                (list(hired_candidate_ids),),
            )
            resume_rows = cur.fetchall()
        logging.info("Hunter refresh resume_rows=%s", len(resume_rows))

        companies_seen = set()

        for resume in resume_rows:
            candidate_id = resume.get("candidate_id")
            if candidate_id is None:
                continue
            companies = _extract_companies(resume.get("work_experience"))
            for company in companies:
                norm = _normalize_company(company)
                if not norm:
                    continue
                companies_seen.add(norm)
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

        stale_norms = [norm for norm in by_company if norm not in companies_seen]
        for norm in stale_norms:
            row = by_company.get(norm)
            if not row:
                continue
            cur.execute(
                """
                DELETE FROM hunter
                WHERE hunter_id = %s
                """,
                (row.get("hunter_id"),),
            )
            by_company.pop(norm, None)

        for row in by_company.values():
            account_ids = set()
            for candidate_id in row.get("candidates") or []:
                account_ids.update(candidate_accounts.get(candidate_id, set()))
            accounts_list = sorted(account_ids)
            existing_accounts = sorted(set(row.get("accounts") or []))
            if accounts_list != existing_accounts:
                cur.execute(
                    """
                    UPDATE hunter
                    SET accounts = %s
                    WHERE hunter_id = %s
                    """,
                    (json.dumps(accounts_list) if accounts_list else None, row.get("hunter_id")),
                )

        conn.commit()
        logging.info("Hunter refresh inserted=%s updated=%s", inserted, updated)

        for row in by_company.values():
            if row.get("industry") and row.get("company_linkedin"):
                continue
            to_classify.append(
                {
                    "hunter_id": row.get("hunter_id"),
                    "company": row.get("company"),
                    "industry": row.get("industry"),
                    "company_linkedin": row.get("company_linkedin"),
                }
            )

        if to_classify:
            threading.Thread(
                target=_classify_companies_async,
                args=(to_classify,),
                daemon=True,
            ).start()
            classified = len(to_classify)
            logging.info("Hunter refresh queued_classifications=%s", classified)

        cur.execute(
            """
            SELECT hunter_id, company, industry, amount_candidates, candidates,
                   accounts, company_linkedin
            FROM hunter
            ORDER BY hunter_id ASC
            """
        )
        rows = cur.fetchall()
        candidate_names = _fetch_candidate_names(cur, rows)
        candidate_positions = _fetch_candidate_positions(cur, rows)
        account_names = _fetch_account_names(cur, rows)
        elapsed = time.time() - started_at
        logging.info("Hunter refresh done rows=%s elapsed=%.2fs", len(rows), elapsed)
        return jsonify(
            {
                "inserted": inserted,
                "updated": updated,
                "classified": classified,
                "rows": _serialize_hunter_rows(
                    rows, candidate_names, candidate_positions, account_names
                ),
            }
        )
    except Exception:
        logging.exception("Hunter refresh failed")
        conn.rollback()
        elapsed = time.time() - started_at
        logging.info("Hunter refresh failed elapsed=%.2fs", elapsed)
        return jsonify({"error": "Hunter refresh failed"}), 500
    finally:
        cur.close()
        conn.close()
