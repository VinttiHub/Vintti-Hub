from __future__ import annotations

from datetime import datetime, timedelta


_ALLOWED_MODELS = {"Staffing", "Recruiting"}


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


def _resolve_model(filters: dict) -> str:
    raw = (filters.get("model") or filters.get("opp_model") or "").strip()
    if not raw:
        return "Staffing"
    norm = raw.capitalize()
    return norm if norm in _ALLOWED_MODELS else "Staffing"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, tuple]:
    today = datetime.utcnow().date().replace(day=1)
    last_full_month = (today - timedelta(days=1)).replace(day=1)

    from_dt = _parse_ym(filters.get("from")) or _parse_ym(filters.get("desde")) or datetime(2023, 1, 1)
    to_dt = _parse_ym(filters.get("to")) or _parse_ym(filters.get("hasta")) or datetime.combine(last_full_month, datetime.min.time())
    if to_dt < from_dt:
        to_dt = from_dt

    model = _resolve_model(filters)

    sql = """
        WITH hires AS (
          SELECT
            ho.account_id,
            ho.candidate_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text, '')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE o.opp_model = %s
            AND ho.candidate_id IS NOT NULL
        ),
        months AS (
          SELECT date_trunc('month', gs)::date AS month_start
          FROM generate_series(%s::date, %s::date, interval '1 month') gs
        ),
        eom AS (
          SELECT
            m.month_start,
            (m.month_start + interval '1 month' - interval '1 day')::date AS month_end
          FROM months m
        )
        SELECT
          to_char(e.month_start, 'YYYY-MM') AS month,
          COUNT(DISTINCT h.candidate_id)::int AS active_count
        FROM eom e
        LEFT JOIN hires h
          ON h.start_d IS NOT NULL
         AND h.start_d <= e.month_end
         AND COALESCE(h.end_d, DATE '9999-12-31') >= e.month_end
        GROUP BY e.month_start
        ORDER BY e.month_start;
    """
    return sql, (model, from_dt.date(), to_dt.date())


DATASET = {
    "key": "active_headcount_history",
    "label": "Active Headcount History",
    "dimensions": [
        {"key": "month", "label": "Month", "type": "date"},
    ],
    "measures": [
        {"key": "active_count", "label": "Active Candidates", "type": "number"},
    ],
    "default_filters": {"model": "Staffing"},
    "query": query,
}
