"""Contactos de HubSpot -> Prospecting: mapeo, empresa de cada contacto, importación en
lote y sync incremental. Espejo de `hubspot_companies.py` (y reusa su OwnerResolver,
la foto `hubspot_seen` y la marca de agua).

Lo usan `scripts/import_hubspot_contacts.py` (importación masiva) y
`POST /prospecting/hubspot/sync-contacts` (cron cada 30 min, después del de empresas).
Sólo HubSpot -> Hub (decisión de la owner, 2026-11-04).

Empresa de cada contacto, en este orden:
  1. La asociación de HubSpot (la Primary si hay varias) -> la empresa del Hub con ese
     `hubspot_company_id`.
  2. El dominio del mail (nunca gmail/hotmail…) de UNA sola empresa del Hub.
  3. Si no: contacto SIN empresa (desde el 2026-11-04 un contacto puede no tener
     empresa, como en HubSpot; antes iba a la bandeja «Unassigned»). Se le asocia sola
     cuando llega una empresa con su dominio (`store.attach_contacts_for_company`) o
     cuando en HubSpot le asocian una que ya está en el Hub.
"""
from __future__ import annotations

import time as _time
from collections import Counter
from datetime import datetime

from psycopg2.extras import Json, RealDictCursor, execute_values

from prospecting import engine, inbound, store
from prospecting.contact_fields import CONTACT_FIELDS, CONTACT_FIELDS_BY_KEY
from prospecting.hubspot_companies import (
    BOOTSTRAP,
    OVERLAP,
    SEARCH_AFTER_CAP,
    OwnerResolver,
    _enc,
    _read_watermark,
    _write_state,
)
from prospecting.rules import has_conditions
from utils.hubspot import HubSpotClient

IMPORT_SOURCE = "hubspot_import"
SYNC_SOURCE = "hubspot_sync"
SYNC_KEY = "prospect_contacts"
SYNC_LOCK_KEY = 72_026_110_5

# Propiedades nativas de HubSpot -> campo del Hub (van antes que el match por label).
NATIVE = {
    "email": ["email"],
    "first_name": ["firstname"],
    "last_name": ["lastname"],
    "owner_email": ["hubspot_owner_id"],
    "phone_number": ["phone", "mobilephone"],
    "linkedin_url": ["hs_linkedin_url"],
    "company_name": ["company"],
    "state_region": ["state"],
}
ALWAYS = ["email", "firstname", "lastname", "createdate", "lastmodifieddate"]
_PERSON_TYPES = ("owner", "user")


