import json
import logging
from typing import Optional
import os
import uuid

import openai
from flask import Blueprint, jsonify, request
from psycopg2.extras import Json
from werkzeug.utils import secure_filename

from ai_routes import (
    _build_opportunity_context,
    _extract_pdf_text_with_openai,
    _score_applicant_with_openai,
)
from db import get_connection
from utils import services

bp = Blueprint("applicants", __name__)

ALLOWED_CV_EXTS = {
    "pdf",
    "png",
    "jpg",
    "jpeg",
    "webp",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "csv",
}

CONTENT_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
}


def _clean(val):
    return (val or "").strip()


def _clean_optional(val):
    value = (val or "").strip()
    return value or None


def _file_size_bytes(file_obj):
    try:
        file_obj.stream.seek(0, os.SEEK_END)
        size = file_obj.stream.tell()
        file_obj.stream.seek(0)
        return size
    except Exception:
        return None


def _is_pdf_upload(filename: str, content_type: Optional[str]) -> bool:
    if content_type and content_type.lower() == "application/pdf":
        return True
    return filename.lower().endswith(".pdf")


def _fetch_s3_bytes(s3_key: str) -> Optional[bytes]:
    try:
        obj = services.s3_client.get_object(Bucket=services.S3_BUCKET, Key=s3_key)
        return obj["Body"].read()
    except Exception:
        logging.exception("Failed to download applicant CV from S3")
        return None


def _backfill_applicant_ai_fields(opportunity_id=None, limit=None, filters=None, dry_run=False):
    filters = filters or {}
    conn = get_connection()
    cur = conn.cursor()
    try:
        query = """
            SELECT
                applicant_id,
                opportunity_id,
                location,
                role_position,
                area,
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
        if limit is not None:
            query += " LIMIT %s"
            params.append(int(limit))

        cur.execute(query, params)
        rows = cur.fetchall()
        opp_cache = {}
        updated = 0
        extracted_count = 0
        scored_count = 0

        for (
            applicant_id,
            opp_id,
            location,
            role_position,
            area,
            s3_key,
            file_name,
            content_type,
            extracted_pdf,
            match_score,
            reasons,
        ) in rows:
            needs_extraction = not (extracted_pdf or "").strip()
            needs_score = match_score is None or reasons is None

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
                extracted_count += 1

            if needs_score and extracted_pdf and opp_id:
                if opp_id not in opp_cache:
                    jd_plain, opp_context = _build_opportunity_context(cur, opp_id)
                    opp_cache[opp_id] = (jd_plain, opp_context)
                jd_plain, opp_context = opp_cache[opp_id]
                score, reason_text = _score_applicant_with_openai(
                    extracted_pdf,
                    location or "",
                    jd_plain,
                    filters=filters,
                    opportunity_context=opp_context,
                    candidate_context={"role_position": role_position or "", "area": area or ""},
                )
                if match_score is None and score is not None:
                    match_score = score
                if (reasons is None or reasons == "") and reason_text:
                    reasons = reason_text
                if score is not None or reason_text:
                    scored_count += 1

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
            "total": len(rows),
            "updated": updated,
            "extracted": extracted_count,
            "scored": scored_count,
            "dry_run": dry_run,
        }
    finally:
        cur.close()
        conn.close()


def _update_applicant_ai_fields(applicant_id, extracted_pdf, match_score, reasons):
    conn = get_connection()
    cur = conn.cursor()
    try:
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
        conn.commit()
    finally:
        cur.close()
        conn.close()


@bp.route("/applicants/<int:applicant_id>/cv", methods=["GET", "OPTIONS"])
def get_applicant_cv(applicant_id):
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT cv_s3_key, cv_file_name, cv_content_type
            FROM applicants
            WHERE applicant_id = %s
            """,
            (applicant_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row or not row[0]:
            return jsonify({"error": "CV not found"}), 404

        s3_key, filename, content_type = row
        safe_name = filename or "applicant_cv"
        url = services.s3_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": services.S3_BUCKET,
                "Key": s3_key,
                "ResponseContentDisposition": f'attachment; filename="{safe_name}"',
                "ResponseContentType": content_type or "application/octet-stream",
            },
            ExpiresIn=3600,
        )
        return jsonify({"url": url, "file_name": safe_name})
    except Exception as exc:
        logging.exception("Failed to get applicant CV")
        return jsonify({"error": str(exc)}), 500


