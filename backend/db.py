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
    )
