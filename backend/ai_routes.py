from flask import Flask, jsonify, request
import os
from typing import Any, Dict, Optional
from dotenv import load_dotenv
from botocore.exceptions import NoCredentialsError
from affinda import AffindaAPI, TokenCredential
import openai
import traceback
import logging
import json
import time
import unicodedata
from flask import Flask, jsonify, request
import requests
import re
import datetime
import io, tempfile
from openai import OpenAI
from flask import request, jsonify
import logging
import traceback
import openai
import json
from db import get_connection 
import time
import re
from flask import jsonify, request
from openai import OpenAI
from PyPDF2 import PdfReader 
from urllib.parse import parse_qs, urlparse
from utils.applicant_matching import score_candidate_against_job

openai.api_key = os.getenv("OPENAI_API_KEY")

RESUME_LINKEDIN_SOURCE_LIMIT = 60000
RESUME_CV_SOURCE_LIMIT = 80000
# Límite para los editores por sección (/ai/improve_*). Antes cortaban a 2000 chars, o sea
# el encabezado y el primer trabajo: el modelo no veía los roles de abajo y "completaba".
# 30k alcanza para un CV entero + perfil de LinkedIn sin volar el costo de cada click.
RESUME_SECTION_EDITOR_SOURCE_LIMIT = 30000
RESUME_NOTES_LIMIT = 8000
RESUME_SOURCE_CHUNK_SIZE = 12000
RESUME_SOURCE_MAX_CHUNKS = 8

# Cuánta job description se inyecta en el prompt del CV, y topes de salida.
RESUME_JD_LIMIT = 6000
RESUME_ABOUT_LIMIT = 1500
RESUME_MAX_TOOLS = 15
RESUME_MAX_LANGUAGES = 6

# El <select> de idiomas en docs/assets/js/resume.js sólo ofrece estos cinco.
# Cualquier otro nombre no matchea ninguna opción, la fila no valida y la
# sección languages nunca se guarda — así que filtramos acá.
RESUME_LANGUAGE_ALIASES = {
    "english": "English", "ingles": "English", "inglés": "English",
    "spanish": "Spanish", "espanol": "Spanish", "español": "Spanish",
    "castellano": "Spanish",
    "portuguese": "Portuguese", "portugues": "Portuguese",
    "português": "Portuguese", "brazilian portuguese": "Portuguese",
    "portuguese (brazil)": "Portuguese", "portuguese (brazilian)": "Portuguese",
    "french": "French", "frances": "French", "francés": "French",
    "français": "French",
    "german": "German", "aleman": "German", "alemán": "German",
    "deutsch": "German",
}

_COUNTRY_ALIASES = {
    "Afghanistan": ["afghanistan"],
    "Albania": ["albania"],
    "Algeria": ["algeria"],
    "Andorra": ["andorra"],
    "Angola": ["angola"],
    "Argentina": ["argentina"],
    "Armenia": ["armenia"],
    "Australia": ["australia"],
    "Austria": ["austria"],
    "Azerbaijan": ["azerbaijan"],
    "Bahamas": ["bahamas"],
    "Bahrain": ["bahrain"],
    "Bangladesh": ["bangladesh"],
    "Barbados": ["barbados"],
    "Belarus": ["belarus"],
    "Belgium": ["belgium"],
    "Belize": ["belize"],
    "Benin": ["benin"],
    "Bhutan": ["bhutan"],
    "Bolivia": ["bolivia"],
    "Bosnia and Herzegovina": ["bosnia and herzegovina", "bosnia"],
    "Brazil": ["brazil", "brasil"],
    "Bulgaria": ["bulgaria"],
    "Cambodia": ["cambodia"],
    "Cameroon": ["cameroon"],
    "Canada": ["canada"],
    "Chile": ["chile"],
    "China": ["china"],
    "Colombia": ["colombia"],
    "Costa Rica": ["costa rica"],
    "Croatia": ["croatia"],
    "Cuba": ["cuba"],
    "Cyprus": ["cyprus"],
    "Czech Republic": ["czech republic", "czechia"],
    "Denmark": ["denmark"],
    "Dominican Republic": ["dominican republic"],
    "Ecuador": ["ecuador"],
    "Egypt": ["egypt"],
    "El Salvador": ["el salvador"],
    "Estonia": ["estonia"],
    "Ethiopia": ["ethiopia"],
    "Finland": ["finland"],
    "France": ["france"],
    "Georgia": ["georgia"],
    "Germany": ["germany", "deutschland"],
    "Ghana": ["ghana"],
    "Greece": ["greece"],
    "Guatemala": ["guatemala"],
    "Honduras": ["honduras"],
    "Hungary": ["hungary"],
    "Iceland": ["iceland"],
    "India": ["india"],
    "Indonesia": ["indonesia"],
    "Ireland": ["ireland"],
    "Israel": ["israel"],
    "Italy": ["italy", "italia"],
    "Jamaica": ["jamaica"],
    "Japan": ["japan"],
    "Jordan": ["jordan"],
    "Kazakhstan": ["kazakhstan"],
    "Kenya": ["kenya"],
    "Kuwait": ["kuwait"],
    "Latvia": ["latvia"],
    "Lebanon": ["lebanon"],
    "Lithuania": ["lithuania"],
    "Luxembourg": ["luxembourg"],
    "Malaysia": ["malaysia"],
    "Malta": ["malta"],
    "Mexico": ["mexico", "méxico"],
    "Morocco": ["morocco"],
    "Netherlands": ["netherlands", "holland"],
    "New Zealand": ["new zealand"],
    "Nicaragua": ["nicaragua"],
    "Nigeria": ["nigeria"],
    "Norway": ["norway"],
    "Pakistan": ["pakistan"],
    "Panama": ["panama"],
    "Paraguay": ["paraguay"],
    "Peru": ["peru", "perú"],
    "Philippines": ["philippines"],
    "Poland": ["poland"],
    "Portugal": ["portugal"],
    "Puerto Rico": ["puerto rico"],
    "Qatar": ["qatar"],
    "Romania": ["romania"],
    "Russia": ["russia"],
    "Saudi Arabia": ["saudi arabia"],
    "Serbia": ["serbia"],
    "Singapore": ["singapore"],
    "Slovakia": ["slovakia"],
    "Slovenia": ["slovenia"],
    "South Africa": ["south africa"],
    "South Korea": ["south korea", "korea"],
    "Spain": ["spain", "espana", "españa"],
    "Sweden": ["sweden"],
    "Switzerland": ["switzerland"],
    "Taiwan": ["taiwan"],
    "Thailand": ["thailand"],
    "Turkey": ["turkey", "turkiye", "türkiye"],
    "Ukraine": ["ukraine"],
    "United Arab Emirates": ["united arab emirates", "uae"],
    "United Kingdom": ["united kingdom", "uk", "england", "scotland", "wales"],
    "United States": ["united states", "usa", "u.s.", "u.s.a.", "united states of america"],
    "Uruguay": ["uruguay"],
    "Venezuela": ["venezuela"],
    "Vietnam": ["vietnam"],
}

_EDUCATION_LOCATION_HINTS = [
    ("Spain", ["barcelona", "madrid", "catalunya", "cataluna", "catalonia"]),
    ("Ecuador", ["loja", "quito", "guayaquil"]),
    ("Italy", ["rome", "roma", "milan", "milano"]),
    ("Colombia", ["medellin", "bogota", "antioquia", "sena"]),
    ("Australia", ["sydney", "melbourne"]),
    ("Canada", ["vancouver", "toronto", "montreal"]),
    ("Mexico", ["aguascalientes", "monterrey", "guadalajara"]),
    ("United States", ["new york", "miami", "california", "texas"]),
]

# arriba de tu archivo (imports)
from openai import OpenAI
from PyPDF2 import PdfReader  # fallback local


def _normalize_filter_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _extract_inline_filter(message: str, labels) -> str:
    if isinstance(labels, str):
        labels = [labels]
    pattern = r"(?:^|[\n,;])\s*(?:" + "|".join(re.escape(label) for label in labels) + r")\s*:\s*([^\n,;]+)"
    match = re.search(pattern, message, flags=re.I)
    return _normalize_filter_text(match.group(1)) if match else ""


def _parse_filters_without_ai(message: str, current_filters: Optional[Dict[str, Any]] = None):
    current_filters = dict(current_filters or {})
    normalized_current = {
        "position": _normalize_filter_text(current_filters.get("position")),
        "salary": _normalize_filter_text(current_filters.get("salary")),
        "years_experience": _normalize_filter_text(current_filters.get("years_experience")),
        "industry": _normalize_filter_text(current_filters.get("industry")),
        "country": _normalize_filter_text(current_filters.get("country")),
    }
    updated = dict(normalized_current)
    raw = _normalize_filter_text(message)
    if not raw:
        return updated, "", False

    lower = raw.lower()
    changed = []

    direct_map = {
        "position": ["position", "role", "title", "puesto", "posicion", "posición"],
        "salary": ["salary", "compensation", "salario"],
        "years_experience": ["years", "experience", "años", "anos", "years_experience"],
        "industry": ["industry", "industria"],
        "country": ["country", "location", "pais", "país", "ubicacion", "ubicación"],
    }

    for field, labels in direct_map.items():
        value = _extract_inline_filter(raw, labels)
        if value:
            updated[field] = value
            changed.append(field)

    clear_targets = {
        "position": ["remove position", "clear position", "sin posicion", "sin posición", "remove role"],
        "salary": ["remove salary", "clear salary", "sin salario"],
        "years_experience": ["remove years", "clear years", "sin anos", "sin años", "remove experience"],
        "industry": ["remove industry", "clear industry", "sin industria"],
        "country": ["remove country", "clear country", "sin pais", "sin país", "remove location"],
    }
    for field, phrases in clear_targets.items():
        if any(phrase in lower for phrase in phrases):
            updated[field] = ""
            changed.append(field)

    year_match = re.search(r"(\d+(?:\s*-\s*\d+)?\+?)\s*(?:years?|anos?|años?)", lower, flags=re.I)
    if year_match and not updated["years_experience"]:
        updated["years_experience"] = _normalize_filter_text(year_match.group(0))
        changed.append("years_experience")

    if "latam" in lower and not updated["country"]:
        updated["country"] = "LATAM"
        changed.append("country")

    countries = ["mexico", "brazil", "argentina", "colombia", "peru", "chile", "uruguay", "ecuador", "united states", "canada"]
    if not updated["country"]:
        for country in countries:
            if country in lower:
                updated["country"] = country.title() if country != "united states" else "United States"
                changed.append("country")
                break

    industries = ["saas", "fintech", "healthcare", "ecommerce", "staffing", "recruiting", "logistics", "education"]
    if not updated["industry"]:
        for industry in industries:
            if industry in lower:
                updated["industry"] = industry.upper() if industry == "saas" else industry.title()
                changed.append("industry")
                break

    known_roles = [
        "account executive", "business development representative", "bdr", "sdr",
        "recruiter", "backend engineer", "frontend engineer", "fullstack engineer",
        "software engineer", "data analyst", "project manager",
    ]
    if not updated["position"]:
        for role in known_roles:
            if role in lower:
                updated["position"] = role.title()
                changed.append("position")
                break

    changed = list(dict.fromkeys(changed))
    if changed:
        labels = ", ".join(changed)
        return updated, f"Listo, actualicé: {labels}.", False

    mentions_filter_words = any(word in lower for word in ["position", "role", "title", "country", "location", "industry", "salary", "years", "experience", "filtro", "filter"])
    if not mentions_filter_words:
        return updated, "No vi cambios concretos en filtros, así que mantuve los actuales.", False

    return updated, "", True

def _local_pdf_text_is_usable(local_text: str) -> bool:
    """¿El texto que sacó PyPDF sirve, o hay que pedirle el PDF al modelo?

    El umbral anterior era `len >= 300`, y ese era el problema: en un CV
    diseñado (multi-columna, títulos con letra espaciada, cajas de texto)
    PyPDF devuelve 800-3000 caracteres fragmentados y desordenados. Cruzaba
    los 300, el fallback nunca corría, y el generador recibía basura que
    después tenía que esquivar con lenguaje defensivo.
    """
    text = (local_text or "").strip()
    if len(text) < 1200:
        return False

    words = re.findall(r"[A-Za-zÀ-ÿ]+", text)
    if len(words) < 150:
        return False

    # Un CV real trae fechas o encabezados de sección reconocibles.
    has_dates = len(re.findall(r"\b(?:19|20)\d{2}\b", text)) >= 2
    has_sections = len(re.findall(
        r"\b(experience|education|skills|work|university|degree|profile|summary|"
        r"experiencia|educacion|educación|habilidades|formacion|formación)\b",
        text, re.IGNORECASE)) >= 2
    if not (has_dates or has_sections):
        return False

    alpha = sum(1 for ch in text if ch.isalpha())
    if alpha / max(len(text), 1) < 0.6:
        return False

    # "E x p e r i e n c e": si demasiados tokens son de un solo carácter,
    # el PDF salió con letter-spacing y el texto es inservible.
    tokens = text.split()
    if tokens:
        singles = sum(1 for t in tokens if len(t) == 1)
        if singles / len(tokens) > 0.25:
            return False

    return True

def _extract_pdf_text_with_openai(pdf_bytes: bytes, prompt_hint: str = "") -> str:
    """
    Intenta extraer texto localmente primero para evitar costo.
    Solo usa OpenAI como fallback cuando el PDF no trae texto suficiente.
    """
    local_text = ""
    try:
        with io.BytesIO(pdf_bytes) as bio:
            reader = PdfReader(bio)
            raw = []
            for idx, page in enumerate(reader.pages, start=1):
                page_text = (page.extract_text() or "").strip()
                if page_text:
                    cleaned_lines = [
                        re.sub(r"[ \t]+", " ", line).strip()
                        for line in page_text.splitlines()
                    ]
                    cleaned_page = "\n".join(line for line in cleaned_lines if line)
                    raw.append(f"--- PAGE {idx} ---\n{cleaned_page}")
            local_text = "\n\n".join(raw).strip()
    except Exception as e:
        logging.error(f"❌ Local PDF read failed: {e}")

    if _local_pdf_text_is_usable(local_text):
        logging.info(
            "pdf_extract: local=%s model=skipped used=local", len(local_text)
        )
        return local_text

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(pdf_bytes)
            tmp.flush()
            up = client.files.create(file=open(tmp.name, "rb"), purpose="assistants")
    except Exception as e:
        logging.error(f"❌ Upload to OpenAI Files failed: {e}")
        up = None

    # --- prompt para extracción “vision”/file-aware ---
    base_prompt = (
        "You are a rigorous CV parser. Read the attached PDF and return ONLY clean plain text in English, "
        "no markdown, no tables, no JSON. Include full name (if present), contacts, headline/summary, skills/tools, "
        "work experience with titles, companies, locations, date ranges, responsibilities, "
        "education (degrees, institutions, dates), certifications, languages. "
        "Do not invent information. "
    ) + (prompt_hint or "")

    # --- 2) Intento con Responses + input_file ---
    extracted = ""
    if up is not None:
        try:
            resp = client.responses.create(
                model="gpt-4.1-mini",   # alternativas: "gpt-4o" también funciona
                input=[{
                    "role": "user",
                    "content": [
                        {"type": "input_file", "file_id": up.id},
                        {"type": "input_text", "text": base_prompt}
                    ]
                }],
                max_output_tokens=12000,
            )

            # Preferir .output_text cuando exista
            extracted = getattr(resp, "output_text", "") or ""
            if not extracted:
                # reconstrucción manual por compatibilidad
                parts = []
                for item in getattr(resp, "output", []) or []:
                    for c in getattr(item, "content", []) or []:
                        t = getattr(c, "text", None)
                        if t:
                            parts.append(t)
                extracted = "\n".join(p for p in parts if p).strip()

        except Exception as e:
            logging.error(f"❌ Responses extraction failed: {e}")

    # A veces el modelo puede responder “I can't view…” si no recibió bien el file
    if not extracted or "can't view or extract" in extracted.lower():
        logging.warning("⚠️ Model did not read the PDF properly. Returning best local extraction.")
        extracted = local_text
    elif local_text and len(extracted) < len(local_text) * 0.6:
        # El modelo resumió o perdió contenido: nos quedamos con el texto local,
        # que aunque esté desordenado conserva todas las fechas y nombres.
        logging.warning(
            "pdf_extract: model output much shorter than local text (%s vs %s); keeping local",
            len(extracted), len(local_text),
        )
        extracted = local_text

    extracted = extracted.strip()
    logging.info(
        "pdf_extract: local=%s model_used=%s final=%s",
        len(local_text), bool(up is not None), len(extracted),
    )
    return extracted

