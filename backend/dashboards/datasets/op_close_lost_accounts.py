"""Operations · lista de accounts con Close Lost en la ventana (para el dropdown).

Una fila por account (client_name) con al menos una opp Closed Lost con motivo en la
ventana. `value` y `label` = TRIM(client_name). Alimenta el <select> de account del
donut de Close Lost.
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
        FROM opportunity o
        LEFT JOIN account a ON a.account_id = o.account_id
        WHERE TRIM(o.opp_stage) = 'Closed Lost'
          AND COALESCE(a.vintti_internal, FALSE) = FALSE
          AND NULLIF(TRIM(o.motive_close_lost), '') IS NOT NULL
          AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
          AND NULLIF(o.opp_close_date::text, '')::date BETWEEN %(w_lo)s AND %(w_hi)s
          AND NULLIF(TRIM(a.client_name), '') IS NOT NULL
        GROUP BY 1, 2
        ORDER BY label;
    """
    return sql, {"w_lo": lo, "w_hi": hi}


DATASET = {
    "key": "op_close_lost_accounts",
    "label": "Operations · accounts con Close Lost (ventana)",
    "dimensions": [
        {"key": "value", "label": "Account", "type": "string"},
        {"key": "label", "label": "Account", "type": "string"},
    ],
    "measures": [{"key": "count", "label": "Close Lost", "type": "number"}],
    "default_filters": {},
    "query": query,
}
