import json
import math
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


_STOPWORDS = {
    "a", "about", "across", "after", "all", "also", "an", "and", "any", "are", "as", "at",
    "backend", "be", "been", "before", "both", "by", "candidate", "company", "con", "current",
    "de", "del", "desarrollo", "desarrollador", "developer", "development", "el", "en", "engineer",
    "engineering", "experience", "experiencia", "for", "from", "full", "have", "in", "is", "it",
    "job", "la", "lead", "los", "management", "manager", "more", "of", "on", "or", "para",
    "por", "product", "project", "que", "role", "senior", "software", "stack", "team", "the",
    "this", "to", "un", "una", "with", "work", "worked", "working", "years", "y",
}

_MONTHS = {
    "jan": 1, "january": 1, "ene": 1, "enero": 1,
    "feb": 2, "february": 2, "febrero": 2,
    "mar": 3, "march": 3, "marzo": 3,
    "apr": 4, "april": 4, "abr": 4, "abril": 4,
    "may": 5, "mayo": 5,
    "jun": 6, "june": 6, "junio": 6,
    "jul": 7, "july": 7, "julio": 7,
    "aug": 8, "august": 8, "ago": 8, "agosto": 8,
    "sep": 9, "sept": 9, "september": 9, "septiembre": 9,
    "oct": 10, "october": 10, "octubre": 10,
    "nov": 11, "november": 11, "noviembre": 11,
    "dec": 12, "december": 12, "dic": 12, "diciembre": 12,
}

_PRESENT_TOKENS = {"present", "current", "now", "actualidad", "hoy", "presente"}

_ROLE_KEYWORDS = {
    "frontend", "backend", "fullstack", "full", "stack", "react", "python", "javascript", "java",
    "node", "qa", "tester", "devops", "data", "analyst", "analysis", "designer", "ux", "ui",
    "accountant", "sales", "recruiter", "sourcer", "bdr", "sdr", "operations", "marketing",
}

_INDUSTRY_KEYWORDS = {
    "fintech", "saas", "ecommerce", "healthcare", "education", "staffing", "recruiting",
    "outsourcing", "logistics", "retail", "manufacturing", "software", "agency", "startup",
}