def _truncate_preserving_edges(text: str, limit: int) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    head_size = int(limit * 0.7)
    tail_size = limit - head_size
    return (
        text[:head_size].rstrip()
        + "\n\n[...SOURCE TRUNCATED: middle omitted to fit model context...]\n\n"
        + text[-tail_size:].lstrip()
    )

def _summarize_long_resume_source(source_name: str, text: str, limit: int) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text

    # Antes se cortaba a RESUME_SOURCE_MAX_CHUNKS y se TIRABA el resto sin
    # dejar rastro. Pre-encogemos con el helper que sí deja marcador, para que
    # sobrevivan cabeza y cola y quede visible que hubo recorte.
    text = _truncate_preserving_edges(
        text, RESUME_SOURCE_CHUNK_SIZE * RESUME_SOURCE_MAX_CHUNKS
    )
    chunks = [
        text[i:i + RESUME_SOURCE_CHUNK_SIZE]
        for i in range(0, len(text), RESUME_SOURCE_CHUNK_SIZE)
    ][:RESUME_SOURCE_MAX_CHUNKS]
    summaries = []
    for idx, chunk in enumerate(chunks, start=1):
        prompt = f"""
        You are condensing source material for a resume generator.
        Keep every factual resume signal from this {source_name} chunk: candidate name, roles, companies,
        dates, responsibilities, achievements, tools, skills, education, certifications, and languages.
        Do not invent or generalize. Preserve page/chunk order and date ranges.
        Preserve every date range and every tool name verbatim.

        SOURCE: {source_name}
        CHUNK {idx} OF {len(chunks)}
        ---
        {chunk}
        ---
        Return clean English notes only.
        """
        try:
            response = call_openai_with_retry(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You preserve resume facts from long sources."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=2500,
            )
            summaries.append(response.choices[0].message.content.strip())
        except Exception:
            logging.exception("Failed to summarize %s chunk %s", source_name, idx)
            summaries.append(chunk[:3000])

    combined = "\n\n".join(
        f"--- {source_name} SUMMARY CHUNK {idx} ---\n{summary}"
        for idx, summary in enumerate(summaries, start=1)
        if summary
    )
    return _truncate_preserving_edges(combined, limit)

def _normalize_resume_date(value: Any, *, allow_year_only: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", raw)
    if match:
        return f"{match.group(1)}-{match.group(2)}-01"
    if re.match(r"^\d{4}-\d{2}$", raw):
        return f"{raw}-01"
    if re.match(r"^\d{4}$", raw):
        return f"{raw}-01-01" if allow_year_only else ""
    return raw

def _fold_location_text(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text).lower().strip()

def _contains_location_token(context: str, token: str) -> bool:
    folded = _fold_location_text(token)
    if not folded:
        return False
    return re.search(rf"(?<![a-z]){re.escape(folded)}(?![a-z])", context) is not None

def _find_explicit_country(context: str) -> str:
    for country, aliases in _COUNTRY_ALIASES.items():
        if any(_contains_location_token(context, alias) for alias in aliases):
            return country
    return ""

def _find_location_hint_country(context: str) -> str:
    for country, hints in _EDUCATION_LOCATION_HINTS:
        if any(_contains_location_token(context, hint) for hint in hints):
            return country
    return ""

def _source_window_for_education(entry: Dict[str, Any], source_text: str, radius: int = 260) -> str:
    folded_source = _fold_location_text(source_text)
    if not folded_source:
        return ""

    candidates = [
        entry.get("institution"),
        entry.get("title"),
    ]
    for raw in candidates:
        needle = _fold_location_text(raw)
        if len(needle) < 5:
            continue
        idx = folded_source.find(needle)
        if idx != -1:
            return folded_source[idx: idx + len(needle) + radius]

    return ""

def _infer_education_country(entry: Dict[str, Any], source_text: str) -> str:
    entry_context = " ".join([
        _fold_location_text(entry.get("institution")),
        _fold_location_text(entry.get("title")),
        _fold_location_text(entry.get("description")),
    ])
    source_context = _source_window_for_education(entry, source_text)
    if not entry_context and not source_context:
        return str(entry.get("country") or "").strip()

    for context in (entry_context, source_context):
        country = _find_explicit_country(context)
        if country:
            return country
        country = _find_location_hint_country(context)
        if country:
            return country

    return str(entry.get("country") or "").strip()

def _clean_generated_education_dates(entry: Dict[str, Any]) -> Dict[str, Any]:
    start = str(entry.get("start_date") or "").strip()
    end = str(entry.get("end_date") or "").strip()

    # A single education year is stored as a full-year range so the existing
    # resume UI can display the year instead of dropping the date entirely.
    same_year_range = (
        re.match(r"^\d{4}-0?1-(?:0?1|15)$", start)
        and re.match(r"^\d{4}-12-(?:31|15|01)$", end)
        and start[:4] == end[:4]
    )
    if same_year_range:
        entry["start_date"] = f"{start[:4]}-01-01"
        entry["end_date"] = f"{start[:4]}-12-31"
        entry["current"] = False
        return entry

    entry["start_date"] = _normalize_resume_date(start, allow_year_only=True)
    entry["end_date"] = _normalize_resume_date(end, allow_year_only=True)
    # Fecha única de graduación ("December 2018", sin inicio): el modelo a veces
    # la repite en ambos campos y la UI muestra un rango de largo cero.
    if entry["start_date"] and entry["start_date"] == entry["end_date"]:
        entry["start_date"] = ""
    if not entry["end_date"] and not entry["start_date"]:
        # Una carrera en curso sin fechas ("8vo semestre, en curso") sigue siendo
        # current: sólo la apagamos si el modelo no la marcó.
        entry["current"] = bool(entry.get("current"))
    return entry

def _clean_generated_work_dates(entry: Dict[str, Any], today: datetime.date) -> Dict[str, Any]:
    start = _normalize_resume_date(entry.get("start_date"), allow_year_only=True)
    raw_end = str(entry.get("end_date") or "").strip()
    if raw_end.lower() in ("", "present", "current", "now", "actualidad"):
        end = ""
        current = True
    else:
        end = _normalize_resume_date(raw_end, allow_year_only=True)
        current = False
        try:
            current = datetime.datetime.strptime(end, "%Y-%m-%d").date() > today if end else False
        except Exception:
            current = False
    entry["start_date"] = start
    entry["end_date"] = "" if current else end
    entry["current"] = current
    return entry

SECTION_CHAT_HISTORY_LIMIT = 12
SECTION_CHAT_TURN_CHARS = 800


def _format_section_chat_history(history: Any) -> str:
    """Arma el bloque de conversación para los editores por sección.

    Sin esto cada prompt nacía sin memoria, así que un follow-up corto
    ("ahora más corto", "lo mismo para Beta") no tenía a qué referirse.
    """
    if not isinstance(history, list) or not history:
        return "(no earlier turns — this is the recruiter's first instruction)"

    lines = []
    for turn in history[-SECTION_CHAT_HISTORY_LIMIT:]:
        if not isinstance(turn, dict):
            continue
        text = _strip_html_text(str(turn.get("content") or "")).strip()
        if not text:
            continue
        role = str(turn.get("role") or "").strip().lower()
        label = "RECRUITER ASKED" if role in ("user", "recruiter") else "YOU DID"
        lines.append(f"{label}: {text[:SECTION_CHAT_TURN_CHARS]}")

    return "\n".join(lines) or "(no earlier turns — this is the recruiter's first instruction)"


SECTION_CHAT_RULES = """
--- HOW TO READ THE CONVERSATION ---
The recruiter is iterating on this section, not starting over. Earlier instructions in the
conversation STILL APPLY unless a later one contradicts them — if they asked for longer
bullets three turns ago and now ask to fix one company, keep the longer bullets.
A short follow-up ("make it shorter", "now the same for the other role", "no, undo that")
refers to this conversation, so resolve it against the turns above before acting.
Change ONLY what was asked. Everything the recruiter did not mention must come back
byte-for-byte identical — silently rewriting untouched parts is the thing that makes them
lose trust in this tool.
"""


def _parse_section_edit_payload(content: str, primary_key: str):
    """Devuelve (valor, summary) del editor por sección.

    Tolera el formato viejo (array/texto pelado) por si el modelo contesta a la
    antigua: así un cambio de formato no rompe el botón en producción.
    """
    cleaned = re.sub(
        r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', str(content or "").strip()
    )
    try:
        data = json.loads(cleaned)
    except Exception:
        return cleaned, ""

    if isinstance(data, list):
        return data, ""
    if isinstance(data, dict):
        summary = _normalize_change_summary(data.get("summary"))
        for key in (primary_key, "entries", "items", "result", "value"):
            if key in data:
                return data[key], summary
        return data, summary
    return data, ""


def _normalize_change_summary(value: Any) -> str:
    """El modelo devuelve el summary como string o como lista de líneas.

    Con str() a secas la lista llegaba al chat como "['Acme: ...', 'Beta: ...']",
    con corchetes y comillas a la vista.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        lines = [str(v).strip() for v in value if str(v or "").strip()]
        return "\n".join(f"• {line}" for line in lines)
    return str(value).strip()


def _sort_work_entries_reverse_chronological(entries: list) -> list:
    """Ordena la experiencia de más reciente a más antigua.

    El prompt ya lo pide, pero cuando los roles llegan de dos fuentes distintas
    (CV escrito + LinkedIn) el modelo los va concatenando por fuente y el orden
    sale mezclado. Acá es determinista y gratis.
    Los roles sin fecha quedan al final, conservando su orden relativo.
    """
    def key(item):
        idx, entry = item
        start = str(entry.get("start_date") or "")
        end = str(entry.get("end_date") or "")
        has_date = bool(start or end)
        # current primero, después por start_date desc; sin fecha, al fondo.
        return (
            0 if has_date else 1,
            0 if entry.get("current") else 1,
            _invert_date_for_sort(start),
            _invert_date_for_sort(end),
            idx,
        )

    return [e for _, e in sorted(enumerate(entries), key=key)]


def _invert_date_for_sort(value: str) -> str:
    """Convierte "YYYY-MM-DD" en una clave que ordena descendente como string."""
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return "￿"  # sin fecha -> al final dentro de su grupo
    digits = digits.ljust(8, "0")[:8]
    return "".join(chr(ord("9") - int(ch) + ord("0")) for ch in digits)


def _format_description_to_html(description: Any, *, bullets_only: bool = False) -> str:
    """Convierte la descripción del modelo ("- bullet" por línea) a HTML.

    La versión anterior vivía inline y duplicada dentro de la ruta, y guardaba
    SÓLO la primera línea que no era bullet, descartando el resto en silencio.
    Con la educación en dos oraciones eso perdía la segunda.

    `bullets_only=True` (experiencia laboral) fuerza que TODO salga como bullet:
    una línea suelta arriba de la lista se ve como texto huérfano en la caja de
    edición y en el CV del cliente.
    """
    if not description:
        return ""
    # Los editores por sección reciben la descripción YA en HTML (así está
    # guardada) y a veces el modelo la devuelve igual. Sin este guard la
    # volvíamos a envolver: <ul><li><ul><li>…</li></ul></li></ul>.
    if re.search(r"<\s*(ul|ol|li|p|br)\b", str(description), re.I):
        return str(description).strip()
    paragraphs, bullets = [], []
    for line in str(description).strip().split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped[0] in "-•–*":
            bullets.append(stripped.lstrip("-•–* ").strip())
        elif bullets or bullets_only:
            # Párrafo suelto (antes o después de los bullets): lo tratamos como
            # bullet para no perderlo ni dejarlo colgado fuera de la lista.
            bullets.append(stripped)
        else:
            paragraphs.append(stripped)
    if bullets_only and paragraphs:
        bullets = paragraphs + bullets
        paragraphs = []
    html = "".join(f"<p>{p}</p>" for p in paragraphs)
    if bullets:
        html += "<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>"
    return html

_ABOUT_FILLER_PATTERNS = [
    # (patrón, reemplazo). Conservan la sustancia que viene después del relleno.
    (r",?\s*with a proven track record (?:in|of)\s+", ", "),
    (r",?\s*with a proven ability to\s+", ", "),
    (r"\bProven ability to\s+", ""),
    (r"\bProven track record (?:in|of)\s+", ""),
    (r",?\s*with a strong background (?:in|working with)\s+", ", experienced in "),
    (r"\bPassionate about\s+", "Focused on "),
    (r",?\s*and is passionate about\s+", ", focused on "),
    (r"\bresults-driven\s+", ""),
    (r"\bdynamic professional\b", "professional"),
    (r"\bdetail-oriented\s+", ""),
    (r"\bteam player\b", "collaborative contributor"),
]

def _scrub_about_filler(about: str) -> str:
    """Saca el relleno de CV del About.

    El prompt lo prohíbe, pero el modelo lo copia igual desde el summary del CV
    original ("Proven ability to build financial models..."), así que hace falta
    una red determinista.
    """
    text = str(about or "")
    if not text.strip():
        return ""
    original = text
    for pattern, replacement in _ABOUT_FILLER_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.;])", r"\1", text)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"(^|\.\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    text = text.strip()
    if text != original:
        logging.info("resume generation: scrubbed filler phrasing from About")
    return text

def _parse_model_json(content: str) -> Dict[str, Any]:
    """Parser tolerante: JSON directo, sin code fences, o el substring {...}."""
    raw = (content or "").strip()
    attempts = [raw, re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', raw)]
    if "{" in raw and "}" in raw:
        attempts.append(raw[raw.find("{"): raw.rfind("}") + 1])
    for candidate in attempts:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    raise Exception(f"❌ Could not parse model JSON. First 300 chars: {raw[:300]}")

def _normalize_tool_level(value: Any) -> str:
    v = str(value or "").strip().lower()
    if re.search(r"adv|expert|senior|master|fluent|native|\b4\b|\b5\b", v):
        return "Advanced"
    if re.search(r"basic|begin|junior|elementary|low|\b1\b", v):
        return "Basic"
    return "Intermediate"

def _normalize_generated_tools(raw: Any) -> list:
    out, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            item = {"tool": item, "level": ""}
        if not isinstance(item, dict):
            continue
        name = str(item.get("tool") or item.get("name") or "").strip()
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        out.append({"tool": name, "level": _normalize_tool_level(item.get("level"))})
        if len(out) >= RESUME_MAX_TOOLS:
            break
    return out

def _normalize_language_level(value: Any) -> str:
    v = str(value or "").strip().lower()
    if re.search(r"native|bilingual|mother", v):
        return "Native"
    if re.search(r"fluent|advanced|full professional|professional working|c1|c2", v):
        return "Fluent"
    if re.search(r"basic|beginner|elementary|a1|a2", v):
        return "Basic"
    return "Regular"

def _normalize_generated_languages(raw: Any) -> list:
    out, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            item = {"language": item, "level": ""}
        if not isinstance(item, dict):
            continue
        key = re.sub(r"\s+", " ", str(item.get("language") or "")).strip().casefold()
        name = RESUME_LANGUAGE_ALIASES.get(key)
        if not name:
            if key:
                logging.info("resume generation: dropping unsupported language %r", key)
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append({
            "language": name,
            "level": _normalize_language_level(item.get("level")),
        })
        if len(out) >= RESUME_MAX_LANGUAGES:
            break
    return out

def _strip_html_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", text).strip()

def _clean_coresignal_html(text: str) -> str:
    clean = re.sub(r'<[^>]+>', ' ', text or "")
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean

def _prune_deleted_coresignal(text: str) -> str:
    try:
        obj = json.loads(text)
    except Exception:
        return text

    def prune(value):
        if isinstance(value, dict):
            if str(value.get('deleted', 0)) in ('1', 'true', 'True', 'TRUE', 1):
                return None
            out = {}
            for key, item in value.items():
                pruned = prune(item)
                if pruned in (None, '', [], {}):
                    continue
                out[key] = pruned
            return out
        if isinstance(value, list):
            out = []
            for item in value:
                pruned = prune(item)
                if pruned not in (None, '', [], {}):
                    out.append(pruned)
            return out
        return value

    pruned = prune(obj)
    try:
        return json.dumps(pruned, ensure_ascii=False)
    except Exception:
        return text

def _extract_linkedin_from_coresignal(coresignal_raw: str) -> str:
    if not (coresignal_raw or "").strip():
        return ""
    raw = _clean_coresignal_html(coresignal_raw)
    source = _prune_deleted_coresignal(raw)[:15000]
    if not source:
        return ""

    prompt = f"""
You are a STRICT CV/LinkedIn extractor. Input is a noisy JSON-like block (often Spanish). Your job:
- Extract EVERY job-relevant fact that exists in the source.
- Translate to English.
- DO NOT invent. If something is missing, omit it.
- Deduplicate across arrays/variants. Prefer items that include richer fields (e.g., issuer_url, company_industry).
- Respect that any entries previously marked as deleted=1 have already been filtered out.

DATE & TEXT NORMALIZATION
- Dates: use "MMM YYYY" if month exists (Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec); otherwise "YYYY".
- Current roles end with "Present".
- Company size: print "Company size: <range or employees_count>" only if present.
- Industry: use company_industry if present.
- Languages: normalize proficiency to one of:
"Native or bilingual", "Full professional", "Professional working", "Limited working", "Elementary".
- Remove tracking params from URLs (strip the query string).
- No placeholders or dashes when a field is unknown: just omit that part of the line.

OUTPUT FORMAT — EXACTLY this sectioned template in plain text (no markdown). Omit any entire section if empty. No extra commentary.

{{FullName}}
{{City, Country}} • LinkedIn: {{ProfileURL}}

Professional Headline
{{Headline}}

Summary
{{ShortSummary}}

Experience
{{For each role, most recent first:}}
{{Title}} — {{Company}} {{(Industry in parentheses if available)}}
{{If location exists, start the line with it followed by " • "}} {{Start}} – {{EndOrPresent}}
{{If any of these exist on the same line, separate with " • " (and omit missing ones): Duration, Company size}}

Education
{{Degree/Program}} — {{Institution}}
{{Dates line (Start–End)}}

Certifications
{{Title}} — {{Issuer}} {{• Date or Date range if any}} {{• Credential: URL if any}}

Awards
{{Title}} — {{Issuer if any}} {{• Date if any}}
{{One short sentence if description exists}}

Volunteering
{{Role}} — {{Organization}} {{• Cause if any}}
{{Dates line (Start–End)}}

Languages
{{Language}} — {{Proficiency}}

Additional Links
{{Profile photo (URL): <photo_url>}}
{{Stats: <connections_count> connections • <follower_count> followers}}  {{(only if available)}}

IMPORTANT
- Plain text only. No bullets, no JSON, no markdown, no table formatting.
- Keep spacing tidy. No empty headings. Do not output empty lines at the end.

SOURCE
---
{source}
---
    """.strip()

    chat = call_openai_with_retry(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert resume writer and information extractor. Output plain text following the exact sectioned template, and never invent facts."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=7000,
    )
    return (chat.choices[0].message.content or "").strip()

def _build_opportunity_context(cursor, opportunity_id: Optional[int]):
    if not opportunity_id:
        return "", {}
    cursor.execute(
        """
        SELECT
            opp_position_name,
            career_country,
            years_experience,
            hr_job_description,
            career_description,
            career_requirements
        FROM opportunity
        WHERE opportunity_id = %s
        """,
        (opportunity_id,),
    )
    row = cursor.fetchone()
    if not row:
        return "", {}
    # Este helper lo llaman cursores de los dos tipos. Desempaquetar un RealDictRow
    # devuelve las CLAVES, no los valores, así que la JD que salía era la palabra
    # "hr_job_description" y el modelo puntuaba contra eso sin que nada fallara. Pasó de
    # verdad en el review de CVs: falla silenciosa, así que se normaliza acá y no en cada
    # llamada.
    if isinstance(row, dict):
        row = (row.get("opp_position_name"), row.get("career_country"),
               row.get("years_experience"), row.get("hr_job_description"),
               row.get("career_description"), row.get("career_requirements"))
    position, career_country, years_experience, hr_jd, career_desc, career_reqs = row
    raw_jd = hr_jd or career_desc or career_reqs or ""
    jd_plain = _strip_html_text(raw_jd)
    context = {
        "position": position or "",
        "career_country": career_country or "",
        "years_experience": years_experience or "",
    }
    return jd_plain, context

def _load_resume_generation_context(candidate_id, opportunity_id):
    """Lee de la DB todo lo que necesita el prompt del CV, en una conexión corta
    y ANTES de la llamada (lenta) a OpenAI.

    Nunca lanza excepción: si la oportunidad no existe, no tiene JD o la query
    falla, devolvemos contexto vacío y el CV sale genérico.
    """
    candidate = {"name": "", "country": ""}
    target = None
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        if candidate_id:
            cur.execute(
                "SELECT COALESCE(name, ''), COALESCE(country, '') "
                "FROM candidates WHERE candidate_id = %s",
                (candidate_id,),
            )
            row = cur.fetchone()
            if row:
                candidate = {"name": row[0], "country": row[1]}
        if opportunity_id:
            jd_plain, opp_ctx = _build_opportunity_context(cur, opportunity_id)
            cur.execute(
                """
                SELECT COALESCE(a.client_name, '')
                FROM opportunity o
                LEFT JOIN account a ON o.account_id = a.account_id
                WHERE o.opportunity_id = %s
                """,
                (opportunity_id,),
            )
            row = cur.fetchone()
            client_name = row[0] if row else ""
            if opp_ctx or jd_plain:
                target = {
                    "client_name": client_name,
                    "position": opp_ctx.get("position", ""),
                    "career_country": opp_ctx.get("career_country", ""),
                    "years_experience": str(opp_ctx.get("years_experience") or ""),
                    "jd": _truncate_preserving_edges(jd_plain, RESUME_JD_LIMIT),
                }
        cur.close()
    except Exception:
        logging.exception(
            "generate_resume_fields: could not load DB context; continuing generically"
        )
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
    return candidate, target

def _load_section_editor_context(candidate_id, opportunity_id=None) -> Dict[str, str]:
    """Contexto compartido para los editores por sección (/ai/improve_*).

    Antes cada endpoint armaba su propio contexto y se quedaba corto de distintas
    maneras: los scrapers recortados a 2000 chars (o sea, el encabezado y poco
    más), `coresignal_scrapper` ignorado por completo — un candidato traído por
    Coresignal llegaba con LinkedIn VACÍO — y ninguno sabía para qué vacante es
    el CV, así que "hacelo más relevante para este cliente" era imposible.

    Nunca lanza: si algo falla, se devuelve lo que se pudo leer.
    """
    ctx = {"name": "", "country": "", "linkedin": "", "cv": "", "target_role_block": ""}
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COALESCE(name, ''), COALESCE(country, ''),
                   COALESCE(linkedin_scrapper, ''), COALESCE(coresignal_scrapper, ''),
                   COALESCE(cv_pdf_scrapper, ''), COALESCE(affinda_scrapper, '')
            FROM candidates WHERE candidate_id = %s
            """,
            (candidate_id,),
        )
        row = cur.fetchone()
        if row:
            name, country, linkedin_raw, coresignal_raw, cv_pdf, affinda = row
            ctx["name"] = name
            ctx["country"] = country

            # Mismo fallback que usa el front para la generación:
            # linkedin_scrapper || coresignal_scrapper.
            linkedin = (linkedin_raw or "").strip()
            if not linkedin and (coresignal_raw or "").strip():
                linkedin = _prune_deleted_coresignal(
                    _clean_coresignal_html(coresignal_raw)
                )
            ctx["linkedin"] = _truncate_preserving_edges(
                linkedin, RESUME_SECTION_EDITOR_SOURCE_LIMIT
            )
            ctx["cv"] = _truncate_preserving_edges(
                ((cv_pdf or "").strip() or (affinda or "").strip()),
                RESUME_SECTION_EDITOR_SOURCE_LIMIT,
            )

        if opportunity_id:
            jd_plain, opp_ctx = _build_opportunity_context(cur, opportunity_id)
            cur.execute(
                """
                SELECT COALESCE(a.client_name, '')
                FROM opportunity o
                LEFT JOIN account a ON o.account_id = a.account_id
                WHERE o.opportunity_id = %s
                """,
                (opportunity_id,),
            )
            name_row = cur.fetchone()
            if opp_ctx or jd_plain:
                ctx["target_role_block"] = _build_resume_target_role_block({
                    "client_name": name_row[0] if name_row else "",
                    "position": opp_ctx.get("position", ""),
                    "career_country": opp_ctx.get("career_country", ""),
                    "years_experience": str(opp_ctx.get("years_experience") or ""),
                    "jd": _truncate_preserving_edges(jd_plain, RESUME_JD_LIMIT),
                })
        cur.close()
    except Exception:
        logging.exception(
            "section editor context: could not load everything; continuing"
        )
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
    return ctx


