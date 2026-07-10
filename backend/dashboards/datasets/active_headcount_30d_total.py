from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar

from ._periods import window_bounds


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
        or today_ar()
    )

    win_ini, win_fin = window_bounds(filters)
    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date AS corte_d,
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin
        ),
        hires AS (
          SELECT
            ho.candidate_id,
            LOWER(TRIM(COALESCE(ho.status, ''))) AS status,
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
          LEFT JOIN account a ON a.account_id = ho.account_id
          WHERE o.opp_model = 'Staffing'
            AND ho.candidate_id IS NOT NULL
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
        )
        SELECT
          COUNT(DISTINCT h.candidate_id)::int AS active_count
        FROM ventana v
        JOIN hires h
          ON h.start_d IS NOT NULL
         AND h.start_d <= v.win_fin
         AND COALESCE(h.end_d, DATE '9999-12-31') >= v.win_fin
         -- Snapshot actual (corte >= hoy): respetar el status de baja igual que el
         -- historial/cohort (un hire dado de baja HOY no cuenta como activo). Para
         -- cortes históricos se mantiene el criterio por fechas.
         AND (v.win_fin < CURRENT_DATE OR h.status = 'active');
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin,"corte": corte}


DATASET = {
    "key": "active_headcount_30d_total",
    "label": "Active Headcount — 30d Rolling Total (Staffing)",
    "dimensions": [],
    "measures": [
        {"key": "active_count", "label": "Active (30d)", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
