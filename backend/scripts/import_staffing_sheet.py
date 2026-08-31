#!/usr/bin/env python3
"""Carga única del Google Sheet "Candidate Success VINTTI" a la base del Hub.

Los CSV de `scripts/data/` son un snapshot congelado del Sheet (bajado el
2026-08-31). El script NO reimporta lo que la base ya sabe: sólo escribe los
campos que existían únicamente en el Sheet.

  * Staffing Database -> staffing_extra.platform / performance / provider / notes
  * Staffing Churn    -> staffing_extra.exit_type (+ notes). La columna "Churn M3"
                         del Sheet NO se importa: el backend la calcula sola y se
                         verificó que coincide 52/52 con lo que decía el Sheet.
  * Bonos             -> bonus_requests (alta): el texto del Sheet va a `reason`
                         (el campo libre que ya usan los bonos existentes), no a
                         `bonus_type`, que es un enum con default.

Las filas que no matchean contra ningún hire de la base se guardan igual, como
filas huérfanas (`candidate_id IS NULL`), para que no se pierda nada; la página
las muestra con un badge "Solo Sheet".

Uso:
    cd backend
    python scripts/import_staffing_sheet.py            # dry-run: sólo el reporte
    python scripts/import_staffing_sheet.py --apply    # escribe

Es idempotente: correrlo dos veces no duplica nada.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from collections import defaultdict
from datetime import date
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
from routes.staffing_routes import HIRES_CTE, PAIRS_SELECT, _ensure_schema  # noqa: E402

DATA = HERE / "data"

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


# --------------------------------------------------------------------------- #
# Parsers del formato del Sheet
# --------------------------------------------------------------------------- #
def norm(text: str | None) -> str:
    """Nombre normalizado para matchear: sin acentos, sin puntuación, minúsculas."""
    if not text:
        return ""
    stripped = unicodedata.normalize("NFKD", str(text))
    stripped = "".join(ch for ch in stripped if not unicodedata.combining(ch))
    stripped = re.sub(r"[^a-zA-Z0-9 ]", " ", stripped)
    return re.sub(r"\s+", " ", stripped).strip().lower()


def parse_sheet_date(raw: str | None, default_year: int | None = None) -> str | None:
    """'June 22nd, 2026' / 'January 6th' / 'May' -> 'YYYY-MM-DD'."""
    if not raw:
        return None
    txt = str(raw).strip()
    if not txt:
        return None
    match = re.match(r"([A-Za-z]+)\s*(\d{1,2})?[a-zA-Z]*,?\s*(\d{4})?", txt)
    if not match:
        return None
    month = MONTHS.get((match.group(1) or "").lower())
    if not month:
        return None
    day = int(match.group(2)) if match.group(2) else 1
    year = int(match.group(3)) if match.group(3) else default_year
    if not year:
        return None
    try:
        return date(year, month, min(day, 28) if month == 2 else day).isoformat()
    except ValueError:
        return None


def parse_money(raw: str | None) -> float | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^0-9.]", "", str(raw))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def read_csv(name: str) -> list[dict]:
    with open(DATA / name, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    header = [h.strip() for h in rows[0]]
    out = []
    for raw in rows[1:]:
        if not any(cell.strip() for cell in raw):
            continue
        record = {}
        for idx, key in enumerate(header):
            if key:
                record[key] = raw[idx].strip() if idx < len(raw) else ""
        out.append(record)
    return out


# --------------------------------------------------------------------------- #
# Matcheo contra la base
# --------------------------------------------------------------------------- #
def same_client(a: str, b: str) -> bool:
    """Los nombres de cliente del Sheet están abreviados y a veces recortados por
    el medio: 'G&A' vs 'G&A Partners', 'Highland Fleets' vs 'Highland Electric
    Fleets'. Alcanza con que las palabras del más corto estén en el más largo."""
    x, y = norm(a), norm(b)
    if not x or not y:
        return False
    if x == y or x.startswith(y) or y.startswith(x):
        return True
    tx, ty = set(x.split()), set(y.split())
    return tx <= ty or ty <= tx


# Umbral de parecido entre dos palabras sueltas. Está calibrado contra los casos
# reales que confirmó la owner (2026-08-31), donde el más flojo es
# 'yadzareth' vs 'yadza' = 0.71:
#   ana/anna 0.86 · foti/fotti 0.89 · jauregi/jauregui 0.93 · meckbel/meckbell 0.93
#   baumarie/beaumerie 0.82 · angela/angeles 0.77 · juliet/julieta 0.92
#   emely/emily 0.80 · biancotti/bianciotti 0.94 · bohorez/bohorquez 0.88
TOKEN_SIM = 0.70