@bp.route("/applicants", methods=["GET", "OPTIONS"])
def get_applicants():
    if request.method == "OPTIONS":
        return ("", 204)

    raw_opportunity_id = request.args.get("opportunity_id")
    if raw_opportunity_id is None:
        return jsonify({"error": "Missing opportunity_id"}), 400

    try:
        opportunity_id = int(raw_opportunity_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid opportunity_id"}), 400

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                applicant_id,
                first_name,
                last_name,
                email,
                phone,
                location,
                role_position,
                area,
                linkedin_url,
                english_level,
                referral_source,
                opportunity_id,
                question_1,
                question_2,
                question_3,
                cv_s3_key,
                cv_file_name,
                cv_content_type,
                cv_size_bytes,
                match_score,
                reasons,
                extracted_pdf,
                parsed_cv,
                created_at,
                updated_at
            FROM applicants
            WHERE opportunity_id = %s
            ORDER BY updated_at DESC
            """,
            (opportunity_id,),
        )
        rows = cur.fetchall()
        colnames = [desc[0] for desc in cur.description]
        data = [dict(zip(colnames, row)) for row in rows]
        cur.close()
        conn.close()
        return jsonify(data)
    except Exception as exc:
        logging.exception("Failed to fetch applicants")
        return jsonify({"error": str(exc)}), 500


@bp.route("/applicants", methods=["POST", "OPTIONS"])
def create_applicant():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.form or {}
    required_fields = [
        "first_name",
        "last_name",
        "email",
        "phone",
        "location",
        "role_position",
        "area",
        "linkedin_url",
        "english_level",
        "referral_source",
    ]

    missing = [f for f in required_fields if not _clean(data.get(f))]
    if missing:
        return jsonify({"error": "Missing required fields", "fields": missing}), 400

    raw_opportunity_id = _clean(data.get("opportunity_id"))
    opportunity_id = None
    if raw_opportunity_id:
        try:
            opportunity_id = int(raw_opportunity_id)
        except ValueError:
            return jsonify({"error": "Invalid opportunity_id"}), 400

    cv_file = request.files.get("cv")
    if not cv_file:
        return jsonify({"error": "Missing CV file"}), 400

    filename_orig = (cv_file.filename or "").strip()
    ext = filename_orig.rsplit(".", 1)[-1].lower() if "." in filename_orig else ""
    if ext not in ALLOWED_CV_EXTS:
        allowed = ", ".join(sorted(ALLOWED_CV_EXTS))
        return jsonify({"error": f"Unsupported file type .{ext}. Allowed: {allowed}"}), 400

    safe_name = secure_filename(filename_orig) or f"cv.{ext}"
    s3_key = f"applicants/{uuid.uuid4()}_{safe_name}"
    content_type = cv_file.mimetype or CONTENT_TYPES.get(ext, "application/octet-stream")
    file_size = _file_size_bytes(cv_file)
    cv_bytes = None
    if _is_pdf_upload(filename_orig, content_type):
        try:
            cv_file.stream.seek(0)
            cv_bytes = cv_file.stream.read()
            cv_file.stream.seek(0)
        except Exception:
            logging.exception("Failed to read CV bytes for extraction")
            cv_bytes = None

    try:
        services.s3_client.upload_fileobj(
            cv_file,
            services.S3_BUCKET,
            s3_key,
            ExtraArgs={"ContentType": content_type},
        )

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO applicants (
                first_name,
                last_name,
                email,
                phone,
                location,
                role_position,
                area,
                linkedin_url,
                english_level,
                referral_source,
                opportunity_id,
                question_1,
                question_2,
                question_3,
                cv_s3_key,
                cv_file_name,
                cv_content_type,
                cv_size_bytes,
                created_at,
                updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s,
                NOW(), NOW()
            )
            RETURNING applicant_id
            """,
            (
                _clean(data.get("first_name")),
                _clean(data.get("last_name")),
                _clean(data.get("email")),
                _clean(data.get("phone")),
                _clean(data.get("location")),
                _clean(data.get("role_position")),
                _clean(data.get("area")),
                _clean(data.get("linkedin_url")),
                _clean(data.get("english_level")),
                _clean(data.get("referral_source")),
                opportunity_id,
                _clean_optional(data.get("question_1")),
                _clean_optional(data.get("question_2")),
                _clean_optional(data.get("question_3")),
                s3_key,
                filename_orig,
                content_type,
                file_size,
            ),
        )
        applicant_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        if cv_bytes:
            try:
                extracted_pdf = _extract_pdf_text_with_openai(cv_bytes)
                score = None
                reasons = None
                if opportunity_id:
                    conn = get_connection()
                    cur = conn.cursor()
                    jd_plain, opp_context = _build_opportunity_context(cur, opportunity_id)
                    cur.close()
                    conn.close()
                    score, reasons = _score_applicant_with_openai(
                        extracted_pdf,
                        _clean(data.get("location")),
                        jd_plain,
                        filters=None,
                        opportunity_context=opp_context,
                        candidate_context={
                            "role_position": _clean(data.get("role_position")),
                            "area": _clean(data.get("area")),
                        },
                    )
                if extracted_pdf or score is not None or reasons:
                    _update_applicant_ai_fields(applicant_id, extracted_pdf, score, reasons)
            except Exception:
                logging.exception("Failed to extract/score applicant CV")

        return jsonify({"message": "Applicant created", "applicant_id": applicant_id}), 201
    except Exception as exc:
        logging.exception("Failed to create applicant")
        return jsonify({"error": str(exc)}), 500


