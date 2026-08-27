# ai_candidate_search_routes.py
import os, json, logging, traceback, re
from flask import Blueprint, request, jsonify
from openai import OpenAI
from db import get_connection
import datetime as dt
import requests
from typing import Optional

# --- LATAM / Central America location gate ---
LATAM_COUNTRIES = [
    # North & Central America
    ("Mexico","MX"), 
    ("United States","US"),
    ("Canada","CA"),
    # South America
    ("Colombia","CO"), ("Ecuador","EC"), ("Peru","PE"), ("Bolivia","BO"),
    ("Chile","CL"), ("Argentina","AR"), ("Uruguay","UY"), ("Paraguay","PY"), ("Brazil","BR"),
    # Caribbean (latino)
    ("Dominican Republic","DO"), ("Puerto Rico","PR")
]

_LATAM_NAMES = [n for (n, _iso) in LATAM_COUNTRIES]
_LATAM_ISO2  = [iso for (_n, iso) in LATAM_COUNTRIES]

# Para OR en filter: "Mexico OR Colombia OR …"
LATAM_COUNTRY_OR = " OR ".join(f"({n})" for n in _LATAM_NAMES)
LATAM_ISO2_OR    = " OR ".join(f"({c})" for c in _LATAM_ISO2)

def _parse_date_soft(s: str) -> Optional[dt.date]:
    """
    Intenta parsear una fecha en varios formatos simples.
    Esperamos principalmente 'YYYY-MM-DD', pero soporta algunos degradados.
    """
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None

    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            d = dt.datetime.strptime(s, fmt).date()
            return d
        except Exception:
            continue
    return None


