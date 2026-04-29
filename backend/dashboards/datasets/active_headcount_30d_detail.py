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
            'hire'::text AS source,
            LOWER(TRIM(o.opp_model)) AS model,
            ho.account_id,
            ho.candidate_id,
            a.client_name,
            c.name AS candidate_name,
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
          JOIN account a     ON a.account_id = ho.account_id
          LEFT JOIN candidates c ON c.candidate_id = ho.candidate_id
          WHERE ho.account_id IS NOT NULL
            AND LOWER(TRIM(o.opp_model)) IN ('staffing', 'recruiting')
        ),
        buyout_rows AS (
          SELECT
            ('buyout_' || b.buyout_id::text) AS row_id,
            'buyout'::text AS source,
            'recruiting'::text AS model,
            b.account_id,
            NULL::integer AS candidate_id,
            a.client_name,
            NULL::text AS candidate_name,
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
          JOIN account a ON a.account_id = b.account_id
          WHERE b.account_id IS NOT NULL
        ),
        all_rows AS (
          SELECT * FROM hire_rows
          UNION ALL
          SELECT * FROM buyout_rows
        )
        SELECT
          v.corte_d AS cutoff_date,
          INITCAP(r.model) AS model,
          r.client_name,
          COALESCE(
            r.candidate_name,
            CASE WHEN r.source = 'buyout' THEN '(buyout)' ELSE NULL END
          ) AS candidate_name,
          r.start_d AS start_date
        FROM ventana v
        JOIN all_rows r
          ON r.start_d IS NOT NULL
         AND r.start_d <= v.win_fin
         AND COALESCE(r.end_d, DATE '9999-12-31') >= v.win_fin
        WHERE (%(segment)s = 'total' OR r.model = %(segment)s)
        ORDER BY r.model, r.client_name, r.candidate_name NULLS LAST;
    """

    return sql, {"corte": corte, "segment": segment}


DATASET = {
    "key": "active_headcount_30d_detail",
    "label": "Active Headcount — 30d Rolling Detail",
    "dimensions": [
        {"key": "cutoff_date", "label": "Cutoff Date", "type": "date"},
        {"key": "model", "label": "Model", "type": "string"},
        {"key": "client_name", "label": "Client", "type": "string"},
        {"key": "candidate_name", "label": "Candidate", "type": "string"},
        {"key": "start_date", "label": "Start Date", "type": "date"},
    ],
    "measures": [],
    "default_filters": {"model": ""},
    "query": query,
}
