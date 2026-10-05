from __future__ import annotations

from datetime import date

from ._mrr_staffing import HIRES_FULL_CTE, unit_snapshot_monthly
from ._nrr_decomp import decomp_cte
from .nrr_30d_detail import DETAIL_SELECT, DIMENSIONS, MEASURES, unit_info_cte
from .nrr_history import UPS_POBLACION


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
    mes = (
        _parse_date(filters.get("fecha_nrr"))
        or _parse_date(filters.get("mes_click"))
        or _parse_date(filters.get("mes"))
    )

    # `meses` es UN solo mes (el que se clickeo), pero se arma igual que en
    # `nrr_history` para poder reusar los mismos snapshots mensuales: la base es el
    # FIN DEL MES ANTERIOR (`prev_end`). El detalle anclaba al `fin_mes`, que es lo que
    # hacia que no cerrara contra la card.
    sql = f"""
        WITH {HIRES_FULL_CTE},
        {unit_info_cte()},
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
        {unit_snapshot_monthly('unit_ini', 'prev_end', exclude_end_day=True)},
        {unit_snapshot_monthly('unit_fin', 'fin_mes', exclude_end_day=True)},
        {unit_snapshot_monthly('unit_ups', 'fin_mes', UPS_POBLACION)},
        {decomp_cte(
            'unit_ini', 'unit_fin', 'unit_ups', 'hires_full',
            'mm.prev_end', 'mm.fin_mes',
            key='mes', reason_join=' JOIN meses mm ON mm.mes = i.mes',
        )}
        {DETAIL_SELECT.format(mes='r.mes')}
    """

    return sql, {"metric": metric, "mes": mes}


DATASET = {
    "key": "nrr_month_detail",
    "label": "NRR — Detalle del mes",
    "dimensions": DIMENSIONS,
    "measures": MEASURES,
    "default_filters": {},
    # Libro de hechos de la auditoria (dashboards/audit/ledger.py).
    "audit": [{
        "fact": "contractor_baja", "entity": ["candidate_name", "client_name"],
        "match": {"componente": "^(churn_no_recorte|downgrades_recorte)$"},
        "month_col": "mes", "date_col": "end_d",
        "excluye": ["nuevo_en_mes", "sigue_en_cuenta", "buyout"],
    }],
    "query": query,
}
