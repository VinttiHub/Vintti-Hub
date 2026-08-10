from __future__ import annotations

import logging
import threading
from typing import Optional, Set

from db import get_connection

ADMIN_ALLOWED_EMAILS: Set[str] = {
    "agustin@vintti.com",
    "lara@vintti.com",
    "jazmin@vintti.com",
    "agostina@vintti.com",
    "bahia@vintti.com",
    "mariano@vintti.com",
    "lucia@vintti.com",
    "camila@vintti.com",
    "mia@vintti.com",
}

_TABLE_READY = False
_TABLE_LOCK = threading.Lock()


def normalize_email(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def ensure_admin_user_access_table() -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return

    with _TABLE_LOCK:
        if _TABLE_READY:
            return
        _ensure_admin_user_access_table_locked()


def _ensure_admin_user_access_table_locked() -> None:
    global _TABLE_READY
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


def bootstrap_admin_user_access_table_async() -> None:
    """Crea la tabla en segundo plano, fuera del camino de arranque.

    Antes esto se llamaba en el top-level del módulo, o sea que importar
    admin_access abría una conexión a RDS y corría un CREATE TABLE IF NOT EXISTS
    antes de que existiera la app Flask. Dos problemas: sumaba una ida y vuelta a
    la base a cada arranque en frío de App Runner, y como la función hace `raise`
    ante un error, un hipo transitorio de RDS tumbaba el boot entero del backend.

    En un hilo daemon la app queda servible al instante y un fallo sólo se loguea.
    Se mantiene la creación automática (nada de migraciones a mano). Cualquier
    request que llegue antes de que termine el hilo igual la crea por su cuenta,
    porque ensure_admin_user_access_table() sigue siendo idempotente y con lock.
    """

    def _run() -> None:
        try:
            ensure_admin_user_access_table()
        except Exception:
            logging.exception("Bootstrap en background de admin_user_access falló")

    threading.Thread(
        target=_run, name="bootstrap-admin-user-access", daemon=True
    ).start()
