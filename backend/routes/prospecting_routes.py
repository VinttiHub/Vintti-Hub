"""Prospecting — el CRM de los BDRs. Ver backend/prospecting/__init__.py.

Tres tipos de caller:
  * La página `docs/prospecting.html` — gate por `X-User-Email`: rol BDR en
    `users.role` o la owner (ADMIN_EMAILS). El panel de pruebas es sólo admin.
  * Clay — `POST /prospecting/clay/webhook` con `X-Clay-Token` (= env
    CLAY_WEBHOOK_TOKEN). Token propio a propósito: es un tercero, y rotarlo no
    tiene que romper los crons que usan DASHBOARD_AUDIT_TOKEN.
  * Zapier (Calendly) — `POST /prospecting/zapier/calendly` con `X-Zapier-Token`
    (= env ZAPIER_WEBHOOK_TOKEN). Ver backend/prospecting/inbound.py.
  * El cron diario de workflows — `X-Audit-Token` (= DASHBOARD_AUDIT_TOKEN), igual
    que el resto de los crons del repo.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_connection
from prospecting import store
from prospecting import engine
from prospecting import inbound
from prospecting import folders as wf_folders
from prospecting import workflows as wf_store
from prospecting import views as views_store
from prospecting.rules import validate_conditions
from prospecting.constants import ADMIN_EMAILS, EDITABLE_FIELDS, WORKFLOW_EDITORS
from prospecting.rules import InvalidWorkflow

bp = Blueprint("prospecting", __name__, url_prefix="/prospecting")


def _current_email() -> str:
    return (request.headers.get("X-User-Email") or "").strip().lower()


def _is_admin(email: str) -> bool:
    return email in ADMIN_EMAILS


def _is_wf_editor(email: str) -> bool:
    return email in WORKFLOW_EDITORS


def _can_configure(email: str) -> bool:
    # Sección «Configuración» de la página (BDR IDs de Clay + Test panel):
    # la owner y las editoras de workflows (mia, manuela), 2026-11-03.
    return _is_admin(email) or _is_wf_editor(email)


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


def _gate(cur, admin_only: bool = False, settings: bool = False):
    email = _current_email()
    if settings:
        ok = _can_configure(email)
    elif admin_only:
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
            "can_configure": _can_configure(email),
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
        filters, err = _company_filters(cur, request.args.to_dict())
        if err:
            return err
        data = store.list_companies(cur, filters)
    return jsonify(_json_safe(data))


def _company_filters(cur, raw: dict):
    """Filtros de la tabla de empresas, listos para store: freno de dummies + avanzados
    validados. Los usan la lista y la edición masiva «todas las del filtro».
    Devuelve (filtros, None) o (None, respuesta de error)."""
    filters = {k: v for k, v in (raw or {}).items() if v is not None}
    filters.pop("ids", None)
    if filters.get("dummy") in ("include", "only") and not _sees_dummies(_current_email()):
        filters["dummy"] = "exclude"
    # Vista segmento: sólo los registros que se guardaron al crearla.
    if filters.get("segment"):
        filters["ids"] = views_store.segment_ids_of(cur, _current_email(), filters["segment"], "company")
    # Filtros avanzados (vistas guardadas): JSON con la forma de las condiciones
    # de un workflow. Se validan con la misma lista blanca antes de llegar al SQL.
    raw_adv = filters.pop("advanced", None)
    if raw_adv:
        try:
            adv = json.loads(raw_adv) if isinstance(raw_adv, str) else raw_adv
        except ValueError:
            return None, (jsonify({"error": "Filtros avanzados inválidos."}), 400)
        errors = validate_conditions(adv, "Filtros avanzados", wf_store._ctx(cur), required=False, obj="company")
        if errors:
            return None, (jsonify({"error": "Los filtros avanzados tienen errores.", "errors": errors}), 400)
        filters["advanced"] = adv
    return filters, None


def _contact_filters(cur, raw: dict):
    """Filtros de la pestaña Contacts, listos para store. Devuelve (filtros, None) o
    (None, respuesta de error), como _company_filters()."""
    filters = {k: v for k, v in (raw or {}).items() if v is not None}
    filters.pop("ids", None)
    if filters.get("dummy") in ("include", "only") and not _sees_dummies(_current_email()):
        filters["dummy"] = "exclude"
    if filters.get("segment"):
        filters["ids"] = views_store.segment_ids_of(cur, _current_email(), filters["segment"], "contact")
    # Filtros avanzados (2026-11-06): condiciones de workflow de CONTACTO, validadas con la
    # misma lista blanca antes de llegar al SQL.
    raw_adv = filters.pop("advanced", None)
    if raw_adv:
        try:
            adv = json.loads(raw_adv) if isinstance(raw_adv, str) else raw_adv
        except ValueError:
            return None, (jsonify({"error": "Filtros avanzados inválidos."}), 400)
        errors = validate_conditions(adv, "Filtros avanzados", wf_store._ctx(cur, obj="contact"), required=False,
                                     obj="contact")
        if errors:
            return None, (jsonify({"error": "Los filtros avanzados tienen errores.", "errors": errors}), 400)
        filters["advanced"] = adv
    return filters, None


# --------------------------------------------------------------------------- #
# Vistas guardadas (por persona; ver prospecting/views.py)
# --------------------------------------------------------------------------- #
@bp.get("/views")
def views_list():
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        data = views_store.list_for(cur, _current_email())
    return jsonify(_json_safe(data))


@bp.post("/views")
def view_create():
    body = request.get_json(silent=True) or {}
    try:
        with _Db() as cur:
            denied = _gate(cur)
            if denied:
                return denied
            view = views_store.create(cur, _current_email(), body, wf_store._ctx(cur))
    except InvalidWorkflow as exc:
        return jsonify({"error": exc.errors[0], "errors": exc.errors}), 400
    return jsonify(_json_safe(view)), 201


@bp.post("/views/segment")
def view_segment():
    """Acciones → «Por segmento»: vista nueva con SÓLO los registros elegidos (los tildados o
    todos los del filtro en este momento: la lista queda fija, como un segmento estático)."""
    body = request.get_json(silent=True) or {}
    obj = body.get("object") or "company"
    if obj not in views_store.OBJECTS:
        return jsonify({"error": "Objeto inválido."}), 400
    try:
        with _Db() as cur:
            denied = _gate(cur)
            if denied:
                return denied
            ids, err = _bulk_target_ids(cur, body, obj, limit=views_store.SEGMENT_MAX)
            if err:
                return err
            table = "prospect_companies" if obj == "company" else "prospect_contacts"
            cur.execute(f"SELECT COUNT(*) FILTER (WHERE is_dummy) AS d FROM {table} WHERE id = ANY(%s)", (ids,))
            # Con dummies adentro, el freno de dummies de la tabla los escondería: la vista sale vacía.
            filters = {"dummy": "include"} if cur.fetchone()["d"] else {}
            view = views_store.create(cur, _current_email(), {
                "name": body.get("name"), "object": obj, "shared": body.get("shared"),
                "config": {"filters": filters, "columns": body.get("columns") or [], "segment_ids": ids,
                           "page_size": body.get("page_size")},
            }, wf_store._ctx(cur))
    except InvalidWorkflow as exc:
        return jsonify({"error": exc.errors[0], "errors": exc.errors}), 400
    return jsonify(_json_safe(view)), 201


@bp.patch("/views/<int:view_id>")
def view_update(view_id: int):
    body = request.get_json(silent=True) or {}
    try:
        with _Db() as cur:
            denied = _gate(cur)
            if denied:
                return denied
            email = _current_email()
            existing = views_store.get_view(cur, view_id)
            if existing is None:
                return jsonify({"error": "La vista no existe."}), 404
            if existing["owner_email"] != email:
                return jsonify({"error": "Sólo quien creó la vista la puede editar. Duplicala para tener la tuya."}), 403
            view = views_store.update(cur, email, view_id, body, wf_store._ctx(cur), existing)
    except InvalidWorkflow as exc:
        return jsonify({"error": exc.errors[0], "errors": exc.errors}), 400
    return jsonify(_json_safe(view))


@bp.delete("/views/<int:view_id>")
def view_delete(view_id: int):
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        email = _current_email()
        existing = views_store.get_view(cur, view_id)
        if existing is None:
            return jsonify({"error": "La vista no existe."}), 404
        if existing["owner_email"] != email:
            return jsonify({"error": "Sólo quien creó la vista la puede eliminar."}), 403
        views_store.delete(cur, email, view_id)
    return jsonify({"ok": True})


@bp.put("/views/tabs")
def view_tabs():
    body = request.get_json(silent=True) or {}
    try:
        with _Db() as cur:
            denied = _gate(cur)
            if denied:
                return denied
            if body.get("object") == "contact":
                return jsonify({"contact_tabs": views_store.set_contact_tabs(cur, _current_email(), body.get("tabs"))})
            tabs = views_store.set_tabs(cur, _current_email(), body.get("tabs"))
    except InvalidWorkflow as exc:
        return jsonify({"error": exc.errors[0], "errors": exc.errors}), 400
    return jsonify({"tabs": tabs})


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
        row.pop("hubspot_seen", None)
    return jsonify(_json_safe(row))


def _history(obj: str, record_id: int):
    """Historial de una propiedad: GET /prospecting/<companies|contacts>/<id>/history?field=."""
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        try:
            data = store.property_history(cur, obj, record_id, request.args.get("field") or "")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    if data is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_json_safe(data))


@bp.get("/companies/<int:company_id>/history")
def company_history(company_id: int):
    return _history("company", company_id)


@bp.get("/contacts/<int:contact_id>/history")
def contact_history(contact_id: int):
    return _history("contact", contact_id)


@bp.post("/companies")
def company_create():
    """Alta manual de una empresa (Empresas → «Nueva empresa», o «Crear empresa» desde el
    panel del contacto). Cualquiera con acceso, como crear un contacto. Dominio repetido →
    409 con la existente, para que la página ofrezca usarla."""
    body = request.get_json(silent=True) or {}
    actor = _current_email()
    try:
        with _Db() as cur:
            denied = _gate(cur)
            if denied:
                return denied
            row = store.create_company(cur, body, actor)
            applied = _run_instant(cur, row["id"], "created", row.pop("_changes"), actor)
            row = engine.load_company(cur, row["id"])
    except store.CompanyExists as exc:
        return jsonify({"error": "exists", "existing": _json_safe(exc.existing)}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    row.pop("raw_payload", None)
    row.pop("hubspot_seen", None)
    row["workflows_applied"] = [a["name"] for a in applied]
    return jsonify(_json_safe(row)), 201


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
            row = engine.load_company(cur, company_id)
            # Pasó a Qualified / SQL sin un contacto completo: la página abre el formulario.
            if "prospecting_status" in patch and row.get("contact_incomplete"):
                contacts = store.company_contacts(cur, company_id)
                row["needs_contact"] = True
                row["contacts"] = [{**c, "missing_required": store.contact_missing(c)} for c in contacts]
    if row is None:
        return jsonify({"error": "not_found"}), 404
    row.pop("raw_payload", None)
    row.pop("hubspot_seen", None)
    row["workflows_applied"] = applied
    return jsonify(_json_safe(row))


def _run_instant(cur, company_id: int | None, kind: str, changes: list, actor: str | None,
                 obj: str = "company", record_id: int | None = None) -> list[dict]:
    """"Al instante": disparadores por evento del registro + tick acotado a su empresa
    (los workflows de empresa miran la empresa; los de contacto, sus contactos).
    Un contacto SIN empresa se alcanza por su id (sin empresa, un tick con company_id
    None sería la corrida global). Devuelve qué workflows le hicieron algo."""
    cur.execute("SELECT COALESCE(MAX(id), 0) AS m FROM prospect_wf_step_log")
    mark = cur.fetchone()["m"]
    now = engine.utcnow()
    engine.emit_event(cur, obj, record_id or company_id, kind, changes, now, actor)
    contact_ids = [record_id] if obj == "contact" and record_id else None
    if company_id is None and contact_ids is None:
        return []
    engine.tick(cur, now, automatic=True, company_id=company_id, actor=actor, contact_ids=contact_ids)
    cur.execute(
        """
        SELECT DISTINCT w.id, w.name FROM prospect_wf_step_log l
          JOIN prospect_wf_enrollments e ON e.id = l.enrollment_id
          JOIN prospect_workflows w ON w.id = e.workflow_id
         WHERE l.id > %s AND l.kind = 'action'
           AND (e.company_id = %s OR e.contact_id = %s)
        """,
        (mark, company_id, record_id if obj == "contact" else None),
    )
    return [dict(r) for r in cur.fetchall()]


# --------------------------------------------------------------------------- #
# Contactos (los carga el BDR desde la ficha de la empresa)
# --------------------------------------------------------------------------- #
def _contact_response(cur, contact_id: int, applied: list) -> dict:
    out = store.get_contact(cur, contact_id) or {}
    out["workflows_applied"] = applied
    comp = engine.load_company(cur, out["company_id"]) if out and out.get("company_id") else None
    out["company_contact_incomplete"] = bool(comp and comp.get("contact_incomplete"))
    return out


@bp.get("/contacts")
def contacts_list():
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        filters, err = _contact_filters(cur, request.args.to_dict())
        if err:
            return err
        data = store.list_contacts(cur, filters)
    return jsonify(_json_safe(data))


@bp.get("/contacts/<int:contact_id>")
def contact_get(contact_id: int):
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        row = store.get_contact(cur, contact_id)
        if row is not None:
            cur.execute(
                """
                SELECT e.id, w.name AS workflow_name, e.status, e.wake_at, e.enrolled_at,
                       (SELECT summary FROM prospect_wf_step_log l WHERE l.enrollment_id = e.id
                         ORDER BY l.id DESC LIMIT 1) AS last_step
                  FROM prospect_wf_enrollments e JOIN prospect_workflows w ON w.id = e.workflow_id
                 WHERE e.contact_id = %s ORDER BY e.enrolled_at DESC LIMIT 50
                """,
                (contact_id,),
            )
            row["enrollments"] = [dict(r) for r in cur.fetchall()]
    if row is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_json_safe(row))


@bp.post("/contacts")
def contact_create_standalone():
    """Contacto desde cero (pestaña Contacts), con o sin empresa (`company_id` opcional)."""
    body = request.get_json(silent=True) or {}
    company_id = store._to_int(body.pop("company_id", None))
    return contact_create(company_id, body)


@bp.patch("/contacts/<int:contact_id>/company")
def contact_set_company(contact_id: int):
    """Asignar, cambiar o quitar (`company_id: null`) la empresa de un contacto."""
    body = request.get_json(silent=True) or {}
    company_id = store._to_int(body.get("company_id"))
    try:
        with _Db() as cur:
            denied = _gate(cur)
            if denied:
                return denied
            res = store.set_contact_company(cur, contact_id, company_id, _current_email())
            if res is None:
                return jsonify({"error": "not_found"}), 404
            applied = []
            if res["changed"]:
                applied = _run_instant(cur, company_id, "updated",
                                       [{"field": "company", "old": res["old"], "new": res["new"]}],
                                       _current_email(), obj="contact", record_id=contact_id)
            out = _contact_response(cur, contact_id, applied)
    except LookupError:
        return jsonify({"error": "not_found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(_json_safe(out))


@bp.post("/companies/<int:company_id>/contacts")
def contact_create(company_id: int | None, body: dict | None = None):
    body = body if body is not None else (request.get_json(silent=True) or {})
    try:
        with _Db() as cur:
            denied = _gate(cur)
            if denied:
                return denied
            row = store.create_contact(cur, company_id, body, _current_email())
            applied = _run_instant(cur, company_id, "created", row.pop("_changes"), _current_email(),
                                   obj="contact", record_id=row["id"])
            out = _contact_response(cur, row["id"], applied)
    except LookupError:
        return jsonify({"error": "not_found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(_json_safe(out)), 201


@bp.patch("/contacts/<int:contact_id>")
def contact_patch(contact_id: int):
    body = request.get_json(silent=True) or {}
    try:
        with _Db() as cur:
            denied = _gate(cur)
            if denied:
                return denied
            row = store.update_contact(cur, contact_id, body, _current_email())
            if row is None:
                return jsonify({"error": "not_found"}), 404
            applied = _run_instant(cur, row["company_id"], "updated", row.pop("_changes"), _current_email(),
                                   obj="contact", record_id=contact_id)
            out = _contact_response(cur, contact_id, applied)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(_json_safe(out))


@bp.delete("/contacts/<int:contact_id>")
def contact_delete(contact_id: int):
    # Eliminar es de admin + editoras (decisión de la owner, 2026-11-06), igual que en masa.
    with _Db() as cur:
        denied = _gate(cur, settings=True)
        if denied:
            return denied
        ok = store.delete_contact(cur, contact_id, _current_email())
    return (jsonify({"deleted": True}), 200) if ok else (jsonify({"error": "not_found"}), 404)


# --------------------------------------------------------------------------- #
# Eliminar en masa (Acciones → Eliminar): tildados o todos los del filtro.
# Sólo admin + editoras (_can_configure). Lo borrado queda en «Registros eliminados»
# y Clay / HubSpot no lo recrean (store.is_deleted).
# --------------------------------------------------------------------------- #
def _bulk_delete(obj: str):
    body = request.get_json(silent=True) or {}
    actor = _current_email()
    with _Db() as cur:
        denied = _gate(cur, settings=True)
        if denied:
            return denied
        ids, err = _bulk_target_ids(cur, body, obj)
        if err:
            return err
        out = store.delete_companies(cur, ids, actor) if obj == "company" else store.delete_contacts(cur, ids, actor)
    return jsonify({"total": len(ids), **out})


@bp.post("/companies/delete")
def companies_delete():
    return _bulk_delete("company")


@bp.post("/contacts/delete")
def contacts_delete():
    return _bulk_delete("contact")


@bp.get("/deleted")
def deleted_list():
    with _Db() as cur:
        denied = _gate(cur, settings=True)
        if denied:
            return denied
        return jsonify(_json_safe({"records": store.list_deleted(cur)}))


@bp.delete("/deleted/<int:deleted_id>")
def deleted_allow_back(deleted_id: int):
    with _Db() as cur:
        denied = _gate(cur, settings=True)
        if denied:
            return denied
        ok = store.allow_back(cur, deleted_id)
    return (jsonify({"ok": True}), 200) if ok else (jsonify({"error": "not_found"}), 404)


# --------------------------------------------------------------------------- #
# Paneles (métricas de BDRs, 2026-11-06): filas a nivel registro, el front agrupa.
# --------------------------------------------------------------------------- #
@bp.get("/panels/<key>")
def panel_data(key: str):
    from datetime import date as _date
    from prospecting import panels

    fn = panels.PANELS.get(key)
    if not fn:
        return jsonify({"error": "not_found"}), 404

    def _d(name):
        v = (request.args.get(name) or "").strip()
        try:
            return _date.fromisoformat(v) if v else None
        except ValueError:
            return None

    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        return jsonify(_json_safe(fn(cur, _d("from"), _d("to"))))


# --------------------------------------------------------------------------- #
# Edición masiva (botón «Editar» con varias filas tildadas)
# --------------------------------------------------------------------------- #
BULK_MAX = 1000
# Contactos: todo el catálogo menos el email (es único: no puede ser igual en varios).
_BULK_CONTACT_SKIP = {"email", "is_primary"}


def _bulk_target_ids(cur, body: dict, obj: str, limit: int = BULK_MAX):
    """Ids a editar: los tildados (`ids`) o todos los que cumplen los filtros de la tabla
    (`filters`, los mismos params del GET). Devuelve (ids, None) o (None, error)."""
    if isinstance(body.get("ids"), list):
        ids = sorted({int(x) for x in body["ids"] if str(x).isdigit()})
    elif isinstance(body.get("filters"), dict):
        if obj == "company":
            filters, err = _company_filters(cur, body["filters"])
            if err:
                return None, err
            ids = store.company_ids(cur, filters)
        else:
            filters, err = _contact_filters(cur, body["filters"])
            if err:
                return None, err
            ids = store.contact_ids(cur, filters)
    else:
        return None, (jsonify({"error": "Mandá `ids` o `filters`."}), 400)
    if not ids:
        return None, (jsonify({"error": "No hay registros seleccionados."}), 400)
    if len(ids) > limit:
        return None, (jsonify({"error": f"Son {len(ids)} registros: el máximo por vez es {limit}. Achicá la selección."}), 400)
    return ids, None


def _bulk_update(obj: str):
    from prospecting.contact_fields import CONTACT_FIELDS_BY_KEY

    body = request.get_json(silent=True) or {}
    field = body.get("field")
    allowed = set(EDITABLE_FIELDS) if obj == "company" else set(CONTACT_FIELDS_BY_KEY) - _BULK_CONTACT_SKIP
    if field not in allowed:
        return jsonify({"error": "Esa propiedad no se puede editar en masa."}), 400
    value = body.get("value")
    actor = _current_email()
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        ids, err = _bulk_target_ids(cur, body, obj)
        if err:
            return err
        # Escrituras en lote (engine.BatchCursor): mismas sentencias, menos viajes a la base.
        cur = engine.batched(cur)
        cur.execute("SELECT COALESCE(MAX(id), 0) AS m FROM prospect_wf_step_log")
        mark = cur.fetchone()["m"]
        now = engine.utcnow()
        updated, unchanged, failed, needs_contact, companies = 0, 0, [], 0, set()
        orphans = set()  # contactos sin empresa: el tick los alcanza por id
        # En el historial se distingue de una edición de a uno: `bulk:<cuántos registros>`.
        source = f"bulk:{len(ids)}"
        for rid in ids:
            # Un SAVEPOINT por registro: un valor que falla en uno no puede abortar la
            # transacción entera (y con ella todo lo ya editado del lote).
            cur.execute("SAVEPOINT bulk_row")
            try:
                if obj == "company":
                    row = store.update_company(cur, rid, {field: value}, actor=actor, source=source)
                    cid = rid
                else:
                    row = store.update_contact(cur, rid, {field: value}, actor, source=source)
                    cid = row["company_id"] if row else None
                if row is None:
                    cur.execute("ROLLBACK TO SAVEPOINT bulk_row")
                    failed.append({"id": rid, "error": "No existe."})
                    continue
                changes = row.pop("_changes")
                if changes:
                    engine.emit_event(cur, obj, rid, "updated", changes, now, actor, row=row)
                    if cid is None:
                        orphans.add(rid)
                    else:
                        companies.add(cid)
                    updated += 1
                else:
                    unchanged += 1
                if obj == "company" and field == "prospecting_status" and row.get("contact_incomplete"):
                    needs_contact += 1
                cur.execute("RELEASE SAVEPOINT bulk_row")
            except (ValueError, LookupError) as exc:
                cur.execute("ROLLBACK TO SAVEPOINT bulk_row")
                failed.append({"id": rid, "error": str(exc)})
        # Lo mismo que _run_instant() de a uno, pero UN tick para todas las empresas tocadas
        # (engine._company_match: company_id acepta una lista).
        if companies or orphans:
            engine.tick(cur, now, automatic=True, company_id=sorted(companies) or None, actor=actor,
                        contact_ids=sorted(orphans) or None)
        applied = []
        if companies or orphans:
            cur.execute(
                """
                SELECT DISTINCT w.name FROM prospect_wf_step_log l
                  JOIN prospect_wf_enrollments e ON e.id = l.enrollment_id
                  JOIN prospect_workflows w ON w.id = e.workflow_id
                 WHERE l.id > %s AND l.kind = 'action'
                   AND (e.company_id = ANY(%s) OR e.contact_id = ANY(%s))
                """,
                (mark, sorted(companies), sorted(orphans)),
            )
            applied = [r["name"] for r in cur.fetchall()]
        if failed:
            if obj == "company":
                cur.execute("SELECT id, name FROM prospect_companies WHERE id = ANY(%s)", ([f["id"] for f in failed],))
            else:
                cur.execute(
                    "SELECT id, COALESCE(NULLIF(CONCAT_WS(' ', first_name, last_name), ''), email) AS name "
                    "FROM prospect_contacts WHERE id = ANY(%s)", ([f["id"] for f in failed],))
            names = {r["id"]: r["name"] for r in cur.fetchall()}
            for f in failed:
                f["name"] = names.get(f["id"]) or f"#{f['id']}"
        cur.flush()  # antes del commit de _Db
    return jsonify(_json_safe({
        "total": len(ids), "updated": updated, "unchanged": unchanged, "failed": failed,
        "needs_contact": needs_contact, "workflows_applied": applied,
    }))


@bp.post("/companies/bulk")
def companies_bulk():
    return _bulk_update("company")


@bp.post("/contacts/bulk")
def contacts_bulk():
    return _bulk_update("contact")


# --------------------------------------------------------------------------- #
# Exportar a CSV (Acciones → «Exportar a CSV»): los tildados o todos los del filtro,
# con las columnas que elige la persona. Leer no toca nada, por eso el tope es más alto.
# --------------------------------------------------------------------------- #
EXPORT_MAX = 20000


def _csv_cell(field: dict, v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Sí" if v else "No"
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v)
    if isinstance(v, datetime):
        if v.tzinfo:  # hora Argentina (UTC−3, sin horario de verano); zoneinfo no está en el 3.8 de App Runner
            v = v.astimezone(timezone(timedelta(hours=-3)))
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _export(obj: str):
    import csv
    import io
    from flask import Response

    body = request.get_json(silent=True) or {}
    catalog = store.export_fields(obj)
    by_key = {f["key"]: f for f in catalog}
    cols = [k for k in (body.get("columns") or []) if k in by_key]
    if not cols:
        return jsonify({"error": "Elegí al menos una columna."}), 400
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        ids, err = _bulk_target_ids(cur, body, obj, limit=EXPORT_MAX)
        if err:
            return err
        sort = body.get("sort") or (body.get("filters") or {}).get("sort")
        rows = store.export_rows(cur, obj, ids, sort)
    buf = io.StringIO()
    buf.write("\ufeff")  # BOM: sin él Excel abre los acentos rotos
    w = csv.writer(buf)
    w.writerow([by_key[k]["label"] for k in cols])
    for r in rows:
        w.writerow([_csv_cell(by_key[k], r.get(k)) for k in cols])
    name = f"prospecting-{'empresas' if obj == 'company' else 'contactos'}-{date.today().isoformat()}.csv"
    return Response(buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@bp.post("/companies/export")
def companies_export():
    return _export("company")


@bp.post("/contacts/export")
def contacts_export():
    return _export("contact")


# --------------------------------------------------------------------------- #
# HubSpot -> Hub (empresas): cron cada 30 min, sólo en esa dirección
# --------------------------------------------------------------------------- #
@bp.post("/hubspot/sync")
def hubspot_companies_sync():
    """Trae a Prospecting lo que cambió en las empresas de HubSpot desde la última corrida.

    Cron (X-Audit-Token) o la owner. `?dry=1` = reporte sin escribir. HubSpot gana sólo
    cuando su valor cambió (foto en `hubspot_seen`); los cambios disparan workflows.
    Ver prospecting/hubspot_companies.py."""
    from prospecting import hubspot_companies as hs_companies

    by_cron = _token_ok("DASHBOARD_AUDIT_TOKEN", "X-Audit-Token")
    if not by_cron and not _is_admin(_current_email()):
        return jsonify({"error": "forbidden"}), 403
    dry = request.args.get("dry") in ("1", "true")
    try:
        limit = max(1, min(5000, int(request.args.get("limit") or 2000)))
    except ValueError:
        limit = 2000
    conn = get_connection()
    try:
        report = hs_companies.sync(conn, dry_run=dry, max_companies=limit)
    finally:
        conn.close()
    if report.get("status") == "busy":
        return jsonify(report), 409
    return jsonify(_json_safe(report))


@bp.post("/hubspot/sync-contacts")
def hubspot_contacts_sync():
    """Lo mismo que /hubspot/sync, para los contactos (prospecting/hubspot_contacts.py).
    El cron lo llama después del de empresas: un contacto nuevo encuentra su empresa."""
    from prospecting import hubspot_contacts as hs_contacts

    by_cron = _token_ok("DASHBOARD_AUDIT_TOKEN", "X-Audit-Token")
    if not by_cron and not _is_admin(_current_email()):
        return jsonify({"error": "forbidden"}), 403
    dry = request.args.get("dry") in ("1", "true")
    try:
        limit = max(1, min(5000, int(request.args.get("limit") or 2000)))
    except ValueError:
        limit = 2000
    conn = get_connection()
    try:
        report = hs_contacts.sync(conn, dry_run=dry, max_contacts=limit)
    finally:
        conn.close()
    if report.get("status") == "busy":
        return jsonify(report), 409
    return jsonify(_json_safe(report))


@bp.get("/hubspot/sync-contacts/last")
def hubspot_contacts_sync_last():
    from prospecting import hubspot_companies as hs_companies
    from prospecting import hubspot_contacts as hs_contacts

    if not _token_ok("DASHBOARD_AUDIT_TOKEN", "X-Audit-Token") and not _is_admin(_current_email()):
        return jsonify({"error": "forbidden"}), 403
    with _Db() as cur:
        row = hs_companies.last_report(cur, hs_contacts.SYNC_KEY)
    return jsonify(_json_safe(dict(row) if row else {}))


@bp.get("/hubspot/sync/last")
def hubspot_companies_sync_last():
    from prospecting import hubspot_companies as hs_companies

    if not _token_ok("DASHBOARD_AUDIT_TOKEN", "X-Audit-Token") and not _is_admin(_current_email()):
        return jsonify({"error": "forbidden"}), 403
    with _Db() as cur:
        row = hs_companies.last_report(cur)
    return jsonify(_json_safe(dict(row) if row else {}))


# --------------------------------------------------------------------------- #
# Clay
# --------------------------------------------------------------------------- #
@bp.post("/clay/webhook")
def clay_webhook():
    """Una empresa por request (columna "HTTP API" de Clay, una fila = un POST).

    También acepta `{"companies": [...]}` para cargas en lote desde un script.
    `"is_dummy": true` en una empresa la crea como prueba: los BDRs no la ven y se
    borra con "Borrar dummies". Sirve para probar la columna de Clay contra prod.
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
                is_dummy = str(item.get("is_dummy", "")).strip().lower() in ("true", "1", "yes", "si", "sí")
                result = store.upsert_from_clay(cur, item, is_dummy=is_dummy)
                result["is_dummy"] = is_dummy
                kind = "created" if result["action"] == "created" else "updated"
                result["workflows_applied"] = [
                    a["name"] for a in _run_instant(cur, result["id"], kind,
                                                    result.pop("changes_detail", []), "clay")
                ]
                attached = inbound.attach_pending_for_company(cur, result["id"])
                for a in attached:
                    _run_instant(cur, a["company_id"], a["action"], a.pop("changes"), "calendly",
                                 obj="contact", record_id=a["contact_id"])
                if attached:
                    result["calendly_contacts_attached"] = [a["contact_id"] for a in attached]
                # Contactos SIN empresa con el dominio de esta empresa: se le asocian solos.
                orphan_ids = store.attach_contacts_for_company(cur, result["id"], "clay", source="clay")
                if orphan_ids:
                    now_ = engine.utcnow()
                    for oid in orphan_ids:
                        engine.emit_event(cur, "contact", oid, "updated",
                                          [{"field": "company", "old": None, "new": result["id"]}], now_, "clay")
                    engine.tick(cur, now_, automatic=True, company_id=result["id"], actor="clay")
                    result["contacts_attached"] = orphan_ids
                results.append(result)
                cur.execute("RELEASE SAVEPOINT clay_item")
            except ValueError as exc:
                cur.execute("ROLLBACK TO SAVEPOINT clay_item")
                results.append({"action": "error", "error": str(exc)})
    status = 200 if all(r.get("action") != "error" for r in results) else 207
    return jsonify({"results": results} if batch else results[0]), status


