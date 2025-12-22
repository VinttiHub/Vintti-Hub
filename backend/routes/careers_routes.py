import logging
import os
import re

from flask import Blueprint, jsonify, request

from db import get_connection
from utils.html_utils import clean_html_for_webflow
from utils.sheets_utils import (
    a1_quote,
    find_existing_candidate,
    find_opportunity_id,
    get_rows_with_headers,
    get_sheet_headers,
    get_sheet_title_by_gid,
    norm_email,
    norm_linkedin,
    norm_phone_digits,
    row_fingerprint,
    sheets_service,
)

bp = Blueprint('careers', __name__)

CAREER_TOOL_SLUGS = [
    "problem-solving",
    "teamwork",
    "time-management",
    "adaptability",
    "critical-thinking",
    "leadership",
    "creativity",
    "technical-skills",
    "interpersonal-skills",
    "communication-skills",
]

CANON = {
    "job_type": {
        "full-time": "Full-time",
        "part-time": "Part-time",
    },
    "seniority": {
        "entry-level": "Entry-level",
        "junior": "Junior",
        "semi-senior": "Semi-senior",
        "senior": "Senior",
        "manager": "Manager",
    },
    "experience_level": {
        "entry level job": "Entry-level Job",
        "experienced": "Experienced",
    },
    "field": {
        "accounting": "Accounting",
        "it": "IT",
        "legal": "Legal",
        "marketing": "Marketing",
        "virtual assistant": "Virtual Assistant",
    },
    "modality": {
        "remote": "Remote",
        "hybrid": "Hybrid",
        "on site": "On-site",
    },
}

GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
GOOGLE_SHEETS_RANGE = os.getenv("GOOGLE_SHEETS_RANGE") or "Open Positions!A:Z"

IMPORT_SPREADSHEET_ID = os.getenv("IMPORT_SPREADSHEET_ID") or "1Jn9xDhu08-eEL2zn9mg_VCXqCdYBdYWiy2FenU2Lmf8"
IMPORT_SHEET_GID = os.getenv("IMPORT_SHEET_GID") or "0"
IMPORT_SHEET_TITLE = os.getenv("IMPORT_SHEET_TITLE") or ""


