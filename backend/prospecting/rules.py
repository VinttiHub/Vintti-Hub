"""Workflows como dato: validación y traducción a SQL.

Un workflow es JSON (lo arma la página, se guarda en `prospect_workflows`):

    conditions = {"groups": [{"rules": [{"field", "op", "value"}, ...]}, ...]}
    actions    = [{"type": "set" | "clear" | "set_today", "field", "value"?}, ...]

Igual que en HubSpot, los grupos se unen con O y las reglas de un grupo con Y.

El JSON NUNCA llega como SQL: `compile_conditions()` sólo arma SQL con nombres de
columna de `FIELDS` y operadores de `OPERATORS` (lista blanca), y todo valor viaja
como parámetro. Por eso `validate()` corre siempre antes, al guardar y al
previsualizar.

Ojo: un `%` literal en el SQL rompe psycopg2 (acá los parámetros son posicionales,
y los ILIKE llevan el comodín dentro del parámetro).
"""
from __future__ import annotations

from datetime import date, datetime

from prospecting.constants import (
    ACTIONS,
    EDITABLE_FIELDS,
    FIELDS_BY_KEY,
    OPERATORS,
    OPERATORS_BY_TYPE,
)

MAX_GROUPS = 10
MAX_RULES = 20
MAX_ACTIONS = 20