# --------------------------------------------------------------------------- #
# Zapier (Calendly) → contactos
# --------------------------------------------------------------------------- #
@bp.post("/zapier/calendly")
def zapier_calendly():
    """Un invitado de Calendly por request (Zap "Invitee Created" → Webhooks POST).

    Si el contacto ya existe se actualiza; si el dominio es de una sola empresa se
    crea ahí; si no, queda como contacto sin empresa. `"is_dummy": true` lo crea
    como prueba, igual que el webhook de Clay.
    """
    if not _token_ok("ZAPIER_WEBHOOK_TOKEN", "X-Zapier-Token"):
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "El body tiene que ser un objeto JSON."}), 400
    is_dummy = str(body.pop("is_dummy", "")).strip().lower() in ("true", "1", "yes", "si", "sí")
    try:
        with _Db() as cur:
            result = inbound.ingest(cur, body, is_dummy=is_dummy)
            changes = result.pop("changes", None)
            if result.get("contact_id"):
                result["workflows_applied"] = [
                    a["name"] for a in _run_instant(cur, result["company_id"], result["action"], changes or [],
                                                    "calendly", obj="contact", record_id=result["contact_id"])
                ]
    except ValueError as exc:
        return jsonify({"action": "error", "error": str(exc)}), 400
    result["is_dummy"] = is_dummy
    return jsonify(_json_safe(result))


