"""Operations · detalle de candidatos caídos por razón (`inactive_reason`).

Una fila por hire inactivo CON razón cargada: razón · candidato · account · posición ·
fecha de baja. Ordenado por razón para leer fácil cada grupo. Alimenta el drawer del
donut de razones de caída.
"""
from __future__ import annotations

from ._periods import window_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    # `reason` = razón clickeada en la dona (vacío = todas).
    reason = str(filters.get("reason") or "").strip()
    lo, hi = window_bounds(filters)
    sql = """
        SELECT
          TRIM(ho.inactive_reason) AS reason,
          COALESCE(c.name, '—') AS candidate_name,
          COALESCE(a.client_name, '—') AS client_name,
          COALESCE(o.opp_position_name, '—') AS opp_position_name,
          TO_CHAR(ho.carga_inactive::date, 'YYYY-MM-DD') AS inactive_date
        FROM hire_opportunity ho
        LEFT JOIN candidates c  ON c.candidate_id  = ho.candidate_id
        LEFT JOIN account a     ON a.account_id     = ho.account_id
        LEFT JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
        WHERE NULLIF(TRIM(ho.inactive_reason), '') IS NOT NULL
          AND (%(reason)s = '' OR TRIM(ho.inactive_reason) = %(reason)s)
          AND ho.carga_inactive BETWEEN %(w_lo)s AND %(w_hi)s
        ORDER BY TRIM(ho.inactive_reason), ho.carga_inactive DESC NULLS LAST, c.name;
    """
    return sql, {"reason": reason, "w_lo": lo, "w_hi": hi}


DATASET = {
    "key": "op_churn_reasons_detail",
    "label": "Operations · detalle caídas por razón",
    "dimensions": [
        {"key": "reason", "label": "Razón", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "client_name", "label": "Account", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "inactive_date", "label": "Fecha baja", "type": "date"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
