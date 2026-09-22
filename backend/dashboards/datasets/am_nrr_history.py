"""NRR del AM, mes a mes. Ver `am_nrr_30d_summary` para la definicion."""
from __future__ import annotations

from datetime import date

from ._am_mrr_staffing import HIRES_CTE, ae_leads, am_unit_snapshot_monthly
from ._nrr_decomp import (
    MEASURES_AM,
    decomp_cte,
    summary_columns,
    upsell_population,
)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.split("-")
    try:
        if len(parts) >= 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def _norm_metric(value) -> str:
    raw = str(value or "").strip().lower()
    if raw == "fee":
        return "Fee"
    if raw == "revenue":
        return "Revenue"
    return "All"


# En el motor del AM la fecha de Close Win se llama `close_d`, no `opp_close_d`.
UPS_POBLACION = upsell_population("m.prev_end", "m.fin_mes", col="close_d")

MESES_CTE = """
        meses AS (
          SELECT
            DATE_TRUNC('month', gs)::date                                AS mes,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS fin_mes,
            (DATE_TRUNC('month', gs) - INTERVAL '1 day')::date           AS prev_end
          FROM generate_series(
            (SELECT MIN(start_d) FROM hires),
            (SELECT MAX(COALESCE(end_d, CURRENT_DATE)) FROM hires),
            INTERVAL '1 month'
          ) gs
        )"""


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    metric = _norm_metric(filters.get("metric"))
    am = str(filters.get("am") or "").strip().lower()
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    sql = f"""
        WITH {HIRES_CTE},
        {MESES_CTE},
        {am_unit_snapshot_monthly('unit_ini', 'prev_end')},
        {am_unit_snapshot_monthly('unit_fin', 'fin_mes')},
        {am_unit_snapshot_monthly('unit_ups', 'fin_mes', UPS_POBLACION)},
        {decomp_cte(
            'unit_ini', 'unit_fin', 'unit_ups', 'hires',
            'mm.prev_end', 'mm.fin_mes',
            owned=True, key='mes', reason_join=' JOIN meses mm ON mm.mes = i.mes',
        )},
        agregado AS (
          SELECT
          {summary_columns(group='mes', owned=True)}
          FROM nrr_rows
          GROUP BY mes
        )
        SELECT
          TO_CHAR(a.mes, 'YYYY-MM-DD') AS mes,
          a.mrr_inicial,
          a.upsells,
          a.salary_updates,
          a.expansion_precio,
          a.contraccion,
          a.downgrades_recorte,
          a.churn_no_recorte,
          a.entradas_m3,
          a.nrr_pct
        FROM agregado a
        WHERE a.mrr_inicial IS NOT NULL AND a.mrr_inicial > 0
          AND (%(desde)s::date IS NULL OR a.mes >= DATE_TRUNC('month', %(desde)s::date))
          AND (%(hasta)s::date IS NULL OR a.mes <= DATE_TRUNC('month', %(hasta)s::date))
        ORDER BY a.mes;
    """

    return sql, {
        "metric": metric,
        "am": am,
        "desde": desde,
        "hasta": hasta,
        "ae_leads": ae_leads(),
    }


DATASET = {
    "key": "am_nrr_history",
    "label": "NRR del AM (mensual)",
    "dimensions": [{"key": "mes", "label": "Mes", "type": "date"}],
    "measures": MEASURES_AM,
    "default_filters": {},
    "query": query,
}
