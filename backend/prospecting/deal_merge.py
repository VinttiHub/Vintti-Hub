"""Fusión de negocios duplicados Hub ↔ HubSpot (2026-11-24; automática desde 2026-11-27).

Cada reunión agendada puede generar DOS negocios: el del workflow #13 del Hub («Meeting
Scheduled --> Deal created», sin `hubspot_deal_id`) y el que HubSpot crea y trae el sync. El sync
adopta el del Hub al crear el de HubSpot (`hubspot_deals.find_adoptable`), pero si el de HubSpot
llegó ANTES, sin contacto ni empresa en el Hub (Siana Marketing, 2026-11-09/10), el par se escapa:
al día siguiente el workflow crea el suyo y nadie vuelve a mirar. Por eso `run()` corre al final
de cada sync de negocios (cron horario) y en `scripts/merge_duplicate_deals.py`.

Pares: negocio de HubSpot reciente + `find_adoptable` (ventana de 3 días, contacto en común o
misma empresa). Qué negocio queda:
  1. el que tiene oportunidad del hub;
  2. si no, el de etapa más avanzada (Closed Lost / Closed Won cuentan como lo más avanzado);
  3. empate → el de HubSpot.
Al otro se le saca todo antes de borrarlo: id de HubSpot (y su foto / raw), oportunidad, cuenta,
empresa, la fecha de creación más vieja, los vacíos, los contactos, las fechas de etapa y el
historial. DELETE directo, no «Eliminar»: eso pondría en la lista de bloqueo el id de HubSpot
que ahora lleva el que queda. Idempotente.
"""
from __future__ import annotations

import logging

from psycopg2.extras import Json

from prospecting import deals as D
from prospecting.deal_fields import DEAL_COLUMNS

PAIR_WINDOW_DAYS = 3
SOURCE = "merge_duplicates"


def _empty(v) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _score(d: dict) -> tuple:
    stage = d["stage_key"]
    r = 100 if stage in ("closed_lost", "closed_won") else D.rank(stage)
    return (1 if d.get("opportunity_id") else 0, -1 if r is None else r, 1 if d.get("hubspot_deal_id") else 0)


def find_pairs(cur, days: int) -> list:
    """[(negocio del Hub, negocio de HubSpot)] que son el mismo."""
    from prospecting import hubspot_deals as hd

    cur.execute(
        """SELECT d.*, ARRAY(SELECT contact_id FROM prospect_deal_contacts x WHERE x.deal_id = d.id) AS contact_ids
             FROM prospect_deals d
            WHERE NULLIF(d.hubspot_deal_id, '') IS NOT NULL AND NOT d.is_dummy
              AND d.created_at > NOW() - make_interval(days => %s)
            ORDER BY d.created_at, d.id""",
        (days,),
    )
    pairs, used = [], set()
    for t in [dict(r) for r in cur.fetchall()]:
        h = hd.find_adoptable(cur, t["pipeline_key"], t["contact_ids"], t["company_id"], t["created_at"],
                              exclude=used, window_days=PAIR_WINDOW_DAYS)
        if h:
            used.add(h["id"])
            t.pop("contact_ids", None)
            pairs.append((h, t))
    return pairs


def keep_and_drop(h: dict, t: dict) -> tuple:
    return (h, t) if _score(h) > _score(t) else (t, h)


def merge(cur, keep: dict, drop: dict) -> list:
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
    # La empresa (2026-11-27): un negocio de HubSpot sin asociación a empresa se queda con la
    # del negocio del Hub. Va después del DELETE para que el evento quede en el que sobrevive.
    if not keep.get("company_id") and drop.get("company_id"):
        D.set_company(cur, keep["id"], drop["company_id"], None, source=SOURCE)
        moved.append(f"empresa #{drop['company_id']}")
    from prospecting import prop_sync
    prop_sync.pull_into_deal(cur, keep["id"], None)
    prop_sync.summary_for_contacts(cur, keep["id"], None)
    return moved


def run(cur, days: int = 60, apply: bool = True, log=None) -> dict:
    """Busca y fusiona los pares. Un SAVEPOINT por par: si uno falla, los demás siguen y la
    transacción no queda abortada."""
    pairs = find_pairs(cur, days)
    out = {"pares": len(pairs), "fusionados": 0, "errores": [], "detalle": []}
    for h, t in pairs:
        keep, drop = keep_and_drop(h, t)
        line = f"queda #{keep['id']} {str(keep.get('name') or '')[:38]!r} [{keep['stage_key']}]  ←  " \
               f"se borra #{drop['id']} [{drop['stage_key']}]"
        if not apply:
            out["detalle"].append(line)
            continue
        cur.execute("SAVEPOINT deal_merge")
        try:
            moved = merge(cur, keep, drop)
            cur.execute("RELEASE SAVEPOINT deal_merge")
            out["fusionados"] += 1
            out["detalle"].append(line + "  · " + ("; ".join(moved) or "sin nada que mover"))
        except Exception as exc:  # noqa: BLE001
            cur.execute("ROLLBACK TO SAVEPOINT deal_merge")
            logging.exception("deal_merge: #%s ← #%s", keep["id"], drop["id"])
            out["errores"].append(f"#{keep['id']} ← #{drop['id']}: {exc}")
        if log:
            log(out["detalle"][-1])
    return out
