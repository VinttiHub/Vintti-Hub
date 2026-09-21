#!/usr/bin/env python3
"""Recalcula el castigo de job hopping de los CV reviews ya guardados.

Se corre después de cada cambio a `job_hopping()` o a sus regex de motivo, en
`utils/cv_review_ai.py`: un arreglo ahí sólo alcanza a lo que se puntúe de ahora en más,
y los reviews que ya están en pantalla siguen mostrando el castigo viejo. Lleva todo a
`ANALYSIS_VERSION`, que es la que lee en vivo — no hay número de versión hardcodeado acá.

Corridas hasta hoy:
  · v15 (2026-09-21) — el motivo escrito FUERA de las viñetas se tiraba antes de buscarlo,
    y el regex no aceptaba "Reason to leave". 4 reviews recuperaron 10 puntos.
  · v16 (2026-09-21) — un puesto que se explica solo por el título (el encargo entre
    paréntesis, la tesis, el contrato con duración, la tutoría) deja de contar como job
    hopping sin justificar. Otros 4.
  · v17 (2026-09-21) — "Project ended" se acepta igual que "End of project", y para
    proyecto / contrato / engagement / assignment por igual. 0 scores movidos: los 179
    reviews sólo se re-sellaron, porque las 10 apariciones del corpus ya venían con
    rótulo. Es la corrida típica de un cambio que sólo blinda hacia adelante.

**No llama a OpenAI.** Lo que cambia es determinístico y sus insumos ya están en la
base: `job_hopping()` sale del `resume_snapshot`, y el score sale de la checklist que
el modelo ya devolvió. Re-scorear con el modelo habría movido también la parte que no
tiene nada de malo — gpt-4o no es determinista ni con temperature=0.

Cuatro límites que el script se pone a sí mismo, y los cuatro se ganaron en la primera
corrida en seco — que iba a tocar 32 reviews en vez de 4:

  · **Sólo toca reviews que YA tienen `_job_hopping`** (v12 en adelante, 178 de 224).
    Los 46 anteriores fueron puntuados con fórmulas que ni siquiera tenían checklist:
    recalcularlos con la de hoy dejaba 27 con el score en NULL y rompía otros 12 con
    un KeyError. No es este arreglo, es reescribir historia.
  · **Si el castigo no cambió, el score no se vuelve a calcular.** Se sella la versión
    y nada más. Un review de la v12 cuyo job hopping da igual da igual: no hay por qué
    pasarlo por la aritmética de hoy y arriesgar una diferencia por otro motivo.
  · **Un castigo que SUBE no se aplica.** Este arreglo sólo puede encontrar motivos,
    nunca perderlos: si el castigo sube es por el reloj (`_role_span()` deja de tratar
    como "en curso" un rol cuyo fin ya quedó atrás), y bajarle 10 puntos a un CV por el
    paso del tiempo, escondido dentro de un arreglo de otra cosa, no.
  · **El score sólo se puede mover exactamente lo que se movió el castigo.** Si la
    cuenta da otra cosa, el review se reporta como DIVERGE y NO se escribe. Es la red
    que evita que este script se convierta en un re-score encubierto.

La v16 fue la última que movió números: 4 reviews subieron 10 puntos (113 Santiago
Regueira 65→75, 207 Daniel Esteban Tapiero 80→90, 234 Fatima Villalta 90→100,
277 Luisa Rodriguez 90→100) y el resto sólo pasó de versión. Ninguno bajó — los
arreglos de este chequeo no aflojan el criterio, le sacan la venda.

Uso:
    cd backend
    python scripts/backfill_job_hopping.py            # dry-run: sólo el reporte
    python scripts/backfill_job_hopping.py --apply    # escribe

Es idempotente: correrlo dos veces no cambia nada la segunda vez.
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

from psycopg2.extras import Json, RealDictCursor  # noqa: E402

from db import get_connection  # noqa: E402
import utils.cv_review_ai as cv  # noqa: E402


def _json(value):
    """`resume_snapshot` y `ai_analysis` vuelven como dict o como texto según la fila."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def rescorear(analysis: dict, hopping: dict) -> tuple:
    """El mismo cierre que hace `finalize()`, con la checklist que ya está guardada.

    Se repite acá en vez de llamar a `finalize()` porque aquélla arranca del JSON crudo
    del modelo, que no se guarda. Las tres funciones que deciden el número —
    `requirements_score`, el override de checklist incompleta y `derive_verdict`— se
    reusan tal cual: si mañana cambia una, este script sigue dando lo mismo que la
    corrida en vivo.
    """
    tools_penalty = int((analysis.get("_tools_check") or {}).get("penalty") or 0)
    req_summary = analysis.get("_requirements_summary") or {}

    composite, score_detail, basis = cv.requirements_score(
        analysis.get("jd_requirements") or [],
        [
            {"key": "tools", "label": "tools list nothing backs up",
             "points": tools_penalty},
            {"key": "job_hopping", "label": "short stint the CV never explains",
             "points": hopping["penalty"]},
        ],
    )
    # Un denominador demostrablemente incompleto sesga el score hacia arriba: se calcula
    # igual, pero no se promedia. Mismo override que `finalize()`.
    if basis == "requirements" and req_summary.get("incomplete"):
        basis = "incomplete_requirements"

    hard_claims = [c for c in (analysis.get("unsupported_claims") or [])
                   if isinstance(c, dict) and c.get("severity") == "hard"]
    verdict, verdict_reason = cv.derive_verdict(
        composite, req_summary, hard_claims, tools_penalty, hopping["penalty"])

    return composite, {
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "_composite_score": composite,
        "_score_basis": basis,
        "_score_detail": score_detail,
        "_partial": basis != "requirements",
    }