def _ensure_cv_pdf_text(candidate_id) -> str:
    """Extrae el texto del CV subido si `candidates.cv_pdf_scrapper` está vacío.

    La extracción automática del front sólo corre al CARGAR la página
    (autoExtractFromPdfOnLoad en resume.js). Si la recruiter sube el CV y
    genera en la misma sesión, el texto todavía no existe y el CV se arma sólo
    con la transcripción — que es exactamente cómo salen los CVs flacos, con
    instituciones sin nombre y sin métricas. Acá lo resolvemos del lado del
    servidor para que no dependa de recargar.
    """
    if not candidate_id:
        return ""
    from utils import services
    from utils.storage_utils import get_cv_keys

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT COALESCE(cv_pdf_scrapper, '') FROM candidates WHERE candidate_id = %s",
            (candidate_id,),
        )
        row = cur.fetchone()
        if row and (row[0] or "").strip():
            cur.close()
            return row[0]

        keys = [k for k in (get_cv_keys(cur, candidate_id) or []) if k.lower().endswith(".pdf")]
        if not keys:
            cur.close()
            return ""

        obj = services.s3_client.get_object(Bucket=services.S3_BUCKET, Key=keys[-1])
        pdf_bytes = obj["Body"].read()
        text = (_extract_pdf_text_with_openai(pdf_bytes) or "").strip()
        if not text:
            cur.close()
            return ""

        cur.execute(
            "UPDATE candidates SET cv_pdf_scrapper = %s, "
            "affinda_scrapper = COALESCE(NULLIF(affinda_scrapper, ''), %s) "
            "WHERE candidate_id = %s",
            (text, text, candidate_id),
        )
        conn.commit()
        cur.close()
        logging.info(
            "generate_resume_fields: extracted CV PDF on demand for candidate %s (%s chars)",
            candidate_id, len(text),
        )
        return text
    except Exception:
        logging.exception(
            "generate_resume_fields: on-demand CV extraction failed for candidate %s",
            candidate_id,
        )
        return ""
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass

def _build_resume_target_role_block(target: Optional[Dict[str, Any]]) -> str:
    """Bloque 'TARGET ROLE' del prompt. Sin oportunidad -> CV genérico."""
    if not target:
        return (
            "TARGET ROLE\n"
            "None provided. Write a strong general-purpose CV. Order and weight the content\n"
            "by the candidate's own seniority and most substantial experience.\n"
        )
    lines = [
        "TARGET ROLE",
        "This CV will be sent to a client for this specific opening.",
    ]
    if target.get("client_name"):
        lines.append(f"Client: {target['client_name']}")
    if target.get("position"):
        lines.append(f"Position: {target['position']}")
    if target.get("career_country"):
        lines.append(f"Country / market: {target['career_country']}")
    if target.get("years_experience"):
        lines.append(f"Experience the client asked for: {target['years_experience']}")
    jd = (target.get("jd") or "").strip()
    if jd:
        lines.append("Job description (verbatim from the client):\n---\n" + jd + "\n---")
    else:
        lines.append("No job description text is available; use the position title only.")
    return "\n".join(lines) + "\n"

