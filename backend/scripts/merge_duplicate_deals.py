#!/usr/bin/env python3
"""Fusiona los negocios de Prospecting que quedaron duplicados (2026-11-24).

Desde el 2026-11-06 cada reunión agendada generaba DOS negocios en Intro Call: el del
workflow #13 del Hub («Meeting Scheduled --> Deal created», sin `hubspot_deal_id`) y el que
HubSpot crea con su propio workflow y trae el sync de negocios. El sync ahora adopta el del
Hub en vez de crear otro (`hubspot_deals.find_adoptable`); este script arregla los pares que
ya existían, buscándolos con ese mismo helper (ventana de 3 días, contacto en común).

Qué negocio queda (el «sobreviviente»):
  1. el que tiene oportunidad del hub;
  2. si no, el de etapa más avanzada (Closed Lost / Closed Won cuentan como lo más avanzado:
     es el resultado real);
  3. empate → el de HubSpot.

Al otro se le saca todo antes de borrarlo: el sobreviviente se queda con el id de HubSpot
(y su foto / raw), la oportunidad y la cuenta si no tenía, la fecha de creación más vieja
(la de HubSpot), los vacíos rellenados, los contactos, las fechas de etapa y el historial.
Se borra con DELETE directo, no con «Eliminar»: eso lo pondría en la lista de bloqueo con
el id de HubSpot que ahora lleva el sobreviviente.

Uso:
    cd backend
    python scripts/merge_duplicate_deals.py            # en seco: lista los pares
    python scripts/merge_duplicate_deals.py --apply
    python scripts/merge_duplicate_deals.py --days 90  # cuánto mirar hacia atrás (default 60)

Es idempotente: un par ya fusionado no vuelve a aparecer.
"""
from __future__ import annotations

import argparse
import sys
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
from prospecting.deal_fields import DEAL_COLUMNS  # noqa: E402

PAIR_WINDOW_DAYS = 3
SOURCE = "merge_duplicates"


def _empty(v) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _score(d: dict) -> tuple:
    stage = d["stage_key"]
    r = 100 if stage in ("closed_lost", "closed_won") else D.rank(stage)
    return (1 if d.get("opportunity_id") else 0, -1 if r is None else r, 1 if d.get("hubspot_deal_id") else 0)


def find_pairs(cur, days: int) -> list[tuple[dict, dict]]:
    cur.execute(
        """SELECT d.*, ARRAY(SELECT contact_id FROM prospect_deal_contacts x WHERE x.deal_id = d.id) AS contact_ids
             FROM prospect_deals d
            WHERE NULLIF(d.hubspot_deal_id, '') IS NOT NULL AND NOT d.is_dummy
              AND d.created_at > NOW() - make_interval(days => %s)
            ORDER BY d.created_at, d.id""",
        (days,),
    )
    pairs, used = [], set()
    for t in cur.fetchall():
        t = dict(t)
        h = hd.find_adoptable(cur, t["pipeline_key"], t["contact_ids"], t["company_id"], t["created_at"],
                              exclude=used, window_days=PAIR_WINDOW_DAYS)
        if h:
            used.add(h["id"])
            t.pop("contact_ids", None)
            pairs.append((h, t))
    return pairs


