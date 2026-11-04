"""Negocios de HubSpot -> Prospecting: mapeo, importación en lote y sync incremental
(2026-11-04). Mismo molde que `hubspot_contacts.py` (OwnerResolver, foto `hubspot_seen`,
marca de agua en `hubspot_sync_state`).

Lo usan `scripts/import_hubspot_deals.py` (importación) y
`POST /prospecting/hubspot/sync-deals` (tercer paso del cron cada 30 min, después de
empresas y contactos). Sólo HubSpot -> Hub, y sólo los dos pipelines de Vintti
(*Proceso de Contratación* y *Vintti AI Pipeline*).

- Etapa: por `hubspot_stage_id` en `prospect_deal_stages`, que se re-siembra de HubSpot en
  cada corrida (`deals.seed_stages_from_hubspot`). Un negocio con oportunidad del hub no
  retrocede por HubSpot (la oportunidad ya avanzó: `deals.reflect`).
- Empresa: asociación de HubSpot (la Primary primero) -> `hubspot_company_id`.
  Contactos: asociaciones -> `hubspot_contact_id`. Un negocio sin empresa en el Hub queda
  sin empresa (se le asigna cuando HubSpot se la asocia y ya está en el Hub).
- La cuenta / oportunidad del hub NO se crean acá: las sigue creando el sync de
  oportunidades de HubSpot. `deals.reflect()` ata el negocio por `hubspot_deal_id`.
- HubSpot gana sólo cuando su valor cambió respecto de la foto: lo editado en el Hub no se
  pisa cada 30 min.
"""
from __future__ import annotations

import time as _time
from collections import Counter
from datetime import datetime

from psycopg2.extras import Json, RealDictCursor, execute_values

from prospecting import deals as D
from prospecting import store
from prospecting.deal_fields import DEAL_COLUMNS, DEAL_FIELDS, DEAL_FIELDS_BY_KEY, LOST_REASONS
from prospecting.hubspot_companies import (
    BOOTSTRAP,
    OVERLAP,
    SEARCH_AFTER_CAP,
    OwnerResolver,
    _enc,
    _read_watermark,
    _write_state,
)
from utils.hubspot import HubSpotClient

IMPORT_SOURCE = "hubspot_import"
SYNC_SOURCE = "hubspot_sync"
SYNC_KEY = "prospect_deals"
SYNC_LOCK_KEY = 72_026_110_6
ALWAYS = ["dealname", "pipeline", "dealstage", "createdate", "hs_lastmodifieddate", "hubspot_owner_id"]
STAGE_SEEN = "__stage"

# Value interno / label viejo de HubSpot -> motivo del hub (ver hubspot_push.CLOSED_LOST_REASON_MAP).
_LOST_ALIASES = {"bad timing": "Timing", "competitor": "Internal Competition", "vintti’s fault": "Vintti's Fault",
                 "vinttis fault": "Vintti's Fault"}


class DealMapping:
    def __init__(self, props: list[dict], owners: dict, users: list[dict], defs: dict | None = None):
        # Catálogo efectivo (opciones de HubSpot encima de las de fábrica): sin esto un
        # desplegable que sólo tiene opciones en HubSpot (Pain Point) no validaría nunca.
        self.defs = defs or DEAL_FIELDS_BY_KEY
        self.meta = {p["name"]: p for p in props}
        by_norm: dict[str, str] = {}
        for p in props:
            for k in (p.get("name"), p.get("label")):
                if k:
                    by_norm.setdefault(store._norm_key(k), p["name"])
        self.fields: dict[str, list[str]] = {}
        for f in DEAL_FIELDS:
            cands = []
            for alias in f["hubspot"] + [f["key"], f["label"]]:
                p = alias if alias in self.meta else by_norm.get(store._norm_key(alias))
                if p and p not in cands:
                    cands.append(p)
            if cands:
                self.fields[f["key"]] = cands
        self._owner = OwnerResolver(self.meta.get("hubspot_owner_id") or {"name": "hubspot_owner_id"}, owners, users)

    def properties(self) -> list[str]:
        return sorted({p for pl in self.fields.values() for p in pl} | set(ALWAYS))

    def _translate(self, prop: str, raw):
        meta = self.meta.get(prop) or {}
        opts = {str(o.get("value")): o.get("label") for o in meta.get("options") or []}
        if meta.get("type") == "enumeration" and opts:
            parts = [p for p in str(raw).split(";") if p != ""]
            return "; ".join(opts.get(p, p) for p in parts) or None
        return raw

    def map(self, rec: dict) -> tuple[dict, set, Counter]:
        props = rec.get("properties") or {}
        data, invalid, notes = {}, set(), Counter()
        for key, plist in self.fields.items():
            prop = next((p for p in plist if props.get(p) not in (None, "")), None)
            if prop is None:
                data[key] = None
                continue
            f = self.defs.get(key) or DEAL_FIELDS_BY_KEY[key]
            raw = props[prop]
            if f["type"] == "user":
                email, why = self._owner.resolve(raw)
                if not email:
                    invalid.add(key)
                    notes[f"{f['label']}: «{raw}» {why}"] += 1
                    continue
                val = email
            else:
                val = self._translate(prop, raw)
                if key == "lost_reason" and isinstance(val, str):
                    val = _LOST_ALIASES.get(val.strip().lower(), val.strip())
                    if val not in LOST_REASONS:
                        val = next((o for o in LOST_REASONS if o.lower() == val.lower()), val)
            try:
                data[key] = store.clean_contact_value(f, val)
            except ValueError as exc:
                invalid.add(key)
                notes[str(exc)[:120]] += 1
        return data, invalid, notes


