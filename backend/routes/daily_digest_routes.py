"""Endpoints del digest diario de pendientes de carga.

`POST /run` corre SINCRONICO, igual que comisiones AE y a diferencia de la
auditoria del dashboard: son tres queries, no ~316.
"""
from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify, request

from daily_digest import people

bp = Blueprint("daily_digest", __name__, url_prefix="/daily-digest")
log = logging.getLogger(__name__)


def _current_email() -> str:
    return (request.headers.get("X-User-Email") or "").strip().lower()


def _authorized_token() -> bool:
    """Token compartido con el cron diario.

    Reusa `DASHBOARD_AUDIT_TOKEN`, que ya esta seteada en App Runner y como
    secret del repo: un secret nuevo solo agrega una cosa mas que puede quedar
    sin setear el dia que el job tenga que correr solo.
    """
    expected = os.environ.get("DASHBOARD_AUDIT_TOKEN")
    if not expected:
        return False
    given = request.headers.get("X-Audit-Token") or request.args.get("token")
    return bool(given) and given == expected


def _bool_arg(name: str) -> bool:
    return str(request.args.get(name, "")).strip().lower() in ("1", "true", "yes")


# --------------------------------------------------------------------------- #
# Preview (gate por email) — para mirar el render desde el Hub, sin token
# --------------------------------------------------------------------------- #
@bp.route("/preview", methods=["GET"])
def preview():
    """Lo que se postearia hoy. No postea ni guarda nada."""
    if _current_email() not in people.DAILY_DIGEST_ALLOWED:
        return jsonify({"error": "You do not have access to the daily digest."}), 403

    from daily_digest import render, service
    from db import get_connection

    conn = get_connection()
    try:
        conn.autocommit = True
        rule = (request.args.get("rule") or "").strip() or None
        payload = service.collect(conn, solo_regla=rule)
    finally:
        conn.close()

    blocks, text = render.build(payload["findings"], fallos=payload["fallos"],
                                heartbeat=True)
    return jsonify({
        "run_date": payload["run_date"],
        "total": payload["total"],
        "people_total": payload["people_total"],
        "huerfanos": payload["huerfanos"],
        "por_regla": payload["por_regla"],
        "fallos": payload["fallos"],
        "findings": payload["findings"],
        "blocks": blocks,
        "text": text,
        "plain": render.to_text(payload["findings"], fallos=payload["fallos"]),
    })


# --------------------------------------------------------------------------- #
# Corrida + post (gate por token) — el cron de las 9
# --------------------------------------------------------------------------- #
@bp.route("/run", methods=["POST"])
def run_digest():
    if not _authorized_token():
        return jsonify({"error": "forbidden"}), 403

    from daily_digest import service

    from daily_digest import queries

    dry = _bool_arg("dry")
    trigger = request.args.get("trigger", "cron")
    # El workflow interpola siempre `rule=`, asi que vacio tiene que significar
    # "todas". Un valor invalido se rechaza en vez de reventar con KeyError.
    rule = (request.args.get("rule") or "").strip() or None
    if rule and rule not in queries.RULES:
        return jsonify({"error": f"rule invalida: {rule}",
                        "validas": sorted(queries.RULES)}), 400
    channel = (request.args.get("channel_override") or "").strip() or None
    if channel and not channel[:1].upper() in ("C", "G"):
        return jsonify({"error": "channel_override tiene que ser un ID de canal (C... o G...)"}), 400

    try:
        payload = service.execute(trigger_source=trigger, post=not dry,
                                  persist=not dry, solo_regla=rule,
                                  channel_override=channel)
    except Exception as exc:  # noqa: BLE001
        log.exception("Digest diario: la corrida fallo")
        return jsonify({"error": "run_failed", "detail": str(exc)[:300]}), 500

    return jsonify({
        "run_date": payload["run_date"],
        "total": payload["total"],
        "people_total": payload["people_total"],
        "huerfanos": payload["huerfanos"],
        "por_regla": payload["por_regla"],
        "fallos": payload["fallos"],
        "posted": bool(payload.get("slack", {}).get("sent")),
        "transport": payload.get("slack", {}).get("transport"),
        "blocks": len(payload["blocks"]),
        "dry": dry,
    }), 200


@bp.route("/runs", methods=["GET"])
def list_runs():
    if _current_email() not in people.DAILY_DIGEST_ALLOWED:
        return jsonify({"error": "You do not have access to the daily digest."}), 403

    from daily_digest import store
    from db import get_connection

    conn = get_connection()
    try:
        conn.autocommit = True
        if not store.tables_exist(conn):
            return jsonify({"runs": []})
        return jsonify({"runs": store.list_runs(conn)})
    finally:
        conn.close()


@bp.route("/slack-users", methods=["GET"])
def slack_users():
    """mail -> member ID, para llenar `daily_digest/people.py` una sola vez.

    Se corre a mano despues de instalar la app; no lo usa el cron.
    """
    if not _authorized_token():
        return jsonify({"error": "forbidden"}), 403

    from utils import slack as slack_api

    result = slack_api.list_members()
    if not result["ok"]:
        return jsonify(result), 502
    snippet = "\n".join(f'    "{m}": "{i}",' for m, i in result["members"].items())
    return jsonify({**result, "paste_into_people_py": snippet})
