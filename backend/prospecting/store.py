"""Tablas del CRM de prospección y todo lo que las escribe.

Esquema autocreado (`CREATE TABLE IF NOT EXISTS`), sin migración a mano: igual que
staffing_extra / cv_reviews. Tres tablas:

  * `prospect_companies`       — una fila por empresa.
  * `prospect_company_events`  — historial: quién (persona, Clay o workflow) cambió
                                 qué campo y de qué valor a cuál. Sin esto no hay forma
                                 de auditar un workflow.
  * `prospect_workflow_runs`   — cada corrida de un workflow (dry run incluido).

Ojo con dos trampas ya conocidas del repo:
  * un `%` literal en el SQL (incluso en un comentario) rompe psycopg2: los patrones
    de ILIKE van siempre como parámetro.
  * desempaquetar un RealDictCursor devuelve las CLAVES, no los valores.
"""
from __future__ import annotations

import random
import re
import unicodedata
from datetime import date, datetime, timedelta

from psycopg2.extras import Json

from prospecting.constants import (
    ACTIONS,
    BRANCHES,
    DELAYS,
    EVENTS,
    SCHEDULES,
    TRIGGERS,
    WEEKDAYS,
    ADMIN_EMAILS,
    AUTOMATION_REAL_DATA,
    DEFAULT_WORKFLOWS,
    EDITABLE_FIELDS,
    FIELDS,
    OPERATORS,
    OPERATORS_BY_TYPE,
    WORKFLOW_EDITORS,
    BDR_FIELDS,
    BDR_ROLE_PATTERN,
    CLAY_FIELDS,
    NOT_ICP_REASONS,
    SIZES,
    STATUS_DQL,
    STATUS_IN_PROGRESS,
    STATUS_RECYCLED,
    STATUSES,
)

# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
_SCHEMA_READY = False


