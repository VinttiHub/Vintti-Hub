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
    """Resolve (win_ini, win_fin) from the `window` filter. Default: last 30d (29-day offset).

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
    if raw in ("ytd", "year_to_date", "year-to-date"):
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
    window_days = (win_fin - win_ini).days + 1

    sql = """
        WITH params AS (
          SELECT
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin
        ),
        recruiting_hires AS (
          SELECT
            ho.account_id,
            ho.candidate_id,
            ho.opportunity_id,
            COALESCE(ho.revenue, 0)::numeric AS revenue,
            o.opp_close_date::date           AS close_d,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text,'')::date
            END AS start_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          LEFT JOIN account a ON a.account_id = ho.account_id
          WHERE o.opp_model = 'Recruiting'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            -- Solo cuentan los que realmente arrancaron: deben tener start date
            -- (carga_active o start_date). Aplica a FTEs, revenue, new clients y activos.
            AND (ho.carga_active IS NOT NULL OR NULLIF(ho.start_date::text, '') IS NOT NULL)
        ),
        revenue_in_window AS (
          SELECT COALESCE(SUM(rh.revenue), 0)::numeric AS revenue_window
          FROM recruiting_hires rh
          CROSS JOIN params p
          WHERE rh.close_d IS NOT NULL
            AND rh.close_d BETWEEN p.win_ini AND p.win_fin
        ),
        new_ftes_in_window AS (
          -- FTE colocado = close win en la ventana, con candidato asignado y start
          -- date (el start date ya viene garantizado por el filtro de recruiting_hires).
          SELECT COUNT(*)::int AS new_ftes_window
          FROM recruiting_hires rh
          CROSS JOIN params p
          WHERE rh.close_d IS NOT NULL
            AND rh.close_d BETWEEN p.win_ini AND p.win_fin
            AND rh.candidate_id IS NOT NULL
        ),
        first_close AS (
          SELECT account_id, MIN(close_d) AS first_close_d
          FROM recruiting_hires
          WHERE close_d IS NOT NULL
            AND account_id IS NOT NULL
          GROUP BY account_id
        ),
        new_clients_in_window AS (
          SELECT COUNT(*)::int AS new_clients_window
          FROM first_close fc
          CROSS JOIN params p
          WHERE fc.first_close_d BETWEEN p.win_ini AND p.win_fin
        ),
        active_clients_in_window AS (
          SELECT COUNT(DISTINCT rh.account_id)::int AS active_clients_window
          FROM recruiting_hires rh
          CROSS JOIN params p
          WHERE rh.close_d IS NOT NULL
            AND rh.close_d BETWEEN p.win_ini AND p.win_fin
            AND rh.account_id IS NOT NULL
        )
        SELECT
          (SELECT win_fin FROM params)               AS corte,
          (SELECT win_ini FROM params)               AS win_ini,
          %(window_days)s::int                       AS window_days,
          rw.revenue_window::bigint                  AS revenue_window,
          nf.new_ftes_window,
          nc.new_clients_window,
          ac.active_clients_window
        FROM revenue_in_window rw,
             new_ftes_in_window nf,
             new_clients_in_window nc,
             active_clients_in_window ac;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin, "window_days": window_days}


DATASET = {
    "key": "recruiting_window_summary",
    "label": "Recruiting — Snapshot por ventana (week | 30d)",
    "dimensions": [
        {"key": "corte", "label": "Corte", "type": "date"},
        {"key": "win_ini", "label": "Inicio ventana", "type": "date"},
        {"key": "window_days", "label": "Ventana (días)", "type": "number"},
    ],
    "measures": [
        {"key": "revenue_window", "label": "Revenue (window)", "type": "currency"},
        {"key": "new_ftes_window", "label": "Nuevos FTEs (window)", "type": "number"},
        {"key": "new_clients_window", "label": "Nuevos clientes Recruiting (window)", "type": "number"},
        {"key": "active_clients_window", "label": "Active clients Recruiting (window)", "type": "number"},
    ],
    "default_filters": {"window": "30d"},
    "query": query,
}
