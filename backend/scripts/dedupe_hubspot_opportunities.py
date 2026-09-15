#!/usr/bin/env python3
"""Limpieza única de las opportunities que el sync de HubSpot duplicó.

Entre el 2026-09-11 y el 2026-09-14 el sync creó 9 opportunities sobre búsquedas
que YA existían en el hub. No fue un problema de nombres parecidos: en la mayoría
el puesto coincidía letra por letra. La gemela estaba en `Closed Lost`, y la
exclusión de los stages cerrados estaba escrita dos veces — en la adopción
automática y otra vez en la lista de candidatas del freno. Cuando la cerrada era
la única opp de la cuenta, esa lista volvía vacía, el freno la leía como "no hay
nada que consultar" y el sync creaba en silencio, sin mail y sin panel.

Eso ya está arreglado en `routes/hubspot_routes.py` (las cerradas entran a la
lista y `/link-deal` las acepta). Este script limpia lo que quedó.

Por cada par, en este orden:

  1. desata el deal de la duplicada,
  2. se lo ata a la opp vieja,
  3. borra la duplicada.

El orden lo exige el índice único parcial `idx_opportunity_hubspot_deal_id`: dos
filas no pueden llevar el mismo deal ni por un instante.

**Borrar sin atar no alcanza.** Si la duplicada desaparece y el deal queda suelto,
el cron la vuelve a crear a los 30 minutos.

Los pares van hardcodeados y verificados a mano contra la base. No se derivan por
heurística a propósito: un puesto repetido en la misma cuenta puede ser un deal
genuinamente nuevo (Criterium-Dudka tiene dos "Admin Assistant / Bookkeeper"), y
tragarlo dentro de la opp vieja borra una contratación del funnel.

Uso:
    cd backend
    python scripts/dedupe_hubspot_opportunities.py            # dry-run: sólo el reporte
    python scripts/dedupe_hubspot_opportunities.py --apply    # escribe

Es idempotente: un par ya resuelto se saltea solo.
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

# (duplicada creada por el sync, opp vieja que ya estaba en el hub)
# Verificados el 2026-09-14: en los 9 casos la fecha de Deep Dive coincide o
# difiere en menos de 5 días, y en 6 de 9 el puesto es el mismo.
PARES = [
    (806, 761),  # Arcady Media · Content Strategist / Director of Lifecycle Marketing
    (807, 788),  # PQ Meats · Administrative Assistant / Bookkeeper Jr
    (813, 777),  # The Art of Broth · Operations Analyst
    (814, 627),  # Flamingo · Account Executive
    (815, 737),  # Catchy · Paid Media Specialist / Part-Time Paid Media Specialist
    (817, 704),  # Rodgers Law Office · Legal Assistant
    (819, 582),  # The Email Marketers · Sr / Senior Email Strategist
    (821, 634),  # Dolsten & Co · Project Manager
    (825, 650),  # Advisant Financial · Tax Specialist / Part Time Senior Tax Professional
]


def tablas_hijas(cursor):
    """Toda tabla que apunte a una opportunity, preguntándoselo a la base.

    No hay NINGUNA foreign key contra `opportunity` en la base: un DELETE sobre
    una opp con hijos no falla, deja filas huérfanas que después no encuentra
    nadie. Por eso la lista se descubre en vez de hardcodearse — si mañana
    aparece una tabla nueva, este chequeo la ve sola.
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
    """Cuántas filas quedarían huérfanas si se borrara esta opp."""
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
               o.deep_dive_date, o.hubspot_deal_id, o.hubspot_pipeline_id,
               o.hubspot_dealstage_id, a.client_name
          FROM opportunity o
          LEFT JOIN account a ON a.account_id = o.account_id
         WHERE o.opportunity_id = %s
        """,
        (opportunity_id,),
    )
    return cursor.fetchone()


def resolver_par(cursor, nueva_id, vieja_id, apply_changes, hijas):
    nueva = cargar(cursor, nueva_id)
    vieja = cargar(cursor, vieja_id)

    if not nueva:
        return "ya resuelto", f"#{nueva_id} no existe (¿ya se borró?)"
    if not vieja:
        return "ERROR", f"#{vieja_id} no existe"
    if nueva["account_id"] != vieja["account_id"]:
        return "ERROR", (
            f"#{nueva_id} y #{vieja_id} no son de la misma cuenta "
            f"({nueva['account_id']} vs {vieja['account_id']})"
        )

    deal = str(nueva["hubspot_deal_id"] or "").strip()
    if not deal:
        return "ERROR", f"#{nueva_id} no tiene deal atado; no se puede mover a #{vieja_id}"
    ya = str(vieja["hubspot_deal_id"] or "").strip()
    if ya and ya != deal:
        return "ERROR", f"#{vieja_id} ya está atada a otro deal ({ya})"

    huerfanos = hijos_de(cursor, hijas, nueva_id)
    if huerfanos:
        return "NO SE BORRA", (
            f"#{nueva_id} tiene hijos y borrarla los dejaría huérfanos: "
            + ", ".join(huerfanos)
        )

    detalle = (
        f"deal {deal}: #{nueva_id} ({nueva['opp_position_name']} · {nueva['opp_stage']}) "
        f"-> #{vieja_id} ({vieja['opp_position_name']} · {vieja['opp_stage']}), "
        f"Deep Dive {nueva['deep_dive_date']} vs {vieja['deep_dive_date']}"
    )
    if not apply_changes:
        return "se haría", detalle

    # 1) soltar el deal de la duplicada. El índice único parcial sobre
    #    hubspot_deal_id no tolera las dos filas con el mismo deal ni un instante.
    cursor.execute(
        """
        UPDATE opportunity
           SET hubspot_deal_id = NULL,
               hubspot_pipeline_id = NULL,
               hubspot_dealstage_id = NULL
         WHERE opportunity_id = %s
        """,
        (nueva_id,),
    )
    # 2) atarlo a la vieja. Misma guarda que /link-deal contra una corrida del
    #    sync que llegue en el medio.
    cursor.execute(
        """
        UPDATE opportunity
           SET hubspot_deal_id = %s,
               hubspot_pipeline_id = %s,
               hubspot_dealstage_id = %s,
               hubspot_synced_at = NOW()
         WHERE opportunity_id = %s
           AND NULLIF(hubspot_deal_id, '') IS NULL
        """,
        (deal, nueva["hubspot_pipeline_id"], nueva["hubspot_dealstage_id"], vieja_id),
    )
    if cursor.rowcount == 0:
        raise RuntimeError(f"no se pudo atar el deal {deal} a #{vieja_id}")
    # 3) recién ahora se borra.
    cursor.execute("DELETE FROM opportunity WHERE opportunity_id = %s", (nueva_id,))
    # 4) el deal ya está decidido: fuera de la cola y de las decisiones guardadas.
    for tabla in ("hubspot_deals_waiting", "hubspot_deal_decisions"):
        cursor.execute("SELECT to_regclass(%s) AS t", (f"public.{tabla}",))
        if (cursor.fetchone() or {}).get("t"):
            cursor.execute(f"DELETE FROM {tabla} WHERE deal_id = %s", (deal,))  # noqa: S608
    return "hecho", detalle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="escribe en la base (por defecto, dry-run)")
    args = parser.parse_args()

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            hijas = tablas_hijas(cursor)
        print(f"Tablas que apuntan a una opportunity: {len(hijas)}")
        print("  " + ", ".join(f"{t}.{c}" for t, c in hijas))
        print()

        resumen = {}
        for nueva_id, vieja_id in PARES:
            # Cada par en su propia transacción: sin esto un fallo en el par 5
            # revierte los 4 anteriores y el COMMIT final actúa como ROLLBACK.
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    estado, detalle = resolver_par(
                        cursor, nueva_id, vieja_id, args.apply, hijas
                    )
                conn.commit() if args.apply else conn.rollback()
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                estado, detalle = "ERROR", str(exc)
            resumen[estado] = resumen.get(estado, 0) + 1
            print(f"[{estado:>12}] {detalle}")

        print()
        print(" · ".join(f"{k}: {v}" for k, v in sorted(resumen.items())))
        if not args.apply:
            print("\nDRY-RUN: no se escribió nada. "
                  "Revisá los pares uno por uno y corré con --apply.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