def ensure_schema(cur) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_companies (
            id                        BIGSERIAL PRIMARY KEY,
            clay_record_id            TEXT,
            domain                    TEXT,
            name                      TEXT NOT NULL,
            website                   TEXT,
            linkedin_url              TEXT,
            description               TEXT,
            industry                  TEXT,
            keywords                  TEXT,
            technologies              TEXT,
            job_types                 TEXT,
            open_jobs                 INTEGER,
            founded_year              INTEGER,
            size                      TEXT,
            city                      TEXT,
            state                     TEXT,
            country                   TEXT,
            lead_source               TEXT,
            week_label                TEXT,
            prospecting_status        TEXT,
            prospecting_owner_email   TEXT,
            prospecting_owner_apollo  TEXT,
            prospecting_start_date    DATE,
            not_icp_reason            TEXT,
            is_dummy                  BOOLEAN NOT NULL DEFAULT FALSE,
            raw_payload               JSONB,
            created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_prospect_companies_clay
          ON prospect_companies (clay_record_id)
          WHERE clay_record_id IS NOT NULL
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_prospect_companies_domain
          ON prospect_companies (domain)
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_prospect_companies_owner_week
          ON prospect_companies (prospecting_owner_email, week_label)
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_company_events (
            id          BIGSERIAL PRIMARY KEY,
            company_id  BIGINT NOT NULL REFERENCES prospect_companies(id) ON DELETE CASCADE,
            actor       TEXT,
            source      TEXT NOT NULL,
            field       TEXT,
            old_value   TEXT,
            new_value   TEXT,
            at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_prospect_company_events_company
          ON prospect_company_events (company_id, at DESC)
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_workflow_runs (
            id            BIGSERIAL PRIMARY KEY,
            workflow_key  TEXT NOT NULL,
            as_of         DATE NOT NULL,
            dry_run       BOOLEAN NOT NULL,
            only_dummy    BOOLEAN NOT NULL DEFAULT FALSE,
            triggered_by  TEXT,
            affected      INTEGER NOT NULL DEFAULT 0,
            details       JSONB,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # Columnas agregadas después de la primera versión: la tabla ya existe en RDS,
    # así que el CREATE de arriba no las suma — van acá.
    # "Id de la empresa" de la planilla es el id de HubSpot: se guarda para la
    # migración (cruzar lo importado con HubSpot), no es la clave del Hub.
    cur.execute("ALTER TABLE prospect_companies ADD COLUMN IF NOT EXISTS hubspot_company_id TEXT")

    # Workflows editables desde la página (ver prospecting/rules.py).
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_workflows (
            id           BIGSERIAL PRIMARY KEY,
            name         TEXT NOT NULL,
            description  TEXT,
            enabled      BOOLEAN NOT NULL DEFAULT FALSE,
            reenroll     BOOLEAN NOT NULL DEFAULT TRUE,
            conditions   JSONB NOT NULL,
            actions      JSONB NOT NULL,
            created_by   TEXT,
            updated_by   TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # Reinscripción apagada = una empresa entra una sola vez: acá queda anotada.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_workflow_enrollments (
            workflow_id  BIGINT NOT NULL REFERENCES prospect_workflows(id) ON DELETE CASCADE,
            company_id   BIGINT NOT NULL REFERENCES prospect_companies(id) ON DELETE CASCADE,
            enrolled_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (workflow_id, company_id)
        )
        """
    )
    cur.execute("ALTER TABLE prospect_workflow_runs ADD COLUMN IF NOT EXISTS workflow_id BIGINT")
    # La tabla de arriba (prospect_workflow_enrollments) era de la primera versión
    # (sin estado). Queda sin uso: el motor con esperas y ramas usa las de abajo.

    # Motor con estado (prospecting/engine.py). Un workflow pasa a ser
    # disparador + grafo de pasos; `conditions` / `actions` quedan para los
    # workflows de la versión anterior, que workflows.normalize() convierte.
    for col in ("trigger", "steps", "unenroll", "goal", "settings"):
        cur.execute(f"ALTER TABLE prospect_workflows ADD COLUMN IF NOT EXISTS {col} JSONB")
    cur.execute("ALTER TABLE prospect_workflows ALTER COLUMN conditions DROP NOT NULL")
    cur.execute("ALTER TABLE prospect_workflows ALTER COLUMN actions DROP NOT NULL")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_wf_enrollments (
            id             BIGSERIAL PRIMARY KEY,
            workflow_id    BIGINT NOT NULL REFERENCES prospect_workflows(id) ON DELETE CASCADE,
            company_id     BIGINT NOT NULL REFERENCES prospect_companies(id) ON DELETE CASCADE,
            status         TEXT NOT NULL,          -- active | waiting | completed | unenrolled | goal_met | failed
            current_node   TEXT,
            wake_at        TIMESTAMPTZ,
            wait_deadline  TIMESTAMPTZ,            -- espera "hasta que se cumpla algo"
            source         TEXT,                   -- trigger | manual | workflow:<id> | event | schedule
            enrolled_by    TEXT,
            enrolled_at    TIMESTAMPTZ NOT NULL,
            finished_at    TIMESTAMPTZ,
            last_error     TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_prospect_wf_enrollments_due
          ON prospect_wf_enrollments (wake_at)
          WHERE status IN ('active', 'waiting')
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_prospect_wf_enrollments_wf_company
          ON prospect_wf_enrollments (workflow_id, company_id)
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_wf_step_log (
            id             BIGSERIAL PRIMARY KEY,
            enrollment_id  BIGINT NOT NULL REFERENCES prospect_wf_enrollments(id) ON DELETE CASCADE,
            node_id        TEXT,
            kind           TEXT NOT NULL,           -- enrolled | action | delay | branch | wake | finished | error ...
            summary        TEXT,
            detail         JSONB,
            ok             BOOLEAN NOT NULL DEFAULT TRUE,
            at             TIMESTAMPTZ NOT NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_prospect_wf_step_log_enr ON prospect_wf_step_log (enrollment_id, id)"
    )
    # Memoria de "ya cumplía": se inscribe sólo en la transición no cumple -> cumple,
    # que es como reinscribe HubSpot.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_wf_match_state (
            workflow_id  BIGINT NOT NULL REFERENCES prospect_workflows(id) ON DELETE CASCADE,
            company_id   BIGINT NOT NULL REFERENCES prospect_companies(id) ON DELETE CASCADE,
            matching     BOOLEAN NOT NULL,
            changed_at   TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (workflow_id, company_id)
        )
        """
    )
    # Turno del reparto entre BDRs, por workflow y paso.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_wf_rotation (
            workflow_id  BIGINT NOT NULL REFERENCES prospect_workflows(id) ON DELETE CASCADE,
            node_id      TEXT NOT NULL,
            last_index   INTEGER NOT NULL,
            PRIMARY KEY (workflow_id, node_id)
        )
        """
    )
    # Última vez que disparó un workflow por horario.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_wf_schedule_state (
            workflow_id  BIGINT PRIMARY KEY REFERENCES prospect_workflows(id) ON DELETE CASCADE,
            last_fired   TIMESTAMPTZ NOT NULL
        )
        """
    )
    _seed_default_workflows(cur)
    _SCHEMA_READY = True


