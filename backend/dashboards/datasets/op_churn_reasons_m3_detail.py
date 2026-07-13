"""Operations · detalle de caídas del churn M3 por razón (`inactive_reason`).

Sibling de `op_churn_reasons_m3`: mismo cohorte M3 (candidatos de Staffing que se
fueron en sus primeros 3 meses de la ventana 90d), pero una fila por candidato-baja
con razón cargada: razón · candidato · account · posición · fecha de baja · recruiter.
Alimenta el drawer de la dona "Razones de caída · churn M3".
"""
from __future__ import annotations

from datetime import timedelta

from .op_churn_reasons_m3 import COHORT_CTES, _WINDOW_DAYS, _corte


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = _corte(filters)
    win_ini = corte - timedelta(days=_WINDOW_DAYS - 1)
    reason = str(filters.get("reason") or "").strip()
    recruiter = str(filters.get("recruiter") or "").strip().lower()
    account = str(filters.get("account") or "").strip()
    sql = COHORT_CTES + """
        SELECT
          bh.reason AS reason,
          COALESCE(c.name, '—') AS candidate_name,
          COALESCE(a.client_name, '—') AS client_name,
          COALESCE(o.opp_position_name, '—') AS opp_position_name,
          TO_CHAR(bh.end_d, 'YYYY-MM-DD') AS inactive_date,
          COALESCE(NULLIF(TRIM(u.nickname), ''),
                   NULLIF(TRIM(u.user_name), ''),
                   NULLIF(TRIM(o.opp_hr_lead), ''),
                   '—') AS recruiter
        FROM baja_hire bh
        LEFT JOIN candidates c  ON c.candidate_id  = bh.candidate_id
        LEFT JOIN account a     ON a.account_id     = bh.account_id
        LEFT JOIN opportunity o ON o.opportunity_id = bh.opportunity_id
        LEFT JOIN users u       ON LOWER(TRIM(u.email_vintti)) = LOWER(TRIM(o.opp_hr_lead))
        WHERE NULLIF(bh.reason, '') IS NOT NULL
          AND (%(reason)s = '' OR bh.reason = %(reason)s)
          AND (%(recruiter)s = '' OR LOWER(TRIM(o.opp_hr_lead)) = %(recruiter)s)
          AND (%(account)s = '' OR TRIM(a.client_name) = %(account)s)
        ORDER BY bh.reason, bh.end_d DESC NULLS LAST, c.name;
    """
    return sql, {
        "corte": corte, "win_ini": win_ini,
        "reason": reason, "recruiter": recruiter, "account": account,
    }


DATASET = {
    "key": "op_churn_reasons_m3_detail",
    "label": "Operations · detalle caídas churn M3 por razón",
    "dimensions": [
        {"key": "reason", "label": "Razón", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "client_name", "label": "Account", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "inactive_date", "label": "Fecha baja", "type": "date"},
        {"key": "recruiter", "label": "Recruiter", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
