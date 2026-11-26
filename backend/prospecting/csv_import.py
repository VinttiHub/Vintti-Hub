"""Importar empresas desde un CSV (Empresas → «Importar CSV»).

Un BDR sube las empresas que prospectó por su cuenta. Como en HubSpot, cada columna del
archivo se mapea a una propiedad del Hub: el backend sugiere el mapeo (alias, label de la
propiedad o palabra clave) y la persona lo corrige o marca «No importar».

Match por dominio contra las empresas reales; por fila (decisión de la owner, 2026-11-25):

- sin nombre (y no existe) o sin dominio → error (sin dominio no se sabe si ya existe);
- dominio repetido en el mismo archivo → se usa la primera fila;
- en «Registros eliminados» → salteada;
- no existe → se crea con lo del CSV y el owner;
- existe sin owner, con un owner inactivo o en Recycled → se le asigna el owner (y la
  semana si viene); el resto sólo rellena vacíos;
- existe con owner (otro status) → salteada, el reporte dice de quién es.

Owner: quien sube si es BDR. Quien maneja owners elige un BDR en el desplegable y además
puede mapear una columna «Prospecting Owner» (ID del Hub o email de BDR) para el owner por
fila; la fila sin owner usa el del desplegable.
"""
from __future__ import annotations

import csv
import io

from prospecting import store
from prospecting.constants import FIELDS, STATUS_RECYCLED

MAX_ROWS = 2000
OWNER_KEY = "prospecting_owner"

# Encabezados típicos (Apollo, LinkedIn, Sheets) que no están en store._ALIASES.
_EXTRA_ALIASES = {
    "website_url": "website", "company_website": "website", "web": "website", "sitio_web": "website",
    "dominio": "website", "domain_name": "website", "company_url": "website",
    "empresa": "name", "nombre": "name", "company_name_for_emails": "name", "organization": "name",
    "company_linkedin": "linkedin_url", "linkedin_company_url": "linkedin_url",
    "employees": "size", "employee_count": "size", "empleados": "size", "tamano": "size",
    "industria_de_la_empresa": "industry",
}

# Palabra clave dentro del encabezado → campo (último recurso de la sugerencia).
_KEYWORDS = (
    ("linkedin", "linkedin_url"),
    ("domain", "website"), ("dominio", "website"), ("website", "website"), ("web", "website"), ("url", "website"),
    ("industr", "industry"),
    ("employee", "size"), ("empleado", "size"),
    ("semana", "week_label"), ("week", "week_label"),
    ("lead_source", "lead_source"), ("source", "lead_source"),
    ("country", "country"), ("pais", "country"),
    ("city", "city"), ("ciudad", "city"),
    ("state", "state"), ("provinc", "state"),
    ("descrip", "description"),
    ("company", "name"), ("empresa", "name"),
)
_OWNER_WORDS = ("owner", "codigo", "bdr", "user_id", "hub_id")

# Lo que se carga además de nombre / website / owner / semana / lead source.
EXTRA_FIELDS = ("linkedin_url", "description", "industry", "keywords", "technologies", "job_types",
                "open_jobs", "founded_year", "size", "city", "state", "country", "tier", "remote_jobs")
_BASE_KEYS = ("name", "website") + EXTRA_FIELDS + ("lead_source", "week_label")


def importable_fields(can_owner: bool) -> list[dict]:
    """Propiedades a las que se puede mapear una columna (el desplegable del modal)."""
    by_key = {f["key"]: f for f in FIELDS}
    out = [{"key": k, "label": by_key.get(k, {}).get("label", k)} for k in _BASE_KEYS]
    # Propiedades nuevas de empresa (Configuración → Propiedades).
    out += [{"key": f["key"], "label": f["label"]} for f in FIELDS if f.get("storage") == "props"]
    if can_owner:
        out.append({"key": OWNER_KEY, "label": "Prospecting Owner (ID del Hub o email del BDR)"})
    return out


