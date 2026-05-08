from __future__ import annotations

from datetime import date, datetime


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

    sql = """
        WITH params AS (
          SELECT
            %(corte)s::date AS corte_d,
            DATE_TRUNC('year', %(corte)s::date)::date AS year_start
        ),
        meses AS (
          SELECT
            DATE_TRUNC('month', gs)::date AS mes,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS fin_mes
          FROM params p,
               generate_series(p.year_start, p.corte_d, INTERVAL '1 month') gs
        ),
        staffing_hires AS (
          SELECT
            ho.candidate_id,
            ho.opportunity_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text,'')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text,'') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            COALESCE(ho.salary,0)::numeric AS salary,
            COALESCE(ho.fee,0)::numeric AS fee
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE o.opp_model = 'Staffing'
        ),
        activos_fin AS (
          SELECT DISTINCT ON (m.mes, h.opportunity_id, h.candidate_id)
                 m.mes, h.salary, h.fee
          FROM meses m
          JOIN staffing_hires h
            ON h.start_d IS NOT NULL
           AND h.start_d <= m.fin_mes
           AND (h.end_d IS NULL OR h.end_d >= m.fin_mes)
          ORDER BY m.mes, h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        staffing_mrr AS (
          SELECT mes, SUM(salary + fee)::numeric AS mrr_mes
          FROM activos_fin
          GROUP BY mes
        ),
        staffing_ytd AS (
          SELECT COALESCE(SUM(mrr_mes), 0)::numeric AS revenue_staffing_ytd
          FROM staffing_mrr
        ),
        recruiting_ytd AS (
          SELECT COALESCE(SUM(ho.revenue), 0)::numeric AS revenue_recruiting_ytd
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          CROSS JOIN params p
          WHERE o.opp_model = 'Recruiting'
            AND o.opp_close_date IS NOT NULL
            AND o.opp_close_date >= p.year_start
            AND o.opp_close_date <= p.corte_d
        )
        SELECT
          (SELECT corte_d    FROM params)               AS corte,
          (SELECT year_start FROM params)               AS year_start,
          s.revenue_staffing_ytd::bigint                AS revenue_staffing_ytd,
          r.revenue_recruiting_ytd::bigint              AS revenue_recruiting_ytd,
          (s.revenue_staffing_ytd + r.revenue_recruiting_ytd)::bigint AS revenue_total_ytd
        FROM staffing_ytd s, recruiting_ytd r;
    """

    return sql, {"corte": corte}


DATASET = {
    "key": "revenue_ytd_total",
    "label": "Revenue YTD — Staffing + Recruiting",
    "dimensions": [
        {"key": "corte", "label": "Corte", "type": "date"},
        {"key": "year_start", "label": "Año desde", "type": "date"},
    ],
    "measures": [
        {"key": "revenue_staffing_ytd", "label": "Revenue Staffing YTD", "type": "currency"},
        {"key": "revenue_recruiting_ytd", "label": "Revenue Recruiting YTD", "type": "currency"},
        {"key": "revenue_total_ytd", "label": "Revenue Total YTD", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
