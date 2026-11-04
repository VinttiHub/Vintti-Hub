"""Empresas de HubSpot -> Prospecting: el mapeo (una sola definición) y el sync incremental.

Lo usan `scripts/import_hubspot_companies.py` (importación masiva, auditoría y reparación
de owners) y `POST /prospecting/hubspot/sync` (cron cada 30 min). Ver CLAUDE.md,
sección Prospecting.

Dirección: SÓLO HubSpot -> Hub (decisión de la owner, 2026-11-04). El Hub no escribe en
HubSpot.
"""
from __future__ import annotations

import json
import time as _time
from collections import Counter
from datetime import datetime, timedelta, timezone

from psycopg2.extras import Json, RealDictCursor

from prospecting import engine, inbound, store
from prospecting.constants import NOT_ICP_REASONS, SIZES, STATUSES
from utils.hubspot import HubSpotClient

# Propiedades nativas de HubSpot -> columna (prioridad sobre los alias de Clay).
NATIVE = {
    "name": ["name"],
    "website": ["website", "domain"],
    "linkedin_url": ["linkedin_company_page"],
    "description": ["description"],
    "industry": ["industry"],
    "city": ["city"],
    "state": ["state"],
    "country": ["country"],
    "founded_year": ["founded_year"],
    "size": ["numberofemployees"],
}
# Columnas que no se mapean desde HubSpot (o que se resuelven aparte).
SKIP_COLS = {"clay_record_id", "hubspot_company_id", "prospecting_owner_id", "prospecting_owner_email"}
# Owner = "Prospecting Owner (HubSpot)" (el "PO HubSpot"). En el Hub hay un solo
# Prospecting Owner y es ése. NUNCA `hubspot_owner_id` (el dueño del registro, otra cosa):
# la primera corrida (2026-11-03) podía caer ahí o en otra "Prospecting Owner" y Valeria
# Arias, BDR activa, quedó sin sus empresas. Orden de preferencia por nombre/label normalizado.
OWNER_PREFERRED = ["prospecting_owner_hubspot", "po_hubspot", "prospecting_owner"]
ALWAYS = ["name", "domain", "website", "createdate", "hubspot_owner_id"]


def owner_property_candidates(props: list[dict]) -> list[dict]:
    """Propiedades de empresa que pueden ser el PO: nombre/label con prospect+owner, o "PO"."""
    out = []
    for p in props:
        keys = {store._norm_key(p.get("name") or ""), store._norm_key(p.get("label") or "")}
        if any(("prospect" in k and "owner" in k) or k.startswith("po_") or k == "po" for k in keys):
            out.append(p)
    return out


def pick_owner_property(props: list[dict], forced: str | None = None) -> dict:
    if forced:
        for p in props:
            if p["name"] == forced:
                return p
        raise ValueError(f"--owner-prop {forced}: no existe esa propiedad de empresa en HubSpot.")
    cands = owner_property_candidates(props)
    for pref in OWNER_PREFERRED:
        for p in cands:
            if pref in (store._norm_key(p["name"]), store._norm_key(p.get("label") or "")):
                return p
    listing = ", ".join(f"{p['name']} («{p.get('label')}»)" for p in cands) or "ninguna"
    raise ValueError(f"No encontré «Prospecting Owner (HubSpot)». Candidatas: {listing}. Usá --owner-prop.")


