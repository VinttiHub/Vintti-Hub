"""Sales → Google Sheet snapshot.

Botón "Actualizar" de la pestaña Sales del dashboard: calcula los valores ACTUALES
de las métricas del tracking semanal y los escribe en la celda correcta del Google
Sheet — columna = semana en curso (última fecha ≤ hoy en la fila "Date"), fila =
auto-detectada por el label de la métrica en la columna A.

Dos modos (preview → confirmar → commit):
  POST /sales/sheet-snapshot/preview  → calcula todo y devuelve las celdas+valores SIN escribir.
  POST /sales/sheet-snapshot/commit   → recalcula y ESCRIBE las celdas (email-gated).

Reusa infra existente:
  - Escritura/lectura vía service account: utils.sheets_utils.sheets_service (mismo SA
    que Careers, `career-site@…iam.gserviceaccount.com`; el sheet destino debe estar
    compartido con ese email como Editor).
  - Valores de métricas: dashboards.executor.run_dataset (mismos datasets que las cards).

Mapeo métrica→dataset/field/reduce cerrado con el dueño (2026-07-20):
  - GMRR / MRR (staffing) = run-rate del mes en curso (reduce=last sobre el histórico
    mensual), NO el acumulado YTD (el sheet baja semana a semana → no es una suma).
  - Conversion Rate (NDA→Win) = rolling 30d (default del dataset).
  - Revenue (total/staffing/recruiting) = snapshot YTD (fila única, reduce=first).
  - Client Wins / Candidates Allocated = total YTD (reduce=last del histórico).
  - Pipeline Worth / Active Opps (NDA) = snapshot actual (reduce=first).

El tipo de escritura (número crudo vs texto "103.2 K" vs % fracción) se AUTO-DETECTA
leyendo una celda ya cargada de la misma fila, para calcar el formato existente y no
romper ni el formato ni los gráficos del sheet.
"""
from __future__ import annotations

import logging
import os
import re

from flask import Blueprint, jsonify, request

from dashboards.executor import run_dataset, DatasetError
from utils.sheets_utils import sheets_service, a1_quote

try:  # today en hora Argentina (mismo criterio que los datasets)
    from dashboards.datasets._now import today_ar
except Exception:  # pragma: no cover - fallback defensivo
    from datetime import date, datetime, timedelta, timezone

    def today_ar() -> "date":
        return (datetime.now(timezone.utc) - timedelta(hours=3)).date()


bp = Blueprint("sales_snapshot", __name__, url_prefix="/sales")

# ---------------------------------------------------------------------------
# Config (todo overrideable por env)
# ---------------------------------------------------------------------------
# Sheet semanal de Sales · ORIGINAL (el botón escribe acá en producción).
# Copia de prueba anterior: 1_XYGiiClNpn8exGBrhF_Lpp7sQ9IEhavDs0-oRF2xy4
DEFAULT_SPREADSHEET_ID = "10uRvwNahlSbeL_qPz1gpQbpjeZLBOXx-ki-eP9ZbYdM"
SPREADSHEET_ID = os.getenv("SALES_SNAPSHOT_SPREADSHEET_ID") or DEFAULT_SPREADSHEET_ID
# Pestaña: si no se setea, se usa la primera hoja del spreadsheet (se reporta cuál).
CONFIG_TAB = os.getenv("SALES_SNAPSHOT_TAB") or None
# Rango a leer (las semanas se extienden a lo ancho → cubrir muchas columnas).
READ_RANGE = "A1:CZ500"

# Allow-list (mirror del botón de CRM). Override por env, coma-separado.
_DEFAULT_EDITORS = {
    "info@vintti.com", "agustin@vintti.com", "bahia@vintti.com",
    "mariano@vintti.com", "lara@vintti.com", "pgonzales@vintti.com",
    "agostina@vintti.com", "mia@vintti.com",
}


def _allowed_editors() -> set[str]:
    raw = os.getenv("SALES_SNAPSHOT_EDITORS", "")
    extra = {p.strip().lower() for p in raw.split(",") if p.strip()}
    return _DEFAULT_EDITORS | extra


