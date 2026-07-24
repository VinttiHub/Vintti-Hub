"""Hirex ATS — self-bootstrapping schema.

Every Hirex migration is idempotent (CREATE TABLE IF NOT EXISTS ...), so we run
them all on app startup. This means Hirex works out of the box locally and in
prod with NO manual migration step — mirrors admin_access.ensure_* pattern.

Add each new backend/sql/<date>_add_hirex_*.sql file to _SQL_FILES below.
"""
import logging
import os

from db import get_connection

_SQL_FILES = [
    "20260724_add_hirex_jobs.sql",
    "20260724_add_hirex_pipeline.sql",
    "20260724_add_hirex_cv_ai.sql",
    "20260724_add_hirex_scorecards.sql",
]

_SCHEMA_READY = False


def ensure_hirex_tables():
    """Apply all Hirex DDL files idempotently. Safe to call repeatedly."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    sql_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sql")
    conn = get_connection()
    try:
        conn.autocommit = True  # each file carries its own BEGIN; ... COMMIT;
        with conn.cursor() as cur:
            for filename in _SQL_FILES:
                path = os.path.join(sql_dir, filename)
                with open(path, "r", encoding="utf-8") as fh:
                    cur.execute(fh.read())
        _SCHEMA_READY = True
        logging.info("Hirex tables ensured (%d migration files).", len(_SQL_FILES))
    except Exception:
        logging.exception("Failed to ensure Hirex tables")
        raise
    finally:
        conn.close()
