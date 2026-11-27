#!/usr/bin/env python3
"""Resúmenes del contacto desde sus negocios + SQL Date contacto → negocio (2026-11-27).

`prospecting/prop_sync.py::summary_for_contacts` los mantiene de acá en adelante (al cambiar de
etapa, al asociar contactos y al editar las fechas del negocio). Este script los iguala sobre lo
que ya existía:

- Contacto ← todos sus negocios: SQL Date (la primera), First / Last Closed Win Date,
  First / Last Closed Lost Date, y los checks First Intro Call Completed / Deep Dive Completed /
  NDA Signed (sólo se prenden). Nunca vacía un valor que el contacto ya tiene.
- Negocio ABIERTO sin SQL Date ← la SQL Date de su contacto (sólo rellena).

En seco (por defecto) sólo reporta. Sin dummies.

Uso:
    cd backend
    python scripts/backfill_contact_summaries.py
    python scripts/backfill_contact_summaries.py --apply
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
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

SOURCE = "sync:backfill_contact_summaries"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        """
        SELECT d.*, dc.contact_id, COALESCE(s.is_closed, FALSE) AS _closed
          FROM prospect_deals d
          JOIN prospect_deal_contacts dc ON dc.deal_id = d.id
          LEFT JOIN prospect_deal_stages s ON s.pipeline_key = d.pipeline_key AND s.stage_key = d.stage_key
         WHERE NOT d.is_dummy
        """
    )
    by_contact = defaultdict(list)
    for r in cur.fetchall():
        r = dict(r)
        cid, closed = r.pop("contact_id"), r.pop("_closed")
        by_contact[cid].append((D._flatten(r), closed))
    ids = sorted(by_contact)
    cur.execute("SELECT * FROM prospect_contacts WHERE id = ANY(%s) AND NOT COALESCE(is_dummy, FALSE)", (ids,))
    contacts = {r["id"]: store._flatten_contact(r) for r in cur.fetchall()}

    ct_todo, deal_todo, closed_missing = [], {}, 0
    for cid, rows in by_contact.items():
        ct = contacts.get(cid)
        if not ct:
            continue
        patch = PS._summary_patch([d for d, _ in rows], ct)
        if patch:
            ct_todo.append((cid, patch))
        sql = patch.get("sql_date") or PS._day(ct.get("sql_date"))
        if sql:
            for d, closed in rows:
                if PS._empty(d.get("sql_date")):
                    if closed:
                        closed_missing += 1
                    else:
                        deal_todo.setdefault(d["id"], (cid, sql))

    c = Counter(k for _, p in ct_todo for k in p)
    print(f"Contactos con negocios: {len(contacts)} · a actualizar: {len(ct_todo)}")
    for k, n in c.most_common():
        print(f"  {k}: {n}")
    print(f"Negocios abiertos sin SQL Date que la toman del contacto: {len(deal_todo)}")
    print(f"(Negocios CERRADOS sin SQL Date con contacto que sí tiene: {closed_missing} — no se tocan)")
    if not args.apply:
        print("En seco: no se escribió nada.")
        conn.rollback()
        return
    for cid, patch in ct_todo:
        store.update_contact(cur, cid, patch, None, source=SOURCE)
    for did, (cid, sql) in deal_todo.items():
        D.update_deal(cur, did, {"sql_date": sql}, None, source=f"{PS.SOURCE_PREFIX}contact:{cid}")
    conn.commit()
    print(f"Listo: {len(ct_todo)} contactos, {len(deal_todo)} negocios.")


if __name__ == "__main__":
    main()