@bp.route("/applicants/recalculate_scores", methods=["POST", "OPTIONS"])
def recalculate_applicant_scores():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}
    opportunity_id = data.get("opportunity_id")
    filters = data.get("filters") or {}

    if opportunity_id is None:
        return jsonify({"error": "Missing opportunity_id"}), 400

    try:
        conn = get_connection()
        cur = conn.cursor()
        jd_plain, opp_context = _build_opportunity_context(cur, int(opportunity_id))
        cur.execute(
            """
            SELECT applicant_id, location, extracted_pdf, role_position, area
            FROM applicants
            WHERE opportunity_id = %s
            """,
            (int(opportunity_id),),
        )
        rows = cur.fetchall()
        updated = 0
        for applicant_id, location, extracted_pdf, role_position, area in rows:
            if not extracted_pdf:
                continue
            score, reasons = _score_applicant_with_openai(
                extracted_pdf,
                location or "",
                jd_plain,
                filters=filters,
                opportunity_context=opp_context,
                candidate_context={"role_position": role_position or "", "area": area or ""},
            )
            if score is None and not reasons:
                continue
            cur.execute(
                """
                UPDATE applicants
                SET match_score = %s,
                    reasons = %s,
                    updated_at = NOW()
                WHERE applicant_id = %s
                """,
                (score, reasons, applicant_id),
            )
            updated += 1
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"updated": updated}), 200
    except Exception as exc:
        logging.exception("Failed to recalculate applicant scores")
        return jsonify({"error": str(exc)}), 500


