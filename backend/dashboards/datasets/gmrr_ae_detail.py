"""Breakdown per contractor of Gross MRR Staffing al corte (hoy) — AEs only.

Lista cada hire Staffing activo al corte cuyo `opp_sales_lead` ∈ {Mariano, Bahia}.
Cada fila aporta `salary + fee` (= GMRR mensual). La suma de la columna `gmrr`
reconcilia con el último mes (`monthly_gmrr` actual) de `gmrr_ae_history` porque
ambos usan el motor canónico compartido `_ae_mrr_staffing.SNAPSHOT_CTE` (dedup de
opp primaria + salary efectivo vía `salary_updates`) — R4.

Usado en el drawer del card "Gross MRR Staffing YTD" del tab AE.
"""
from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar

from ._ae_mrr_staffing import AE_LEADS, SNAPSHOT_CTE


def _parse_date(value):
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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    # `corte` = end of selected month, sent by refetchMonthAwareElements when
    # the user clicks a point on the YTD line chart. Defaults to today.
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or today_ar()
    )
    # YTD: limitar a deals cuya Close Win fue este año (el año del mes consultado).
    year_start = date(corte.year, 1, 1)

    sql = f"""
        WITH {SNAPSHOT_CTE}
        SELECT
          candidate_name,
          client_name,
          opp_sales_lead,
          salary::float                  AS salary,
          fee::float                     AS fee,
          (salary + fee)::float          AS gmrr,
          TO_CHAR(start_d, 'YYYY-MM-DD') AS start_date
        FROM eff
        ORDER BY gmrr DESC NULLS LAST, candidate_name;
    """

    return sql, {
        "ae_leads": AE_LEADS,
        "corte": corte,
        "year_start": year_start,
    }


DATASET = {
    "key": "gmrr_ae_detail",
    "label": "Gross MRR Staffing — Detalle contractors activos (M+B)",
    "dimensions": [
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_sales_lead", "label": "AE", "type": "string"},
        {"key": "start_date", "label": "Start", "type": "date"},
    ],
    "measures": [
        {"key": "salary", "label": "Salary", "type": "currency"},
        {"key": "fee", "label": "Fee", "type": "currency"},
        {"key": "gmrr", "label": "GMRR mensual", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
