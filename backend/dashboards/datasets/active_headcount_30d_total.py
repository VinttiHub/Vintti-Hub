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


def _resolve_segment(filters: dict) -> str:
    raw = (
        filters.get("segmento")
        or filters.get("model")
        or filters.get("opp_model")
        or ""
    ).strip().lower()
    if raw in {"staffing", "staff"}:
        return "staffing"
    if raw in {"recruiting", "recru"}:
        return "recruiting"
    return "total"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or _parse_date(filters.get("fecha"))
        or datetime.utcnow().date()
    )
    segment = _resolve_segment(filters)

    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date AS corte_d,
            (%(corte)s::date - INTERVAL '29 day')::date AS win_ini,
            %(corte)s::date AS win_fin
        ),
        hire_rows AS (
          SELECT
            ('hire_' || ho.hire_opp_id::text) AS row_id,
            ho.candidate_id,
            LOWER(TRIM(o.opp_model)) AS model,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '') IS NOT NULL
                THEN NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '')::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(TRIM(CAST(ho.end_date AS TEXT)), '') IS NULL THEN NULL
              ELSE NULLIF(TRIM(CAST(ho.end_date AS TEXT)), '')::date
            END AS end_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.account_id IS NOT NULL
            AND LOWER(TRIM(o.opp_model)) IN ('staffing', 'recruiting')
        ),
        buyout_rows AS (
          SELECT
            ('buyout_' || b.buyout_id::text) AS row_id,
            NULL::integer AS candidate_id,
            'recruiting'::text AS model,
            CASE
              WHEN NULLIF(TRIM(CAST(b.start_date AS TEXT)), '') IS NOT NULL
                THEN NULLIF(TRIM(CAST(b.start_date AS TEXT)), '')::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN NULLIF(TRIM(CAST(b.end_date AS TEXT)), '') IS NOT NULL
                THEN NULLIF(TRIM(CAST(b.end_date AS TEXT)), '')::date
              ELSE NULL
            END AS end_d
          FROM buyouts b
          WHERE b.account_id IS NOT NULL
        ),
        all_rows AS (
          SELECT * FROM hire_rows
          UNION ALL
          SELECT * FROM buyout_rows
        ),
        activos AS (
          SELECT r.*
          FROM ventana v
          JOIN all_rows r
            ON r.start_d IS NOT NULL
           AND r.start_d <= v.win_fin
           AND COALESCE(r.end_d, DATE '9999-12-31') >= v.win_fin
          WHERE (%(segment)s = 'total' OR r.model = %(segment)s)
        )
        SELECT
          CASE
            WHEN %(segment)s = 'staffing'
              THEN COUNT(DISTINCT candidate_id)
                     FILTER (WHERE model = 'staffing' AND candidate_id IS NOT NULL)
            WHEN %(segment)s = 'recruiting'
              THEN COUNT(DISTINCT row_id) FILTER (WHERE model = 'recruiting')
            ELSE
              COUNT(DISTINCT candidate_id)
                FILTER (WHERE model = 'staffing' AND candidate_id IS NOT NULL)
              + COUNT(DISTINCT row_id) FILTER (WHERE model = 'recruiting')
          END::int AS active_count
        FROM activos;
    """

    return sql, {"corte": corte, "segment": segment}


DATASET = {
    "key": "active_headcount_30d_total",
    "label": "Active Headcount — 30d Rolling Total",
    "dimensions": [],
    "measures": [
        {"key": "active_count", "label": "Active (30d)", "type": "number"},
    ],
    "default_filters": {"model": ""},
    "query": query,
}
