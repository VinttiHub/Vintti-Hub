"""Operations · detalle de rechazos por razón (candidates_batches.status negativos).

Una fila por candidato rechazado: razón · candidato · account · posición. Filtro
`reason` = razón clickeada en la dona (vacío = todas). Alimenta el drawer del donut.
"""
from __future__ import annotations

from .op_rejection_reasons import REASON_CASE
from ._periods import window_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    reason = str(filters.get("reason") or "").strip()
    lo, hi = window_bounds(filters)
    sql = f"""
        WITH base AS (
          SELECT
            {REASON_CASE.format(col='cb.status')} AS reason,
            COALESCE(c.name, '—') AS candidate_name,
            COALESCE(a.client_name, '—') AS client_name,
            COALESCE(o.opp_position_name, '—') AS opp_position_name
          FROM candidates_batches cb
          LEFT JOIN batch b       ON b.batch_id       = cb.batch_id
          LEFT JOIN opportunity o ON o.opportunity_id = b.opportunity_id
          LEFT JOIN account a     ON a.account_id      = o.account_id
          LEFT JOIN candidates c  ON c.candidate_id    = cb.candidate_id
          WHERE b.presentation_date BETWEEN %(w_lo)s AND %(w_hi)s
        )
        SELECT reason, candidate_name, client_name, opp_position_name
        FROM base
        WHERE reason IS NOT NULL
          AND (%(reason)s = '' OR reason = %(reason)s)
        ORDER BY reason, candidate_name;
    """
    return sql, {"reason": reason, "w_lo": lo, "w_hi": hi}


DATASET = {
    "key": "op_rejection_reasons_detail",
    "label": "Operations · detalle rechazos por razón",
    "dimensions": [
        {"key": "reason", "label": "Razón", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "client_name", "label": "Account", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
