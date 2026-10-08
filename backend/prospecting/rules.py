"""Workflows como dato: validación, traducción a SQL y evaluador en Python.

Un workflow (lo arma la página, se guarda en `prospect_workflows`) corre sobre un
OBJETO — empresas o contactos (ver objects.py):

    trigger  = {"type": "filter" | "event" | "schedule" | "manual", ...}
    steps    = {"start": "<id>", "nodes": {"<id>": {"type": "action"|"delay"|"branch", ..., "next"}}}
    unenroll = {"groups": [...]} | null        (condiciones para sacarla)
    goal     = {"groups": [...]} | null        (condiciones de meta)
    settings = {"business_days": bool, "window": {"from": "09:00", "to": "18:00"} | null,
                "unenroll_if_not_matching": bool}

Condiciones, igual que HubSpot: grupos unidos por O, reglas de un grupo por Y.
Un campo `company.<key>` (en un workflow de contacto) es de la empresa asociada;
`contact.<key>` (en uno de empresa) es "tiene algún contacto que…".

Dos formas de evaluar una condición, que TIENEN que dar lo mismo:
  * `compile_conditions()` -> SQL, para la inscripción por lote.
  * `matches()`            -> Python sobre una fila, para las ramas y "Probar con
                              una empresa". El test de paridad las compara campo
                              por campo y operador por operador, en los dos objetos.

El JSON NUNCA llega como SQL: sólo se arma SQL con campos de los catálogos y
operadores de `OPERATORS` (lista blanca), y todo valor viaja como parámetro.
Por eso validate_*() corre siempre antes de guardar, previsualizar o probar.

Ojo: un `%` literal en el SQL rompe psycopg2; los comodines de LIKE van dentro
del parámetro (y los `%` / `_` que escribe la persona se escapan).
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from prospecting.constants import (
    ACTIONS,
    BRANCHES,
    DELAYS,
    EVENTS,
    INTERNAL_EMAIL_DOMAIN,
    OPERATORS,
    OPERATORS_BY_TYPE,
    SCHEDULES,
    TIMEZONE,
    TRIGGERS,
)
from prospecting.objects import (
    OBJECTS,
    TEXTUAL,
    cross_wrap,
    history_filter,
    resolve,
    sql_date,
    sql_expr,
)

_TZ = ZoneInfo(TIMEZONE)

MAX_GROUPS = 10
MAX_RULES = 20
MAX_NODES = 100
MAX_PATHS = 10

# Compatibilidad: los campos de empresa con historial (los usa engine.load_history).
HISTORY_FIELDS = OBJECTS["company"]["history"]

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SLACK_CHANNEL_RE = re.compile(r"^[CG][A-Z0-9]{6,}$")


class InvalidWorkflow(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# --------------------------------------------------------------------------- #
# Parseo
# --------------------------------------------------------------------------- #
def parse_date(v):
    if isinstance(v, datetime):
        # Un timestamptz que viene de la base ya está en la zona de la sesión, igual
        # que `col::date` en SQL: tomar su fecha tal cual mantiene la paridad.
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def parse_datetime(v):
    """Datetime con zona. Sin zona se toma como hora Argentina."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=_TZ)
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=_TZ)


def parse_number(v):
    if isinstance(v, bool) or v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_int(v):
    n = parse_number(v)
    return int(n) if n is not None and n == int(n) else None


def is_time(v) -> bool:
    return isinstance(v, str) and bool(_TIME_RE.match(v))


def changed_since(as_of: date, days: int) -> datetime:
    """"Cambió en los últimos N días" va por días de calendario, como HubSpot:
    0 = hoy (desde las 00:00 hora Argentina), 1 = desde ayer, etc."""
    return datetime.combine(as_of - timedelta(days=days), time(0, 0), tzinfo=_TZ)


# --------------------------------------------------------------------------- #
# Validación de condiciones
# --------------------------------------------------------------------------- #
class Ctx:
    """Lo que la validación necesita saber de afuera."""

    def __init__(self, owners=None, workflow_ids=None, self_id=None, obj="company", users=None):
        self.owners = owners          # emails de BDRs (None = no chequear)
        self.users = users            # emails de usuarios activos (None = no chequear)
        self.workflow_ids = workflow_ids or set()
        self.self_id = self_id
        self.obj = obj


