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
            for page in reader.pages:
                raw.append(page.extract_text() or "")
            local_text = re.sub(r"\s+", " ", "\n".join(raw)).strip()
    except Exception as e:
        logging.error(f"❌ Local PDF read failed: {e}")

    if len(local_text) >= 300:
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
                max_output_tokens=4000,
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

    return extracted.strip()

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
    position, career_country, years_experience, hr_jd, career_desc, career_reqs = row
    raw_jd = hr_jd or career_desc or career_reqs or ""
    jd_plain = _strip_html_text(raw_jd)
    context = {
        "position": position or "",
        "career_country": career_country or "",
        "years_experience": years_experience or "",
    }
    return jd_plain, context

def _score_applicant_with_openai(
    extracted_pdf: str,
    applicant_location: str,
    job_description: str,
    filters: Optional[Dict[str, Any]] = None,
    opportunity_context: Optional[Dict[str, Any]] = None,
):
    return score_candidate_against_job(
        extracted_pdf,
        applicant_location,
        job_description,
        filters=filters,
        opportunity_context=opportunity_context,
    )

def _recalculate_applicant_scores(opportunity_id: int, filters: Optional[Dict[str, Any]] = None):
    filters = filters or {}
    conn = get_connection()
    cursor = conn.cursor()
    try:
        jd_plain, opp_context = _build_opportunity_context(cursor, opportunity_id)
        cursor.execute(
            """
            SELECT applicant_id, location, extracted_pdf
            FROM applicants
            WHERE opportunity_id = %s
            """,
            (opportunity_id,),
        )
        rows = cursor.fetchall()
        updated = 0
        for applicant_id, location, extracted_pdf in rows:
            if not extracted_pdf:
                continue
            score, reasons = _score_applicant_with_openai(
                extracted_pdf,
                location or "",
                jd_plain,
                filters=filters,
                opportunity_context=opp_context,
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

            conn = get_connection()
            cursor = conn.cursor()

            # Obtener tools actuales
            cursor.execute("SELECT tools FROM resume WHERE candidate_id = %s", (candidate_id,))
            tools = cursor.fetchone()[0] or "[]"

            # Obtener scraps
            cursor.execute("SELECT linkedin_scrapper, cv_pdf_scrapper FROM candidates WHERE candidate_id = %s", (candidate_id,))
            linkedin_scrapper, cv_pdf_scrapper = cursor.fetchone()

            prompt = f"""
    You are a resume tools editor.

    --- CURRENT TOOLS ---
    {tools}

    --- LINKEDIN SCRAP ---
    {linkedin_scrapper[:2000]}

    --- PDF SCRAP ---
    {cv_pdf_scrapper[:2000]}

    --- USER COMMENTS ---
    {user_prompt}

    Improve the tools section using this info. Output must be a JSON array of this format:
    [{{"tool":"Excel","level":"Advanced"}},{{"tool":"QuickBooks","level":"Intermediate"}},{{"tool":"SAP","level":"Intermediate"}}]

    - Infer the level (Basic, Intermediate, Advanced) based on context.
    - Do NOT invent tools.
    - If no level is specified, infer from experience.
    Return only the JSON array.
    - translate everything to english
    """

            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=800
            )

            content = chat.choices[0].message.content.strip()
            tools_json = json.loads(re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', content))

            cursor.execute("UPDATE resume SET tools = %s WHERE candidate_id = %s", (json.dumps(tools_json), candidate_id))
            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"tools": json.dumps(tools_json)})
        except Exception as e:
            logging.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route('/ai/improve_work_experience', methods=['POST'])
    def improve_work_experience_section():
        try:
            data = request.json
            candidate_id = data['candidate_id']
            user_prompt = data.get('user_prompt', '').strip()

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT work_experience FROM resume WHERE candidate_id = %s", (candidate_id,))
            work_experience = cursor.fetchone()[0] or "[]"

            cursor.execute("SELECT linkedin_scrapper, cv_pdf_scrapper FROM candidates WHERE candidate_id = %s", (candidate_id,))
            linkedin_scrapper, cv_pdf_scrapper = cursor.fetchone()

            prompt = f"""
    You are a resume work experience editor.

    --- CURRENT WORK EXPERIENCE ---
    {work_experience}

    --- LINKEDIN SCRAP ---
    {linkedin_scrapper[:2000]}

    --- PDF SCRAP ---
    {cv_pdf_scrapper[:2000]}

    --- USER COMMENTS ---
    {user_prompt}

    Improve the work experience section using this info. Output must be a JSON array with objects of this format:
    [{{"title":"...", "company":"...", "start_date":"YYYY-MM-DD", "end_date":"YYYY-MM-DD", "current":true/false, "description":"..."}}]

    - If month or day is missing, complete with 01
    - If end_date is missing or says "present", set current = true
    - Else set current = false
    Return only the JSON array.
    - translate everything to english
    """

            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=7000
            )

            content = chat.choices[0].message.content.strip()
            work_json = json.loads(re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', content))

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

            cursor.execute("UPDATE resume SET work_experience = %s WHERE candidate_id = %s", (json.dumps(work_json), candidate_id))
            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"work_experience": json.dumps(work_json)})

        except Exception as e:
            logging.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500




    @app.route('/ai/improve_education', methods=['POST'])
    def improve_education_section():
        try:
            data = request.json
            candidate_id = data['candidate_id']
            user_prompt = data.get('user_prompt', '').strip()

            conn = get_connection()
            cursor = conn.cursor()

            # Obtener education actual
            cursor.execute("SELECT education FROM resume WHERE candidate_id = %s", (candidate_id,))
            education = cursor.fetchone()[0] or "[]"

            # Obtener scraps
            cursor.execute("SELECT linkedin_scrapper, cv_pdf_scrapper FROM candidates WHERE candidate_id = %s", (candidate_id,))
            linkedin_scrapper, cv_pdf_scrapper = cursor.fetchone()

            prompt = f"""
    You are a resume education editor.

    --- CURRENT EDUCATION SECTION ---
    {education}

    --- LINKEDIN SCRAP ---
    {linkedin_scrapper[:2000]}

    --- PDF SCRAP ---
    {cv_pdf_scrapper[:2000]}

    --- USER COMMENTS ---
    {user_prompt}

    Improve the education section using this info. Output must be a JSON array with objects of this format:
    [{{"institution":"...", "start_date":"YYYY-MM-DD", "end_date":"YYYY-MM-DD", "current":true/false, "description":"..."}}]

    - If month or day is missing, complete with 01
    - If end_date is missing or says "present", set current = true
    - Else set current = false
    Return only the JSON array.
    - translate everything to english
    """

            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=700
            )

            content = chat.choices[0].message.content.strip()
            education_json = json.loads(re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', content))

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

            cursor.execute("UPDATE resume SET education = %s WHERE candidate_id = %s", (json.dumps(education_json), candidate_id))
            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"education": json.dumps(education_json)})

        except Exception as e:
            logging.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500



    @app.route('/ai/improve_about', methods=['POST'])
    def improve_about_section():
        
        try:
            data = request.json
            candidate_id = data['candidate_id']
            user_prompt = data.get('user_prompt', '').strip()

            conn = get_connection()
            cursor = conn.cursor()

            # Extraer información de la base
            cursor.execute("SELECT about, education, work_experience, tools FROM resume WHERE candidate_id = %s", (candidate_id,))
            result = cursor.fetchone()
            about, education, work_experience, tools = result if result else ("", "[]", "[]", "[]")

            prompt = f"""
            You are a professional resume editor.

            Your task is to rewrite the candidate's "About" section (also known as Summary or Profile) using only the following information.

            --- CANDIDATE NAME ---
            {data.get("candidate_name", "")}

            --- EDUCATION ---
            {education}

            --- WORK EXPERIENCE ---
            {work_experience}

            --- TOOLS ---
            {tools}

            --- USER COMMENT ---
            {user_prompt}

            Instructions:
            - Write a **concise and professional summary (5–7 lines)** in the **third person**.
            - Deduce the candidate’s gender based on the name and context. If unclear, use **gender-neutral language without inventing names or making assumptions**.
            - If the user comment asks to focus on a particular skill, role, industry, or experience, **do not just repeat the comment**. Instead:
                - **Identify a relevant experience or education entry** that supports that focus.
                - **Reorganize and highlight that experience** naturally within the summary.
                - Do not start the summary with the explicit comment the user wrote.
            - Emphasize skills, tools, industries, strengths, and years of experience according to the user comment.
            - Do **not** invent any information. Use only what is available.
            - Return only the final text, no formatting, no explanation, no markdown.
            - Translate everything into English.
            """


            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=300
            )

            new_about = chat.choices[0].message.content.strip()

            cursor.execute("UPDATE resume SET about = %s WHERE candidate_id = %s", (new_about, candidate_id))
            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"about": new_about})

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
            linkedin_scrapper = data.get('linkedin_scrapper', '')[:8000]
            cv_pdf_scrapper = data.get('cv_pdf_scrapper', '')[:8000]
            intro_call_link = data.get('intro_call_link', '')
            deep_dive_link = data.get('deep_dive_link', '')
            first_interview_link = data.get('first_interview_link', '')
            intro_call_transcript = data.get('intro_call_transcript', '')
            deep_dive_transcript = data.get('deep_dive_transcript', '')
            first_interview_transcript = data.get('first_interview_transcript', '')
            notes = data.get('notes', '')[:4000]

            if intro_call_link:
                logging.info("generate_resume_fields: fetching Intro Call transcript from Grain link")
                intro_call_transcript = _fetch_grain_transcript_from_link(intro_call_link)
            if deep_dive_link:
                logging.info("generate_resume_fields: fetching Deep Dive transcript from Grain link")
                deep_dive_transcript = _fetch_grain_transcript_from_link(deep_dive_link)
            if first_interview_link:
                logging.info("generate_resume_fields: fetching First Interview transcript from Grain link")
                first_interview_transcript = _fetch_grain_transcript_from_link(first_interview_link)

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

            prompt = f"""
            You are a resume generation assistant. Based only on the following data, generate a resume in valid JSON format. Do NOT invent or assume any information.

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

            RECRUITER NOTES / COMMENTS:
            {notes}

            You must always return all 3 fields, even if any of them are empty. Return a complete valid JSON.

            - education: [
                {{
                    "institution": "...", \\translate everything to english
                    "title": "...", \\translate everything to english
                    "start_date": "YYYY-MM-DD",
                    "end_date": "YYYY-MM-DD",
                    "current": true/false,
                    "description": "- Bullet 1\\n- Bullet 2\\n- Bullet 3\\n- Bullet 4\\n..."  // Use all available details. Each description must include at least 5-8 bullet points, written in professional tone. Bullets must cover responsibilities, methods, tools, skills applied, outcomes (if mentioned), and relevant context. Do not add or assume anything that is not clearly present in the input."
                }}
            ]
            - work_experience: [
                {{
                    "title": "...", \\translate everything to english
                    "company": "...", \\translate everything to english
                    "start_date": "YYYY-MM-DD",
                    "end_date": "YYYY-MM-DD",
                    "current": true/false,
                    "description": "In this role I did (short summary). \\n- Bullet 1\\n- Bullet 2\\n- Bullet 3\\n..."  // Start with a simple summary sentence finished with dot, then detailed bullet points using all available data. No extra info.
                }}
            ]
            - tools: [{{"tool":"Excel", "level":"Advanced"}}, ...]

            Rules:
            - Do NOT invent or assume any data. Only use what is explicitly or implicitly present.
            - Use the available sources when present: LinkedIn, CV PDF, Intro Call transcript, Deep Dive transcript, and First Interview transcript.
            - The call transcripts may contain extra context about scope, achievements, tools, responsibilities, communication, leadership, domain experience, and interview examples. Use that information when it clearly refers to the candidate's real background.
            - Use all possible details found in the source to make the descriptions **long, rich and specific**.
            - The descriptions in both education and work experience must be **very detailed bullet points** using `- ` for each bullet.
            - If there is too little info, still write one or two bullets summarizing the available data — but do not fabricate anything.
            - If sources overlap, merge them carefully without duplicating the same point.
            - Prefer the most specific version of a fact when multiple sources mention it.
            - Ignore speculative statements, future plans, or recruiter opinions unless they describe factual past experience already stated in the source material.
            - Expand acronyms and explain concepts if mentioned.
            - translate everything to english
            Return only the full JSON object. Do not return only partial content or text outside of the JSON.
            DO NOT merge bullet points into paragraphs. Keep each bullet on a separate line starting with "- ".

            """

            completion = call_openai_with_retry(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a resume generation assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=7000
            )

            if not completion.choices or not hasattr(completion.choices[0], "message"):
                raise Exception("❌ OpenAI response missing 'choices[0].message'")

            content = completion.choices[0].message.content
            print("📥 Resume raw response content:", content)


            try:
                print("🔍 Raw OpenAI response content:", repr(content[:500]))
                json_data = json.loads(content)
                def format_description_to_html(description):
                    if not description:
                        return ""

                    # Separar por líneas
                    lines = description.strip().split("\n")
                    first_sentence = ""
                    bullet_lines = []

                    for line in lines:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        if stripped.startswith("-") or stripped.startswith("•") or stripped.startswith("–"):
                            bullet_lines.append(stripped.lstrip("-•–").strip())
                        elif not first_sentence:
                            first_sentence = stripped

                    html = ""
                    if first_sentence:
                        html += f"<p>{first_sentence}</p>"

                    if bullet_lines:
                        html += "<ul>" + "".join(f"<li>{b}</li>" for b in bullet_lines) + "</ul>"

                    return html

                for entry in json_data.get("education", []):
                    entry["description"] = format_description_to_html(entry.get("description", ""))

                for entry in json_data.get("work_experience", []):
                    entry["description"] = format_description_to_html(entry.get("description", ""))

                today = datetime.date.today()

                # Preprocesar fechas en work_experience
                for entry in json_data.get("work_experience", []):
                    # Formatear fechas incompletas
                    start = entry.get("start_date", "")
                    end = entry.get("end_date", "")

                    if start and len(start) == 4:
                        entry["start_date"] = f"{start}-01-01"
                    elif start and len(start) == 7:
                        entry["start_date"] = f"{start}-01"

                    if end and len(end) == 4:
                        entry["end_date"] = f"{end}-01-01"
                    elif end and len(end) == 7:
                        entry["end_date"] = f"{end}-01"

                    # Evaluar si es actual
                    if not entry.get("end_date"):
                        entry["current"] = True
                    else:
                        try:
                            end_date_obj = datetime.datetime.strptime(entry["end_date"], "%Y-%m-%d").date()
                            entry["current"] = end_date_obj > today
                        except:
                            entry["current"] = False

                # Preprocesar fechas en education
                for entry in json_data.get("education", []):
                    start = entry.get("start_date", "")
                    end = entry.get("end_date", "")

                    if start and len(start) == 4:
                        entry["start_date"] = f"{start}-01-01"
                    elif start and len(start) == 7:
                        entry["start_date"] = f"{start}-01"

                    if end and len(end) == 4:
                        entry["end_date"] = f"{end}-01-01"
                    elif end and len(end) == 7:
                        entry["end_date"] = f"{end}-01"

                    if not entry.get("end_date"):
                        entry["current"] = True
                    else:
                        try:
                            end_date_obj = datetime.datetime.strptime(entry["end_date"], "%Y-%m-%d").date()
                            entry["current"] = end_date_obj > today
                        except:
                            entry["current"] = False

            except Exception as e1:
                try:
                    cleaned = re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', content.strip())
                    json_data = json.loads(cleaned)
                    # 🔄 Convertir bullets a HTML incluso en el segundo intento
                    def format_description_to_html(description):
                        if not description:
                            return ""
                        lines = description.strip().split("\n")
                        first_sentence = ""
                        bullet_lines = []
                        for line in lines:
                            stripped = line.strip()
                            if not stripped:
                                continue
                            if stripped.startswith("-") or stripped.startswith("•") or stripped.startswith("–"):
                                bullet_lines.append(stripped.lstrip("-•–").strip())
                            elif not first_sentence:
                                first_sentence = stripped
                        html = ""
                        if first_sentence:
                            html += f"<p>{first_sentence}</p>"
                        if bullet_lines:
                            html += "<ul>" + "".join(f"<li>{b}</li>" for b in bullet_lines) + "</ul>"
                        return html

                    for entry in json_data.get("education", []):
                        entry["description"] = format_description_to_html(entry.get("description", ""))

                    for entry in json_data.get("work_experience", []):
                        entry["description"] = format_description_to_html(entry.get("description", ""))

                except Exception as e2:
                    raise Exception(f"❌ Error parsing JSON. First attempt: {str(e1)} | Second attempt: {str(e2)} | Content: {content[:300]}")

            education = json.dumps(json_data.get('education', []))
            work_experience = json.dumps(json_data.get('work_experience', []))
            tools = json.dumps(json_data.get('tools', []))

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT 1 FROM resume WHERE candidate_id = %s", (candidate_id,))
            result = cursor.fetchone()
            exists = result is not None


            if exists:
                cursor.execute("""
                    UPDATE resume SET education=%s, work_experience=%s, tools=%s
                    WHERE candidate_id=%s
                """, (education, work_experience, tools, candidate_id))
            else:
                cursor.execute("""
                    INSERT INTO resume (candidate_id, education, work_experience, tools)
                    VALUES (%s, %s, %s, %s)
                """, (candidate_id, education, work_experience, tools))

            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"success": True, "education": education, "work_experience": work_experience, "tools": tools})

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
        Solo corre si affinda_scrapper está vacío.
        Body: { "candidate_id": "<id>", "pdf_url": "<https://.../cv.pdf>" }
        """
        try:
            data = request.get_json(force=True) or {}
            candidate_id = str(data.get('candidate_id', '')).strip()
            pdf_url = (data.get('pdf_url') or '').strip()

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
            if (affinda_now or "").strip():
                cur.close(); conn.close()
                return jsonify({"skipped": True, "reason": "affinda_scrapper already has content"}), 200

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


def call_openai_with_retry(model, messages, temperature=0.7, max_tokens=1200, retries=3):
        for attempt in range(retries):
            try:
                response = openai.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                return response
            except openai.RateLimitError as e:
                logging.warning(f"⏳ Rate limit reached, retrying in 10s... (Attempt {attempt + 1})")
                if hasattr(e, 'response') and e.response is not None:
                    logging.warning("🔎 Response headers: %s", e.response.headers)
                time.sleep(10)
            except Exception as e:
                logging.error("❌ Error en llamada a OpenAI: " + str(e))
                raise e
        raise Exception("Exceeded maximum retries due to rate limit")

    
