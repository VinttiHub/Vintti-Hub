"""Workflows del CRM de prospección — lo que antes corría HubSpot.

Los workflows ya no están en código: son filas de `prospect_workflows` que se arman
desde la página (pestaña Workflows). La definición la valida y la traduce a SQL
`prospecting/rules.py`. Este módulo los CORRE:

  * `run_workflows()`   — pasada por lote (botón Apply / Preview, cron diario).
  * `run_for_company()` — sobre UNA empresa, apenas alguien la edita o llega de
                          Clay ("al instante", decisión de la owner 2026-10-05).
  * `preview_definition()` — dry run de una definición todavía sin guardar.

Cada cambio deja un evento en `prospect_company_events` con
`source = 'workflow:<id>'`, así que en el historial se ve qué workflow tocó qué.

Reinscripción:
  * prendida — la condición se evalúa en cada corrida; una empresa vuelve a entrar
    cada vez que la cumple y la acción le cambiaría algo.
  * apagada  — entra una sola vez (queda en `prospect_workflow_enrollments`).

Una empresa sólo cuenta como afectada si la acción le CAMBIA algo: una que ya está
como el workflow la dejaría no es un cambio (ni en el Preview ni en el historial).

`as_of` es la fecha "de hoy" para las condiciones: permite simular el paso del
tiempo con datos dummy.

Freno de la fase de prueba: con `AUTOMATION_REAL_DATA = False`, lo automático
(`automatic=True`: al instante y cron) sólo toca empresas dummy.
"""
from __future__ import annotations

from datetime import date

from psycopg2.extras import Json

from prospecting.constants import AUTOMATION_REAL_DATA
from prospecting.rules import InvalidWorkflow, action_values, compile_conditions, validate
from prospecting.store import list_bdrs, log_event

# Una acción de un workflow puede hacer que otro se cumpla (A pone DQL, B mira DQL).
# Al instante se repite hasta que nada cambie, con este tope contra loops.
MAX_CHAIN_PASSES = 3


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
WF_COLUMNS = """
    w.id, w.name, w.description, w.enabled, w.reenroll, w.conditions, w.actions,
    w.created_by, w.updated_by, w.created_at, w.updated_at
"""


def list_workflows(cur) -> list[dict]:
    cur.execute(
        f"""
        SELECT {WF_COLUMNS},
               lr.created_at AS last_run_at, lr.affected AS last_run_affected,
               lr.triggered_by AS last_run_by
          FROM prospect_workflows w
          LEFT JOIN LATERAL (
                SELECT r.created_at, r.affected, r.triggered_by
                  FROM prospect_workflow_runs r
                 WHERE r.workflow_id = w.id AND NOT r.dry_run
                 ORDER BY r.created_at DESC
                 LIMIT 1
          ) lr ON TRUE
         ORDER BY w.created_at, w.id
        """
    )
    return [dict(r) for r in cur.fetchall()]


