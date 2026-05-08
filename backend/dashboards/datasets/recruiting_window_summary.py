from __future__ import annotations

from datetime import date, datetime


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


def _window_days(filters: dict) -> int:
    raw = (filters.get("window") or filters.get("ventana") or "30d")
    raw = str(raw).strip().lower()
    if raw in ("week", "7d", "7", "semana"):
        return 7
    return 30


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or datetime.utcnow().date()
    )
    window_days = _window_days(filters)

    sql = """
        WITH params AS (
          SELECT
            %(corte)s::date AS corte_d,
            (%(corte)s::date - (%(window_days)s - 1) * INTERVAL '1 day')::date AS win_ini
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
          WHERE o.opp_model = 'Recruiting'
        ),
        revenue_in_window AS (
          SELECT COALESCE(SUM(rh.revenue), 0)::numeric AS revenue_window
          FROM recruiting_hires rh
          CROSS JOIN params p
          WHERE rh.close_d IS NOT NULL
            AND rh.close_d BETWEEN p.win_ini AND p.corte_d
        ),
        new_ftes_in_window AS (
          SELECT COUNT(*)::int AS new_ftes_window
          FROM recruiting_hires rh
          CROSS JOIN params p
          WHERE rh.close_d IS NOT NULL
            AND rh.close_d BETWEEN p.win_ini AND p.corte_d
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
          WHERE fc.first_close_d BETWEEN p.win_ini AND p.corte_d
        ),
        active_clients_in_window AS (
          SELECT COUNT(DISTINCT rh.account_id)::int AS active_clients_window
          FROM recruiting_hires rh
          CROSS JOIN params p
          WHERE rh.close_d IS NOT NULL
            AND rh.close_d BETWEEN p.win_ini AND p.corte_d
            AND rh.account_id IS NOT NULL
        )
        SELECT
          (SELECT corte_d FROM params)               AS corte,
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

    return sql, {"corte": corte, "window_days": window_days}


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
