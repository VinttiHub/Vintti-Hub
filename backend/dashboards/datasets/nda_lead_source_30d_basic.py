from __future__ import annotations

from datetime import date, datetime


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.split("-")
    try:
        if len(parts) == 3:
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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or datetime.utcnow().date()
    )
    modelo = _resolve_modelo(filters)

    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date AS corte_d,
            (%(corte)s::date - INTERVAL '30 days')::date AS win_ini,
            %(corte)s::date AS win_fin
        ),
        base_nda AS (
          SELECT
            o.account_id,
            MIN(NULLIF(o.nda_signature_or_start_date::text,'')::date) AS first_nda_d
          FROM opportunity o
          WHERE o.account_id IS NOT NULL
            AND NULLIF(o.nda_signature_or_start_date::text,'') IS NOT NULL
            AND TRIM(LOWER(o.opp_sales_lead)) IN (
              'bahia@vintti.com',
              'mariano@vintti.com'
            )
          GROUP BY 1
        ),
        closed_all AS (
          SELECT
            o.opportunity_id,
            o.account_id,
            COALESCE(NULLIF(TRIM(a.where_come_from), ''), 'Unknown') AS lead_source,
            o.opp_model,
            NULLIF(o.opp_close_date::text,'')::date AS close_d,
            TRIM(o.opp_stage) AS opp_stage
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          JOIN base_nda c ON c.account_id = o.account_id
          WHERE o.account_id IS NOT NULL
            AND TRIM(o.opp_stage) IN ('Close Win','Closed Lost')
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND TRIM(LOWER(o.opp_sales_lead)) IN (
              'bahia@vintti.com',
              'mariano@vintti.com'
            )
        ),
        windowed AS (
          SELECT w.*
          FROM closed_all w
          CROSS JOIN ventana v
          WHERE w.close_d BETWEEN v.win_ini AND v.win_fin
            AND (%(modelo)s::text IS NULL OR LOWER(TRIM(w.opp_model)) = LOWER(%(modelo)s))
        ),
        totals AS (
          SELECT COUNT(*)::int AS total FROM windowed
        )
        SELECT
          w.lead_source,
          COUNT(*)::int AS total_closed_opps,
          ROUND(COUNT(*)::numeric * 100.0 / NULLIF(t.total, 0), 1) AS pct_of_total,
          COUNT(*) FILTER (WHERE w.opp_stage = 'Close Win')::int   AS close_win,
          COUNT(*) FILTER (WHERE w.opp_stage = 'Closed Lost')::int AS closed_lost
        FROM windowed w
        CROSS JOIN totals t
        GROUP BY w.lead_source, t.total
        ORDER BY total_closed_opps DESC, w.lead_source;
    """

    return sql, {"corte": corte, "modelo": modelo}


DATASET = {
    "key": "nda_lead_source_30d_basic",
    "label": "Lead Source — Ventana 30 días (sin stage filter)",
    "dimensions": [
        {"key": "lead_source", "label": "Lead Source", "type": "string"},
    ],
    "measures": [
        {"key": "total_closed_opps", "label": "Total cerradas", "type": "number"},
        {"key": "pct_of_total", "label": "% del total", "type": "percent"},
        {"key": "close_win", "label": "Close Win", "type": "number"},
        {"key": "closed_lost", "label": "Closed Lost", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