def _build_resume_generation_prompt(
    *,
    target_role_block: str,
    candidate_name: str,
    candidate_country: str,
    linkedin_scrapper: str,
    cv_pdf_scrapper: str,
    intro_call_transcript: str,
    deep_dive_transcript: str,
    first_interview_transcript: str,
    notes: str,
    today: str,
) -> str:
    return f"""You are a senior recruiter at Vintti writing a client-facing CV in English.
Vintti presents LatAm talent to US clients, so the CV must read like a professional,
confident, factual English CV — never like a machine describing a document.

Return ONE valid JSON object and nothing else. No markdown, no code fences, no commentary.

TODAY'S DATE: {today}
CANDIDATE NAME (context only, never write it inside the sections): {candidate_name}
CANDIDATE COUNTRY (context only): {candidate_country}

{target_role_block}

SOURCE MATERIAL — this is the ONLY thing you may draw facts from.

WARNING ABOUT THE LINKEDIN SCRAPE: it is a raw dump that also contains OTHER PEOPLE's
content — feed posts, comments, recommendations written by third parties, "people also
viewed" profiles. Only use facts that belong to THIS candidate's own profile sections
(their experience, education, skills, languages). If a degree, employer or achievement
appears only inside a post or a third-party name block, it is somebody else's — ignore it.

LINKEDIN SCRAPER:
{linkedin_scrapper}

CV PDF SCRAPER:
{cv_pdf_scrapper}

INTRO CALL TRANSCRIPT:
{intro_call_transcript}

DEEP DIVE TRANSCRIPT:
{deep_dive_transcript}

FIRST INTERVIEW TRANSCRIPT:
{first_interview_transcript}

(The recruiter may have supplied additional facts and directions — see the RECRUITER
INSTRUCTIONS block below the rules. Those count as source material too.)

=========================
ABSOLUTE RULES (violating any of these ruins the deliverable)
=========================
1. NO FABRICATION. Every statement must be traceable to a specific fact in the source
   material above. Do not invent responsibilities, clients, deliverables, metrics, team
   sizes, industries, tools, certifications, coursework or achievements.
2. NO EXAGGERATION. Do not upgrade scope ("supported" is not "led"), do not turn a task
   into an achievement, do not add numbers that are not in the source.
3. WHEN A ROLE IS SPARSE, WRITE FEWER BULLETS — but never shallower ones. Dropping a bullet
   you cannot ground is correct; stripping the detail out of a bullet you CAN ground is not.
   One accurate bullet beats four padded ones. Never pad, never restate the job title as a
   bullet, never write filler.
4. NEVER WRITE META-COMMENTARY ABOUT THE SOURCES. Forbidden phrasings include:
   "the CV presents...", "the CV lists this role as...", "CV-wide context includes...",
   "listed software includes...", "according to the source", "the candidate's profile states".
   Write the fact directly in professional CV language, or omit it entirely.
5. THE WRITTEN CV DECIDES WHICH ROLES APPEAR. The candidate chose what to put on their own
   CV, and that choice is respected. The list of work experience entries comes from the CV
   PDF, and EVERY role it lists must appear — never drop an older, shorter, freelance,
   internship, consulting, RPO, part-time or overlapping role to save space. LinkedIn and
   the interviews do NOT add roles; they only ENRICH the roles the CV already lists. See
   "LINKEDIN ENRICHES THE CV'S ROLES" below for the exact procedure and the one fallback.
6. OUTPUT ENGLISH. Translate job titles, degrees and descriptions into English. Keep company
   and institution proper names as they appear in the source.
7. Do not use first person ("I", "my"). Do not use "Responsible for". Do not use markdown,
   bold, emojis or HTML tags anywhere in your output.
8. NEVER INVENT PLACEHOLDER NAMES. If the source does not name the company, institution or
   school, leave that field as an empty string. Writing "Unnamed University", "Unknown
   Company", "A university in the US" or similar is a fabrication and is forbidden.
9. USE THE MOST COMPLETE VERSION OF EVERY NAME the sources contain. If the CV says
   "CSLR Investments Corp" and the interview says "CSLR", write "CSLR Investments Corp".
   Never shorten or abbreviate a company or institution name.
10. CARRY OVER EVERY NUMBER the source states for a role: portfolio and deal sizes, budgets,
   percentages, headcounts, account volumes, AUM growth, savings. These are the strongest
   part of a CV and dropping them is the most common way this output comes out weak.
11. DEPTH IS NOT FABRICATION, AND THIN BULLETS ARE A DEFECT. The recurring complaint about
   this output is that the bullets are too short to tell a client anything. "Managed monthly
   close" is not the safe version of the truth — it is the useless version. Every fact the
   source attaches to a piece of work (the system it ran on, who it was for, how often, how
   many, what came out of it, why it existed) belongs INSIDE that bullet. Compressing a rich
   source line into a stub is as much a failure as inventing one. Rules 1 and 2 tell you not
   to add facts that are not there; they never tell you to leave out facts that are.

=========================
RECRUITER INSTRUCTIONS — HIGHEST AUTHORITY AFTER THE ABSOLUTE RULES
=========================
The block below was written by the recruiter who actually knows this candidate, usually
because a previous version of this CV came out wrong. It may contain two kinds of content,
and you must honour both:

  (a) FACTS the recruiter is adding from their own knowledge — a tool, a client, an
      employer, a responsibility, a metric that never made it into the CV or the call.
      TREAT THESE AS SOURCE MATERIAL. The recruiter vouches for them, so using them is NOT
      fabrication and ABSOLUTE RULE 1 does not block them. Put each fact exactly where the
      recruiter says it belongs: "add QuickBooks and Xero to the work experience at Acme"
      means those tools appear in the Acme role's bullets AND in the tools list, and
      nowhere else.

  (b) DIRECTIONS about how to write the CV — what to emphasise, what to cut, what to fix,
      how long or short something should be, which role matters most. These OVERRIDE the
      defaults written further down, including bullet counts, ordering and emphasis.

Apply them precisely and completely, and re-read this block before you answer to confirm
every instruction actually landed. If an instruction names a specific role or company, find
that exact entry and apply it there — never approximately, never to a similar role. If an
instruction contradicts a default in the sections below, the instruction wins. The one thing
it cannot override is the ban on inventing facts that neither the sources nor the recruiter
supplied. If the block is empty, ignore it entirely.

RECRUITER INSTRUCTIONS:
{notes}

=========================
TAILORING TO THE TARGET ROLE
=========================
- If a target role is given, make the relevant experience obvious at a glance:
  * Within each role, order bullets so the most relevant-to-the-target ones come FIRST.
  * Give more bullets (4-6) to roles whose work overlaps the target role; give fewer (1-3)
    to roles that do not.
  * Prefer source facts that match the job description's responsibilities, tools, industry
    and seniority. This is the whole point of tailoring: a CV that ignores the JD is a
    worse CV. Align hard on SUBSTANCE.
  * But NEVER align on WORDING. The job description tells you what to LOOK FOR in the
    source material; it is never a source of content. Do not lift a sentence, a phrase or
    a responsibility line out of the JD and conjugate it into the candidate's history.
    Write every bullet in the candidate's own terms, from what the source actually says.
  * THE TEST — apply it to every bullet you write: could this exact sentence be written
    for ANY candidate applying to this job? If yes, it is the job description talking, not
    this person. Rewrite it around the specific thing THIS candidate did, or drop it.
    Illustration of the failure this rule exists to prevent. It is from a DIFFERENT,
    unrelated opening — never reuse its wording:
      JD says:  "Process vendor invoices and reconcile accounts payable in NetSuite."
      CV said:  "Processes vendor invoices and reconciles accounts payable in NetSuite."
      That is the JD line with the verbs conjugated. Three different candidates for that
      opening were handed the same sentence, so the client read their own posting back
      three times under three names. Never do this.
  * Sharing a KEYWORD with the JD is good when the source proves it ("NetSuite" in both,
    "influencer campaigns" in both). Sharing a whole CLAUSE is the failure. If more than a
    few consecutive words match the JD, you are copying — rewrite it.
  * Never claim a JD requirement the candidate did not actually demonstrate. Gaps stay
    gaps. Renaming a candidate's experience to match the JD is fabrication.
- Do NOT reorder the roles themselves. Work experience is always reverse-chronological
  (most recent first), and education is reverse-chronological too.

=========================
OUTPUT SHAPE
=========================
Return exactly this JSON object, always with all five keys, using [] or "" when a section
genuinely has no grounded content:

{{
  "about": "string",
  "work_experience": [
    {{
      "title": "...",
      "company": "...",
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD or empty string if current",
      "current": true/false,
      "description": "One-line role context.\\n- Bullet 1\\n- Bullet 2\\n- Bullet 3"
    }}
  ],
  "education": [
    {{
      "institution": "...",
      "title": "...",
      "country": "Country name or empty string",
      "start_date": "YYYY-MM-DD or empty string",
      "end_date": "YYYY-MM-DD or empty string",
      "current": true/false,
      "description": "Two sentences on one single line, no bullets."
    }}
  ],
  "tools": [{{"tool": "Excel", "level": "Advanced"}}],
  "languages": [{{"language": "English", "level": "Fluent"}}]
}}

=========================
ABOUT
=========================
- 3 to 5 sentences, ONE plain-text paragraph, third person, no name, no line breaks,
  no bullets, no HTML.
- START WITH THE PROFESSION, NOT WITH A PRONOUN OR A LABEL. Never begin with "This
  candidate", "The candidate", "A professional with", "They have" or "With over X years".
  Write it like a headline: "Economist and finance professional (MBA & MSc in Finance,
  University of Miami) with close to 4 years of experience across strategic finance, FP&A
  and real estate investment analysis." Avoid "they/them" as a subject throughout — lead
  each sentence with the work, e.g. "Leads capital planning across...", "Comfortable acting
  as the client-facing point of contact with...".
- Name the real companies, degrees and institutions when the source gives them.
- Then the two or three strengths most relevant to the target role, then the core
  tools/industries. Close with education or a differentiator only if it adds something.
- THOSE STRENGTHS ARE SELECTED FROM THE SOURCE, NEVER IMPORTED FROM THE JOB DESCRIPTION.
  The target role only decides WHICH of the candidate's real strengths to lead with. Never
  name an industry, platform, channel or specialty in the About unless the source material
  evidences it for this candidate. The About is the first thing the client reads, so a
  borrowed phrase here is the most expensive kind.
  Concrete failure this rule exists to stop: the opening was for a beauty/influencer social
  media role, the candidate's source only showed SEO, paid media and analytics, and the
  About still claimed "experienced in managing social media and influencer marketing
  campaigns, particularly in the beauty industry". None of that was in the source. If the
  candidate does not have what the role wants, the About says what they DO have.
- Grounded and specific. These phrases are BANNED outright, even if the source CV uses them
  in its own summary: "passionate", "results-driven", "dynamic professional", "proven track
  record", "proven ability", "team player", "detail-oriented", "strong background",
  "excellent communication skills", "drive strategic decisions". They say nothing. Replace
  each one with the concrete fact underneath it — instead of "proven track record of
  optimizing capital deployment", write what was actually deployed and how much.
- Do not close the About with a languages sentence; languages have their own section.
- If there is not enough material for 3 sentences, write 2. Never invent to reach a length.

=========================
WORK EXPERIENCE
=========================
- One entry per distinct title/company. Keep a promotion as its own entry; do not merge it
  into the previous title, and do not split one role into several.

*** LINKEDIN ENRICHES THE CV'S ROLES — IT NEVER ADDS NEW ONES ***
Follow this procedure in order, before writing anything:

STEP 1 — Build the role list from the CV PDF ALONE. Every role printed on the written CV
gets an entry. Nothing else does.

STEP 2 — For each of those roles, go find the SAME role in the LinkedIn scrape and in the
transcripts, and fold their detail into that entry's bullets. This is where the CV gets
better: LinkedIn and the interviews routinely describe responsibilities, tools, clients and
scope that never fit on the printed page. Use all of it, on the role it belongs to.

STEP 3 — A role that exists ONLY in LinkedIn or only in a transcript, with no counterpart on
the written CV, IS EXCLUDED. The candidate deliberately left it off their own CV — an old
call-centre job, a short stint, an unrelated role — and re-adding it overrides their choice
and clutters the CV with work they did not want presented. Do not create an entry for it, and
do not mention it in the About section either. This is not a completeness failure; it is the
required behaviour.

THE ONLY FALLBACK: if there is no usable CV PDF at all (missing, empty, or the extraction is
unreadable garbage), then LinkedIn becomes the role list and STEP 3 does not apply — use
every role LinkedIn gives you. Never leave the work experience empty just because the CV is
missing.

OVERRIDE: if the RECRUITER INSTRUCTIONS block explicitly asks for a role that is not on the
written CV, add it. The recruiter outranks this rule.

*** MATCHING THE SAME ROLE ACROSS SOURCES — NEVER LIST IT TWICE ***
To do STEP 2 you must recognise when a CV role and a LinkedIn role are the same job. They
are THE SAME ROLE — one entry, never two — when the company is the same and the date ranges
are the same or clearly overlapping, even if:
  * the titles are abbreviated differently: "Junior Brand Strategist" vs "Jr. Brand
    Strategist", "Sr. Analyst" vs "Senior Analyst", "Acct Manager" vs "Account Manager".
  * one source writes the title in Spanish and the other in English: "Coordinadora de
    digital" vs "Digital Coordinator", "Gerente de Ventas" vs "Sales Manager".
  * the company is written differently: "GARNIER.AGENCY" vs "Garnier BBDO Costa Rica",
    "Acme Corp" vs "Acme". Same employer, written two ways.
  * one source gives bullets and the other gives only the title and dates.
When you merge: keep the FULLEST company name, keep the title in English, take the widest
correct date range, and COMBINE the detail from both sources into one bullet list — that
merged list is richer than either source alone, which is exactly what you want.

Do NOT merge when the WRITTEN CV ITSELF shows two different titles at that company with
different date ranges (a real promotion, or two separate stints). Those stay separate — see
the STACKED TITLES rules below.

But when the CV shows ONE entry at a company and LinkedIn splits that same tenure into two
or three titles, follow the CV: keep the single entry the CV shows, and use the extra
LinkedIn detail inside its bullets. The CV's structure is the one being respected.

A role listed twice under two spellings is a visible defect that makes the CV look
auto-generated — that is the error to watch for here.

*** STACKED TITLES AT ONE COMPANY — READ THIS TWICE ***
CVs very often print the company name ONCE and then stack two or more titles under it,
each with its own date range, followed by a SINGLE shared bullet list. Example layout:

    CSLR Investments Corp                          Miami, FL
    Director of Strategic Finance & Investments    December 2025-Present
    Finance Strategy & Investment Lead (Part-Time) September 2023-December 2025
    - Lead financial strategy, capital planning...
    - Build and manage underwriting models...
    - Support financing structures for $4M+...

That is TWO work_experience entries, not one. Rules:
  * Every title that has its own date range becomes its OWN entry, repeating the same
    company name. Two titles -> two entries. Three titles -> three entries.
  * NEVER collapse them into the most recent title. Doing so silently deletes years of
    tenure from the timeline — it is the single worst error you can make here.
  * NEVER drop the older/junior title just because the bullets are shared.
  * DISTRIBUTE the shared bullets — do not copy them all to the senior title. Leadership,
    strategy, ownership and client-facing bullets go to the SENIOR/most recent title;
    hands-on execution, modelling, building and analysis bullets go to the EARLIER title.
    If a bullet plainly describes the whole tenure, put it on the entry where that work
    started.
  * THE SHARED BULLETS ARE THE ONLY CONTENT YOU HAVE FOR BOTH ENTRIES. Never invent new
    bullets to fill the earlier title, and never restate a bullet you already used on the
    other entry in weaker words. Writing "Managed demand planning for multiple business
    units" or "Focused on improving accuracy and optimization" because the earlier entry
    looked empty is fabrication — those sentences exist nowhere in the source.
  * If after distributing, one entry would end up with zero bullets, MOVE one real bullet
    to it rather than inventing. An entry with a single real bullet is correct and normal.
    An entry with invented bullets is a defect.
  * Use present tense for the current title and past tense for the earlier one, even though
    the source wrote them all in the same tense.
  * Scan every company block for this pattern before you write your answer.
- "description" format: BULLETS ONLY. Every line starts with "- ". Never write an
  introductory sentence or a paragraph above the bullets — a loose line floating above the
  list looks broken in the editor and in the client-facing CV. If you want to give role
  context (scope, team, what the company does), make it the FIRST BULLET, not a paragraph.
  And if the source already states that context as one of its own bullets, keep it as a
  bullet — never promote a real bullet into an intro line.
- 4-6 substantive bullets for the roles most relevant to the target; 1-3 for less relevant
  or sparse roles. Never more than 6. Fewer, fuller bullets beat more, thinner ones — never
  split one rich piece of work into three stubs just to reach a count.

*** SPARSE ROLES — WHEN THE SOURCE ONLY GIVES TITLE, COMPANY AND DATES ***
Designed/visual CVs often list roles with no bullets at all, and put the software in a
single global "Software"/"Skills" list. In that situation:
  * Write 1-2 bullets maximum. A short honest entry is correct; a padded one is a lie.
  * NEVER attribute the global software list to a specific role. If the CV lists
    "Cinema 4D, After Effects, Photoshop" once at the bottom, you may NOT write "Used
    Cinema 4D and RedShift at this company" — the source never says where each tool was
    used. Put those tools in the tools section only.
  * NEVER invent a skill name the source does not contain (e.g. writing "Adobe Creative
    Suite" when the CV lists "Photoshop, Illustrator").
  * BANNED generic bullets that say nothing and could apply to anyone. Do not write:
    "Collaborated with cross-functional teams", "Supported senior colleagues",
    "Gained proficiency in X", "Contributed to project success", "Developed engaging
    content", "Enhanced project outcomes", "Delivered high-quality work", "Assisted in
    daily tasks". If the only thing you can write is one of these, write nothing.
  * Also banned as padding: "various projects", "diverse projects", "various media
    platforms", "a wide range of clients", "multiple industries", "enhancing visual
    storytelling", "contributing to the agency's creative output". Vague scope invented to
    fill a line. Name the real thing or leave it out.
  * What you MAY write for a sparse role: a plain statement of what that job title does,
    phrased as work, with no invented scope, clients, metrics or tools. Example for a
    "Motion Designer" with no detail: "- Produced motion graphics and animated content."
    One line. Stop there.
  * The BULLET DEPTH rules below do NOT apply here. They tell you to carry over detail the
    source already contains; a sparse role has none, so a short bullet is the right answer.
    Never use "the bullet looks too short" as a reason to invent context.

*** BULLET DEPTH — THE MOST COMMON WEAKNESS OF THIS OUTPUT ***
Clients read these bullets to decide whether to interview. A bullet that only names an
activity ("Managed accounts payable") tells them nothing they could not already guess from
the job title, and wastes the line.

*** LENGTH IS A HARD, COUNTABLE REQUIREMENT — NOT A STYLE PREFERENCE ***
TARGET: 25-40 words per bullet. HARD FLOOR: 20 words.
COUNT THE WORDS of every bullet you write. A bullet of 8-15 words is a FAILED bullet, not a
concise one, and it is the single defect this output is corrected for most often. If a
bullet lands under 20 words, you have almost certainly thrown away detail the source gave
you — go back to that role in the sources and find the tool, the volume, the cadence, the
stakeholder, the deliverable or the outcome that you dropped, and put it back.
The ONLY legitimate reason to publish a bullet under 20 words is that the source truly
contains nothing more about that work (see SPARSE ROLES above). That is rare. Assume by
default that the detail exists and you failed to look for it, not that it is missing.
Do not exceed ~45 words either — past that it stops reading like a CV.

Build each bullet in two parts:
  (a) ACTION + OBJECT — a strong verb and the concrete thing it acted on.
  (b) GROUNDED CONTEXT — one or two details that make the work legible to a reader who does
      not know the company. This is where the length comes from, and every element of it
      must already exist in the source material FOR THAT ROLE:
        * the tool, system or platform the work ran on (QuickBooks, NetSuite, Salesforce)
        * volume, value, headcount, portfolio size, number of entities/clients/markets
        * the cadence (monthly close, weekly reporting cycle, quarterly board pack)
        * who it was for or with (the CFO, US-based clients, the sales team, auditors)
        * the deliverable produced (reconciliation, dashboard, forecast model, brief)
        * what the company or business unit actually does, when the name does not say it
        * the outcome or purpose the source states (faster close, cleaner data, funded deal)

Same fact, too short then right — note that the right-hand versions add NO new facts, they
only stop discarding the ones the source already gave:
  WEAK:  "- Managed accounts payable and receivable."
  RIGHT: "- Manages accounts payable and receivable in QuickBooks for a portfolio of 12 US
          clients, owning the full monthly close and bank reconciliations."
  WEAK:  "- Built financial models."
  RIGHT: "- Builds underwriting models for real estate acquisitions, sizing debt and equity
          on $4M+ construction loans targeting 25%-35% IRRs for the investment committee."
  WEAK:  "- Handled social media."
  RIGHT: "- Runs organic social media for Flormar and Super Salon on Instagram and TikTok,
          sourcing and briefing creators and producing the monthly content calendar."
Those expansions are legal only because the source stated QuickBooks, the 12 clients, the
loan sizes, the brand names. If the source truly only supports the weak version, write the
weak version — but search the transcripts and the rest of the CV first, because the detail
usually IS there, just not in the same sentence.

- NEVER SHORTEN A SOURCE BULLET. If the source already writes a long, detailed line, your
  version carries the same content, rewritten in cleaner English — not summarized. Dropping
  half of a source bullet is the single most common way this output comes out weak.
- Each bullet: one line, starts with a strong verb. Past tense for finished roles, present
  tense for the current role. Include the concrete object of the work (system, process,
  market, deliverable, stakeholder) whenever the source names it.
- Include metrics, volumes, budgets, team sizes and tool names ONLY when they appear in the
  source for THAT role — but when they DO appear, they are mandatory. If the source bullet
  says "projects totaling $10M+", "$4M+ in construction loans targeting 25%-35% IRRs",
  "reduced discrepancies by 5%" or "AUM from $48M to $102M", your bullet must carry those
  exact figures. Rewriting "$4M+ in construction loans" as "construction loans" strips the
  CV of its strongest evidence. Before finishing, re-read every source bullet and confirm
  no number was left behind.
- INTERVIEW TRANSCRIPTS ADD CONTENT — they are not just for cross-checking. A written CV is
  always shorter than what the candidate actually did. When the candidate describes clients,
  brands, platforms, channels, team sizes, tools, deliverables or responsibilities that are
  NOT in the written CV, ADD them as extra bullets on the matching role. Example: if the CV
  says "Lead integrated digital strategies" and in the call the candidate says she runs
  social media for Flormar and Súper Salón, manages influencer campaigns on Instagram and
  TikTok, and sources and briefs creators — all of that belongs in that role's bullets.
  Failing to carry over what the candidate said in the interview wastes the best source you
  have.
- The ONLY thing you exclude from a transcript is recruiting logistics, never the work
  itself. Forbidden anywhere in the output: reason for leaving, notice period, salary
  expectations, availability, visa or relocation status, layoffs or restructuring at the
  current employer, motivations for changing jobs, and any assessment of the candidate.
  Also ignore speculation and future plans. Everything the candidate says about work they
  actually did is fair game and should be used.
- Merge overlapping facts from several sources into one bullet; never state the same fact
  twice. Prefer the most specific version of a fact.
- Expand acronyms the first time they appear when the source makes their meaning clear.
- Do NOT add a "Tools:" line inside any role description.

DATES (work experience)
- Always "YYYY-MM-DD". If the source gives only month/year, use the first day of that month.
  If the source gives only a year, use YYYY-01-01. Never guess a day.
- Ongoing role: "current": true and "end_date": "".
- If the dates for a role cannot be determined at all, leave them as empty strings but still
  include the role.

=========================
EDUCATION
=========================
- One entry per degree/program. Include certifications only if they are substantial programs.
- NEVER UPGRADE THE LEVEL OF A DEGREE, AND ALWAYS WRITE IT IN ENGLISH. These are two
  separate rules and they do not conflict: you may not change WHAT the qualification is,
  and you must write it in the CLIENT'S LANGUAGE. Keeping the source's own level is
  mandatory; keeping the source's own Spanish or Portuguese wording is a defect — this CV
  goes to a US client and every "title" must be English.
  * Translate the qualification literally, at the exact same academic level:
    "Licenciatura en Administración de Empresas" -> "Bachelor's Degree in Business
    Administration"; "Contador Público" -> "Public Accountant"; "Técnico Superior en
    Comercio Exterior" -> "Advanced Technical Degree in Foreign Trade"; "Tecnicatura en
    Programación" -> "Technical Degree in Programming"; "Diplomado en Finanzas" ->
    "Diploma in Finance"; "Maestría"/"Magíster" -> "Master's Degree"; "Especialización"
    -> "Postgraduate Specialization"; "Curso de..." -> "Course in...".
  * "Bachiller"/"Bachillerato" is SECONDARY SCHOOL -> "High School Diploma". It is NEVER
    a "Bachelor's Degree" — that false friend is the most common error here.
  * A "Técnico Superior" / "Advanced Technical Degree" is NOT a Bachelor's. A "Diplomado"
    or a certificate is not a Master's. If the CV and LinkedIn disagree on the level, use
    the more conservative (lower) one.
  * Translating is NOT inventing. What is forbidden is changing the level, adding a field
    of study, a specialization, honours or a thesis the source never named, or "improving"
    a vague program into a specific one. If a qualification has no clean English
    equivalent, translate it word for word and stop there — never leave it in Spanish and
    never guess an equivalent that implies a higher level.
- The institution name is a proper name: leave it exactly as the source writes it. Do NOT
  translate "Universidad Nacional de Córdoba" or "Instituto Tecnológico de Monterrey".
- "description" and "country" are English too ("Spain", not "España").
- "description": EXACTLY two sentences on a SINGLE line (no line breaks, no "- " bullets,
  ~30-45 words total) briefly describing the subjects the program covers, plus any explicit
  detail from the source (thesis, honors, specialization, exchange, notable coursework).
- The two sentences must stay within what the degree title plainly implies plus what the
  source explicitly states. Example, for "Bachelor's Degree in Business Administration":
  "Covered accounting, finance, operations and organizational management, with a focus on
  business analysis and decision-making. Included coursework in economics, marketing and
  corporate strategy." Do not claim specific courses, grades, projects or honors that are
  not in the source and not plainly implied by the degree name.
- When a target role is given, emphasize the parts of the program that connect to it —
  without inventing anything.

DATES (education)
- "YYYY-MM-DD". Full range if the source gives a range. Month/year if given.
- If the source gives only ONE year for the program, set "start_date": "YYYY-01-01" and
  "end_date": "YYYY-12-31" and "current": false.
- If the source gives only a GRADUATION date (e.g. "December 2018", "May 2023") and no start,
  put it in "end_date" and leave "start_date" as an empty string. Never set start and end to
  the same date — that renders as a zero-length range — and never invent a start year.
- If the source gives NO dates at all for a program, leave both as empty strings. That is
  correct and expected; do not guess.
- Ongoing studies: "current": true and "end_date": "".

COUNTRY (education)
- Fill "country" whenever the source explicitly gives a country, or a city/region that
  unambiguously identifies one ("Barcelona, Spain" -> "Spain", "Loja, Ecuador" -> "Ecuador",
  "Sydney" -> "Australia"). If ambiguous, leave it as an empty string.

=========================
TOOLS
=========================
- Only real software, platforms, systems and technical frameworks the candidate has actually
  used. No soft skills, no spoken languages, no methodologies-as-buzzwords, no company names.
- SPELL EACH TOOL EXACTLY AS THE SOURCE SPELLS IT. "NetX360" is not "Net360", "Power BI" is
  not "PowerBI". Copy the string, do not normalize or abbreviate it from memory.
- EVERY tool must have an explicit level: exactly "Basic", "Intermediate" or "Advanced".
  Assign the real level using the evidence:
  * Advanced — 4+ years of hands-on use, or the tool is central to their main roles across
    multiple jobs, or the source/interview says expert/advanced/daily/administrator/trained
    others/holds a certification in it.
  * Intermediate — roughly 1-3 years of regular use, or used substantively in a specific
    project or role, or named as a core skill without depth evidence.
  * Basic — mentioned once, exposure only, "familiar with", "learning", "basic".
- Use the dates of the roles where the tool appears to estimate years of use, relative to
  TODAY'S DATE above. Never leave a level blank.
- If the source explicitly states a level (e.g. "Technical Skills: Advanced in X, Y, Z"),
  USE IT even if that means several tools share the same level.
- If the source states NO levels — just a flat software list — do NOT mark everything
  "Advanced". You have no evidence for that, and an all-Advanced list reads as inflated to
  a client. Infer conservatively from how central each tool is to the roles and how long
  it has been in use: "Intermediate" is the honest default, "Advanced" only for the two or
  three tools that are clearly core to the candidate's main job, "Basic" for the peripheral
  ones. The result must be a mix.
- Maximum 15 tools. When a target role is given, list the tools relevant to it first.

=========================
LANGUAGES
=========================
- Spoken languages only. Allowed names, spelled exactly like this and nothing else:
  "English", "Spanish", "Portuguese", "French", "German". Omit any other language.
- Allowed levels, exactly: "Basic", "Regular", "Fluent", "Native".
  Map source wording: native/bilingual/mother tongue -> "Native";
  C1/C2/advanced/fluent/full professional/professional working -> "Fluent";
  B1/B2/intermediate/conversational/limited working -> "Regular";
  A1/A2/beginner/elementary/basic -> "Basic".
- If a language is listed with NO level at all, do not upgrade it. Use "Regular" — never
  assume "Fluent" or "Native" from a bare mention. The only exception is the candidate's
  own native language (see below).
- Include a language only when there is evidence. Two inferences ARE allowed:
  (a) the candidate's native language may be inferred from their country and from the
      language the source documents are written in;
  (b) the English level may be inferred from an interview transcript conducted in English —
      if the candidate held a full professional conversation in English, that is "Fluent".
  Beyond these two, do not guess.

=========================
FINAL CHECK BEFORE ANSWERING
=========================
Go back over your draft and verify each of these. Fix anything that fails.
- ROLE LIST: every role printed on the WRITTEN CV is present. Then check the reverse — for
  each entry you produced, confirm that company appears on the written CV. If one does not,
  it came from LinkedIn or a transcript only, and unless the recruiter asked for it or there
  was no usable CV at all, DELETE IT.
- STACKED TITLES: for every company, count the titles that have their own date range ON THE
  WRITTEN CV, and count your entries for that company. The two numbers must match. If the CV
  shows two titles at one company and you produced one entry, you deleted a role — go back
  and split it.
- NO DUPLICATE ROLES: list your entries and compare every pair. If two entries share the same
  company and the same or overlapping dates, they are the same role reaching you from two
  different sources under two spellings ("Junior" vs "Jr.", Spanish vs English, short vs long
  company name). Merge them into one entry with the combined bullets and delete the extra.
- No gaps you created: the date ranges of your entries must cover the same span the source
  covers for each company.
- Every number in the source bullets you used appears in your bullets.
- BULLET WORD COUNT — DO THIS ONE LITERALLY. Go bullet by bullet and count the words. For
  every bullet under 20 words, return to that role in the sources and look for the tool,
  volume, cadence, stakeholder, deliverable or outcome you left out, and rewrite the bullet
  with it. Only if the source genuinely holds nothing more may the short bullet stay. Most
  of your bullets should land in the 25-40 word range.
- No bullet came out shorter or less specific than the source line it came from.
- RECRUITER INSTRUCTIONS: re-read that block. Every fact the recruiter added appears in the
  exact role they named, and every direction they gave was applied. If any instruction did
  not land, fix it now — this is the most visible failure to the person reviewing the CV.
- Every company and institution name is the full version the source uses; no "Unnamed" or
  invented placeholders anywhere.
- Every bullet can be pointed back to a specific line in the source material.
- JD LEAK SWEEP — do this over the WHOLE draft, About included, not just the bullets. Take
  every industry, platform, tool, channel and specialty you named anywhere in the CV and
  ask: does the SOURCE MATERIAL show this candidate doing it? If it only appears in the job
  description, delete it. Then re-read each sentence and ask whether it could have been
  written for any other applicant to this same opening; if yes, it is the JD talking and it
  has to go or be rewritten around what this person actually did.
- No meta-commentary about the CV or the sources anywhere.
- The About does not contain any banned filler phrase and does not start with "This
  candidate" or "A professional".
- Every tool has a level; the levels are not all identical; tool names are spelled as in
  the source.
- Education descriptions are single-line two-sentence paragraphs, not bullets.
- LANGUAGES: for each one, did the source actually state a level? If it just listed the
  language with no level, it must be "Regular" — not "Fluent", not "Native". Only the
  candidate's own native language and a language they demonstrably conducted the interview
  in may be rated higher.
- SPARSE ROLES: no role invented tools, scope, clients or metrics that the source did not
  attach to that specific role, and no padding phrases.
- Output is one raw JSON object, parseable as-is.
"""

