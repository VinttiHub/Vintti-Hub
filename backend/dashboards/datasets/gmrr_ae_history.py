"""Gross MRR Staffing YTD per mes — AEs only (Mariano + Bahia).

Para cada mes desde 1 de enero del año actual hasta el mes actual, devuelve:
  - `monthly_gmrr`     : SUM(salary + fee) de hires Staffing activos al cierre
                         de ese mes, cuyo `opp_sales_lead` ∈ {mariano, bahia}.
  - `cumulative_gmrr`  : suma corrida desde enero hasta ese mes.
  - `active_contractors` / `active_accounts`: head-count en cada mes.
  - `total_ytd`        : total acumulado al mes actual (mismo valor en todas
                         las filas — sirve como hero number en el card).

Usa el motor canónico compartido `_ae_mrr_staffing.HISTORY_CTE` (dedup de opp
primaria por candidato+cuenta + salary efectivo vía `salary_updates`), igual que
`mrr_history.py`, para que los totales cuadren con el resto del dashboard (R4).
"""
from __future__ import annotations

from datetime import date, datetime

from ._ae_mrr_staffing import AE_LEADS, HISTORY_CTE


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    today = datetime.utcnow().date()
    year_start = date(today.year, 1, 1)
    period_end = today

    sql = f"""
        WITH {HISTORY_CTE}
        SELECT
          TO_CHAR(mes, 'YYYY-MM')                                          AS mes,
          monthly_gmrr::bigint                                             AS monthly_gmrr,
          SUM(monthly_gmrr) OVER (ORDER BY mes)::bigint                    AS cumulative_gmrr,
          active_contractors,
          active_accounts,
          SUM(monthly_gmrr) OVER ()::bigint                                AS total_ytd
        FROM monthly
        ORDER BY mes;
    """

    return sql, {
        "ae_leads": AE_LEADS,
        "year_start": year_start,
        "period_end": period_end,
    }


DATASET = {
    "key": "gmrr_ae_history",
    "label": "Gross MRR Staffing YTD (M+B) — por mes",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
        {"key": "active_contractors", "label": "Contractors activos", "type": "number"},
        {"key": "active_accounts", "label": "Clientes activos", "type": "number"},
    ],
    "measures": [
        {"key": "monthly_gmrr", "label": "GMRR mensual", "type": "currency"},
        {"key": "cumulative_gmrr", "label": "GMRR acumulado YTD", "type": "currency"},
        {"key": "total_ytd", "label": "Total YTD", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
