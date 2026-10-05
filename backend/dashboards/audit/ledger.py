"""Libro de hechos: cruza todos los detalles del dashboard entre si.

Las reglas de `rules.py` miran cada card contra SU drawer. Eso no ve el caso que
la motivo: Restor Medical SPA (baja 30-sep) salia como churn de septiembre en
Client churn y de octubre en el CRR. Cada card cuadraba consigo misma; el
problema era entre dos metricas distintas (2026-10-02).

El dashboard no son 1219 numeros independientes: todos salen de pocos HECHOS
(un cliente se va, un contractor arranca, una opp se cierra). Cada detalle que
lista un hecho declara en su DATASET una etiqueta `audit`:

    "audit": [{
        "fact": "cliente_baja",          # que hecho lista
        "entity": "client_name",         # columna con la clave
        "match": {"tipo": "^churn_inicio$"},  # que filas son ese hecho (regex)
        "month_col": "mes",              # opcional: si no, el mes de la ventana
        "date_col": "fecha_baja",        # opcional: chequea que caiga en el mes
        "excluye": ["nuevo_en_mes"],     # flags de canon.FLAGS que no cuenta
    }]

El libro corre cada detalle etiquetado mes por mes y lo compara contra el
hecho canonico (`canon.py`). Para cada hecho y cada mes:

  * el detalle lo pone en OTRO mes  -> `hecho_mes_distinto` (el caso Restor)
  * el detalle no lo tiene          -> `hecho_faltante`
  * el detalle tiene algo que no paso -> `hecho_sobrante`

salvo que un flag que el detalle declara excluir lo explique. Como todos se
miden contra la misma fuente, cualquier par de detalles queda cruzado sin
escribir una regla por par.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from dashboards.datasets import get as get_dataset, list_all

from . import canon as C
from . import rules as R


def months_back(n: int, today: date | None = None) -> list:
    """Los ultimos `n` meses, incluido el actual, como 'YYYY-MM'."""
    d = (today or date.today()).replace(day=1)
    out = []
    for _ in range(n):
        out.append(C.month_key(d))
        d = (d - timedelta(days=1)).replace(day=1)
    return sorted(out)


def _shift(month: str, k: int) -> str:
    y, m = int(month[:4]), int(month[5:7]) + k
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def tagged_datasets() -> list:
    out = []
    # list_all() es el listado publico y no trae `audit`: la etiqueta se lee del
    # DATASET completo.
    for meta in list_all():
        for spec in (get_dataset(meta["key"]) or {}).get("audit") or []:
            out.append((meta["key"], spec))
    return out


def _rows_for(ex, spec, window_month: str) -> list:
    out = []
    match = {k: re.compile(v) for k, v in (spec.get("match") or {}).items()}
    for r in ex.rows:
        if any(not rx.search(str(r.get(col) or "")) for col, rx in match.items()):
            continue
        # `entity` es una columna o varias (contractor = candidato @ cliente).
        cols = spec["entity"] if isinstance(spec["entity"], list) else [spec["entity"]]
        parts = [r.get(c) for c in cols]
        if not all(parts):
            continue
        dval = str(r.get(spec["date_col"]))[:10] if spec.get("date_col") and r.get(spec["date_col"]) else None
        if spec.get("month_from_date"):
            # Detalles de cohorte: listan bajas de meses anteriores dentro de su
            # ventana, así que el mes del hecho es el de su fecha, no el de la ventana.
            if not dval:
                continue
            month = C.month_key(dval)
        elif spec.get("month_col"):
            month = C.month_key(str(r.get(spec["month_col"])))
        else:
            month = window_month
        out.append({
            "entity": C.entity_key(*parts), "label": " @ ".join(map(str, parts)), "month": month,
            "date": dval,
        })
    return out


def collect(conn, months: list, execute, progress=None) -> dict:
    """Corre cada detalle etiquetado en cada mes. Devuelve el libro.

    `execute` es `runner._execute`: misma conexion, mismo timeout, mismos errores.
    """
    tagged = tagged_datasets()
    by_ds = {}
    for key, spec in tagged:
        by_ds.setdefault(key, []).append(spec)

    entries = {}   # (dataset, fact) -> list de filas
    errors = {}
    total = len(by_ds) * len(months)
    i = 0
    for key, specs in sorted(by_ds.items()):
        for month in months:
            i += 1
            ex = execute(conn, "ledger", key, key, {**(specs[0].get("filters") or {}), "mes": month})
            if progress:
                progress(i, total, ex)
            if ex.error:
                errors[key] = ex.error
                continue
            for spec in specs:
                entries.setdefault((key, spec["fact"]), []).extend(_rows_for(ex, spec, month))

    # El canon cubre un mes de mas a cada lado: una baja del 31-ago que un detalle
    # pone en septiembre tiene que encontrarse para decir "mes distinto" y no
    # "sobrante".
    ini = date.fromisoformat(_shift(months[0], -1) + "-01")
    fin = date.fromisoformat(_shift(months[-1], 1) + "-01") + timedelta(days=31)
    facts = {f for _, f in entries}
    canon = []
    for fact in sorted(facts):
        fn = C.CANON.get(fact)
        if fn:
            canon.extend(fn(conn, ini, fin))
    return {"months": months, "entries": entries, "canon": canon,
            "errors": errors, "specs": {(k, s["fact"]): s for k, s in tagged}}


def _node_for(ctx, dataset_key):
    """Un nodo del HTML que use ese dataset, para que el hallazgo diga donde mirar."""
    for node in ctx.topo.nodes:
        chart = ctx.charts.get(node.chart_key) or {}
        if chart.get("dataset_key") == dataset_key:
            return node
    return None


def compare(ctx, book) -> list:
    months = set(book["months"])
    canon = {}
    for c in book["canon"]:
        canon.setdefault((c["fact"], c["entity"]), []).append(c)

    out = []
    for (ds, fact), rows in sorted(book["entries"].items()):
        spec = book["specs"][(ds, fact)]
        excluye = set(spec.get("excluye") or [])
        node = _node_for(ctx, ds)
        base = dict(tab=node.tab if node else None, panel=node.panel if node else None,
                    chart_key=node.chart_key if node else None, dataset_key=ds,
                    html_line=node.line if node else None)

        have = {}
        for r in rows:
            have.setdefault(r["entity"], {})[r["month"]] = r
            # El detalle trae su propia fecha y no cae en el mes en que lo lista.
            if r["date"] and C.month_key(r["date"]) != r["month"]:
                out.append(R.Finding(
                    rule="hecho_fecha_fuera_de_mes", severity=R.HIGH,
                    message=(f"{r['label']}: lo lista en {r['month']} pero su fecha es "
                             f"{r['date']}"),
                    observed=f"{r['month']} vs {r['date']}", expected="la fecha cae en el mes",
                    where=f"{fact} · {r['label']}", field=f"{fact}:{r['entity']}", **base))

        # Lo que paso, y que este detalle deberia contar.
        expected = {}
        for (f, ent), evs in canon.items():
            if f != fact:
                continue
            for ev in evs:
                if ev["flags"] & excluye:
                    continue
                expected.setdefault(ent, {})[ev["month"]] = ev

        seen = set()
        for ent in sorted(set(have) | set(expected)):
            got = have.get(ent, {})
            exp = expected.get(ent, {})
            all_evs = canon.get((fact, ent), [])
            label = next(iter(got.values()), None) or next(iter(exp.values()), None) or {}
            label = label.get("label") or ent
            for m in sorted(set(exp) - set(got)):
                if m not in months:
                    continue
                near = [g for g in got if g not in exp and abs(_mdiff(g, m)) == 1]
                if near:
                    seen.add((ent, near[0]))
                    out.append(R.Finding(
                        rule="hecho_mes_distinto", severity=R.CRITICAL,
                        message=(f"{label}: la baja es del {exp[m]['date']} ({m}), pero esta "
                                 f"card la cuenta en {near[0]}. El mismo hecho cae en meses "
                                 f"distintos segun la card"),
                        observed=f"{near[0]}", expected=m,
                        where=f"{fact} · {label}", field=f"{fact}:{ent}", **base))
                elif spec.get("scope") == "subset":
                    # El detalle mira una parte a propósito (cohorte, cartera del AM):
                    # que no tenga un hecho no dice nada. Sólo se le chequea el mes.
                    continue
                else:
                    out.append(R.Finding(
                        rule="hecho_faltante", severity=R.HIGH,
                        message=(f"{label}: la baja es del {exp[m]['date']} y esta card no la "
                                 f"cuenta en {m}"
                                 + _flags_txt(exp[m]["flags"])),
                        observed="ausente", expected=m,
                        where=f"{fact} · {label}", field=f"{fact}:{ent}", **base))
            for m in sorted(set(got) - set(exp)):
                if m not in months or (ent, m) in seen:
                    continue
                if any(abs(_mdiff(e, m)) == 1 and e not in got for e in exp):
                    continue  # ya informado como mes distinto desde el otro lado
                why = [ev for ev in all_evs if ev["month"] == m]
                if why:
                    # Paso, pero este detalle declaro no contarlo y lo cuenta igual.
                    msg = (f"{label}: esta card la cuenta en {m} aunque declara excluir "
                           f"{', '.join(sorted(why[0]['flags'] & excluye))}")
                else:
                    msg = (f"{label}: esta card la cuenta en {m}, pero en las tablas no hay "
                           f"ninguna baja ese mes")
                out.append(R.Finding(
                    rule="hecho_sobrante", severity=R.HIGH, message=msg,
                    observed=m, expected="ausente",
                    where=f"{fact} · {label}", field=f"{fact}:{ent}", **base))

    out = _group(out)
    for ds, err in sorted(book["errors"].items()):
        out.append(R.Finding(
            rule="hecho_dataset_error", severity=R.HIGH,
            message=f"El libro de hechos no pudo correr {ds}: {err}",
            dataset_key=ds, where=ds))
    return out


def coverage(ctx) -> list:
    """Detalles que todavia no estan en el libro: lo que la auditoria NO cruza."""
    tagged = {k for k, _ in tagged_datasets()}
    used = {(c or {}).get("dataset_key") for c in ctx.charts.values()}
    return sorted(d for d in used if d and d.endswith("detail") and d not in tagged)


_TITLES = {
    "hecho_mes_distinto": "{n} baja(s) en un mes distinto al de su fecha",
    "hecho_faltante": "{n} baja(s) que pasaron y esta card no cuenta",
    "hecho_sobrante": "{n} baja(s) que esta card cuenta y no corresponden",
    "hecho_fecha_fuera_de_mes": "{n} fila(s) listadas en un mes que no es el de su fecha",
}
_MAX_CASOS = 8


def _group(findings) -> list:
    """Un hallazgo por (regla, card, hecho), con los casos adentro.

    Un mismo problema de criterio (la baja del ultimo dia cae en el mes siguiente)
    toca a todas las bajas de fin de mes: sin agrupar eran 40 lineas en el mail por
    una sola causa. Se agrupa por card porque el arreglo se hace en una card.
    """
    # Si ya dice "mes distinto" para esa baja, "fecha fuera de mes" es lo mismo.
    distinto = {(f.dataset_key, f.field) for f in findings if f.rule == "hecho_mes_distinto"}
    findings = [f for f in findings
                if not (f.rule == "hecho_fecha_fuera_de_mes" and (f.dataset_key, f.field) in distinto)]

    groups = {}
    for f in findings:
        fact = (f.field or ":").split(":")[0]
        groups.setdefault((f.rule, f.dataset_key, fact), []).append(f)
    out = []
    for (rule, ds, fact), fs in groups.items():
        f0 = fs[0]
        casos = [f.message for f in fs]
        extra = len(casos) - _MAX_CASOS
        msg = (_TITLES.get(rule, rule).format(n=len(fs)) + f" ({fact}): "
               + " | ".join(casos[:_MAX_CASOS]) + (f" | …y {extra} mas" if extra > 0 else ""))
        out.append(R.Finding(
            rule=rule, severity=f0.severity, message=msg,
            observed=f"{len(fs)} caso(s)", expected="0",
            tab=f0.tab, panel=f0.panel, where=f"{fact} · {ds}",
            chart_key=f0.chart_key, dataset_key=ds,
            # Estable entre corridas: la card y el hecho, no los casos (que cambian).
            field=fact, html_line=f0.html_line))
    return out


def _mdiff(a: str, b: str) -> int:
    return (int(a[:4]) * 12 + int(a[5:7])) - (int(b[:4]) * 12 + int(b[5:7]))


def _flags_txt(flags) -> str:
    if not flags:
        return ""
    return " (" + "; ".join(C.FLAGS[f] for f in sorted(flags)) + ")"
