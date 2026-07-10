from __future__ import annotations

from datetime import date, datetime, timedelta
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
    return window_bounds(filters)


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or today_ar()
    )
    win_ini, win_fin = _window_bounds(filters, corte)

    # % Reemplazos colocados = de los REEMPLAZOS QUE SE CERRARON en la ventana, qué %
    # fue Close Win.
    #   - Denominator `placed_count`: Replacement opps CLOSED (decididas) en la ventana
    #                                  = stage IN (Close Win, Closed Lost) y opp_close_date en ventana.
    #   - Numerator   `churn_count` : de esas, las que son Close Win.
    #   - placed_pct  = Close Win ÷ cerradas.
    sql = """
        WITH ventana AS (
          SELECT
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin
        ),
        replacement_closed AS (
          SELECT
            o.opportunity_id,
            (TRIM(o.opp_stage) = 'Close Win') AS won
          FROM opportunity o
          LEFT JOIN account a ON a.account_id = o.account_id
          CROSS JOIN ventana v
          WHERE o.opp_type = 'Replacement'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND TRIM(COALESCE(o.opp_stage, '')) IN ('Close Win', 'Closed Lost')
            AND NULLIF(o.opp_close_date::text, '')::date BETWEEN v.win_ini AND v.win_fin
        )
        SELECT
          (SELECT win_ini FROM ventana)                          AS ventana_desde,
          (SELECT win_fin FROM ventana)                          AS ventana_hasta,
          COUNT(*) FILTER (WHERE won)::int                       AS churn_count,
          COUNT(*)::int                                          AS placed_count,
          ROUND(
            CASE
              WHEN COUNT(*) = 0 THEN NULL
              ELSE 100.0 * COUNT(*) FILTER (WHERE won)::numeric / COUNT(*)
            END, 2
          )::float                                               AS placed_pct
        FROM replacement_closed;
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
        {"key": "placed_count", "label": "Replacements cerrados en ventana", "type": "number"},
        {"key": "churn_count", "label": "Replacements Close Win en ventana", "type": "number"},
        {"key": "placed_pct", "label": "% Reemplazos colocados (Close Win / cerrados)", "type": "percent"},
    ],
    "default_filters": {"window": "30d"},
    "query": query,
}
