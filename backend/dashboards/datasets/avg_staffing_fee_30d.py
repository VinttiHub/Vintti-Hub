"""Avg Staffing Fee — últimos 30 días, M+B.

Promedio del fee mensual (margen Vintti, sin salario del candidato) cobrado en
deals Staffing `Close Win` de Mariano + Bahia cuya `opp_close_date` cae en los
últimos 30 días.

Un "deal" = una opportunity. Si una opp tiene N hires, se suman los fees por
opp y después se promedia entre opps.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


SALES_LEADS = ("mariano@vintti.com", "bahia@vintti.com")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.split("-")
    try:
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or datetime.utcnow().date()
    )
    win_ini = corte - timedelta(days=29)
    win_fin = corte

    sql = """
        WITH ae_wins AS (
          SELECT
            o.opportunity_id,
            o.account_id,
            NULLIF(o.opp_close_date::text, '')::date AS close_d
          FROM opportunity o
          WHERE o.opp_model = 'Staffing'
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
            AND TRIM(o.opp_stage) = 'Close Win'
        ),
        per_opp AS (
          SELECT
            w.opportunity_id,
            w.account_id,
            w.close_d,
            COALESCE(SUM(ho.fee), 0)::numeric AS deal_fee
          FROM ae_wins w
          LEFT JOIN hire_opportunity ho ON ho.opportunity_id = w.opportunity_id
          GROUP BY w.opportunity_id, w.account_id, w.close_d
        ),
        scoped AS (
          SELECT *
          FROM per_opp
          WHERE close_d IS NOT NULL
            AND close_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
        )
        SELECT
          %(win_ini)s::date                                       AS win_ini,
          %(win_fin)s::date                                       AS win_fin,
          COALESCE(AVG(deal_fee), 0)::numeric                     AS avg_fee,
          COALESCE(SUM(deal_fee), 0)::numeric                     AS total_fee,
          COUNT(*)::int                                           AS deal_count,
          COUNT(DISTINCT account_id)::int                         AS client_count
        FROM scoped;
    """

    return sql, {
        "sales_leads": SALES_LEADS,
        "win_ini": win_ini,
        "win_fin": win_fin,
    }


DATASET = {
    "key": "avg_staffing_fee_30d",
    "label": "Avg Staffing Fee — últimos 30 días (M+B)",
    "dimensions": [
        {"key": "win_ini", "label": "Inicio ventana", "type": "date"},
        {"key": "win_fin", "label": "Corte", "type": "date"},
    ],
    "measures": [
        {"key": "avg_fee", "label": "Avg fee mensual por deal", "type": "currency"},
        {"key": "total_fee", "label": "Total fee mensual (window)", "type": "currency"},
        {"key": "deal_count", "label": "Deals (window)", "type": "number"},
        {"key": "client_count", "label": "Clientes (window)", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
