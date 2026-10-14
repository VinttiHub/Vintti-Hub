"""Sales · Razones de SQL perdidos (AE + AM, por fecha de cierre).

Universo = los Closed Lost de la card "SQL → Close Win · AE + AM · por cierre"
(`sql_to_cw_ae_am_cierre.rows()`): opps del hub (`motive_close_lost`) + deals de
HubSpot perdidos antes de Deep Dive, sin opp (`sql_ae_lost_reason`). La dona suma
`cl_opp + cl_sin_opp` de esa card por construcción.

Los dos lados no hablan el mismo idioma: HubSpot guarda el *value* interno del select
("Bad Timing", "Competitor", "Vintti's Fault") y el hub el label que eligió la persona.
`CLOSED_LOST_REASON_MAP` (utils/hubspot_push.py) traduce hub → HubSpot para el push;
acá se invierte para llevar todo al label del hub, así "Timing" no sale dos veces.

Dona y detalle leen `rows()`.
"""
from __future__ import annotations

from .sql_to_cw_ae_am_cierre import rows as cierre_rows

NO_REASON_LABEL = "Sin razón"

# value de HubSpot (en minúscula) → label del hub: la inversa de CLOSED_LOST_REASON_MAP.
# Si HubSpot suma un value, sumalo acá; mientras tanto sale tal cual, no se pierde.
_HUB_LABEL = {
    "ghosting": "Ghosting",
    "pricing": "Pricing",
    "shopping": "Shopping",
    "bad timing": "Timing",
    "vintti's fault": "Vinttis Fault",
    "other": "Other",
    "external competition": "External Competition",
    "competitor": "Internal Competition",
}


def normalize_reason(raw) -> str:
    s = str(raw or "").strip()
    if not s or s == "—":
        return NO_REASON_LABEL
    return _HUB_LABEL.get(s.lower(), s)


def rows(filters: dict) -> list[dict]:
    out = [{
        "reason": normalize_reason(r["motivo"]),
        "client_name": r["client_name"],
        "position": r["position"],
        "close_date": r["close_date"],
        "quien": r["quien"],
        "sales_lead": r["sales_lead"],
        "origen": "Opp del hub" if r["grupo"] == "cl_opp" else "Deal sin opp",
        "ref": r["ref"],
    } for r in cierre_rows(filters) if r["grupo"] in ("cl_opp", "cl_sin_opp")]
    reason = str((filters or {}).get("reason") or "").strip()
    if reason:
        out = [r for r in out if r["reason"] == reason]
    return out


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
    "key": "sales_sql_lost_reasons",
    "label": "Sales · Razones de SQL perdidos (AE + AM, por cierre)",
    "dimensions": [{"key": "reason", "label": "Razón", "type": "string"}],
    "measures": [
        {"key": "count", "label": "SQLs", "type": "number"},
        {"key": "share_pct", "label": "% del total", "type": "percent"},
    ],
    "default_filters": {},
    "compute": compute,
}