def _score_applicant_with_openai(
    extracted_pdf: str,
    applicant_location: str,
    job_description: str,
    filters: Optional[Dict[str, Any]] = None,
    opportunity_context: Optional[Dict[str, Any]] = None,
    candidate_context: Optional[Dict[str, Any]] = None,
):
    return score_candidate_against_job(
        extracted_pdf,
        applicant_location,
        job_description,
        filters=filters,
        opportunity_context=opportunity_context,
        candidate_context=candidate_context,
    )

def _recalculate_applicant_scores(opportunity_id: int, filters: Optional[Dict[str, Any]] = None):
    filters = filters or {}
    conn = get_connection()
    cursor = conn.cursor()
    try:
        jd_plain, opp_context = _build_opportunity_context(cursor, opportunity_id)
        cursor.execute(
            """
            SELECT applicant_id, location, extracted_pdf, role_position, area
            FROM applicants
            WHERE opportunity_id = %s
            """,
            (opportunity_id,),
        )
        rows = cursor.fetchall()
        updated = 0
        for applicant_id, location, extracted_pdf, role_position, area in rows:
            if not extracted_pdf:
                continue
            score, reasons = _score_applicant_with_openai(
                extracted_pdf,
                location or "",
                jd_plain,
                filters=filters,
                opportunity_context=opp_context,
                candidate_context={"role_position": role_position or "", "area": area or ""},
            )
            if score is None and not reasons:
                continue
            cursor.execute(
                """
                UPDATE applicants
                SET match_score = %s,
                    reasons = %s,
                    updated_at = NOW()
                WHERE applicant_id = %s
                """,
                (score, reasons, applicant_id),
            )
            updated += 1
        conn.commit()
        return updated
    finally:
        cursor.close()
        conn.close()

