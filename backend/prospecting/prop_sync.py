"""Propiedades sincronizadas contacto ↔ negocio ↔ empresa (2026-11-06).

Reemplaza las dos subcarpetas de workflows de HubSpot que copiaban propiedades de negocio a
contacto y al revés (pedido de la owner). No son workflows: un workflow del Hub no edita
negocios, y son ~30 reglas que tienen que valer siempre. Es UNA tabla (`LINKS`) y un motor
(`propagate`), enganchado al final de `store.update_contact`, `store.update_company` y
`deals.update_deal`: cubre la UI, la edición masiva, los workflows, el popup de etapa y los
syncs de HubSpot.

Tres políticas (las del doc de la owner):
- `contact`: predomina el contacto. Contacto → sus negocios ABIERTOS (pisa).
- `deal`: predomina el negocio. Negocio → todos sus contactos (pisa; gana el último valor,
  como la reinscripción activada de HubSpot).
- `common`: el último cambio gana entre el contacto y sus negocios abiertos (en los dos
  sentidos). Si la propiedad también existe en la EMPRESA, la empresa sólo rellena vacíos en
  los dos sentidos: nunca se pisa lo que trajo Clay (decisión de la owner).

Negocios cerrados (Closed Won / Lost): un cambio en el contacto ya no los toca (su foto al
cerrar queda), pero lo que cambia en un negocio cerrado sí viaja a sus contactos.

Lead Life NO está acá: el del contacto lo manejan los workflows de contacto, y el del negocio
(`lead_life_deal`) se pone solo por etapa (`deals.LEAD_LIFE_BY_STAGE`). First / Last Deep Dive
Date del contacto también son aparte (`deep_dive_dates_for_contacts`): la primera y la última
de sus negocios.

Anti-loop: lo que escribe este módulo lleva `source = "sync:<obj>:<id>"` y un cambio con ese
source no se vuelve a propagar.
"""
from __future__ import annotations

import logging
import re

from prospecting import store
from prospecting.rules import parse_datetime

SOURCE_PREFIX = "sync:"

# (contacto, negocio, empresa, política)
LINKS = [
    # ---- Predomina el contacto ---- #
    ("origin", "origin", None, "contact"),
    ("linkedin_url", "linkedin_contact", None, "contact"),
    # ---- Predomina el negocio ---- #
    ("mql_ae_lost_reason", "mql_lost_reason", None, "deal"),
    ("sql_lost_reason", "lost_reason", None, "deal"),
    ("model", "model", None, "deal"),
    ("role_hired", "role_hired", None, "deal"),
    # 2026-11-06: el Slack de «Pipeline Closed Lost --> Lead Life Closed Lost» lo lee del contacto.
    ("lost_reason_detail", "lost_reason_detail", None, "deal"),
    # ---- En común ---- #
    ("company_linkedin_url", "linkedin_company", "linkedin_url", "common"),
    ("website", "website", "website", "common"),
    ("state_region", "state_region", "state", "common"),
    ("industria", "industry", "industry", "common"),
    ("company_type", "company_type", None, "common"),
    ("position", "position", None, "common"),
    ("headcount", "headcount", None, "common"),
    ("conversion_channel", "conversion_channel", None, "common"),
    ("origin_detail", "origin_detail", None, "common"),
    # La empresa ya tiene nombre siempre: en la práctica nunca se toca (fill-only).
    ("company_name", "company_name_deal", "name", "common"),
    ("credit_loop", "credit_loop", None, "common"),
    ("credits_won", "credits_won", None, "common"),
    ("outsourced_before", "outsourced_before", None, "common"),
    ("credits_expiring_date", "credits_expiring_date", None, "common"),
    ("mkt_collab", "mkt_collab", None, "common"),
    ("follow_up_date", "follow_up_date", None, "common"),
]
_IDX = {"contact": 0, "deal": 1, "company": 2}


def _empty(v) -> bool:
    return v is None or v == "" or v == []


def _convert(target: dict, v):
    """Valor de una propiedad llevado al tipo del destino. ValueError si no entra."""
    if _empty(v):
        return None
    ty = target["type"]
    if ty == "multi" and not isinstance(v, list):
        v = [v]
    elif ty != "multi" and isinstance(v, list):
        v = v[0] if v else None
        if v is None:
            return None
    if ty in ("text", "longtext", "url") and not isinstance(v, str):
        v = str(v)
    return store.clean_contact_value(target, v)


def _defs(cur):
    from prospecting.contact_fields import CONTACT_FIELDS_BY_KEY
    from prospecting import deals as D
    return {"contact": CONTACT_FIELDS_BY_KEY, "deal": D.defs_by_key(cur)}


def _patch_for(targets: dict, pairs: list[tuple[str, object]], current: dict, fill_only: bool) -> dict:
    out = {}
    for key, v in pairs:
        f = targets.get(key)
        if not f:
            continue
        if fill_only and (_empty(v) or not _empty(current.get(key))):
            continue
        try:
            val = _convert(f, v)
        except ValueError:
            continue  # el valor no entra en el destino (otra lista de opciones): se saltea
        if _same(current.get(key), val):
            continue
        out[key] = val
    return out


