"""Desglose por contractor del GMRR/MRR del AM, al corte.

Lista cada par (candidato, cuenta) de Staffing activo al `corte` que **ya es del AM**
— o sea, descontando las vacantes que todavia estan dentro de los 3 meses posteriores
al Close Win de un AE. La suma de `gmrr` reconcilia con el ultimo mes de
`am_mrr_history` porque las dos usan el motor compartido `_am_mrr_staffing`.

El `corte` sale de `corte | cutoff | hasta | hoy`, igual que
`gmrr_contractors_detail.py`: como el pill **Mes** setea `hasta` solo, eso es lo que
hace que el drawer respete mes y rango junto con la card (regla R09 del auditor).

Usado en los drawers "GMRR del AM" y "MRR del AM" del tab Account Management.
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
          account_manager,
          salary::float                  AS salary,
          fee::float                     AS fee,
          (salary + fee)::float          AS gmrr,
          TO_CHAR(start_d, 'YYYY-MM-DD') AS start_date,
          TO_CHAR(close_d, 'YYYY-MM-DD') AS close_date
        FROM eff
        WHERE am_owned
        ORDER BY (salary + fee) DESC NULLS LAST, candidate_name;
    """

    return sql, {"ae_leads": ae_leads(), "am": am, "corte": corte}


DATASET = {
    "key": "am_gmrr_contractors_detail",
    "label": "GMRR del AM — Desglose por contractor (snapshot al corte)",
    "dimensions": [
        {"key": "candidate_name", "label": "Contractor", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "account_manager", "label": "Account Manager", "type": "string"},
        {"key": "start_date", "label": "Start", "type": "date"},
        {"key": "close_date", "label": "Close Win", "type": "date"},
    ],
    "measures": [
        {"key": "salary", "label": "Salary", "type": "currency"},
        {"key": "fee", "label": "Fee", "type": "currency"},
        {"key": "gmrr", "label": "GMRR (salary + fee)", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
