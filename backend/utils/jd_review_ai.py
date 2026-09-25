"""El juez del JD Review: ¿la JD dice lo que se habló en la Intro Call y la Deep Dive?

La JD la escribe gpt-4o desde los transcripts de Grain (POST /ai/generate_jd) y después
nadie la contrasta con las reuniones. Este módulo hace ese contraste en dos pasos, a
propósito separados:

  1. EXTRAER: de los transcripts (sin ver la JD) sale la lista de hechos que el cliente
     dijo sobre el puesto — responsabilidades, stack, años, inglés, horario, etc. El
     extractor no ve la JD para que no se "acomode" a lo que la JD ya dice.
  2. JUZGAR: cada hecho contra la JD (covered / partial / contradicted / missing), más lo
     que la JD afirma y nadie dijo (`unsupported`).

El número NO lo pone el modelo: lo calcula `compute_score()`, igual que el CV Review
(`cv_review_ai.requirements_score`). Así un cambio de prompt no mueve la escala en silencio.

Nunca levanta excepción hacia afuera: `score_jd()` devuelve (score, analysis, error_code).
"""
from __future__ import annotations

import html as _html
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from utils.cv_review_ai import input_hash, parse_json

MODEL = "gpt-4o"

# Subirla invalida el promedio de calidad de las métricas (sólo cuentan los análisis de la
# versión vigente), igual que en cv_review_ai.
# v2 (2026-09-25): el salario cuenta como cubierto si la JD habla de la paga en cualquier forma.
# v3 (2026-09-25): un dato por hecho ("full-time contractor" eran dos) y lo que se deduce sin
#     ambigüedad cuenta (9 a 5 = full-time). Caso real: opp 844.
# v4 (2026-09-25): el estado ya no lo elige el juez; lo deriva el código de las PARTES de cada
#     hecho (explicit / implied / no). Con criterio libre el mismo "full-time contractor" salía
#     missing aunque la JD dijera "9 to 5", y el salario volvía a missing. Ver derive_status().
# v5 (2026-09-25): las partes las define el EXTRACTOR (que sabe qué dijo el cliente) y el juez
#     sólo las evalúa. Pedirle al juez que partiera y juzgara a la vez fallaba: la misma opp 844
#     dejaba "full-time contractor" entero una corrida sí y otra no.
ANALYSIS_VERSION = 5

# Versión SÓLO del extractor (el prompt que saca los puntos de las reuniones). La lista de puntos
# se guarda por (vacante, transcripts, esta versión) y se reusa en cada re-run y cada ronda: así el
# score sólo cambia cuando cambia la JD. Subirla invalida las listas guardadas.
EXTRACT_VERSION = 1

# Cuánto transcript entra al extractor. La generación de la JD corta a 12k por reunión;
# el juez necesita ver todo para decir "esto se habló y no está", y gpt-4o aguanta.
TRANSCRIPT_LIMIT = 40000
JD_LIMIT = 12000

# --- score -----------------------------------------------------------------------------
_STATUS_CREDIT = {"covered": 1.0, "partial": 0.5, "missing": 0.0, "contradicted": 0.0}
_IMPORTANCE_WEIGHT = {"must": 2.0, "nice": 1.0}

# Una contradicción ya da 0 crédito a su hecho; la penalización extra existe porque es
# peor que omitir: la JD le dice al candidato algo FALSO sobre el puesto.
CONTRADICTION_PENALTY = 5
CONTRADICTION_CAP = 20
# Sólo lo inventado "hard" (un requisito o condición concreta: una herramienta, años, un
# título, un horario). El relleno genérico ("strong communication skills") se muestra pero
# no resta: lo agrega casi cualquier JD y castigarlo sería ruido.
UNSUPPORTED_PENALTY = 5
UNSUPPORTED_CAP = 20

CATEGORIES = (
    ("responsibilities", "Responsibilities"),
    ("tools", "Tools / tech stack"),
    ("experience", "Experience / seniority"),
    ("english", "English level"),
    ("schedule_location", "Schedule / timezone / location"),
    ("conditions", "Contract / conditions"),
    ("nice_to_have", "Nice to have"),
    ("company_context", "Company / team context"),
)
_CATEGORY_CODES = {c for c, _ in CATEGORIES}

