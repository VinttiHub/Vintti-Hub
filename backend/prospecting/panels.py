"""Paneles de métricas de BDRs (sección «Paneles» de prospecting.html).

Cada panel devuelve FILAS a nivel registro, no agregados: el front agrupa por período y
por persona, así el número de una barra y su detalle salen de las mismas filas por
construcción. Se calcula en vivo sobre las tablas del Hub (sin caché).

Para sumar un panel: una función `(cur, date_from, date_to) -> dict` en `PANELS`.
"""
from __future__ import annotations

from datetime import date

from prospecting.constants import NOT_ICP_REASONS

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
# Equipos con su propio panel: «Scheduled By es cualquiera de …» del reporte de HubSpot.
TEAMS = {
    # «SQLs by BDR - VinttiKids» (2026-11-06)
    "vinttikids": (
        "abril@vintti.com",       # Abril Acosta
        "victoria@vintti.com",    # Victoria Frech
        "valeria@vintti.com",     # Valeria Arias
        "catalina@vintti.com",    # Catalina Berardi
        "joel@vintti.com",        # Joel Salomone
        "bartolome@vintti.com",   # Bartolomé Rossi
        "marcos@vintti.com",      # Marcos Gonzalez del Solar
    ),
    # «SQLs by BDR - NextGen» (2026-11-06)
    "nextgen": (
        "lunaberto@vintti.com",        # Luna Berto
        "santiago.botana@vintti.com",  # Santiago Botana
        "matias@vintti.com",           # Matias Lopez Ferrando
        "agustina@vintti.com",         # Agustina Valentini
        "agustin.penna@vintti.com",    # Agustin Penna
        "magali@vintti.com",           # Magalí Müller
        "matias.larran@vintti.com",    # Matias Larran
        "luca.garegnani@vintti.com",   # Luca Garegnani
    ),
}
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


def sqls_by_bdr(cur, date_from: date | None, date_to: date | None, team: str | None = None) -> dict:
    """Contactos distintos con negocio en SQL, por SQL Date (Deal) y Scheduled By.

    Los 5 filtros del reporte de HubSpot:
      1. Scheduled By conocido.
      2. Scheduled By fuera de EXCLUDED_SCHEDULERS.
      3. Contacto fuera del segmento Internal Team (email de INTERNAL_DOMAINS).
      4. Meeting Date & Time conocido (HubSpot: > 01-01-2026; acá lo corta Desde/Hasta).
      5. Algún negocio asociado con SQL Date (Deal): su fecha es la dimensión.
    Un contacto con varios negocios cuenta una vez por SQL Date distinta (como HubSpot).
    Con `team`, además Scheduled By tiene que ser de ese equipo (TEAMS)."""
    where, params = [], []
    members = list(TEAMS[team]) if team else None
    if members:
        where.append("LOWER(ct.props->>'scheduled_by') = ANY(%s)")
        params.append(members)
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
        r["date"] = r["sql_date"]  # la dimensión: el front agrupa siempre por `date`
        r.pop("pipeline_key", None)
        r.pop("stage_key", None)
        rows.append(r)
    return {
        "rows": rows,
        "people_order": people_order(cur),
        "definition": {
            "excluded_schedulers": list(EXCLUDED_SCHEDULERS),
            "internal_domains": list(INTERNAL_DOMAINS),
            "team": _names(cur, members) if members else None,
        },
    }


