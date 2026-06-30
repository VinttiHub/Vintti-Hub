"""Operations · lista de recruiters con caídas en la ventana (para el dropdown).

Una fila por recruiter (opp_hr_lead resuelto a nickname vía `users`) con al menos un
candidato caído con razón en la ventana. `value` = email (lower) para el filtro;
`label` = nombre para mostrar. Alimenta el <select> del donut de caídas.
"""
from __future__ import annotations

from ._periods import window_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    lo, hi = window_bounds(filters)
    sql = """
        SELECT
          LOWER(TRIM(o.opp_hr_lead)) AS value,
          COALESCE(NULLIF(TRIM(u.nickname), ''),
                   NULLIF(TRIM(u.user_name), ''),
                   o.opp_hr_lead) AS label,
          COUNT(*)::int AS count
        FROM hire_opportunity ho
        LEFT JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
        LEFT JOIN users u ON LOWER(TRIM(u.email_vintti)) = LOWER(TRIM(o.opp_hr_lead))
        WHERE NULLIF(TRIM(ho.inactive_reason), '') IS NOT NULL
          AND ho.carga_inactive BETWEEN %(w_lo)s AND %(w_hi)s
          AND NULLIF(TRIM(o.opp_hr_lead), '') IS NOT NULL
          AND LOWER(TRIM(o.opp_hr_lead)) <> 'agustina.barbero@vintti.com'
        GROUP BY 1, 2
        ORDER BY label;
    """
    return sql, {"w_lo": lo, "w_hi": hi}


DATASET = {
    "key": "op_churn_recruiters",
    "label": "Operations · recruiters con caídas (ventana)",
    "dimensions": [
        {"key": "value", "label": "Recruiter email", "type": "string"},
        {"key": "label", "label": "Recruiter", "type": "string"},
    ],
    "measures": [{"key": "count", "label": "Caídas", "type": "number"}],
    "default_filters": {},
    "query": query,
}
