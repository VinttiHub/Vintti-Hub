"""Corrida en seco del reporte de comisiones AE: imprime, no manda ni guarda.

    python -m ae_commissions                    # mes vencido
    python -m ae_commissions --period 2026-08
    python -m ae_commissions --period 2026-08 --send   # manda el mail de verdad
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_BACKEND / ".env")

from ae_commissions import queries, report, service  # noqa: E402

_VIOLET = "\033[95m"
_CYAN = "\033[96m"
_MAGENTA = "\033[91m"
_DIM = "\033[90m"
_RESET = "\033[0m"


def _print_block(color, title, rows, cols, empty_text):
    print(f"\n{color}### {title} ({len(rows)}){_RESET}")
    if not rows:
        print(f"  {empty_text}")
        return
    widths = []
    for key, label, _align in cols:
        cells = [report._cell(r, key) for r in rows]
        widths.append(max(len(label), *(len(c) for c in cells)) if cells else len(label))
    header = "  " + " | ".join(l.ljust(w) for (_k, l, _a), w in zip(cols, widths))
    print(header)
    print(f"{_DIM}  " + "-+-".join("-" * w for w in widths) + _RESET)
    for r in rows:
        print("  " + " | ".join(report._cell(r, k).ljust(w)
                                for (k, _l, _a), w in zip(cols, widths)))


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m ae_commissions")
    ap.add_argument("--period", help="mes a reportar, YYYY-MM (default: mes vencido)")
    ap.add_argument("--send", action="store_true",
                    help="mandar el mail de verdad (por default NO manda)")
    ap.add_argument("--persist", action="store_true",
                    help="guardar la corrida en ae_commission_runs")
    args = ap.parse_args()

    mes_ini, mes_fin = queries.month_bounds(args.period)
    print(f"Comisiones AE · {report.period_label(mes_ini)} "
          f"({mes_ini} a {mes_fin})")

    if args.send or args.persist:
        artifact = service.execute(args.period, trigger_source="cli",
                                   send_email=args.send, persist=args.persist)
        payload = artifact
    else:
        from db import get_connection
        conn = get_connection()
        try:
            payload = service.collect(conn, mes_ini, mes_fin)
        finally:
            conn.close()

    _print_block(_VIOLET, "STAFFING", payload.get("staffing") or [],
                 report.COLS_STAFFING, "Sin cierres de Staffing en el mes.")
    _print_block(_CYAN, "RECRUITING", payload.get("recruiting") or [],
                 report.COLS_RECRUITING, "Sin cierres de Recruiting en el mes.")
    _print_block(_MAGENTA, "M3 - REPLACEMENTS", payload.get("m3") or [],
                 report.COLS_M3, "No M3 churn.")

    hecho = []
    if args.send:
        hecho.append("mail enviado a " + ", ".join(service.RECIPIENTS))
    if args.persist:
        hecho.append("corrida guardada en ae_commission_runs")
    print("\n" + (", ".join(hecho) if hecho
                  else f"{_DIM}(en seco: no se mando mail ni se guardo nada){_RESET}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
