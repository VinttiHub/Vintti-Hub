"""Sales · Razones de "no SQL": por qué los MQLs de la cohorte no pasaron a SQL.

Universo = los MQLs de la card MQL → SQL (`sales_mql_to_sql_30d.cohort_rows()`) que NO
llegaron a SQL, así la dona suma `total_mql − total_sql` por construcción. La razón es
`mql_ae_lost_reason` del contacto en HubSpot. Los que siguen en `MQL (AE)` todavía no
se perdieron: van en su propia porción, "Todavía abierto" (decisión de la owner,
2026-10-14). Un Closed Lost sin razón cargada sale como "Sin razón".

Dona y detalle leen `rows()`.
"""
from __future__ import annotations

from ._periods import window_bounds
from .sales_mql_to_sql_30d import cohort_rows

try:
    from backend.utils import shared_cache  # type: ignore
except ImportError:
    from utils import shared_cache  # type: ignore

_CACHE_TTL_SECONDS = 300
_CACHE_VERSION = 1

OPEN_LABEL = "Todavía abierto"
NO_REASON_LABEL = "Sin razón"


def _reason(r: dict) -> str:
    if str(r.get("lead_life") or "").strip().lower() == "mql (ae)":
        return OPEN_LABEL
    return r.get("lost_reason") or NO_REASON_LABEL


def rows(filters: dict) -> list[dict]:
    """Una fila por MQL de la cohorte que no llegó a SQL, con su `reason`.

    La dona, el select y el drawer piden lo mismo a la vez y cada `cohort_rows()` es un
    search completo de contactos en HubSpot: se cachea 5 min por ventana.
    """
    ini, fin = window_bounds(filters or {})
    key = f"sales_mql_no_sql__v{_CACHE_VERSION}__{ini.isoformat()}__{fin.isoformat()}"
    hit, cached = shared_cache.get(key)
    if hit:
        rs = cached
    else:
        cohort, _ini, _fin = cohort_rows(filters)
        rs = [{
            "reason": _reason(r),
            "client_name": r["client_name"],
            "mql_date": r["mql_date"],
            "tipo": "Outbound" if r["bucket"] == "out" else "Inbound",
            "origin": r["origin"],
            "channel": r["channel"],
            "lead_life": r["lead_life"],
        } for r in cohort if not r["reached_sql"]]
        rs.sort(key=lambda r: r["client_name"])
        rs.sort(key=lambda r: r["mql_date"], reverse=True)
        shared_cache.set(key, rs, _CACHE_TTL_SECONDS)

    reason = str((filters or {}).get("reason") or "").strip()
    if reason:
        rs = [r for r in rs if r["reason"] == reason]
    return rs


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    counts: dict[str, int] = {}
    for r in rows(filters):
        counts[r["reason"]] = counts.get(r["reason"], 0) + 1
    total = sum(counts.values())
    out = [{
        "reason": k,
        "count": v,
        "share_pct": round(100.0 * v / total, 1) if total else None,
    } for k, v in counts.items()]
    out.sort(key=lambda r: r["reason"])
    out.sort(key=lambda r: r["count"], reverse=True)
    return out


DATASET = {
    "key": "sales_mql_no_sql_reasons",
    "label": "Sales · Razones de no SQL (MQLs de la cohorte que no pasaron, live HubSpot)",
    "dimensions": [{"key": "reason", "label": "Razón", "type": "string"}],
    "measures": [
        {"key": "count", "label": "MQLs", "type": "number"},
        {"key": "share_pct", "label": "% del total", "type": "percent"},
    ],
    "default_filters": {},
    "compute": compute,
}
