"""Sales · AE's Performance → Google Sheet "SALES - AE METRICS".

Botón "Actualizar Sheet AE" (tab Sales, subtab AE's · Performance): calcula los
valores ACTUALES de las cards de esa subtab y los escribe en el Sheet de métricas de
AE — columna = semana en curso (último lunes ≤ hoy en la fila 1), fila = label de la
col A. Es el gemelo de "Actualizar OKRs" y usa su mismo motor
(`okr_snapshot_routes._build_tab_snapshot`): acá sólo cambian el spreadsheet y la
lista de métricas.

Layout del Sheet (2026-10-09): una sola pestaña, fila 1 =
`SALES METRICS | Periodo | 5-Oct | 12-Oct | …`, col B = período (informativo).
Las filas "Revenue" / "Conversión" / "Churn" son títulos de sección, sin métrica.

  POST /sales/ae-sheet/preview  → calcula y devuelve celdas+valores SIN escribir.
  POST /sales/ae-sheet/commit   → recalcula y ESCRIBE (email-gated).
  GET  /sales/ae-sheet/debug    → pestañas + primeras filas, para un "no encontré la fila".
"""
from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify

from utils.sheets_utils import sheets_service, a1_quote
from routes.okr_snapshot_routes import (
    _require_editor, _asof_override, _list_tabs, _find_header_row,
    _match_tab_title, _build_tab_snapshot, today_ar,
)

bp = Blueprint("sales_ae_sheet", __name__, url_prefix="/sales/ae-sheet")

DEFAULT_SPREADSHEET_ID = "1b2DiG6gymaZsMRRaZH5WimPRKv66-Rix0glsz_fkjNU"
SPREADSHEET_ID = os.getenv("SALES_AE_SHEET_SPREADSHEET_ID") or DEFAULT_SPREADSHEET_ID

_REV = "Revenue"
_CONV = "Conversión"
_CHURN = "Churn"

# Cada métrica = la card de Sales › AE's · Performance con el MISMO data-chart y los
# mismos overrides (verificados contra dashboard.html). % en escala 0-100.
# `exact`: la card del setup fee muestra el monto exacto, no "$1.2K".
METRICS = [
    # Card "Gross Revenue Generated", pane "Semana" (data-override-window="week"):
    # la semana completa anterior (Lun–Dom), igual que el toggle de la card.
    {"key": "gross_rev_staffing", "match": "gross revenue generated staffing", "obj": _REV,
     "dataset": "revenue_ae_card", "field": "staffing_revenue", "reduce": "first", "fmt": "money",
     "filters": {"window": "week"}},
    {"key": "gross_rev_recruiting", "match": "gross revenue generated recruiting", "obj": _REV,
     "dataset": "revenue_ae_card", "field": "recruiting_revenue", "reduce": "first", "fmt": "money",
     "filters": {"window": "week"}},
    {"key": "avg_recruiting_fee", "match": "avg recruiting fee", "obj": _REV,
     "dataset": "avg_recruiting_fee_30d", "field": "avg_fee", "reduce": "first", "fmt": "money", "filters": {}},
    {"key": "avg_staffing_fee", "match": "avg staffing fee", "obj": _REV,
     "dataset": "avg_staffing_fee_30d", "field": "avg_fee", "reduce": "first", "fmt": "money", "filters": {}},
    {"key": "avg_setup_fee_pc", "exact": True, "match": "avg setup fee con computadora", "obj": _REV,
     "dataset": "avg_setup_fee_30d", "field": "avg_with_pc", "reduce": "first", "fmt": "money", "filters": {}},
    {"key": "avg_setup_fee_no_pc", "exact": True, "match": "avg setup fee sin computadora", "obj": _REV,
     "dataset": "avg_setup_fee_30d", "field": "avg_without_pc", "reduce": "first", "fmt": "money", "filters": {}},
    {"key": "mql_sql", "match": "mql sql", "obj": _CONV,
     "dataset": "sales_mql_to_sql_30d", "field": "total_pct", "reduce": "first", "fmt": "pct", "filters": {}},
    {"key": "sql_nda_signed", "match": "sql nda signed", "obj": _CONV,
     "dataset": "sql_to_ndasigned_30d", "field": "total_pct", "reduce": "first", "fmt": "pct", "filters": {}},
    # "NDA Signed → Closed Win (per Opportunity)", NO la "NDA → Close Win" de al lado
    # (sa_kpi_nda_to_clientwin_30d), que es por cliente.
    {"key": "nda_cw_opp", "match": "nda close win per opportunity", "obj": _CONV,
     "dataset": "nda_closewin_opp_30d", "field": "total_pct", "reduce": "first", "fmt": "pct", "filters": {}},
    {"key": "sql_cw", "match": "sql close win", "obj": _CONV,
     "dataset": "sql_to_clientwin_30d", "field": "total_pct", "reduce": "first", "fmt": "pct", "filters": {}},
    # Churn: misma card con data-override-meses 1 / 3. M3 mira una cohorte de 90 días
    # (así lo calcula el dataset), aunque la col B del sheet diga "30 Dias".
    {"key": "cand_churn_m1", "match": "candidate churn m1", "obj": _CHURN,
     "dataset": "ae_candidate_churn_window", "field": "churn_real_pct", "reduce": "first", "fmt": "pct",
     "filters": {"meses": "1"}},
    {"key": "cand_churn_m3", "match": "candidate churn m3", "obj": _CHURN,
     "dataset": "ae_candidate_churn_window", "field": "churn_real_pct", "reduce": "first", "fmt": "pct",
     "filters": {"meses": "3"}},
    {"key": "client_churn_m1", "match": "client churn m1", "obj": _CHURN,
     "dataset": "ae_client_churn_window", "field": "churn_real_pct", "reduce": "first", "fmt": "pct",
     "filters": {"meses": "1"}},
    {"key": "client_churn_m3", "match": "client churn m3", "obj": _CHURN,
     "dataset": "ae_client_churn_window", "field": "churn_real_pct", "reduce": "first", "fmt": "pct",
     "filters": {"meses": "3"}},
]