# --------------------------------------------------------------------------- #
# Mapeo
# --------------------------------------------------------------------------- #
class ContactMapping:
    """Qué propiedad de HubSpot alimenta cada campo de `contact_fields.py`, y cómo se
    traduce el valor (opción interna -> label, `a;b` -> lista, owner id -> email)."""

    def __init__(self, props: list[dict], owners: dict, bdrs: list[dict], users: list[dict]):
        self.meta = {p["name"]: p for p in props}
        by_norm: dict[str, str] = {}
        for p in props:
            for k in (p.get("name"), p.get("label")):
                if k:
                    by_norm.setdefault(store._norm_key(k), p["name"])
        self.fields: dict[str, list[str]] = {}
        taken: set[str] = set()
        for f in CONTACT_FIELDS:
            key = f["key"]
            cands = [p for p in NATIVE.get(key, []) if p in self.meta]
            for k in (key, f["label"]):
                p = by_norm.get(store._norm_key(k))
                if p and p not in cands and p != "hs_object_id":
                    cands.append(p)
            cands = [p for p in cands if p not in taken]
            if cands:
                self.fields[key] = cands
                taken.update(cands)
        self._owners = owners
        self._resolvers: dict[tuple, OwnerResolver] = {}
        self._bdrs, self._users = bdrs, users
        # Propiedades tipo `user` (Scheduled By…) de gente que ya no está en el Hub: se
        # guarda el email del owner de HubSpot y su nombre va a prospect_people.
        self.fallback_people: dict[str, str | None] = {}

    def properties(self) -> list[str]:
        return sorted({p for pl in self.fields.values() for p in pl} | set(ALWAYS))

    def _resolver(self, prop: str, kind: str) -> OwnerResolver:
        k = (prop, kind)
        if k not in self._resolvers:
            people = self._bdrs if kind == "owner" else self._users
            self._resolvers[k] = OwnerResolver(self.meta.get(prop) or {"name": prop}, self._owners, people)
        return self._resolvers[k]

    def _translate(self, prop: str, raw):
        """Valor de HubSpot -> lo que espera el Hub (sin validar todavía)."""
        meta = self.meta.get(prop) or {}
        opts = {str(o.get("value")): o.get("label") for o in meta.get("options") or []}
        if meta.get("type") == "enumeration" and opts and meta.get("fieldType") != "booleancheckbox":
            parts = [p for p in str(raw).split(";") if p != ""]
            labels = [opts.get(p, p) for p in parts]
            return labels if meta.get("fieldType") == "checkbox" or len(labels) > 1 else (labels[0] if labels else None)
        return raw

    def map(self, rec: dict) -> tuple[dict, set, Counter]:
        """(datos por campo del Hub, campos con valor intraducible, avisos)."""
        props = rec.get("properties") or {}
        data, invalid, notes = {}, set(), Counter()
        for key, plist in self.fields.items():
            prop = next((p for p in plist if props.get(p) not in (None, "")), None)
            if prop is None:
                data[key] = None
                continue
            f = CONTACT_FIELDS_BY_KEY[key]
            raw = props[prop]
            if f["type"] in _PERSON_TYPES:
                resolver = self._resolver(prop, f["type"])
                email, why = resolver.resolve(raw)
                if not email and f["type"] == "user":
                    # Histórico (2026-11-06): Scheduled By de alguien que se fue sigue
                    # siendo quién agendó. Sólo `user`; Contact Owner exige un BDR activo.
                    hs_email, hs_name = resolver.describe(store._clean_text(raw) or "")
                    if hs_email and "@" in hs_email:
                        email = hs_email
                        self.fallback_people.setdefault(hs_email, hs_name)
                if not email:
                    invalid.add(key)
                    notes[f"{f['label']}: «{raw}» {why}"] += 1
                    continue
                val = email
            else:
                val = self._translate(prop, raw)
                if f["type"] != "multi" and isinstance(val, list):
                    val = "; ".join(str(x) for x in val)
            try:
                data[key] = store.clean_contact_value(f, val)
            except ValueError as exc:
                invalid.add(key)
                notes[str(exc)[:120]] += 1
        return data, invalid, notes


def load_mapping(cur, client: HubSpotClient) -> ContactMapping:
    return ContactMapping(client.get_properties("contacts"), client.list_owners(),
                          store.list_bdrs(cur), store.list_users(cur))


def seen_of(data: dict, invalid: set) -> dict:
    return {k: _enc(v if not isinstance(v, list) else ";".join(map(str, v)))
            for k, v in data.items() if k not in invalid}


def _enc_any(v):
    return _enc(";".join(map(str, v)) if isinstance(v, list) else v)


def created_at_of(rec: dict):
    v = (rec.get("properties") or {}).get("createdate") or rec.get("createdAt")
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None


def modified_at_of(rec: dict):
    v = (rec.get("properties") or {}).get("lastmodifieddate") or rec.get("updatedAt")
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None


def associations_of_record(rec: dict) -> list[tuple[str, bool]]:
    """Asociaciones que trae el GET de lista (`associations=companies`)."""
    res = (((rec.get("associations") or {}).get("companies") or {}).get("results")) or []
    return [(str(a.get("id")), (a.get("type") or "") == "contact_to_company") for a in res if a.get("id")]


