"""Client Wins · Outbound (Sales/AE) · acumulativo YTD + barras mensuales.

Close wins del canal Outbound vendidos por AE (opp_sales_lead ∈ {mariano,bahia}),
del año en curso. Devuelve una fila por mes con `wins` (para las barras) y, repetidos
en cada fila como constantes, los agregados YTD para los chips:
  total_ytd, staffing_ytd, recruiting_ytd, delta_vs_py.
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
        wins AS (
          SELECT
            TRIM(o.opp_model) AS model,
            NULLIF(o.opp_close_date::text,'')::date AS close_d
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
            COUNT(w.*) FILTER (WHERE w.close_d BETWEEN (SELECT year_start FROM params) AND (SELECT corte_d FROM params))::int AS wins
          FROM meses m
          LEFT JOIN wins w ON DATE_TRUNC('month', w.close_d)::date = m.mes
          GROUP BY m.mes
        ),
        agg AS (
          SELECT
            COUNT(*) FILTER (WHERE close_d BETWEEN p.year_start AND p.corte_d)::int AS total_ytd,
            COUNT(*) FILTER (WHERE close_d BETWEEN p.year_start AND p.corte_d AND model='Staffing')::int AS staffing_ytd,
            COUNT(*) FILTER (WHERE close_d BETWEEN p.year_start AND p.corte_d AND model='Recruiting')::int AS recruiting_ytd,
            COUNT(*) FILTER (WHERE close_d BETWEEN p.year_start_py AND p.corte_py)::int AS prev_ytd
          FROM wins w CROSS JOIN params p
        )
        SELECT
          TO_CHAR(pm.mes, 'YYYY-MM') AS mes,
          pm.wins,
          a.total_ytd,
          a.staffing_ytd,
          a.recruiting_ytd,
          (a.total_ytd - a.prev_ytd) AS delta_vs_py
        FROM per_month pm CROSS JOIN agg a
        ORDER BY pm.mes;
    """

    return sql, {"corte": corte, "ae_leads": AE_LEADS}


DATASET = {
    "key": "client_wins_outbound_history",
    "label": "Client Wins · Outbound (AE) · YTD + mensual",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "wins", "label": "Client wins (mes)", "type": "number"},
        {"key": "total_ytd", "label": "Total YTD", "type": "number"},
        {"key": "staffing_ytd", "label": "Staffing YTD", "type": "number"},
        {"key": "recruiting_ytd", "label": "Recruiting YTD", "type": "number"},
        {"key": "delta_vs_py", "label": "Δ vs año ant.", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
