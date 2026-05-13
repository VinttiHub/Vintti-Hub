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
    """`week` = previous full calendar week (Mon-Sun); `7d` = rolling 7 days.

    The default 30d window uses a 30-day offset to match the boundary used by
    `candidate_churn_30d_summary` (the dataset that supplies the denominator's
    raw count). Without this alignment the two tiles disagree by ±1.
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
    return corte - timedelta(days=29), corte


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or datetime.utcnow().date()
    )
    win_ini, win_fin = _window_bounds(filters, corte)

    # % Reemplazos colocados = (Replacement opps Close Win en 30d) / (candidate
    # churn en 30d). Both metrics restricted to Staffing.
    #   - Numerator   `placed_count`: opportunity_id where opp_type='Replacement'
    #                                  AND opp_stage='Close Win'
    #                                  AND opp_close_date in window.
    #   - Denominator `churn_count` : distinct candidates whose end_d falls in the
    #                                  window (excluding buyouts), same logic as
    #                                  candidate_churn_30d_summary.bajas_real.
    sql = """
        WITH ventana AS (
          SELECT
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin
        ),
        replacement_wins_in_window AS (
          SELECT COUNT(*)::int AS placed_count
          FROM opportunity o
          CROSS JOIN ventana v
          WHERE o.opp_type = 'Replacement'
            AND TRIM(o.opp_stage) = 'Close Win'
            AND o.opp_close_date IS NOT NULL
            AND NULLIF(o.opp_close_date::text, '')::date BETWEEN v.win_ini AND v.win_fin
        ),
        candidatos AS (
          SELECT
            ho.candidate_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(ho.start_date::text,'') IS NOT NULL THEN ho.start_date::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text,'') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            CASE
              WHEN NULLIF(TRIM(ho.buyout_daterange::text), '') IS NOT NULL
                THEN TO_DATE(NULLIF(TRIM(ho.buyout_daterange::text), '') || '-01', 'YYYY-MM-DD')
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
          SELECT COUNT(DISTINCT a.candidate_id) FILTER (
            WHERE NOT (a.buyout_d IS NOT NULL AND a.buyout_d >= DATE_TRUNC('month', a.end_d))
          )::int AS bajas_real
          FROM activos_inicio a
          CROSS JOIN ventana v
          WHERE a.end_d IS NOT NULL
            AND a.end_d BETWEEN v.win_ini AND v.win_fin
        ),
        bajas_starts AS (
          SELECT COUNT(DISTINCT c.candidate_id) FILTER (
            WHERE NOT (c.buyout_d IS NOT NULL AND c.buyout_d >= DATE_TRUNC('month', c.end_d))
          )::int AS bajas_real
          FROM candidatos c
          CROSS JOIN ventana v
          WHERE c.start_d IS NOT NULL
            AND c.end_d   IS NOT NULL
            AND c.start_d BETWEEN v.win_ini AND v.win_fin
            AND c.end_d   BETWEEN v.win_ini AND v.win_fin
        ),
        candidate_churn_in_window AS (
          SELECT (
            COALESCE((SELECT bajas_real FROM bajas_inicio), 0)
            + COALESCE((SELECT bajas_real FROM bajas_starts), 0)
          )::int AS churn_count
        )
        SELECT
          (SELECT win_ini FROM ventana)              AS ventana_desde,
          (SELECT win_fin FROM ventana)              AS ventana_hasta,
          cc.churn_count                             AS churn_count,
          rw.placed_count                            AS placed_count,
          ROUND(
            CASE
              WHEN cc.churn_count = 0 THEN NULL
              ELSE 100.0 * rw.placed_count::numeric / cc.churn_count
            END, 2
          )::float                                   AS placed_pct
        FROM replacement_wins_in_window rw
        CROSS JOIN candidate_churn_in_window cc;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "replacement_coverage_30d",
    "label": "% Reemplazos colocados — ventana 30d",
    "dimensions": [
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "churn_count", "label": "Candidate churn en ventana", "type": "number"},
        {"key": "placed_count", "label": "Replacements Close Win en ventana", "type": "number"},
        {"key": "placed_pct", "label": "% Reemplazos colocados", "type": "percent"},
    ],
    "default_filters": {"window": "30d"},
    "query": query,
}
