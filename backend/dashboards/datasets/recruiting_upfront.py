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
        if len(parts) >= 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    desde = (
        _parse_date(filters.get("desde"))
        or _parse_date(filters.get("from"))
        or date(2023, 1, 1)
    )
    hasta = (
        _parse_date(filters.get("hasta"))
        or _parse_date(filters.get("to"))
        or datetime.utcnow().date().replace(day=1)
    )
    if hasta < desde:
        hasta = desde

    sql = """
        WITH base AS (
          SELECT
            DATE_TRUNC('month', o.opp_close_date)::date AS mes_cierre,
            SUM(ho.revenue)::numeric AS monto_recruiting
          FROM hire_opportunity ho
          JOIN opportunity o
            ON ho.opportunity_id = o.opportunity_id
          WHERE o.opp_model = 'Recruiting'
            AND o.opp_close_date IS NOT NULL
            AND ho.revenue IS NOT NULL
          GROUP BY 1
        )
        SELECT
          to_char(mes_cierre, 'YYYY-MM') AS mes_cierre,
          monto_recruiting::bigint        AS monto_recruiting
        FROM base
        WHERE mes_cierre >= DATE_TRUNC('month', %(desde)s::date)
          AND mes_cierre <= DATE_TRUNC('month', %(hasta)s::date)
        ORDER BY mes_cierre;
    """

    return sql, {"desde": desde, "hasta": hasta}


DATASET = {
    "key": "recruiting_upfront",
    "label": "Recruiting Upfront Payment (by close month)",
    "dimensions": [
        {"key": "mes_cierre", "label": "Close Month", "type": "date"},
    ],
    "measures": [
        {"key": "monto_recruiting", "label": "Monto Recruiting", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
