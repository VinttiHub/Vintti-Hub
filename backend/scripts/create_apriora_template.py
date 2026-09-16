#!/usr/bin/env python3
"""Crea en Apriora el interview guide template con las 6 preguntas obligatorias.

Por qué existe: el Hub venía mandando esas preguntas en `additionalQuestions` de
`createJob`, y la doc de Apriora llama a ese campo "optional free-text questions
to append to the generated interview" — literalmente sugerencias. En las 31
positions que creó el Hub se ve el resultado: Apriora las reescribe ("Are you
participating in other processes?" salió como "Are you currently participating in
other hiring processes?"), las intercala aunque se mande
`intelligentlyOrderQuestions=false`, y en la opp 792 directamente dropeó la de la
computadora propia — las 10 entrevistas de esa búsqueda quedaron sin preguntarla.

En un template las preguntas son parte del guion, aceptan instrucciones por
pregunta, y los tags los nombramos nosotros (hoy Apriora se los inventa en cada
entrevista: la misma pregunta salía como "Planned Absences", "Planned Time Off" y
"Planned Vacations", así que no servían para verificar nada).

El contenido sale de `utils/alex.py::build_template_payload()`, que es la misma
definición que usa el fallback por `additionalQuestions` y la verificación
posterior — una sola fuente de verdad.

Uso:
    cd backend
    python scripts/create_apriora_template.py             # dry-run: imprime el payload
    python scripts/create_apriora_template.py --apply     # lo crea
    python scripts/create_apriora_template.py --name "..."  # nombre alternativo

Después de crearlo hay que pegar el id en la env `APRIORA_TEMPLATE_ID`, en
`backend/.env` **y en App Runner**. Sin esa env el Hub sigue con el camino viejo.

OJO: `/templates` sólo tiene GET y POST. No se puede editar ni borrar un template,
ni reusar un nombre. Cambiar una pregunta = correr esto de nuevo con `--name`
distinto y repuntar la env al id nuevo.
"""
from __future__ import annotations

import argparse
import json
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

from utils.alex import (  # noqa: E402
    APRIORA_TEMPLATE_NAME,
    AlexClient,
    AlexError,
    build_template_payload,
)


def _extract_template_id(created):
    """Id del template en la respuesta de Apriora.

    Viene de formas distintas según el endpoint: a veces `{"id": ...}`, a veces
    envuelto en `payload`, y el `payload` puede ser **el id pelado como string**
    (que es lo que rompió la primera corrida con un `'str' object has no attribute
    'get'`). Se prueban todas y si ninguna encaja, None — el template igual quedó
    creado y el id se saca de `GET /templates`."""
    if isinstance(created, str):
        return created
    if not isinstance(created, dict):
        return None
    payload = created.get("payload")
    if isinstance(payload, dict):
        payload = payload.get("id") or payload.get("templateId")
    if not isinstance(payload, str):
        payload = None
    return created.get("id") or created.get("templateId") or payload


def _print_env_hint(template_id):
    print("=" * 72)
    print(f"  TEMPLATE: {template_id}")
    print()
    print("  Pegá esto en backend/.env Y en las env vars de App Runner:")
    print(f"      APRIORA_TEMPLATE_ID={template_id}")
    print()
    print("  Hasta que la env esté seteada en App Runner, el Hub sigue creando las")
    print("  entrevistas por el camino viejo (additionalQuestions).")
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="crear de verdad (default: dry-run)")
    parser.add_argument("--name", default=None, help=f"nombre del template (default: {APRIORA_TEMPLATE_NAME!r})")
    args = parser.parse_args()

    payload = build_template_payload(args.name)
    name = payload["name"]

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print()
    print(f"  {len(payload['questions'])} preguntas obligatorias")
    print(f"  {len(payload['criteria'])} criterio(s) de evaluación: "
          + ", ".join(c["name"] for c in payload["criteria"]))
    print(f"  {len(payload['tags'])} tags")
    print("  questionLimit: sin setear (Apriora sigue generando las preguntas del rol)")
    print()

    try:
        client = AlexClient()
    except AlexError as e:
        print(f"[ERROR] {e}. Seteá ALEX_API_KEY en backend/.env.")
        return 1

    existing = client.list_templates()
    print(f"Templates que ya existen en Apriora ({len(existing)}):")
    for t in existing:
        print(f"  - {t.get('id')}  {t.get('name')!r}")
    already = next((t for t in existing if (t.get("name") or "").strip() == name), None)
    if already:
        # Idempotente a propósito: el nombre es único y no se puede renombrar ni
        # borrar, así que lo útil acá no es un error sino decirte cuál es el id.
        print()
        print(f"Ya existe un template llamado {name!r}, no se crea otro.")
        print()
        _print_env_hint(already.get("id"))
        print()
        print("Si querés uno distinto (p. ej. cambiaste una pregunta), corré con --name <otro>.")
        return 0
    print()

    if not args.apply:
        print("DRY-RUN: no se creó nada. Repetí con --apply para crearlo.")
        return 0

    created = client.create_template(payload)
    print("Respuesta de Apriora:")
    print(json.dumps(created, ensure_ascii=False, indent=2))
    print()

    template_id = _extract_template_id(created)
    if not template_id:
        # El POST salió bien, así que el template EXISTE aunque no se pueda leer el
        # id de la respuesta. Volver a correr el script no crea un duplicado.
        match = next((t for t in client.list_templates()
                      if (t.get("name") or "").strip() == name), None)
        template_id = match.get("id") if match else None
    if not template_id:
        print("[AVISO] El template se creó pero no se pudo resolver el id.")
        print("        Sacalo de: GET https://api.alex.com/v1/api/templates")
        return 1

    _print_env_hint(template_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
