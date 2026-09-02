"""Port 1:1 de reduce() y fmt de docs/assets/js/dashboards/control-dashboard.js.

El dashboard calcula el numero que se ve en pantalla en el cliente: el backend
devuelve filas crudas y el JS las colapsa con `data-reduce` sobre `data-field`.
Para auditar lo que el usuario REALMENTE ve hay que repetir esa cuenta igual,
incluidos sus bordes (el default distinto por binding, el descarte de no-finitos
en las agregaciones numericas, el None de delta-mom cuando prev == 0).

Cualquier cambio en reduce() del JS tiene que replicarse aca o la auditoria
empieza a comparar contra un numero que nadie ve. Ver control-dashboard.js:873.
"""
from __future__ import annotations

import math

# El JS usa 'last' como default en renderText y 'first' en renderProgressFill /
# renderLowSample. No es cosmetico: en una serie mensual first y last son meses
# distintos, asi que el default se resuelve por binding, no globalmente.
DEFAULT_REDUCE_BY_BIND = {
    "text": "last",
    "progress-fill": "first",
    "low-sample": "first",
}

# Formatos que admiten negativos por diseno (son deltas o puntos porcentuales),
# y por lo tanto no pueden dispararlas reglas de "valor negativo" ni de rango.
SIGNED_FORMATS = {
    "percent-pp",
    "delta-percent",
    "delta-int",
    "delta-currency-k",
}

PERCENT_FORMATS = {"percent", "percent2"}


def _num(v):
    """Equivalente a `+v` de JS: devuelve float o None si no es finito."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return float(v)
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def is_finite_number(v) -> bool:
    return _num(v) is not None


def reduce_rows(rows, field, mode):
    """Espejo de reduce(rows, field, mode) del JS.

    Devuelve el valor crudo (puede ser str si la columna es texto y el modo es
    first/last, igual que en JS) o None cuando el JS devolveria null/undefined.
    """
    if not rows:
        return None

    # count no necesita field: va antes de cualquier acceso por columna.
    if mode == "count":
        return len(rows)

    if mode == "count-distinct":
        if not field:
            return len(rows)
        seen = set()
        for r in rows:
            v = r.get(field)
            if v is not None and str(v) != "":
                seen.add(str(v))
        return len(seen)

    if mode == "first":
        return rows[0].get(field)
    if mode == "last":
        return rows[-1].get(field)

    nums = [n for n in (_num(r.get(field)) for r in rows) if n is not None]

    if mode in ("sum", "avg", "max", "min", "avg-last-12"):
        if not nums:
            return None
        if mode == "sum":
            return sum(nums)
        if mode == "avg":
            return sum(nums) / len(nums)
        if mode == "max":
            return max(nums)
        if mode == "min":
            return min(nums)
        tail = nums[-12:]
        return sum(tail) / len(tail)

    # Los deltas indexan por POSICION en rows (no sobre la lista filtrada de
    # numeros), asi que se resuelven aparte y despues de nums.
    if mode in ("delta-mom", "delta-mom-abs"):
        last = _num(rows[-1].get(field)) if len(rows) >= 1 else None
        prev = _num(rows[-2].get(field)) if len(rows) >= 2 else None
        if last is None or prev is None:
            return None
        if mode == "delta-mom-abs":
            return last - prev
        if prev == 0:
            return None
        return ((last - prev) / abs(prev)) * 100

    if mode == "delta-yoy":
        last = _num(rows[-1].get(field)) if len(rows) >= 1 else None
        prev = _num(rows[-13].get(field)) if len(rows) >= 13 else None
        if last is None or prev is None or prev == 0:
            return None
        return ((last - prev) / abs(prev)) * 100

    # Default del JS: ultimo valor.
    return rows[-1].get(field)


def renders_as_empty(value, fmt_name: str) -> bool:
    """True si el formatter del JS pintaria el guion largo (card en blanco).

    Todos los formatters menos `raw` devuelven '—' ante null/''/no-finito; raw
    solo ante null/''. Es la definicion operativa de "la card no muestra nada".
    """
    if value is None or value == "":
        return True
    if fmt_name == "raw":
        return False
    return _num(value) is None
