"""Operations · Close wins mensuales (YTD) — TODOS los close wins (AM + AE).

Cuenta `opportunity.opp_stage = 'Close Win'` por mes de `opp_close_date`, del año en
curso (year_start → corte). SIN filtro de `opp_sales_lead` (incluye AM y AE) ni de
canal. Una fila por (mes, modelo) con `wins`, para barras apiladas Staffing/Recruiting.
"""
from __future__ import annotations

from datetime import date, datetime

from ._period import monthly_range


def _parse_date(value):
    if not value:
        return None
    parts = str(value).strip().split("-")
    try:
        if len(parts) >= 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    # Rango de meses: Mes/Desde-Hasta > Corte (ventana 30d) > YTD por defecto.
    lo, hi = monthly_range(filters)
    sql = """
        WITH params AS (
          SELECT DATE_TRUNC('month', %(lo)s::date)::date AS lo_mes,
                 %(lo)s::date AS lo_real,
                 %(hi)s::date AS hi_d
        ),
        meses AS (
          SELECT DATE_TRUNC('month', gs)::date AS mes
          FROM params p, generate_series(p.lo_mes, p.hi_d, INTERVAL '1 month') gs
        ),
        models AS (SELECT UNNEST(ARRAY['Staffing', 'Recruiting']) AS model),
        wins AS (
          SELECT TRIM(o.opp_model) AS model,
                 DATE_TRUNC('month', NULLIF(o.opp_close_date::text, '')::date)::date AS mes,
                 COUNT(*)::int AS wins
          FROM opportunity o
          LEFT JOIN account a ON a.account_id = o.account_id, params p
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
            AND TRIM(o.opp_model) IN ('Staffing', 'Recruiting')
            AND NULLIF(o.opp_close_date::text, '')::date BETWEEN p.lo_real AND p.hi_d
          GROUP BY 1, 2
        )
        SELECT
          TO_CHAR(m.mes, 'YYYY-MM-DD') AS bucket_start,
          (ARRAY['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'])[EXTRACT(MONTH FROM m.mes)::int] AS bucket_label,
          md.model AS model,
          COALESCE(w.wins, 0)::int AS wins
        FROM meses m
        CROSS JOIN models md
        LEFT JOIN wins w ON w.mes = m.mes AND w.model = md.model
        ORDER BY m.mes, md.model;
    """
    return sql, {"lo": lo, "hi": hi}


DATASET = {
    "key": "op_close_wins_monthly",
    "label": "Operations · Close wins mensuales (YTD, por modelo)",
    "dimensions": [
        {"key": "bucket_start", "label": "Mes", "type": "date"},
        {"key": "bucket_label", "label": "Mes", "type": "string"},
        {"key": "model", "label": "Modelo", "type": "string"},
    ],
    "measures": [{"key": "wins", "label": "Close wins", "type": "number"}],
    "default_filters": {},
    "query": query,
}