def intro_calls(cur, date_from: date | None, date_to: date | None, team: str | None = None) -> dict:
    """Intro calls: contactos por Date of Meeting Scheduled y Scheduled By (2026-11-07).

    Los filtros del reporte «Intro calls by BDR» de HubSpot:
      1. Scheduled By conocido y fuera de EXCLUDED_SCHEDULERS.
      2. Contacto fuera del segmento Internal Team (email de INTERNAL_DOMAINS).
      3. Meeting Date & Time conocido (HubSpot: dentro de 2026; acá lo corta Desde/Hasta).
      4. Date of Meeting Scheduled conocido: es la dimensión.
    Sin negocios: un contacto, una intro call. Con `team`, Scheduled By ∈ TEAMS[team]."""
    where, params = [], []
    members = list(TEAMS[team]) if team else None
    if members:
        where.append("LOWER(ct.props->>'scheduled_by') = ANY(%s)")
        params.append(members)
    if date_from:
        where.append("(ct.props->>'date_of_meeting_scheduled')::date >= %s")
        params.append(date_from)
    if date_to:
        where.append("(ct.props->>'date_of_meeting_scheduled')::date <= %s")
        params.append(date_to)
    extra = "".join(" AND " + w for w in where)
    domains = " AND ".join("ct.email NOT ILIKE %s" for _ in INTERNAL_DOMAINS)
    cur.execute(
        f"""
        WITH base AS (
            SELECT ct.id AS contact_id,
                   NULLIF(TRIM(CONCAT_WS(' ', ct.first_name, ct.last_name)), '') AS contact_name,
                   ct.email,
                   ct.company_id,
                   c.name AS company_name,
                   (ct.props->>'date_of_meeting_scheduled')::date AS date,
                   ct.props->>'meeting_datetime' AS meeting_datetime,
                   ct.lead_life,
                   LOWER(ct.props->>'scheduled_by') AS scheduled_by
              FROM prospect_contacts ct
              LEFT JOIN prospect_companies c ON c.id = ct.company_id
             WHERE NOT ct.is_dummy
               AND NULLIF(ct.props->>'scheduled_by', '') IS NOT NULL
               AND LOWER(ct.props->>'scheduled_by') <> ALL(%s)
               AND ({domains} OR ct.email IS NULL)
               AND NULLIF(ct.props->>'meeting_datetime', '') IS NOT NULL
               AND NULLIF(ct.props->>'date_of_meeting_scheduled', '') IS NOT NULL
               {extra}
        )
        SELECT b.*, {_person_name_sql('b.scheduled_by')} AS scheduled_by_name
          FROM base b
         ORDER BY b.date, b.contact_id
        """,
        [list(EXCLUDED_SCHEDULERS), *[f"%@{d}" for d in INTERNAL_DOMAINS], *params],
    )
    rows = []
    for r in cur.fetchall():
        r = dict(r)
        r["date"] = r["date"].isoformat() if r["date"] else None
        rows.append(r)
    return {
        "rows": rows,
        "people_order": people_order(cur),
        "definition": {
            "excluded_schedulers": list(EXCLUDED_SCHEDULERS),
            "internal_domains": list(INTERNAL_DOMAINS),
            "team": _names(cur, members) if members else None,
        },
    }


# Lead Quality: el reporte de HubSpot excluye a estos 3 (Valentina Cadirola sí cuenta acá).
LQ_EXCLUDED_SCHEDULERS = ("bahia@vintti.com", "agustin@vintti.com", "mariano@vintti.com")


