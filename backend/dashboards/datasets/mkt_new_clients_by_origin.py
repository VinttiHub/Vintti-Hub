"""Marketing · New active clients aperturados por origin — ranking por período.

New active client = cuenta cuyo PRIMER Close Win (opp_close_date) cae en el
período (se volvió cliente en ese período). Segmentado por origin
(account.where_come_from). Período a la fecha: semana / mes / q / anio.
"""
from __future__ import annotations

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


def period_bounds(filters: dict) -> tuple[date, date, str]:
    corte = (_parse_date(filters.get("corte")) or _parse_date(filters.get("hasta"))
             or today_ar())
    p = str(filters.get("periodo") or filters.get("period") or "mes").strip().lower()
    if p in ("semana", "week", "w"):
        return corte - timedelta(days=corte.weekday()), corte, "Semana"
    if p in ("q", "trimestre", "quarter"):
        q_month = ((corte.month - 1) // 3) * 3 + 1
        return date(corte.year, q_month, 1), corte, "Trimestre"
    if p in ("anio", "año", "year", "anual", "ytd"):
        return date(corte.year, 1, 1), corte, "Año"
    return date(corte.year, corte.month, 1), corte, "Mes"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    ini, fin, label = period_bounds(filters)
    sql = """
        WITH first_close AS (
          SELECT o.account_id, MIN(NULLIF(o.opp_close_date::text, '')::date) AS first_d
          FROM opportunity o
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
          GROUP BY o.account_id
        ),
        base AS (
          SELECT COALESCE(NULLIF(TRIM(a.where_come_from), ''), '(Sin origen)') AS origin
          FROM first_close fc
          JOIN account a ON a.account_id = fc.account_id
          WHERE fc.first_d BETWEEN %(ini)s::date AND %(fin)s::date
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral', 'import')
        ),
        agg AS (SELECT origin, COUNT(*)::int AS c FROM base GROUP BY origin)
        SELECT
          origin,
          c AS count,
          ROUND(100.0 * c / NULLIF(SUM(c) OVER (), 0), 1)::float AS share_pct,
          SUM(c) OVER ()::int AS total,
          %(label)s::text AS period_label
        FROM agg
        ORDER BY c DESC, origin;
    """
    return sql, {"ini": ini, "fin": fin, "label": label}


DATASET = {
    "key": "mkt_new_clients_by_origin",
    "label": "Marketing · New active clients por origin (ranking, período)",
    "dimensions": [
        {"key": "origin", "label": "Origin", "type": "string"},
        {"key": "period_label", "label": "Período", "type": "string"},
    ],
    "measures": [
        {"key": "count", "label": "Clientes nuevos", "type": "number"},
        {"key": "share_pct", "label": "% del total", "type": "percent"},
        {"key": "total", "label": "Total clientes nuevos", "type": "number"},
    ],
    "default_filters": {"periodo": "mes"},
    "query": query,
}