# Defectos que el sales lead tilda a mano. Tildar = "este defecto está", como en el CV.
CHECKLIST_ITEMS = (
    ("missing_responsibilities", "Missing responsibilities discussed in the calls"),
    ("missing_tools_stack", "Missing tools / tech stack"),
    ("wrong_experience_seniority", "Wrong years of experience / seniority"),
    ("missing_english_level", "English level missing or wrong"),
    ("missing_schedule_location", "Schedule / timezone / location missing or wrong"),
    ("invented_requirement", "Includes requirements nobody asked for"),
)
CHECKLIST_CODES = {c for c, _ in CHECKLIST_ITEMS}


# --- texto -----------------------------------------------------------------------------

# Red de seguridad por si el extractor no marca is_salary.
_SALARY_RE = re.compile(r"(?i)\b(salary|salario|compensation|pay|wage|sueldo|bonus(es)?)\b")


def jd_html_to_text(raw: str) -> str:
    """La JD vive como HTML del editor. Se pasa a texto CONSERVANDO los saltos de línea:
    `ai_routes._strip_html_text` los colapsa y entonces cada bullet deja de ser una línea,
    que es lo que el juez cita y lo que la página resalta."""
    s = raw or ""
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|li|h[1-6]|ul|ol|tr)>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "- ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln).strip()


def jd_hash(jd_html: str) -> str:
    """Huella de la JD tal como la ve el juez (texto), no del HTML: el editor reformatea el
    HTML al cargar y eso no puede contar como "la JD cambió"."""
    return input_hash(jd_html_to_text(jd_html))


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    # Punta y cola: los requisitos suelen salir al final de la Deep Dive.
    half = limit // 2
    return text[:half] + "\n[…transcript truncated…]\n" + text[-half:]


# --- prompts ---------------------------------------------------------------------------

_EXTRACT_SYSTEM = """You analyse recordings of sales calls between a staffing agency and a client who is hiring.
You get the transcript of the INTRO CALL and/or the DEEP DIVE for one open position.
Extract every concrete FACT the client stated about the role that a job description for it should reflect.

Rules:
- Only facts about THIS role/hire. Ignore agency pricing, small talk, scheduling of the next call, and generic sales pitch.
- One fact per item, short and specific, written in English (translate if needed).
- "quote" must be a VERBATIM excerpt of the transcript (original language, max ~25 words) that supports the fact.
- "source": "intro" or "deep_dive" — where the quote comes from.
- "importance": "must" when the client presented it as required / core to the job; "nice" when it was optional, a plus, or secondary.
- "category": one of responsibilities, tools, experience, english, schedule_location, conditions, nice_to_have, company_context.
- Do not merge different facts. Never bundle two attributes in one fact: "full-time contractor role" is TWO facts ("full-time" and "contractor, not an employee"); "5+ years in B2B SaaS" is one fact only if the client said it as one requirement. Do not invent. If the same fact appears in both calls, keep the clearest one.
- "parts": the atomic pieces a JD would have to say for this fact to be fully there, usually 1, sometimes 2-4. "Full-time contractor role" -> ["full-time", "contractor, not an employee"]. "Advanced Excel with pivot tables" -> ["Excel", "advanced level / pivot tables"]. A list gets one part per item: "Google Ads, LinkedIn Ads and Meta Ads" -> ["Google Ads", "LinkedIn Ads", "Meta Ads"]. A salary fact has the single part "compensation is mentioned".
- If the two calls disagree, keep the DEEP DIVE version (it comes later) and mention the change in "note".
- Be exhaustive and granular: each tool, each task, each condition is its own fact (a typical deep dive yields 15-35 facts). Maximum 40; prioritise what matters to a candidate deciding whether to apply.
- Money: the client's budget, the agency fee and anything about what Vintti charges are NOT facts. The candidate's salary / compensation / bonuses is a "conditions" fact with importance "nice" and "is_salary": true (JDs leave the amount out on purpose). Every other fact has "is_salary": false.

Return JSON: {"facts": [{"id": "f1", "category": "...", "fact": "...", "quote": "...", "source": "intro|deep_dive", "importance": "must|nice", "is_salary": false, "parts": ["..."], "note": ""}]}"""

