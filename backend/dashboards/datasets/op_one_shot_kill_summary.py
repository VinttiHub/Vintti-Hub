"""Operations · "One shot, one kill" — KPI global.

Alineado a las WINS de NDA→CW: la población es las oportunidades Close Win con
opp_sales_lead M+B+Lara, ancladas en opp_close_date y con los mismos filtros
(modelo/canal) que `nda_close_win_30d_summary`. Se cuenta POR WIN (no por placement),
así el denominador `placements` coincide exactamente con las wins de NDA→CW.
Numerador `one_shot_count` = wins cuyo candidato contratado provino del batch N°1.

NOTA: a diferencia de la versión anterior, NO se excluyen recruiters inactivos ni se
exige que la opp tenga batch N°1 — porque el total debe matchear las wins de NDA→CW
(que no aplican ese filtro). Una win sin batch N°1 o sin hire cuenta como "no one-shot".
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
    sql = """
        WITH wins AS (   -- misma población que nda_close_win_30d_summary (Close Win)
          SELECT o.opportunity_id
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND NULLIF(o.opp_close_date::text,'')::date BETWEEN %(w_lo)s AND %(w_hi)s
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
            AND (%(canal)s::text IS NULL OR LOWER(TRIM(COALESCE(a.where_come_from,''))) = %(canal)s)
        ),
        firstbatch AS (   -- primer batch donde apareció cada candidato por opp
          SELECT b.opportunity_id, cb.candidate_id, MIN(b.batch_number) AS batch_num
          FROM batch b
          JOIN candidates_batches cb ON cb.batch_id = b.batch_id
          GROUP BY b.opportunity_id, cb.candidate_id
        ),
        scored AS (   -- una fila por win; one_shot = algún hire vino del batch N°1
          SELECT
            w.opportunity_id,
            BOOL_OR(fb.batch_num = 1) AS one_shot
          FROM wins w
          LEFT JOIN hire_opportunity ho ON ho.opportunity_id = w.opportunity_id
          LEFT JOIN firstbatch fb
            ON fb.opportunity_id = ho.opportunity_id AND fb.candidate_id = ho.candidate_id
          GROUP BY w.opportunity_id
        )
        SELECT
          COUNT(*)::int                                        AS placements,
          COUNT(*) FILTER (WHERE one_shot)::int                AS one_shot_count,
          ROUND(100.0 * COUNT(*) FILTER (WHERE one_shot)
                / NULLIF(COUNT(*), 0), 1)::float               AS conversion_pct
        FROM scored;
    """
    return sql, {"w_lo": lo, "w_hi": hi, "sales_leads": SALES_LEADS,
                 "modelo": modelo, "canal": canal}


DATASET = {
    "key": "op_one_shot_kill_summary",
    "label": "Operations · One shot one kill (KPI) — sobre wins NDA→CW",
    "dimensions": [],
    "measures": [
        {"key": "conversion_pct", "label": "% one-shot", "type": "percent"},
        {"key": "one_shot_count", "label": "One-shot", "type": "number"},
        {"key": "placements", "label": "Close Win", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
