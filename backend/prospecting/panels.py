"""Paneles de métricas de BDRs (sección «Paneles» de prospecting.html).

Cada panel devuelve FILAS a nivel registro, no agregados: el front agrupa por período y
por persona, así el número de una barra y su detalle salen de las mismas filas por
construcción. Se calcula en vivo sobre las tablas del Hub (sin caché).

Para sumar un panel: una función `(cur, date_from, date_to) -> dict` en `PANELS`.
"""
from __future__ import annotations

from datetime import date

# --------------------------------------------------------------------------- #
# SQLs by BDR — réplica del reporte de HubSpot (filtros de la owner, 2026-11-06)
# --------------------------------------------------------------------------- #
# Scheduled By que el reporte deja afuera: no son BDRs (AEs / dirección).
EXCLUDED_SCHEDULERS = (
    "bahia@vintti.com",             # Bahía Larcamón
    "agustin@vintti.com",           # Agustín Morrone
    "mariano@vintti.com",           # Mariano Salinas
    "valentinacadirola@vintti.com", # Valentina Cadirola
)
# Segmento «Internal Team» de HubSpot: contactos del propio equipo.
INTERNAL_DOMAINS = ("vintti.com",)
# El reporte de HubSpot pedía además «Meeting Date & Time después del 01/01/2026»: acá es
# «Meeting Date & Time conocido» y el corte lo da Desde/Hasta del panel (2026-11-06). 2026 da
# igual; sólo aparecen los 2 SQLs de dic-2025. «SQL Date» no existe antes del 25-11-2025.


def _person_name_sql(col: str) -> str:
    """Nombre de una persona por email: users (cualquier estado) → prospect_people → email."""
    return f"""COALESCE(
        (SELECT u.user_name FROM users u WHERE LOWER(TRIM(u.email_vintti)) = {col} LIMIT 1),
        (SELECT pp.name FROM prospect_people pp WHERE pp.email = {col}),
        INITCAP(SPLIT_PART({col}, '@', 1)))"""


def sqls_by_bdr(cur, date_from: date | None, date_to: date | None) -> dict:
    """Contactos distintos con negocio en SQL, por SQL Date (Deal) y Scheduled By.

    Los 5 filtros del reporte de HubSpot:
      1. Scheduled By conocido.
      2. Scheduled By fuera de EXCLUDED_SCHEDULERS.
      3. Contacto fuera del segmento Internal Team (email de INTERNAL_DOMAINS).
      4. Meeting Date & Time conocido (HubSpot: > 01-01-2026; acá lo corta Desde/Hasta).
      5. Algún negocio asociado con SQL Date (Deal): su fecha es la dimensión.
    Un contacto con varios negocios cuenta una vez por SQL Date distinta (como HubSpot)."""
    where, params = [], []
    if date_from:
        where.append("(d.props->>'sql_date')::date >= %s")
        params.append(date_from)
    if date_to:
        where.append("(d.props->>'sql_date')::date <= %s")
        params.append(date_to)
    extra = "".join(" AND " + w for w in where)
    domains = " AND ".join("ct.email NOT ILIKE %s" for _ in INTERNAL_DOMAINS)
    cur.execute(
        f"""
        WITH base AS (
            SELECT DISTINCT ON (ct.id, (d.props->>'sql_date')::date)
                   ct.id AS contact_id,
                   NULLIF(TRIM(CONCAT_WS(' ', ct.first_name, ct.last_name)), '') AS contact_name,
                   ct.email,
                   ct.company_id,
                   c.name AS company_name,
                   d.id AS deal_id,
                   d.name AS deal_name,
                   d.pipeline_key, d.stage_key,
                   (d.props->>'sql_date')::date AS sql_date,
                   ct.props->>'meeting_datetime' AS meeting_datetime,
                   LOWER(ct.props->>'scheduled_by') AS scheduled_by
              FROM prospect_contacts ct
              JOIN prospect_deal_contacts dc ON dc.contact_id = ct.id
              JOIN prospect_deals d ON d.id = dc.deal_id
              LEFT JOIN prospect_companies c ON c.id = ct.company_id
             WHERE NOT ct.is_dummy AND NOT d.is_dummy
               AND NULLIF(ct.props->>'scheduled_by', '') IS NOT NULL
               AND LOWER(ct.props->>'scheduled_by') <> ALL(%s)
               AND ({domains} OR ct.email IS NULL)
               AND NULLIF(ct.props->>'meeting_datetime', '') IS NOT NULL
               AND NULLIF(d.props->>'sql_date', '') IS NOT NULL
               {extra}
             ORDER BY ct.id, (d.props->>'sql_date')::date, d.id
        )
        SELECT b.*, {_person_name_sql('b.scheduled_by')} AS scheduled_by_name,
               st.label AS stage_label
          FROM base b
          LEFT JOIN prospect_deal_stages st ON st.pipeline_key = b.pipeline_key AND st.stage_key = b.stage_key
         ORDER BY b.sql_date, b.contact_id
        """,
        [list(EXCLUDED_SCHEDULERS), *[f"%@{d}" for d in INTERNAL_DOMAINS], *params],
    )
    rows = []
    for r in cur.fetchall():
        r = dict(r)
        r["sql_date"] = r["sql_date"].isoformat() if r["sql_date"] else None
        r.pop("pipeline_key", None)
        r.pop("stage_key", None)
        rows.append(r)
    return {
        "rows": rows,
        "definition": {
            "excluded_schedulers": list(EXCLUDED_SCHEDULERS),
            "internal_domains": list(INTERNAL_DOMAINS),
        },
    }


PANELS = {
    "sqls_by_bdr": sqls_by_bdr,
}