_JUDGE_SYSTEM = """You audit a JOB DESCRIPTION against the list of facts the client stated in the sales calls.

For EACH fact:
1. Each fact comes already split into "parts". Evaluate EVERY part given, in the same order, and do not merge or re-split them.
2. For each part say whether the JD has it:
   - "explicit": the JD says it (wording may differ).
   - "implied": it follows unambiguously from what the JD says. "9 to 5 schedule" implies full-time; "work from your local timezone" implies remote. Only clear implications, never guesses.
   - "no": the JD does not say it.
   Give "evidence": the VERBATIM JD text for explicit/implied parts (copy it character by character), empty for "no".
3. "contradicted": true ONLY if the JD states something INCOMPATIBLE with the fact (3 years vs 5, part-time vs full-time, EST vs PST, B2 vs C1). Not mentioning it is NOT a contradiction.
4. "jd_quote": the main verbatim JD text (the evidence, or the contradicting text).
5. "why": one short sentence saying what is there and what is not, or what the JD says instead. Empty when every part is explicit.

SALARY: JDs never publish the amount on purpose. "compensation is mentioned" is "explicit" if the JD mentions pay in ANY form ("competitive salary", a range, bonuses).

Then list "unsupported": statements in the JD that NO fact supports (things nobody said in the calls).
- "jd_quote": verbatim JD text.
- "severity": "hard" when it is a concrete requirement or condition a candidate would filter on (a tool, years, a degree, a certification, a schedule, a location, a language level, a salary/benefit); "soft" for generic filler (soft skills, "fast-paced environment", boilerplate about the company).
- "why": one short sentence.
Do not list the job title or section headings as unsupported.

Return JSON: {"facts": [{"id": "f1", "parts": [{"part": "", "in_jd": "explicit|implied|no", "evidence": ""}], "contradicted": false, "jd_quote": "", "why": ""}], "unsupported": [{"jd_quote": "", "severity": "hard|soft", "why": ""}]}"""


