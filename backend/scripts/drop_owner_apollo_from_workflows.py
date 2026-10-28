#!/usr/bin/env python3
"""Saca "Prospecting Owner Apollo" de los workflows de Prospecting guardados en RDS.

Desde el 2026-10-28 hay un solo owner (Prospecting Owner) y el campo
`prospecting_owner_apollo` salió de `FIELDS`: un workflow que lo nombre ya no
valida al editarlo. Este script, por cada workflow:

- si el DISPARADOR usa el campo (el "6) Prospecting Owner HubSpot", que copiaba
  Apollo → Owner), lo borra: sin ese campo no le queda función;
- si sólo lo usa un PASO (el clear de los workflows de liberar la empresa), quita
  ese paso y engancha lo que apuntaba a él con el paso siguiente.

Uso:
    cd backend
    python scripts/drop_owner_apollo_from_workflows.py            # dry-run: sólo el reporte
    python scripts/drop_owner_apollo_from_workflows.py --apply    # escribe

Es idempotente: una segunda corrida no encuentra nada.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from psycopg2.extras import Json, RealDictCursor  # noqa: E402

from db import get_connection  # noqa: E402

FIELD = "prospecting_owner_apollo"


def _is_apollo_step(node: dict) -> bool:
    action = node.get("action") or {}
    fields = (action.get("field"), action.get("from_field"))
    return node.get("type") == "action" and any(
        f and f.split(".")[-1] == FIELD for f in fields
    )


def _drop_steps(steps: dict) -> tuple[dict, list[str]]:
    nodes = dict(steps.get("nodes") or {})
    removed = [nid for nid, n in nodes.items() if _is_apollo_step(n)]
    for nid in removed:
        nxt = nodes.pop(nid).get("next")
        # Todo lo que apuntaba al paso borrado pasa a apuntar a su siguiente.
        for n in nodes.values():
            if n.get("next") == nid:
                n["next"] = nxt
            br = n.get("branch") or {}
            if br.get("else_next") == nid:
                br["else_next"] = nxt
            for p in br.get("paths") or []:
                if p.get("next") == nid:
                    p["next"] = nxt
        if steps.get("start") == nid:
            steps = {**steps, "start": nxt}
    return {**steps, "nodes": nodes}, removed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="escribe (sin esto es dry-run)")
    args = ap.parse_args()

    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name, enabled, trigger, steps FROM prospect_workflows "
                "WHERE (trigger::text || steps::text) LIKE %s ORDER BY id",
                (f"%{FIELD}%",),
            )
            rows = cur.fetchall()
            if not rows:
                print("Ningún workflow usa el campo. Nada que hacer.")
                return 0
            for wf in rows:
                label = f"#{wf['id']} {wf['name']} ({'ACTIVO' if wf['enabled'] else 'apagado'})"
                if FIELD in json.dumps(wf["trigger"]):
                    print(f"BORRAR   {label}: el disparador usa {FIELD}")
                    if args.apply:
                        cur.execute("DELETE FROM prospect_workflows WHERE id = %s", (wf["id"],))
                    continue
                new_steps, removed = _drop_steps(wf["steps"] or {})
                if FIELD in json.dumps(new_steps):
                    print(f"REVISAR  {label}: sigue nombrando {FIELD} fuera de un paso simple; no se toca")
                    continue
                print(f"EDITAR   {label}: se quitan los pasos {', '.join(removed)}")
                if args.apply:
                    cur.execute(
                        "UPDATE prospect_workflows SET steps = %s, updated_at = NOW(), updated_by = 'script' "
                        "WHERE id = %s",
                        (Json(new_steps), wf["id"]),
                    )
            if not args.apply:
                conn.rollback()
                print("\nDry-run: no se escribió nada. Correr con --apply para aplicar.")
            else:
                print("\nAplicado.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
