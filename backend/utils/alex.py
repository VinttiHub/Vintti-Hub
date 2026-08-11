"""Cliente para la API de Alex AI (plataforma de entrevistas por IA).

Espeja el patrón de utils/hubspot.py::HubSpotClient, pero Alex autentica con el
header ``X-API-Key`` (no Bearer). Se usa para traer, por opportunity, cuántos
candidatos entrevistó Alex. El enlace opportunity <-> position se hace por el
``opportunity_id`` del Hub incrustado en el ``name`` de la job en Alex.

Docs: https://docs.alex.com/api-reference  (base https://api.alex.com/v1/api)
"""

import html
import os
import re
import time
import unicodedata

import requests

from . import shared_cache


ALEX_API_BASE = "https://api.alex.com/v1/api"

# Alex no ofrece filtrar positions por substring del nombre, así que listamos
# todas y hacemos el match localmente; el TTL corto evita re-listar en cada
# request. El cache vive en Postgres (utils/shared_cache) y no en memoria: con
# varios workers, dos clicks seguidos en "Traer de Apriora" podían caer en
# procesos con caches distintos y devolver números distintos.
_POSITIONS_CACHE_KEY = "alex__positions"
_POSITIONS_TTL_SECONDS = 60


class AlexError(RuntimeError):
    pass


def html_to_text(value):
    """Convierte la job description (HTML del Hub) a texto plano legible para
    Apriora, conservando saltos de párrafo/lista."""
    s = str(value or "")
    s = re.sub(r"(?i)<\s*br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</\s*(p|div|li|h[1-6])\s*>", "\n", s)
    s = re.sub(r"(?i)<\s*li[^>]*>", "• ", s)
    s = re.sub(r"<[^>]+>", "", s)          # resto de tags
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# Criterios de evaluación que lleva TODA entrevista creada desde el Hub.
# (nombre, instrucciones) — ver append_grading_criteria().
APRIORA_GRADING_CRITERIA = [
    (
        "C1 Level of English",
        "Grade whether the transcript shows C1-level English (CEFR). Strong: wide, "
        "precise vocabulary including idioms; varied complex grammar with rare errors; "
        "coherent, well-linked answers; expresses nuanced and abstract ideas easily. "
        "Weak: basic or repetitive vocabulary; simple sentences with frequent grammar "
        "errors; disjointed answers; avoids or fails at complex ideas. Judge language "
        "quality only — not answer length, opinions, or content.",
    ),
]


def append_grading_criteria(jd_text, criteria=APRIORA_GRADING_CRITERIA):
    """Anexa a la JD un bloque de criterios de evaluación. createJob no tiene campo
    de rubric: Apriora deriva los criterios del jobDescription, así que este es el
    único punto de inyección. La nota de "no preguntar" evita que además genere una
    pregunta de inglés (el criterio se juzga sobre el transcript completo)."""
    if not criteria:
        return jd_text
    lines = [
        "Evaluation Criteria",
        "",
        "These are scoring criteria only — do not turn them into interview questions.",
        "Grade them from the candidate's answers to the rest of the interview.",
    ]
    for name, instructions in criteria:
        lines.extend(["", str(name), str(instructions)])
    return f"{str(jd_text or '').rstrip()}\n\n" + "\n".join(lines)


# Sufijos legales que no aportan a las iniciales (Elevate Clinics Inc -> EC).
_INITIALS_SKIP = {"inc", "llc", "ltd", "corp", "co", "sa", "srl", "sas", "sl", "plc", "the"}