# El sheet tiene una sola pestaña ("Sheet1"): si no matchea el título, se usa la primera.
TAB = {"key": "sales_ae", "title_match": "sales", "date_format": "intl", "metrics": METRICS}


def _pick_tab(titles):
    return _match_tab_title(titles, TAB) or (titles[0] if titles else None)


def _build_snapshot():
    svc = sheets_service()
    titles = _list_tabs(svc, SPREADSHEET_ID)
    as_of = _asof_override()
    today = as_of or today_ar()
    tab = _pick_tab(titles)
    if not tab:
        snap = {"key": TAB["key"], "error": "el spreadsheet no tiene pestañas", "cells": []}
    else:
        snap = _build_tab_snapshot(svc, tab, TAB, today, {}, as_of is not None,
                                   spreadsheet_id=SPREADSHEET_ID)
        snap["key"] = TAB["key"]
    cells = snap.get("cells", [])
    ok = [c for c in cells if "error" not in c]
    return {
        "spreadsheet_id": SPREADSHEET_ID,
        "today": today.isoformat(),
        "as_of": as_of.isoformat() if as_of else None,
        "tabs": [snap],
        "ok_count": len(ok),
        "error_count": len(cells) - len(ok),
    }


@bp.route("/preview", methods=["POST"])
def sales_ae_sheet_preview():
    gate = _require_editor()
    if gate:
        return gate
    try:
        snap = _build_snapshot()
    except Exception as exc:  # noqa: BLE001
        logging.exception("❌ sales ae-sheet preview failed")
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "mode": "preview", **snap}), 200


@bp.route("/commit", methods=["POST"])
def sales_ae_sheet_commit():
    gate = _require_editor()
    if gate:
        return gate
    try:
        snap = _build_snapshot()
        cells = [c for t in snap["tabs"] for c in t.get("cells", [])]
        good = [c for c in cells if "error" not in c and c.get("write_value") is not None]
        if not good:
            return jsonify({"error": "No hay celdas válidas para escribir", **snap}), 400
        updates = [{"range": f"{a1_quote(c['tab'])}!{c['cell']}", "values": [[c["write_value"]]]}
                   for c in good]
        sheets_service().spreadsheets().values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"valueInputOption": "USER_ENTERED", "data": updates},
        ).execute()
    except Exception as exc:  # noqa: BLE001
        logging.exception("❌ sales ae-sheet commit failed")
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "ok": True, "mode": "commit",
        "cells_written": len(updates),
        "written": [{"tab": c["tab"], "cell": c["cell"], "label": c.get("label"),
                     "display": c.get("display")} for c in good],
        "skipped": [{"tab": c.get("tab"), "key": c["key"], "error": c.get("error")}
                    for c in cells if "error" in c],
    }), 200


@bp.route("/debug", methods=["GET"])
def sales_ae_sheet_debug():
    """Abrible en browser: /sales/ae-sheet/debug?user_email=info@vintti.com"""
    gate = _require_editor()
    if gate:
        return gate
    try:
        svc = sheets_service()
        titles = _list_tabs(svc, SPREADSHEET_ID)
        tab = _pick_tab(titles)
        grid = []
        if tab:
            grid = svc.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID, range=f"{a1_quote(tab)}!A1:H40",
                valueRenderOption="FORMATTED_VALUE").execute().get("values", [])
        hr = _find_header_row(grid, TAB["date_format"], today_ar().year)
    except Exception as exc:  # noqa: BLE001
        logging.exception("❌ sales ae-sheet debug failed")
        return jsonify({"error": str(exc)}), 500
    return jsonify({
        "spreadsheet_id": SPREADSHEET_ID, "tabs": titles, "matched_tab": tab,
        "header_row": (hr + 1) if hr is not None else None,
        "preview": [[str(c) for c in (row[:8] if row else [])] for row in grid[:35]],
    }), 200
