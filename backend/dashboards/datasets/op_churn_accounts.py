"""Operations · lista de accounts con caídas en la ventana (para el dropdown).

Una fila por account (client_name) con al menos un candidato caído con razón en la
ventana. `value` y `label` = TRIM(client_name). Alimenta el <select> de account del
donut de caídas.
"""
from __future__ import annotations

from ._periods import window_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    lo, hi = window_bounds(filters)
    sql = """
        SELECT
          TRIM(a.client_name) AS value,
          TRIM(a.client_name) AS label,
          COUNT(*)::int AS count
        FROM hire_opportunity ho
        LEFT JOIN account a     ON a.account_id      = ho.account_id
        LEFT JOIN opportunity o ON o.opportunity_id  = ho.opportunity_id
        WHERE NULLIF(TRIM(ho.inactive_reason), '') IS NOT NULL
          AND ho.carga_inactive BETWEEN %(w_lo)s AND %(w_hi)s
          AND NULLIF(TRIM(a.client_name), '') IS NOT NULL
          AND LOWER(TRIM(o.opp_hr_lead)) <> 'agustina.barbero@vintti.com'
        GROUP BY 1, 2
        ORDER BY label;
    """
    return sql, {"w_lo": lo, "w_hi": hi}


DATASET = {
    "key": "op_churn_accounts",
    "label": "Operations · accounts con caídas (ventana)",
    "dimensions": [
        {"key": "value", "label": "Account", "type": "string"},
        {"key": "label", "label": "Account", "type": "string"},
    ],
    "measures": [{"key": "count", "label": "Caídas", "type": "number"}],
    "default_filters": {},
    "query": query,
}