def account_initials(name):
    """Iniciales del nombre de la account: 'Elevate Clinics' -> 'EC'."""
    words = re.findall(r"[A-Za-z0-9]+", str(name or ""))
    letters = [w[0] for w in words if w.lower() not in _INITIALS_SKIP]
    if not letters:  # si todo era sufijo/stopword, usa todas las palabras
        letters = [w[0] for w in words]
    return "".join(letters).upper()


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
        """Lista las positions de Alex. Cachea el resultado en Postgres (TTL corto),
        compartido por todos los workers e instancias."""
        # La clave incluye el status porque los llamadores piden tanto "Active"
        # como todas (status=None), y son listas distintas.
        cache_key = f"{_POSITIONS_CACHE_KEY}__{status or 'all'}"
        if use_cache:
            hit, cached = shared_cache.get(cache_key)
            if hit:
                return cached
        params = {}
        if status:
            params["status"] = status
        payload = self._request("GET", "/positions", params=params)
        positions = _extract_list(payload)
        if use_cache:
            shared_cache.set(cache_key, positions, _POSITIONS_TTL_SECONDS)
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

    def create_job(self, external_job_id, job_description, additional_questions=None,
                   intelligently_order_questions=False, active=None,
                   additional_generation_context=None, job_title=None):
        """Crea una job (interviewer) en Apriora desde una job description.
        `external_job_id` debe ser único por company (usamos el opportunity_id del
        Hub, que además sirve para enlazar después por externalJobId).
        `job_title` fija el título de la position. SIEMPRE mandarlo: si va vacío,
        Apriora lo INFIERE del cuerpo de la JD y se queda con el rol que menciona el
        texto (ej. "Account Executive") en vez del opportunity name del Hub.
        `intelligently_order_questions=False` => las preguntas extra se agregan al
        final en el orden dado (no las intercala Apriora).
        `additional_generation_context` sesga la generación de la entrevista (texto
        libre); lo usamos para reforzar los criterios de grading fijos.
        Devuelve el dict de respuesta (payload = interviewerId)."""
        body = {
            "externalJobId": str(external_job_id),
            "jobDescription": job_description,
        }
        if job_title:
            body["jobTitle"] = job_title
        if additional_questions:
            body["additionalQuestions"] = additional_questions
            # Enviar explícito para que NO reordene/intercale las preguntas extra.
            body["intelligentlyOrderQuestions"] = bool(intelligently_order_questions)
        if additional_generation_context:
            body["additionalGenerationContext"] = additional_generation_context
        if active is not None:
            body["active"] = active
        return self._request("POST", "/createJob", json=body)

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

    def find_position_for_opportunity(self, opportunity_id, use_cache=True):
        """Encuentra la position de Alex cuyo `name` contiene el opportunity_id
        como token delimitado (evita que "12" haga match con "123").
        Devuelve el dict de la position o None.
        `use_cache=False` fuerza releer las positions de Apriora sin el cache de
        60s (lo usa el polling de "¿ya está lista?" para detectarla al toque)."""
        oid = str(opportunity_id or "").strip()
        if not oid:
            return None
        # El id debe aparecer sin dígitos pegados a los lados: cubre formatos
        # como "Role [#1234]", "Role — 1234", "Role (1234)", etc.
        pattern = re.compile(r"(?<!\d)" + re.escape(oid) + r"(?!\d)")
        # status=None => busca entre TODAS las positions (activas e inactivas).
        # Preferimos el match EXACTO por externalJobId (jobs creadas desde el Hub);
        # si no, caemos al match por el id en el nombre (jobs creadas a mano).
        name_fallback = None
        for position in self.list_positions(status=None, use_cache=use_cache):
            ext = str(position.get("externalJobId") or "").strip()
            if ext and ext == oid:
                return position
            if name_fallback is None and pattern.search(str(position.get("name") or "")):
                name_fallback = position
        return name_fallback

    def count_interviewed_for_opportunity(self, opportunity_id, use_cache=True):
        """Devuelve (count, position_id, matched) para una opportunity.
        Si no hay position que haga match, matched=False y count=0.
        `use_cache=False` saltea el cache de positions (polling de readiness)."""
        position = self.find_position_for_opportunity(opportunity_id, use_cache=use_cache)
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