def _allowed_values(field: dict, ctx: Ctx):
    if field["type"] == "enum" or (field["type"] == "multi" and field.get("options")):
        return field.get("options") or []
    if field["type"] == "owner":
        return ctx.owners
    if field["type"] == "user":
        return ctx.users
    return None


def _check_rule(rule: dict, where: str, ctx: Ctx, obj: str) -> list[str]:
    if not isinstance(rule, dict):
        return [f"{where}: condición inválida."]
    owner_obj, field, _cross = resolve(obj, rule.get("field"))
    if not field:
        return [f"{where}: elegí una propiedad."]
    op = rule.get("op")
    if op not in OPERATORS_BY_TYPE[field["type"]]:
        return [f"{where}: «{field['label']}» no admite esa condición."]
    if OPERATORS[op].get("history") and field["key"] not in OBJECTS[owner_obj]["history"]:
        return [f"{where}: «{field['label']}» no guarda historial."]
    kind = OPERATORS[op]["value"]
    v = rule.get("value")
    label = f"{where} ({field['label']})"
    if kind is None:
        return []
    if kind == "list":
        if not isinstance(v, list) or not v:
            return [f"{label}: elegí al menos un valor."]
        allowed = _allowed_values(field, ctx)
        if allowed is not None:
            bad = [x for x in v if x not in allowed]
            if bad:
                return [f"{label}: valor que no está en la lista ({', '.join(map(str, bad))})."]
        return []
    if kind == "text":
        return [] if isinstance(v, str) and v.strip() else [f"{label}: escribí un texto."]
    if kind == "number":
        return [] if parse_number(v) is not None else [f"{label}: tiene que ser un número."]
    if kind == "days":
        n = parse_int(v)
        return [] if n is not None and n >= 0 else [f"{label}: cantidad de días inválida."]
    if kind == "date":
        return [] if parse_date(v) else [f"{label}: elegí una fecha."]
    if kind == "number_range":
        if not isinstance(v, list) or len(v) != 2 or any(parse_number(x) is None for x in v):
            return [f"{label}: completá desde y hasta."]
        return [] if parse_number(v[0]) <= parse_number(v[1]) else [f"{label}: «desde» es mayor que «hasta»."]
    if kind == "date_range":
        if not isinstance(v, list) or len(v) != 2 or any(parse_date(x) is None for x in v):
            return [f"{label}: elegí las dos fechas."]
        return [] if parse_date(v[0]) <= parse_date(v[1]) else [f"{label}: la primera fecha es posterior a la segunda."]
    return [f"{label}: condición desconocida."]


def validate_conditions(conditions, where: str, ctx: Ctx, required: bool = True, obj: str | None = None) -> list[str]:
    obj = obj or ctx.obj
    groups = conditions.get("groups") if isinstance(conditions, dict) else None
    if not groups:
        return [f"{where}: agregá al menos una condición."] if required else []
    if not isinstance(groups, list):
        return [f"{where}: formato inválido."]
    errors = []
    if len(groups) > MAX_GROUPS:
        errors.append(f"{where}: máximo {MAX_GROUPS} grupos.")
    for gi, g in enumerate(groups[:MAX_GROUPS], start=1):
        rules = g.get("rules") if isinstance(g, dict) else None
        if not isinstance(rules, list) or not rules:
            errors.append(f"{where}, grupo {gi}: está vacío.")
            continue
        if len(rules) > MAX_RULES:
            errors.append(f"{where}, grupo {gi}: máximo {MAX_RULES} condiciones.")
        for ri, r in enumerate(rules[:MAX_RULES], start=1):
            errors += _check_rule(r, f"{where}, grupo {gi}, condición {ri}", ctx, obj)
    return errors


def has_conditions(conditions) -> bool:
    return bool(isinstance(conditions, dict) and conditions.get("groups"))


