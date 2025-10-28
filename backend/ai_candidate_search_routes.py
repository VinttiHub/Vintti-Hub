# ai_candidate_search_routes.py
import os, json, logging, traceback, re
from flask import Blueprint, request, jsonify
from openai import OpenAI
from db import get_connection

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

@bp_candidate_search.route('/ai/parse_candidate_query', methods=['POST','OPTIONS'])
def parse_candidate_query():
    if request.method == 'OPTIONS':
        resp = jsonify({}); resp.status_code=204
        return _ok_origin(resp)

    try:
        data = request.get_json(force=True) or {}
        query = (data.get("query") or "").strip()
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
        cleaned = re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', content).strip()

        try:
            obj = json.loads(cleaned)
        except Exception:
            obj = {"title":"", "tools":[], "years_experience": None}

        # normalizar
        title = (obj.get("title") or "").strip()
        tools = [str(t).strip().lower() for t in (obj.get("tools") or []) if str(t).strip()]
        years = obj.get("years_experience", None)
        try:
            years = int(years) if years is not None else None
        except:
            years = None

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
        tools = _parse_list(request.args.get('tools', ''))
        tools_lc = [t.lower() for t in tools]
        # Si no hay tools, devolvemos vacío para evitar traer todo
        if not tools_lc:
            resp = jsonify({"items":[]})
            return _ok_origin(resp), 200

        conn = get_connection()
        cur = conn.cursor()

        # IMPORTANTE:
        # - Contamos cuántas herramientas del query existen en resume.tools (json/ jsonb).
        # - Debe cumplir un match AND: el candidato debe tener TODAS las tools pedidas.
        # - Usamos HAVING COUNT(DISTINCT ...) = len(tools_lc).
        sql = """
        SELECT c.candidate_id, c.name, c.country, c.comments
        FROM candidates c
        JOIN resume r ON r.candidate_id = c.candidate_id
        LEFT JOIN LATERAL jsonb_array_elements(COALESCE(r.tools::jsonb, '[]'::jsonb)) AS t(elem) ON TRUE
        GROUP BY c.candidate_id, c.name, c.country, c.comments
        HAVING COUNT(DISTINCT CASE
        WHEN lower(t.elem->>'tool') = ANY(%s) THEN lower(t.elem->>'tool')
        ELSE NULL
        END) >= 1
        ORDER BY COUNT(DISTINCT CASE
                WHEN lower(t.elem->>'tool') = ANY(%s) THEN lower(t.elem->>'tool')
                ELSE NULL
                END) DESC,
                c.name NULLS LAST, c.candidate_id ASC
        LIMIT 200
        """
        cur.execute(sql, (tools_lc, tools_lc))

        rows = cur.fetchall()
        cur.close(); conn.close()

        items = []
        for candidate_id, name, country, comments in rows:
            items.append({
                "candidate_id": candidate_id,
                "name": name,
                "country": country,
                "comments": comments
            })

        resp = jsonify({"items": items})
        return _ok_origin(resp), 200

    except Exception:
        logging.error("❌ /search/candidates\n"+traceback.format_exc())
        resp = jsonify({"items":[]})
        return _ok_origin(resp), 200
