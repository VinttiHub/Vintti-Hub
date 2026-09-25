"""Esquema de jd_reviews, creado automáticamente al arrancar.

Calco de backend/cv_review_store.py: flag de módulo + lock + ensure_*() idempotente +
bootstrap en hilo daemon, así la feature corre local sin que nadie tenga que acordarse de
correr un .sql a mano. Mismos timeouts y mismo freno de reintentos, por las mismas razones
(el backend local usa las credenciales de RDS de producción y un DDL colgado ahoga la base).

Las tablas que se agreguen después van en una rama de migración como en cv_review_store,
NO en _tables_exist(): si no, producción nunca las crea.
"""
from __future__ import annotations

import logging
import threading
import time

from db import get_connection

_TABLE_READY = False
_TABLE_LOCK = threading.Lock()
_LAST_FAILURE_TS = 0.0

_LOCK_TIMEOUT = "3s"
_STATEMENT_TIMEOUT = "15s"
_RETRY_AFTER_SECONDS = 60

# Una fila por ronda. No hay "rejected": una JD no se descarta, se corrige — el sales lead
# aprueba o pide cambios.
_JD_REVIEWS_DDL = """
CREATE TABLE IF NOT EXISTS jd_reviews (
    review_id            BIGSERIAL PRIMARY KEY,
    opportunity_id       INTEGER      NOT NULL,
    round                SMALLINT     NOT NULL CHECK (round >= 1),
    status               TEXT         NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'approved', 'changes_requested', 'cancelled')),
    recruiter_email      TEXT         NOT NULL,
    hr_lead_email        TEXT,
    sales_lead_email     TEXT,
    reviewed_by          TEXT,
    requested_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    reviewed_at          TIMESTAMPTZ,
    reviewer_comment     TEXT,
    recruiter_note       TEXT,
    ai_score             SMALLINT CHECK (ai_score BETWEEN 0 AND 100),
    ai_analysis          JSONB,
    ai_analyzed_at       TIMESTAMPTZ,
    ai_error             TEXT,
    -- La JD tal cual se envió: el sales lead decide sobre ESA versión, no sobre la que
    -- la recruiter siga editando mientras tanto.
    jd_snapshot          TEXT         NOT NULL,
    jd_hash              TEXT         NOT NULL,
    -- Los transcripts de Grain congelados al scorear. Re-scorear sobre esto da lo mismo
    -- aunque Grain esté caído o el link se haya cambiado.
    transcript_snapshot  JSONB,
    checklist_done       BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT jd_reviews_decided_has_reviewer CHECK (
        status IN ('pending', 'cancelled')
        OR (reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL)
    )
)
"""

_INDEX_DDL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS jd_reviews_round_uq "
    "ON jd_reviews (opportunity_id, round)",
    # Una sola ronda abierta por vacante: el doble click o dos pestañas no crean dos.
    "CREATE UNIQUE INDEX IF NOT EXISTS jd_reviews_one_pending_uq "
    "ON jd_reviews (opportunity_id) WHERE status = 'pending'",
    "CREATE INDEX IF NOT EXISTS jd_reviews_pending_idx "
    "ON jd_reviews (requested_at) WHERE status = 'pending'",
    "CREATE INDEX IF NOT EXISTS jd_reviews_sales_lead_idx "
    "ON jd_reviews (LOWER(TRIM(sales_lead_email)))",
    "CREATE INDEX IF NOT EXISTS jd_reviews_recruiter_idx "
    "ON jd_reviews (LOWER(TRIM(recruiter_email)))",
)

# Tildar un ítem = "este defecto está". Mismo contrato que cv_review_checklist.
_CHECKLIST_DDL = """
CREATE TABLE IF NOT EXISTS jd_review_checklist (
    review_id  BIGINT NOT NULL REFERENCES jd_reviews(review_id) ON DELETE CASCADE,
    item_code  TEXT   NOT NULL,
    PRIMARY KEY (review_id, item_code)
)
"""


