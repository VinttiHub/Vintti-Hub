from __future__ import annotations

from datetime import date, datetime


def _parse_ym(value: str | None) -> date | None:
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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    target = (
        _parse_ym(filters.get("fecha"))
        or _parse_ym(filters.get("mes"))
        or _parse_ym(filters.get("month"))
        or datetime.utcnow().date().replace(day=1)
    )

    sql = """
        WITH target AS (
          SELECT
            DATE_TRUNC('month', %(target)s::date)::date AS month_start,
            (DATE_TRUNC('month', %(target)s::date)
              + INTERVAL '1 month - 1 day')::date AS month_end
        ),
        hires AS (
          SELECT
            ho.account_id,
            a.client_name,
            ho.candidate_id,
            c.name AS candidate_name,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(CAST(ho.start_date AS TEXT), '')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(CAST(ho.end_date AS TEXT), '') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          JOIN account a     ON a.account_id     = ho.account_id
          JOIN candidates c  ON c.candidate_id   = ho.candidate_id
          WHERE o.opp_model = 'Staffing'
            AND ho.account_id IS NOT NULL
            AND ho.candidate_id IS NOT NULL
        )
        SELECT
          t.month_start AS month,
          h.client_name,
          h.candidate_name,
          h.start_d AS start_date,
          h.end_d   AS end_date
        FROM target t
        JOIN hires h
          ON h.end_d IS NOT NULL
         AND h.end_d >= t.month_start
         AND h.end_d <= t.month_end
        ORDER BY t.month_start, h.client_name, h.candidate_name;
    """

    return sql, {"target": target}


DATASET = {
    "key": "inactive_candidates_detail",
    "label": "Inactive Candidates — Detail by Month (Staffing)",
    "dimensions": [
        {"key": "month", "label": "Month", "type": "date"},
        {"key": "client_name", "label": "Client", "type": "string"},
        {"key": "candidate_name", "label": "Candidate", "type": "string"},
        {"key": "start_date", "label": "Start Date", "type": "date"},
        {"key": "end_date", "label": "End Date", "type": "date"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