def _seed_default_workflows(cur) -> None:
    """Siembra el workflow que vino de HubSpot sólo si la tabla NUNCA tuvo filas.

    Se mira la secuencia y no sólo si está vacía: si alguien borra todos los
    workflows a propósito, no tienen que reaparecer en el próximo arranque.
    """
    cur.execute("SELECT is_called FROM prospect_workflows_id_seq")
    if cur.fetchone()["is_called"]:
        return
    for wf in DEFAULT_WORKFLOWS:
        cur.execute(
            """
            INSERT INTO prospect_workflows
                (name, description, enabled, reenroll, trigger, steps, settings, created_by, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'system', 'system')
            """,
            (wf["name"], wf["description"], wf["enabled"], wf["reenroll"],
             Json(wf["trigger"]), Json(wf["steps"]), Json({})),
        )


# --------------------------------------------------------------------------- #
# Acceso: rol BDR en `users.role` (texto libre) + la owner siempre
# --------------------------------------------------------------------------- #
def list_bdrs(cur) -> list[dict]:
    """BDRs activos + los admins (pgonzales siempre)."""
    cur.execute(
        """
        SELECT LOWER(TRIM(u.email_vintti)) AS email, u.user_name AS name, u.role
          FROM users u
          LEFT JOIN admin_user_access aua ON aua.user_id = u.user_id
         WHERE COALESCE(aua.is_active, TRUE)
           AND NULLIF(TRIM(u.email_vintti), '') IS NOT NULL
           AND (UPPER(COALESCE(u.role, '')) LIKE %s
                OR LOWER(TRIM(u.email_vintti)) = ANY(%s))
         ORDER BY LOWER(u.user_name)
        """,
        (BDR_ROLE_PATTERN, list(ADMIN_EMAILS)),
    )
    return [dict(r) for r in cur.fetchall()]


def has_access(cur, email: str) -> bool:
    email = (email or "").strip().lower()
    if not email:
        return False
    if email in ADMIN_EMAILS or email in WORKFLOW_EDITORS:
        return True
    return any(b["email"] == email for b in list_bdrs(cur))


