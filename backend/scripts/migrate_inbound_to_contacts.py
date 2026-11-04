#!/usr/bin/env python3
"""Pasa la bandeja «Unassigned contacts» a contactos de verdad (2026-11-04).

Desde ese día un contacto puede existir SIN empresa (como en HubSpot), así que lo que
esperaba en la bandeja (`prospect_inbound_contacts`, status 'pending': contactos de
HubSpot y de Calendly sin empresa) pasa a ser un contacto normal:

- Si ya hay un contacto con ese email -> se rellenan sus vacíos (y si no tenía empresa y
  ahora hay una, se le asigna).
- Si no -> contacto nuevo, con la empresa de su dominio si hoy es UNA sola, o sin empresa.
- La fila de la bandeja queda 'linked' (registro de la llegada).
- Los de HubSpot conservan su id y la foto que usa el sync (`hubspot_seen`).
- Workflows: igual que en las importaciones, los que YA cumplen un workflow de contacto
  por condiciones quedan como "ya cumplía" (no se inscriben en masa).

Idempotente: sólo mira filas 'pending'.

Uso:
    cd backend
    python scripts/migrate_inbound_to_contacts.py            # en seco: conteos
    python scripts/migrate_inbound_to_contacts.py --apply    # migra
"""
from __future__ import annotations

import argparse
import json
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

from psycopg2.extras import Json, RealDictCursor, execute_values  # noqa: E402

from db import get_connection  # noqa: E402
from prospecting import hubspot_contacts as hc  # noqa: E402
from prospecting import store  # noqa: E402
from prospecting.contact_fields import CONTACT_COLUMNS  # noqa: E402

SOURCE = "inbound_migration"


def _company_by_domain(cur, rows: list[dict]) -> dict:
    domains = sorted({r["domain"] for r in rows if r.get("domain")})
    if not domains:
        return {}
    cur.execute(
        "SELECT domain, is_dummy, MIN(id) AS id, COUNT(*) AS n FROM prospect_companies "
        "WHERE domain = ANY(%s) GROUP BY domain, is_dummy",
        (domains,),
    )
    return {(r["domain"], r["is_dummy"]): r["id"] for r in cur.fetchall() if r["n"] == 1}


