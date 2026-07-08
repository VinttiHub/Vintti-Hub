"""Operations · "One shot, one kill" — tendencia mensual.

% de one-shot por mes (mes de opp_close_date). Misma definición/población que el KPI:
población = wins de NDA→CW (Close Win · sales_lead M+B+Lara), numerador = wins cuyo
candidato contratado provino del batch N°1. Acota opcionalmente con desde/hasta.
"""
from __future__ import annotations

from datetime import date


SALES_LEADS = ("bahia@vintti.com", "mariano@vintti.com", "lara@vintti.com")


def _parse_date(value) -> date | None:
    if not value:
        return None
    parts = str(value).strip().split("-")
    try:
        if len(parts) >= 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


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
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))
    modelo = _resolve_modelo(filters)
    canal = (filters.get("canal") or filters.get("channel") or "").strip().lower() or None
    sql = """
        WITH wins AS (
          SELECT
            o.opportunity_id,
            DATE_TRUNC('month', NULLIF(o.opp_close_date::text,'')::date)::date AS mes
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND (%(desde)s::date IS NULL OR NULLIF(o.opp_close_date::text,'')::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR NULLIF(o.opp_close_date::text,'')::date <= %(hasta)s::date)
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
            AND (%(canal)s::text IS NULL OR LOWER(TRIM(COALESCE(a.where_come_from,''))) = %(canal)s)
        ),
        firstbatch AS (
          SELECT b.opportunity_id, cb.candidate_id, MIN(b.batch_number) AS batch_num
          FROM batch b
          JOIN candidates_batches cb ON cb.batch_id = b.batch_id
          GROUP BY b.opportunity_id, cb.candidate_id
        ),
        scored AS (
          SELECT w.opportunity_id, w.mes, BOOL_OR(fb.batch_num = 1) AS one_shot
          FROM wins w
          LEFT JOIN hire_opportunity ho ON ho.opportunity_id = w.opportunity_id
          LEFT JOIN firstbatch fb
            ON fb.opportunity_id = ho.opportunity_id AND fb.candidate_id = ho.candidate_id
          GROUP BY w.opportunity_id, w.mes
        )
        SELECT
          TO_CHAR(mes, 'YYYY-MM-DD')                           AS mes,
          COUNT(*)::int                                        AS placements,
          COUNT(*) FILTER (WHERE one_shot)::int                AS one_shot_count,
          ROUND(100.0 * COUNT(*) FILTER (WHERE one_shot)
                / NULLIF(COUNT(*), 0), 1)::float               AS conversion_pct
        FROM scored
        GROUP BY mes
        ORDER BY mes;
    """
    return sql, {"desde": desde, "hasta": hasta, "sales_leads": SALES_LEADS,
                 "modelo": modelo, "canal": canal}


DATASET = {
    "key": "op_one_shot_kill_history",
    "label": "Operations · One shot one kill — por mes",
    "dimensions": [{"key": "mes", "label": "Mes", "type": "date"}],
    "measures": [
        {"key": "conversion_pct", "label": "% one-shot", "type": "percent"},
        {"key": "one_shot_count", "label": "One-shot", "type": "number"},
        {"key": "placements", "label": "Close Win", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
