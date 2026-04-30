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
    mes = (
        _parse_date(filters.get("fecha"))
        or _parse_date(filters.get("mes"))
        or _parse_date(filters.get("month"))
    )
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))
    modelo = _resolve_modelo(filters)
    stage = _resolve_stage(filters)

    sql = """
        WITH mes_pick AS (
          SELECT COALESCE(
            DATE_TRUNC('month', %(mes)s::date)::date,
            DATE_TRUNC('month', CURRENT_DATE)::date
          ) AS mes_pick
        ),
        base_nda AS (
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
            COALESCE(NULLIF(TRIM(a.where_come_from), ''), 'Unknown') AS lead_source,
            NULLIF(o.opp_close_date::text,'')::date AS close_d,
            TRIM(o.opp_stage) AS opp_stage
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          JOIN cohort c  ON c.account_id = o.account_id
          CROSS JOIN mes_pick mp
          WHERE o.account_id IS NOT NULL
            AND TRIM(o.opp_stage) IN ('Close Win','Closed Lost')
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND TRIM(LOWER(o.opp_sales_lead)) IN (
              'bahia@vintti.com',
              'mariano@vintti.com'
            )
            AND (%(modelo)s::text IS NULL OR LOWER(TRIM(o.opp_model)) = LOWER(%(modelo)s))
            AND DATE_TRUNC('month', NULLIF(o.opp_close_date::text,'')::date) = mp.mes_pick
            AND (%(desde)s::date IS NULL OR NULLIF(o.opp_close_date::text,'')::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR NULLIF(o.opp_close_date::text,'')::date <= %(hasta)s::date)
        ),
        filtered AS (
          SELECT *
          FROM closed_all
          WHERE %(stage)s = 'Total' OR opp_stage = %(stage)s
        ),
        totals AS (
          SELECT COUNT(*)::int AS total_filtered FROM filtered
        )
        SELECT
          f.lead_source,
          COUNT(*)::int AS total_closed_opps,
          t.total_filtered AS total_selected_stage,
          ROUND(COUNT(*)::numeric * 100.0 / NULLIF(t.total_filtered, 0), 1) AS pct_of_selected_stage,
          COUNT(*) FILTER (WHERE f.opp_stage = 'Close Win')::int   AS close_win,
          COUNT(*) FILTER (WHERE f.opp_stage = 'Closed Lost')::int AS closed_lost,
          COUNT(DISTINCT f.account_id)::int AS unique_clients
        FROM filtered f
        CROSS JOIN totals t
        GROUP BY f.lead_source, t.total_filtered
        ORDER BY total_closed_opps DESC, f.lead_source;
    """

    return sql, {
        "mes": mes,
        "desde": desde,
        "hasta": hasta,
        "modelo": modelo,
        "stage": stage,
    }


DATASET = {
    "key": "nda_lead_source_month",
    "label": "Lead Source x Close Win/Closed Lost — Mes",
    "dimensions": [
        {"key": "lead_source", "label": "Lead Source", "type": "string"},
    ],
    "measures": [
        {"key": "total_closed_opps", "label": "Total cerradas", "type": "number"},
        {"key": "total_selected_stage", "label": "Total stage", "type": "number"},
        {"key": "pct_of_selected_stage", "label": "% del stage", "type": "percent"},
        {"key": "close_win", "label": "Close Win", "type": "number"},
        {"key": "closed_lost", "label": "Closed Lost", "type": "number"},
        {"key": "unique_clients", "label": "Clientes únicos", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
