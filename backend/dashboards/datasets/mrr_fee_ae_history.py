"""MRR Staffing YTD per mes — Vintti fee only (sin salario), AEs only.

Espejo de `gmrr_ae_history` pero sumando SOLO el `fee` efectivo — el margen de
Vintti, no el costo del candidato. Mismo motor canónico compartido
(`_ae_mrr_staffing.HISTORY_CTE`: dedup de opp primaria + `salary_updates`), así
que los head-counts y la base de hires coinciden exactamente con `gmrr_ae_history`.

Para cada mes desde 1 de enero del año actual hasta el mes actual:
  - `monthly_fee`     : SUM(fee) de hires Staffing activos al cierre del mes.
  - `cumulative_fee`  : suma corrida desde enero.
  - `total_ytd_fee`   : total acumulado al mes actual (constante en todas las filas).
  - `active_contractors` / `active_accounts`: head-count por mes.
"""
from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar

from ._ae_mrr_staffing import AE_LEADS, HISTORY_CTE


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    today = today_ar()
    year_start = date(today.year, 1, 1)
    period_end = today

    sql = f"""
        WITH {HISTORY_CTE}
        SELECT
          TO_CHAR(mes, 'YYYY-MM')                                          AS mes,
          monthly_fee::bigint                                              AS monthly_fee,
          SUM(monthly_fee) OVER (ORDER BY mes)::bigint                     AS cumulative_fee,
          active_contractors,
          active_accounts,
          SUM(monthly_fee) OVER ()::bigint                                 AS total_ytd_fee
        FROM monthly
        ORDER BY mes;
    """

    return sql, {
        "ae_leads": AE_LEADS,
        "year_start": year_start,
        "period_end": period_end,
    }


DATASET = {
    "key": "mrr_fee_ae_history",
    "label": "MRR Staffing YTD · Vintti fee only (M+B) — por mes",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
        {"key": "active_contractors", "label": "Contractors activos", "type": "number"},
        {"key": "active_accounts", "label": "Clientes activos", "type": "number"},
    ],
    "measures": [
        {"key": "monthly_fee", "label": "Fee mensual", "type": "currency"},
        {"key": "cumulative_fee", "label": "Fee acumulado YTD", "type": "currency"},
        {"key": "total_ytd_fee", "label": "Total YTD (fee)", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
