# db.py
# R13: credenciales RDS leídas de variables de entorno (App Runner / .env).
# El fallback al valor actual es TEMPORAL para no causar una caída si la env var
# todavía no está seteada. PASOS PARA CERRARLO:
#   1) Setear RDS_HOST/RDS_PORT/RDS_DB/RDS_USER/RDS_PASSWORD en App Runner.
#   2) ROTAR el password en AWS (RDS) — ya estuvo en el historial de git.
#   3) Borrar el fallback hardcodeado de abajo (dejar os.environ[...] sin default).
#   4) Limpiar el historial de git del password viejo (BFG / git filter-repo).
import os
import psycopg2


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("RDS_HOST", "vintti-hub-db.ctia0ga4u82m.us-east-2.rds.amazonaws.com"),
        port=os.environ.get("RDS_PORT", "5432"),
        database=os.environ.get("RDS_DB", "postgres"),
        user=os.environ.get("RDS_USER", "adminuser"),
        password=os.environ.get("RDS_PASSWORD", "Elementum54!"),  # TEMP fallback — borrar tras rotar (ver arriba)
    )