class OwnerResolver:
    """Valor del PO en HubSpot -> email de un BDR activo del Hub.

    El valor puede ser un owner id / user id (propiedad de tipo usuario), un email, o un
    texto / opción de desplegable con el nombre. Se cruza por email y, si no, por nombre
    completo contra `users.user_name`: el mail del owner en HubSpot no siempre es el
    `email_vintti` del Hub."""

    def __init__(self, prop: dict, owners: dict, bdrs: list[dict]):
        self.prop = prop
        self.owners = owners
        self.options = {str(o.get("value")): o.get("label") for o in prop.get("options") or []}
        self.by_email = {b["email"]: b["email"] for b in bdrs if b.get("email")}
        self.by_name: dict[str, str | None] = {}
        for b in bdrs:
            k = store._norm_key(b.get("name") or "")
            if k:
                # Nombre repetido entre BDRs = ambiguo: no se adivina.
                self.by_name[k] = None if k in self.by_name else b["email"]
        self.bdr_names = {b["email"]: b.get("name") for b in bdrs}

    def describe(self, raw: str) -> tuple[str | None, str | None]:
        """(email, nombre) que HubSpot tiene para ese valor."""
        if "@" in raw:
            return raw.lower(), None
        o = self.owners.get(raw)
        if o:
            return o.get("email"), o.get("name")
        return None, self.options.get(raw) or raw

    def _by_name(self, name: str | None) -> str | None:
        k = store._norm_key(name or "")
        if not k:
            return None
        if self.by_name.get(k):
            return self.by_name[k]
        # "Valeria Arias" vs "Valeria Arias Gómez": todas las palabras de HubSpot en el
        # nombre del Hub, y una sola BDR que cumpla.
        toks = set(k.split("_"))
        hits = {e for n, e in self.by_name.items() if e and toks <= set(n.split("_"))}
        return hits.pop() if len(hits) == 1 else None

    def resolve(self, raw) -> tuple[str | None, str]:
        """(email del BDR o None, motivo)."""
        raw = store._clean_text(raw)
        if not raw:
            return None, "vacío"
        email, name = self.describe(raw)
        if email and email in self.by_email:
            return email, "email"
        hit = self._by_name(name)
        if hit:
            return hit, "nombre"
        return None, "sin BDR activo que coincida"


def resolve_mapping(client: HubSpotClient, forced_owner: str | None = None) -> tuple[dict, dict, list]:
    """{columna: [propiedades de HubSpot en orden]} + propiedad de owner.

    Los alias de Clay (`store._ALIASES`) ya traen los nombres de la planilla de
    propiedades de HubSpot, así que se reusan: se compara contra el nombre interno y
    el label normalizados."""
    props = client.get_properties("companies")
    by_norm: dict[str, str] = {}
    for p in props:
        for k in (p.get("name"), p.get("label")):
            if k:
                by_norm.setdefault(store._norm_key(k), p["name"])
    names = {p["name"] for p in props}

    mapping: dict[str, list[str]] = {}
    for col, cands in NATIVE.items():
        mapping[col] = [c for c in cands if c in names]
    for col, aliases in store._ALIASES.items():
        if col in SKIP_COLS:
            continue
        found = mapping.setdefault(col, [])
        for a in aliases:
            prop = by_norm.get(a)
            if prop and prop not in found and prop != "hs_object_id":
                found.append(prop)
    mapping = {c: v for c, v in mapping.items() if v}

    return mapping, pick_owner_property(props, forced_owner), props


def size_of(v) -> str | None:
    s = store._clean_text(v)
    if not s:
        return None
    if s in SIZES:
        return s
    n = store._to_int(s)
    if n is None:
        return None
    for top, label in ((10, "1-10"), (50, "11-50"), (200, "51-200"), (500, "201-500"),
                       (1000, "501-1000"), (5000, "1001-5000")):
        if n <= top:
            return label
    return "5000+"


def _in_list(v, options) -> str | None:
    s = store._clean_text(v)
    if not s:
        return None
    low = {o.lower(): o for o in options}
    return low.get(s.lower())


def map_company(rec: dict, mapping: dict, owner: OwnerResolver) -> tuple[dict, Counter]:
    props = rec.get("properties") or {}
    notes: Counter = Counter()
    data: dict = {}
    # Columnas con un valor en HubSpot que no se pudo traducir (status fuera de la lista,
    # PO que no es un BDR activo): el sync no las toca, para no vaciar el dato del Hub.
    invalid: set[str] = set()
    for col, plist in mapping.items():
        raw = next((props.get(p) for p in plist if props.get(p) not in (None, "")), None)
        if raw is None:
            continue
        if col == "size":
            v = size_of(raw)
        elif col == "prospecting_status":
            v = _in_list(raw, STATUSES)
        elif col == "not_icp_reason":
            v = _in_list(raw, NOT_ICP_REASONS)
        else:
            v = store.clean_value(col, raw)
        if v is None:
            notes[f"{col}: valor fuera de la lista (queda en raw_payload)"] += 1
            invalid.add(col)
            continue
        data[col] = v

    email, why = owner.resolve(props.get(owner.prop["name"]))
    if email:
        data["prospecting_owner_email"] = email
    elif why != "vacío":
        notes[f"PO HubSpot «{props.get(owner.prop['name'])}» {why} (queda sin owner)"] += 1
        invalid.add("prospecting_owner_email")

    data["hubspot_company_id"] = str(rec["id"])
    data["domain"] = store.normalize_domain(data.get("website") or props.get("domain"))
    data["name"] = data.get("name") or data["domain"]
    created = props.get("createdate")
    try:
        data["created_at"] = datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None
    except ValueError:
        data["created_at"] = None
    data["raw_payload"] = {k: v for k, v in props.items() if v not in (None, "")}
    data["_invalid"] = invalid
    return data, notes


