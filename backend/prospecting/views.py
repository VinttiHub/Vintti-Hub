"""Vistas guardadas de la tabla de empresas, por persona (como las de HubSpot).

Dos tablas, autocreadas desde `store.ensure_schema()`:

  * `prospect_saved_views` — una fila por vista: dueña, nombre, `config` (filtros,
    filtros avanzados, columnas en orden, orden de filas, tamaño de página) y
    `shared`. Privada por defecto; compartida = cualquiera con acceso a Prospecting
    la puede AGREGAR a sus pestañas y duplicar, pero sólo la dueña la edita.
  * `prospect_view_prefs` — por persona, la lista ordenada de pestañas que ve:
    `"sys:<all|mine|unassigned|recycled>"` (las fijas, que se pueden ocultar) y
    `"v:<id>"`. NULL = nunca tocó nada → las 4 fijas + sus vistas.

`config` se valida acá y nunca llega como SQL: las columnas contra el catálogo,
el orden contra `FIELDS`, y los filtros avanzados con `rules.validate_conditions()`
(la misma lista blanca de los workflows).
"""
from __future__ import annotations

from psycopg2.extras import Json

from prospecting.constants import FIELDS_BY_KEY, STATUSES
from prospecting.rules import InvalidWorkflow, has_conditions, validate_conditions

SYSTEM_TABS = ["sys:all", "sys:mine", "sys:unassigned", "sys:recycled"]
# Columnas de la tabla que no son campo (se muestran, no se filtran ni ordenan).
EXTRA_COLUMNS = {"contacts_count"}
FILTER_KEYS = ("owner", "week", "status", "start_from", "start_to", "q", "contact_incomplete", "dummy")
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
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_view_prefs (
            user_email  TEXT PRIMARY KEY,
            tabs        JSONB,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def parse_sort(raw) -> tuple[str, str] | None:
    """`<campo>:<asc|desc>` con un campo del catálogo, o None."""
    if not isinstance(raw, str) or ":" not in raw:
        return None
    key, d = raw.rsplit(":", 1)
    if key in FIELDS_BY_KEY and d in ("asc", "desc"):
        return key, d
    return None


def clean_config(cfg, ctx) -> dict:
    """Valida y normaliza lo que manda la página. Levanta InvalidWorkflow."""
    if not isinstance(cfg, dict):
        cfg = {}
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
    return {"filters": filters, "advanced": advanced, "columns": cols, "sort": sort, "page_size": page_size}


def _clean_name(name) -> str:
    name = (name or "").strip()[:MAX_NAME]
    if not name:
        raise InvalidWorkflow(["Ponele un nombre a la vista."])
    return name


def _row(r, email: str) -> dict:
    d = dict(r)
    d["mine"] = d["owner_email"] == email
    return d


def get_view(cur, view_id: int) -> dict | None:
    cur.execute("SELECT * FROM prospect_saved_views WHERE id = %s", (view_id,))
    r = cur.fetchone()
    return dict(r) if r else None


def _visible_ids(cur, email: str) -> set[int]:
    cur.execute("SELECT id FROM prospect_saved_views WHERE owner_email = %s OR shared", (email,))
    return {r["id"] for r in cur.fetchall()}


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
    return {"views": views, "tabs": get_tabs(cur, email, {v["id"] for v in views}, views)}


def get_tabs(cur, email: str, visible: set[int] | None = None, views: list | None = None) -> list[str]:
    if visible is None:
        visible = _visible_ids(cur, email)
    cur.execute("SELECT tabs FROM prospect_view_prefs WHERE user_email = %s", (email,))
    r = cur.fetchone()
    if r is None or r["tabs"] is None:
        own = [v["id"] for v in (views or []) if v["owner_email"] == email]
        if views is None:
            cur.execute("SELECT id FROM prospect_saved_views WHERE owner_email = %s ORDER BY created_at, id", (email,))
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


def create(cur, email: str, body: dict, ctx) -> dict:
    cur.execute("SELECT COUNT(*) AS n FROM prospect_saved_views WHERE owner_email = %s", (email,))
    if cur.fetchone()["n"] >= MAX_VIEWS:
        raise InvalidWorkflow([f"Máximo {MAX_VIEWS} vistas por persona."])
    name = _clean_name(body.get("name"))
    cfg = clean_config(body.get("config"), ctx)
    tabs = get_tabs(cur, email)  # antes del INSERT: si era NULL, fija el default sin la nueva
    cur.execute(
        """
        INSERT INTO prospect_saved_views (owner_email, name, config, shared)
        VALUES (%s, %s, %s, %s) RETURNING *
        """,
        (email, name, Json(cfg), bool(body.get("shared"))),
    )
    view = _row(cur.fetchone(), email)
    set_tabs(cur, email, tabs + [f"v:{view['id']}"])
    return view


def update(cur, email: str, view_id: int, body: dict, ctx) -> dict:
    sets, params = [], []
    if "name" in body:
        sets.append("name = %s")
        params.append(_clean_name(body.get("name")))
    if "config" in body:
        sets.append("config = %s")
        params.append(Json(clean_config(body.get("config"), ctx)))
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
