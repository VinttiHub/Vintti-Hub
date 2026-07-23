"""OKRs 2026 → Google Sheet snapshot.

Botón "Actualizar OKRs" (tab Growth & Revenue del dashboard): calcula los valores
ACTUALES de las métricas de los OKRs y los escribe en la celda correcta del Google
Sheet de OKRs — columna = semana en curso (última fecha ≤ hoy en la fila de fechas),
fila = auto-detectada por el label del KR en la columna A.

Es el mismo patrón que `sales_snapshot_routes.py` (botón de Sales), pero:
  - Apunta a OTRO spreadsheet (el de OKRs 2026) y escribe en DOS pestañas de una:
    "OKR 2 - 2026" y "Sales NEW".
  - Cada pestaña tiene su propia lista de métricas y su propio formato de fecha
    (la de OKR usa MM/DD/YYYY tipo "07/20/2026"; la de Sales usa "20-Jul").
  - La fila de fechas NO tiene una celda literal "Date": se auto-detecta como la
    primera fila con ≥3 celdas que parsean como fecha; la columna de labels es la A.

Modos (preview → confirmar → commit):
  POST /okr/sheet-snapshot/preview  → calcula todo y devuelve celdas+valores SIN escribir.
  POST /okr/sheet-snapshot/commit   → recalcula y ESCRIBE las celdas (email-gated).
  GET  /okr/sheet-snapshot/debug    → lista pestañas + preview para inspeccionar layout.

Reusa infra existente: utils.sheets_utils.sheets_service (mismo service account que
Careers; el Sheet destino debe estar compartido con ese email como Editor) y
dashboards.executor.run_dataset (mismos datasets que las cards del dashboard).
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date

from flask import Blueprint, jsonify, request

from dashboards.executor import run_dataset, DatasetError
from utils.sheets_utils import sheets_service, a1_quote

try:  # today en hora Argentina (mismo criterio que los datasets)
    from dashboards.datasets._now import today_ar
except Exception:  # pragma: no cover - fallback defensivo
    from datetime import datetime, timedelta, timezone

    def today_ar() -> "date":
        return (datetime.now(timezone.utc) - timedelta(hours=3)).date()


bp = Blueprint("okr_snapshot", __name__, url_prefix="/okr")

# ---------------------------------------------------------------------------
# Config (todo overrideable por env)
# ---------------------------------------------------------------------------
DEFAULT_SPREADSHEET_ID = "1AWjj2ZO5oGSQCoTxTcjqvJrqetP0y4KAkZqA4YjyRqE"
SPREADSHEET_ID = os.getenv("OKR_SNAPSHOT_SPREADSHEET_ID") or DEFAULT_SPREADSHEET_ID
# Rango a leer (semanas a lo ancho → cubrir muchas columnas y bastantes filas).
READ_RANGE = "A1:BZ200"

# Acceso: cualquier usuario del dashboard (@vintti.com). Ampliable con env.
_ALLOWED_DOMAIN = "@vintti.com"


def _extra_editors() -> set[str]:
    raw = os.getenv("OKR_SNAPSHOT_EDITORS", "")
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


def _parse_iso(s):
    """YYYY-MM-DD → date | None."""
    try:
        p = str(s or "").strip().split("-")
        if len(p) == 3:
            return date(int(p[0]), int(p[1]), int(p[2]))
    except (ValueError, TypeError):
        return None
    return None


def _asof_override():
    """Fecha "as-of" para congelar el corte y comparar contra datos ya cargados.
    Prioridad: request (as_of|asof) > env OKR_SNAPSHOT_ASOF. None = comportamiento normal
    (usa hoy). Cuando está activa: elige la misma columna de esa fecha e inyecta corte a
    los datasets (ventanas rolling-30d y point-in-time terminan en esa fecha).
    OJO: no rebobina la BASE (los datasets históricos MRR/GMRR/ACPA reflejan el estado
    actual de la DB igual); sirve para las métricas parametrizadas por fecha."""
    req = request.get_json(silent=True) or {}
    raw = (req.get("as_of") or req.get("asof")
           or request.args.get("as_of") or request.args.get("asof")
           or os.getenv("OKR_SNAPSHOT_ASOF"))
    return _parse_iso(raw)


def _user_email() -> str | None:
    email = request.headers.get("X-User-Email") or request.args.get("user_email")
    if not email:
        body = request.get_json(silent=True) or {}
        email = body.get("user_email")
    return (email or "").strip().lower() or None


def _require_editor():
    email = _user_email()
    allowed = bool(email) and (email.endswith(_ALLOWED_DOMAIN) or email in _extra_editors())
    if not allowed:
        return jsonify({"error": "forbidden", "email": email}), 403
    return None


# ---------------------------------------------------------------------------
# Mapeo métricas → dataset / field / reduce / formato, POR PESTAÑA.
#   match  : prefijo normalizado del label del KR en la col A (case-insensitive).
#            Incluye el "krN" para desambiguar (los KR se repiten entre objetivos).
#   reduce : first (rows[0]) | last (rows[-1]) | sum (Σ)
#   fmt    : money | int | pct | days   (para display y para write de filas de TEXTO)
#   filters: dict pasado tal cual a run_dataset (mismos overrides que las cards).
# ---------------------------------------------------------------------------
OKR_METRICS = [
    # Objetivo 1 · Sustainable Growth
    {"key": "staffing_fee", "match": "kr3 staffing fee",
     "dataset": "staffing_window_summary", "field": "staffing_fee_avg", "reduce": "first", "fmt": "money", "filters": {}},
    {"key": "gmrr", "match": "kr4 gmrr",
     "dataset": "mrr_history", "field": "mrr_total", "reduce": "last", "fmt": "money", "filters": {"metric": "Revenue"}},
    {"key": "mrr", "match": "kr5 mrr",
     "dataset": "mrr_history", "field": "mrr_total", "reduce": "last", "fmt": "money", "filters": {"metric": "Fee"}},
    {"key": "new_clients_staffing", "match": "kr6 new clients staffing",
     "dataset": "new_clients_30d_total", "field": "new_clients_30d", "reduce": "first", "fmt": "int", "filters": {"window": "week"}},
    # recruiting_window_summary SÍ maneja window=week (tiene su propio _window_bounds).
    # Mismo filtro que la card gr_kpi_recruiting_window (data-override-window="week").
    {"key": "new_clients_recruiting", "match": "kr7 new clients recruiting",
     "dataset": "recruiting_window_summary", "field": "new_clients_window", "reduce": "first", "fmt": "int", "filters": {"window": "week"}},
    # Objetivo 2 · Client & Candidate Obsession
    {"key": "active_contractors", "match": "kr1 total contractors",
     "dataset": "active_headcount_30d_total", "field": "active_count", "reduce": "first", "fmt": "int", "filters": {}},
    {"key": "new_contractors_staffing", "match": "kr2 new candidates staffing",
     "dataset": "new_contractors_30d_total", "field": "new_contractors_30d", "reduce": "first", "fmt": "int", "filters": {"window": "week"}},
    {"key": "new_contractors_recruiting", "match": "kr3 new candidates recruiting",
     "dataset": "recruiting_window_summary", "field": "new_ftes_window", "reduce": "first", "fmt": "int", "filters": {"window": "week"}},
    {"key": "candidate_churn", "match": "kr4 churn candidatos",
     "dataset": "candidate_churn_30d_summary", "field": "churn_real_pct", "reduce": "first", "fmt": "pct", "filters": {}},
    {"key": "clients_multi", "match": "kr5 de clientes con",
     "dataset": "clients_multi_30d_summary", "field": "pct_percent", "reduce": "first", "fmt": "pct", "filters": {"modelo": "Staffing"}},
    {"key": "candidate_churn_m3", "match": "kr8 churn candidatos m3",
     "dataset": "candidate_churn_window_summary", "field": "churn_real_pct", "reduce": "first", "fmt": "pct", "filters": {}},
    {"key": "active_clients_staffing", "match": "kr9 active clients staffing",
     "dataset": "acpa_history", "field": "cuentas_activas", "reduce": "last", "fmt": "int", "filters": {"modelo": "Staffing"}},
    {"key": "client_churn_staffing", "match": "kr10 churn clients",
     "dataset": "client_churn_30d_summary", "field": "churn_real_pct", "reduce": "first", "fmt": "pct", "filters": {}},
    {"key": "replacements_placed", "match": "kr11 de reemplazos colocados",
     "dataset": "replacement_coverage_30d", "field": "placed_pct", "reduce": "first", "fmt": "pct", "filters": {}},
    # Objetivo 3 · Pipeline Explotion
    {"key": "active_pipeline_new", "match": "kr1 active pipeline",
     "dataset": "active_pipeline", "field": "pipeline_count_new", "reduce": "first", "fmt": "int", "filters": {}},
    {"key": "expected_pipeline_rev", "match": "kr2 expected pipeline revenue",
     "dataset": "pipeline_cr_minus_churn", "field": "net_mrr_fee_staffing_30d", "reduce": "first", "fmt": "money", "filters": {}},
    {"key": "sql_marketing", "match": "kr4 sql marketing",
     "dataset": "mkt_business_metrics", "field": "sqls", "reduce": "first", "fmt": "int", "filters": {"periodo": "mes"}},
    {"key": "new_opps_am", "match": "kr5 new opportunities by am",
     "dataset": "new_opps_am_windows", "field": "opps_last_week", "reduce": "first", "fmt": "int", "filters": {}},
    # Objetivo 4 · Operations Excellence
    # O4·KR2 = card de Sales "NDA → Close Win" (línea ~2756 dashboard.html): chart
    # sa_kpi_lead_channel_winrate_30d, campo total_win_rate (win-rate total = Close Win /
    # (Win+Lost) de TODOS los canales, ~30%). NO es nda_to_clientwin (cohorte volátil).
    {"key": "cr_nda_win_sales", "match": "kr2 conversion rate sql close",
     "dataset": "lead_channel_winrate_30d", "field": "total_win_rate", "reduce": "first", "fmt": "pct", "filters": {}},
    {"key": "cr_am", "match": "kr3 conversion rate am",
     "dataset": "lara_winrate_30d_summary", "field": "conversion_30d_pct", "reduce": "first", "fmt": "pct", "filters": {}},
    # O4·KR4 = Operations NDA → Close Win (win rate CW/(CW+CL) ~26%).
    {"key": "cr_nda_win_ops", "match": "kr4 conversion rate nda signed",
     "dataset": "nda_close_win_30d_summary", "field": "conversion_pct", "reduce": "first", "fmt": "pct", "filters": {"resultado": "Close Win"}},
    # KR5/6/7 = cards HERO de Operations (líneas ~4342/4373/4447 dashboard.html): SIN
    # override de modelo (todos los modelos). El data-override-modelo="Staffing" es de
    # otras tiles del área Staffing (líneas 1034/1042/1050), NO de estas hero.
    {"key": "new_placement_time", "match": "kr5 time to close win",
     "dataset": "placement_time_30d_summary", "field": "promedio_dias", "reduce": "first", "fmt": "days", "filters": {"resultado": "Close Win"}},
    {"key": "repl_placement_time", "match": "kr6 replacements",
     "dataset": "placement_time_repl_30d_summary", "field": "promedio_dias", "reduce": "first", "fmt": "days", "filters": {"resultado": "Close Win"}},
    {"key": "sent_hired", "match": "kr7 candidates hire",
     "dataset": "sent_hired_30d_summary", "field": "conversion_pct_general", "reduce": "first", "fmt": "pct", "filters": {}},
]

SALES_METRICS = [
    # Objetivo 1 · Revenue Engine
    {"key": "avg_recruiting_fee", "match": "kr4 avg recruiting fee",
     "dataset": "avg_recruiting_fee_30d", "field": "avg_fee", "reduce": "first", "fmt": "money", "filters": {}},
    {"key": "avg_staffing_fee", "match": "kr5 avg staffing fee",
     "dataset": "avg_staffing_fee_30d", "field": "avg_fee", "reduce": "first", "fmt": "money", "filters": {}},
    {"key": "new_clients_generated", "match": "kr6 new clients generated",
     "dataset": "new_clients_30d_total", "field": "new_clients_30d", "reduce": "first", "fmt": "int", "filters": {}},
    # Objetivo 2 · Ops Generation
    {"key": "pipeline_worth_outbound", "match": "kr2 pipeline worth generado por outbound",
     "dataset": "pipeline_outbound_ae", "field": "pipeline_worth", "reduce": "first", "fmt": "money", "filters": {}},
    # Objetivo 3 · Deal Win
    {"key": "sql_win_total", "match": "kr1 cr sql closed win total",
     "dataset": "sql_to_clientwin_30d", "field": "total_pct", "reduce": "first", "fmt": "pct", "filters": {}},
    {"key": "sql_win_outbound", "match": "kr2 cr sql closed win outbound",
     "dataset": "sql_to_clientwin_30d", "field": "sales_pct", "reduce": "first", "fmt": "pct", "filters": {}},
    # En Sales NEW la celda de Time to Close Win va como número pelado (sin "days").
    {"key": "time_to_close_win", "match": "kr3 time to close win desde nda",
     "dataset": "kr_time_to_closewin", "field": "promedio_dias", "reduce": "first", "fmt": "int", "filters": {}},
]

# Objetivo (grupo) de cada métrica, para agrupar el preview como el Excel.
_OBJ = {
    # OKR 2 - 2026
    "staffing_fee": "Obj 1 · Sustainable Growth", "gmrr": "Obj 1 · Sustainable Growth",
    "mrr": "Obj 1 · Sustainable Growth", "new_clients_staffing": "Obj 1 · Sustainable Growth",
    "new_clients_recruiting": "Obj 1 · Sustainable Growth",
    "active_contractors": "Obj 2 · Client & Candidate Obsession",
    "new_contractors_staffing": "Obj 2 · Client & Candidate Obsession",
    "new_contractors_recruiting": "Obj 2 · Client & Candidate Obsession",
    "candidate_churn": "Obj 2 · Client & Candidate Obsession",
    "clients_multi": "Obj 2 · Client & Candidate Obsession",
    "candidate_churn_m3": "Obj 2 · Client & Candidate Obsession",
    "active_clients_staffing": "Obj 2 · Client & Candidate Obsession",
    "client_churn_staffing": "Obj 2 · Client & Candidate Obsession",
    "replacements_placed": "Obj 2 · Client & Candidate Obsession",
    "active_pipeline_new": "Obj 3 · Pipeline Explosion",
    "expected_pipeline_rev": "Obj 3 · Pipeline Explosion",
    "sql_marketing": "Obj 3 · Pipeline Explosion", "new_opps_am": "Obj 3 · Pipeline Explosion",
    "cr_nda_win_sales": "Obj 4 · Operations Excellence", "cr_am": "Obj 4 · Operations Excellence",
    "cr_nda_win_ops": "Obj 4 · Operations Excellence",
    "new_placement_time": "Obj 4 · Operations Excellence",
    "repl_placement_time": "Obj 4 · Operations Excellence", "sent_hired": "Obj 4 · Operations Excellence",
    # Sales NEW
    "avg_recruiting_fee": "Obj 1 · Revenue Engine", "avg_staffing_fee": "Obj 1 · Revenue Engine",
    "new_clients_generated": "Obj 1 · Revenue Engine",
    "pipeline_worth_outbound": "Obj 2 · Ops Generation",
    "sql_win_total": "Obj 3 · Deal Win", "sql_win_outbound": "Obj 3 · Deal Win",
    "time_to_close_win": "Obj 3 · Deal Win",
}


# Cada pestaña: cómo encontrarla (por título) + formato de fecha + métricas.
TABS = [
    {"key": "okr", "title_match": "okr", "signature": "owner",
     "date_format": "us", "metrics": OKR_METRICS},
    {"key": "sales_new", "title_match": "sales", "signature": "sales metrics",
     "date_format": "intl", "metrics": SALES_METRICS},
]

_MONTHS = {
    "jan": 1, "ene": 1, "feb": 2, "mar": 3, "apr": 4, "abr": 4, "may": 5,
    "jun": 6, "jul": 7, "aug": 8, "ago": 8, "sep": 9, "set": 9, "oct": 10,
    "nov": 11, "dec": 12, "dic": 12,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _norm(s) -> str:
    """lowercase + solo alfanumérico separado por espacios simples."""
    out = []
    for ch in str(s or "").lower():
        out.append(ch if ch.isalnum() else " ")
    return " ".join("".join(out).split())


def _prev_full_week(today: date) -> tuple[str, str]:
    """Semana anterior completa (Lun–Dom), MISMA fórmula que el `window=week` de los
    datasets de Staffing (new_clients_30d_total._window_bounds). Devuelve ISO strings."""
    from datetime import timedelta
    prev_sunday = today - timedelta(days=today.weekday() + 1)
    prev_monday = prev_sunday - timedelta(days=6)
    return prev_monday.isoformat(), prev_sunday.isoformat()


def _metric_filters(metric, ref_date, inject_cutoff=False):
    """Filtros efectivos de la métrica.
    - Si `prev_week`: inyecta desde/hasta de la semana anterior completa a `ref_date`
      (para datasets que ignoran window=week).
    - Si `inject_cutoff` (modo as-of): inyecta corte/cutoff/fecha_corte = ref_date para
      que las ventanas rolling-30d y point-in-time terminen en esa fecha."""
    filters = dict(metric.get("filters") or {})
    if metric.get("prev_week"):
        desde, hasta = _prev_full_week(ref_date)
        filters.setdefault("desde", desde)
        filters.setdefault("hasta", hasta)
    elif inject_cutoff:
        iso = ref_date.isoformat()
        for k in ("corte", "cutoff", "fecha_corte"):
            filters.setdefault(k, iso)
    return filters


def _col_letter(idx0: int) -> str:
    s = ""
    n = idx0
    while True:
        s = chr(ord("A") + (n % 26)) + s
        n = n // 26 - 1
        if n < 0:
            break
    return s


def _cell(grid, r, c):
    if 0 <= r < len(grid):
        row = grid[r]
        if 0 <= c < len(row):
            return row[c]
    return None


def _parse_week_date(raw, year, fmt="intl"):
    """Parsea celdas de la fila de fechas. `fmt`:
      - "us"   → MM/DD/YYYY tipo "07/20/2026" (mes primero).
      - "intl" → "20-Jul", "20 jul", ISO "2026-07-20", etc. (día primero cuando ambiguo).
    Devuelve datetime.date o None."""
    s = str(raw or "").strip().lower()
    if not s:
        return None

    if fmt == "us":
        m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$", s)
        if m:
            mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 100:
                y += 2000
            try:
                return date(y, mo, d)
            except ValueError:
                return None
        # si no matchea el formato US, cae al parser genérico de abajo.

    # fast-path ISO: 2026-07-20 / 2026/7/20
    iso = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", s)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None

    for sep in ("/", "-", ".", " "):
        s = s.replace(sep, " ")
    toks = [t for t in s.split() if t]
    if not toks:
        return None
    day = month = yr = None
    for t in toks:
        if t[:3] in _MONTHS:
            month = _MONTHS[t[:3]]
        elif t.isdigit():
            n = int(t)
            if n > 31:
                yr = n if n > 100 else 2000 + n
            elif month is None and 1 <= n <= 12 and day is not None:
                month = n
            elif day is None and 1 <= n <= 31:
                day = n
            elif month is None and 1 <= n <= 12:
                month = n
    if day is None or month is None:
        return None
    try:
        return date(yr or year, month, day)
    except ValueError:
        return None


def _round_money(v):
    """Redondea al mismo nivel que la card del dashboard (`$X.XK`, 1 decimal en miles):
    ≥1000 → a la centena más cercana (264.365 → 264.4K → 264400); <1000 → entero exacto."""
    v = float(v)
    if abs(v) >= 1000:
        return int(round(v / 100.0) * 100)
    return int(round(v))


def _display(value, fmt) -> str:
    """Formatea como lo escriben a mano en el sheet."""
    if value is None:
        return ""
    if fmt == "money":
        return "$" + f"{_round_money(value):,.0f}"
    if fmt == "pct":
        return f"{int(round(float(value)))}%"
    if fmt == "days":
        return f"{int(round(float(value)))} days"
    return str(int(round(float(value))))  # int


def _reduce_value(rows, field, reduce):
    if not rows:
        return None, "dataset vacío (0 filas)"
    if field not in rows[0]:
        return None, f"campo '{field}' no está en el dataset"
    if reduce == "first":
        v = rows[0].get(field)
    elif reduce == "last":
        v = rows[-1].get(field)
    elif reduce == "sum":
        v = sum((r.get(field) or 0) for r in rows)
    else:
        return None, f"reduce '{reduce}' inválido"
    try:
        return (float(v) if v is not None else None), None
    except (TypeError, ValueError):
        return None, f"valor no numérico: {v!r}"


def _resolve_write(computed, fmt, ref_unf, ref_fmt):
    """Decide QUÉ escribir según el formato de una celda de referencia ya cargada
    (misma fila). Devuelve (write_value, display, note).

    - ref numérica  → escribe número crudo (la celda ya tiene formato $/%/etc.).
      · para % detecta si la celda guarda fracción (0.38) o entero (38).
    - ref texto/vacía → escribe el string formateado (calca el tipeo manual)."""
    if computed is None:  # sin dato (dataset devolvió null) → escribe "NA", no vacío
        return "NA", "NA", "sin dato → NA"
    disp = _display(computed, fmt)
    ref_is_num = isinstance(ref_unf, (int, float)) and not isinstance(ref_unf, bool)

    if fmt == "pct" and ref_is_num:
        try:
            ref_pct = float(str(ref_fmt).replace("%", "").strip())
        except (TypeError, ValueError):
            ref_pct = None
        if ref_pct is not None and abs(ref_unf * 100 - ref_pct) < 1.5:
            return round(computed) / 100.0, disp, "celda %-fracción (entero)"
        return round(computed), disp, "celda numérica"

    if ref_is_num:
        num = _round_money(computed) if fmt == "money" else round(computed)
        return num, disp, "celda numérica"

    note = "celda de texto" if (ref_unf not in (None, "")) else "fila vacía → escribe texto"
    return disp, disp, note


# ---------------------------------------------------------------------------
# Lectura + layout
# ---------------------------------------------------------------------------
def _read_grids(svc, spreadsheet_id, tab):
    quoted = a1_quote(tab)
    rng = f"{quoted}!{READ_RANGE}"
    fmt = svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=rng,
        valueRenderOption="FORMATTED_VALUE").execute().get("values", [])
    unf = svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=rng,
        valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    return fmt, unf


def _list_tabs(svc, spreadsheet_id):
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    return [s["properties"]["title"] for s in meta.get("sheets", [])]


def _find_header_row(fmt, date_format, year, max_rows=15):
    """Fila de fechas = primera fila (de las primeras `max_rows`) con ≥3 celdas que
    parsean como fecha. label_col fijo = 0."""
    for r, row in enumerate(fmt[:max_rows]):
        cnt = sum(1 for c in row[1:] if _parse_week_date(c, year, date_format))
        if cnt >= 3:
            return r
    return None


def _match_tab_title(titles, cfg):
    """Elige la pestaña por título (contiene title_match)."""
    tm = cfg["title_match"]
    for t in titles:
        if tm in _norm(t):
            return t
    return None


# ---------------------------------------------------------------------------
# Core: construye el snapshot de UNA pestaña (columna + filas + valores)
# ---------------------------------------------------------------------------
def _build_tab_snapshot(svc, tab, cfg, today, dataset_cache, inject_cutoff=False):
    date_format = cfg["date_format"]
    fmt, unf = _read_grids(svc, SPREADSHEET_ID, tab)

    date_row = _find_header_row(fmt, date_format, today.year)
    if date_row is None:
        return {"tab": tab, "error": "no encontré la fila de fechas (header)", "cells": []}
    label_col = 0

    # 1) elegir columna = última fecha ≤ hoy
    best_col = best_date = week_label = None
    for c in range(label_col + 1, len(fmt[date_row])):
        d = _parse_week_date(fmt[date_row][c], today.year, date_format)
        if d is None or d > today:
            continue
        if best_date is None or d > best_date:
            best_date, best_col = d, c
            week_label = str(fmt[date_row][c]).strip()
    if best_col is None:
        return {"tab": tab, "error": "no hay columna de semana con fecha ≤ hoy", "cells": []}
    col_letter = _col_letter(best_col)

    def _rows_for(metric):
        eff = _metric_filters(metric, today, inject_cutoff)
        key = (metric["dataset"], tuple(sorted(eff.items())))
        if key not in dataset_cache:
            dataset_cache[key] = run_dataset(metric["dataset"], eff)
        return dataset_cache[key]

    used_rows: set[int] = set()
    cells = []
    for metric in cfg["metrics"]:
        entry = {
            "tab": tab, "key": metric["key"], "dataset": metric["dataset"],
            "field": metric["field"], "reduce": metric["reduce"], "fmt": metric["fmt"],
            "obj": _OBJ.get(metric["key"], ""),
        }
        # localizar la fila por prefijo de label
        row_idx = None
        for r, row in enumerate(fmt):
            if r in used_rows or len(row) <= label_col:
                continue
            label_norm = _norm(row[label_col])
            if label_norm and label_norm.startswith(metric["match"]):
                row_idx = r
                break
        if row_idx is None:
            entry["error"] = f"no encontré la fila para '{metric['match']}'"
            cells.append(entry)
            continue
        used_rows.add(row_idx)
        entry["label"] = str(fmt[row_idx][label_col]).strip()
        entry["row"] = row_idx + 1
        entry["cell"] = f"{col_letter}{row_idx + 1}"

        try:
            rows = _rows_for(metric)
        except (DatasetError, Exception) as exc:  # noqa: BLE001
            entry["error"] = f"dataset falló: {exc}"
            cells.append(entry)
            continue
        value, err = _reduce_value(rows, metric["field"], metric["reduce"])
        if err:
            entry["error"] = err
            cells.append(entry)
            continue

        ref_unf = _cell(unf, row_idx, best_col)
        ref_fmt = _cell(fmt, row_idx, best_col)
        if ref_unf in (None, ""):
            for c in range(best_col - 1, label_col, -1):
                cand = _cell(unf, row_idx, c)
                if cand not in (None, ""):
                    ref_unf = cand
                    ref_fmt = _cell(fmt, row_idx, c)
                    break

        write_value, display, note = _resolve_write(value, metric["fmt"], ref_unf, ref_fmt)
        entry["value"] = value
        entry["write_value"] = write_value
        entry["display"] = display
        entry["current"] = ref_fmt if ref_fmt not in (None, "") else None
        entry["note"] = note
        cells.append(entry)

    return {
        "tab": tab,
        "column": col_letter,
        "week_label": week_label,
        "week_date": best_date.isoformat() if best_date else None,
        "cells": cells,
    }


def _build_snapshot():
    svc = sheets_service()
    titles = _list_tabs(svc, SPREADSHEET_ID)
    as_of = _asof_override()
    today = as_of or today_ar()
    inject_cutoff = as_of is not None
    dataset_cache: dict = {}

    tabs_out = []
    all_cells = []
    for cfg in TABS:
        tab = _match_tab_title(titles, cfg)
        if not tab:
            tabs_out.append({"key": cfg["key"], "error": f"no encontré la pestaña ({cfg['title_match']})", "cells": []})
            continue
        snap = _build_tab_snapshot(svc, tab, cfg, today, dataset_cache, inject_cutoff)
        snap["key"] = cfg["key"]
        tabs_out.append(snap)
        all_cells.extend(snap.get("cells", []))

    ok = [c for c in all_cells if "error" not in c]
    return {
        "spreadsheet_id": SPREADSHEET_ID,
        "today": today.isoformat(),
        "as_of": as_of.isoformat() if as_of else None,
        "tabs": tabs_out,
        "ok_count": len(ok),
        "error_count": len(all_cells) - len(ok),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@bp.route("/sheet-snapshot/preview", methods=["POST"])
def okr_sheet_snapshot_preview():
    gate = _require_editor()
    if gate:
        return gate
    try:
        snap = _build_snapshot()
    except Exception as exc:  # noqa: BLE001
        logging.exception("❌ okr sheet-snapshot preview failed")
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "mode": "preview", **snap}), 200


@bp.route("/sheet-snapshot/commit", methods=["POST"])
def okr_sheet_snapshot_commit():
    gate = _require_editor()
    if gate:
        return gate
    try:
        snap = _build_snapshot()
        updates = []
        for tab_snap in snap["tabs"]:
            for c in tab_snap.get("cells", []):
                if "error" in c or c.get("write_value") is None:
                    continue
                updates.append({
                    "range": f"{a1_quote(c['tab'])}!{c['cell']}",
                    "values": [[c["write_value"]]],
                })
        if not updates:
            return jsonify({"error": "No hay celdas válidas para escribir", **snap}), 400

        svc = sheets_service()
        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"valueInputOption": "USER_ENTERED", "data": updates},
        ).execute()
    except Exception as exc:  # noqa: BLE001
        logging.exception("❌ okr sheet-snapshot commit failed")
        return jsonify({"error": str(exc)}), 500

    written = [{"tab": c["tab"], "cell": c["cell"], "label": c.get("label"), "display": c.get("display")}
               for t in snap["tabs"] for c in t.get("cells", [])
               if "error" not in c and c.get("write_value") is not None]
    skipped = [{"tab": c.get("tab"), "key": c["key"], "error": c.get("error")}
               for t in snap["tabs"] for c in t.get("cells", []) if "error" in c]
    return jsonify({
        "ok": True, "mode": "commit",
        "cells_written": len(updates),
        "written": written, "skipped": skipped,
    }), 200


@bp.route("/sheet-snapshot/debug", methods=["GET"])
def okr_sheet_snapshot_debug():
    """Inspección de layout: lista pestañas + preview (primeras filas × columnas).
    Abrible en browser: /okr/sheet-snapshot/debug?user_email=info@vintti.com"""
    gate = _require_editor()
    if gate:
        return gate
    try:
        svc = sheets_service()
        titles = _list_tabs(svc, SPREADSHEET_ID)
        today = today_ar()
        out = []
        for cfg in TABS:
            tab = _match_tab_title(titles, cfg)
            if not tab:
                out.append({"cfg": cfg["key"], "matched_tab": None})
                continue
            quoted = a1_quote(tab)
            grid = svc.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID, range=f"{quoted}!A1:H40",
                valueRenderOption="FORMATTED_VALUE").execute().get("values", [])
            hr = _find_header_row(grid, cfg["date_format"], today.year)
            out.append({
                "cfg": cfg["key"], "matched_tab": tab, "date_format": cfg["date_format"],
                "header_row": (hr + 1) if hr is not None else None,
                "preview": [[str(c) for c in (row[:8] if row else [])] for row in grid[:35]],
            })
    except Exception as exc:  # noqa: BLE001
        logging.exception("❌ okr sheet-snapshot debug failed")
        return jsonify({"error": str(exc)}), 500
    return jsonify({"spreadsheet_id": SPREADSHEET_ID, "tabs": titles, "cfgs": out}), 200
