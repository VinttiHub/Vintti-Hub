"""Avg Setup Fee · Breakdown — últimos 30 días, M+B (Staffing only).

Promedio del setup fee cobrado en deals Staffing Close Win de Mariano + Bahia
cuya `opp_close_date` cae en los últimos 30 días, partido en:
  - `with_pc`:    `ho.computer` = 'yes'  (Vintti provee computadora)
  - `without_pc`: `ho.computer` ∈ {'no', '', NULL}

Devuelve también la ventana anterior (días -59..-30) para calcular delta y la
proporción relativa de cada avg para el bar de distribución.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from ._now import today_ar


SALES_LEADS = ("mariano@vintti.com", "bahia@vintti.com")


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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or today_ar()
    )
    win_fin = corte
    win_ini = corte - timedelta(days=29)
    prev_fin = win_ini - timedelta(days=1)
    prev_ini = prev_fin - timedelta(days=29)

    sql = """
        WITH ae_wins AS (
          SELECT
            o.opportunity_id,
            NULLIF(o.opp_close_date::text, '')::date AS close_d
          FROM opportunity o
          LEFT JOIN account a ON a.account_id = o.account_id
          WHERE o.opp_model = 'Staffing'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
            AND TRIM(o.opp_stage) = 'Close Win'
        ),
        per_opp AS (
          -- One row per opp: SUM setup_fee de todos los hires del deal.
          -- has_pc del deal = TRUE si CUALQUIER hire tiene computer='yes'.
          -- Esto evita doble conteo cuando una opp tiene N candidatos (ej Theta).
          SELECT
            w.opportunity_id,
            w.close_d,
            COALESCE(SUM(ho.setup_fee), 0)::numeric                       AS deal_setup_fee,
            BOOL_OR(LOWER(TRIM(COALESCE(ho.computer, ''))) = 'yes')       AS has_pc
          FROM ae_wins w
          JOIN hire_opportunity ho ON ho.opportunity_id = w.opportunity_id
          WHERE ho.candidate_id IS NOT NULL
          GROUP BY w.opportunity_id, w.close_d
        ),
        cur AS (
          SELECT * FROM per_opp
          WHERE close_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
        ),
        prev AS (
          SELECT * FROM per_opp
          WHERE close_d BETWEEN %(prev_ini)s::date AND %(prev_fin)s::date
        ),
        agg AS (
          SELECT
            COALESCE(AVG(deal_setup_fee), 0)::numeric                          AS avg_total,
            COALESCE(AVG(deal_setup_fee) FILTER (WHERE has_pc), 0)::numeric    AS avg_with_pc,
            COALESCE(AVG(deal_setup_fee) FILTER (WHERE NOT has_pc), 0)::numeric AS avg_without_pc,
            COUNT(*)::int                                                      AS count_total,
            COUNT(*) FILTER (WHERE has_pc)::int                                AS count_with_pc,
            COUNT(*) FILTER (WHERE NOT has_pc)::int                            AS count_without_pc
          FROM cur
        ),
        agg_prev AS (
          SELECT
            COALESCE(AVG(deal_setup_fee), 0)::numeric                          AS avg_total,
            COALESCE(AVG(deal_setup_fee) FILTER (WHERE has_pc), 0)::numeric    AS avg_with_pc,
            COALESCE(AVG(deal_setup_fee) FILTER (WHERE NOT has_pc), 0)::numeric AS avg_without_pc
          FROM prev
        )
        SELECT
          %(win_ini)s::date                                              AS win_ini,
          %(win_fin)s::date                                              AS win_fin,
          a.avg_total,
          a.avg_with_pc,
          a.avg_without_pc,
          a.count_total,
          a.count_with_pc,
          a.count_without_pc,
          CASE WHEN a.count_total = 0 THEN 0
               ELSE ROUND(100.0 * a.count_with_pc / a.count_total, 1)
          END                                                            AS pct_count_with_pc,
          CASE WHEN a.count_total = 0 THEN 0
               ELSE ROUND(100.0 * a.count_without_pc / a.count_total, 1)
          END                                                            AS pct_count_without_pc,
          CASE WHEN (a.avg_with_pc + a.avg_without_pc) = 0 THEN 0
               ELSE ROUND(100.0 * a.avg_with_pc / (a.avg_with_pc + a.avg_without_pc), 1)
          END                                                            AS pct_dist_with_pc,
          CASE WHEN (a.avg_with_pc + a.avg_without_pc) = 0 THEN 0
               ELSE ROUND(100.0 * a.avg_without_pc / (a.avg_with_pc + a.avg_without_pc), 1)
          END                                                            AS pct_dist_without_pc,
          (a.avg_total       - p.avg_total)::numeric                     AS delta_total_abs,
          (a.avg_with_pc     - p.avg_with_pc)::numeric                   AS delta_with_pc_abs,
          (a.avg_without_pc  - p.avg_without_pc)::numeric                AS delta_without_pc_abs
        FROM agg a, agg_prev p;
    """

    return sql, {
        "sales_leads": SALES_LEADS,
        "win_ini": win_ini,
        "win_fin": win_fin,
        "prev_ini": prev_ini,
        "prev_fin": prev_fin,
    }


DATASET = {
    "key": "avg_setup_fee_30d",
    "label": "Avg Setup Fee · Breakdown — últimos 30 días (Staffing · M+B)",
    "dimensions": [
        {"key": "win_ini", "label": "Inicio ventana", "type": "date"},
        {"key": "win_fin", "label": "Corte", "type": "date"},
    ],
    "measures": [
        {"key": "avg_total", "label": "Avg setup fee total", "type": "currency"},
        {"key": "avg_with_pc", "label": "Avg setup fee CON PC", "type": "currency"},
        {"key": "avg_without_pc", "label": "Avg setup fee SIN PC", "type": "currency"},
        {"key": "count_total", "label": "Deals (window)", "type": "number"},
        {"key": "count_with_pc", "label": "Deals CON PC (window)", "type": "number"},
        {"key": "count_without_pc", "label": "Deals SIN PC (window)", "type": "number"},
        {"key": "pct_count_with_pc", "label": "% deals CON PC", "type": "percent"},
        {"key": "pct_count_without_pc", "label": "% deals SIN PC", "type": "percent"},
        {"key": "pct_dist_with_pc", "label": "% avg CON / total avg", "type": "percent"},
        {"key": "pct_dist_without_pc", "label": "% avg SIN / total avg", "type": "percent"},
        {"key": "delta_total_abs", "label": "Δ total vs prev 30d", "type": "currency"},
        {"key": "delta_with_pc_abs", "label": "Δ CON vs prev 30d", "type": "currency"},
        {"key": "delta_without_pc_abs", "label": "Δ SIN vs prev 30d", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
