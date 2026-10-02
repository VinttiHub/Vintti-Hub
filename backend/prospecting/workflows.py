"""Workflows del CRM de prospección — lo que antes corría HubSpot.

Cada workflow es una entrada de `WORKFLOWS`: una condición de inscripción (SQL
sobre `prospect_companies`) y los campos que pisa. `run_workflows()` los evalúa
todos; cada cambio deja un evento en `prospect_company_events` con
`source = 'workflow:<key>'`, así que en el historial de la empresa se ve qué
workflow la tocó.

La "reinscripción activada" de HubSpot sale gratis: la condición se evalúa en cada
corrida, así que una empresa que vuelve a cumplirla (la reasignan, pasan 60 días)
vuelve a entrar.

`as_of` es la fecha "de hoy" para la condición: permite simular el paso del tiempo
con datos dummy sin esperar 60 días de verdad.

Para agregar uno: una entrada más en WORKFLOWS. No hace falta tocar el runner.
"""
from __future__ import annotations

from datetime import date

from psycopg2.extras import Json

from prospecting.constants import STATUS_IN_PROGRESS, STATUS_RECYCLED
from prospecting.store import log_event

# `condition` recibe params nombrados: %(as_of)s.
WORKFLOWS = [
    {
        # HubSpot: "Prospecting Start Date es más que hace más de 60 días" y
        # "Prospecting Status es igual a In Progress" -> borra Owner HubSpot, Owner
        # Apollo y Start Date, y pasa el status a Recycled.
        "key": "recycle_60d",
        "name": "Recycle: In Progress hace más de 60 días",
        "condition": """
            prospecting_status = '""" + STATUS_IN_PROGRESS + """'
            AND prospecting_start_date < %(as_of)s::date - 60
        """,
        "set": {
            "prospecting_owner_email": None,
            "prospecting_owner_apollo": None,
            "prospecting_start_date": None,
            "prospecting_status": STATUS_RECYCLED,
        },
    },
]

WORKFLOWS_BY_KEY = {w["key"]: w for w in WORKFLOWS}


def _run_one(cur, wf: dict, as_of: date, dry_run: bool, only_dummy: bool, actor: str | None) -> dict:
    scope = "AND is_dummy" if only_dummy else ""
    cur.execute(
        f"""
        SELECT id, name, is_dummy, {', '.join(wf['set'].keys())}
          FROM prospect_companies
         WHERE ({wf['condition']}) {scope}
         ORDER BY id
         {'' if dry_run else 'FOR UPDATE'}
        """,
        {"as_of": as_of},
    )
    rows = [dict(r) for r in cur.fetchall()]
    items = []
    for r in rows:
        changes = {
            col: {"from": r.get(col), "to": new}
            for col, new in wf["set"].items()
            if r.get(col) != new
        }
        items.append({"id": r["id"], "name": r["name"], "is_dummy": r["is_dummy"], "changes": changes})
        if dry_run or not changes:
            continue
        sets = ", ".join(f"{c} = %s" for c in changes)
        cur.execute(
            f"UPDATE prospect_companies SET {sets}, updated_at = NOW() WHERE id = %s",
            [changes[c]["to"] for c in changes] + [r["id"]],
        )
        for col, ch in changes.items():
            log_event(cur, r["id"], f"workflow:{wf['key']}", actor, col, ch["from"], ch["to"])

    def _plain(v):
        return v.isoformat() if hasattr(v, "isoformat") else v

    details = [
        {**it, "changes": {c: {"from": _plain(v["from"]), "to": _plain(v["to"])} for c, v in it["changes"].items()}}
        for it in items
    ]
    cur.execute(
        """
        INSERT INTO prospect_workflow_runs
            (workflow_key, as_of, dry_run, only_dummy, triggered_by, affected, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (wf["key"], as_of, dry_run, only_dummy, actor, len(items), Json(details)),
    )
    return {"key": wf["key"], "name": wf["name"], "affected": len(items), "items": details}


def run_workflows(cur, as_of: date | None = None, dry_run: bool = True,
                  only_dummy: bool = False, keys: list[str] | None = None,
                  actor: str | None = None) -> dict:
    as_of = as_of or date.today()
    selected = [WORKFLOWS_BY_KEY[k] for k in keys if k in WORKFLOWS_BY_KEY] if keys else WORKFLOWS
    results = [_run_one(cur, wf, as_of, dry_run, only_dummy, actor) for wf in selected]
    return {
        "as_of": as_of.isoformat(),
        "dry_run": dry_run,
        "only_dummy": only_dummy,
        "workflows": results,
        "total_affected": sum(r["affected"] for r in results),
    }


def list_workflows() -> list[dict]:
    return [{"key": w["key"], "name": w["name"]} for w in WORKFLOWS]
