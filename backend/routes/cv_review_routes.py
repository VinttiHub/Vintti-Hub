"""Gate de review de sales lead para los CVs client-facing que arman las recruiters.

La recruiter manda el CV a review; el sales lead aprueba o rechaza con razones
tipificadas; si rechaza vuelve a la recruiter, que corrige y re-envía como round N+1.
Cada ronda queda registrada, así "rechazado a la primera" sigue siendo contestable.

NO confundir con candidates_batches.status = 'Rejected By Sales', que es el resultado
POST-envío de un perfil que el cliente ya vio. Esto es el gate PRE-envío. En la UI se
llaman distinto a propósito: "Review" (esto) vs "Outcome" (aquello). Cuando el sales lead
rechaza acá y el candidato YA está en un batch de esa opp, además le escribimos el status
del batch, para que el donut existente (dashboards/datasets/op_rejection_reasons.py) siga
siendo verdad.

El score AI es informativo, nunca bloqueante: si OpenAI se cae o se queda sin cuota el
review se crea igual con ai_score NULL y ai_error contando qué pasó. Un gate de proceso
no puede depender del presupuesto de OpenAI.
"""
# App Runner corre Python 3.8: `set[str]` y demás genéricos de builtins revientan ahí con
# "TypeError: 'type' object is not subscriptable" al importar el módulo. Este future import
# convierte TODAS las anotaciones en strings, así que nunca se evalúan. Mismo patrón que
# cv_review_store.py, utils/cv_review_ai.py y dashboards/datasets/_periods.py.
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import date, datetime, timezone
from threading import Lock

import psycopg2
from psycopg2 import errors as pg_errors
from flask import Blueprint, jsonify, request
from psycopg2.extras import Json, RealDictCursor

from cv_review_store import ensure_cv_review_tables
from db import get_connection
# Reusamos el gate de dashboards en vez de duplicar su caché de usuarios activos. Es el
# mismo chequeo débil de X-User-Email que usa el resto de la app — spoofable, pero corta
# el acceso anónimo y el de cuentas desactivadas.
from routes.dashboards_routes import _require_active_user, _user_email
from utils import cv_review_ai

bp = Blueprint("cv_review", __name__)

# El par fijo de supervisión: ven TODOS los reviews (no sólo los de sus oportunidades),
# reciben TODOS los mails y pueden decidir. Mismo par que ya usa
# public_reference_feedback_routes.reference_feedback_recipients, para que la app tenga una
# sola noción de "quién supervisa" y no dos listas que se desincronizan.
OVERSIGHT_EMAILS = ("pgonzales@vintti.com", "agostina@vintti.com")

# Quien puede decidir además de los sales leads con rol. Corta a propósito.
REVIEW_OVERRIDE_EMAILS = set(OVERSIGHT_EMAILS)

_SALES_LEADS: set[str] = set()
_SALES_LEADS_TS: float = 0.0
_SALES_LEADS_LOCK = Lock()
_SALES_LEADS_TTL = 300

# Gente de la casa. El mail de review lleva scores de la AI y avisos de CVs que exageran:
# eso no puede salir de Vintti ni por error.
_TEAM_EMAILS: set[str] = set()
_TEAM_TS: float = 0.0
_TEAM_LOCK = Lock()
_TEAM_TTL = 300
_INTERNAL_DOMAINS = ("vintti.com",)

# Cuánto tiempo se le concede al hilo de scoring antes de dejar de decir "scoring…".
# Holgado: gpt-4o con este prompt puede tardar un minuto, y call_openai_with_retry
# duerme 10 s entre reintentos de rate limit.
AI_PENDING_GRACE_SECONDS = 600

_SELECT_COLS = """
    r.review_id, r.candidate_id, r.opportunity_id, r.round, r.status,
    r.recruiter_email, r.hr_lead_email, r.sales_lead_email, r.reviewed_by,
    r.requested_at, r.reviewed_at, r.reject_other, r.reviewer_comment,
    r.recruiter_note, r.ai_score, r.ai_analyzed_at, r.ai_error, r.resume_hash,
    r.checklist_done
"""


# --- auth -------------------------------------------------------------------

