from __future__ import annotations

from datetime import date, datetime, timedelta
from ._now import today_ar

from ._periods import window_bounds
from .reactivated_clients_30d_total import _BASE_SQL


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
    """Igual que reactivated_clients_30d_total, pero `event_window` (click en un
    tile del drawer) tiene prioridad sobre la ventana global.
    """
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
    return window_bounds(filters)


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("fecha_corte"))
        or _parse_date(filters.get("cutoff"))
        or today_ar()
    )
    win_ini, win_fin = _window_bounds(filters, corte)

    sql = _BASE_SQL + """
        , baja_previa AS (
          SELECT
            re.account_id,
            re.start_d,
            (
              SELECT MAX(h3.end_d)
              FROM hires h3
              WHERE h3.account_id = re.account_id
                AND h3.end_d IS NOT NULL
                AND h3.end_d < re.start_d
            ) AS fecha_baja_previa
          FROM reactivation_events re
        )
        SELECT
          TO_CHAR(re.start_d, 'YYYY-MM-DD') AS start_date,
          a.client_name,
          c.name AS candidate_name,
          TO_CHAR(bp.fecha_baja_previa, 'YYYY-MM-DD') AS fecha_baja_previa,
          (re.start_d - bp.fecha_baja_previa)::int    AS dias_inactivo
        FROM reactivation_events re
        CROSS JOIN ventana v
        LEFT JOIN baja_previa bp
          ON bp.account_id = re.account_id AND bp.start_d = re.start_d
        LEFT JOIN account    a ON a.account_id   = re.account_id
        LEFT JOIN candidates c ON c.candidate_id = re.candidate_id
        WHERE re.start_d BETWEEN v.win_ini AND v.win_fin
        ORDER BY re.start_d;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "reactivated_clients_30d_detail",
    "label": "Reactivated Clients — Detalle por ventana (Staffing)",
    "dimensions": [
        {"key": "start_date", "label": "Vuelta", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "fecha_baja_previa", "label": "Baja previa", "type": "date"},
    ],
    "measures": [
        {"key": "dias_inactivo", "label": "Días inactivo", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
