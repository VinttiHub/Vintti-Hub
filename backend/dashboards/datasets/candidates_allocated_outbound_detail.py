"""Detalle Candidates Allocated · Outbound (AE) · YTD — una fila por hire."""
from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar


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
        or today_ar()
    )
    sql = """
        WITH params AS (
          SELECT %(corte)s::date AS corte_d, DATE_TRUNC('year', %(corte)s::date)::date AS year_start
        ),
        hires AS (
          SELECT
            a.client_name, COALESCE(c.name,'') AS candidate_name,
            o.opp_position_name,
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
          TO_CHAR(h.start_d, 'YYYY-MM-DD') AS start_date,
          h.client_name,
          h.candidate_name,
          h.opp_position_name
        FROM hires h CROSS JOIN params p
        WHERE h.start_d IS NOT NULL
          AND h.start_d >= p.year_start AND h.start_d <= p.corte_d
        ORDER BY h.start_d DESC, h.client_name;
    """
    return sql, {"corte": corte, "ae_leads": AE_LEADS}


DATASET = {
    "key": "candidates_allocated_outbound_detail",
    "label": "Candidates Allocated · Outbound (AE) · detalle YTD",
    "dimensions": [
        {"key": "start_date", "label": "Start", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "candidate_name", "label": "Contractor", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
