"""Objetos del CRM de prospección: empresas y contactos.

Un workflow corre sobre UN tipo de objeto (`prospect_workflows.object`). Este
registro le dice a rules.py / engine.py, por cada objeto:
  * qué tabla y qué catálogo de campos usa;
  * cómo se lee cada campo en SQL (columna propia o `props->>'key'` con su cast);
  * qué columna de prospect_company_events tiene su historial.

Condiciones cruzadas: en un workflow de contacto, un campo `company.<key>` es de
su empresa asociada; en uno de empresa, `contact.<key>` significa "tiene algún
contacto que…". Desde los dos, `deal.<key>` es "tiene algún negocio asociado que…"
(2026-11-05; sólo condiciones: un negocio no se edita ni se lee en textos desde un
workflow). Las acciones de "Editar registro" sobre `company.<key>` editan la
empresa asociada (el "Editar la empresa asociada" de HubSpot).

Las claves vienen de catálogos fijos y sólo tienen [a-z0-9_]: nunca del JSON de un
workflow sin validar.
"""
from __future__ import annotations

import re

from prospecting.constants import CLAY_FIELDS, EDITABLE_FIELDS, FIELDS_BY_KEY, TIMEZONE
from prospecting.contact_fields import CONTACT_FIELDS_BY_KEY
from prospecting.deal_fields import DEAL_FIELDS


def _deal_condition_fields() -> dict:
    """Campos del negocio para condiciones. Las opciones de los desplegables y de la
    etapa salen de la base (deals.field_defs / prospect_deal_stages): la validación las
    recibe en `Ctx.deal_options`. Un desplegable sin opciones de fábrica va como texto
    (el mismo criterio de deals.field_defs sin HubSpot), así el tipo —y con él los
    operadores— no depende de lo que haya en la base."""
    out = {
        # Valor = "<pipeline_key>:<stage_key>": la misma etapa existe en los dos pipelines.
        "stage": {"key": "stage", "label": "Etapa del negocio", "type": "enum", "storage": "expr",
                  "sql": "(prospect_deals.pipeline_key || ':' || prospect_deals.stage_key)"},
        "pipeline": {"key": "pipeline", "label": "Pipeline", "type": "enum", "storage": "expr",
                     "sql": "prospect_deals.pipeline_key"},
    }
    for f in DEAL_FIELDS:
        g = {k: v for k, v in f.items() if k != "hubspot"}
        if g["type"] == "enum" and not g.get("options"):
            g["type"] = "text"
            g.pop("options", None)
        out[g["key"]] = g
    return out

OBJECTS = {
    "company": {
        "label": "Empresas",
        "table": "prospect_companies",
        "fields": FIELDS_BY_KEY,
        "editable": set(EDITABLE_FIELDS),
        "history": set(EDITABLE_FIELDS) | set(CLAY_FIELDS),
        "event_fk": "company_id",
        "owner_field": "prospecting_owner_email",
        "cross": "contact",
    },
    "contact": {
        "label": "Contactos",
        "table": "prospect_contacts",
        "fields": CONTACT_FIELDS_BY_KEY,
        "editable": set(CONTACT_FIELDS_BY_KEY),
        "history": set(CONTACT_FIELDS_BY_KEY),
        "event_fk": "contact_id",
        "owner_field": "owner_email",
        "cross": "company",
    },
    # Sólo como destino de condiciones cruzadas (`deal.<key>`): no hay workflows de negocio.
    "deal": {
        "label": "Negocios",
        "table": "prospect_deals",
        "fields": _deal_condition_fields(),
        "editable": set(),
        "history": set(),
        "event_fk": "deal_id",
        "owner_field": "owner_email",
        "cross": None,
    },
}
# Objetos con los que se arman workflows (el negocio no es uno).
WORKFLOW_OBJECTS = ("company", "contact")
OBJECT_KEYS = list(WORKFLOW_OBJECTS)
# Objetos asociados que una condición puede mirar, por objeto del workflow.
CROSS_TARGETS = {"company": ("contact", "deal"), "contact": ("company", "deal")}

TEXTUAL = ("enum", "owner", "user", "text", "longtext", "url", "email", "phone")
_KEY_RE = re.compile(r"^[a-z0-9_]+$")


def resolve(obj: str, key):
    """(objeto dueño del campo, definición del campo, ¿es cruzado?) o (None, None, False)."""
    if not isinstance(key, str):
        return None, None, False
    if "." in key:
        prefix, k = key.split(".", 1)
        if prefix not in CROSS_TARGETS.get(obj, ()):
            return None, None, False
        f = OBJECTS[prefix]["fields"].get(k)
        return (prefix, f, True) if f else (None, None, False)
    f = OBJECTS[obj]["fields"].get(key)
    return (obj, f, False) if f else (None, None, False)


def sql_expr(obj: str, field: dict) -> str:
    """Expresión SQL tipada del campo, calificada con la tabla del objeto."""
    t = OBJECTS[obj]["table"]
    key = field["key"]
    assert _KEY_RE.match(key)
    if field.get("storage") == "expr":
        return field["sql"]
    if obj == "company" or field.get("storage") == "col":
        return f"{t}.{key}"
    raw = f"({t}.props->>'{key}')"
    ty = field["type"]
    if ty == "number":
        return f"NULLIF({raw}, '')::numeric"
    if ty == "date":
        return f"NULLIF({raw}, '')::date"
    if ty == "datetime":
        return f"NULLIF({raw}, '')::timestamptz"
    if ty == "bool":
        return f"NULLIF({raw}, '')::boolean"
    if ty == "multi":
        return f"{t}.props->'{key}'"
    return raw


def sql_date(obj: str, field: dict) -> str:
    """El campo como fecha. Un datetime se lleva a la fecha de Argentina."""
    e = sql_expr(obj, field)
    if field["type"] == "datetime":
        return f"(({e}) AT TIME ZONE '{TIMEZONE}')::date"
    return f"({e})::date"


def history_filter(obj: str) -> str:
    """Condición sobre `e` (prospect_company_events) para el historial del objeto."""
    t = OBJECTS[obj]["table"]
    if obj == "company":
        return f"e.company_id = {t}.id AND e.contact_id IS NULL AND e.deal_id IS NULL"
    return f"e.contact_id = {t}.id"


def cross_wrap(ctx_obj: str, target_obj: str, inner_sql: str) -> str:
    """Envuelve una regla sobre el objeto asociado."""
    if ctx_obj == "contact" and target_obj == "company":
        return ("EXISTS (SELECT 1 FROM prospect_companies WHERE "
                f"prospect_companies.id = prospect_contacts.company_id AND {inner_sql})")
    if ctx_obj == "company" and target_obj == "contact":
        return ("EXISTS (SELECT 1 FROM prospect_contacts WHERE "
                f"prospect_contacts.company_id = prospect_companies.id AND {inner_sql})")
    if ctx_obj == "contact" and target_obj == "deal":
        return ("EXISTS (SELECT 1 FROM prospect_deal_contacts dc JOIN prospect_deals ON prospect_deals.id = dc.deal_id "
                f"WHERE dc.contact_id = prospect_contacts.id AND {inner_sql})")
    if ctx_obj == "company" and target_obj == "deal":
        return ("EXISTS (SELECT 1 FROM prospect_deals WHERE "
                f"prospect_deals.company_id = prospect_companies.id AND {inner_sql})")
    raise ValueError("cruce inválido")