def token_hits(a: str, b: str) -> int:
    """Cuántas palabras de `a` encuentran una parecida en `b` (sin reusarlas)."""
    tokens_a, tokens_b = norm(a).split(), norm(b).split()
    used, hits = set(), 0
    for token in tokens_a:
        best_score, best_idx = 0.0, None
        for idx, other in enumerate(tokens_b):
            if idx in used:
                continue
            score = SequenceMatcher(None, token, other).ratio()
            if score > best_score:
                best_score, best_idx = score, idx
        if best_score >= TOKEN_SIM:
            used.add(best_idx)
            hits += 1
    return hits


def name_close(a: str, b: str) -> bool:
    """¿Son la misma persona escrita distinto?

    Dos palabras parecidas alcanzan (nombre + apellido). Con una sola sirve
    únicamente si uno de los dos nombres es de una sola palabra ('Bianca'):
    si no, 'Juan Perez' y 'Juan Gomez' matchearían.
    """
    shortest = min(len(norm(a).split()), len(norm(b).split()))
    hits = token_hits(a, b)
    return hits >= 2 or (hits >= 1 and shortest == 1)


class Matcher:
    """Indexa los pares (candidato, cuenta) de Staffing que ya están en la base.

    El Sheet escribe los nombres distinto que el Hub, y no sólo abreviados: hay
    errores de tipeo ('Yanina Fotti' vs 'Yanina Foti', 'Anna Arroyo' vs 'Ana
    Arroyo', 'Sergio Jauregi' vs 'Sergio Jauregui'). Por eso el paso difuso
    compara palabra por palabra con SequenceMatcher en vez de exigir subconjunto.

    Orden de intentos:
      1. exact       nombre idéntico + mismo cliente
      2. by-name     nombre idéntico, único en la base, otro cliente
      3. fuzzy       nombre parecido DENTRO del mismo cliente
      4. fuzzy-solo  nombre parecido en toda la base, pero sólo si es único
                     (para las filas cuyo "cliente" del Sheet no es una cuenta real)
    Si hay más de un candidato en cualquier paso, se marca ambiguo y no se toca.
    """

    def __init__(self, pairs: list[dict]):
        self.pairs = pairs
        self.by_name = defaultdict(list)
        for pair in pairs:
            self.by_name[norm(pair["candidate_name"])].append(pair)

    def find(self, candidate: str, client: str):
        """-> (par, calidad): exact / by-name / fuzzy / fuzzy-solo / ambiguous / none."""
        options = self.by_name.get(norm(candidate)) or []
        if options:
            exact = [p for p in options if same_client(p["client_name"], client)]
            if len(exact) == 1:
                return exact[0], "exact"
            if len(exact) > 1:
                return exact[0], "ambiguous"
            if len(options) == 1:
                return options[0], "by-name"
            return None, "ambiguous"

        in_client = [p for p in self.pairs if same_client(p["client_name"], client)]
        hits = [p for p in in_client if name_close(candidate, p["candidate_name"])]
        if len(hits) == 1:
            return hits[0], "fuzzy"
        if len(hits) > 1:
            return None, "ambiguous"

        # Sin cliente que ayude: sólo se acepta si en TODA la base hay una sola
        # persona parecida. Es el caso de los bonos con un "cliente" que no es cuenta.
        loose = [p for p in self.pairs if name_close(candidate, p["candidate_name"])]
        names = {norm(p["candidate_name"]) for p in loose}
        if len(names) == 1:
            return loose[0], "fuzzy-solo"
        if len(names) > 1:
            return None, "ambiguous"
        return None, "none"


def load_pairs(cur) -> list[dict]:
    cur.execute(f"WITH {HIRES_CTE} {PAIRS_SELECT}")
    return [dict(r) for r in cur.fetchall()]


