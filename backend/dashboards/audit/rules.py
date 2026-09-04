"""Catalogo de invariantes que todo numero del dashboard deberia cumplir.

Cada regla recibe el contexto completo de una corrida y devuelve hallazgos. Las
reglas son genericas a proposito: se aplican a los 1219 nodos por igual, asi una
card nueva queda auditada sin tocar este archivo.

Criterio para agregar una regla: tiene que poder fallar de una forma que hoy
solo se descubre mirando la pantalla. Una regla que no puede senalar nada
concreto y accionable es ruido semanal.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field as dc_field

from .reduce import reduce_rows, renders_as_empty, _num

CRITICAL, HIGH, MEDIUM, LOW = "critical", "high", "medium", "low"

# Formatos donde un valor negativo o nulo es esperable (son deltas).
_DELTA_FMTS = {"percent-pp", "delta-percent", "delta-int", "delta-currency-k"}
_DELTA_REDUCES = {"delta-mom", "delta-mom-abs", "delta-yoy"}
_PERCENT_FMTS = {"percent", "percent2"}
_COUNT_FMTS = {"int"}
# Campos que legitimamente pueden ser negativos aunque se pinten como enteros.
_SIGNED_FIELD = re.compile(r"delta|growth|neto|net_|diff|var_|change|balance")
# Metricas donde superar el 100% es el resultado bueno, no un error: CRR/NRR
# cuentan expansion (crr_pct = fin/inicio da 103.92% cuando la cuenta crece),
# y cualquier tasa de crecimiento tambien. Pasarse de 100 ahi no es un bug;
# ser negativo o pasar de 1000 sigue siendolo.
# Columnas que hacen de denominador. Si el denominador de la ventana es 0, que
# el porcentaje venga nulo es la respuesta correcta ("no hubo cierres esta
# semana"), no una metrica rota.
_DENOMINATOR = re.compile(r"total|count|closes|sqls|denom|inicio|candidatos|base|opps")
_CAN_EXCEED_100 = re.compile(r"crr|nrr|retention|retencion|growth|yoy|mom|expansion|var")


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    tab: str | None = None
    panel: str | None = None
    where: str | None = None
    chart_key: str | None = None
    dataset_key: str | None = None
    field: str | None = None
    observed: str | None = None
    expected: str | None = None
    html_line: int | None = None

    def fingerprint_parts(self) -> tuple:
        """Identidad estable entre corridas: no incluye el valor observado.

        Asi el mismo problema en la misma card se reconoce semana a semana
        aunque el numero haya cambiado, que es lo que permite decir
        "nuevo / recurrente / resuelto" en vez de repetir la lista entera.
        """
        return (self.rule, self.tab or "", self.panel or "",
                self.chart_key or "", self.field or "")


@dataclass
class Execution:
    """Resultado de correr un dataset con un juego concreto de filtros."""
    comp_key: str
    chart_key: str
    dataset_key: str | None
    filters: dict
    rows: list = dc_field(default_factory=list)
    columns: set = dc_field(default_factory=set)
    error: str | None = None
    elapsed_ms: int = 0


@dataclass
class Context:
    topo: object
    execs: dict           # comp_key -> Execution
    charts: dict          # chart_key -> {dataset_key, filters, tab_key}

    def ex(self, node) -> Execution | None:
        return self.execs.get(node.comp_key)

    def value(self, node):
        """Valor que el nodo pinta en pantalla, o None si no se pudo calcular."""
        ex = self.ex(node)
        if ex is None or ex.error is not None:
            return None
        return reduce_rows(ex.rows, node.field, node.reduce)

    def _base(self, node, ex=None) -> dict:
        ex = ex or self.ex(node)
        return dict(
            tab=node.tab, panel=node.panel, where=node.where(),
            chart_key=node.chart_key, field=node.field,
            dataset_key=(ex.dataset_key if ex else None), html_line=node.line,
        )


# --- R01 ---------------------------------------------------------------------
def r01_dataset_error(ctx) -> list:
    """El dataset no corre: SQL roto, timeout, o chart_key que no existe."""
    out, seen = [], set()
    for node in ctx.topo.nodes:
        ex = ctx.ex(node)
        if ex is None or ex.error is None or ex.comp_key in seen:
            continue
        seen.add(ex.comp_key)
        missing = ex.dataset_key is None
        out.append(Finding(
            rule="dataset_error", severity=CRITICAL,
            message=("Esta card no esta conectada a ningun dato: se ve vacia siempre"
                     if missing else "Esta card no carga: la consulta que la alimenta "
                                     "esta fallando"),
            observed=ex.error, expected="ejecuta sin error",
            **ctx._base(node, ex),
        ))
    return out


# --- R02 ---------------------------------------------------------------------
def r02_field_missing(ctx) -> list:
    """La columna que la card lee no viene en la respuesta: se pinta vacia.

    Es el sintoma tipico de un rename de columna en el SQL que no se propago al
    HTML. La card no da error: muestra un guion, y nadie se entera.
    """
    out, seen = [], set()
    for node in ctx.topo.nodes:
        ex = ctx.ex(node)
        if ex is None or ex.error or not ex.rows or not node.field:
            continue
        if node.reduce == "count":
            continue                      # count no lee ninguna columna
        for fld in filter(None, (node.field, node.corte_field)):
            key = (node.chart_key, fld)
            if fld in ex.columns or key in seen:
                continue
            seen.add(key)
            out.append(Finding(
                rule="field_missing", severity=CRITICAL,
                message=(f"La card busca un dato que ya no existe con ese nombre "
                     f"('{fld}'), asi que queda en blanco"),
                observed=f"columnas: {', '.join(sorted(ex.columns))[:200]}",
                expected=f"'{fld}' presente",
                **{**ctx._base(node, ex), "field": fld},
            ))
    return out


# --- R03 ---------------------------------------------------------------------
def r03_empty_rows(ctx) -> list:
    """El dataset no devuelve ninguna fila.

    La gravedad la decide el propio HTML: una lista que declara
    `data-empty-text` fue disenada para poder estar vacia (un mes sin churn es
    una buena noticia, no un bug), mientras que un KPI sin filas se pinta como
    un guion y ahi si el usuario ve algo roto.
    """
    out = []
    by_comp = {}
    for node in ctx.topo.nodes:
        ex = ctx.ex(node)
        if ex is None or ex.error or ex.rows:
            continue
        by_comp.setdefault(ex.comp_key, []).append(node)

    for comp_key, nodes in by_comp.items():
        ex = ctx.execs[comp_key]
        kpis = [n for n in nodes if n.bind == "text" and n.reduce not in ("count", "count-distinct")]
        declares_empty = any(n.empty_text for n in nodes)
        if kpis and not declares_empty:
            sev = HIGH
            msg = "No hay ningun dato en este periodo, asi que el numero queda en blanco"
        elif declares_empty:
            sev = LOW
            msg = ("La lista esta vacia en este periodo. Puede ser normal: la pantalla "
                   "ya contempla que no haya movimiento")
        else:
            sev = MEDIUM
            msg = "La lista no tiene nada para mostrar en este periodo"
        out.append(Finding(
            rule="empty_rows", severity=sev, message=msg,
            observed="0 filas", expected="al menos 1 fila",
            **ctx._base(nodes[0], ex),
        ))
    return out


# --- R04 ---------------------------------------------------------------------
def r04_blank_value(ctx) -> list:
    """La card muestra el guion largo aunque el dataset trajo datos.

    Se excluyen los deltas: un delta mensual sin mes previo devuelve null por
    diseno y pintar un guion ahi es correcto.
    """
    out = []
    for node in ctx.topo.nodes:
        if node.bind != "text" or not node.field:
            continue
        if node.fmt in _DELTA_FMTS or node.reduce in _DELTA_REDUCES:
            continue
        ex = ctx.ex(node)
        if ex is None or ex.error or not ex.rows or node.field not in ex.columns:
            continue                      # ya cubierto por R01/R02/R03
        val = reduce_rows(ex.rows, node.field, node.reduce)
        if not renders_as_empty(val, node.fmt):
            continue

        if val is not None and val != "":
            # Hay dato, pero es texto y el formateador es numerico: el JS hace
            # +v -> NaN y pinta un guion. Le falta data-fmt="raw" al nodo.
            # Es un bug del HTML, no de la metrica, y tiene arreglo directo.
            out.append(Finding(
                rule="blank_value", severity=HIGH,
                message=(f"Muestra un guion donde deberia decir \u00ab{val}\u00bb. "
                         f"El dato existe, pero la pantalla lo esta tratando como si "
                         f"fuera un numero y no un texto"),
                observed=repr(val), expected="el texto renderizado",
                **ctx._base(node, ex),
            ))
            continue

        zero_denom = next(
            (c for c, v in (ex.rows[0] or {}).items()
             if _DENOMINATOR.search(c) and _num(v) == 0),
            None,
        )
        if zero_denom:
            sev = LOW
            msg = ("Muestra un guion porque no hubo movimiento en este periodo. "
                   "No es un error")
        elif node.fmt in _PERCENT_FMTS:
            # Un porcentaje nulo es, casi siempre, la guarda NULLIF(den, 0) que
            # usa todo el repo: no hubo base para calcularlo en el periodo.
            # Sigue valiendo la pena verlo (puede ser que la base este mal
            # armada), pero no es lo mismo que una metrica rota.
            sev = MEDIUM
            msg = ("No se puede calcular este porcentaje: no hubo casos en el "
                   "periodo sobre los cuales sacarlo")
        else:
            sev = HIGH
            msg = "Este numero llega vacio cuando deberia traer un valor"
        out.append(Finding(
            rule="blank_value", severity=sev, message=msg,
            observed=repr(val), expected="un valor numerico",
            **ctx._base(node, ex),
        ))
    return out


# --- R05 ---------------------------------------------------------------------
def r05_pct_out_of_range(ctx) -> list:
    """Un porcentaje fuera de [0, 100]: casi siempre num/den mal armado."""
    out = []
    for node in ctx.topo.nodes:
        if node.fmt not in _PERCENT_FMTS or node.reduce in _DELTA_REDUCES:
            continue
        val = _num(ctx.value(node))
        if val is None or 0 <= val <= 100:
            continue
        elastic = bool(_CAN_EXCEED_100.search(node.field or ""))
        if val > 100 and elastic and val <= 1000:
            continue
        if val > 1000:
            sev = CRITICAL
            msg = (f"Este porcentaje da {val:.0f}%. Parece que se esta mostrando una "
                   f"fraccion como si fuera un porcentaje")
        elif val < 0:
            sev = HIGH
            msg = f"Este porcentaje da negativo ({val:.2f}%), y eso no puede ser"
        else:
            sev = HIGH
            msg = f"Este porcentaje da {val:.2f}%, o sea mas de 100%. No tiene sentido"
        out.append(Finding(
            rule="pct_out_of_range", severity=sev, message=msg,
            observed=f"{val:.2f}%", expected="entre 0% y 100%",
            **ctx._base(node),
        ))
    return out


# --- R07 ---------------------------------------------------------------------
def r07_negative_count(ctx) -> list:
    """Un conteo negativo: no existe "menos tres clientes"."""
    out = []
    for node in ctx.topo.nodes:
        if node.fmt not in _COUNT_FMTS or node.reduce in _DELTA_REDUCES:
            continue
        if node.fmt in _DELTA_FMTS or _SIGNED_FIELD.search(node.field or ""):
            continue
        val = _num(ctx.value(node))
        if val is None or val >= 0:
            continue
        out.append(Finding(
            rule="negative_count", severity=HIGH,
            message=(f"Esta contando en negativo ({val:g}). Un conteo no puede dar "
                     f"menos de cero"),
            observed=f"{val:g}", expected=">= 0",
            **ctx._base(node),
        ))
    return out


# --- R08 ---------------------------------------------------------------------
def r08_hero_vs_detail(ctx) -> list:
    """El numero del drawer no coincide con su propio detalle.

    Es el error que mas se repite y el que hoy solo se ve abriendo el panel a
    mano: hero y detalle salen de datasets distintos que nada obliga a
    mantener en paridad.
    """
    from .topology import hero_detail_pairs

    out = []
    for pair in hero_detail_pairs(ctx.topo):
        hero_val = _num(ctx.value(pair.hero))
        det_val = _num(ctx.value(pair.detail))
        if hero_val is None or det_val is None:
            continue
        # El chart_key puede ocultar el scope: am_table_candidate_churn_window_detail
        # resuelve al dataset candidate_churn_window_MONTH_detail, que recorre
        # varios meses mientras el hero mira una sola ventana. Comparar sus
        # totales seria comparar cosas distintas.
        hero_ds = (ctx.ex(pair.hero).dataset_key or "") if ctx.ex(pair.hero) else ""
        det_ds = (ctx.ex(pair.detail).dataset_key or "") if ctx.ex(pair.detail) else ""
        scoped = ("_month" in det_ds or "_history" in det_ds) and \
                 not ("_month" in hero_ds or "_history" in hero_ds)
        if scoped:
            continue
        # La plata se compara con tolerancia: el detalle puede redondear por fila.
        tol = max(1.0, abs(hero_val) * 0.01) if pair.kind == "sum" else 0.0
        if abs(hero_val - det_val) <= tol:
            continue
        det_ex = ctx.ex(pair.detail)
        strong = pair.confidence == "strong"
        out.append(Finding(
            rule="hero_vs_detail", severity=CRITICAL if strong else LOW,
            message=(
                f"El numero grande dice {hero_val:g}, pero al abrir el detalle da "
                f"{det_val:g}. No coinciden"
                + ("" if strong else ". Puede que no sean exactamente la misma metrica, "
                   "conviene confirmarlo")
            ),
            observed=f"hero {hero_val:g} vs detalle {det_val:g}",
            expected="mismo valor",
            tab=pair.hero.tab, panel=pair.panel,
            where=f"{pair.panel_title or pair.panel} · {pair.hero.label or 'hero'}",
            chart_key=pair.hero.chart_key, field=pair.hero.field,
            dataset_key=(det_ex.dataset_key if det_ex else None),
            html_line=pair.hero.line,
        ))
    return out


# --- R12 ---------------------------------------------------------------------
def r12_cross_tab_divergence(ctx) -> list:
    """La misma metrica muestra numeros distintos en pestanas distintas.

    No siempre es un bug (una pestana puede mirar otra ventana a proposito),
    pero es exactamente lo que la gente reporta como "no coincide". Se informa
    con el valor de cada pestana para que la decision sea de un humano.
    """
    # La clave incluye los FILTROS: la misma metrica con ventanas distintas en
    # dos pestanas debe dar distinto (Growth muestra la semana y AM los 30
    # dias). Sin eso la regla marcaba como error algo que es el diseno.
    groups = {}
    for node in ctx.topo.nodes:
        if node.bind != "text" or not node.field or not node.tab:
            continue
        key = (node.chart_key, node.field, node.reduce,
               tuple(sorted(node.filters.items())))
        groups.setdefault(key, {}).setdefault(node.tab, []).append(node)

    out = []
    for (chart_key, fld, _red, _filters), by_tab in groups.items():
        if len(by_tab) < 2:
            continue
        vals = {}
        for tab, nodes in by_tab.items():
            v = _num(ctx.value(nodes[0]))
            if v is not None:
                vals[tab] = (v, nodes[0])
        if len(vals) < 2 or len({round(v, 6) for v, _ in vals.values()}) == 1:
            continue
        detail = ", ".join(f"{t}={v:g}" for t, (v, _) in sorted(vals.items()))
        any_node = next(iter(vals.values()))[1]
        out.append(Finding(
            rule="cross_tab_divergence", severity=CRITICAL,
            message=(f"'{fld}' muestra valores distintos en cada pestana con los "
                     f"MISMOS filtros: {detail}"),
            observed=detail, expected="el mismo valor en todas las pestanas",
            tab="/".join(sorted(vals)), panel=None,
            where=f"{chart_key}[{fld}] en {len(vals)} pestanas",
            chart_key=chart_key, field=fld,
            dataset_key=(ctx.ex(any_node).dataset_key if ctx.ex(any_node) else None),
            html_line=any_node.line,
        ))
    return out


ALL_RULES = [
    r01_dataset_error, r02_field_missing, r03_empty_rows, r04_blank_value,
    r05_pct_out_of_range, r07_negative_count, r08_hero_vs_detail,
    r12_cross_tab_divergence,
]


def run_all(ctx, only=None) -> list:
    rules = [r for r in ALL_RULES if not only or r.__name__.split("_")[0] in only]
    out = []
    for rule in rules:
        out.extend(rule(ctx))
    order = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3}
    out.sort(key=lambda f: (order.get(f.severity, 9), f.tab or "", f.rule))
    return out


# --- R06 ---------------------------------------------------------------------
# Pares numerador/denominador que el propio HTML muestra juntos ("12 / 47").
_NUM_DEN_HINTS = (
    ("_dd", "_sqls"), ("_nda", "_sqls"), ("_cw", "_sqls"), ("_wins", "_opps"),
    ("retenidos", "inicio"), ("placed", "total"), ("con_candidatos", "total"),
)


def r06_ratio_inverted(ctx) -> list:
    """Un numerador mayor que su denominador: el subconjunto no puede superar al todo.

    Se detecta sobre la fila devuelta, buscando pares de columnas que el
    dashboard muestra como "A / B". Es el sintoma tipico de un JOIN que duplica
    filas del numerador.
    """
    out, seen = [], set()
    for node in ctx.topo.nodes:
        ex = ctx.ex(node)
        if ex is None or ex.error or not ex.rows or ex.comp_key in seen:
            continue
        seen.add(ex.comp_key)
        row = ex.rows[0]
        for num_hint, den_hint in _NUM_DEN_HINTS:
            for num_col in [c for c in row if c.endswith(num_hint) or c == num_hint]:
                prefix = num_col[: -len(num_hint)] if num_col.endswith(num_hint) else ""
                den_col = next(
                    (c for c in row
                     if (c == prefix + den_hint or c == den_hint) and c != num_col),
                    None,
                )
                if not den_col:
                    continue
                a, b = _num(row.get(num_col)), _num(row.get(den_col))
                if a is None or b is None or b < 0 or a <= b:
                    continue
                out.append(Finding(
                    rule="ratio_inverted", severity=HIGH,
                    message=(f"La parte es mas grande que el total: {a:g} de {b:g}. "
                             f"No tiene sentido"),
                    observed=f"{a:g} / {b:g}", expected=f"{num_col} <= {den_col}",
                    **{**ctx._base(node, ex), "field": num_col},
                ))
    return out


# --- R11 ---------------------------------------------------------------------
_MIX_PAIRS = (
    ("staffing_pct_of_total", "recruiting_pct_of_total"),
    ("churn_real_pct", "retention_pct"),
)


def r11_mix_not_100(ctx) -> list:
    """Dos porcentajes que reparten un total y no suman 100."""
    out, seen = [], set()
    for node in ctx.topo.nodes:
        ex = ctx.ex(node)
        if ex is None or ex.error or not ex.rows or ex.comp_key in seen:
            continue
        seen.add(ex.comp_key)
        row = ex.rows[0]
        for a_col, b_col in _MIX_PAIRS:
            a, b = _num(row.get(a_col)), _num(row.get(b_col))
            if a is None or b is None or (a == 0 and b == 0):
                continue
            total = a + b
            if abs(total - 100) <= 0.5:
                continue
            out.append(Finding(
                rule="mix_not_100", severity=HIGH,
                message=(f"Estos dos porcentajes tendrian que sumar 100% entre los dos "
                         f"y suman {total:.2f}%"),
                observed=f"{a:.2f}% + {b:.2f}% = {total:.2f}%", expected="100%",
                **{**ctx._base(node, ex), "field": f"{a_col}+{b_col}"},
            ))
    return out


# --- R14 ---------------------------------------------------------------------
_ID_COL = re.compile(r"_id$|^id$")


def r14_duplicate_rows(ctx) -> list:
    """Filas indistinguibles en un detalle del drawer.

    Solo se mira la fila COMPLETA duplicada. Repetir una entidad es legitimo
    (un candidato con dos colocaciones), pero dos filas identicas caracter por
    caracter tienen dos causas posibles y hay que abrir el caso para saber cual:
    un JOIN mal cardinalizado que infla el conteo, o dos entidades reales
    distintas que el detalle no muestra con suficiente columna como para
    distinguirlas. Por eso no se afirma que el numero este mal.
    """
    out, seen = [], set()
    for node in ctx.topo.nodes:
        ex = ctx.ex(node)
        if ex is None or ex.error or len(ex.rows) < 2:
            continue
        if not (ex.dataset_key or "").endswith("detail") or ex.dataset_key in seen:
            continue
        seen.add(ex.dataset_key)
        keys = [tuple(sorted((k, str(v)) for k, v in r.items())) for r in ex.rows]
        dupes = len(keys) - len(set(keys))
        if not dupes:
            continue
        out.append(Finding(
            rule="duplicate_detail_rows", severity=MEDIUM,
            message=(f"En el detalle hay {dupes} "
                     + ("fila repetida" if dupes == 1 else "filas repetidas")
                     + f" de {len(ex.rows)}. O esta contando de mas, o son cosas "
                     "distintas que en pantalla no se pueden diferenciar"),
            observed=f"{dupes} fila(s) identica(s)",
            expected="cada fila distinguible de las demas",
            **ctx._base(node, ex),
        ))
    return out


# --- R13 ---------------------------------------------------------------------
_DATE_COL = re.compile(r"date|fecha|_d$|_at$|mes|month")
# Datasets que miran cohortes cerradas o historia: estar "viejos" es correcto.
# `revenue_outbound_*`: son acumulados del año (YTD) aunque la key no diga "ytd";
# que el close win más nuevo sea de hace meses es el dato, no un pipeline caído.
_STALE_EXEMPT = re.compile(
    r"lifetime|cohort|history|ytd|all_time|churn_window|revenue_outbound"
)


def r13_stale_data(ctx, max_days=60) -> list:
    """La fecha mas nueva del dataset quedo vieja: dejo de llegar informacion."""
    from datetime import date

    out, seen = [], set()
    today = date.today()
    for node in ctx.topo.nodes:
        ex = ctx.ex(node)
        if ex is None or ex.error or not ex.rows:
            continue
        if _STALE_EXEMPT.search(ex.dataset_key or "") or ex.dataset_key in seen:
            continue
        seen.add(ex.dataset_key)
        newest, col = None, None
        for c in ex.columns:
            if not _DATE_COL.search(c):
                continue
            for r in ex.rows:
                v = str(r.get(c) or "")[:10]
                if len(v) == 10 and v[4] == "-" and (newest is None or v > newest):
                    newest, col = v, c
        if not newest:
            continue
        try:
            age = (today - date(int(newest[:4]), int(newest[5:7]), int(newest[8:10]))).days
        except ValueError:
            continue
        if age <= max_days:
            continue
        out.append(Finding(
            rule="stale_data", severity=MEDIUM,
            message=(f"El dato mas nuevo es del {newest}, hace {age} dias. Puede que "
                     f"haya dejado de actualizarse"),
            observed=f"{newest} ({age}d)", expected=f"< {max_days} dias",
            **{**ctx._base(node, ex), "field": col},
        ))
    return out


# --- R16 ---------------------------------------------------------------------
def r16_slow_query(ctx, threshold_ms=10000) -> list:
    """Un dataset que tarda demasiado: la card llega tarde o el usuario ve '—'."""
    out = []
    for comp_key, ex in ctx.execs.items():
        if ex.error or ex.elapsed_ms < threshold_ms:
            continue
        node = next((n for n in ctx.topo.nodes if n.comp_key == comp_key), None)
        if node is None:
            continue
        out.append(Finding(
            rule="slow_query", severity=LOW,
            message=f"Esta card tarda {ex.elapsed_ms / 1000:.1f} segundos en cargar",
            observed=f"{ex.elapsed_ms}ms", expected=f"< {threshold_ms}ms",
            **ctx._base(node, ex),
        ))
    return out


# --- R09 ---------------------------------------------------------------------
def r09_detail_ignores_window(ctx) -> list:
    """Un detalle que devuelve lo mismo con cualquier ventana.

    Es el defecto que mas se repite: el `_detail` no llama a window_bounds(), y
    entonces el drawer muestra siempre el historico completo mientras la card
    de al lado si respeta el periodo. Los dos numeros no cuadran y el detalle
    no cambia aunque muevas el filtro.

    El contraste se corre en el runner (necesita ir a la base); aca solo se
    interpretan los resultados que dejo en ctx.window_probe.
    """
    out = []
    for dataset_key, info in (getattr(ctx, "window_probe", None) or {}).items():
        if not info.get("identical") or not info.get("rows"):
            continue
        node = info["node"]
        out.append(Finding(
            rule="detail_ignores_window", severity=CRITICAL,
            message=(f"Al cambiar el filtro de fechas el numero de la card cambia, "
                     f"pero el detalle sigue mostrando siempre las mismas "
                     f"{info['rows']} filas. El detalle no esta respetando el filtro"),
            observed=f"KPI ({info['kpi']}) se mueve, detalle no",
            expected="distinta cantidad de filas segun la ventana",
            **{**ctx._base(node), "dataset_key": dataset_key},
        ))
    return out


ALL_RULES = [
    r01_dataset_error, r02_field_missing, r03_empty_rows, r04_blank_value,
    r05_pct_out_of_range, r06_ratio_inverted, r07_negative_count,
    r08_hero_vs_detail, r09_detail_ignores_window, r11_mix_not_100,
    r12_cross_tab_divergence, r13_stale_data, r14_duplicate_rows, r16_slow_query,
]
