import json
import re
from typing import List, Optional

from utils import services


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
        url = services.s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': services.S3_BUCKET, 'Key': key},
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
        url = services.s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': services.S3_BUCKET, 'Key': key},
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
    resp = services.s3_client.list_objects_v2(Bucket=services.S3_BUCKET, Prefix=prefix)
    for obj in resp.get('Contents', []):
        key = obj['Key']
        url = services.s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': services.S3_BUCKET,
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


def _normalize_tests_documents(raw_value):
    if not raw_value:
        return []
    data = raw_value
    if isinstance(raw_value, str):
        try:
            data = json.loads(raw_value)
        except Exception:
            data = []
    if not isinstance(data, list):
        return []
    normalized = []
    for item in data:
        if isinstance(item, str):
            normalized.append({
                "key": item,
                "name": item.split('/')[-1],
            })
        elif isinstance(item, dict) and item.get("key"):
            normalized.append({
                "key": item["key"],
                "name": item.get("name") or item["key"].split('/')[-1],
                "content_type": item.get("content_type"),
                "size": item.get("size"),
                "uploaded_at": item.get("uploaded_at"),
                "uploaded_by": item.get("uploaded_by"),
            })
    return normalized


def get_candidate_tests_documents(cursor, candidate_id: int):
    cursor.execute("SELECT tests_documents_s3 FROM candidates WHERE candidate_id = %s", (candidate_id,))
    row = cursor.fetchone()
    raw_value = row[0] if row else None
    return _normalize_tests_documents(raw_value)


def set_candidate_tests_documents(cursor, candidate_id: int, documents):
    cursor.execute(
        "UPDATE candidates SET tests_documents_s3 = %s WHERE candidate_id = %s",
        (json.dumps(documents), candidate_id)
    )


def make_candidate_tests_payload(documents, expires=604800):
    payload = []
    for doc in documents:
        key = doc.get("key") if isinstance(doc, dict) else doc
        if not key:
            continue
        name = (doc.get("name") if isinstance(doc, dict) else None) or key.split('/')[-1]
        url = services.s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': services.S3_BUCKET, 'Key': key},
            ExpiresIn=expires
        )
        payload.append({
            "key": key,
            "name": name,
            "url": url,
            "content_type": doc.get("content_type") if isinstance(doc, dict) else None,
            "size": doc.get("size") if isinstance(doc, dict) else None,
            "uploaded_at": doc.get("uploaded_at") if isinstance(doc, dict) else None,
            "uploaded_by": doc.get("uploaded_by") if isinstance(doc, dict) else None,
        })
    return payload


__all__ = [
    "get_account_pdf_keys",
    "set_account_pdf_keys",
    "make_account_pdf_payload",
    "get_cv_keys",
    "set_cv_keys",
    "make_cv_payload",
    "list_s3_with_prefix",
    "get_candidate_tests_documents",
    "set_candidate_tests_documents",
    "make_candidate_tests_payload",
]
