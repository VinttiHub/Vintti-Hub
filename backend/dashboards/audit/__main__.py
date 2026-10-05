"""Corrida en seco de la auditoria: imprime hallazgos, no escribe ni manda mail.

Es el modo con el que se calibra. Antes de automatizar nada hay que mirar los
hallazgos al lado del dashboard y decidir cuales son reales.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_BACKEND / ".env")

from dashboards.audit import rules as R  # noqa: E402
from dashboards.audit.runner import run, run_ledger  # noqa: E402

_COLOR = {"critical": "\033[91m", "high": "\033[93m", "medium": "\033[96m", "low": "\033[90m"}
_RESET = "\033[0m"


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m dashboards.audit")
    ap.add_argument("--tab", help="limitar a una pestana (sales, ops, am, growth-new, marketing)")
    ap.add_argument("--rule", action="append", help="correr solo estas reglas (rNN)")
    ap.add_argument("--local-html", action="store_true", help="usar docs/dashboard.html del repo")
    ap.add_argument("--quiet", action="store_true", help="sin barra de progreso")
    ap.add_argument("--ledger-only", action="store_true",
                    help="solo el libro de hechos (cruce entre cards), sin el resto")
    ap.add_argument("--months", type=int, help="meses hacia atras del libro de hechos")
    args = ap.parse_args()

    if args.local_html:
        os.environ["DASHBOARD_AUDIT_HTML"] = "local"

    def progress(i, total, ex):
        if args.quiet:
            return
        mark = "!" if ex.error else "."
        end = "\n" if i == total else ""
        print(f"\r  [{i}/{total}] {mark} {ex.chart_key[:48]:<48}", end=end, flush=True)

    if args.ledger_only:
        print("Libro de hechos...")
        findings, book, sin_etiqueta = run_ledger(months=args.months, progress=progress)
        print(f"\nMeses: {book['months'][0]} .. {book['months'][-1]} | "
              f"datasets en el libro: {len({k for k, _ in book['entries']})} | "
              f"hechos canonicos: {len(book['canon'])}")
        print(f"Detalles sin etiqueta (no cruzados todavia): {len(sin_etiqueta)}")
        for key in sin_etiqueta:
            print(f"  - {key}")
        _print_findings(findings)
        return 0

    print("Auditando dashboard...")
    findings, execs, topo = run(tab=args.tab, progress=progress)

    ok = sum(1 for e in execs.values() if not e.error)
    slow = sorted(execs.values(), key=lambda e: -e.elapsed_ms)[:3]
    print(f"\nHTML: {topo.source}")
    print(f"Nodos: {len(topo.nodes)} | datasets ejecutados: {len(execs)} ({ok} ok)")
    print("Mas lentos: " + ", ".join(f"{e.dataset_key or e.chart_key} {e.elapsed_ms}ms" for e in slow))

    if args.rule:
        keep = {r.lower() for r in args.rule}
        findings = [f for f in findings if f.rule in keep]

    _print_findings(findings)
    return 0


def _print_findings(findings) -> None:
    by_sev = {}
    for f in findings:
        by_sev.setdefault(f.severity, []).append(f)

    print("\n" + "=" * 78)
    head = " | ".join(f"{s}: {len(by_sev.get(s, []))}"
                      for s in ("critical", "high", "medium", "low"))
    print(f"HALLAZGOS  {head}")
    print("=" * 78)

    for sev in ("critical", "high", "medium", "low"):
        group = by_sev.get(sev) or []
        if not group:
            continue
        color = _COLOR.get(sev, "")
        print(f"\n{color}### {sev.upper()} ({len(group)}){_RESET}")
        for f in group:
            print(f"\n  [{f.rule}] {f.where or f.chart_key}")
            print(f"    {f.message}")
            if f.observed:
                print(f"    observado: {f.observed}")
            print(f"    dataset: {f.dataset_key or '?'} · docs/dashboard.html:{f.html_line}")

    if not findings:
        print("\n  Sin hallazgos.")


if __name__ == "__main__":
    raise SystemExit(main())