def _sales_lead_emails() -> set[str]:
    """Sales leads activos, por rol. Cacheado 300s como la lista de activos del
    dashboard: este set se consulta en cada decisión y en cada carga de la cola."""
    global _SALES_LEADS, _SALES_LEADS_TS
    now = time.time()
    with _SALES_LEADS_LOCK:
        if _SALES_LEADS and (now - _SALES_LEADS_TS) < _SALES_LEADS_TTL:
            return _SALES_LEADS
    emails: set[str] = set()
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT LOWER(TRIM(u.email_vintti))
            FROM user_roles ur
            JOIN users u ON u.user_id = ur.user_id
            LEFT JOIN admin_user_access aua ON aua.user_id = u.user_id
            WHERE ur.role_type = 'sales_lead'
              AND COALESCE(aua.is_active, TRUE)
              AND NULLIF(TRIM(u.email_vintti), '') IS NOT NULL
            """
        )
        emails = {r[0] for r in cur.fetchall() if r and r[0]}
        cur.close()
    except Exception:
        logging.exception("cv_review: no se pudo cargar la lista de sales leads")
        return _SALES_LEADS  # lo que haya; _require_reviewer falla cerrado si está vacía
    finally:
        if conn:
            conn.close()
    with _SALES_LEADS_LOCK:
        _SALES_LEADS = emails
        _SALES_LEADS_TS = now
    return emails


def _is_internal(email):
    """¿Esta dirección es del equipo?

    El dominio no alcanza como única regla: hay gente del equipo con casilla propia
    (hoy una en gmail). Así que vale @vintti.com O estar en la tabla de usuarios.
    """
    e = _as_email(email)
    if not e:
        return False
    if e.rsplit("@", 1)[-1] in _INTERNAL_DOMAINS:
        return True
    return e in _team_emails()


def _team_emails() -> set[str]:
    """Todas las casillas cargadas en users, cacheadas 300s como la lista de sales leads."""
    global _TEAM_EMAILS, _TEAM_TS
    now = time.time()
    with _TEAM_LOCK:
        if _TEAM_EMAILS and (now - _TEAM_TS) < _TEAM_TTL:
            return _TEAM_EMAILS
    emails: set[str] = set()
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT LOWER(TRIM(email_vintti)) FROM users "
            "WHERE NULLIF(TRIM(email_vintti), '') IS NOT NULL"
        )
        emails = {r[0] for r in cur.fetchall() if r and r[0]}
        cur.close()
    except Exception:
        # Falla cerrado: sin lista, sólo pasa el dominio. Preferimos no mandarle el mail
        # interno a alguien de afuera antes que asegurar que le llegue a todo el equipo.
        logging.exception("cv_review: no se pudo cargar la lista del equipo")
        return _TEAM_EMAILS
    finally:
        if conn:
            conn.close()
    with _TEAM_LOCK:
        _TEAM_EMAILS = emails
        _TEAM_TS = now
    return emails


def _require_reviewer():
    """Aprobar/rechazar y ver la cola: sólo sales leads (por rol) + el override.

    A propósito NO se restringe al opp_sales_lead de esa oportunidad: esa columna es
    texto libre y a veces está vieja o vacía, y una restricción dura dejaría esas filas
    imposibles de decidir para siempre. reviewed_by siempre queda grabado, así una
    auditoría puede encontrar quién decidió qué.

    Falla CERRADO si no se pudo cargar el set de sales leads: _require_active_user()
    degrada a chequeo de dominio, lo cual está bien para lecturas y mal para aprobaciones.
    """
    denied = _require_active_user()
    if denied:
        return denied
    email = _user_email()
    if email in REVIEW_OVERRIDE_EMAILS or email in _sales_lead_emails():
        return None
    return jsonify({"error": "forbidden", "code": "not_a_reviewer"}), 403


def _require_actor():
    """Cualquier usuario activo, pero con email: la atribución es todo el punto."""
    denied = _require_active_user()
    if denied:
        return denied
    if not _user_email():
        return jsonify({"error": "unauthorized"}), 401
    return None


# --- serialización ----------------------------------------------------------

def _iso(value):
    return value.isoformat() if value else None


def _within(ts, seconds):
    """True si `ts` es de hace menos de `seconds`. Tolera un valor naive en vez de
    reventar con TypeError: esto sólo decide qué cartelito mostrar."""
    if not ts:
        return False
    try:
        now = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            now = now.replace(tzinfo=None)
        return (now - ts).total_seconds() < seconds
    except (TypeError, AttributeError):
        return False


def _serialize(row, *, reasons=None, checklist=None, analysis=None, live_hash=None):
    out = {
        "review_id": row["review_id"],
        "candidate_id": row["candidate_id"],
        "opportunity_id": row["opportunity_id"],
        "round": row["round"],
        "status": row["status"],
        "recruiter_email": row["recruiter_email"],
        "hr_lead_email": row.get("hr_lead_email"),
        "sales_lead_email": row.get("sales_lead_email"),
        "reviewed_by": row.get("reviewed_by"),
        "requested_at": _iso(row["requested_at"]),
        "reviewed_at": _iso(row.get("reviewed_at")),
        "reject_other": row.get("reject_other"),
        "reviewer_comment": row.get("reviewer_comment"),
        "recruiter_note": row.get("recruiter_note"),
        "ai_score": row.get("ai_score"),
        "ai_analyzed_at": _iso(row.get("ai_analyzed_at")),
        "ai_error": row.get("ai_error"),
        "reasons": list(reasons or []),
        # Los defectos del documento. Van SIEMPRE, no sólo en los rechazos: el caso que esto
        # existe para capturar es el CV aprobado al que igual le faltaba la educación.
        "checklist": list(checklist or []),
        "checklist_done": bool(row.get("checklist_done")),
    }
    # La cobertura de la JD también le sirve a la recruiter: es lo que tiene que arreglar.
    # Va sólo esa parte y no el ai_analysis entero, que pesa varios KB por ronda y el
    # historial trae todas las rondas.
    blob = row.get("ai_analysis")
    if isinstance(blob, dict):
        out["jd_requirements"] = blob.get("jd_requirements") or []
        out["requirements_summary"] = blob.get("_requirements_summary") or {}
        # El motivo por el que no hay número va como dato, no se re-deriva en el front:
        # "sin score" se puede leer de scorable==0, pero dos copias de la misma regla se
        # desincronizan — misma razón por la que `counts` viaja en vez de recalcularse.
        out["score_basis"] = blob.get("_score_basis")
        # Del job hopping va sólo el resumen, no los tramos: acá se pinta UNA línea. Mandar
        # la lista entera repetiría el mismo peso por cada ronda del historial para algo que
        # esa vista no muestra.
        hop = blob.get("_job_hopping")
        if isinstance(hop, dict):
            out["job_hopping"] = {k: hop.get(k) for k in
                                  ("state", "penalty", "short", "explained", "unexplained")}
    # "Todavía scoreando": la fila se crea antes que el score a propósito (ver el submit).
    # Con ventana de tiempo: el score corre en un hilo daemon, así que si App Runner
    # recicla el worker a mitad de camino nadie lo vuelve a tocar. Sin este corte la UI
    # diría "scoring…" para siempre, que es mentira — pasado el límite se muestra como
    # sin score y el botón "Re-run" de la cola lo arregla.
    out["ai_pending"] = (
        row["status"] != "cancelled"
        and not row.get("ai_analyzed_at")
        and not row.get("ai_error")
        and _within(row.get("requested_at"), AI_PENDING_GRACE_SECONDS)
    )
    for extra in ("candidate_name", "opp_position_name", "client_name", "opp_stage"):
        if extra in row:
            out[extra] = row[extra]
    if analysis is not None:
        out["ai_analysis"] = analysis
    if live_hash is not None:
        # La recruiter puede editar el CV mientras el review está pendiente: no lo
        # bloqueamos (PATCH /resumes/<id> es también por donde el CLIENTE deja las
        # estrellas), pero el reviewer tiene que ver que cambió.
        out["resume_drift"] = bool(live_hash and live_hash != row.get("resume_hash"))
    return out


def _load_reasons(cur, review_ids):
    if not review_ids:
        return {}
    cur.execute(
        "SELECT review_id, reason_code FROM cv_review_reasons WHERE review_id = ANY(%s)",
        (list(review_ids),),
    )
    out = {}
    for row in cur.fetchall():
        out.setdefault(row["review_id"], []).append(row["reason_code"])
    return out


def _load_checklist(cur, review_ids):
    """Los ítems tildados, en lote. Mismo motivo que _load_reasons: la cola pinta decenas de
    filas y un query por fila la vuelve inusable."""
    if not review_ids:
        return {}
    cur.execute(
        "SELECT review_id, item_code FROM cv_review_checklist WHERE review_id = ANY(%s)",
        (list(review_ids),),
    )
    out = {}
    for row in cur.fetchall():
        out.setdefault(row["review_id"], []).append(row["item_code"])
    return out


# --- razones y checklist (una sola fuente para el frontend) -----------------

@bp.route("/cv_review_reasons", methods=["GET"])
def list_reject_reasons():
    """Para que la lista no quede hardcodeada dos veces (Python y JS)."""
    return jsonify({
        "reasons": [{"code": c, "label": l} for c, l in cv_review_ai.REJECT_REASONS],
    })


@bp.route("/cv_review_checklist_items", methods=["GET"])
def list_checklist_items():
    """Igual que las razones: la lista se pinta en la UI en ESTE orden y no se duplica en JS."""
    return jsonify({
        "items": [{"code": c, "label": l} for c, l in cv_review_ai.CHECKLIST_ITEMS],
    })


# --- submit -----------------------------------------------------------------
#
# El núcleo por-candidato vive en _prepare_review + _insert_review porque lo usan DOS
# caminos: el botón individual de candidate-details y el "Send for Approval" de un batch
# entero en opportunity-detail. Los dos tienen que aplicar exactamente las mismas
# validaciones y armar el mismo snapshot, o el mismo CV mediría distinto según por dónde
# entró.

# Motivos por los que un candidato puede quedar afuera. El texto es el que ve la recruiter.
SKIP_REASONS = {
    "not_found": "Candidate not found",
    "not_linked": "Not linked to this opportunity",
    "empty_resume": "No CV generated yet",
    "no_jd": "The opportunity has no job description",
    "already_pending": "Already waiting for a sales review",
    "failed": "Could not be prepared",
}


def _prepare_review(cur, candidate_id, opportunity_id):
    """Valida y arma todo lo que necesita un review. Devuelve (ctx, error_code)."""
    cur.execute(
        """
        SELECT c.name AS candidate_name,
               c.cv_pdf_scrapper, c.affinda_scrapper,
               c.linkedin_scrapper, c.coresignal_scrapper
        FROM candidates c WHERE c.candidate_id = %s LIMIT 1
        """,
        (candidate_id,),
    )
    candidate = cur.fetchone()
    if not candidate:
        return None, "not_found"

    cur.execute(
        """
        SELECT o.opp_position_name, o.opp_sales_lead, o.opp_hr_lead,
               COALESCE(a.client_name, '') AS client_name,
               EXISTS (SELECT 1 FROM opportunity_candidates oc
                        WHERE oc.opportunity_id = o.opportunity_id
                          AND oc.candidate_id = %s) AS linked
        FROM opportunity o
        LEFT JOIN account a ON a.account_id = o.account_id
        WHERE o.opportunity_id = %s LIMIT 1
        """,
        (candidate_id, opportunity_id),
    )
    opp = cur.fetchone()
    if not opp:
        return None, "opp_not_found"
    if not opp["linked"]:
        return None, "not_linked"

    cur.execute("SELECT * FROM resume WHERE candidate_id = %s LIMIT 1", (candidate_id,))
    snapshot = cv_review_ai.resume_snapshot(cur.fetchone() or {})
    if cv_review_ai.snapshot_is_empty(snapshot):
        return None, "empty_resume"

    # La JD la trae el mismo helper que usa el generador, así el juez ve exactamente la JD
    # que vio el generador (misma precedencia hr_jd → career_desc → career_reqs y el mismo
    # RESUME_JD_LIMIT).
    from ai_routes import _build_resume_target_role_block, _build_opportunity_context
    from ai_routes import RESUME_JD_LIMIT, _truncate_preserving_edges
    jd_plain, opp_ctx = _build_opportunity_context(cur, opportunity_id)
    jd_block = _build_resume_target_role_block({
        "client_name": opp["client_name"],
        "position": opp_ctx.get("position", "") or (opp["opp_position_name"] or ""),
        "career_country": opp_ctx.get("career_country", ""),
        "years_experience": str(opp_ctx.get("years_experience") or ""),
        "jd": _truncate_preserving_edges(jd_plain, RESUME_JD_LIMIT),
    })

    return {
        "candidate_id": candidate_id,
        "opportunity_id": opportunity_id,
        "candidate_name": candidate["candidate_name"],
        "snapshot": snapshot,
        "resume_hash": cv_review_ai.snapshot_hash(snapshot),
        "source_text": cv_review_ai.build_source_text(candidate),
        "jd_block": jd_block,
        # Sin JD el review se crea igual (el gate es de proceso, no de datos) pero el score
        # queda marcado como no aplicable.
        "has_jd": bool((jd_plain or "").strip()),
        "sales_lead": (opp["opp_sales_lead"] or "").strip().lower() or None,
        "hr_lead": (opp["opp_hr_lead"] or "").strip().lower() or None,
    }, None


def _insert_review(conn, cur, ctx, actor, note):
    """Inserta la ronda N+1. Devuelve (row, error_code).

    La fila va ANTES del score a propósito: si scoreáramos primero, el usuario miraría un
    spinner de 20-60s y un doble click crearía dos rondas.
    """
    cid, oid = ctx["candidate_id"], ctx["opportunity_id"]
    for attempt in (1, 2):  # el índice parcial puede rechazar una carrera; un retry
        try:
            cur.execute(
                """
                INSERT INTO cv_reviews (
                    candidate_id, opportunity_id, round, recruiter_email,
                    hr_lead_email, sales_lead_email, recruiter_note,
                    resume_snapshot, resume_hash
                )
                SELECT %s, %s,
                       COALESCE(MAX(round), 0) + 1,
                       %s, %s, %s, %s, %s, %s
                FROM cv_reviews
                WHERE candidate_id = %s AND opportunity_id = %s
                -- Un RECHAZO cierra el perfil para esta vacante: el candidato no va, y
                -- otra ronda sería rehacer un CV que igual no se manda. Para pedir una
                -- corrección está el otro botón, que sí deja reenviar.
                -- HAVING y no un SELECT previo: así la guarda es atómica contra el INSERT,
                -- igual que el índice parcial lo es contra el doble submit.
                -- El COALESCE es obligatorio: sin filas, bool_or() da NULL y el HAVING
                -- bloquearía el PRIMER envío de todos los perfiles.
                HAVING COALESCE(bool_or(status = 'rejected'), false) = false
                RETURNING """ + _SELECT_COLS.replace("r.", ""),
                (cid, oid, actor, ctx["hr_lead"], ctx["sales_lead"], note,
                 Json(ctx["snapshot"]), ctx["resume_hash"], cid, oid),
            )
            row = cur.fetchone()
            if row is None:
                # Sólo lo devuelve vacío el HAVING de arriba: el perfil está rechazado.
                conn.rollback()
                return None, "rejected"
            conn.commit()
            return row, None
        except pg_errors.UniqueViolation:
            conn.rollback()
            # Ya hay un review abierto para este perfil (índice parcial
            # cv_reviews_one_pending_uq) → devolvemos el que hay y la UI pinta el chip.
            cur.execute(
                "SELECT " + _SELECT_COLS + """
                FROM cv_reviews r
                WHERE r.candidate_id = %s AND r.opportunity_id = %s AND r.status = 'pending'
                LIMIT 1
                """,
                (cid, oid),
            )
            existing = cur.fetchone()
            if existing:
                return existing, "already_pending"
            if attempt == 2:
                raise  # choque de round contra round: ya reintentamos una vez
    return None, "failed"


@bp.route("/candidates/<int:candidate_id>/cv_reviews", methods=["POST", "OPTIONS"])
def submit_cv_review(candidate_id):
    if request.method == "OPTIONS":
        return ("", 204)

    denied = _require_actor()
    if denied:
        return denied
    actor = _user_email()

    data = request.get_json(silent=True) or {}
    try:
        opportunity_id = int(data.get("opportunity_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "opportunity_id is required", "code": "no_opportunity"}), 400
    note = (data.get("note") or "").strip() or None

    ensure_cv_review_tables()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        ctx, err = _prepare_review(cur, candidate_id, opportunity_id)
        if err == "not_found":
            return jsonify({"error": "candidate not found"}), 404
        if err == "opp_not_found":
            return jsonify({"error": "opportunity not found"}), 404
        if err == "not_linked":
            return jsonify({"error": "That candidate is not linked to that opportunity.",
                            "code": "not_linked"}), 409
        if err == "empty_resume":
            return jsonify({"error": "Generate the CV before sending it to review.",
                            "code": "empty_resume"}), 422

        inserted, ins_err = _insert_review(conn, cur, ctx, actor, note)
        if ins_err == "already_pending":
            return jsonify({
                "error": "This CV is already waiting for a sales review.",
                "code": "already_pending",
                "review": _serialize(inserted),
            }), 409
        if ins_err == "rejected":
            return jsonify({
                "error": "This candidate was rejected for this vacancy, so there is no new "
                         "round to send. If that was a mistake, ask the sales lead to "
                         "reopen the rejection.",
                "code": "rejected"}), 409
    except Exception:
        # Exception y no psycopg2.Error: este bloque también arma el snapshot e importa
        # ai_routes, así que un fallo no-SQL acá tiene que devolver un error limpio en vez
        # de un traceback con datos del candidato adentro.
        conn.rollback()
        logging.exception("cv_review submit failed")
        return jsonify({"error": "Could not create the review."}), 500
    finally:
        cur.close()
        conn.close()

    if not inserted:  # defensivo: no debería pasar, pero mejor 500 que AttributeError
        return jsonify({"error": "Could not create the review."}), 500

    # Score AI + mail EN BACKGROUND: gpt-4o tarda 20-60s y _send_email hace un POST con
    # timeout=30. Lo que importa para el gate es que la fila exista, y ya está commiteada.
    _spawn_scoring(
        review_id=inserted["review_id"],
        has_jd=ctx["has_jd"],
        snapshot=ctx["snapshot"],
        jd_block=ctx["jd_block"],
        source_text=ctx["source_text"],
        resume_hash=ctx["resume_hash"],
    )

    return jsonify({
        "review": _serialize(inserted),
        "ai_pending": True,
        # El mail sale del hilo, así que en este punto todavía no se sabe. La UI no debe
        # afirmar que se mandó.
        "email_queued": True,
    }), 201


@bp.route("/cv_reviews/reviewers", methods=["GET"])
def cv_review_reviewers():
    """Quién puede revisar un CV. Lo usa el popup de batch para detectar el modo.

    MISMA fuente que la autorización (_require_reviewer), a propósito. Es tentador usar
    GET /users/sales-leads, pero eso sale de DISTINCT account.account_manager — los dueños
    de cuentas del CRM — y NO de user_roles. Son conjuntos distintos, y usar el equivocado
    lleva al peor caso: el popup dice "modo review" y después el backend le devuelve 403 a
    esa persona cuando intenta decidir.
    """
    denied = _require_active_user()
    if denied:
        return denied
    emails = sorted(set(_sales_lead_emails()) | set(OVERSIGHT_EMAILS))
    return jsonify({"emails": emails})


@bp.route("/batches/<int:batch_id>/cv_reviews", methods=["POST", "OPTIONS"])
def submit_batch_cv_reviews(batch_id):
    """Manda TODOS los CVs de un batch a review de una sola vez.

    Lo dispara el "Send for Approval" de opportunity-detail cuando detecta un sales lead
    entre los destinatarios. Hace lo mismo que el botón individual por cada candidato, pero
    manda UN solo mail con los N CVs en vez de N mails.

    Devuelve 200 con el parcial: los que entraron y los que quedaron afuera con el motivo.
    Frenar el batch entero porque a uno le falta el CV sería peor — la recruiter arregla ese
    y re-manda, y el índice parcial evita duplicar los que ya estaban.
    """
    if request.method == "OPTIONS":
        return ("", 204)

    denied = _require_actor()
    if denied:
        return denied
    actor = _user_email()

    data = request.get_json(silent=True) or {}
    note = (data.get("note") or "").strip() or None
    extra_to = [str(e).strip().lower() for e in (data.get("recipients") or []) if str(e).strip()]
    extra_cc = [str(e).strip().lower() for e in (data.get("cc") or []) if str(e).strip()]
    # El borrador al cliente viaja con el review: el sales lead lo copia y lo pega para
    # mandárselo al cliente una vez que aprueba. Si no lo adjuntáramos, tendría que volver
    # a la oportunidad a generarlo de nuevo.
    client_subject = (data.get("client_subject") or "").strip() or None
    client_body = _sanitize_client_draft(data.get("client_body"))

    ensure_cv_review_tables()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    created, skipped = [], []
    batch_number = None
    try:
        cur.execute(
            "SELECT batch_number, opportunity_id FROM batch WHERE batch_id = %s LIMIT 1",
            (batch_id,),
        )
        batch = cur.fetchone()
        if not batch:
            return jsonify({"error": "batch not found"}), 404
        batch_number = batch["batch_number"]
        opportunity_id = batch["opportunity_id"]

        # Sin `c.*`: ese es el SELECT de /batches/<id>/candidates y arrastra los blobs de
        # los scrapers (49 KB por candidato en un caso real). Acá sólo hace falta el nombre.
        cur.execute(
            """
            SELECT cb.candidate_id, COALESCE(c.name, '') AS name
            FROM candidates_batches cb
            JOIN candidates c ON c.candidate_id = cb.candidate_id
            WHERE cb.batch_id = %s
            ORDER BY c.name
            """,
            (batch_id,),
        )
        members = cur.fetchall()
        if not members:
            return jsonify({"error": "That batch has no candidates.",
                            "code": "empty_batch"}), 422

        for m in members:
            cid, name = m["candidate_id"], m["name"]
            try:
                ctx, err = _prepare_review(cur, cid, opportunity_id)
                if err:
                    skipped.append({"candidate_id": cid, "name": name, "code": err,
                                    "reason": SKIP_REASONS.get(err, err)})
                    continue
                row, ins_err = _insert_review(conn, cur, ctx, actor, note)
                if ins_err:
                    skipped.append({"candidate_id": cid, "name": name, "code": ins_err,
                                    "reason": SKIP_REASONS.get(ins_err, ins_err)})
                    continue
                created.append({
                    "candidate_id": cid, "name": name,
                    "review_id": row["review_id"], "round": row["round"],
                    "_ctx": ctx,
                })
            except Exception:
                # Un candidato roto no puede tumbar el batch entero.
                conn.rollback()
                logging.exception("cv_review batch: candidate %s failed", cid)
                skipped.append({"candidate_id": cid, "name": name, "code": "failed",
                                "reason": SKIP_REASONS["failed"]})
    except Exception:
        conn.rollback()
        logging.exception("cv_review batch submit failed")
        return jsonify({"error": "Could not create the reviews."}), 500
    finally:
        cur.close()
        conn.close()

    if not created:
        return jsonify({
            "error": "None of the candidates in this batch could be sent to review.",
            "code": "none_eligible",
            "batch_number": batch_number,
            "created": [], "skipped": skipped,
        }), 422

    # UN hilo para todo el batch: scorea los N y después manda UN mail con los N scores.
    _spawn_batch_scoring(
        items=[{k: v for k, v in c.items()} for c in created],
        batch_id=batch_id,
        batch_number=batch_number,
        note=note,
        extra_to=extra_to,
        extra_cc=extra_cc,
        client_subject=client_subject,
        client_body=client_body,
    )

    return jsonify({
        "batch_number": batch_number,
        "created": [{k: v for k, v in c.items() if k != "_ctx"} for c in created],
        "skipped": skipped,
        "ai_pending": True,
        "email_queued": True,
    }), 200


def _score_batch_and_notify(*, items, batch_id, batch_number, note, extra_to, extra_cc,
                            client_subject=None, client_body=None):
    """Scorea los N CVs del batch y después manda UN solo mail. Fuera del request."""
    for it in items:
        ctx = it.get("_ctx") or {}
        try:
            _score_and_notify(
                review_id=it["review_id"],
                has_jd=ctx.get("has_jd", False),
                snapshot=ctx.get("snapshot") or {},
                jd_block=ctx.get("jd_block") or "",
                source_text=ctx.get("source_text") or "",
                resume_hash=ctx.get("resume_hash") or "",
                notify=False,   # el mail del batch va uno solo, al final
            )
        except Exception:
            logging.exception("cv_review batch: scoring review %s failed", it.get("review_id"))

    try:
        _notify_batch_submitted(
            review_ids=[it["review_id"] for it in items],
            batch_number=batch_number,
            note=note,
            extra_to=extra_to,
            extra_cc=extra_cc,
            client_subject=client_subject,
            client_body=client_body,
        )
    except Exception:
        logging.exception("cv_review batch: notification failed")


def _spawn_batch_scoring(**kwargs):
    def _run():
        try:
            _score_batch_and_notify(**kwargs)
        except Exception:
            logging.exception("cv_review: background batch scoring failed")

    threading.Thread(
        target=_run, name=f"cv-review-batch-{kwargs.get('batch_id')}", daemon=True
    ).start()


def _score_and_notify(*, review_id, has_jd, snapshot, jd_block, source_text, resume_hash,
                      notify=True):
    """Scorea y avisa. Corre fuera del request: nada de `request` ni de Flask acá.

    `notify=False` lo usa el camino de batch, que manda un único mail al final en vez de uno
    por candidato.
    """
    if has_jd:
        fingerprint = cv_review_ai.input_hash({
            "s": resume_hash, "j": jd_block, "src": cv_review_ai.input_hash(source_text),
            "v": cv_review_ai.ANALYSIS_VERSION,
        })
        score, analysis, ai_error = cv_review_ai.score_cv(
            snapshot=snapshot, jd_block=jd_block, source_text=source_text,
            fingerprint=fingerprint,
        )
    else:
        # Sin JD el score no significa nada, pero el review ya se creó: el gate es de
        # proceso, no de datos.
        score, analysis, ai_error = None, None, "no_jd"

    _store_analysis(review_id, score, analysis, ai_error)

    # El mail va DESPUÉS del score para que lleve el número adentro, pero se manda pase lo
    # que pase: avisarle al sales lead importa más que el score.
    if notify:
        _notify_submitted(review_id)


def _spawn_scoring(**kwargs):
    def _run():
        try:
            _score_and_notify(**kwargs)
        except Exception:
            logging.exception("cv_review: background scoring/notification failed")

    threading.Thread(
        target=_run, name=f"cv-review-score-{kwargs.get('review_id')}", daemon=True
    ).start()


def _store_analysis(review_id, score, analysis, ai_error):
    """Guarda el resultado del juez. Devuelve el ai_analyzed_at que quedó, o None."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE cv_reviews
               SET ai_score = %s,
                   ai_analysis = %s,
                   ai_analyzed_at = CASE WHEN %s THEN NOW() ELSE NULL END,
                   ai_error = %s,
                   updated_at = NOW()
             WHERE review_id = %s
            RETURNING ai_analyzed_at
            """,
            (score, Json(analysis) if analysis else None,
             analysis is not None, ai_error, review_id),
        )
        row = cur.fetchone()
        conn.commit()
        return row[0] if row else None
    except Exception:
        conn.rollback()
        logging.exception("cv_review: could not store the AI analysis")
        return None
    finally:
        cur.close()
        conn.close()


# --- historial de un candidato ---------------------------------------------

@bp.route("/candidates/<int:candidate_id>/cv_reviews", methods=["GET"])
def list_candidate_cv_reviews(candidate_id):
    denied = _require_active_user()
    if denied:
        return denied

    ensure_cv_review_tables()
    opportunity_id = request.args.get("opportunity_id")

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        params = [candidate_id]
        clause = ""
        if opportunity_id:
            try:
                params.append(int(opportunity_id))
                clause = "AND r.opportunity_id = %s"
            except ValueError:
                return jsonify({"error": "opportunity_id must be an integer"}), 400
        cur.execute(
            "SELECT " + _SELECT_COLS + """,
                   r.ai_analysis,
                   o.opp_position_name, COALESCE(a.client_name, '') AS client_name
            FROM cv_reviews r
            LEFT JOIN opportunity o ON o.opportunity_id = r.opportunity_id
            LEFT JOIN account a     ON a.account_id     = o.account_id
            WHERE r.candidate_id = %s """ + clause + """
            ORDER BY r.opportunity_id, r.round DESC
            """,
            tuple(params),
        )
        rows = cur.fetchall()
        review_ids = [r["review_id"] for r in rows]
        reasons = _load_reasons(cur, review_ids)
        checklist = _load_checklist(cur, review_ids)

        cur.execute("SELECT * FROM resume WHERE candidate_id = %s LIMIT 1", (candidate_id,))
        live = cur.fetchone()
        live_hash = cv_review_ai.snapshot_hash(cv_review_ai.resume_snapshot(live)) if live else None
    finally:
        cur.close()
        conn.close()

    return jsonify({
        "reviews": [_serialize(r, reasons=reasons.get(r["review_id"]),
                              checklist=checklist.get(r["review_id"]), live_hash=live_hash)
                    for r in rows],
        "live_resume_hash": live_hash,
    })


# --- cola del sales lead ---------------------------------------------------

@bp.route("/cv_reviews", methods=["GET"])
def list_cv_reviews():
    denied = _require_reviewer()
    if denied:
        return denied

    ensure_cv_review_tables()

    status = (request.args.get("status") or "").strip().lower()
    recruiter = (request.args.get("recruiter") or "").strip().lower()
    sales_lead = (request.args.get("sales_lead") or "").strip().lower()
    if request.args.get("mine") == "1":
        sales_lead = _user_email() or sales_lead
    try:
        limit = min(int(request.args.get("limit", 100)), 500)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        return jsonify({"error": "limit and offset must be integers"}), 400

    where = ["TRUE"]
    params = {}
    if status:
        if status not in ("pending", "approved", "rejected", "changes_requested", "cancelled"):
            return jsonify({"error": "unknown status"}), 400
        where.append("r.status = %(status)s")
        params["status"] = status
    if recruiter:
        where.append("LOWER(TRIM(r.recruiter_email)) = %(recruiter)s")
        params["recruiter"] = recruiter
    if sales_lead:
        where.append("LOWER(TRIM(COALESCE(r.sales_lead_email, ''))) = %(sales_lead)s")
        params["sales_lead"] = sales_lead
    params["limit"] = limit
    params["offset"] = offset

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT COUNT(*) AS total FROM cv_reviews r WHERE " + " AND ".join(where), params
        )
        total = cur.fetchone()["total"]
        cur.execute(
            "SELECT " + _SELECT_COLS + """,
                   c.name AS candidate_name,
                   o.opp_position_name, o.opp_stage,
                   COALESCE(a.client_name, '') AS client_name
            FROM cv_reviews r
            LEFT JOIN candidates c  ON c.candidate_id   = r.candidate_id
            LEFT JOIN opportunity o ON o.opportunity_id = r.opportunity_id
            LEFT JOIN account a     ON a.account_id     = o.account_id
            WHERE """ + " AND ".join(where) + """
            -- pendientes primero, y dentro de eso lo más viejo arriba: la cola se lee
            -- de arriba hacia abajo y lo que espera más tiempo es lo más urgente.
            ORDER BY (r.status = 'pending') DESC,
                     CASE WHEN r.status = 'pending' THEN r.requested_at END ASC,
                     r.requested_at DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            params,
        )
        rows = cur.fetchall()
        review_ids = [r["review_id"] for r in rows]
        reasons = _load_reasons(cur, review_ids)
        checklist = _load_checklist(cur, review_ids)
    finally:
        cur.close()
        conn.close()

    return jsonify({
        "reviews": [_serialize(r, reasons=reasons.get(r["review_id"]),
                              checklist=checklist.get(r["review_id"])) for r in rows],
        "total": total,
    })