# --------------------------------------------------------------------------- #
# Validación del disparador
# --------------------------------------------------------------------------- #
def validate_trigger(trigger, ctx: Ctx) -> list[str]:
    if not isinstance(trigger, dict) or trigger.get("type") not in TRIGGERS:
        return ["Disparador: elegí cómo se inscriben."]
    t = trigger["type"]
    if t == "filter":
        return validate_conditions(trigger.get("conditions"), "Disparador", ctx)
    if t == "manual":
        return []
    errors = validate_conditions(trigger.get("conditions"), "Disparador (filtro extra)", ctx, required=False)
    if t == "event":
        ev = trigger.get("event")
        if ev not in EVENTS:
            return errors + ["Disparador: elegí el evento."]
        if ev == "property_changed":
            field = OBJECTS[ctx.obj]["fields"].get(trigger.get("field"))
            if not field or field["key"] not in OBJECTS[ctx.obj]["history"]:
                errors.append("Disparador: elegí qué propiedad tiene que cambiar.")
            else:
                to = trigger.get("to_values") or []
                if not isinstance(to, list):
                    errors.append("Disparador: valores inválidos.")
                elif to:
                    allowed = _allowed_values(field, ctx)
                    if allowed is not None and any(x not in allowed for x in to):
                        errors.append("Disparador: hay un valor que no está en la lista.")
        return errors
    if t == "schedule":
        sch = trigger.get("schedule") or {}
        kind = sch.get("kind")
        if kind not in SCHEDULES:
            errors.append("Horario: elegí cuándo corre.")
        elif kind == "weekly":
            days = sch.get("days")
            if not isinstance(days, list) or not days or any(parse_int(d) not in range(7) for d in days):
                errors.append("Horario: elegí al menos un día de la semana.")
        elif kind == "date" and not parse_date(sch.get("date")):
            errors.append("Horario: elegí la fecha.")
        if not is_time(sch.get("time")):
            errors.append("Horario: elegí la hora (HH:MM).")
        return errors
    return errors


# --------------------------------------------------------------------------- #
# Validación de acciones
# --------------------------------------------------------------------------- #
def check_value_for_field(field: dict, v, label: str, ctx: Ctx) -> list[str]:
    ty = field["type"]
    if ty == "bool":
        return [] if isinstance(v, bool) or str(v).lower() in ("true", "false") else [f"{label}: elegí sí o no."]
    if ty == "multi":
        if not isinstance(v, list) or not v:
            return [f"{label}: elegí al menos un valor."]
        allowed = _allowed_values(field, ctx)
        return [] if allowed is None or all(x in allowed for x in v) else [f"{label}: hay un valor que no está en la lista."]
    if v is None or (isinstance(v, str) and not v.strip()):
        return [f"{label}: falta el valor (para dejarlo vacío usá «Borrar»)."]
    allowed = _allowed_values(field, ctx)
    if allowed is not None and v not in allowed:
        return [f"{label}: «{v}» no está en la lista."]
    if ty == "date" and not parse_date(v):
        return [f"{label}: elegí una fecha."]
    if ty == "datetime" and not parse_datetime(v):
        return [f"{label}: elegí fecha y hora."]
    if ty == "number" and parse_number(v) is None:
        return [f"{label}: tiene que ser un número."]
    if ty == "email" and not _EMAIL_RE.match(str(v).strip()):
        return [f"{label}: no es un mail válido."]
    return []


# Tipos que se pueden copiar a cada tipo de destino.
COPY_COMPATIBLE = {
    "text": TEXTUAL + ("number", "date", "datetime"),
    "longtext": TEXTUAL + ("number", "date", "datetime"),
    "url": ("url", "text"),
    "email": ("email", "text"),
    "phone": ("phone", "text", "number"),
    "enum": ("enum",),
    "owner": ("owner", "user"),
    "user": ("user", "owner"),
    "number": ("number",),
    "date": ("date", "datetime"),
    "datetime": ("datetime", "date"),
    "bool": ("bool",),
    "multi": ("multi",),
}
DATE_TYPES = ("date", "datetime")


def _email_list_errors(values, label: str, allow_owner: bool) -> list[str]:
    if not isinstance(values, list) or not values:
        return [f"{label}: elegí a quién."]
    for x in values:
        if allow_owner and x == "owner":
            continue
        if not (isinstance(x, str) and _EMAIL_RE.match(x) and x.lower().endswith(INTERNAL_EMAIL_DOMAIN)):
            return [f"{label}: «{x}» no es un mail de {INTERNAL_EMAIL_DOMAIN}."]
    return []


