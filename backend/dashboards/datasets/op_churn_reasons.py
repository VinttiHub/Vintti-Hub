"""Operations · % de razón por la que se caen los candidatos.

Distribución de `hire_opportunity.inactive_reason` entre los hires que tienen una
razón cargada (los '(sin razón)' se excluyen, por decisión del owner). Devuelve una
fila por razón con count y % del total — para un donut.
"""
from __future__ import annotations

from ._periods import window_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    # Ventana estándar del dashboard: Desde/Hasta > Mes > rolling 30d (corte).
    # Ancla en la fecha de baja `carga_inactive`.
    lo, hi = window_bounds(filters)
    sql = """
        SELECT
          TRIM(inactive_reason) AS reason,
          COUNT(*)::int AS count,
          ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 1)::float AS share_pct
        FROM hire_opportunity
        WHERE NULLIF(TRIM(inactive_reason), '') IS NOT NULL
          AND carga_inactive BETWEEN %(w_lo)s AND %(w_hi)s
        GROUP BY TRIM(inactive_reason)
        ORDER BY count DESC, reason;
    """
    return sql, {"w_lo": lo, "w_hi": hi}


DATASET = {
    "key": "op_churn_reasons",
    "label": "Operations · Razones de caída de candidatos (%)",
    "dimensions": [{"key": "reason", "label": "Razón", "type": "string"}],
    "measures": [
        {"key": "count", "label": "Candidatos", "type": "number"},
        {"key": "share_pct", "label": "% del total", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