@bp.route("/cv_reviews/pending_count", methods=["GET"])
def cv_review_pending_count():
    """Cuántos CVs esperan decisión. Para la burbujita del sidebar.

    Endpoint aparte y no `GET /cv_reviews?status=pending` porque esto lo pide el sidebar en
    CADA página del Hub: acá es un COUNT y nada más, sin traer filas ni hacer los JOINs de
    la cola. `mine=1` lo acota al sales lead, igual que la cola y la métrica.
    """
    denied = _require_reviewer()
    if denied:
        return denied

    ensure_cv_review_tables()
    sales_lead = (request.args.get("sales_lead") or "").strip().lower()
    if request.args.get("mine") == "1":
        sales_lead = _user_email() or sales_lead

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM cv_reviews
            WHERE status = 'pending'
              AND (%s = '' OR LOWER(TRIM(COALESCE(sales_lead_email, ''))) = %s)
            """,
            (sales_lead, sales_lead),
        )
        count = cur.fetchone()[0]
    finally:
        cur.close()
        conn.close()
    return jsonify({"count": count, "sales_lead": sales_lead})


@bp.route("/cv_reviews/<int:review_id>", methods=["GET"])
def get_cv_review(review_id):
    denied = _require_reviewer()
    if denied:
        return denied

    ensure_cv_review_tables()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT " + _SELECT_COLS + """,
                   r.ai_analysis, r.resume_snapshot,
                   c.name AS candidate_name,
                   o.opp_position_name, o.opp_stage,
                   COALESCE(a.client_name, '') AS client_name
            FROM cv_reviews r
            LEFT JOIN candidates c  ON c.candidate_id   = r.candidate_id
            LEFT JOIN opportunity o ON o.opportunity_id = r.opportunity_id
            LEFT JOIN account a     ON a.account_id     = o.account_id
            WHERE r.review_id = %s LIMIT 1
            """,
            (review_id,),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "review not found"}), 404
        reasons = _load_reasons(cur, [review_id]).get(review_id)
        checklist = _load_checklist(cur, [review_id]).get(review_id)

        cur.execute("SELECT * FROM resume WHERE candidate_id = %s LIMIT 1", (row["candidate_id"],))
        live = cur.fetchone()
        live_hash = cv_review_ai.snapshot_hash(cv_review_ai.resume_snapshot(live)) if live else None

        # ¿La JD cambió desde que se corrió el análisis? Sin esto, editar la vacante y
        # volver a abrir el review muestra una checklist vieja que parece actual, y el
        # reviewer decide contra requisitos que ya no son los del cliente.
        # Tres estados, no dos: la JD cambió, la JD está igual, o NO SE PUEDE SABER porque
        # el análisis es anterior a que se guardara la huella. El tercero es el que más
        # avisa que hay que re-correr, y tratarlo como "está igual" lo escondía.
        jd_changed = False
        blob = row.get("ai_analysis")
        jd_checked = bool(isinstance(blob, dict) and blob.get("_jd_hash"))
        if isinstance(blob, dict) and blob.get("_jd_hash"):
            # El MISMO bloque que arma la ruta de análisis, o la huella no es comparable.
            from ai_routes import (_build_opportunity_context, _build_resume_target_role_block,
                                   RESUME_JD_LIMIT, _truncate_preserving_edges)
            jd_now, opp_ctx = _build_opportunity_context(cur, row["opportunity_id"])
            block_now = _build_resume_target_role_block({
                "client_name": row["client_name"],
                "position": opp_ctx.get("position", "") or (row["opp_position_name"] or ""),
                "career_country": opp_ctx.get("career_country", ""),
                "years_experience": str(opp_ctx.get("years_experience") or ""),
                "jd": _truncate_preserving_edges(jd_now, RESUME_JD_LIMIT),
            })
            jd_changed = cv_review_ai.jd_fingerprint(block_now) != blob["_jd_hash"]
    finally:
        cur.close()
        conn.close()

    payload = _serialize(row, reasons=reasons, checklist=checklist,
                         analysis=row.get("ai_analysis"), live_hash=live_hash)
    payload["resume_snapshot"] = row.get("resume_snapshot")
    payload["jd_changed"] = jd_changed
    payload["jd_checked"] = jd_checked
    return jsonify({"review": payload, "live_resume_hash": live_hash})


@bp.route("/cv_reviews/<int:review_id>/resume", methods=["GET"])
def get_cv_review_snapshot(review_id):
    """Sirve el snapshot con la misma forma que GET /resumes/<id>, así
    resume-readonly.html puede renderizar el CV tal como se envió."""
    denied = _require_active_user()
    if denied:
        return denied

    ensure_cv_review_tables()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT candidate_id, resume_snapshot FROM cv_reviews WHERE review_id = %s LIMIT 1",
            (review_id,),
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()
    if not row:
        return jsonify({"error": "review not found"}), 404
    out = dict(row["resume_snapshot"] or {})
    out["candidate_id"] = row["candidate_id"]
    return jsonify(out)


# --- decisión ---------------------------------------------------------------

@bp.route("/cv_reviews/<int:review_id>/decision", methods=["POST", "OPTIONS"])
def decide_cv_review(review_id):
    if request.method == "OPTIONS":
        return ("", 204)

    denied = _require_reviewer()
    if denied:
        return denied
    actor = _user_email()

    data = request.get_json(silent=True) or {}
    decision = (data.get("decision") or "").strip().lower()
    if decision not in ("approved", "rejected", "changes_requested"):
        return jsonify({"error": "decision must be 'approved', 'rejected' or "
                                 "'changes_requested'"}), 400

    reasons = [str(r).strip().lower() for r in (data.get("reasons") or []) if str(r).strip()]
    reasons = list(dict.fromkeys(reasons))  # dedupe, conservando el orden
    reason_other = (data.get("reason_other") or "").strip() or None
    comment = (data.get("reviewer_comment") or data.get("comment") or "").strip() or None

    # La checklist va en las TRES decisiones, no sólo en el rechazo. Las razones son sobre el
    # candidato; esto es sobre lo que la recruiter escribió mal, y el caso que hay que poder
    # registrar es justamente el CV que se APRUEBA teniendo la educación sin cargar.
    checklist = [str(c).strip().lower() for c in (data.get("checklist") or []) if str(c).strip()]
    checklist = list(dict.fromkeys(checklist))
    unknown_items = [c for c in checklist if c not in cv_review_ai.CHECKLIST_ITEM_CODES]
    if unknown_items:
        return jsonify({"error": f"unknown checklist item(s): {', '.join(unknown_items)}",
                        "code": "bad_checklist_item"}), 422
    # Tildar un ítem ya prueba que el reviewer la miró; el flag explícito existe para el caso
    # contrario, el CV limpio. Sin él, "0 defectos" y "nadie la abrió" serían la misma fila y la
    # métrica terminaría midiendo qué tan prolijo es el reviewer en vez de la recruiter — por eso
    # es el denominador y por eso es obligatorio.
    checklist_done = bool(data.get("checklist_done")) or bool(checklist)
    if not checklist_done:
        return jsonify({"error": "Go through the checklist before deciding: tick what the "
                                 "recruiter got wrong, or mark the CV as clean.",
                        "code": "no_checklist"}), 422

    if decision == "rejected":
        unknown = [r for r in reasons if r not in cv_review_ai.REJECT_REASON_CODES]
        if unknown:
            return jsonify({"error": f"unknown reason code(s): {', '.join(unknown)}",
                            "code": "bad_reason"}), 422
        if not reasons:
            return jsonify({"error": "A rejection needs at least one reason.",
                            "code": "no_reason"}), 422
        if not comment:
            return jsonify({"error": "A rejection needs a comment so the recruiter knows "
                                     "why. If the CV can be fixed, request changes "
                                     "instead.", "code": "no_comment"}), 422
        if "other" in reasons and not reason_other:
            return jsonify({"error": "Describe the 'Other' reason.",
                            "code": "no_reason_other"}), 422
    elif decision == "changes_requested":
        # Pedir cambios NO lleva razones a propósito: la lista fija existe para poder
        # medir POR QUÉ se rechaza un perfil, y esto no es un rechazo — el candidato sigue
        # en carrera y lo que falla es el documento. Encajarlo en esos códigos ensuciaría
        # el donut de razones de rechazo con casos que no lo son.
        # El comentario, en cambio, es obligatorio: es literalmente lo único que la
        # recruiter recibe, y sin él esto no le dice qué corregir.
        reasons, reason_other = [], None
        if not comment:
            return jsonify({"error": "Say what needs changing — the comment is the only "
                                     "thing the recruiter gets.", "code": "no_comment"}), 422
    else:
        reasons, reason_other = [], None

    ensure_cv_review_tables()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # UPDATE condicional, nunca SELECT-y-después-UPDATE: si dos sales leads deciden a
        # la vez, el segundo afecta 0 filas y se va con un 409 en vez de pisar el veredicto.
        cur.execute(
            """
            UPDATE cv_reviews
               SET status = %s, reviewed_by = %s, reviewed_at = NOW(),
                   reviewer_comment = %s, reject_other = %s, checklist_done = %s,
                   updated_at = NOW()
             WHERE review_id = %s AND status = 'pending'
            RETURNING """ + _SELECT_COLS.replace("r.", ""),
            (decision, actor, comment, reason_other, checklist_done, review_id),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            cur.execute(
                "SELECT " + _SELECT_COLS + " FROM cv_reviews r WHERE r.review_id = %s",
                (review_id,),
            )
            existing = cur.fetchone()
            if not existing:
                return jsonify({"error": "review not found"}), 404
            return jsonify({
                "error": "This review was already decided.",
                "code": "already_decided",
                "review": _serialize(existing),
            }), 409

        if reasons:
            cur.executemany(
                "INSERT INTO cv_review_reasons (review_id, reason_code) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                [(review_id, code) for code in reasons],
            )

        if checklist:
            cur.executemany(
                "INSERT INTO cv_review_checklist (review_id, item_code) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                [(review_id, code) for code in checklist],
            )

        batch_synced = False
        # SÓLO el rechazo, nunca "changes_requested": pedir cambios es sobre el documento y
        # el candidato sigue en carrera. Marcarlo "Rejected By Sales" lo sacaría del batch
        # por un CV mal escrito, que es justo lo que este estado existe para evitar.
        if decision == "rejected":
            # Que el donut existente siga siendo verdad. El EXISTS es lo que evita pisar
            # batches de OTRAS oportunidades del mismo candidato (misma forma que
            # accounts_routes.py:1476). Si todavía no hay batch afecta 0 filas y no pasa
            # nada: el caso normal, porque el review es pre-batch.
            cur.execute(
                """
                UPDATE candidates_batches cb
                   SET status = 'Rejected By Sales'
                 WHERE cb.candidate_id = %s
                   AND COALESCE(TRIM(cb.status), '') = ''
                   AND EXISTS (
                         SELECT 1 FROM batch b
                          WHERE b.batch_id = cb.batch_id
                            AND b.opportunity_id = %s
                   )
                """,
                (row["candidate_id"], row["opportunity_id"]),
            )
            batch_synced = cur.rowcount > 0

        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        logging.exception("cv_review decision failed")
        return jsonify({"error": "Could not store the decision."}), 500
    finally:
        cur.close()
        conn.close()

    email_sent = _notify_decided(review_id)
    return jsonify({
        "review": _serialize(row, reasons=reasons, checklist=checklist),
        "batch_synced": batch_synced,
        "email_sent": bool(email_sent),
    })


@bp.route("/cv_reviews/<int:review_id>/reopen", methods=["POST", "OPTIONS"])
def reopen_cv_review(review_id):
    """Deshacer un rechazo: la ronda vuelve a 'pending' y la recruiter puede reenviar.

    Existe porque el rechazo pasó a ser TERMINAL — bloquea la ronda siguiente. Sin una
    salida, un click en el botón equivocado deja a ese candidato fuera de esa vacante para
    siempre y la única forma de arreglarlo sería tocar la base a mano.

    Sólo sobre rechazos, y sólo el sales lead: aprobar por error no traba a nadie (la
    recruiter puede volver a mandar), así que no hace falta deshacerlo desde acá.
    """
    if request.method == "OPTIONS":
        return ("", 204)

    denied = _require_reviewer()
    if denied:
        return denied
    actor = _user_email()

    ensure_cv_review_tables()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Se limpia TODO el veredicto, no sólo el status: dejar reviewed_by y el comentario
        # de un rechazo que ya no existe haría que la ronda se lea como decidida en el
        # historial, y `cv_reviews_decided_has_reviewer` deja de exigirlos en 'pending'.
        cur.execute(
            """
            UPDATE cv_reviews
               SET status = 'pending', reviewed_by = NULL, reviewed_at = NULL,
                   reviewer_comment = NULL, reject_other = NULL, checklist_done = FALSE,
                   updated_at = NOW()
             WHERE review_id = %s AND status = 'rejected'
            RETURNING """ + _SELECT_COLS.replace("r.", ""),
            (review_id,),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            cur.execute("SELECT " + _SELECT_COLS + " FROM cv_reviews r WHERE r.review_id = %s",
                        (review_id,))
            existing = cur.fetchone()
            if not existing:
                return jsonify({"error": "review not found"}), 404
            return jsonify({
                "error": "Only a rejected round can be reopened.",
                "code": "not_rejected",
                "review": _serialize(existing),
            }), 409

        # Las razones eran de un rechazo que se está deshaciendo. Si quedaran, seguirían
        # contando en el donut de "por qué las rechazan" de una decisión que ya no existe.
        cur.execute("DELETE FROM cv_review_reasons WHERE review_id = %s", (review_id,))
        # Lo mismo con la checklist. El flag se baja arriba, en el mismo UPDATE que el resto del
        # veredicto: la ronda vuelve a 'pending', así que nadie la chequeó todavía, y si quedara
        # en TRUE el perfil entraría al denominador de "CVs limpios" sin que nadie lo mirara.
        cur.execute("DELETE FROM cv_review_checklist WHERE review_id = %s", (review_id,))
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        # El índice parcial cv_reviews_one_pending_uq: ya hay otra ronda abierta para este
        # perfil, así que ésta no puede volver a 'pending'.
        if isinstance(exc, pg_errors.UniqueViolation):
            return jsonify({
                "error": "There is already an open round for this candidate on this "
                         "vacancy, so this one cannot be reopened.",
                "code": "already_pending"}), 409
        logging.exception("cv_review reopen failed")
        return jsonify({"error": "Could not reopen the review."}), 500
    finally:
        cur.close()
        conn.close()

    logging.info("cv_review: %s reabrió el rechazo del review %s", actor, review_id)
    return jsonify({"review": _serialize(row)})


@bp.route("/cv_reviews/<int:review_id>/cancel", methods=["POST", "OPTIONS"])
def cancel_cv_review(review_id):
    """Retirar una ronda pendiente sin quemar un rechazo (se eligió la opp equivocada, la
    recruiter ya lo arregló sola). Las canceladas quedan fuera de todas las métricas."""
    if request.method == "OPTIONS":
        return ("", 204)

    denied = _require_actor()
    if denied:
        return denied
    actor = _user_email()

    ensure_cv_review_tables()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """
            UPDATE cv_reviews SET status = 'cancelled', updated_at = NOW()
             WHERE review_id = %s AND status = 'pending'
               AND (LOWER(TRIM(recruiter_email)) = %s OR %s = ANY(%s))
            RETURNING """ + _SELECT_COLS.replace("r.", ""),
            (review_id, actor, actor, list(REVIEW_OVERRIDE_EMAILS)),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return jsonify({
                "error": "Only the recruiter who submitted it can cancel a pending review.",
                "code": "cannot_cancel",
            }), 409
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return jsonify({"review": _serialize(row)})


# --- re-score ---------------------------------------------------------------

@bp.route("/cv_reviews/<int:review_id>/analyze", methods=["POST", "OPTIONS"])
def analyze_cv_review(review_id):
    """Re-corre el score sobre el SNAPSHOT, nunca sobre el resume vivo: si re-scoreara el
    CV actual, volver a correr una ronda cambiaría una métrica histórica."""
    if request.method == "OPTIONS":
        return ("", 204)

    denied = _require_actor()
    if denied:
        return denied

    ensure_cv_review_tables()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """
            SELECT r.review_id, r.candidate_id, r.opportunity_id, r.resume_snapshot,
                   r.resume_hash, r.ai_analysis, r.ai_analyzed_at, r.ai_score,
                   c.cv_pdf_scrapper, c.affinda_scrapper,
                   c.linkedin_scrapper, c.coresignal_scrapper,
                   o.opp_position_name, COALESCE(a.client_name, '') AS client_name
            FROM cv_reviews r
            LEFT JOIN candidates c  ON c.candidate_id   = r.candidate_id
            LEFT JOIN opportunity o ON o.opportunity_id = r.opportunity_id
            LEFT JOIN account a     ON a.account_id     = o.account_id
            WHERE r.review_id = %s LIMIT 1
            """,
            (review_id,),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "review not found"}), 404

        from ai_routes import _build_resume_target_role_block, _build_opportunity_context
        from ai_routes import RESUME_JD_LIMIT, _truncate_preserving_edges
        jd_plain, opp_ctx = _build_opportunity_context(cur, row["opportunity_id"])
        if not (jd_plain or "").strip():
            return jsonify({
                "error": f"Opportunity #{row['opportunity_id']} has no job description, "
                         "so a quality score would be meaningless.",
                "code": "no_jd",
            }), 422
        jd_block = _build_resume_target_role_block({
            "client_name": row["client_name"],
            "position": opp_ctx.get("position", "") or (row["opp_position_name"] or ""),
            "career_country": opp_ctx.get("career_country", ""),
            "years_experience": str(opp_ctx.get("years_experience") or ""),
            "jd": _truncate_preserving_edges(jd_plain, RESUME_JD_LIMIT),
        })
    finally:
        cur.close()
        conn.close()

    snapshot = row["resume_snapshot"] or {}
    source_text = cv_review_ai.build_source_text(row)
    fingerprint = cv_review_ai.input_hash({
        "s": row["resume_hash"], "j": jd_block,
        "src": cv_review_ai.input_hash(source_text),
        "v": cv_review_ai.ANALYSIS_VERSION,
    })

    # Guarda barata contra el doble click: mismas entradas, scoreado hace segundos.
    previous = row.get("ai_analysis") or {}
    if previous.get("_input_hash") == fingerprint and row.get("ai_analyzed_at"):
        age = time.time() - row["ai_analyzed_at"].timestamp()
        if age < cv_review_ai.COOLDOWN_SECONDS:
            return jsonify({"ai_score": row["ai_score"], "ai_analysis": previous,
                            "cached": True})

    score, analysis, ai_error = cv_review_ai.score_cv(
        snapshot=snapshot, jd_block=jd_block, source_text=source_text,
        fingerprint=fingerprint,
    )
    if ai_error == "budget":
        return jsonify({"error": "The OpenAI budget for this month is exhausted.",
                        "code": "budget"}), 503
    if ai_error:
        return jsonify({"error": "The AI analysis failed. Try again.",
                        "code": ai_error}), 502

    _store_analysis(review_id, score, analysis, None)
    return jsonify({"ai_score": score, "ai_analysis": analysis, "cached": False})


# --- métricas ---------------------------------------------------------------
#
# La unidad es el PERFIL (candidate_id, opportunity_id), no la ronda. Si el denominador
# fueran rondas, una recruiter que re-envía cuatro veces tendría MENOR tasa de rechazo que
# una que acertó en el segundo intento: la métrica premiaría el churn. Y la frase que pidió
# el owner es "de 20 PERFILES que se mandaron".
#
# Cada perfil se imputa al período de su PRIMER envío, no al de su decisión: "perfiles
# mandados en Julio" es una afirmación sobre la producción de Julio de la recruiter. La
# consecuencia hay que mostrarla en la UI: el número de Julio se sigue moviendo hasta que
# se decida el backlog de Julio, así que los porcentajes van sobre profiles_decided y no
# sobre profiles_sent (un ratio sobre lo enviado la favorecería sólo porque el sales lead
# está atrasado).
#
# "La calidad de la recruiter" es el score de la PRIMERA ronda. La ronda 2 es calidad
# después del coaching; puntuar eso borraría justo lo que se quiere medir.

# ---------------------------------------------------------------------------
# PISO DE LAS MÉTRICAS. Nada anterior a esta fecha cuenta en /cv_reviews/metrics.
#
# Por qué existe: la checklist y la rúbrica de coverage llegaron después de que la feature
# ya estuviera en uso. Todo lo decidido antes no tiene checklist (era imposible tenerla) y
# fue scoreado con rúbricas viejas. Mezclarlo con lo nuevo hunde los números de todas las
# recruiters por igual y hace que la métrica mida CUÁNDO se usó la herramienta en vez de
# cómo trabaja cada una.
#
# Se aplica clampeando el piso de la ventana, NO como un filtro aparte: así el scope, las
# razones de rechazo y la checklist quedan consistentes entre sí sin poder desincronizarse.
# Afecta las DOS pantallas que consumen este endpoint (el panel "Per recruiter" de CV Review
# y la pestaña CV quality de Recruiter Power), que es lo que se decidió.
#
# PARA MOVERLA: cambiá esta sola línea. Si algún día no hace falta más, poné date(1900, 1, 1).
METRICS_FROM = date(1900, 1, 1)

_METRICS_CTES = """
live AS (
    -- Las rondas canceladas nunca pasaron.
    SELECT r.*
    FROM cv_reviews r
    JOIN opportunity o  ON o.opportunity_id = r.opportunity_id
    LEFT JOIN account a ON a.account_id     = o.account_id
    WHERE r.status <> 'cancelled'
      AND COALESCE(a.vintti_internal, FALSE) = FALSE
),
first_sub AS (
    -- El envío que define el perfil.
    SELECT DISTINCT ON (candidate_id, opportunity_id)
           candidate_id, opportunity_id, review_id, recruiter_email,
           sales_lead_email, requested_at, ai_score, ai_analysis
    FROM live
    ORDER BY candidate_id, opportunity_id, requested_at, review_id
),
first_dec AS (
    -- La primera ronda que efectivamente recibió un veredicto.
    SELECT DISTINCT ON (candidate_id, opportunity_id)
           candidate_id, opportunity_id, review_id AS decided_review_id, status, reviewed_at,
           checklist_done,
           -- El EXISTS va ACÁ y no como JOIN en el agregado a propósito: un perfil con dos
           -- ítems tildados tiene que sumar UNO al denominador, no dos. Colapsarlo a un
           -- booleano por perfil antes de agregar es lo que lo garantiza.
           EXISTS (SELECT 1 FROM cv_review_checklist ck
                    WHERE ck.review_id = live.review_id) AS flagged
    FROM live
    -- "changes_requested" cierra la ronda igual que las otras dos, así que cuenta como
    -- decidido: si no, un perfil devuelto para corregir quedaría para siempre en
    -- "pendiente" y le inflaría el backlog a la recruiter que ya hizo su parte.
    WHERE status IN ('approved', 'rejected', 'changes_requested')
    ORDER BY candidate_id, opportunity_id, requested_at, review_id
),
scope AS (
    SELECT f.*, rc.label AS recruiter_label
    FROM first_sub f
    JOIN recruiters rc ON rc.email = LOWER(TRIM(f.recruiter_email))
    -- Misma zona horaria que window_bounds (today_ar, UTC-3), para que la página nueva y
    -- las futuras tarjetas del dashboard den el mismo número.
    WHERE (f.requested_at AT TIME ZONE 'America/Argentina/Buenos_Aires')::date
            BETWEEN %(w_lo)s AND %(w_hi)s
      AND (%(recruiter)s = '' OR LOWER(TRIM(f.recruiter_email)) = %(recruiter)s)
      -- Acota la métrica a las oportunidades de un sales lead. Se compara contra el
      -- SNAPSHOT que guardó el review, no contra opportunity.opp_sales_lead de hoy: si la
      -- oportunidad cambia de dueño, los números del mes pasado no se tienen que mover.
      AND (%(sales_lead)s = '' OR LOWER(TRIM(COALESCE(f.sales_lead_email, ''))) = %(sales_lead)s)
)
"""


def _pct(numerator, denominator):
    if not denominator:
        return None
    return round(100.0 * numerator / denominator, 1)


@bp.route("/cv_reviews/metrics", methods=["GET"])
def cv_review_metrics():
    """Las métricas también las mira la recruiter en Recruiter Power, no sólo el sales lead.

    Por eso el gate es _require_actor y no _require_reviewer: quien NO es reviewer queda
    acotado a SU propia fila en el servidor, ignorando el ?recruiter= que haya mandado. En
    Recruiter Power eso ya pasa, pero sólo en el cliente (isRestrictedEmail en
    recruiter-power.js); acá queda hecho donde no se puede saltear con la consola.
    """
    denied = _require_actor()
    if denied:
        return denied

    ensure_cv_review_tables()

    from dashboards.datasets._periods import window_bounds
    from dashboards.datasets._recruiters import RECRUITERS_CTE

    lo, hi = window_bounds(request.args.to_dict())
    # El piso gana siempre, aunque pidan un rango que empiece antes.
    clamped = lo < METRICS_FROM
    if clamped:
        lo = METRICS_FROM
    # El rango pedido termina ANTES del piso: no hay nada que medir. La query devuelve 0 igual
    # (lo > hi no matchea nada), pero sin este flag el meta reporta una ventana invertida
    # —"2026-09-01 → 2026-08-27"— y la UI la pinta tal cual, que se lee como un bug.
    window_empty = lo > hi
    # `mine=1` acota a las oportunidades de quien mira, igual que en la cola, para que la
    # métrica y la lista de abajo no cuenten universos distintos.
    sales_lead = (request.args.get("sales_lead") or "").strip().lower()
    if request.args.get("mine") == "1":
        sales_lead = _user_email() or sales_lead

    recruiter = (request.args.get("recruiter") or "").strip().lower()
    me = _user_email()
    is_reviewer = me in REVIEW_OVERRIDE_EMAILS or me in _sales_lead_emails()
    if not is_reviewer:
        # Se PISA el parámetro, no se valida: así no hay forma de pedir la fila de otra.
        recruiter = me or ""
        sales_lead = ""

    params = {
        "w_lo": lo, "w_hi": hi,
        "recruiter": recruiter,
        "sales_lead": sales_lead,
        # ->> devuelve texto, así que la versión viaja como texto.
        "ai_version": str(cv_review_ai.ANALYSIS_VERSION),
    }

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "WITH " + RECRUITERS_CTE + ", " + _METRICS_CTES + """
            SELECT
                s.recruiter_email,
                s.recruiter_label,
                COUNT(*)                                       AS profiles_sent,
                COUNT(d.decided_review_id)                     AS profiles_decided,
                COUNT(*) - COUNT(d.decided_review_id)          AS profiles_pending,
                COUNT(*) FILTER (WHERE d.status = 'rejected')  AS rejected_first_try,
                COUNT(*) FILTER (WHERE d.status = 'approved')  AS approved_first_try,
                COUNT(*) FILTER (WHERE d.status = 'changes_requested')
                                                               AS changes_first_try,
                -- Denominador de TODO lo de checklist. No es profiles_decided: los perfiles
                -- decididos antes de que la checklist existiera tienen checklist_done=false y
                -- quedan afuera, que es lo correcto — nadie los chequeó. La UI muestra el n.
                COUNT(*) FILTER (WHERE d.checklist_done)        AS profiles_checklisted,
                COUNT(*) FILTER (WHERE d.checklist_done AND NOT d.flagged)
                                                               AS profiles_clean,
                -- Dos exclusiones del promedio de calidad, por la misma razón: mezclar
                -- escalas distintas corrompe el número.
                --   1) los scores parciales (sin JD, así que jd_alignment, que pesa 30
                --      puntos, se cayó): un 82 sin JD no es comparable con un 41 con JD.
                --   2) los scoreados con una VERSION VIEJA del prompt: el mismo CV dio
                --      55, 57 y 65 en v1, v2 y v3. Si se promedian juntos, la "calidad"
                --      de una recruiter sube o baja porque cambiamos el prompt, no porque
                --      ella trabajara distinto — y esto se usa para evaluar gente.
                -- OJO: en este SQL no puede haber un signo de porcentaje suelto, ni
                -- siquiera adentro de un comentario. psycopg2 escanea el string entero y
                -- cualquiera que no sea un placeholder con nombre revienta la query con
                -- "argument formats can't be mixed". Escribí "por ciento" en palabras.
                COUNT(s.ai_score) FILTER (
                    WHERE COALESCE(s.ai_analysis->>'_partial', 'false') <> 'true'
                      AND COALESCE(s.ai_analysis->>'_version', '0') = %(ai_version)s
                )                                              AS quality_n,
                ROUND(AVG(s.ai_score) FILTER (
                    WHERE COALESCE(s.ai_analysis->>'_partial', 'false') <> 'true'
                      AND COALESCE(s.ai_analysis->>'_version', '0') = %(ai_version)s
                ), 1)                                          AS quality_avg,
                COUNT(*) FILTER (WHERE s.ai_score IS NULL)     AS unscored_profiles,
                -- Cuántos quedaron afuera por versión vieja. Se reporta SIEMPRE: si no,
                -- "calidad 65 (n=3)" esconde que otros 17 perfiles tienen score y no se
                -- están contando, y eso se lee como si no existieran.
                COUNT(*) FILTER (
                    WHERE s.ai_score IS NOT NULL
                      AND COALESCE(s.ai_analysis->>'_version', '0') <> %(ai_version)s
                )                                              AS stale_version_profiles
            FROM scope s
            LEFT JOIN first_dec d
                   ON d.candidate_id = s.candidate_id AND d.opportunity_id = s.opportunity_id
            GROUP BY 1, 2
            ORDER BY 2
            """,
            params,
        )
        rows = [dict(r) for r in cur.fetchall()]

        cur.execute(
            "WITH " + RECRUITERS_CTE + ", " + _METRICS_CTES + """
            SELECT s.recruiter_email, rr.reason_code, COUNT(*) AS profiles
            -- Ya es una fila por (perfil, razón): lo garantiza el PK de cv_review_reasons.
            FROM scope s
            JOIN first_dec d          ON d.candidate_id = s.candidate_id
                                     AND d.opportunity_id = s.opportunity_id
            JOIN cv_review_reasons rr ON rr.review_id = d.decided_review_id
            WHERE d.status = 'rejected'
            GROUP BY 1, 2
            ORDER BY 1, 3 DESC
            """,
            params,
        )
        reason_rows = [dict(r) for r in cur.fetchall()]

        # Calcada de la de razones: una fila por (perfil, ítem), garantizado por el PK de
        # cv_review_checklist. A diferencia de aquélla NO se filtra por status — un CV se
        # aprueba con defectos y ése es justo el caso que hay que contar.
        cur.execute(
            "WITH " + RECRUITERS_CTE + ", " + _METRICS_CTES + """
            SELECT s.recruiter_email, ck.item_code, COUNT(*) AS profiles
            FROM scope s
            JOIN first_dec d            ON d.candidate_id = s.candidate_id
                                       AND d.opportunity_id = s.opportunity_id
            JOIN cv_review_checklist ck ON ck.review_id = d.decided_review_id
            GROUP BY 1, 2
            ORDER BY 1, 3 DESC
            """,
            params,
        )
        checklist_rows = [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

    labels = dict(cv_review_ai.REJECT_REASONS)
    by_recruiter = {}
    for r in reason_rows:
        by_recruiter.setdefault(r["recruiter_email"], []).append({
            "reason_code": r["reason_code"],
            "reason_label": labels.get(r["reason_code"], r["reason_code"]),
            "profiles": r["profiles"],
        })

    item_labels = dict(cv_review_ai.CHECKLIST_ITEMS)
    checklist_by_recruiter = {}
    for r in checklist_rows:
        checklist_by_recruiter.setdefault(r["recruiter_email"], []).append({
            "item_code": r["item_code"],
            "item_label": item_labels.get(r["item_code"], r["item_code"]),
            "profiles": r["profiles"],
        })

    out_rows = []
    for r in rows:
        decided = r["profiles_decided"]
        reasons = by_recruiter.get(r["recruiter_email"], [])
        for item in reasons:
            item["pct"] = _pct(item["profiles"], decided)
        # Los ítems van sobre profiles_checklisted, NO sobre decided: mezclarlos daría un
        # porcentaje diluido por los perfiles que nadie chequeó.
        checklisted = r["profiles_checklisted"]
        checklist = checklist_by_recruiter.get(r["recruiter_email"], [])
        for item in checklist:
            item["pct"] = _pct(item["profiles"], checklisted)
        out_rows.append({
            **r,
            "quality_avg": float(r["quality_avg"]) if r["quality_avg"] is not None else None,
            "rejected_first_try_pct": _pct(r["rejected_first_try"], decided),
            "approved_first_try_pct": _pct(r["approved_first_try"], decided),
            "changes_first_try_pct": _pct(r["changes_first_try"], decided),
            "reasons": reasons,
            "checklist": checklist,
            "clean_pct": _pct(r["profiles_clean"], checklisted),
            # Cobertura de la checklist. Se reporta SIEMPRE por el mismo motivo que
            # stale_version_profiles: sin esto, "80 por ciento limpios (n=5)" esconde que
            # había 40 perfiles decididos y 35 sin chequear.
            "checklisted_pct": _pct(checklisted, decided),
        })

    totals = {
        "profiles_sent": sum(r["profiles_sent"] for r in rows),
        "profiles_decided": sum(r["profiles_decided"] for r in rows),
        "profiles_pending": sum(r["profiles_pending"] for r in rows),
        "rejected_first_try": sum(r["rejected_first_try"] for r in rows),
        "approved_first_try": sum(r["approved_first_try"] for r in rows),
        "changes_first_try": sum(r["changes_first_try"] for r in rows),
        "quality_n": sum(r["quality_n"] for r in rows),
        "stale_version_profiles": sum(r["stale_version_profiles"] for r in rows),
        "profiles_checklisted": sum(r["profiles_checklisted"] for r in rows),
        "profiles_clean": sum(r["profiles_clean"] for r in rows),
    }
    weighted = sum(
        float(r["quality_avg"]) * r["quality_n"] for r in rows if r["quality_avg"] is not None
    )
    totals["quality_avg"] = round(weighted / totals["quality_n"], 1) if totals["quality_n"] else None
    totals["clean_pct"] = _pct(totals["profiles_clean"], totals["profiles_checklisted"])
    totals["checklisted_pct"] = _pct(totals["profiles_checklisted"], totals["profiles_decided"])
    # El desglose global se suma de las filas en vez de re-consultarse: es la misma agregación
    # y así no puede divergir de lo que ve cada recruiter.
    totals_checklist = {}
    for r in checklist_rows:
        entry = totals_checklist.setdefault(r["item_code"], {
            "item_code": r["item_code"],
            "item_label": item_labels.get(r["item_code"], r["item_code"]),
            "profiles": 0,
        })
        entry["profiles"] += r["profiles"]
    for entry in totals_checklist.values():
        entry["pct"] = _pct(entry["profiles"], totals["profiles_checklisted"])
    totals["checklist"] = sorted(totals_checklist.values(),
                                 key=lambda e: e["profiles"], reverse=True)
    totals["rejected_first_try_pct"] = _pct(totals["rejected_first_try"], totals["profiles_decided"])
    totals["approved_first_try_pct"] = _pct(totals["approved_first_try"], totals["profiles_decided"])
    totals["changes_first_try_pct"] = _pct(totals["changes_first_try"], totals["profiles_decided"])

    return jsonify({
        "rows": out_rows,
        "totals": totals,
        "by_reason": reason_rows,
        "meta": {
            "desde": lo.isoformat(),
            "hasta": hi.isoformat(),
            # Un rechazo puede llevar varias razones, así que estos porcentajes suman más
            # de 100. La UI TIENE que decirlo o el primero que los sume abre un bug.
            "reasons_are_not_exclusive": True,
            "denominator": "profiles_decided",
            # Un CV puede tener tres defectos, así que estos porcentajes también suman más de
            # 100. Y su denominador NO es el mismo que el de las razones: hay que decir las dos
            # cosas o el primero que los sume abre un bug.
            "checklist_is_not_exclusive": True,
            "checklist_denominator": "profiles_checklisted",
            # Para que la UI pueda decir "estás viendo sólo lo tuyo" en vez de dejar creer
            # que la recruiter está mirando al equipo entero.
            "scoped_to_self": not is_reviewer,
            # Sin esto, "0 sent" en un rango que el usuario eligió a mano se lee como que la
            # pantalla está rota, en vez de como que no hay datos todavía.
            "metrics_from": METRICS_FROM.isoformat(),
            "window_clamped": clamped,
            "window_empty": window_empty,
            # La calidad promedio SÓLO cuenta análisis de esta versión del prompt. Las
            # razones de rechazo no se filtran: son decisiones humanas y no dependen de
            # la IA.
            "ai_version": cv_review_ai.ANALYSIS_VERSION,
            "quality_is_version_scoped": True,
            # Vacío = todas las oportunidades. La UI lo usa para decir qué está mostrando.
            "sales_lead": sales_lead,
        },
    })


# --- emails ----------------------------------------------------------------

def _review_email_context(review_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT " + _SELECT_COLS + """,
                   r.ai_analysis,
                   c.name AS candidate_name,
                   o.opp_position_name, COALESCE(a.client_name, 'Client') AS client_name,
                   -- Con qué marca sale el CV de esta vacante: el sales lead que aprueba y
                   -- reenvía tiene que saber qué va a ver el cliente al abrir el link.
                   COALESCE(a.vintti_ai, FALSE) AS vintti_ai
            FROM cv_reviews r
            LEFT JOIN candidates c  ON c.candidate_id   = r.candidate_id
            LEFT JOIN opportunity o ON o.opportunity_id = r.opportunity_id
            LEFT JOIN account a     ON a.account_id     = o.account_id
            WHERE r.review_id = %s LIMIT 1
            """,
            (review_id,),
        )
        row = cur.fetchone()
        reasons = _load_reasons(cur, [review_id]).get(review_id, []) if row else []
    finally:
        cur.close()
        conn.close()
    return row, reasons


def _review_email_contexts(review_ids):
    """Lo mismo que _review_email_context pero para varios, en UNA sola conexión.

    Llamar al singular en un loop abría una conexión a RDS por candidato. Con
    max_connections=81 y sin pool, N conexiones seguidas desde un hilo de fondo es
    exactamente el tipo de presión que ya tumbó la base una vez.
    Devuelve las filas en el mismo orden que review_ids.
    """
    if not review_ids:
        return []
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT " + _SELECT_COLS + """,
                   r.ai_analysis,
                   c.name AS candidate_name,
                   o.opp_position_name, COALESCE(a.client_name, 'Client') AS client_name,
                   -- Con qué marca sale el CV de esta vacante: el sales lead que aprueba y
                   -- reenvía tiene que saber qué va a ver el cliente al abrir el link.
                   COALESCE(a.vintti_ai, FALSE) AS vintti_ai
            FROM cv_reviews r
            LEFT JOIN candidates c  ON c.candidate_id   = r.candidate_id
            LEFT JOIN opportunity o ON o.opportunity_id = r.opportunity_id
            LEFT JOIN account a     ON a.account_id     = o.account_id
            WHERE r.review_id = ANY(%s)
            """,
            (list(review_ids),),
        )
        by_id = {r["review_id"]: r for r in cur.fetchall()}
    finally:
        cur.close()
        conn.close()
    return [by_id[rid] for rid in review_ids if rid in by_id]


def _brand_chip(row):
    """Chip 'Vintti AI' al lado del cliente en los mails internos.

    El CV que abre el cliente sale con la marca de la cuenta de esta vacante, y el mismo
    candidato puede estar en un proceso de Vintti AI y en otro de Vintti normal. Quien
    aprueba y reenvía el borrador necesita saber qué va a ver el cliente; sin esto, el
    mail no lo dice por ningún lado. Violeta de marca (#5c6af7), igual que el CV.
    """
    if not (row or {}).get("vintti_ai"):
        return ""
    return ('<span style="display:inline-block;margin-left:8px;padding:2px 9px;'
            'border-radius:999px;background:#eceefe;color:#2f3a86;'
            'font-weight:700;font-size:11px;">Vintti AI</span>')


def _review_cta_block(review_id, title, body):
    """profile_cta_block apunta al perfil del candidato; el reviewer necesita la cola."""
    from routes.public_reference_feedback_routes import _escape_html
    url = f"https://vinttihub.vintti.com/cv-review.html?review_id={review_id}"
    return f"""
    <div style="margin:0 0 20px;padding:18px 20px;border-radius:16px;
                background:#eef2ff;border:1px solid #c7d2fe;">
      <div style="font-size:16px;font-weight:800;color:#312e81;margin-bottom:6px;">
        {_escape_html(title)}
      </div>
      <div style="color:#3730a3;margin-bottom:14px;">{_escape_html(body)}</div>
      <a href="{url}" style="display:inline-block;padding:11px 20px;border-radius:12px;
         background:#4f46e5;color:#ffffff;text-decoration:none;font-weight:700;font-size:14px;">
        Open the CV review →
      </a>
    </div>
    """


# Un score en None NO significa una sola cosa, y decir "No JD to score against" para todas
# fue una mentira que llegó a los mails: la vacante 771 (BDR) SÍ tenía JD, y bien larga —
# lo que no tenía era un solo requisito técnico obligatorio, porque el "Requirements
# (Must-Haves)" listaba tres soft skills y todo lo demás (BDR/SDR, CRM, lead generation)
# estaba abajo, en "Nice-to-Haves", que no se puntúa a propósito.
# El sales lead leyó "no hay JD", fue a mirar, y la JD estaba. Cada motivo dice el suyo.
_NO_SCORE_PILL = {
    "no_jd": "No JD on that opportunity",
    "no_requirements": "JD has no requirements list",
    "no_scorable_requirements": "JD asks for nothing technical",
    "budget": "Not scored — AI budget spent",
}


def _score_pill(score, summary=None, basis=None, error=None):
    """El pill del mail. Lleva la fracción además del número: con pocos requisitos el score
    salta de a tramos grandes, y "2 of 3" explica el 67 mejor que el 67 solo."""
    if score is None:
        label = _NO_SCORE_PILL.get(error or basis)
        if label is None:
            # Cualquier otro ai_error (failed / truncated / unparseable) es un problema
            # nuestro, no de la vacante. No se le echa la culpa a la JD.
            label = "Not scored" if error else "No score"
        # Sin escapar a propósito: `label` sale siempre de _NO_SCORE_PILL o de dos
        # literales de acá al lado, nunca de la base ni del modelo. (_escape_html en este
        # módulo se importa adentro de cada función, no existe a nivel de módulo.)
        return ('<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
                'background:#eceff5;color:#50607f;font-weight:700;font-size:12px;">'
                f'{label}</span>')
    # Lima de marca para lo bueno, ámbar para el medio, rojo para lo flojo.
    bg, fg = ("#c1ff72", "#3a6b00") if score >= 75 else \
             ("#ffe4a3", "#7a5200") if score >= 50 else ("#ffd9d9", "#a01111")
    n = (summary or {}).get("scorable")
    shown = (summary or {}).get("described")
    frac = f"{shown} of {n} · " if n else ""
    return (f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
            f'background:{bg};color:{fg};font-weight:700;font-size:12px;">'
            f'JD coverage {frac}{score}/100</span>')


# Chequeo deliberadamente laxo: sólo queremos descartar lo que NO es una dirección, no
# validar RFC 5322. Alcanza con exigir algo@algo.tld sin espacios.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def _as_email(value):
    """Devuelve el mail normalizado, o None si eso no es una dirección.

    `opportunity.opp_sales_lead` es texto libre y a veces guarda el placeholder del
    desplegable ("select sales lead"). SendGrid rechaza el mensaje COMPLETO si un solo
    destinatario es inválido, así que una opp con ese campo mal escrito hacía que NADIE
    recibiera el mail — ni el sales lead ni la supervisión, en silencio.
    """
    v = str(value or "").strip().lower()
    if not v:
        return None
    if not _EMAIL_RE.match(v):
        logging.warning("cv_review: %r no es una dirección de mail; se descarta", v)
        return None
    return v


def clean_emails(values):
    """Normaliza, descarta lo que no es mail y deduplica conservando el orden."""
    return list(dict.fromkeys(e for e in (_as_email(v) for v in values) if e))


def submitted_recipients(row):
    """Quién se entera de que hay un CV para revisar.

    Cada sales lead recibe SÓLO los CVs de sus oportunidades; el par de supervisión
    (OVERSIGHT_EMAILS) recibe TODOS.

    `opp_sales_lead` es texto libre: puede estar vacío o tener basura. Si de ahí saliera una
    lista vacía el review sería invisible y el gate no serviría de nada, así que la
    supervisión va SIEMPRE, y sin un sales lead usable se suma el hr_lead para que al menos
    alguien del proceso lo vea.
    """
    recipients = []
    sales_lead = _as_email(row.get("sales_lead_email"))
    hr_lead = _as_email(row.get("hr_lead_email"))
    if sales_lead:
        recipients.append(sales_lead)
    elif hr_lead:
        recipients.append(hr_lead)
    recipients.extend(OVERSIGHT_EMAILS)
    # dict.fromkeys en vez de set() para no perder el orden: el sales lead va primero.
    return clean_emails(recipients)


def _notify_submitted(review_id):
    from routes.public_reference_feedback_routes import _escape_html, _send_email
    row, _ = _review_email_context(review_id)
    if not row:
        return False

    recipients = submitted_recipients(row)
    # Vacío o con basura da igual: en los dos casos no hay a quién rutear.
    orphan = not _as_email(row.get("sales_lead_email"))
    orphan_note = ('<p style="padding:12px 16px;background:#fff4dc;border-left:5px solid '
                   '#e0a300;border-radius:12px;color:#6b4700;font-weight:700;">'
                   '⚠️ This opportunity has no usable sales lead on file, so there was nobody '
                   'to route this to. Assign one on the opportunity, or review it yourself.</p>'
                   ) if orphan else ''

    analysis = row.get("ai_analysis") or {}
    # Un pill de dos palabras no alcanza para explicar por qué no hay número: el sales lead
    # abre el mail, ve que falta el score y no sabe si se rompió algo o si la vacante está
    # mal escrita. Esto último es accionable y por eso se dice acá, no sólo en el panel.
    no_score_note = ""
    if row.get("ai_score") is None and not row.get("ai_error"):
        basis = analysis.get("_score_basis")
        if basis == "no_scorable_requirements":
            no_score_note = (
                'There is a job description, but everything it lists under its required '
                'section is a soft skill, so there is nothing technical to measure this CV '
                'against. If this posting has real must-haves, they are sitting under '
                '“Nice to have” — move them up and score it again.')
        elif basis == "no_requirements":
            no_score_note = (
                'There is a job description, but no requirements list could be read from '
                'it, so there is nothing to measure this CV against.')
    if no_score_note:
        no_score_note = ('<p style="padding:12px 16px;background:#eef2ff;border-left:5px '
                         'solid #4f46e5;border-radius:12px;color:#312e81;">'
                         f'{no_score_note}</p>')
    fixes = analysis.get("fixes") or []
    fixes_html = "".join(
        f"<li><b>{_escape_html(f.get('section') or '')}</b>: {_escape_html(f.get('fix') or '')}</li>"
        for f in fixes[:3]
    )
    unsupported = analysis.get("unsupported_claims") or []
    warn = ""
    if any(c.get("severity") == "hard" for c in unsupported):
        warn = ('<p style="padding:12px 16px;background:#ffeaea;border-left:5px solid #d84343;'
                'border-radius:12px;color:#8f0f0f;font-weight:700;">'
                "⚠️ The AI flagged claims in this CV that the candidate's own CV and "
                'LinkedIn do not support. Check them before this goes out.</p>')
    # Eco de JD: ámbar, no rojo. No es invención, es redacción calcada — pero si sale así
    # el cliente lee su propio aviso de vuelta, así que tiene que verse antes de abrir.
    echo = analysis.get("jd_echo") or []
    if echo:
        warn += (f'<p style="padding:12px 16px;background:#fff4dc;border-left:5px solid '
                 f'#e0a300;border-radius:12px;color:#6b4700;font-weight:700;">'
                 f'📋 {len(echo)} line(s) in this CV reuse the job description almost word '
                 f'for word. Aligning with the JD is fine; copying its sentences means the '
                 f'client reads their own posting back as this candidate\'s experience.</p>')

    html = f"""
    <div style="font-family:Arial,sans-serif;color:#172036;line-height:1.5;">
      <h2 style="margin:0 0 12px;">CV ready for your review</h2>
      <p style="margin:0 0 6px;"><b>Candidate:</b> {_escape_html(row['candidate_name'] or '—')}</p>
      <p style="margin:0 0 6px;"><b>Position:</b> {_escape_html(row['opp_position_name'] or '—')}</p>
      <p style="margin:0 0 6px;"><b>Client:</b> {_escape_html(row['client_name'] or '—')}{_brand_chip(row)}</p>
      <p style="margin:0 0 6px;"><b>Recruiter:</b> {_escape_html(row['recruiter_email'] or '—')}</p>
      <p style="margin:0 0 16px;"><b>Round:</b> {row['round']} &nbsp; {_score_pill(row.get('ai_score'), (row.get('ai_analysis') or {}).get('_requirements_summary'), (row.get('ai_analysis') or {}).get('_score_basis'), row.get('ai_error'))}</p>
      {orphan_note}
      {no_score_note}
      {warn}
      {f'<p style="margin:0 0 6px;"><b>Note from the recruiter:</b> {_escape_html(row["recruiter_note"])}</p>' if row.get('recruiter_note') else ''}
      {f'<p style="margin:0 0 6px;"><b>Top AI suggestions:</b></p><ul>{fixes_html}</ul>' if fixes_html else ''}
      {_review_cta_block(review_id, '✅ Decide on this CV',
                         'The score is the match between this CV and the posting, not a verdict — '
                         'read the CV, then approve it, request changes if the document can be '
                         'fixed, or reject it if the candidate is not right for this opening.')}
    </div>
    """
    subject = (f"CV to review – {row['candidate_name'] or 'Candidate'} • "
               f"{row['opp_position_name'] or 'Opportunity'}")
    return _send_email(subject, html, recipients)


def _batch_cta_block(opportunity_id, title, body):
    """Como _review_cta_block pero apunta a la cola filtrada por oportunidad, porque un
    batch son N reviews y no tiene sentido abrir uno solo."""
    from routes.public_reference_feedback_routes import _escape_html
    url = f"https://vinttihub.vintti.com/cv-review.html?opportunity_id={opportunity_id}"
    return f"""
    <div style="margin:0 0 20px;padding:18px 20px;border-radius:16px;
                background:#eef2ff;border:1px solid #c7d2fe;">
      <div style="font-size:16px;font-weight:800;color:#312e81;margin-bottom:6px;">
        {_escape_html(title)}
      </div>
      <div style="color:#3730a3;margin-bottom:14px;">{_escape_html(body)}</div>
      <a href="{url}" style="display:inline-block;padding:11px 20px;border-radius:12px;
         background:#4f46e5;color:#ffffff;text-decoration:none;font-weight:700;font-size:14px;">
        Review these CVs →
      </a>
    </div>
    """


# El borrador al cliente sale de un contenteditable, así que se limpia antes de reenviarlo
# adentro de otro mail. No es desconfianza del equipo: un <style> o un <script> pegados sin
# querer desde Word o Google Docs rompen el render en varios clientes de correo.
_DRAFT_LIMIT = 20000
_DRAFT_PAIRED = re.compile(
    r"<\s*(script|style|iframe|object|embed|title)\b[^>]*>.*?<\s*/\s*\1\s*>",
    re.I | re.S,
)
_DRAFT_LONE = re.compile(
    r"<\s*/?\s*(script|style|iframe|object|embed|link|meta|base|form|input|title)\b[^>]*>",
    re.I,
)
_DRAFT_ON_ATTR = re.compile(r"""\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", re.I)
_DRAFT_JS_URL = re.compile(r"""\b(href|src)\s*=\s*("|')?\s*javascript:[^"'>\s]*("|')?""", re.I)


def _sanitize_client_draft(html):
    """Deja el borrador listo para viajar adentro del mail de review."""
    raw = str(html or "").strip()
    if not raw:
        return ""
    clean = _DRAFT_PAIRED.sub("", raw)
    clean = _DRAFT_LONE.sub("", clean)
    clean = _DRAFT_ON_ATTR.sub("", clean)
    clean = _DRAFT_JS_URL.sub("", clean)
    return clean.strip()[:_DRAFT_LIMIT]


def _client_draft_block(subject, body):
    """El mail listo para reenviar al cliente, adentro del mail de review.

    Va enmarcado y al final a propósito: primero se decide, después se reenvía. Y va
    entero, con los XXX incluidos, porque quien lo reenvía es quien los completa.
    """
    from routes.public_reference_feedback_routes import _escape_html
    body = _sanitize_client_draft(body)
    if not body:
        return ""
    subj = _escape_html(str(subject or "").strip())
    subject_row = (
        f'<div style="padding:10px 16px;border-bottom:1px solid #e4ebfb;font-size:13px;'
        f'color:#50607f;background:#fbfcff;"><b>Subject:</b> {subj}</div>'
    ) if subj else ""
    return f"""
      <div style="margin:24px 0 0;border:1px solid #d7e0f5;border-radius:14px;overflow:hidden;">
        <div style="padding:12px 16px;background:#f2f6ff;border-bottom:1px solid #d7e0f5;">
          <div style="font-weight:800;color:#172036;">📤 Email ready to forward to the client</div>
          <div style="font-size:12px;color:#50607f;margin-top:3px;">
            Once you approve these CVs, copy everything below and send it to the client.
            Replace <b>XXX</b> with the client's name and yours.
          </div>
        </div>
        {subject_row}
        <div style="padding:16px;background:#ffffff;">{body}</div>
      </div>
    """


def _notify_batch_submitted(*, review_ids, batch_number, note, extra_to, extra_cc,
                            client_subject=None, client_body=None):
    """UN mail con los N CVs de un batch.

    N mails separados para un batch de cinco es exactamente lo que hace que la gente deje
    de leerlos, así que acá va uno con la tabla completa.
    """
    from routes.public_reference_feedback_routes import _escape_html, _send_email
    if not review_ids:
        return False

    rows = _review_email_contexts(review_ids)
    if not rows:
        return False

    first = rows[0]
    # Política de destinatarios compartida con el mail individual, más los que la recruiter
    # eligió en el popup. La supervisión va siempre (está dentro de submitted_recipients).
    # El popup acepta direcciones de afuera (para mandarle al cliente), pero ESTE mail es
    # interno: lleva los scores de la AI y los avisos de CVs que exageran. Si alguien deja
    # puesto al cliente y encima elige a un sales lead, el modo sigue siendo review y el
    # cliente terminaría leyendo la evaluación de sus propios candidatos. Se descartan acá,
    # en el backend, porque el aviso del popup se puede ignorar.
    wanted = clean_emails(list(extra_to) + submitted_recipients(first))
    recipients = [e for e in wanted if _is_internal(e)]
    dropped = [e for e in wanted if e not in recipients]
    cc_wanted = [c for c in clean_emails(extra_cc) if c not in recipients]
    cc = [c for c in cc_wanted if _is_internal(c)]
    dropped += [c for c in cc_wanted if c not in cc]
    if dropped:
        logging.warning(
            "cv_review batch: %s quedaron fuera del mail de review por ser externas: %s",
            len(dropped), ", ".join(dropped),
        )
    if not recipients:
        logging.error("cv_review batch: no quedó ningún destinatario interno; no se manda")
        return False

    flagged, echoed, blocks = 0, 0, []
    for r in rows:
        a = r.get("ai_analysis") or {}
        if any(c.get("severity") == "hard" for c in (a.get("unsupported_claims") or [])):
            flagged += 1
        if a.get("jd_echo"):
            echoed += 1
        # La vacante define la marca del CV (Vintti vs vintti.ai): sale de la cuenta de
        # ESTA review, no de todos los procesos del candidato.
        url = f"https://vinttihub.vintti.com/resume-readonly.html?id={r['candidate_id']}"
        if r.get('opportunity_id'):
            url += f"&opportunity_id={r['opportunity_id']}"
        blocks.append(f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #e4ebfb;">
            <b>{_escape_html(r['candidate_name'] or 'Candidate')}</b>
            <div style="font-size:12px;color:#50607f;">Round {r['round']}</div>
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #e4ebfb;">
            {_score_pill(r.get('ai_score'), (r.get('ai_analysis') or {}).get('_requirements_summary'), (r.get('ai_analysis') or {}).get('_score_basis'), r.get('ai_error'))}
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #e4ebfb;">
            <a href="{url}" style="color:#0028ff;">Open CV</a>
          </td>
        </tr>""")

    warn = ""
    if flagged:
        warn += (f'<p style="padding:12px 16px;background:#ffeaea;border-left:5px solid '
                 f'#d84343;border-radius:12px;color:#8f0f0f;font-weight:700;">'
                 f'⚠️ {flagged} of these CVs claim things the source material does not '
                 f'support. Check those before any of this goes to the client.</p>')
    if echoed:
        warn += (f'<p style="padding:12px 16px;background:#fff4dc;border-left:5px solid '
                 f'#e0a300;border-radius:12px;color:#6b4700;font-weight:700;">'
                 f'📋 {echoed} of these CVs reuse the job description almost word for word, '
                 f'so the client would read their own posting back as experience.</p>')

    # No basta con "está vacío": si el campo tiene basura ("select sales lead") tampoco hay
    # a quién rutear, y hay que decirlo igual.
    orphan = not _as_email(first.get("sales_lead_email"))
    orphan_note = ('<p style="padding:12px 16px;background:#fff4dc;border-left:5px solid '
                   '#e0a300;border-radius:12px;color:#6b4700;font-weight:700;">'
                   '⚠️ This opportunity has no usable sales lead on file. Assign one on the '
                   'opportunity, or review these yourself.</p>') if orphan else ''

    # Un batch es de UNA vacante, así que si no hay nada técnico que medir les pasa a todos
    # los CVs por el mismo motivo: se explica una vez arriba y no N veces en la tabla.
    def _basis(r):
        return (r.get("ai_analysis") or {}).get("_score_basis") if r.get("ai_score") is None \
            and not r.get("ai_error") else None
    bases = {_basis(r) for r in rows} - {None}
    no_score_note = ""
    if bases == {"no_scorable_requirements"}:
        no_score_note = (
            'None of these got a score, and it is not the CVs: there is a job description, '
            'but everything under its required section is a soft skill, so there is nothing '
            'technical to measure them against. If this posting has real must-haves, they '
            'are sitting under “Nice to have” — move them up and score again.')
    elif bases == {"no_requirements"}:
        no_score_note = (
            'None of these got a score: there is a job description, but no requirements '
            'list could be read from it, so there is nothing to measure them against.')
    if no_score_note:
        no_score_note = ('<p style="padding:12px 16px;background:#eef2ff;border-left:5px '
                         'solid #4f46e5;border-radius:12px;color:#312e81;">'
                         f'{no_score_note}</p>')

    html = f"""
    <div style="font-family:Arial,sans-serif;color:#172036;line-height:1.5;">
      <h2 style="margin:0 0 12px;">{len(rows)} CV{'s' if len(rows) != 1 else ''} ready for your review</h2>
      <p style="margin:0 0 6px;"><b>Batch:</b> #{batch_number}</p>
      <p style="margin:0 0 6px;"><b>Position:</b> {_escape_html(first['opp_position_name'] or '—')}</p>
      <p style="margin:0 0 6px;"><b>Client:</b> {_escape_html(first['client_name'] or '—')}{_brand_chip(first)}</p>
      <p style="margin:0 0 16px;"><b>Recruiter:</b> {_escape_html(first['recruiter_email'] or '—')}</p>
      {orphan_note}
      {no_score_note}
      {warn}
      {f'<p style="margin:0 0 12px;"><b>Note from the recruiter:</b> {_escape_html(note)}</p>' if note else ''}
      <table style="width:100%;border-collapse:collapse;margin:0 0 18px;
                    border:1px solid #e4ebfb;border-radius:12px;overflow:hidden;">
        {''.join(blocks)}
      </table>
      {_batch_cta_block(first['opportunity_id'],
                        '✅ Decide on each CV',
                        'The scores are a hint, not a verdict — read each CV, then approve it, '
                        'request changes if the document can be fixed, or reject it if the '
                        'candidate is not right for this opening.')}
      {_client_draft_block(client_subject, client_body)}
    </div>
    """
    subject = (f"{len(rows)} CVs to review – Batch#{batch_number} • "
               f"{first['opp_position_name'] or 'Opportunity'} • "
               f"{first['client_name'] or 'Client'}")
    return _send_email(subject, html, recipients + cc)


def _notify_decided(review_id):
    from routes.public_reference_feedback_routes import _escape_html, _send_email
    row, reasons = _review_email_context(review_id)
    if not row:
        return False

    labels = dict(cv_review_ai.REJECT_REASONS)
    status = row["status"]
    reasons_html = "".join(f"<li>{_escape_html(labels.get(c, c))}</li>" for c in reasons)

    # Tres veredictos, tres mails distintos. Que "pedir cambios" llegue con cara de rechazo
    # sería exactamente el problema que este estado vino a resolver: la recruiter lee
    # "rejected" y entiende que el candidato no sirve, cuando lo que falla es el documento.
    if status == "approved":
        banner = ('<p style="padding:12px 16px;background:#eefbdd;border-left:5px solid #7aa23c;'
                  'border-radius:12px;color:#33600a;font-weight:700;">'
                  '✅ Approved — you can send this CV to the client.</p>')
    elif status == "changes_requested":
        banner = ('<p style="padding:12px 16px;background:#eef2ff;border-left:5px solid #4f46e5;'
                  'border-radius:12px;color:#312e81;font-weight:700;">'
                  '✏️ Changes requested — the candidate is still in play. Fix what the '
                  'comment asks for and send it back for another round.</p>')
    else:
        # Desde que existe "changes requested", el rechazo dejó de ser "arreglalo y
        # reenvialo": ése es el otro botón. Un rechazo es sobre el CANDIDATO, y decirle a la
        # recruiter que lo mande de nuevo la manda a rehacer un CV que no va a ir igual.
        banner = ('<p style="padding:12px 16px;background:#ffeaea;border-left:5px solid #d84343;'
                  'border-radius:12px;color:#8f0f0f;font-weight:700;">'
                  '❌ Rejected — this candidate is not going to the client for this opening. '
                  'The reasons below are for the next search, not for another round.</p>')

    html = f"""
    <div style="font-family:Arial,sans-serif;color:#172036;line-height:1.5;">
      <h2 style="margin:0 0 12px;">Your CV review is back</h2>
      {banner}
      <p style="margin:0 0 6px;"><b>Candidate:</b> {_escape_html(row['candidate_name'] or '—')}</p>
      <p style="margin:0 0 6px;"><b>Position:</b> {_escape_html(row['opp_position_name'] or '—')}</p>
      <p style="margin:0 0 6px;"><b>Client:</b> {_escape_html(row['client_name'] or '—')}{_brand_chip(row)}</p>
      <p style="margin:0 0 16px;"><b>Reviewed by:</b> {_escape_html(row.get('reviewed_by') or '—')}
         &nbsp;·&nbsp; Round {row['round']}</p>
      {f'<p style="margin:0 0 6px;"><b>Reasons:</b></p><ul>{reasons_html}</ul>' if reasons_html else ''}
      {f'<p style="margin:0 0 6px;"><b>Other:</b> {_escape_html(row["reject_other"])}</p>' if row.get('reject_other') else ''}
      {f'<p style="margin:0 0 16px;"><b>{"What to change" if status == "changes_requested" else "Comment"}:</b> {_escape_html(row["reviewer_comment"])}</p>' if row.get('reviewer_comment') else ''}
    </div>
    """
    subject = {"approved": "CV approved",
               "changes_requested": "CV needs changes",
               }.get(status, "CV rejected") + \
        f" – {row['candidate_name'] or 'Candidate'} • {row['opp_position_name'] or 'Opportunity'}"
    # La recruiter que lo mandó es la destinataria; la supervisión ve cerrarse el circuito.
    # clean_emails: un solo destinatario inválido hace que SendGrid descarte TODO el mensaje.
    recipients = clean_emails([
        row.get("recruiter_email"), row.get("hr_lead_email"), *OVERSIGHT_EMAILS,
    ])
    return _send_email(subject, html, recipients)
