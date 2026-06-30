"""Operations · lista de accounts con rechazos en la ventana (para el dropdown).

Una fila por account (client_name) con al menos un candidato rechazado en la ventana.
`value` y `label` = TRIM(client_name). Alimenta el <select> de account del donut de rechazos.
"""
from __future__ import annotations

from .op_rejection_reasons import REASON_CASE
from ._periods import window_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    lo, hi = window_bounds(filters)
    sql = f"""
        SELECT
          TRIM(a.client_name) AS value,
          TRIM(a.client_name) AS label,
          COUNT(*)::int AS count
        FROM candidates_batches cb
        LEFT JOIN batch b       ON b.batch_id       = cb.batch_id
        LEFT JOIN opportunity o ON o.opportunity_id = b.opportunity_id
        LEFT JOIN account a     ON a.account_id      = o.account_id
        WHERE b.presentation_date BETWEEN %(w_lo)s AND %(w_hi)s
          AND NULLIF(TRIM(a.client_name), '') IS NOT NULL
          AND LOWER(TRIM(o.opp_hr_lead)) <> 'agustina.barbero@vintti.com'
          AND {REASON_CASE.format(col='cb.status')} IS NOT NULL
        GROUP BY 1, 2
        ORDER BY label;
    """
    return sql, {"w_lo": lo, "w_hi": hi}


DATASET = {
    "key": "op_rejection_accounts",
    "label": "Operations · accounts con rechazos (ventana)",
    "dimensions": [
        {"key": "value", "label": "Account", "type": "string"},
        {"key": "label", "label": "Account", "type": "string"},
    ],
    "measures": [{"key": "count", "label": "Rechazos", "type": "number"}],
    "default_filters": {},
    "query": query,
}