class InvalidWorkflow(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# --------------------------------------------------------------------------- #
# Validación
# --------------------------------------------------------------------------- #
def _parse_date(v):
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _parse_number(v):
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _allowed_values(field: dict, owners: list[str] | None):
    if field["type"] == "enum":
        return field.get("options") or []
    if field["type"] == "owner":
        return owners
    return None


def _check_rule(rule: dict, where: str, owners: list[str] | None) -> list[str]:
    if not isinstance(rule, dict):
        return [f"{where}: invalid condition."]
    field = FIELDS_BY_KEY.get(rule.get("field"))
    if not field:
        return [f"{where}: pick a property."]
    op = rule.get("op")
    if op not in OPERATORS_BY_TYPE[field["type"]]:
        return [f"{where}: «{field['label']}» doesn't support that condition."]
    kind = OPERATORS[op]["value"]
    v = rule.get("value")
    label = f"{where} ({field['label']})"
    if kind is None:
        return []
    if kind == "list":
        if not isinstance(v, list) or not v:
            return [f"{label}: pick at least one value."]
        allowed = _allowed_values(field, owners)
        if allowed is not None:
            bad = [x for x in v if x not in allowed]
            if bad:
                return [f"{label}: value not in the list ({', '.join(map(str, bad))})."]
        return []
    if kind == "text":
        return [] if isinstance(v, str) and v.strip() else [f"{label}: type some text."]
    if kind == "number":
        return [] if _parse_number(v) is not None else [f"{label}: must be a number."]
    if kind == "days":
        n = _parse_number(v)
        return [] if n is not None and n >= 0 and n == int(n) else [f"{label}: invalid number of days."]
    if kind == "date":
        return [] if _parse_date(v) else [f"{label}: pick a date."]
    return [f"{label}: unknown condition."]


def _check_action(action: dict, where: str, owners: list[str] | None) -> list[str]:
    if not isinstance(action, dict):
        return [f"{where}: invalid action."]
    atype = action.get("type")
    if atype not in ACTIONS:
        return [f"{where}: pick what to do."]
    key = action.get("field")
    field = FIELDS_BY_KEY.get(key)
    if not field or key not in EDITABLE_FIELDS:
        return [f"{where}: pick an editable property."]
    types = ACTIONS[atype].get("types")
    if types and field["type"] not in types:
        return [f"{where}: «{ACTIONS[atype]['label']}» only works on dates."]
    if not ACTIONS[atype]["needs_value"]:
        return []
    v = action.get("value")
    label = f"{where} ({field['label']})"
    if v is None or (isinstance(v, str) and not v.strip()):
        return [f"{label}: missing value (use «Clear» to empty it)."]
    allowed = _allowed_values(field, owners)
    if allowed is not None and v not in allowed:
        return [f"{label}: «{v}» is not in the list."]
    if field["type"] == "date" and not _parse_date(v):
        return [f"{label}: pick a date."]
    if field["type"] == "number" and _parse_number(v) is None:
        return [f"{label}: must be a number."]
    return []


def validate(conditions, actions, owners: list[str] | None = None) -> list[str]:
    """Errores legibles; lista vacía = válido. `owners` = emails de BDRs válidos."""
    errors: list[str] = []
    groups = (conditions or {}).get("groups") if isinstance(conditions, dict) else None
    if not isinstance(groups, list) or not groups:
        errors.append("Add at least one enrollment condition.")
        groups = []
    if len(groups) > MAX_GROUPS:
        errors.append(f"At most {MAX_GROUPS} groups.")
    for gi, g in enumerate(groups[:MAX_GROUPS], start=1):
        rules = g.get("rules") if isinstance(g, dict) else None
        if not isinstance(rules, list) or not rules:
            errors.append(f"Group {gi}: is empty.")
            continue
        if len(rules) > MAX_RULES:
            errors.append(f"Group {gi}: at most {MAX_RULES} conditions.")
        for ri, r in enumerate(rules[:MAX_RULES], start=1):
            errors += _check_rule(r, f"Group {gi}, condition {ri}", owners)
    if not isinstance(actions, list) or not actions:
        errors.append("Add at least one action.")
        actions = []
    if len(actions) > MAX_ACTIONS:
        errors.append(f"At most {MAX_ACTIONS} actions.")
    seen = set()
    for ai, a in enumerate(actions[:MAX_ACTIONS], start=1):
        errors += _check_action(a, f"Action {ai}", owners)
        key = a.get("field") if isinstance(a, dict) else None
        if key in seen:
            errors.append(f"Action {ai}: that property is already edited by another action.")
        seen.add(key)
    return errors


# --------------------------------------------------------------------------- #
# Traducción a SQL (sólo después de validate())
# --------------------------------------------------------------------------- #
def _col(key: str) -> str:
    # El nombre de columna sale de la lista blanca, nunca del JSON.
    field = FIELDS_BY_KEY[key]
    return field["key"]


def _rule_sql(rule: dict, as_of: date) -> tuple[str, list]:
    field = FIELDS_BY_KEY[rule["field"]]
    col = _col(rule["field"])
    ftype = field["type"]
    op = rule["op"]
    v = rule.get("value")
    textual = ftype in ("enum", "owner", "text", "longtext", "url")
    if op == "known":
        return (f"NULLIF({col}::text, '') IS NOT NULL" if textual else f"{col} IS NOT NULL"), []
    if op == "unknown":
        return (f"NULLIF({col}::text, '') IS NULL" if textual else f"{col} IS NULL"), []
    if op == "is_any":
        return f"{col} = ANY(%s)", [list(v)]
    if op == "is_none_of":
        # Como en HubSpot: "no es ninguno de" incluye a las que no tienen valor.
        return f"({col} IS NULL OR NOT ({col} = ANY(%s)))", [list(v)]
    if op == "equals":
        return f"LOWER(TRIM({col})) = LOWER(TRIM(%s))", [str(v)]
    if op == "contains":
        return f"{col} ILIKE %s", [f"%{str(v).strip()}%"]
    if op == "not_contains":
        return f"({col} IS NULL OR {col} NOT ILIKE %s)", [f"%{str(v).strip()}%"]
    if op in ("eq", "gt", "lt"):
        sym = {"eq": "=", "gt": ">", "lt": "<"}[op]
        return f"{col} {sym} %s", [_parse_number(v)]
    if op == "older_than_days":
        return f"{col}::date < %s::date - %s::int", [as_of, int(_parse_number(v))]
    if op == "within_last_days":
        return (f"({col}::date >= %s::date - %s::int AND {col}::date <= %s::date)",
                [as_of, int(_parse_number(v)), as_of])
    if op == "before":
        return f"{col}::date < %s::date", [_parse_date(v)]
    if op == "after":
        return f"{col}::date > %s::date", [_parse_date(v)]
    raise InvalidWorkflow([f"Unknown operator: {op}"])


def compile_conditions(conditions: dict, as_of: date) -> tuple[str, list]:
    group_sql, params = [], []
    for g in conditions["groups"]:
        parts = []
        for r in g["rules"]:
            sql, p = _rule_sql(r, as_of)
            parts.append(sql)
            params += p
        group_sql.append("(" + " AND ".join(parts) + ")")
    return "(" + " OR ".join(group_sql) + ")", params


def action_values(actions: list[dict], as_of: date) -> dict:
    """{columna: valor nuevo} con los valores ya tipados."""
    out = {}
    for a in actions:
        field = FIELDS_BY_KEY[a["field"]]
        if a["type"] == "clear":
            out[field["key"]] = None
        elif a["type"] == "set_today":
            out[field["key"]] = as_of
        else:
            v = a.get("value")
            if field["type"] == "date":
                v = _parse_date(v)
            elif field["type"] == "number":
                v = int(_parse_number(v))
            elif isinstance(v, str):
                v = v.strip()
                if field["type"] == "owner":
                    v = v.lower()
            out[field["key"]] = v
    return out