_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?([+-]\d{2}(:?\d{2})?|Z)?)?$")


def _norm(v):
    if hasattr(v, "isoformat"):
        v = v.isoformat()
    if isinstance(v, str) and _ISO.match(v.strip()):
        v = v.strip()
        if len(v) == 10:
            return v
        dt = parse_datetime(v)
        return dt.isoformat() if dt else v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return v


def _same(a, b) -> bool:
    if _empty(a) and _empty(b):
        return True
    return _norm(a) == _norm(b)


def _open_deals_of_contact(cur, contact_id: int) -> list[dict]:
    cur.execute(
        """
        SELECT d.* FROM prospect_deals d
          JOIN prospect_deal_contacts dc ON dc.deal_id = d.id
          LEFT JOIN prospect_deal_stages s ON s.pipeline_key = d.pipeline_key AND s.stage_key = d.stage_key
         WHERE dc.contact_id = %s AND NOT COALESCE(s.is_closed, FALSE)
        """,
        (contact_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def _flat_deal(r: dict) -> dict:
    from prospecting.deals import _flatten
    return _flatten(r)


def _contact(cur, contact_id: int) -> dict | None:
    cur.execute("SELECT * FROM prospect_contacts WHERE id = %s", (contact_id,))
    r = cur.fetchone()
    return store._flatten_contact(r) if r else None


def _company(cur, company_id) -> dict | None:
    if not company_id:
        return None
    cur.execute("SELECT * FROM prospect_companies WHERE id = %s", (company_id,))
    r = cur.fetchone()
    return dict(r) if r else None


def propagate(cur, obj: str, record_id: int, changes: list[dict], actor: str | None, source: str | None) -> list:
    """Lleva los `changes` de un registro a sus relacionados. Devuelve
    [(obj, id, company_id, cambios)] de lo que escribió (para historial / workflows)."""
    if not changes or str(source or "").startswith(SOURCE_PREFIX):
        return []
    changed = {c["field"]: c["new"] for c in changes}
    i = _IDX[obj]
    links = [l for l in LINKS if l[i] and l[i] in changed]
    if not links:
        return []
    try:
        return _propagate(cur, obj, record_id, changed, links, actor)
    except Exception:  # noqa: BLE001 — nunca romper el guardado del registro original
        logging.exception("prop_sync: no se pudo propagar %s #%s", obj, record_id)
        return []


def _propagate(cur, obj, record_id, changed, links, actor) -> list:
    from prospecting import deals as D

    defs = _defs(cur)
    src = f"{SOURCE_PREFIX}{obj}:{record_id}"
    out = []

    def write(target_obj, tid, patch, company_id):
        if not patch:
            return
        if target_obj == "contact":
            r = store.update_contact(cur, tid, patch, actor, source=src)
        elif target_obj == "deal":
            row, ch = D.update_deal(cur, tid, patch, actor, source=src)
            r = {**row, "_changes": ch}
        else:
            r = store.update_company(cur, tid, patch, actor, source=src)
        ch = (r or {}).get("_changes") or []
        if ch:
            out.append((target_obj, tid, company_id, ch))

    if obj == "contact":
        ct = _contact(cur, record_id) or {}
        # contacto → negocios abiertos (contact + common)
        pairs = [(l[1], changed[l[0]]) for l in links if l[1] and l[3] in ("contact", "common")]
        if pairs:
            for d in _open_deals_of_contact(cur, record_id):
                fd = _flat_deal(d)
                write("deal", d["id"], _patch_for(defs["deal"], pairs, fd, fill_only=False), d["company_id"])
        # contacto → empresa (sólo rellena vacíos)
        comp = _company(cur, ct.get("company_id"))
        if comp:
            pairs = [(l[2], changed[l[0]]) for l in links if l[2] and l[3] == "common"]
            write("company", comp["id"], _company_patch(pairs, comp), comp["id"])

    elif obj == "deal":
        cur.execute("SELECT * FROM prospect_deals WHERE id = %s", (record_id,))
        d = cur.fetchone()
        if d is None:
            return out
        # negocio → todos sus contactos (deal + common)
        pairs = [(l[0], changed[l[1]]) for l in links if l[0] and l[3] in ("deal", "common")]
        if pairs:
            cur.execute("SELECT contact_id FROM prospect_deal_contacts WHERE deal_id = %s", (record_id,))
            for r in cur.fetchall():
                ct = _contact(cur, r["contact_id"])
                if ct:
                    write("contact", ct["id"], _patch_for(defs["contact"], pairs, ct, fill_only=False),
                          ct.get("company_id"))
        comp = _company(cur, d["company_id"])
        if comp:
            pairs = [(l[2], changed[l[1]]) for l in links if l[2] and l[3] == "common"]
            write("company", comp["id"], _company_patch(pairs, comp), comp["id"])

    else:  # empresa → contactos y negocios abiertos, sólo rellena vacíos
        pairs_ct = [(l[0], changed[l[2]]) for l in links if l[0] and l[3] == "common"]
        pairs_d = [(l[1], changed[l[2]]) for l in links if l[1] and l[3] == "common"]
        for ct in store.company_contacts(cur, record_id):
            write("contact", ct["id"], _patch_for(defs["contact"], pairs_ct, ct, fill_only=True), record_id)
        cur.execute(
            """
            SELECT d.* FROM prospect_deals d
              LEFT JOIN prospect_deal_stages s ON s.pipeline_key = d.pipeline_key AND s.stage_key = d.stage_key
             WHERE d.company_id = %s AND NOT COALESCE(s.is_closed, FALSE)
            """,
            (record_id,),
        )
        for d in [dict(r) for r in cur.fetchall()]:
            write("deal", d["id"], _patch_for(defs["deal"], pairs_d, _flat_deal(d), fill_only=True), record_id)

    _emit(cur, out, actor)
    return out


def _company_patch(pairs, comp: dict) -> dict:
    patch = {}
    for key, v in pairs:
        if key == "name" or _empty(v) or not _empty(comp.get(key)):
            continue
        if isinstance(v, list):
            v = v[0] if v else None
        if v is not None:
            patch[key] = v
    return patch


def _emit(cur, out: list, actor: str | None) -> None:
    """Los workflows «cuando cambia una propiedad» de los registros que se copiaron. Las
    condiciones los ven en el próximo tick (cron horario o la próxima edición)."""
    from prospecting import engine

    for target_obj, tid, _company_id, ch in out:
        if target_obj not in ("contact", "company") or not isinstance(ch, list) or not ch or not isinstance(ch[0], dict):
            continue
        try:
            engine.emit_event(cur, target_obj, tid, "updated", ch, actor=actor)
        except Exception:  # noqa: BLE001
            logging.exception("prop_sync: emit_event %s #%s", target_obj, tid)


def pull_into_deal(cur, deal_id: int, actor: str | None) -> list:
    """Negocio nuevo (o contacto recién asociado): completa los VACÍOS del negocio con lo que ya
    tienen su primer contacto y su empresa. Nunca pisa."""
    from prospecting import deals as D

    cur.execute("SELECT * FROM prospect_deals WHERE id = %s", (deal_id,))
    d = cur.fetchone()
    if d is None:
        return []
    fd = _flat_deal(d)
    cur.execute("SELECT contact_id FROM prospect_deal_contacts WHERE deal_id = %s ORDER BY created_at LIMIT 1",
                (deal_id,))
    r = cur.fetchone()
    ct = _contact(cur, r["contact_id"]) if r else None
    comp = _company(cur, d["company_id"]) or {}
    pairs = []
    for c_key, d_key, co_key, pol in LINKS:
        if not d_key or pol == "deal":
            continue
        v = (ct or {}).get(c_key) if c_key else None
        if _empty(v) and co_key and pol == "common":
            v = comp.get(co_key)
        if not _empty(v):
            pairs.append((d_key, v))
    patch = _patch_for(_defs(cur)["deal"], pairs, fd, fill_only=True)
    if not patch:
        return []
    D.update_deal(cur, deal_id, patch, actor, source=f"{SOURCE_PREFIX}deal:{deal_id}")
    return [("deal", deal_id, d["company_id"], list(patch))]


def deep_dive_dates_for_contacts(cur, deal_id: int, actor: str | None) -> None:
    """First / Last Deep Dive Date de cada contacto del negocio = la primera y la última
    «First Deep Dive Date (Deal)» de todos sus negocios (si un contacto abrió más de una
    oportunidad, la primera fecha va a First y la del último negocio a Last)."""
    cur.execute("SELECT contact_id FROM prospect_deal_contacts WHERE deal_id = %s", (deal_id,))
    for r in cur.fetchall():
        cid = r["contact_id"]
        cur.execute(
            """
            SELECT MIN(NULLIF(d.props->>'first_deep_dive_date', '')::timestamptz) AS first,
                   MAX(NULLIF(d.props->>'first_deep_dive_date', '')::timestamptz) AS last
              FROM prospect_deals d JOIN prospect_deal_contacts dc ON dc.deal_id = d.id
             WHERE dc.contact_id = %s
            """,
            (cid,),
        )
        m = cur.fetchone()
        if not m or not m["first"]:
            continue
        ct = _contact(cur, cid) or {}
        patch = {}
        if not _same(ct.get("first_deep_dive_date"), m["first"].isoformat()):
            patch["first_deep_dive_date"] = m["first"].isoformat()
        if not _same(ct.get("last_deep_dive_date"), m["last"].isoformat()):
            patch["last_deep_dive_date"] = m["last"].isoformat()
        if patch:
            res = store.update_contact(cur, cid, patch, actor, source=f"{SOURCE_PREFIX}deal:{deal_id}")
            _emit(cur, [("contact", cid, ct.get("company_id"), (res or {}).get("_changes") or [])], actor)
