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
    # Narrow event-mode results to accounts whose FIRST-EVER Recruiting close
    # falls in the window. Matches "new clients · Recruiting" card semantics.
    first_close_only = str(filters.get("first_close_only") or "").strip().lower() in ("1", "true", "yes")
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
        ),
        -- Loose Recruiting rows (no candidate join) + buyouts. Mirrors the
        -- account-activity set counted by acpa_history.cuentas_activas so the
        -- "Active clients · Recruiting" detail aligns with the card.
        recruiting_hires_loose AS (
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
            'Recruiting'::text AS model
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          JOIN account a     ON a.account_id     = ho.account_id
          LEFT JOIN candidates c  ON c.candidate_id = ho.candidate_id
          WHERE o.opp_model = 'Recruiting'
            AND ho.account_id IS NOT NULL
        ),
        recruiting_buyouts AS (
          SELECT
            b.account_id,
            a.client_name,
            NULL::int  AS candidate_id,
            NULL::text AS candidate_name,
            CASE
              WHEN NULLIF(TRIM(CAST(b.start_date AS TEXT)), '') IS NOT NULL
                THEN NULLIF(TRIM(CAST(b.start_date AS TEXT)), '')::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN NULLIF(TRIM(CAST(b.end_date AS TEXT)), '') IS NOT NULL
                THEN NULLIF(TRIM(CAST(b.end_date AS TEXT)), '')::date
              ELSE NULL
            END AS end_d,
            'Recruiting'::text AS model
          FROM buyouts b
          JOIN account a ON a.account_id = b.account_id
          WHERE b.account_id IS NOT NULL
        ),
        recruiting_all AS (
          SELECT * FROM recruiting_hires_loose
          UNION ALL
          SELECT * FROM recruiting_buyouts
        )
    """
    if event_mode and first_close_only:
        # New-client semantics: restrict to accounts whose FIRST Recruiting
        # close_d falls in the window (the same set the card counts).
        sql += """,
        first_recruiting_close AS (
          SELECT account_id, MIN(close_d) AS first_close_d
          FROM hires
          WHERE model = 'Recruiting' AND close_d IS NOT NULL
          GROUP BY account_id
        ),
        new_recruiting_accounts AS (
          SELECT fr.account_id
          FROM first_recruiting_close fr
          CROSS JOIN ventana v
          WHERE fr.first_close_d BETWEEN v.win_ini AND v.win_fin
        )
        SELECT
          v.corte_d AS cutoff_date,
          h.client_name,
          h.candidate_name,
          h.start_d AS start_date,
          h.model   AS opp_model
        FROM ventana v
        JOIN hires h
          ON h.model = 'Recruiting'
         AND h.close_d BETWEEN v.win_ini AND v.win_fin
         AND h.account_id IN (SELECT account_id FROM new_recruiting_accounts)
        ORDER BY h.client_name, h.candidate_name;
        """
    elif event_mode:
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
    elif modelo == 'Recruiting':
        # Recruiting snapshot uses the loose hire set + buyouts so the row count
        # matches acpa_history.cuentas_activas exactly.
        sql += """
        SELECT
          v.corte_d AS cutoff_date,
          r.client_name,
          r.candidate_name,
          r.start_d AS start_date,
          r.model   AS opp_model
        FROM ventana v
        JOIN recruiting_all r
          ON r.start_d IS NOT NULL
         AND r.start_d <= v.win_fin
         AND COALESCE(r.end_d, DATE '9999-12-31') >= v.win_fin
        ORDER BY r.client_name, COALESCE(r.candidate_name, '');
        """
    elif modelo == 'Total':
        # Total = Staffing hires (with candidate join) UNION Recruiting loose set + buyouts
        sql += """
        , combined_total AS (
          SELECT account_id, client_name, candidate_id, candidate_name, start_d, end_d, model
          FROM hires
          WHERE model = 'Staffing'
          UNION ALL
          SELECT account_id, client_name, candidate_id, candidate_name, start_d, end_d, model
          FROM recruiting_all
        )
        SELECT
          v.corte_d AS cutoff_date,
          ct.client_name,
          ct.candidate_name,
          ct.start_d AS start_date,
          ct.model   AS opp_model
        FROM ventana v
        JOIN combined_total ct
          ON ct.start_d IS NOT NULL
         AND ct.start_d <= v.win_fin
         AND COALESCE(ct.end_d, DATE '9999-12-31') >= v.win_fin
        ORDER BY ct.client_name, COALESCE(ct.candidate_name, '');
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