def _user_email() -> str | None:
    email = request.headers.get("X-User-Email") or request.args.get("user_email")
    if not email:
        body = request.get_json(silent=True) or {}
        email = body.get("user_email")
    return (email or "").strip().lower() or None


def _require_editor():
    email = _user_email()
    if email not in _allowed_editors():
        return jsonify({"error": "forbidden", "email": email}), 403
    return None


# ---------------------------------------------------------------------------
# Mapeo métricas → dataset / field / reduce / formato
#   match  : prefijo normalizado del label en la col A del sheet (case-insensitive)
#   reduce : first (rows[0]) | last (rows[-1]) | sum (Σ)
#   fmt    : money | int | pct   (solo para display y para write de filas de TEXTO)
# ---------------------------------------------------------------------------
METRICS = [
    {"key": "annual_revenue", "match": "annual revenue outbound",
     "dataset": "revenue_outbound_ytd", "field": "total_revenue", "reduce": "first", "fmt": "money", "filters": {}},
    {"key": "staffing", "match": "staffing",
     "dataset": "revenue_outbound_ytd", "field": "staffing_revenue", "reduce": "first", "fmt": "money", "filters": {}},
    {"key": "recruiting", "match": "recruiting",
     "dataset": "revenue_outbound_ytd", "field": "recruiting_revenue", "reduce": "first", "fmt": "money", "filters": {}},
    {"key": "gmrr", "match": "gmrr",
     "dataset": "sales_mrr_staffing_ae_history", "field": "gmrr", "reduce": "last", "fmt": "money", "filters": {}},
    {"key": "mrr", "match": "mrr",
     "dataset": "sales_mrr_staffing_ae_history", "field": "mrr_fee", "reduce": "last", "fmt": "money", "filters": {}},
    {"key": "client_wins", "match": "client wins",
     "dataset": "client_wins_outbound_history", "field": "total_ytd", "reduce": "last", "fmt": "int", "filters": {}},
    {"key": "candidates_allocated", "match": "candidates allocated",
     "dataset": "candidates_allocated_outbound_history", "field": "total_ytd", "reduce": "last", "fmt": "int", "filters": {}},
    {"key": "pipeline_worth", "match": "pipeline worth",
     "dataset": "pipeline_outbound_ae", "field": "pipeline_worth", "reduce": "first", "fmt": "money", "filters": {}},
    {"key": "active_opps_nda", "match": "active opportunities",
     "dataset": "pipeline_outbound_ae", "field": "nda_signed_count", "reduce": "first", "fmt": "int", "filters": {}},
    # Conversion Rate = el card "NDA → Close Win" de AE Performance (win rate =
    # Close Win / (Win+Lost), solo Sales), al día (rolling 30d default, sin filtro).
    {"key": "conversion_rate", "match": "conversion rate",
     "dataset": "lead_channel_winrate_30d", "field": "sales_win_rate", "reduce": "first", "fmt": "pct", "filters": {}},
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


def _col_letter(idx0: int) -> str:
    """0-based → A1 (0→A, 25→Z, 26→AA)."""
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


def _parse_week_date(raw, year):
    """Parsea celdas de la fila Date: '1-jun', '1 jun', '6/1', '6/1/2026',
    '2026-06-01', 'Jun 1', etc. Devuelve datetime.date o None."""
    from datetime import date

    s = str(raw or "").strip().lower()
    if not s:
        return None
    # fast-path ISO: 2026-06-29 / 2026/6/29
    iso = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", s)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    # separadores comunes → tokens
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


def _display(value, fmt) -> str:
    """Formatea como lo escriben a mano en el sheet."""
    if value is None:
        return ""
    if fmt == "money":
        k = round(float(value) / 1000.0, 1)
        txt = f"{k:.1f}".rstrip("0").rstrip(".")
        return f"{txt} K"
    if fmt == "pct":
        return f"{int(round(float(value)))}%"
    # int
    return str(int(round(float(value))))


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

    - ref numérica  → escribe número crudo (la celda ya tiene formato → renderiza "K"/%).
      · para % detecta si la celda guarda fracción (0.38) o entero (38).
    - ref texto/vacía → escribe el string formateado (calca el tipeo manual)."""
    disp = _display(computed, fmt)
    ref_is_num = isinstance(ref_unf, (int, float)) and not isinstance(ref_unf, bool)

    if fmt == "pct" and ref_is_num:
        # ¿la celda vecina guarda 0.38 (fracción, formato %) o 38 (entero)?
        try:
            ref_pct = float(str(ref_fmt).replace("%", "").strip())
        except (TypeError, ValueError):
            ref_pct = None
        if ref_pct is not None and abs(ref_unf * 100 - ref_pct) < 1.5:
            return round(computed / 100.0, 4), disp, "celda %-fracción → escribe " + repr(round(computed / 100.0, 4))
        return round(computed, 2), disp, "celda numérica"

    if ref_is_num:
        num = round(computed) if fmt == "int" else round(computed, 2)
        return num, disp, "celda numérica"

    # texto o vacía → calcar el string
    note = "celda de texto" if (ref_unf not in (None, "")) else "fila vacía → escribe texto"
    return disp, disp, note


# ---------------------------------------------------------------------------
# Core: construye el snapshot (columna + filas + valores) sin escribir
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


def _find_layout(fmt, max_cols=8):
    """Ubica (fila 'Date', columna de labels) escaneando las primeras columnas.
    Tolera una columna espaciadora inicial (labels en A, B o donde estén)."""
    for r, row in enumerate(fmt):
        for c in range(min(max_cols, len(row))):
            if _norm(row[c]) == "date":
                return r, c
    return None


def _resolve_layout(svc, spreadsheet_id):
    """Devuelve (tab, fmt, unf, date_row, label_col). Autodetecta la pestaña que
    contiene la fila 'Date' (prueba todas si no se forzó una por env/request)."""
    req = request.get_json(silent=True) or {}
    forced = CONFIG_TAB or req.get("tab")
    titles = [forced] if forced else _list_tabs(svc, spreadsheet_id)
    if not titles:
        raise RuntimeError("El spreadsheet no tiene hojas")

    for tab in titles:
        fmt, unf = _read_grids(svc, spreadsheet_id, tab)
        layout = _find_layout(fmt)
        if layout:
            return tab, fmt, unf, layout[0], layout[1]

    raise RuntimeError(
        "No encontré una fila 'Date' en ninguna pestaña. Pestañas revisadas: "
        + ", ".join(str(t) for t in titles)
        + ". Verificá que la tabla tenga una fila cuyo primer valor sea 'Date'."
    )


def _build_snapshot():
    svc = sheets_service()
    tab, fmt, unf, date_row, label_col = _resolve_layout(svc, SPREADSHEET_ID)
    today = today_ar()

    # 1) fila "Date" → elegir columna = última fecha ≤ hoy
    best_col = None
    best_date = None
    week_label = None
    for c in range(label_col + 1, len(fmt[date_row])):
        d = _parse_week_date(fmt[date_row][c], today.year)
        if d is None or d > today:
            continue
        if best_date is None or d > best_date:
            best_date, best_col = d, c
            week_label = str(fmt[date_row][c]).strip()
    if best_col is None:
        raise RuntimeError(f"No hay ninguna columna de semana con fecha ≤ hoy en la fila 'Date' (pestaña '{tab}')")

    col_letter = _col_letter(best_col)

    # 2) resolver filas por label + calcular valores
    dataset_cache: dict = {}

    def _rows_for(metric):
        key = (metric["dataset"], tuple(sorted((metric.get("filters") or {}).items())))
        if key not in dataset_cache:
            dataset_cache[key] = run_dataset(metric["dataset"], metric.get("filters") or {})
        return dataset_cache[key]

    used_rows: set[int] = set()
    cells = []
    for metric in METRICS:
        entry = {
            "key": metric["key"], "dataset": metric["dataset"], "field": metric["field"],
            "reduce": metric["reduce"], "fmt": metric["fmt"],
        }
        # localizar la fila por prefijo de label en la columna de labels
        row_idx = None
        for r, row in enumerate(fmt):
            if r in used_rows or len(row) <= label_col:
                continue
            label_norm = _norm(row[label_col])
            if label_norm and label_norm.startswith(metric["match"]):
                row_idx = r
                break
        if row_idx is None:
            entry["error"] = f"no encontré la fila para '{metric['match']}' en la columna de labels"
            cells.append(entry)
            continue
        used_rows.add(row_idx)
        entry["label"] = str(fmt[row_idx][label_col]).strip()
        entry["row"] = row_idx + 1
        entry["cell"] = f"{col_letter}{row_idx + 1}"

        # valor calculado
        try:
            rows = _rows_for(metric)
        except (DatasetError, Exception) as exc:  # noqa: BLE001 - reportar por métrica
            entry["error"] = f"dataset falló: {exc}"
            cells.append(entry)
            continue
        value, err = _reduce_value(rows, metric["field"], metric["reduce"])
        if err:
            entry["error"] = err
            cells.append(entry)
            continue

        # referencia = valor actual de la celda destino o el más cercano a la izquierda
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

    ok_cells = [c for c in cells if "error" not in c]
    return {
        "spreadsheet_id": SPREADSHEET_ID,
        "tab": tab,
        "today": today.isoformat(),
        "week_label": week_label,
        "week_date": best_date.isoformat() if best_date else None,
        "column": col_letter,
        "cells": cells,
        "ok_count": len(ok_cells),
        "error_count": len(cells) - len(ok_cells),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@bp.route("/sheet-snapshot/preview", methods=["POST"])
def sheet_snapshot_preview():
    gate = _require_editor()
    if gate:
        return gate
    try:
        snap = _build_snapshot()
    except Exception as exc:  # noqa: BLE001
        logging.exception("❌ sales sheet-snapshot preview failed")
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "mode": "preview", **snap}), 200


@bp.route("/sheet-snapshot/debug", methods=["GET"])
def sheet_snapshot_debug():
    """Inspección: lista pestañas y un preview (primeras filas × primeras columnas) de
    cada una, para ubicar dónde está la fila 'Date' y la columna de labels.
    Abrible en el browser: /sales/sheet-snapshot/debug?user_email=info@vintti.com"""
    gate = _require_editor()
    if gate:
        return gate
    try:
        svc = sheets_service()
        titles = _list_tabs(svc, SPREADSHEET_ID)
        out = []
        for tab in titles:
            quoted = a1_quote(tab)
            grid = svc.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID, range=f"{quoted}!A1:H40",
                valueRenderOption="FORMATTED_VALUE").execute().get("values", [])
            layout = _find_layout(grid)
            out.append({
                "tab": tab,
                "layout": ({"date_row": layout[0] + 1, "label_col": _col_letter(layout[1])}
                           if layout else None),
                "preview": [[str(c) for c in (row[:8] if row else [])] for row in grid[:25]],
            })
    except Exception as exc:  # noqa: BLE001
        logging.exception("❌ sales sheet-snapshot debug failed")
        return jsonify({"error": str(exc)}), 500
    return jsonify({"spreadsheet_id": SPREADSHEET_ID, "tabs": titles, "sheets": out}), 200


@bp.route("/sheet-snapshot/commit", methods=["POST"])
def sheet_snapshot_commit():
    gate = _require_editor()
    if gate:
        return gate
    try:
        snap = _build_snapshot()
        updates = [
            {"range": f"{a1_quote(snap['tab'])}!{c['cell']}", "values": [[c["write_value"]]]}
            for c in snap["cells"]
            if "error" not in c and c.get("write_value") is not None
        ]
        if not updates:
            return jsonify({"error": "No hay celdas válidas para escribir", **snap}), 400

        svc = sheets_service()
        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"valueInputOption": "USER_ENTERED", "data": updates},
        ).execute()
    except Exception as exc:  # noqa: BLE001
        logging.exception("❌ sales sheet-snapshot commit failed")
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "ok": True, "mode": "commit",
        "cells_written": len(updates),
        "column": snap["column"], "tab": snap["tab"], "week_label": snap["week_label"],
        "written": [{"cell": c["cell"], "label": c.get("label"), "display": c.get("display")}
                    for c in snap["cells"] if "error" not in c and c.get("write_value") is not None],
        "skipped": [{"key": c["key"], "error": c.get("error")}
                    for c in snap["cells"] if "error" in c],
    }), 200
