"""Endpoints del reporte mensual de comisiones AE.

`POST /run` corre SINCRONICO, a diferencia de la auditoria del dashboard: son
tres queries, no ~316, y terminan en segundos. No hace falta el hilo ni el 202.
"""
from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify, request

from db import get_connection

bp = Blueprint("ae_commissions", __name__, url_prefix="/ae-commissions")
log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Permisos — el gate REAL es este. Hay dos listas mas, ambas cosmeticas y
# sincronizadas a mano, que tienen que quedar identicas a esta:
#   * docs/assets/js/sidebar.js        -> setDisplay('aeCommissionsLink', ...)
#   * docs/assets/js/ae-commissions.js -> ALLOWED (panel "sin acceso")
# No confundir con service.RECIPIENTS: esa es quien RECIBE el mail (2 personas),
# esta es quien puede ABRIR la seccion (4).
# --------------------------------------------------------------------------- #
AE_COMMISSIONS_ALLOWED = {
    "pgonzales@vintti.com",
    "bahia@vintti.com",
    "lara@vintti.com",
    "agustin@vintti.com",
}


def _current_email() -> str:
    return (request.headers.get("X-User-Email") or "").strip().lower()


def _forbidden():
    return jsonify({"error": "You do not have access to the AE Commissions section."}), 403


def _authorized_token() -> bool:
    """Token compartido con el cron mensual.

    Reusa `DASHBOARD_AUDIT_TOKEN`, que ya esta seteada en App Runner y como
    secret del repo: un secret nuevo solo agrega una cosa mas que puede quedar
    sin setear el dia que el job tenga que correr solo.
    """
    expected = os.environ.get("DASHBOARD_AUDIT_TOKEN")
    if not expected:
        return False
    given = request.headers.get("X-Audit-Token") or request.args.get("token")
    return bool(given) and given == expected


# --------------------------------------------------------------------------- #
# Lectura (gate por email) — la pagina del Hub
# --------------------------------------------------------------------------- #
@bp.route("", methods=["GET"])
@bp.route("/", methods=["GET"])
def get_report():
    """Los tres bloques de un mes, calculados en vivo.

    `?period=YYYY-MM`; sin periodo, el mes vencido.
    """
    if _current_email() not in AE_COMMISSIONS_ALLOWED:
        return _forbidden()

    from ae_commissions import queries, report, service

    mes_ini, mes_fin = queries.month_bounds(request.args.get("period"))
    conn = get_connection()
    try:
        payload = service.collect(conn, mes_ini, mes_fin)
    finally:
        conn.close()

    return jsonify(report.to_json(mes_ini, payload, {
        "mes_ini": mes_ini.isoformat(),
        "mes_fin": mes_fin.isoformat(),
        "churn_m3_override_applied": payload.get("churn_m3_override_applied"),
    }))


@bp.route("/runs", methods=["GET"])
def list_runs():
    """Corridas guardadas, para el historial de la pagina."""
    if _current_email() not in AE_COMMISSIONS_ALLOWED:
        return _forbidden()

    from ae_commissions import store

    conn = get_connection()
    try:
        conn.autocommit = True
        if not store.tables_exist(conn):
            return jsonify({"runs": []})
        return jsonify({"runs": store.list_runs(conn)})
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Corrida + mail (gate por token) — el cron del dia 1
# --------------------------------------------------------------------------- #
@bp.route("/run", methods=["POST"])
def run_report():
    if not _authorized_token():
        return jsonify({"error": "forbidden"}), 403

    from ae_commissions import service

    period = request.args.get("period")
    trigger = request.args.get("trigger", "cron")
    dry = str(request.args.get("dry", "")).strip().lower() in ("1", "true", "yes")

    try:
        artifact = service.execute(period, trigger_source=trigger,
                                   send_email=not dry, persist=not dry)
    except Exception as exc:  # noqa: BLE001
        log.exception("Comisiones AE: la corrida fallo")
        return jsonify({"error": "run_failed", "detail": str(exc)[:300]}), 500

    return jsonify({
        "period": artifact["period"],
        "staffing": len(artifact["staffing"]),
        "recruiting": len(artifact["recruiting"]),
        "m3": len(artifact["m3"]),
        "emailed_to": artifact["meta"].get("emailed_to", []),
        "dry": dry,
    }), 200
