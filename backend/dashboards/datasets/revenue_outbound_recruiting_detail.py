"""Detalle Recruiting del Revenue Outbound (AE+AM) — close wins del año.

Una fila por close win Recruiting del año (YTD), canal Outbound + book AE+AM, con
su revenue one-time (ho.revenue). Sirve para verificar el Recruiting acumulado.
"""
from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar


AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")
AM_LEADS = ("lara@vintti.com",)


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
        )
        SELECT
          TO_CHAR(o.opp_close_date, 'YYYY-MM-DD') AS close_date,
          a.client_name,
          o.opp_position_name,
          COALESCE(SUM(COALESCE(ho.revenue,0)),0)::bigint AS revenue
        FROM opportunity o
        JOIN account a ON a.account_id = o.account_id
        LEFT JOIN hire_opportunity ho ON ho.opportunity_id = o.opportunity_id
        CROSS JOIN params p
        WHERE o.opp_model = 'Recruiting'
          AND COALESCE(a.vintti_internal, FALSE) = FALSE
          AND TRIM(o.opp_stage) = 'Close Win'
          AND o.opp_close_date IS NOT NULL
          AND o.opp_close_date >= p.year_start AND o.opp_close_date <= p.corte_d
          AND LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'outbound'
          AND (TRIM(LOWER(o.opp_sales_lead)) IN %(ae_leads)s
               OR TRIM(LOWER(a.account_manager)) IN %(am_leads)s)
        GROUP BY o.opp_close_date, a.client_name, o.opp_position_name, o.opportunity_id
        ORDER BY o.opp_close_date DESC, revenue DESC;
    """

    return sql, {"corte": corte, "ae_leads": AE_LEADS, "am_leads": AM_LEADS}


DATASET = {
    "key": "revenue_outbound_recruiting_detail",
    "label": "Revenue Outbound — Detalle Recruiting (closes YTD)",
    "dimensions": [
        {"key": "close_date", "label": "Close date", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
    ],
    "measures": [
        {"key": "revenue", "label": "Revenue", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