# La lista de puntos que el extractor sacó de las reuniones, guardada para reusarla: sin esto
# cada re-run y cada ronda volvía a extraer y el score se movía ±10 por azar (opp 844: 68 y 80
# con la misma JD). Clave = vacante + huella de los transcripts + versión del extractor.
_FACTS_DDL = """
CREATE TABLE IF NOT EXISTS jd_review_facts (
    opportunity_id  INTEGER     NOT NULL,
    facts_key       TEXT        NOT NULL,
    facts           JSONB       NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Quién apretó "Rebuild the list of points" y cuándo. NULL = la lista automática del primer
    -- análisis. Queda a la vista en el drawer: reconstruir cambia la vara de todas las rondas.
    rebuilt_by      TEXT,
    rebuilt_at      TIMESTAMPTZ,
    PRIMARY KEY (opportunity_id, facts_key)
)
"""
_FACTS_REBUILT_COLS = (
    "ALTER TABLE jd_review_facts ADD COLUMN IF NOT EXISTS rebuilt_by TEXT",
    "ALTER TABLE jd_review_facts ADD COLUMN IF NOT EXISTS rebuilt_at TIMESTAMPTZ",
)


def ensure_jd_review_tables() -> bool:
    """Crea las tablas si faltan. Devuelve True si están listas.

    NUNCA levanta excepción y NUNCA bloquea indefinidamente (ver ensure_cv_review_tables).
    """
    global _LAST_FAILURE_TS
    if _TABLE_READY:
        return True
    if _LAST_FAILURE_TS and (time.time() - _LAST_FAILURE_TS) < _RETRY_AFTER_SECONDS:
        return False
    if not _TABLE_LOCK.acquire(timeout=5):
        return False
    try:
        if _TABLE_READY:
            return True
        return _ensure_locked()
    finally:
        _TABLE_LOCK.release()


def _tables_exist(cur) -> bool:
    """to_regclass no toma ningún lock: el caso normal (ya existen) no corre DDL."""
    cur.execute("SELECT to_regclass('public.jd_reviews'), to_regclass('public.jd_review_checklist')")
    row = cur.fetchone()
    return bool(row and row[0] and row[1])


def _ensure_locked() -> bool:
    global _TABLE_READY, _LAST_FAILURE_TS
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '5s'")
            if _tables_exist(cur):
                # Rama de migración: lo que llegó después de las dos primeras tablas va acá, o
                # producción (donde _tables_exist ya da True) no lo crea nunca.
                cur.execute("SELECT to_regclass('public.jd_review_facts') IS NOT NULL")
                facts_ok = bool(cur.fetchone()[0])
                # Catálogo puro, sin locks: ¿la tabla ya tiene las columnas de rebuild?
                cur.execute("""SELECT COUNT(*) FROM information_schema.columns
                                WHERE table_schema = 'public' AND table_name = 'jd_review_facts'
                                  AND column_name IN ('rebuilt_by', 'rebuilt_at')""")
                rebuilt_ok = cur.fetchone()[0] == 2
                conn.commit()
                if not facts_ok or not rebuilt_ok:
                    with conn.cursor() as c2:
                        c2.execute(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'")
                        c2.execute(f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT}'")
                        c2.execute(_FACTS_DDL)
                        for stmt in _FACTS_REBUILT_COLS:
                            c2.execute(stmt)
                    conn.commit()
                    logging.info("jd_reviews: jd_review_facts creada/migrada")
                _TABLE_READY = True
                _LAST_FAILURE_TS = 0.0
                return True
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'")
            cur.execute(f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT}'")
            cur.execute(_JD_REVIEWS_DDL)
            for stmt in _INDEX_DDL:
                cur.execute(stmt)
            cur.execute(_CHECKLIST_DDL)
            cur.execute(_FACTS_DDL)
        conn.commit()
        _TABLE_READY = True
        _LAST_FAILURE_TS = 0.0
        logging.info("jd_reviews: tablas creadas")
        return True
    except Exception:
        _LAST_FAILURE_TS = time.time()
        logging.exception(
            "jd_reviews: no se pudieron asegurar las tablas. Se reintenta en %ss.",
            _RETRY_AFTER_SECONDS,
        )
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def bootstrap_jd_review_tables_async() -> None:
    """Crea las tablas en segundo plano, fuera del camino de arranque."""

    def _run() -> None:
        try:
            if ensure_jd_review_tables():
                logging.info("jd_reviews: tablas listas")
        except Exception:
            logging.exception("Bootstrap en background de jd_reviews falló")

    threading.Thread(target=_run, name="bootstrap-jd-reviews", daemon=True).start()
