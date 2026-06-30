"""Operations · "One shot, one kill" — detalle por placement.

Una fila por placement (opp + candidato contratado) cuya opp tiene batch N°1, con el
batch donde apareció por primera vez el candidato contratado y si fue one-shot (batch
N°1). Filtros opcionales: recruiter, account. Excluye recruiters inactivos.
"""
from __future__ import annotations

from ._periods import window_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    lo, hi = window_bounds(filters)
    recruiter = str(filters.get("recruiter") or "").strip().lower()
    account = str(filters.get("account") or "").strip()
    sql = """
        WITH hires AS (
          SELECT
            ho.opportunity_id,
            ho.candidate_id,
            MIN(ho.carga_active) AS hire_date,
            o.opp_hr_lead,
            COALESCE(o.opp_position_name, '—') AS opp_position_name,
            COALESCE(a.client_name, '—')       AS client_name,
            COALESCE(c.name, '—')              AS candidate_name
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          LEFT JOIN account a    ON a.account_id    = ho.account_id
          LEFT JOIN candidates c ON c.candidate_id  = ho.candidate_id
          WHERE ho.carga_active BETWEEN %(w_lo)s AND %(w_hi)s
            AND LOWER(TRIM(o.opp_hr_lead)) <> 'agustina.barbero@vintti.com'
          GROUP BY ho.opportunity_id, ho.candidate_id, o.opp_hr_lead,
                   o.opp_position_name, a.client_name, c.name
        ),
        firstbatch AS (
          SELECT b.opportunity_id, cb.candidate_id, MIN(b.batch_number) AS batch_num
          FROM batch b
          JOIN candidates_batches cb ON cb.batch_id = b.batch_id
          GROUP BY b.opportunity_id, cb.candidate_id
        ),
        oppb1 AS (
          SELECT DISTINCT opportunity_id FROM batch WHERE batch_number = 1
        )
        SELECT
          TO_CHAR(h.hire_date::date, 'YYYY-MM-DD')             AS hire_date,
          h.opp_position_name,
          h.client_name,
          COALESCE(NULLIF(TRIM(u.nickname), ''),
                   NULLIF(TRIM(u.user_name), ''),
                   h.opp_hr_lead, '—')                         AS recruiter,
          h.candidate_name,
          fb.batch_num                                         AS batch_num,
          CASE WHEN fb.batch_num = 1 THEN 'Sí' ELSE 'No' END   AS one_shot
        FROM hires h
        JOIN oppb1 ON oppb1.opportunity_id = h.opportunity_id
        LEFT JOIN firstbatch fb
          ON fb.opportunity_id = h.opportunity_id AND fb.candidate_id = h.candidate_id
        LEFT JOIN users u ON LOWER(TRIM(u.email_vintti)) = LOWER(TRIM(h.opp_hr_lead))
        WHERE (%(recruiter)s = '' OR LOWER(TRIM(h.opp_hr_lead)) = %(recruiter)s)
          AND (%(account)s = '' OR TRIM(h.client_name) = %(account)s)
        ORDER BY h.hire_date DESC NULLS LAST, h.client_name;
    """
    return sql, {"w_lo": lo, "w_hi": hi, "recruiter": recruiter, "account": account}


DATASET = {
    "key": "op_one_shot_kill_detail",
    "label": "Operations · One shot one kill — detalle por placement",
    "dimensions": [
        {"key": "hire_date", "label": "Fecha hire", "type": "date"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "recruiter", "label": "Recruiter", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "one_shot", "label": "One-shot", "type": "string"},
    ],
    "measures": [
        {"key": "batch_num", "label": "Batch del hire", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
