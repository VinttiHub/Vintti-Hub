"""Vistas guardadas de la tabla de empresas, por persona (como las de HubSpot).

Dos tablas, autocreadas desde `store.ensure_schema()`:

  * `prospect_saved_views` — una fila por vista: dueña, nombre, `config` (filtros,
    filtros avanzados, columnas en orden, orden de filas, tamaño de página) y
    `shared`. Privada por defecto; compartida = cualquiera con acceso a Prospecting
    la puede AGREGAR a sus pestañas y duplicar, pero sólo la dueña la edita.
  * `prospect_view_prefs` — por persona, la lista ordenada de pestañas que ve:
    `"sys:<all|mine|unassigned|recycled>"` (las fijas, que se pueden ocultar) y
    `"v:<id>"`. NULL = nunca tocó nada → las 4 fijas + sus vistas.

`object` = 'company' (pestañas de la tabla de empresas) o 'contact' (la tira de vistas de
la pestaña Contacts, en orden de creación). Un **segmento** (Acciones → «Por segmento») es una
vista con `config.segment_ids`: la lista FIJA de registros que se tildaron al crearla.

`config` se valida acá y nunca llega como SQL: las columnas contra el catálogo,
el orden contra `FIELDS`, y los filtros avanzados con `rules.validate_conditions()`
(la misma lista blanca de los workflows).
"""
from __future__ import annotations

from psycopg2.extras import Json

from prospecting.constants import FIELDS_BY_KEY, STATUSES
from prospecting.rules import InvalidWorkflow, has_conditions, normalize_tree, validate_conditions

SYSTEM_TABS = ["sys:all", "sys:mine", "sys:unassigned", "sys:recycled"]
# Columnas de la tabla que no son campo (se muestran, no se filtran ni ordenan).
EXTRA_COLUMNS = {"contacts_count"}
FILTER_KEYS = ("owner", "week", "status", "start_from", "start_to", "q", "contact_incomplete", "dummy")
# Vistas de contactos: `name` (nombre + apellido, abre la ficha) y `hub_company` (la empresa
# del Hub; `company_name` ya es una propiedad del contacto) son columnas de la tabla, no campos.
CONTACT_EXTRA_COLUMNS = {"name", "hub_company"}
CONTACT_FILTER_KEYS = ("q", "lead_life", "owner", "dummy")
OBJECTS = ("company", "contact")
SEGMENT_MAX = 5000
PAGE_SIZES = (25, 50, 100)
MAX_NAME = 60
MAX_VIEWS = 40