@bp.route("/applicants/backfill_extracted_pdf", methods=["POST", "OPTIONS"])
def backfill_applicant_extracted_pdf():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}
    opportunity_id = data.get("opportunity_id")
    filters = data.get("filters") or {}
    limit = data.get("limit")
    try:
        limit = int(limit) if limit is not None else None
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid limit"}), 400

    try:
        conn = get_connection()
        cur = conn.cursor()

        query = """
            SELECT applicant_id, opportunity_id, location, role_position, area, cv_s3_key, cv_file_name, cv_content_type,
                   extracted_pdf
            FROM applicants
            WHERE (extracted_pdf IS NULL OR extracted_pdf = '')
        """
        params = []
        if opportunity_id is not None:
            query += " AND opportunity_id = %s"
            params.append(int(opportunity_id))
        query += " ORDER BY updated_at DESC"
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)

        cur.execute(query, params)
        rows = cur.fetchall()
        opp_cache = {}
        extracted_count = 0
        scored_count = 0

        for applicant_id, opp_id, location, role_position, area, s3_key, file_name, content_type, extracted_pdf in rows:
            if not s3_key:
                continue
            if extracted_pdf:
                continue
            if not _is_pdf_upload(file_name or s3_key, content_type):
                continue

            pdf_bytes = _fetch_s3_bytes(s3_key)
            if not pdf_bytes:
                continue

            extracted_pdf = _extract_pdf_text_with_openai(pdf_bytes)
            if not extracted_pdf:
                continue

            score = None
            reasons = None
            if opp_id:
                if opp_id not in opp_cache:
                    jd_plain, opp_context = _build_opportunity_context(cur, opp_id)
                    opp_cache[opp_id] = (jd_plain, opp_context)
                jd_plain, opp_context = opp_cache[opp_id]
                score, reasons = _score_applicant_with_openai(
                    extracted_pdf,
                    location or "",
                    jd_plain,
                    filters=filters,
                    opportunity_context=opp_context,
                    candidate_context={"role_position": role_position or "", "area": area or ""},
                )
            cur.execute(
                """
                UPDATE applicants
                SET extracted_pdf = %s,
                    match_score = %s,
                    reasons = %s,
                    updated_at = NOW()
                WHERE applicant_id = %s
                """,
                (extracted_pdf, score, reasons, applicant_id),
            )
            extracted_count += 1
            if score is not None or reasons:
                scored_count += 1

        conn.commit()
        cur.close()
        conn.close()
        return jsonify(
            {
                "extracted": extracted_count,
                "scored": scored_count,
            }
        ), 200
    except Exception as exc:
        logging.exception("Failed to backfill applicant PDFs")
        return jsonify({"error": str(exc)}), 500