def load_mapping(cur, client: HubSpotClient) -> DealMapping:
    return DealMapping(client.get_properties("deals"), client.list_owners(), store.list_users(cur), D.defs_by_key(cur))


def _dt(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None


def _assoc(rec: dict, kind: str) -> list[tuple[str, bool]]:
    """Asociaciones que trae el GET de lista. La Primary viene con el tipo `deal_to_company`
    (las demás, `deal_to_company_unlabeled`); un mismo id puede venir con los dos."""
    res = (((rec.get("associations") or {}).get(kind) or {}).get("results")) or []
    out: dict[str, bool] = {}
    for a in res:
        if a.get("id"):
            k = str(a["id"])
            out[k] = out.get(k, False) or str(a.get("type") or "") in ("deal_to_company", "deal_to_contact")
    return list(out.items())


def _stage_index(cur) -> dict:
    cur.execute("SELECT pipeline_key, stage_key, hubspot_pipeline_id, hubspot_stage_id FROM prospect_deal_stages "
                "WHERE hubspot_stage_id IS NOT NULL")
    return {(r["hubspot_pipeline_id"], r["hubspot_stage_id"]): (r["pipeline_key"], r["stage_key"]) for r in cur.fetchall()}


def build_items(cur, recs: list[dict], mapping: DealMapping, assoc: dict | None, notes: Counter,
                stats: Counter) -> list[dict]:
    idx = _stage_index(cur)
    items = []
    for rec in recs:
        props = rec.get("properties") or {}
        ps = idx.get((str(props.get("pipeline") or ""), str(props.get("dealstage") or "")))
        if ps is None:
            stats["otro_pipeline (se ignora)"] += 1
            continue
        data, invalid, n = mapping.map(rec)
        notes.update(n)
        if not data.get("name"):
            data["name"] = f"Deal {rec['id']}"
        hs_id = str(rec["id"])
        seen = {k: _enc(v) for k, v in data.items() if k not in invalid}
        seen[STAGE_SEEN] = f"{ps[0]}:{ps[1]}"
        items.append({
            "hs_id": hs_id, "data": data, "invalid": invalid, "seen": seen,
            "pipeline_key": ps[0], "stage_key": ps[1],
            "raw": {k: v for k, v in props.items() if v not in (None, "")},
            "companies": (assoc or {}).get(("companies", hs_id)) if assoc is not None else _assoc(rec, "companies"),
            "contacts": (assoc or {}).get(("contacts", hs_id)) if assoc is not None else _assoc(rec, "contacts"),
            "created_at": _dt(props.get("createdate") or rec.get("createdAt")),
            "modified_at": _dt(props.get("hs_lastmodifieddate") or rec.get("updatedAt")),
        })
    return items


def resolve_links(cur, items: list[dict]) -> None:
    """company_id (Primary primero), contact_ids y el negocio existente (`existing`)."""
    co_ids = sorted({c for it in items for c, _ in it["companies"] or []})
    ct_ids = sorted({c for it in items for c, _ in it["contacts"] or []})
    by_co, by_ct = {}, {}
    if co_ids:
        cur.execute("SELECT id, hubspot_company_id FROM prospect_companies WHERE hubspot_company_id = ANY(%s) "
                    "AND NOT is_dummy ORDER BY id", (co_ids,))
        for r in cur.fetchall():
            by_co.setdefault(r["hubspot_company_id"], r["id"])
    if ct_ids:
        cur.execute("SELECT id, hubspot_contact_id FROM prospect_contacts WHERE hubspot_contact_id = ANY(%s) "
                    "AND NOT is_dummy ORDER BY id", (ct_ids,))
        for r in cur.fetchall():
            by_ct.setdefault(r["hubspot_contact_id"], r["id"])
    cur.execute("SELECT * FROM prospect_deals WHERE hubspot_deal_id = ANY(%s)", ([it["hs_id"] for it in items],))
    existing = {r["hubspot_deal_id"]: dict(r) for r in cur.fetchall()}
    for it in items:
        ordered = sorted(it["companies"] or [], key=lambda a: not a[1])
        it["company_id"] = next((by_co[c] for c, _ in ordered if c in by_co), None)
        it["contact_ids"] = [by_ct[c] for c, _ in it["contacts"] or [] if c in by_ct]
        it["existing"] = existing.get(it["hs_id"])


# --------------------------------------------------------------------------- #
# Importación masiva
# --------------------------------------------------------------------------- #
def import_batch(cur, items: list[dict], apply: bool, stats: Counter, sample: list) -> None:
    if not items:
        return
    resolve_links(cur, items)
    new = [it for it in items if it["existing"] is None]
    stats["nuevos"] += len(new)
    stats["ya_existían"] += len(items) - len(new)
    stats["nuevos_sin_empresa_en_el_hub"] += sum(1 for it in new if it["company_id"] is None)
    for it in new:
        stats[f"etapa: {it['pipeline_key']} / {it['stage_key']}"] += 1
    for it in new[:6]:
        if len(sample) < 12:
            sample.append({"negocio": it["data"].get("name"), "pipeline": it["pipeline_key"], "etapa": it["stage_key"],
                           "empresa": it["company_id"], "contactos": it["contact_ids"],
                           "datos": {k: v for k, v in it["data"].items() if v is not None}})
    if not apply or not new:
        return
    cols = list(DEAL_COLUMNS)
    tuples = []
    for it in new:
        d = it["data"]
        props = {k: v for k, v in d.items() if v is not None and k not in cols}
        tuples.append(tuple([it["pipeline_key"], it["stage_key"], it["company_id"]] + [d.get(c) for c in cols]) + (
            Json(props), IMPORT_SOURCE, it["created_at"], it["modified_at"] or it["created_at"], it["hs_id"],
            Json(it["seen"]), Json(it["raw"])))
    res = execute_values(
        cur,
        f"INSERT INTO prospect_deals (pipeline_key, stage_key, company_id, {', '.join(cols)}, props, created_by, "
        f"created_at, stage_entered_at, hubspot_deal_id, hubspot_seen, raw_payload) VALUES %s "
        f"ON CONFLICT (hubspot_deal_id) WHERE hubspot_deal_id IS NOT NULL DO NOTHING "
        f"RETURNING id, company_id, hubspot_deal_id, created_at",
        tuples,
        template="(" + ", ".join(["%s"] * (3 + len(cols))) + ", %s, %s, COALESCE(%s, NOW()), COALESCE(%s, NOW()), %s, %s, %s)",
        page_size=len(tuples),
        fetch=True,
    )
    rows = {r["hubspot_deal_id"]: dict(r) for r in res}
    if not rows:
        return
    execute_values(
        cur,
        "INSERT INTO prospect_company_events (company_id, actor, source, field, new_value, deal_id, at) VALUES %s",
        [(r["company_id"], None, IMPORT_SOURCE, None, "deal_created", r["id"], r["created_at"]) for r in rows.values()],
        page_size=max(1, len(rows)),
    )
    links = [(rows[it["hs_id"]]["id"], c) for it in new if it["hs_id"] in rows for c in sorted(set(it["contact_ids"]))]
    if links:
        execute_values(cur, "INSERT INTO prospect_deal_contacts (deal_id, contact_id) VALUES %s ON CONFLICT DO NOTHING",
                       links, page_size=len(links))
    D.reflect(cur, [r["id"] for r in rows.values()])


# --------------------------------------------------------------------------- #
# Sync incremental
# --------------------------------------------------------------------------- #
def _search_since(client: HubSpotClient, since: datetime, properties: list[str], pipeline_ids: list[str], after=None):
    filters = [{"propertyName": "hs_lastmodifieddate", "operator": "GTE", "value": str(int(since.timestamp() * 1000))}]
    if pipeline_ids:
        filters.append({"propertyName": "pipeline", "operator": "IN", "values": pipeline_ids})
    body = {
        "filterGroups": [{"filters": filters}],
        "sorts": [{"propertyName": "hs_lastmodifieddate", "direction": "ASCENDING"}],
        "properties": properties,
        "limit": 100,
    }
    if after:
        body["after"] = after
    payload = client._request("POST", "/crm/v3/objects/deals/search", json=body)
    nxt = ((payload.get("paging") or {}).get("next") or {}).get("after")
    return payload.get("results", []), nxt


def _sync_one(cur, it: dict, dry_run: bool) -> tuple[str, list]:
    ex = it["existing"]
    if ex is None:
        data = {k: v for k, v in it["data"].items() if v is not None}
        out = [{"field": k, "old": None, "new": v} for k, v in data.items()]
        if dry_run:
            return "created", out
        row = D.create_deal(cur, {**data, "pipeline_key": it["pipeline_key"], "stage_key": it["stage_key"],
                                  "company_id": it["company_id"], "contact_ids": it["contact_ids"]},
                            None, source=SYNC_SOURCE, check_required=False)
        cur.execute("UPDATE prospect_deals SET hubspot_deal_id = %s, hubspot_seen = %s, raw_payload = %s, "
                    "created_at = COALESCE(%s, created_at) WHERE id = %s",
                    (it["hs_id"], Json(it["seen"]), Json(it["raw"]), it["created_at"], row["id"]))
        it["deal_id"] = row["id"]
        return "created", out

    it["deal_id"] = ex["id"]
    before = D._flatten(ex)
    base = ex.get("hubspot_seen") if isinstance(ex.get("hubspot_seen"), dict) else None
    patch, new_seen = {}, dict(base or {})
    for k, v in it["data"].items():
        if k in it["invalid"]:
            continue
        hs, cur_v = _enc(v), _enc(before.get(k))
        if base is not None and k in base:
            if hs != base[k] and hs != cur_v:
                patch[k] = v
        elif cur_v is None and hs is not None:
            patch[k] = v
        new_seen[k] = hs
    stage_val = f"{it['pipeline_key']}:{it['stage_key']}"
    move = None
    if (base or {}).get(STAGE_SEEN) != stage_val and stage_val != f"{ex['pipeline_key']}:{ex['stage_key']}":
        move = (it["pipeline_key"], it["stage_key"])
        # Con oportunidad del hub, HubSpot no hace retroceder al negocio (la opp ya avanzó).
        if ex.get("opportunity_id") and it["pipeline_key"] == ex["pipeline_key"]:
            r_new, r_cur = D.rank(it["stage_key"]), D.rank(ex["stage_key"])
            if r_new is not None and r_cur is not None and r_new < r_cur:
                move = None
    new_seen[STAGE_SEEN] = stage_val
    gains_company = ex["company_id"] is None and it["company_id"] is not None
    cur.execute("SELECT contact_id FROM prospect_deal_contacts WHERE deal_id = %s", (ex["id"],))
    have = {r["contact_id"] for r in cur.fetchall()}
    add_contacts = [c for c in it["contact_ids"] if c not in have]
    out = [{"field": k, "old": before.get(k), "new": v} for k, v in patch.items()]
    if move:
        out.append({"field": "stage", "old": ex["stage_key"], "new": move[1]})
    if gains_company:
        out.append({"field": "company", "old": None, "new": it["company_id"]})
    if add_contacts:
        out.append({"field": "contacts", "old": None, "new": add_contacts})
    if dry_run:
        return ("updated" if out else "same"), out
    cur.execute("UPDATE prospect_deals SET hubspot_seen = %s, raw_payload = %s WHERE id = %s",
                (Json(new_seen), Json(it["raw"]), ex["id"]))
    if patch:
        D.update_deal(cur, ex["id"], patch, None, source=SYNC_SOURCE)
    if gains_company:
        D.set_company(cur, ex["id"], it["company_id"], None, source=SYNC_SOURCE)
    if add_contacts:
        D.set_contacts(cur, ex["id"], sorted(have | set(add_contacts)), None, source=SYNC_SOURCE)
    if move:
        D.move_stage(cur, ex["id"], move[1], None, source=SYNC_SOURCE, check_required=False, pipeline_key=move[0])
    return ("updated" if out else "same"), out


def sync(conn, client: HubSpotClient | None = None, *, dry_run: bool = False, max_deals: int = 2000,
         time_budget: float = 200.0, since: datetime | None = None, log=None) -> dict:
    client = client or HubSpotClient()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    store.ensure_schema(cur)
    cur.execute("SELECT pg_try_advisory_lock(%s) AS got", (SYNC_LOCK_KEY,))
    if not cur.fetchone()["got"]:
        conn.rollback()
        return {"status": "busy", "error": "Otra corrida del sync de negocios está en curso."}
    t0 = _time.time()
    stats, notes = Counter(), Counter()
    sample, errors = [], []
    status = "ok"
    try:
        stages = D.seed_stages_from_hubspot(cur, client)
        conn.commit()
        cur.execute("SELECT DISTINCT hubspot_pipeline_id FROM prospect_deal_stages WHERE hubspot_pipeline_id IS NOT NULL")
        pipeline_ids = [r["hubspot_pipeline_id"] for r in cur.fetchall()]
        mapping = load_mapping(cur, client)
        properties = mapping.properties()
        watermark = _read_watermark(cur, SYNC_KEY)
        conn.commit()
        start = since or ((watermark - OVERLAP) if watermark else BOOTSTRAP)
        lower, after, processed, last_ts = start, None, 0, watermark
        seen_ids: set[str] = set()
        while processed < max_deals:
            if _time.time() - t0 > time_budget:
                status = "partial"
                break
            results, nxt = _search_since(client, lower, properties, pipeline_ids, after)
            if not results:
                break
            recs = [r for r in results if str(r["id"]) not in seen_ids]
            seen_ids.update(str(r["id"]) for r in results)
            assoc = {}
            if recs:
                ids = [r["id"] for r in recs]
                for kind in ("companies", "contacts"):
                    for did, lst in client.batch_associations("deals", kind, ids).items():
                        assoc[(kind, did)] = lst
            items = build_items(cur, recs, mapping, assoc, notes, stats)
            _sync_page(cur, items, dry_run, stats, sample, errors)
            processed += len(results)
            page_ts = max((_dt((r.get("properties") or {}).get("hs_lastmodifieddate")) for r in results
                           if (r.get("properties") or {}).get("hs_lastmodifieddate")), default=None)
            if not dry_run:
                if not errors and page_ts and (last_ts is None or page_ts > last_ts):
                    last_ts = page_ts
                _write_state(cur, last_ts, "running", {"stats": dict(stats)}, SYNC_KEY)
                conn.commit()
            if log:
                log(f"  {processed} leídos · {dict(stats)}")
            if not nxt:
                break
            if int(nxt) >= SEARCH_AFTER_CAP and page_ts:
                lower, after = page_ts, None
            else:
                after = nxt
        else:
            status = "partial"
        # Oportunidades del hub -> negocios (todas: una opp se mueve sin tocar HubSpot).
        if not dry_run:
            r = D.reflect(cur, values=True)
            stats["atados_a_su_oportunidad"] += r["linked"]
            stats["etapa_desde_la_oportunidad"] += r["moved"]
            stats["campos_de_cierre_desde_la_oportunidad"] += r["copied"]
        report = {
            "status": status, "dry_run": dry_run, "since": start.isoformat(),
            "watermark": last_ts.isoformat() if last_ts else None, "read": processed,
            "seconds": round(_time.time() - t0, 1), "stats": dict(stats), "pipelines": stages["pipelines"],
            "avisos": dict(notes.most_common(30)), "sample": sample, "errors": errors[:50],
        }
        if not dry_run:
            _write_state(cur, None, "error" if errors else status, report, SYNC_KEY)
            conn.commit()
        else:
            conn.rollback()
        return report
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            cur.execute("SELECT pg_advisory_unlock(%s)", (SYNC_LOCK_KEY,))
            conn.commit()
        except Exception:
            conn.rollback()


def _sync_page(cur, items: list[dict], dry_run: bool, stats: Counter, sample: list, errors: list) -> None:
    if not items:
        return
    resolve_links(cur, items)
    for it in items:
        cur.execute("SAVEPOINT hs_deal")
        try:
            kind, changes = _sync_one(cur, it, dry_run)
            cur.execute("RELEASE SAVEPOINT hs_deal")
        except Exception as exc:  # un negocio roto no frena el lote
            cur.execute("ROLLBACK TO SAVEPOINT hs_deal")
            errors.append({"hubspot_deal_id": it["hs_id"], "negocio": it["data"].get("name"), "error": str(exc)[:300]})
            stats["errores"] += 1
            continue
        stats[{"created": "creados", "updated": "actualizados", "same": "sin_cambios"}[kind]] += 1
        if kind in ("created", "updated") and len(sample) < 25:
            sample.append({"negocio": it["data"].get("name"), "accion": kind,
                           "cambios": [{"campo": c["field"], "antes": _enc(c["old"]) if not isinstance(c["old"], list) else c["old"],
                                        "ahora": _enc(c["new"]) if not isinstance(c["new"], list) else c["new"]}
                                       for c in changes][:12]})
    if not dry_run:
        ids = [it["deal_id"] for it in items if it.get("deal_id")]
        D.reflect(cur, ids)


def last_report(cur) -> dict | None:
    from prospecting.hubspot_companies import last_report as _lr
    return _lr(cur, SYNC_KEY)
