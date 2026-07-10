"""Marketing · Oportunidades GENERADAS segmentadas por industria — ranking por período.

Opps generadas = TODAS las opps (sin filtro de stage) de cuentas que entraron al CRM
(account.creation_date) en el período en curso. Mide demanda por industria: un cliente
de una industria puede generar varias opps (ej. pidió 3 puestos → 3 opps).
Segmentadas por account.industry. Filtra el origen marketing (excluye outbound, etc.).
Devuelve count + expected_revenue por industria, con totales (constantes).
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
        WITH base AS (
          SELECT
            COALESCE(NULLIF(TRIM(a.industry), ''), '(Sin industria)') AS industry,
            COALESCE(o.expected_revenue, 0)::numeric AS rev
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE a.creation_date IS NOT NULL
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND a.creation_date::date BETWEEN %(ini)s::date AND %(fin)s::date
            AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral', 'import')
        ),
        agg AS (
          SELECT industry, COUNT(*)::int AS c, COALESCE(SUM(rev), 0)::bigint AS rev
          FROM base GROUP BY industry
        )
        SELECT
          industry,
          c AS count,
          rev AS expected_revenue,
          ROUND(100.0 * c / NULLIF(SUM(c) OVER (), 0), 1)::float AS share_pct,
          SUM(c) OVER ()::int AS total,
          SUM(rev) OVER ()::bigint AS total_revenue,
          %(label)s::text AS period_label
        FROM agg
        ORDER BY c DESC, industry;
    """
    return sql, {"ini": ini, "fin": fin, "label": label}


DATASET = {
    "key": "mkt_open_opps_by_industry",
    "label": "Marketing · Opps generadas por industria (ranking, período)",
    "dimensions": [
        {"key": "industry", "label": "Industria", "type": "string"},
        {"key": "period_label", "label": "Período", "type": "string"},
    ],
    "measures": [
        {"key": "count", "label": "Opps generadas", "type": "number"},
        {"key": "expected_revenue", "label": "Expected revenue", "type": "currency"},
        {"key": "share_pct", "label": "% del total", "type": "percent"},
        {"key": "total", "label": "Total opps", "type": "number"},
        {"key": "total_revenue", "label": "Total expected revenue", "type": "currency"},
    ],
    "default_filters": {"periodo": "mes"},
    "query": query,
}