# --------------------------------------------------------------------------- #
# Upserts
# --------------------------------------------------------------------------- #
def upsert_extra(cur, pair, fields: dict, orphan_name=None, orphan_client=None) -> str:
    """Escribe en staffing_extra sin pisar valores ya cargados a mano en el Hub."""
    fields = {k: v for k, v in fields.items() if v not in (None, "")}
    if not fields:
        return "skip"

    if pair is not None:
        where = "candidate_id = %(candidate_id)s AND account_id = %(account_id)s"
        keys = {"candidate_id": pair["candidate_id"], "account_id": pair["account_id"]}
        insert_cols = ["candidate_id", "account_id"]
    else:
        where = ("candidate_id IS NULL AND LOWER(candidate_name) = LOWER(%(candidate_name)s) "
                 "AND LOWER(COALESCE(client_name, '')) = LOWER(%(client_name)s)")
        keys = {"candidate_name": orphan_name, "client_name": orphan_client or ""}
        insert_cols = ["candidate_name", "client_name"]

    cur.execute(f"SELECT staffing_extra_id FROM staffing_extra WHERE {where}", keys)
    existing = cur.fetchone()
    params = dict(fields, **keys)

    if existing:
        # Idempotente y no destructivo: sólo completa lo que está vacío.
        assignments = ", ".join(f"{k} = COALESCE({k}, %({k})s)" for k in fields)
        cur.execute(
            f"UPDATE staffing_extra SET {assignments}, updated_at = NOW() WHERE {where}",
            params,
        )
        return "update"

    cols = insert_cols + list(fields)
    placeholders = ", ".join(f"%({c})s" for c in cols)
    cur.execute(
        f"INSERT INTO staffing_extra ({', '.join(cols)}, source) "
        f"VALUES ({placeholders}, 'sheet_import')",
        params,
    )
    return "insert"


def import_database(cur, matcher, apply: bool, report):
    for row in read_csv("staffing_database.csv"):
        candidate = row.get("Candidate", "")
        client = row.get("Client", "")
        pair, quality = matcher.find(candidate, client)
        report["database"][quality].append(label(candidate, client, pair, quality))
        if not apply:
            continue
        fields = {
            "platform": row.get("Platform") or None,
            "performance": row.get("Performance") or None,
            "provider": row.get("Provider") or None,
            "notes": row.get("Comments") or None,
        }
        upsert_extra(cur, pair, fields, orphan_name=candidate, orphan_client=client)


def import_churn(cur, matcher, apply: bool, report):
    for filename, year in (("staffing_churn_2026.csv", 2026), ("staffing_churn_2025.csv", 2025)):
        for row in read_csv(filename):
            candidate = row.get("Nombre", "")
            client = row.get("Cliente", "")
            pair, quality = matcher.find(candidate, client)
            report["churn"][quality].append(label(candidate, client, pair, quality) + f" ({year})")
            if not apply:
                continue
            fields = {
                # La página está en inglés: el Sheet dice Renuncia/Despido.
                "exit_type": {"renuncia": "Resigned", "despido": "Terminated"}.get(
                    (row.get("Renuncia o Despido") or "").strip().lower()) or None,
                "notes": row.get("Comments") or None,
            }
            upsert_extra(cur, pair, fields, orphan_name=candidate, orphan_client=client)


