#!/usr/bin/env python3
"""Saca la foto del Model de HubSpot en las opps atadas que nunca la tuvieron.

`opportunity.hubspot_model_seen` guarda el último Model visto en HubSpot, y
`_apply_model_from_hubspot()` (routes/hubspot_routes.py) decide con él: si la foto
coincide con HubSpot gana el hub; si está en NULL la opp se considera "recién
vinculada" y gana HubSpot.

El 2026-09-23 esa regla se deployó unas horas después de crear la columna, asumiendo
que para entonces todas las opps atadas ya tenían foto. No: el sync es incremental y
sólo mira un deal cuando alguien lo toca en HubSpot, así que las opps que nadie movió
en esas horas quedaron en NULL. El 24-sep founderfirst (825) y Summit Chase (808) se
movieron de stage en HubSpot, el sync las vio "por primera vez" y pisó el Recruiting
que la recruiter había corregido a mano con el Staffing de HubSpot.

Este script cierra ese agujero: escribe SÓLO `hubspot_model_seen` con el Model actual
del deal. Nunca toca `opp_model`, así que las diferencias que haya quedan resueltas a
favor del hub (que es lo que la regla ya hacía con las opps que sí tenían foto).

Uso:
    cd backend
    python scripts/backfill_hubspot_model_seen.py            # dry-run: sólo el reporte
    python scripts/backfill_hubspot_model_seen.py --apply    # escribe

Es idempotente: sólo mira las opps con la foto en NULL.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")
except Exception:
    pass

from psycopg2.extras import RealDictCursor  # noqa: E402

from db import get_connection  # noqa: E402
from utils.hubspot import HubSpotClient  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="escribe (default: dry-run)")
    args = parser.parse_args()

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT opportunity_id, opp_model, opp_stage, hubspot_deal_id
                  FROM opportunity
                 WHERE NULLIF(hubspot_deal_id, '') IS NOT NULL
                   AND hubspot_model_seen IS NULL
                 ORDER BY opportunity_id
                """
            )
            rows = cursor.fetchall()

        if not rows:
            print("No hay opps atadas sin foto. Nada que hacer.")
            return

        client = HubSpotClient()
        pendientes = []
        for row in rows:
            try:
                deal = client.get_deal_with_associations(
                    row["hubspot_deal_id"], extra_properties=["model"]
                )
                model = ((deal.get("properties") or {}).get("model") or "").strip()
            except Exception as exc:
                print(f"#{row['opportunity_id']}  ERROR leyendo el deal "
                      f"{row['hubspot_deal_id']}: {str(exc)[:120]}")
                continue
            hub = (row["opp_model"] or "").strip()
            if not model:
                print(f"#{row['opportunity_id']}  deal sin Model en HubSpot: se saltea")
                continue
            marca = "" if hub.lower() == model.lower() else "   <-- distinto, gana el hub"
            print(f"#{row['opportunity_id']:<5} {row['opp_stage'] or '':<13} "
                  f"hub={hub or '-':<11} hubspot={model:<11}{marca}")
            pendientes.append((model, row["opportunity_id"]))

        if not args.apply:
            print(f"\nDry-run: se escribiría la foto en {len(pendientes)} opps. "
                  "Correr con --apply para escribir.")
            return

        with conn:
            with conn.cursor() as cursor:
                for model, opportunity_id in pendientes:
                    cursor.execute(
                        """
                        UPDATE opportunity SET hubspot_model_seen = %s
                         WHERE opportunity_id = %s AND hubspot_model_seen IS NULL
                           AND NULLIF(hubspot_deal_id, '') IS NOT NULL
                        """,
                        (model, opportunity_id),
                    )
        print(f"\nFoto escrita en {len(pendientes)} opps.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
