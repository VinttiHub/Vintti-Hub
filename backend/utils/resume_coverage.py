"""Cobertura de la JD y CVs hermanos para el generador de CVs (`/generate_resume_fields`).

Dos quejas de las recruiters (2026-10-26) que el prompt solo no resolvía:

1. El CV se salteaba must-haves y tools de la JD. El prompt tiene ~580 líneas de reglas y
   ninguna le daba una LISTA concreta de qué buscar, ni había chequeo después.
2. Los CVs de una misma vacante salían clonados: "3 years of Python" en los tres, porque el
   modelo repetía el umbral del cliente en vez de los años de cada candidato, y no sabía
   nada de los CVs que ya se habían escrito para esa vacante.

El circuito es: `build_coverage_map()` (una llamada, antes de generar) lista cada must-have
con su evidencia en las fuentes y los años REALES del candidato; el prompt recibe ese
checklist y los CVs hermanos (`load_siblings()`); `check_draft()` revisa el borrador sin
modelo y, si algo falla, el endpoint hace UNA pasada de reparación con `repair_messages()`.

Un must-have sin evidencia NO se afirma (decisión de la owner): sale en el reporte como
"not_in_sources" para que la recruiter lo confirme en las notas y regenere.

Nada de esto levanta excepción hacia el endpoint: si OpenAI o la base fallan, el CV se
genera como antes, sin checklist.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from utils.cv_review_ai import _tool_find, optional_section_start, required_years

MODEL = "gpt-4o"
SOURCE_LIMIT = 40000        # chars de fuentes que ve el extractor de cobertura
MAX_SIBLINGS = 4
SIBLING_DAYS = 90
SHINGLE_SIBLING = 6         # frase compartida con un hermano = 6 palabras seguidas
SHINGLE_JD = 8              # con la JD se tolera más: "accounts payable and receivable" es keyword
MAX_ISSUES = 12

_tables_ready = False


# --------------------------------------------------------------------------- tablas

def _ensure_tables(cur) -> None:
    global _tables_ready
    if _tables_ready:
        return
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_generations (
            id SERIAL PRIMARY KEY,
            candidate_id INTEGER NOT NULL,
            opportunity_id INTEGER NOT NULL,
            about TEXT,
            work_experience TEXT,
            coverage JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS resume_generations_opp_idx "
        "ON resume_generations (opportunity_id, created_at DESC)"
    )
    _tables_ready = True


def record_generation(candidate_id, opportunity_id, about: str, work_experience: str,
                      coverage: Optional[Dict[str, Any]]) -> None:
    """Guarda el CV generado para esa vacante: es de donde salen los hermanos del próximo."""
    if not candidate_id or not opportunity_id:
        return
    from db import get_connection
    conn = None
    try:
        conn = get_connection()
        with conn:
            with conn.cursor() as cur:
                _ensure_tables(cur)
                cur.execute(
                    "INSERT INTO resume_generations "
                    "(candidate_id, opportunity_id, about, work_experience, coverage) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (int(candidate_id), int(opportunity_id), about or "",
                     work_experience or "", json.dumps(coverage) if coverage else None),
                )
    except Exception:
        logging.exception("resume_coverage: could not record generation")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# --------------------------------------------------------------------------- hermanos

def _plain(html: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(html or ""))
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def _bullets(description: Any) -> List[str]:
    raw = str(description or "")
    if "<li" in raw.lower():
        parts = re.findall(r"<li[^>]*>(.*?)</li>", raw, flags=re.I | re.S)
    else:
        parts = re.split(r"\n+", raw)
    out = []
    for p in parts:
        p = _plain(p).lstrip("-•* ").strip()
        if p:
            out.append(p)
    return out


def _work_list(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    return [e for e in (raw or []) if isinstance(e, dict)]


def load_siblings(opportunity_id, candidate_id) -> List[Dict[str, Any]]:
    """Los CVs de OTROS candidatos para esta vacante: About + bullets de los 2 roles recientes.

    Primero lo generado con esta vacante (`resume_generations`). Para los CVs escritos antes
    de que existiera la tabla, cae al `resume` actual de los candidatos que están en el
    pipeline de la vacante.
    """
    if not opportunity_id:
        return []
    from db import get_connection
    conn = None
    rows: List[Tuple[Any, Any, Any]] = []
    try:
        conn = get_connection()
        with conn:
            with conn.cursor() as cur:
                _ensure_tables(cur)
                cur.execute(
                    """
                    SELECT candidate_id, about, work_experience FROM (
                        SELECT DISTINCT ON (candidate_id) candidate_id, about,
                               work_experience, created_at
                        FROM resume_generations
                        WHERE opportunity_id = %s AND candidate_id <> %s
                          AND created_at >= NOW() - (%s || ' days')::interval
                        ORDER BY candidate_id, created_at DESC
                    ) t ORDER BY created_at DESC LIMIT %s
                    """,
                    (int(opportunity_id), int(candidate_id or 0), str(SIBLING_DAYS),
                     MAX_SIBLINGS),
                )
                rows = list(cur.fetchall())
                if len(rows) < MAX_SIBLINGS:
                    seen = [r[0] for r in rows] or [0]
                    cur.execute(
                        """
                        SELECT r.candidate_id, r.about, r.work_experience
                        FROM resume r
                        WHERE r.candidate_id IN (
                                SELECT oc.candidate_id FROM opportunity_candidates oc
                                WHERE oc.opportunity_id = %s)
                          AND r.candidate_id <> %s
                          AND NOT (r.candidate_id = ANY(%s))
                          AND NULLIF(TRIM(r.about), '') IS NOT NULL
                        LIMIT %s
                        """,
                        (int(opportunity_id), int(candidate_id or 0), seen,
                         MAX_SIBLINGS - len(rows)),
                    )
                    rows.extend(cur.fetchall())
    except Exception:
        logging.exception("resume_coverage: could not load sibling CVs")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    siblings = []
    for _cid, about, work in rows:
        bullets: List[str] = []
        for entry in _work_list(work)[:2]:
            bullets.extend(_bullets(entry.get("description"))[:3])
        about_txt = _plain(about)
        if about_txt or bullets:
            siblings.append({"about": about_txt, "bullets": bullets})
    return siblings


def siblings_prompt_block(siblings: List[Dict[str, Any]]) -> str:
    if not siblings:
        return ""
    parts = [
        "=========================",
        "OTHER CVs ALREADY WRITTEN FOR THIS SAME OPENING",
        "=========================",
        "The client will read these CVs side by side with yours. Below are excerpts of the",
        "other candidates' CVs. They are NOT source material for this candidate — never take a",
        "fact from them. They are here so this CV does not read like the same template:",
        "- Open the About differently: a different first words, a different sentence structure,",
        "  and lead with the strength that is MOST distinctive for THIS candidate.",
        "- Never reuse a phrase of 6 or more consecutive words from these excerpts.",
        "- When this candidate meets the same requirement as the others, tell it through what",
        "  THIS person did: the company, the project, the volume, the system, the numbers. Two",
        "  candidates who both know Python did different things with it — write the thing.",
        "",
    ]
    for i, sib in enumerate(siblings, 1):
        parts.append(f"CANDIDATE {chr(64 + i)} — About: {sib['about'][:700]}")
        for b in sib["bullets"][:5]:
            parts.append(f"  - {b[:300]}")
        parts.append("")
    return "\n".join(parts) + "\n"


# --------------------------------------------------------------------------- cobertura

def _must_have_jd(jd: str) -> str:
    jd = str(jd or "")
    cut = optional_section_start(jd)
    return jd[:cut] if cut else jd


def jd_required_years(target: Optional[Dict[str, Any]]) -> Optional[int]:
    """El umbral de años del cliente: el campo de la opp, o el que diga la JD."""
    if not target:
        return None
    m = re.search(r"\d+", str(target.get("years_experience") or ""))
    if m:
        return int(m.group(0))
    try:
        return required_years(_must_have_jd(target.get("jd") or ""))
    except Exception:
        return None


_COVERAGE_SYSTEM = (
    "You audit a candidate's source material against a job description's MUST-HAVE "
    "requirements. You are strict: evidence must come from the candidate's own material, "
    "never from the job description. Reply with one JSON object only."
)


def _coverage_user_prompt(target: Dict[str, Any], sources: str, today: str) -> str:
    return f"""TODAY: {today}