def resolver(fila: dict) -> tuple:
    """(estado, detalle, ai_score nuevo o None, ai_analysis nuevo o None)."""
    rid = fila["review_id"]
    nombre = fila["candidato"]
    analysis = _json(fila["ai_analysis"])
    snapshot = _json(fila["resume_snapshot"])
    if not isinstance(analysis, dict) or not isinstance(snapshot, dict):
        return "ERROR", f"review {rid}: ai_analysis o resume_snapshot ilegible", None, None

    viejo_jh = analysis.get("_job_hopping") or {}
    pen_vieja = int(viejo_jh.get("penalty") or 0)
    hopping = cv.job_hopping(snapshot)
    pen_nueva = hopping["penalty"]
    version_vieja = analysis.get("_version")

    nuevo = dict(analysis)
    nuevo["_job_hopping"] = hopping
    nuevo["_version"] = cv.ANALYSIS_VERSION
    # `_input_hash` y `_model` se dejan como estaban: siguen describiendo la corrida que
    # produjo la checklist, que es justo lo que este script NO vuelve a pedir.

    if pen_nueva == pen_vieja:
        # El castigo no es lo único que se ve en pantalla: la CITA del motivo también, y un
        # arreglo puede mejorarla sin mover el número (la de Orbia arrastraba el bullet de
        # al lado, "Tools: Excel Reason to leave: ..."). Se compara el chequeo entero.
        if hopping == viejo_jh and version_vieja == cv.ANALYSIS_VERSION:
            return "sin cambios", "", None, None
        if hopping != viejo_jh:
            return ("citas",
                    f"review {rid} · {nombre} · mismo castigo ({pen_nueva}), se refresca el "
                    f"chequeo y las citas",
                    fila["ai_score"], nuevo)
        return ("solo version",
                f"review {rid} · {nombre} · v{version_vieja} → v{cv.ANALYSIS_VERSION}",
                fila["ai_score"], nuevo)

    # Un castigo que SUBE no puede venir de este arreglo: leer más texto y aceptar más
    # frases sólo puede encontrar motivos, nunca perderlos. Viene del reloj. `_role_span()`
    # trata un fin en el futuro como rol en curso, y un rol en curso no se juzga — cuando
    # esa fecha queda atrás, el tramo pasa a contar. Le pasó al review 94 (Luisa Rodriguez):
    # se puntuó el 2026-08-25 con el rol de BAGS terminando el 2026-08-15, todavía adelante.
    # Aplicarlo acá sería bajarle 10 puntos a un CV por el paso del tiempo, escondido dentro
    # de un arreglo de otra cosa. Que lo decida una persona apretando "score again".
    if pen_nueva > pen_vieja:
        return ("AL ALZA",
                f"review {rid} · {nombre} · v{version_vieja} · el castigo subiría de "
                f"{pen_vieja} a {pen_nueva} ({hopping['state']}) por fechas que quedaron "
                f"atrás desde que se puntuó, no por este arreglo. NO se escribe.",
                None, None)

    score_viejo = fila["ai_score"]
    composite, campos = rescorear(analysis, hopping)
    nuevo.update(campos)

    # La red: el score sólo se puede mover exactamente lo que se movió el castigo. Si da
    # otra cosa, la diferencia viene de otro lado (una fórmula que cambió entre la versión
    # con la que se puntuó y la de hoy) y este script no es quien para decidirla.
    esperado = None if score_viejo is None else score_viejo + (pen_vieja - pen_nueva)
    if composite != esperado:
        return ("DIVERGE",
                f"review {rid} · {nombre} · v{version_vieja} · score {score_viejo} → "
                f"{composite} pero por el castigo debería dar {esperado}. NO se escribe.",
                None, None)

    return ("score",
            f"review {rid} · {nombre} · {score_viejo} → {composite} "
            f"(job hopping: {pen_vieja} → {pen_nueva}, {hopping['state']})",
            composite, nuevo)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="escribe los cambios (sin esto sólo imprime el reporte)")
    args = parser.parse_args()

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # `ai_analysis ? '_job_hopping'` es el filtro que importa: los reviews
            # anteriores a la v12 no tienen el chequeo y no se tocan.
            cursor.execute(
                """
                SELECT r.review_id, r.ai_score, r.ai_analysis, r.resume_snapshot,
                       c.name AS candidato
                  FROM cv_reviews r
                  LEFT JOIN candidates c ON c.candidate_id = r.candidate_id
                 WHERE r.ai_analysis ? '_job_hopping'
                   AND r.resume_snapshot IS NOT NULL
                 ORDER BY r.review_id
                """
            )
            filas = cursor.fetchall()

        print(f"{len(filas)} reviews con chequeo de job hopping guardado "
              f"(los anteriores a la v12 no se tocan).\n")
        resumen: dict = {}

        for fila in filas:
            # Cada review en su propia transacción: sin esto un fallo a mitad de camino
            # revierte todo lo anterior y el COMMIT final actúa como ROLLBACK.
            try:
                estado, detalle, score, analysis = resolver(fila)
                if args.apply and analysis is not None:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            "UPDATE cv_reviews SET ai_score = %s, ai_analysis = %s, "
                            "updated_at = NOW() WHERE review_id = %s",
                            (score, Json(analysis), fila["review_id"]),
                        )
                    conn.commit()
                else:
                    conn.rollback()
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                estado, detalle = "ERROR", f"review {fila['review_id']}: {exc}"

            resumen[estado] = resumen.get(estado, 0) + 1
            if detalle:
                print(f"[{estado:>12}] {detalle}")

        print()
        print(" · ".join(f"{k}: {v}" for k, v in sorted(resumen.items())))
        if not args.apply:
            print("\nDRY-RUN: no se escribió nada. "
                  "Revisá los cambios de score uno por uno y corré con --apply.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