def normalize_ascii(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def compact_whitespace(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def tokenize(value: Any) -> List[str]:
    text = normalize_ascii(value)
    if not text:
        return []
    tokens = re.findall(r"[a-z0-9][a-z0-9.+#/-]{1,}", text)
    return [token for token in tokens if token not in _STOPWORDS and len(token) > 1]


def keyword_set(*chunks: Any) -> Set[str]:
    tokens: Set[str] = set()
    for chunk in chunks:
        tokens.update(tokenize(chunk))
    return tokens


def extract_keywords(text: Any, limit: int = 24) -> List[str]:
    counts: Dict[str, int] = {}
    for token in tokenize(text):
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [token for token, _count in ranked[:limit]]


def parse_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def _resolve_month(token: str) -> Optional[int]:
    return _MONTHS.get(normalize_ascii(token))


def _to_month_index(year: int, month: int) -> int:
    return year * 12 + max(1, min(month, 12)) - 1


def _merge_ranges(ranges: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    ordered = sorted((item for item in ranges if item[0] <= item[1]), key=lambda item: item[0])
    if not ordered:
        return []
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + 1:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def estimate_years_experience(text: Any) -> Optional[float]:
    clean = normalize_ascii(text)
    if not clean:
        return None

    now = datetime.utcnow()
    now_year = now.year
    now_month = now.month
    ranges: List[Tuple[int, int]] = []

    year_range = re.compile(r"\b((?:19|20)\d{2})\b\s*(?:-|–|—|to|a|hasta)\s*((?:19|20)\d{2}|present|current|actualidad|hoy)")
    for match in year_range.finditer(clean):
        start_year = int(match.group(1))
        end_token = match.group(2)
        if end_token in _PRESENT_TOKENS:
            end_year = now_year
            end_month = now_month
        else:
            end_year = int(end_token)
            end_month = 12
        ranges.append((_to_month_index(start_year, 1), _to_month_index(end_year, end_month)))

    month_year_range = re.compile(
        r"\b([a-z]{3,10})\s+((?:19|20)\d{2})\b\s*(?:-|–|—|to|a|hasta)\s*(?:([a-z]{3,10})\s+)?((?:19|20)\d{2}|present|current|actualidad|hoy)"
    )
    for match in month_year_range.finditer(clean):
        start_month = _resolve_month(match.group(1))
        start_year = int(match.group(2))
        end_month_token = match.group(3)
        end_token = match.group(4)
        if not start_month:
            continue
        if end_token in _PRESENT_TOKENS:
            end_year = now_year
            end_month = now_month
        else:
            end_year = int(end_token)
            end_month = _resolve_month(end_month_token or "") or 12
        ranges.append((_to_month_index(start_year, start_month), _to_month_index(end_year, end_month)))

    numeric_range = re.compile(
        r"\b(\d{1,2})[/-]((?:19|20)\d{2})\b\s*(?:-|–|—|to|a|hasta)\s*(?:(\d{1,2})[/-])?((?:19|20)\d{2}|present|current|actualidad|hoy)"
    )
    for match in numeric_range.finditer(clean):
        start_month = int(match.group(1))
        start_year = int(match.group(2))
        end_month_token = match.group(3)
        end_token = match.group(4)
        if end_token in _PRESENT_TOKENS:
            end_year = now_year
            end_month = now_month
        else:
            end_year = int(end_token)
            end_month = int(end_month_token or 12)
        ranges.append((_to_month_index(start_year, start_month), _to_month_index(end_year, end_month)))

    merged = _merge_ranges(ranges)
    if merged:
        total_months = sum((end - start + 1) for start, end in merged)
        return round(total_months / 12, 1)

    explicit_years = re.findall(r"(\d+(?:\.\d+)?)\+?\s+(?:years|year|anos|ano)", clean)
    if explicit_years:
        try:
            return max(float(value) for value in explicit_years)
        except Exception:
            return None
    return None


def overlap_ratio(left: Set[str], right: Set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = left.intersection(right)
    base = min(len(left), len(right)) or 1
    return len(overlap) / base


def match_strength(candidate_value: Any, target_value: Any, fallback_text: Any = "") -> Optional[int]:
    target = normalize_ascii(target_value)
    if not target:
        return None

    haystack = normalize_ascii(candidate_value)
    combined = " ".join(part for part in [haystack, normalize_ascii(fallback_text)] if part).strip()
    if not combined:
        return 0
    if target in combined:
        return 2
    tokens = [token for token in re.split(r"[\s,;/|-]+", target) if token]
    if not tokens:
        return 0
    return 1 if any(token in combined for token in tokens) else 0


def match_years(candidate_years: Optional[float], target_years: Optional[float]) -> Optional[int]:
    if target_years is None:
        return None
    if candidate_years is None:
        return 0
    if candidate_years >= target_years:
        return 2
    if target_years - candidate_years <= 2:
        return 1
    return 0


def build_candidate_profile(extracted_pdf: str, applicant_location: str = "") -> Dict[str, Any]:
    text = compact_whitespace(extracted_pdf)
    keywords = extract_keywords(text, limit=30)
    token_set = keyword_set(text)
    role = next((token for token in keywords if token in _ROLE_KEYWORDS), "")
    industry = next((token for token in keywords if token in _INDUSTRY_KEYWORDS), "")
    years = estimate_years_experience(text)
    return {
        "text": text[:12000],
        "keywords": keywords,
        "token_set": token_set,
        "role_hint": role,
        "industry_hint": industry,
        "location": compact_whitespace(applicant_location),
        "years_experience": years,
    }


def build_job_profile(
    job_description: str,
    filters: Optional[Dict[str, Any]] = None,
    opportunity_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    filters = filters or {}
    opportunity_context = opportunity_context or {}
    text = compact_whitespace(job_description)
    keywords = extract_keywords(text, limit=30)

    position = compact_whitespace(filters.get("position") or opportunity_context.get("position") or "")
    country = compact_whitespace(filters.get("country") or opportunity_context.get("career_country") or "")
    years = parse_number(filters.get("years_experience") or opportunity_context.get("years_experience"))
    industry = compact_whitespace(filters.get("industry") or "")
    salary = compact_whitespace(filters.get("salary") or "")

    return {
        "text": text[:8000],
        "keywords": keywords,
        "token_set": keyword_set(text, position, country, industry),
        "position": position,
        "country": country,
        "industry": industry,
        "salary": salary,
        "years_experience": years,
    }


def _score_to_percent(score: int) -> int:
    bounded = max(1, min(10, int(score)))
    return int(round((bounded / 10) * 100))


def _strength_to_percent(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    if value <= 0:
        return 0
    if value == 1:
        return 60
    return 100


def _detail_for_strength(value: Optional[int], match_text: str, close_text: str, miss_text: str, missing_text: str) -> str:
    if value is None:
        return missing_text
    if value == 2:
        return match_text
    if value == 1:
        return close_text
    return miss_text


def score_candidate_against_job(
    extracted_pdf: str,
    applicant_location: str,
    job_description: str,
    filters: Optional[Dict[str, Any]] = None,
    opportunity_context: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[int], Optional[str]]:
    if not compact_whitespace(extracted_pdf):
        return None, None

    candidate = build_candidate_profile(extracted_pdf, applicant_location)
    job = build_job_profile(job_description, filters=filters, opportunity_context=opportunity_context)

    jd_overlap = overlap_ratio(candidate["token_set"], job["token_set"])
    jd_percent = max(15, min(100, int(round(jd_overlap * 100)))) if job["token_set"] else 50

    position_strength = match_strength(candidate["role_hint"], job["position"], candidate["text"])
    industry_strength = match_strength(candidate["industry_hint"], job["industry"], candidate["text"])
    location_strength = match_strength(candidate["location"], job["country"], candidate["text"])
    years_strength = match_years(candidate["years_experience"], job["years_experience"])

    weights = [
        ("jd", jd_percent, 0.45),
        ("position", _strength_to_percent(position_strength), 0.2),
        ("industry", _strength_to_percent(industry_strength), 0.1),
        ("location", _strength_to_percent(location_strength), 0.15),
        ("years", _strength_to_percent(years_strength), 0.1),
    ]

    weighted_total = 0.0
    used_weight = 0.0
    for _name, percent, weight in weights:
        if percent is None:
            continue
        weighted_total += percent * weight
        used_weight += weight
    overall_percent = int(round(weighted_total / used_weight)) if used_weight else jd_percent
    score = max(1, min(10, int(round(overall_percent / 10))))

    keyword_overlap = sorted(candidate["token_set"].intersection(job["token_set"]))
    if keyword_overlap:
        overlap_snippet = ", ".join(keyword_overlap[:8])
        jd_detail = f"Se detectó coincidencia entre CV y JD en palabras clave como {overlap_snippet}."
    else:
        jd_detail = "La coincidencia con la JD es limitada porque el CV comparte pocas palabras clave explícitas con la vacante."

    missing_bits = []
    if job["position"] and position_strength == 0:
        missing_bits.append(f"posición '{job['position']}'")
    if job["industry"] and industry_strength == 0:
        missing_bits.append(f"industria '{job['industry']}'")
    if job["country"] and location_strength == 0:
        missing_bits.append(f"ubicación '{job['country']}'")
    if job["years_experience"] and years_strength == 0:
        missing_bits.append(f"{int(math.ceil(job['years_experience']))} años de experiencia")

    if missing_bits:
        gap_sentence = f"Hay brechas visibles respecto a {', '.join(missing_bits[:3])}."
    else:
        gap_sentence = "No se observan brechas críticas en los filtros definidos."

    years_label = (
        f"El CV sugiere aproximadamente {candidate['years_experience']} años de experiencia."
        if candidate["years_experience"] is not None
        else "No se pudo estimar con precisión la experiencia total desde el CV."
    )

    summary = f"{jd_detail} {gap_sentence} {years_label}".strip()

    reasons_payload = {
        "summary": summary,
        "overall_percent": overall_percent,
        "breakdown": [
            {
                "category": "Ubicación",
                "percent": _strength_to_percent(location_strength),
                "detail": _detail_for_strength(
                    location_strength,
                    "La ubicación del candidato está alineada con la vacante.",
                    "La ubicación parece cercana o parcialmente compatible con la vacante.",
                    "La ubicación del candidato no coincide con la definida para la vacante.",
                    "La vacante no define ubicación o no se pudo validar con el CV.",
                ),
            },
            {
                "category": "Similitud con la JD",
                "percent": jd_percent,
                "detail": f"{jd_detail} {gap_sentence}",
            },
            {
                "category": "Posición (filtro)",
                "percent": _strength_to_percent(position_strength),
                "detail": _detail_for_strength(
                    position_strength,
                    "El CV menciona una posición claramente alineada con el rol buscado.",
                    "El CV muestra una posición o funciones similares al rol buscado.",
                    "No se encontró una posición claramente alineada con el rol buscado.",
                    "La vacante no define un título específico para evaluar.",
                ),
            },
            {
                "category": "Industria (filtro)",
                "percent": _strength_to_percent(industry_strength),
                "detail": _detail_for_strength(
                    industry_strength,
                    "El CV incluye experiencia en la industria requerida.",
                    "El CV muestra señales parciales de la industria requerida.",
                    "No se encontró evidencia clara de la industria requerida.",
                    "La vacante no define una industria específica para evaluar.",
                ),
            },
            {
                "category": "Años de experiencia (filtro)",
                "percent": _strength_to_percent(years_strength),
                "detail": (
                    "Cumple con el nivel de experiencia solicitado."
                    if years_strength == 2 else
                    "La experiencia está cerca del umbral solicitado."
                    if years_strength == 1 else
                    f"No alcanza o no demuestra claramente los {job['years_experience']} años solicitados."
                    if years_strength == 0 else
                    "La vacante no define años de experiencia para evaluar."
                ),
            },
            {
                "category": "Salario (filtro)",
                "percent": None,
                "detail": "No se evaluó salario porque este flujo aún no extrae expectativa salarial del CV.",
            },
            {
                "category": "País (filtro)",
                "percent": _strength_to_percent(location_strength),
                "detail": _detail_for_strength(
                    location_strength,
                    "El país del candidato coincide con el filtro definido.",
                    "El país parece cercano o parcialmente compatible con el filtro definido.",
                    "El país del candidato no coincide con el filtro definido.",
                    "No hay país definido para esta evaluación.",
                ),
            },
        ],
        "meta": {
            "analysis_version": 2,
            "candidate_keywords": candidate["keywords"][:15],
            "job_keywords": job["keywords"][:15],
        },
    }

    return score, json.dumps(reasons_payload, ensure_ascii=False)
