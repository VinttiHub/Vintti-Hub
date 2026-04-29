from __future__ import annotations

from datetime import date, datetime


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.split("-")
    try:
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or _parse_date(filters.get("fecha"))
        or datetime.utcnow().date()
    )

    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date AS corte_d,
            (%(corte)s::date - INTERVAL '29 day')::date AS win_ini,
            %(corte)s::date AS win_fin
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
          v.corte_d AS cutoff_date,
          h.client_name,
          h.candidate_name,
          h.start_d AS start_date
        FROM ventana v
        JOIN hires h
          ON h.start_d IS NOT NULL
         AND h.start_d <= v.win_fin
         AND COALESCE(h.end_d, DATE '9999-12-31') >= v.win_fin
        ORDER BY h.client_name, h.candidate_name;
    """

    return sql, {"corte": corte}


DATASET = {
    "key": "active_headcount_30d_detail",
    "label": "Active Headcount — 30d Rolling Detail (Staffing)",
    "dimensions": [
        {"key": "cutoff_date", "label": "Cutoff Date", "type": "date"},
        {"key": "client_name", "label": "Client", "type": "string"},
        {"key": "candidate_name", "label": "Candidate", "type": "string"},
        {"key": "start_date", "label": "Start Date", "type": "date"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
