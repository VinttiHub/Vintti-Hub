from __future__ import annotations

from datetime import date, datetime, timedelta


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


def _resolve_modelo(filters: dict) -> str:
    raw = (
        filters.get("modelo")
        or filters.get("model")
        or filters.get("opp_model")
        or filters.get("segmento")
        or ""
    ).strip().lower()
    if raw in {"recruiting", "recru"}:
        return "Recruiting"
    if raw in {"total", "all", "todos"}:
        return "Total"
    return "Staffing"


def _window_bounds(window_raw: str, corte: date) -> tuple[date, date]:
    """Resolve (win_ini, win_fin) from a `window` filter value."""
    raw = (window_raw or "").strip().lower()
    if raw in ("7d", "7"):
        return corte - timedelta(days=6), corte
    if raw in ("week", "semana", "last_week", "last-week", "prev_week"):
        prev_sunday = corte - timedelta(days=corte.weekday() + 1)
        prev_monday = prev_sunday - timedelta(days=6)
        return prev_monday, prev_sunday
    if raw == "mtd":
        return corte.replace(day=1), corte
    if raw in ("month", "last_month", "last-month", "prev_month"):
        first_this = corte.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_prev, last_prev
    if raw in ("ytd", "year_to_date", "year-to-date"):
        return corte.replace(month=1, day=1), corte
    return corte - timedelta(days=29), corte


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or _parse_date(filters.get("fecha"))
        or datetime.utcnow().date()
    )
    modelo = _resolve_modelo(filters)
    # When a `window` filter is set, switch from snapshot mode (everyone active
    # at corte) to event-in-window mode (only candidates whose start_d falls in
    # the window). Lets KPI count cards and detail lists agree.
    window_raw = str(filters.get("window") or filters.get("ventana") or "").strip().lower()
    event_mode = bool(window_raw)
    if event_mode:
        win_ini, win_fin = _window_bounds(window_raw, corte)
    else:
        win_ini = corte - timedelta(days=29)
        win_fin = corte

    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date AS corte_d,
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin
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
            END AS end_d,
            o.opp_model AS model,
            o.opp_close_date::date AS close_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          JOIN account a     ON a.account_id     = ho.account_id
          JOIN candidates c  ON c.candidate_id   = ho.candidate_id
          WHERE o.opp_model IN ('Staffing', 'Recruiting')
            AND ho.account_id IS NOT NULL
            AND ho.candidate_id IS NOT NULL
        )
    """
    if event_mode:
        # Event-in-window: rows whose entry-into-the-business date is in window.
        # For Recruiting we anchor on close_d (FTE placed); for Staffing on start_d.
        sql += """
        SELECT
          v.corte_d AS cutoff_date,
          h.client_name,
          h.candidate_name,
          h.start_d AS start_date,
          h.model   AS opp_model
        FROM ventana v
        JOIN hires h
          ON (%(modelo)s = 'Total' OR h.model = %(modelo)s)
         AND (
              (h.model = 'Recruiting' AND h.close_d BETWEEN v.win_ini AND v.win_fin)
           OR (h.model = 'Staffing'   AND h.start_d BETWEEN v.win_ini AND v.win_fin)
         )
        ORDER BY h.client_name, h.candidate_name;
        """
    else:
        sql += """
        SELECT
          v.corte_d AS cutoff_date,
          h.client_name,
          h.candidate_name,
          h.start_d AS start_date,
          h.model   AS opp_model
        FROM ventana v
        JOIN hires h
          ON h.start_d IS NOT NULL
         AND h.start_d <= v.win_fin
         AND COALESCE(h.end_d, DATE '9999-12-31') >= v.win_fin
         AND (%(modelo)s = 'Total' OR h.model = %(modelo)s)
        ORDER BY h.client_name, h.candidate_name;
        """

    return sql, {"corte": corte, "modelo": modelo, "win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "active_headcount_30d_detail",
    "label": "Active Headcount — 30d Rolling Detail",
    "dimensions": [
        {"key": "cutoff_date", "label": "Cutoff Date", "type": "date"},
        {"key": "client_name", "label": "Client", "type": "string"},
        {"key": "candidate_name", "label": "Candidate", "type": "string"},
        {"key": "start_date", "label": "Start Date", "type": "date"},
        {"key": "opp_model", "label": "Model", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