def check_action(a: dict, where: str, ctx: Ctx) -> list[str]:
    if not isinstance(a, dict) or a.get("type") not in ACTIONS:
        return [f"{where}: elegí qué hacer."]
    t = a["type"]
    meta = ACTIONS[t]
    if meta.get("field"):
        # En un workflow de contacto, `company.<key>` = editar la empresa asociada.
        target, field, cross = resolve(ctx.obj, a.get("field"))
        if cross and target != "company":
            field = None  # desde una empresa no se editan "sus contactos"
        if not field or field["key"] not in OBJECTS[target]["editable"]:
            return [f"{where}: elegí una propiedad que se pueda editar."]
        types = meta.get("types")
        if types and field["type"] not in types and not (t in ("set_today", "set_date_offset") and field["type"] in DATE_TYPES):
            return [f"{where}: «{meta['label']}» no sirve para «{field['label']}»."]
        label = f"{where} ({field['label']})"
        if t == "set":
            return check_value_for_field(field, a.get("value"), label, ctx)
        if t == "set_date_offset":
            return [] if parse_int(a.get("days")) is not None else [f"{label}: cantidad de días inválida."]
        if t == "increment":
            n = parse_number(a.get("amount"))
            return [] if n not in (None, 0) else [f"{label}: poné cuánto sumar o restar."]
        if t == "copy":
            _sobj, src, _ = resolve(ctx.obj, a.get("from_field"))
            if not src:
                return [f"{label}: elegí de qué propiedad copiar."]
            if a.get("from_field") == a.get("field"):
                return [f"{label}: no se puede copiar sobre sí misma."]
            if src["type"] not in COPY_COMPATIBLE.get(field["type"], ()):
                return [f"{label}: no se puede copiar «{src['label']}» acá (tipos distintos)."]
        return []
    if meta.get("objects") and ctx.obj not in meta["objects"]:
        return [f"{where}: «{meta['label']}» sólo sirve en workflows de contactos."]
    if t == "associate_company":
        return []
    if t == "rotate_owner":
        owners = a.get("owners")
        if not isinstance(owners, list) or not owners:
            return [f"{where}: elegí entre qué BDRs repartir."]
        if ctx.owners is not None and any(o not in ctx.owners for o in owners):
            return [f"{where}: hay un BDR que no está en la lista."]
        return []
    if t == "create_todo":
        errs = []
        assignee = a.get("assignee") or "owner"
        if assignee != "owner":
            errs += _email_list_errors([assignee], f"{where} (para quién)", allow_owner=False)
        if not (a.get("text") or "").strip():
            errs.append(f"{where}: escribí el To-Do.")
        d = parse_int(a.get("due_days"))
        if d is None or not 0 <= d <= 365:
            errs.append(f"{where}: vencimiento inválido (0 a 365 días).")
        return errs
    if t == "send_email":
        errs = _email_list_errors(a.get("to"), f"{where} (para)", allow_owner=True)
        if not (a.get("subject") or "").strip():
            errs.append(f"{where}: falta el asunto.")
        if not (a.get("body") or "").strip():
            errs.append(f"{where}: falta el texto del mail.")
        return errs
    if t == "send_slack":
        errs = [] if (a.get("text") or "").strip() else [f"{where}: escribí el mensaje."]
        ch = (a.get("channel") or "").strip()
        if ch and not _SLACK_CHANNEL_RE.match(ch):
            errs.append(f"{where}: el canal tiene que ser un id de Slack (C0…).")
        return errs
    if t == "add_note":
        return [] if (a.get("text") or "").strip() else [f"{where}: escribí la nota."]
    if t == "webhook":
        url = (a.get("url") or "").strip()
        return [] if url.startswith("https://") and len(url) <= 500 else [f"{where}: la URL tiene que empezar con https://."]
    if t in ("enroll_workflow", "unenroll_workflow"):
        wid = parse_int(a.get("workflow_id"))
        if wid is None or (ctx.workflow_ids and wid not in ctx.workflow_ids):
            return [f"{where}: elegí el workflow."]
        if ctx.self_id is not None and wid == ctx.self_id:
            return [f"{where}: no puede apuntar a este mismo workflow."]
        return []
    return [f"{where}: acción desconocida."]


