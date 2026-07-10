"""Marketing · detalle Net revenue de UN bucket (semana/mes/Q/año clickeado)."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from ._now import today_ar


def _parse_date(value):
    if not value:
        return None
    parts = str(value).strip().split("-")
    try:
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        return None
    return None


def _gran(filters: dict) -> str:
    p = str(filters.get("periodo") or "mes").strip().lower()
    if p in ("semana", "week", "w"):
        return "semana"
    if p in ("q", "trimestre", "quarter"):
        return "q"
    if p in ("anio", "año", "year", "anual", "ytd"):
        return "anio"
    return "mes"


def _bucket_bounds(start: date, gran: str) -> date:
    if gran == "semana":
        return start + timedelta(days=6)
    if gran == "mes":
        return date(start.year, start.month, monthrange(start.year, start.month)[1])
    if gran == "q":
        m = start.month + 3
        y = start.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        return date(y, m, 1) - timedelta(days=1)
    return date(start.year, 12, 31)


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (_parse_date(filters.get("corte")) or _parse_date(filters.get("hasta"))
             or today_ar())
    gran = _gran(filters)
    # bucket = inicio del bucket clickeado; default = bucket actual.
    start = _parse_date(filters.get("bucket"))
    if not start:
        if gran == "semana":
            start = corte - timedelta(days=corte.weekday())
        elif gran == "q":
            start = date(corte.year, ((corte.month - 1) // 3) * 3 + 1, 1)
        elif gran == "anio":
            start = date(corte.year, 1, 1)
        else:
            start = date(corte.year, corte.month, 1)
    end = min(_bucket_bounds(start, gran), corte)

    sql = """
        WITH wins AS (
          SELECT o.opportunity_id, a.client_name, o.opp_position_name, TRIM(o.opp_model) AS model,
                 COALESCE(NULLIF(TRIM(a.where_come_from), ''), '(Sin origen)') AS origin,
                 NULLIF(o.opp_close_date::text, '')::date AS close_d
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND o.opp_model IN ('Staffing', 'Recruiting')
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
            AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral', 'import')
        )
        SELECT
          w.client_name, w.origin, w.model, w.opp_position_name,
          TO_CHAR(w.close_d, 'YYYY-MM-DD') AS close_date,
          COALESCE(SUM(CASE WHEN w.model = 'Recruiting' THEN COALESCE(ho.revenue, 0)
                            ELSE COALESCE(ho.fee, 0) END), 0)::bigint AS net_revenue
        FROM wins w
        LEFT JOIN hire_opportunity ho ON ho.opportunity_id = w.opportunity_id
        WHERE w.close_d BETWEEN %(ini)s::date AND %(fin)s::date
        GROUP BY w.client_name, w.origin, w.model, w.opp_position_name, w.close_d
        ORDER BY net_revenue DESC, w.client_name;
    """
    return sql, {"ini": start, "fin": end}


DATASET = {
    "key": "mkt_net_revenue_history_detail",
    "label": "Marketing · detalle Net revenue (bucket)",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "origin", "label": "Origin", "type": "string"},
        {"key": "model", "label": "Modelo", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "close_date", "label": "Close date", "type": "date"},
    ],
    "measures": [{"key": "net_revenue", "label": "Net revenue", "type": "currency"}],
    "default_filters": {"periodo": "mes"},
    "query": query,
}
