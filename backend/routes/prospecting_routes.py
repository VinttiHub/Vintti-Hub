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
from datetime import date, datetime

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_connection
from prospecting import store
from prospecting import engine
from prospecting import workflows as wf_store
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
        if row is not None:
            row["enrollments"] = wf_store.company_enrollments(cur, company_id)
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
            applied = _run_instant(cur, company_id, "updated", row.pop("_changes"), _current_email())
            if applied:
                row = engine.load_company(cur, company_id)
    if row is None:
        return jsonify({"error": "not_found"}), 404
    row.pop("raw_payload", None)
    row["workflows_applied"] = applied
    return jsonify(_json_safe(row))


def _run_instant(cur, company_id: int, kind: str, changes: list, actor: str | None) -> list[dict]:
    """"Al instante": disparadores por evento + tick acotado a esta empresa.
    Devuelve qué workflows le hicieron algo (para el aviso de la página)."""
    cur.execute("SELECT COALESCE(MAX(id), 0) AS m FROM prospect_wf_step_log")
    mark = cur.fetchone()["m"]
    now = engine.utcnow()
    engine.emit_event(cur, company_id, kind, changes, now, actor)
    engine.tick(cur, now, automatic=True, company_id=company_id, actor=actor)
    cur.execute(
        """
        SELECT DISTINCT w.id, w.name FROM prospect_wf_step_log l
          JOIN prospect_wf_enrollments e ON e.id = l.enrollment_id
          JOIN prospect_workflows w ON w.id = e.workflow_id
         WHERE l.id > %s AND e.company_id = %s AND l.kind = 'action'
        """,
        (mark, company_id),
    )
    return [dict(r) for r in cur.fetchall()]


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
                kind = "created" if result["action"] == "created" else "updated"
                result["workflows_applied"] = [
                    a["name"] for a in _run_instant(cur, result["id"], kind,
                                                    result.pop("changes_detail", []), "clay")
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
def _parse_now(body: dict):
    """Hora simulada ("Avanzar el reloj" / pruebas). Acepta YYYY-MM-DD o YYYY-MM-DDTHH:MM
    (hora Argentina)."""
    raw = (body.get("now") or body.get("as_of") or "").strip()
    if not raw:
        return engine.utcnow()
    try:
        dt = datetime.fromisoformat(raw if "T" in raw else raw + "T12:00")
    except ValueError:
        raise ValueError("La fecha tiene que ser YYYY-MM-DD o YYYY-MM-DDTHH:MM.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=engine.TZ)
    return dt.astimezone(engine.utcnow().tzinfo)


def _invalid(exc: InvalidWorkflow):
    return jsonify({"error": "El workflow tiene errores.", "errors": exc.errors}), 400


def _editor_only():
    if not _is_wf_editor(_current_email()):
        return jsonify({"error": "Sólo pgonzales, manuela y mia pueden editar workflows."}), 403
    return None


@bp.get("/workflows")
def workflows_list():
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        rows = wf_store.list_workflows(cur)
    return jsonify(_json_safe({"workflows": rows, "can_edit": _is_wf_editor(_current_email())}))


@bp.get("/workflows/<int:wf_id>")
def workflow_get(wf_id: int):
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        row = wf_store.get_workflow(cur, wf_id)
    if row is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_json_safe(row))


@bp.post("/workflows")
def workflow_create():
    denied = _editor_only()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    try:
        with _Db() as cur:
            row = wf_store.create_workflow(cur, body, _current_email())
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
            row = wf_store.update_workflow(cur, wf_id, body, _current_email())
    except InvalidWorkflow as exc:
        return _invalid(exc)
    if row is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_json_safe(row))


@bp.post("/workflows/<int:wf_id>/toggle")
def workflow_toggle(wf_id: int):
    """Body: {enabled, include_existing}. `include_existing` = al activar un workflow de
    filtro, inscribir también las que ya cumplen hoy (como pregunta HubSpot)."""
    denied = _editor_only()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    try:
        with _Db() as cur:
            row = wf_store.set_enabled(cur, wf_id, bool(body.get("enabled")), _current_email(),
                                       include_existing=bool(body.get("include_existing")))
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
        ok = wf_store.delete_workflow(cur, wf_id)
    return (jsonify({"deleted": True}), 200) if ok else (jsonify({"error": "not_found"}), 404)


