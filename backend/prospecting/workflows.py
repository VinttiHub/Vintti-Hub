"""Workflows del CRM de prospección: guardarlos, leerlos, activarlos.

Los arma la página (pestaña Workflows, editor tipo HubSpot). Un workflow es
disparador + grafo de pasos + desinscripción / meta / configuración; lo valida
`rules.py` y lo corre `engine.py`.

Los workflows de la versión anterior (sin estado) tenían `conditions` + una
lista de `actions`. `normalize()` los convierte al leerlos: el filtro pasa a ser
el disparador y las acciones una cadena de pasos. No hace falta migrarlos.
"""
from __future__ import annotations

from psycopg2.extras import Json

from prospecting.rules import Ctx, InvalidWorkflow, prune_steps, validate_definition
from prospecting.store import list_bdrs

WF_COLUMNS = """
    w.id, w.name, w.description, w.enabled, w.reenroll, w.conditions, w.actions,
    w.trigger, w.steps, w.unenroll, w.goal, w.settings,
    w.created_by, w.updated_by, w.created_at, w.updated_at
"""


def normalize(row: dict) -> dict:
    wf = dict(row)
    if not wf.get("trigger"):
        wf["trigger"] = {"type": "filter", "conditions": wf.get("conditions") or {"groups": []}}
    if not wf.get("steps"):
        acts = wf.get("actions") or []
        ids = [f"n{i + 1}" for i in range(len(acts))]
        wf["steps"] = {
            "start": ids[0] if ids else None,
            "nodes": {
                nid: {"type": "action", "action": a, "next": ids[i + 1] if i + 1 < len(ids) else None}
                for i, (nid, a) in enumerate(zip(ids, acts))
            },
        }
    wf["settings"] = wf.get("settings") or {}
    wf.pop("conditions", None)
    wf.pop("actions", None)
    return wf


def get_workflow(cur, wf_id) -> dict | None:
    if wf_id is None:
        return None
    cur.execute(f"SELECT {WF_COLUMNS} FROM prospect_workflows w WHERE w.id = %s", (wf_id,))
    row = cur.fetchone()
    return normalize(row) if row else None


def list_enabled(cur) -> list[dict]:
    cur.execute(f"SELECT {WF_COLUMNS} FROM prospect_workflows w WHERE w.enabled ORDER BY w.id")
    return [normalize(r) for r in cur.fetchall()]


def list_workflows(cur) -> list[dict]:
    """Con los contadores de inscripciones que muestra la lista."""
    cur.execute(
        f"""
        SELECT {WF_COLUMNS}, st.stats
          FROM prospect_workflows w
          LEFT JOIN LATERAL (
                SELECT jsonb_object_agg(status, n) AS stats FROM (
                    SELECT status, COUNT(*) AS n FROM prospect_wf_enrollments
                     WHERE workflow_id = w.id GROUP BY status
                ) x
          ) st ON TRUE
         ORDER BY w.created_at, w.id
        """
    )
    out = []
    for r in cur.fetchall():
        wf = normalize(r)
        wf["stats"] = r.get("stats") or {}
        out.append(wf)
    return out


def _ctx(cur, self_id=None) -> Ctx:
    cur.execute("SELECT id FROM prospect_workflows")
    ids = {r["id"] for r in cur.fetchall()}
    return Ctx(owners=[b["email"] for b in list_bdrs(cur)], workflow_ids=ids, self_id=self_id)


def clean_definition(cur, body: dict, self_id=None, require_name: bool = True) -> dict:
    """Valida lo que manda el editor. Levanta InvalidWorkflow con todos los errores."""
    name = (body.get("name") or "").strip()
    errors = [] if name or not require_name else ["Ponele un nombre al workflow."]
    steps = prune_steps(body.get("steps") or {})
    defn = {
        "trigger": body.get("trigger"),
        "steps": steps,
        "unenroll": body.get("unenroll") or None,
        "goal": body.get("goal") or None,
        "settings": body.get("settings") or {},
    }
    errors += validate_definition(defn, _ctx(cur, self_id))
    if errors:
        raise InvalidWorkflow(errors)
    return {
        "name": name[:200],
        "description": (body.get("description") or "").strip()[:1000] or None,
        "reenroll": body.get("reenroll", True) is not False,
        **defn,
    }


