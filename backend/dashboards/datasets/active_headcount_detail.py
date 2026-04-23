from __future__ import annotations

from datetime import datetime


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
    target = (
        _parse_ym(filters.get("fecha"))
        or _parse_ym(filters.get("mes"))
        or _parse_ym(filters.get("month"))
        or datetime.utcnow().replace(day=1)
    )

    model = _resolve_model(filters)

    sql = """
        WITH target AS (
          SELECT
            date_trunc('month', %s::date)::date AS month_start,
            (date_trunc('month', %s::date) + INTERVAL '1 month - 1 day')::date AS month_end
        ),
        hires AS (
          SELECT
            a.client_name,
            c.name AS candidate_name,
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
          JOIN account a     ON a.account_id = ho.account_id
          JOIN candidates c  ON c.candidate_id = ho.candidate_id
          WHERE o.opp_model = %s
            AND ho.account_id IS NOT NULL
            AND ho.candidate_id IS NOT NULL
        )
        SELECT
          to_char(t.month_start, 'YYYY-MM') AS month,
          h.client_name,
          h.candidate_name,
          h.start_d AS start_date
        FROM target t
        JOIN hires h
          ON h.start_d IS NOT NULL
         AND h.start_d <= t.month_end
         AND COALESCE(h.end_d, DATE '9999-12-31') >= t.month_end
        ORDER BY h.client_name, h.candidate_name;
    """
    target_date = target.date()
    return sql, (target_date, target_date, model)


DATASET = {
    "key": "active_headcount_detail",
    "label": "Active Headcount — Detail by Month",
    "dimensions": [
        {"key": "month", "label": "Month", "type": "date"},
        {"key": "client_name", "label": "Client", "type": "string"},
        {"key": "candidate_name", "label": "Candidate", "type": "string"},
        {"key": "start_date", "label": "Start Date", "type": "date"},
    ],
    "measures": [],
    "default_filters": {"model": "Staffing"},
    "query": query,
}
