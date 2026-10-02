"""Simula a Clay: manda empresas al webhook con la forma exacta del payload.

Sirve para probar el mapeo antes de configurar la columna "HTTP API" en Clay.
Las empresas que manda son dummy (nombre con "(sim)", dominio .example.com) y el
clay_record_id es fijo, así que correrlo dos veces ACTUALIZA en vez de duplicar:
es justamente la prueba de que un re-envío no pisa lo que cargó un BDR.

    cd backend
    python scripts/clay_webhook_simulator.py                       # imprime los payloads
    python scripts/clay_webhook_simulator.py --send                # contra http://localhost:5000
    python scripts/clay_webhook_simulator.py --send --base https://7m6mw95m8y.us-east-2.awsapprunner.com

Lee CLAY_WEBHOOK_TOKEN de backend/.env.

Ojo: el webhook las crea con is_dummy = FALSE (Clay no manda esa marca), así que
después de probar se borran a mano desde el panel o con el filtro "(sim)".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

SAMPLE = [
    {
        "clay_record_id": "sim-0001",
        "company_name": "Qodo (sim)",
        "website": "https://www.qodo-sim.example.com",
        "linkedin_url": "https://www.linkedin.com/company/qodo-sim",
        "description": "AI code integrity platform.",
        "industry": "Software Development",
        "keywords": "ai, code review, testing",
        "technologies": "AWS, React, Python",
        "job_types": "Software Engineer, Customer Success",
        "open_jobs": 3,
        "founded_year": 2022,
        "size": "51-200",
        "city": "New York",
        "state": "NY",
        "country": "United States",
        "lead_source": "Clay",
        "semana": "Semana 40",
    },
    {
        "clay_record_id": "sim-0002",
        "company_name": "Arango Bookkeeping (sim)",
        "website": "arango-sim.example.com",
        "industry": "Accounting",
        "job_types": "Bookkeeper",
        "open_jobs": 25,
        "founded_year": 2011,
        "size": "11-50",
        "city": "Miami",
        "state": "FL",
        "country": "United States",
        "lead_source": "Clay",
        "semana": "40",
    },
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="manda de verdad (sin esto sólo imprime)")
    ap.add_argument("--base", default="http://localhost:5000")
    args = ap.parse_args()

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    if not args.send:
        print(json.dumps(SAMPLE, indent=2, ensure_ascii=False))
        print("\n(dry: agregá --send para mandarlas)")
        return 0
    token = os.environ.get("CLAY_WEBHOOK_TOKEN")
    if not token:
        print("Falta CLAY_WEBHOOK_TOKEN en backend/.env", file=sys.stderr)
        return 1
    for item in SAMPLE:
        r = requests.post(
            f"{args.base.rstrip('/')}/prospecting/clay/webhook",
            json=item,
            headers={"X-Clay-Token": token},
            timeout=30,
        )
        print(r.status_code, r.text.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
