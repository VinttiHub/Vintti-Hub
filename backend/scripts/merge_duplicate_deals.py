#!/usr/bin/env python3
"""Fusiona los negocios de Prospecting que quedaron duplicados (2026-11-24).

La lógica vive en `prospecting/deal_merge.py` (desde 2026-11-27 también corre sola al final de
cada sync de negocios). Este script es para correrla a mano.

Uso:
    cd backend
    python scripts/merge_duplicate_deals.py            # en seco: lista los pares
    python scripts/merge_duplicate_deals.py --apply
    python scripts/merge_duplicate_deals.py --days 90  # cuánto mirar hacia atrás (default 60)

Es idempotente: un par ya fusionado no vuelve a aparecer.
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
from prospecting import deal_merge  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--days", type=int, default=60)
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    r = deal_merge.run(cur, args.days, apply=args.apply)
    print(f"{r['pares']} pares {'(se fusionan)' if args.apply else '(en seco)'}\n")
    for line in r["detalle"]:
        print(line)
    for e in r["errores"]:
        print("ERROR:", e)
    if args.apply:
        conn.commit()
        print(f"\n{r['fusionados']}/{r['pares']} fusionados.")
    else:
        conn.rollback()
        print("\nEn seco: no se escribió nada. Correr con --apply para fusionar.")
    conn.close()


if __name__ == "__main__":
    main()
