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
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or datetime.utcnow().date()
    )
    win_ini, win_fin = _window_bounds(filters, corte)

    # Numerator  : churned accounts in the window that ALSO have a Replacement Close Win
    #              for the same account_id (no time-limit per user spec).
    # Denominator: churned accounts in the window (same churn definition as
    #              client_churn_30d_summary — Staffing real bajas, no buyouts).
    sql = """
        WITH ventana AS (
          SELECT
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin
        ),
        hires AS (
          SELECT
            ho.account_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text,'')::date
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
          WHERE ho.account_id IS NOT NULL
            AND o.opp_model = 'Staffing'
        ),
        ultima_baja_raw AS (
          SELECT account_id, MAX(end_d) AS fecha_baja
          FROM hires
          WHERE end_d IS NOT NULL
          GROUP BY account_id
        ),
        cuentas_con_activos_posteriores AS (
          SELECT DISTINCT ub.account_id
          FROM ultima_baja_raw ub
          JOIN hires h
            ON h.account_id = ub.account_id
           AND COALESCE(h.end_d, DATE '9999-12-31') > ub.fecha_baja
        ),
        ultima_baja AS (
          SELECT *
          FROM ultima_baja_raw
          WHERE account_id NOT IN (SELECT account_id FROM cuentas_con_activos_posteriores)
        ),
        buyout_por_cuenta AS (
          SELECT account_id, MAX(buyout_d) AS buyout_d
          FROM hires
          WHERE buyout_d IS NOT NULL
          GROUP BY account_id
        ),
        churns_in_window AS (
          SELECT ub.account_id
          FROM ultima_baja ub
          LEFT JOIN buyout_por_cuenta b ON b.account_id = ub.account_id
          CROSS JOIN ventana v
          WHERE ub.fecha_baja BETWEEN v.win_ini AND v.win_fin
            AND NOT (
              b.buyout_d IS NOT NULL
              AND b.buyout_d >= DATE_TRUNC('month', ub.fecha_baja)
            )
        ),
        accounts_with_replacement_win AS (
          SELECT DISTINCT o.account_id
          FROM opportunity o
          WHERE o.opp_type = 'Replacement'
            AND TRIM(o.opp_stage) = 'Close Win'
            AND o.account_id IS NOT NULL
        )
        SELECT
          (SELECT win_ini FROM ventana)                                AS ventana_desde,
          (SELECT win_fin FROM ventana)                                AS ventana_hasta,
          COALESCE((SELECT COUNT(*) FROM churns_in_window), 0)::int    AS churn_count,
          COALESCE((
            SELECT COUNT(*)
            FROM churns_in_window c
            WHERE c.account_id IN (SELECT account_id FROM accounts_with_replacement_win)
          ), 0)::int                                                   AS placed_count,
          ROUND(
            CASE
              WHEN (SELECT COUNT(*) FROM churns_in_window) = 0 THEN NULL
              ELSE 100.0 * (
                SELECT COUNT(*)
                FROM churns_in_window c
                WHERE c.account_id IN (SELECT account_id FROM accounts_with_replacement_win)
              )::numeric / (SELECT COUNT(*) FROM churns_in_window)
            END, 2
          )::float                                                     AS placed_pct;
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
        {"key": "churn_count", "label": "Churns en ventana", "type": "number"},
        {"key": "placed_count", "label": "Churns con replacement Close Win", "type": "number"},
        {"key": "placed_pct", "label": "% Reemplazos colocados", "type": "percent"},
    ],
    "default_filters": {"window": "30d"},
    "query": query,
}