def create_workflow(cur, body: dict, actor: str) -> dict:
    d = clean_definition(cur, body)
    cur.execute(
        """
        INSERT INTO prospect_workflows
            (name, description, enabled, reenroll, trigger, steps, unenroll, goal, settings,
             created_by, updated_by)
        VALUES (%s, %s, FALSE, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (d["name"], d["description"], d["reenroll"], Json(d["trigger"]), Json(d["steps"]),
         Json(d["unenroll"]), Json(d["goal"]), Json(d["settings"]), actor, actor),
    )
    return get_workflow(cur, cur.fetchone()["id"])


def update_workflow(cur, wf_id: int, body: dict, actor: str) -> dict | None:
    if get_workflow(cur, wf_id) is None:
        return None
    d = clean_definition(cur, body, self_id=wf_id)
    cur.execute(
        """
        UPDATE prospect_workflows
           SET name = %s, description = %s, reenroll = %s, trigger = %s, steps = %s,
               unenroll = %s, goal = %s, settings = %s, conditions = NULL, actions = NULL,
               updated_by = %s, updated_at = NOW()
         WHERE id = %s
        """,
        (d["name"], d["description"], d["reenroll"], Json(d["trigger"]), Json(d["steps"]),
         Json(d["unenroll"]), Json(d["goal"]), Json(d["settings"]), actor, wf_id),
    )
    return get_workflow(cur, wf_id)


def set_enabled(cur, wf_id: int, enabled: bool, actor: str, include_existing: bool = False) -> dict | None:
    """Activar / desactivar. Al activar un workflow de filtro, como HubSpot, se elige si
    también entran las empresas que YA cumplen hoy; si no, se las anota como "ya
    cumplía" y sólo entran las que pasen a cumplir de acá en adelante."""
    from prospecting import engine

    wf = get_workflow(cur, wf_id)
    if wf is None:
        return None
    if enabled:
        errors = validate_definition(wf, _ctx(cur, wf_id))
        if errors:
            raise InvalidWorkflow(errors)
    cur.execute(
        "UPDATE prospect_workflows SET enabled = %s, updated_by = %s, updated_at = NOW() WHERE id = %s",
        (enabled, actor, wf_id),
    )
    result = get_workflow(cur, wf_id)
    if enabled and not wf["enabled"]:
        now = engine.utcnow()
        t = wf["trigger"]["type"]
        if t == "filter":
            dummy_only = engine._dummy_only(True, False)
            ids = engine.matching_ids(cur, wf["trigger"]["conditions"], now, dummy_only)
            if include_existing:
                result["activation"] = engine.enroll_now(cur, result, now, actor, dummy_only)
            else:
                engine.snapshot_matches(cur, result, now, dummy_only, ids)
                result["activation"] = {"enrolled": 0, "skipped_existing": len(ids)}
        elif t == "schedule":
            # Sólo los horarios de acá en adelante (no el de hoy temprano que ya pasó).
            cur.execute(
                """
                INSERT INTO prospect_wf_schedule_state (workflow_id, last_fired) VALUES (%s, %s)
                ON CONFLICT (workflow_id) DO UPDATE SET last_fired = EXCLUDED.last_fired
                """,
                (wf_id, now),
            )
    return result


def delete_workflow(cur, wf_id: int) -> bool:
    cur.execute("DELETE FROM prospect_workflows WHERE id = %s", (wf_id,))
    return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Historial
# --------------------------------------------------------------------------- #
def list_enrollments(cur, wf_id: int, status: str | None = None, limit: int = 300) -> list[dict]:
    params = [wf_id]
    extra = ""
    if status:
        extra = " AND e.status = %s"
        params.append(status)
    cur.execute(
        f"""
        SELECT e.id, e.company_id, c.name AS company_name, c.is_dummy, e.status, e.current_node,
               e.wake_at, e.source, e.enrolled_by, e.enrolled_at, e.finished_at, e.last_error,
               (SELECT summary FROM prospect_wf_step_log l WHERE l.enrollment_id = e.id
                 ORDER BY l.id DESC LIMIT 1) AS last_step
          FROM prospect_wf_enrollments e
          JOIN prospect_companies c ON c.id = e.company_id
         WHERE e.workflow_id = %s {extra}
         ORDER BY e.enrolled_at DESC, e.id DESC
         LIMIT %s
        """,
        params + [limit],
    )
    return [dict(r) for r in cur.fetchall()]


def enrollment_detail(cur, enrollment_id: int) -> dict | None:
    cur.execute(
        """
        SELECT e.*, c.name AS company_name, c.is_dummy, w.name AS workflow_name
          FROM prospect_wf_enrollments e
          JOIN prospect_companies c ON c.id = e.company_id
          JOIN prospect_workflows w ON w.id = e.workflow_id
         WHERE e.id = %s
        """,
        (enrollment_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    out = dict(row)
    cur.execute(
        "SELECT node_id, kind, summary, detail, ok, at FROM prospect_wf_step_log WHERE enrollment_id = %s ORDER BY id",
        (enrollment_id,),
    )
    out["log"] = [dict(r) for r in cur.fetchall()]
    return out


def company_enrollments(cur, company_id: int) -> list[dict]:
    cur.execute(
        """
        SELECT e.id, e.workflow_id, w.name AS workflow_name, e.status, e.wake_at, e.enrolled_at,
               e.finished_at,
               (SELECT summary FROM prospect_wf_step_log l WHERE l.enrollment_id = e.id
                 ORDER BY l.id DESC LIMIT 1) AS last_step
          FROM prospect_wf_enrollments e
          JOIN prospect_workflows w ON w.id = e.workflow_id
         WHERE e.company_id = %s
         ORDER BY e.enrolled_at DESC, e.id DESC
         LIMIT 50
        """,
        (company_id,),
    )
    return [dict(r) for r in cur.fetchall()]
