import argparse
import logging
import os
import sys

from ai_routes import _build_opportunity_context, _extract_pdf_text_with_openai, _score_applicant_with_openai
from db import get_connection
from utils import services


def _is_pdf_upload(filename, content_type):
    if content_type and content_type.lower() == "application/pdf":
        return True
    return str(filename or "").lower().endswith(".pdf")


def _fetch_s3_bytes(s3_key):
    try:
        obj = services.s3_client.get_object(Bucket=services.S3_BUCKET, Key=s3_key)
        return obj["Body"].read()
    except Exception:
        logging.exception("Failed to download applicant CV from S3")
        return None


def backfill(applicant_limit=None, opportunity_id=None, dry_run=False):
    conn = get_connection()
    cur = conn.cursor()
    try:
        query = """
            SELECT
                applicant_id,
                opportunity_id,
                location,
                cv_s3_key,
                cv_file_name,
                cv_content_type,
                extracted_pdf,
                match_score,
                reasons
            FROM applicants
            WHERE (
                extracted_pdf IS NULL OR extracted_pdf = ''
                OR match_score IS NULL
                OR reasons IS NULL
            )
        """
        params = []
        if opportunity_id is not None:
            query += " AND opportunity_id = %s"
            params.append(int(opportunity_id))
        query += " ORDER BY updated_at DESC"
        if applicant_limit is not None:
            query += " LIMIT %s"
            params.append(int(applicant_limit))

        cur.execute(query, params)
        rows = cur.fetchall()
        opp_cache = {}
        updated = 0
        extracted = 0
        scored = 0

        for (
            applicant_id,
            opp_id,
            location,
            s3_key,
            file_name,
            content_type,
            extracted_pdf,
            match_score,
            reasons,
        ) in rows:
            needs_extraction = not (extracted_pdf or "").strip()
            needs_scoring = match_score is None or reasons is None

            if needs_extraction:
                if not s3_key:
                    continue
                if not _is_pdf_upload(file_name or s3_key, content_type):
                    continue
                pdf_bytes = _fetch_s3_bytes(s3_key)
                if not pdf_bytes:
                    continue
                extracted_pdf = _extract_pdf_text_with_openai(pdf_bytes)
                if not extracted_pdf:
                    continue
                extracted += 1

            if needs_scoring and extracted_pdf and opp_id:
                if opp_id not in opp_cache:
                    jd_plain, opp_context = _build_opportunity_context(cur, opp_id)
                    opp_cache[opp_id] = (jd_plain, opp_context)
                jd_plain, opp_context = opp_cache[opp_id]
                score, reason_text = _score_applicant_with_openai(
                    extracted_pdf,
                    location or "",
                    jd_plain,
                    filters=None,
                    opportunity_context=opp_context,
                )
                if score is not None:
                    match_score = score
                if reason_text:
                    reasons = reason_text
                if score is not None or reason_text:
                    scored += 1

            if dry_run:
                continue

            cur.execute(
                """
                UPDATE applicants
                SET extracted_pdf = %s,
                    match_score = %s,
                    reasons = %s,
                    updated_at = NOW()
                WHERE applicant_id = %s
                """,
                (extracted_pdf, match_score, reasons, applicant_id),
            )
            updated += 1

        if not dry_run:
            conn.commit()

        return {
            "total_candidates": len(rows),
            "updated": updated,
            "extracted": extracted,
            "scored": scored,
            "dry_run": dry_run,
        }
    finally:
        cur.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Backfill applicants AI fields (extracted_pdf, match_score, reasons).")
    parser.add_argument("--limit", type=int, default=None, help="Max applicants to process.")
    parser.add_argument("--opportunity-id", type=int, default=None, help="Limit to one opportunity_id.")
    parser.add_argument("--dry-run", action="store_true", help="Compute counts without updating the DB.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = backfill(
        applicant_limit=args.limit,
        opportunity_id=args.opportunity_id,
        dry_run=args.dry_run,
    )
    print(result)


if __name__ == "__main__":
    sys.exit(main())
