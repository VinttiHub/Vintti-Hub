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
    """Resolve (win_ini, win_fin) from the `window` filter. Default: last 30d (29-day offset)."""
    raw = str(filters.get("window") or filters.get("ventana") or "30d").strip().lower()
    if raw in ("week", "7d", "7", "semana"):
        return corte - timedelta(days=6), corte
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
        or _parse_date(filters.get("fecha_corte"))
        or _parse_date(filters.get("cutoff"))
        or datetime.utcnow().date()
    )
    win_ini, win_fin = _window_bounds(filters, corte)

    sql = """
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini, %(win_fin)s::date AS win_fin
        ),
        base AS (
          SELECT
            ho.account_id,
            ho.candidate_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text,'')::date
            END AS start_d,
            ROW_NUMBER() OVER (
              PARTITION BY ho.account_id
              ORDER BY
                CASE
                  WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                  ELSE NULLIF(ho.start_date::text,'')::date
                END,
                ho.candidate_id
            ) AS rn
          FROM hire_opportunity ho
          JOIN opportunity o
            ON o.opportunity_id = ho.opportunity_id
           AND o.opp_model = 'Staffing'
          WHERE ho.account_id IS NOT NULL
            AND ho.candidate_id IS NOT NULL
            AND (
              CASE
                WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                ELSE NULLIF(ho.start_date::text,'')::date
              END
            ) IS NOT NULL
        ),
        first_hire AS (
          SELECT account_id, candidate_id, start_d
          FROM base
          WHERE rn = 1
        )
        SELECT
          COUNT(*)::int AS new_clients_30d
        FROM first_hire fh
        CROSS JOIN ventana v
        WHERE fh.start_d BETWEEN v.win_ini AND v.win_fin;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "new_clients_30d_total",
    "label": "New Clients — 30d Rolling Total (Staffing)",
    "dimensions": [],
    "measures": [
        {"key": "new_clients_30d", "label": "Nuevos clientes (30d)", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
