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
    """Resolve (win_ini, win_fin) from the `window` filter. Default: rolling
    last 30d (29-day offset). Mirrors client_churn_30d_summary.
    """
    # event_window (drawer-tile click) takes priority over the global window.
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
    return corte - timedelta(days=29), corte


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or datetime.utcnow().date()
    )
    win_ini, win_fin = _window_bounds(filters, corte)

    sql = """
        WITH ventana AS (
          SELECT
            %(win_fin)s::date AS corte_d,
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
            AND (
              ho.carga_active IS NOT NULL
              OR NULLIF(ho.start_date::text,'') IS NOT NULL
            )
        ),
        clientes_en_ventana AS (
          SELECT DISTINCT h.account_id
          FROM hires h
          CROSS JOIN ventana v
          WHERE
            (h.start_d <= v.win_ini AND COALESCE(h.end_d, DATE '9999-12-31') >= v.win_ini)
            OR (h.start_d >= v.win_ini AND h.start_d <= v.win_fin)
        ),
        ultima_baja_raw AS (
          SELECT account_id, MAX(end_d) AS fecha_baja
          FROM hires
          WHERE end_d IS NOT NULL
          GROUP BY 1
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
          GROUP BY 1
        ),
        bajas_clasificadas AS (
          SELECT
            ub.account_id,
            ub.fecha_baja::date AS fecha_baja,
            CASE
              WHEN b.buyout_d IS NOT NULL
               AND b.buyout_d >= DATE_TRUNC('month', ub.fecha_baja)
              THEN 'Churn – Buyout (Conversión)'
              ELSE 'Churn – Real'
            END AS tipo_churn
          FROM ultima_baja ub
          LEFT JOIN buyout_por_cuenta b ON b.account_id = ub.account_id
        ),
        bajas_ventana AS (
          SELECT
            v.win_ini,
            v.win_fin,
            bc.account_id,
            bc.fecha_baja,
            bc.tipo_churn
          FROM ventana v
          JOIN bajas_clasificadas bc ON TRUE
          JOIN clientes_en_ventana cev ON cev.account_id = bc.account_id
          WHERE bc.fecha_baja >= v.win_ini
            AND bc.fecha_baja <= v.win_fin
        )
        -- Return only "Churn – Real" rows so the detail list matches the
        -- bajas_real card count. Other states (Activo, Buyout) are filtered out.
        SELECT
          TO_CHAR(v.win_ini, 'YYYY-MM-DD') AS win_ini,
          TO_CHAR(v.win_fin, 'YYYY-MM-DD') AS win_fin,
          a.client_name,
          TO_CHAR(bv.fecha_baja, 'YYYY-MM-DD') AS fecha_baja,
          bv.tipo_churn AS estado_cliente_ventana
        FROM ventana v
        JOIN bajas_ventana bv ON TRUE
        JOIN account a ON a.account_id = bv.account_id
        WHERE bv.tipo_churn = 'Churn – Real'
        ORDER BY bv.fecha_baja DESC, a.client_name;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "client_churn_30d_detail",
    "label": "Churn de clientes (Staffing) — Detalle ventana 30 días",
    "dimensions": [
        {"key": "win_ini", "label": "Inicio", "type": "date"},
        {"key": "win_fin", "label": "Fin", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "fecha_baja", "label": "Fecha baja", "type": "date"},
        {"key": "estado_cliente_ventana", "label": "Estado", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
