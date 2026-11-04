#!/usr/bin/env python3
"""Importa TODAS las empresas de HubSpot (~165 k) a Prospecting (`prospect_companies`).

Por qué un script y no el webhook de Clay (`store.upsert_from_clay`): ese camino va de
a una empresa y escribe un evento por campo — ~2 M de inserts a ~70 ms cada viaje a la
RDS, horas. Acá se lee HubSpot de a 100 y se escribe en lote.

Lo que NO se puede romper:

- **Workflows.** Desde el 2026-11-03 el motor corre sobre empresas reales y el
  disparador por condiciones inscribe en la transición "no cumple → cumple": una empresa
  sin fila en `prospect_wf_match` cuenta como recién llegada. Sin protección, el cron de
  la hora siguiente inscribiría a todas las importadas que cumplan (mails, Slack,
  To-Dos). Por eso, en la misma transacción de cada lote, las que YA cumplen quedan
  anotadas como "ya cumplía" (lo mismo que `engine.snapshot_matches()`), y no se llama
  ni a `emit_event()` ni a `tick()`. Si después un BDR las mueve y empiezan a cumplir,
  entran normalmente. Los workflows por HORARIO no tienen memoria: el resumen final
  avisa cuántas importadas cumplirían cada uno.
- **Lo que trabajó un BDR.** Una empresa que ya existe (por `hubspot_company_id`, o por
  dominio si entró por Clay sin id de HubSpot) sólo se RELLENA en los campos vacíos.
- **Duplicados de HubSpot.** Dos empresas de HubSpot con el mismo dominio entran como
  dos filas (son dos registros allá). El cruce por dominio sólo adopta filas de Clay.

Es idempotente: correrlo de nuevo no duplica (cruza por `hubspot_company_id`) y sólo
rellena vacíos, así que sirve también para traer las empresas nuevas de HubSpot.

Uso:
    cd backend
    python scripts/import_hubspot_companies.py --limit 300          # dry-run: mapeo + muestra
    python scripts/import_hubspot_companies.py --apply --limit 500  # prueba chica
    python scripts/import_hubspot_companies.py --apply              # todo (~20-30 min)
    python scripts/import_hubspot_companies.py --apply --resume     # sigue desde el cursor guardado

Owners (el «Prospecting Owner (HubSpot)» es EL Prospecting Owner del Hub):
    python scripts/import_hubspot_companies.py --audit --week "Semana 30"   # diagnóstico, sólo lectura
    python scripts/import_hubspot_companies.py --repair-owners              # qué corregiría
    python scripts/import_hubspot_companies.py --repair-owners --apply      # corrige

Sync incremental (lo mismo que corre el cron cada 30 min, sin tope de tiempo; sirve
para ponerse al día la primera vez):
    python scripts/import_hubspot_companies.py --sync            # qué cambiaría
    python scripts/import_hubspot_companies.py --sync --apply    # aplica
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

from psycopg2.extras import Json, RealDictCursor, execute_values  # noqa: E402

from db import get_connection  # noqa: E402
from prospecting import engine, store  # noqa: E402
from prospecting.rules import has_conditions  # noqa: E402
from utils.hubspot import HubSpotClient  # noqa: E402

SOURCE = "hubspot_import"
CURSOR_FILE = HERE / "data" / "hubspot_companies_import.cursor"

from prospecting.hubspot_companies import (  # noqa: E402
    COLS,
    FILLABLE,
    OwnerResolver,
    map_company,
    owner_property_candidates,
    resolve_mapping,
)



class Importer:
    def __init__(self, conn, apply: bool):
        self.conn = conn
        self.apply = apply
        self.cur = conn.cursor(cursor_factory=RealDictCursor)
        self.stats = Counter()
        self.notes = Counter()
        self.sample: list[dict] = []
        self.imported_ids: list[int] = []
        self.filter_wfs = []
        self.schedule_wfs = []
        if apply:
            store.ensure_schema(self.cur)
            conn.commit()
        for wf in engine.enabled_workflows(self.cur):
            if engine.obj_of(wf) != "company":
                continue
            t = wf["trigger"]
            if not has_conditions(t.get("conditions")):
                continue
            if t.get("type") == "filter":
                self.filter_wfs.append(wf)
            elif t.get("type") == "schedule":
                self.schedule_wfs.append(wf)

    def process(self, rows: list[dict]) -> None:
        if not rows:
            return
        cur = self.cur
        hs_ids = [r["hubspot_company_id"] for r in rows]
        cur.execute(
            "SELECT * FROM prospect_companies WHERE hubspot_company_id = ANY(%s) AND NOT is_dummy",
            (hs_ids,),
        )
        by_hs = {r["hubspot_company_id"]: r for r in cur.fetchall()}
        domains = sorted({r["domain"] for r in rows if r["domain"] and r["hubspot_company_id"] not in by_hs})
        by_domain: dict[str, dict] = {}
        if domains:
            cur.execute(
                """
                SELECT * FROM prospect_companies
                 WHERE domain = ANY(%s) AND NOT is_dummy AND hubspot_company_id IS NULL
                 ORDER BY id
                """,
                (domains,),
            )
            for r in cur.fetchall():
                by_domain.setdefault(r["domain"], r)

        new_rows, updates = [], []
        claimed: set[int] = set()
        for d in rows:
            existing = by_hs.get(d["hubspot_company_id"])
            if existing is None and d["domain"]:
                cand = by_domain.get(d["domain"])
                if cand is not None and cand["id"] not in claimed:
                    existing = cand
            if existing is None:
                if not d.get("name"):
                    self.stats["sin_nombre_ni_dominio"] += 1
                    continue
                new_rows.append(d)
                continue
            claimed.add(existing["id"])
            changes = []
            for c in FILLABLE:
                v = d.get(c)
                if v is not None and existing.get(c) in (None, ""):
                    changes.append((c, existing.get(c), v))
            if not existing.get("hubspot_company_id"):
                changes.append(("hubspot_company_id", None, d["hubspot_company_id"]))
            self.stats["ya_existia_por_id" if existing.get("hubspot_company_id") else "adoptada_por_dominio"] += 1
            if changes:
                updates.append((existing["id"], changes))

        self.stats["nuevas"] += len(new_rows)
        self.stats["existentes_con_campos_rellenados"] += len(updates)
        for d in new_rows:
            if len(self.sample) < 10:
                self.sample.append({k: d.get(k) for k in COLS if d.get(k) is not None})
        if not self.apply:
            return

        new_ids: list[int] = []
        if new_rows:
            tuples = []
            for d in new_rows:
                vals = [d.get(c) for c in COLS]
                if vals[COLS.index("lead_source")] is None:
                    vals[COLS.index("lead_source")] = "HubSpot"
                tuples.append(tuple(vals) + (False, Json(d["raw_payload"]), d.get("created_at")))
            res = execute_values(
                cur,
                f"INSERT INTO prospect_companies ({', '.join(COLS)}, is_dummy, raw_payload, created_at) "
                f"VALUES %s RETURNING id",
                tuples,
                template="(" + ", ".join(["%s"] * len(COLS)) + ", %s, %s, COALESCE(%s, NOW()))",
                page_size=len(tuples),
                fetch=True,
            )
            new_ids = [r["id"] for r in res]
            execute_values(
                cur,
                "INSERT INTO prospect_company_events (company_id, actor, source, field) VALUES %s",
                [(i, None, SOURCE, None) for i in new_ids],
                template="(%s, %s, %s, %s)",
                page_size=len(new_ids),
            )
            self.imported_ids.extend(new_ids)

        for cid, changes in updates:
            sets = ", ".join(f"{c} = %s" for c, _, _ in changes)
            cur.execute(
                f"UPDATE prospect_companies SET {sets}, updated_at = NOW() WHERE id = %s",
                [v for _, _, v in changes] + [cid],
            )
            for field, old, new in changes:
                store.log_event(cur, cid, SOURCE, None, field, old, new)

        self.shield(new_ids + [cid for cid, _ in updates])
        self.conn.commit()

    def shield(self, ids: list[int]) -> None:
        """Lo que ya cumple un workflow por condiciones queda como "ya cumplía" (lo mismo
        que engine.snapshot_matches(), en lote): el cron no lo inscribe en masa."""
        if not ids:
            return
        now = engine.utcnow()
        for wf in self.filter_wfs:
            hits = engine.matching_ids(self.cur, wf["trigger"]["conditions"], now, False, ids, "company")
            if hits:
                execute_values(
                    self.cur,
                    """
                    INSERT INTO prospect_wf_match (workflow_id, record_id, matching, changed_at) VALUES %s
                    ON CONFLICT (workflow_id, record_id) DO UPDATE SET matching = TRUE, changed_at = EXCLUDED.changed_at
                    """,
                    [(wf["id"], h, True, now) for h in hits],
                    page_size=len(hits),
                )
                self.stats[f"blindadas en workflow #{wf['id']}"] += len(hits)

    def schedule_report(self) -> list[str]:
        out = []
        if not self.imported_ids:
            return out
        now = engine.utcnow()
        for wf in self.schedule_wfs:
            hits = engine.matching_ids(self.cur, wf["trigger"]["conditions"], now, False, self.imported_ids, "company")
            if hits:
                out.append(f"  ⚠ Workflow por horario #{wf['id']} «{wf.get('name')}»: {len(hits)} importadas "
                           f"cumplen hoy y entrarían en su próximo horario.")
        return out


def iter_pages(client: HubSpotClient, properties: list[str], limit: int, after: str | None):
    """Yield (results, next_after) página por página."""
    read = 0
    while True:
        want = 100 if not limit else min(100, limit - read)
        if want <= 0:
            return
        results, nxt = client.list_companies_page(properties, after=after, limit=want)
        read += len(results)
        yield results, nxt
        after = nxt
        if not nxt:
            return


def run_import(args, client, imp: Importer, mapping, owner: OwnerResolver) -> None:
    properties = sorted({p for plist in mapping.values() for p in plist} | set(ALWAYS) | {owner.prop["name"]})
    after = None
    if args.resume and CURSOR_FILE.exists():
        after = CURSOR_FILE.read_text().strip() or None
        print(f"Retomando desde el cursor {after}")
    buf, read, t0 = [], 0, time.time()
    for results, nxt in iter_pages(client, properties, args.limit, after):
        for rec in results:
            d, notes = map_company(rec, mapping, owner)
            imp.notes.update(notes)
            buf.append(d)
        read += len(results)
        if len(buf) >= args.batch or not nxt:
            imp.process(buf)
            buf = []
            if args.apply:
                CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
                CURSOR_FILE.write_text(nxt or "")
            print(f"  leídas {read:>7} · {read / max(time.time() - t0, 1e-6):.0f}/s · {dict(imp.stats)}", flush=True)
    imp.process(buf)

    print("\nResumen:", json.dumps(dict(imp.stats), ensure_ascii=False, indent=2))
    if imp.notes:
        print("Avisos de mapeo:")
        for k, n in imp.notes.most_common(40):
            print(f"  {n:>7} × {k}")
    if imp.sample:
        print("\nMuestra de empresas nuevas:")
        for smp in imp.sample:
            print("  ", json.dumps(smp, ensure_ascii=False, default=str)[:300])
    for line in imp.schedule_report():
        print(line)


def _protected_owner_ids(cur, ids: list[int]) -> set[int]:
    """Empresas cuyo owner lo tocó alguien que no es la importación (BDR, workflow, Clay,
    edición masiva): la reparación no las pisa."""
    cur.execute(
        """
        SELECT DISTINCT company_id FROM prospect_company_events
         WHERE company_id = ANY(%s) AND field = 'prospecting_owner_email' AND source NOT IN (%s, %s)
        """,
        (ids, SOURCE, "hubspot_sync"),
    )
    return {r["company_id"] for r in cur.fetchall()}


def run_repair_owners(args, client, imp: Importer, owner: OwnerResolver) -> None:
    """Pone en cada importada el BDR que dice «Prospecting Owner (HubSpot)».

    Sólo toca las empresas cuyo owner actual vino de la importación (ningún evento de
    owner de otra fuente). PO vacío en HubSpot -> se vacía; PO que no matchea ningún BDR
    activo -> no se toca y sale en el reporte."""
    cur = imp.cur
    stats, unresolved, sample = Counter(), Counter(), []
    read, t0 = 0, time.time()
    pending: list[tuple[str, str | None, str]] = []

    def flush():
        if not pending:
            return
        cur.execute(
            "SELECT id, hubspot_company_id, prospecting_owner_email FROM prospect_companies "
            "WHERE hubspot_company_id = ANY(%s) AND NOT is_dummy",
            ([h for h, _, _ in pending],),
        )
        rows = {}
        for r in cur.fetchall():
            rows.setdefault(r["hubspot_company_id"], []).append(r)
        protected = _protected_owner_ids(cur, [r["id"] for rs in rows.values() for r in rs])
        changes = []
        for hs_id, email, why in pending:
            for r in rows.get(hs_id, []):
                cur_v = r["prospecting_owner_email"] or None
                if why == "sin BDR activo que coincida":
                    stats["sin_cambio_po_no_matchea"] += 1
                    continue
                if cur_v == email:
                    stats["ya_estaba_bien"] += 1
                    continue
                if r["id"] in protected:
                    stats["distinto_pero_lo_toco_una_persona"] += 1
                    continue
                changes.append((r["id"], cur_v, email))
        stats["a_corregir"] += len(changes)
        for c in changes:
            if len(sample) < 15:
                sample.append(c)
        if args.apply and changes:
            execute_values(
                cur,
                "UPDATE prospect_companies p SET prospecting_owner_email = v.email, updated_at = NOW() "
                "FROM (VALUES %s) AS v(id, email) WHERE p.id = v.id",
                [(cid, new) for cid, _, new in changes],
                template="(%s::bigint, %s::text)",
                page_size=len(changes),
            )
            execute_values(
                cur,
                "INSERT INTO prospect_company_events (company_id, actor, source, field, old_value, new_value) VALUES %s",
                [(cid, None, SOURCE, "prospecting_owner_email", old, new) for cid, old, new in changes],
                page_size=len(changes),
            )
            imp.shield([cid for cid, _, _ in changes])
            imp.conn.commit()
        pending.clear()

    for results, nxt in iter_pages(client, [owner.prop["name"]], args.limit, None):
        for rec in results:
            raw = (rec.get("properties") or {}).get(owner.prop["name"])
            email, why = owner.resolve(raw)
            if why == "sin BDR activo que coincida":
                unresolved[owner.describe(store._clean_text(raw))] += 1
            pending.append((str(rec["id"]), email, why))
        read += len(results)
        if len(pending) >= args.batch or not nxt:
            flush()
            print(f"  leídas {read:>7} · {read / max(time.time() - t0, 1e-6):.0f}/s · {dict(stats)}", flush=True)
    flush()

    print("\nResumen:", json.dumps(dict(stats), ensure_ascii=False, indent=2))
    if sample:
        print("\nMuestra de correcciones (id Hub: antes -> después):")
        for cid, old, new in sample:
            print(f"  #{cid}: {old or '(vacío)'} -> {new or '(vacío)'}")
    if unresolved:
        print("\nPO de HubSpot que no matchean ningún BDR activo (no se tocaron):")
        for (email, name), n in unresolved.most_common():
            print(f"  {n:>7} × {name or '?'} <{email or 'sin email'}>")


def run_audit(args, client, imp: Importer, props: list, owner: OwnerResolver, bdrs: list) -> None:
    """Sólo lectura: qué propiedad es el PO, cómo resuelve cada valor y cómo está hoy el Hub."""
    cur = imp.cur
    print("Propiedades de empresa candidatas a PO:")
    for p in owner_property_candidates(props):
        mark = "  <- la que se usa" if p["name"] == owner.prop["name"] else ""
        print(f"  {p['name']:<40} «{p.get('label')}» type={p.get('type')} fieldType={p.get('fieldType')}{mark}")
    print("Propiedades de semana:")
    for p in props:
        k = store._norm_key(p.get("label") or "") + " " + p["name"]
        if "semana" in k or "week" in k:
            print(f"  {p['name']:<40} «{p.get('label')}» type={p.get('type')}")
    print("\nBDRs activos del Hub:")
    for b in bdrs:
        print(f"  {b.get('name')} <{b['email']}>")

    cur.execute(
        """
        SELECT COALESCE(prospecting_owner_email, '(sin owner)') AS owner, COUNT(*) AS n
          FROM prospect_companies WHERE hubspot_company_id IS NOT NULL AND NOT is_dummy
         GROUP BY 1 ORDER BY 2 DESC
        """
    )
    print("\nImportadas por owner en el Hub hoy:")
    for r in cur.fetchall():
        print(f"  {r['n']:>7} × {r['owner']}")

    where, params = "hubspot_company_id IS NOT NULL AND NOT is_dummy", []
    if args.week:
        where += " AND week_label = %s"
        params.append(args.week)
    cur.execute(
        f"SELECT hubspot_company_id, name, prospecting_owner_email FROM prospect_companies "
        f"WHERE {where} ORDER BY id LIMIT %s",
        params + [args.audit_sample],
    )
    rows = cur.fetchall()
    print(f"\nMuestra de {len(rows)} importadas{' de ' + args.week if args.week else ''} contra HubSpot:")
    table = Counter()
    for i in range(0, len(rows), 100):
        chunk = rows[i:i + 100]
        res = client._request(
            "POST", "/crm/v3/objects/companies/batch/read",
            json={"properties": [owner.prop["name"]], "inputs": [{"id": r["hubspot_company_id"]} for r in chunk]},
        )
        hs = {str(x["id"]): (x.get("properties") or {}).get(owner.prop["name"]) for x in res.get("results", [])}
        for r in chunk:
            raw = store._clean_text(hs.get(r["hubspot_company_id"]))
            email, name = owner.describe(raw) if raw else (None, None)
            hit, why = owner.resolve(raw)
            table[(name or email or "(vacío)", hit or "-", why, r["prospecting_owner_email"] or "-")] += 1
    print(f"  {'n':>5}  {'PO en HubSpot':<28} {'BDR que matchea':<30} {'cómo':<28} hoy en el Hub")
    for (hs_name, hit, why, now), n in table.most_common():
        print(f"  {n:>5}  {hs_name[:28]:<28} {hit[:30]:<30} {why[:28]:<28} {now}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="escribe (default: dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="máximo de empresas a leer de HubSpot (0 = todas)")
    ap.add_argument("--batch", type=int, default=500, help="empresas por transacción (default 500)")
    ap.add_argument("--resume", action="store_true", help="arranca desde el cursor guardado")
    ap.add_argument("--owner-prop", help="nombre interno de la propiedad del PO en HubSpot (si no la encuentra sola)")
    ap.add_argument("--audit", action="store_true", help="diagnóstico de owners, sólo lectura")
    ap.add_argument("--week", help="con --audit: sólo esa semana, p. ej. 'Semana 30'")
    ap.add_argument("--audit-sample", type=int, default=300, help="con --audit: cuántas empresas comparar")
    ap.add_argument("--repair-owners", action="store_true",
                    help="corrige el owner de las importadas según «Prospecting Owner (HubSpot)»")
    ap.add_argument("--sync", action="store_true",
                    help="sync incremental HubSpot -> Hub (lo del cron), sin tope de tiempo")
    args = ap.parse_args()
    if args.sync:
        from prospecting import hubspot_companies as hs_companies
        conn = get_connection()
        try:
            report = hs_companies.sync(conn, dry_run=not args.apply, max_companies=args.limit or 10**9,
                                       time_budget=float("inf"), log=print)
        finally:
            conn.close()
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str)[:20000])
        if not args.apply:
            print("\nSIN --apply: no se escribió nada.")
        return
    if args.audit:
        args.apply = False

    client = HubSpotClient()
    mapping, owner_prop, props = resolve_mapping(client, args.owner_prop)
    print("Mapeo HubSpot -> prospect_companies:")
    for col, plist in mapping.items():
        print(f"  {col:<26} <- {', '.join(plist)}")
    print(f"  {'prospecting_owner_email':<26} <- {owner_prop['name']} «{owner_prop.get('label')}» "
          f"(BDR activo, por email o nombre)")
    print(f"  {'created_at':<26} <- createdate\n")

    owners = client.list_owners()
    conn = get_connection()
    try:
        imp = Importer(conn, args.apply)
        bdrs = store.list_bdrs(imp.cur)
        owner = OwnerResolver(owner_prop, owners, bdrs)
        print(f"Workflows por condiciones a blindar: {[w['id'] for w in imp.filter_wfs] or 'ninguno'}")
        print(f"Owners de HubSpot: {len(owners)} · BDRs activos en el Hub: {len(bdrs)}\n")

        if args.audit:
            run_audit(args, client, imp, props, owner, bdrs)
        elif args.repair_owners:
            run_repair_owners(args, client, imp, owner)
        else:
            run_import(args, client, imp, mapping, owner)
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