@bp.get("/inbound")
def inbound_list():
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        dummy = request.args.get("dummy") or "exclude"
        if dummy in ("include", "only") and not _sees_dummies(_current_email()):
            dummy = "exclude"
        status = request.args.get("status") or "pending"
        if status not in ("pending", "linked", "discarded"):
            return jsonify({"error": "status inválido"}), 400
        source = request.args.get("source") or None
        data = inbound.list_inbound(cur, status=status, dummy=dummy, source=source,
                                    q=request.args.get("q") or None)
    return jsonify(_json_safe(data))


@bp.post("/inbound/<int:inbound_id>/link")
def inbound_link(inbound_id: int):
    body = request.get_json(silent=True) or {}
    company_id = store._to_int(body.get("company_id"))
    if not company_id:
        return jsonify({"error": "Falta company_id."}), 400
    try:
        with _Db() as cur:
            denied = _gate(cur)
            if denied:
                return denied
            result = inbound.link(cur, inbound_id, company_id, _current_email())
            result["workflows_applied"] = _run_instant(
                cur, result["company_id"], result["action"], result.pop("changes"), _current_email(),
                obj="contact", record_id=result["contact_id"])
    except LookupError:
        return jsonify({"error": "not_found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(_json_safe(result))


@bp.post("/inbound/<int:inbound_id>/discard")
def inbound_discard(inbound_id: int):
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        ok = inbound.discard(cur, inbound_id, _current_email())
    return (jsonify({"discarded": True}), 200) if ok else (jsonify({"error": "not_found"}), 404)


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
        folders = wf_folders.list_folders(cur)
    return jsonify(_json_safe({"workflows": rows, "folders": folders, "can_edit": _is_wf_editor(_current_email())}))


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
    except wf_folders.FolderError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(_json_safe(row)), 201


# --------------------------------------------------------------------------- #
# Carpetas de workflows (prospecting/folders.py)
# --------------------------------------------------------------------------- #
def _folder_call(fn, status: int = 200):
    denied = _editor_only()
    if denied:
        return denied
    try:
        with _Db() as cur:
            out = fn(cur)
    except wf_folders.FolderError as exc:
        return jsonify({"error": str(exc)}), 400
    if out is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_json_safe(out)), status


@bp.post("/workflow-folders")
def workflow_folder_create():
    body = request.get_json(silent=True) or {}
    return _folder_call(lambda cur: wf_folders.create_folder(cur, body.get("name"), body.get("parent_id"),
                                                             _current_email()), 201)


@bp.patch("/workflow-folders/<int:folder_id>")
def workflow_folder_update(folder_id: int):
    body = request.get_json(silent=True) or {}
    return _folder_call(lambda cur: wf_folders.update_folder(cur, folder_id, body))


@bp.delete("/workflow-folders/<int:folder_id>")
def workflow_folder_delete(folder_id: int):
    return _folder_call(lambda cur: wf_folders.delete_folder(cur, folder_id))


@bp.post("/workflows/move")
def workflows_move():
    body = request.get_json(silent=True) or {}
    return _folder_call(lambda cur: {"moved": wf_folders.move_workflows(cur, body.get("ids"), body.get("folder_id"))})


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
            ids = engine.matching_ids(cur, conds, now, bool(body.get("only_dummy")), None, d["object"])
            items = []
            if ids and d["object"] == "contact":
                cur.execute(
                    """
                    SELECT ct.id, COALESCE(NULLIF(TRIM(CONCAT_WS(' ', ct.first_name, ct.last_name)), ''), ct.email)
                           || COALESCE(' · ' || c.name, ' · sin empresa') AS name, ct.is_dummy, ct.lead_life AS prospecting_status,
                           EXISTS (SELECT 1 FROM prospect_wf_enrollments e WHERE e.contact_id = ct.id
                                    AND e.workflow_id = %s AND e.status IN ('active','waiting')) AS already_in
                      FROM prospect_contacts ct LEFT JOIN prospect_companies c ON c.id = ct.company_id
                     WHERE ct.id = ANY(%s) ORDER BY 2 LIMIT 200
                    """,
                    (body.get("id") or 0, ids),
                )
                items = [dict(r) for r in cur.fetchall()]
            elif ids:
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
            rid = int(body.get("record_id") or body.get("company_id") or 0)
            result = engine.simulate(cur, d, rid, now)
    except InvalidWorkflow as exc:
        return _invalid(exc)
    except LookupError:
        return jsonify({"error": "Ese registro no existe."}), 404
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
    ids = body.get("record_ids", body.get("company_ids"))
    with _Db() as cur:
        wf = wf_store.get_workflow(cur, wf_id)
        if wf is None:
            return jsonify({"error": "not_found"}), 404
        result = engine.enroll_now(cur, wf, engine.utcnow(), _current_email(),
                                   bool(body.get("only_dummy")),
                                   record_ids=[int(x) for x in ids] if isinstance(ids, list) else None)
    return jsonify(_json_safe(result))


@bp.post("/workflows/<int:wf_id>/unenroll")
def workflow_unenroll(wf_id: int):
    denied = _editor_only()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    with _Db() as cur:
        wf = wf_store.get_workflow(cur, wf_id)
        if wf is None:
            return jsonify({"error": "not_found"}), 404
        n = sum(
            engine.unenroll_record(cur, wf, int(c), engine.utcnow(), f"Sacado a mano por {_current_email()}")
            for c in (body.get("record_ids") or body.get("company_ids") or []) if c is not None
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
# Datos de prueba (sección Configuración: owner + editoras de workflows)
# --------------------------------------------------------------------------- #
@bp.post("/dummy/seed")
def dummy_seed():
    body = request.get_json(silent=True) or {}
    n = max(1, min(300, int(body.get("n") or 60)))
    with _Db() as cur:
        denied = _gate(cur, settings=True)
        if denied:
            return denied
        owners = [b["email"] for b in store.list_bdrs(cur)]
        ids = store.seed_dummies(cur, n, owners, date.today())
        n_contacts = store.seed_dummy_contacts(cur, ids, owners, date.today())
        # Disparadores "se crea": las dummies (y sus contactos) cuentan como recién llegados.
        now = engine.utcnow()
        for cid in ids:
            for c in store.company_contacts(cur, cid):
                engine.emit_event(cur, "contact", c["id"], "created",
                                  [{"field": k, "old": None, "new": v} for k, v in c.items() if v not in (None, "", [])],
                                  now, _current_email())
            _run_instant(cur, cid, "created", [], _current_email())
    return jsonify({"created": len(ids), "contacts": n_contacts})


@bp.delete("/dummy")
def dummy_delete():
    with _Db() as cur:
        denied = _gate(cur, settings=True)
        if denied:
            return denied
        deleted = store.delete_dummies(cur)
    return jsonify({"deleted": deleted})


# --------------------------------------------------------------------------- #
# Negocios (deals, 2026-11-04): el pipeline de HubSpot dentro del Hub.
# Ver prospecting/deals.py (tablas) y prospecting/deal_to_hub.py (cuenta / oportunidad).
# --------------------------------------------------------------------------- #
def _deal_filters(raw: dict) -> dict:
    f = {k: v for k, v in (raw or {}).items() if v not in (None, "")}
    f.pop("ids", None)
    if f.get("dummy") in ("include", "only") and not _sees_dummies(_current_email()):
        f["dummy"] = "exclude"
    return f


def _deal_out(cur, deal_id: int, hub: dict | None = None) -> dict:
    from prospecting import deal_to_hub, deals as deals_store

    # Lo que pasó en su oportunidad (etapa + valores de Signed / Close Win / Closed Lost).
    cur.execute("SAVEPOINT deal_reflect")
    try:
        deals_store.reflect(cur, [deal_id], values=True)
        cur.execute("RELEASE SAVEPOINT deal_reflect")
    except Exception:  # noqa: BLE001 — leer el negocio no puede fallar por esto
        cur.execute("ROLLBACK TO SAVEPOINT deal_reflect")
    out = deals_store.get_deal(cur, deal_id) or {}
    if out:
        out["candidates"] = deal_to_hub.waiting_candidates(cur, out)
        ok, why = deal_to_hub.applies(out)
        out["hub_rule"] = None if ok else why
    if hub:
        out["hub"] = {k: v for k, v in hub.items() if k != "after_commit"}
    return out


def _deal_write(fn):
    """Corre `fn(cur)` -> (deal_id, status) y después el puente con el hub; el Slack de
    Sourcing sale después del commit. Errores de validación -> 400 / 409."""
    from prospecting import deal_to_hub, deals as deals_store

    hub: dict = {}
    try:
        with _Db() as cur:
            denied = _gate(cur)
            if denied:
                return denied
            res = fn(cur)
            deal_id, status = res[0], res[1]
            fill = res[2] if len(res) > 2 else None
            if deal_id is None:
                return jsonify({"error": "not_found"}), 404
            # Lo cargado en el popup rellena los vacíos de la empresa / contacto (y eso son
            # cambios de verdad: disparan sus workflows como cualquier edición).
            if fill:
                for obj, rid, cid, changes in deals_store.fill_related(cur, deal_id, fill, _current_email()):
                    _run_instant(cur, cid, "updated", changes, _current_email(), obj=obj, record_id=rid)
            cur.execute("SAVEPOINT deal_hub")
            try:
                hub = deal_to_hub.run(cur, deal_id, _current_email())
                cur.execute("RELEASE SAVEPOINT deal_hub")
            except Exception as exc:  # noqa: BLE001 — el negocio se guarda igual
                cur.execute("ROLLBACK TO SAVEPOINT deal_hub")
                hub = {"error": f"No se pudo crear/actualizar la cuenta u oportunidad del hub: {str(exc)[:200]}"}
            out = _deal_out(cur, deal_id, hub)
    except deals_store.MissingFields as exc:
        return jsonify({"error": str(exc), "needs_fields": exc.missing, "stage_key": exc.stage_key}), 409
    except LookupError:
        return jsonify({"error": "not_found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    deal_to_hub.after_commit(hub)
    return jsonify(_json_safe(out)), status


@bp.get("/deals/board")
def deals_board():
    from prospecting import deals as deals_store

    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        f = _deal_filters(request.args.to_dict())
        # Lo que pasó en las oportunidades del hub se ve al abrir el tablero (no espera al cron).
        if not f.get("offset"):
            deals_store.reflect(cur, pipeline=f.get("pipeline"))
        data = deals_store.board(cur, f)
    return jsonify(_json_safe(data))


@bp.get("/deals")
def deals_list():
    from prospecting import deals as deals_store

    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        data = deals_store.list_deals(cur, _deal_filters(request.args.to_dict()))
        data["pipelines"] = deals_store.pipelines(cur)
    return jsonify(_json_safe(data))


@bp.get("/deals/pipelines")
def deals_pipelines():
    from prospecting import deals as deals_store

    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        data = deals_store.pipelines(cur)
    return jsonify(_json_safe({"pipelines": data}))


@bp.get("/deals/<int:deal_id>/stage-form")
def deal_stage_form(deal_id: int):
    """«Propiedades dependientes» de la etapa `?stage=`: campos con su valor o el prellenado."""
    from prospecting import deals as deals_store

    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        deal = deals_store.get_deal(cur, deal_id)
        if deal is None:
            return jsonify({"error": "not_found"}), 404
        data = deals_store.stage_form(cur, request.args.get("stage") or "", deal=deal)
    return jsonify(_json_safe(data))


@bp.post("/deals/stage-form")
def deal_stage_form_draft():
    """Lo mismo para un negocio que todavía no existe: {stage_key, company_id, contact_ids, values}."""
    from prospecting import deals as deals_store

    body = request.get_json(silent=True) or {}
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        data = deals_store.stage_form(cur, str(body.get("stage_key") or ""), deal=body.get("values") or {},
                                      company_id=store._to_int(body.get("company_id")),
                                      contact_ids=[store._to_int(x) for x in body.get("contact_ids") or []])
    return jsonify(_json_safe(data))


@bp.get("/deals/<int:deal_id>")
def deal_get(deal_id: int):
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        out = _deal_out(cur, deal_id)
    if not out:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_json_safe(out))


@bp.post("/deals")
def deal_create():
    from prospecting import deals as deals_store

    body = request.get_json(silent=True) or {}
    is_dummy = bool(body.pop("is_dummy", False)) and _sees_dummies(_current_email())

    def go(cur):
        row = deals_store.create_deal(cur, dict(body), _current_email(), is_dummy=is_dummy)
        return row["id"], 201, body
    return _deal_write(go)


@bp.patch("/deals/<int:deal_id>")
def deal_patch(deal_id: int):
    from prospecting import deals as deals_store

    body = request.get_json(silent=True) or {}

    def go(cur):
        deals_store.update_deal(cur, deal_id, body, _current_email())
        return deal_id, 200
    return _deal_write(go)


@bp.patch("/deals/<int:deal_id>/stage")
def deal_move(deal_id: int):
    """{stage_key, pipeline_key?, fields?}: `fields` son los del popup de obligatorios.
    409 + `needs_fields` si falta alguno (la página abre el popup)."""
    from prospecting import deals as deals_store

    body = request.get_json(silent=True) or {}

    def go(cur):
        deals_store.move_stage(cur, deal_id, str(body.get("stage_key") or ""), _current_email(),
                               patch=body.get("fields") or None, pipeline_key=body.get("pipeline_key") or None)
        return deal_id, 200, body.get("fields")
    return _deal_write(go)


@bp.patch("/deals/<int:deal_id>/company")
def deal_set_company(deal_id: int):
    from prospecting import deals as deals_store

    body = request.get_json(silent=True) or {}

    def go(cur):
        deals_store.set_company(cur, deal_id, store._to_int(body.get("company_id")), _current_email())
        return deal_id, 200
    return _deal_write(go)


@bp.put("/deals/<int:deal_id>/contacts")
def deal_set_contacts(deal_id: int):
    from prospecting import deals as deals_store

    body = request.get_json(silent=True) or {}

    def go(cur):
        ids = [store._to_int(x) for x in (body.get("contact_ids") or [])]
        deals_store.set_contacts(cur, deal_id, [x for x in ids if x], _current_email())
        return deal_id, 200
    return _deal_write(go)


@bp.post("/deals/<int:deal_id>/link-opportunity")
def deal_link_opportunity(deal_id: int):
    from prospecting import deal_to_hub

    body = request.get_json(silent=True) or {}
    opp_id = store._to_int(body.get("opportunity_id"))
    if not opp_id:
        return jsonify({"error": "Falta opportunity_id."}), 400

    def go(cur):
        deal_to_hub.link_opportunity(cur, deal_id, opp_id, _current_email())
        return deal_id, 200
    return _deal_write(go)


@bp.delete("/deals/<int:deal_id>/link-opportunity")
def deal_unlink_opportunity(deal_id: int):
    from prospecting import deal_to_hub

    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        try:
            deal_to_hub.unlink_opportunity(cur, deal_id, _current_email())
        except LookupError:
            return jsonify({"error": "not_found"}), 404
        out = _deal_out(cur, deal_id)
    return jsonify(_json_safe(out))


@bp.post("/deals/<int:deal_id>/mark-new")
def deal_mark_new(deal_id: int):
    """«Es nueva, creala»: el negocio no es ninguna de las oportunidades de la cuenta."""
    def go(cur):
        cur.execute("UPDATE prospect_deals SET hub_mark_new = TRUE, hub_status = NULL, hub_note = NULL "
                    "WHERE id = %s RETURNING id", (deal_id,))
        r = cur.fetchone()
        return (r["id"] if r else None), 200
    return _deal_write(go)


@bp.delete("/deals/<int:deal_id>")
def deal_delete(deal_id: int):
    from prospecting import deals as deals_store

    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        ok = deals_store.delete_deal(cur, deal_id, _current_email())
    return (jsonify({"deleted": True}), 200) if ok else (jsonify({"error": "not_found"}), 404)


@bp.get("/deals/<int:deal_id>/history")
def deal_history(deal_id: int):
    from prospecting import deals as deals_store

    field = request.args.get("field") or ""
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        deal = deals_store.get_deal(cur, deal_id)
        if deal is None:
            return jsonify({"error": "not_found"}), 404
        cur.execute(
            "SELECT actor, source, old_value, new_value, at FROM prospect_company_events "
            "WHERE deal_id = %s AND field = %s ORDER BY at DESC, id DESC LIMIT 500",
            (deal_id, field),
        )
        changes = [dict(r) for r in cur.fetchall()]
    created = {"actor": deal.get("created_by"), "source": None, "at": deal.get("created_at"),
               "value": changes[-1]["old_value"] if changes else store._fmt(deal.get(field))}
    return jsonify(_json_safe({"field": field, "current": store._fmt(deal.get(field)), "changes": changes,
                               "created": created}))


@bp.post("/deals/export")
def deals_export():
    import csv
    import io
    from flask import Response
    from prospecting import deals as deals_store

    body = request.get_json(silent=True) or {}
    catalog = deals_store.export_fields()
    by_key = {f["key"]: f for f in catalog}
    cols = [k for k in (body.get("columns") or [f["key"] for f in catalog]) if k in by_key]
    with _Db() as cur:
        denied = _gate(cur)
        if denied:
            return denied
        if isinstance(body.get("ids"), list):
            ids = [int(x) for x in body["ids"] if str(x).isdigit()]
        else:
            ids = deals_store.deal_ids(cur, _deal_filters(body.get("filters") or {}))
        ids = ids[:EXPORT_MAX]
        rows = deals_store.export_rows(cur, ids, body.get("sort") or (body.get("filters") or {}).get("sort"))
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    w.writerow([by_key[k]["label"] for k in cols])
    for r in rows:
        w.writerow([_csv_cell(by_key[k], r.get(k)) for k in cols])
    name = f"prospecting-negocios-{date.today().isoformat()}.csv"
    return Response(buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@bp.post("/hubspot/sync-deals")
def hubspot_deals_sync():
    """Negocios de HubSpot -> Hub (prospecting/hubspot_deals.py). Tercer paso del cron, después
    de empresas y contactos: un negocio nuevo encuentra su empresa y sus contactos."""
    from prospecting import hubspot_deals as hs_deals

    by_cron = _token_ok("DASHBOARD_AUDIT_TOKEN", "X-Audit-Token")
    if not by_cron and not _is_admin(_current_email()):
        return jsonify({"error": "forbidden"}), 403
    dry = request.args.get("dry") in ("1", "true")
    try:
        limit = max(1, min(5000, int(request.args.get("limit") or 2000)))
    except ValueError:
        limit = 2000
    conn = get_connection()
    try:
        report = hs_deals.sync(conn, dry_run=dry, max_deals=limit)
    finally:
        conn.close()
    if report.get("status") == "busy":
        return jsonify(report), 409
    return jsonify(_json_safe(report))


@bp.get("/hubspot/sync-deals/last")
def hubspot_deals_sync_last():
    from prospecting import hubspot_companies as hs_companies
    from prospecting import hubspot_deals as hs_deals

    if not _token_ok("DASHBOARD_AUDIT_TOKEN", "X-Audit-Token") and not _is_admin(_current_email()):
        return jsonify({"error": "forbidden"}), 403
    with _Db() as cur:
        row = hs_companies.last_report(cur, hs_deals.SYNC_KEY)
    return jsonify(_json_safe(dict(row) if row else {}))