def _call(system: str, user: str, max_tokens: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        from ai_routes import call_openai_with_retry  # después de init_services()
        resp = call_openai_with_retry(
            MODEL,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0, max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        choice = resp.choices[0]
        if getattr(choice, "finish_reason", None) == "length":
            return None, "truncated"
        content = choice.message.content or ""
    except RuntimeError:
        logging.exception("JD review: OpenAI budget exhausted")
        return None, "budget"
    except Exception:
        logging.exception("JD review: OpenAI call failed")
        return None, "failed"
    parsed = parse_json(content)
    if not isinstance(parsed, dict):
        return None, "unparseable"
    return parsed, None


def _transcripts_block(transcripts: Dict[str, Any]) -> str:
    parts = []
    for key, label in (("intro", "INTRO CALL"), ("deep_dive", "DEEP DIVE")):
        t = (transcripts.get(key) or {}).get("text") or ""
        if t.strip():
            parts.append(f"=== {label} TRANSCRIPT ===\n{_truncate(t, TRANSCRIPT_LIMIT)}")
    return "\n\n".join(parts)


def _clean_facts(raw: Any) -> List[Dict[str, Any]]:
    out = []
    seen = set()
    for i, f in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(f, dict):
            continue
        fact = str(f.get("fact") or "").strip()
        if not fact:
            continue
        fid = str(f.get("id") or f"f{i + 1}").strip() or f"f{i + 1}"
        if fid in seen:
            fid = f"f{i + 1}_{len(seen)}"
        seen.add(fid)
        cat = str(f.get("category") or "").strip().lower()
        src = str(f.get("source") or "").strip().lower()
        imp = str(f.get("importance") or "").strip().lower()
        out.append({
            "id": fid,
            "category": cat if cat in _CATEGORY_CODES else "responsibilities",
            "fact": fact,
            "quote": str(f.get("quote") or "").strip(),
            "source": src if src in ("intro", "deep_dive") else "",
            # nice_to_have es por definición opcional, aunque el modelo diga otra cosa.
            "importance": "nice" if cat == "nice_to_have" or imp == "nice" else "must",
            "note": str(f.get("note") or "").strip(),
            "is_salary": bool(f.get("is_salary")) or bool(_SALARY_RE.search(fact)),
            # Sin partes, el hecho entero es una sola parte.
            "part_names": [str(x).strip() for x in (f.get("parts") or []) if str(x).strip()][:6]
                          or [fact],
        })
    return out[:40]


def _find_in_jd(quote: str, jd_text: str) -> bool:
    """¿La cita existe en la JD? El modelo a veces "cita" parafraseando: si no se encuentra,
    la página no puede resaltarla y lo decimos en vez de mostrar una cita inventada."""
    if not quote:
        return False
    norm = lambda s: re.sub(r"\s+", " ", re.sub(r"[“”\"'’`]", "", s or "")).strip().lower()
    return norm(quote) in norm(jd_text)


def derive_status(parts: List[Dict[str, Any]], contradicted: bool) -> str:
    """El estado sale de las partes, no de la opinión del juez.

    Todas las partes están (explícitas o implícitas sin ambigüedad) → covered; algunas →
    partial; ninguna → missing. Sin partes (el juez no devolvió el hecho) → missing: si no lo
    encontró, no puede decir que está.
    """
    if contradicted:
        return "contradicted"
    if not parts:
        return "missing"
    present = sum(1 for p in parts if p.get("in_jd") in ("explicit", "implied"))
    if present == len(parts):
        return "covered"
    return "partial" if present else "missing"


def compute_score(facts: List[Dict[str, Any]], unsupported: List[Dict[str, Any]]) -> Dict[str, Any]:
    """El score sale de acá, no del modelo.

    Además deja la cuenta ARMADA para que la página la muestre sin reimplementarla: cada hecho
    se lleva `points` / `max_points` (y `penalty` si resta), cada inventado "hard" su `penalty`,
    y el resumen trae `breakdown` (una fila por importancia × estado) con `earned` / `possible`.
    """
    total_w = 0.0
    got = 0.0
    counts = {"covered": 0, "partial": 0, "missing": 0, "contradicted": 0}
    must_missing = 0
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    contradiction_pen = 0
    for f in facts:
        st = f.get("status")
        if st not in _STATUS_CREDIT:
            continue
        imp = "must" if f.get("importance") != "nice" else "nice"
        w = _IMPORTANCE_WEIGHT[imp]
        pts = w * _STATUS_CREDIT[st]
        total_w += w
        got += pts
        counts[st] += 1
        f["points"] = pts
        f["max_points"] = w
        f["penalty"] = 0
        if st == "contradicted" and contradiction_pen < CONTRADICTION_CAP:
            f["penalty"] = min(CONTRADICTION_PENALTY, CONTRADICTION_CAP - contradiction_pen)
            contradiction_pen += f["penalty"]
        if st == "missing" and imp == "must":
            must_missing += 1
        g = groups.setdefault((imp, st), {"importance": imp, "status": st, "count": 0,
                                         "weight": w, "credit": _STATUS_CREDIT[st],
                                         "points": 0.0, "max": 0.0})
        g["count"] += 1
        g["points"] += pts
        g["max"] += w

    unsupported_pen = 0
    hard_unsupported = 0
    for u in unsupported:
        u["penalty"] = 0
        if u.get("severity") != "hard":
            continue
        hard_unsupported += 1
        if unsupported_pen < UNSUPPORTED_CAP:
            u["penalty"] = min(UNSUPPORTED_PENALTY, UNSUPPORTED_CAP - unsupported_pen)
            unsupported_pen += u["penalty"]

    order = {"covered": 0, "partial": 1, "missing": 2, "contradicted": 3}
    breakdown = sorted(groups.values(),
                       key=lambda g: (g["importance"] != "must", order[g["status"]]))
    rules = {
        "weights": dict(_IMPORTANCE_WEIGHT),
        "credit": dict(_STATUS_CREDIT),
        "contradiction_penalty": CONTRADICTION_PENALTY, "contradiction_cap": CONTRADICTION_CAP,
        "unsupported_penalty": UNSUPPORTED_PENALTY, "unsupported_cap": UNSUPPORTED_CAP,
    }

    if not total_w:
        return {"score": None, "base": None, "counts": counts, "facts_n": 0,
                "must_missing": 0, "hard_unsupported": hard_unsupported,
                "contradiction_penalty": 0, "unsupported_penalty": 0,
                "earned": 0, "possible": 0, "breakdown": [], "rules": rules}
    base = 100.0 * got / total_w
    score = max(0, min(100, round(base - contradiction_pen - unsupported_pen)))
    return {
        "score": score,
        "base": round(base, 1),
        "earned": got,
        "possible": total_w,
        "breakdown": breakdown,
        "rules": rules,
        "counts": counts,
        "facts_n": sum(counts.values()),
        "must_missing": must_missing,
        "hard_unsupported": hard_unsupported,
        "contradiction_penalty": contradiction_pen,
        "unsupported_penalty": unsupported_pen,
    }


def derive_verdict(summary: Dict[str, Any]) -> Tuple[str, str]:
    """Como en el CV: el veredicto sale de qué hay que hacer, no del número."""
    if summary.get("score") is None:
        return "", ""
    counts = summary.get("counts") or {}
    if counts.get("contradicted") or summary.get("hard_unsupported"):
        bits = []
        if counts.get("contradicted"):
            bits.append(f"{counts['contradicted']} fact(s) the JD states differently from the calls")
        if summary.get("hard_unsupported"):
            bits.append(f"{summary['hard_unsupported']} requirement(s) nobody asked for")
        text = "; ".join(bits)
        return "not_sendable", text[:1].upper() + text[1:] + ". Fix them before publishing."
    if summary.get("must_missing"):
        return "needs_work", (f"{summary['must_missing']} core point(s) from the calls are not in "
                              "the JD.")
    return "ready", "Everything core from the calls is in the JD."


def facts_key(transcripts: Dict[str, Any], position: str = "") -> str:
    """Huella de lo que ve el extractor: si no cambia, la lista de puntos guardada sigue valiendo."""
    return input_hash({"t": _transcripts_block(transcripts or {}), "p": position or "",
                       "v": EXTRACT_VERSION})


def extract_facts(*, transcripts: Dict[str, Any], position: str = "",
                  client_name: str = "") -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Paso 1: los puntos que dijo el cliente, SIN ver la JD. Devuelve (facts, error_code)."""
    tblock = _transcripts_block(transcripts or {})
    if not tblock:
        return None, "no_transcripts"
    header = f"Position: {position or '—'}\nClient: {client_name or '—'}\n\n"
    extracted, err = _call(_EXTRACT_SYSTEM, header + tblock, max_tokens=4000)
    if err:
        return None, err
    return _clean_facts(extracted.get("facts")), None


def score_jd(*, jd_html: str, transcripts: Dict[str, Any], position: str = "",
             client_name: str = "", facts: Optional[List[Dict[str, Any]]] = None
             ) -> Tuple[Optional[int], Optional[Dict[str, Any]], Optional[str]]:
    """Paso 2 (y el 1 si no vienen `facts`). Devuelve (score, analysis, error_code). Nunca levanta.

    `facts` es la lista guardada de una corrida anterior (ver facts_key). Se copia: el juez le
    agrega estado y puntos a cada hecho y la lista guardada tiene que quedar limpia.
    """
    jd_text = jd_html_to_text(jd_html)
    if not jd_text:
        return None, None, "no_jd"
    if not _transcripts_block(transcripts or {}):
        return None, None, "no_transcripts"

    header = f"Position: {position or '—'}\nClient: {client_name or '—'}\n\n"
    if facts is None:
        facts, err = extract_facts(transcripts=transcripts, position=position,
                                   client_name=client_name)
        if err:
            return None, None, err
    facts = json.loads(json.dumps(facts))
    for f in facts:
        f.setdefault("part_names", [f.get("fact") or ""])
    if not facts:
        analysis = _finalize([], [], jd_text, transcripts)
        return None, analysis, None

    facts_for_judge = [{"id": f["id"], "category": f["category"], "fact": f["fact"],
                        "parts": f["part_names"]} for f in facts]
    judge_user = (header
                  + "=== JOB DESCRIPTION ===\n" + _truncate(jd_text, JD_LIMIT)
                  + "\n\n=== FACTS FROM THE CALLS ===\n"
                  + json.dumps(facts_for_judge, ensure_ascii=False, indent=1))
    judged, err = _call(_JUDGE_SYSTEM, judge_user, max_tokens=7000)
    if err:
        return None, None, err

    by_id = {}
    for j in judged.get("facts") or []:
        if isinstance(j, dict) and j.get("id"):
            by_id[str(j["id"]).strip()] = j
    jd_mentions_pay = bool(_SALARY_RE.search(jd_text))
    for f in facts:
        j = by_id.get(f["id"]) or {}
        # Las partes son las del extractor; del juez sólo se toma el veredicto, por posición.
        # Una parte que el juez no devolvió cuenta como "no".
        got = [p for p in (j.get("parts") or []) if isinstance(p, dict)]
        parts = []
        for k, name in enumerate(f.pop("part_names")):
            p = got[k] if k < len(got) else {}
            v = str(p.get("in_jd") or "").strip().lower()
            parts.append({"part": name,
                          "in_jd": v if v in ("explicit", "implied") else "no",
                          "evidence": str(p.get("evidence") or "").strip()})
        f["parts"] = parts
        f["status"] = derive_status(parts, bool(j.get("contradicted")))
        q = str(j.get("jd_quote") or "").strip() or next(
            (p["evidence"] for p in parts if p["evidence"]), "")
        f["why"] = str(j.get("why") or "").strip()
        # Decisión de la owner (2026-09-25): en la JD nunca va el monto. Si la JD habla de la
        # paga en cualquier forma, el punto de salario está cubierto — lo decide el código y no
        # el juez, que igual lo marcaba partial o missing por no tener el número.
        if f.get("is_salary") and f["status"] != "contradicted" and jd_mentions_pay:
            f["status"] = "covered"
            f["why"] = ""
            if not q:
                m = re.search(r"[^\n.]*" + _SALARY_RE.pattern[4:] + r"[^\n.]*", jd_text, re.I)
                q = m.group(0).strip() if m else ""
        f["jd_quote"] = q if f["status"] != "missing" else ""
        f["jd_quote_found"] = _find_in_jd(f["jd_quote"], jd_text) if f["jd_quote"] else False

    unsupported = []
    for u in judged.get("unsupported") or []:
        if not isinstance(u, dict):
            continue
        q = str(u.get("jd_quote") or "").strip()
        if not q:
            continue
        sev = str(u.get("severity") or "").strip().lower()
        unsupported.append({
            "jd_quote": q,
            "jd_quote_found": _find_in_jd(q, jd_text),
            "severity": "hard" if sev == "hard" else "soft",
            "why": str(u.get("why") or "").strip(),
        })

    analysis = _finalize(facts, unsupported, jd_text, transcripts)
    return analysis["score"], analysis, None


def _finalize(facts, unsupported, jd_text, transcripts) -> Dict[str, Any]:
    summary = compute_score(facts, unsupported)
    verdict, verdict_why = derive_verdict(summary)
    have = [k for k in ("intro", "deep_dive") if ((transcripts or {}).get(k) or {}).get("text")]
    return {
        "score": summary["score"],
        "summary": summary,
        "verdict": verdict,
        "verdict_why": verdict_why,
        "facts": facts,
        "unsupported": unsupported,
        # Con una sola reunión el score mide contra lo que hay: lo que se habló en la otra no
        # se puede exigir. Se marca para que el drawer y el mail lo digan; SÍ entra al
        # promedio (muchas vacantes sólo tienen Intro cargada y excluirlas vaciaría la métrica).
        "sources": have,
        "_partial": len(have) < 2,
        "_score_basis": "no_facts" if summary["score"] is None else "",
        "_version": ANALYSIS_VERSION,
        "_jd_hash": input_hash(jd_text),
        "_jd_chars": len(jd_text),
    }
