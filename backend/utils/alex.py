"""Cliente para la API de Alex AI (plataforma de entrevistas por IA).

Espeja el patrón de utils/hubspot.py::HubSpotClient, pero Alex autentica con el
header ``X-API-Key`` (no Bearer). Se usa para traer, por opportunity, cuántos
candidatos entrevistó Alex. El enlace opportunity <-> position se hace por el
``opportunity_id`` del Hub incrustado en el ``name`` de la job en Alex.

Docs: https://docs.alex.com/api-reference  (base https://api.alex.com/v1/api)
"""

import os
import re
import time
import unicodedata

import requests


ALEX_API_BASE = "https://api.alex.com/v1/api"

# Cache en memoria de la lista de positions (compartida por proceso). Alex no
# ofrece filtrar positions por substring del nombre, así que listamos todas y
# hacemos el match localmente; el TTL corto evita re-listar en cada request.
_POSITIONS_CACHE = {"expires_at": 0.0, "data": None}
_POSITIONS_TTL_SECONDS = 60.0


class AlexError(RuntimeError):
    pass


def _extract_list(payload):
    """Alex puede devolver una lista pelada o envuelta ({data|results|...}).
    Normaliza a lista en cualquiera de los casos."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "results", "positions", "candidates", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


class AlexClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("ALEX_API_KEY")
        if not self.api_key:
            raise AlexError("Missing ALEX_API_KEY")

    def _request(self, method, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers.update({
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        })
        url = f"{ALEX_API_BASE}{path}"
        # Reintenta ante rate-limit (429) y errores transitorios (502/503/504)
        # con backoff exponencial, igual que HubSpotClient.
        last_status = None
        for attempt in range(5):
            response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
            if response.status_code in (429, 502, 503, 504) and attempt < 4:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after)
                except (TypeError, ValueError):
                    delay = 0.5 * (2 ** attempt)
                time.sleep(min(delay, 8))
                last_status = response.status_code
                continue
            if not response.ok:
                raise AlexError(f"Alex {method} {path} failed: {response.status_code} {response.text}")
            if response.status_code == 204:
                return {}
            return response.json()
        raise AlexError(f"Alex {method} {path} rate-limited after retries (last={last_status})")

    def list_positions(self, status="Active", use_cache=True):
        """Lista las positions de Alex. Cachea el resultado por proceso (TTL corto)."""
        if use_cache:
            now = time.time()
            if _POSITIONS_CACHE["data"] is not None and now < _POSITIONS_CACHE["expires_at"]:
                return _POSITIONS_CACHE["data"]
        params = {}
        if status:
            params["status"] = status
        payload = self._request("GET", "/positions", params=params)
        positions = _extract_list(payload)
        if use_cache:
            _POSITIONS_CACHE["data"] = positions
            _POSITIONS_CACHE["expires_at"] = time.time() + _POSITIONS_TTL_SECONDS
        return positions

    def list_candidates(self, position_id):
        """Candidatos entrevistados por Alex para una position."""
        payload = self._request("GET", "/candidates", params={"positionId": position_id})
        return _extract_list(payload)

    def list_reports(self, position_id):
        """Reportes de entrevista (con score/feedback/video) para una position.
        Cada reporte existe solo cuando el candidato COMPLETA la entrevista."""
        payload = self._request("GET", "/reports", params={"positionId": position_id})
        return _extract_list(payload)

    def get_interview_results_for_opportunity(self, opportunity_id):
        """Devuelve (position_id, results) para una opportunity, donde results es una
        lista de dicts con el score/feedback/video/pdf de Alex por cada reporte,
        ya enriquecidos con el email y nombre del candidato (para el match posterior).
        Si no hay position que haga match, devuelve (None, [])."""
        position = self.find_position_for_opportunity(opportunity_id)
        if not position:
            return None, []
        position_id = position.get("positionId") or position.get("id")

        # candidateId -> {email, name} (los reportes solo traen candidateId)
        cand_map = {}
        for c in self.list_candidates(position_id):
            cid = c.get("candidateId") or c.get("id")
            name = (str(c.get("firstName") or "") + " " + str(c.get("lastName") or "")).strip()
            cand_map[cid] = {"email": c.get("email"), "name": name}

        results = []
        for r in self.list_reports(position_id):
            cid = r.get("candidateId")
            info = cand_map.get(cid, {})
            results.append({
                "alex_candidate_id": cid,
                "email": info.get("email"),
                "name": info.get("name"),
                "overall_score": r.get("overallScore"),
                "overall_feedback": r.get("overallFeedback"),
                "skills": r.get("skills") or [],
                "tags": r.get("tags") or [],
                # Apriora devuelve las URLs con "URL" en mayúscula (videoURL/pdfURL).
                "video_url": r.get("videoURL") or r.get("videoUrl"),
                "pdf_url": r.get("pdfURL") or r.get("pdfUrl"),
                "time_completed": r.get("timeCompleted"),
            })
        return position_id, results

    def find_position_for_opportunity(self, opportunity_id):
        """Encuentra la position de Alex cuyo `name` contiene el opportunity_id
        como token delimitado (evita que "12" haga match con "123").
        Devuelve el dict de la position o None."""
        oid = str(opportunity_id or "").strip()
        if not oid:
            return None
        # El id debe aparecer sin dígitos pegados a los lados: cubre formatos
        # como "Role [#1234]", "Role — 1234", "Role (1234)", etc.
        pattern = re.compile(r"(?<!\d)" + re.escape(oid) + r"(?!\d)")
        # status=None => busca entre TODAS las positions (activas e inactivas),
        # para seguir contando aunque la job quede inactiva en Alex.
        for position in self.list_positions(status=None):
            name = str(position.get("name") or "")
            if pattern.search(name):
                return position
        return None

    def count_interviewed_for_opportunity(self, opportunity_id):
        """Devuelve (count, position_id, matched) para una opportunity.
        Si no hay position que haga match, matched=False y count=0."""
        position = self.find_position_for_opportunity(opportunity_id)
        if not position:
            return 0, None, False
        position_id = position.get("positionId") or position.get("id")
        candidates = self.list_candidates(position_id)
        return len(candidates), position_id, True


def _norm_email(value):
    return (value or "").strip().lower()


def _norm_name(value):
    # Minúsculas, sin acentos y espacios colapsados, para tolerar variaciones.
    s = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.lower().split())


def match_alex_results_to_candidates(alex_results, hub_candidates):
    """Cruza los resultados de Alex con los candidatos del Hub. Match por EMAIL
    (normalizado) primero; si no hay, por NOMBRE (normalizado, sin acentos).
    Devuelve un dict { str(hub_candidate_id): { ...datos de Alex, matched_by } }.

    hub_candidates: lista de dicts con keys candidate_id, email, name.
    """
    by_email = {}
    by_name = {}
    for hc in hub_candidates:
        hub_id = hc.get("candidate_id")
        if hub_id is None:
            continue
        e = _norm_email(hc.get("email"))
        n = _norm_name(hc.get("name"))
        if e and e not in by_email:
            by_email[e] = hub_id
        if n and n not in by_name:
            by_name[n] = hub_id

    out = {}
    for r in alex_results:
        e = _norm_email(r.get("email"))
        n = _norm_name(r.get("name"))
        hub_id, how = None, None
        if e and e in by_email:
            hub_id, how = by_email[e], "email"
        elif n and n in by_name:
            hub_id, how = by_name[n], "name"
        if hub_id is None:
            continue  # candidato de Alex sin correspondencia en el Hub
        out[str(hub_id)] = {**r, "matched_by": how}
    return out
