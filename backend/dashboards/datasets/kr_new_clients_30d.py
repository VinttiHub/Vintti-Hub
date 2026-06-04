"""KR5 · New Clients Generated (#) — AM + AE, últimos 30 días.

Clientes nuevos (new logos) cuyo PRIMER Close Win cae en la ventana. Se cuenta
una cuenta (cliente) una sola vez. Scope AM + AE (unión opp_sales_lead ∈ {AEs}
OR account_manager = {AM}). Incluye delta vs los 30 días previos y el target
mensual.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")
AM_LEADS = ("lara@vintti.com",)
TARGET = 20


def _parse_date(value):
    if not value:
        return None
    parts = str(value).strip().split("-")
    try:
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        return None
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (_parse_date(filters.get("corte")) or _parse_date(filters.get("hasta"))
             or datetime.utcnow().date())
    cur_ini, cur_fin = corte - timedelta(days=29), corte
    prev_ini, prev_fin = corte - timedelta(days=59), corte - timedelta(days=30)

    sql = """
        WITH all_wins AS (
          SELECT o.account_id,
                 NULLIF(o.opp_close_date::text, '')::date AS close_d,
                 LOWER(TRIM(COALESCE(o.opp_sales_lead, '')))  AS lead,
                 LOWER(TRIM(COALESCE(a.account_manager, '')))  AS amgr
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND o.opp_model IN ('Staffing', 'Recruiting')
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
        ),
        first_close AS (
          SELECT account_id, MIN(close_d) AS first_d FROM all_wins GROUP BY account_id
        ),
        new_logos AS (
          SELECT DISTINCT f.account_id, f.first_d
          FROM first_close f
          JOIN all_wins w ON w.account_id = f.account_id AND w.close_d = f.first_d
          WHERE ( w.lead IN %(ae_leads)s OR w.amgr IN %(am_leads)s )
        ),
        agg AS (
          SELECT
            COUNT(*) FILTER (WHERE first_d BETWEEN %(cur_ini)s::date  AND %(cur_fin)s::date)::int  AS cnt,
            COUNT(*) FILTER (WHERE first_d BETWEEN %(prev_ini)s::date AND %(prev_fin)s::date)::int AS prev_cnt
          FROM new_logos
        )
        SELECT
          cnt                                               AS count,
          prev_cnt                                          AS prev_count,
          (cnt - prev_cnt)                                  AS delta,
          %(target)s::int                                   AS target,
          ROUND(100.0 * cnt / NULLIF(%(target)s, 0), 0)::int            AS pct_of_target,
          LEAST(100, ROUND(100.0 * cnt / NULLIF(%(target)s, 0)))::int   AS bar_pct
        FROM agg;
    """
    return sql, {"ae_leads": AE_LEADS, "am_leads": AM_LEADS, "target": TARGET,
                 "cur_ini": cur_ini, "cur_fin": cur_fin, "prev_ini": prev_ini, "prev_fin": prev_fin}


DATASET = {
    "key": "kr_new_clients_30d",
    "label": "KR5 · New Clients Generated (AM+AE, 30d)",
    "dimensions": [],
    "measures": [
        {"key": "count", "label": "Clientes nuevos", "type": "number"},
        {"key": "prev_count", "label": "Período anterior", "type": "number"},
        {"key": "delta", "label": "Δ vs anterior", "type": "number"},
        {"key": "target", "label": "Target mensual", "type": "number"},
        {"key": "pct_of_target", "label": "% del target", "type": "percent"},
        {"key": "bar_pct", "label": "% barra (capado 100)", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
