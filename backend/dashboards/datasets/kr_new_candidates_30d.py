"""KR6 · New Candidates Allocated (#) — AM + AE, últimos 30 días.

Candidatos colocados (hires con candidate_id) cuya fecha de colocación
(COALESCE(carga_active, start_date)) cae en la ventana. Scope AM + AE (unión
opp_sales_lead ∈ {AEs} OR account_manager = {AM}). Incluye delta vs los 30 días
previos y el target mensual.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from ._now import today_ar

from ._periods import window_bounds


AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")
AM_LEADS = ("lara@vintti.com",)
TARGET = 30


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
             or today_ar())
    cur_ini, cur_fin = window_bounds(filters)
    prev_ini, prev_fin = corte - timedelta(days=59), corte - timedelta(days=30)

    sql = """
        WITH hires AS (
          SELECT
            CASE WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                 ELSE NULLIF(ho.start_date::text, '')::date END AS start_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          JOIN account a ON a.account_id = o.account_id
          WHERE o.opp_model IN ('Staffing', 'Recruiting')
            AND TRIM(o.opp_stage) = 'Close Win'
            AND ho.candidate_id IS NOT NULL
            AND ( LOWER(TRIM(COALESCE(o.opp_sales_lead, ''))) IN %(ae_leads)s
                  OR LOWER(TRIM(COALESCE(a.account_manager, ''))) IN %(am_leads)s )
        ),
        agg AS (
          SELECT
            COUNT(*) FILTER (WHERE start_d BETWEEN %(cur_ini)s::date  AND %(cur_fin)s::date)::int  AS cnt,
            COUNT(*) FILTER (WHERE start_d BETWEEN %(prev_ini)s::date AND %(prev_fin)s::date)::int AS prev_cnt
          FROM hires
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
    "key": "kr_new_candidates_30d",
    "label": "KR6 · New Candidates Allocated (AM+AE, 30d)",
    "dimensions": [],
    "measures": [
        {"key": "count", "label": "Candidatos colocados", "type": "number"},
        {"key": "prev_count", "label": "Período anterior", "type": "number"},
        {"key": "delta", "label": "Δ vs anterior", "type": "number"},
        {"key": "target", "label": "Target mensual", "type": "number"},
        {"key": "pct_of_target", "label": "% del target", "type": "percent"},
        {"key": "bar_pct", "label": "% barra (capado 100)", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
