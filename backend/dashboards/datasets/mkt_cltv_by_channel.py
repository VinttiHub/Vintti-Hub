"""Marketing · CLTV por canal de adquisición — por modelo (Staffing | Recruiting).

Filtro `model` (default 'Staffing'):

STAFFING (recurrente) — vida REAL por cliente, all-time:
  CLTV_cliente = Σ (fee mensual del hire × meses activos)        [Staffing]
  MRR_cliente  = CLTV_cliente / meses_de_vida_del_cliente
  Activo       = el cliente tiene ≥1 contractor con baja vacía o futura.
  Columnas: clients · active_clients · avg_mrr · avg_lifetime · avg_cltv · total_cltv.

RECRUITING (one-time) — no hay MRR ni vida ni "activo":
  CLTV_cliente = Σ fee de placement (ho.revenue) de sus deals Recruiting Close Win.
  Columnas: clients · placements · avg_fee (por placement) · avg_cltv (por cliente) · total_cltv.

Por canal (origin = where_come_from, sin outbound, '(Sin origen)' aparte).
"""
from __future__ import annotations


def _model(filters: dict) -> str:
    m = str(filters.get("model") or "").strip().lower()
    return "Recruiting" if m == "recruiting" else "Staffing"


def _mql_sql_by_origin() -> tuple[dict, dict]:
    """Conteo all-time de MQLs y SQLs por origin (where_come_from), filtro de
    marketing OFICIAL `mql_source ∈ {Inbound MQL, Event MQL}`. Vive en HubSpot."""
    from utils.hubspot import HubSpotClient
    from routes.hubspot_routes import (
        _resolve_account_property_maps, _first_mapped_value, _normalize_lead_source,
    )
    from .mkt_mqls_by_origin import _IN_VALUES, _REACHED_MQL
    from .mkt_funnel_mql_sql_cw import _REACHED_SQL
    from ._marketing_scope import is_marketing_mql_source

    client = HubSpotClient()
    pm = _resolve_account_property_maps(client)
    origin_prop = (pm.get("contacts") or {}).get("where_come_from") or "origin"
    contacts = client.search_contacts(
        [{"propertyName": "lead_life", "operator": "IN", "values": _IN_VALUES}],
        extra_properties=["lead_life", origin_prop, "mql_source"],
    )
    mql, sql = {}, {}
    for c in contacts:
        p = c.get("properties") or {}
        ll = str(p.get("lead_life") or "").strip().lower()
        if ll not in _REACHED_MQL:
            continue
        if not is_marketing_mql_source(p.get("mql_source")):
            continue
        origin = _normalize_lead_source(_first_mapped_value(pm, "where_come_from", contact=c))
        origin = (str(origin or "").strip()) or "(Sin origen)"
        mql[origin] = mql.get(origin, 0) + 1
        if ll in _REACHED_SQL:
            sql[origin] = sql.get(origin, 0) + 1
    return mql, sql


