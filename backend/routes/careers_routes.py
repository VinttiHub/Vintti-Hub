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

SHEET_JOB_ID_HEADERS = ["Job ID", "Item ID", "Job", "JobID", "ID"]
SHEET_ACTION_HEADERS = [
    "Action",
    "Action (Hub)",
    "Action Hub",
    "Action HUB",
    "Accion",
    "Acción",
    "Status",
    "Status Hub",
    "Estado",
    "Estado Hub",
]

IMPORT_SPREADSHEET_ID = os.getenv("IMPORT_SPREADSHEET_ID") or "1Jn9xDhu08-eEL2zn9mg_VCXqCdYBdYWiy2FenU2Lmf8"
IMPORT_SHEET_GID = os.getenv("IMPORT_SHEET_GID") or "0"
IMPORT_SHEET_TITLE = os.getenv("IMPORT_SHEET_TITLE") or ""


def _sheet_title_from_range(range_value: str) -> str:
    sheet_part = (range_value or "Open Positions!A:Z").split("!")[0].strip()
    if len(sheet_part) >= 2 and sheet_part[0] == sheet_part[-1] == "'":
        sheet_part = sheet_part[1:-1]
    return sheet_part or "Open Positions"


def _find_column_index(headers, candidates) -> int:
    if not headers:
        return -1
    lowered = [str(h or "").strip().lower() for h in headers]
    for candidate in candidates:
        key = str(candidate or "").strip().lower()
        if not key:
            continue
        for idx, header in enumerate(lowered):
            if header == key:
                return idx
    return -1


def _column_index_to_a1(idx: int) -> str:
    if idx < 0:
        raise ValueError("Column index must be >= 0")
    idx += 1
    label = ""
    while idx > 0:
        idx, remainder = divmod(idx - 1, 26)
        label = chr(65 + remainder) + label
    return label


def _resolve_career_job_id(opportunity_id: int) -> str:
    job_id = str(opportunity_id)
    try:
        conn = get_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT career_job_id FROM opportunity WHERE opportunity_id = %s", (opportunity_id,))
                row = cur.fetchone()
                if row and row[0]:
                    candidate = str(row[0]).strip()
                    if candidate:
                        job_id = candidate
    except Exception:
        logging.exception("⚠️ Unable to fetch career_job_id for opportunity %s", opportunity_id)
    return job_id


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

        sheet_title = _sheet_title_from_range(GOOGLE_SHEETS_RANGE or "Open Positions!A:Z")

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
        if not GOOGLE_SHEETS_SPREADSHEET_ID:
            return jsonify({"error": "Missing GOOGLE_SHEETS_SPREADSHEET_ID"}), 500

        svc = sheets_service()
        payload = request.get_json(silent=True) or {}
        action = (payload.get("action") or "").strip()
        if not action:
            return jsonify({"error": "Missing action"}), 400

        # Permite overrides manuales, pero generalmente usamos career_job_id
        explicit_job_id = (payload.get("job_id") or "").strip()
        job_id = explicit_job_id or _resolve_career_job_id(opportunity_id)

        sheet_title = _sheet_title_from_range(GOOGLE_SHEETS_RANGE or "Open Positions!A:Z")
        quoted_title = a1_quote(sheet_title)

        meta = svc.spreadsheets().get(spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID).execute()
        sheet_id = None
        for s in meta.get("sheets", []):
            props = s.get("properties", {})
            if props.get("title") == sheet_title:
                sheet_id = props.get("sheetId")
                break

        if sheet_id is None:
            return jsonify({"error": f"Sheet '{sheet_title}' not found"}), 500

        row_number = payload.get("row_number")
        needs_lookup = (not row_number) or action != "wrap_row"

        headers = []
        rows = []
        if needs_lookup:
            values_resp = svc.spreadsheets().values().get(
                spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID,
                range=f"{quoted_title}!A:AZ"
            ).execute()
            rows = values_resp.get("values", [])
            if not rows:
                return jsonify({"error": "Sheet appears empty"}), 400
            headers = rows[0]

        if row_number:
            try:
                target_rows = [int(row_number)]
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid row_number"}), 400
        else:
            job_col = _find_column_index(headers, SHEET_JOB_ID_HEADERS)
            if job_col < 0:
                return jsonify({"error": "Job ID column not found"}), 500
            job_norm = str(job_id or "").strip().lower()
            fallback_norm = str(opportunity_id).strip().lower()
            target_rows = []
            for idx, row in enumerate(rows[1:], start=2):
                cell = row[job_col] if job_col < len(row) else ""
                cell_norm = str(cell or "").strip().lower()
                if not cell_norm:
                    continue
                if cell_norm == job_norm or (fallback_norm and cell_norm == fallback_norm):
                    target_rows.append(idx)
            target_rows = sorted(set(target_rows))

        if not target_rows:
            return jsonify({"error": f"No rows found for Job ID {job_id}"}), 404

        if action == "wrap_row":
            batch_requests = []
            for rn in target_rows:
                start_row = rn - 1
                batch_requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": start_row,
                            "endRowIndex": rn
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "wrapStrategy": "WRAP"
                            }
                        },
                        "fields": "userEnteredFormat.wrapStrategy"
                    }
                })

            svc.spreadsheets().batchUpdate(
                spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID,
                body={"requests": batch_requests}
            ).execute()

            return jsonify({"updated": len(batch_requests), "action": action, "rows": target_rows}), 200

        if action in {"Archived", "Borrar"}:
            action_col = _find_column_index(headers, SHEET_ACTION_HEADERS)
            if action_col < 0:
                return jsonify({"error": "Action column not found"}), 400

            updates = []
            for rn in target_rows:
                col_letter = _column_index_to_a1(action_col)
                updates.append({
                    "range": f"{quoted_title}!{col_letter}{rn}",
                    "values": [[action]]
                })

            if not updates:
                return jsonify({"error": "Nothing to update"}), 400

            svc.spreadsheets().values().batchUpdate(
                spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID,
                body={
                    "valueInputOption": "USER_ENTERED",
                    "data": updates
                }
            ).execute()

            return jsonify({
                "updated": len(updates),
                "action": action,
                "job_id": job_id,
                "rows": target_rows
            }), 200

        return jsonify({"error": "Unsupported action"}), 400

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
