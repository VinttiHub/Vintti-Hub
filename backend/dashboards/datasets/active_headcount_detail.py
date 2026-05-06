from __future__ import annotations

from datetime import date, datetime


def _parse_ym(value: str | None) -> date | None:
    if not value:
        return None
    parts = str(value).split("-")
    if len(parts) < 2:
        return None
    try:
        return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None


def _resolve_modelo(filters: dict) -> str:
    raw = (
        filters.get("modelo")
        or filters.get("model")
        or filters.get("segmento")
        or filters.get("opp_model")
        or ""
    ).strip().lower()
    if raw in {"staffing", "staff"}:
        return "staffing"
    if raw in {"recruiting", "recru"}:
        return "recruiting"
    return "total"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    target = (
        _parse_ym(filters.get("fecha"))
        or _parse_ym(filters.get("mes"))
        or _parse_ym(filters.get("month"))
        or datetime.utcnow().date().replace(day=1)
    )
    modelo = _resolve_modelo(filters)

    sql = """
        WITH target AS (
          SELECT
            DATE_TRUNC('month', %(target)s::date)::date AS mes_ini,
            (DATE_TRUNC('month', %(target)s::date)
              + INTERVAL '1 month - 1 day')::date AS mes_fin
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
            LOWER(TRIM(COALESCE(ho.status, ''))) AS status,
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
            ''::text AS status,
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
          to_char(t.mes_ini, 'YYYY-MM') AS month,
          INITCAP(r.model) AS model,
          r.client_name,
          COALESCE(
            r.candidate_name,
            CASE WHEN r.source = 'buyout' THEN '(buyout)' ELSE NULL END
          ) AS candidate_name,
          r.start_d AS start_date,
          r.end_d  AS end_date
        FROM target t
        JOIN all_rows r
          ON (
            (
              r.start_d IS NOT NULL
              AND r.start_d <= t.mes_fin
              AND COALESCE(r.end_d, DATE '9999-12-31') >= t.mes_fin
            )
            OR (
              t.mes_ini = DATE_TRUNC('month', CURRENT_DATE)
              AND r.status = 'active'
              AND (r.end_d IS NULL OR r.end_d >= CURRENT_DATE)
            )
          )
         AND (%(modelo)s = 'total' OR r.model = %(modelo)s)
        ORDER BY r.model, r.client_name, r.candidate_name NULLS LAST;
    """

    return sql, {"target": target, "modelo": modelo}


DATASET = {
    "key": "active_headcount_detail",
    "label": "Active Headcount — Detail by Month",
    "dimensions": [
        {"key": "month", "label": "Month", "type": "date"},
        {"key": "model", "label": "Model", "type": "string"},
        {"key": "client_name", "label": "Client", "type": "string"},
        {"key": "candidate_name", "label": "Candidate", "type": "string"},
        {"key": "start_date", "label": "Start Date", "type": "date"},
        {"key": "end_date", "label": "End Date", "type": "date"},
    ],
    "measures": [],
    "default_filters": {"model": ""},
    "query": query,
}
