#!/usr/bin/env python3
"""Importa TODOS los contactos de HubSpot a Prospecting (`prospect_contacts`).

La lógica vive en `prospecting/hubspot_contacts.py` (la misma que usa el sync cada 30 min).
Correr DESPUÉS de importar las empresas: la empresa de cada contacto se busca por
`hubspot_company_id`.

- Con empresa (asociación de HubSpot, o dominio del mail de una sola empresa) -> contacto
  en esa empresa.
- Sin empresa -> bandeja «Unassigned» de la pestaña Contacts (origen HubSpot), con Link /
  Discard; se vinculan solos cuando llega una empresa con su dominio.
- Contacto que ya existe en el Hub (por id de HubSpot o email) -> sólo rellena vacíos.
- Workflows: los workflows de contacto por condiciones NO inscriben en masa a los
  importados que ya cumplen (quedan como "ya cumplía"); el que empiece a cumplir
  después entra solo. Para meter a los que ya cumplen: «Inscribir las que cumplen ahora»
  en el workflow.

Idempotente: re-correrlo no duplica (cruza por id de HubSpot).

Uso:
    cd backend
    python scripts/import_hubspot_contacts.py --limit 300          # dry-run: mapeo + conteos
    python scripts/import_hubspot_contacts.py --apply --limit 500  # prueba chica
    python scripts/import_hubspot_contacts.py --apply              # todos
    python scripts/import_hubspot_contacts.py --apply --resume     # sigue desde el cursor
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
from prospecting import store  # noqa: E402
from prospecting import hubspot_contacts as hc  # noqa: E402
from utils.hubspot import HubSpotClient  # noqa: E402

CURSOR_FILE = HERE / "data" / "hubspot_contacts_import.cursor"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="escribe (default: dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="máximo de contactos a leer (0 = todos)")
    ap.add_argument("--batch", type=int, default=500, help="contactos por transacción (default 500)")
    ap.add_argument("--resume", action="store_true", help="arranca desde el cursor guardado")
    args = ap.parse_args()

    client = HubSpotClient()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Siempre, también en seco: las columnas nuevas (hubspot_contact_id…) hacen falta para
        # leer, son nullable y las crea igual el backend al arrancar. Commit en el acto para no
        # dejar el lock del ALTER tomado durante toda la corrida.
        store.ensure_schema(cur)
        conn.commit()
        mapping = hc.load_mapping(cur, client)
        print(f"Contactos en HubSpot: {client.count_objects('contacts')}\n")
        print("Mapeo HubSpot -> contacto del Hub:")
        for key, plist in mapping.fields.items():
            print(f"  {key:<28} <- {', '.join(plist)}")
        unmapped = [f["key"] for f in hc.CONTACT_FIELDS if f["key"] not in mapping.fields]
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
            results, nxt = client.list_contacts_page(properties, after=after, limit=want)
            buf += results
            read += len(results)
            if len(buf) >= args.batch or not nxt:
                items = hc.build_items(buf, mapping, None, notes)
                hc.import_batch(cur, items, args.apply, stats, sample)
                if args.apply:
                    conn.commit()
                    CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
                    CURSOR_FILE.write_text(nxt or "")
                else:
                    conn.rollback()
                buf = []
                print(f"  leídos {read:>7} · {read / max(time.time() - t0, 1e-6):.0f}/s · {dict(stats)}", flush=True)
            after = nxt
            if not nxt:
                break
        if buf:
            hc.import_batch(cur, hc.build_items(buf, mapping, None, notes), args.apply, stats, sample)
            if args.apply:
                conn.commit()

        print("\nResumen:", json.dumps(dict(stats), ensure_ascii=False, indent=2))
        if notes:
            print("Avisos (valores que no se pudieron pasar; quedan en raw_payload):")
            for k, n in notes.most_common(40):
                print(f"  {n:>7} × {k}")
        if sample:
            print("\nMuestra:")
            for s in sample:
                print("  ", json.dumps(s, ensure_ascii=False, default=str)[:400])
        if not args.apply:
            print("\nSIN --apply: no se escribió nada.")
            conn.rollback()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
