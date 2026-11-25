"""Editor de propiedades de Prospecting (empresas, contactos, negocios) — 2026-11-25.

Los catálogos siguen escritos en código (`constants.FIELDS`, `contact_fields.CONTACT_FIELDS`,
`deal_fields.DEAL_FIELDS`): son las propiedades «de fábrica». Encima va una capa en la base,
`prospect_properties`, que editan desde la página las personas de `PROPERTY_EDITORS`:

  * fila con `is_custom = FALSE` = OVERRIDE de una de fábrica (nombre, descripción, opciones,
    tipo texto ↔ desplegable, obligatoria, oculta, orden). Las de fábrica no se borran.
  * fila con `is_custom = TRUE` = propiedad nueva, completa. Su valor vive en `props` (JSONB)
    del registro (`prospect_companies.props` se agregó para esto). Borrarla = archivarla.

Cómo llega al resto del código sin cambiar cada import: `refresh(cur)` reconstruye EN EL LUGAR
las listas y dicts compartidos (`FIELDS`, `FIELDS_BY_KEY`, `EDITABLE_FIELDS`, `CONTACT_FIELDS*`,
`DEAL_FIELDS*`, los sets de `objects.OBJECTS`) a partir de una copia del catálogo de código +
las filas de la tabla. Todos los módulos tienen la misma referencia, así que lo ven todos. Se
llama en cada request de /prospecting (`_Db` de las rutas): una consulta barata compara la
versión de la tabla con la del proceso y sólo reconstruye si cambió (gunicorn tiene varios
workers: así se enteran todos).

«Obligatoria» frena sólo lo MANUAL (alta y edición desde la página: rutas); Clay, HubSpot,
Calendly y los workflows no pasan por `check_*` (decisión de la owner): una llegada nunca se
pierde por un campo vacío.
"""
from __future__ import annotations

import copy
import re
import unicodedata

from psycopg2.extras import Json

from prospecting import constants as C
from prospecting import contact_fields as CF
from prospecting import deal_fields as DF
from prospecting import objects as OB

OBJECTS = ("company", "contact", "deal")
TYPES = ["text", "longtext", "number", "date", "datetime", "bool", "enum", "multi", "url", "email", "phone", "user"]
TYPE_LABELS = {
    "text": "Texto", "longtext": "Texto largo", "number": "Número", "date": "Fecha",
    "datetime": "Fecha y hora", "bool": "Sí / No", "enum": "Desplegable (una opción)",
    "multi": "Casillas (varias opciones)", "url": "URL", "email": "Email", "phone": "Teléfono",
    "user": "Persona del Hub", "owner": "BDR (owner)",
}
# Con datos cargados sólo se cambia dentro de la misma familia: el valor guardado sigue sirviendo.
_TEXTUAL = {"text", "longtext", "enum", "url", "email", "phone"}

# Copia del catálogo de código, tomada antes de cualquier refresh.
_BASE = {
    "company": copy.deepcopy(C.FIELDS),
    "contact": copy.deepcopy(CF.CONTACT_FIELDS),
    "deal": copy.deepcopy(DF.DEAL_FIELDS),
}
_BASE_GROUPS = {"contact": list(CF.CONTACT_GROUPS), "deal": list(DF.DEAL_GROUPS)}
_BASE_EDITABLE = list(C.EDITABLE_FIELDS)
_VERSION = [None]