# --------------------------------------------------------------------------- #
# Empresa de cada contacto
# --------------------------------------------------------------------------- #
def resolve_companies(cur, items: list[dict]) -> None:
    """Completa `company_id` (o `reason` si va a la bandeja) en cada item.
    item = {"email", "assoc": [(hs_company_id, primaria)]}."""
    hs_ids = sorted({c for it in items for c, _ in it["assoc"]})
    by_hs = {}
    if hs_ids:
        cur.execute(
            "SELECT id, hubspot_company_id FROM prospect_companies "
            "WHERE hubspot_company_id = ANY(%s) AND NOT is_dummy ORDER BY id",
            (hs_ids,),
        )
        for r in cur.fetchall():
            by_hs.setdefault(r["hubspot_company_id"], r["id"])
    for it in items:
        ordered = sorted(it["assoc"], key=lambda a: not a[1])  # la Primary primero
        it["company_id"] = next((by_hs[c] for c, _ in ordered if c in by_hs), None)
        it["domain"] = inbound.company_domain(it.get("email"), None)
    domains = sorted({it["domain"] for it in items if it["company_id"] is None and it["domain"]})
    by_dom: dict[str, list] = {}
    if domains:
        cur.execute(
            "SELECT domain, MIN(id) AS id, COUNT(*) AS n FROM prospect_companies "
            "WHERE domain = ANY(%s) AND NOT is_dummy GROUP BY domain",
            (domains,),
        )
        by_dom = {r["domain"]: [r["id"], r["n"]] for r in cur.fetchall()}
    for it in items:
        if it["company_id"] is not None:
            it["reason"] = "hubspot_association"
            continue
        if not it["domain"]:
            it["reason"] = "free_email"
            continue
        hit = by_dom.get(it["domain"])
        if hit and hit[1] == 1:
            it["company_id"], it["reason"] = hit[0], "domain_match"
        else:
            it["reason"] = "multiple_companies" if hit else "no_company"


# --------------------------------------------------------------------------- #
# Escrituras compartidas
# --------------------------------------------------------------------------- #
def find_existing(cur, items: list[dict]) -> None:
    """`existing` = fila de prospect_contacts por id de HubSpot, si no por email;
    `waiting` = fila pendiente de la bandeja con ese id de HubSpot."""
    ids = [it["hs_id"] for it in items]
    cur.execute("SELECT * FROM prospect_contacts WHERE hubspot_contact_id = ANY(%s) AND NOT is_dummy", (ids,))
    by_id = {r["hubspot_contact_id"]: dict(r) for r in cur.fetchall()}
    emails = sorted({it["email"].lower() for it in items if it.get("email") and it["hs_id"] not in by_id})
    by_email = {}
    if emails:
        cur.execute(
            "SELECT * FROM prospect_contacts WHERE LOWER(email) = ANY(%s) AND NOT is_dummy ORDER BY id",
            (emails,),
        )
        for r in cur.fetchall():
            by_email.setdefault(r["email"].lower(), dict(r))
    cur.execute(
        "SELECT * FROM prospect_inbound_contacts WHERE hubspot_contact_id = ANY(%s) AND status = 'pending'",
        (ids,),
    )
    waiting = {r["hubspot_contact_id"]: dict(r) for r in cur.fetchall()}
    for it in items:
        ex = by_id.get(it["hs_id"])
        if ex is None and it.get("email"):
            ex = by_email.get(it["email"].lower())
            if ex is not None and ex.get("hubspot_contact_id") and ex["hubspot_contact_id"] != it["hs_id"]:
                ex = None  # ese mail ya es otro contacto de HubSpot
        it["existing"] = ex
        it["waiting"] = waiting.get(it["hs_id"])


