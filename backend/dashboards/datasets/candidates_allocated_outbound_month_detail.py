"""Candidates Allocated · Outbound (AE) · detalle del mes seleccionado (filtro `mes`)."""
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
        ),
        hires AS (
          SELECT
            a.client_name, COALESCE(c.name,'') AS candidate_name, o.opp_position_name,
            CASE WHEN h.carga_active IS NOT NULL THEN h.carga_active::date
                 ELSE NULLIF(h.start_date::text,'')::date END AS start_d
          FROM hire_opportunity h
          JOIN opportunity o ON o.opportunity_id = h.opportunity_id
          JOIN account a ON a.account_id = h.account_id
          LEFT JOIN candidates c ON c.candidate_id = h.candidate_id
          WHERE h.candidate_id IS NOT NULL
            AND LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'outbound'
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(ae_leads)s
        )
        SELECT
          h.candidate_name,
          h.client_name,
          h.opp_position_name,
          TO_CHAR(h.start_d, 'YYYY-MM-DD') AS start_date
        FROM hires h CROSS JOIN params p
        WHERE h.start_d IS NOT NULL
          AND h.start_d >= p.mes_ini
          AND h.start_d <  (p.mes_ini + INTERVAL '1 month')
        ORDER BY h.client_name, h.candidate_name;
    """
    return sql, {"mes": mes, "ae_leads": AE_LEADS}


DATASET = {
    "key": "candidates_allocated_outbound_month_detail",
    "label": "Candidates Allocated · Outbound (AE) · detalle del mes",
    "dimensions": [
        {"key": "candidate_name", "label": "Contractor", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "start_date", "label": "Start", "type": "date"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
