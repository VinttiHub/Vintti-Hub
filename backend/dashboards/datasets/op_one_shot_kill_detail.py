"""Operations · "One shot, one kill" — detalle por win.

Una fila por WIN de NDA→CW (Close Win · sales_lead M+B+Lara · por opp_close_date),
con el candidato contratado "de mejor batch" (el de menor primer-batch), el batch en
que apareció y si fue one-shot (batch N°1). Reconcilia 1:1 con el KPI global.
Filtros opcionales: recruiter, account.
"""
from __future__ import annotations

from ._periods import window_bounds


SALES_LEADS = ("bahia@vintti.com", "mariano@vintti.com", "lara@vintti.com")


def _resolve_modelo(filters: dict) -> str | None:
    raw = (
        filters.get("modelo")
        or filters.get("modelo1")
        or filters.get("model")
        or filters.get("opp_model")
        or ""
    ).strip().lower()
    if raw in {"staffing", "staff"}:
        return "Staffing"
    if raw in {"recruiting", "recru"}:
        return "Recruiting"
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    lo, hi = window_bounds(filters)
    modelo = _resolve_modelo(filters)
    canal = (filters.get("canal") or filters.get("channel") or "").strip().lower() or None
    recruiter = str(filters.get("recruiter") or "").strip().lower()
    account = str(filters.get("account") or "").strip()
    sql = """
        WITH wins AS (
          SELECT
            o.opportunity_id,
            o.opp_hr_lead,
            COALESCE(o.opp_position_name, '—') AS opp_position_name,
            COALESCE(a.client_name, '—')       AS client_name,
            NULLIF(o.opp_close_date::text,'')::date AS close_d
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND NULLIF(o.opp_close_date::text,'')::date BETWEEN %(w_lo)s AND %(w_hi)s
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
            AND (%(canal)s::text IS NULL OR LOWER(TRIM(COALESCE(a.where_come_from,''))) = %(canal)s)
        ),
        firstbatch AS (
          SELECT b.opportunity_id, cb.candidate_id, MIN(b.batch_number) AS batch_num
          FROM batch b
          JOIN candidates_batches cb ON cb.batch_id = b.batch_id
          GROUP BY b.opportunity_id, cb.candidate_id
        ),
        hires AS (   -- candidatos contratados por win, con su primer-batch
          SELECT
            ho.opportunity_id,
            ho.candidate_id,
            MIN(ho.carga_active) AS hire_date,
            fb.batch_num
          FROM hire_opportunity ho
          LEFT JOIN firstbatch fb
            ON fb.opportunity_id = ho.opportunity_id AND fb.candidate_id = ho.candidate_id
          GROUP BY ho.opportunity_id, ho.candidate_id, fb.batch_num
        ),
        best AS (    -- un hire por win: el de menor primer-batch (el "mejor tiro")
          SELECT DISTINCT ON (h.opportunity_id)
            h.opportunity_id, h.candidate_id, h.hire_date, h.batch_num
          FROM hires h
          ORDER BY h.opportunity_id, h.batch_num ASC NULLS LAST, h.hire_date ASC
        )
        SELECT
          TO_CHAR(COALESCE(b.hire_date::date, w.close_d), 'YYYY-MM-DD') AS hire_date,
          w.opp_position_name,
          w.client_name,
          COALESCE(NULLIF(TRIM(u.nickname), ''),
                   NULLIF(TRIM(u.user_name), ''),
                   w.opp_hr_lead, '—')                         AS recruiter,
          COALESCE(c.name, '—')                                AS candidate_name,
          b.batch_num                                          AS batch_num,
          CASE WHEN b.batch_num = 1 THEN 'Sí' ELSE 'No' END    AS one_shot
        FROM wins w
        LEFT JOIN best b        ON b.opportunity_id = w.opportunity_id
        LEFT JOIN candidates c  ON c.candidate_id = b.candidate_id
        LEFT JOIN users u       ON LOWER(TRIM(u.email_vintti)) = LOWER(TRIM(w.opp_hr_lead))
        WHERE (%(recruiter)s = '' OR LOWER(TRIM(w.opp_hr_lead)) = %(recruiter)s)
          AND (%(account)s = '' OR TRIM(w.client_name) = %(account)s)
        ORDER BY w.close_d DESC NULLS LAST, w.client_name;
    """
    return sql, {"w_lo": lo, "w_hi": hi, "sales_leads": SALES_LEADS,
                 "modelo": modelo, "canal": canal,
                 "recruiter": recruiter, "account": account}


DATASET = {
    "key": "op_one_shot_kill_detail",
    "label": "Operations · One shot one kill — detalle por win",
    "dimensions": [
        {"key": "hire_date", "label": "Fecha", "type": "date"},
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