def drop_deleted(cur, items: list[dict], stats: Counter) -> list[dict]:
    """Saca los contactos NUEVOS que alguien eliminó en el Hub (prospect_deleted_records):
    si no, el sync los volvería a crear cada vez que HubSpot los toque."""
    blocked = store.deleted_hubspot_ids(cur, "contact", [it["hs_id"] for it in items if it["existing"] is None])
    if blocked:
        stats["eliminado en el Hub (no se recrea)"] += sum(1 for it in items if it["hs_id"] in blocked)
    return [it for it in items if it["existing"] is not None or it["hs_id"] not in blocked]


def _resolve_waiting(cur, it: dict, contact_id: int, company_id) -> None:
    """La fila que esperaba en la bandeja (de antes de los contactos sin empresa) queda
    resuelta: el contacto ya existe."""
    if it.get("waiting"):
        inbound._resolve(cur, it["waiting"]["id"], contact_id, company_id, SYNC_SOURCE)


def build_items(recs: list[dict], mapping: ContactMapping, assoc: dict | None, notes: Counter) -> list[dict]:
    items = []
    for rec in recs:
        data, invalid, n = mapping.map(rec)
        notes.update(n)
        props = rec.get("properties") or {}
        hs_id = str(rec["id"])
        items.append({
            "hs_id": hs_id, "data": data, "invalid": invalid, "seen": seen_of(data, invalid),
            "email": data.get("email"), "raw": {k: v for k, v in props.items() if v not in (None, "")},
            "assoc": assoc.get(hs_id, []) if assoc is not None else associations_of_record(rec),
            "created_at": created_at_of(rec), "modified_at": modified_at_of(rec),
        })
    return items


def shield(cur, contact_ids: list[int], stats: Counter) -> None:
    """Workflows de contacto por condiciones: los recién importados que YA cumplen quedan
    como "ya cumplía" (no se inscriben en masa). Igual que Importer.shield() de empresas."""
    if not contact_ids:
        return
    now = engine.utcnow()
    mine = set(contact_ids)
    for wf in engine.enabled_workflows(cur):
        if engine.obj_of(wf) != "contact" or wf["trigger"].get("type") != "filter":
            continue
        if not has_conditions(wf["trigger"].get("conditions")):
            continue
        hits = engine.matching_ids(cur, wf["trigger"]["conditions"], now, False, None, "contact",
                                   contact_ids=sorted(mine))
        if hits:
            execute_values(
                cur,
                """
                INSERT INTO prospect_wf_match (workflow_id, record_id, matching, changed_at) VALUES %s
                ON CONFLICT (workflow_id, record_id) DO UPDATE SET matching = TRUE, changed_at = EXCLUDED.changed_at
                """,
                [(wf["id"], h, True, now) for h in hits],
                page_size=len(hits),
            )
            stats[f"blindados en workflow #{wf['id']}"] += len(hits)


