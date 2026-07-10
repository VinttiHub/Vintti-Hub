"""Marketing · Tasa de cierre por canal de adquisición — win rate por CLIENTE.

Para cada canal (origin = account.where_come_from, sin outbound, '(Sin origen)'
aparte), mide qué % de las cuentas DECIDIDAS terminaron como cliente.

Unidad = cuenta única (no oportunidad). Una cuenta cuenta como:
  - ganada (won)  → tiene ≥1 opp 'Close Win' cerrada en el período.
  - perdida (lost) → tiene ≥1 opp decidida en el período pero NINGUNA 'Close Win'
                     (solo 'Closed Lost').
  - en proceso     → solo opps abiertas → NO entra al denominador.

Tasa de cierre = won / (won + lost).  (Win rate de lo decidido, a nivel cuenta.)
Company-wide (todos los sales_lead). Ventana por FECHA DE CIERRE (opp_close_date),
seleccionable: semana / mes / q / año (default 'mes').
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
    """(ini, fin=corte, label) para el período en curso a la fecha."""
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
        WITH acct AS (
          SELECT a.account_id,
                 COALESCE(NULLIF(TRIM(a.where_come_from), ''), '(Sin origen)') AS origin
          FROM account a
          WHERE LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral', 'import')
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
        ),
        acct_decided AS (
          SELECT
            ac.account_id,
            ac.origin,
            BOOL_OR(TRIM(o.opp_stage) = 'Close Win') AS has_win
          FROM acct ac
          JOIN opportunity o ON o.account_id = ac.account_id
          WHERE TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost')
            AND NULLIF(o.opp_close_date::text, '')::date
                BETWEEN %(ini)s::date AND %(fin)s::date
          GROUP BY ac.account_id, ac.origin
        ),
        agg AS (
          SELECT
            origin,
            COUNT(*) FILTER (WHERE has_win)::int      AS won,
            COUNT(*) FILTER (WHERE NOT has_win)::int  AS lost,
            COUNT(*)::int                             AS decided
          FROM acct_decided
          GROUP BY origin
        )
        SELECT
          origin,
          won,
          lost,
          decided,
          ROUND(won::numeric * 100.0 / NULLIF(decided, 0), 1)::float AS close_rate,
          (won::text || '/' || decided::text)                        AS ratio,
          (SUM(won) OVER ()::text || '/' || SUM(decided) OVER ()::text) AS total_ratio,
          %(label)s::text                                            AS period_label
        FROM agg
        ORDER BY close_rate DESC, won DESC, origin;
    """
    return sql, {"ini": ini, "fin": fin, "label": label}


DATASET = {
    "key": "mkt_close_rate_by_channel",
    "label": "Marketing · Tasa de cierre por canal (win rate por cliente)",
    "dimensions": [
        {"key": "origin", "label": "Canal", "type": "string"},
        {"key": "period_label", "label": "Período", "type": "string"},
    ],
    "measures": [
        {"key": "won", "label": "Ganados", "type": "number"},
        {"key": "lost", "label": "Perdidos", "type": "number"},
        {"key": "decided", "label": "Decididos", "type": "number"},
        {"key": "close_rate", "label": "Tasa de cierre", "type": "percent"},
        {"key": "ratio", "label": "Ganados / Decididos", "type": "string"},
        {"key": "total_ratio", "label": "Total ganados / decididos", "type": "string"},
    ],
    "default_filters": {"periodo": "mes"},
    "query": query,
}
