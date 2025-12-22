import json
import re
from typing import List, Optional

from utils.services import S3_BUCKET, s3_client


def _extract_account_pdf_key(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    match = re.search(r"accounts%2F(.+?\.pdf)", value)
    if not match:
        match = re.search(r"accounts/(.+?\.pdf)", value)
    return f"accounts/{match.group(1)}" if match else None


def get_account_pdf_keys(cursor, account_id):
    cursor.execute("SELECT pdf_s3 FROM account WHERE account_id = %s", (account_id,))
    row = cursor.fetchone()
    keys = []
    if row and row[0]:
        raw = row[0]
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                keys = [k for k in data if isinstance(k, str)]
            elif isinstance(data, str):
                raise ValueError("legacy string")
        except Exception:
            key = _extract_account_pdf_key(raw)
            if key:
                keys = [key]
    return keys


def set_account_pdf_keys(cursor, account_id, keys):
    cursor.execute(
        "UPDATE account SET pdf_s3 = %s WHERE account_id = %s",
        (json.dumps(keys), account_id)
    )


def make_account_pdf_payload(keys):
    pdfs = []
    for key in keys:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET, 'Key': key},
            ExpiresIn=604800
        )
        pdfs.append({
            "key": key,
            "url": url,
            "name": key.split('/')[-1]
        })
    return pdfs


def _extract_cv_key_from_url(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    match = re.search(r"cvs%2F(.+?\.(?:pdf|png|jpg|jpeg|webp))", value, re.IGNORECASE)
    if not match:
        match = re.search(r"cvs/(.+?\.(?:pdf|png|jpg|jpeg|webp))", value, re.IGNORECASE)
    return f"cvs/{match.group(1)}" if match else None


def _ensure_resume_row(cursor, candidate_id: int):
    cursor.execute("SELECT 1 FROM resume WHERE candidate_id = %s", (candidate_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO resume (candidate_id) VALUES (%s)", (candidate_id,))


def get_cv_keys(cursor, candidate_id: int):
    cursor.execute("SELECT cv_pdf_s3 FROM resume WHERE candidate_id = %s", (candidate_id,))
    row = cursor.fetchone()
    keys: List[str] = []
    if row and row[0]:
        raw = row[0]
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                keys = [k for k in data if isinstance(k, str)]
            elif isinstance(data, str):
                raise ValueError("legacy string")
        except Exception:
            key = _extract_cv_key_from_url(raw)
            if key:
                keys = [key]
    return keys


def set_cv_keys(cursor, candidate_id: int, keys: List[str]):
    _ensure_resume_row(cursor, candidate_id)
    cursor.execute(
        "UPDATE resume SET cv_pdf_s3 = %s WHERE candidate_id = %s",
        (json.dumps(keys), candidate_id)
    )


def make_cv_payload(keys: List[str]):
    items = []
    for key in keys:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET, 'Key': key},
            ExpiresIn=604800
        )
        items.append({
            "key": key,
            "url": url,
            "name": key.split('/')[-1]
        })
    return items


def list_s3_with_prefix(prefix, expires=3600):
    out = []
    resp = s3_client.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
    for obj in resp.get('Contents', []):
        key = obj['Key']
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': S3_BUCKET,
                'Key': key,
                'ResponseContentType': 'application/pdf',
                'ResponseContentDisposition': 'inline; filename="resignation-letter.pdf"'
            },
            ExpiresIn=expires
        )
        out.append({
            "name": key.split('/')[-1],
            "key": key,
            "url": url
        })
    return out


__all__ = [
    "get_account_pdf_keys",
    "set_account_pdf_keys",
    "make_account_pdf_payload",
    "get_cv_keys",
    "set_cv_keys",
    "make_cv_payload",
    "list_s3_with_prefix",
]
