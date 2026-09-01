from __future__ import annotations

from datetime import date, timedelta

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
    """Same resolution as candidate_churn_30d_detail so this detail and the
    `bajas_buyout` card always share one window."""
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
    # YTD: del 1 de enero al corte. Corta acá a propósito — no delega en
    # window_bounds, así el bloque "Año en curso" del drawer NO se mueve cuando el
    # usuario carga Mes o Desde/Hasta en la barra de filtros.
    if raw in ("ytd", "anio", "year"):
        return corte.replace(month=1, day=1), corte
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

    # Mirror image of candidate_churn_30d_detail: same candidatos/activos_inicio/
    # bajas_starts skeleton, but keeping ONLY the rows that classify as buyout
    # (buyout_daterange >= the month of the baja), which is the exact predicate
    # candidate_churn_30d_summary uses for `bajas_buyout`.
    sql = """
        WITH ventana AS (
          SELECT
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin
        ),
        candidatos AS (
          SELECT
            ho.candidate_id,
            COALESCE(c.name, '') AS candidate_name,
            COALESCE(a.client_name, '') AS client_name,
            COALESCE(ho.fee, 0)::numeric AS fee,
            COALESCE(ho.salary, 0)::numeric AS salary,
            ho.buyout_dolar::numeric AS buyout_dolar,
            NULLIF(TRIM(ho.buyout_daterange), '') AS buyout_mes,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(ho.start_date::text, '') IS NOT NULL THEN ho.start_date::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            CASE
              WHEN NULLIF(TRIM(ho.buyout_daterange), '') IS NOT NULL
                THEN TO_DATE(TRIM(ho.buyout_daterange) || '-01', 'YYYY-MM-DD')
              ELSE NULL
            END AS buyout_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          LEFT JOIN candidates c ON c.candidate_id = ho.candidate_id
          LEFT JOIN account a    ON a.account_id   = ho.account_id
          WHERE ho.candidate_id IS NOT NULL
            AND o.opp_model = 'Staffing'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
        ),
        activos_inicio AS (
          SELECT c.*, v.win_ini, v.win_fin
          FROM candidatos c
          CROSS JOIN ventana v
          WHERE c.start_d IS NOT NULL
            AND c.start_d <= v.win_ini
            AND (c.end_d IS NULL OR c.end_d >= v.win_ini)
        ),
        buyouts_inicio AS (
          SELECT *
          FROM activos_inicio d
          WHERE d.end_d IS NOT NULL
            AND d.end_d BETWEEN d.win_ini AND d.win_fin
            AND d.buyout_d IS NOT NULL
            AND d.buyout_d >= DATE_TRUNC('month', d.end_d)
        ),
        buyouts_starts AS (
          SELECT c.*, v.win_ini, v.win_fin
          FROM candidatos c
          CROSS JOIN ventana v
          WHERE c.start_d IS NOT NULL
            AND c.end_d IS NOT NULL
            AND c.start_d BETWEEN v.win_ini AND v.win_fin
            AND c.end_d   BETWEEN v.win_ini AND v.win_fin
            AND c.buyout_d IS NOT NULL
            AND c.buyout_d >= DATE_TRUNC('month', c.end_d)
        ),
        -- Ancla alternativa: el MES DE BUYOUT (buyout_daterange), no la fecha de baja.
        -- Los dos no siempre coinciden: si el cliente compra el contrato meses después
        -- de que el contractor salió de nuestra nómina (Alberto Ortiz: baja 10-2025,
        -- buyout 01-2026), anclar por baja lo tira al año anterior. Para el acumulado
        -- del año la dueña cuenta por mes de buyout, así que ese bloque pide
        -- anchor=buyout; el card de 30d sigue anclando por baja (es composición de
        -- churn y tiene que cerrar con `bajas_buyout`).
        buyouts_por_mes AS (
          SELECT c.*, v.win_ini, v.win_fin
          FROM candidatos c
          CROSS JOIN ventana v
          WHERE c.buyout_d IS NOT NULL
            AND c.end_d IS NOT NULL
            AND c.buyout_d >= DATE_TRUNC('month', c.end_d)
            AND c.buyout_d BETWEEN DATE_TRUNC('month', v.win_ini) AND v.win_fin
        ),
        all_rows AS (
          SELECT * FROM buyouts_inicio  WHERE %(anchor)s <> 'buyout'
          UNION ALL
          SELECT * FROM buyouts_starts  WHERE %(anchor)s <> 'buyout'
          UNION ALL
          SELECT * FROM buyouts_por_mes WHERE %(anchor)s =  'buyout'
        ),
        -- Un candidato = una fila, igual que el COUNT(DISTINCT candidate_id) del
        -- card `bajas_buyout`: si tiene 2 hires con buyout gana el más reciente.
        dedup AS (
          SELECT DISTINCT ON (candidate_id) *
          FROM all_rows
          ORDER BY candidate_id, end_d DESC NULLS LAST, buyout_dolar DESC NULLS LAST
        )
        SELECT
          TO_CHAR(win_ini, 'YYYY-MM-DD') AS win_ini,
          client_name,
          candidate_name,
          buyout_mes,
          buyout_dolar::float AS buyout_dolar,
          fee::float          AS fee,
          salary::float       AS salary,
          (salary + fee)::float AS gmrr,
          TO_CHAR(start_d, 'YYYY-MM-DD') AS start_d,
          TO_CHAR(end_d,   'YYYY-MM-DD') AS end_d,
          'Buyout'::text AS estado
        FROM dedup
        ORDER BY end_d DESC NULLS LAST, client_name, candidate_name;
    """

    anchor = str(filters.get("anchor") or "").strip().lower()
    return sql, {"win_ini": win_ini, "win_fin": win_fin,
                 "anchor": "buyout" if anchor == "buyout" else "baja"}


DATASET = {
    "key": "buyouts_window_detail",
    "label": "Buyouts (Staffing) — Detalle de la ventana",
    "dimensions": [
        {"key": "win_ini", "label": "Inicio", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "buyout_mes", "label": "Mes de buyout", "type": "string"},
        {"key": "start_d", "label": "Start", "type": "date"},
        {"key": "end_d", "label": "Baja", "type": "date"},
        {"key": "estado", "label": "Estado", "type": "string"},
    ],
    "measures": [
        {"key": "buyout_dolar", "label": "Buyout pagado", "type": "currency"},
        {"key": "fee", "label": "Fee mensual", "type": "currency"},
        {"key": "salary", "label": "Salary mensual", "type": "currency"},
        {"key": "gmrr", "label": "GMRR mensual", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
