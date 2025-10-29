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

        sql = """
        SELECT c.candidate_id, c.name, c.country, c.comments
        FROM candidates c
        JOIN resume r ON r.candidate_id = c.candidate_id
        LEFT JOIN LATERAL jsonb_array_elements(COALESCE(r.tools::jsonb, '[]'::jsonb)) AS t(elem) ON TRUE
        GROUP BY c.candidate_id, c.name, c.country, c.comments
        HAVING COUNT(DISTINCT CASE
                 WHEN EXISTS (
                     SELECT 1 FROM unnest(%s::text[]) AS kw
                     WHERE lower(t.elem->>'tool') ILIKE kw
                 )
                 THEN lower(t.elem->>'tool')
                 ELSE NULL
               END) >= 1
        ORDER BY COUNT(DISTINCT CASE
                 WHEN EXISTS (
                     SELECT 1 FROM unnest(%s::text[]) AS kw
                     WHERE lower(t.elem->>'tool') ILIKE kw
                 )
                 THEN lower(t.elem->>'tool')
                 ELSE NULL
               END) DESC,
               c.name NULLS LAST, c.candidate_id ASC
        LIMIT 200
        """

        cur.execute(sql, (patterns, patterns))
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

    try:
        payload = request.get_json(force=True) or {}
        title   = (payload.get("title") or "").strip()
        tools   = [str(x).strip() for x in (payload.get("skills") or payload.get("tools") or []) if str(x).strip()]
        loc     = (payload.get("location") or "").strip()
        years   = payload.get("years_min") or payload.get("years_experience") or None
        page    = int(payload.get("page") or 1)

        # —— Construcción de filtros Coresignal
        filt = {}
        if title:
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
                pass

        url = f"{CORESIGNAL_API_BASE}/employee_base/search/filter/preview?page={page}"
        r = requests.post(url, headers=_cs_headers(), json=filt, timeout=30)
        r.raise_for_status()
        data = r.json()

        resp = jsonify({"page": page, "filters": filt, "data": data})
        return _ok_origin(resp), 200

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
