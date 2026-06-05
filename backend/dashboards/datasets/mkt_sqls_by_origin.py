"""Marketing · SQLs aperturados por origin — ranking por período.

SQL = cuenta que entra al CRM (account.creation_date). Segmentado por origin
(account.where_come_from). Período (a la fecha): semana / mes / q / anio.
Devuelve una fila por origin con count, share_pct y total (constante).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


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
    """(ini, fin=corte, label) para el período en curso a la fecha."""
    corte = (_parse_date(filters.get("corte")) or _parse_date(filters.get("hasta"))
             or datetime.utcnow().date())
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
        WITH base AS (
          SELECT COALESCE(NULLIF(TRIM(a.where_come_from), ''), '(Sin origen)') AS origin
          FROM account a
          WHERE a.creation_date IS NOT NULL
            AND a.creation_date::date BETWEEN %(ini)s::date AND %(fin)s::date
            AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) <> 'outbound'
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
    "key": "mkt_sqls_by_origin",
    "label": "Marketing · SQLs por origin (ranking, período)",
    "dimensions": [
        {"key": "origin", "label": "Origin", "type": "string"},
        {"key": "period_label", "label": "Período", "type": "string"},
    ],
    "measures": [
        {"key": "count", "label": "SQLs", "type": "number"},
        {"key": "share_pct", "label": "% del total", "type": "percent"},
        {"key": "total", "label": "Total SQLs", "type": "number"},
    ],
    "default_filters": {"periodo": "mes"},
    "query": query,
}
