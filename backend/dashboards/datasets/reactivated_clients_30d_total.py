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
    """Resolve (win_ini, win_fin) from the `window` filter. Mirrors
    new_clients_30d_total so ambos tiles usan exactamente la misma ventana.
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


# Base compartida con reactivated_clients_30d_detail: un "reactivado" es una
# cuenta que pasa de 0 hires activos a >= 1 en la fecha `start_d`, y donde esa
# no es su primera alta histórica (esa sería un "new client").
#
# Con esto cierra la identidad del tab Staffing:
#   Active clients = Active previo + New clients + Reactivated - Churn clients
_BASE_SQL = """
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini, %(win_fin)s::date AS win_fin
        ),
        hires AS (
          SELECT
            ho.account_id,
            ho.candidate_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text,'')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text,'') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d
          FROM hire_opportunity ho
          JOIN opportunity o
            ON o.opportunity_id = ho.opportunity_id
           AND o.opp_model = 'Staffing'
          LEFT JOIN account a ON a.account_id = ho.account_id
          WHERE ho.account_id IS NOT NULL
            AND ho.candidate_id IS NOT NULL
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
        ),
        first_hire_per_account AS (
          SELECT account_id, MIN(start_d) AS first_d
          FROM hires
          WHERE start_d IS NOT NULL
          GROUP BY account_id
        ),
        reactivation_events AS (
          SELECT DISTINCT ON (h.account_id, h.start_d)
            h.account_id,
            h.start_d,
            h.candidate_id
          FROM hires h
          JOIN first_hire_per_account fh ON fh.account_id = h.account_id
          WHERE h.start_d IS NOT NULL
            AND h.start_d > fh.first_d
            AND NOT EXISTS (
              SELECT 1
              FROM hires h2
              WHERE h2.account_id = h.account_id
                AND h2.start_d IS NOT NULL
                AND h2.start_d <= h.start_d - 1
                AND (h2.end_d IS NULL OR h2.end_d >= h.start_d - 1)
            )
          ORDER BY h.account_id, h.start_d, h.candidate_id
        )
"""


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("fecha_corte"))
        or _parse_date(filters.get("cutoff"))
        or today_ar()
    )
    win_ini, win_fin = _window_bounds(filters, corte)

    sql = _BASE_SQL + """
        SELECT
          COUNT(*)::int AS reactivated_clients_30d
        FROM reactivation_events re
        CROSS JOIN ventana v
        WHERE re.start_d BETWEEN v.win_ini AND v.win_fin;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "reactivated_clients_30d_total",
    "label": "Reactivated Clients — Total por ventana (Staffing)",
    "dimensions": [],
    "measures": [
        {"key": "reactivated_clients_30d", "label": "Clientes reactivados", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