COLS = ["name", "hubspot_company_id", "domain", "website", "linkedin_url", "description",
        "industry", "keywords", "technologies", "job_types", "open_jobs", "founded_year", "size",
        "city", "state", "country", "lead_source", "tier", "remote_jobs", "week_label",
        "prospecting_status", "prospecting_owner_email", "prospecting_start_date", "not_icp_reason"]
FILLABLE = [c for c in COLS if c not in ("hubspot_company_id",)]


# --------------------------------------------------------------------------- #
# Sync incremental HubSpot -> Hub
# --------------------------------------------------------------------------- #
SYNC_SOURCE = "hubspot_sync"
SYNC_KEY = "prospect_companies"
SYNC_LOCK_KEY = 72_026_110_4  # advisory lock propio (el de opps es otro)
# Bootstrap: la importación masiva fue el 2026-11-03; todo lo modificado desde ese día
# en HubSpot se revisa en la primera corrida.
BOOTSTRAP = datetime(2026, 11, 3, 3, 0, tzinfo=timezone.utc)
# El índice de búsqueda de HubSpot llega con unos segundos/minutos de atraso: se relee
# un tramo. Es idempotente (la foto `hubspot_seen` hace que lo ya aplicado no cambie).
OVERLAP = timedelta(minutes=10)
# La búsqueda de HubSpot no pagina más allá de 10.000 resultados: antes de eso se vuelve
# a buscar desde la última fecha procesada.
SEARCH_AFTER_CAP = 9_000

_CTX: dict = {}
_CTX_TTL = 3600


def _context(cur, client: HubSpotClient) -> tuple[dict, OwnerResolver]:
    """Mapeo + owners, cacheados una hora por proceso (son 3-4 requests a HubSpot)."""
    if _CTX and _time.time() - _CTX["at"] < _CTX_TTL:
        return _CTX["mapping"], _CTX["owner"]
    mapping, owner_prop, _props = resolve_mapping(client)
    owner = OwnerResolver(owner_prop, client.list_owners(), store.list_bdrs(cur))
    _CTX.update(at=_time.time(), mapping=mapping, owner=owner)
    return mapping, owner


def sync_fields(mapping: dict) -> list[str]:
    return [c for c in FILLABLE if c != "domain" and (c in mapping or c == "prospecting_owner_email")]


def _enc(v):
    """Valor comparable/guardable en la foto (JSON): todo como texto, vacío = None."""
    if v in (None, ""):
        return None
    return store._fmt(v)


def _baseline(row: dict, mapping: dict, owner: OwnerResolver, fields: list[str],
              owner_touched: bool = True) -> dict:
    """Lo último que se vio en HubSpot para esta empresa, por campo.

    `hubspot_seen` si ya pasó por el sync. Si no (las ~165 k importadas), el `raw_payload`
    de la importación, que es la foto de HubSpot de ese momento (sólo trae los valores no
    vacíos, así que ausente = vacío). El owner no: la importación pudo leer otra
    propiedad y la reparación lo cambió después, así que queda "desconocido" y la primera
    vez sólo se rellena si está vacío — salvo que nadie lo haya tocado en el Hub después de
    la importación/reparación (`owner_touched` False): entonces el owner del Hub ES lo que
    había en HubSpot, y si ahora difiere es porque cambió allá."""
    seen = row.get("hubspot_seen")
    if isinstance(seen, str):
        seen = json.loads(seen)
    if isinstance(seen, dict):
        return seen
    raw = row.get("raw_payload")
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict) or "hs_object_id" not in raw:
        return {}
    d, _ = map_company({"id": row.get("hubspot_company_id"), "properties": raw}, mapping, owner)
    base = {f: _enc(d.get(f)) for f in fields if f != "prospecting_owner_email"}
    if not owner_touched:
        base["prospecting_owner_email"] = _enc(row.get("prospecting_owner_email"))
    return base


