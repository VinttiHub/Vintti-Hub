from __future__ import annotations

import logging
from typing import Optional, Set

from db import get_connection

ADMIN_ALLOWED_EMAILS: Set[str] = {
    "agustin@vintti.com",
    "lara@vintti.com",
    "bahia@vintti.com",
    "agostina@vintti.com",
    "jazmin@vintti.com",
}

_TABLE_READY = False


def normalize_email(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def ensure_admin_user_access_table() -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_user_access (
                    user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_by_email TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        conn.commit()
        _TABLE_READY = True
    except Exception:
        logging.exception("Failed to ensure admin_user_access table")
        raise
    finally:
        conn.close()


def is_allowed_admin(email: Optional[str]) -> bool:
    return normalize_email(email) in ADMIN_ALLOWED_EMAILS


ensure_admin_user_access_table()
