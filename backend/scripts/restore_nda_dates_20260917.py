#!/usr/bin/env python3
"""Devuelve la NDA Signed original a las 5 Close Win que el sync pisó el 2026-09-17.

Qué pasó: el 16-sep a las 21:17 UTC un push de prueba del sync inverso movió 8 deals
a Closed Won en HubSpot. El 17-sep a las 14:48 se los volvió a NDA Signed para
deshacerlo, y a las 18:22 se los empujó otra vez a Closed Won. Al volver a entrar a
NDA Signed, HubSpot actualizó `hs_v2_date_entered_<nda signed>` al 17-sep (guarda la
ÚLTIMA entrada, no la primera), y el sync entrante copió esa fecha a
`nda_signature_or_start_date`. La protección de las opps cerradas (sólo rellenar NULL)
llegó el 18-sep, un día tarde.

La 780 (QoEPRO) también cayó, pero ya la corrigieron a mano, y es por eso que no está
acá. La fecha a restaurar es la PRIMERA entrada a NDA Signed en el historial de
`dealstage` de HubSpot, la que cargó el AE a mano (sourceType CRM_UI), verificada deal
por deal el 2026-09-23.

Ya no se repite: el push no retrocede stages (`decide_push_stage`) y, desde el
2026-09-23, el sync nunca atrasa una fecha del hub (gana la más temprana).

Uso:
    cd backend
    python scripts/restore_nda_dates_20260917.py            # dry-run: sólo el reporte
    python scripts/restore_nda_dates_20260917.py --apply    # escribe

Es idempotente: sólo toca las filas que siguen en 2026-09-17. Si alguien ya la
corrigió a mano, se saltea.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from db import get_connection  # noqa: E402

FECHA_PISADA = date(2026, 9, 17)

# opportunity_id -> (cuenta, deal de HubSpot, NDA Signed original)
RESTAURAR = {
    628: ("Seven Weeks Coffee", "60036762893", date(2026, 5, 14)),
    724: ("CM Products", "62475772196", date(2026, 7, 14)),
    752: ("Sunline Group", "63018486830", date(2026, 7, 31)),
    762: ("GrowthWise", "63156442517", date(2026, 8, 10)),
    768: ("Pep Talk", "63728740263", date(2026, 8, 14)),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="escribe en la base (sin esto es sólo el reporte)")
    args = parser.parse_args()

    conn = get_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT opportunity_id, opp_stage, nda_signature_or_start_date, hubspot_deal_id
                  FROM opportunity
                 WHERE opportunity_id = ANY(%s)
                 ORDER BY opportunity_id
                """,
                (list(RESTAURAR),),
            )
            filas = {r[0]: r for r in cur.fetchall()}

            pendientes = 0
            for opp_id, (cuenta, deal_id, original) in RESTAURAR.items():
                fila = filas.get(opp_id)
                if not fila:
                    print(f"#{opp_id} {cuenta}: NO EXISTE, se saltea")
                    continue
                _, stage, actual, deal_hub = fila
                if deal_hub != deal_id:
                    print(f"#{opp_id} {cuenta}: el deal atado es {deal_hub}, no {deal_id}; se saltea")
                    continue
                if actual != FECHA_PISADA:
                    print(f"#{opp_id} {cuenta}: ya está en {actual}, no se toca")
                    continue
                pendientes += 1
                print(f"#{opp_id} {cuenta} ({stage}): {actual} -> {original}")
                if args.apply:
                    cur.execute(
                        """
                        UPDATE opportunity
                           SET nda_signature_or_start_date = %s
                         WHERE opportunity_id = %s
                           AND nda_signature_or_start_date = %s
                        """,
                        (original, opp_id, FECHA_PISADA),
                    )
                    if cur.rowcount != 1:
                        raise RuntimeError(f"#{opp_id}: se esperaba 1 fila y se tocaron {cur.rowcount}")

            if not args.apply:
                conn.rollback()
                print(f"\nDry run: {pendientes} fila(s) por restaurar. Corré con --apply para escribir.")
            else:
                print(f"\nListo: {pendientes} fila(s) restaurada(s).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