# --------------------------------------------------------------------------- #
# Normalización del payload de Clay
# --------------------------------------------------------------------------- #
def _norm_key(k: str) -> str:
    k = unicodedata.normalize("NFKD", str(k)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", k.lower()).strip("_")


# Clave normalizada del JSON de Clay -> columna. Acepta el snake_case que
# documentamos para la columna "HTTP API" de Clay y también los nombres de la
# planilla de propiedades de HubSpot, para que el mapeo en Clay sea a ojo.
_ALIASES = {
    "name": ["name", "company_name", "nombre_de_la_empresa", "company"],
    "clay_record_id": ["clay_record_id", "clay_id", "record_id"],
    "hubspot_company_id": ["hubspot_company_id", "hubspot_id", "id_de_la_empresa", "record_id_hubspot"],
    "website": ["website", "url_del_sitio_web", "domain", "company_domain", "url"],
    "linkedin_url": ["linkedin_url", "linkedin", "pagina_corporativa_de_linkedin", "company_linkedin_url"],
    "description": ["description", "descripcion"],
    "industry": ["industry", "industria"],
    "keywords": ["keywords", "keywords_of_the_company"],
    "technologies": ["technologies", "tech_stack"],
    "job_types": ["job_types", "tipo_de_vacantes"],
    "open_jobs": ["open_jobs", "numero_de_vacantes_abiertas", "job_openings"],
    "founded_year": ["founded_year", "founded"],
    "size": ["size", "company_size", "employee_count_range"],
    "city": ["city", "ciudad"],
    "state": ["state", "estado"],
    "country": ["country", "pais"],
    "lead_source": ["lead_source"],
    "week_label": ["week_label", "semana", "week"],
    "prospecting_status": ["prospecting_status"],
    "prospecting_owner_email": ["prospecting_owner_email", "prospecting_owner", "prospecting_owner_hubspot", "owner_email"],
    "prospecting_owner_apollo": ["prospecting_owner_apollo"],
    "prospecting_start_date": ["prospecting_start_date"],
    "not_icp_reason": ["not_icp_reason"],
}
_ALIAS_TO_COL = {alias: col for col, aliases in _ALIASES.items() for alias in aliases}


def normalize_domain(website: str | None) -> str | None:
    if not website:
        return None
    d = str(website).strip().lower()
    d = re.sub(r"^[a-z]+://", "", d)
    d = d.split("/")[0].split("?")[0].split("#")[0]
    if d.startswith("www."):
        d = d[4:]
    return d or None


def _to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _to_date(v):
    if not v:
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _clean_text(v):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        v = ", ".join(str(x) for x in v if x not in (None, ""))
    s = str(v).strip()
    return s or None


def clean_value(col: str, v):
    if col in ("open_jobs", "founded_year"):
        return _to_int(v)
    if col == "prospecting_start_date":
        return _to_date(v)
    if col == "prospecting_owner_email":
        s = _clean_text(v)
        return s.lower() if s else None
    if col == "week_label":
        s = _clean_text(v)
        # "39" -> "Semana 39", igual que lo cargaban en HubSpot.
        if s and s.isdigit():
            s = f"Semana {int(s)}"
        return s
    return _clean_text(v)


def map_clay_payload(payload: dict) -> dict:
    out: dict = {}
    for k, v in (payload or {}).items():
        col = _ALIAS_TO_COL.get(_norm_key(k))
        if col and col not in out:
            out[col] = clean_value(col, v)
    return out


# --------------------------------------------------------------------------- #
# Escrituras
# --------------------------------------------------------------------------- #
def _fmt(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v)


def log_event(cur, company_id: int, source: str, actor: str | None,
              field: str | None = None, old=None, new=None) -> None:
    cur.execute(
        """
        INSERT INTO prospect_company_events (company_id, actor, source, field, old_value, new_value)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (company_id, actor, source, field, _fmt(old), _fmt(new)),
    )


def upsert_from_clay(cur, payload: dict, is_dummy: bool = False) -> dict:
    """Crea o actualiza una empresa con lo que manda Clay.

    Match por `clay_record_id`; si no viene o no matchea, por dominio. Los campos
    de enriquecimiento (CLAY_FIELDS) se actualizan siempre que Clay mande un valor;
    los que trabaja el BDR (BDR_FIELDS) sólo se rellenan si están vacíos: un
    re-envío de Clay nunca deshace lo que hizo una persona o un workflow.
    """
    data = map_clay_payload(payload)
    if not data.get("name"):
        raise ValueError("Falta el nombre de la empresa (name / company_name).")
    domain = normalize_domain(data.get("website"))
    clay_id = data.get("clay_record_id")

    existing = None
    if clay_id:
        cur.execute("SELECT * FROM prospect_companies WHERE clay_record_id = %s", (clay_id,))
        existing = cur.fetchone()
    if existing is None and domain:
        cur.execute(
            "SELECT * FROM prospect_companies WHERE domain = %s ORDER BY id LIMIT 1",
            (domain,),
        )
        existing = cur.fetchone()

    if existing is None:
        cols = ["name", "clay_record_id", "domain", "is_dummy", "raw_payload"]
        vals = [data["name"], clay_id, domain, is_dummy, Json(payload)]
        for c in CLAY_FIELDS + BDR_FIELDS:
            if c != "name" and data.get(c) is not None:
                cols.append(c)
                vals.append(data[c])
        if "lead_source" not in cols:
            cols.append("lead_source")
            vals.append("Clay")
        cur.execute(
            f"INSERT INTO prospect_companies ({', '.join(cols)}) "
            f"VALUES ({', '.join(['%s'] * len(vals))}) RETURNING id",
            vals,
        )
        new_id = cur.fetchone()["id"]
        log_event(cur, new_id, "clay", None, None, None, "created")
        return {"id": new_id, "action": "created"}

    sets, vals, changes = [], [], []
    for c in CLAY_FIELDS:
        v = data.get(c)
        if v is not None and v != existing.get(c):
            sets.append(f"{c} = %s")
            vals.append(v)
            changes.append((c, existing.get(c), v))
    for c in BDR_FIELDS:
        v = data.get(c)
        cur_v = existing.get(c)
        if v is not None and (cur_v is None or cur_v == ""):
            sets.append(f"{c} = %s")
            vals.append(v)
            changes.append((c, cur_v, v))
    if clay_id and not existing.get("clay_record_id"):
        sets.append("clay_record_id = %s")
        vals.append(clay_id)
    if domain and not existing.get("domain"):
        sets.append("domain = %s")
        vals.append(domain)
    sets.append("raw_payload = %s")
    vals.append(Json(payload))
    sets.append("updated_at = NOW()")
    cur.execute(
        f"UPDATE prospect_companies SET {', '.join(sets)} WHERE id = %s",
        vals + [existing["id"]],
    )
    for field, old, new in changes:
        log_event(cur, existing["id"], "clay", None, field, old, new)
    return {"id": existing["id"], "action": "updated", "changed": [c[0] for c in changes],
            "changes_detail": [{"field": f, "old": o, "new": n} for f, o, n in changes]}


def update_company(cur, company_id: int, patch: dict, actor: str, source: str = "user") -> dict | None:
    """Aplica `patch` (ya filtrado a columnas editables) y deja un evento por campo.

    La fila devuelta trae `_changes` ([{field, old, new}]): con eso se disparan los
    workflows "cuando cambia una propiedad" (engine.emit_event)."""
    cur.execute("SELECT * FROM prospect_companies WHERE id = %s FOR UPDATE", (company_id,))
    row = cur.fetchone()
    if row is None:
        return None
    sets, vals, changes = [], [], []
    for col, raw in patch.items():
        v = clean_value(col, raw)
        if v != row.get(col):
            sets.append(f"{col} = %s")
            vals.append(v)
            changes.append((col, row.get(col), v))
    if not sets:
        return {**dict(row), "_changes": []}
    sets.append("updated_at = NOW()")
    cur.execute(
        f"UPDATE prospect_companies SET {', '.join(sets)} WHERE id = %s RETURNING *",
        vals + [company_id],
    )
    updated = cur.fetchone()
    for col, old, new in changes:
        log_event(cur, company_id, source, actor, col, old, new)
    return {**dict(updated), "_changes": [{"field": f, "old": o, "new": n} for f, o, n in changes]}


# --------------------------------------------------------------------------- #
# Lecturas
# --------------------------------------------------------------------------- #
LIST_COLUMNS = """
    id, hubspot_company_id, name, domain, website, linkedin_url, description, industry,
    keywords, technologies, job_types, size, city, state, country,
    open_jobs, founded_year, lead_source, week_label, prospecting_status,
    prospecting_owner_email, prospecting_owner_apollo, prospecting_start_date,
    not_icp_reason, is_dummy, created_at, updated_at
"""

SORTS = {
    "created_desc": "created_at DESC, id DESC",
    "created_asc": "created_at ASC, id ASC",
    "name": "LOWER(name) ASC, id ASC",
    "start_asc": "prospecting_start_date ASC NULLS LAST, id ASC",
    "open_jobs_desc": "open_jobs DESC NULLS LAST, id DESC",
    "week_desc": "week_label DESC NULLS LAST, id DESC",
}


def list_companies(cur, f: dict) -> dict:
    where, params = [], []

    dummy = f.get("dummy") or "exclude"
    if dummy == "only":
        where.append("is_dummy")
    elif dummy != "include":
        where.append("NOT is_dummy")

    owner = f.get("owner")
    if owner == "__none__":
        where.append("NULLIF(prospecting_owner_email, '') IS NULL")
    elif owner:
        where.append("prospecting_owner_email = %s")
        params.append(owner.lower())

    week = f.get("week")
    if week == "__none__":
        where.append("NULLIF(week_label, '') IS NULL")
    elif week:
        where.append("week_label = %s")
        params.append(week)

    status = f.get("status")
    if status == "__none__":
        where.append("NULLIF(prospecting_status, '') IS NULL")
    elif status:
        where.append("prospecting_status = %s")
        params.append(status)

    if f.get("start_from"):
        where.append("prospecting_start_date >= %s")
        params.append(_to_date(f["start_from"]))
    if f.get("start_to"):
        where.append("prospecting_start_date <= %s")
        params.append(_to_date(f["start_to"]))

    q = (f.get("q") or "").strip()
    if q:
        where.append("(name ILIKE %s OR domain ILIKE %s OR hubspot_company_id = %s)")
        params += [f"%{q}%", f"%{q}%", q]

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    order = SORTS.get(f.get("sort") or "", SORTS["created_desc"])
    page = max(1, _to_int(f.get("page")) or 1)
    size = min(200, max(10, _to_int(f.get("page_size")) or 50))

    cur.execute(f"SELECT COUNT(*) AS n FROM prospect_companies {where_sql}", params)
    total = cur.fetchone()["n"]
    cur.execute(
        f"SELECT {LIST_COLUMNS} FROM prospect_companies {where_sql} "
        f"ORDER BY {order} LIMIT %s OFFSET %s",
        params + [size, (page - 1) * size],
    )
    rows = [dict(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": size, "rows": rows}


def get_company(cur, company_id: int) -> dict | None:
    cur.execute("SELECT * FROM prospect_companies WHERE id = %s", (company_id,))
    row = cur.fetchone()
    if row is None:
        return None
    row = dict(row)
    cur.execute(
        """
        SELECT actor, source, field, old_value, new_value, at
          FROM prospect_company_events
         WHERE company_id = %s
         ORDER BY at DESC, id DESC
         LIMIT 200
        """,
        (company_id,),
    )
    row["events"] = [dict(r) for r in cur.fetchall()]
    return row


def list_weeks(cur) -> list[str]:
    cur.execute(
        """
        SELECT DISTINCT week_label FROM prospect_companies
         WHERE NULLIF(week_label, '') IS NOT NULL
        """
    )
    weeks = [r["week_label"] for r in cur.fetchall()]

    def key(w):
        m = re.search(r"(\d+)", w)
        return (int(m.group(1)) if m else -1, w)

    return sorted(weeks, key=key, reverse=True)


# --------------------------------------------------------------------------- #
# Datos dummy (para probar workflows sin tocar datos reales)
# --------------------------------------------------------------------------- #
_W1 = ["Blue", "North", "Bright", "Summit", "Green", "Atlas", "Iron", "Nova", "Cedar",
       "Pioneer", "Harbor", "Silver", "Quantum", "Maple", "Vertex", "Coral", "Echo", "Lumen"]
_W2 = ["Path", "Ledger", "Labs", "Partners", "Accounting", "Analytics", "Health", "Logistics",
       "Media", "Capital", "Tax", "Systems", "Works", "Group", "Advisors", "Cloud"]
_INDUSTRIES = ["Accounting", "Software", "Healthcare", "Marketing", "Logistics",
               "Real Estate", "Legal Services", "Financial Services", "E-commerce"]
_TECH = ["HubSpot, Salesforce", "QuickBooks, Xero", "AWS, React", "Shopify, Klaviyo",
         "NetSuite", "Google Workspace, Slack"]
_JOBS = ["Bookkeeper, Accountant", "Customer Support", "Software Engineer",
         "Marketing Coordinator", "Executive Assistant", "Sales Development Rep"]
_PLACES = [("Austin", "TX"), ("Miami", "FL"), ("Chicago", "IL"), ("Denver", "CO"),
           ("New York", "NY"), ("Seattle", "WA"), ("Atlanta", "GA"), ("Boston", "MA")]


def seed_dummies(cur, n: int, owners: list[str], today: date) -> list[int]:
    """Crea `n` empresas `is_dummy` con la forma exacta de un payload de Clay.

    Las In Progress tienen start date entre 10 y 90 días atrás, así que el
    workflow de Recycle a 60 días tiene casos de los dos lados del corte.
    """
    rnd = random.Random()
    owners = owners or sorted(ADMIN_EMAILS)
    iso_week = today.isocalendar()[1]
    weeks = [f"Semana {w}" for w in range(max(1, iso_week - 4), iso_week + 1)]
    ids = []
    for i in range(n):
        name = f"{rnd.choice(_W1)} {rnd.choice(_W2)} (dummy)"
        slug = re.sub(r"[^a-z0-9]+", "", name.lower().replace("(dummy)", ""))
        city, state = rnd.choice(_PLACES)
        roll = rnd.random()
        status, reason, owner, start, week = None, None, None, None, rnd.choice(weeks)
        if roll < 0.55:
            status = STATUS_IN_PROGRESS
            owner = rnd.choice(owners)
            start = today - timedelta(days=rnd.randint(10, 90))
        elif roll < 0.75:
            status = STATUS_DQL
            owner = rnd.choice(owners)
            reason = rnd.choice(NOT_ICP_REASONS[:-1])
            start = today - timedelta(days=rnd.randint(5, 40))
        elif roll < 0.85:
            status = STATUS_RECYCLED
        else:
            week = None  # recién llegada de Clay, sin asignar
        payload = {
            "clay_record_id": f"dummy-{today.isoformat()}-{rnd.randint(100000, 999999)}-{i}",
            "company_name": name,
            "website": f"https://www.{slug}{i}.example.com",
            "linkedin_url": f"https://www.linkedin.com/company/{slug}{i}",
            "description": f"Empresa de prueba generada para testear workflows ({name}).",
            "industry": rnd.choice(_INDUSTRIES),
            "keywords": "outsourcing, remote team, latam",
            "technologies": rnd.choice(_TECH),
            "job_types": rnd.choice(_JOBS),
            "open_jobs": rnd.choice([None, 1, 2, 3, 5, 8, 12, 17, 25, 50]),
            "founded_year": rnd.randint(1985, 2022),
            "size": rnd.choice(SIZES[:5]),
            "city": city,
            "state": state,
            "country": "United States",
            "lead_source": "Clay",
            "semana": week,
            "prospecting_status": status,
            "prospecting_owner_email": owner,
            "prospecting_start_date": start.isoformat() if start else None,
            "not_icp_reason": reason,
        }
        ids.append(upsert_from_clay(cur, payload, is_dummy=True)["id"])
    return ids


def delete_dummies(cur) -> int:
    cur.execute("DELETE FROM prospect_companies WHERE is_dummy")
    return cur.rowcount


def options(cur) -> dict:
    bdrs = list_bdrs(cur)
    return {
        "statuses": STATUSES,
        "not_icp_reasons": NOT_ICP_REASONS,
        "sizes": SIZES,
        "bdrs": bdrs,
        "weeks": list_weeks(cur),
        # Lo que necesita el constructor de workflows de la página.
        "workflow_schema": {
            "fields": [
                {**f, "editable": f["key"] in EDITABLE_FIELDS}
                for f in FIELDS
            ],
            "operators": OPERATORS,
            "operators_by_type": OPERATORS_BY_TYPE,
            "actions": ACTIONS,
            "triggers": TRIGGERS,
            "events": EVENTS,
            "schedules": SCHEDULES,
            "delays": DELAYS,
            "branches": BRANCHES,
            "weekdays": WEEKDAYS,
            "history_fields": sorted(set(EDITABLE_FIELDS) | set(CLAY_FIELDS)),
            # jsonify ordena las claves alfabéticamente: el orden de los menús va aparte.
            "order": {
                "actions": list(ACTIONS), "triggers": list(TRIGGERS), "events": list(EVENTS),
                "schedules": list(SCHEDULES), "delays": list(DELAYS), "branches": list(BRANCHES),
            },
            # Fase de prueba: lo automático sólo toca dummies (ver constants.py).
            "automation_real_data": AUTOMATION_REAL_DATA,
        },
    }

