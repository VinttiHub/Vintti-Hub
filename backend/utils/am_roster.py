"""Quien es Account Manager. Fuente unica para TODO el backend: `users.role`.

Existe como modulo neutro (y no adentro de `dashboards/`) porque lo necesitan dos
mundos: los datasets del dashboard y el PATCH de `account`. Tenerlo en dos lados fue
exactamente el problema que hubo hasta el 2026-09-21, con 'lara@vintti.com' escrito a
mano en 30 datasets y en 2 lugares del JS.

Cacheado 5 min por proceso: es una consulta de una fila que se pregunta muy seguido.
Override por entorno: `DASHBOARD_AM_EMAILS` (emails separados por coma).
"""
from __future__ import annotations

import os
import time

from db import get_connection


# Ex-AMs. Sus opps y sus cuentas historicas siguen existiendo, pero el rol ya no es de
# ellos. Se usa para dos cosas: `am_history()` en los datasets, y para detectar que un
# front cacheado esta mandando al AM viejo (ver `normalize_account_manager`).
PAST_AMS = ("lara@vintti.com",)

# Si la consulta falla o `users` no tiene a nadie con rol AM, una tupla vacia se
# renderiza como `IN ()`, que es error de sintaxis en Postgres, y tumbaria ~20 cards.
FALLBACK = ("pilar@vintti.com",)

ROLE_LABELS = ("AM", "ACCOUNT MANAGER")

_TTL_SECONDS = 300
_cache: dict = {"at": 0.0, "emails": None}

_SQL = """
    SELECT LOWER(TRIM(u.email_vintti)) AS email
    FROM users u
    LEFT JOIN admin_user_access aua ON aua.user_id = u.user_id
    WHERE UPPER(TRIM(COALESCE(u.role, ''))) IN %(roles)s
      AND COALESCE(aua.is_active, TRUE)
      AND NULLIF(TRIM(u.email_vintti), '') IS NOT NULL
    ORDER BY 1
"""


def _from_env() -> tuple[str, ...]:
    raw = os.environ.get("DASHBOARD_AM_EMAILS", "")
    return tuple(p.strip().lower() for p in raw.split(",") if p.strip())


def current_ams() -> tuple[str, ...]:
    """Los AM de hoy, segun `users.role`."""
    env = _from_env()
    if env:
        return env

    now = time.time()
    cached = _cache.get("emails")
    if cached is not None and (now - _cache.get("at", 0.0)) < _TTL_SECONDS:
        return cached

    emails: tuple[str, ...] = ()
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(_SQL, {"roles": ROLE_LABELS})
            emails = tuple(r[0] for r in cur.fetchall() if r and r[0])
    except Exception:
        emails = ()
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    emails = emails or FALLBACK
    _cache["emails"] = emails
    _cache["at"] = now
    return emails


def am_history() -> tuple[str, ...]:
    """Los AM de hoy + los que lo fueron. Para columnas historicas."""
    return tuple(dict.fromkeys(current_ams() + PAST_AMS))


def normalize_account_manager(value):
    """Reescribe al AM vigente si llega el email de un AM **retirado**.

    El 2026-09-21 se movieron 123 cuentas de Lara a Pilar y a las pocas horas 80 habian
    vuelto a Lara, todas `Active Client`. La causa: `docs/` se sirve por GitHub Pages, o
    sea que el `crm.js` que corre en el navegador es el DEPLOYADO, y ese todavia tiene
    `desiredManager = 'lara@vintti.com'` a mano. Cada vez que alguien abria el CRM,
    `assignManagersFromStatus()` pateaba un PATCH por cada Active Client y deshacia la
    migracion.

    Arreglar solo el JS no alcanzaba: una pestania vieja o un navegador con el archivo
    cacheado sigue mandando el email viejo durante dias. Con este freno el servidor es
    la fuente de verdad y el sistema **se arregla solo**: el PATCH del front viejo entra
    diciendo Lara y sale escribiendo Pilar.

    Es deliberadamente angosto: solo toca emails que estan en `PAST_AMS` y que ya no son
    AM. Asignar a mano a Mariano o a cualquier otro no se toca.
    """
    email = (value or "").strip().lower()
    if not email:
        return value
    if email not in PAST_AMS:
        return value
    vigentes = current_ams()
    if email in vigentes or not vigentes:
        return value
    return vigentes[0]
