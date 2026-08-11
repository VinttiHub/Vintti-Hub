"""Cache compartido, respaldado en Postgres.

Reemplaza a los caches en memoria (`_CACHE = {}` a nivel módulo) que había en los
datasets del dashboard y en el cliente de Apriora.

El problema de los caches en memoria acá: cada proceso tiene el suyo. App Runner
escala hasta 5 instancias y gunicorn corre 3 workers por instancia, o sea hasta
15 copias del mismo cache, cada una con su propio TTL corriendo por su lado. El
síntoma visible era que refrescabas el dashboard dos veces y podías ver números
distintos, según en qué worker cayeras. Nada se calculaba mal: veías dos fotos
tomadas en momentos distintos.

Guardándolo en Postgres, los 15 procesos ven exactamente el mismo valor y el
mismo vencimiento.

Regla de oro: **un cache nunca puede tumbar la app**. Todo acá falla en silencio.
Si la base no responde o la tabla no existe, `get()` devuelve "miss" y el que
llama hace el trabajo real, igual que si el cache estuviera vacío.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Tuple

from psycopg2.extras import Json

from db import get_connection

log = logging.getLogger(__name__)

_TABLE_READY = False
_TABLE_LOCK = threading.Lock()

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS app_cache (
    cache_key  TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

# Para que el borrado de vencidos no haga scan completo.
_INDEX_SQL = "CREATE INDEX IF NOT EXISTS app_cache_expires_at_idx ON app_cache (expires_at)"


def _ensure_table(cur) -> None:
    """Crea la tabla la primera vez, reusando el cursor que ya tiene el que llama.

    Se hace perezoso —no al importar el módulo— para no sumar una ida y vuelta a
    RDS en cada arranque en frío de App Runner. Mismo criterio que en
    admin_access.py.
    """
    global _TABLE_READY
    if _TABLE_READY:
        return
    with _TABLE_LOCK:
        if _TABLE_READY:
            return
        cur.execute(_CREATE_SQL)
        cur.execute(_INDEX_SQL)
        _TABLE_READY = True


def get(cache_key: str) -> Tuple[bool, Any]:
    """Devuelve (hit, value). hit=False si no está, venció, o algo falló."""
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                _ensure_table(cur)
                cur.execute(
                    "SELECT value FROM app_cache "
                    "WHERE cache_key = %s AND expires_at > NOW()",
                    (cache_key,),
                )
                row = cur.fetchone()
            conn.commit()
        finally:
            conn.close()
    except Exception:
        log.warning("shared_cache: lectura falló para %s", cache_key, exc_info=True)
        return False, None

    if row is None:
        return False, None
    return True, row[0]


def set(cache_key: str, value: Any, ttl_seconds: int) -> None:
    """Guarda el valor con vencimiento. Si falla, no pasa nada: se recalcula."""
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                _ensure_table(cur)
                cur.execute(
                    """
                    INSERT INTO app_cache (cache_key, value, expires_at, updated_at)
                    VALUES (%s, %s, NOW() + make_interval(secs => %s), NOW())
                    ON CONFLICT (cache_key) DO UPDATE
                       SET value      = EXCLUDED.value,
                           expires_at = EXCLUDED.expires_at,
                           updated_at = NOW()
                    """,
                    (cache_key, Json(value), ttl_seconds),
                )
                # Limpieza oportunista. Sólo corre en un miss (que es raro), y el
                # índice de expires_at la hace barata. Sin esto las claves que
                # llevan fechas se irían acumulando para siempre.
                cur.execute(
                    "DELETE FROM app_cache WHERE expires_at < NOW() - INTERVAL '1 day'"
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        log.warning("shared_cache: escritura falló para %s", cache_key, exc_info=True)


def invalidate(cache_key: str) -> None:
    """Borra una clave. Para los botones de 'Refresh' que fuerzan recálculo."""
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                _ensure_table(cur)
                cur.execute("DELETE FROM app_cache WHERE cache_key = %s", (cache_key,))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        log.warning("shared_cache: invalidación falló para %s", cache_key, exc_info=True)
