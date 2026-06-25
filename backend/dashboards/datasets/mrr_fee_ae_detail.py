"""Breakdown per contractor de MRR Staffing al corte (hoy) — fee Vintti only, M+B.

Mismo set de filas que `gmrr_ae_detail` (mismo motor canónico compartido
`_ae_mrr_staffing.SNAPSHOT_CTE`: dedup de opp primaria + `salary_updates`) pero la
métrica principal `gmrr` se reemplaza por `fee` (margen Vintti). La suma de `fee`
reconcilia con `monthly_fee` del último mes de `mrr_fee_ae_history` — R4.

`salary` se devuelve igual como contexto (útil en el drawer).
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
          TO_CHAR(start_d, 'YYYY-MM-DD') AS start_date
        FROM eff
        ORDER BY fee DESC NULLS LAST, candidate_name;
    """

    return sql, {
        "ae_leads": AE_LEADS,
        "corte": corte,
        "year_start": year_start,
    }


DATASET = {
    "key": "mrr_fee_ae_detail",
    "label": "MRR Staffing · Vintti fee — Detalle contractors activos (M+B)",
    "dimensions": [
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_sales_lead", "label": "AE", "type": "string"},
        {"key": "start_date", "label": "Start", "type": "date"},
    ],
    "measures": [
        {"key": "salary", "label": "Salary", "type": "currency"},
        {"key": "fee", "label": "Fee Vintti", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
