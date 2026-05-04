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


def _parse_umbral(value) -> int:
    try:
        n = int(str(value).strip())
        if n in (3, 6, 12):
            return n
    except (TypeError, ValueError):
        pass
    return 3


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    umbral = _parse_umbral(filters.get("umbral"))
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    sql = """
        WITH ho_norm AS (
          SELECT
            ho.candidate_id,
            ho.start_date::date AS start_d,
            CASE
              WHEN ho.end_date IS NULL OR ho.end_date::text = '' THEN NULL
              ELSE ho.end_date::date
            END AS end_d
          FROM hire_opportunity ho
          JOIN opportunity o
            ON o.opportunity_id = ho.opportunity_id
           AND o.opp_model = 'Staffing'
          WHERE ho.start_date IS NOT NULL
            AND (%(desde)s::date IS NULL OR ho.start_date::date >= DATE_TRUNC('month', %(desde)s::date))
            AND (%(hasta)s::date IS NULL OR ho.start_date::date <  (DATE_TRUNC('month', %(hasta)s::date) + INTERVAL '1 month'))
        ),
        placements AS (
          SELECT candidate_id, start_d, MIN(end_d) AS end_d
          FROM ho_norm
          GROUP BY 1, 2
        ),
        enriched AS (
          SELECT
            p.candidate_id,
            p.start_d,
            p.end_d,
            DATE_TRUNC('month', p.start_d)::date AS cohort_month,
            (DATE_TRUNC('month', p.start_d) + (INTERVAL '1 month' * %(umbral)s))::date AS window_limit_d,
            DATE_TRUNC('month', COALESCE(p.end_d, CURRENT_DATE))::date AS last_month_reached
          FROM placements p
        ),
        cohort AS (
          SELECT cohort_month, COUNT(*)::int AS cohort_n
          FROM enriched
          GROUP BY 1
        ),
        cohort_age AS (
          SELECT
            c.cohort_month,
            c.cohort_n,
            FLOOR(
              EXTRACT(EPOCH FROM (DATE_TRUNC('month', CURRENT_DATE) - DATE_TRUNC('month', c.cohort_month)))
              / EXTRACT(EPOCH FROM INTERVAL '1 month')
            )::int AS cohort_age_m
          FROM cohort c
        ),
        agg AS (
          SELECT
            e.cohort_month,
            SUM(CASE WHEN e.last_month_reached >= e.window_limit_d THEN 1 ELSE 0 END)::int AS kept_ge_window
          FROM enriched e
          GROUP BY 1
        )
        SELECT
          TO_CHAR(a.cohort_month, 'YYYY-MM-DD')                                                AS cohorte_mes,
          ca.cohort_n                                                                          AS start_candidate_total,
          CASE WHEN ca.cohort_age_m >= %(umbral)s THEN ca.cohort_n END                         AS start_candidate,
          %(umbral)s                                                                           AS umbral_meses,
          TO_CHAR(ca.cohort_month, 'YYYY-MM-DD')                                               AS ventana_inicio_mes,
          TO_CHAR(
            (ca.cohort_month + (INTERVAL '1 month' * (%(umbral)s - 1)))::date,
            'YYYY-MM-DD'
          )                                                                                    AS ventana_fin_mes,
          CASE WHEN ca.cohort_age_m >= %(umbral)s THEN a.kept_ge_window END                    AS stay_candidate,
          CASE WHEN ca.cohort_age_m >= %(umbral)s
               THEN ROUND(100.0 * a.kept_ge_window / NULLIF(ca.cohort_n, 0), 2)::float
          END                                                                                  AS retention,
          (ca.cohort_age_m >= %(umbral)s)                                                      AS eligible_n
        FROM agg a
        JOIN cohort_age ca ON ca.cohort_month = a.cohort_month
        ORDER BY a.cohort_month;
    """

    return sql, {"umbral": umbral, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "candidate_retention_rate",
    "label": "Retention Rate de candidatos por cohorte (Staffing)",
    "dimensions": [
        {"key": "cohorte_mes", "label": "Cohorte", "type": "date"},
    ],
    "measures": [
        {"key": "start_candidate_total", "label": "Cohorte total", "type": "number"},
        {"key": "start_candidate", "label": "Start candidates", "type": "number"},
        {"key": "stay_candidate", "label": "Stay candidates", "type": "number"},
        {"key": "retention", "label": "Retention %", "type": "percent"},
        {"key": "umbral_meses", "label": "Umbral (meses)", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
