# coresignal_routes.py
import os, re, json, logging, urllib.parse, requests
from flask import Blueprint, jsonify, request
from db import get_connection
from typing import Optional

bp = Blueprint("coresignal", __name__, url_prefix="/coresignal")
API_BASE = "https://api.coresignal.com/cdapi/v2"
API_KEY  = os.getenv("CORESIGNAL_API_KEY")

def _api_key():
    # Se lee al momento de la llamada: el módulo se importa antes de que create_app()
    # cargue backend/.env, y en local API_KEY quedaba en None.
    return os.getenv("CORESIGNAL_API_KEY") or API_KEY

def _h():
    return {"apikey": _api_key(), "accept": "application/json"}

def _slug_from_linkedin(url: str) -> Optional[str]:
    if not url: 
        return None
    url = url.strip()
    if url.startswith("www."): 
        url = "https://" + url
    m = re.search(r"linkedin\.com/(?:in|pub)/([^/?#]+)", url, flags=re.I)
    if not m: 
        return None
    slug = urllib.parse.unquote(m.group(1))
    return slug.strip("/")

def _collect_employee(slug: str):
    # 1) employee_base
    r = requests.get(f"{API_BASE}/employee_base/collect/{slug}", headers=_h(), timeout=30)
    if r.status_code == 404:
        # 2) fallback: employee_clean
        r = requests.get(f"{API_BASE}/employee_clean/collect/{slug}", headers=_h(), timeout=30)
    if not r.ok:
        return None, {"status": r.status_code, "text": r.text}
    return r.json(), {"credits": r.headers.get("x-credits-remaining")}

def fetch_and_store_coresignal(candidate_id: int, linkedin_url: str, overwrite: bool = False):
    """Trae el perfil de Coresignal y lo guarda en candidates.coresignal_scrapper.

    Para llamar desde otro backend (el CV Review, antes de chequear el CV contra LinkedIn).
    Devuelve (perfil, None) o (None, código): "no_api_key" | "no_linkedin" | "fetch_failed".
    Nunca levanta: quien llama sigue sin LinkedIn, no se cae.
    """
    if not _api_key():
        return None, "no_api_key"
    slug = _slug_from_linkedin(linkedin_url or "")
    if not slug:
        return None, "no_linkedin"
    try:
        data, _meta = _collect_employee(slug)
    except Exception:
        logging.exception("coresignal: collect failed for candidate %s", candidate_id)
        return None, "fetch_failed"
    if not isinstance(data, dict):
        return None, "fetch_failed"
    conn = get_connection(); cur = conn.cursor()
    try:
        # Sin `overwrite`, sólo si sigue vacío: la ficha del candidato puede haberlo llenado
        # mientras tanto. Con `overwrite` (copia vieja, se pidió una nueva) se pisa.
        cur.execute("""
            UPDATE candidates SET coresignal_scrapper = %s
            WHERE candidate_id = %s AND (%s OR COALESCE(coresignal_scrapper, '') = '')
        """, (json.dumps(data), candidate_id, bool(overwrite)))
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception("coresignal: could not store profile for candidate %s", candidate_id)
    finally:
        cur.close(); conn.close()
    return data, None

@bp.route("/candidates/<int:candidate_id>/sync", methods=["POST"])
def sync_candidate(candidate_id: int):
    """Lee linkedin del candidato, si coresignal_scrapper está vacío → llama Coresignal y guarda el JSON."""
    if not _api_key():
        return jsonify({"error": "CORESIGNAL_API_KEY missing"}), 500

    force = request.args.get("force") in ("1", "true", "yes")

    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT linkedin, COALESCE(coresignal_scrapper, '') AS cs
            FROM candidates WHERE candidate_id = %s
        """, (candidate_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Candidate not found"}), 404

        linkedin, existing = row[0] or "", row[1] or ""
        if existing and not force:
            return jsonify({"skipped": True, "reason": "coresignal_scrapper already filled"})

        slug = _slug_from_linkedin(linkedin)
        if not slug:
            return jsonify({"error": "Invalid or missing LinkedIn URL on candidate"}), 400

        data, meta = _collect_employee(slug)
        if data is None:
            return jsonify({"error": "Coresignal collect failed", **meta}), 502

        cur.execute("""
            UPDATE candidates SET coresignal_scrapper = %s
            WHERE candidate_id = %s
        """, (json.dumps(data), candidate_id))
        conn.commit()

        # (Opcional) pequeño resumen para la UI
        name = data.get("full name") or data.get("name")
        headline = data.get("headline") or data.get("summary")
        return jsonify({
            "saved": True,
            "credits_remaining": meta.get("credits"),
            "name": name,
            "headline": headline
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close(); conn.close()
