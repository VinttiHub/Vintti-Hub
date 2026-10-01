#!/usr/bin/env python3
"""Devuelve la start date (NDA firmado) a las 11 opps que la perdieron al pasar por Stop.

Qué pasó: desde feb-2026, mover una opp a Stop en Opportunities hacía
`patchOppFields(id, { nda_signature_or_start_date: null })` (main.js,
`dispatchStageChange`). Al reactivarla se pedía una fecha nueva y la original se perdía
para siempre. Se notó el 2026-10-01, cuando NDA → Close Win (Operations) empezó a
excluir las opps sin start date y se cayeron 582, 623, 624 y 712.

El valor que se tipeó en el popup no quedó guardado en ningún lado. La fecha a restaurar
es el día (hora Argentina) del PRIMER click en "Save" del popup de Sourcing: en `tracks`
queda `opp-stage-<id>` seguido de `saveSourcingDate` en el mismo segundo. Puede diferir
unos días de la tipeada; es la mejor evidencia que hay y la owner eligió usarla.

Ya no se repite: desde el 2026-10-01 Stop no borra la fecha.

Uso:
    cd backend
    python scripts/restore_nda_dates_stop_20261001.py            # dry-run: sólo el reporte
    python scripts/restore_nda_dates_stop_20261001.py --apply    # escribe

Es idempotente: sólo toca las filas que siguen sin fecha (NULL o ''). Si alguien ya la
cargó a mano, se saltea.
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

# opportunity_id -> (cuenta, primer saveSourcingDate en tracks, hora ARG)
RESTAURAR = {
    503: ("Eventpack", date(2026, 2, 23)),
    495: ("Sightline CFO", date(2026, 3, 2)),
    569: ("Greaton AI", date(2026, 3, 18)),
    582: ("The Email Marketers", date(2026, 4, 1)),
    612: ("Theta", date(2026, 4, 23)),
    623: ("Bearing Line LLC", date(2026, 4, 30)),
    624: ("Bearing Line LLC", date(2026, 4, 30)),
    643: ("Guerreros de Ley", date(2026, 6, 1)),
    712: ("Heavys", date(2026, 7, 8)),
    797: ("Hometeam", date(2026, 9, 4)),
    790: ("Papaya Tutor", date(2026, 9, 15)),
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
                SELECT opportunity_id, opp_stage,
                       NULLIF(nda_signature_or_start_date::text, '') AS actual
                  FROM opportunity
                 WHERE opportunity_id = ANY(%s)
                 ORDER BY opportunity_id
                """,
                (list(RESTAURAR),),
            )
            filas = {r[0]: r for r in cur.fetchall()}

            pendientes = 0
            for opp_id, (cuenta, original) in RESTAURAR.items():
                fila = filas.get(opp_id)
                if not fila:
                    print(f"#{opp_id} {cuenta}: NO EXISTE, se saltea")
                    continue
                _, stage, actual = fila
                if actual is not None:
                    print(f"#{opp_id} {cuenta}: ya tiene fecha ({actual}), no se toca")
                    continue
                pendientes += 1
                print(f"#{opp_id} {cuenta} ({stage}): vacía -> {original}")
                if args.apply:
                    cur.execute(
                        """
                        UPDATE opportunity
                           SET nda_signature_or_start_date = %s
                         WHERE opportunity_id = %s
                           AND NULLIF(nda_signature_or_start_date::text, '') IS NULL
                        """,
                        (original, opp_id),
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
