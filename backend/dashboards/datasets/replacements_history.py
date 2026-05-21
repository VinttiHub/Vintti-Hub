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

    # Monthly trend aligned with the 30d coverage tile:
    #   - replacements  = Replacement opps OPENED in the month
    #                     (nda_signature_or_start_date in month)
    #   - total_closed  = Replacement opps CLOSED in the month
    #                     (opp_close_date in month, any closing stage)
    #   - pct_replacements = replacements / total_closed * 100
    sql = """
        WITH replacement_opps AS (
          SELECT
            o.opportunity_id,
            o.opp_model,
            NULLIF(o.nda_signature_or_start_date::text, '')::date AS opened_d,
            NULLIF(o.opp_close_date::text, '')::date              AS closed_d
          FROM opportunity o
          WHERE o.opp_type = 'Replacement'
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
        ),
        opens_per_month AS (
          SELECT
            DATE_TRUNC('month', r.opened_d)::date AS month,
            r.opp_model,
            COUNT(*)::int AS replacements
          FROM replacement_opps r
          WHERE r.opened_d IS NOT NULL
            AND (%(desde)s::date IS NULL OR r.opened_d >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR r.opened_d <= %(hasta)s::date)
          GROUP BY 1, 2
        ),
        closes_per_month AS (
          SELECT
            DATE_TRUNC('month', r.closed_d)::date AS month,
            r.opp_model,
            COUNT(*)::int AS total_closed
          FROM replacement_opps r
          WHERE r.closed_d IS NOT NULL
            AND (%(desde)s::date IS NULL OR r.closed_d >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR r.closed_d <= %(hasta)s::date)
          GROUP BY 1, 2
        ),
        months AS (
          SELECT month, opp_model FROM opens_per_month
          UNION
          SELECT month, opp_model FROM closes_per_month
        )
        SELECT
          TO_CHAR(m.month, 'YYYY-MM-DD')                                          AS month,
          m.opp_model,
          COALESCE(o.replacements, 0)                                             AS replacements,
          COALESCE(c.total_closed, 0)                                             AS total_closed,
          ROUND(
            (COALESCE(o.replacements, 0)::numeric / NULLIF(c.total_closed, 0)) * 100,
            2
          )::float                                                                AS pct_replacements,
          NULL::float                                                             AS avg_days_to_replace
        FROM months m
        LEFT JOIN opens_per_month  o ON o.month = m.month AND o.opp_model = m.opp_model
        LEFT JOIN closes_per_month c ON c.month = m.month AND c.opp_model = m.opp_model
        ORDER BY m.month, m.opp_model;
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
