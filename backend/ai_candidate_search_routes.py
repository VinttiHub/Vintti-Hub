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
        query = (data.get("query") or "").strip()
        logging.info("🧠 [/ai/parse_candidate_query] query_in=%r", query)

        if not query:
            resp = jsonify({"title":"", "tools":[], "years_experience": None})
            return _ok_origin(resp), 200

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        prompt = f"""
Read the following natural language query describing a candidate.
Extract a STRICT JSON with:
- title: the role/job title in English (short, lowercase words, no punctuation). If absent, return "".
- tools: array of tool/technology names in English, lowercase (e.g., ["python","excel","react"]). Only explicit tools; do NOT invent; singularize if possible.
- years_experience: integer years if explicitly stated (e.g., "3 years"), else null.

Rules:
- Only parse what's explicitly present in the query.
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
            obj = {"title":"", "tools":[], "years_experience": None}

        # normalizar
        title = (obj.get("title") or "").strip()
        tools = [str(t).strip().lower() for t in (obj.get("tools") or []) if str(t).strip()]
        years = obj.get("years_experience", None)
        try:
            years = int(years) if years is not None else None
        except:
            years = None

        logging.info("🧠 normalized → title=%r tools=%r years=%r", title, tools, years)

        resp = jsonify({"title": title, "tools": tools, "years_experience": years})
        return _ok_origin(resp), 200

    except Exception:
        logging.error("❌ /ai/parse_candidate_query\n"+traceback.format_exc())
        resp = jsonify({"title":"", "tools":[], "years_experience": None})
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
        CROSS JOIN LATERAL jsonb_array_elements(COALESCE(r.tools::jsonb, '[]'::jsonb)) AS t(elem)
        JOIN unnest(%s::text[]) AS kw
        ON lower(t.elem->>'tool') ILIKE kw
        GROUP BY c.candidate_id, c.name, c.country, c.comments
        HAVING COUNT(DISTINCT kw) >= 1
        ORDER BY hits DESC, c.name NULLS LAST, c.candidate_id ASC
        LIMIT 200
        """
        # --- Sanity checks (BORRAR en prod) ---
        try:
            cur.execute("select current_database()")
            dbname = cur.fetchone()[0]
            logging.info("🗄️ current_database=%s", dbname)

            cur.execute("""
                SELECT count(*) FROM resume r
                WHERE jsonb_typeof(COALESCE(r.tools::jsonb, '[]'::jsonb)) = 'array'
            """)
            logging.info("🧮 resume rows with tools array = %s", cur.fetchone()[0])

            # Muestra 1 ejemplo real de tools en la DB
            cur.execute("""
                SELECT c.candidate_id,
                    array_agg(lower(t.elem->>'tool')) AS tools_lc
                FROM candidates c
                JOIN resume r ON r.candidate_id = c.candidate_id
                CROSS JOIN LATERAL jsonb_array_elements(COALESCE(r.tools::jsonb, '[]'::jsonb)) AS t(elem)
                WHERE t.elem ? 'tool'
                GROUP BY c.candidate_id
                ORDER BY c.candidate_id
                LIMIT 1
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
            {"candidate_id": cid, "name": name, "country": country, "comments": comments}
            for cid, name, country, comments in rows
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
        resp = jsonify({}); resp.status_code=204
        return _ok_origin(resp)

    import time
    try:
        payload = request.get_json(force=True) or {}
        title   = (payload.get("title") or "").strip()
        tools   = [str(x).strip() for x in (payload.get("skills") or payload.get("tools") or []) if str(x).strip()]
        loc     = (payload.get("location") or "").strip()
        years   = payload.get("years_min") or payload.get("years_experience") or None
        page    = int(payload.get("page") or 1)
        debug   = bool(payload.get("debug"))  # ← permite devolver metadatos de depuración al front

        # —— Construcción de filtros Coresignal
        filt = {}
        if title:
            # headline exacta entre comillas si hay espacios; y además experiencia por título
            filt["headline"] = f"\"{title}\"" if " " in title else title
            filt["experience_title"] = title
        if tools:
            # Prefieres OR → "(a) OR (b) OR (c)"
            filt["skill"] = " OR ".join([f"({t})" for t in tools])
        if loc:
            filt["location"] = loc
        if years:
            try:
                years = int(years)
                cutoff = dt.date.today().replace(year=dt.date.today().year - years)
                filt["experience_date_from"] = cutoff.isoformat()
            except Exception:
                logging.exception("⚠️ years_experience inválido, ignorando filtro")

        url = f"{CORESIGNAL_API_BASE}/employee_base/search/filter/preview?page={page}"

        # —— LOG previo a la llamada
        logging.info("🌐 [Coresignal.preview] page=%s url=%s", page, url)
        logging.info("➡️ Filtros enviados (minificado): %s", json.dumps(filt, ensure_ascii=False))

        t0 = time.time()
        r = requests.post(url, headers=_cs_headers(), json=filt, timeout=30)
        dt_ms = int((time.time() - t0) * 1000)

        # —— LOG de respuesta
        logging.info("⬅️ Status=%s Duración=%sms Content-Type=%s Content-Length=%s",
                     r.status_code, dt_ms, r.headers.get("Content-Type"), r.headers.get("Content-Length"))

        # Si no es 2xx, intenta loguear texto para diagnóstico
        try:
            r.raise_for_status()
        except Exception:
            txt = r.text[:2000] if r.text else ""
            logging.error("❌ Error HTTP Coresignal (%s). Primeros 2000 chars de body:\n%s", r.status_code, txt)
            # devuelve estructura estándar vacía con debug si se pidió
            out = {"page": page, "filters": filt, "data": {"items": []}}
            if debug:
                out["debug"] = {
                    "request": {"url": url, "body": filt},
                    "response": {"status": r.status_code, "duration_ms": dt_ms, "raw_snippet": txt[:500]}
                }
            return _ok_origin(jsonify(out)), 200

        # Parsear JSON y loguear métricas
        data = {}
        try:
            data = r.json()
        except Exception:
            txt = r.text[:2000] if r.text else ""
            logging.exception("⚠️ Respuesta no JSON. Snippet:\n%s", txt)
            data = {"items": []}

        items = (data or {}).get("items") or []
        logging.info("📦 Coresignal preview items=%d", len(items))

        # Muestreo de IDs/campos (hasta 5)
        sample = []
        for it in items[:5]:
            sample.append({
                "id": it.get("employee_id") or it.get("id") or it.get("public_identifier"),
                "name": it.get("name") or it.get("full_name") or it.get("public_identifier"),
                "loc": it.get("location") or it.get("country"),
                "headline": (it.get("headline") or "")[:120]
            })
        logging.info("🔎 Sample(≤5): %s", json.dumps(sample, ensure_ascii=False))

        # Armar salida estándar con sección debug opcional
        out = {"page": page, "filters": filt, "data": data}
        if debug:
            out["debug"] = {
                "request": {
                    "url": url,
                    # NUNCA devolvemos headers (para no filtrar API key) — solo el body:
                    "body": filt
                },
                "response": {
                    "status": r.status_code,
                    "duration_ms": dt_ms,
                    "items_count": len(items),
                    "sample": sample
                }
            }

        return _ok_origin(jsonify(out)), 200

    except Exception:
        logging.error("❌ /ext/coresignal/search\n"+traceback.format_exc())
        resp = jsonify({"page": 1, "filters": {}, "data": {"items":[]}})
        return _ok_origin(resp), 200
    
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
