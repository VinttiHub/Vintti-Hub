#!/usr/bin/env python3
"""Devuelve los días del 24 y 31-dic-2026 a quien ya tenía aprobadas vacaciones que los cruzan.

Desde el 2026-11-25 esos dos días son libres para todo Vintti y no se descuentan
(`VINTTI_COMPANY_DAYS_OFF` en profile_routes.py). Los pedidos pendientes ya se cuentan bien
al aprobarse, y el uso recalculado también. Lo que queda mal es el contador
`users.vacaciones_consumidas` de los pedidos que se aprobaron ANTES: al aprobar se le sumó el
total del cálculo viejo, y el perfil muestra max(contador, recalculado), así que seguirían
apareciendo los días de más (ej.: 21→31-dic sumó 8 y ahora son 6).

Este script resta la diferencia (viejo − nuevo) de cada pedido aprobado, sin bajar de 0.

Uso:
    cd backend
    python scripts/fix_company_days_off_2026.py            # dry-run: sólo el reporte
    python scripts/fix_company_days_off_2026.py --apply    # escribe

Idempotente: cada pedido corregido queda en `company_days_off_fixes` y no se vuelve a restar.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from psycopg2.extras import RealDictCursor  # noqa: E402

from db import get_connection  # noqa: E402
from profile_routes import (  # noqa: E402
    VINTTI_COMPANY_DAYS_OFF,
    _parse_timeoff_reason_meta,
    _timeoff_total_days,
    us_federal_holidays_observed_for_year,
)

FIRST = min(VINTTI_COMPANY_DAYS_OFF)
LAST = max(VINTTI_COMPANY_DAYS_OFF)


def old_total(sd, ed, is_half_day):
    """Cálculo de antes del cambio: lun-vie menos feriados de EE.UU., sin días libres de Vintti."""
    hols = set()
    for y in range(sd.year, ed.year + 1):
        hols |= us_federal_holidays_observed_for_year(y)
    n, cur = 0, sd
    while cur <= ed:
        if cur.weekday() < 5 and cur not in hols:
            n += 1
        cur += timedelta(days=1)
    if is_half_day and sd == ed and n >= 1:
        return 0.5
    return float(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS company_days_off_fixes (
                    request_id BIGINT PRIMARY KEY,
                    user_id    BIGINT NOT NULL,
                    days_back  NUMERIC NOT NULL,
                    fixed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                SELECT r.id, r.user_id, u.user_name, r.start_date, r.end_date, r.reason,
                       COALESCE(u.vacaciones_consumidas, 0) AS consumidas
                  FROM time_off_requests r
                  JOIN users u ON u.user_id = r.user_id
                 WHERE LOWER(r.kind) = 'vacation'
                   AND LOWER(r.status) = 'approved'
                   AND r.end_date >= %s AND r.start_date <= %s
                   AND NOT EXISTS (SELECT 1 FROM company_days_off_fixes f WHERE f.request_id = r.id)
                 ORDER BY u.user_name, r.start_date
            """, (FIRST, LAST))
            rows = cur.fetchall()

            todo = []
            for r in rows:
                _, half = _parse_timeoff_reason_meta(r["reason"])
                before = old_total(r["start_date"], r["end_date"], half)
                after = _timeoff_total_days("vacation", r["start_date"], r["end_date"], is_half_day=half)
                diff = before - after
                if diff > 0:
                    todo.append((r, before, after, diff))

            if not todo:
                print("No hay pedidos aprobados para corregir.")
                return

            print(f"{'Persona':<28} {'Pedido':>7}  {'Fechas':<23} {'Antes':>5} {'Ahora':>5} {'Devuelve':>8}")
            for r, before, after, diff in todo:
                print(f"{(r['user_name'] or '')[:28]:<28} {r['id']:>7}  "
                      f"{r['start_date']} → {r['end_date']} {before:>5g} {after:>5g} {diff:>8g}")

            if not args.apply:
                print("\nDry-run: no se escribió nada. Correr con --apply para aplicar.")
                conn.rollback()
                return

            for r, _, _, diff in todo:
                cur.execute("""
                    UPDATE users
                       SET vacaciones_consumidas = GREATEST(0, COALESCE(vacaciones_consumidas, 0) - %s),
                           updated_at = NOW() AT TIME ZONE 'UTC'
                     WHERE user_id = %s
                """, (diff, r["user_id"]))
                cur.execute(
                    "INSERT INTO company_days_off_fixes (request_id, user_id, days_back) VALUES (%s, %s, %s)",
                    (r["id"], r["user_id"], diff),
                )
            print(f"\nAplicado: {len(todo)} pedido(s) corregido(s).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