def get_workflow(cur, wf_id: int) -> dict | None:
    cur.execute(f"SELECT {WF_COLUMNS} FROM prospect_workflows w WHERE w.id = %s", (wf_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def _owners(cur) -> list[str]:
    return [b["email"] for b in list_bdrs(cur)]


def _clean_payload(cur, body: dict) -> dict:
    name = (body.get("name") or "").strip()
    errors = [] if name else ["Give the workflow a name."]
    errors += validate(body.get("conditions"), body.get("actions"), _owners(cur))
    if errors:
        raise InvalidWorkflow(errors)
    return {
        "name": name[:200],
        "description": (body.get("description") or "").strip()[:1000] or None,
        "reenroll": body.get("reenroll", True) is not False,
        "conditions": body["conditions"],
        "actions": body["actions"],
    }


def create_workflow(cur, body: dict, actor: str) -> dict:
    data = _clean_payload(cur, body)
    cur.execute(
        """
        INSERT INTO prospect_workflows
            (name, description, enabled, reenroll, conditions, actions, created_by, updated_by)
        VALUES (%s, %s, FALSE, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (data["name"], data["description"], data["reenroll"],
         Json(data["conditions"]), Json(data["actions"]), actor, actor),
    )
    return get_workflow(cur, cur.fetchone()["id"])


def update_workflow(cur, wf_id: int, body: dict, actor: str) -> dict | None:
    if get_workflow(cur, wf_id) is None:
        return None
    data = _clean_payload(cur, body)
    cur.execute(
        """
        UPDATE prospect_workflows
           SET name = %s, description = %s, reenroll = %s, conditions = %s, actions = %s,
               updated_by = %s, updated_at = NOW()
         WHERE id = %s
        """,
        (data["name"], data["description"], data["reenroll"],
         Json(data["conditions"]), Json(data["actions"]), actor, wf_id),
    )
    return get_workflow(cur, wf_id)


def set_enabled(cur, wf_id: int, enabled: bool, actor: str) -> dict | None:
    wf = get_workflow(cur, wf_id)
    if wf is None:
        return None
    if enabled:
        # Una definición vieja puede haber quedado inválida (p. ej. se sacó un BDR).
        errors = validate(wf["conditions"], wf["actions"], _owners(cur))
        if errors:
            raise InvalidWorkflow(errors)
    cur.execute(
        "UPDATE prospect_workflows SET enabled = %s, updated_by = %s, updated_at = NOW() WHERE id = %s",
        (enabled, actor, wf_id),
    )
    return get_workflow(cur, wf_id)


def delete_workflow(cur, wf_id: int) -> bool:
    cur.execute("DELETE FROM prospect_workflows WHERE id = %s", (wf_id,))
    return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Ejecución
# --------------------------------------------------------------------------- #
def _plain(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _scope_sql(only_dummy: bool, company_id: int | None) -> tuple[str, list]:
    parts, params = [], []
    if only_dummy:
        parts.append("is_dummy")
    if company_id is not None:
        parts.append("id = %s")
        params.append(company_id)
    return ("".join(" AND " + p for p in parts)), params


def _run_one(cur, wf: dict, as_of: date, dry_run: bool, only_dummy: bool,
             actor: str | None, company_id: int | None = None) -> list[dict]:
    """Corre un workflow (guardado o no) y devuelve las empresas que cambió/cambiaría."""
    cond_sql, cond_params = compile_conditions(wf["conditions"], as_of)
    new_values = action_values(wf["actions"], as_of)
    cols = list(new_values.keys())
    scope_sql, scope_params = _scope_sql(only_dummy, company_id)

    enroll_sql, enroll_params = "", []
    if wf.get("id") and not wf.get("reenroll", True):
        enroll_sql = (" AND NOT EXISTS (SELECT 1 FROM prospect_workflow_enrollments e"
                      " WHERE e.workflow_id = %s AND e.company_id = prospect_companies.id)")
        enroll_params = [wf["id"]]

    cur.execute(
        f"""
        SELECT id, name, is_dummy, {', '.join(cols)}
          FROM prospect_companies
         WHERE {cond_sql} {scope_sql} {enroll_sql}
         ORDER BY id
         {'' if dry_run else 'FOR UPDATE'}
        """,
        cond_params + scope_params + enroll_params,
    )
    items = []
    for r in cur.fetchall():
        changes = {c: {"from": r.get(c), "to": v} for c, v in new_values.items() if r.get(c) != v}
        if not changes:
            continue
        items.append({
            "id": r["id"],
            "name": r["name"],
            "is_dummy": r["is_dummy"],
            "changes": {c: {"from": _plain(ch["from"]), "to": _plain(ch["to"])} for c, ch in changes.items()},
        })
        if dry_run:
            continue
        cur.execute(
            f"UPDATE prospect_companies SET {', '.join(c + ' = %s' for c in changes)}, "
            f"updated_at = NOW() WHERE id = %s",
            [changes[c]["to"] for c in changes] + [r["id"]],
        )
        for col, ch in changes.items():
            log_event(cur, r["id"], f"workflow:{wf['id']}", actor, col, ch["from"], ch["to"])
        if enroll_sql:
            cur.execute(
                "INSERT INTO prospect_workflow_enrollments (workflow_id, company_id) "
                "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (wf["id"], r["id"]),
            )
    return items


def _log_run(cur, wf: dict, as_of: date, dry_run: bool, only_dummy: bool,
             actor: str | None, items: list[dict]) -> None:
    cur.execute(
        """
        INSERT INTO prospect_workflow_runs
            (workflow_key, workflow_id, as_of, dry_run, only_dummy, triggered_by, affected, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (str(wf["id"]), wf["id"], as_of, dry_run, only_dummy, actor, len(items), Json(items)),
    )


def run_workflows(cur, as_of: date | None = None, dry_run: bool = True,
                  only_dummy: bool = False, workflow_ids: list[int] | None = None,
                  actor: str | None = None, automatic: bool = False) -> dict:
    """Pasada por lote. Sin `workflow_ids` corre los ACTIVOS; con ids, esos (activos o no:
    así se prueba uno antes de activarlo)."""
    as_of = as_of or date.today()
    if automatic and not AUTOMATION_REAL_DATA:
        only_dummy = True
    if workflow_ids:
        wfs = [w for w in (get_workflow(cur, int(i)) for i in workflow_ids) if w]
    else:
        wfs = [w for w in list_workflows(cur) if w["enabled"]]
    results = []
    for wf in wfs:
        items = _run_one(cur, wf, as_of, dry_run, only_dummy, actor)
        _log_run(cur, wf, as_of, dry_run, only_dummy, actor, items)
        results.append({"id": wf["id"], "name": wf["name"], "affected": len(items), "items": items})
    return {
        "as_of": as_of.isoformat(),
        "dry_run": dry_run,
        "only_dummy": only_dummy,
        "workflows": results,
        "total_affected": sum(r["affected"] for r in results),
    }


def preview_definition(cur, body: dict, as_of: date | None = None, only_dummy: bool = False) -> dict:
    """Dry run de lo que está en el editor, guardado o no. No escribe nada."""
    errors = validate(body.get("conditions"), body.get("actions"), _owners(cur))
    if errors:
        raise InvalidWorkflow(errors)
    as_of = as_of or date.today()
    wf = {
        "id": body.get("id"),
        "name": body.get("name") or "(unsaved)",
        "reenroll": body.get("reenroll", True) is not False,
        "conditions": body["conditions"],
        "actions": body["actions"],
    }
    items = _run_one(cur, wf, as_of, True, only_dummy, None)
    return {"as_of": as_of.isoformat(), "affected": len(items), "items": items}


def run_for_company(cur, company_id: int, actor: str | None = None) -> list[dict]:
    """Al instante: los workflows activos sobre una empresa recién editada o recién llegada.

    Devuelve qué workflows la cambiaron (para que la página refresque la fila).
    No registra una corrida por cada edición: el historial de la empresa ya lo dice.
    """
    only_dummy = not AUTOMATION_REAL_DATA
    wfs = [w for w in list_workflows(cur) if w["enabled"]]
    applied = []
    for _ in range(MAX_CHAIN_PASSES):
        changed = False
        for wf in wfs:
            try:
                items = _run_one(cur, wf, date.today(), False, only_dummy, actor, company_id)
            except InvalidWorkflow:
                continue
            if items:
                changed = True
                applied.append({"id": wf["id"], "name": wf["name"], "changes": items[0]["changes"]})
        if not changed:
            break
    return applied

