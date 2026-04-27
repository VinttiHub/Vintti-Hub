from __future__ import annotations

from datetime import date, datetime


_ALLOWED_SEGMENTS = {"staffing", "recruiting", "total"}


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
    today = datetime.utcnow().date()
    current_month_start = today.replace(day=1)

    desde = (
        _parse_ym(filters.get("desde"))
        or _parse_ym(filters.get("from"))
        or date(2023, 1, 1)
    )
    hasta = (
        _parse_ym(filters.get("hasta"))
        or _parse_ym(filters.get("to"))
        or current_month_start
    )
    if hasta < desde:
        hasta = desde

    segment = _resolve_segment(filters)

    sql = """
        WITH hire_rows AS (
          SELECT
            ('hire_' || ho.hire_opp_id::text) AS row_id,
            ho.candidate_id,
            ho.account_id,
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
            END AS end_d,
            LOWER(TRIM(o.opp_model)) AS model
          FROM hire_opportunity ho
          JOIN opportunity o
            ON o.opportunity_id = ho.opportunity_id
          WHERE ho.account_id IS NOT NULL
            AND LOWER(TRIM(o.opp_model)) IN ('staffing', 'recruiting')
        ),
        buyout_rows AS (
          SELECT
            ('buyout_' || b.buyout_id::text) AS row_id,
            NULL::integer AS candidate_id,
            b.account_id,
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
            END AS end_d,
            'recruiting'::text AS model
          FROM buyouts b
          WHERE b.account_id IS NOT NULL
        ),
        account_rows AS (
          SELECT * FROM hire_rows
          UNION ALL
          SELECT * FROM buyout_rows
        ),
        meses AS (
          SELECT
            DATE_TRUNC('month', gs)::date AS mes_ini,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS mes_fin
          FROM generate_series(
            DATE_TRUNC('month', %(desde)s::date),
            DATE_TRUNC('month', %(hasta)s::date),
            INTERVAL '1 month'
          ) gs
        ),
        activos_base AS (
          SELECT DISTINCT
            m.mes_ini AS mes,
            r.model,
            r.row_id,
            r.candidate_id
          FROM meses m
          JOIN account_rows r
            ON (
              (
                r.start_d IS NOT NULL
                AND r.start_d <= m.mes_fin
                AND COALESCE(r.end_d, DATE '9999-12-31') >= m.mes_fin
              )
              OR (
                m.mes_ini = DATE_TRUNC('month', CURRENT_DATE)
                AND r.status = 'active'
                AND (r.end_d IS NULL OR r.end_d >= CURRENT_DATE)
              )
            )
           AND (%(segment)s = 'total' OR r.model = %(segment)s)
        ),
        metricas_mes AS (
          SELECT
            mes,
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
            END AS active_count
          FROM activos_base
          GROUP BY 1
        )
        SELECT
          to_char(m.mes_ini, 'YYYY-MM') AS month,
          COALESCE(mm.active_count, 0)::int AS active_count
        FROM meses m
        LEFT JOIN metricas_mes mm ON mm.mes = m.mes_ini
        ORDER BY m.mes_ini;
    """

    params = {
        "desde": desde,
        "hasta": hasta,
        "segment": segment,
    }
    return sql, params


DATASET = {
    "key": "active_headcount_history",
    "label": "Active Headcount History",
    "dimensions": [
        {"key": "month", "label": "Month", "type": "date"},
    ],
    "measures": [
        {"key": "active_count", "label": "Active Candidates", "type": "number"},
    ],
    "default_filters": {"model": ""},
    "query": query,
}
