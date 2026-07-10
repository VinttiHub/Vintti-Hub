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

    # Tendencia mensual alineada con el tile 30d (% CW de los replacements cerrados):
    #   - total_closed  = Replacement opps CERRADAS en el mes (Close Win + Closed Lost,
    #                     por opp_close_date) → denominador.
    #   - replacements  = de esas, las Close Win → numerador.
    #   - pct_replacements = Close Win / cerradas * 100.
    sql = """
        WITH replacement_closed AS (
          SELECT
            DATE_TRUNC('month', NULLIF(o.opp_close_date::text, '')::date)::date AS month,
            (TRIM(o.opp_stage) = 'Close Win') AS won
          FROM opportunity o
          LEFT JOIN account a ON a.account_id = o.account_id
          WHERE o.opp_type = 'Replacement'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND TRIM(COALESCE(o.opp_stage, '')) IN ('Close Win', 'Closed Lost')
            AND NULLIF(o.opp_close_date::text, '')::date IS NOT NULL
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
            AND (%(desde)s::date IS NULL OR NULLIF(o.opp_close_date::text, '')::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR NULLIF(o.opp_close_date::text, '')::date <= %(hasta)s::date)
        )
        SELECT
          TO_CHAR(month, 'YYYY-MM-DD')                                            AS month,
          NULL::text                                                              AS opp_model,
          COUNT(*) FILTER (WHERE won)::int                                        AS replacements,
          COUNT(*)::int                                                           AS total_closed,
          ROUND(
            CASE WHEN COUNT(*) = 0 THEN NULL
                 ELSE 100.0 * COUNT(*) FILTER (WHERE won)::numeric / COUNT(*) END,
            2
          )::float                                                                AS pct_replacements,
          NULL::float                                                             AS avg_days_to_replace
        FROM replacement_closed
        GROUP BY month
        ORDER BY month;
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
