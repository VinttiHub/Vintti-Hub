"""Detalle Client Wins · Outbound (AE) · YTD — una fila por close win."""
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
          SELECT %(corte)s::date AS corte_d, DATE_TRUNC('year', %(corte)s::date)::date AS year_start
        )
        SELECT
          TO_CHAR(o.opp_close_date, 'YYYY-MM-DD') AS close_date,
          a.client_name,
          TRIM(o.opp_model) AS model,
          o.opp_position_name
        FROM opportunity o
        JOIN account a ON a.account_id = o.account_id
        CROSS JOIN params p
        WHERE TRIM(o.opp_stage) = 'Close Win'
          AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
          AND o.opp_close_date >= p.year_start AND o.opp_close_date <= p.corte_d
          AND LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'outbound'
          AND TRIM(LOWER(o.opp_sales_lead)) IN %(ae_leads)s
        ORDER BY o.opp_close_date DESC, a.client_name;
    """
    return sql, {"corte": corte, "ae_leads": AE_LEADS}


DATASET = {
    "key": "client_wins_outbound_detail",
    "label": "Client Wins · Outbound (AE) · detalle YTD",
    "dimensions": [
        {"key": "close_date", "label": "Close date", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "model", "label": "Modelo", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
