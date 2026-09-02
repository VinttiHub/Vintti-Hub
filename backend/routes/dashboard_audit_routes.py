"""Endpoints de la auditoria semanal de metricas.

`POST /run` responde 202 y trabaja en un hilo: la corrida tarda varios minutos
y gunicorn corta a los 300s (backend/gunicorn.conf.py), asi que responder
sincronicamente garantizaria un worker muerto a mitad de camino y un run
colgado en estado 'running'.
"""
from __future__ import annotations

import json
import logging
import os
import threading

from flask import Blueprint, jsonify, request

from db import get_connection

bp = Blueprint("dashboard_audit", __name__, url_prefix="/dashboards/audit")
log = logging.getLogger(__name__)


def _authorized() -> bool:
    """Token compartido con el cron. La corrida es cara: no se deja abierta."""
    expected = os.environ.get("DASHBOARD_AUDIT_TOKEN")
    if not expected:
        return False
    given = request.headers.get("X-Audit-Token") or request.args.get("token")
    return bool(given) and given == expected


@bp.route("/run", methods=["POST"])
def start_run():
    if not _authorized():
        return jsonify({"error": "forbidden"}), 403

    from dashboards.audit import service, store

    conn = get_connection()
    try:
        conn.autocommit = True
        if not store.tables_exist(conn):
            return jsonify({"error": "migration_missing",
                            "detail": "correr backend/sql/20260902_dashboard_audit.sql"}), 503
        with conn.cursor() as cur:
            # Una sola corrida a la vez: son ~320 queries analiticas y dos en
            # paralelo duplicarian la carga sobre RDS sin ningun beneficio.
            cur.execute(
                """SELECT run_id FROM dashboard_audit_runs
                    WHERE status = 'running'
                      AND started_at > NOW() - INTERVAL '1 hour'
                 ORDER BY run_id DESC LIMIT 1"""
            )
            row = cur.fetchone()
            if row:
                return jsonify({"error": "already_running", "run_id": row[0]}), 409
        run_id = store.start_run(conn, request.args.get("trigger", "cron"), None)
    finally:
        conn.close()

    threading.Thread(
        target=_run_in_background, args=(run_id, request.args.get("trigger", "cron")),
        daemon=True, name=f"dashboard-audit-{run_id}",
    ).start()
    return jsonify({"run_id": run_id, "status": "running"}), 202


def _run_in_background(run_id, trigger):
    from dashboards.audit import service

    try:
        service.execute(run_id=run_id, trigger_source=trigger)
    except Exception:  # noqa: BLE001 - service ya logueo y aviso por mail
        log.exception("Auditoria #%s termino con error", run_id)


@bp.route("/last", methods=["GET"])
@bp.route("/<int:run_id>", methods=["GET"])
def get_run(run_id=None):
    """Artefacto para el triage. Sin token: es solo lectura de diagnostico."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if run_id is None:
                cur.execute(
                    """SELECT run_id FROM dashboard_audit_runs
                        WHERE status IN ('ok', 'error')
                     ORDER BY run_id DESC LIMIT 1"""
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"error": "no_runs"}), 404
                run_id = row[0]

            cur.execute(
                """SELECT run_id, started_at, finished_at, status, trigger_source,
                          html_source, nodes_seen, datasets_run, datasets_failed,
                          elapsed_ms, findings_total, error_text
                     FROM dashboard_audit_runs WHERE run_id = %s""",
                (run_id,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "not_found"}), 404
            cols = ("run_id", "started_at", "finished_at", "status", "trigger_source",
                    "html_source", "nodes_seen", "datasets_run", "datasets_failed",
                    "elapsed_ms", "findings_total", "error_text")
            run = {k: (v.isoformat() if hasattr(v, "isoformat") else v)
                   for k, v in zip(cols, row)}

            cur.execute(
                """SELECT fingerprint, rule, severity, tab, panel, where_txt,
                          chart_key, dataset_key, field, message, observed, expected,
                          html_line, waived, waive_reason
                     FROM dashboard_audit_findings
                    WHERE run_id = %s
                 ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                                        WHEN 'medium' THEN 2 ELSE 3 END, tab, rule""",
                (run_id,),
            )
            fcols = ("fingerprint", "rule", "severity", "tab", "panel", "where",
                     "chart_key", "dataset_key", "field", "message", "observed",
                     "expected", "html_line", "waived", "waive_reason")
            findings = []
            for f in cur.fetchall():
                d = dict(zip(fcols, f))
                # Las dos rutas que evitan tener que re-explorar en el triage.
                d["html_file"] = "docs/dashboard.html"
                d["source_file"] = (f"backend/dashboards/datasets/{d['dataset_key']}.py"
                                    if d["dataset_key"] else None)
                findings.append(d)
    finally:
        conn.close()

    return jsonify({"run": run, "findings": findings})


@bp.route("/waivers", methods=["POST"])
def add_waiver():
    """Acepta un hallazgo conocido para que deje de aparecer en el mail."""
    if not _authorized():
        return jsonify({"error": "forbidden"}), 403
    body = request.get_json(silent=True) or {}
    if not body.get("reason"):
        return jsonify({"error": "reason_required"}), 400
    targets = {k: body.get(k) for k in ("fingerprint", "rule", "chart_key",
                                        "dataset_key", "panel")}
    if not any(targets.values()):
        return jsonify({"error": "target_required"}), 400

    conn = get_connection()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO dashboard_audit_waivers
                     (fingerprint, rule, chart_key, dataset_key, panel, reason,
                      created_by, expires_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (targets["fingerprint"], targets["rule"], targets["chart_key"],
                 targets["dataset_key"], targets["panel"], body["reason"],
                 body.get("created_by"), body.get("expires_at")),
            )
            return jsonify({"id": cur.fetchone()[0]}), 201
    finally:
        conn.close()
