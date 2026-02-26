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


def _file_size_bytes(file_obj):
    try:
        file_obj.stream.seek(0, os.SEEK_END)
        size = file_obj.stream.tell()
        file_obj.stream.seek(0)
        return size
    except Exception:
        return None


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
                cv_s3_key,
                cv_file_name,
                cv_content_type,
                cv_size_bytes,
                created_at,
                updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
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