def _extract_grain_recording_id(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""

    if re.fullmatch(r"[A-Za-z0-9_-]{8,}", raw):
        return raw

    try:
        parsed = urlparse(raw)
    except Exception:
        return ""

    path_parts = [part for part in parsed.path.split("/") if part]
    query = parse_qs(parsed.query or "")

    for key in ("recording_id", "recordingId", "id"):
        values = query.get(key) or []
        for item in values:
            candidate = (item or "").strip()
            if re.fullmatch(r"[A-Za-z0-9_-]{8,}", candidate):
                return candidate

    preferred_markers = {"recordings", "recording", "r"}
    for index, part in enumerate(path_parts[:-1]):
        if part.lower() in preferred_markers:
            candidate = path_parts[index + 1].strip()
            if re.fullmatch(r"[A-Za-z0-9_-]{8,}", candidate):
                return candidate

    if len(path_parts) >= 3 and path_parts[0].lower() == "share" and path_parts[1].lower() == "recording":
        candidate = path_parts[2].strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{8,}", candidate):
            return candidate

    for part in reversed(path_parts):
        candidate = part.strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{8,}", candidate):
            return candidate

    return ""

def _extract_grain_transcript_text(value: Any) -> str:
    lines = []

    def walk(node: Any):
        if node is None:
            return
        if isinstance(node, str):
            text = re.sub(r"\s+", " ", node).strip()
            if text:
                lines.append(text)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return

        speaker = (
            node.get("speaker_name")
            or node.get("speaker")
            or node.get("participant_name")
            or node.get("name")
        )
        text_fields = [
            node.get("text"),
            node.get("transcript"),
            node.get("utterance"),
            node.get("content"),
        ]
        joined = " ".join(
            re.sub(r"\s+", " ", str(item)).strip()
            for item in text_fields
            if isinstance(item, str) and item.strip()
        ).strip()
        if joined:
            if speaker:
                lines.append(f"{speaker}: {joined}")
            else:
                lines.append(joined)
            return

        for key in (
            "utterances",
            "segments",
            "entries",
            "items",
            "paragraphs",
            "transcript",
            "results",
            "data",
            "words",
            "children",
        ):
            if key in node:
                walk(node[key])

    walk(value)

    deduped = []
    seen = set()
    for line in lines:
        normalized = line.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(line)

    return "\n".join(deduped).strip()

def _fetch_grain_transcript_from_link(link_or_id: str) -> str:
    recording_id = _extract_grain_recording_id(link_or_id)
    if not recording_id:
        raise ValueError("Invalid Grain recording link.")

    token = (os.getenv("GRAIN_API_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("Grain integration is not configured. Missing GRAIN_API_TOKEN.")

    response = requests.get(
        f"https://api.grain.com/_/workspace-api/recordings/{recording_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        params={
            "transcript_format": "json",
        },
        timeout=30,
    )
    if not response.ok:
        logging.error("Grain error body for recording_id=%s: %s", recording_id, response.text)
        raise RuntimeError(f"Failed to fetch Grain recording ({response.status_code}): {response.text}")

    payload = response.json()
    transcript = (
        _extract_grain_transcript_text(payload.get("transcript_json"))
        or _extract_grain_transcript_text(payload.get("transcript"))
    )
    if not transcript:
        raise RuntimeError("The Grain recording did not return transcript content.")

    if (os.getenv("GRAIN_DEBUG_LOGS") or "").strip().lower() in {"1", "true", "yes", "on"}:
        logging.info("Grain transcript fetched for recording_id=%s", recording_id)
        logging.info("Grain transcript preview (%s chars): %s", len(transcript), transcript[:1500])

    return transcript

def register_ai_routes(app):
    @app.route('/ai/jd_to_career_fields', methods=['POST', 'OPTIONS'])
    def jd_to_career_fields():
        """
        Recibe: { "job_description": "<texto o HTML del JD>" }
        Devuelve: { "career_description": str, "career_requirements": str, "career_additional_info": str }
        *No inventa información; solo reorganiza lo que viene en el JD.*
        """
        # CORS preflight
        if request.method == 'OPTIONS':
            resp = app.response_class(status=204)
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            resp.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
            resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,PATCH,OPTIONS'
            return resp

        try:
            data = request.get_json(force=True) or {}
            raw_jd = (data.get('job_description') or '').strip()
            opp_id = data.get('opportunity_id')
            if not raw_jd:
                return jsonify({"error": "job_description is required"}), 400

            # Quita HTML simple si te llega el editor con tags
            import re
            jd_plain = re.sub(r'<[^>]+>', ' ', raw_jd)
            jd_plain = re.sub(r'\s+', ' ', jd_plain).strip()
            logging.info("📄 Talentum JD extract opp_id=%s len=%s", opp_id, len(jd_plain or ""))

            prompt = f"""
You are an ATS-friendly job description analyzer.
Read ONLY the provided job description text and return a STRICT JSON object with 3 fields:

- career_description: one cohesive paragraph that summarizes the role and its main responsibilities exactly as stated in the JD (no lists, no headings).
- career_requirements: a bullet list using "- " (hyphen + space) of the qualifications/requirements explicitly asked for in the JD (education, years of experience, skills, tools, certifications, languages, etc).
- career_additional_info: everything relevant that is NOT already included above (company info, benefits, nice to have, location, schedule, compensation clues, culture, notes).

Rules:
- DO NOT invent, infer or generalize beyond what is explicitly stated in the JD.
- If a section doesn't exist in the JD, return an empty string for that field.
- Output valid, minified JSON. No markdown, no extra commentary, no code fences.
- Translate everything to English.

JOB DESCRIPTION (verbatim):
---
{jd_plain}
---
"""

            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,       # 👈 cero creatividad = no inventar
                max_tokens=1200
            )

            content = (chat.choices[0].message.content or "").strip()

            # Limpia si llegara con ```json ... ```
            import json, re
            cleaned = re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', content)
            try:
                obj = json.loads(cleaned)
            except Exception:
                # fallback: devolver todo vacío para no romper el front
                obj = {
                    "career_description": "",
                    "career_requirements": "",
                    "career_additional_info": ""
                }

            # Normaliza tipos → siempre strings
            def as_text(v):
                if v is None:
                    return ""
                if isinstance(v, list):
                    # Si vino como lista, únelas con saltos
                    return "\n".join(str(x).strip() for x in v if str(x).strip())
                return str(v).strip()

            result = {
                "career_description": as_text(obj.get("career_description", "")),
                "career_requirements": as_text(obj.get("career_requirements", "")),
                "career_additional_info": as_text(obj.get("career_additional_info", ""))
            }

            resp = jsonify(result)
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp, 200

        except Exception as e:
            logging.error("❌ /ai/jd_to_career_fields failed\n" + traceback.format_exc())
            resp = jsonify({"error": str(e)})
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp, 500


    @app.route('/ai/jd_to_talentum_filters', methods=['POST', 'OPTIONS'])
    def jd_to_talentum_filters():
        """
        Recibe: { "job_description": "<texto o HTML del JD>" }
        Devuelve: { "position": str, "salary": str, "years_experience": str, "industry": str, "country": str }
        *No inventa información; solo extrae lo explícito del JD.*
        """
        if request.method == 'OPTIONS':
            resp = app.response_class(status=204)
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            resp.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
            resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,PATCH,OPTIONS'
            return resp

        try:
            data = request.get_json(force=True) or {}
            raw_jd = (data.get('job_description') or '').strip()
            if not raw_jd:
                return jsonify({"error": "job_description is required"}), 400

            import re
            jd_plain = re.sub(r'<[^>]+>', ' ', raw_jd)
            jd_plain = re.sub(r'\s+', ' ', jd_plain).strip()
            prompt = f"""
You are a strict job description parser.
Read ONLY the provided job description text and return a STRICT JSON object with EXACTLY these fields:

- position: title/role name as written in the JD.
- salary: compensation, range, or currency details as written in the JD.
- years_experience: years of experience requirement as written in the JD.
- industry: industry or domain as written in the JD.
- country: country or location as written in the JD.

Rules:
- DO NOT invent or infer beyond the text.
- If a field is missing, return an empty string.
- Output valid, minified JSON. No markdown, no commentary, no code fences.
- Keep original language from the JD for extracted values.

JOB DESCRIPTION (verbatim):
---
{jd_plain}
---
"""

            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=500
            )

            content = (chat.choices[0].message.content or "").strip()
            cleaned = re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', content)
            try:
                obj = json.loads(cleaned)
            except Exception:
                obj = {}

            def as_text(v):
                if v is None:
                    return ""
                if isinstance(v, list):
                    return " ".join(str(x).strip() for x in v if str(x).strip())
                return str(v).strip()

            result = {
                "position": as_text(obj.get("position", "")),
                "salary": as_text(obj.get("salary", "")),
                "years_experience": as_text(obj.get("years_experience", "")),
                "industry": as_text(obj.get("industry", "")),
                "country": as_text(obj.get("country", "")),
            }

            resp = jsonify(result)
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp, 200

        except Exception as e:
            logging.error("❌ /ai/jd_to_talentum_filters failed\n" + traceback.format_exc())
            resp = jsonify({"error": str(e)})
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp, 500


    @app.route('/ai/talentum_chat_update', methods=['POST', 'OPTIONS'])
    def talentum_chat_update():
        """
        Recibe: { "message": "<user text>", "current_filters": {...} }
        Devuelve: { "updated_filters": {...}, "response": "<assistant text>" }
        """
        if request.method == 'OPTIONS':
            resp = app.response_class(status=204)
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            resp.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
            resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,PATCH,OPTIONS'
            return resp

        try:
            data = request.get_json(force=True) or {}
            message = (data.get('message') or '').strip()
            current_filters = data.get('current_filters') or {}
            opportunity_id = data.get('opportunity_id')

            if not message:
                return jsonify({"error": "message is required"}), 400

            updated, response, needs_ai = _parse_filters_without_ai(message, current_filters)

            if needs_ai:
                prompt = f"""
You are a recruiting assistant updating filters.
Current filters (JSON):
{json.dumps(current_filters, ensure_ascii=False)}

User message:
\"\"\"{message}\"\"\"

Update ONLY these fields: position, salary, years_experience, industry, country.
Rules:
- If the user explicitly asks to remove or ignore a filter, set that field to "".
- If the user adds constraints, update or add the field accordingly.
- If the message is unrelated, keep filters unchanged.
- DO NOT invent data. Use only what the user says.

Return STRICT JSON:
{{"updated_filters": {{...}}, "response": "<short Spanish summary of changes>" }}
"""

                chat = call_openai_with_retry(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=350
                )

                content = (chat.choices[0].message.content or "").strip()
                cleaned = re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', content)
                try:
                    payload = json.loads(cleaned)
                except Exception:
                    payload = {}

                maybe_updated = payload.get("updated_filters")
                if isinstance(maybe_updated, dict):
                    updated = maybe_updated

                maybe_response = payload.get("response")
                if isinstance(maybe_response, str) and maybe_response.strip():
                    response = maybe_response.strip()

            if not isinstance(updated, dict):
                updated = current_filters
            if not isinstance(response, str) or not response.strip():
                response = "Listo, actualicé los filtros con tu mensaje."

            rescored = None
            if opportunity_id is not None:
                try:
                    rescored = _recalculate_applicant_scores(int(opportunity_id), updated)
                except Exception:
                    logging.exception("❌ Failed to rescore applicants from chat update")

            payload = {"updated_filters": updated, "response": response.strip()}
            if rescored is not None:
                payload["rescored"] = rescored

            resp = jsonify(payload)
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp, 200

        except Exception as e:
            logging.error("❌ /ai/talentum_chat_update failed\n" + traceback.format_exc())
            resp = jsonify({"error": str(e)})
            resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
            return resp, 500


    @app.route('/ai/improve_tools', methods=['POST'])
    def improve_tools_section():
        try:
            data = request.json
            candidate_id = data['candidate_id']
            user_prompt = data.get('user_prompt', '').strip()
            history_block = _format_section_chat_history(data.get('history'))
            ctx = _load_section_editor_context(
                candidate_id, data.get('opportunity_id')
            )

            conn = get_connection()
            cursor = conn.cursor()

            # Obtener tools actuales
            cursor.execute("SELECT tools FROM resume WHERE candidate_id = %s", (candidate_id,))
            row = cursor.fetchone()
            tools = (row[0] if row else None) or "[]"

            # Las tools suelen vivir en una lista global al final del CV, así que
            # recortar la fuente a 2000 chars era justo perderla.
            cursor.execute("SELECT work_experience FROM resume WHERE candidate_id = %s", (candidate_id,))
            row = cursor.fetchone()
            work_experience_for_tools = (row[0] if row else None) or "[]"

            prompt = f"""
    You are a resume tools editor.

    --- CURRENT TOOLS ---
    {tools}

    --- WORK EXPERIENCE (to judge how central and how long-used each tool is) ---
    {work_experience_for_tools}

    {ctx["target_role_block"]}

    --- LINKEDIN SCRAP ---
    {ctx["linkedin"]}

    --- PDF SCRAP ---
    {ctx["cv"]}

    --- CONVERSATION SO FAR (oldest first) ---
    {history_block}
{SECTION_CHAT_RULES}
    --- RECRUITER'S LATEST INSTRUCTION (this is what you must act on now) ---
    {user_prompt}

    Improve the tools section using this info. Return STRICT JSON, one object:
    {{"entries": [{{"tool":"Excel","level":"Advanced"}},{{"tool":"QuickBooks","level":"Intermediate"}}],
      "summary": "..."}}

    - "entries" is the FULL updated tools list, not only the ones you touched.
    - "summary" is a STRING (not a list): what changed, plain English, max 4 short lines
      separated by \\n ("Added Xero (Intermediate)", "QuickBooks: Basic -> Advanced").
      Never vague.
    - Infer the level (Basic, Intermediate, Advanced) based on context.
    - Do NOT invent tools. The exception is a tool the recruiter names in their
      instruction — they know the candidate, so add it where they say.
    - If no level is specified, infer from experience.
    - translate everything to english
    """

            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=800
            )

            content = chat.choices[0].message.content.strip()
            tools_json, change_summary = _parse_section_edit_payload(content, "tools")
            if not isinstance(tools_json, list):
                raise ValueError("The model did not return a tools list.")

            cursor.execute("UPDATE resume SET tools = %s WHERE candidate_id = %s", (json.dumps(tools_json), candidate_id))
            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"tools": json.dumps(tools_json), "summary": change_summary})
        except Exception as e:
            logging.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route('/ai/improve_work_experience', methods=['POST'])
    def improve_work_experience_section():
        try:
            data = request.json
            candidate_id = data['candidate_id']
            user_prompt = data.get('user_prompt', '').strip()
            history_block = _format_section_chat_history(data.get('history'))
            ctx = _load_section_editor_context(
                candidate_id, data.get('opportunity_id')
            )

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT work_experience FROM resume WHERE candidate_id = %s", (candidate_id,))
            row = cursor.fetchone()
            work_experience = (row[0] if row else None) or "[]"

            prompt = f"""
    You are a resume work experience editor.

    --- CURRENT WORK EXPERIENCE ---
    {work_experience}

    --- CANDIDATE ---
    {ctx["name"]} ({ctx["country"]})

    {ctx["target_role_block"]}

    --- LINKEDIN SCRAP ---
    {ctx["linkedin"]}

    --- PDF SCRAP (the written CV — this decides which roles exist) ---
    {ctx["cv"]}

    --- CONVERSATION SO FAR (oldest first) ---
    {history_block}
{SECTION_CHAT_RULES}
    --- RECRUITER'S LATEST INSTRUCTION (this is what you must act on now) ---
    {user_prompt}

    Improve the work experience section using this info. Return STRICT JSON, one object:
    {{"entries": [ {{"title":"...", "company":"...", "start_date":"YYYY-MM-DD", "end_date":"YYYY-MM-DD", "current":true/false, "description":"..."}} ],
      "summary": "..."}}

    - "entries" is the FULL updated section — include every role, not only the edited ones.
    - "description" MUST be a bullet list in PLAIN TEXT: every line starts with "- " and
      lines are separated by \\n. Never write HTML (<ul>, <li>, <p>) and never merge the
      bullets into one paragraph — a role whose bullets got flattened into prose is a
      broken entry. Example: "- Leads digital strategy...\\n- Runs website audits...".
    - "summary" is a STRING, not a list. Plain English, what you actually changed, one
      short line per change, max 4 lines separated by \\n, each starting with the company
      name. Be concrete: "Acme Corp: added QuickBooks and the monthly close to the
      bullets" — never vague ("improved the section"). If you changed nothing, say so
      and why.
    - If month or day is missing, complete with 01
    - If end_date is missing or says "present", set current = true
    - Else set current = false
    - translate everything to english

    WHICH ROLES EXIST — do not add roles. The entries in CURRENT WORK EXPERIENCE are the
    role list; keep exactly those, and never create a new entry for a job you spot in the
    LinkedIn scrape but that is not already there. The candidate left those off their own CV
    on purpose. LinkedIn and the PDF are here to ENRICH the existing entries with detail
    (responsibilities, tools, clients, scope, metrics) that did not fit on the page. Never
    list the same role twice: if a role reaches you under two spellings ("Junior" vs "Jr.",
    Spanish vs English title, short vs long company name), it is one entry. The only way a
    new role gets added is if the RECRUITER INSTRUCTIONS explicitly ask for it.

    RECRUITER INSTRUCTIONS — the block above was written by the recruiter who knows this
    candidate, almost always because the current version came out wrong. It may contain:
      (a) FACTS they are adding from their own knowledge (a tool, client, employer, metric
          or responsibility missing from the CV). Treat these as source material — the
          recruiter vouches for them, so using them is NOT fabrication. Put each fact
          exactly where they say it belongs: "add QuickBooks and Xero to the work
          experience at Acme" means those tools go into the Acme role's bullets and nowhere
          else. Find that exact company, never a similar one.
      (b) DIRECTIONS on how to write it, which override every default below.
    Apply every instruction completely, then re-read the block to confirm each one landed.
    The only thing it cannot override is inventing facts nobody supplied.

    BULLET DEPTH — the usual defect here is bullets too short to tell a client anything.
    "description" is bullets only, every line starting with "- ", 4-6 bullets for a rich
    role and 1-3 for a sparse one. TARGET 25-40 WORDS PER BULLET, HARD FLOOR 20 — count the
    words. A bullet of 8-15 words is a failed bullet, not a concise one. Each bullet is a
    strong verb plus the concrete object of the work, plus one or two grounded details: the
    tool or system used, volumes/values/headcounts, the cadence (monthly close, weekly
    reporting), who it was for (the CFO, US clients, auditors), the deliverable produced, or
    the stated outcome. Take those details ONLY from the sources or the recruiter block
    above — never invent a tool, client, metric or scope, and never pad with filler like
    "collaborated with cross-functional teams" or "various projects". If a bullet already in
    CURRENT WORK EXPERIENCE is detailed, keep that detail; rewriting it shorter is a
    regression. If the source genuinely has nothing more for a role, a short honest bullet
    is correct — but that is rare, so look properly before settling for one.
    """

            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                # Antes 0.6: con fuentes completas y una orden de "agregá más info", la
                # temperatura alta era una invitación a inventar.
                temperature=0.2,
                max_tokens=12000
            )

            content = chat.choices[0].message.content.strip()
            work_json, change_summary = _parse_section_edit_payload(
                content, "work_experience"
            )
            if not isinstance(work_json, list):
                raise ValueError("The model did not return a work experience list.")
            work_json = [e for e in work_json if isinstance(e, dict)]

            today = datetime.date.today()
            for entry in work_json:
                if entry.get("start_date", "").count("-") == 0:
                    entry["start_date"] += "-01-01"
                elif entry.get("start_date", "").count("-") == 1:
                    entry["start_date"] += "-01"

                if entry.get("end_date", "") in ["", None, "present", "Present"]:
                    entry["end_date"] = ""
                    entry["current"] = True
                else:
                    if entry["end_date"].count("-") == 0:
                        entry["end_date"] += "-01-01"
                    elif entry["end_date"].count("-") == 1:
                        entry["end_date"] += "-01"
                    try:
                        end = datetime.datetime.strptime(entry["end_date"], "%Y-%m-%d").date()
                        entry["current"] = end > today
                    except:
                        entry["current"] = False

                # El flujo de generación hacía esto y el editor no: por eso cada
                # edición devolvía "- linea" en crudo y los bullets se veían como
                # un párrafo aplastado en el CV.
                entry["description"] = _format_description_to_html(
                    entry.get("description", ""), bullets_only=True
                )

            work_json = _sort_work_entries_reverse_chronological(work_json)

            cursor.execute("UPDATE resume SET work_experience = %s WHERE candidate_id = %s", (json.dumps(work_json), candidate_id))
            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({
                "work_experience": json.dumps(work_json),
                "summary": change_summary,
            })

        except Exception as e:
            logging.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500




    @app.route('/ai/improve_education', methods=['POST'])
    def improve_education_section():
        try:
            data = request.json
            candidate_id = data['candidate_id']
            user_prompt = data.get('user_prompt', '').strip()
            history_block = _format_section_chat_history(data.get('history'))
            ctx = _load_section_editor_context(
                candidate_id, data.get('opportunity_id')
            )

            conn = get_connection()
            cursor = conn.cursor()

            # Obtener education actual
            cursor.execute("SELECT education FROM resume WHERE candidate_id = %s", (candidate_id,))
            row = cursor.fetchone()
            education = (row[0] if row else None) or "[]"

            # Guardamos los title/country previos: el modelo a veces los omite y
            # el UPDATE de más abajo pisa el array entero, borrándolos.
            try:
                previous_education = json.loads(education)
                if not isinstance(previous_education, list):
                    previous_education = []
            except Exception:
                previous_education = []

            prompt = f"""
    You are a resume education editor.

    --- CURRENT EDUCATION SECTION ---
    {education}

    {ctx["target_role_block"]}

    --- LINKEDIN SCRAP ---
    {ctx["linkedin"]}

    --- PDF SCRAP ---
    {ctx["cv"]}

    --- CONVERSATION SO FAR (oldest first) ---
    {history_block}
{SECTION_CHAT_RULES}
    --- RECRUITER'S LATEST INSTRUCTION (this is what you must act on now) ---
    {user_prompt}

    Improve the education section using this info. Return STRICT JSON, one object:
    {{"entries": [ {{"institution":"...", "title":"...", "country":"...", "start_date":"YYYY-MM-DD", "end_date":"YYYY-MM-DD", "current":true/false, "description":"..."}} ],
      "summary": "..."}}

    - "entries" is the FULL updated section, not only the entries you touched.
    - "description" is plain text, two sentences on one line — no HTML, no "- " bullets.
    - "summary" is a STRING (not a list): what changed, plain English, max 4 short lines
      separated by \\n, each starting with the institution name. Never vague.
    - ALWAYS return "title" (the degree/program name) and "country" for every entry.
      Keep the values already present in the current education section unless the
      sources clearly correct them. Never drop them and never return them empty
      when the current section already has a value.
    - If month or day is missing, complete with 01
    - If end_date is missing or says "present", set current = true
    - Else set current = false
    - EVERYTHING IS IN ENGLISH: "title", "description" and "country". This CV goes to a US
      client, so a degree left in Spanish or Portuguese is a defect — if an entry already
      on screen is in Spanish, translate it even if the recruiter did not ask.
      Translating is NOT changing the entry, so it does not break the rule above.
    - NEVER UPGRADE THE LEVEL OF A DEGREE when translating it. Same level, English words:
      "Licenciatura en X" -> "Bachelor's Degree in X"; "Contador Público" -> "Public
      Accountant"; "Técnico Superior en X" -> "Advanced Technical Degree in X";
      "Tecnicatura" -> "Technical Degree"; "Diplomado" -> "Diploma"; "Maestría" ->
      "Master's Degree"; "Especialización" -> "Postgraduate Specialization".
      "Bachiller"/"Bachillerato" is secondary school -> "High School Diploma", NEVER
      "Bachelor's Degree". Never add a field of study, specialization or honours the
      source did not name, and never invent a program name — if you cannot map it,
      translate it word for word.
    - The institution is a proper name: keep it exactly as it is, do not translate
      "Universidad Nacional de Córdoba".
    """

            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1500
            )

            content = chat.choices[0].message.content.strip()
            education_json, change_summary = _parse_section_edit_payload(
                content, "education"
            )
            if not isinstance(education_json, list):
                raise ValueError("The model did not return an education list.")
            education_json = [e for e in education_json if isinstance(e, dict)]

            today = datetime.date.today()
            for entry in education_json:
                if entry.get("start_date", "").count("-") == 0:
                    entry["start_date"] += "-01-01"
                elif entry.get("start_date", "").count("-") == 1:
                    entry["start_date"] += "-01"

                if entry.get("end_date", "") in ["", None, "present", "Present"]:
                    entry["end_date"] = ""
                    entry["current"] = True
                else:
                    if entry["end_date"].count("-") == 0:
                        entry["end_date"] += "-01-01"
                    elif entry["end_date"].count("-") == 1:
                        entry["end_date"] += "-01"
                    try:
                        end = datetime.datetime.strptime(entry["end_date"], "%Y-%m-%d").date()
                        entry["current"] = end > today
                    except:
                        entry["current"] = False

            # Restaurar title/country desde la entrada previa equivalente cuando
            # el modelo los devolvió vacíos o directamente los omitió.
            def _match_previous(entry):
                institution = _fold_location_text(entry.get("institution"))
                if not institution:
                    return None
                for prev in previous_education:
                    if not isinstance(prev, dict):
                        continue
                    if _fold_location_text(prev.get("institution")) == institution:
                        return prev
                return None

            for entry in education_json:
                if not isinstance(entry, dict):
                    continue
                # Igual que en work experience: el editor no formateaba y guardaba
                # el texto crudo, mientras el flujo de generación sí lo hacía.
                entry["description"] = _format_description_to_html(
                    entry.get("description", "")
                )
                prev = _match_previous(entry)
                if not prev:
                    entry.setdefault("title", "")
                    entry.setdefault("country", "")
                    continue
                for field in ("title", "country"):
                    if not str(entry.get(field) or "").strip():
                        entry[field] = prev.get(field, "") or ""

            cursor.execute("UPDATE resume SET education = %s WHERE candidate_id = %s", (json.dumps(education_json), candidate_id))
            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({
                "education": json.dumps(education_json),
                "summary": change_summary,
            })

        except Exception as e:
            logging.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500



    @app.route('/ai/improve_about', methods=['POST'])
    def improve_about_section():
        
        try:
            data = request.json
            candidate_id = data['candidate_id']
            user_prompt = data.get('user_prompt', '').strip()
            history_block = _format_section_chat_history(data.get('history'))
            ctx = _load_section_editor_context(
                candidate_id, data.get('opportunity_id')
            )

            conn = get_connection()
            cursor = conn.cursor()

            # Extraer información de la base
            cursor.execute("SELECT about, education, work_experience, tools FROM resume WHERE candidate_id = %s", (candidate_id,))
            result = cursor.fetchone()
            about, education, work_experience, tools = result if result else ("", "[]", "[]", "[]")

            # El nombre sale de la base, no del request: el chat de sección no lo
            # mandaba, así que el modelo escribía "The candidate" cuando le pedían
            # justamente que usara el nombre.
            candidate_name = (data.get("candidate_name") or "").strip() or ctx["name"]

            prompt = f"""
            You are a professional resume editor.

            Your task is to rewrite the candidate's "About" section (also known as Summary or Profile) using only the following information.

            --- CANDIDATE NAME ---
            {candidate_name or "(unknown — do NOT write a placeholder)"}

            --- EDUCATION ---
            {education}

            --- WORK EXPERIENCE ---
            {work_experience}

            --- TOOLS ---
            {tools}

            {ctx["target_role_block"]}

            --- LINKEDIN SCRAP ---
            {ctx["linkedin"]}

            --- CV PDF SCRAP ---
            {ctx["cv"]}

            --- CURRENT ABOUT (this is what you are editing) ---
            {about or "(empty — write it from scratch)"}

            --- CONVERSATION SO FAR (oldest first) ---
            {history_block}
{SECTION_CHAT_RULES}
            --- RECRUITER'S LATEST INSTRUCTION (act on this now) ---
            {user_prompt}

            Return STRICT JSON, one object:
            {{"about": "the full rewritten About paragraph", "summary": "what you changed"}}
            - "summary" is plain English, max 3 short lines, concrete about what moved or was
              added ("Led with the FP&A work", "Added the MBA"). Never vague.

            Instructions:
            - EDIT the CURRENT ABOUT above rather than starting over. Keep the sentences that
              already work and change what the recruiter asked about. Rewriting the whole
              paragraph every time makes their earlier fixes disappear.
            - NEVER write "The candidate", "This candidate", "The professional" or a bare
              "They" as the subject. They are empty filler that makes the CV read like a
              form letter. Lead with the profession ("Digital Marketing Specialist with 5+
              years...") or, if the recruiter asked for the name, with the real name from
              CANDIDATE NAME above. If that name is unknown, lead with the profession —
              never invent a name and never substitute the word "candidate" for one.
            - Write a **concise and professional summary (5–7 lines)** in the **third person**.
            - Deduce the candidate’s gender based on the name and context. If unclear, use **gender-neutral language without inventing names or making assumptions**.
            - If the user comment asks to focus on a particular skill, role, industry, or experience, **do not just repeat the comment**. Instead:
                - **Identify a relevant experience or education entry** that supports that focus.
                - **Reorganize and highlight that experience** naturally within the summary.
                - Do not start the summary with the explicit comment the user wrote.
            - Emphasize skills, tools, industries, strengths, and years of experience according to the user comment.
            - Do **not** invent any information. Use only what is available — except facts
              the recruiter states in their instruction, which they vouch for.
            - No markdown inside the About text itself.
            - Translate everything into English.
            """


            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=900
            )

            raw_about, change_summary = _parse_section_edit_payload(
                chat.choices[0].message.content.strip(), "about"
            )
            new_about = _strip_html_text(str(raw_about or "")).strip()
            if not new_about:
                raise ValueError("The model returned an empty About section.")

            cursor.execute("UPDATE resume SET about = %s WHERE candidate_id = %s", (new_about, candidate_id))
            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"about": new_about, "summary": change_summary})

        except Exception as e:
            logging.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500




    @app.route('/ai/generate_jd', methods=['POST', 'OPTIONS'])
    def generate_job_description():
        logging.info("🔁 Entrando a /ai/generate_jd")

        if request.method == 'OPTIONS':
            logging.info("🔁 OPTIONS request recibida para /ai/generate_jd")
            response = app.response_class(status=204)
            response.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
            response.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,PATCH,OPTIONS'
            return response

        logging.info("📡 POST request recibida en /ai/generate_jd")

        try:
            data = request.get_json()
            if not data:
                logging.warning("❗ No se recibió JSON o está vacío")
                raise ValueError("No JSON payload received")

            intro_link = data.get('intro_link', '')
            deep_dive_link = data.get('deep_dive_link', '')
            intro = data.get('intro', '')
            deep_dive = data.get('deepDive', '')
            notes = data.get('notes', '')

            if intro_link:
                logging.info("generate_jd: fetching Intro Call transcript from Grain link")
                intro = _fetch_grain_transcript_from_link(intro_link)
            if deep_dive_link:
                logging.info("generate_jd: fetching Deep Dive transcript from Grain link")
                deep_dive = _fetch_grain_transcript_from_link(deep_dive_link)

            intro = (intro or '')[:12000]
            deep_dive = (deep_dive or '')[:12000]
            notes = (notes or '')[:4000]

            if not intro.strip() and not deep_dive.strip() and not notes.strip():
                raise ValueError("No usable source material was provided. Add notes or a valid Grain link with transcript.")

            logging.info("📥 Datos recibidos:")
            logging.info(f"   - Intro link: {intro_link[:100] + '...' if intro_link else 'VACÍO'}")
            logging.info(f"   - DeepDive link: {deep_dive_link[:100] + '...' if deep_dive_link else 'VACÍO'}")
            logging.info(f"   - Intro: {intro[:100] + '...' if intro else 'VACÍO'}")
            logging.info(f"   - DeepDive: {deep_dive[:100] + '...' if deep_dive else 'VACÍO'}")
            logging.info(f"   - Notes: {notes[:100] + '...' if notes else 'VACÍO'}")

            prompt = f"""
            You are a job posting assistant. Based on the following input, generate a complete and professional **Job Description** suitable for LinkedIn.

            Your response must include the following structured sections:

            - Job Title (if applicable)
            - Role Summary (1 short paragraph)
            - Key Responsibilities (as a bulleted list)
            - Requirements (as a bulleted list)
            - Nice to Haves (as a bulleted list)
            - Additional Information (optional – if relevant)

            Use:
            - Clear, inclusive, and engaging language.
            - titles (no hashtags, no **bold**).
            - Bullet points (`-`) for lists.
            - A plain text markdown format (no HTML, no hashtags, no headings with `#`).

            SOURCE MATERIAL:
            ---
            **INTRO CALL TRANSCRIPT:**
            {intro}

            **DEEP DIVE NOTES:**
            {deep_dive}

            **EMAILS AND COMMENTS:**
            {notes}
            ---
            Please output only the job description, fully formatted and ready to copy into LinkedIn.you cannot add info
            that is not explicity said in the source material
            - translate everything to english
            """

            logging.info("🧠 Prompt construido correctamente, conectando con OpenAI...")

            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an expert recruiter and job description writer."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=1200
            )

            logging.info("✅ OpenAI respondió sin errores")
            content = chat.choices[0].message.content
            logging.info(f"📝 Respuesta de OpenAI (primeros 200 caracteres): {content[:200] + '...' if content else 'VACÍO'}")

            response = jsonify({"job_description": content})
            response.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            return response, 200

        except Exception as e:
            logging.error("❌ ERROR al generar la job description:")
            logging.error(traceback.format_exc())
            response = jsonify({"error": str(e)})
            response.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            return response, 500
    
    def resumir_fuente(nombre, contenido):
        prompt = f"""
        Resume solo la información profesional más útil para armar un CV a partir de este bloque de texto JSON o plano.
        Elimina cosas irrelevantes o duplicadas.
        
        Fuente: {nombre.upper()}
        ---
        {contenido[:8000]}  # recortamos para evitar token overflow
        ---
        Devuelve solo texto limpio y resumido, en inglés.
        """
        print(f"✂️ Resumiendo fuente: {nombre}")
        respuesta = call_openai_with_retry(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert resume cleaner."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=700
        )
        return respuesta.choices[0].message.content.strip()
    
    @app.route('/generate_resume_fields', methods=['POST'])
    def generate_resume_fields():
        try:
            data = request.json
            candidate_id = data.get('candidate_id')
            try:
                opportunity_id = int(str(data.get('opportunity_id') or "").strip() or 0) or None
            except (TypeError, ValueError):
                opportunity_id = None
            # Si el front no mandó el texto del CV (típico: subieron el PDF y
            # generaron sin recargar la página), lo extraemos acá. Sin esto el
            # CV se arma sólo con la transcripción y sale flaco.
            raw_cv_source = str(data.get('cv_pdf_scrapper', '') or '')
            if not raw_cv_source.strip():
                raw_cv_source = _ensure_cv_pdf_text(candidate_id)

            linkedin_scrapper = _summarize_long_resume_source(
                "LINKEDIN SCRAPER",
                data.get('linkedin_scrapper', ''),
                RESUME_LINKEDIN_SOURCE_LIMIT,
            )
            cv_pdf_scrapper = _summarize_long_resume_source(
                "CV PDF SCRAPER",
                raw_cv_source,
                RESUME_CV_SOURCE_LIMIT,
            )
            intro_call_link = data.get('intro_call_link', '')
            deep_dive_link = data.get('deep_dive_link', '')
            first_interview_link = data.get('first_interview_link', '')
            intro_call_transcript = data.get('intro_call_transcript', '')
            deep_dive_transcript = data.get('deep_dive_transcript', '')
            first_interview_transcript = data.get('first_interview_transcript', '')
            notes = str(data.get('notes', '') or '')[:RESUME_NOTES_LIMIT]

            # Grain degrada suave: un link vencido, un token faltante o una
            # grabación sin transcript no puede tumbar toda la generación del CV.
            grain_warnings = []

            def _try_grain(label, link, fallback):
                if not link:
                    return fallback
                logging.info("generate_resume_fields: fetching %s transcript from Grain link", label)
                try:
                    return _fetch_grain_transcript_from_link(link)
                except Exception as grain_error:
                    logging.warning(
                        "generate_resume_fields: Grain fetch failed for %s: %s", label, grain_error
                    )
                    grain_warnings.append(f"{label}: {grain_error}")
                    return fallback

            intro_call_transcript = _try_grain("Intro Call", intro_call_link, intro_call_transcript)
            deep_dive_transcript = _try_grain("Deep Dive", deep_dive_link, deep_dive_transcript)
            first_interview_transcript = _try_grain(
                "First Interview", first_interview_link, first_interview_transcript
            )

            intro_call_transcript = intro_call_transcript[:12000]
            deep_dive_transcript = deep_dive_transcript[:12000]
            first_interview_transcript = first_interview_transcript[:12000]

            logging.info(
                "generate_resume_fields sources: linkedin=%s cv=%s intro_link=%s intro_chars=%s deep_link=%s deep_chars=%s first_link=%s first_chars=%s notes=%s",
                bool(linkedin_scrapper.strip()),
                bool(cv_pdf_scrapper.strip()),
                bool((intro_call_link or "").strip()),
                len(intro_call_transcript or ""),
                bool((deep_dive_link or "").strip()),
                len(deep_dive_transcript or ""),
                bool((first_interview_link or "").strip()),
                len(first_interview_transcript or ""),
                len(notes or ""),
            )
            logging.info(
                "generate_resume_fields source lengths after preparation: linkedin_chars=%s cv_chars=%s",
                len(linkedin_scrapper or ""),
                len(cv_pdf_scrapper or ""),
            )

            candidate_ctx, target_role = _load_resume_generation_context(
                candidate_id, opportunity_id
            )
            target_role_block = _build_resume_target_role_block(target_role)
            logging.info(
                "generate_resume_fields tailoring: opportunity_id=%s position=%s client=%s jd_chars=%s",
                opportunity_id,
                (target_role or {}).get("position"),
                (target_role or {}).get("client_name"),
                len((target_role or {}).get("jd") or ""),
            )

            prompt = _build_resume_generation_prompt(
                target_role_block=target_role_block,
                candidate_name=candidate_ctx.get("name", ""),
                candidate_country=candidate_ctx.get("country", ""),
                linkedin_scrapper=linkedin_scrapper,
                cv_pdf_scrapper=cv_pdf_scrapper,
                intro_call_transcript=intro_call_transcript,
                deep_dive_transcript=deep_dive_transcript,
                first_interview_transcript=first_interview_transcript,
                notes=notes,
                today=datetime.date.today().isoformat(),
            )

            completion = call_openai_with_retry(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a senior recruiter writing client-facing CVs. You never "
                            "invent facts, and you always reply with a single valid JSON object."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                # Bullets ahora son más largos (BULLET DEPTH en el prompt): subimos el techo
                # porque en JSON mode una respuesta truncada es irrecuperable.
                max_tokens=16000,
                response_format={"type": "json_object"},
            )

            choice = completion.choices[0] if completion.choices else None
            if not choice or not getattr(choice, "message", None):
                raise Exception("❌ OpenAI response missing 'choices[0].message'")
            if getattr(choice, "finish_reason", "") == "length":
                # En JSON mode una respuesta truncada es irrecuperable; sin este
                # guard sale como un "Expecting ',' delimiter" incomprensible.
                raise Exception(
                    "The model hit the output limit before finishing the CV. "
                    "Trim the source material (very long LinkedIn/CV text) and try again."
                )

            content = choice.message.content
            json_data = _parse_model_json(content)

            today = datetime.date.today()
            education_country_source = "\n".join([
                linkedin_scrapper or "",
                cv_pdf_scrapper or "",
                intro_call_transcript or "",
                deep_dive_transcript or "",
                first_interview_transcript or "",
                notes or "",
            ])

            work_entries = [
                e for e in json_data.get("work_experience", []) if isinstance(e, dict)
            ]
            for entry in work_entries:
                _clean_generated_work_dates(entry, today)
                entry["description"] = _format_description_to_html(
                    entry.get("description", ""), bullets_only=True
                )
            # Con dos fuentes (CV + LinkedIn) el modelo concatena por fuente y el
            # orden sale mezclado; acá lo forzamos.
            work_entries = _sort_work_entries_reverse_chronological(work_entries)

            edu_entries = [e for e in json_data.get("education", []) if isinstance(e, dict)]
            for entry in edu_entries:
                _clean_generated_education_dates(entry)
                # _infer_education_country lee entry["description"], así que corre
                # ANTES de convertirla a HTML.
                entry["country"] = _infer_education_country(entry, education_country_source)
                entry["description"] = _format_description_to_html(entry.get("description", ""))

            # About se guarda como texto plano: resume.js lo lee con
            # stripHtmlToText() SIN separadores, así que "<p>a</p><p>b</p>"
            # volvería como "ab".
            about_raw = json_data.get("about")
            if isinstance(about_raw, list):
                about_raw = " ".join(str(x) for x in about_raw)
            about_text = _scrub_about_filler(
                _strip_html_text(str(about_raw or ""))
            )[:RESUME_ABOUT_LIMIT].strip()

            tools_list = _normalize_generated_tools(json_data.get("tools"))
            languages_list = _normalize_generated_languages(json_data.get("languages"))

            education = json.dumps(edu_entries)
            work_experience = json.dumps(work_entries)
            tools = json.dumps(tools_list)
            languages = json.dumps(languages_list)

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT 1 FROM resume WHERE candidate_id = %s", (candidate_id,))
            exists = cursor.fetchone() is not None

            # Sólo escribimos las columnas que el modelo realmente llenó: un
            # about vacío no debe pisar el que escribió la recruiter a mano.
            columns = {
                "education": education,
                "work_experience": work_experience,
                "tools": tools,
            }
            if about_text:
                columns["about"] = about_text
            if languages_list:
                columns["languages"] = languages

            if exists:
                sets = ", ".join(f"{c}=%s" for c in columns)
                cursor.execute(
                    f"UPDATE resume SET {sets} WHERE candidate_id=%s",
                    (*columns.values(), candidate_id),
                )
            else:
                cols = ", ".join(["candidate_id", *columns])
                placeholders = ", ".join(["%s"] * (len(columns) + 1))
                cursor.execute(
                    f"INSERT INTO resume ({cols}) VALUES ({placeholders})",
                    (candidate_id, *columns.values()),
                )

            conn.commit()
            cursor.close()
            conn.close()

            # Las claves vacías se OMITEN a propósito: applyGenerated() en
            # resume.js gatea con hasOwnProperty, no por truthiness, así que
            # mandar about:"" o languages:"[]" borraría lo que ya había.
            payload = {
                "success": True,
                "education": education,
                "work_experience": work_experience,
                "tools": tools,
                "tailored_to_opportunity_id": opportunity_id,
            }
            if about_text:
                payload["about"] = about_text
            if languages_list:
                payload["languages"] = languages
            if grain_warnings:
                payload["warnings"] = grain_warnings
            return jsonify(payload)

        except Exception as e:
            logging.error("❌ Error en /generate_resume_fields:")
            logging.error(traceback.format_exc())
            return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

    @app.route('/ai/coresignal_to_linkedin_scrapper', methods=['POST'])
    def coresignal_to_linkedin_scrapper():
        """
        Genera y guarda en candidates.linkedin_scrapper un texto en inglés,
        bien estructurado (secciones), a partir de candidates.coresignal_scrapper,
        SOLO si coresignal_scrapper tiene contenido y linkedin_scrapper está vacío.
        """
        try:
            data = request.get_json(force=True)
            candidate_id = str(data.get('candidate_id')).strip()
            if not candidate_id:
                return jsonify({"error": "candidate_id is required"}), 400

            conn = get_connection()
            cur = conn.cursor()

            # Lee estado actual
            cur.execute("""
                SELECT COALESCE(coresignal_scrapper, ''), COALESCE(linkedin_scrapper, ''), COALESCE(name, '')
                FROM candidates
                WHERE candidate_id = %s
            """, (candidate_id,))
            row = cur.fetchone()
            if not row:
                cur.close(); conn.close()
                return jsonify({"error": "Candidate not found"}), 404

            coresignal_raw, linkedin_scrap_current, db_name = row
            coresignal_raw = (coresignal_raw or "").strip()
            linkedin_scrap_current = (linkedin_scrap_current or "").strip()

            # Reglas de activación
            if not coresignal_raw:
                cur.close(); conn.close()
                return jsonify({"skipped": True, "reason": "coresignal_scrapper vacío"}), 200
            if linkedin_scrap_current:
                cur.close(); conn.close()
                return jsonify({"skipped": True, "reason": "linkedin_scrapper ya tiene valor"}), 200

            out_text = _extract_linkedin_from_coresignal(coresignal_raw)
            if not out_text:
                cur.close(); conn.close()
                return jsonify({"skipped": True, "reason": "Failed to extract linkedin_scrapper"}), 200

            # Guarda en candidates.linkedin_scrapper
            cur.execute("""
                UPDATE candidates
                SET linkedin_scrapper = %s
                WHERE candidate_id = %s
            """, (out_text, candidate_id))
            conn.commit()
            cur.close(); conn.close()

            return jsonify({"linkedin_scrapper": out_text, "updated": True}), 200

        except Exception as e:
            logging.error("❌ /ai/coresignal_to_linkedin_scrapper failed\n" + traceback.format_exc())
            return jsonify({"error": str(e)}), 500
    @app.route('/ai/extract_cv_from_pdf', methods=['POST'])
    def extract_cv_from_pdf():
        """
        Extrae texto del último CV (PDF) y lo guarda en candidates.affinda_scrapper y candidates.cv_pdf_scrapper
        Solo corre si affinda_scrapper está vacío, salvo que se mande force=true.
        Body: { "candidate_id": "<id>", "pdf_url": "<https://.../cv.pdf>", "force": false }
        """
        try:
            data = request.get_json(force=True) or {}
            candidate_id = str(data.get('candidate_id', '')).strip()
            pdf_url = (data.get('pdf_url') or '').strip()
            # Sin force, una extracción mala queda congelada para siempre y sólo
            # se arregla editando la DB a mano.
            force_reextract = str(data.get('force', '')).strip().lower() in ("1", "true", "yes", "on")

            if not candidate_id:
                return jsonify({"error": "candidate_id is required"}), 400

            conn = get_connection()
            cur = conn.cursor()

            # 1) Verificar estado actual
            cur.execute("""
                SELECT COALESCE(affinda_scrapper, ''), COALESCE(cv_pdf_scrapper, '')
                FROM candidates WHERE candidate_id = %s
            """, (candidate_id,))
            row = cur.fetchone()
            if not row:
                cur.close(); conn.close()
                return jsonify({"error": "Candidate not found"}), 404

            affinda_now, cv_pdf_now = row
            if (cv_pdf_now or "").strip() and not force_reextract:
                cur.close(); conn.close()
                return jsonify({"skipped": True, "reason": "cv_pdf_scrapper already has content"}), 200

            if not pdf_url:
                cur.close(); conn.close()
                return jsonify({"skipped": True, "reason": "pdf_url missing"}), 200

            # 2) Descargar PDF
            r = requests.get(pdf_url, timeout=45)
            if not r.ok or not r.content:
                cur.close(); conn.close()
                return jsonify({"error": f"Failed to download PDF ({r.status_code})"}), 502

            # 3) Enviar a OpenAI para extraer texto
            extracted = _extract_pdf_text_with_openai(r.content)

            if not extracted:
                cur.close(); conn.close()
                return jsonify({"error": "Empty extraction from OpenAI"}), 500

            # 4) Guardar en ambas columnas
            if (affinda_now or "").strip():
                cur.execute("""
                    UPDATE candidates
                    SET cv_pdf_scrapper = %s
                    WHERE candidate_id = %s
                """, (extracted, candidate_id))
            else:
                cur.execute("""
                    UPDATE candidates
                    SET affinda_scrapper = %s, cv_pdf_scrapper = %s
                    WHERE candidate_id = %s
                """, (extracted, extracted, candidate_id))
            conn.commit()
            cur.close(); conn.close()

            # Devolvemos el texto por si lo quieres pintar en UI
            return jsonify({"updated": True, "extracted_text": extracted}), 200

        except Exception as e:
            logging.error("❌ /ai/extract_cv_from_pdf failed\n" + traceback.format_exc())
            return jsonify({"error": str(e)}), 500


