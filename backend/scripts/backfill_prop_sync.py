#!/usr/bin/env python3
"""Propiedades sincronizadas (prospecting/prop_sync.py) sobre los datos que ya existían.

En seco (por defecto) sólo REPORTA: por cada propiedad del mapa, cuántos pares contacto ↔
negocio abierto tienen hoy valores distintos (la regla los iguala recién cuando uno cambia).
No pisa nada de eso.

Con --apply completa, sólo donde están VACÍAS, las propiedades nuevas del negocio: primero con
el valor de HubSpot (la importación de negocios no toca los que ya existen) y, si sigue vacía,
con lo que el Hub llena solo:
- Lead Life (Deal) según la etapa actual (deals.LEAD_LIFE_BY_STAGE);
- First Deep Dive Date (Deal) desde la fecha de entrada a Deep Dive (stage_dates);
- Credit Loop? / Credits Won / Credits Expiring Date de los Close Win con crédito.

Uso:
    cd backend
    python scripts/backfill_prop_sync.py
    python scripts/backfill_prop_sync.py --apply
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

from psycopg2.extras import RealDictCursor  # noqa: E402

from db import get_connection  # noqa: E402
from prospecting import deals as D  # noqa: E402
from prospecting import prop_sync as PS  # noqa: E402
from prospecting import store  # noqa: E402

NEW_DEAL_KEYS = ["mql_lost_reason", "lead_life_deal", "first_deep_dive_date", "follow_up_date", "credit_loop",
                 "credits_won", "credits_expiring_date"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-hubspot", action="store_true", help="no leer HubSpot")
    args = ap.parse_args()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Diferencias contacto ↔ negocio abierto (sólo reporte)
    cur.execute(
        """
        SELECT d.*, dc.contact_id FROM prospect_deals d
          JOIN prospect_deal_contacts dc ON dc.deal_id = d.id
          LEFT JOIN prospect_deal_stages s ON s.pipeline_key = d.pipeline_key AND s.stage_key = d.stage_key
         WHERE NOT COALESCE(s.is_closed, FALSE) AND NOT d.is_dummy
        """
    )
    pairs = [dict(r) for r in cur.fetchall()]
    ids = sorted({p["contact_id"] for p in pairs})
    cur.execute("SELECT * FROM prospect_contacts WHERE id = ANY(%s)", (ids,))
    contacts = {r["id"]: store._flatten_contact(r) for r in cur.fetchall()}
    diff = Counter()
    for p in pairs:
        d, ct = D._flatten(p), contacts.get(p["contact_id"]) or {}
        for c_key, d_key, _co, pol in PS.LINKS:
            a, b = ct.get(c_key), d.get(d_key)
            if PS._empty(a) and PS._empty(b):
                continue
            if not PS._same(a if not isinstance(a, list) else (a[0] if a else None), b):
                diff[f"{c_key} ↔ {d_key} ({pol})"] += 1
    print(f"Pares contacto ↔ negocio abierto: {len(pairs)}")
    for k, n in diff.most_common():
        print(f"  distintos · {k}: {n}")

    # 2. Propiedades nuevas: primero lo que HubSpot ya tiene (la importación de negocios no
    #    toca los existentes), después lo que el Hub llena solo.
    cur.execute("SELECT * FROM prospect_deals WHERE NOT is_dummy")
    deals = [dict(r) for r in cur.fetchall()]
    from_hs: dict[int, dict] = {}
    if not args.no_hubspot:
        from prospecting import hubspot_deals as hd
        from utils.hubspot import HubSpotClient
        client = HubSpotClient()
        mapping = hd.load_mapping(cur, client)
        props = sorted({p for k in NEW_DEAL_KEYS for p in mapping.fields.get(k, [])})
        by_hs = {r["hubspot_deal_id"]: r["id"] for r in deals if r.get("hubspot_deal_id")}
        hs_ids = list(by_hs)
        for i in range(0, len(hs_ids), 100):
            payload = client._request("POST", "/crm/v3/objects/deals/batch/read",
                                      json={"properties": props, "inputs": [{"id": x} for x in hs_ids[i:i + 100]]})
            for rec in payload.get("results", []):
                data, invalid, _n = mapping.map(rec)
                did = by_hs.get(str(rec["id"]))
                if did:
                    from_hs[did] = {k: data[k] for k in NEW_DEAL_KEYS if k not in invalid and data.get(k) is not None}
        print(f"HubSpot: {len(hs_ids)} negocios leídos, {sum(1 for v in from_hs.values() if v)} con valores")
    todo = []
    for r in deals:
        d = D._flatten(r)
        patch = {k: v for k, v in (from_hs.get(r["id"]) or {}).items() if PS._empty(d.get(k))}
        d = {**d, **patch}
        ll = D.LEAD_LIFE_BY_STAGE.get(r["stage_key"])
        if ll and PS._empty(d.get("lead_life_deal")):
            patch["lead_life_deal"] = ll
        dd = (r.get("stage_dates") or {}).get(f"{r['pipeline_key']}:deep_dive")
        if dd and PS._empty(d.get("first_deep_dive_date")):
            patch["first_deep_dive_date"] = dd
        if r.get("opportunity_id") and r["stage_key"] == "closed_won":
            for k, v in D._credit_values(cur, r["opportunity_id"], r.get("account_id")).items():
                if PS._empty(d.get(k)):
                    patch[k] = v
        if patch:
            todo.append((r["id"], patch))
    c = Counter(k for _, p in todo for k in p)
    print(f"Negocios a completar: {len(todo)} · {dict(c)}")
    if not args.apply:
        print("En seco: no se escribió nada (--apply completa sólo las propiedades nuevas vacías).")
        conn.rollback()
        return
    for did, patch in todo:
        D.update_deal(cur, did, patch, None, source="backfill_prop_sync")
    conn.commit()
    print(f"Listo: {len(todo)} negocios.")


if __name__ == "__main__":
    main()