def lead_quality(cur, date_from: date | None, date_to: date | None, team: str | None = None) -> dict:
    """Lead Quality: por qué las intro calls no pasaron a SQL (2026-11-07).

    Contactos con «MQL (AE) Lost Reason» por mes de Meeting Date & Time (UTC, como HubSpot),
    con el motivo (`reason`) y Scheduled By en cada fila: el panel general desglosa por
    motivo y «x BDR» por persona. Filtros del reporte de HubSpot:
      1. MQL (AE) Lost Reason conocido. Incluye el que vino del negocio (prop_sync, decisión
         de la owner 2026-11-07): por eso da 175 y HubSpot 162.
      2. Lead Life alguna vez Closed Lost: no se aplica, todos los que tienen motivo lo
         cumplen (verificado en HubSpot y en el Hub).
      3. Scheduled By conocido y fuera de LQ_EXCLUDED_SCHEDULERS.
      4. Meeting Date & Time conocido (es la dimensión)."""
    where, params = [], []
    members = list(TEAMS[team]) if team else None
    if members:
        where.append("LOWER(ct.props->>'scheduled_by') = ANY(%s)")
        params.append(members)
    day = "((ct.props->>'meeting_datetime')::timestamptz AT TIME ZONE 'UTC')::date"
    if date_from:
        where.append(f"{day} >= %s")
        params.append(date_from)
    if date_to:
        where.append(f"{day} <= %s")
        params.append(date_to)
    extra = "".join(" AND " + w for w in where)
    cur.execute(
        f"""
        WITH base AS (
            SELECT ct.id AS contact_id,
                   NULLIF(TRIM(CONCAT_WS(' ', ct.first_name, ct.last_name)), '') AS contact_name,
                   ct.email,
                   ct.company_id,
                   c.name AS company_name,
                   {day} AS date,
                   ct.props->>'meeting_datetime' AS meeting_datetime,
                   ct.props->>'mql_ae_lost_reason' AS reason,
                   ct.lead_life,
                   LOWER(ct.props->>'scheduled_by') AS scheduled_by
              FROM prospect_contacts ct
              LEFT JOIN prospect_companies c ON c.id = ct.company_id
             WHERE NOT ct.is_dummy
               AND NULLIF(ct.props->>'mql_ae_lost_reason', '') IS NOT NULL
               AND NULLIF(ct.props->>'scheduled_by', '') IS NOT NULL
               AND LOWER(ct.props->>'scheduled_by') <> ALL(%s)
               AND NULLIF(ct.props->>'meeting_datetime', '') IS NOT NULL
               {extra}
        )
        SELECT b.*, {_person_name_sql('b.scheduled_by')} AS scheduled_by_name
          FROM base b
         ORDER BY b.date, b.contact_id
        """,
        [list(LQ_EXCLUDED_SCHEDULERS), *params],
    )
    rows = []
    for r in cur.fetchall():
        r = dict(r)
        r["date"] = r["date"].isoformat() if r["date"] else None
        rows.append(r)
    from prospecting.deal_fields import MQL_LOST_REASONS
    return {
        "rows": rows,
        "people_order": people_order(cur),
        "reasons": list(MQL_LOST_REASONS),  # orden fijo = color fijo por motivo
        "definition": {
            "excluded_schedulers": list(LQ_EXCLUDED_SCHEDULERS),
            "internal_domains": [],
            "team": _names(cur, members) if members else None,
        },
    }


def people_order(cur) -> list[str]:
    """Las personas con algún SQL o alguna intro call, en orden de aparición (su primera).
    El front asigna los colores con esta lista en TODOS los paneles: así Abril tiene el
    mismo color en cada gráfico, y alguien nuevo se agrega al final sin correr a nadie.
    Sin los que no salen en ningún panel (LQ_EXCLUDED_SCHEDULERS) para que alcance la paleta."""
    cur.execute(
        """
        WITH firsts AS (
            SELECT LOWER(ct.props->>'scheduled_by') AS email, (d.props->>'sql_date')::date AS at
              FROM prospect_contacts ct
              JOIN prospect_deal_contacts dc ON dc.contact_id = ct.id
              JOIN prospect_deals d ON d.id = dc.deal_id
             WHERE NOT ct.is_dummy AND NOT d.is_dummy
               AND NULLIF(ct.props->>'scheduled_by', '') IS NOT NULL
               AND NULLIF(d.props->>'sql_date', '') IS NOT NULL
            UNION ALL
            SELECT LOWER(ct.props->>'scheduled_by'), (ct.props->>'date_of_meeting_scheduled')::date
              FROM prospect_contacts ct
             WHERE NOT ct.is_dummy
               AND NULLIF(ct.props->>'scheduled_by', '') IS NOT NULL
               AND NULLIF(ct.props->>'meeting_datetime', '') IS NOT NULL
               AND NULLIF(ct.props->>'date_of_meeting_scheduled', '') IS NOT NULL
        )
        SELECT email FROM firsts
         WHERE email <> ALL(%s)
         GROUP BY 1
         ORDER BY BOOL_OR(email = ANY(%s)), MIN(at), 1
        """,
        # Quien sólo sale en Lead Quality (excluido de SQLs/Intro, p. ej. Valentina Cadirola)
        # va al final: así sumarla no le corre el color a nadie.
        (list(LQ_EXCLUDED_SCHEDULERS), list(EXCLUDED_SCHEDULERS)),
    )
    order = [r["email"] for r in cur.fetchall()]
    # Owners de empresas Not ICP que no agendaron nada: al final, así no corren a nadie.
    cur.execute(
        """
        SELECT LOWER(prospecting_owner_email) AS email
          FROM prospect_companies
         WHERE NOT is_dummy AND NULLIF(not_icp_reason, '') IS NOT NULL
           AND NULLIF(prospecting_owner_email, '') IS NOT NULL
         GROUP BY 1
         ORDER BY MIN(created_at), 1
        """
    )
    seen = set(order)
    order += [r["email"] for r in cur.fetchall() if r["email"] not in seen]
    return order