def _search_since(client: HubSpotClient, since: datetime, properties: list[str], after=None):
    body = {
        "filterGroups": [{"filters": [{
            "propertyName": "hs_lastmodifieddate", "operator": "GTE",
            "value": str(int(since.timestamp() * 1000)),
        }]}],
        "sorts": [{"propertyName": "hs_lastmodifieddate", "direction": "ASCENDING"}],
        "properties": properties,
        "limit": 100,
    }
    if after:
        body["after"] = after
    payload = client._request("POST", "/crm/v3/objects/companies/search", json=body)
    nxt = ((payload.get("paging") or {}).get("next") or {}).get("after")
    return payload.get("results", []), nxt


def _modified_at(rec: dict) -> datetime | None:
    v = (rec.get("properties") or {}).get("hs_lastmodifieddate") or rec.get("updatedAt")
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None


def _read_watermark(cur, key: str = SYNC_KEY) -> datetime | None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS hubspot_sync_state (
            sync_key     TEXT PRIMARY KEY,
            watermark_ms BIGINT,
            last_run_at  TIMESTAMPTZ,
            last_status  TEXT,
            last_report  JSONB
        )
        """
    )
    cur.execute("SELECT watermark_ms FROM hubspot_sync_state WHERE sync_key = %s", (key,))
    r = cur.fetchone()
    if not r or r["watermark_ms"] is None:
        return None
    return datetime.fromtimestamp(int(r["watermark_ms"]) / 1000, tz=timezone.utc)


def _write_state(cur, watermark: datetime | None, status: str, report: dict, key: str = SYNC_KEY) -> None:
    cur.execute(
        """
        INSERT INTO hubspot_sync_state (sync_key, watermark_ms, last_run_at, last_status, last_report)
        VALUES (%s, %s, NOW(), %s, %s::jsonb)
        ON CONFLICT (sync_key) DO UPDATE
           SET watermark_ms = COALESCE(EXCLUDED.watermark_ms, hubspot_sync_state.watermark_ms),
               last_run_at = EXCLUDED.last_run_at, last_status = EXCLUDED.last_status,
               last_report = EXCLUDED.last_report
        """,
        (key, int(watermark.timestamp() * 1000) if watermark else None, status,
         json.dumps(report, default=str)),
    )


def last_report(cur, key: str = SYNC_KEY) -> dict | None:
    _read_watermark(cur, key)
    cur.execute("SELECT * FROM hubspot_sync_state WHERE sync_key = %s", (key,))
    return cur.fetchone()


def _create(cur, d: dict, fields: list[str]) -> dict:
    cols = ["name", "hubspot_company_id", "domain", "is_dummy", "raw_payload", "hubspot_seen"]
    seen = {f: _enc(d.get(f)) for f in fields if f not in d["_invalid"]}
    vals = [d["name"], d["hubspot_company_id"], d.get("domain"), False, Json(d["raw_payload"]), Json(seen)]
    for c in COLS:
        if c not in cols and d.get(c) is not None:
            cols.append(c)
            vals.append(d[c])
    if "lead_source" not in cols:
        cols.append("lead_source")
        vals.append("HubSpot")
    cur.execute(
        f"INSERT INTO prospect_companies ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(vals))}) RETURNING *",
        vals,
    )
    row = dict(cur.fetchone())
    store.log_event(cur, row["id"], SYNC_SOURCE, None, None, None, "created")
    changes = [{"field": c, "old": None, "new": v} for c, v in zip(cols, vals)
               if c in COLS and c not in ("hubspot_company_id", "domain") and v not in (None, "")]
    for ch in changes:
        store.log_event(cur, row["id"], SYNC_SOURCE, None, ch["field"], None, ch["new"])
    return {**row, "_changes": changes}


def _apply_one(cur, d: dict, row: dict | None, mapping: dict, owner: OwnerResolver,
               fields: list[str], dry_run: bool, owner_touched: bool = True) -> tuple[str, dict | None, list[dict]]:
    """('created' | 'updated' | 'same', fila, cambios). Regla: HubSpot gana sólo cuando
    su valor cambió respecto de la última foto; si no, gana el Hub."""
    if row is None:
        if dry_run:
            return "created", None, [{"field": c, "old": None, "new": d.get(c)}
                                     for c in fields if d.get(c) is not None]
        created = _create(cur, d, fields)
        return "created", created, created.pop("_changes")

    base = _baseline(row, mapping, owner, fields, owner_touched)
    patch, new_seen = {}, dict(base)
    for f in fields:
        if f in d["_invalid"]:
            continue  # valor de HubSpot que no se pudo traducir: no se toca, ni la foto
        hs = _enc(d.get(f))
        cur_v = _enc(row.get(f))
        if f in base:
            if hs != base[f] and hs != cur_v:
                patch[f] = d.get(f)
        elif cur_v is None and hs is not None:
            patch[f] = d.get(f)
        new_seen[f] = hs

    extra_sets, extra_vals = ["hubspot_seen = %s"], [Json(new_seen)]
    if not row.get("hubspot_company_id"):
        extra_sets.append("hubspot_company_id = %s")
        extra_vals.append(d["hubspot_company_id"])
    if "website" in patch and d.get("domain"):
        extra_sets.append("domain = %s")
        extra_vals.append(d["domain"])

    if dry_run:
        return ("updated" if patch else "same"), row, [
            {"field": f, "old": row.get(f), "new": v} for f, v in patch.items()]
    cur.execute(f"UPDATE prospect_companies SET {', '.join(extra_sets)} WHERE id = %s",
                extra_vals + [row["id"]])
    if not patch:
        return "same", row, []
    updated = store.update_company(cur, row["id"], patch, None, source=SYNC_SOURCE)
    return "updated", updated, updated.pop("_changes", [])


def sync(conn, client: HubSpotClient | None = None, *, dry_run: bool = False,
         max_companies: int = 2000, time_budget: float = 200.0, since: datetime | None = None,
         log=None) -> dict:
    """Trae de HubSpot las empresas modificadas desde la marca de agua y las aplica.

    Commit por página (100). La marca avanza a la última `hs_lastmodifieddate` procesada,
    así una corrida cortada por tiempo o por `max_companies` sigue en la próxima. Los
    cambios son cambios reales para los workflows (decisión de la owner, 2026-11-04):
    `emit_event()` por empresa y un `tick()` por página."""
    client = client or HubSpotClient()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    store.ensure_schema(cur)
    cur.execute("SELECT pg_try_advisory_lock(%s) AS got", (SYNC_LOCK_KEY,))
    if not cur.fetchone()["got"]:
        conn.rollback()
        return {"status": "busy", "error": "Otra corrida del sync está en curso."}
    t0 = _time.time()
    stats: Counter = Counter()
    sample: list[dict] = []
    errors: list[dict] = []
    status = "ok"
    try:
        mapping, owner = _context(cur, client)
        fields = sync_fields(mapping)
        properties = sorted({p for pl in mapping.values() for p in pl} | set(ALWAYS)
                            | {owner.prop["name"], "hs_lastmodifieddate"})
        watermark = _read_watermark(cur)
        conn.commit()
        start = since or ((watermark - OVERLAP) if watermark else BOOTSTRAP)
        lower, after, processed, last_ts = start, None, 0, watermark
        seen_ids: set[str] = set()
        while processed < max_companies:
            if _time.time() - t0 > time_budget:
                status = "partial"
                break
            results, nxt = _search_since(client, lower, properties, after)
            if not results:
                break
            page = []
            for rec in results:
                if str(rec["id"]) in seen_ids:
                    continue
                seen_ids.add(str(rec["id"]))
                d, notes = map_company(rec, mapping, owner)
                stats.update({f"aviso: {k}": n for k, n in notes.items()})
                page.append((d, _modified_at(rec)))
            _process_page(cur, page, mapping, owner, fields, dry_run, stats, sample, errors)
            processed += len(results)
            page_ts = max((ts for _, ts in page if ts), default=None)
            if not dry_run:
                # Con un error en el camino la marca se congela: la próxima corrida vuelve
                # a mirar desde ahí (lo ya aplicado no cambia, por la foto).
                if not errors and page_ts and (last_ts is None or page_ts > last_ts):
                    last_ts = page_ts
                _write_state(cur, last_ts, "running", {"stats": dict(stats)})
                conn.commit()
            if log:
                log(f"  {processed} leídas · {dict((k, v) for k, v in stats.items() if not k.startswith('aviso'))}")
            if not nxt:
                break
            if int(nxt) >= SEARCH_AFTER_CAP and page_ts:
                lower, after = page_ts, None  # nueva búsqueda desde la última fecha
            else:
                after = nxt
        else:
            status = "partial"
        report = {
            "status": status, "dry_run": dry_run, "since": start.isoformat(),
            "watermark": last_ts.isoformat() if last_ts else None,
            "read": processed, "seconds": round(_time.time() - t0, 1),
            "stats": dict(stats), "sample": sample, "errors": errors[:50],
        }
        if not dry_run:
            _write_state(cur, None, "error" if errors else status, report)
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


def _process_page(cur, page, mapping, owner, fields, dry_run, stats, sample, errors) -> None:
    if not page:
        return
    hs_ids = [d["hubspot_company_id"] for d, _ in page]
    cur.execute(
        "SELECT * FROM prospect_companies WHERE hubspot_company_id = ANY(%s) AND NOT is_dummy ORDER BY id",
        (hs_ids,),
    )
    by_hs: dict[str, list] = {}
    for r in cur.fetchall():
        by_hs.setdefault(r["hubspot_company_id"], []).append(dict(r))
    missing_domains = sorted({d["domain"] for d, _ in page if d["domain"] and d["hubspot_company_id"] not in by_hs})
    by_domain: dict[str, dict] = {}
    if missing_domains:
        # Una empresa nueva de HubSpot adopta la fila de Clay del mismo dominio (sin id de HubSpot).
        cur.execute(
            "SELECT * FROM prospect_companies WHERE domain = ANY(%s) AND NOT is_dummy "
            "AND hubspot_company_id IS NULL ORDER BY id",
            (missing_domains,),
        )
        for r in cur.fetchall():
            by_domain.setdefault(r["domain"], dict(r))

    # Owners que tocó alguien en el Hub (BDR, workflow, Clay, edición masiva) después de la
    # importación: para esos, la primera vez gana el Hub.
    ids = [r["id"] for rs in by_hs.values() for r in rs]
    owner_touched: set[int] = set()
    if ids:
        cur.execute(
            """
            SELECT DISTINCT company_id FROM prospect_company_events
             WHERE company_id = ANY(%s) AND field = 'prospecting_owner_email'
               AND source NOT IN ('hubspot_import', %s)
            """,
            (ids, SYNC_SOURCE),
        )
        owner_touched = {r["company_id"] for r in cur.fetchall()}

    now = engine.utcnow()
    touched: list[int] = []
    for d, _ts in page:
        rows = by_hs.get(d["hubspot_company_id"]) or ([by_domain.pop(d["domain"])] if d["domain"] in by_domain else [None])
        for row in rows:
            if row is None and not d.get("name"):
                stats["sin_nombre"] += 1
                continue
            cur.execute("SAVEPOINT hs_company")
            try:
                kind, out, changes = _apply_one(cur, d, row, mapping, owner, fields, dry_run,
                                                owner_touched=row is None or row["id"] in owner_touched)
                if not dry_run and out is not None and kind != "same":
                    engine.emit_event(cur, "company", out["id"], "created" if kind == "created" else "updated",
                                      changes, now, SYNC_SOURCE)
                    touched.append(out["id"])
                    # Contactos de la bandeja (Calendly / HubSpot) que esperaban una empresa
                    # con este dominio: se vinculan solos, como con Clay.
                    for a in inbound.attach_pending_for_company(cur, out["id"]):
                        engine.emit_event(cur, "contact", a["contact_id"], a["action"], a.pop("changes"),
                                          now, SYNC_SOURCE)
                        stats["contactos_de_la_bandeja_vinculados"] += 1
                cur.execute("RELEASE SAVEPOINT hs_company")
            except Exception as exc:  # una empresa rota no frena el lote
                cur.execute("ROLLBACK TO SAVEPOINT hs_company")
                errors.append({"hubspot_company_id": d["hubspot_company_id"], "error": str(exc)[:300]})
                stats["errores"] += 1
                continue
            stats[{"created": "creadas", "updated": "actualizadas", "same": "sin_cambios"}[kind]] += 1
            if kind != "same" and len(sample) < 25:
                sample.append({"id": out["id"] if out else None, "hubspot_company_id": d["hubspot_company_id"],
                               "name": d.get("name"), "accion": kind,
                               "cambios": [{"campo": c["field"], "antes": _enc(c["old"]), "ahora": _enc(c["new"])}
                                           for c in changes][:12]})
    if touched:
        res = engine.tick(cur, now, automatic=True, company_id=sorted(set(touched)), actor=SYNC_SOURCE)
        stats["inscripciones_en_workflows"] += int(res.get("enrolled") or 0)