JOB — MUST-HAVE PART (nice-to-haves already removed):
Position: {target.get('position') or ''}
Years the client asked for: {target.get('years_experience') or 'not stated'}
---
{_must_have_jd(target.get('jd') or '')}
---

CANDIDATE SOURCE MATERIAL (CV, LinkedIn, call transcripts, recruiter notes):
---
{sources}
---

TASK
1. List every MUST-HAVE requirement of the job as ATOMIC items: each named tool/software/
   language is its own item (kind "tool"); "N years of X" is kind "years"; a hands-on
   skill or responsibility area is kind "skill"; an industry/domain is kind "domain".
   Skip soft skills (communication, teamwork, proactive) and logistics (time zone,
   availability, remote/hybrid/on-site, schedule, contract type, benefits, English level):
   those are conditions of the job, not experience a CV can show. Max 15 items, the most important first.
2. For each item, look ONLY in the candidate source material:
   - "found": the source clearly shows the candidate doing/using it.
   - "weak": only listed (a skills list) or loosely related, no role shows it in use.
   - "not_found": nothing in the source.
3. "evidence": up to 2 short items {{"company": ..., "role": ..., "quote": "<= 25 words copied
   from the source"}}. Empty list when not_found.
4. "candidate_years": for kind "years" (and for tools/skills when the dates allow it), the
   number of years THIS candidate has, computed from the start/end dates of the roles
   where the evidence is (current roles end at TODAY). Round down to a whole number.
   null when the dates do not allow it. NEVER copy the job's number.

Return:
{{"items": [{{"requirement": "Python", "kind": "tool", "status": "found",
  "evidence": [{{"company": "...", "role": "...", "quote": "..."}}],
  "candidate_years": 5}}]}}"""


def build_coverage_map(target: Optional[Dict[str, Any]], sources: str,
                       today: str) -> Optional[Dict[str, Any]]:
    """Must-haves de la JD con su evidencia en las fuentes. None sin JD o si falla."""
    if not target or not (target.get("jd") or "").strip():
        return None
    try:
        from ai_routes import call_openai_with_retry  # después de init_services()
        resp = call_openai_with_retry(
            MODEL,
            [{"role": "system", "content": _COVERAGE_SYSTEM},
             {"role": "user", "content": _coverage_user_prompt(
                 target, str(sources or "")[:SOURCE_LIMIT], today)}],
            temperature=0, max_tokens=3000,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content or "{}")
    except Exception:
        logging.exception("resume_coverage: coverage extraction failed; generating without it")
        return None

    items = []
    for it in data.get("items") or []:
        if not isinstance(it, dict) or not str(it.get("requirement") or "").strip():
            continue
        status = str(it.get("status") or "").lower()
        if status not in ("found", "weak", "not_found"):
            status = "not_found"
        years = it.get("candidate_years")
        try:
            years = int(years) if years is not None and str(years).strip() != "" else None
        except (TypeError, ValueError):
            years = None
        items.append({
            "requirement": str(it["requirement"]).strip()[:160],
            "kind": str(it.get("kind") or "skill").lower(),
            "status": status,
            "evidence": [e for e in (it.get("evidence") or []) if isinstance(e, dict)][:2],
            "candidate_years": years,
        })
    return {"items": items[:15], "jd_years": jd_required_years(target)}


def coverage_prompt_block(coverage: Optional[Dict[str, Any]]) -> str:
    if not coverage or not coverage.get("items"):
        return ""
    lines = [
        "=========================",
        "COVERAGE CHECKLIST — THE CLIENT'S MUST-HAVES, ALREADY MATCHED TO THIS CANDIDATE",
        "=========================",
        "Each must-have of the job was looked up in the source material for you. This list is",
        "the reason the CV is tailored — skipping a FOUND item is the most common complaint.",
        "- FOUND: it MUST appear in the CV, inside the bullets of the role named in the",
        "  evidence (and in the tools list if it is a tool), written with THIS candidate's own",
        "  facts: their company, project, volume, numbers. Never echo the job's sentence.",
        "- WEAK: include it only as far as the evidence goes (e.g. in the tools list), never",
        "  upgrade it into hands-on experience.",
        "- NOT FOUND: do NOT claim it anywhere. The recruiter is told it is missing.",
        "- YEARS: never write the job's number of years. If you mention years, use the",
        "  candidate's own figure below (computed from the role dates). If it is unknown, do",
        "  not state a number of years for that skill.",
        "",
    ]
    jd_years = coverage.get("jd_years")
    if jd_years:
        lines.append(f"(The client's threshold is {jd_years} years. That number is the client's, "
                     "not the candidate's — never copy it into the CV.)")
    for it in coverage["items"]:
        ev = "; ".join(
            f"{e.get('company') or '?'} / {e.get('role') or '?'}: \"{e.get('quote') or ''}\""
            for e in it["evidence"]
        )
        yrs = (f" | candidate's own years: {it['candidate_years']}"
               if it.get("candidate_years") is not None else "")
        lines.append(f"- [{it['status'].upper()}] {it['requirement']} ({it['kind']}){yrs}"
                     + (f" | evidence: {ev}" if ev else ""))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- chequeo

_WORD = re.compile(r"[a-z0-9][a-z0-9+#.\-]*")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years|yrs)\b", re.I)


def _tokens(text: str) -> List[str]:
    return _WORD.findall(str(text or "").lower())


def _shingles(text: str, n: int) -> set:
    toks = _tokens(text)
    return {" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def _draft_sentences(draft: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(dónde, oración) del borrador: About partido en oraciones + cada bullet."""
    out: List[Tuple[str, str]] = []
    about = _plain(draft.get("about"))
    for s in _SENT_SPLIT.split(about):
        if s.strip():
            out.append(("About", s.strip()))
    for entry in _work_list(draft.get("work_experience")):
        where = f"{entry.get('title') or ''} @ {entry.get('company') or ''}".strip()
        for b in _bullets(entry.get("description")):
            out.append((where, b))
    return out


def check_draft(draft: Dict[str, Any], coverage: Optional[Dict[str, Any]],
                siblings: List[Dict[str, Any]], jd: str) -> Dict[str, Any]:
    """Revisión sin modelo. Devuelve {"issues": [...], "missing_tools": [...]}."""
    issues: List[str] = []
    missing_tools: List[str] = []
    sentences = _draft_sentences(draft)
    work_text = " \n ".join(s for w, s in sentences if w != "About")
    tools_text = " \n ".join(
        str(t.get("tool") or "") for t in (draft.get("tools") or []) if isinstance(t, dict)
    )

    items = (coverage or {}).get("items") or []
    # 1) Tools con evidencia que el CV no muestra.
    for it in items:
        if it["kind"] != "tool" or it["status"] != "found":
            continue
        if _tool_find(it["requirement"], work_text) is None:
            missing_tools.append(it["requirement"])
            where = (it["evidence"][0].get("company") if it["evidence"] else "") or "the role in the evidence"
            in_list = _tool_find(it["requirement"], tools_text) is not None
            issues.append(
                f"MISSING MUST-HAVE: '{it['requirement']}' is required by the client and the "
                f"source shows the candidate using it, but no bullet mentions it. Add it to a "
                f"bullet of the {where} role, grounded in the evidence"
                + ("" if in_list else ", and add it to the tools list") + "."
            )

    # 2) El número de años del cliente copiado al CV.
    jd_years = (coverage or {}).get("jd_years")
    real_years = {it["candidate_years"] for it in items if it.get("candidate_years") is not None}
    if jd_years:
        for where, s in sentences:
            for m in _YEARS_RE.finditer(s):
                n = int(m.group(1))
                if n == jd_years and n not in real_years:
                    fix = (f"use the candidate's own figure ({', '.join(str(y) for y in sorted(real_years))})"
                           if real_years else "remove the number of years")
                    issues.append(
                        f"COPIED THRESHOLD in {where}: \"{s}\" states {n} years, which is the "
                        f"client's requirement, not this candidate's. Rewrite it and {fix}."
                    )

    # 3) Frases compartidas con los hermanos o calcadas de la JD.
    sib_grams = set()
    for sib in siblings or []:
        sib_grams |= _shingles(sib["about"] + " " + " ".join(sib["bullets"]), SHINGLE_SIBLING)
    jd_grams = _shingles(jd or "", SHINGLE_JD)
    for where, s in sentences:
        if sib_grams and _shingles(s, SHINGLE_SIBLING) & sib_grams:
            issues.append(
                f"SAME AS ANOTHER CANDIDATE in {where}: \"{s}\" repeats wording from another "
                f"CV sent for this opening. Rewrite it around what THIS candidate specifically did."
            )
        elif jd_grams and _shingles(s, SHINGLE_JD) & jd_grams:
            issues.append(
                f"COPIED FROM THE JOB DESCRIPTION in {where}: \"{s}\". Keep the facts, rewrite "
                f"it in the candidate's own terms."
            )

    # La primera frase del About con la misma apertura que un hermano (3 palabras).
    about_first = _tokens(_plain(draft.get("about")))[:3]
    if about_first and any(_tokens(sib["about"])[:3] == about_first for sib in siblings or []):
        issues.append(
            "SAME ABOUT OPENING as another candidate for this opening. Start the About with "
            "different words and lead with this candidate's most distinctive strength."
        )

    return {"issues": issues[:MAX_ISSUES], "missing_tools": missing_tools}


def repair_messages(draft: Dict[str, Any], issues: List[str], coverage_block: str,
                    siblings_block: str, system_prompt: str) -> List[Dict[str, str]]:
    body = f"""Below is a CV draft (JSON) that failed a review. Fix ONLY the listed problems and
return the COMPLETE corrected JSON object with the same five keys and the same shape. Do not
touch anything else: same roles, same dates, same education, same languages, same bullet
count unless a fix requires adding a fact to an existing bullet.

All original rules still apply. Above all: NO FABRICATION. A missing must-have may only be
added using the evidence quoted in the checklist; if the evidence does not support it,
leave it out.

PROBLEMS TO FIX:
{chr(10).join('- ' + i for i in issues)}

{coverage_block}
{siblings_block}
DRAFT:
{json.dumps(draft, ensure_ascii=False)}"""
    return [{"role": "system", "content": system_prompt},
            {"role": "user", "content": body}]


def coverage_report(coverage: Optional[Dict[str, Any]], final_check: Optional[Dict[str, Any]],
                    repaired: bool) -> Optional[Dict[str, Any]]:
    """Lo que ve la recruiter en el popup."""
    if not coverage or not coverage.get("items"):
        return None
    still_missing = set((final_check or {}).get("missing_tools") or [])
    covered, weak, absent = [], [], []
    for it in coverage["items"]:
        if it["status"] == "not_found":
            absent.append(it["requirement"])
        elif it["status"] == "weak" or it["requirement"] in still_missing:
            weak.append(it["requirement"])
        else:
            covered.append(it["requirement"])
    return {"covered": covered, "weak": weak, "not_in_sources": absent,
            "repaired": bool(repaired),
            "open_issues": len((final_check or {}).get("issues") or [])}