@bp.route('/careers/<int:opportunity_id>/publish', methods=['POST'])
def publish_career_to_sheet(opportunity_id):
    """
    Inserta UNA fila en el Google Sheet usando los encabezados reales del sheet.
    """
    try:
        if not GOOGLE_SHEETS_SPREADSHEET_ID:
            return jsonify({"error": "Missing GOOGLE_SHEETS_SPREADSHEET_ID"}), 500

        svc = sheets_service()
        data = request.get_json(silent=True) or {}

        def _norm(s):
            return (s or '').strip()

        def _canon(kind, val):
            v = _norm(val)
            table = CANON.get(kind, {})
            for k, tgt in table.items():
                if k.lower() == v.lower():
                    return tgt
            return v

        job_id = str(data.get("career_job_id") or opportunity_id)
        country = _norm(data.get("career_country"))
        city = _norm(data.get("career_city"))
        job_type = _canon("job_type", data.get("career_job_type"))
        seniority = _canon("seniority", data.get("career_seniority"))
        years_exp = _norm(data.get("career_years_experience"))
        exp_level = _canon("experience_level", data.get("career_experience_level"))
        field_ = _canon("field", data.get("career_field"))
        remote = _canon("modality", data.get("career_modality"))
        tools_arr = data.get("career_tools") or []
        tools_txt = ", ".join([str(t).strip() for t in tools_arr if str(t).strip()])
        job_title = _norm(data.get("career_job"))

        desc_html = clean_html_for_webflow(data.get("sheet_description_html", ""))
        reqs_html = clean_html_for_webflow(data.get("sheet_requirements_html", ""))
        addi_html = clean_html_for_webflow(data.get("sheet_additional_html", ""))

        sheet_part = (GOOGLE_SHEETS_RANGE or "Open Positions!A:Z").split("!")[0].strip()
        if len(sheet_part) >= 2 and sheet_part[0] == sheet_part[-1] == "'":
            sheet_part = sheet_part[1:-1]
        sheet_title = sheet_part

        headers = get_sheet_headers(svc, GOOGLE_SHEETS_SPREADSHEET_ID, sheet_title)

        header_alias = {
            "JOB_ID": ["Job ID", "Item ID"],
            "JOB": ["Job", "Position", "Role"],
            "COUNTRY": ["Location Country", "Country"],
            "CITY": ["Location City", "City"],
            "JOB_TYPE": ["Job Type"],
            "SENIORITY": ["Seniority"],
            "YOE": ["Years of Experience"],
            "EXP_LEVEL": ["Experience Level"],
            "FIELD": ["Field"],
            "REMOTE": ["Remote Type", "Modality"],
            "TOOLS": ["Tools & Skills", "Tools"],
            "DESC": ["Description"],
            "REQS": ["Requirements"],
            "ADDI": ["Additional Information"],
        }

        def find_col(names):
            for name in names:
                try:
                    return headers.index(name)
                except ValueError:
                    continue
            return -1

        targets = {key: find_col(names) for key, names in header_alias.items()}

        if all(v < 0 for v in targets.values()):
            return jsonify({"error": "Sheet headers not found or misnamed"}), 500

        row_len = max([i for i in targets.values() if i >= 0]) + 1
        new_row = [""] * row_len

        def put(key, value):
            idx = targets.get(key, -1)
            if idx >= 0:
                if idx >= len(new_row):
                    new_row.extend([""] * (idx - len(new_row) + 1))
                new_row[idx] = value

        put("JOB_ID", job_id)
        put("JOB", job_title)
        put("COUNTRY", country)
        put("CITY", city)
        put("JOB_TYPE", job_type)
        put("SENIORITY", seniority)
        put("YOE", years_exp)
        put("EXP_LEVEL", exp_level)
        put("FIELD", field_)
        put("REMOTE", remote)
        put("TOOLS", tools_txt)
        put("DESC", desc_html)
        put("REQS", reqs_html)
        put("ADDI", addi_html)

        quoted_title = a1_quote(sheet_title)
        target_range = f"{quoted_title}!A:Z"

        append = svc.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID,
            range=target_range,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [new_row]}
        ).execute()

        meta = svc.spreadsheets().get(spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID).execute()
        sheet_id = None
        for s in meta.get("sheets", []):
            if s.get("properties", {}).get("title") == sheet_title:
                sheet_id = s.get("properties", {}).get("sheetId")
                break

        updated_range = (append.get("updates", {}) or {}).get("updatedRange")
        if sheet_id is not None and updated_range:
            match = re.search(r'!([A-Z]+)(\d+):([A-Z]+)(\d+)$', updated_range)
            if match:
                start_row = int(match.group(2)) - 1
                end_row = int(match.group(4))

                requests = [{
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": start_row,
                            "endRowIndex": end_row
                        },
                        "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                        "fields": "userEnteredFormat.wrapStrategy"
                    }
                }]

                tools_col = targets.get("TOOLS", -1)
                if tools_col >= 0:
                    requests.append({
                        "setDataValidation": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": start_row,
                                "endRowIndex": end_row,
                                "startColumnIndex": tools_col,
                                "endColumnIndex": tools_col + 1
                            },
                            "rule": {
                                "condition": {
                                    "type": "ONE_OF_LIST",
                                    "values": [{"userEnteredValue": v} for v in CAREER_TOOL_SLUGS]
                                },
                                "strict": True,
                                "showCustomUi": True
                            }
                        }
                    })

                svc.spreadsheets().batchUpdate(
                    spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID,
                    body={"requests": requests}
                ).execute()

        return jsonify({"career_id": job_id}), 200

    except Exception as exc:
        logging.exception("❌ publish_career_to_sheet failed")
        return jsonify({"error": str(exc)}), 500


@bp.route('/careers/<int:opportunity_id>/sheet_action', methods=['POST'])
def set_career_sheet_action(opportunity_id):
    try:
        svc = sheets_service()
        payload = request.get_json(silent=True) or {}
        action = payload.get("action")
        row_number = payload.get("row_number")
        sheet_id = payload.get("sheet_id")

        if not (row_number and sheet_id and action):
            return jsonify({"error": "Missing parameters"}), 400

        batch_requests = []

        if action == "wrap_row":
            start_row = row_number - 1
            end_row = row_number
            batch_requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": start_row,
                        "endRowIndex": end_row
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "wrapStrategy": "WRAP"
                        }
                    },
                    "fields": "userEnteredFormat.wrapStrategy"
                }
            })

        if not batch_requests:
            return jsonify({"error": "Unsupported action"}), 400

        svc.spreadsheets().batchUpdate(
            spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID,
            body={"requests": batch_requests}
        ).execute()

        return jsonify({"updated": len(batch_requests), "action": action}), 200

    except Exception as exc:
        logging.exception("❌ set_career_sheet_action failed")
        return jsonify({"error": str(exc)}), 500


