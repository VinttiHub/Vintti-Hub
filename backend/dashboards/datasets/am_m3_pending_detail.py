"""Quienes estan todavia en el M3 del AE y por eso NO cuentan en el AM.

El complemento exacto de `am_gmrr_contractors_detail`: las mismas filas del snapshot
al corte, pero del lado `NOT am_owned`. La suma de las dos reconcilia con el GMRR
global (`mrr_history`), que es lo que hace verificable la card — ver
`_am_mrr_staffing`.

Cada fila dice ademas **cuando entra**: `close_d + 3 meses`. Con eso la owner ve el
panorama completo sin tener que ir a buscar la opp una por una.
"""
from __future__ import annotations

from datetime import date

from ._now import today_ar
from ._am_mrr_staffing import SNAPSHOT_CTE, ae_leads


def _parse_date(value) -> date | None:
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
    filters = filters or {}
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or today_ar()
    )
    am = str(filters.get("am") or "").strip().lower()

    sql = f"""
        WITH {SNAPSHOT_CTE}
        SELECT
          candidate_name,
          client_name,
          sales_lead                                            AS ae,
          TO_CHAR(close_d, 'YYYY-MM-DD')                        AS close_date,
          TO_CHAR((close_d + INTERVAL '3 months')::date, 'YYYY-MM-DD') AS entra_el,
          GREATEST(((close_d + INTERVAL '3 months')::date - %(corte)s::date), 0)::int AS dias_restantes,
          salary::float                                         AS salary,
          fee::float                                            AS fee,
          (salary + fee)::float                                 AS gmrr
        FROM eff
        WHERE NOT am_owned
        ORDER BY (close_d + INTERVAL '3 months')::date, (salary + fee) DESC NULLS LAST;
    """

    return sql, {"ae_leads": ae_leads(), "am": am, "corte": corte}


DATASET = {
    "key": "am_m3_pending_detail",
    "label": "Esperando el M3 del AE — Detalle de contractors",
    "dimensions": [
        {"key": "candidate_name", "label": "Contractor", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "ae", "label": "AE que vendio", "type": "string"},
        {"key": "close_date", "label": "Close Win", "type": "date"},
        {"key": "entra_el", "label": "Entra al AM", "type": "date"},
        {"key": "dias_restantes", "label": "Dias restantes", "type": "number"},
    ],
    "measures": [
        {"key": "salary", "label": "Salary", "type": "currency"},
        {"key": "fee", "label": "Fee", "type": "currency"},
        {"key": "gmrr", "label": "GMRR mensual", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
