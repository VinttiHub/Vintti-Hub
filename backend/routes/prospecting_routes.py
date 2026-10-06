"""Prospecting — el CRM de los BDRs. Ver backend/prospecting/__init__.py.

Tres tipos de caller:
  * La página `docs/prospecting.html` — gate por `X-User-Email`: rol BDR en
    `users.role` o la owner (ADMIN_EMAILS). El panel de pruebas es sólo admin.
  * Clay — `POST /prospecting/clay/webhook` con `X-Clay-Token` (= env
    CLAY_WEBHOOK_TOKEN). Token propio a propósito: es un tercero, y rotarlo no
    tiene que romper los crons que usan DASHBOARD_AUDIT_TOKEN.
  * El cron diario de workflows — `X-Audit-Token` (= DASHBOARD_AUDIT_TOKEN), igual
    que el resto de los crons del repo.
"""
from __future__ import annotations

import os
from datetime import date

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_connection
from prospecting import store
from prospecting import workflows as wf_engine
from prospecting.constants import ADMIN_EMAILS, EDITABLE_FIELDS, WORKFLOW_EDITORS
from prospecting.rules import InvalidWorkflow

bp = Blueprint("prospecting", __name__, url_prefix="/prospecting")


def _current_email() -> str:
    return (request.headers.get("X-User-Email") or "").strip().lower()


def _is_admin(email: str) -> bool:
    return email in ADMIN_EMAILS


def _is_wf_editor(email: str) -> bool:
    return email in WORKFLOW_EDITORS


def _sees_dummies(email: str) -> bool:
    # Quien arma workflows necesita ver las dummies para probarlos.
    return _is_admin(email) or _is_wf_editor(email)


def _token_ok(env_name: str, header: str) -> bool:
    expected = os.environ.get(env_name)
    if not expected:
        return False
    given = request.headers.get(header) or request.args.get("token")
    return bool(given) and given == expected


def _json_safe(obj):
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


class _Db:
    """Conexión + cursor con el esquema asegurado; commit al salir sin error."""

    def __enter__(self):
        self.conn = get_connection()
        self.cur = self.conn.cursor(cursor_factory=RealDictCursor)
        store.ensure_schema(self.cur)
        return self.cur

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()
        return False


def _gate(cur, admin_only: bool = False):
    email = _current_email()
    if admin_only:
        ok = _is_admin(email)
    else:
        ok = store.has_access(cur, email)
    if not ok:
        return jsonify({"error": "You do not have access to Prospecting."}), 403
    return None


# --------------------------------------------------------------------------- #
# Página
# --------------------------------------------------------------------------- #
@bp.get("/me")
def me():
    email = _current_email()
    with _Db() as cur:
        return jsonify({
            "email": email,
            "has_access": store.has_access(cur, email),
            "is_admin": _is_admin(email),
            "can_edit_workflows": _is_wf_editor(email),
            "sees_dummies": _sees_dummies(email),
        })


@bp.get("/options")
def options():
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        data = store.options(cur)
    return jsonify(data)


@bp.get("/companies")
def companies():
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        filters = request.args.to_dict()
        if filters.get("dummy") in ("include", "only") and not _sees_dummies(_current_email()):
            filters["dummy"] = "exclude"
        data = store.list_companies(cur, filters)
    return jsonify(_json_safe(data))


@bp.get("/companies/<int:company_id>")
def company(company_id: int):
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        row = store.get_company(cur, company_id)
    if row is None:
        return jsonify({"error": "not_found"}), 404
    if not _is_admin(_current_email()):
        row.pop("raw_payload", None)
    return jsonify(_json_safe(row))


@bp.patch("/companies/<int:company_id>")
def patch_company(company_id: int):
    body = request.get_json(silent=True) or {}
    patch = {k: v for k, v in body.items() if k in EDITABLE_FIELDS}
    if not patch:
        return jsonify({"error": "Nada para actualizar.", "editable": list(EDITABLE_FIELDS)}), 400
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        row = store.update_company(cur, company_id, patch, actor=_current_email())
        applied = []
        if row is not None:
            # Al instante: los workflows activos sobre la empresa recién editada.
            applied = wf_engine.run_for_company(cur, company_id, actor=_current_email())
            if applied:
                cur.execute("SELECT * FROM prospect_companies WHERE id = %s", (company_id,))
                row = dict(cur.fetchone())
    if row is None:
        return jsonify({"error": "not_found"}), 404
    row.pop("raw_payload", None)
    row["workflows_applied"] = applied
    return jsonify(_json_safe(row))


# --------------------------------------------------------------------------- #
# Clay
# --------------------------------------------------------------------------- #
@bp.post("/clay/webhook")
def clay_webhook():
    """Una empresa por request (columna "HTTP API" de Clay, una fila = un POST).

    También acepta `{"companies": [...]}` para cargas en lote desde un script.
    """
    if not _token_ok("CLAY_WEBHOOK_TOKEN", "X-Clay-Token"):
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "El body tiene que ser un objeto JSON."}), 400
    batch = isinstance(body.get("companies"), list)
    items = body["companies"] if batch else [body]
    results = []
    with _Db() as cur:
        for item in items:
            try:
                cur.execute("SAVEPOINT clay_item")
                result = store.upsert_from_clay(cur, item)
                result["workflows_applied"] = [
                    a["name"] for a in wf_engine.run_for_company(cur, result["id"], actor="clay")
                ]
                results.append(result)
                cur.execute("RELEASE SAVEPOINT clay_item")
            except ValueError as exc:
                cur.execute("ROLLBACK TO SAVEPOINT clay_item")
                results.append({"action": "error", "error": str(exc)})
    status = 200 if all(r.get("action") != "error" for r in results) else 207
    return jsonify({"results": results} if batch else results[0]), status