def _sql_for(model: str) -> str:
    if model == "Recruiting":
        # One-time: el ingreso del cliente es la suma de fees de placement (ho.revenue)
        # de sus oportunidades Recruiting ganadas. Sin MRR / vida / activo.
        sql = """
            WITH acct AS (
              SELECT a.account_id,
                     COALESCE(NULLIF(TRIM(a.where_come_from), ''), '(Sin origen)') AS origin
              FROM account a
              WHERE LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral', 'import')
                AND COALESCE(a.vintti_internal, FALSE) = FALSE
            ),
            rec AS (
              SELECT
                o.opportunity_id,
                o.account_id,
                ac.origin,
                COALESCE(SUM(ho.revenue), 0)::numeric AS deal_fee
              FROM opportunity o
              JOIN acct ac ON ac.account_id = o.account_id
              LEFT JOIN hire_opportunity ho ON ho.opportunity_id = o.opportunity_id
              WHERE o.opp_model = 'Recruiting' AND TRIM(o.opp_stage) = 'Close Win'
              GROUP BY o.opportunity_id, o.account_id, ac.origin
            ),
            per_client AS (
              SELECT account_id, origin,
                     COUNT(*)::int        AS placements,
                     SUM(deal_fee)::numeric AS client_fee
              FROM rec
              GROUP BY account_id, origin
            )
            SELECT
              origin,
              COUNT(*)::int                                            AS clients,
              NULL::int                                                AS active_clients,
              NULL::int                                                AS inactive_clients,
              NULL::bigint                                             AS avg_mrr,
              NULL::float                                              AS avg_lifetime,
              SUM(placements)::int                                     AS placements,
              ROUND(SUM(client_fee) / NULLIF(SUM(placements), 0))::bigint AS avg_fee,
              ROUND(AVG(client_fee))::bigint                           AS avg_cltv,
              ROUND(SUM(client_fee))::bigint                           AS total_cltv,
              CASE WHEN COUNT(*) < 3 THEN '⚠ reducida' ELSE '' END     AS muestra
            FROM per_client
            GROUP BY origin
            ORDER BY total_cltv DESC, origin;
        """
        return sql

    # STAFFING (default)
    sql = """
        WITH acct AS (
          SELECT a.account_id,
                 COALESCE(NULLIF(TRIM(a.where_come_from), ''), '(Sin origen)') AS origin
          FROM account a
          WHERE LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral', 'import')
                AND COALESCE(a.vintti_internal, FALSE) = FALSE
        ),
        hires AS (
          SELECT
            ho.account_id,
            COALESCE(ho.fee, 0)::numeric AS fee,
            CASE WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                 ELSE NULLIF(ho.start_date::text, '')::date END AS start_d,
            CASE WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
                 WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
                 ELSE ho.end_date::date END AS end_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.account_id IS NOT NULL AND TRIM(o.opp_stage) = 'Close Win'
            AND o.opp_model = 'Staffing'
        ),
        -- R6: lifetime canónico = meses calendario ACTIVOS (overlap), igual que
        -- client_lifetime_avg. Expandimos cada hire en sus meses calendario:
        --   CLTV  = Σ fee por cada mes calendario activo del hire.
        --   lifetime_months = nº de meses calendario DISTINTOS con ≥1 contractor
        --   (excluye huecos; meses con contractors paralelos cuentan una vez).
        -- Antes usaba AGE() por hire y MIN/MAX por cliente (incluía huecos).
        hire_months AS (
          SELECT
            h.account_id, ac.origin, h.fee,
            (h.end_d IS NULL OR h.end_d >= CURRENT_DATE) AS hire_active,
            DATE_TRUNC('month', gs)::date AS mes
          FROM hires h
          JOIN acct ac ON ac.account_id = h.account_id
          CROSS JOIN LATERAL generate_series(
            DATE_TRUNC('month', h.start_d),
            DATE_TRUNC('month', COALESCE(h.end_d, CURRENT_DATE)),
            interval '1 month'
          ) gs
          WHERE h.start_d IS NOT NULL
        ),
        per_client AS (
          SELECT
            account_id, origin,
            BOOL_OR(hire_active) AS is_active,
            SUM(fee)::numeric        AS cltv,
            COUNT(DISTINCT mes)::int AS lifetime_months
          FROM hire_months
          GROUP BY account_id, origin
        ),
        pc AS (
          SELECT *,
            (cltv / NULLIF(lifetime_months, 0))::numeric AS mrr
          FROM per_client
        )
        SELECT
          origin,
          COUNT(*)::int                                              AS clients,
          COUNT(*) FILTER (WHERE is_active)::int                     AS active_clients,
          COUNT(*) FILTER (WHERE NOT is_active)::int                 AS inactive_clients,
          ROUND(AVG(mrr))::bigint                                    AS avg_mrr,
          ROUND(AVG(lifetime_months), 1)::float                     AS avg_lifetime,
          NULL::int                                                 AS placements,
          NULL::bigint                                              AS avg_fee,
          ROUND(AVG(cltv))::bigint                                   AS avg_cltv,
          ROUND(SUM(cltv))::bigint                                   AS total_cltv,
          CASE WHEN COUNT(*) < 3 THEN '⚠ reducida' ELSE '' END       AS muestra
        FROM pc
        GROUP BY origin
        ORDER BY avg_cltv DESC, origin;
    """
    return sql


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    from db import get_connection

    sql = _sql_for(_model(filters))
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close()
    finally:
        conn.close()

    # MQL / SQL por canal (HubSpot, all-time, filtro mql_source). Se unen por origin.
    mql_o, sql_o = _mql_sql_by_origin()
    for r in rows:
        o = r.get("origin")
        r["mql"] = mql_o.get(o, 0)
        r["sql"] = sql_o.get(o, 0)
    return rows


DATASET = {
    "key": "mkt_cltv_by_channel",
    "label": "Marketing · CLTV por canal (Staffing | Recruiting)",
    "dimensions": [{"key": "origin", "label": "Canal", "type": "string"}],
    "measures": [
        {"key": "mql", "label": "MQL", "type": "number"},
        {"key": "sql", "label": "SQL", "type": "number"},
        {"key": "clients", "label": "Clientes", "type": "number"},
        {"key": "active_clients", "label": "Activos", "type": "number"},
        {"key": "placements", "label": "# Placements", "type": "number"},
        {"key": "avg_fee", "label": "Fee promedio", "type": "currency"},
        {"key": "avg_mrr", "label": "MRR promedio", "type": "currency"},
        {"key": "avg_lifetime", "label": "Vida promedio (meses)", "type": "number"},
        {"key": "avg_cltv", "label": "CLTV promedio", "type": "currency"},
        {"key": "total_cltv", "label": "CLTV total", "type": "currency"},
    ],
    "default_filters": {"model": "Staffing"},
    "compute": compute,
}
