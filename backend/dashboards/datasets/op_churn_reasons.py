"""Operations · % de razón por la que se caen los candidatos.

Población = la MISMA cohorte de bajas REALES que la card "Candidate churn"
(`candidate_churn_30d_summary`, campo `bajas_real`): candidatos de **Staffing**
(cuenta no-interna) distintos cuyo `end_d = COALESCE(carga_inactive, end_date)` cae
en la ventana, EXCLUYENDO buyouts. Así el total de la dona coincide 1:1 con las
"bajas reales" de esa card (no cuenta buyouts, igual que el churn).

De cada candidato-baja se toma la razón (`inactive_reason`) del hire dado de baja
más reciente; los que no tienen razón cargada se agrupan como 'Sin razón' — NO se
excluyen — para que el total refleje el churn real. Una fila por razón (count + share).

Nota: a diferencia de las donas de rechazo/close-lost, acá NO se excluye a
`agustina.barbero` (la card de churn tampoco lo hace) para poder reconciliar exacto.
"""
from __future__ import annotations

from ._periods import window_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    # Ventana estándar del dashboard: Desde/Hasta > Mes > rolling 30d.
    lo, hi = window_bounds(filters)
    recruiter = str(filters.get("recruiter") or "").strip().lower()
    account = str(filters.get("account") or "").strip()
    reason = str(filters.get("reason") or "").strip()
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
        -- Una fila por candidato-baja (mismo criterio que candidate_churn_30d_summary):
        -- end_d en la ventana. Se toma el hire dado de baja más reciente como
        -- representante (su razón / account / opp).
        bajas AS (
          SELECT DISTINCT ON (c.candidate_id)
            c.candidate_id, c.account_id, c.opportunity_id, c.reason_raw, c.end_d
          FROM candidatos c
          CROSS JOIN ventana v
          WHERE c.start_d IS NOT NULL
            AND c.end_d BETWEEN v.win_ini AND v.win_fin
            -- Solo BAJAS REALES: excluir buyouts (igual que bajas_real de la card
            -- Candidate churn). Buyout = buyout_daterange en/después del mes de baja.
            AND NOT (c.buyout_d IS NOT NULL AND c.buyout_d >= DATE_TRUNC('month', c.end_d))
          ORDER BY c.candidate_id, c.end_d DESC NULLS LAST, c.opportunity_id DESC
        )
        SELECT
          COALESCE(b.reason_raw, 'Sin razón') AS reason,
          COUNT(*)::int AS count,
          ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 1)::float AS share_pct
        FROM bajas b
        LEFT JOIN opportunity o ON o.opportunity_id = b.opportunity_id
        LEFT JOIN account a     ON a.account_id      = b.account_id
        WHERE (%(recruiter)s = '' OR LOWER(TRIM(o.opp_hr_lead)) = %(recruiter)s)
          AND (%(account)s = '' OR TRIM(a.client_name) = %(account)s)
          AND (%(reason)s = '' OR COALESCE(b.reason_raw, 'Sin razón') = %(reason)s)
        GROUP BY COALESCE(b.reason_raw, 'Sin razón')
        ORDER BY count DESC, reason;
    """
    return sql, {"w_lo": lo, "w_hi": hi, "recruiter": recruiter, "account": account, "reason": reason}


DATASET = {
    "key": "op_churn_reasons",
    "label": "Operations · Razones de caída de candidatos (%)",
    "dimensions": [{"key": "reason", "label": "Razón", "type": "string"}],
    "measures": [
        {"key": "count", "label": "Candidatos", "type": "number"},
        {"key": "share_pct", "label": "% del total", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
