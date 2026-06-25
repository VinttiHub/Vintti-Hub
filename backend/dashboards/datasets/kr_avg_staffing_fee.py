"""KR3 · Avg Staffing Fee por candidato colocado ($) — AM + AE, últimos 30 días.

Fee promedio de Vintti (margen mensual `ho.fee`, sin salario) por CANDIDATO
colocado en deals Staffing Close Win cuyo `opp_close_date` cae en los últimos
30 días. Scope AM + AE (unión opp_sales_lead ∈ {AEs} OR account_manager = {AM}).
avg = Σ fee / nº de candidatos colocados (hires con candidate_id).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from ._now import today_ar

from ._periods import window_bounds


AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")
AM_LEADS = ("lara@vintti.com",)
OPP_MODEL = "Staffing"
FEE_EXPR = "COALESCE(ho.fee, 0)"


def _parse_date(value: str | None) -> date | None:
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
             or today_ar())
    win_ini, win_fin = window_bounds(filters)

    sql = f"""
        WITH hires AS (
          SELECT
            ho.candidate_id,
            o.opportunity_id,
            o.account_id,
            {FEE_EXPR}::numeric AS fee,
            CASE WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                 ELSE NULLIF(ho.start_date::text, '')::date END AS start_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          JOIN account a ON a.account_id = o.account_id
          WHERE o.opp_model = %(model)s
            AND TRIM(o.opp_stage) = 'Close Win'
            AND ho.candidate_id IS NOT NULL
            AND ( LOWER(TRIM(COALESCE(o.opp_sales_lead, ''))) IN %(ae_leads)s
                  OR LOWER(TRIM(COALESCE(a.account_manager, ''))) IN %(am_leads)s )
        ),
        scoped AS (
          SELECT * FROM hires
          WHERE start_d IS NOT NULL AND start_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
        )
        SELECT
          %(win_ini)s::date                                  AS win_ini,
          %(win_fin)s::date                                  AS win_fin,
          COALESCE(SUM(fee) / NULLIF(COUNT(*), 0), 0)::bigint AS avg_fee,
          COALESCE(SUM(fee), 0)::bigint                       AS total_fee,
          COUNT(*)::int                                       AS candidate_count,
          COUNT(DISTINCT opportunity_id)::int                 AS deal_count,
          COUNT(DISTINCT account_id)::int                     AS client_count
        FROM scoped;
    """
    return sql, {"model": OPP_MODEL, "ae_leads": AE_LEADS, "am_leads": AM_LEADS,
                 "win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "kr_avg_staffing_fee",
    "label": "KR3 · Avg Staffing Fee / candidato (AM+AE, 30d)",
    "dimensions": [],
    "measures": [
        {"key": "avg_fee", "label": "Avg fee / candidato", "type": "currency"},
        {"key": "total_fee", "label": "Fee total", "type": "currency"},
        {"key": "candidate_count", "label": "Candidatos colocados", "type": "number"},
        {"key": "deal_count", "label": "Deals", "type": "number"},
        {"key": "client_count", "label": "Clientes", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