def import_bonuses(cur, matcher, apply: bool, report):
    for row in read_csv("bonos_2026.csv"):
        candidate = row.get("Candidate", "")
        client = row.get("Client", "")
        amount = parse_money(row.get("Bonus ammount"))
        payout = parse_sheet_date(row.get("Date"), default_year=2026)
        tag = f"{candidate} — {client} — {row.get('Bonus ammount')}"

        # `bonus_requests.payout_date` es NOT NULL, así que una fila sin fecha
        # (el Sheet tiene una en "NA") no se puede importar. No se inventa la
        # fecha: se saltea y se reporta para cargarla a mano.
        if not payout:
            report["bonos"]["sin-fecha"].append(f"{tag} — fecha: {row.get('Date')!r}")
            continue
        # Un año fuera de la hoja casi siempre es un typo ('March 20th, 2027').
        # Se importa igual — corregirlo sería adivinar — pero se avisa.
        if not payout.startswith("2026"):
            report["bonos"]["fecha-rara"].append(f"{tag} — {row.get('Date')} -> {payout}")

        pair, quality = matcher.find(candidate, client)
        report["bonos"][quality].append(
            label(candidate, client, pair, quality) + f" — {row.get('Bonus ammount')}")
        # account_id también es NOT NULL sin default.
        if not pair:
            report["bonos"]["sin-cuenta"].append(tag)
            continue
        if not apply:
            continue

        # Dedupe por (candidate_id, monto, fecha): así se puede volver a correr sin
        # duplicar. Tiene que ser por candidate_id y NO por nombre: la fila se
        # inserta con el candidate_id del match difuso, así que en la corrida
        # siguiente el nombre del Sheet ('Yanina Fotti') ya no coincide con el de
        # la base ('Yanina Foti') y se colaba un duplicado.
        cur.execute(
            """
            SELECT br.bonus_request_id
            FROM bonus_requests br
            WHERE COALESCE(br.amount, 0) = %(amount)s
              AND COALESCE(br.payout_date::text, '') = COALESCE(%(payout)s, '')
              AND br.candidate_id = %(candidate_id)s
            LIMIT 1
            """,
            {"amount": amount or 0, "payout": payout, "candidate_id": pair["candidate_id"]},
        )
        existing = cur.fetchone()
        if existing:
            # El bono ya estaba cargado en el Hub: no se duplica, pero sí se le
            # completan los dos estados de pago que sólo tenía el Sheet.
            cur.execute(
                """
                UPDATE bonus_requests
                   SET invoice_status   = COALESCE(invoice_status, %(invoice_status)s),
                       candidate_status = COALESCE(candidate_status, %(candidate_status)s),
                       updated_at = NOW()
                 WHERE bonus_request_id = %(id)s
                """,
                {
                    "id": existing["bonus_request_id"],
                    "invoice_status": row.get("Invoice Payment (Client)") or None,
                    "candidate_status": row.get("Status (Candidate)") or None,
                },
            )
            continue

        cur.execute(
            """
            INSERT INTO bonus_requests (
                account_id, candidate_id, employee_name_manual, currency, amount,
                payout_date, reason, notes, status,
                invoice_status, candidate_status, created_at, updated_at
            ) VALUES (
                %(account_id)s, %(candidate_id)s, %(name)s, 'USD', %(amount)s,
                %(payout)s, %(reason)s, %(notes)s, 'paid',
                %(invoice_status)s, %(candidate_status)s, NOW(), NOW()
            )
            """,
            {
                "account_id": pair["account_id"] if pair else None,
                "candidate_id": pair["candidate_id"] if pair else None,
                "name": candidate,
                "amount": amount or 0,
                "payout": payout,
                "reason": row.get("Comments") or None,
                "notes": row.get("Column 1") or None,
                "invoice_status": row.get("Invoice Payment (Client)") or None,
                "candidate_status": row.get("Status (Candidate)") or None,
            },
        )


def label(candidate, client, pair, quality):
    base = f"{candidate} — {client}"
    if quality in ("by-name", "fuzzy", "fuzzy-solo") and pair:
        base += f"  ->  {pair['candidate_name']} ({pair['client_name']})"
    return base


def print_report(report):
    for section, buckets in report.items():
        total = sum(len(v) for k, v in buckets.items()
                    if k not in ("fecha-rara", "sin-cuenta"))
        print(f"\n=== {section.upper()} — {total} filas del Sheet")
        for quality in ("exact", "by-name", "fuzzy", "fuzzy-solo", "ambiguous",
                        "none", "fecha-rara", "sin-fecha", "sin-cuenta"):
            items = buckets.get(quality) or []
            label = {
                "exact": "match exacto (candidato + cliente)",
                "by-name": "match por nombre (el cliente no coincide)",
                "fuzzy": "match difuso (mismo cliente, nombre escrito distinto)",
                "fuzzy-solo": "match difuso por nombre, único en toda la base",
                "ambiguous": "ambiguo (varios candidatos con el mismo nombre)",
                "none": "SIN MATCH en la base -> quedan como fila huérfana",
                "fecha-rara": "OJO: fecha fuera de 2026, probable typo (se importa igual)",
                "sin-fecha": "NO SE IMPORTAN: sin fecha, y payout_date es NOT NULL",
                "sin-cuenta": "NO SE IMPORTAN: sin cuenta, y account_id es NOT NULL",
            }[quality]
            print(f"  {len(items):4d}  {label}")
            if quality in ("by-name", "fuzzy", "fuzzy-solo", "ambiguous",
                           "none", "fecha-rara", "sin-fecha", "sin-cuenta"):
                for item in items:
                    print(f"          · {item}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="escribe en la base (por defecto, dry-run)")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    _ensure_schema(cur)
    conn.commit()

    pairs = load_pairs(cur)
    print(f"Pares (candidato, cuenta) de Staffing en la base: {len(pairs)}")
    matcher = Matcher(pairs)

    report = {k: defaultdict(list) for k in ("database", "churn", "bonos")}
    import_database(cur, matcher, args.apply, report)
    import_churn(cur, matcher, args.apply, report)
    import_bonuses(cur, matcher, args.apply, report)

    if args.apply:
        conn.commit()
        print("\nAplicado.")
    else:
        conn.rollback()
        print("\nDRY-RUN: no se escribió nada. Volvé a correr con --apply cuando el matcheo cierre.")

    print_report(report)
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