# --------------------------------------------------------------------------- #
# Validación del grafo de pasos
# --------------------------------------------------------------------------- #
def _check_delay(d: dict, where: str, ctx: Ctx) -> list[str]:
    if not isinstance(d, dict) or d.get("kind") not in DELAYS:
        return [f"{where}: elegí el tipo de espera."]
    k = d["kind"]
    if k == "duration":
        parts = [parse_int(d.get(x) or 0) for x in ("days", "hours", "minutes")]
        if any(p is None or p < 0 for p in parts) or sum(parts) == 0:
            return [f"{where}: poné cuánto esperar."]
        return []
    if k == "until_date":
        errs = [] if parse_date(d.get("date")) else [f"{where}: elegí la fecha."]
        if d.get("time") and not is_time(d["time"]):
            errs.append(f"{where}: hora inválida.")
        return errs
    if k == "until_property":
        _o, f, _c = resolve(ctx.obj, d.get("field"))
        if not f or f["type"] not in DATE_TYPES:
            return [f"{where}: elegí una propiedad de fecha."]
        return [] if parse_int(d.get("offset_days") or 0) is not None else [f"{where}: días inválidos."]
    if k == "until_weekday":
        days = d.get("days")
        if not isinstance(days, list) or not days or any(parse_int(x) not in range(7) for x in days):
            return [f"{where}: elegí al menos un día."]
        return [] if is_time(d.get("time")) else [f"{where}: elegí la hora."]
    if k == "until_time":
        return [] if is_time(d.get("time")) else [f"{where}: elegí la hora."]
    if k == "until_condition":
        errs = validate_conditions(d.get("conditions"), where, ctx)
        n = parse_int(d.get("max_days"))
        if n is None or not 1 <= n <= 365:
            errs.append(f"{where}: poné el máximo de días a esperar (1 a 365).")
        return errs
    return []


def node_targets(node: dict) -> list:
    if node.get("type") == "branch":
        b = node.get("branch") or {}
        return [p.get("next") for p in (b.get("paths") or []) if isinstance(p, dict)] + [b.get("else_next")]
    return [node.get("next")]


def _check_branch(b: dict, where: str, ctx: Ctx) -> list[str]:
    if not isinstance(b, dict) or b.get("kind") not in BRANCHES:
        return [f"{where}: elegí el tipo de rama."]
    paths = b.get("paths")
    if not isinstance(paths, list) or not paths:
        return [f"{where}: agregá al menos una rama."]
    if len(paths) > MAX_PATHS:
        return [f"{where}: máximo {MAX_PATHS} ramas."]
    k = b["kind"]
    errs = []
    if k == "value":
        _o, field, _c = resolve(ctx.obj, b.get("field"))
        if not field or field["type"] not in ("enum", "owner", "user"):
            return [f"{where}: elegí una propiedad de lista (status, owner, Lead Life…)."]
        seen = set()
        for i, p in enumerate(paths, start=1):
            vals = p.get("values") if isinstance(p, dict) else None
            if not isinstance(vals, list) or not vals:
                errs.append(f"{where}, rama {i}: elegí al menos un valor.")
                continue
            allowed = _allowed_values(field, ctx)
            if allowed is not None and any(v not in allowed for v in vals):
                errs.append(f"{where}, rama {i}: hay un valor que no está en la lista.")
            if seen & set(vals):
                errs.append(f"{where}, rama {i}: un valor ya está en otra rama.")
            seen |= set(vals)
    elif k == "conditions":
        for i, p in enumerate(paths, start=1):
            errs += validate_conditions(p.get("conditions") if isinstance(p, dict) else None, f"{where}, rama {i}", ctx)
    elif k == "random":
        if len(paths) < 2:
            return [f"{where}: el reparto necesita al menos 2 ramas."]
        pcts = [parse_int(p.get("pct")) if isinstance(p, dict) else None for p in paths]
        if any(x is None or x <= 0 for x in pcts) or sum(pcts) != 100:
            errs.append(f"{where}: los porcentajes tienen que sumar 100.")
    return errs


def number_nodes(steps: dict) -> dict:
    """{id: número} en orden de recorrido (profundidad), como los numera HubSpot."""
    nodes = steps.get("nodes") or {}
    order, stack = {}, [steps.get("start")]
    while stack:
        nid = stack.pop()
        if nid is None or nid in order or nid not in nodes:
            continue
        order[nid] = len(order) + 1
        stack += list(reversed(node_targets(nodes[nid])))
    return order


def prune_steps(steps: dict) -> dict:
    """Saca los pasos a los que no se llega desde el inicio (los deja el editor al borrar)."""
    nodes = (steps or {}).get("nodes") or {}
    reachable = number_nodes(steps or {})
    start = steps.get("start") if steps and steps.get("start") in nodes else None
    return {"start": start, "nodes": {k: v for k, v in nodes.items() if k in reachable}}


