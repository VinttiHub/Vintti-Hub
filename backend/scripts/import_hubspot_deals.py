#!/usr/bin/env python3
"""Importa los negocios de HubSpot (los 2 pipelines de Vintti) a Prospecting (`prospect_deals`).

La lógica vive en `prospecting/hubspot_deals.py` (la misma del sync cada 30 min). Correr
DESPUÉS de empresas y contactos: la empresa y los contactos de cada negocio se buscan por
`hubspot_company_id` / `hubspot_contact_id`.

- Siembra primero las etapas de los pipelines desde HubSpot (labels, orden, %).
- Sólo *Proceso de Contratación* y *Vintti AI Pipeline*; los demás se ignoran.
- Negocio que ya existe (por id de HubSpot) -> no se toca (para eso está el sync).
- No crea cuentas ni oportunidades del hub: esas ya las creó el sync de oportunidades;
  el negocio se ata a la suya por `hubspot_deal_id`.

Idempotente: re-correrlo no duplica.

Uso:
    cd backend
    python scripts/import_hubspot_deals.py --limit 200        # en seco: etapas, mapeo, conteos
    python scripts/import_hubspot_deals.py --apply            # todos
    python scripts/import_hubspot_deals.py --apply --resume   # sigue desde el cursor
"""
from __future__ import annotations

import argparse
import json
import sys
import time
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
from prospecting import hubspot_deals as hd  # noqa: E402
from prospecting import store  # noqa: E402
from prospecting.deal_fields import DEAL_FIELDS  # noqa: E402
from utils.hubspot import HubSpotClient  # noqa: E402

CURSOR_FILE = HERE / "data" / "hubspot_deals_import.cursor"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="escribe (default: dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="máximo de negocios a leer (0 = todos)")
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--resume", action="store_true", help="arranca desde el cursor guardado")
    args = ap.parse_args()

    client = HubSpotClient()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        store.ensure_schema(cur)
        rep = D.seed_stages_from_hubspot(cur, client)
        conn.commit()  # las etapas se guardan también en seco: sin eso no se puede leer nada
        print("Pipelines y etapas (de HubSpot):")
        for p in rep["pipelines"]:
            print(f"  {p['label']} ({p['key']}, id {p['hubspot_id']}): {', '.join(p['stages'])}")
            if p.get("sin_resolver"):
                print(f"    sin resolver: {', '.join(p['sin_resolver'])}")
        for w in rep["warnings"]:
            print(f"  aviso: {w}")
        mapping = hd.load_mapping(cur, client)
        print(f"\nNegocios en HubSpot (todos los pipelines): {client.count_objects('deals')}\n")
        print("Mapeo HubSpot -> negocio del Hub:")
        for key, plist in mapping.fields.items():
            print(f"  {key:<22} <- {', '.join(plist)}")
        unmapped = [f["key"] for f in DEAL_FIELDS if f["key"] not in mapping.fields]
        if unmapped:
            print(f"  (sin propiedad en HubSpot: {', '.join(unmapped)})")
        print()

        after = None
        if args.resume and CURSOR_FILE.exists():
            after = CURSOR_FILE.read_text().strip() or None
            print(f"Retomando desde el cursor {after}")
        properties = mapping.properties()
        stats, notes, sample = Counter(), Counter(), []
        buf, read, t0 = [], 0, time.time()
        while True:
            want = 100 if not args.limit else min(100, args.limit - read)
            if want <= 0:
                break
            results, nxt = client.list_deals_page(properties, after=after, limit=want)
            buf += results
            read += len(results)
            if len(buf) >= args.batch or not nxt:
                items = hd.build_items(cur, buf, mapping, None, notes, stats)
                hd.import_batch(cur, items, args.apply, stats, sample)
                if args.apply:
                    conn.commit()
                    CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
                    CURSOR_FILE.write_text(nxt or "")
                else:
                    conn.rollback()
                buf = []
                print(f"  leídos {read:>6} · {read / max(time.time() - t0, 1e-6):.0f}/s · {dict(stats)}", flush=True)
            after = nxt
            if not nxt:
                break
        if buf:
            hd.import_batch(cur, hd.build_items(cur, buf, mapping, None, notes, stats), args.apply, stats, sample)
            if args.apply:
                conn.commit()
            else:
                conn.rollback()

        print("\nResumen:", json.dumps(dict(sorted(stats.items())), ensure_ascii=False, indent=2))
        if notes:
            print("Avisos (valores que no se pudieron pasar; quedan en raw_payload):")
            for k, n in notes.most_common(40):
                print(f"  {n:>6} × {k}")
        if sample:
            print("\nMuestra:")
            for s in sample:
                print("  ", json.dumps(s, ensure_ascii=False, default=str)[:400])
        if not args.apply:
            print("\nSIN --apply: no se escribió nada (salvo las etapas de los pipelines).")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
