"""Esquema de cv_reviews, creado automáticamente al arrancar.

Mismo patrón que backend/admin_access.py: flag de módulo + lock + ensure_*()
idempotente + bootstrap en hilo daemon, así la feature corre local sin que nadie tenga
que acordarse de correr un .sql a mano.

Por qué auto-create y no sólo la migración: en este repo las migraciones manuales se
pierden. Los siete .sql de Hirex y el de reference_feedback_ai están referenciados en
docstrings pero no existen ni en disco ni en git — el esquema vive sólo en RDS. El DDL
igual queda commiteado en backend/sql/20260812_add_cv_reviews.sql como registro.

El DDL de acá y el del .sql tienen que quedar iguales. Si tocás uno, tocá el otro.
"""
from __future__ import annotations

import logging
import threading
import time

from db import get_connection

_TABLE_READY = False
_TABLE_LOCK = threading.Lock()
_LAST_FAILURE_TS = 0.0

# Si el DDL no puede tomar el lock en este tiempo, se rinde. SIN ESTO un solo lock tomado
# por otra conexión (típico: un proceso viejo del dev server que quedó colgado en el mismo
# puerto) cuelga el CREATE TABLE para siempre — y como ensure() se llama al principio de
# cada ruta, cuelga TODOS los endpoints de CV Review sin un solo mensaje de error.
# Mismo criterio que hirex_ai_routes.py / hirex_scorecards_routes.py.
_LOCK_TIMEOUT = "3s"
_STATEMENT_TIMEOUT = "15s"
# Si falló, no reintentar en cada request: sin este freno un DDL roto convierte cada
# request en un intento nuevo de tomar el lock.
_RETRY_AFTER_SECONDS = 60

# Una fila por RONDA. Ver el .sql para el comentario largo de cada decisión.
_CV_REVIEWS_DDL = """
CREATE TABLE IF NOT EXISTS cv_reviews (
    review_id        BIGSERIAL   PRIMARY KEY,
    candidate_id     INTEGER     NOT NULL,
    opportunity_id   INTEGER     NOT NULL,
    round            SMALLINT    NOT NULL CHECK (round >= 1),
    status           TEXT        NOT NULL DEFAULT 'pending'
                                 CHECK (status IN ('pending','approved','rejected','cancelled')),
    recruiter_email  TEXT        NOT NULL,
    hr_lead_email    TEXT,
    sales_lead_email TEXT,
    reviewed_by      TEXT,
    requested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at      TIMESTAMPTZ,
    reject_other     TEXT,
    reviewer_comment TEXT,
    recruiter_note   TEXT,
    ai_score         SMALLINT    CHECK (ai_score BETWEEN 0 AND 100),
    ai_analysis      JSONB,
    ai_analyzed_at   TIMESTAMPTZ,
    ai_error         TEXT,
    resume_snapshot  JSONB       NOT NULL,
    resume_hash      TEXT        NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT cv_reviews_decided_has_reviewer CHECK (
        status IN ('pending','cancelled')
        OR (reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL)
    )
)
"""

_INDEX_DDL = (
    # Los números de ronda son por perfil e inmutables.
    """CREATE UNIQUE INDEX IF NOT EXISTS cv_reviews_round_uq
         ON cv_reviews (candidate_id, opportunity_id, round)""",
    # El índice importante: a lo sumo un review abierto por perfil. Hace imposible en la
    # base el doble submit y la carrera decisión-vs-re-envío.
    """CREATE UNIQUE INDEX IF NOT EXISTS cv_reviews_one_pending_uq
         ON cv_reviews (candidate_id, opportunity_id) WHERE status = 'pending'""",
    """CREATE INDEX IF NOT EXISTS cv_reviews_pending_idx
         ON cv_reviews (requested_at DESC) WHERE status = 'pending'""",
    """CREATE INDEX IF NOT EXISTS cv_reviews_sales_lead_idx
         ON cv_reviews (sales_lead_email, status, requested_at DESC)""",
    """CREATE INDEX IF NOT EXISTS cv_reviews_recruiter_idx
         ON cv_reviews (recruiter_email, requested_at)""",
    """CREATE INDEX IF NOT EXISTS cv_reviews_profile_idx
         ON cv_reviews (candidate_id, opportunity_id, round DESC)""",
)

# Tabla hija en vez de TEXT[]: la métrica titular es "% de perfiles rechazados por la
# razón X", y un JOIN + COUNT lo da bien mientras que unnest() adentro de un agregado es
# de donde sale el doble conteo. Sin CHECK: los códigos viven en utils/cv_review_ai.py
# porque agregar una razón no puede ser una migración.
_REASONS_DDL = """
CREATE TABLE IF NOT EXISTS cv_review_reasons (
    review_id   BIGINT NOT NULL REFERENCES cv_reviews(review_id) ON DELETE CASCADE,
    reason_code TEXT   NOT NULL,
    PRIMARY KEY (review_id, reason_code)
)
"""