def validate_steps(steps, ctx: Ctx) -> list[str]:
    if not isinstance(steps, dict) or not isinstance(steps.get("nodes"), dict):
        return ["Pasos: formato inválido."]
    nodes = steps["nodes"]
    if not nodes or steps.get("start") not in nodes:
        return ["Agregá al menos un paso después del disparador."]
    if len(nodes) > MAX_NODES:
        return [f"Máximo {MAX_NODES} pasos."]
    errors = []
    order = number_nodes(steps)
    for nid, node in nodes.items():
        where = f"Paso {order.get(nid, '?')}"
        if not _NODE_ID_RE.match(str(nid)) or not isinstance(node, dict):
            errors.append(f"{where}: identificador inválido.")
            continue
        for target in node_targets(node):
            if target is not None and target not in nodes:
                errors.append(f"{where}: apunta a un paso que no existe.")
        t = node.get("type")
        if t == "action":
            errors += check_action(node.get("action"), where, ctx)
        elif t == "delay":
            errors += _check_delay(node.get("delay"), where, ctx)
        elif t == "branch":
            errors += _check_branch(node.get("branch"), where, ctx)
        else:
            errors.append(f"{where}: tipo de paso desconocido.")
    return errors


def validate_settings(settings) -> list[str]:
    if settings is None:
        return []
    if not isinstance(settings, dict):
        return ["Configuración: formato inválido."]
    w = settings.get("window")
    if w and not (isinstance(w, dict) and is_time(w.get("from")) and is_time(w.get("to")) and w["from"] < w["to"]):
        return ["Configuración: la franja horaria tiene que ir de una hora a otra posterior."]
    return []


def validate_definition(defn: dict, ctx: Ctx) -> list[str]:
    errors = []
    errors += validate_trigger(defn.get("trigger"), ctx)
    errors += validate_steps(defn.get("steps"), ctx)
    errors += validate_conditions(defn.get("unenroll"), "Desinscripción", ctx, required=False)
    errors += validate_conditions(defn.get("goal"), "Meta", ctx, required=False)
    errors += validate_settings(defn.get("settings"))
    return errors


