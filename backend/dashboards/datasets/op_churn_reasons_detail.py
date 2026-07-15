"""Operations · detalle de candidatos caídos por razón (`inactive_reason`).

Misma cohorte que `op_churn_reasons` (= bajas de la card Candidate churn): una fila por
candidato-baja de Staffing con `end_d` en la ventana. Columnas: razón · candidato ·
account · posición · fecha de baja · recruiter. Los sin razón cargada → 'Sin razón'.
Alimenta el drawer del donut de razones de caída.
"""
from __future__ import annotations

from ._periods import window_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    # `reason` = razón clickeada en la dona (vacío = todas).
    reason = str(filters.get("reason") or "").strip()
    recruiter = str(filters.get("recruiter") or "").strip().lower()
    account = str(filters.get("account") or "").strip()
    lo, hi = window_bounds(filters)
    sql = """
        WITH ventana AS (
          SELECT %(w_lo)s::date AS win_ini, %(w_hi)s::date AS win_fin
        ),
        candidatos AS (
          SELECT
            ho.candidate_id,
            ho.account_id,
            ho.opportunity_id,
            NULLIF(TRIM(ho.inactive_reason), '') AS reason_raw,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(ho.start_date::text, '') IS NOT NULL THEN ho.start_date::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            CASE
              WHEN NULLIF(TRIM(ho.buyout_daterange), '') IS NOT NULL
                THEN TO_DATE(TRIM(ho.buyout_daterange) || '-01', 'YYYY-MM-DD')
              ELSE NULL
            END AS buyout_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          LEFT JOIN account a ON a.account_id = ho.account_id
          WHERE ho.candidate_id IS NOT NULL
            AND o.opp_model = 'Staffing'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
        ),
        bajas AS (
          SELECT DISTINCT ON (c.candidate_id)
            c.candidate_id, c.account_id, c.opportunity_id, c.reason_raw, c.end_d
          FROM candidatos c
          CROSS JOIN ventana v
          WHERE c.start_d IS NOT NULL
            AND c.end_d BETWEEN v.win_ini AND v.win_fin
            -- Solo bajas reales: excluir buyouts (igual que la card Candidate churn).
            AND NOT (c.buyout_d IS NOT NULL AND c.buyout_d >= DATE_TRUNC('month', c.end_d))
          ORDER BY c.candidate_id, c.end_d DESC NULLS LAST, c.opportunity_id DESC
        )
        SELECT
          COALESCE(b.reason_raw, 'Sin razón')                AS reason,
          COALESCE(c.name, '—')                              AS candidate_name,
          COALESCE(a.client_name, '—')                       AS client_name,
          COALESCE(o.opp_position_name, '—')                 AS opp_position_name,
          TO_CHAR(b.end_d, 'YYYY-MM-DD')                     AS inactive_date,
          COALESCE(NULLIF(TRIM(u.nickname), ''),
                   NULLIF(TRIM(u.user_name), ''),
                   NULLIF(TRIM(o.opp_hr_lead), ''),
                   '—')                                      AS recruiter
        FROM bajas b
        LEFT JOIN candidates c  ON c.candidate_id  = b.candidate_id
        LEFT JOIN account a     ON a.account_id     = b.account_id
        LEFT JOIN opportunity o ON o.opportunity_id = b.opportunity_id
        LEFT JOIN users u       ON LOWER(TRIM(u.email_vintti)) = LOWER(TRIM(o.opp_hr_lead))
        WHERE (%(reason)s = '' OR COALESCE(b.reason_raw, 'Sin razón') = %(reason)s)
          AND (%(recruiter)s = '' OR LOWER(TRIM(o.opp_hr_lead)) = %(recruiter)s)
          AND (%(account)s = '' OR TRIM(a.client_name) = %(account)s)
        ORDER BY COALESCE(b.reason_raw, 'Sin razón'), b.end_d DESC NULLS LAST, c.name;
    """
    return sql, {"reason": reason, "recruiter": recruiter, "account": account, "w_lo": lo, "w_hi": hi}


DATASET = {
    "key": "op_churn_reasons_detail",
    "label": "Operations · detalle caídas por razón",
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