@bp.route('/sheets/candidates/import', methods=['POST'])
def import_candidates_from_sheet():
    """
    Lee el Sheet de candidatos y crea/relaciona filas nuevas.
    """
    try:
        payload = request.get_json(silent=True) or {}
        spreadsheet_id = payload.get("spreadsheet_id") or IMPORT_SPREADSHEET_ID
        sheet_gid = str(payload.get("sheet_gid") or IMPORT_SHEET_GID)
        sheet_title = (payload.get("sheet_title") or IMPORT_SHEET_TITLE).strip()
        dry_run = bool(payload.get("dry_run", False))

        svc = sheets_service()
        if not sheet_title:
            sheet_title = get_sheet_title_by_gid(svc, spreadsheet_id, sheet_gid)

        rows = get_rows_with_headers(svc, spreadsheet_id, sheet_title)

        def getv(record, *aliases):
            for key in aliases:
                if key in record and record[key] != "":
                    return record[key]
            return ""

        to_process = []
        for row in rows:
            record = {
                "job_id":        getv(row, "job_id", "job", "opportunity_id"),
                "first_name":    getv(row, "first_name", "name", "nombre"),
                "last_name":     getv(row, "last_name", "apellido"),
                "email_address": getv(row, "email_address", "email"),
                "phone_number":  getv(row, "phone_number", "phone", "telefono"),
                "location":      getv(row, "location", "country", "pais"),
                "role":          getv(row, "role"),
                "area":          getv(row, "area"),
                "linkedin_url":  getv(row, "linkedin_url", "linkedin"),
                "english_level": getv(row, "english_level", "englishlevel", "ingles"),
                "_row_number":   row.get("_row_number"),
            }
            has_contact = any([record["email_address"], record["linkedin_url"], record["phone_number"]])
            if record["job_id"] and has_contact:
                to_process.append(record)

        conn = get_connection()
        cur = conn.cursor()

        report = {
            "sheet": {"spreadsheet_id": spreadsheet_id, "sheet_title": sheet_title, "gid": sheet_gid},
            "checked": len(to_process),
            "created_candidates": 0,
            "linked_existing": 0,
            "skipped_no_opportunity": 0,
            "skipped_already_logged": 0,
            "skipped_missing_contact": 0,
            "details": []
        }

        for rec in to_process:
            email_norm = norm_email(rec["email_address"])
            phone_norm = norm_phone_digits(rec["phone_number"])
            linkedin_norm = norm_linkedin(rec["linkedin_url"])
            fingerprint = row_fingerprint(rec)

            cur.execute("""
                SELECT 1 FROM sheet_import_log
                WHERE spreadsheet_id = %s AND sheet_gid = %s AND fingerprint = %s
                LIMIT 1
            """, (spreadsheet_id, sheet_gid, fingerprint))
            if cur.fetchone():
                report["skipped_already_logged"] += 1
                report["details"].append({"row": rec["_row_number"], "result": "already-logged"})
                continue

            opp_id = find_opportunity_id(cur, rec["job_id"])
            if not opp_id:
                report["skipped_no_opportunity"] += 1
                report["details"].append({"row": rec["_row_number"], "result": "no-opportunity", "job_id": rec["job_id"]})
                continue

            existing_id = find_existing_candidate(cur, email_norm, linkedin_norm, phone_norm)

            name = ((rec["first_name"] or "").strip() + " " + (rec["last_name"] or "").strip()).strip()
            country = rec.get("location") or ""

            if existing_id:
                cur.execute("""
                    INSERT INTO opportunity_candidates (opportunity_id, candidate_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                """, (opp_id, existing_id))
                if cur.rowcount > 0:
                    report["linked_existing"] += 1
                    report["details"].append({"row": rec["_row_number"], "result": "linked-existing", "candidate_id": existing_id})
            else:
                cur.execute("SELECT COALESCE(MAX(candidate_id), 0) FROM candidates")
                new_candidate_id = cur.fetchone()[0] + 1
                if not dry_run:
                    cur.execute("""
                        INSERT INTO candidates (
                            candidate_id, name, email, phone, linkedin,
                            english_level, country, stage, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """, (
                        new_candidate_id,
                        name or f"Candidate {new_candidate_id}",
                        email_norm or None,
                        rec["phone_number"] or None,
                        rec["linkedin_url"] or None,
                        rec["english_level"] or None,
                        country,
                        "Contactado"
                    ))
                    cur.execute("""
                        INSERT INTO opportunity_candidates (opportunity_id, candidate_id)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                    """, (opp_id, new_candidate_id))
                    report["created_candidates"] += 1
                    report["details"].append({"row": rec["_row_number"], "result": "created", "candidate_id": new_candidate_id})

            if not dry_run:
                cur.execute("""
                    INSERT INTO sheet_import_log (spreadsheet_id, sheet_gid, fingerprint, created_at, row_number)
                    VALUES (%s, %s, %s, NOW(), %s)
                """, (spreadsheet_id, sheet_gid, fingerprint, rec["_row_number"]))

        if not dry_run:
            conn.commit()
        else:
            conn.rollback()

        cur.close()
        conn.close()

        return jsonify(report)

    except Exception as exc:
        logging.exception("❌ import_candidates_from_sheet failed")
        return jsonify({"error": str(exc)}), 500
