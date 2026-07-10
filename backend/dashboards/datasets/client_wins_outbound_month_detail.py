"""Client Wins · Outbound (AE) · detalle del mes seleccionado (filtro `mes`)."""
from __future__ import annotations

from datetime import date


AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")


def _parse_date(value):
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.split("-")
    try:
        if len(parts) >= 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    mes = _parse_date(filters.get("mes")) or _parse_date(filters.get("mes_click"))

    sql = """
        WITH params AS (
          SELECT COALESCE(DATE_TRUNC('month', %(mes)s::date)::date,
                          DATE_TRUNC('month', CURRENT_DATE)::date) AS mes_ini
        )
        SELECT
          a.client_name,
          TRIM(o.opp_model) AS model,
          o.opp_position_name,
          TO_CHAR(o.opp_close_date, 'YYYY-MM-DD') AS close_date
        FROM opportunity o
        JOIN account a ON a.account_id = o.account_id
        CROSS JOIN params p
        WHERE TRIM(o.opp_stage) = 'Close Win'
          AND COALESCE(a.vintti_internal, FALSE) = FALSE
          AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
          AND o.opp_close_date >= p.mes_ini
          AND o.opp_close_date <  (p.mes_ini + INTERVAL '1 month')
          AND LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'outbound'
          AND TRIM(LOWER(o.opp_sales_lead)) IN %(ae_leads)s
        ORDER BY model, a.client_name;
    """
    return sql, {"mes": mes, "ae_leads": AE_LEADS}


DATASET = {
    "key": "client_wins_outbound_month_detail",
    "label": "Client Wins · Outbound (AE) · detalle del mes",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "model", "label": "Modelo", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "close_date", "label": "Close date", "type": "date"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
