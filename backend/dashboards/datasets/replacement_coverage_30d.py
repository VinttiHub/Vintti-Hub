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

    # % Reemplazos colocados — per user definition:
    #   - Numerator   `placed_count`: Replacement opps OPENED in the window.
    #                                  "Opened" = nda_signature_or_start_date in window.
    #   - Denominator `churn_count` : Replacement opps CLOSED in the window (any
    #                                  closing stage, not only Close Win).
    #                                  "Closed" = opp_close_date in window.
    sql = """
        WITH ventana AS (
          SELECT
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin
        ),
        replacement_opps AS (
          SELECT
            o.opportunity_id,
            TRIM(COALESCE(o.opp_stage, '')) AS stage,
            NULLIF(o.nda_signature_or_start_date::text, '')::date AS opened_d,
            NULLIF(o.opp_close_date::text, '')::date              AS closed_d
          FROM opportunity o
          WHERE o.opp_type = 'Replacement'
        ),
        replacement_totals AS (
          SELECT
            COUNT(*) FILTER (
              WHERE r.opened_d BETWEEN v.win_ini AND v.win_fin
            )::int AS placed_count,
            COUNT(*) FILTER (
              WHERE r.closed_d BETWEEN v.win_ini AND v.win_fin
            )::int AS churn_count
          FROM replacement_opps r
          CROSS JOIN ventana v
        )
        SELECT
          (SELECT win_ini FROM ventana)              AS ventana_desde,
          (SELECT win_fin FROM ventana)              AS ventana_hasta,
          rt.churn_count                             AS churn_count,
          rt.placed_count                            AS placed_count,
          ROUND(
            CASE
              WHEN rt.churn_count = 0 THEN NULL
              ELSE 100.0 * rt.placed_count::numeric / rt.churn_count
            END, 2
          )::float                                   AS placed_pct
        FROM replacement_totals rt;
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
        {"key": "placed_count", "label": "Replacements abiertas en ventana", "type": "number"},
        {"key": "churn_count", "label": "Replacements cerradas en ventana", "type": "number"},
        {"key": "placed_pct", "label": "% Reemplazos colocados (abiertas / cerradas)", "type": "percent"},
    ],
    "default_filters": {"window": "30d"},
    "query": query,
}
