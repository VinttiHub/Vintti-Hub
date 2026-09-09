"""Corrida en seco del digest diario: imprime, no postea ni guarda.

    python -m daily_digest                  # en seco, texto plano
    python -m daily_digest --rule jd        # una sola regla (para calibrar)
    python -m daily_digest --json           # el Block Kit, para pegarlo en
                                            # app.slack.com/block-kit-builder
    python -m daily_digest --post           # postea DE VERDAD al canal del .env
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_BACKEND / ".env")

from daily_digest import people, render, service  # noqa: E402
from utils import slack as slack_api  # noqa: E402

_DIM = "\033[90m"
_VIOLET = "\033[95m"
_RESET = "\033[0m"


_VERDE = "\033[92m"
_ROJO = "\033[91m"


def _check() -> int:
    """Verifica el setup de Slack contra la API, no contra el .env."""
    d = slack_api.diagnose()
    for paso in d["pasos"]:
        if paso.get("aviso"):
            marca = f"{_DIM}--  {_RESET}"
        elif paso["ok"]:
            marca = f"{_VERDE}OK  {_RESET}"
        else:
            marca = f"{_ROJO}FALTA{_RESET}"
        print(f"  {marca} {paso['paso']}" + (f" - {paso['detalle']}" if paso["detalle"] else ""))

    faltan = [p for p in d["pasos"] if not p["ok"]]
    ids = len(people.SLACK_MEMBER_IDS)
    print(f"\n  {'OK  ' if ids else '    '} Member IDs en people.py: {ids}"
          + ("" if ids else "  (sin esto se ven los nombres pero no notifica)"))
    if faltan:
        print(f"\n{_ROJO}Falta resolver {len(faltan)} paso(s).{_RESET}")
        return 1
    print(f"\n{_VERDE}Slack listo.{_RESET} Probalo con: python3 -m daily_digest --post")
    return 0


def _members() -> int:
    """Imprime el bloque listo para pegar en daily_digest/people.py."""
    r = slack_api.list_members()
    if not r["ok"]:
        print(f"{_ROJO}No se pudo leer el directorio: {r['error']}{_RESET}")
        print("Si dice 'missing_scope', agregale a la app los scopes "
              "users:read y users:read.email y reinstalala.")
        return 1
    print(f"{len(r['members'])} personas con mail @vintti.com.\n"
          "Pegar dentro de SLACK_MEMBER_IDS en daily_digest/people.py:\n")
    for mail, mid in r["members"].items():
        print(f'    "{mail}": "{mid}",')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m daily_digest")
    ap.add_argument("--rule", choices=sorted(service.queries.RULES),
                    help="correr una sola regla")
    ap.add_argument("--json", action="store_true",
                    help="imprimir el Block Kit en vez del texto")
    ap.add_argument("--post", action="store_true",
                    help="postear de verdad a Slack (por default NO postea)")
    ap.add_argument("--persist", action="store_true",
                    help="guardar la corrida en daily_digest_runs")
    ap.add_argument("--check", action="store_true",
                    help="verificar la configuracion de Slack y salir")
    ap.add_argument("--members", action="store_true",
                    help="cosechar los member IDs para pegar en people.py")
    args = ap.parse_args()

    if args.check:
        return _check()
    if args.members:
        return _members()

    payload = service.execute(trigger_source="cli", post=args.post,
                              persist=args.persist, solo_regla=args.rule)

    if args.json:
        print(json.dumps(payload["blocks"], indent=2, ensure_ascii=False))
    else:
        print(render.to_text(payload["findings"], fallos=payload["fallos"]))

    print(f"\n{_VIOLET}Por regla{_RESET}: " + ", ".join(
        f"{k}={'CAIDA' if v < 0 else v}" for k, v in payload["por_regla"].items()))
    print(f"Total {payload['total']} en {payload['people_total']} personas"
          + (f", {payload['huerfanos']} sin duenio activo" if payload["huerfanos"] else ""))

    transporte = slack_api.configured()
    print(f"Slack: {transporte or 'SIN CONFIGURAR'}"
          f" - member IDs cargados: {len(people.SLACK_MEMBER_IDS)}")
    sin_id = sorted({f["owner_email"] for f in payload["findings"]
                     if f.get("owner_active") and not people.slack_id(f["owner_email"])})
    if sin_id:
        print(f"  sin member ID: {', '.join(sin_id)}")
    print(f"Payload Slack: {slack_api.payload_size(payload['blocks'])} bytes, "
          f"{len(payload['blocks'])} bloques (techo: 40000 / 50)")

    if not args.post:
        print(f"{_DIM}(en seco: no se posteo nada){_RESET}")
    elif payload["slack"].get("sent"):
        print(f"posteado a Slack via {payload['slack']['transport']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
