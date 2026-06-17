"""Operations · detalle de Close wins de UN mes (bucket clickeado en las barras).

Lista todos los Close Wins (AM + AE, Staffing + Recruiting) cuyo `opp_close_date`
cae en el mes del bucket seleccionado. Filtro `bucket` = inicio del mes clickeado
(lo setea el drawer de barras apiladas); default = mes actual.
"""
from __future__ import annotations

from datetime import date


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
    bucket = _parse_date(filters.get("bucket")) or _parse_date(filters.get("mes"))
    sql = """
        WITH params AS (
          SELECT COALESCE(DATE_TRUNC('month', %(bucket)s::date)::date,
                          DATE_TRUNC('month', CURRENT_DATE)::date) AS mes_ini
        )
        SELECT
          TO_CHAR(o.opp_close_date, 'YYYY-MM-DD') AS close_date,
          a.client_name,
          o.opp_position_name,
          TRIM(o.opp_model) AS model,
          COALESCE(NULLIF(TRIM(o.opp_sales_lead), ''), '—') AS sales_lead
        FROM opportunity o
        JOIN account a ON a.account_id = o.account_id
        CROSS JOIN params p
        WHERE TRIM(o.opp_stage) = 'Close Win'
          AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
          AND o.opp_close_date >= p.mes_ini
          AND o.opp_close_date <  (p.mes_ini + INTERVAL '1 month')
          AND TRIM(o.opp_model) IN ('Staffing', 'Recruiting')
        ORDER BY o.opp_close_date DESC, TRIM(o.opp_model), a.client_name;
    """
    return sql, {"bucket": bucket}


DATASET = {
    "key": "op_close_wins_monthly_detail",
    "label": "Operations · detalle Close wins del mes",
    "dimensions": [
        {"key": "close_date", "label": "Close date", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "model", "label": "Modelo", "type": "string"},
        {"key": "sales_lead", "label": "Sales lead", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
