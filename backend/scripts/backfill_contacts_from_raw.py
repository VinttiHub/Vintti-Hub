"""Rellena los campos de contacto que el sync de HubSpot descartaba (2026-11-24).

Hasta hoy el sync de contactos tiraba, y dejaba sólo en `raw_payload`:
  - Contact Owner / Follow Up Task Owner que no fueran BDR activo (Justo, Bahía, Mariano,
    Juliana…: ~6.000 contactos). Ahora vale cualquier persona activa del Hub.
  - Lead Life «PQL (BDRs)», «MQL (Event)», «MQL (MKT) - LM» (~330) y otras opciones que el
    catálogo no tenía (Event Name / Attendance, Industria, Model, Country/Continent…).
  - Marketing contact status (`true`/`false` en vez de la etiqueta).

Con el catálogo y el mapeo nuevos el sync ya los trae en adelante, pero sólo para los
contactos que HubSpot vuelva a tocar. Este script vuelve a mapear el `raw_payload` guardado
con el mapeo de hoy y escribe **sólo donde el Hub está vacío** (nunca pisa algo cargado en el
Hub), con historial (source `hubspot_sync`), y suma esos campos a la foto `hubspot_seen`.

No dispara workflows: como la importación, blinda los workflows de contacto por condiciones
(los que ya cumplen quedan como "ya cumplía") para que no inscriban a miles de una vez.

    python scripts/backfill_contacts_from_raw.py              # en seco: cuenta qué cambiaría
    python scripts/backfill_contacts_from_raw.py --apply
    python scripts/backfill_contacts_from_raw.py --apply --limit 200
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
from prospecting import hubspot_contacts as hct  # noqa: E402
from prospecting import store  # noqa: E402
from utils.hubspot import HubSpotClient  # noqa: E402

SOURCE = "hubspot_sync"
BATCH = 200


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="escribir (sin esto, en seco)")
    ap.add_argument("--limit", type=int, default=0, help="como mucho N contactos a tocar")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    mapping = hct.load_mapping(cur, HubSpotClient())
    cur.execute(
        "SELECT * FROM prospect_contacts WHERE raw_payload IS NOT NULL AND hubspot_contact_id IS NOT NULL "
        "AND NOT is_dummy ORDER BY id"
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.rollback()

    stats: Counter = Counter()
    touched: list[int] = []
    pending: list[int] = []
    for row in rows:
        data, invalid, _ = mapping.map({"properties": row["raw_payload"] or {}})
        before = store._flatten_contact(row)
        patch = {k: v for k, v in data.items()
                 if v is not None and k != "email" and k not in invalid
                 and before.get(k) in (None, "", [])}
        if not patch:
            continue
        for k in patch:
            stats[k] += 1
        stats["contactos"] += 1
        if not args.apply:
            continue
        cur.execute("SAVEPOINT bf")
        try:
            store.update_contact(cur, row["id"], patch, None, source=SOURCE)
            seen = row["hubspot_seen"] if isinstance(row.get("hubspot_seen"), dict) else {}
            seen = {**seen, **{k: hct._enc_any(v) for k, v in patch.items()}}
            cur.execute("UPDATE prospect_contacts SET hubspot_seen = %s WHERE id = %s", (Json(seen), row["id"]))
            cur.execute("RELEASE SAVEPOINT bf")
        except Exception as exc:  # uno roto no frena el resto
            cur.execute("ROLLBACK TO SAVEPOINT bf")
            stats["errores"] += 1
            print(f"  contacto {row['id']}: {exc}")
            continue
        pending.append(row["id"])
        touched.append(row["id"])
        if len(pending) >= BATCH:
            hct.shield(cur, pending, stats)
            conn.commit()
            print(f"  {len(touched)} contactos actualizados…")
            pending = []
        if args.limit and len(touched) >= args.limit:
            break
    if args.apply:
        hct.shield(cur, pending, stats)
        conn.commit()
    conn.close()

    print(("APLICADO" if args.apply else "EN SECO (usá --apply para escribir)"))
    print(f"contactos a completar: {stats.pop('contactos', 0)}")
    for k, n in stats.most_common():
        print(f"  {k}: {n}")
    if mapping.fallback_people:
        print("(personas fuera del Hub en Scheduled By: el sync las registra en prospect_people)")


if __name__ == "__main__":
    main()