# --------------------------------------------------------------------------- #
# Workflows
# --------------------------------------------------------------------------- #
def _as_of(body: dict):
    if not body.get("as_of"):
        return None
    return date.fromisoformat(str(body["as_of"])[:10])


def _invalid(exc: InvalidWorkflow):
    return jsonify({"error": "The workflow has errors.", "errors": exc.errors}), 400


@bp.get("/workflows")
def workflows_list():
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        rows = wf_engine.list_workflows(cur)
    return jsonify(_json_safe({"workflows": rows, "can_edit": _is_wf_editor(_current_email())}))


@bp.get("/workflows/<int:wf_id>")
def workflow_get(wf_id: int):
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        row = wf_engine.get_workflow(cur, wf_id)
    if row is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_json_safe(row))


def _editor_only():
    if not _is_wf_editor(_current_email()):
        return jsonify({"error": "Only pgonzales, manuela and mia can edit workflows."}), 403
    return None


@bp.post("/workflows")
def workflow_create():
    denied = _editor_only()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    try:
        with _Db() as cur:
            row = wf_engine.create_workflow(cur, body, _current_email())
    except InvalidWorkflow as exc:
        return _invalid(exc)
    return jsonify(_json_safe(row)), 201


@bp.put("/workflows/<int:wf_id>")
def workflow_update(wf_id: int):
    denied = _editor_only()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    try:
        with _Db() as cur:
            row = wf_engine.update_workflow(cur, wf_id, body, _current_email())
    except InvalidWorkflow as exc:
        return _invalid(exc)
    if row is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_json_safe(row))


@bp.post("/workflows/<int:wf_id>/toggle")
def workflow_toggle(wf_id: int):
    denied = _editor_only()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    try:
        with _Db() as cur:
            row = wf_engine.set_enabled(cur, wf_id, bool(body.get("enabled")), _current_email())
    except InvalidWorkflow as exc:
        return _invalid(exc)
    if row is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_json_safe(row))


@bp.delete("/workflows/<int:wf_id>")
def workflow_delete(wf_id: int):
    denied = _editor_only()
    if denied:
        return denied
    with _Db() as cur:
        ok = wf_engine.delete_workflow(cur, wf_id)
    return (jsonify({"deleted": True}), 200) if ok else (jsonify({"error": "not_found"}), 404)


@bp.post("/workflows/preview")
def workflow_preview():
    """Dry run de lo que está en el editor (guardado o no). No escribe nada."""
    denied = _editor_only()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    try:
        as_of = _as_of(body)
        with _Db() as cur:
            result = wf_engine.preview_definition(cur, body, as_of=as_of,
                                                  only_dummy=bool(body.get("only_dummy")))
    except ValueError as exc:
        if isinstance(exc, InvalidWorkflow):
            return _invalid(exc)
        return jsonify({"error": "as_of tiene que ser YYYY-MM-DD"}), 400
    return jsonify(_json_safe(result))


@bp.post("/workflows/run")
def workflows_run():
    """Corre los workflows. Dry run por defecto: hay que mandar `dry_run: false`.

    Body: {dry_run, as_of: "YYYY-MM-DD", only_dummy, workflow_ids: [...]}
    Sin `workflow_ids` corre los activos. Lo llama el cron (X-Audit-Token, y ahí
    cuenta como automático: con AUTOMATION_REAL_DATA apagado sólo toca dummies) o
    una editora desde la página.
    """
    by_cron = _token_ok("DASHBOARD_AUDIT_TOKEN", "X-Audit-Token")
    email = _current_email()
    if not by_cron and not _is_wf_editor(email):
        return jsonify({"error": "forbidden"}), 403
    body = request.get_json(silent=True) or {}
    try:
        as_of = _as_of(body)
    except ValueError:
        return jsonify({"error": "as_of tiene que ser YYYY-MM-DD"}), 400
    with _Db() as cur:
        result = wf_engine.run_workflows(
            cur,
            as_of=as_of,
            dry_run=body.get("dry_run", True) is not False,
            only_dummy=bool(body.get("only_dummy")),
            workflow_ids=body.get("workflow_ids"),
            actor=email or ("cron" if by_cron else None),
            automatic=by_cron,
        )
    return jsonify(_json_safe(result))


# --------------------------------------------------------------------------- #
# Datos de prueba (sólo admin)
# --------------------------------------------------------------------------- #
@bp.post("/dummy/seed")
def dummy_seed():
    body = request.get_json(silent=True) or {}
    n = max(1, min(300, int(body.get("n") or 60)))
    with _Db() as cur:
        denied = _gate(cur, admin_only=True)
        if denied:
            return denied
        owners = [b["email"] for b in store.list_bdrs(cur)]
        created = store.seed_dummies(cur, n, owners, date.today())
    return jsonify({"created": created})


@bp.delete("/dummy")
def dummy_delete():
    with _Db() as cur:
        denied = _gate(cur, admin_only=True)
        if denied:
            return denied
        deleted = store.delete_dummies(cur)
    return jsonify({"deleted": deleted})
