# ai_candidate_search_routes.py
import os, json, logging, traceback, re
from flask import Blueprint, request, jsonify
from openai import OpenAI
from db import get_connection
import datetime as dt
import requests

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
- tools: array of tool/technology names in English, lowercase (e.g., ["python","excel","react"]). Only explicit tools; do NOT invent; singularize if possible.
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

        if not tools_lc:
            logging.info("🔎 No tools provided → return empty items")
            resp = jsonify({"items":[]})
            return _ok_origin(resp), 200

        # Preparamos patrones para coincidencia parcial
        patterns = [f"%{t}%" for t in tools_lc]
        logging.info("🧾 ILIKE patterns=%r", patterns)

        conn = get_connection()
        cur = conn.cursor()

        # Ordenamos por cantidad de tools matcheadas (hits) y luego por nombre/id
        sql = """
        SELECT
            c.candidate_id,
            c.name,
            c.country,
            c.comments,
            COUNT(DISTINCT kw) AS hits
        FROM candidates c
        JOIN resume r ON r.candidate_id = c.candidate_id

        -- ✅ Fix: solo castea JSON si r.tools es JSON válido
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE
                WHEN r.tools IS NULL OR trim(r.tools) = '' THEN '[]'::jsonb
                WHEN r.tools ~ '^\s*\[.*\]\s*$' THEN r.tools::jsonb
                ELSE '[]'::jsonb
            END
        ) AS t(elem)

        JOIN unnest(%s::text[]) AS kw
            ON lower(t.elem->>'tool') ILIKE kw

        GROUP BY c.candidate_id, c.name, c.country, c.comments
        HAVING COUNT(DISTINCT kw) >= 1
        ORDER BY hits DESC, c.name NULLS LAST, c.candidate_id ASC
        LIMIT 200;
        """
        # --- Sanity checks (SEGUROS; quita en prod si quieres) ---
        try:
            cur.execute("select current_database()")
            dbname = cur.fetchone()[0]
            logging.info("🗄️ current_database=%s", dbname)

            # Cuenta filas que PARECEN json array por regex (sin castear)
            cur.execute("""
                SELECT count(*)
                FROM resume r
                WHERE r.tools ~ '^\s*\[.*\]\s*$'
            """)
            logging.info("🧮 resume rows with tools that look like JSON array = %s", cur.fetchone()[0])

            # Muestra 1 ejemplo usando cast SOLO si pasa regex
            cur.execute("""
                SELECT c.candidate_id,
                       array_agg(lower(t.elem->>'tool')) AS tools_lc
                FROM candidates c
                JOIN resume r ON r.candidate_id = c.candidate_id
                CROSS JOIN LATERAL jsonb_array_elements(
                CASE
                    WHEN r.tools ~ '^\s*\[.*\]\s*$' THEN r.tools::jsonb
                    ELSE '[]'::jsonb
                END
                ) AS t(elem)
                WHERE t.elem ? 'tool'
                GROUP BY c.candidate_id
                ORDER BY c.candidate_id
                LIMIT 1;
            """)
            logging.info("🔎 sample tools from DB: %r", cur.fetchone())
        except Exception:
            logging.exception("⚠️ sanity checks failed")
        # --- fin sanity checks ---

        cur.execute(sql, (patterns,))
        rows = cur.fetchall()
        logging.info("📦 rows_found=%d", len(rows))

        cur.close(); conn.close()

        items = [
            {
                "candidate_id": cid,
                "name": name,
                "country": country,
                "comments": comments,
                "hits": int(hits),
            }
            for cid, name, country, comments, hits in rows
        ]

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
            filt["skill"] = " OR ".join([f"({t})" for t in tools])

        # ⚠️ si el usuario no puso location, no agregamos filtro
        if loc:
            filt["location"] = loc

        # ⚠️ si el usuario no puso años, no agregamos filtro temporal
        if years:
            try:
                y = int(years)
                cutoff_year = dt.date.today().year - y
                # Coresignal acepta "%Y" o "%B %Y". Mandemos solo el año: "2022"
                filt["experience_date_from"] = str(cutoff_year)
            except Exception:
                logging.exception("⚠️ years_experience inválido, ignorando filtro")

        url = f"{CORESIGNAL_API_BASE}/employee_base/search/filter/preview?page={page}"
        logging.info("🌐 [Coresignal] POST %s", url)
        logging.info("➡️ filtros enviados=%s", json.dumps(filt, ensure_ascii=False))

        t0 = time.time()
        r = requests.post(url, headers=_cs_headers(), json=filt, timeout=30)
        dur = int((time.time() - t0) * 1000)

        logging.info("⬅️ status=%s ms=%s", r.status_code, dur)
        try:
            r.raise_for_status()
            data = r.json()
        except Exception:
            txt = (r.text or "")[:800]
            logging.error("❌ Error Coresignal %s: %s", r.status_code, txt)
            data = {"items": []}

        try:
            r.raise_for_status()
            data = r.json()
        except Exception:
            txt = (r.text or "")[:800]
            logging.error("❌ Error Coresignal %s: %s", r.status_code, txt)
            data = {"items": []}

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