# --------------------------------------------------------------------------- #
# Importación masiva (la usa scripts/import_hubspot_contacts.py)
# --------------------------------------------------------------------------- #
def import_batch(cur, items: list[dict], apply: bool, stats: Counter, sample: list) -> None:
    """Lote de la importación: en lote, sin disparar workflows (los que ya cumplen quedan
    blindados). Sin empresa -> contacto sin empresa. Contacto existente -> sólo rellena
    vacíos (y si no tenía empresa y ahora hay una, se le asigna)."""
    if not items:
        return
    resolve_companies(cur, items)
    find_existing(cur, items)
    items = drop_deleted(cur, items, stats)
    new = [it for it in items if it["existing"] is None]
    fills = [it for it in items if it["existing"] is not None]
    stats["nuevos_con_empresa"] += sum(1 for it in new if it["company_id"] is not None)
    stats["nuevos_sin_empresa"] += sum(1 for it in new if it["company_id"] is None)
    stats["ya_existian"] += len(fills)
    for it in new:
        stats[f"empresa por: {it['reason']}"] += 1
    for it in new[:8]:
        if len(sample) < 12:
            sample.append({"email": it["email"], "empresa": it["company_id"], "por": it["reason"],
                           "datos": {k: v for k, v in it["data"].items() if v is not None}})
    if not apply:
        return

    from prospecting.contact_fields import CONTACT_COLUMNS
    cols = list(CONTACT_COLUMNS)
    new_ids: list[int] = []
    if new:
        tuples = []
        for it in new:
            d = it["data"]
            props = {k: v for k, v in d.items() if v is not None and k not in cols}
            tuples.append(tuple([it["company_id"]] + [d.get(c) for c in cols]) + (
                Json(props), IMPORT_SOURCE, it.get("created_at"), it["hs_id"], Json(it["seen"]), Json(it["raw"])))
        res = execute_values(
            cur,
            f"INSERT INTO prospect_contacts (company_id, {', '.join(cols)}, props, created_by, created_at, "
            f"hubspot_contact_id, hubspot_seen, raw_payload) VALUES %s RETURNING id, company_id, hubspot_contact_id",
            tuples,
            template="(" + ", ".join(["%s"] * (1 + len(cols))) + ", %s, %s, COALESCE(%s, NOW()), %s, %s, %s)",
            page_size=len(tuples),
            fetch=True,
        )
        rows = [dict(r) for r in res]
        new_ids = [r["id"] for r in rows]
        execute_values(
            cur,
            "INSERT INTO prospect_company_events (company_id, actor, source, field, new_value, contact_id) VALUES %s",
            [(r["company_id"], None, IMPORT_SOURCE, None, "contact_created", r["id"]) for r in rows],
            page_size=len(rows),
        )
        by_hs = {r["hubspot_contact_id"]: r["id"] for r in rows}
        for it in new:
            if it.get("waiting") and it["hs_id"] in by_hs:
                _resolve_waiting(cur, it, by_hs[it["hs_id"]], it["company_id"])
        companies = sorted({r["company_id"] for r in rows if r["company_id"] is not None})
        if companies:
            # Contacto principal: el primero de cada empresa que no tenía ninguno.
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
            # «Completá el contacto» sólo importa en empresas Qualified / SQL.
            cur.execute(
                "SELECT id, prospecting_status FROM prospect_companies WHERE id = ANY(%s) "
                "AND prospecting_status IN ('Qualified', 'SQL')",
                (companies,),
            )
            for r in cur.fetchall():
                store.recompute_contact_incomplete(cur, r["id"], status=r["prospecting_status"])

    filled_ids = []
    for it in fills:
        ex = it["existing"]
        before = store._flatten_contact(ex)
        patch = {k: v for k, v in it["data"].items()
                 if v is not None and k != "email" and before.get(k) in (None, "", [])}
        cur.execute(
            "UPDATE prospect_contacts SET hubspot_contact_id = COALESCE(hubspot_contact_id, %s), "
            "hubspot_seen = COALESCE(hubspot_seen, %s), raw_payload = COALESCE(raw_payload, %s) WHERE id = %s",
            (it["hs_id"], Json(it["seen"]), Json(it["raw"]), ex["id"]),
        )
        touched = False
        if patch:
            store.update_contact(cur, ex["id"], patch, None, source=IMPORT_SOURCE)
            touched = True
        if ex["company_id"] is None and it["company_id"] is not None:
            store.set_contact_company(cur, ex["id"], it["company_id"], None, source=IMPORT_SOURCE)
            stats["sin_empresa_que_ganaron_empresa"] += 1
            touched = True
        if touched:
            filled_ids.append(ex["id"])

    shield(cur, new_ids + filled_ids, stats)


