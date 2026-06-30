"""Operations · lista de recruiters con rechazos en la ventana (para el dropdown).

Una fila por recruiter (opp_hr_lead resuelto a nickname vía `users`) que tiene al
menos un candidato rechazado en la ventana. `value` = email (lower) para el filtro;
`label` = nombre para mostrar. Alimenta el <select> del donut de rechazos.
"""
from __future__ import annotations

from .op_rejection_reasons import REASON_CASE
from ._periods import window_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    lo, hi = window_bounds(filters)
    sql = f"""
        SELECT
          LOWER(TRIM(o.opp_hr_lead)) AS value,
          COALESCE(NULLIF(TRIM(u.nickname), ''),
                   NULLIF(TRIM(u.user_name), ''),
                   o.opp_hr_lead) AS label,
          COUNT(*)::int AS count
        FROM candidates_batches cb
        LEFT JOIN batch b       ON b.batch_id       = cb.batch_id
        LEFT JOIN opportunity o ON o.opportunity_id = b.opportunity_id
        LEFT JOIN users u       ON LOWER(TRIM(u.email_vintti)) = LOWER(TRIM(o.opp_hr_lead))
        WHERE b.presentation_date BETWEEN %(w_lo)s AND %(w_hi)s
          AND NULLIF(TRIM(o.opp_hr_lead), '') IS NOT NULL
          AND LOWER(TRIM(o.opp_hr_lead)) <> 'agustina.barbero@vintti.com'
          AND {REASON_CASE.format(col='cb.status')} IS NOT NULL
        GROUP BY 1, 2
        ORDER BY label;
    """
    return sql, {"w_lo": lo, "w_hi": hi}


DATASET = {
    "key": "op_rejection_recruiters",
    "label": "Operations · recruiters con rechazos (ventana)",
    "dimensions": [
        {"key": "value", "label": "Recruiter email", "type": "string"},
        {"key": "label", "label": "Recruiter", "type": "string"},
    ],
    "measures": [{"key": "count", "label": "Rechazos", "type": "number"}],
    "default_filters": {},
    "query": query,
}