def compute_years_experience_from_workexp(raw) -> Optional[int]:
    """
    raw viene de resume.work_experience (texto JSON).
    Regla:
      - Tomar la start_date más antigua.
      - Tomar la end_date más reciente (o hoy si está current=true o end_date vacío).
      - Devolver diferencia en años (entero, redondeado hacia abajo).
    """
    if not raw:
        return None

    try:
        if isinstance(raw, str):
            work_list = json.loads(raw)
        else:
            # por si ya viene parseado como dict/list en algún contexto futuro
            work_list = raw
    except Exception:
        logging.exception("⚠️ compute_years_experience_from_workexp: JSON inválido")
        return None

    if not isinstance(work_list, list) or not work_list:
        return None

    earliest_start = None
    latest_end = None
    today = dt.date.today()

    for job in work_list:
        if not isinstance(job, dict):
            continue

        s_start = job.get("start_date") or ""
        s_end   = job.get("end_date") or ""
        current = bool(job.get("current"))

        start = _parse_date_soft(s_start)
        if not start:
            continue

        if current or not s_end.strip():
            end = today
        else:
            end = _parse_date_soft(s_end) or today

        # actualizar rangos
        if earliest_start is None or start < earliest_start:
            earliest_start = start
        if latest_end is None or end > latest_end:
            latest_end = end

    if not earliest_start or not latest_end or latest_end < earliest_start:
        return None

    delta_days = (latest_end - earliest_start).days
    years = int(delta_days // 365.25)  # aprox, redondeando hacia abajo
    if years < 0:
        return None

    # por seguridad, acotamos a un rango razonable (0–60)
    years = max(0, min(years, 60))
    return years


def _is_latam_location(text: str) -> bool:
    """True si el string sugiere un país LATAM (por nombre o ISO2)."""
    if not text:
        return False
    tl = text.lower().strip()
    return any(n.lower() in tl for n in _LATAM_NAMES) or any(iso.lower() == tl for iso in _LATAM_ISO2)

def _resolve_latam_country_name(text: str) -> Optional[str]:
    """Devuelve el nombre canónico del país LATAM si el texto coincide por nombre o ISO2."""
    if not text:
        return None
    tl = text.lower().strip()
    for name, iso in LATAM_COUNTRIES:
        if tl == name.lower() or tl == iso.lower():
            return name
    # matches parciales tipo "México", "mexico city", "cdmx" → intenta encontrar por substring de nombre
    for name, _iso in LATAM_COUNTRIES:
        if name.lower() in tl:
            return name
    return None

CORESIGNAL_API_BASE = "https://api.coresignal.com/cdapi/v2"
CORESIGNAL_API_KEY = os.getenv("CORESIGNAL_API_KEY")  # <-- ponla en variables de entorno

bp_candidate_search = Blueprint("candidate_search", __name__)
OPENAI_MODEL = os.getenv("OPENAI_QUERY_MODEL", "gpt-4o-mini")

def _ok_origin(resp):
    # Ajusta si tu front cambia de dominio
    resp.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
    resp.headers['Access-Control-Allow-Credentials'] = 'true'
    return resp

def _parse_list(s):
    if isinstance(s, list): return s
    if not s: return []
    return [x.strip() for x in str(s).split(",") if x.strip()]

def _cs_headers():
    if not CORESIGNAL_API_KEY:
        raise RuntimeError("Falta CORESIGNAL_API_KEY en variables de entorno")
    return {"apikey": CORESIGNAL_API_KEY, "Content-Type": "application/json"}

_CS_OUT_OF_CREDITS_MESSAGE = (
    "Se acabaron los créditos de Coresignal: la búsqueda en LinkedIn queda "
    "desactivada hasta que se recargue la cuenta."
)

def _cs_out_of_credits(status, body=""):
    """402 siempre; 401/403 sólo si el cuerpo habla de saldo (una key mal puesta
    o un rate limit no son lo mismo y no deben decir 'sin créditos')."""
    if status == 402:
        return True
    if status in (401, 403):
        t = (body or "").lower()
        return any(m in t for m in ("credit", "quota", "balance", "insufficient", "limit reached"))
    return False

def _log_cs_credits(response):
    """El saldo viene en cada respuesta. Logueándolo se puede medir el costo real
    por endpoint sin gastar nada extra."""
    left = response.headers.get("x-credits-remaining")
    if left is not None:
        logging.info("💳 Coresignal credits remaining: %s", left)
    return left

@bp_candidate_search.route('/ai/parse_candidate_query', methods=['POST','OPTIONS'])
def parse_candidate_query():
    if request.method == 'OPTIONS':
        resp = jsonify({}); resp.status_code=204
        return _ok_origin(resp)

    try:
        data = request.get_json(force=True) or {}
        raw = data.get("query")
        query = raw.strip() if isinstance(raw, str) else str(raw or "").strip()
        logging.info("🧠 [/ai/parse_candidate_query] query_in=%r", query)

        if not query:
            resp = jsonify({"title":"", "tools":[], "years_experience": None, "location": ""})
            return _ok_origin(resp), 200

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        prompt = f"""
Read the following natural language query describing a candidate.
Extract a STRICT JSON with:
- title: role/job title in English (short, lowercase words, no punctuation). If absent, return "".
  Fix obvious misspellings BEFORE translating: the query is typed fast by a recruiter, so
  "cotador"->accountant, "contdor"->accountant, "desarollador"->developer. A misspelled title
  is sent verbatim to the search provider and matches almost nobody, so never pass one through.
- tools: array of tool/technology names in English, lowercase (e.g., ["python","excel","react"]).
  Only explicit tools; do NOT invent; singularize if possible; fix misspellings and translate
  ("bases de datos"->"sql", "hoja de calculo"->"excel").
- years_experience: integer years if explicitly stated (e.g., "3 years"), else null.
- location: city/region/country if explicitly present (e.g., "Mexico", "Mexico City", "CDMX", "Guadalajara", "Latin America"). If absent, return "".

Rules:
- Only parse what's explicitly present in the query (do NOT infer).
- Output minified JSON. No markdown, no commentary.

QUERY:
---
{query}
---
"""
        r = client.responses.create(
            model=OPENAI_MODEL,
            input=prompt,
            max_output_tokens=300,
            temperature=0
        )
        content = getattr(r, "output_text", "") or ""
        logging.info("🧠 raw_model_output=%r", content)

        cleaned = re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', content).strip()
        logging.info("🧠 cleaned_json_candidate=%r", cleaned)

        try:
            obj = json.loads(cleaned)
        except Exception:
            logging.exception("⚠️ JSON parse error on model output")
            obj = {"title":"", "tools":[], "years_experience": None, "location": ""}

        # normalizar
        title = (obj.get("title") or "").strip()
        tools = [str(t).strip().lower() for t in (obj.get("tools") or []) if str(t).strip()]
        years = obj.get("years_experience", None)
        try:
            years = int(years) if years is not None else None
        except:
            years = None
        location = (obj.get("location") or "").strip()

        logging.info("🧠 normalized → title=%r tools=%r years=%r location=%r", title, tools, years, location)

        resp = jsonify({"title": title, "tools": tools, "years_experience": years, "location": location})
        return _ok_origin(resp), 200

    except Exception:
        logging.error("❌ /ai/parse_candidate_query\n"+traceback.format_exc())
        resp = jsonify({"title":"", "tools":[], "years_experience": None, "location": ""})
        return _ok_origin(resp), 200


@bp_candidate_search.route('/search/candidates', methods=['GET','OPTIONS'])
def search_candidates():
    if request.method == 'OPTIONS':
        resp = jsonify({}); resp.status_code=204
        return _ok_origin(resp)

    try:
        raw_tools = request.args.get('tools', '')
        tools = _parse_list(raw_tools)
        tools_lc = [t.lower().strip() for t in tools if t.strip()]

        logging.info("🔎 [/search/candidates] qs.tools_raw=%r → tools_lc=%r", raw_tools, tools_lc)

        # 🔹 title que viene del parser (posición buscada)
        raw_title = request.args.get('title', '') or ''
        title = raw_title.strip()
        logging.info("🔎 [/search/candidates] qs.title_raw=%r → title=%r", raw_title, title)

        # 🔹 location que viene del parser (país / ciudad / región)
        raw_location = request.args.get('location', '') or ''
        location = raw_location.strip()
        logging.info("🔎 [/search/candidates] qs.location_raw=%r", raw_location)

        country_filter = None
        if location:
            if _is_latam_location(location):
                cname = _resolve_latam_country_name(location)
                country_filter = cname or location
            else:
                country_filter = location

        logging.info("🔎 country_filter (normalizado)=%r", country_filter)

        # 🛑 Caso límite: sin tools y sin title → no tenemos cómo filtrar
        if not tools_lc and not title:
            logging.info("🔎 No tools AND no title provided → return empty items")
            resp = jsonify({"items": []})
            return _ok_origin(resp), 200

        conn = get_connection()
        cur = conn.cursor()

        items = []

        # ============================
        # 1️⃣ Rama con tools (como antes)
        # ============================
        if tools_lc:
            # Preparamos patrones para coincidencia parcial
            patterns = [f"%{t}%" for t in tools_lc]
            logging.info("🧾 ILIKE patterns=%r", patterns)

            # Base SQL (con tools + hits)
            sql = """
            SELECT
                c.candidate_id,
                c.name,
                c.country,
                c.comments,
                c.english_level,
                c.salary_range,
                COUNT(DISTINCT kw) AS hits,
                r.work_experience
            FROM candidates c
            JOIN resume r ON r.candidate_id = c.candidate_id

            CROSS JOIN LATERAL jsonb_array_elements(
                CASE
                    WHEN r.tools IS NULL OR trim(r.tools) = '' THEN '[]'::jsonb
                    WHEN r.tools ~ '^\\s*\\[.*\\]\\s*$' THEN r.tools::jsonb
                    ELSE '[]'::jsonb
                END
            ) AS t(elem)

            JOIN unnest(%s::text[]) AS kw
                ON lower(t.elem->>'tool') ILIKE kw

            WHERE
                (
                    c.english_level IS NULL
                    OR trim(c.english_level) = ''
                    OR lower(c.english_level) NOT IN ('regular', 'poor')
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM hire_opportunity h
                    WHERE
                        h.candidate_id = c.candidate_id
                        AND h.start_date IS NOT NULL
                        AND h.end_date IS NULL
                )
            """

            params = [patterns]

            if country_filter:
                sql += "\n            AND (c.country ILIKE %s)\n"
                params.append(f"%{country_filter}%")

            if title:
                sql += "\n            AND (r.work_experience ILIKE %s)\n"
                params.append(f"%{title}%")

            sql += """
            GROUP BY
                c.candidate_id,
                c.name,
                c.country,
                c.comments,
                c.english_level,
                c.salary_range,
                r.work_experience
            HAVING COUNT(DISTINCT kw) >= 1
            ORDER BY hits DESC, c.name NULLS LAST, c.candidate_id ASC
            LIMIT 200;
            """

            # (sanity checks se pueden dejar aquí si quieres)
            try:
                cur.execute("select current_database()")
                dbname = cur.fetchone()[0]
                logging.info("🗄️ current_database=%s", dbname)

                cur.execute("""
                    SELECT count(*)
                    FROM resume r
                    WHERE r.tools ~ '^\\s*\\[.*\\]\\s*$'
                """)
                logging.info("🧮 resume rows with tools that look like JSON array = %s", cur.fetchone()[0])
            except Exception:
                logging.exception("⚠️ sanity checks failed")

            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            logging.info("📦 rows_found(tools-branch)=%d", len(rows))

            for cid, name, country, comments, english_level, salary_range, hits, work_exp_raw in rows:
                years = compute_years_experience_from_workexp(work_exp_raw)
                items.append({
                    "candidate_id": cid,
                    "name": name,
                    "country": country,
                    "comments": comments,
                    "english_level": english_level,
                    "salary_range": salary_range,
                    "hits": int(hits),
                    "years_experience": years
                })

        # ============================
        # 2️⃣ Rama SOLO por posición (title) + country opcional
        # ============================
        else:
            logging.info("🔎 title-only search branch (sin tools)")

            sql = """
            SELECT
                c.candidate_id,
                c.name,
                c.country,
                c.comments,
                c.english_level,
                c.salary_range,
                r.work_experience
            FROM candidates c
            JOIN resume r ON r.candidate_id = c.candidate_id
            WHERE
                (
                    c.english_level IS NULL
                    OR trim(c.english_level) = ''
                    OR lower(c.english_level) NOT IN ('regular', 'poor')
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM hire_opportunity h
                    WHERE
                        h.candidate_id = c.candidate_id
                        AND h.start_date IS NOT NULL
                        AND h.end_date IS NULL
                )
            """
            params = []

            if country_filter:
                sql += "\n                AND (c.country ILIKE %s)"
                params.append(f"%{country_filter}%")

            if title:
                sql += "\n                AND (r.work_experience ILIKE %s)"
                params.append(f"%{title}%")

            sql += "\n            ORDER BY c.name NULLS LAST, c.candidate_id ASC\n            LIMIT 200;"

            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            logging.info("📦 rows_found(title-only)=%d", len(rows))

            for cid, name, country, comments, english_level, salary_range, work_exp_raw in rows:
                years = compute_years_experience_from_workexp(work_exp_raw)
                items.append({
                    "candidate_id": cid,
                    "name": name,
                    "country": country,
                    "comments": comments,
                    "english_level": english_level,
                    "salary_range": salary_range,
                    "hits": 0,  # sin tools → sin score de hits
                    "years_experience": years
                })

        cur.close()
        conn.close()

        logging.info("🪞 first_ids=%r", [it["candidate_id"] for it in items[:10]])

        resp = jsonify({"items": items})
        return _ok_origin(resp), 200

    except Exception:
        logging.error("❌ /search/candidates\n"+traceback.format_exc())
        resp = jsonify({"items":[]})
        return _ok_origin(resp), 200
    
@bp_candidate_search.route('/ext/coresignal/search', methods=['POST','OPTIONS'])
def coresignal_search():
    if request.method == 'OPTIONS':
        resp = jsonify({}); resp.status_code = 204
        return _ok_origin(resp)

    import time
    try:
        payload = request.get_json(force=True) or {}

        title = (payload.get("title") or "").strip()
        tools = [str(x).strip() for x in (payload.get("skills") or payload.get("tools") or []) if str(x).strip()]
        loc = (payload.get("location") or "").strip()
        years = payload.get("years_min") or payload.get("years_experience") or None
        page = int(payload.get("page") or 1)
        debug = bool(payload.get("debug"))

        # ——— construir filtros solo con lo que realmente exista
        filt = {}

        # si hay title, usa experience_title (headline solo si es corto o sin espacios)
        if title:
            filt["experience_title"] = title
            if " " not in title:
                filt["headline"] = title

        if tools:
            # `skill` NO existe en la API v2 de Coresignal: contesta 422
            # ("extra_forbidden") y descarta la request COMPLETA, así que toda
            # búsqueda con herramientas devolvía cero. Verificado contra la API:
            # válidos son keyword / summary / experience_description /
            # experience_title / headline / country / location / industry / name.
            filt["keyword"] = " OR ".join([f"({t})" for t in tools])

        # --- Ubicación: siempre restringimos a LATAM/CA ---
        # Si el usuario dio país LATAM, usamos country exacto;
        # si no, gateamos a todo LATAM por country OR.
        if loc and _is_latam_location(loc):
            country_name = _resolve_latam_country_name(loc)
            if country_name:
                filt["country"] = country_name                    # <-- antes: location_country
                logging.info("🌎 location del usuario aceptada (LATAM-country): %r", country_name)
                # si el usuario puso ciudad/estado además del país, puedes opcionalmente mantener 'location'
                if country_name.lower() not in loc.lower():
                    filt["location"] = loc
            else:
                # Ciudad/estado dentro de país LATAM no mapeado con exactitud
                filt["country"] = LATAM_COUNTRY_OR               # <-- antes: location_country = OR
                filt["location"] = loc                            # ciudad/estado ayuda a acotar
                logging.info("🌎 location de usuario (ciudad en LATAM): %r → country gate LATAM + location=%r", loc, loc)
        else:
            # Sin location del usuario o fuera de LATAM → gate amplio LATAM por país
            filt["country"] = LATAM_COUNTRY_OR                   # <-- antes: location_country
            if loc:
                logging.info("🌎 location del usuario NO es LATAM (%r) → aplicando gate LATAM por país", loc)
            else:
                logging.info("🌎 sin location del usuario → aplicando gate LATAM por país")

        # ⚠️ `experience_date_from` TAMPOCO existe en la API v2 (mismo 422 que
        # `skill`), así que mandarlo hacía que la búsqueda devolviera cero. No hay
        # campo temporal en el schema; los años sólo filtran en Vintti Talent.
        if years:
            logging.info("ℹ️ years_experience=%s: Coresignal v2 no tiene filtro temporal, se ignora", years)

        url = f"{CORESIGNAL_API_BASE}/employee_base/search/filter/preview?page={page}"
        logging.info("🌐 [Coresignal] POST %s", url)
        logging.info("➡️ filtros enviados=%s", json.dumps(filt, ensure_ascii=False))

        t0 = time.time()
        r = requests.post(url, headers=_cs_headers(), json=filt, timeout=30)
        dur = int((time.time() - t0) * 1000)

        logging.info("⬅️ status=%s ms=%s", r.status_code, dur)
        _log_cs_credits(r)

        out_of_credits = False
        try:
            r.raise_for_status()
            data = r.json()
        except Exception:
            txt = (r.text or "")[:800]
            logging.error("❌ Error Coresignal %s: %s", r.status_code, txt)
            data = {"items": []}
            # Sin esta distinción la UI muestra "sin resultados para este criterio"
            # y parece que no hay candidatos, cuando en realidad no hay saldo.
            out_of_credits = _cs_out_of_credits(r.status_code, txt)
            if out_of_credits:
                logging.error("💳 Coresignal sin créditos en /ext/coresignal/search")

        # --- Soportar list ó dict ---
        if isinstance(data, list):
            items = data
        else:
            items = (data or {}).get("items") or []

        logging.info("📦 items=%d", len(items))

        sample = [{
            "id": it.get("employee_id") or it.get("id") or it.get("public_identifier"),
            "name": it.get("name") or it.get("full_name") or it.get("public_identifier"),
            "loc": it.get("location") or it.get("country"),
            "headline": (it.get("headline") or "")[:120]
        } for it in items[:5]]
        logging.info("🔎 sample=%s", json.dumps(sample, ensure_ascii=False))

        out = {"page": page, "filters": filt, "data": data}
        if out_of_credits:
            out["out_of_credits"] = True
            out["error"] = _CS_OUT_OF_CREDITS_MESSAGE
        if debug:
            out["debug"] = {
                "filters": filt,
                "duration_ms": dur,
                "items_count": len(items),
                "sample": sample
            }
        return _ok_origin(jsonify(out)), 200

    except Exception:
        logging.error("❌ /ext/coresignal/search\n" + traceback.format_exc())
        return _ok_origin(jsonify({"page": 1, "filters": {}, "data": {"items": []}})), 200
    
@bp_candidate_search.route('/ext/coresignal/collect', methods=['POST','OPTIONS'])
def coresignal_collect():
    if request.method == 'OPTIONS':
        resp = jsonify({}); resp.status_code=204
        return _ok_origin(resp)

    try:
        employee_id = (request.get_json(force=True) or {}).get("employee_id")
        if not employee_id:
            return _ok_origin(jsonify({"error":"missing employee_id"})), 400

        url = f"{CORESIGNAL_API_BASE}/employee_base/collect/{employee_id}"
        r = requests.get(url, headers=_cs_headers(), timeout=30)
        r.raise_for_status()
        data = r.json()
        return _ok_origin(jsonify(data)), 200

    except Exception:
        logging.error("❌ /ext/coresignal/collect\n"+traceback.format_exc())
        return _ok_origin(jsonify({"error":"collect-failed"})), 200
