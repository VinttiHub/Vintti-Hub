"""Ejecuta los datasets del dashboard una sola vez cada uno y aplica las reglas.

No usa dashboards.executor.run_dataset por dos motivos concretos:

  1. run_dataset abre y cierra una conexion por llamada. Con ~320 datasets eso
     son ~320 handshakes TLS (~0.5s cada uno) tirados a la basura.
  2. Deduce las columnas de las filas devueltas, asi que un dataset vacio no
     reporta ninguna columna — y justamente ahi es donde hace falta saberlas,
     para poder decir "la card lee 'foo' y esa columna no existe".

La ejecucion es estrictamente secuencial sobre UNA conexion. RDS tiene
max_connections=81 y produccion ya usa ~60 en pico (backend/gunicorn.conf.py):
paralelizar la auditoria arriesga tirar el dashboard un lunes a la manana, que
es exactamente el momento en que la gente lo mira.
"""
from __future__ import annotations

import hashlib
import os
import re
import time

from dashboards.datasets import get as get_dataset
from dashboards.executor import _jsonable

from . import rules as R
from .topology import build as build_topology

# Datasets donde ser invariante a la ventana es correcto: miran cohortes
# cerradas, snapshots del presente o todo el historico por diseno.
WINDOW_EXEMPT = re.compile(
    r"lifetime|cohort|snapshot|_history|pipeline|risk|ytd|all_time|_current"
)

# Igual que dashboards/executor.py: si un dataset devuelve exactamente esto,
# la lista vino truncada y cualquier suma o conteo sobre ella miente.
ROW_LIMIT = 5000
STATEMENT_TIMEOUT = os.environ.get("DASHBOARD_AUDIT_STMT_TIMEOUT", "25s")


def load_charts(conn) -> dict:
    """chart_key -> {dataset_key, filters, tab_key} para el dashboard 'main'.

    Una sola query en vez de 280: es el mismo lookup que hace
    routes/dashboards_routes.py por cada request de card.
    """
    import json

    sql = """
        SELECT c.chart_key, c.dataset_key, c.config_json, c.tab_key
          FROM dashboard_charts c
          JOIN dashboards d ON d.id = c.dashboard_id
         WHERE d.slug = 'main'
    """
    out = {}
    with conn.cursor() as cur:
        cur.execute(sql)
        for chart_key, dataset_key, config, tab_key in cur.fetchall():
            if isinstance(config, str):
                try:
                    config = json.loads(config)
                except ValueError:
                    config = {}
            out[chart_key] = {
                "dataset_key": dataset_key,
                "filters": (config or {}).get("filters") or {},
                "tab_key": tab_key,
            }
    return out


def _open_connection():
    from db import get_connection

    conn = get_connection()
    # Sin autocommit, el primer SQL roto deja la conexion en
    # InFailedSqlTransaction y TODOS los datasets siguientes fallan en cascada:
    # el reporte se llenaria de errores falsos que tapan el error real.
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
        cur.execute("SET application_name = 'dashboard_audit'")
    return conn


def _execute(conn, comp_key, chart_key, dataset_key, filters) -> R.Execution:
    ex = R.Execution(comp_key=comp_key, chart_key=chart_key,
                     dataset_key=dataset_key, filters=filters)
    if dataset_key is None:
        ex.error = "chart_key sin fila en dashboard_charts"
        return ex

    dataset = get_dataset(dataset_key)
    if dataset is None:
        ex.error = f"dataset '{dataset_key}' no esta registrado"
        return ex

    t0 = time.monotonic()
    try:
        compute = dataset.get("compute")
        if callable(compute):
            # Datasets vivos (HubSpot): no tocan SQL y su latencia es ajena.
            rows = compute(filters) or []
            ex.rows = [{k: _jsonable(v) for k, v in r.items()} for r in rows[:ROW_LIMIT]]
            ex.columns = set(ex.rows[0]) if ex.rows else set()
        else:
            sql, params = dataset["query"](filters)
            with conn.cursor() as cur:
                cur.execute(sql, params)
                # De cur.description, no de las filas: asi un dataset vacio
                # igual reporta que columnas deberia tener.
                ex.columns = {c[0] for c in (cur.description or [])}
                cols = [c[0] for c in (cur.description or [])]
                ex.rows = [
                    {c: _jsonable(v) for c, v in zip(cols, row)}
                    for row in cur.fetchall()[:ROW_LIMIT]
                ]
    except Exception as exc:  # noqa: BLE001 - un dataset roto es un hallazgo, no un crash
        ex.error = f"{type(exc).__name__}: {exc}".strip()[:500]
    ex.elapsed_ms = int((time.monotonic() - t0) * 1000)
    return ex


def run(topo=None, tab=None, progress=None) -> tuple:
    """Corre la auditoria completa. Devuelve (findings, execs, topo).

    `tab` limita a una pestana (util para iterar rapido durante el desarrollo).
    """
    topo = topo or build_topology()
    nodes = [n for n in topo.nodes if not tab or n.tab == tab]

    conn = _open_connection()
    try:
        charts = load_charts(conn)

        wanted = {}
        for node in nodes:
            wanted.setdefault(node.comp_key, node)

        execs = {}
        for i, (comp_key, node) in enumerate(sorted(wanted.items()), 1):
            chart = charts.get(node.chart_key)
            dataset_key = (chart or {}).get("dataset_key")
            # Mismo merge que dashboards_routes.py: los filtros del chart son la
            # base y los del nodo (data-override-*) mandan por encima.
            filters = {**(chart or {}).get("filters", {}), **node.filters}
            execs[comp_key] = _execute(conn, comp_key, node.chart_key, dataset_key, filters)
            if progress:
                progress(i, len(wanted), execs[comp_key])
    finally:
        conn.close()

    ctx = R.Context(topo=topo, execs=execs, charts=charts)
    ctx.window_probe = window_contrast(execs, topo, charts, progress=progress)
    findings = R.run_all(ctx)
    findings.extend(_row_limit_findings(ctx, execs))
    return findings, execs, topo


