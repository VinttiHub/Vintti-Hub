from __future__ import annotations

from datetime import datetime, timedelta


def _parse_ym(value: str | None) -> datetime | None:
    if not value:
        return None
    parts = str(value).split("-")
    if len(parts) < 2:
        return None
    try:
        return datetime(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, tuple]:
    today = datetime.utcnow().date().replace(day=1)
    last_full_month = (today - timedelta(days=1)).replace(day=1)

    from_dt = _parse_ym(filters.get("from")) or _parse_ym(filters.get("desde"))
    to_dt = _parse_ym(filters.get("to")) or _parse_ym(filters.get("hasta")) or datetime.combine(last_full_month, datetime.min.time())

    if from_dt is None:
        from_dt = datetime(2023, 1, 1)
    if to_dt < from_dt:
        to_dt = from_dt

    sql = """
        WITH params AS (
          SELECT %s::date AS from_month, %s::date AS to_month
        ),
        months AS (
          SELECT date_trunc('month', gs)::date AS month
          FROM params p,
               generate_series(p.from_month, p.to_month, interval '1 month') gs
        ),
        staffing AS (
          SELECT
            COALESCE(h.salary, 0)::numeric AS salary,
            COALESCE(h.fee, 0)::numeric AS fee,
            h.start_date::date AS start_date,
            h.end_date::date AS end_date
          FROM hire_opportunity h
          JOIN opportunity o ON o.opportunity_id = h.opportunity_id
          WHERE lower(o.opp_model) LIKE 'staffing%%'
            AND h.start_date IS NOT NULL
        ),
        eom AS (
          SELECT
            m.month,
            (m.month + INTERVAL '1 month' - INTERVAL '1 day')::date AS month_end
          FROM months m
        )
        SELECT
          to_char(e.month, 'YYYY-MM') AS month,
          COALESCE(SUM(CASE
            WHEN s.start_date <= e.month_end
             AND (s.end_date IS NULL OR s.end_date > e.month_end)
            THEN s.salary + s.fee END), 0)::bigint AS tsr,
          COALESCE(SUM(CASE
            WHEN s.start_date <= e.month_end
             AND (s.end_date IS NULL OR s.end_date > e.month_end)
            THEN s.fee END), 0)::bigint AS tsf,
          COALESCE(COUNT(*) FILTER (
            WHERE s.start_date <= e.month_end
              AND (s.end_date IS NULL OR s.end_date > e.month_end)
          ), 0) AS active_count
        FROM eom e
        LEFT JOIN staffing s ON TRUE
        GROUP BY e.month
        ORDER BY e.month;
    """
    return sql, (from_dt.date(), to_dt.date())


DATASET = {
    "key": "ts_history",
    "label": "Time Series History (TSR/TSF/Active)",
    "dimensions": [
        {"key": "month", "label": "Month", "type": "date"},
    ],
    "measures": [
        {"key": "tsr", "label": "Total Staffing Revenue", "type": "currency"},
        {"key": "tsf", "label": "Total Staffing Fee", "type": "currency"},
        {"key": "active_count", "label": "Active Hires", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
