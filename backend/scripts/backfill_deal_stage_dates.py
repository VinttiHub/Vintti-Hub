#!/usr/bin/env python3
"""Completa `prospect_deals.stage_dates` (la fecha de entrada a cada etapa) en los negocios
que ya existían antes de que se empezara a guardar (2026-11-06).

De dónde sale cada fecha, de menor a mayor prioridad (gana la última):
1. El historial del Hub: cada cambio de `stage` en `prospect_company_events` (deal_id).
   El pipeline es el actual del negocio.
2. La etapa actual: `stage_entered_at`.
3. HubSpot, para los negocios importados: `hs_v2_date_entered_<stage id>` (la última
   entrada real). Las etapas «NDA Sent» y «Candidate Signed» no tienen esa propiedad.

Nunca borra una fecha: sólo agrega o actualiza claves. Re-correrlo da lo mismo.

Uso:
    cd backend
    python scripts/backfill_deal_stage_dates.py            # en seco: cuenta qué cambiaría
    python scripts/backfill_deal_stage_dates.py --apply
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")
except Exception:
    pass

from psycopg2.extras import Json, RealDictCursor  # noqa: E402

from db import get_connection  # noqa: E402
from prospecting import deals as D  # noqa: E402
from prospecting import hubspot_deals as hd  # noqa: E402
from utils.hubspot import HubSpotClient  # noqa: E402


def _iso(v) -> str:
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-hubspot", action="store_true", help="sólo historial del Hub y etapa actual")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    D.ensure_schema(cur)
    conn.commit()

    cur.execute("SELECT id, pipeline_key, stage_key, stage_entered_at, hubspot_deal_id, stage_dates FROM prospect_deals")
    deals = {r["id"]: dict(r) for r in cur.fetchall()}
    new: dict[int, dict] = {i: {} for i in deals}
    stats = Counter()

    # 1. Historial del Hub
    cur.execute("SELECT deal_id, new_value, at FROM prospect_company_events "
                "WHERE deal_id IS NOT NULL AND field = 'stage' AND new_value IS NOT NULL ORDER BY at")
    for r in cur.fetchall():
        d = deals.get(r["deal_id"])
        if d and r["at"]:
            new[d["id"]][f"{d['pipeline_key']}:{r['new_value']}"] = _iso(r["at"])
            stats["fechas del historial"] += 1
    # 2. Etapa actual
    for d in deals.values():
        if d["stage_entered_at"]:
            new[d["id"]][f"{d['pipeline_key']}:{d['stage_key']}"] = _iso(d["stage_entered_at"])
    # 3. HubSpot
    if not args.no_hubspot:
        client = HubSpotClient()
        mapping = hd.load_mapping(cur, client)
        props = sorted(mapping.entered)
        by_hs = {d["hubspot_deal_id"]: d["id"] for d in deals.values() if d["hubspot_deal_id"]}
        ids = list(by_hs)
        print(f"HubSpot: {len(props)} propiedades de fecha de entrada, {len(ids)} negocios a leer")
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            payload = client._request("POST", "/crm/v3/objects/deals/batch/read",
                                      json={"properties": props, "inputs": [{"id": x} for x in chunk]})
            for rec in payload.get("results", []):
                did = by_hs.get(str(rec["id"]))
                if did:
                    got = mapping.stage_dates(rec)
                    new[did].update(got)
                    stats["fechas de HubSpot"] += len(got)

    changed = []
    for did, dates in new.items():
        cur_dates = deals[did]["stage_dates"] or {}
        diff = {k: v for k, v in dates.items() if cur_dates.get(k) != v}
        if diff:
            changed.append((did, diff))
            for k in diff:
                stats[f"etapa {k}"] += 1
    print(f"Negocios: {len(deals)} · a actualizar: {len(changed)}")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    for did, diff in changed[:5]:
        print(f"  ej. negocio {did}: {diff}")
    if not args.apply:
        print("En seco: no se escribió nada (--apply para aplicar).")
        conn.rollback()
        return
    for did, diff in changed:
        cur.execute("UPDATE prospect_deals SET stage_dates = COALESCE(stage_dates, '{}'::jsonb) || %s WHERE id = %s",
                    (Json(diff), did))
    conn.commit()
    print(f"Listo: {len(changed)} negocios actualizados.")


if __name__ == "__main__":
    main()
