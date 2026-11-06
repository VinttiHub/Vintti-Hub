"""Negocios (deals) del CRM de prospección — tablas, lectura y escritura (2026-11-04).

El tercer objeto de Prospecting, después de empresas y contactos: el pipeline de ventas
que hoy vive en HubSpot (*Proceso de Contratación* y *Vintti AI Pipeline*), como tablero
por etapas. Un negocio tiene una empresa (opcional) y N contactos, igual que en HubSpot.

Tablas (autocreadas desde `store.ensure_schema()`):
  * `prospect_deal_stages`   — pipelines y etapas, con label, orden y % ponderado. Se
                               siembran de HubSpot (`seed_stages_from_hubspot`) y, sin
                               HubSpot, de `deal_fields.DEFAULT_STAGES`.
  * `prospect_deals`         — un negocio; propiedades en columnas + `props` JSONB.
  * `prospect_deal_contacts` — contactos asociados.
  * `prospect_company_events.deal_id` — el historial del negocio va al mismo log que el de
    empresas y contactos (así aparece también en la actividad de su empresa). Los filtros
    de historial de EMPRESA excluyen `deal_id` (si no, un cambio de «owner» del negocio
    contaría como cambio de owner de la empresa en un workflow).

El puente a la cuenta / oportunidad del hub vive en `deal_to_hub.py`; acá sólo
`reflect()`, que trae al negocio lo que pasó en su oportunidad.
"""
from __future__ import annotations

from datetime import datetime, timezone

from psycopg2.extras import Json

from prospecting import store
from prospecting.deal_fields import (
    CLOSED_LOST,
    DEAL_COLUMNS,
    DEAL_FIELDS,
    DEAL_FIELDS_BY_KEY,
    DEFAULT_PIPELINES,
    DEFAULT_STAGES,
    HUB_EXTRA_OPTIONS,
    LOST_REASONS,
    OPPORTUNITY_OWNED_STAGES,
    PREFILL,
    STAGE_RANK,
    form_for,
    required_for,
)

BOARD_PER_STAGE = 50


class MissingFields(ValueError):
    """Faltan campos obligatorios para pasar a una etapa (la página abre el popup)."""

    def __init__(self, stage_key: str, missing: list[str]):
        super().__init__("Faltan campos para pasar a esa etapa.")
        self.stage_key = stage_key
        self.missing = missing


