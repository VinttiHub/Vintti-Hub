"""Candidates Allocated · Outbound (Sales/AE) · acumulativo YTD + barras mensuales.

Candidatos colocados (hires) en deals del canal Outbound vendidos por AE
(opp_sales_lead ∈ {mariano,bahia}), del año en curso, por mes de inicio.
Fila por mes con `cands` (barras) + constantes YTD para los chips:
  total_ytd, delta_vs_py, cands_per_win_label ("1.4x"), avg_per_month_label ("9.6").
"""
from __future__ import annotations

from datetime import date, datetime


AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")


def _parse_date(value):
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

    sql = """
        WITH params AS (
          SELECT %(corte)s::date AS corte_d,
                 DATE_TRUNC('year', %(corte)s::date)::date AS year_start,
                 (%(corte)s::date - INTERVAL '1 year')::date AS corte_py,
                 DATE_TRUNC('year', (%(corte)s::date - INTERVAL '1 year'))::date AS year_start_py
        ),
        hires AS (
          SELECT
            CASE WHEN h.carga_active IS NOT NULL THEN h.carga_active::date
                 ELSE NULLIF(h.start_date::text,'')::date END AS start_d
          FROM hire_opportunity h
          JOIN opportunity o ON o.opportunity_id = h.opportunity_id
          JOIN account a ON a.account_id = h.account_id
          WHERE h.candidate_id IS NOT NULL
            AND LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'outbound'
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(ae_leads)s
        ),
        wins AS (
          SELECT NULLIF(o.opp_close_date::text,'')::date AS close_d
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'outbound'
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(ae_leads)s
        ),
        meses AS (
          SELECT DATE_TRUNC('month', gs)::date AS mes
          FROM params p, generate_series(p.year_start, p.corte_d, INTERVAL '1 month') gs
        ),
        per_month AS (
          SELECT m.mes,
            COUNT(h.*) FILTER (WHERE h.start_d BETWEEN (SELECT year_start FROM params) AND (SELECT corte_d FROM params))::int AS cands
          FROM meses m
          LEFT JOIN hires h ON DATE_TRUNC('month', h.start_d)::date = m.mes
          GROUP BY m.mes
        ),
        agg AS (
          SELECT
            (SELECT COUNT(*) FROM hires h CROSS JOIN params p WHERE h.start_d BETWEEN p.year_start AND p.corte_d)::int AS total_ytd,
            (SELECT COUNT(*) FROM hires h CROSS JOIN params p WHERE h.start_d BETWEEN p.year_start_py AND p.corte_py)::int AS prev_ytd,
            (SELECT COUNT(*) FROM wins w CROSS JOIN params p WHERE w.close_d BETWEEN p.year_start AND p.corte_d)::int AS wins_ytd,
            EXTRACT(MONTH FROM (SELECT corte_d FROM params))::int AS months_elapsed
        )
        SELECT
          TO_CHAR(pm.mes, 'YYYY-MM') AS mes,
          pm.cands,
          a.total_ytd,
          (a.total_ytd - a.prev_ytd) AS delta_vs_py,
          (ROUND(a.total_ytd::numeric / NULLIF(a.wins_ytd, 0), 1) || 'x') AS cands_per_win_label,
          TO_CHAR(ROUND(a.total_ytd::numeric / NULLIF(a.months_elapsed, 0), 1), 'FM999990.0') AS avg_per_month_label
        FROM per_month pm CROSS JOIN agg a
        ORDER BY pm.mes;
    """

    return sql, {"corte": corte, "ae_leads": AE_LEADS}


DATASET = {
    "key": "candidates_allocated_outbound_history",
    "label": "Candidates Allocated · Outbound (AE) · YTD + mensual",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
        {"key": "cands_per_win_label", "label": "Cands/win", "type": "string"},
        {"key": "avg_per_month_label", "label": "Avg/mes", "type": "string"},
    ],
    "measures": [
        {"key": "cands", "label": "Candidatos (mes)", "type": "number"},
        {"key": "total_ytd", "label": "Total YTD", "type": "number"},
        {"key": "delta_vs_py", "label": "Δ vs año ant.", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