# --------------------------------------------------------------------------- #
# Sync incremental (cron cada 30 min)
# --------------------------------------------------------------------------- #
def _search_since(client: HubSpotClient, since: datetime, properties: list[str], after=None):
    body = {
        "filterGroups": [{"filters": [{
            "propertyName": "lastmodifieddate", "operator": "GTE",
            "value": str(int(since.timestamp() * 1000)),
        }]}],
        "sorts": [{"propertyName": "lastmodifieddate", "direction": "ASCENDING"}],
        "properties": properties,
        "limit": 100,
    }
    if after:
        body["after"] = after
    payload = client._request("POST", "/crm/v3/objects/contacts/search", json=body)
    nxt = ((payload.get("paging") or {}).get("next") or {}).get("after")
    return payload.get("results", []), nxt


def _sync_one(cur, it: dict, dry_run: bool) -> tuple[str, dict | None, list]:
    """('created' | 'updated' | 'same', contacto, cambios). HubSpot gana sólo cuando su
    valor cambió respecto de la foto; si no, gana el Hub. Sin empresa = contacto sin empresa."""
    ex = it["existing"]
    if ex is None:
        data = {k: v for k, v in it["data"].items() if v is not None}
        if dry_run:
            return "created", None, [{"field": k, "old": None, "new": v} for k, v in data.items()]
        created = store.create_contact(cur, it["company_id"], data, None, source=SYNC_SOURCE)
        cur.execute(
            "UPDATE prospect_contacts SET hubspot_contact_id = %s, hubspot_seen = %s, raw_payload = %s WHERE id = %s",
            (it["hs_id"], Json(it["seen"]), Json(it["raw"]), created["id"]),
        )
        _resolve_waiting(cur, it, created["id"], it["company_id"])
        return "created", created, created.pop("_changes")

    before = store._flatten_contact(ex)
    base = ex.get("hubspot_seen") if isinstance(ex.get("hubspot_seen"), dict) else None
    patch, new_seen = {}, dict(base or {})
    for k, v in it["data"].items():
        if k in it["invalid"] or k == "email" and v is None:
            continue
        hs, cur_v = _enc_any(v), _enc_any(before.get(k))
        if base is not None and k in base:
            if hs != base[k] and hs != cur_v:
                patch[k] = v
        elif cur_v is None and hs is not None:
            patch[k] = v
        new_seen[k] = hs
    gains_company = ex["company_id"] is None and it["company_id"] is not None
    if dry_run:
        out = [{"field": k, "old": before.get(k), "new": v} for k, v in patch.items()]
        if gains_company:
            out.append({"field": "company", "old": None, "new": it["company_id"]})
        return ("updated" if out else "same"), ex, out
    cur.execute(
        "UPDATE prospect_contacts SET hubspot_contact_id = COALESCE(hubspot_contact_id, %s), "
        "hubspot_seen = %s, raw_payload = %s WHERE id = %s",
        (it["hs_id"], Json(new_seen), Json(it["raw"]), ex["id"]),
    )
    changes = []
    if gains_company:
        # Un contacto sin empresa al que en HubSpot le asociaron una (o cuyo dominio ya es de
        # una sola empresa): se le asigna. Uno que ya tiene empresa no se mueve.
        store.set_contact_company(cur, ex["id"], it["company_id"], None, source=SYNC_SOURCE)
        changes.append({"field": "company", "old": None, "new": it["company_id"]})
    if patch:
        upd = store.update_contact(cur, ex["id"], patch, None, source=SYNC_SOURCE)
        changes += upd.pop("_changes", [])
    if not changes:
        return "same", ex, []
    cur.execute("SELECT id, company_id FROM prospect_contacts WHERE id = %s", (ex["id"],))
    return "updated", dict(cur.fetchone()), changes