def merge(cur, keep: dict, drop: dict) -> list[str]:
    """Pasa todo de `drop` a `keep` y borra `drop`. Devuelve qué movió."""
    moved, sets, args = [], [], []
    # Índices únicos parciales: primero se suelta en el que se va.
    move_hs = not keep.get("hubspot_deal_id") and drop.get("hubspot_deal_id")
    move_opp = not keep.get("opportunity_id") and drop.get("opportunity_id")
    if move_hs or move_opp:
        cur.execute("UPDATE prospect_deals SET hubspot_deal_id = CASE WHEN %s THEN NULL ELSE hubspot_deal_id END, "
                    "opportunity_id = CASE WHEN %s THEN NULL ELSE opportunity_id END WHERE id = %s",
                    (bool(move_hs), bool(move_opp), drop["id"]))
    if move_hs:
        sets += ["hubspot_deal_id = %s", "hubspot_seen = %s", "raw_payload = %s"]
        args += [drop["hubspot_deal_id"], Json(drop.get("hubspot_seen")), Json(drop.get("raw_payload"))]
        moved.append(f"id HubSpot {drop['hubspot_deal_id']}")
    if move_opp:
        sets += ["opportunity_id = %s", "account_id = COALESCE(account_id, %s)"]
        args += [drop["opportunity_id"], drop.get("account_id")]
        moved.append(f"oportunidad #{drop['opportunity_id']}")
    elif not keep.get("account_id") and drop.get("account_id"):
        sets.append("account_id = %s")
        args.append(drop["account_id"])
        moved.append(f"cuenta #{drop['account_id']}")
    if drop["created_at"] < keep["created_at"]:
        sets.append("created_at = %s")
        args.append(drop["created_at"])
        moved.append(f"creado {drop['created_at']:%Y-%m-%d}")
    filled = []
    for c in DEAL_COLUMNS:
        if c != "name" and _empty(keep.get(c)) and not _empty(drop.get(c)):
            sets.append(f"{c} = %s")
            args.append(drop[c])
            filled.append(c)
    kp = {k: v for k, v in (keep.get("props") or {}).items() if not _empty(v)}
    dp = {k: v for k, v in (drop.get("props") or {}).items() if not _empty(v)}
    filled += [k for k in dp if k not in kp]
    sets += ["props = %s", "stage_dates = %s", "updated_at = NOW()"]
    args += [Json({**dp, **kp}), Json({**(drop.get("stage_dates") or {}), **(keep.get("stage_dates") or {})})]
    if filled:
        moved.append("rellena " + ", ".join(sorted(filled)))
    cur.execute(f"UPDATE prospect_deals SET {', '.join(sets)} WHERE id = %s", args + [keep["id"]])
    cur.execute("INSERT INTO prospect_deal_contacts (deal_id, contact_id) "
                "SELECT %s, contact_id FROM prospect_deal_contacts WHERE deal_id = %s ON CONFLICT DO NOTHING",
                (keep["id"], drop["id"]))
    cur.execute("UPDATE prospect_company_events SET deal_id = %s WHERE deal_id = %s", (keep["id"], drop["id"]))
    D._log(cur, keep, SOURCE, None, "merged_from", None, f"{drop['name']} (#{drop['id']})")
    cur.execute("DELETE FROM prospect_deals WHERE id = %s", (drop["id"],))
    return moved


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--days", type=int, default=60)
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    pairs = find_pairs(cur, args.days)
    print(f"{len(pairs)} pares {'(se fusionan)' if args.apply else '(en seco)'}\n")
    ok = 0
    for h, t in pairs:
        keep, drop = (h, t) if _score(h) > _score(t) else (t, h)
        tag = lambda d: f"#{d['id']} {d['name'][:38]!r} [{d['stage_key']}] {'HubSpot' if d is t else 'Hub'}"  # noqa: E731
        print(f"queda {tag(keep)}  ←  se borra {tag(drop)}")
        if not args.apply:
            continue
        cur.execute("SAVEPOINT m")
        try:
            moved = merge(cur, keep, drop)
            cur.execute("RELEASE SAVEPOINT m")
            ok += 1
            print("    " + ("; ".join(moved) or "sin nada que mover"))
        except Exception as exc:
            cur.execute("ROLLBACK TO SAVEPOINT m")
            print(f"    ERROR: {exc}")
    if args.apply:
        conn.commit()
        print(f"\n{ok}/{len(pairs)} fusionados.")
    else:
        conn.rollback()
        print("\nEn seco: no se escribió nada. Correr con --apply para fusionar.")
    conn.close()


if __name__ == "__main__":
    main()
