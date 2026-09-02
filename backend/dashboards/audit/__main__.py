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
from dashboards.audit.runner import run  # noqa: E402

_COLOR = {"critical": "\033[91m", "high": "\033[93m", "medium": "\033[96m", "low": "\033[90m"}
_RESET = "\033[0m"


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m dashboards.audit")
    ap.add_argument("--tab", help="limitar a una pestana (sales, ops, am, growth-new, marketing)")
    ap.add_argument("--rule", action="append", help="correr solo estas reglas (rNN)")
    ap.add_argument("--local-html", action="store_true", help="usar docs/dashboard.html del repo")
    ap.add_argument("--quiet", action="store_true", help="sin barra de progreso")
    args = ap.parse_args()

    if args.local_html:
        os.environ["DASHBOARD_AUDIT_HTML"] = "local"

    def progress(i, total, ex):
        if args.quiet:
            return
        mark = "!" if ex.error else "."
        end = "\n" if i == total else ""
        print(f"\r  [{i}/{total}] {mark} {ex.chart_key[:48]:<48}", end=end, flush=True)

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