# --------------------------------------------------------------------------- #
# Esquema
# --------------------------------------------------------------------------- #
def ensure_schema(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_properties (
            object       TEXT NOT NULL,
            key          TEXT NOT NULL,
            is_custom    BOOLEAN NOT NULL DEFAULT FALSE,
            label        TEXT,
            description  TEXT,
            type         TEXT,
            group_name   TEXT,
            options      JSONB,
            required     BOOLEAN,
            hidden       BOOLEAN,
            position     INTEGER,
            hubspot_name TEXT,
            created_by   TEXT,
            updated_by   TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            archived_at  TIMESTAMPTZ,
            PRIMARY KEY (object, key)
        )
        """
    )
    # Propiedades nuevas de empresa (las de fábrica son columnas).
    cur.execute("ALTER TABLE prospect_companies ADD COLUMN IF NOT EXISTS props JSONB NOT NULL DEFAULT '{}'::jsonb")


# --------------------------------------------------------------------------- #
# Claves que el código usa a mano: no se ocultan ni cambian de tipo
# --------------------------------------------------------------------------- #
def _locked_keys(obj: str) -> set:
    from prospecting import deals as D
    from prospecting import prop_sync

    idx = {"contact": 0, "deal": 1, "company": 2}[obj]
    out = {t[idx] for t in prop_sync.LINKS if t[idx]}
    if obj == "company":
        out |= {"name", "created_at", "hubspot_company_id", "website", "size", "city", "state",
                "linkedin_url", "industry"} | set(C.BDR_FIELDS)
        out |= {src[1] for srcs in DF.PREFILL.values() for src in srcs if src[0] == "company"}
    elif obj == "contact":
        out |= set(CF.REQUIRED_ON_QUALIFIED) | set(CF.CONTACT_COLUMNS)
        out |= {src[1] for srcs in DF.PREFILL.values() for src in srcs if src[0] == "contact"}
        out |= {"company_name", "first_deep_dive_date", "last_deep_dive_date", "website", "headcount",
                "vintti_ai", "date_of_meeting_scheduled", "meeting_datetime", "scheduled_by",
                "mql_ae_lost_reason", "country_continent", "origin_detail", "phone"}
    else:
        out |= set(DF.DEAL_COLUMNS) | set(DF.MIN_FOR_OPPORTUNITY) | set(DF.PREFILL)
        out |= {k for rows in DF.STAGE_FORMS.values() for k, _ in rows}
        out |= {"lead_life_deal", "first_deep_dive_date", "credit_loop", "credits_won",
                "credits_expiring_date", "mql_lost_reason", "close_date"}
        out |= set(D._HIRE_TO_DEAL.values())
    return out


# Opciones que el código compara por texto: no se editan.
_OPTIONS_LOCKED = {("company", "prospecting_status")}


# --------------------------------------------------------------------------- #
# Construcción del catálogo
# --------------------------------------------------------------------------- #
def _rows(cur) -> list[dict]:
    cur.execute("SELECT * FROM prospect_properties WHERE archived_at IS NULL ORDER BY object, key")
    return [dict(r) for r in cur.fetchall()]


def _build(obj: str, rows: list[dict]) -> list[dict]:
    mine = {r["key"]: r for r in rows if r["object"] == obj}
    order = []
    for i, base in enumerate(_BASE[obj]):
        f = copy.deepcopy(base)
        r = mine.get(f["key"])
        if r and not r["is_custom"]:
            if r["label"]:
                f["label"] = r["label"]
            if r["description"] is not None:
                f["description"] = r["description"]
            if r["type"] and r["type"] != f["type"]:
                f["type"] = r["type"]
            if r["options"] is not None and f["type"] in ("enum", "multi"):
                f["options"] = list(r["options"])
                f["options_locked"] = True  # deals.field_defs: gana sobre las de HubSpot
            if r["group_name"] and obj != "company":
                f["group"] = r["group_name"]
            if r["required"]:
                f["required"] = True
            if r["hidden"]:
                f["hidden"] = True
            if r["hubspot_name"] and obj == "deal":
                f["hubspot"] = [r["hubspot_name"]] + [h for h in f.get("hubspot", []) if h != r["hubspot_name"]]
        if f["type"] not in ("enum", "multi"):
            f.pop("options", None)
            f.pop("options_locked", None)
        pos = r["position"] if r and r["position"] is not None else i * 10
        order.append((pos, i, f))
    n = len(_BASE[obj])
    for j, r in enumerate(sorted((r for r in mine.values() if r["is_custom"]), key=lambda r: r["created_at"])):
        f = {"key": r["key"], "label": r["label"] or r["key"], "type": r["type"] or "text",
             "storage": "props", "custom": True}
        if obj != "company":
            f["group"] = r["group_name"] or ("Otras" if obj == "contact" else "Negocio")
        elif r["group_name"]:
            f["group"] = r["group_name"]
        if r["description"]:
            f["description"] = r["description"]
        if f["type"] in ("enum", "multi"):
            f["options"] = list(r["options"] or [])
            f["options_locked"] = True
        if r["required"]:
            f["required"] = True
        if r["hidden"]:
            f["hidden"] = True
        if obj == "deal":
            f["hubspot"] = [r["hubspot_name"]] if r["hubspot_name"] else []
        pos = r["position"] if r["position"] is not None else (n + j) * 10 + 100000
        order.append((pos, n + j, f))
    order.sort(key=lambda t: (t[0], t[1]))
    return [f for _, _, f in order]


def refresh(cur, force: bool = False) -> None:
    """Reconstruye los catálogos compartidos si la tabla cambió desde la última vez."""
    cur.execute("SELECT COUNT(*) AS n, MAX(updated_at) AS m FROM prospect_properties")
    v = cur.fetchone()
    ver = (v["n"], v["m"])
    if not force and ver == _VERSION[0]:
        return
    rows = _rows(cur)
    comp, cont, deal = _build("company", rows), _build("contact", rows), _build("deal", rows)

    C.FIELDS[:] = comp
    C.FIELDS_BY_KEY.clear()
    C.FIELDS_BY_KEY.update({f["key"]: f for f in comp})
    custom_company = [f["key"] for f in comp if f.get("custom")]
    C.EDITABLE_FIELDS[:] = _BASE_EDITABLE + custom_company
    OB.OBJECTS["company"]["editable"].clear()
    OB.OBJECTS["company"]["editable"].update(C.EDITABLE_FIELDS)
    OB.OBJECTS["company"]["history"].clear()
    OB.OBJECTS["company"]["history"].update(set(C.EDITABLE_FIELDS) | set(C.CLAY_FIELDS))

    CF.CONTACT_FIELDS[:] = cont
    CF.CONTACT_FIELDS_BY_KEY.clear()
    CF.CONTACT_FIELDS_BY_KEY.update({f["key"]: f for f in cont})
    for k in ("editable", "history"):
        OB.OBJECTS["contact"][k].clear()
        OB.OBJECTS["contact"][k].update(CF.CONTACT_FIELDS_BY_KEY)

    DF.DEAL_FIELDS[:] = deal
    DF.DEAL_FIELDS_BY_KEY.clear()
    DF.DEAL_FIELDS_BY_KEY.update({f["key"]: f for f in deal})
    cond = OB._deal_condition_fields()
    OB.OBJECTS["deal"]["fields"].clear()
    OB.OBJECTS["deal"]["fields"].update(cond)

    for obj, lst, fields in (("contact", CF.CONTACT_GROUPS, cont), ("deal", DF.DEAL_GROUPS, deal)):
        groups = list(_BASE_GROUPS[obj])
        for f in fields:
            if f.get("group") and f["group"] not in groups:
                groups.append(f["group"])
        lst[:] = groups
    _VERSION[0] = ver


# --------------------------------------------------------------------------- #
# Lecturas para el editor
# --------------------------------------------------------------------------- #
def catalog(obj: str) -> list[dict]:
    return {"company": C.FIELDS, "contact": CF.CONTACT_FIELDS, "deal": DF.DEAL_FIELDS}[obj]


def _field(obj: str, key: str) -> dict | None:
    return {"company": C.FIELDS_BY_KEY, "contact": CF.CONTACT_FIELDS_BY_KEY, "deal": DF.DEAL_FIELDS_BY_KEY}[obj].get(key)


def _base_field(obj: str, key: str) -> dict | None:
    return next((f for f in _BASE[obj] if f["key"] == key), None)


def editor_list(cur) -> dict:
    """Todo lo que necesita la pantalla «Propiedades»."""
    from prospecting import deals as D

    deal_defs = {f["key"]: f for f in D.field_defs(cur)}
    out = {}
    for obj in OBJECTS:
        locked = _locked_keys(obj)
        rows = []
        for f in catalog(obj):
            if f.get("storage") == "expr" or f["key"] == "created_at":
                continue
            base = _base_field(obj, f["key"])
            g = {k: v for k, v in f.items() if k not in ("hubspot",)}
            if obj == "deal" and f["key"] in deal_defs:
                # Las opciones que se ven en las fichas (con las de HubSpot encima).
                dd = deal_defs[f["key"]]
                if dd.get("options"):
                    g["options"] = dd["options"]
            g["factory"] = base is not None
            g["factory_type"] = base["type"] if base else None
            g["locked"] = f["key"] in locked
            g["options_locked"] = (obj, f["key"]) in _OPTIONS_LOCKED
            g["hubspot_name"] = (f.get("hubspot") or [None])[0] if obj == "deal" else None
            rows.append(g)
        groups = {"contact": CF.CONTACT_GROUPS, "deal": DF.DEAL_GROUPS}.get(obj, [])
        out[obj] = {"fields": rows, "groups": list(groups)}
    return {"objects": out, "types": [{"value": t, "label": TYPE_LABELS[t]} for t in TYPES]}


def _table(obj: str) -> str:
    return {"company": "prospect_companies", "contact": "prospect_contacts", "deal": "prospect_deals"}[obj]


def _is_col(obj: str, f: dict) -> bool:
    if f.get("storage") == "col":
        return True
    return obj == "company" and f.get("storage") != "props"


def value_counts(cur, obj: str, key: str, limit: int = 300) -> list[dict]:
    """Valores distintos cargados (sin dummies) y cuántos registros tiene cada uno."""
    f = _field(obj, key)
    if not f:
        raise LookupError(key)
    t = _table(obj)
    assert re.match(r"^[a-z0-9_]+$", key)
    if _is_col(obj, f):
        expr = f"NULLIF(BTRIM({key}::text), '')"
        cur.execute(f"SELECT {expr} AS v, COUNT(*) AS n FROM {t} WHERE NOT is_dummy AND {expr} IS NOT NULL "
                    f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT %s", (limit,))
    elif f["type"] == "multi":
        cur.execute(f"""
            SELECT x AS v, COUNT(*) AS n FROM {t},
                   jsonb_array_elements_text(CASE WHEN jsonb_typeof(props->'{key}') = 'array'
                                                  THEN props->'{key}' ELSE '[]'::jsonb END) x
             WHERE NOT is_dummy GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT %s""", (limit,))
    else:
        cur.execute(f"""
            SELECT NULLIF(BTRIM(props->>'{key}'), '') AS v, COUNT(*) AS n FROM {t}
             WHERE NOT is_dummy AND NULLIF(BTRIM(props->>'{key}'), '') IS NOT NULL
             GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT %s""", (limit,))
    return [{"value": r["v"], "count": r["n"]} for r in cur.fetchall()]


def _has_data(cur, obj: str, key: str) -> bool:
    f = _field(obj, key)
    if not f:
        return False
    t = _table(obj)
    if _is_col(obj, f):
        cur.execute(f"SELECT 1 FROM {t} WHERE {key} IS NOT NULL AND {key}::text <> '' LIMIT 1")
    else:
        cur.execute(f"SELECT 1 FROM {t} WHERE props ? %s LIMIT 1", (key,))
    return cur.fetchone() is not None


def usages(cur, obj: str, key: str) -> list[dict]:
    """Workflows y vistas guardadas que nombran la propiedad (por texto en su JSON). Las claves
    nuevas son únicas entre los tres objetos, así que no hay falsos positivos de otro objeto."""
    pat = r'["\.:]' + re.escape(key) + r'["}]'
    cur.execute(
        """
        SELECT id, name FROM prospect_workflows
         WHERE CONCAT_WS(' ', trigger::text, steps::text, unenroll::text, goal::text,
                         conditions::text, actions::text) ~ %s
         ORDER BY name
        """,
        (pat,),
    )
    out = [{"kind": "workflow", "id": r["id"], "name": r["name"]} for r in cur.fetchall()]
    cur.execute("SELECT id, name, owner_email FROM prospect_saved_views WHERE config::text ~ %s ORDER BY name", (pat,))
    out += [{"kind": "view", "id": r["id"], "name": r["name"], "owner": r["owner_email"]} for r in cur.fetchall()]
    return out


# --------------------------------------------------------------------------- #
# Escrituras
# --------------------------------------------------------------------------- #
class PropertyError(ValueError):
    pass


_RESERVED = {"id", "props", "stage", "pipeline", "company", "contact", "deal", "hub_company", "contacts_count",
             "domain", "is_dummy", "raw_payload", "hubspot_seen", "created_at", "updated_at", "company_id",
             "contact_id", "deal_id", "is_primary", "created_by", "stage_key", "pipeline_key", "stage_dates",
             "opportunity_id", "account_id", "hubspot_deal_id", "hubspot_contact_id", "contact_incomplete",
             "clay_record_id", "contact_company_name", "company_status", "missing_required", "name", "events",
             "contacts", "deals", "enrollments", "workflows_applied"}


def _slug(label: str) -> str:
    s = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:48] or "propiedad"
    if s[0].isdigit():
        s = "p_" + s
    return s


def _taken(cur) -> set:
    cur.execute("SELECT key FROM prospect_properties")
    keys = {r["key"] for r in cur.fetchall()}
    for obj in OBJECTS:
        keys |= {f["key"] for f in _BASE[obj]}
    keys |= set(OB.OBJECTS["deal"]["fields"]) | _RESERVED
    return keys


def _clean_options(raw) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PropertyError("Las opciones tienen que ser una lista.")
    out = []
    for o in raw:
        s = str(o if o is not None else "").strip()
        if not s:
            continue
        if len(s) > 200:
            raise PropertyError("Una opción es demasiado larga (máx. 200 caracteres).")
        if s.lower() in {x.lower() for x in out}:
            raise PropertyError(f"La opción «{s}» está repetida.")
        out.append(s)
    return out


def _upsert(cur, obj: str, key: str, is_custom: bool, vals: dict, actor: str) -> None:
    cols = list(vals)
    cur.execute(
        f"""
        INSERT INTO prospect_properties (object, key, is_custom, created_by, updated_by {''.join(', ' + c for c in cols)})
        VALUES (%s, %s, %s, %s, %s {''.join(', %s' for _ in cols)})
        ON CONFLICT (object, key) DO UPDATE SET
            updated_by = EXCLUDED.updated_by, updated_at = NOW()
            {''.join(f', {c} = EXCLUDED.{c}' for c in cols)}
        """,
        [obj, key, is_custom, actor, actor] + [Json(v) if c == "options" and v is not None else v for c, v in vals.items()],
    )


def create(cur, obj: str, data: dict, actor: str) -> dict:
    if obj not in OBJECTS:
        raise PropertyError("Objeto inválido.")
    label = (data.get("label") or "").strip()
    if not label:
        raise PropertyError("Ponele un nombre a la propiedad.")
    if any(f["label"].strip().lower() == label.lower() for f in catalog(obj)):
        raise PropertyError(f"Ya hay una propiedad «{label}».")
    ty = data.get("type") or "text"
    if ty not in TYPES:
        raise PropertyError("Tipo inválido.")
    opts = _clean_options(data.get("options")) if ty in ("enum", "multi") else None
    if ty in ("enum", "multi") and not opts:
        raise PropertyError("Un desplegable necesita al menos una opción.")
    taken = _taken(cur)
    base = _slug(data.get("key") or label)
    key, n = base, 2
    while key in taken or key.startswith("entered_"):
        key = f"{base}_{n}"
        n += 1
    _upsert(cur, obj, key, True, {
        "label": label, "description": (data.get("description") or "").strip() or None, "type": ty,
        "group_name": (data.get("group") or "").strip() or None, "options": opts,
        "required": bool(data.get("required")), "hidden": False,
        "hubspot_name": (data.get("hubspot_name") or "").strip() or None,
    }, actor)
    refresh(cur, force=True)
    return {"key": key}


def update(cur, obj: str, key: str, data: dict, actor: str) -> dict:
    """Cambia una propiedad (de fábrica = override). `renames` = {viejo: nuevo}: actualiza los
    registros que tenían el valor viejo (renombrar o unificar opciones)."""
    f = _field(obj, key)
    if not f:
        raise LookupError(key)
    base = _base_field(obj, key)
    locked = key in _locked_keys(obj)
    vals: dict = {}

    if "label" in data:
        label = (data.get("label") or "").strip()
        if not label:
            raise PropertyError("El nombre no puede quedar vacío.")
        if any(g["key"] != key and g["label"].strip().lower() == label.lower() for g in catalog(obj)):
            raise PropertyError(f"Ya hay una propiedad «{label}».")
        vals["label"] = label
    if "description" in data:
        vals["description"] = (data.get("description") or "").strip() or None
    if "group" in data:
        vals["group_name"] = (data.get("group") or "").strip() or None
    if "required" in data:
        vals["required"] = bool(data["required"])
    if "hidden" in data:
        if data["hidden"] and locked:
            raise PropertyError("Esta propiedad la usa el sistema: no se puede ocultar.")
        if data["hidden"]:
            vals["required"] = False  # una oculta no puede frenar a nadie
        vals["hidden"] = bool(data["hidden"])
    if "hubspot_name" in data and obj == "deal":
        vals["hubspot_name"] = (data.get("hubspot_name") or "").strip() or None

    new_type = data.get("type") or f["type"]
    if new_type != f["type"]:
        if new_type not in TYPES:
            raise PropertyError("Tipo inválido.")
        if base is not None:
            if locked:
                raise PropertyError("Esta propiedad la usa el sistema: no se le puede cambiar el tipo.")
            ok = {base["type"], "text", "longtext", "enum"} if base["type"] in _TEXTUAL else {base["type"]}
            if not _is_col(obj, f) and base["type"] in _TEXTUAL | {"multi"}:
                ok |= {"multi"}
            if new_type not in ok:
                raise PropertyError("A una propiedad de fábrica sólo se le cambia el tipo entre texto y desplegable.")
        elif _has_data(cur, obj, key):
            if not ({f["type"], new_type} <= _TEXTUAL or {f["type"], new_type} <= {"enum", "multi"}):
                raise PropertyError("Ya tiene valores cargados: sólo se puede cambiar entre texto y desplegable.")
        vals["type"] = new_type

    if "options" in data and new_type in ("enum", "multi"):
        if (obj, key) in _OPTIONS_LOCKED:
            raise PropertyError("Las opciones de esta propiedad las usa el sistema: no se editan acá.")
        opts = _clean_options(data.get("options"))
        if not opts:
            raise PropertyError("Un desplegable necesita al menos una opción.")
        vals["options"] = opts
    elif "type" in vals and new_type in ("enum", "multi") and not f.get("options"):
        raise PropertyError("Un desplegable necesita al menos una opción.")
    if "type" in vals and new_type not in ("enum", "multi"):
        vals["options"] = None

    renamed = 0
    renames = data.get("renames") or {}
    if renames and new_type in ("enum", "multi", "text", "longtext"):
        renamed = _apply_renames(cur, obj, f, renames, new_type, actor)

    if vals:
        _upsert(cur, obj, key, base is None, vals, actor)
    refresh(cur, force=True)
    return {"key": key, "renamed": renamed}


def _apply_renames(cur, obj: str, f: dict, renames: dict, new_type: str, actor: str) -> int:
    """UPDATE de los registros con el valor viejo, con un evento por registro en el historial
    (source = property_edit). No dispara workflows: es un cambio de estructura, no de negocio."""
    key = f["key"]
    t = _table(obj)
    total = 0
    pairs = [(str(o).strip(), str(n).strip()) for o, n in renames.items()
             if str(o).strip() and str(n).strip() and str(o).strip() != str(n).strip()]
    if obj == "company":
        ev_cols, ev_sel = "company_id", "id"
    elif obj == "contact":
        ev_cols, ev_sel = "company_id, contact_id", "company_id, id"
    else:
        ev_cols, ev_sel = "company_id, deal_id", "company_id, id"
    for old, new in pairs:
        if _is_col(obj, f):
            sql = f"UPDATE {t} SET {key} = %s, updated_at = NOW() WHERE BTRIM({key}::text) = %s RETURNING *"
            params = [new, old]
        elif f["type"] == "multi" or new_type == "multi":
            sql = (f"UPDATE {t} SET props = jsonb_set(props, '{{{key}}}', "
                   f"(SELECT COALESCE(jsonb_agg(DISTINCT CASE WHEN x = %s THEN %s ELSE x END), '[]'::jsonb) "
                   f"   FROM jsonb_array_elements_text(props->'{key}') x)), updated_at = NOW() "
                   f"WHERE jsonb_typeof(props->'{key}') = 'array' AND props->'{key}' ? %s RETURNING *")
            params = [old, new, old]
        else:
            sql = (f"UPDATE {t} SET props = jsonb_set(props, '{{{key}}}', to_jsonb(%s::text)), updated_at = NOW() "
                   f"WHERE BTRIM(props->>'{key}') = %s RETURNING *")
            params = [new, old]
        cur.execute(
            f"""
            WITH up AS ({sql})
            INSERT INTO prospect_company_events ({ev_cols}, actor, source, field, old_value, new_value)
            SELECT {ev_sel}, %s, 'property_edit', %s, %s, %s FROM up
            """,
            params + [actor, key, old, new],
        )
        total += cur.rowcount
    return total


def delete(cur, obj: str, key: str, actor: str, purge: bool = False) -> dict:
    f = _field(obj, key)
    if not f:
        raise LookupError(key)
    if _base_field(obj, key) is not None:
        raise PropertyError("Las propiedades de fábrica no se borran: se ocultan.")
    used = usages(cur, obj, key)
    if used:
        return {"deleted": False, "usages": used}
    cur.execute(
        "UPDATE prospect_properties SET archived_at = NOW(), updated_at = NOW(), updated_by = %s "
        "WHERE object = %s AND key = %s",
        (actor, obj, key),
    )
    cleared = 0
    if purge:
        cur.execute(f"UPDATE {_table(obj)} SET props = props - %s WHERE props ? %s", (key, key))
        cleared = cur.rowcount
    refresh(cur, force=True)
    return {"deleted": True, "cleared": cleared}


def reorder(cur, obj: str, keys: list, actor: str) -> None:
    known = {f["key"] for f in catalog(obj)}
    for i, k in enumerate([k for k in keys if k in known]):
        base = _base_field(obj, k)
        cur.execute(
            """
            INSERT INTO prospect_properties (object, key, is_custom, position, created_by, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (object, key) DO UPDATE SET position = EXCLUDED.position,
                updated_by = EXCLUDED.updated_by, updated_at = NOW()
            """,
            (obj, k, base is None, i * 10, actor, actor),
        )
    refresh(cur, force=True)


# --------------------------------------------------------------------------- #
# Obligatorias (sólo lo manual: lo llaman las rutas)
# --------------------------------------------------------------------------- #
class MissingRequired(ValueError):
    def __init__(self, labels: list[str], keys: list[str]):
        super().__init__("Obligatorio: " + ", ".join(labels) + ".")
        self.keys = keys


def _empty(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, dict)) and not v)


def required_fields(obj: str) -> list[dict]:
    return [f for f in catalog(obj) if f.get("required") and not f.get("hidden")]


def check_create(obj: str, data: dict, skip: tuple = ()) -> None:
    miss = [f for f in required_fields(obj) if f["key"] not in skip and _empty((data or {}).get(f["key"]))]
    if miss:
        raise MissingRequired([f["label"] for f in miss], [f["key"] for f in miss])


def check_patch(obj: str, patch: dict) -> None:
    """Editar no frena por lo que ya faltaba: sólo no deja VACIAR una obligatoria."""
    miss = [f for f in required_fields(obj) if f["key"] in (patch or {}) and _empty(patch[f["key"]])]
    if miss:
        raise MissingRequired([f["label"] for f in miss], [f["key"] for f in miss])
