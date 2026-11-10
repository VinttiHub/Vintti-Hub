"""Recupera «Not ICP Reason» de las empresas cuyo motivo de HubSpot no estaba en la lista.

Hasta el 2026-11-10 `constants.NOT_ICP_REASONS` tenía 3 opciones (Equipo en Asia, +500
empleados, Other) y HubSpot usa 6. La importación y el sync de empresas descartaban todo
valor fuera de la lista (quedaba sólo en `raw_payload`): «Sin contactos validos/ actividad en
LinkedIn», «Otro», «Industria no objetivo» y «Empresa de staffing» quedaron vacíos en ~4,5 k
empresas, y el panel «Not ICP Reason» no cuadraba con HubSpot.

Con la lista ampliada el sync ya los trae en adelante, pero no rellena los viejos (la foto de
`raw_payload` ya decía ese valor: para el sync "no cambió"). Este script los trae de HubSpot
en vivo y los escribe **sólo donde el Hub está vacío**, con historial (source `hubspot_sync`).
Si el Hub tiene otro motivo, no lo pisa y lo reporta. Actualiza la foto `hubspot_seen` y
blinda los workflows de empresa por condiciones (el 7, «Not ICP Reason conocido → DQL», los
tomaría a todos): las que ya cumplen quedan como "ya cumplía".

    python scripts/backfill_not_icp_reason.py           # en seco
    python scripts/backfill_not_icp_reason.py --apply
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")
except Exception:
    pass

from psycopg2.extras import RealDictCursor, execute_values  # noqa: E402

from db import get_connection  # noqa: E402
from prospecting import engine, store  # noqa: E402
from prospecting import hubspot_companies as hco  # noqa: E402
from prospecting.constants import NOT_ICP_REASONS, STATUS_DQL  # noqa: E402
from prospecting.rules import has_conditions  # noqa: E402
from utils.hubspot import HubSpotClient  # noqa: E402

SOURCE = "hubspot_sync"


def fetch_hubspot(client: HubSpotClient, prop: str) -> dict[str, str]:
    """{hubspot_company_id: motivo} de todas las empresas con el motivo cargado. Una
    búsqueda por valor: cada una queda bajo el tope de 10 000 resultados de /search."""
    out: dict[str, str] = {}
    for value in NOT_ICP_REASONS:
        after = None
        while True:
            body = {
                "filterGroups": [{"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}],
                "properties": [prop],
                "sorts": [{"propertyName": "hs_object_id", "direction": "ASCENDING"}],
                "limit": 100,
            }
            if after:
                body["after"] = after
            payload = client._request("POST", "/crm/v3/objects/companies/search", json=body)
            for rec in payload.get("results", []):
                v = (rec.get("properties") or {}).get(prop)
                if v:
                    out[str(rec["id"])] = v
            after = ((payload.get("paging") or {}).get("next") or {}).get("after")
            if not after:
                break
    return out


def shield(cur, ids: list[int], stats: Counter) -> None:
    """Lo mismo que Importer.shield() de la importación de empresas."""
    if not ids:
        return
    now = engine.utcnow()
    for wf in engine.enabled_workflows(cur):
        if engine.obj_of(wf) != "company" or wf["trigger"].get("type") != "filter":
            continue
        if not has_conditions(wf["trigger"].get("conditions")):
            continue
        hits = engine.matching_ids(cur, wf["trigger"]["conditions"], now, False, ids, "company")
        if hits:
            execute_values(
                cur,
                """
                INSERT INTO prospect_wf_match (workflow_id, record_id, matching, changed_at) VALUES %s
                ON CONFLICT (workflow_id, record_id) DO UPDATE SET matching = TRUE, changed_at = EXCLUDED.changed_at
                """,
                [(wf["id"], h, True, now) for h in hits],
                page_size=1000,
            )
            stats[f"blindadas en workflow #{wf['id']} «{wf.get('name')}»"] += len(hits)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="escribe (default: en seco)")
    args = ap.parse_args()

    client = HubSpotClient()
    mapping, _, _ = hco.resolve_mapping(client)
    props = mapping.get("not_icp_reason") or []
    if not props:
        sys.exit("No encontré la propiedad Not ICP Reason en HubSpot.")
    prop = props[0]
    hs = fetch_hubspot(client, prop)
    print(f"HubSpot ({prop}): {len(hs)} empresas con motivo")
    for v, n in Counter(hs.values()).most_common():
        print(f"  {n:>6}  {v}")

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        store.ensure_schema(cur)
        cur.execute(
            """
            SELECT id, hubspot_company_id, not_icp_reason, prospecting_status,
                   hubspot_seen ? 'not_icp_reason' AS has_seen
              FROM prospect_companies
             WHERE NOT is_dummy AND hubspot_company_id = ANY(%s)
            """,
            (list(hs),),
        )
        rows = cur.fetchall()
        found = {r["hubspot_company_id"] for r in rows}
        fill, conflicts, same = [], [], 0
        status = Counter()
        for r in rows:
            v = hs[r["hubspot_company_id"]]
            if v not in NOT_ICP_REASONS:
                continue
            if not r["not_icp_reason"]:
                fill.append((r["id"], v, r["has_seen"]))
                status[r["prospecting_status"] or "(vacío)"] += 1
            elif r["not_icp_reason"] == v:
                same += 1
            else:
                conflicts.append((r["id"], r["not_icp_reason"], v))

        by_reason = Counter(v for _, v, _ in fill)
        print(f"\nEn el Hub: {len(rows)} | ya iguales: {same} | a completar: {len(fill)} | "
              f"con otro motivo (no se pisa): {len(conflicts)} | no están en el Hub: {len(set(hs) - found)}")
        for v, n in by_reason.most_common():
            print(f"  +{n:>5}  {v}")
        print("Status de las que se completan:", dict(status.most_common()))
        print(f"  (las que no están en {STATUS_DQL} no se mueven: el workflow 7 queda blindado)")
        for cid, old, new in conflicts[:20]:
            print(f"  conflicto #{cid}: Hub «{old}» vs HubSpot «{new}»")

        if not args.apply:
            conn.rollback()
            print("\nEn seco: no se escribió nada (--apply para aplicar).")
            return

        stats = Counter()
        ids = [cid for cid, _, _ in fill]
        for i in range(0, len(fill), 500):
            chunk = fill[i:i + 500]
            execute_values(
                cur,
                """
                UPDATE prospect_companies c
                   SET not_icp_reason = v.reason,
                       hubspot_seen = CASE WHEN v.has_seen
                                           THEN jsonb_set(c.hubspot_seen, '{not_icp_reason}', to_jsonb(v.reason))
                                           ELSE c.hubspot_seen END,
                       updated_at = NOW()
                  FROM (VALUES %s) AS v(id, reason, has_seen)
                 WHERE c.id = v.id AND NULLIF(c.not_icp_reason, '') IS NULL
                """,
                chunk,
                template="(%s::int, %s::text, %s::bool)",
                page_size=500,
            )
            execute_values(
                cur,
                """
                INSERT INTO prospect_company_events (company_id, actor, source, field, old_value, new_value)
                VALUES %s
                """,
                [(cid, None, SOURCE, "not_icp_reason", None, v) for cid, v, _ in chunk],
                page_size=500,
            )
        shield(cur, ids, stats)
        conn.commit()
        print(f"\nAplicado: {len(fill)} empresas. Blindaje: {dict(stats)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
