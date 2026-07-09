"""Operations · detalle de opps Close Lost por razón (`motive_close_lost`).

Una fila por opp Closed Lost CON motivo cargado: razón · account · posición · fecha de
cierre · owner (opp_sales_lead resuelto a nombre). Ordenado por razón. Alimenta el
drawer del donut de razones de Close Lost.
"""
from __future__ import annotations

from ._periods import window_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    # `reason` = razón clickeada en la dona (vacío = todas).
    reason = str(filters.get("reason") or "").strip()
    account = str(filters.get("account") or "").strip()
    recruiter = str(filters.get("recruiter") or "").strip().lower()
    lo, hi = window_bounds(filters)
    sql = """
        SELECT
          TRIM(o.motive_close_lost) AS reason,
          COALESCE(a.client_name, '—') AS client_name,
          COALESCE(o.opp_position_name, '—') AS opp_position_name,
          TO_CHAR(NULLIF(o.opp_close_date::text, '')::date, 'YYYY-MM-DD') AS close_date,
          COALESCE(NULLIF(TRIM(us.nickname), ''),
                   NULLIF(TRIM(us.user_name), ''),
                   NULLIF(TRIM(o.opp_sales_lead), ''),
                   '—') AS owner,
          COALESCE(NULLIF(TRIM(ur.nickname), ''),
                   NULLIF(TRIM(ur.user_name), ''),
                   NULLIF(TRIM(o.opp_hr_lead), ''),
                   '—') AS recruiter
        FROM opportunity o
        LEFT JOIN account a ON a.account_id = o.account_id
        LEFT JOIN users us  ON LOWER(TRIM(us.email_vintti)) = LOWER(TRIM(o.opp_sales_lead))
        LEFT JOIN users ur  ON LOWER(TRIM(ur.email_vintti)) = LOWER(TRIM(o.opp_hr_lead))
        WHERE TRIM(o.opp_stage) = 'Closed Lost'
          AND NULLIF(TRIM(o.motive_close_lost), '') IS NOT NULL
          AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
          AND NULLIF(o.opp_close_date::text, '')::date BETWEEN %(w_lo)s AND %(w_hi)s
          AND (%(reason)s = '' OR TRIM(o.motive_close_lost) = %(reason)s)
          AND (%(account)s = '' OR TRIM(a.client_name) = %(account)s)
          AND (%(recruiter)s = '' OR LOWER(TRIM(o.opp_hr_lead)) = %(recruiter)s)
        ORDER BY TRIM(o.motive_close_lost),
                 NULLIF(o.opp_close_date::text, '')::date DESC NULLS LAST,
                 a.client_name;
    """
    return sql, {"reason": reason, "account": account, "recruiter": recruiter, "w_lo": lo, "w_hi": hi}


DATASET = {
    "key": "op_close_lost_reasons_detail",
    "label": "Operations · detalle Close Lost por razón",
    "dimensions": [
        {"key": "reason", "label": "Razón", "type": "string"},
        {"key": "client_name", "label": "Account", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "close_date", "label": "Fecha cierre", "type": "date"},
        {"key": "owner", "label": "Owner", "type": "string"},
        {"key": "recruiter", "label": "Recruiter", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
