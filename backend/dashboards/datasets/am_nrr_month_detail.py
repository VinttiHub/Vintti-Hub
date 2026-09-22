"""Drawer mensual del NRR del AM. Sale del MISMO `nrr_rows` que la serie."""
from __future__ import annotations

from datetime import date

from ._am_mrr_staffing import HIRES_CTE, ae_leads, am_unit_snapshot_monthly
from ._nrr_decomp import decomp_cte
from .am_nrr_history import UPS_POBLACION
from .nrr_30d_detail import DETAIL_SELECT, DIMENSIONS, MEASURES, unit_info_cte


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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    metric = _norm_metric(filters.get("metric"))
    am = str(filters.get("am") or "").strip().lower()
    mes = (
        _parse_date(filters.get("fecha_nrr_am"))
        or _parse_date(filters.get("fecha_nrr"))
        or _parse_date(filters.get("mes_click"))
        or _parse_date(filters.get("mes"))
    )

    sql = f"""
        WITH {HIRES_CTE},
        {unit_info_cte('hires', close_col='close_d')},
        meses AS (
          SELECT
            m.mes,
            (m.mes + INTERVAL '1 month - 1 day')::date AS fin_mes,
            (m.mes - INTERVAL '1 day')::date           AS prev_end
          FROM (
            SELECT COALESCE(
              DATE_TRUNC('month', %(mes)s::date)::date,
              DATE_TRUNC('month', CURRENT_DATE)::date
            ) AS mes
          ) m
        ),
        {am_unit_snapshot_monthly('unit_ini', 'prev_end')},
        {am_unit_snapshot_monthly('unit_fin', 'fin_mes')},
        {am_unit_snapshot_monthly('unit_ups', 'fin_mes', UPS_POBLACION)},
        {decomp_cte(
            'unit_ini', 'unit_fin', 'unit_ups', 'hires',
            'mm.prev_end', 'mm.fin_mes',
            owned=True, key='mes', reason_join=' JOIN meses mm ON mm.mes = i.mes',
        )}
        {DETAIL_SELECT.format(mes='r.mes')}
    """

    return sql, {"metric": metric, "mes": mes, "am": am, "ae_leads": ae_leads()}


DATASET = {
    "key": "am_nrr_month_detail",
    "label": "NRR del AM — Detalle del mes",
    "dimensions": DIMENSIONS,
    "measures": MEASURES,
    "default_filters": {},
    "query": query,
}
