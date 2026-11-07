"""Recupera «Scheduled By» de los contactos agendados por gente que ya no está en el Hub.

Hasta el 2026-11-06 el sync / la importación de contactos de HubSpot resolvía las
propiedades tipo `user` sólo contra usuarios ACTIVOS del Hub, así que el Scheduled By de
ex-BDRs (Vianney, Pilar, Felicitas, Felipe, Juliana…) se descartaba y quedaba sólo en
`raw_payload` como owner id de HubSpot. Sin eso el panel «SQLs by BDR» no cuadra con HubSpot.

Este script lo traduce con los owners de HubSpot (activos y archivados), lo escribe sólo
donde `scheduled_by` está vacío (con historial, source `hubspot_sync`), guarda los nombres
en `prospect_people` y blinda los workflows de contacto por condiciones (los que ya cumplen
quedan como "ya cumplía": un backfill histórico no manda Slacks ni inscribe en masa).

    python scripts/backfill_scheduled_by.py           # en seco
    python scripts/backfill_scheduled_by.py --apply
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
from prospecting import store  # noqa: E402
from prospecting import hubspot_contacts as hc  # noqa: E402
from utils.hubspot import HubSpotClient  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="escribe (default: en seco)")
    args = ap.parse_args()

    owners = HubSpotClient().list_owners()
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        store.ensure_schema(cur)
        cur.execute(
            """
            SELECT id, raw_payload->>'scheduled_by' AS raw
              FROM prospect_contacts
             WHERE NULLIF(props->>'scheduled_by', '') IS NULL
               AND NULLIF(raw_payload->>'scheduled_by', '') IS NOT NULL
             ORDER BY id
            """
        )
        rows = cur.fetchall()
        by_person, unresolved, people, done = Counter(), Counter(), {}, []
        for r in rows:
            raw = r["raw"].strip()
            o = owners.get(raw) or {}
            email = raw.lower() if "@" in raw else o.get("email")
            if not email:
                unresolved[raw] += 1
                continue
            by_person[email] += 1
            if o.get("name"):
                people.setdefault(email, o["name"])
            if args.apply:
                store.update_contact(cur, r["id"], {"scheduled_by": email}, None, source="hubspot_sync")
                done.append(r["id"])

        print(f"Contactos con Scheduled By sólo en raw_payload: {len(rows)}")
        for email, n in by_person.most_common():
            print(f"  {n:>4}  {email}  ({people.get(email) or '—'})")
        if unresolved:
            print("Sin owner en HubSpot:", dict(unresolved))

        if args.apply:
            store.remember_people(cur, people, "hubspot")
            stats = Counter()
            hc.shield(cur, done, stats)
            conn.commit()
            print(f"Aplicado: {len(done)} contactos. Blindaje: {dict(stats)}")
        else:
            conn.rollback()
            print("En seco: no se escribió nada (--apply para aplicar).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
