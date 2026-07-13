"""Operations · lista de accounts con caídas en el churn M3 (para el dropdown).

Una fila por account (client_name) con al menos un candidato-baja del cohorte M3 con
razón cargada. `value`/`label` = TRIM(client_name). Alimenta el <select> de account de
la dona "Razones de caída · churn M3". Ver [[op_churn_reasons_m3]].
"""
from __future__ import annotations

from datetime import timedelta

from .op_churn_reasons_m3 import COHORT_CTES, _WINDOW_DAYS, _corte


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = _corte(filters)
    win_ini = corte - timedelta(days=_WINDOW_DAYS - 1)
    sql = COHORT_CTES + """
        SELECT
          TRIM(a.client_name) AS value,
          TRIM(a.client_name) AS label,
          COUNT(*)::int AS count
        FROM baja_hire bh
        LEFT JOIN account a ON a.account_id = bh.account_id
        WHERE NULLIF(bh.reason, '') IS NOT NULL
          AND NULLIF(TRIM(a.client_name), '') IS NOT NULL
        GROUP BY 1, 2
        ORDER BY label;
    """
    return sql, {"corte": corte, "win_ini": win_ini}


DATASET = {
    "key": "op_churn_m3_accounts",
    "label": "Operations · accounts con caídas churn M3 (dropdown)",
    "dimensions": [
        {"key": "value", "label": "Account", "type": "string"},
        {"key": "label", "label": "Account", "type": "string"},
    ],
    "measures": [{"key": "count", "label": "Caídas", "type": "number"}],
    "default_filters": {},
    "query": query,
}
