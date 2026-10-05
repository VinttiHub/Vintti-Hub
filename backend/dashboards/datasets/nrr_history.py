from __future__ import annotations

from datetime import date

from ._mrr_staffing import HIRES_FULL_CTE, unit_snapshot_monthly
from ._nrr_decomp import (
    MEASURES,
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


# Poblacion de los upsells del mes M: vacantes cerradas dentro de (prev_end, fin_mes].
UPS_POBLACION = upsell_population("m.prev_end", "m.fin_mes")


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    metric = _norm_metric(filters.get("metric"))
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    # R5: mismo motor canonico que la card de 30d, mes a mes. Para el mes M la base
    # (`mrr_inicial`) es el MRR al FIN DEL MES ANTERIOR (`prev_end`), de modo que cuadra
    # EXACTO con el GMRR de Management del mes M-1 (anclarla al fin del propio mes
    # inflaba la base). La ventana del mes M es (prev_end, fin_mes].
    sql = f"""
        WITH {HIRES_FULL_CTE},
        meses AS (
          SELECT
            DATE_TRUNC('month', gs)::date                                AS mes,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS fin_mes,
            (DATE_TRUNC('month', gs) - INTERVAL '1 day')::date           AS prev_end
          FROM generate_series(
            (SELECT MIN(start_d) FROM hires_full),
            (SELECT MAX(COALESCE(end_d, CURRENT_DATE)) FROM hires_full),
            INTERVAL '1 month'
          ) gs
        ),
        {unit_snapshot_monthly('unit_ini', 'prev_end', exclude_end_day=True)},
        {unit_snapshot_monthly('unit_fin', 'fin_mes', exclude_end_day=True)},
        {unit_snapshot_monthly('unit_ups', 'fin_mes', UPS_POBLACION)},
        {decomp_cte(
            'unit_ini', 'unit_fin', 'unit_ups', 'hires_full',
            'mm.prev_end', 'mm.fin_mes',
            key='mes', reason_join=' JOIN meses mm ON mm.mes = i.mes',
        )},
        agregado AS (
          SELECT
          {summary_columns(group='mes')}
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
          a.buyouts,
          a.nrr_pct
        FROM agregado a
        WHERE a.mrr_inicial IS NOT NULL AND a.mrr_inicial > 0
          AND (%(desde)s::date IS NULL OR a.mes >= DATE_TRUNC('month', %(desde)s::date))
          AND (%(hasta)s::date IS NULL OR a.mes <= DATE_TRUNC('month', %(hasta)s::date))
        ORDER BY a.mes;
    """

    return sql, {"metric": metric, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "nrr_history",
    "label": "NRR mensual (Staffing)",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": MEASURES,
    "default_filters": {},
    "query": query,
}
