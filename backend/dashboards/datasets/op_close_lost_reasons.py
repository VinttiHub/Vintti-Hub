"""Operations · % de razón de Close Lost de oportunidades (opportunity.motive_close_lost).

Distribución de `opportunity.motive_close_lost` entre las opps en stage 'Closed Lost'
que tienen un motivo cargado (se excluyen los vacíos). Ancla en la fecha de cierre
(`opp_close_date`). Para un donut, hermano de op_churn_reasons / op_rejection_reasons.
"""
from __future__ import annotations

from ._periods import window_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    # Ventana estándar del dashboard: Desde/Hasta > Mes > rolling 30d.
    lo, hi = window_bounds(filters)
    account = str(filters.get("account") or "").strip()
    reason = str(filters.get("reason") or "").strip()
    recruiter = str(filters.get("recruiter") or "").strip().lower()
    sql = """
        SELECT
          COALESCE(NULLIF(TRIM(o.motive_close_lost), ''), 'Sin razón') AS reason,
          COUNT(*)::int AS count,
          ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 1)::float AS share_pct
        FROM opportunity o
        LEFT JOIN account a ON a.account_id = o.account_id
        WHERE TRIM(o.opp_stage) = 'Closed Lost'
          AND COALESCE(a.vintti_internal, FALSE) = FALSE
          AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
          AND NULLIF(o.opp_close_date::text, '')::date BETWEEN %(w_lo)s AND %(w_hi)s
          AND (%(account)s = '' OR TRIM(a.client_name) = %(account)s)
          AND (%(reason)s = '' OR COALESCE(NULLIF(TRIM(o.motive_close_lost), ''), 'Sin razón') = %(reason)s)
          AND (%(recruiter)s = '' OR LOWER(TRIM(o.opp_hr_lead)) = %(recruiter)s)
        GROUP BY COALESCE(NULLIF(TRIM(o.motive_close_lost), ''), 'Sin razón')
        ORDER BY count DESC, reason;
    """
    return sql, {"w_lo": lo, "w_hi": hi, "account": account, "reason": reason, "recruiter": recruiter}


DATASET = {
    "key": "op_close_lost_reasons",
    "label": "Operations · Razones de Close Lost (%)",
    "dimensions": [{"key": "reason", "label": "Razón", "type": "string"}],
    "measures": [
        {"key": "count", "label": "Opps", "type": "number"},
        {"key": "share_pct", "label": "% del total", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