def ensure_schema(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_saved_views (
            id           BIGSERIAL PRIMARY KEY,
            owner_email  TEXT NOT NULL,
            name         TEXT NOT NULL,
            config       JSONB NOT NULL DEFAULT '{}'::jsonb,
            shared       BOOLEAN NOT NULL DEFAULT FALSE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS ix_prospect_saved_views_owner ON prospect_saved_views (owner_email)")
    cur.execute("ALTER TABLE prospect_saved_views ADD COLUMN IF NOT EXISTS object TEXT NOT NULL DEFAULT 'company'")
    # Orden de la tira de vistas de contactos (ids), por persona. NULL = orden de creación.
    cur.execute("ALTER TABLE prospect_view_prefs ADD COLUMN IF NOT EXISTS contact_tabs JSONB")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_view_prefs (
            user_email  TEXT PRIMARY KEY,
            tabs        JSONB,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


# Cómo se ordena una columna (store.order_sql): `asc` / `desc` = A→Z, menor→mayor, más
# antiguo→reciente según el tipo; `list_asc` / `list_desc` = el orden de las opciones de una
# lista (Size 1-10 → 10001+, Status en el orden del pipeline).
SORT_MODES = ("asc", "desc", "list_asc", "list_desc")
SORT_EXTRA = {"company": {"contacts_count"}, "contact": {"name", "hub_company"}}


def parse_sort(raw, obj: str = "company") -> tuple[str, str] | None:
    """`<campo>:<modo>` con un campo del catálogo del objeto (o una calculada), o None."""
    if not isinstance(raw, str) or ":" not in raw:
        return None
    key, d = raw.rsplit(":", 1)
    if obj == "company":
        ok = key in FIELDS_BY_KEY
    else:
        from prospecting.contact_fields import CONTACT_FIELDS_BY_KEY
        ok = key in CONTACT_FIELDS_BY_KEY
    if (ok or key in SORT_EXTRA[obj]) and d in SORT_MODES:
        return key, d
    return None


def clean_segment(raw) -> list[int] | None:
    if not isinstance(raw, list):
        return None
    ids = sorted({int(x) for x in raw if str(x).isdigit()})
    if len(ids) > SEGMENT_MAX:
        raise InvalidWorkflow([f"Un segmento puede tener hasta {SEGMENT_MAX} registros."])
    return ids


def _clean_contact_config(cfg) -> dict:
    from prospecting.contact_fields import CONTACT_FIELDS_BY_KEY

    raw_f = cfg.get("filters") if isinstance(cfg.get("filters"), dict) else {}
    filters = {k: str(raw_f[k])[:200] for k in CONTACT_FILTER_KEYS if raw_f.get(k) not in (None, "", False)}
    if filters.get("dummy") and filters["dummy"] not in ("exclude", "include", "only"):
        filters.pop("dummy")
    cols, seen = [], set()
    for c in cfg.get("columns") or []:
        if isinstance(c, str) and c not in seen and (c in CONTACT_FIELDS_BY_KEY or c in CONTACT_EXTRA_COLUMNS):
            cols.append(c)
            seen.add(c)
    if "name" in seen:
        cols.remove("name")
    cols.insert(0, "name")
    try:
        page_size = int(cfg.get("page_size") or 25)
    except (TypeError, ValueError):
        page_size = 25
    sort = cfg.get("sort") if parse_sort(cfg.get("sort"), "contact") else None
    return {"filters": filters, "columns": cols, "page_size": page_size if page_size in PAGE_SIZES else 25, "sort": sort}


def clean_config(cfg, ctx, obj: str = "company") -> dict:
    """Valida y normaliza lo que manda la página. Levanta InvalidWorkflow."""
    if not isinstance(cfg, dict):
        cfg = {}
    segment = clean_segment(cfg.get("segment_ids"))
    if obj == "contact":
        out = _clean_contact_config(cfg)
        if segment is not None:
            out["segment_ids"] = segment
        return out
    errors = []

    filters = {}
    raw_f = cfg.get("filters") if isinstance(cfg.get("filters"), dict) else {}
    for k in FILTER_KEYS:
        v = raw_f.get(k)
        if v in (None, "", False):
            continue
        filters[k] = str(v)[:200]
    if filters.get("status") and filters["status"] not in STATUSES and filters["status"] != "__none__":
        errors.append("Filtro de status inválido.")
    if filters.get("dummy") and filters["dummy"] not in ("exclude", "include", "only"):
        filters.pop("dummy")

    advanced = cfg.get("advanced") if has_conditions(cfg.get("advanced")) else None
    if advanced:
        errors += validate_conditions(advanced, "Filtros avanzados", ctx, required=False, obj="company")

    cols, seen = [], set()
    for c in cfg.get("columns") or []:
        if isinstance(c, str) and c not in seen and (c in FIELDS_BY_KEY or c in EXTRA_COLUMNS):
            cols.append(c)
            seen.add(c)
    if "name" in seen:
        cols.remove("name")
    cols.insert(0, "name")  # el nombre va siempre primero: es el link a la ficha

    sort = cfg.get("sort") if parse_sort(cfg.get("sort")) else None
    try:
        page_size = int(cfg.get("page_size") or 25)
    except (TypeError, ValueError):
        page_size = 25
    if page_size not in PAGE_SIZES:
        page_size = 25

    if errors:
        raise InvalidWorkflow(errors)
    out = {"filters": filters, "advanced": advanced, "columns": cols, "sort": sort, "page_size": page_size}
    if segment is not None:
        out["segment_ids"] = segment
    return out


def _clean_name(name) -> str:
    name = (name or "").strip()[:MAX_NAME]
    if not name:
        raise InvalidWorkflow(["Ponele un nombre a la vista."])
    return name


def _row(r, email: str) -> dict:
    d = dict(r)
    normalize_tree(d.get("config"))  # filtros guardados con los operadores de antes
    d["mine"] = d["owner_email"] == email
    return d


def get_view(cur, view_id: int) -> dict | None:
    cur.execute("SELECT * FROM prospect_saved_views WHERE id = %s", (view_id,))
    r = cur.fetchone()
    return dict(r) if r else None


def _visible_ids(cur, email: str) -> set[int]:
    """Vistas de EMPRESAS que puede poner en sus pestañas (las de contacto van aparte)."""
    cur.execute("SELECT id FROM prospect_saved_views WHERE (owner_email = %s OR shared) AND object = 'company'", (email,))
    return {r["id"] for r in cur.fetchall()}


def segment_ids_of(cur, email: str, view_id, obj: str) -> list[int]:
    """Los registros de un segmento, si la vista es de esta persona o compartida y del
    objeto pedido. Cualquier otra cosa da la lista vacía (la tabla sale vacía, no entera)."""
    try:
        view_id = int(view_id)
    except (TypeError, ValueError):
        return []
    cur.execute(
        "SELECT config FROM prospect_saved_views WHERE id = %s AND object = %s AND (owner_email = %s OR shared)",
        (view_id, obj, email),
    )
    r = cur.fetchone()
    ids = ((r or {}).get("config") or {}).get("segment_ids")
    return [int(x) for x in ids] if isinstance(ids, list) else []


def list_for(cur, email: str) -> dict:
    cur.execute(
        """
        SELECT v.*,
               COALESCE((SELECT u.user_name FROM users u
                          WHERE LOWER(TRIM(u.email_vintti)) = v.owner_email LIMIT 1), v.owner_email) AS owner_name
          FROM prospect_saved_views v
         WHERE v.owner_email = %s OR v.shared
         ORDER BY v.created_at, v.id
        """,
        (email,),
    )
    views = [_row(r, email) for r in cur.fetchall()]
    company = {v["id"] for v in views if v.get("object", "company") == "company"}
    cur.execute("SELECT contact_tabs FROM prospect_view_prefs WHERE user_email = %s", (email,))
    r = cur.fetchone()
    return {"views": views, "tabs": get_tabs(cur, email, company, views),
            "contact_tabs": (r or {}).get("contact_tabs") or []}


def get_tabs(cur, email: str, visible: set[int] | None = None, views: list | None = None) -> list[str]:
    if visible is None:
        visible = _visible_ids(cur, email)
    cur.execute("SELECT tabs FROM prospect_view_prefs WHERE user_email = %s", (email,))
    r = cur.fetchone()
    if r is None or r["tabs"] is None:
        own = [v["id"] for v in (views or []) if v["owner_email"] == email and v.get("object", "company") == "company"]
        if views is None:
            cur.execute("SELECT id FROM prospect_saved_views WHERE owner_email = %s AND object = 'company' ORDER BY created_at, id", (email,))
            own = [x["id"] for x in cur.fetchall()]
        return SYSTEM_TABS + [f"v:{i}" for i in own]
    # Una vista borrada o que dejó de compartirse se cae sola.
    return [t for t in r["tabs"] if t in SYSTEM_TABS or (t.startswith("v:") and _tab_id(t) in visible)]


def _tab_id(t: str) -> int | None:
    try:
        return int(t[2:])
    except ValueError:
        return None


def set_tabs(cur, email: str, tabs) -> list[str]:
    if not isinstance(tabs, list):
        raise InvalidWorkflow(["Formato inválido."])
    visible = _visible_ids(cur, email)
    out = []
    for t in tabs:
        if not isinstance(t, str) or t in out:
            continue
        if t in SYSTEM_TABS or (t.startswith("v:") and _tab_id(t) in visible):
            out.append(t)
    cur.execute(
        """
        INSERT INTO prospect_view_prefs (user_email, tabs, updated_at) VALUES (%s, %s, NOW())
        ON CONFLICT (user_email) DO UPDATE SET tabs = EXCLUDED.tabs, updated_at = NOW()
        """,
        (email, Json(out)),
    )
    return out


def set_contact_tabs(cur, email: str, ids) -> list[int]:
    """Orden de la tira de vistas de contactos. Sólo ids de vistas de contacto que ve."""
    if not isinstance(ids, list):
        raise InvalidWorkflow(["Formato inválido."])
    cur.execute("SELECT id FROM prospect_saved_views WHERE (owner_email = %s OR shared) AND object = 'contact'", (email,))
    visible = {r["id"] for r in cur.fetchall()}
    out = []
    for x in ids:
        if str(x).isdigit() and int(x) in visible and int(x) not in out:
            out.append(int(x))
    cur.execute(
        """
        INSERT INTO prospect_view_prefs (user_email, contact_tabs, updated_at) VALUES (%s, %s, NOW())
        ON CONFLICT (user_email) DO UPDATE SET contact_tabs = EXCLUDED.contact_tabs, updated_at = NOW()
        """,
        (email, Json(out)),
    )
    return out


def create(cur, email: str, body: dict, ctx) -> dict:
    cur.execute("SELECT COUNT(*) AS n FROM prospect_saved_views WHERE owner_email = %s", (email,))
    if cur.fetchone()["n"] >= MAX_VIEWS:
        raise InvalidWorkflow([f"Máximo {MAX_VIEWS} vistas por persona."])
    name = _clean_name(body.get("name"))
    obj = body.get("object") or "company"
    if obj not in OBJECTS:
        raise InvalidWorkflow(["Objeto inválido."])
    cfg = clean_config(body.get("config"), ctx, obj)
    tabs = get_tabs(cur, email) if obj == "company" else None  # antes del INSERT: si era NULL, fija el default sin la nueva
    cur.execute(
        """
        INSERT INTO prospect_saved_views (owner_email, name, config, shared, object)
        VALUES (%s, %s, %s, %s, %s) RETURNING *
        """,
        (email, name, Json(cfg), bool(body.get("shared")), obj),
    )
    view = _row(cur.fetchone(), email)
    if obj == "company":
        set_tabs(cur, email, tabs + [f"v:{view['id']}"])
    return view


def update(cur, email: str, view_id: int, body: dict, ctx, existing: dict | None = None) -> dict:
    existing = existing or get_view(cur, view_id) or {}
    obj = existing.get("object") or "company"
    sets, params = [], []
    if "name" in body:
        sets.append("name = %s")
        params.append(_clean_name(body.get("name")))
    if "config" in body:
        cfg = clean_config(body.get("config"), ctx, obj)
        # Guardar columnas o filtros no puede convertir un segmento en «todos».
        old_seg = (existing.get("config") or {}).get("segment_ids")
        if "segment_ids" not in cfg and isinstance(old_seg, list):
            cfg["segment_ids"] = old_seg
        sets.append("config = %s")
        params.append(Json(cfg))
    if "shared" in body:
        sets.append("shared = %s")
        params.append(bool(body.get("shared")))
    if not sets:
        raise InvalidWorkflow(["Nada para guardar."])
    cur.execute(
        f"UPDATE prospect_saved_views SET {', '.join(sets)}, updated_at = NOW() "
        "WHERE id = %s AND owner_email = %s RETURNING *",
        params + [view_id, email],
    )
    r = cur.fetchone()
    return _row(r, email) if r else None


def delete(cur, email: str, view_id: int) -> bool:
    cur.execute("DELETE FROM prospect_saved_views WHERE id = %s AND owner_email = %s", (view_id, email))
    return cur.rowcount > 0