def _row_limit_findings(ctx, execs) -> list:
    """R25: el dataset choco el techo de 5000 filas del executor.

    Cuando eso pasa, el drawer cuenta 5000 y no la cantidad real, y cualquier
    suma queda corta. Es silencioso y no da error: la card muestra un numero
    plausible pero incorrecto.
    """
    out = []
    seen = set()
    for node in ctx.topo.nodes:
        ex = execs.get(node.comp_key)
        if ex is None or ex.error or len(ex.rows) < ROW_LIMIT or ex.comp_key in seen:
            continue
        seen.add(ex.comp_key)
        out.append(R.Finding(
            rule="row_limit_hit", severity=R.CRITICAL,
            message=f"El dataset devolvio {ROW_LIMIT} filas: el executor lo trunco, "
                    "asi que los conteos y sumas de esta card estan por debajo del real",
            observed=f"{ROW_LIMIT} filas (techo)", expected=f"< {ROW_LIMIT} filas",
            **ctx._base(node, ex),
        ))
    return out


def _rows_hash(rows) -> str:
    raw = repr([sorted(r.items()) for r in rows]).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _variants(base, node) -> dict:
    """Contrastes de ventana, usando SOLO perillas que el dashboard manda de verdad.

    Nada de inventar parametros: `dias` lo entiende window_bounds() pero la UI
    nunca lo envia (no esta en FILTER_KEYS de control-dashboard.js), asi que
    contrastar con el marcaba como rotos a detalles que en pantalla cuadran
    perfecto. Un hallazgo que el usuario no puede reproducir es ruido.

    Se contrastan los cuatro mecanismos reales de periodo que conviven en el
    repo: `mes`, `desde/hasta`, `window` y, donde aplican, `periodo` y `meses`.
    """
    out = {
        "mes_a": {**base, "mes": "2026-07"},
        "mes_b": {**base, "mes": "2026-08"},
        "rango_a": {**base, "desde": "2026-01-01", "hasta": "2026-03-31"},
        "rango_b": {**base, "desde": "2026-01-01", "hasta": "2026-12-31"},
        "win_week": {**base, "window": "week"},
        "win_30d": {**base, "window": "30d"},
    }
    if "periodo" in node.overrides or "periodo" in base:
        out["per_semana"] = {**base, "periodo": "semana"}
        out["per_anio"] = {**base, "periodo": "anio"}
    if "meses" in node.overrides or "meses" in base:
        out["meses_1"] = {**base, "meses": "1"}
        out["meses_12"] = {**base, "meses": "12"}
    return out


_PAIRS = (("mes_a", "mes_b"), ("rango_a", "rango_b"), ("win_week", "win_30d"),
          ("per_semana", "per_anio"), ("meses_1", "meses_12"))


def window_contrast(execs, topo, charts, progress=None) -> dict:
    """Detecta el detalle que no sigue la ventana que su card SI sigue.

    La prueba no es "el detalle no cambia" a secas: un acumulador YTD tampoco
    cambia y esta bien asi. La prueba es que el KPI de la misma card cambie con
    la ventana y su detalle no — ahi los dos numeros dejan de cuadrar, que es
    justo lo que se ve como "el detalle da mal".
    """
    candidates = {}
    for node in topo.nodes:
        ex = execs.get(node.comp_key)
        if ex is None or ex.error or not ex.rows or not node.panel:
            continue
        ds = ex.dataset_key or ""
        if not ds.endswith("detail") or WINDOW_EXEMPT.search(ds):
            continue
        # El KPI del mismo panel es la referencia: si el se mueve, el detalle
        # tambien deberia.
        kpi = next(
            (e for n in topo.by_panel(node.panel)
             if (e := execs.get(n.comp_key)) and not e.error and e.rows
             and e.dataset_key and not e.dataset_key.endswith("detail")),
            None,
        )
        if kpi is not None and ds not in candidates:
            candidates[ds] = (node, ex, kpi)

    if not candidates:
        return {}

    out = {}
    conn = _open_connection()
    cache = {}

    def probe(dataset_key, chart_key, filters):
        key = (dataset_key, tuple(sorted(filters.items())))
        if key not in cache:
            ex = _execute(conn, "contrast", chart_key, dataset_key, filters)
            cache[key] = None if ex.error else (len(ex.rows), _rows_hash(ex.rows))
        return cache[key]

    try:
        for i, (ds, (node, det_ex, kpi_ex)) in enumerate(sorted(candidates.items()), 1):
            variants = _variants(dict(det_ex.filters), node)
            kpi_variants = _variants(dict(kpi_ex.filters), node)
            moved_kpi = False
            frozen_detail = True
            for a, b in _PAIRS:
                if a not in variants:
                    continue
                ka = probe(kpi_ex.dataset_key, kpi_ex.chart_key, kpi_variants[a])
                kb = probe(kpi_ex.dataset_key, kpi_ex.chart_key, kpi_variants[b])
                da = probe(ds, node.chart_key, variants[a])
                db = probe(ds, node.chart_key, variants[b])
                if None in (ka, kb, da, db):
                    continue
                if ka != kb:
                    moved_kpi = True
                    if da != db:
                        frozen_detail = False
                        break
            out[ds] = {
                "node": node, "rows": len(det_ex.rows),
                "identical": moved_kpi and frozen_detail,
                "kpi": kpi_ex.dataset_key,
            }
            if progress:
                progress(i, len(candidates), det_ex)
    finally:
        conn.close()
    return out
