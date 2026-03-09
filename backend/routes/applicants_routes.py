import logging
import os
import uuid

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

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

        return jsonify({"message": "Applicant created", "applicant_id": applicant_id}), 201
    except Exception as exc:
        logging.exception("Failed to create applicant")
        return jsonify({"error": str(exc)}), 500


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