def sync(conn, client: HubSpotClient | None = None, *, dry_run: bool = False,
         max_contacts: int = 2000, time_budget: float = 200.0, since: datetime | None = None,
         log=None) -> dict:
    """Trae de HubSpot los contactos modificados desde la marca y los aplica. Commit por
    página; la marca avanza a la última `lastmodifieddate` procesada (se congela si hubo
    errores). Los cambios disparan workflows (emit_event + un tick por página)."""
    client = client or HubSpotClient()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    store.ensure_schema(cur)
    cur.execute("SELECT pg_try_advisory_lock(%s) AS got", (SYNC_LOCK_KEY,))
    if not cur.fetchone()["got"]:
        conn.rollback()
        return {"status": "busy", "error": "Otra corrida del sync de contactos está en curso."}
    t0 = _time.time()
    stats, notes = Counter(), Counter()
    sample, errors = [], []
    status = "ok"
    try:
        mapping = load_mapping(cur, client)
        properties = mapping.properties()
        watermark = _read_watermark(cur, SYNC_KEY)
        conn.commit()
        start = since or ((watermark - OVERLAP) if watermark else BOOTSTRAP)
        lower, after, processed, last_ts = start, None, 0, watermark
        seen_ids: set[str] = set()
        while processed < max_contacts:
            if _time.time() - t0 > time_budget:
                status = "partial"
                break
            results, nxt = _search_since(client, lower, properties, after)
            if not results:
                break
            recs = [r for r in results if str(r["id"]) not in seen_ids]
            seen_ids.update(str(r["id"]) for r in results)
            assoc = client.contact_company_associations([r["id"] for r in recs]) if recs else {}
            items = build_items(recs, mapping, assoc, notes)
            _sync_page(cur, items, dry_run, stats, sample, errors)
            if not dry_run and mapping.fallback_people:
                store.remember_people(cur, mapping.fallback_people, "hubspot")
            processed += len(results)
            page_ts = max((it["modified_at"] for it in items if it["modified_at"]), default=None)
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
        report = {
            "status": status, "dry_run": dry_run, "since": start.isoformat(),
            "watermark": last_ts.isoformat() if last_ts else None, "read": processed,
            "seconds": round(_time.time() - t0, 1), "stats": dict(stats),
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
    resolve_companies(cur, items)
    find_existing(cur, items)
    items = drop_deleted(cur, items, stats)
    now = engine.utcnow()
    companies: set[int] = set()
    orphans: set[int] = set()
    for it in items:
        ex = it["existing"]
        if ex is not None and ex["company_id"] is not None and it["company_id"] \
                and it["company_id"] != ex["company_id"] and it["reason"] == "hubspot_association":
            stats["cambió_de_empresa_en_hubspot (no se mueve)"] += 1
        cur.execute("SAVEPOINT hs_contact")
        try:
            kind, out, changes = _sync_one(cur, it, dry_run)
            if not dry_run and out is not None and kind in ("created", "updated"):
                engine.emit_event(cur, "contact", out["id"], kind, changes, now, SYNC_SOURCE)
                if out.get("company_id") is None:
                    orphans.add(out["id"])
                else:
                    companies.add(out["company_id"])
            cur.execute("RELEASE SAVEPOINT hs_contact")
        except Exception as exc:  # un contacto roto no frena el lote
            cur.execute("ROLLBACK TO SAVEPOINT hs_contact")
            errors.append({"hubspot_contact_id": it["hs_id"], "email": it["email"], "error": str(exc)[:300]})
            stats["errores"] += 1
            continue
        stats[{"created": "creados", "updated": "actualizados", "same": "sin_cambios"}[kind]] += 1
        if kind == "created" and it["company_id"] is None:
            stats["creados_sin_empresa"] += 1
        if kind in ("created", "updated") and len(sample) < 25:
            sample.append({"email": it["email"], "accion": kind,
                           "cambios": [{"campo": c["field"], "antes": _enc_any(c["old"]), "ahora": _enc_any(c["new"])}
                                       for c in changes][:12]})
    if companies or orphans:
        res = engine.tick(cur, now, automatic=True, company_id=sorted(companies) or None, actor=SYNC_SOURCE,
                          contact_ids=sorted(orphans) or None)
        stats["inscripciones_en_workflows"] += int(res.get("enrolled") or 0)
