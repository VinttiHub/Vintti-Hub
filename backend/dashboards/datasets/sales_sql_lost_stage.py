"""Sales · ¿Dónde se pierden los SQLs? (AE + AM, por fecha de cierre).

Mismo universo que "Razones de SQL perdidos" (`sales_sql_lost_reasons`): los Closed Lost
de la card "SQL → Close Win · AE + AM" (`sql_to_cw_ae_am_cierre.rows()`). En vez de la
razón, la ETAPA desde la que se cerró cada uno:
  - opps del hub: `opportunity.stage_before_closed_lost`, que el PATCH de stage
    (`accounts_routes.py`) graba con el stage anterior al pasar a Closed Lost. Es de dónde
    la cerraron, no necesariamente dónde se enfrió: una opp quieta en Interviewing y cerrada
    semanas después dice Interviewing. Vacía si se cerró por otro camino -> "Sin dato".
  - deals de HubSpot sin opp: "SQL (antes del Deep Dive)".

Dona y detalle leen `rows()`, así la dona suma `cl_opp + cl_sin_opp` de la card.
"""
from __future__ import annotations

from .sql_to_cw_ae_am_cierre import rows as cierre_rows

NO_STAGE_LABEL = "Sin dato"


def rows(filters: dict) -> list[dict]:
    out = []
    for r in cierre_rows(filters):
        if r["grupo"] not in ("cl_opp", "cl_sin_opp"):
            continue
        stage = str(r.get("perdido_en") or "").strip()
        out.append({
            "stage": stage if stage and stage != "—" else NO_STAGE_LABEL,
            "client_name": r["client_name"],
            "position": r["position"],
            "close_date": r["close_date"],
            "quien": r["quien"],
            "sales_lead": r["sales_lead"],
            "motivo": r["motivo"],
            "origen": "Opp del hub" if r["grupo"] == "cl_opp" else "Deal sin opp",
            "ref": r["ref"],
        })
    stage = str((filters or {}).get("stage") or "").strip()
    if stage:
        out = [r for r in out if r["stage"] == stage]
    return out


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    counts: dict[str, int] = {}
    for r in rows(filters):
        counts[r["stage"]] = counts.get(r["stage"], 0) + 1
    total = sum(counts.values())
    out = [{
        "stage": k,
        "count": v,
        "share_pct": round(100.0 * v / total, 1) if total else None,
    } for k, v in counts.items()]
    out.sort(key=lambda r: r["stage"])
    out.sort(key=lambda r: r["count"], reverse=True)
    return out


DATASET = {
    "key": "sales_sql_lost_stage",
    "label": "Sales · ¿Dónde se pierden los SQLs? (etapa, AE + AM, por cierre)",
    "dimensions": [{"key": "stage", "label": "Etapa", "type": "string"}],
    "measures": [
        {"key": "count", "label": "SQLs", "type": "number"},
        {"key": "share_pct", "label": "% del total", "type": "percent"},
    ],
    "default_filters": {},
    "compute": compute,
}