_REASONS_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS cv_review_reasons_code_idx ON cv_review_reasons (reason_code)"
)


def ensure_cv_review_tables() -> bool:
    """Crea las tablas si faltan. Devuelve True si están listas.

    NUNCA levanta excepción y NUNCA bloquea indefinidamente: las rutas la llaman al
    principio, así que si esto se cuelga o revienta se cae toda la feature. Cuando no
    puede, devuelve False y quien llama sigue igual — la query que viene después va a dar
    un error de verdad ("relation cv_reviews does not exist"), que es infinitamente más
    útil que un request colgado.
    """
    global _LAST_FAILURE_TS
    if _TABLE_READY:
        return True

    # Freno de reintentos: si acabamos de fallar, no volver a pelear por el lock.
    if _LAST_FAILURE_TS and (time.time() - _LAST_FAILURE_TS) < _RETRY_AFTER_SECONDS:
        return False

    # timeout en el lock del hilo: si otro request ya está corriendo el DDL, no nos
    # quedamos esperándolo (y él ya tiene su propio timeout contra la base).
    if not _TABLE_LOCK.acquire(timeout=5):
        return False
    try:
        if _TABLE_READY:
            return True
        return _ensure_locked()
    finally:
        _TABLE_LOCK.release()


def _tables_exist(cur) -> bool:
    """¿Ya están las dos tablas? to_regclass NO toma ningún lock y es instantáneo.

    Este chequeo es lo que evita el problema de fondo: en este repo el backend LOCAL usa
    las credenciales de RDS de producción (db.py), así que cada laptop que arranca le
    corría DDL a la base real. Varios procesos a la vez (típico: dev servers viejos que
    quedaron dando vueltas) se peleaban el ACCESS EXCLUSIVE sobre cv_reviews, y de ahí
    salían requests colgadas sosteniendo conexiones — con max_connections=81 eso ahoga la
    base para TODOS, producción incluida.

    Con este chequeo, el caso normal (las tablas ya existen) no toma un solo lock.
    """
    cur.execute("SELECT to_regclass('public.cv_reviews'), to_regclass('public.cv_review_reasons')")
    row = cur.fetchone()
    return bool(row and row[0] and row[1])


def _ensure_locked() -> bool:
    global _TABLE_READY, _LAST_FAILURE_TS
    conn = None
    try:
        conn = get_connection()
        # Camino rápido y sin locks: si ya existen, no corremos DDL nunca más.
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '5s'")
            if _tables_exist(cur):
                conn.commit()
                _TABLE_READY = True
                _LAST_FAILURE_TS = 0.0
                return True
        conn.commit()

        with conn.cursor() as cur:
            # Los timeouts van ANTES del DDL y en la misma transacción. SET LOCAL sólo
            # aplica dentro de la transacción, que es justo lo que queremos: no toquetear
            # la sesión que después reusa otro código.
            cur.execute(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'")
            cur.execute(f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT}'")
            cur.execute(_CV_REVIEWS_DDL)
            cur.execute(_REASONS_DDL)
            for stmt in _INDEX_DDL:
                cur.execute(stmt)
            cur.execute(_REASONS_INDEX_DDL)
        conn.commit()
        _TABLE_READY = True
        _LAST_FAILURE_TS = 0.0
        return True
    except Exception:
        _LAST_FAILURE_TS = time.time()
        logging.exception(
            "cv_reviews: no se pudieron asegurar las tablas (¿lock tomado por otra "
            "conexión, o falta permiso de DDL?). Se reintenta en %ss.", _RETRY_AFTER_SECONDS
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


def bootstrap_cv_review_tables_async() -> None:
    """Crea las tablas en segundo plano, fuera del camino de arranque.

    Igual que bootstrap_admin_user_access_table_async(): en un hilo daemon la app queda
    servible al instante y un hipo transitorio de RDS sólo se loguea en vez de tumbar el
    boot. Cualquier request que llegue antes de que el hilo termine las crea por su
    cuenta, porque ensure_cv_review_tables() es idempotente y con lock.
    """

    def _run() -> None:
        # ensure_cv_review_tables() ya no levanta excepción; el try queda como red por si
        # get_connection explota antes de entrar.
        try:
            if ensure_cv_review_tables():
                logging.info("cv_reviews: tablas listas")
        except Exception:
            logging.exception("Bootstrap en background de cv_reviews falló")

    threading.Thread(
        target=_run, name="bootstrap-cv-reviews", daemon=True
    ).start()