def call_openai_with_retry(model, messages, temperature=0.7, max_tokens=1200, retries=3, response_format=None,
                           tools=None, tool_choice=None):
        for attempt in range(retries):
            try:
                kwargs = dict(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if response_format is not None:
                    kwargs["response_format"] = response_format
                # Tool calling. Only sent when asked for, so the ~15 existing
                # callers keep the exact request body they had before.
                if tools is not None:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = tool_choice or "auto"
                response = openai.chat.completions.create(**kwargs)
                return response
            except openai.RateLimitError as e:
                # A 429 means two very different things. "rate_limit_exceeded" is
                # temporary and worth waiting out; "insufficient_quota" means the
                # billing limit is spent and no amount of waiting will fix it —
                # retrying just makes the user stare at a spinner for 30s before
                # getting a misleading "rate limit" message.
                body = getattr(e, "body", None)
                code = getattr(e, "code", None) or (
                    body.get("code") if isinstance(body, dict) else None)
                if code == "insufficient_quota":
                    logging.error("❌ OpenAI budget exhausted — raise the limit or add credits.")
                    raise RuntimeError(
                        "OpenAI budget exhausted. Raise the monthly limit or add credits at "
                        "platform.openai.com/settings/organization/limits, then try again."
                    ) from e
                logging.warning(f"⏳ Rate limit reached, retrying in 10s... (Attempt {attempt + 1})")
                if hasattr(e, 'response') and e.response is not None:
                    logging.warning("🔎 Response headers: %s", e.response.headers)
                time.sleep(10)
            except Exception as e:
                logging.error("❌ Error en llamada a OpenAI: " + str(e))
                raise e
        raise Exception("Exceeded maximum retries due to rate limit")

    