def read_csv(text: str) -> tuple[list[str], list[dict]]:
    """(encabezados, filas crudas {encabezado: texto}). Tolera BOM y separador `;` o tab."""
    text = (text or "").lstrip("﻿")
    if not text.strip():
        raise ValueError("El archivo está vacío.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [h for h in (reader.fieldnames or []) if h is not None]
    if not headers:
        raise ValueError("El archivo no tiene encabezados.")
    rows = []
    for raw in reader:
        if not any(isinstance(v, str) and v.strip() for v in raw.values()):
            continue  # fila vacía
        if len(rows) >= MAX_ROWS:
            raise ValueError(f"Máximo {MAX_ROWS} empresas por archivo.")
        rows.append({h: (raw.get(h) or "") for h in headers})
    if not rows:
        raise ValueError("El archivo no tiene filas.")
    return headers, rows


def suggest_mapping(headers: list[str], can_owner: bool, rows: list | None = None,
                    bdrs: list | None = None) -> dict:
    """{encabezado: campo o None}. Cada campo va a una sola columna (la primera que lo pide).
    Owner: entre las columnas candidatas (nombre, código…) gana la que más valores reconoce."""
    all_headers = list(headers)
    allowed = {f["key"] for f in importable_fields(can_owner)}
    by_label = {store._norm_key(f["label"]): f["key"] for f in FIELDS if f["key"] in allowed}
    taken, out = set(), {}

    def pick(h):
        nk = store._norm_key(h)
        if can_owner and (nk in ("prospecting_owner_id", "owner_id", "bdr_id", "hub_owner_id",
                                 "prospecting_owner", "prospecting_owner_email", "owner_email")):
            return OWNER_KEY
        alias = _EXTRA_ALIASES.get(nk) or store._ALIAS_TO_COL.get(nk) or by_label.get(nk)
        if alias in allowed:
            return alias
        if can_owner and any(w in nk for w in _OWNER_WORDS):
            return OWNER_KEY
        for word, key in _KEYWORDS:
            if word in nk and key in allowed:
                return key
        return None

    if can_owner and rows and bdrs:
        cands = [h for h in headers if pick(h) == OWNER_KEY]
        if len(cands) > 1:
            def score(h):
                # Más valores reconocidos; en empate, la de IDs (un nombre puede ser ambiguo).
                ok = sum(1 for r in rows if resolve_row_owner(r.get(h), bdrs)[0])
                ids = sum(1 for r in rows if str(r.get(h) or "").strip().replace(".0", "").isdigit())
                return (ok, ids)
            best = max(cands, key=score)
            for h in cands:
                if h != best:
                    out[h] = None  # queda «No importar»
            headers = [h for h in headers if h == best or h not in cands]

    # Primero los exactos, después las palabras clave: «Company Domain» no le gana a «Domain».
    for exact_pass in (True, False):
        for h in headers:
            if h in out:
                continue
            k = pick(h)
            if k is None:
                continue
            nk = store._norm_key(h)
            exact = (k == OWNER_KEY and nk in ("prospecting_owner_id", "owner_id", "bdr_id", "hub_owner_id",
                                               "prospecting_owner", "prospecting_owner_email", "owner_email")) or \
                (_EXTRA_ALIASES.get(nk) or store._ALIAS_TO_COL.get(nk) or by_label.get(nk)) == k
            if exact_pass and not exact:
                continue
            if k in taken:
                continue
            out[h] = k
            taken.add(k)
    return {h: out.get(h) for h in all_headers}


def clean_mapping(mapping: dict, headers: list[str], can_owner: bool) -> dict:
    """El mapeo que manda la página, sólo con encabezados del archivo y campos permitidos."""
    allowed = {f["key"] for f in importable_fields(can_owner)}
    out, taken = {}, set()
    for h in headers:
        k = (mapping or {}).get(h)
        if k in allowed and k not in taken:
            out[h] = k
            taken.add(k)
        else:
            out[h] = None
    return out


def apply_mapping(rows: list[dict], mapping: dict) -> list[dict]:
    out = []
    for raw in rows:
        data = {}
        for h, k in mapping.items():
            if not k:
                continue
            v = raw.get(h)
            if k == OWNER_KEY:
                data[OWNER_KEY] = (v or "").strip() or None
            else:
                data[k] = store.clean_value(k, v)
        out.append(data)
    return out


def sample(headers: list[str], rows: list[dict]) -> dict:
    """Primer valor no vacío de cada columna (el «ejemplo» del paso Columnas)."""
    out = {}
    for h in headers:
        out[h] = next((r[h].strip() for r in rows if (r.get(h) or "").strip()), "")[:80]
    return out


def _plain(s) -> str:
    return " ".join(store._norm_key(s or "").split("_"))


def resolve_row_owner(raw, bdrs: list[dict]):
    """(email, error). Acepta el ID del Hub (users.user_id), el email de un BDR o su nombre
    (completo, o sólo el nombre de pila si no hay dos BDRs que lo compartan)."""
    if raw is None or not str(raw).strip():
        return None, None
    key = str(raw).strip().lower()
    if key.endswith(".0") and key[:-2].isdigit():  # Excel: 27 → «27.0»
        key = key[:-2]
    for b in bdrs:
        if key == str(b["id"]) or key == (b["email"] or "").lower():
            return b["email"], None
    name = _plain(key)
    full = [b for b in bdrs if _plain(b.get("name")) == name]
    if len(full) == 1:
        return full[0]["email"], None
    first = [b for b in bdrs if _plain(b.get("name")).split(" ")[:1] == name.split(" ")[:1]] if " " not in name else []
    if len(first) == 1:
        return first[0]["email"], None
    if len(first) > 1 or len(full) > 1:
        return None, f"Owner «{raw}» coincide con más de un BDR: usá el ID de BDR IDs o el email."
    return None, f"Owner «{raw}» no es un BDR del Hub (usá el ID de BDR IDs, el email o el nombre)."


def classify(cur, rows: list[dict], default_owner: str | None, bdrs: list[dict],
             active_emails: set | None = None) -> list[dict]:
    """Qué pasaría con cada fila, sin escribir nada. Cada item lleva su `owner`.
    `active_emails`: usuarios activos del Hub (store.list_users). Una empresa cuyo owner ya no
    está activo (dejó de trabajar) cuenta como libre y se asigna, como una sin owner."""
    domains = list({d for d in (store.normalize_domain(r.get("website")) for r in rows) if d})
    existing, deleted = {}, set()
    if domains:
        cur.execute(
            "SELECT id, name, domain, prospecting_owner_email, prospecting_status FROM prospect_companies "
            "WHERE domain = ANY(%s) AND NOT is_dummy ORDER BY id",
            (domains,),
        )
        for r in cur.fetchall():
            existing.setdefault(r["domain"], dict(r))  # la más vieja, como create_company
        cur.execute("SELECT domain FROM prospect_deleted_records WHERE object = 'company' AND domain = ANY(%s)",
                    (domains,))
        deleted = {r["domain"] for r in cur.fetchall()}

    seen, out = set(), []
    for i, data in enumerate(rows, start=2):  # fila 1 = encabezados, como en Excel
        name = data.get("name")
        domain = store.normalize_domain(data.get("website"))
        owner, owner_err = resolve_row_owner(data.get(OWNER_KEY), bdrs)
        owner = owner or default_owner
        item = {"row": i, "name": name or "", "domain": domain or "", "owner": owner or "",
                "data": data, "action": None, "reason": "", "company_id": None}
        hit = existing.get(domain) if domain else None
        if not domain:
            item.update(action="error", reason="Falta el website / dominio: sin él no se puede saber si ya existe.")
        elif domain in seen:
            item.update(action="skip", reason="Dominio repetido en el archivo: se usa la primera fila.")
        elif owner_err:
            item.update(action="error", reason=owner_err)
        elif not owner:
            item.update(action="error", reason="Sin Prospecting Owner: elegí un BDR para las filas sin owner.")
        elif hit is None and domain in deleted:
            item.update(action="skip", reason="Se eliminó en el Hub (Registros eliminados).")
        elif hit is None and not name:
            item.update(action="error", reason="Falta el nombre de la empresa.")
        elif hit is None:
            item.update(action="create", reason="Nueva.")
        else:
            item["company_id"] = hit["id"]
            item["name"] = item["name"] or hit["name"]
            cur_owner = (hit.get("prospecting_owner_email") or "").strip().lower()
            status = hit.get("prospecting_status") or ""
            if cur_owner == owner:
                item.update(action="skip", reason="Ya es de este owner.")
            elif not cur_owner:
                item.update(action="assign", reason="Ya existe sin owner: se asigna.")
            elif active_emails is not None and cur_owner not in active_emails:
                item.update(action="assign", reason=f"Ya existe, pero su owner ({cur_owner}) está inactivo: se reasigna.")
            elif status == STATUS_RECYCLED:
                item.update(action="assign", reason=f"Ya existe en Recycled (era de {cur_owner}): se reasigna.")
            else:
                item.update(action="skip", reason=f"Ya existe y es de {cur_owner} ({status or 'sin status'}).")
        if domain:
            seen.add(domain)
        out.append(item)
    return out


def apply_row(cur, item: dict, week_label: str | None, actor: str) -> tuple:
    """Crea o asigna una fila ya clasificada. Devuelve (company_id, kind, changes) para los workflows."""
    data = {k: v for k, v in item["data"].items() if k != OWNER_KEY}
    owner = item["owner"]
    week = week_label or data.get("week_label")
    props_keys = {f["key"] for f in FIELDS if f.get("storage") == "props"}
    if item["action"] == "create":
        base = {"name": data["name"], "website": data.get("website"),
                "prospecting_owner_email": owner,
                "lead_source": data.get("lead_source") or "Manual"}
        row = store.create_company(cur, base, actor)
        changes = list(row.pop("_changes"))
        extra = {k: v for k, v in data.items()
                 if k in EXTRA_FIELDS + tuple(props_keys) and v not in (None, "")}
        if week:
            extra["week_label"] = week
        if extra:
            # Sin validar (como Clay): un Size escrito distinto no frena la fila.
            upd = store.update_company(cur, row["id"], extra, actor)
            changes += upd["_changes"]
        return row["id"], "created", changes

    # assign: owner + semana siempre; lo demás sólo donde está vacío.
    cur.execute("SELECT * FROM prospect_companies WHERE id = %s FOR UPDATE", (item["company_id"],))
    current = store.flatten_company(cur.fetchone())
    patch = {"prospecting_owner_email": owner}
    if week:
        patch["week_label"] = week
    for k, v in data.items():
        if k in EXTRA_FIELDS + ("lead_source",) + tuple(props_keys) and v not in (None, "") \
                and current.get(k) in (None, ""):
            patch[k] = v
    upd = store.update_company(cur, item["company_id"], patch, actor, current=current)
    return item["company_id"], "updated", upd["_changes"]


def summary(items: list[dict]) -> dict:
    s = {"create": 0, "assign": 0, "skip": 0, "error": 0}
    for it in items:
        s[it["action"]] = s.get(it["action"], 0) + 1
    return s


def public(items: list[dict]) -> list[dict]:
    return [{k: v for k, v in it.items() if k != "data"} for it in items]
