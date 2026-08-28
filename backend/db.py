# db.py
# R13: credenciales RDS desde variables de entorno (App Runner en prod; backend/.env
# en local). El password NO tiene fallback hardcodeado — el secreto vive solo en la
# env var. Host/puerto/usuario/db (no secretos) mantienen un default por comodidad.
# El password viejo ya fue ROTADO (2026-06-25); quedó en el historial de git pero
# muerto. Pendiente opcional: limpiar el historial (BFG / git filter-repo).
import os
import psycopg2


def get_connection():
    password = os.environ.get("RDS_PASSWORD")
    if not password:
        raise RuntimeError(
            "RDS_PASSWORD no está seteada. Configurala en App Runner (prod) "
            "o en backend/.env (local)."
        )
    return psycopg2.connect(
        host=os.environ.get("RDS_HOST", "vintti-hub-db.ctia0ga4u82m.us-east-2.rds.amazonaws.com"),
        port=os.environ.get("RDS_PORT", "5432"),
        database=os.environ.get("RDS_DB", "postgres"),
        user=os.environ.get("RDS_USER", "adminuser"),
        password=password,
        # Sin esto, un problema de red hacia RDS deja la request colgada hasta que
        # se rinde el navegador (~30-60s): el front muestra spinner eterno y no hay
        # error en los logs. Los statement_timeout/lock_timeout de las rutas no
        # cubren este caso porque corren DESPUÉS de tener la conexión.
        connect_timeout=int(os.environ.get("RDS_CONNECT_TIMEOUT", "10")),
    )


# ---------------------------------------------------------------------------
# users.color (color de equipo: azul / rojo / amarillo)
# ---------------------------------------------------------------------------
# La columna la crea backend/sql/20260828_add_user_color.sql, que se corre a mano.
# NO hacemos el "ALTER TABLE ... ADD COLUMN IF NOT EXISTS" dentro de las rutas de
# lectura: un ADD COLUMN toma ACCESS EXCLUSIVE sobre `users`, y hecho en cada
# request dos llamadas concurrentes terminan deadlockeándose contra
# admin_user_access (una tiene users y quiere aua, la otra al revés).
# Esto sólo consulta el catálogo —lectura barata— y cachea el resultado por proceso.
_USERS_HAS_COLOR = None


def users_has_color(cur) -> bool:
    """True si `users.color` ya existe. Se cachea por proceso."""
    global _USERS_HAS_COLOR
    if _USERS_HAS_COLOR is None:
        cur.execute(
            """
            SELECT 1
              FROM information_schema.columns
             WHERE table_name = 'users' AND column_name = 'color'
             LIMIT 1
            """
        )
        _USERS_HAS_COLOR = cur.fetchone() is not None
    return _USERS_HAS_COLOR


def mark_users_color_present() -> None:
    """Invalida el cache tras crear la columna (lo usa el path de admin)."""
    global _USERS_HAS_COLOR
    _USERS_HAS_COLOR = True