@bp.route("/applicants/backfill_ai_fields", methods=["POST", "OPTIONS"])
def backfill_applicant_ai_fields():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}
    opportunity_id = data.get("opportunity_id")
    limit = data.get("limit")
    filters = data.get("filters") or {}
    dry_run = bool(data.get("dry_run"))

    try:
        if opportunity_id is not None:
            opportunity_id = int(opportunity_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid opportunity_id"}), 400

    try:
        limit = int(limit) if limit is not None else None
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid limit"}), 400

    try:
        result = _backfill_applicant_ai_fields(
            opportunity_id=opportunity_id,
            limit=limit,
            filters=filters,
            dry_run=dry_run,
        )
        return jsonify(result), 200
    except Exception as exc:
        logging.exception("Failed to backfill applicant AI fields")
        return jsonify({"error": str(exc)}), 500


@bp.route("/applicants/<int:applicant_id>/refresh_ai_fields", methods=["POST", "OPTIONS"])
def refresh_applicant_ai_fields(applicant_id):
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}
    filters = data.get("filters") or {}

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT
                applicant_id,
                opportunity_id,
                location,
                role_position,
                area,
                cv_s3_key,
                cv_file_name,
                cv_content_type,
                extracted_pdf,
                match_score,
                reasons
            FROM applicants
            WHERE applicant_id = %s
            """,
            (applicant_id,),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Applicant not found"}), 404

        (
            _,
            opp_id,
            location,
            role_position,
            area,
            s3_key,
            file_name,
            content_type,
            extracted_pdf,
            match_score,
            reasons,
        ) = row

        updated = False
        extracted = False
        scored = False

        if not (extracted_pdf or "").strip():
            if not s3_key:
                return jsonify({"error": "Applicant has no CV uploaded"}), 400
            if not _is_pdf_upload(file_name or s3_key, content_type):
                return jsonify({"error": "Applicant CV is not a PDF"}), 400
            pdf_bytes = _fetch_s3_bytes(s3_key)
            if not pdf_bytes:
                return jsonify({"error": "Unable to download applicant CV"}), 502
            extracted_pdf = _extract_pdf_text_with_openai(pdf_bytes)
            if not extracted_pdf:
                return jsonify({"error": "Unable to extract CV text"}), 500
            extracted = True
            updated = True

        if extracted_pdf and opp_id:
            jd_plain, opp_context = _build_opportunity_context(cur, opp_id)
            score, reason_text = _score_applicant_with_openai(
                extracted_pdf,
                location or "",
                jd_plain,
                filters=filters,
                opportunity_context=opp_context,
                candidate_context={"role_position": role_position or "", "area": area or ""},
            )
            if score is not None and score != match_score:
                match_score = score
                updated = True
            if reason_text and reason_text != (reasons or ""):
                reasons = reason_text
                updated = True
            if score is not None or reason_text:
                scored = True

        if updated:
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
            conn.commit()

        return jsonify(
            {
                "updated": updated,
                "extracted": extracted,
                "scored": scored,
                "match_score": match_score,
                "reasons": reasons,
            }
        ), 200
    except Exception as exc:
        logging.exception("Failed to refresh applicant AI fields")
        return jsonify({"error": str(exc)}), 500
    finally:
        cur.close()
        conn.close()


PARSE_CV_SYSTEM_PROMPT = (
    "You extract structured work experience and education from CV text. "
    "Return ONLY valid JSON matching this exact shape:\n"
    "{\n"
    '  "experience": [{"title": "", "company": "", "start": "", "end": ""}],\n'
    '  "education":  [{"degree": "", "institution": "", "start": "", "end": ""}]\n'
    "}\n"
    "Rules:\n"
    "- Use empty strings for missing fields. Do NOT invent data.\n"
    "- Dates: prefer YYYY or YYYY-MM. Use 'Present' for current roles when stated.\n"
    "- Order both arrays from most recent to oldest.\n"
    "- If the CV has no clear experience or education section, return an empty array for it."
)


def _coerce_parse_cv_payload(raw):
    if not isinstance(raw, dict):
        return {"experience": [], "education": []}

    def _coerce_entries(items, fields):
        if not isinstance(items, list):
            return []
        cleaned = []
        for item in items:
            if not isinstance(item, dict):
                continue
            cleaned.append({field: str(item.get(field, "") or "").strip() for field in fields})
        return cleaned

    return {
        "experience": _coerce_entries(raw.get("experience"), ("title", "company", "start", "end")),
        "education": _coerce_entries(raw.get("education"), ("degree", "institution", "start", "end")),
    }


@bp.route("/applicants/<int:applicant_id>/parse-cv", methods=["POST", "OPTIONS"])
def parse_applicant_cv(applicant_id):
    if request.method == "OPTIONS":
        return ("", 204)

    force = request.args.get("force") in ("1", "true", "yes")

    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT parsed_cv, extracted_pdf FROM applicants WHERE applicant_id = %s",
            (applicant_id,),
        )
        row = cur.fetchone()
        if row is None:
            return jsonify({"error": "Applicant not found"}), 404

        parsed_cv, extracted_pdf = row

        if parsed_cv and not force:
            if isinstance(parsed_cv, str):
                try:
                    parsed_cv = json.loads(parsed_cv)
                except Exception:
                    parsed_cv = None
            if parsed_cv:
                return jsonify({"parsed_cv": parsed_cv, "cached": True}), 200

        cv_text = (extracted_pdf or "").strip()
        if not cv_text:
            return jsonify({"parsed_cv": None, "reason": "no_cv_text"}), 200

        truncated = cv_text[:12000]

        try:
            response = openai.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": PARSE_CV_SYSTEM_PROMPT},
                    {"role": "user", "content": truncated},
                ],
            )
            content = response.choices[0].message.content or "{}"
            raw = json.loads(content)
        except Exception as exc:
            logging.exception("OpenAI parse-cv call failed for applicant %s", applicant_id)
            return jsonify({"error": "Failed to parse CV", "detail": str(exc)}), 502

        normalized = _coerce_parse_cv_payload(raw)

        cur.execute(
            "UPDATE applicants SET parsed_cv = %s, updated_at = NOW() WHERE applicant_id = %s",
            (Json(normalized), applicant_id),
        )
        conn.commit()

        return jsonify({"parsed_cv": normalized, "cached": False}), 200
    except Exception as exc:
        logging.exception("parse-cv endpoint failed for applicant %s", applicant_id)
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return jsonify({"error": str(exc)}), 500
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()


@bp.route("/linkedin_hub", methods=["GET", "OPTIONS"])
def get_linkedin_hub_entry():
    if request.method == "OPTIONS":
        return ("", 204)

    raw_opportunity_id = request.args.get("opportunity_id")
    if raw_opportunity_id is None:
        return jsonify({"error": "Missing opportunity_id"}), 400

    try:
        opportunity_id = int(raw_opportunity_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid opportunity_id"}), 400

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                question_1,
                question_2,
                question_3,
                answer_question_1,
                answer_question_2,
                answer_question_3
            FROM linkedin_hub
            WHERE opportunity_id = %s
            ORDER BY linkedin_hub_id DESC
            LIMIT 1
            """,
            (opportunity_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return (
                jsonify(
                    {
                        "opportunity_id": opportunity_id,
                        "question_1": None,
                        "question_2": None,
                        "question_3": None,
                        "answer_question_1": None,
                        "answer_question_2": None,
                        "answer_question_3": None,
                    }
                ),
                200,
            )

        return (
            jsonify(
                {
                    "opportunity_id": opportunity_id,
                    "question_1": row[0],
                    "question_2": row[1],
                    "question_3": row[2],
                    "answer_question_1": row[3],
                    "answer_question_2": row[4],
                    "answer_question_3": row[5],
                }
            ),
            200,
        )
    except Exception as exc:
        logging.exception("Failed to fetch linkedin_hub entry")
        return jsonify({"error": str(exc)}), 500


@bp.route("/linkedin_hub", methods=["POST", "OPTIONS"])
def create_linkedin_hub_entry():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}
    raw_opportunity_id = data.get("opportunity_id")
    if raw_opportunity_id is None:
        return jsonify({"error": "Missing opportunity_id"}), 400

    try:
        opportunity_id = int(raw_opportunity_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid opportunity_id"}), 400

    def _clean_optional(val):
        s = (val or "").strip()
        return s or None

    question_1 = _clean_optional(data.get("question_1"))
    question_2 = _clean_optional(data.get("question_2"))
    question_3 = _clean_optional(data.get("question_3"))

    answer_1 = _clean_optional(data.get("answer_question_1")) if question_1 else None
    answer_2 = _clean_optional(data.get("answer_question_2")) if question_2 else None
    answer_3 = _clean_optional(data.get("answer_question_3")) if question_3 else None

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(linkedin_hub_id), 0) FROM linkedin_hub")
        next_id = int(cur.fetchone()[0]) + 1

        cur.execute(
            """
            INSERT INTO linkedin_hub (
                linkedin_hub_id,
                opportunity_id,
                question_1,
                question_2,
                question_3,
                answer_question_1,
                answer_question_2,
                answer_question_3
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING linkedin_hub_id
            """,
            (
                next_id,
                opportunity_id,
                question_1,
                question_2,
                question_3,
                answer_1,
                answer_2,
                answer_3,
            ),
        )
        linkedin_hub_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "message": "LinkedIn hub entry created",
                "linkedin_hub_id": linkedin_hub_id,
                "opportunity_id": opportunity_id,
            }
        ), 201
    except Exception as exc:
        logging.exception("Failed to create linkedin_hub entry")
        return jsonify({"error": str(exc)}), 500
