from __future__ import annotations


def query(filters: dict, *_args, **_kwargs) -> tuple[str, tuple]:
    where = ["b.presentation_date IS NOT NULL"]
    params: list = []

    desde = filters.get("desde") or filters.get("from")
    hasta = filters.get("hasta") or filters.get("to")
    if desde:
        where.append("b.presentation_date >= %s")
        params.append(desde)
    if hasta:
        where.append("b.presentation_date <= %s")
        params.append(hasta)

    sql = f"""
        WITH first_sourcing AS (
          SELECT opportunity_id, MIN(since_sourcing::date) AS sourcing_start
          FROM sourcing
          WHERE since_sourcing IS NOT NULL
          GROUP BY opportunity_id
        )
        SELECT
          b.batch_id,
          b.batch_number,
          b.presentation_date::date AS presentation_date,
          b.opportunity_id,
          fs.sourcing_start,
          (b.presentation_date::date - fs.sourcing_start) AS days_from_sourcing,
          to_char(b.presentation_date, 'YYYY-MM') AS month
        FROM batch b
        LEFT JOIN first_sourcing fs ON fs.opportunity_id = b.opportunity_id
        WHERE {' AND '.join(where)}
        ORDER BY b.presentation_date DESC
        LIMIT 5000;
    """
    return sql, tuple(params)


DATASET = {
    "key": "batch_sourcing",
    "label": "Batches (sourcing → presentation timing)",
    "dimensions": [
        {"key": "month", "label": "Month", "type": "date"},
        {"key": "batch_number", "label": "Batch #", "type": "number"},
        {"key": "opportunity_id", "label": "Opportunity", "type": "number"},
    ],
    "measures": [
        {"key": "days_from_sourcing", "label": "Days from Sourcing", "type": "number"},
        {"key": "batch_id", "label": "Count", "type": "number", "agg": "count"},
    ],
    "default_filters": {},
    "query": query,
}
