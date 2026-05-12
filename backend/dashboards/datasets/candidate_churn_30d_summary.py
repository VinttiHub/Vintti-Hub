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


def _window_bounds(filters: dict, corte: date) -> tuple[date, date]:
    """Resolve (win_ini, win_fin) from the `window` filter. Default: last 30d (30-day offset).

    `week` means the previous full calendar week (Mon-Sun ending before today's
    week). For a rolling 7-day window use `7d`.
    """
    raw = str(filters.get("window") or filters.get("ventana") or "30d").strip().lower()
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
    return corte - timedelta(days=30), corte


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or datetime.utcnow().date()
    )
    win_ini, win_fin = _window_bounds(filters, corte)
    corte_d = win_fin

    sql = """
        WITH ventana AS (
          SELECT
            %(corte_d)s::date AS corte_d,
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin
        ),
        candidatos AS (
          SELECT
            ho.candidate_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(ho.start_date::text, '') IS NOT NULL THEN ho.start_date::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            CASE
              WHEN NULLIF(TRIM(ho.buyout_daterange), '') IS NOT NULL
                THEN TO_DATE(TRIM(ho.buyout_daterange) || '-01', 'YYYY-MM-DD')
              ELSE NULL
            END AS buyout_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.candidate_id IS NOT NULL
            AND o.opp_model = 'Staffing'
        ),
        activos_inicio AS (
          SELECT DISTINCT c.candidate_id, c.end_d, c.buyout_d
          FROM candidatos c
          CROSS JOIN ventana v
          WHERE c.start_d IS NOT NULL
            AND c.start_d <= v.win_ini
            AND (c.end_d IS NULL OR c.end_d >= v.win_ini)
        ),
        bajas_inicio AS (
          SELECT
            COUNT(DISTINCT a.candidate_id) FILTER (
              WHERE NOT (a.buyout_d IS NOT NULL AND a.buyout_d >= DATE_TRUNC('month', a.end_d))
            )::int AS bajas_real,
            COUNT(DISTINCT a.candidate_id) FILTER (
              WHERE a.buyout_d IS NOT NULL AND a.buyout_d >= DATE_TRUNC('month', a.end_d)
            )::int AS bajas_buyout
          FROM activos_inicio a
          CROSS JOIN ventana v
          WHERE a.end_d IS NOT NULL
            AND a.end_d BETWEEN v.win_ini AND v.win_fin
        ),
        bajas_starts AS (
          SELECT
            COUNT(DISTINCT c.candidate_id) FILTER (
              WHERE NOT (c.buyout_d IS NOT NULL AND c.buyout_d >= DATE_TRUNC('month', c.end_d))
            )::int AS bajas_real,
            COUNT(DISTINCT c.candidate_id) FILTER (
              WHERE c.buyout_d IS NOT NULL AND c.buyout_d >= DATE_TRUNC('month', c.end_d)
            )::int AS bajas_buyout
          FROM candidatos c
          CROSS JOIN ventana v
          WHERE c.start_d IS NOT NULL
            AND c.end_d IS NOT NULL
            AND c.start_d BETWEEN v.win_ini AND v.win_fin
            AND c.end_d   BETWEEN v.win_ini AND v.win_fin
        ),
        totals AS (
          SELECT
            (SELECT COUNT(*) FROM activos_inicio)::int AS activos_inicio,
            (COALESCE((SELECT bajas_real FROM bajas_inicio), 0)
             + COALESCE((SELECT bajas_real FROM bajas_starts), 0))::int AS bajas_real,
            (COALESCE((SELECT bajas_buyout FROM bajas_inicio), 0)
             + COALESCE((SELECT bajas_buyout FROM bajas_starts), 0))::int AS bajas_buyout
        )
        SELECT
          activos_inicio AS candidatos_activos,
          bajas_real,
          bajas_buyout,
          (bajas_real + bajas_buyout)::int AS bajas_total_staffing,
          ROUND((bajas_real::numeric / NULLIF(activos_inicio, 0)) * 100, 2)::float AS churn_real_pct,
          ROUND((bajas_buyout::numeric / NULLIF(activos_inicio, 0)) * 100, 2)::float AS buyout_pct,
          ROUND(((bajas_real + bajas_buyout)::numeric / NULLIF(activos_inicio, 0)) * 100, 2)::float AS churn_total_staffing_pct
        FROM totals;
    """

    return sql, {"corte_d": corte_d, "win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "candidate_churn_30d_summary",
    "label": "Churn de candidatos (Staffing) — Resumen 30 días",
    "dimensions": [],
    "measures": [
        {"key": "candidatos_activos", "label": "Candidatos", "type": "number"},
        {"key": "bajas_real", "label": "Bajas Staffing", "type": "number"},
        {"key": "bajas_buyout", "label": "Bajas Buyout", "type": "number"},
        {"key": "bajas_total_staffing", "label": "Bajas Staffing + Buyout", "type": "number"},
        {"key": "churn_real_pct", "label": "Churn Staffing %", "type": "percent"},
        {"key": "buyout_pct", "label": "Churn Buyout %", "type": "percent"},
        {"key": "churn_total_staffing_pct", "label": "Churn Staffing + Buyout %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