def not_icp_reason(cur, date_from: date | None = None, date_to: date | None = None) -> dict:
    """Not ICP Reason (grupo «Rendimiento de Islas», 2026-11-10): empresas por motivo,
    desglosadas por Prospecting Owner. Igual que el reporte de HubSpot: todas, sin fecha
    (`date_from` / `date_to` se ignoran), con el motivo en alguno de los 6 de la lista.
    Las que no tienen owner van con `owner` NULL («Sin owner» en el front)."""
    cur.execute(
        f"""
        SELECT c.id AS company_id, c.name, c.domain, c.not_icp_reason AS reason,
               c.prospecting_status AS status,
               LOWER(NULLIF(c.prospecting_owner_email, '')) AS owner,
               CASE WHEN NULLIF(c.prospecting_owner_email, '') IS NULL THEN NULL
                    ELSE {_person_name_sql("LOWER(c.prospecting_owner_email)")} END AS owner_name
          FROM prospect_companies c
         WHERE NOT c.is_dummy AND c.not_icp_reason = ANY(%s)
         ORDER BY c.name
        """,
        (list(NOT_ICP_REASONS),),
    )
    return {
        "rows": [dict(r) for r in cur.fetchall()],
        "people_order": people_order(cur),
        "reasons": list(NOT_ICP_REASONS),  # orden fijo = color fijo por motivo
    }


def _names(cur, emails: list[str]) -> list[str]:
    cur.execute(
        f"SELECT {_person_name_sql('e')} AS name FROM UNNEST(%s::text[]) WITH ORDINALITY AS t(e, i) ORDER BY i",
        (emails,),
    )
    return [r["name"] for r in cur.fetchall()]


PANELS = {
    "sqls_by_bdr": sqls_by_bdr,
    "sqls_by_bdr_vinttikids": lambda cur, f, t: sqls_by_bdr(cur, f, t, team="vinttikids"),
    "sqls_by_bdr_nextgen": lambda cur, f, t: sqls_by_bdr(cur, f, t, team="nextgen"),
    "intro_calls": intro_calls,
    "intro_calls_vinttikids": lambda cur, f, t: intro_calls(cur, f, t, team="vinttikids"),
    "intro_calls_nextgen": lambda cur, f, t: intro_calls(cur, f, t, team="nextgen"),
    "lead_quality": lead_quality,
    "lead_quality_vinttikids": lambda cur, f, t: lead_quality(cur, f, t, team="vinttikids"),
    "lead_quality_nextgen": lambda cur, f, t: lead_quality(cur, f, t, team="nextgen"),
    "not_icp_reason": not_icp_reason,
}
