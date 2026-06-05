from __future__ import annotations

from datetime import date, datetime, timedelta

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


# Shared CTE source used by all snapshot variants. Mirrors acpa_history's
# hire_rows + buyout_rows so detail counts always match the card.
_BASE_CTES = """
        WITH ventana AS (
          SELECT
            %(corte)s::date AS corte_d,
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin,
            DATE_TRUNC('month', %(corte)s::date)::date = DATE_TRUNC('month', CURRENT_DATE)::date AS is_current_month
        ),
        hire_rows AS (
          SELECT
            ho.account_id,
            a.client_name,
            ho.candidate_id,
            c.name AS candidate_name,
            LOWER(TRIM(COALESCE(ho.status, ''))) AS status,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '') IS NOT NULL
                THEN NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '')::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(TRIM(CAST(ho.end_date AS TEXT)), '') IS NULL THEN NULL
              ELSE NULLIF(TRIM(CAST(ho.end_date AS TEXT)), '')::date
            END AS end_d,
            LOWER(TRIM(o.opp_model)) AS model,
            o.opp_close_date::date AS close_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          JOIN account a     ON a.account_id     = ho.account_id
          LEFT JOIN candidates c ON c.candidate_id = ho.candidate_id
          WHERE ho.account_id IS NOT NULL
            AND LOWER(TRIM(o.opp_model)) IN ('staffing', 'recruiting')
        ),
        buyout_rows AS (
          SELECT
            b.account_id,
            a.client_name,
            NULL::int  AS candidate_id,
            NULL::text AS candidate_name,
            ''::text   AS status,
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
            'recruiting'::text AS model,
            NULL::date AS close_d
          FROM buyouts b
          JOIN account a ON a.account_id = b.account_id
          WHERE b.account_id IS NOT NULL
        ),
        account_rows AS (
          SELECT * FROM hire_rows
          UNION ALL
          SELECT * FROM buyout_rows
        )
"""


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or _parse_date(filters.get("fecha"))
        or datetime.utcnow().date()
    )
    modelo = _resolve_modelo(filters)
    # ONLY `event_window` triggers event-in-window mode here. The global state
    # `window` filter (defaults to '30d') is intentionally ignored on this
    # dataset so the snapshot used by Active Clients / Active Contractors keeps
    # matching acpa_history.
    window_raw = str(filters.get("event_window") or "").strip().lower()
    event_mode = bool(window_raw)
    # Narrow event-mode results to accounts whose FIRST-EVER Recruiting close
    # falls in the window. Matches "new clients · Recruiting" card semantics.
    first_close_only = str(filters.get("first_close_only") or "").strip().lower() in ("1", "true", "yes")
    if event_mode:
        win_ini, win_fin = _window_bounds(window_raw, corte)
    else:
        win_ini, win_fin = window_bounds(filters)

    sql = _BASE_CTES

    modelo_lc = modelo.lower()  # 'staffing' | 'recruiting' | 'total'

    if event_mode and first_close_only:
        # New-client semantics: restrict to accounts whose FIRST Recruiting
        # close_d falls in the window (the same set the recruiting card counts).
        sql += """,
        first_recruiting_close AS (
          SELECT account_id, MIN(close_d) AS first_close_d
          FROM hire_rows
          WHERE model = 'recruiting' AND close_d IS NOT NULL
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
          r.client_name,
          r.candidate_name,
          r.start_d AS start_date,
          INITCAP(r.model) AS opp_model
        FROM ventana v
        JOIN hire_rows r
          ON r.model = 'recruiting'
         AND r.close_d BETWEEN v.win_ini AND v.win_fin
         AND r.account_id IN (SELECT account_id FROM new_recruiting_accounts)
        ORDER BY r.client_name, COALESCE(r.candidate_name, '');
        """
    elif event_mode:
        # Event-in-window: rows that became "events" inside the window.
        # Recruiting anchors on close_d (FTE placed). Staffing on start_d.
        sql += """
        SELECT
          v.corte_d AS cutoff_date,
          r.client_name,
          r.candidate_name,
          r.start_d AS start_date,
          INITCAP(r.model) AS opp_model
        FROM ventana v
        JOIN hire_rows r
          ON (%(modelo_lc)s = 'total' OR r.model = %(modelo_lc)s)
         AND (
              (r.model = 'recruiting' AND r.close_d BETWEEN v.win_ini AND v.win_fin)
           OR (r.model = 'staffing'   AND r.start_d BETWEEN v.win_ini AND v.win_fin)
         )
        ORDER BY r.client_name, COALESCE(r.candidate_name, '');
        """
    else:
        # Snapshot mode — MUST match acpa_history.cuentas_activas exactly:
        #   row active = (start_d <= corte AND end_d null/future)
        #             OR (corte is current month AND status='active' AND end_d null/future)
        sql += """
        SELECT
          v.corte_d AS cutoff_date,
          r.client_name,
          r.candidate_name,
          r.start_d AS start_date,
          INITCAP(r.model) AS opp_model
        FROM ventana v
        JOIN account_rows r
          ON (%(modelo_lc)s = 'total' OR r.model = %(modelo_lc)s)
         AND (
              (
                r.start_d IS NOT NULL
                AND r.start_d <= v.win_fin
                AND COALESCE(r.end_d, DATE '9999-12-31') >= v.win_fin
              )
              OR (
                v.is_current_month
                AND r.status = 'active'
                AND (r.end_d IS NULL OR r.end_d >= CURRENT_DATE)
              )
         )
        ORDER BY r.client_name, COALESCE(r.candidate_name, '');
        """

    return sql, {
        "corte": corte,
        "modelo": modelo,
        "modelo_lc": modelo_lc,
        "win_ini": win_ini,
        "win_fin": win_fin,
    }


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