# --------------------------------------------------------------------------- #
# Esquema
# --------------------------------------------------------------------------- #
def ensure_schema(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_deal_stages (
            pipeline_key        TEXT NOT NULL,
            pipeline_label      TEXT NOT NULL,
            pipeline_position   INT NOT NULL DEFAULT 0,
            stage_key           TEXT NOT NULL,
            label               TEXT NOT NULL,
            position            INT NOT NULL DEFAULT 0,
            probability         NUMERIC,
            is_closed           BOOLEAN NOT NULL DEFAULT FALSE,
            is_won              BOOLEAN NOT NULL DEFAULT FALSE,
            hubspot_pipeline_id TEXT,
            hubspot_stage_id    TEXT,
            active              BOOLEAN NOT NULL DEFAULT TRUE,
            PRIMARY KEY (pipeline_key, stage_key)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_deals (
            id               BIGSERIAL PRIMARY KEY,
            name             TEXT NOT NULL,
            pipeline_key     TEXT NOT NULL,
            stage_key        TEXT NOT NULL,
            owner_email      TEXT,
            amount           NUMERIC,
            close_date       DATE,
            company_id       BIGINT REFERENCES prospect_companies(id) ON DELETE SET NULL,
            account_id       BIGINT,
            opportunity_id   BIGINT,
            hub_status       TEXT,
            hub_note         JSONB,
            hub_mark_new     BOOLEAN NOT NULL DEFAULT FALSE,
            hubspot_deal_id  TEXT,
            hubspot_seen     JSONB,
            raw_payload      JSONB,
            is_dummy         BOOLEAN NOT NULL DEFAULT FALSE,
            props            JSONB NOT NULL DEFAULT '{}'::jsonb,
            stage_entered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by       TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # Fecha de entrada a cada etapa («Date entered …» de HubSpot), {"<pipeline>:<etapa>": ts}.
    # Guarda la ÚLTIMA entrada, como hs_v2_date_entered_*; se sella en STAMP_STAGE.
    cur.execute("ALTER TABLE prospect_deals ADD COLUMN IF NOT EXISTS stage_dates JSONB NOT NULL DEFAULT '{}'::jsonb")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_prospect_deals_board ON prospect_deals (pipeline_key, stage_key)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_prospect_deals_company ON prospect_deals (company_id)")
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_prospect_deals_hubspot ON prospect_deals (hubspot_deal_id) "
        "WHERE hubspot_deal_id IS NOT NULL"
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_prospect_deals_opportunity ON prospect_deals (opportunity_id) "
        "WHERE opportunity_id IS NOT NULL"
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_deal_contacts (
            deal_id     BIGINT NOT NULL REFERENCES prospect_deals(id) ON DELETE CASCADE,
            contact_id  BIGINT NOT NULL REFERENCES prospect_contacts(id) ON DELETE CASCADE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (deal_id, contact_id)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS ix_prospect_deal_contacts_contact ON prospect_deal_contacts (contact_id)")
    cur.execute("ALTER TABLE prospect_company_events ADD COLUMN IF NOT EXISTS deal_id BIGINT")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_prospect_company_events_deal ON prospect_company_events (deal_id) "
        "WHERE deal_id IS NOT NULL"
    )
    # Opciones de los desplegables tal como están en HubSpot (seed_stages_from_hubspot).
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prospect_deal_field_options (
            field_key         TEXT PRIMARY KEY,
            hubspot_property  TEXT,
            options           JSONB NOT NULL,
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute("SELECT 1 FROM prospect_deal_stages LIMIT 1")
    if cur.fetchone() is None:
        _seed_default_stages(cur)


def _seed_default_stages(cur) -> None:
    for pp, (pkey, plabel) in enumerate(DEFAULT_PIPELINES):
        for pos, (skey, label, prob, closed, won) in enumerate(DEFAULT_STAGES):
            cur.execute(
                """
                INSERT INTO prospect_deal_stages (pipeline_key, pipeline_label, pipeline_position, stage_key,
                                                  label, position, probability, is_closed, is_won)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (pkey, plabel, pp, skey, label, pos, prob, closed, won),
            )


def seed_stages_from_hubspot(cur, client) -> dict:
    """Pipelines y etapas tal como están en HubSpot (labels, orden, % y marcas de cerrado).
    Las etapas que conocemos se guardan con su `stage_key` (intro_call, sql…) — resueltas por
    label con el mismo `resolve_pipeline_stage_map()` del sync de oportunidades —; el resto
    (p. ej. DQL) como `hs_<id>`. Una etapa que ya no está en HubSpot queda `active = FALSE`
    (no se borra: puede haber negocios ahí)."""
    from utils import hubspot_opportunities as hs_opps

    pmap = hs_opps.resolve_pipeline_stage_map(client, force_refresh=True)
    raw = {str(p.get("id")): p for p in client.get_deal_pipelines()}
    report = {"pipelines": [], "warnings": pmap.get("warnings") or []}
    order = {k: i for i, (k, _) in enumerate(DEFAULT_PIPELINES)}
    for pid, entry in (pmap.get("by_pipeline_id") or {}).items():
        pkey = entry["key"]
        stages = sorted((raw.get(pid) or {}).get("stages") or [], key=lambda s: s.get("displayOrder") or 0)
        lost_id = entry.get("closed_lost_stage_id")
        keys = []
        for pos, s in enumerate(stages):
            sid = str(s.get("id"))
            meta = s.get("metadata") or {}
            skey = entry["stage_key_by_id"].get(sid) or (CLOSED_LOST if sid == lost_id else f"hs_{sid}")
            try:
                prob = float(meta.get("probability")) if meta.get("probability") not in (None, "") else None
            except ValueError:
                prob = None
            closed = str(meta.get("isClosed", "")).lower() == "true"
            cur.execute(
                """
                INSERT INTO prospect_deal_stages (pipeline_key, pipeline_label, pipeline_position, stage_key, label,
                                                  position, probability, is_closed, is_won, hubspot_pipeline_id,
                                                  hubspot_stage_id, active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (pipeline_key, stage_key) DO UPDATE SET
                    pipeline_label = EXCLUDED.pipeline_label, pipeline_position = EXCLUDED.pipeline_position,
                    label = EXCLUDED.label, position = EXCLUDED.position, probability = EXCLUDED.probability,
                    is_closed = EXCLUDED.is_closed, is_won = EXCLUDED.is_won,
                    hubspot_pipeline_id = EXCLUDED.hubspot_pipeline_id,
                    hubspot_stage_id = EXCLUDED.hubspot_stage_id, active = TRUE
                """,
                (pkey, entry["label"], order.get(pkey, 9), skey, s.get("label") or skey, pos, prob, closed,
                 closed and prob == 1.0, pid, sid),
            )
            keys.append(skey)
        if keys:
            cur.execute(
                "UPDATE prospect_deal_stages SET active = FALSE WHERE pipeline_key = %s AND NOT (stage_key = ANY(%s))",
                (pkey, keys),
            )
        report["pipelines"].append({"key": pkey, "label": entry["label"], "hubspot_id": pid, "stages": keys,
                                    "sin_resolver": entry.get("unresolved")})
    report["opciones"] = seed_options_from_hubspot(cur, client)
    return report


def seed_options_from_hubspot(cur, client) -> dict:
    """Opciones de cada desplegable del negocio = las de la propiedad de deal en HubSpot (por
    nombre interno o label, igual que el mapeo de la importación). Devuelve {campo: propiedad}."""
    props = client.get_properties("deals")
    by_norm = {}
    for p in props:
        for k in (p.get("name"), p.get("label")):
            if k:
                by_norm.setdefault(store._norm_key(k), p)
    by_name = {p["name"]: p for p in props}
    out = {}
    for f in DEAL_FIELDS:
        if f["type"] != "enum":
            continue
        prop = next((by_name.get(a) or by_norm.get(store._norm_key(a)) for a in f["hubspot"]
                     if by_name.get(a) or by_norm.get(store._norm_key(a))), None)
        opts = [o.get("label") for o in (prop or {}).get("options") or [] if not o.get("hidden") and o.get("label")]
        if not opts:
            continue
        cur.execute(
            """
            INSERT INTO prospect_deal_field_options (field_key, hubspot_property, options, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (field_key) DO UPDATE SET hubspot_property = EXCLUDED.hubspot_property,
                options = EXCLUDED.options, updated_at = NOW()
            """,
            (f["key"], prop["name"], Json(opts)),
        )
        out[f["key"]] = prop["name"]
    return out


def field_defs(cur) -> list[dict]:
    """El catálogo con las opciones de HubSpot encima de las de fábrica. Un desplegable sin
    opciones (ni de HubSpot ni de fábrica) se carga como texto."""
    cur.execute("SELECT field_key, options FROM prospect_deal_field_options")
    hs = {r["field_key"]: r["options"] for r in cur.fetchall()}
    out = []
    for f in DEAL_FIELDS:
        g = {k: v for k, v in f.items() if k != "hubspot"}
        if f["type"] == "enum":
            opts = list(hs.get(f["key"]) or f.get("options") or [])
            opts += [o for o in HUB_EXTRA_OPTIONS.get(f["key"], []) if o not in opts]
            if opts:
                g["options"] = opts
            else:
                g.pop("options", None)
                g["type"] = "text"
        out.append(g)
    return out


def defs_by_key(cur) -> dict:
    return {f["key"]: f for f in field_defs(cur)}


def pipelines(cur) -> list[dict]:
    cur.execute(
        "SELECT * FROM prospect_deal_stages WHERE active ORDER BY pipeline_position, pipeline_key, position"
    )
    out: dict[str, dict] = {}
    for r in cur.fetchall():
        p = out.setdefault(r["pipeline_key"], {"key": r["pipeline_key"], "label": r["pipeline_label"], "stages": []})
        p["stages"].append({
            "key": r["stage_key"], "label": r["label"],
            "probability": float(r["probability"]) if r["probability"] is not None else None,
            "is_closed": r["is_closed"], "is_won": r["is_won"],
            "required": required_for(r["stage_key"]),
            "form": form_for(r["stage_key"]),
        })
    return list(out.values())


def _stage(cur, pipeline_key: str, stage_key: str) -> dict | None:
    cur.execute("SELECT * FROM prospect_deal_stages WHERE pipeline_key = %s AND stage_key = %s",
                (pipeline_key, stage_key))
    r = cur.fetchone()
    return dict(r) if r else None


def first_stage(cur, pipeline_key: str) -> str | None:
    cur.execute(
        "SELECT stage_key FROM prospect_deal_stages WHERE pipeline_key = %s AND active ORDER BY position LIMIT 1",
        (pipeline_key,),
    )
    r = cur.fetchone()
    return r["stage_key"] if r else None


def rank(stage_key: str | None) -> int | None:
    return STAGE_RANK.get(stage_key or "")


# --------------------------------------------------------------------------- #
# Lectura
# --------------------------------------------------------------------------- #
def _flatten(row) -> dict:
    r = dict(row)
    props = r.pop("props", None) or {}
    r.pop("raw_payload", None)
    r.pop("hubspot_seen", None)
    out = {**props, **r}
    for k in DEAL_COLUMNS:
        out.setdefault(k, None)
    if out.get("amount") is not None:
        out["amount"] = float(out["amount"])
    if out.get("close_date") is not None and hasattr(out["close_date"], "isoformat"):
        out["close_date"] = out["close_date"].isoformat()
    return out


_SELECT = """
    SELECT d.*, c.name AS company_name, s.label AS stage_label, s.probability AS stage_probability,
           s.is_closed AS stage_is_closed, s.is_won AS stage_is_won,
           (SELECT MAX(e.at) FROM prospect_company_events e WHERE e.deal_id = d.id) AS last_activity_at,
           (SELECT json_agg(json_build_object('id', ct.id,
                    'name', COALESCE(NULLIF(TRIM(CONCAT_WS(' ', ct.first_name, ct.last_name)), ''), ct.email),
                    'email', ct.email) ORDER BY dc.created_at)
              FROM prospect_deal_contacts dc JOIN prospect_contacts ct ON ct.id = dc.contact_id
             WHERE dc.deal_id = d.id) AS contacts
      FROM prospect_deals d
      LEFT JOIN prospect_companies c ON c.id = d.company_id
      LEFT JOIN prospect_deal_stages s ON s.pipeline_key = d.pipeline_key AND s.stage_key = d.stage_key
"""


def _row(r) -> dict:
    out = _flatten(r)
    out["contacts"] = r.get("contacts") or []
    if out.get("stage_probability") is not None:
        out["stage_probability"] = float(out["stage_probability"])
    return out


def get_deal(cur, deal_id: int) -> dict | None:
    cur.execute(_SELECT + " WHERE d.id = %s", (deal_id,))
    r = cur.fetchone()
    if r is None:
        return None
    out = _row(r)
    cur.execute(
        """
        SELECT actor, source, field, old_value, new_value, at FROM prospect_company_events
         WHERE deal_id = %s ORDER BY at DESC, id DESC LIMIT 200
        """,
        (deal_id,),
    )
    out["events"] = [dict(e) for e in cur.fetchall()]
    out["opportunity"] = None
    if out.get("opportunity_id"):
        cur.execute(
            """
            SELECT o.opportunity_id, o.opp_stage, o.opp_position_name, o.opp_model, o.opp_sales_lead,
                   a.client_name
              FROM opportunity o LEFT JOIN account a ON a.account_id = o.account_id
             WHERE o.opportunity_id = %s
            """,
            (out["opportunity_id"],),
        )
        o = cur.fetchone()
        out["opportunity"] = dict(o) if o else None
    out["account"] = None
    if out.get("account_id"):
        cur.execute("SELECT account_id, client_name, sql_date FROM account WHERE account_id = %s", (out["account_id"],))
        a = cur.fetchone()
        out["account"] = dict(a) if a else None
    return out


def _where(f: dict) -> tuple[str, list]:
    where, params = [], []
    dummy = f.get("dummy") or "exclude"
    if dummy == "only":
        where.append("d.is_dummy")
    elif dummy != "include":
        where.append("NOT d.is_dummy")
    if f.get("pipeline"):
        where.append("d.pipeline_key = %s")
        params.append(f["pipeline"])
    if f.get("stage"):
        where.append("d.stage_key = %s")
        params.append(f["stage"])
    if f.get("owner") == "__none__":
        where.append("NULLIF(d.owner_email, '') IS NULL")
    elif f.get("owner"):
        where.append("d.owner_email = %s")
        params.append(str(f["owner"]).lower())
    for key, col, op in (("created_from", "d.created_at", ">="), ("created_to", "d.created_at", "<"),
                         ("close_from", "d.close_date", ">="), ("close_to", "d.close_date", "<=")):
        d = store._to_date(f.get(key))
        if d:
            if key == "created_to":
                where.append(f"{col} < (%s::date + 1)")
            elif key == "created_from":
                where.append(f"{col} >= %s::date")
            else:
                where.append(f"{col} {op} %s")
            params.append(d)
    if f.get("company_id"):
        where.append("d.company_id = %s")
        params.append(store._to_int(f["company_id"]))
    if f.get("contact_id"):
        where.append("EXISTS (SELECT 1 FROM prospect_deal_contacts x WHERE x.deal_id = d.id AND x.contact_id = %s)")
        params.append(store._to_int(f["contact_id"]))
    if isinstance(f.get("ids"), list):
        where.append("d.id = ANY(%s)")
        params.append(f["ids"])
    if f.get("waiting"):
        where.append("d.hub_status = 'waiting'")
    q = (f.get("q") or "").strip()
    if q:
        where.append("(d.name ILIKE %s OR c.name ILIKE %s)")
        params += [f"%{q}%"] * 2
    return (("WHERE " + " AND ".join(where)) if where else ""), params


_SORT_EXTRA = {"created_at": "d.created_at", "stage": "s.position", "company": "LOWER(c.name)",
               "last_activity": "(SELECT MAX(e.at) FROM prospect_company_events e WHERE e.deal_id = d.id)"}


def order_sql(sort) -> str:
    if isinstance(sort, str) and ":" in sort:
        key, mode = sort.rsplit(":", 1)
        d = "ASC" if mode == "asc" else "DESC"
        if key in _SORT_EXTRA:
            return f"{_SORT_EXTRA[key]} {d} NULLS LAST, d.id {d}"
        f = DEAL_FIELDS_BY_KEY.get(key)
        if f and mode in ("asc", "desc"):
            if f["storage"] == "col":
                e = f"d.{key}"
            else:
                raw = f"NULLIF(d.props->>'{key}', '')"
                e = (f"(CASE WHEN {raw} ~ '^-?[0-9]+([.][0-9]+)?$' THEN ({raw})::numeric END)"
                     if f["type"] == "number" else f"LOWER({raw})")
            if f["type"] in ("text", "longtext", "enum", "user") and f["storage"] == "col":
                e = f"LOWER(d.{key})"
            return f"{e} {d} NULLS LAST, d.id {d}"
    return "d.created_at DESC, d.id DESC"


def list_deals(cur, f: dict) -> dict:
    where_sql, params = _where(f)
    page = max(1, store._to_int(f.get("page")) or 1)
    size = min(200, max(10, store._to_int(f.get("page_size")) or 25))
    base = (f"FROM prospect_deals d LEFT JOIN prospect_companies c ON c.id = d.company_id "
            f"LEFT JOIN prospect_deal_stages s ON s.pipeline_key = d.pipeline_key AND s.stage_key = d.stage_key "
            f"{where_sql}")
    cur.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM(d.amount), 0) AS amount {base}", params)
    tot = cur.fetchone()
    cur.execute(
        _SELECT + f" {where_sql} ORDER BY {order_sql(f.get('sort'))} LIMIT %s OFFSET %s",
        params + [size, (page - 1) * size],
    )
    return {"total": tot["n"], "amount": float(tot["amount"]), "page": page, "page_size": size,
            "rows": [_row(r) for r in cur.fetchall()]}


def deal_ids(cur, f: dict) -> list[int]:
    where_sql, params = _where(f)
    cur.execute(f"SELECT d.id FROM prospect_deals d LEFT JOIN prospect_companies c ON c.id = d.company_id "
                f"{where_sql} ORDER BY d.id", params)
    return [r["id"] for r in cur.fetchall()]


def board(cur, f: dict) -> dict:
    """Tablero de un pipeline: por etapa, cantidad, total, ponderado y las primeras
    `BOARD_PER_STAGE` tarjetas (`stage` + `offset` = «cargar más» de una columna)."""
    pls = pipelines(cur)
    pipeline = f.get("pipeline") or (pls[0]["key"] if pls else None)
    pl = next((p for p in pls if p["key"] == pipeline), None)
    if pl is None:
        return {"pipelines": pls, "pipeline": None, "columns": []}
    f = {**f, "pipeline": pipeline}
    where_sql, params = _where({k: v for k, v in f.items() if k != "stage"})
    cur.execute(
        f"""
        SELECT d.stage_key, COUNT(*) AS n, COALESCE(SUM(d.amount), 0) AS amount
          FROM prospect_deals d LEFT JOIN prospect_companies c ON c.id = d.company_id {where_sql}
         GROUP BY d.stage_key
        """,
        params,
    )
    totals = {r["stage_key"]: r for r in cur.fetchall()}
    offset = max(0, store._to_int(f.get("offset")) or 0)
    only = f.get("stage")
    cards: dict[str, list] = {}
    stage_keys = [s["key"] for s in pl["stages"]] + [k for k in totals if k not in {s["key"] for s in pl["stages"]}]
    for sk in stage_keys:
        if only and sk != only:
            continue
        w, p = _where({**f, "stage": sk})
        cur.execute(_SELECT + f" {w} ORDER BY {order_sql(f.get('sort'))} LIMIT %s OFFSET %s",
                    p + [BOARD_PER_STAGE, offset if only else 0])
        cards[sk] = [_row(r) for r in cur.fetchall()]
    columns = []
    known = {s["key"]: s for s in pl["stages"]}
    for sk in stage_keys:
        s = known.get(sk) or {"key": sk, "label": sk, "probability": None, "is_closed": False, "is_won": False,
                              "required": [], "inactive": True}
        t = totals.get(sk) or {"n": 0, "amount": 0}
        amount = float(t["amount"] or 0)
        prob = s.get("probability")
        columns.append({**s, "count": t["n"], "amount": amount,
                        "weighted": amount * prob if prob is not None else None,
                        "cards": cards.get(sk, [])})
    return {"pipelines": pls, "pipeline": pipeline, "columns": columns}


def company_deals(cur, company_id: int) -> list[dict]:
    cur.execute(_SELECT + " WHERE d.company_id = %s ORDER BY d.created_at DESC", (company_id,))
    return [_row(r) for r in cur.fetchall()]


def contact_deals(cur, contact_id: int) -> list[dict]:
    cur.execute(
        _SELECT + " WHERE EXISTS (SELECT 1 FROM prospect_deal_contacts x WHERE x.deal_id = d.id AND x.contact_id = %s)"
        " ORDER BY d.created_at DESC",
        (contact_id,),
    )
    return [_row(r) for r in cur.fetchall()]


# --------------------------------------------------------------------------- #
# Escritura
# --------------------------------------------------------------------------- #
def _split(cur, data: dict) -> tuple[dict, dict]:
    defs = defs_by_key(cur)
    cols, props = {}, {}
    for k, v in (data or {}).items():
        f = defs.get(k)
        if not f:
            continue
        val = store.clean_contact_value(f, v)
        if k == "name" and not val:
            raise ValueError("El negocio necesita un nombre.")
        (cols if f["storage"] == "col" else props)[k] = val
    return cols, props


def _log(cur, deal: dict, source: str, actor: str | None, field=None, old=None, new=None) -> None:
    store.log_event(cur, deal.get("company_id"), source, actor, field, old, new, deal_id=deal["id"])


def _log_hub(cur, deal: dict, actor: str | None, what: str) -> None:
    """Evento del puente con el hub: `account:<id>`, `opportunity:<id>`, `opportunity_linked:<id>`…"""
    store.log_event(cur, deal.get("company_id"), "hub", actor, None, None, f"hub_{what}", deal_id=deal["id"])


def lost_before_sql(deal: dict) -> bool:
    """¿El negocio nunca llegó a SQL? (etapa actual y todas por las que pasó, antes de SQL).
    Un negocio sin etapa todavía (borrador del popup) cuenta como antes de SQL."""
    sql = rank("sql")
    stages = [deal.get("stage_key")] + [k.partition(":")[2] for k in (deal.get("stage_dates") or {})]
    ranks = [rank(s) for s in stages if s]
    return all(r is None or r < sql for r in ranks)


def missing_for(deal: dict, stage_key: str) -> list[str]:
    return [k for k in required_for(stage_key, before_sql=lost_before_sql(deal)) if deal.get(k) in (None, "", [])]


# Lead Life (Deal) por etapa (decisión de la owner, 2026-11-06). Etapas de HubSpot sin rank
# (hs_*) no la tocan.
LEAD_LIFE_BY_STAGE = {
    "intro_call": "MQL (AE)", "sql": "SQL (AE)", "deep_dive": "SQL (AE)", "nda_sent": "SQL (AE)",
    "nda_signed": "SQL (AE)", "signed": "SQL (AE)", "closed_won": "Active Client", "closed_lost": "Closed Lost",
}


def after_stage(cur, deal_id: int, pipeline: str, stage: str, actor: str | None) -> None:
    """Lo que se llena solo al entrar a una etapa (sin depender de HubSpot): Lead Life (Deal),
    y en Deep Dive la First Deep Dive Date del negocio (si está vacía) + First / Last Deep Dive
    Date de sus contactos."""
    cur.execute("SELECT * FROM prospect_deals WHERE id = %s", (deal_id,))
    raw = cur.fetchone()
    if raw is None:
        return
    d = _flatten(raw)
    patch = {}
    ll = LEAD_LIFE_BY_STAGE.get(stage)
    if ll and d.get("lead_life_deal") != ll:
        patch["lead_life_deal"] = ll
    if stage == "deep_dive" and not d.get("first_deep_dive_date"):
        patch["first_deep_dive_date"] = ((raw.get("stage_dates") or {}).get(f"{pipeline}:deep_dive")
                                         or datetime.now(timezone.utc).isoformat())
    if patch:
        update_deal(cur, deal_id, patch, actor, source="deal_stage")
    if stage == "deep_dive" or "first_deep_dive_date" in patch:
        from prospecting import prop_sync
        prop_sync.deep_dive_dates_for_contacts(cur, deal_id, actor)


# Sella la entrada a una etapa en stage_dates (parámetro: "<pipeline>:<etapa>").
STAMP_STAGE = "stage_dates = COALESCE(stage_dates, '{}'::jsonb) || jsonb_build_object(%s::text, to_jsonb(NOW()))"


def create_deal(cur, data: dict, actor: str | None, source: str = "user", is_dummy: bool = False,
                check_required: bool = True) -> dict:
    data = dict(data or {})
    pipeline = data.pop("pipeline_key", None) or "hiring"
    stage = data.pop("stage_key", None) or first_stage(cur, pipeline)
    if _stage(cur, pipeline, stage or "") is None:
        raise ValueError("Esa etapa no existe en ese pipeline.")
    company_id = store._to_int(data.pop("company_id", None))
    contact_ids = [store._to_int(x) for x in (data.pop("contact_ids", None) or []) if store._to_int(x)]
    if company_id is not None:
        cur.execute("SELECT id, is_dummy, name FROM prospect_companies WHERE id = %s", (company_id,))
        comp = cur.fetchone()
        if comp is None:
            raise LookupError("company")
        is_dummy = is_dummy or comp["is_dummy"]
        if not data.get("name"):
            data["name"] = comp["name"]
    cols, props = _split(cur, data)
    if not cols.get("name"):
        raise ValueError("El negocio necesita un nombre.")
    if check_required:
        miss = missing_for({**cols, **props}, stage)
        if miss:
            raise MissingFields(stage, miss)
    names = list(cols)
    cur.execute(
        f"""
        INSERT INTO prospect_deals (pipeline_key, stage_key, company_id, is_dummy, props, created_by, stage_dates
                                    {''.join(', ' + c for c in names)})
        VALUES (%s, %s, %s, %s, %s, %s, jsonb_build_object(%s::text, to_jsonb(NOW())) {''.join(', %s' for _ in names)})
        RETURNING *
        """,
        [pipeline, stage, company_id, bool(is_dummy), Json({k: v for k, v in props.items() if v is not None}), actor,
         f"{pipeline}:{stage}"]
        + [cols[c] for c in names],
    )
    row = _flatten(cur.fetchone())
    _log(cur, row, source, actor, None, None, "deal_created")
    _log(cur, row, source, actor, "stage", None, stage)
    for k, v in {**cols, **props}.items():
        if v is not None:
            _log(cur, row, source, actor, k, None, v)
    if contact_ids:
        set_contacts(cur, row["id"], contact_ids, actor, source, log=True)
    else:
        from prospecting import prop_sync
        prop_sync.pull_into_deal(cur, row["id"], actor)
    after_stage(cur, row["id"], pipeline, stage, actor)
    cur.execute("SELECT * FROM prospect_deals WHERE id = %s", (row["id"],))
    return _flatten(cur.fetchone())


def update_deal(cur, deal_id: int, patch: dict, actor: str | None, source: str = "user") -> tuple[dict, list]:
    cur.execute("SELECT * FROM prospect_deals WHERE id = %s FOR UPDATE", (deal_id,))
    raw = cur.fetchone()
    if raw is None:
        raise LookupError("deal")
    before = _flatten(raw)
    cols, props = _split(cur, patch)
    changes = [{"field": k, "old": before.get(k), "new": v} for k, v in {**cols, **props}.items()
               if _same(before.get(k)) != _same(v)]
    if changes:
        new_props = dict(raw["props"] or {})
        for k, v in props.items():
            if v is None:
                new_props.pop(k, None)
            else:
                new_props[k] = v
        sets = [f"{c} = %s" for c in cols] + ["props = %s", "updated_at = NOW()"]
        cur.execute(f"UPDATE prospect_deals SET {', '.join(sets)} WHERE id = %s",
                    [cols[c] for c in cols] + [Json(new_props), deal_id])
        for ch in changes:
            _log(cur, before, source, actor, ch["field"], ch["old"], ch["new"])
        from prospecting import prop_sync
        prop_sync.propagate(cur, "deal", deal_id, changes, actor, source)
    cur.execute("SELECT * FROM prospect_deals WHERE id = %s", (deal_id,))
    return _flatten(cur.fetchone()), changes


def _same(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    try:
        return float(v) if isinstance(v, str) and v.replace(".", "", 1).lstrip("-").isdigit() else v
    except ValueError:
        return v


def move_stage(cur, deal_id: int, stage_key: str, actor: str | None, source: str = "user",
               patch: dict | None = None, check_required: bool = True, pipeline_key: str | None = None) -> dict:
    """Cambia la etapa (y opcionalmente el pipeline). `patch` = los campos del popup, que se
    guardan antes de validar. Levanta MissingFields si faltan obligatorios.
    Devuelve {"deal", "old_stage", "changed"}."""
    if patch:
        update_deal(cur, deal_id, patch, actor, source)
    cur.execute("SELECT * FROM prospect_deals WHERE id = %s FOR UPDATE", (deal_id,))
    raw = cur.fetchone()
    if raw is None:
        raise LookupError("deal")
    deal = _flatten(raw)
    pipeline = pipeline_key or deal["pipeline_key"]
    if _stage(cur, pipeline, stage_key) is None:
        raise ValueError("Esa etapa no existe en ese pipeline.")
    old = deal["stage_key"]
    if old == stage_key and pipeline == deal["pipeline_key"]:
        return {"deal": deal, "old_stage": old, "changed": False}
    if source == "user" and deal.get("opportunity_id") and stage_key in OPPORTUNITY_OWNED_STAGES:
        raise ValueError(
            f"Este negocio ya tiene la oportunidad #{deal['opportunity_id']}: Candidate Signed, Closed Won y "
            "Closed Lost se mueven desde Opportunities (ahí se cargan el hire, el MKT Collab y el motivo). "
            "El negocio se actualiza solo."
        )
    if check_required:
        miss = missing_for(deal, stage_key)
        if miss:
            raise MissingFields(stage_key, miss)
    cur.execute(
        "UPDATE prospect_deals SET stage_key = %s, pipeline_key = %s, stage_entered_at = NOW(), updated_at = NOW(), "
        + STAMP_STAGE + " WHERE id = %s",
        (stage_key, pipeline, f"{pipeline}:{stage_key}", deal_id),
    )
    if pipeline != deal["pipeline_key"]:
        _log(cur, deal, source, actor, "pipeline", deal["pipeline_key"], pipeline)
    _log(cur, deal, source, actor, "stage", old, stage_key)
    after_stage(cur, deal_id, pipeline, stage_key, actor)
    cur.execute("SELECT * FROM prospect_deals WHERE id = %s", (deal_id,))
    return {"deal": _flatten(cur.fetchone()), "old_stage": old, "changed": True}


# --------------------------------------------------------------------------- #
# «Propiedades dependientes» (el popup de cada etapa) + prellenado
# --------------------------------------------------------------------------- #
def _related(cur, company_id, contact_ids) -> tuple[dict, dict]:
    company, contact = {}, {}
    if company_id:
        cur.execute("SELECT * FROM prospect_companies WHERE id = %s", (company_id,))
        company = dict(cur.fetchone() or {})
    ids = [i for i in (contact_ids or []) if i]
    if ids:
        cur.execute("SELECT * FROM prospect_contacts WHERE id = %s", (ids[0],))
        r = cur.fetchone()
        contact = store._flatten_contact(r) if r else {}
    elif company_id:
        cur.execute("SELECT * FROM prospect_contacts WHERE company_id = %s ORDER BY is_primary DESC, created_at LIMIT 1",
                    (company_id,))
        r = cur.fetchone()
        contact = store._flatten_contact(r) if r else {}
    return company, contact


def _prefill_value(f: dict, company: dict, contact: dict):
    for obj, key in PREFILL.get(f["key"], []):
        v = (company if obj == "company" else contact).get(key)
        if isinstance(v, list):
            v = v[0] if len(v) == 1 else None
        if v in (None, ""):
            continue
        try:
            v = store.clean_contact_value(f, v)
        except ValueError:
            continue  # p. ej. una industria de Clay que no está en la lista de HubSpot
        if v not in (None, ""):
            return v
    return None


def stage_form(cur, stage_key: str, deal: dict | None = None, company_id=None, contact_ids=None) -> dict:
    """Los campos que pide la etapa, con el valor del negocio o, si está vacío, el prellenado
    de la empresa / contacto (lo que hace HubSpot en «Propiedades dependientes»)."""
    deal = deal or {}
    if deal.get("id"):
        company_id = deal.get("company_id")
        contact_ids = [c["id"] for c in deal.get("contacts") or []]
    company, contact = _related(cur, company_id, contact_ids)
    defs = defs_by_key(cur)
    form = []
    before_sql = lost_before_sql(deal)
    req = set(required_for(stage_key, before_sql=before_sql))
    keys = [x["key"] for x in form_for(stage_key, before_sql=before_sql)]
    # Role to hire / Model (sin eso no hay oportunidad) sólo se piden si faltan.
    keys += [k for k in req if k not in keys and deal.get(k) in (None, "", [])]
    for k in keys:
        f = defs.get(k)
        if not f:
            continue
        v, pre = deal.get(k), False
        if v in (None, "", []):
            v = _prefill_value(f, company, contact)
            pre = v is not None
        form.append({**f, "required": k in req, "value": v, "prefilled": pre})
    return {"stage_key": stage_key, "fields": form}


def fill_related(cur, deal_id: int, values: dict, actor: str | None) -> list[tuple]:
    """Lo cargado en el negocio rellena los VACÍOS de su empresa y de su (primer) contacto,
    con historial (decisión de la owner). Nunca pisa un valor que ya tienen.
    Devuelve [(obj, record_id, company_id, cambios)] para disparar los workflows."""
    out: list[tuple] = []
    vals = {k: v for k, v in (values or {}).items() if k in PREFILL and v not in (None, "", [])}
    if not vals:
        return out
    cur.execute("SELECT company_id FROM prospect_deals WHERE id = %s", (deal_id,))
    d = cur.fetchone()
    if d is None:
        return out
    cur.execute("SELECT contact_id FROM prospect_deal_contacts WHERE deal_id = %s ORDER BY created_at LIMIT 1",
                (deal_id,))
    r = cur.fetchone()
    company, contact = _related(cur, d["company_id"], [r["contact_id"]] if r else [])
    from prospecting.contact_fields import CONTACT_FIELDS_BY_KEY as CF
    co_patch, ct_patch = {}, {}
    for k, v in vals.items():
        for obj, key in PREFILL[k]:
            if obj == "company" and company and company.get(key) in (None, ""):
                co_patch.setdefault(key, v)
            elif obj == "contact" and contact and contact.get(key) in (None, "", []):
                f = CF.get(key)
                if not f:
                    continue
                val = [v] if f["type"] == "multi" else v
                try:
                    store.clean_contact_value(f, val)
                except ValueError:
                    continue
                ct_patch.setdefault(key, val)
    co_patch.pop("name", None)  # la empresa ya tiene nombre: nunca se renombra desde un negocio
    if co_patch:
        r = store.update_company(cur, company["id"], co_patch, actor, source=f"deal:{deal_id}")
        if r and r.get("_changes"):
            out.append(("company", company["id"], company["id"], r["_changes"]))
    if ct_patch:
        r = store.update_contact(cur, contact["id"], ct_patch, actor, source=f"deal:{deal_id}")
        if r and r.get("_changes"):
            out.append(("contact", contact["id"], contact.get("company_id"), r["_changes"]))
    return out


def set_company(cur, deal_id: int, company_id: int | None, actor: str | None, source: str = "user") -> bool:
    cur.execute("SELECT d.id, d.company_id, c.name FROM prospect_deals d LEFT JOIN prospect_companies c "
                "ON c.id = d.company_id WHERE d.id = %s FOR UPDATE OF d", (deal_id,))
    d = cur.fetchone()
    if d is None:
        raise LookupError("deal")
    if (d["company_id"] or None) == (company_id or None):
        return False
    new_name = None
    if company_id is not None:
        cur.execute("SELECT name FROM prospect_companies WHERE id = %s", (company_id,))
        c = cur.fetchone()
        if c is None:
            raise LookupError("company")
        new_name = c["name"]
    cur.execute("UPDATE prospect_deals SET company_id = %s, updated_at = NOW() WHERE id = %s", (company_id, deal_id))
    # El cambio queda en la actividad de las dos empresas.
    for cid in {d["company_id"], company_id}:
        store.log_event(cur, cid, source, actor, "company", d["name"], new_name, deal_id=deal_id)
    return True


def set_contacts(cur, deal_id: int, contact_ids: list[int], actor: str | None, source: str = "user",
                 log: bool = True) -> dict:
    cur.execute("SELECT id, company_id FROM prospect_deals WHERE id = %s", (deal_id,))
    d = cur.fetchone()
    if d is None:
        raise LookupError("deal")
    want = sorted({int(x) for x in contact_ids if x})
    cur.execute("SELECT contact_id FROM prospect_deal_contacts WHERE deal_id = %s", (deal_id,))
    have = {r["contact_id"] for r in cur.fetchall()}
    add, drop = [x for x in want if x not in have], [x for x in have if x not in want]
    if add:
        cur.execute("SELECT id FROM prospect_contacts WHERE id = ANY(%s)", (add,))
        add = [r["id"] for r in cur.fetchall()]
        for cid in add:
            cur.execute("INSERT INTO prospect_deal_contacts (deal_id, contact_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (deal_id, cid))
    if drop:
        cur.execute("DELETE FROM prospect_deal_contacts WHERE deal_id = %s AND contact_id = ANY(%s)", (deal_id, drop))
    if add:
        from prospecting import prop_sync
        prop_sync.pull_into_deal(cur, deal_id, actor)
    if log and (add or drop):
        names = _contact_names(cur, add + drop)
        if add:
            store.log_event(cur, d["company_id"], source, actor, "contacts", None,
                            ", ".join(names.get(x, f"#{x}") for x in add), deal_id=deal_id)
        if drop:
            store.log_event(cur, d["company_id"], source, actor, "contacts",
                            ", ".join(names.get(x, f"#{x}") for x in drop), None, deal_id=deal_id)
    return {"added": add, "removed": drop}


def _contact_names(cur, ids: list[int]) -> dict:
    if not ids:
        return {}
    cur.execute(
        "SELECT id, COALESCE(NULLIF(TRIM(CONCAT_WS(' ', first_name, last_name)), ''), email) AS n "
        "FROM prospect_contacts WHERE id = ANY(%s)",
        (ids,),
    )
    return {r["id"]: r["n"] for r in cur.fetchall()}


def delete_deal(cur, deal_id: int, actor: str | None) -> bool:
    cur.execute("DELETE FROM prospect_deals WHERE id = %s RETURNING id, company_id, name", (deal_id,))
    r = cur.fetchone()
    if r is None:
        return False
    store.log_event(cur, r["company_id"], "user", actor, None, None, f"deal_deleted:{r['name']}", deal_id=deal_id)
    return True


def delete_dummies(cur) -> int:
    cur.execute("DELETE FROM prospect_deals WHERE is_dummy")
    return cur.rowcount


# --------------------------------------------------------------------------- #
# Oportunidad del hub -> negocio
# --------------------------------------------------------------------------- #
# Etapa del hub (opp_stage) -> etapa del negocio.
HUB_TO_DEAL_STAGE = {
    "deep dive": "deep_dive",
    "nda sent": "nda_sent",
    "sourcing": "nda_signed",
    "interviewing": "nda_signed",
    "negotiating": "nda_signed",
    "signed": "signed",
    "close win": "closed_won",
    "closed lost": CLOSED_LOST,
    "stop": CLOSED_LOST,
}


# Campo lógico de hire_values_for_opportunity() -> campo del negocio.
_HIRE_TO_DEAL = {
    "final_salary": "final_salary", "final_fee": "final_fee", "setup_fee": "setup_fee", "role_hired": "role_hired",
    "price_type": "price_type", "computer": "computer", "candidate_start_date": "candidate_start_date",
    "candidate_end_date": "candidate_end_date", "candidate_address": "candidate_address",
    "candidate_dni": "candidate_dni", "candidate_location": "candidate_location",
    "candidate_signed_date": "candidate_signed_date", "mkt_collab": "mkt_collab",
    "closed_win_date": "closed_win_date", "close_date": "close_date",
}
_ONLY_ON_WIN = {"mkt_collab", "closed_win_date", "close_date"}


def copy_closing_values(cur, deal_id: int) -> int:
    """Signed / Close Win / Closed Lost de la oportunidad -> el negocio, con la MISMA regla con
    que el hub se los empuja a HubSpot (utils/hubspot_push.py): mismos valores
    (`hire_values_for_opportunity`), se pisan todos menos Role Hired (sólo si está vacío), y
    MKT Collab / Closed Win Date / fecha de cierre sólo al ganar. Closed Lost: motivo, detalle
    y fecha. Devuelve cuántos campos cambió."""
    from utils.hubspot_push_values import hire_values_for_opportunity

    cur.execute(
        """
        SELECT d.*, LOWER(BTRIM(o.opp_stage)) AS opp_stage, o.motive_close_lost, o.details_close_lost,
               o.opp_close_date
          FROM prospect_deals d JOIN opportunity o ON o.opportunity_id = d.opportunity_id
         WHERE d.id = %s
        """,
        (deal_id,),
    )
    r = cur.fetchone()
    if r is None:
        return 0
    deal = _flatten(r)
    stage = r["opp_stage"] or ""
    patch = {}
    if stage in ("signed", "close win"):
        vals = (hire_values_for_opportunity(cur, r["opportunity_id"]) or {}).get("valores") or {}
        for src, key in _HIRE_TO_DEAL.items():
            v = vals.get(src)
            if v is None or (src in _ONLY_ON_WIN and stage != "close win"):
                continue
            if key == "role_hired" and deal.get(key) not in (None, ""):
                continue
            patch[key] = v
    elif stage in ("closed lost", "stop"):
        motivo = str(r.get("motive_close_lost") or "").strip()
        hit = next((o for o in LOST_REASONS if o.lower().replace("’", "'") == motivo.lower().replace("’", "'")
                    or o.lower().replace("'", "") == motivo.lower().replace("'", "")), None)
        if hit:
            patch["lost_reason"] = hit
        if str(r.get("details_close_lost") or "").strip():
            patch["lost_reason_detail"] = str(r["details_close_lost"]).strip()
        if r.get("opp_close_date"):
            patch["closed_lost_date"] = str(r["opp_close_date"])[:10]
            patch["close_date"] = str(r["opp_close_date"])[:10]
    if stage == "close win":
        patch.update(_credit_values(cur, r["opportunity_id"], r.get("account_id")))
    if not patch:
        return 0
    try:
        _, changes = update_deal(cur, deal_id, patch, None, source="opportunity")
    except ValueError:
        return 0
    return len(changes)


def _credit_values(cur, opportunity_id: int, account_id) -> dict:
    """Credit Loop? / Credits Won / Credits Expiring Date del Close Win, desde el Credit Loop del
    hub: el crédito que generó ESA oportunidad (utils/credit_loop.create_credit_for_close_win).
    Sin crédito, Credit Loop? sale de `account.credit_loop` (texto Yes/No) si está cargado."""
    cur.execute("SELECT credit_amount, expires_at, status FROM account_credit_loop "
                "WHERE source_opportunity_id = %s AND status <> 'reversed' ORDER BY credit_id DESC LIMIT 1",
                (opportunity_id,))
    c = cur.fetchone()
    if c:
        out = {"credit_loop": True, "credits_expiring_date": str(c["expires_at"])[:10]}
        if c["credit_amount"] is not None:
            out["credits_won"] = float(c["credit_amount"])
        return out
    if account_id:
        cur.execute("SELECT credit_loop FROM account WHERE account_id = %s", (account_id,))
        a = cur.fetchone()
        v = str((a or {}).get("credit_loop") or "").strip().lower()
        if v in ("yes", "true", "si", "sí"):
            return {"credit_loop": True}
        if v in ("no", "false"):
            return {"credit_loop": False}
    return {}


def reflect(cur, deal_ids: list[int] | None = None, pipeline: str | None = None, values: bool = False) -> dict:
    """Trae al negocio lo que pasó en el hub:
      1. ata los negocios de HubSpot a la cuenta / oportunidad que ya tiene su
         `hubspot_deal_id` (las crea el sync de oportunidades de siempre);
      2. alinea la etapa del negocio con la de su oportunidad, **sólo hacia adelante**
         (Sourcing/Interviewing/Negotiating = NDA Signed, Signed = Candidate Signed, Close
         Win = Closed Won). Closed Lost / Stop de la oportunidad cierra el negocio.
    Lo corren el tablero y el cron. Devuelve {"linked", "moved"}."""
    scope, params = "", []
    if deal_ids is not None:
        if not deal_ids:
            return {"linked": 0, "moved": 0, "copied": 0}
        scope = " AND d.id = ANY(%s)"
        params = [deal_ids]
    elif pipeline:
        scope = " AND d.pipeline_key = %s"
        params = [pipeline]
    cur.execute(
        f"""
        UPDATE prospect_deals d SET opportunity_id = o.opportunity_id,
               account_id = COALESCE(d.account_id, o.account_id)
          FROM opportunity o
         WHERE d.opportunity_id IS NULL AND d.hubspot_deal_id IS NOT NULL
           AND NULLIF(o.hubspot_deal_id, '') = d.hubspot_deal_id
           AND NOT EXISTS (SELECT 1 FROM prospect_deals x WHERE x.opportunity_id = o.opportunity_id){scope}
        RETURNING d.id
        """,
        params,
    )
    linked = len(cur.fetchall())
    cur.execute(
        f"""
        UPDATE prospect_deals d SET account_id = a.account_id
          FROM account a
         WHERE d.account_id IS NULL AND d.hubspot_deal_id IS NOT NULL
           AND NULLIF(a.hubspot_deal_id, '') = d.hubspot_deal_id{scope}
        RETURNING d.id
        """,
        params,
    )
    linked += len(cur.fetchall())
    cur.execute(
        f"""
        SELECT d.id, d.company_id, d.pipeline_key, d.stage_key, LOWER(BTRIM(o.opp_stage)) AS opp_stage
          FROM prospect_deals d JOIN opportunity o ON o.opportunity_id = d.opportunity_id
         WHERE TRUE{scope}
        """,
        params,
    )
    moved = 0
    for r in cur.fetchall():
        target = HUB_TO_DEAL_STAGE.get(r["opp_stage"] or "")
        if not target or target == r["stage_key"]:
            continue
        cur_stage = _stage(cur, r["pipeline_key"], r["stage_key"]) or {}
        if target == CLOSED_LOST:
            if cur_stage.get("is_closed"):
                continue
        else:
            if cur_stage.get("is_closed"):
                continue  # un negocio ya cerrado no se reabre solo
            tr, cr = rank(target), rank(r["stage_key"])
            if tr is None or (cr is not None and tr <= cr):
                continue
        if _stage(cur, r["pipeline_key"], target) is None:
            continue
        cur.execute(
            "UPDATE prospect_deals SET stage_key = %s, stage_entered_at = NOW(), updated_at = NOW(), "
            + STAMP_STAGE + " WHERE id = %s",
            (target, f"{r['pipeline_key']}:{target}", r["id"]),
        )
        store.log_event(cur, r["company_id"], "opportunity", None, "stage", r["stage_key"], target, deal_id=r["id"])
        after_stage(cur, r["id"], r["pipeline_key"], target, None)
        moved += 1
    # Los valores de Signed / Close Win / Closed Lost: en el cron, al abrir un negocio y cuando la
    # etapa recién se movió (no en cada carga del tablero: es una consulta por oportunidad).
    copied = 0
    if values:
        cur.execute(
            f"""
            SELECT d.id FROM prospect_deals d JOIN opportunity o ON o.opportunity_id = d.opportunity_id
             WHERE LOWER(BTRIM(o.opp_stage)) IN ('signed', 'close win', 'closed lost', 'stop'){scope}
            """,
            params,
        )
        for x in cur.fetchall():
            cur.execute("SAVEPOINT deal_copy")
            try:
                copied += copy_closing_values(cur, x["id"])
                cur.execute("RELEASE SAVEPOINT deal_copy")
            except Exception:  # noqa: BLE001 — un hire raro no frena al resto
                cur.execute("ROLLBACK TO SAVEPOINT deal_copy")
    return {"linked": linked, "moved": moved, "copied": copied}


# --------------------------------------------------------------------------- #
# Exportar
# --------------------------------------------------------------------------- #
EXPORT_EXTRA = [
    {"key": "pipeline_label", "label": "Pipeline", "type": "text"},
    {"key": "stage_label", "label": "Etapa", "type": "text"},
    {"key": "company_name", "label": "Empresa", "type": "text"},
    {"key": "contact_names", "label": "Contactos", "type": "text"},
    {"key": "opportunity_id", "label": "Oportunidad (hub)", "type": "number"},
    {"key": "created_at", "label": "Fecha de creación", "type": "datetime"},
    {"key": "id", "label": "Id (Hub)", "type": "number"},
]


def export_fields() -> list[dict]:
    return [{"key": f["key"], "label": f["label"], "type": f["type"], "group": f["group"]} for f in DEAL_FIELDS] \
        + EXPORT_EXTRA


def export_rows(cur, ids: list[int], sort=None) -> list[dict]:
    labels = {p["key"]: p["label"] for p in pipelines(cur)}
    cur.execute(_SELECT + f" WHERE d.id = ANY(%s) ORDER BY {order_sql(sort)}", (ids,))
    rows = []
    for r in cur.fetchall():
        out = _row(r)
        out["pipeline_label"] = labels.get(out["pipeline_key"], out["pipeline_key"])
        out["contact_names"] = ", ".join(c.get("name") or "" for c in out.get("contacts") or [])
        rows.append(out)
    return rows


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
