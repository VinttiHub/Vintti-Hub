from __future__ import annotations

from datetime import date


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.split("-")
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
        or filters.get("model")
        or filters.get("opp_model")
        or ""
    ).strip().lower()
    if raw in {"staffing", "staff"}:
        return "Staffing"
    if raw in {"recruiting", "recru"}:
        return "Recruiting"
    return None


def _resolve_stage(filters: dict) -> str:
    raw = (filters.get("opp_stage") or "").strip()
    if raw in ("Close Win", "Closed Lost"):
        return raw
    return "Total"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    desde = _parse_date(filters.get("desde")) or _parse_date(filters.get("from"))
    hasta = _parse_date(filters.get("hasta")) or _parse_date(filters.get("to"))
    modelo = _resolve_modelo(filters)
    opp_stage = _resolve_stage(filters)

    sql = """
        WITH base_nda AS (
          SELECT
            o.account_id,
            NULLIF(o.nda_signature_or_start_date::text,'')::date AS nda_d
          FROM opportunity o
          WHERE o.account_id IS NOT NULL
            AND NULLIF(o.nda_signature_or_start_date::text,'') IS NOT NULL
            AND TRIM(LOWER(o.opp_sales_lead)) IN (
              'bahia@vintti.com',
              'mariano@vintti.com'
            )
            AND (%(modelo)s::text IS NULL OR LOWER(TRIM(o.opp_model)) = LOWER(%(modelo)s))
        ),
        cohort AS (
          SELECT account_id, MIN(nda_d) AS first_nda_d
          FROM base_nda
          GROUP BY 1
        ),
        closed_all AS (
          SELECT
            o.opportunity_id,
            o.account_id,
            NULLIF(o.opp_close_date::text,'')::date AS close_d,
            TRIM(o.opp_stage) AS opp_stage
          FROM opportunity o
          JOIN cohort c ON c.account_id = o.account_id
          WHERE o.account_id IS NOT NULL
            AND TRIM(o.opp_stage) IN ('Close Win','Closed Lost')
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND TRIM(LOWER(o.opp_sales_lead)) IN (
              'bahia@vintti.com',
              'mariano@vintti.com'
            )
            AND (%(modelo)s::text IS NULL OR LOWER(TRIM(o.opp_model)) = LOWER(%(modelo)s))
            AND (%(desde)s::date IS NULL OR NULLIF(o.opp_close_date::text,'')::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR NULLIF(o.opp_close_date::text,'')::date <= %(hasta)s::date)
        )
        SELECT
          TO_CHAR(DATE_TRUNC('month', close_d), 'YYYY-MM') AS mes_close,
          COUNT(*)::int AS total_closed_opps,
          COUNT(*) FILTER (WHERE opp_stage = 'Close Win')::int   AS close_win,
          COUNT(*) FILTER (WHERE opp_stage = 'Closed Lost')::int AS closed_lost,
          ROUND(
            CASE
              WHEN %(opp_stage)s = 'Closed Lost' THEN
                COUNT(*) FILTER (WHERE opp_stage = 'Closed Lost')::numeric * 100.0
                / NULLIF(COUNT(*), 0)
              WHEN %(opp_stage)s IN ('Close Win', 'Total') THEN
                COUNT(*) FILTER (WHERE opp_stage = 'Close Win')::numeric * 100.0
                / NULLIF(COUNT(*), 0)
              ELSE NULL
            END,
            1
          ) AS conversion_pct,
          COUNT(DISTINCT account_id)::int AS unique_clients_closed_that_month
        FROM closed_all
        GROUP BY 1
        ORDER BY 1;
    """

    return sql, {"desde": desde, "hasta": hasta, "modelo": modelo, "opp_stage": opp_stage}


DATASET = {
    "key": "nda_to_clients_history",
    "label": "NDA a Clientes — Conversion por mes",
    "dimensions": [
        {"key": "mes_close", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "total_closed_opps", "label": "Total cerradas", "type": "number"},
        {"key": "close_win", "label": "Close Win", "type": "number"},
        {"key": "closed_lost", "label": "Closed Lost", "type": "number"},
        {"key": "conversion_pct", "label": "Conversion %", "type": "percent"},
        {"key": "unique_clients_closed_that_month", "label": "Clientes únicos cerrados", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