# --------------------------------------------------------------------------- #
# SQL (sólo después de validar)
# --------------------------------------------------------------------------- #
def _like(v) -> str:
    return str(v).strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _rule_sql_on(obj: str, field: dict, rule: dict, as_of: date, now: datetime) -> tuple[str, list]:
    col = sql_expr(obj, field)  # de la lista blanca, nunca del JSON
    ty = field["type"]
    textual = ty in TEXTUAL
    op = rule["op"]
    v = rule.get("value")
    if op == "known":
        if ty == "multi":
            return f"COALESCE(jsonb_array_length({col}) > 0, FALSE)", []
        return (f"NULLIF({col}::text, '') IS NOT NULL" if textual else f"{col} IS NOT NULL"), []
    if op == "unknown":
        if ty == "multi":
            return f"NOT COALESCE(jsonb_array_length({col}) > 0, FALSE)", []
        return (f"NULLIF({col}::text, '') IS NULL" if textual else f"{col} IS NULL"), []
    if op == "is_true":
        return f"COALESCE({col}, FALSE)", []
    if op == "is_false":
        return f"NOT COALESCE({col}, FALSE)", []
    if op in ("has_any", "has_none"):
        sql = f"COALESCE({col} ?| %s::text[], FALSE)"
        return (sql if op == "has_any" else f"NOT {sql}"), [[str(x) for x in v]]
    if op == "is_any":
        return f"COALESCE({col} = ANY(%s), FALSE)", [list(v)]
    if op == "is_none_of":
        # Como en HubSpot: "no es ninguno de" incluye a las que no tienen valor.
        return f"({col} IS NULL OR NOT ({col} = ANY(%s)))", [list(v)]
    hist = f"FROM prospect_company_events e WHERE {history_filter(obj)} AND e.field = %s"
    if op in ("ever_was", "never_was"):
        sql = f"(COALESCE({col} = ANY(%s), FALSE) OR EXISTS (SELECT 1 {hist} AND e.new_value = ANY(%s)))"
        params = [list(v), field["key"], [str(x) for x in v]]
        return (sql if op == "ever_was" else f"NOT {sql}"), params
    if op in ("changed_in_last_days", "not_changed_in_days"):
        sql = f"EXISTS (SELECT 1 {hist} AND e.at >= %s)"
        params = [field["key"], changed_since(as_of, parse_int(v))]
        return (sql if op == "changed_in_last_days" else f"NOT {sql}"), params
    if op == "equals":
        return f"COALESCE(LOWER(TRIM({col})) = LOWER(TRIM(%s)), FALSE)", [str(v)]
    if op == "contains":
        return f"COALESCE({col} ILIKE %s, FALSE)", [f"%{_like(v)}%"]
    if op == "not_contains":
        return f"({col} IS NULL OR {col} NOT ILIKE %s)", [f"%{_like(v)}%"]
    if op == "starts_with":
        return f"COALESCE({col} ILIKE %s, FALSE)", [f"{_like(v)}%"]
    if op == "ends_with":
        return f"COALESCE({col} ILIKE %s, FALSE)", [f"%{_like(v)}"]
    if op in ("eq", "gt", "gte", "lt", "lte"):
        sym = {"eq": "=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
        return f"COALESCE({col} {sym} %s, FALSE)", [parse_number(v)]
    if op == "between":
        return f"COALESCE({col} BETWEEN %s AND %s, FALSE)", [parse_number(v[0]), parse_number(v[1])]
    d = sql_date(obj, field)
    if op == "is_today":
        return f"COALESCE({d} = %s::date, FALSE)", [as_of]
    if op == "is_on":
        return f"COALESCE({d} = %s::date, FALSE)", [parse_date(v)]
    if op == "before":
        return f"COALESCE({d} < %s::date, FALSE)", [parse_date(v)]
    if op == "after":
        return f"COALESCE({d} > %s::date, FALSE)", [parse_date(v)]
    if op == "between_dates":
        return f"COALESCE({d} BETWEEN %s::date AND %s::date, FALSE)", [parse_date(v[0]), parse_date(v[1])]
    if op == "older_than_days":
        return f"COALESCE({d} < %s::date - %s::int, FALSE)", [as_of, parse_int(v)]
    if op == "within_last_days":
        return f"COALESCE({d} >= %s::date - %s::int AND {d} <= %s::date, FALSE)", [as_of, parse_int(v), as_of]
    if op == "in_next_days":
        return f"COALESCE({d} >= %s::date AND {d} <= %s::date + %s::int, FALSE)", [as_of, as_of, parse_int(v)]
    raise InvalidWorkflow([f"Operador desconocido: {op}"])


def _rule_sql(rule: dict, as_of: date, now: datetime, obj: str) -> tuple[str, list]:
    target, field, cross = resolve(obj, rule["field"])
    sql, params = _rule_sql_on(target, field, rule, as_of, now)
    return (cross_wrap(obj, target, sql) if cross else sql), params


def compile_conditions(conditions: dict, as_of: date, now: datetime, obj: str = "company") -> tuple[str, list]:
    """WHERE para `FROM <tabla del objeto>`. Cada regla devuelve TRUE/FALSE (nunca NULL),
    así el resultado coincide con el evaluador de Python también al negarlo."""
    group_sql, params = [], []
    for g in conditions["groups"]:
        parts = []
        for r in g["rules"]:
            sql, p = _rule_sql(r, as_of, now, obj)
            parts.append(sql)
            params += p
        group_sql.append("(" + " AND ".join(parts) + ")")
    return "(" + " OR ".join(group_sql) + ")", params


# --------------------------------------------------------------------------- #
# Python (mismo resultado que el SQL; lo verifica el test de paridad)
# --------------------------------------------------------------------------- #
def _num(v):
    n = parse_number(v)
    return n


def _bool(v):
    if isinstance(v, bool):
        return v
    if v is None or v == "":
        return None
    return str(v).lower() == "true"


def _as_date(field: dict, v):
    if field["type"] == "datetime":
        dt = parse_datetime(v)
        return dt.astimezone(_TZ).date() if dt else None
    return parse_date(v)


def _rule_py_on(field: dict, rule: dict, row: dict, as_of: date, now: datetime, history: dict) -> bool:
    key = field["key"]
    ty = field["type"]
    textual = ty in TEXTUAL
    op = rule["op"]
    v = rule.get("value")
    cur = row.get(key)
    if ty == "multi":
        lst = cur if isinstance(cur, list) else []
        if op == "known":
            return len(lst) > 0
        if op == "unknown":
            return len(lst) == 0
        if op in ("has_any", "has_none"):
            hit = any(str(x) in {str(y) for y in lst} for x in v)
            return hit if op == "has_any" else not hit
    if ty == "bool":
        b = _bool(cur)
        if op == "is_true":
            return b is True
        if op == "is_false":
            return b is not True
        if op == "known":
            return b is not None
        if op == "unknown":
            return b is None
    if ty in ("number", "date", "datetime") and op in ("known", "unknown"):
        val = _num(cur) if ty == "number" else _as_date(field, cur)
        return (val is not None) if op == "known" else (val is None)
    has = (cur is not None and str(cur) != "") if textual else cur is not None
    if op == "known":
        return has
    if op == "unknown":
        return not has
    if op == "is_any":
        return cur is not None and cur in v
    if op == "is_none_of":
        return cur is None or cur not in v
    if op in ("ever_was", "never_was"):
        vals = {str(x) for x in v}
        hit = (cur is not None and cur in v) or any(e["new"] in vals for e in history.get(key, []))
        return hit if op == "ever_was" else not hit
    if op in ("changed_in_last_days", "not_changed_in_days"):
        since = changed_since(as_of, parse_int(v))
        hit = any(e["at"] >= since for e in history.get(key, []))
        return hit if op == "changed_in_last_days" else not hit
    if op in ("equals", "contains", "not_contains", "starts_with", "ends_with"):
        s = None if cur is None else str(cur)
        if op == "equals":
            # TRIM de Postgres saca sólo espacios: strip(" ") para dar lo mismo.
            return s is not None and s.strip(" ").lower() == str(v).strip(" ").lower()
        needle = str(v).strip().lower()
        if op == "not_contains":
            return s is None or needle not in s.lower()
        if s is None:
            return False
        low = s.lower()
        if op == "contains":
            return needle in low
        return low.startswith(needle) if op == "starts_with" else low.endswith(needle)
    if op in ("eq", "gt", "gte", "lt", "lte", "between"):
        n = _num(cur)
        if n is None:
            return False
        if op == "between":
            return parse_number(v[0]) <= n <= parse_number(v[1])
        t = parse_number(v)
        return {"eq": n == t, "gt": n > t, "gte": n >= t, "lt": n < t, "lte": n <= t}[op]
    d = _as_date(field, cur)
    if d is None:
        return False
    if op == "is_today":
        return d == as_of
    if op == "is_on":
        return d == parse_date(v)
    if op == "before":
        return d < parse_date(v)
    if op == "after":
        return d > parse_date(v)
    if op == "between_dates":
        return parse_date(v[0]) <= d <= parse_date(v[1])
    n = parse_int(v)
    if op == "older_than_days":
        return d < as_of - timedelta(days=n)
    if op == "within_last_days":
        return as_of - timedelta(days=n) <= d <= as_of
    if op == "in_next_days":
        return as_of <= d <= as_of + timedelta(days=n)
    raise InvalidWorkflow([f"Operador desconocido: {op}"])


def _rule_py(rule: dict, row: dict, as_of: date, now: datetime, history: dict, obj: str, related: dict) -> bool:
    target, field, cross = resolve(obj, rule["field"])
    if not cross:
        return _rule_py_on(field, rule, row, as_of, now, history)
    if target == "company":
        comp = related.get("company")
        return bool(comp) and _rule_py_on(field, rule, comp["row"], as_of, now, comp["history"])
    return any(_rule_py_on(field, rule, c["row"], as_of, now, c["history"]) for c in related.get("contacts") or [])


def matches(conditions, row: dict, as_of: date, now: datetime, history: dict | None = None,
            obj: str = "company", related: dict | None = None) -> bool:
    """¿La fila cumple? Sin condiciones = sí (para filtros opcionales).
    `related`: {"company": {"row", "history"}} en un contacto,
               {"contacts": [{"row", "history"}, ...]} en una empresa."""
    if not has_conditions(conditions):
        return True
    history = history or {}
    related = related or {}
    return any(
        all(_rule_py(r, row, as_of, now, history, obj, related) for r in g["rules"])
        for g in conditions["groups"]
    )


def uses_cross(conditions) -> bool:
    return has_conditions(conditions) and any("." in str(r.get("field")) for g in conditions["groups"] for r in g["rules"])


def uses_history(conditions) -> bool:
    return has_conditions(conditions) and any(
        OPERATORS.get(r.get("op"), {}).get("history") for g in conditions["groups"] for r in g["rules"]
    )
