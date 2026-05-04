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


def _norm_model(value) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return raw[:1].upper() + raw[1:].lower()


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    modelo = _norm_model(filters.get("model") or filters.get("modelo"))
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    sql = """
        WITH opp_replacements AS (
          SELECT
            o.opportunity_id,
            o.account_id,
            a.client_name,
            o.opp_model,
            o.opp_stage,
            o.opp_type,
            NULLIF(o.replacement_of::text, '')::text AS old_candidate_id
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE o.opp_type = 'Replacement'
            AND o.opp_stage IN ('Close Win', 'Close Lost')
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
        ),
        old_end AS (
          SELECT
            ho.candidate_id::text AS old_candidate_id,
            MAX(NULLIF(ho.end_date::text, '')::date) AS old_end_date
          FROM hire_opportunity ho
          GROUP BY ho.candidate_id::text
        ),
        new_start AS (
          SELECT
            ho.opportunity_id,
            MIN(NULLIF(ho.start_date::text, '')::date) AS new_start_date,
            MIN(ho.candidate_id)::text AS new_candidate_id
          FROM hire_opportunity ho
          GROUP BY ho.opportunity_id
        ),
        replacement_detail AS (
          SELECT
            r.opportunity_id,
            r.opp_model,
            ns.new_start_date,
            (ns.new_start_date - oe.old_end_date) AS days_to_replace
          FROM opp_replacements r
          LEFT JOIN old_end   oe ON oe.old_candidate_id = r.old_candidate_id
          LEFT JOIN new_start ns ON ns.opportunity_id   = r.opportunity_id
          WHERE ns.new_start_date IS NOT NULL
            AND (%(desde)s::date IS NULL OR ns.new_start_date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR ns.new_start_date <= %(hasta)s::date)
        ),
        replacements AS (
          SELECT
            DATE_TRUNC('month', rd.new_start_date)::date AS month,
            rd.opp_model,
            COUNT(*)::int                AS replacements,
            AVG(rd.days_to_replace)      AS avg_days_to_replace
          FROM replacement_detail rd
          GROUP BY 1, 2
        ),
        closed_opps AS (
          SELECT
            DATE_TRUNC('month', o.opp_close_date::date)::date AS month,
            o.opp_model,
            COUNT(*)::int AS total_closed
          FROM opportunity o
          WHERE o.opp_stage IN ('Close Win', 'Close Lost')
            AND o.opp_close_date IS NOT NULL
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
            AND (%(desde)s::date  IS NULL OR o.opp_close_date::date >= %(desde)s::date)
            AND (%(hasta)s::date  IS NULL OR o.opp_close_date::date <= %(hasta)s::date)
          GROUP BY 1, 2
        )
        SELECT
          TO_CHAR(r.month, 'YYYY-MM-DD')                                          AS month,
          r.opp_model,
          r.replacements,
          c.total_closed,
          ROUND(
            (r.replacements::numeric / NULLIF(c.total_closed, 0)) * 100, 2
          )::float                                                                AS pct_replacements,
          ROUND(r.avg_days_to_replace, 1)::float                                  AS avg_days_to_replace
        FROM replacements r
        LEFT JOIN closed_opps c
          ON c.month     = r.month
         AND c.opp_model = r.opp_model
        ORDER BY r.month, r.opp_model;
    """

    return sql, {"modelo": modelo, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "replacements_history",
    "label": "% de reemplazos realizados (mensual)",
    "dimensions": [
        {"key": "month", "label": "Mes", "type": "date"},
        {"key": "opp_model", "label": "Modelo", "type": "string"},
    ],
    "measures": [
        {"key": "replacements", "label": "Reemplazos", "type": "number"},
        {"key": "total_closed", "label": "Total cerradas", "type": "number"},
        {"key": "pct_replacements", "label": "% reemplazos", "type": "percent"},
        {"key": "avg_days_to_replace", "label": "Promedio días", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