@bp.post("/workflows/preview")
def workflow_preview():
    """Qué empresas cumplen HOY el disparador de lo que está en el editor (guardado o no).
    No escribe nada."""
    denied = _editor_only()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    try:
        now = _parse_now(body)
        with _Db() as cur:
            d = wf_store.clean_definition(cur, body, self_id=body.get("id"), require_name=False)
            conds = d["trigger"].get("conditions")
            if d["trigger"]["type"] == "manual" or not (conds and conds.get("groups")):
                return jsonify({"affected": None, "items": [],
                                "note": "Este disparador no depende de condiciones: usá «Probar con una empresa»."})
            ids = engine.matching_ids(cur, conds, now, bool(body.get("only_dummy")))
            items = []
            if ids:
                cur.execute(
                    """
                    SELECT c.id, c.name, c.is_dummy, c.prospecting_status, c.prospecting_owner_email,
                           EXISTS (SELECT 1 FROM prospect_wf_enrollments e WHERE e.company_id = c.id
                                    AND e.workflow_id = %s AND e.status IN ('active','waiting')) AS already_in
                      FROM prospect_companies c WHERE c.id = ANY(%s) ORDER BY c.name LIMIT 200
                    """,
                    (body.get("id") or 0, ids),
                )
                items = [dict(r) for r in cur.fetchall()]
    except InvalidWorkflow as exc:
        return _invalid(exc)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(_json_safe({"as_of": engine.as_of_of(now), "affected": len(ids), "items": items}))


@bp.post("/workflows/test")
def workflow_test():
    """«Probar con una empresa»: el recorrido entero, sin escribir nada."""
    denied = _editor_only()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    try:
        now = _parse_now(body)
        with _Db() as cur:
            d = wf_store.clean_definition(cur, body, self_id=body.get("id"), require_name=False)
            d["id"], d["name"] = body.get("id"), body.get("name") or "(sin guardar)"
            # simulate() corre todo en seco (Ctx dry=True): no escribe nada.
            result = engine.simulate(cur, d, int(body.get("company_id") or 0), now)
    except InvalidWorkflow as exc:
        return _invalid(exc)
    except LookupError:
        return jsonify({"error": "Esa empresa no existe."}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(_json_safe(result))


@bp.post("/workflows/<int:wf_id>/enroll")
def workflow_enroll(wf_id: int):
    """Inscripción manual (empresas elegidas) o «Aplicar ahora» (todas las que cumplen).
    Body: {company_ids?: [...], only_dummy?: bool}. Corre en el momento aunque el
    workflow esté apagado: lo pide una persona."""
    denied = _editor_only()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    ids = body.get("company_ids")
    with _Db() as cur:
        wf = wf_store.get_workflow(cur, wf_id)
        if wf is None:
            return jsonify({"error": "not_found"}), 404
        result = engine.enroll_now(cur, wf, engine.utcnow(), _current_email(),
                                   bool(body.get("only_dummy")),
                                   company_ids=[int(x) for x in ids] if isinstance(ids, list) else None)
    return jsonify(_json_safe(result))


@bp.post("/workflows/<int:wf_id>/unenroll")
def workflow_unenroll(wf_id: int):
    denied = _editor_only()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    with _Db() as cur:
        n = sum(
            engine.unenroll_company(cur, wf_id, int(c), engine.utcnow(), f"Sacada a mano por {_current_email()}")
            for c in body.get("company_ids") or []
        )
    return jsonify({"unenrolled": n})


@bp.get("/workflows/<int:wf_id>/enrollments")
def workflow_enrollments(wf_id: int):
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        rows = wf_store.list_enrollments(cur, wf_id, request.args.get("status") or None)
    return jsonify(_json_safe({"enrollments": rows}))


@bp.get("/workflows/enrollments/<int:enrollment_id>")
def workflow_enrollment(enrollment_id: int):
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        row = wf_store.enrollment_detail(cur, enrollment_id)
    if row is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_json_safe(row))


@bp.post("/workflows/tick")
def workflows_tick():
    """Procesa los workflows activos: inscribe, cierra, avanza esperas.

    * Cron (X-Audit-Token): automático; con AUTOMATION_REAL_DATA apagado, sólo dummies.
    * Editora desde el Test panel («Avanzar el reloj»): siempre sólo dummies, con la
      hora que mande en `now` (para probar esperas sin aguardar días).
    """
    by_cron = _token_ok("DASHBOARD_AUDIT_TOKEN", "X-Audit-Token")
    email = _current_email()
    if not by_cron and not _is_wf_editor(email):
        return jsonify({"error": "forbidden"}), 403
    body = request.get_json(silent=True) or {}
    try:
        now = _parse_now(body) if not by_cron else engine.utcnow()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    with _Db() as cur:
        result = engine.tick(cur, now, automatic=True, dummy_only=not by_cron,
                             actor=email or "cron")
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
        ids = store.seed_dummies(cur, n, owners, date.today())
        # Disparadores "se crea la empresa": las dummies cuentan como recién llegadas.
        for cid in ids:
            _run_instant(cur, cid, "created", [], _current_email())
    return jsonify({"created": len(ids)})


@bp.delete("/dummy")
def dummy_delete():
    with _Db() as cur:
        denied = _gate(cur, admin_only=True)
        if denied:
            return denied
        deleted = store.delete_dummies(cur)
    return jsonify({"deleted": deleted})
