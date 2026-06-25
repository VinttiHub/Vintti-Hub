"""Detalle de New FTEs placed (Recruiting) dentro de una ventana.

Una fila por FTE colocado vía Recruiting = close win con candidato asignado Y
con start date (carga_active o start_date). Reconcilia con el contador
`new_ftes_window` de `recruiting_window_summary`. Ventana via `window` /
`event_window` (week, mtd, month, 30d, 7d, ytd) — misma lógica que el detalle de
revenue para que los totales por ventana coincidan.
"""
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
    raw = str(
        filters.get("event_window")
        or filters.get("window")
        or filters.get("ventana")
        or "30d"
    ).strip().lower()
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
    if raw == "ytd":
        return corte.replace(month=1, day=1), corte
    return window_bounds(filters)


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or today_ar()
    )
    win_ini, win_fin = _window_bounds(filters, corte)

    sql = """
        WITH rh AS (
          SELECT
            ho.candidate_id,
            ho.account_id,
            COALESCE(c.name, '')        AS candidate_name,
            COALESCE(a.client_name, '') AS client_name,
            NULLIF(o.opp_close_date::text, '')::date AS close_d,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text, '')::date
            END AS start_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          LEFT JOIN candidates c ON c.candidate_id = ho.candidate_id
          LEFT JOIN account a    ON a.account_id   = ho.account_id
          WHERE o.opp_model = 'Recruiting'
            AND ho.candidate_id IS NOT NULL
        )
        SELECT
          candidate_name,
          client_name,
          TO_CHAR(start_d, 'YYYY-MM-DD') AS start_date,
          TO_CHAR(close_d, 'YYYY-MM-DD') AS close_date
        FROM rh
        WHERE close_d IS NOT NULL
          AND close_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
          AND start_d IS NOT NULL
        ORDER BY close_d DESC NULLS LAST, candidate_name;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "recruiting_new_ftes_detail",
    "label": "New FTEs placed (Recruiting) — detalle por ventana (close win + start date)",
    "dimensions": [
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "start_date", "label": "Start date", "type": "date"},
        {"key": "close_date", "label": "Close date", "type": "date"},
    ],
    "measures": [],
    "default_filters": {"window": "30d"},
    "query": query,
}
