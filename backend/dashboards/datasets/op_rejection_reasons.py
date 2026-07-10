"""Operations · % de razón de rechazo de candidatos (candidates_batches.status).

Distribución del status del candidato en el pipeline de la opp, SOLO las razones
NEGATIVAS (rechazos). Se excluyen Client Interviewing / Candidate Testing / hired /
vacíos. Normaliza mayúsculas/espacios y mapea a etiquetas canónicas. Para un donut.
"""
from __future__ import annotations

from ._periods import window_bounds

# CASE compartido: normaliza el status a su etiqueta canónica negativa (o NULL si
# no es una razón de rechazo que queramos contar).
REASON_CASE = """
    CASE LOWER(TRIM({col}))
      WHEN 'rejected by sales'                   THEN 'Rejected By Sales'
      WHEN 'client rejected cv'                  THEN 'Client Rejected CV'
      WHEN 'client rejected after interviewing'  THEN 'Client Rejected after interviewing'
      WHEN 'candidate failed test'               THEN 'Candidate Failed Test'
      WHEN 'candidate abandoned process'         THEN 'Candidate abandoned process'
      ELSE NULL
    END
"""


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    # Ventana estándar (Desde/Hasta > Mes > rolling 30d). Proxy de fecha del rechazo
    # = fecha de presentación del batch (candidates_batches no guarda fecha).
    lo, hi = window_bounds(filters)
    recruiter = str(filters.get("recruiter") or "").strip().lower()
    account = str(filters.get("account") or "").strip()
    reason = str(filters.get("reason") or "").strip()
    sql = f"""
        WITH mapped AS (
          SELECT {REASON_CASE.format(col='cb.status')} AS reason
          FROM candidates_batches cb
          LEFT JOIN batch b       ON b.batch_id       = cb.batch_id
          LEFT JOIN opportunity o ON o.opportunity_id = b.opportunity_id
          LEFT JOIN account a     ON a.account_id      = o.account_id
          WHERE b.presentation_date BETWEEN %(w_lo)s AND %(w_hi)s
            AND (%(recruiter)s = '' OR LOWER(TRIM(o.opp_hr_lead)) = %(recruiter)s)
            AND (%(account)s = '' OR TRIM(a.client_name) = %(account)s)
            -- Excluir recruiters inactivos (ya no trabajan en Vintti)
            AND LOWER(TRIM(o.opp_hr_lead)) <> 'agustina.barbero@vintti.com'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
        )
        SELECT reason,
               COUNT(*)::int AS count,
               ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 1)::float AS share_pct
        FROM mapped
        WHERE reason IS NOT NULL
          AND (%(reason)s = '' OR reason = %(reason)s)
        GROUP BY reason
        ORDER BY count DESC, reason;
    """
    return sql, {"w_lo": lo, "w_hi": hi, "recruiter": recruiter, "account": account, "reason": reason}


DATASET = {
    "key": "op_rejection_reasons",
    "label": "Operations · Razones de rechazo de candidatos (%)",
    "dimensions": [{"key": "reason", "label": "Razón", "type": "string"}],
    "measures": [
        {"key": "count", "label": "Candidatos", "type": "number"},
        {"key": "share_pct", "label": "% del total", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