def migrate_batch(cur, rows: list[dict], apply: bool, stats: Counter) -> None:
    by_domain = _company_by_domain(cur, rows)
    emails = sorted({r["email"].lower() for r in rows if r.get("email")})
    existing = {}
    if emails:
        cur.execute("SELECT * FROM prospect_contacts WHERE LOWER(email) = ANY(%s) ORDER BY id", (emails,))
        for r in cur.fetchall():
            existing.setdefault((r["email"].lower(), r["is_dummy"]), dict(r))
    new, fills, seen_emails = [], [], set()
    for r in rows:
        key = ((r.get("email") or "").lower(), r["is_dummy"])
        r["company_id"] = by_domain.get((r.get("domain"), r["is_dummy"]))
        if r.get("email") and key in existing:
            fills.append((r, existing[key]))
        elif r.get("email") and key in seen_emails:
            stats["repetido_en_la_bandeja (se descarta)"] += 1
            r["_dup"] = True
        else:
            if r.get("email"):
                seen_emails.add(key)
            new.append(r)
    stats["nuevos_con_empresa"] += sum(1 for r in new if r["company_id"])
    stats["nuevos_sin_empresa"] += sum(1 for r in new if not r["company_id"])
    stats["ya_existia_el_contacto"] += len(fills)
    if not apply:
        return

    cols = list(CONTACT_COLUMNS)
    new_ids: list[int] = []
    if new:
        tuples = []
        for r in new:
            data = {}
            for k, v in (r.get("contact_data") or {}).items():
                f = hc.CONTACT_FIELDS_BY_KEY.get(k)
                if not f:
                    continue
                try:
                    data[k] = store.clean_contact_value(f, v)
                except ValueError:
                    stats["valor_inválido_omitido"] += 1
            props = {k: v for k, v in data.items() if v is not None and k not in cols}
            seen = (r.get("extra") or {}).get("hubspot_seen")
            tuples.append(tuple([r["company_id"], r["is_dummy"]] + [data.get(c) for c in cols]) + (
                Json(props), r.get("source") or SOURCE, r.get("received_at"), r.get("hubspot_contact_id"),
                Json(seen) if seen else None, Json(r["raw_payload"]) if r.get("hubspot_contact_id") and r.get("raw_payload") else None))
        res = execute_values(
            cur,
            f"INSERT INTO prospect_contacts (company_id, is_dummy, {', '.join(cols)}, props, created_by, created_at, "
            f"hubspot_contact_id, hubspot_seen, raw_payload) VALUES %s RETURNING id",
            tuples,
            template="(" + ", ".join(["%s"] * (2 + len(cols))) + ", %s, %s, COALESCE(%s, NOW()), %s, %s, %s)",
            page_size=len(tuples),
            fetch=True,
        )
        new_ids = [x["id"] for x in res]
        for r, cid in zip(new, new_ids):
            r["contact_id"] = cid
        execute_values(
            cur,
            "INSERT INTO prospect_company_events (company_id, actor, source, field, new_value, contact_id) VALUES %s",
            [(r["company_id"], None, r.get("source") or SOURCE, None, "contact_created", r["contact_id"]) for r in new],
            page_size=len(new),
        )
        companies = sorted({r["company_id"] for r in new if r["company_id"]})
        if companies:
            cur.execute(
                """
                UPDATE prospect_contacts SET is_primary = TRUE WHERE id IN (
                    SELECT DISTINCT ON (company_id) id FROM prospect_contacts
                     WHERE company_id = ANY(%s)
                       AND company_id NOT IN (SELECT company_id FROM prospect_contacts
                                               WHERE is_primary AND company_id = ANY(%s))
                     ORDER BY company_id, created_at, id)
                """,
                (companies, companies),
            )
            for c in companies:
                store.recompute_contact_incomplete(cur, c)

    filled = []
    for r, ex in fills:
        before = store._flatten_contact(ex)
        patch = {k: v for k, v in (r.get("contact_data") or {}).items()
                 if v not in (None, "", []) and k != "email" and before.get(k) in (None, "", [])}
        try:
            if patch:
                store.update_contact(cur, ex["id"], patch, None, source=r.get("source") or SOURCE)
            if ex["company_id"] is None and r["company_id"]:
                store.set_contact_company(cur, ex["id"], r["company_id"], None, source=SOURCE)
        except ValueError:
            stats["valor_inválido_omitido"] += 1
        r["contact_id"] = ex["id"]
        r["company_id"] = ex["company_id"] or r["company_id"]
        filled.append(ex["id"])

    done = [r for r in rows if r.get("contact_id")]
    if done:
        execute_values(
            cur,
            """
            UPDATE prospect_inbound_contacts i
               SET status = 'linked', contact_id = v.contact_id, company_id = v.company_id,
                   resolved_at = NOW(), resolved_by = 'inbound_migration'
              FROM (VALUES %s) AS v(id, contact_id, company_id)
             WHERE i.id = v.id
            """,
            [(r["id"], r["contact_id"], r["company_id"]) for r in done],
            template="(%s::bigint, %s::bigint, %s::bigint)",
            page_size=len(done),
        )
    dups = [r["id"] for r in rows if r.get("_dup")]
    if dups:
        cur.execute(
            "UPDATE prospect_inbound_contacts SET status = 'discarded', reason = 'duplicate_in_tray', "
            "resolved_at = NOW(), resolved_by = %s WHERE id = ANY(%s)",
            (SOURCE, dups),
        )
    hc.shield(cur, new_ids + filled, stats)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="migra (default: dry-run)")
    ap.add_argument("--batch", type=int, default=500)
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        store.ensure_schema(cur)  # columnas nuevas (company_id nullable): commit en el acto
        conn.commit()
        cur.execute("SELECT source, COUNT(*) AS n FROM prospect_inbound_contacts WHERE status = 'pending' GROUP BY 1")
        print("Pendientes en la bandeja:", {r["source"]: r["n"] for r in cur.fetchall()})
        stats = Counter()
        last_id = 0
        while True:
            cur.execute(
                "SELECT * FROM prospect_inbound_contacts WHERE status = 'pending' AND id > %s ORDER BY id LIMIT %s",
                (last_id, args.batch),
            )
            rows = [dict(r) for r in cur.fetchall()]
            if not rows:
                break
            last_id = rows[-1]["id"]
            migrate_batch(cur, rows, args.apply, stats)
            if args.apply:
                conn.commit()
            else:
                conn.rollback()
            print(f"  hasta la fila {last_id}: {dict(stats)}", flush=True)
        print("\nResumen:", json.dumps(dict(stats), ensure_ascii=False, indent=2))
        if not args.apply:
            print("\nSIN --apply: no se escribió nada.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
