#!/usr/bin/env python3
"""Limpieza puntual del 2026-09-18: 2 opportunities duplicadas.

Es el mismo problema que `dedupe_hubspot_opportunities.py` (ver ese archivo para
el detalle), pero estos dos casos no venían de la tanda del 11 al 14 de
septiembre y cada uno tiene su propia vuelta de tuerca:

  #828 KTB Services · Tax Specialist  ->  #672 KTB Services · Controller
      La creó el sync el 2026-09-16 desde el deal 60346828579, que en HubSpot
      seguía parado en NDA Signed mientras la búsqueda real ya estaba Closed
      Lost en el hub desde el 24 de agosto. El puesto NO coincide (Controller vs
      Tax Specialist) ni el modelo (Staffing vs Recruiting): lo que las empareja
      es la fecha de Deep Dive, idéntica al día (29-may), y la confirmación de
      la owner. Por eso va hardcodeado y no por heurística.

  #731 Precursive · Project Manager  ->  #732 Precursive · Project Manager
      Las dos las cargó la recruiter a mano en julio, así que NINGUNA tiene deal
      atado y no hay nada que mover entre filas. El deal de Precursive
      (62608738990) está suelto en HubSpot, abierto en Deep Dive. Se lo atamos a
      #732 —la fila real, Closed Lost— para que el cron no pueda crear una
      tercera el día que alguien toque ese deal.

Atar un deal a una opp cerrada NO la revive: `decide_stage_transition()` marca
`hub_stage_is_terminal` y el sync no le toca el stage. Es justamente lo que se
quiere acá, porque en los dos casos el hub tiene razón y HubSpot quedó atrasado.

Uso:
    cd backend
    python scripts/dedupe_opportunities_20260918.py            # dry-run
    python scripts/dedupe_opportunities_20260918.py --apply    # escribe

Es idempotente: un caso ya resuelto se saltea solo.
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

# (duplicada a borrar, opp que se queda, deal que tiene que terminar en la que se
# queda). Cuando la duplicada ya trae el deal, `deal` es None y se toma de ella.
CASOS = [
    # KTB Services: el deal viaja de la duplicada a la vieja.
    {"borrar": 828, "queda": 672, "deal": None,
     "nota": "KTB Services · Tax Specialist -> Controller (mismo Deep Dive 29-may)"},
    # Precursive: ninguna de las dos tiene deal; el de HubSpot está suelto.
    {"borrar": 731, "queda": 732, "deal": "62608738990",
     "nota": "Precursive · Project Manager duplicada; deal suelto -> #732"},
]


def tablas_hijas(cursor):
    """Toda tabla que apunte a una opportunity, preguntándoselo a la base.

    Igual que en `dedupe_hubspot_opportunities.py`: no hay NINGUNA foreign key
    contra `opportunity`, así que un DELETE con hijos no falla — deja filas
    huérfanas. La lista se descubre para que una tabla nueva no se escape.
    """
    cursor.execute(
        """
        SELECT table_name, column_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND column_name IN ('opportunity_id', 'source_opportunity_id',
                               'used_by_opportunity_id')
           AND table_name <> 'opportunity'
         ORDER BY table_name, column_name
        """
    )
    return [(r["table_name"], r["column_name"]) for r in cursor.fetchall()]


def hijos_de(cursor, hijas, opportunity_id):
    encontrados = []
    for tabla, columna in hijas:
        cursor.execute(
            f'SELECT count(*) AS n FROM "{tabla}" WHERE {columna} = %s',  # noqa: S608
            (opportunity_id,),
        )
        n = cursor.fetchone()["n"]
        if n:
            encontrados.append(f"{tabla}.{columna}={n}")
    return encontrados


def cargar(cursor, opportunity_id):
    cursor.execute(
        """
        SELECT o.opportunity_id, o.account_id, o.opp_stage, o.opp_position_name,
               o.opp_model, o.deep_dive_date, o.hubspot_deal_id,
               o.hubspot_pipeline_id, o.hubspot_dealstage_id, a.client_name
          FROM opportunity o
          LEFT JOIN account a ON a.account_id = o.account_id
         WHERE o.opportunity_id = %s
        """,
        (opportunity_id,),
    )
    return cursor.fetchone()


def resolver(cursor, caso, apply_changes, hijas):
    borrar_id, queda_id = caso["borrar"], caso["queda"]
    dupe = cargar(cursor, borrar_id)
    vieja = cargar(cursor, queda_id)

    if not dupe:
        return "ya resuelto", f"#{borrar_id} no existe (¿ya se borró?)"
    if not vieja:
        return "ERROR", f"#{queda_id} no existe"
    if dupe["account_id"] != vieja["account_id"]:
        return "ERROR", (f"#{borrar_id} y #{queda_id} no son de la misma cuenta "
                         f"({dupe['account_id']} vs {vieja['account_id']})")

    # El deal sale de la duplicada, salvo que el caso traiga uno suelto de HubSpot.
    deal = caso.get("deal") or str(dupe["hubspot_deal_id"] or "").strip()
    if not deal:
        return "ERROR", f"#{borrar_id} no tiene deal y el caso no declara uno suelto"
    ya = str(vieja["hubspot_deal_id"] or "").strip()
    if ya and ya != deal:
        return "ERROR", f"#{queda_id} ya está atada a otro deal ({ya})"

    huerfanos = hijos_de(cursor, hijas, borrar_id)
    if huerfanos:
        return "NO SE BORRA", (f"#{borrar_id} tiene hijos y borrarla los dejaría "
                               f"huérfanos: " + ", ".join(huerfanos))

    detalle = (f"deal {deal}: #{borrar_id} ({dupe['opp_position_name']} · "
               f"{dupe['opp_stage']}) -> #{queda_id} ({vieja['opp_position_name']} · "
               f"{vieja['opp_stage']}), Deep Dive {dupe['deep_dive_date']} vs "
               f"{vieja['deep_dive_date']}")
    if not apply_changes:
        return "se haría", detalle

    # 1) soltar el deal de la duplicada. El índice único parcial sobre
    #    hubspot_deal_id no tolera las dos filas con el mismo deal ni un instante.
    cursor.execute(
        """
        UPDATE opportunity
           SET hubspot_deal_id = NULL, hubspot_pipeline_id = NULL,
               hubspot_dealstage_id = NULL
         WHERE opportunity_id = %s
        """,
        (borrar_id,),
    )
    # 2) atarlo a la que se queda. Misma guarda que /link-deal contra una corrida
    #    del sync que llegue en el medio.
    cursor.execute(
        """
        UPDATE opportunity
           SET hubspot_deal_id = %s,
               hubspot_pipeline_id = COALESCE(%s, hubspot_pipeline_id),
               hubspot_dealstage_id = COALESCE(%s, hubspot_dealstage_id),
               hubspot_synced_at = NOW()
         WHERE opportunity_id = %s
           AND NULLIF(hubspot_deal_id, '') IS NULL
        """,
        (deal, dupe["hubspot_pipeline_id"], dupe["hubspot_dealstage_id"], queda_id),
    )
    if cursor.rowcount == 0:
        raise RuntimeError(f"no se pudo atar el deal {deal} a #{queda_id}")
    # 3) recién ahora se borra.
    cursor.execute("DELETE FROM opportunity WHERE opportunity_id = %s", (borrar_id,))
    # 4) el deal ya está decidido: fuera de la cola y de las decisiones guardadas.
    for tabla in ("hubspot_deals_waiting", "hubspot_deal_decisions"):
        cursor.execute("SELECT to_regclass(%s) AS t", (f"public.{tabla}",))
        if (cursor.fetchone() or {}).get("t"):
            cursor.execute(f"DELETE FROM {tabla} WHERE deal_id = %s", (deal,))  # noqa: S608
    return "hecho", detalle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="escribe de verdad (sin esto sólo reporta)")
    args = parser.parse_args()

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            hijas = tablas_hijas(cursor)
            print(f"{'APLICANDO' if args.apply else 'DRY-RUN'} · "
                  f"{len(CASOS)} casos · {len(hijas)} tablas hijas conocidas\n")
            fallos = 0
            for caso in CASOS:
                estado, detalle = resolver(cursor, caso, args.apply, hijas)
                print(f"  [{estado:11}] {caso['nota']}")
                print(f"                {detalle}")
                if estado.startswith(("ERROR", "NO SE BORRA")):
                    fallos += 1
        if args.apply and not fallos:
            conn.commit()
            print("\nCommit hecho.")
        elif args.apply:
            conn.rollback()
            print("\nHubo errores: ROLLBACK, no se escribió nada.")
        else:
            conn.rollback()
        return 1 if fallos else 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
