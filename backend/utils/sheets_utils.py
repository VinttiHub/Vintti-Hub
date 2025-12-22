from __future__ import annotations

import hashlib
import json as _json
import os
import re

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def sheets_credentials():
    """
    Create credentials from GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE.
    """
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    sa_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")

    if sa_json:
        info = _json.loads(sa_json)
        pk = info.get("private_key")
        if isinstance(pk, str) and "\\n" in pk:
            info["private_key"] = pk.replace("\\n", "\n")
        return Credentials.from_service_account_info(info, scopes=SHEETS_SCOPES)

    if sa_file:
        return Credentials.from_service_account_file(sa_file, scopes=SHEETS_SCOPES)

    raise RuntimeError("Service Account credentials not configured")


def sheets_service():
    return build("sheets", "v4", credentials=sheets_credentials(), cache_discovery=False)


def a1_quote(sheet_name: str) -> str:
    s = (sheet_name or "").strip()
    if len(s) >= 2 and s[0] == s[-1] == "'":
        s = s[1:-1]
    s = s.replace("'", "''")
    return f"'{s}'"


def get_sheet_headers(service, spreadsheet_id, sheet_name):
    quoted = a1_quote(sheet_name)
    try:
        resp = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{quoted}!1:1"
        ).execute()
        values = resp.get("values", [[]])
        headers = values[0] if values else []
        return [h.strip() for h in headers]
    except Exception:
        meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = meta.get("sheets", [])
        if not sheets:
            raise
        first_title = sheets[0]["properties"]["title"]
        resp = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{a1_quote(first_title)}!1:1"
        ).execute()
        values = resp.get("values", [[]])
        headers = values[0] if values else []
        return [h.strip() for h in headers]


def get_sheet_title_by_gid(service, spreadsheet_id: str, gid: str) -> str:
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for sheet in meta.get("sheets", []):
        props = sheet.get("properties", {})
        if str(props.get("sheetId")) == str(gid):
            return props.get("title")
    return meta.get("sheets", [])[0].get("properties", {}).get("title")


def get_rows_with_headers(service, spreadsheet_id: str, sheet_title: str) -> list[dict]:
    quoted = a1_quote(sheet_title)
    resp = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{quoted}!A:Z"
    ).execute()
    values = resp.get("values", [])
    if not values:
        return []

    headers = [(h or "").strip() for h in values[0]]

    def _to_key(h):
        return re.sub(r'[^a-z0-9]+', '_', h.strip().lower()).strip('_')

    head_norm = [_to_key(h) for h in headers]

    out = []
    for idx, row in enumerate(values[1:], start=2):
        data = {}
        for j, cell in enumerate(row):
            key = head_norm[j] if j < len(head_norm) else f"col_{j+1}"
            data[key] = cell
        data["_row_number"] = idx
        out.append(data)
    return out


def norm_phone_digits(value: str | None) -> str:
    if not value:
        return ""
    return "".join(ch for ch in str(value) if ch.isdigit())


def norm_linkedin(value: str | None) -> str:
    if not value:
        return ""
    s = value.strip()
    s = s.split("?")[0].rstrip("/")
    return s.lower()


def norm_email(value: str | None) -> str:
    return (value or "").strip().lower()


def row_fingerprint(row: dict) -> str:
    parts = [
        str(row.get("job_id") or "").strip(),
        norm_email(row.get("email_address")),
        norm_linkedin(row.get("linkedin_url")),
        norm_phone_digits(row.get("phone_number")),
        (str(row.get("first_name") or "").strip() + " " + str(row.get("last_name") or "").strip()).strip(),
    ]
    base = "||".join(parts)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def find_opportunity_id(cursor, job_id: str | None) -> int | None:
    if not job_id:
        return None
    cursor.execute(
        "SELECT opportunity_id FROM opportunity "
        "WHERE CAST(opportunity_id AS TEXT) = %s OR CAST(career_job_id AS TEXT) = %s LIMIT 1",
        (str(job_id), str(job_id))
    )
    row = cursor.fetchone()
    return row[0] if row else None


def find_existing_candidate(cursor, email: str, linkedin: str, phone_norm: str) -> int | None:
    if email:
        cursor.execute(
            "SELECT candidate_id FROM candidates WHERE lower(email) = %s LIMIT 1",
            (email,)
        )
        row = cursor.fetchone()
        if row:
            return row[0]

    if linkedin:
        cursor.execute(
            """
            SELECT candidate_id
            FROM candidates
            WHERE lower(regexp_replace(COALESCE(linkedin,''), '/+$', '')) = %s
            LIMIT 1
            """,
            (linkedin.rstrip('/'),)
        )
        row = cursor.fetchone()
        if row:
            return row[0]

    if phone_norm:
        cursor.execute(
            """
            SELECT candidate_id
            FROM candidates
            WHERE regexp_replace(COALESCE(phone,''), '[^0-9]', '', 'g') = %s
            LIMIT 1
            """,
            (phone_norm,)
        )
        row = cursor.fetchone()
        if row:
            return row[0]
    return None


__all__ = [
    "sheets_service",
    "a1_quote",
    "get_sheet_headers",
    "get_sheet_title_by_gid",
    "get_rows_with_headers",
    "norm_phone_digits",
    "norm_linkedin",
    "norm_email",
    "row_fingerprint",
    "find_opportunity_id",
    "find_existing_candidate",
]
