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
import threading
import time
from datetime import datetime, timezone
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

# Cuánto tiempo se le concede al hilo de scoring antes de dejar de decir "scoring…".
# Holgado: gpt-4o con este prompt puede tardar un minuto, y call_openai_with_retry
# duerme 10 s entre reintentos de rate limit.
AI_PENDING_GRACE_SECONDS = 600

_SELECT_COLS = """
    r.review_id, r.candidate_id, r.opportunity_id, r.round, r.status,
    r.recruiter_email, r.hr_lead_email, r.sales_lead_email, r.reviewed_by,
    r.requested_at, r.reviewed_at, r.reject_other, r.reviewer_comment,
    r.recruiter_note, r.ai_score, r.ai_analyzed_at, r.ai_error, r.resume_hash
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


def _serialize(row, *, reasons=None, analysis=None, live_hash=None):
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
    }
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


# --- razones (una sola fuente para el frontend) -----------------------------

@bp.route("/cv_review_reasons", methods=["GET"])
def list_reject_reasons():
    """Para que la lista no quede hardcodeada dos veces (Python y JS)."""
    return jsonify({
        "reasons": [{"code": c, "label": l} for c, l in cv_review_ai.REJECT_REASONS],
    })


# --- submit -----------------------------------------------------------------

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

    # --- 1. cargar contexto, armar el snapshot, y soltar la conexión ---------
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
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
            return jsonify({"error": "candidate not found"}), 404

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
            return jsonify({"error": "opportunity not found"}), 404
        if not opp["linked"]:
            return jsonify({
                "error": "That candidate is not linked to that opportunity.",
                "code": "not_linked",
            }), 409

        cur.execute("SELECT * FROM resume WHERE candidate_id = %s LIMIT 1", (candidate_id,))
        resume_row = cur.fetchone() or {}
        snapshot = cv_review_ai.resume_snapshot(resume_row)
        if cv_review_ai.snapshot_is_empty(snapshot):
            return jsonify({
                "error": "Generate the CV before sending it to review.",
                "code": "empty_resume",
            }), 422

        source_text = cv_review_ai.build_source_text(candidate)
        # La JD la trae el mismo helper que usa el generador, así el juez ve exactamente
        # la JD que vio el generador (misma precedencia hr_jd → career_desc → career_reqs
        # y el mismo RESUME_JD_LIMIT).
        from ai_routes import _build_resume_target_role_block, _build_opportunity_context
        from ai_routes import RESUME_JD_LIMIT, _truncate_preserving_edges
        jd_plain, opp_ctx = _build_opportunity_context(cur, opportunity_id)
        has_jd = bool((jd_plain or "").strip())
        jd_block = _build_resume_target_role_block({
            "client_name": opp["client_name"],
            "position": opp_ctx.get("position", "") or (opp["opp_position_name"] or ""),
            "career_country": opp_ctx.get("career_country", ""),
            "years_experience": str(opp_ctx.get("years_experience") or ""),
            "jd": _truncate_preserving_edges(jd_plain, RESUME_JD_LIMIT),
        })

        resume_hash = cv_review_ai.snapshot_hash(snapshot)
        sales_lead = (opp["opp_sales_lead"] or "").strip().lower() or None
        hr_lead = (opp["opp_hr_lead"] or "").strip().lower() or None

        # --- 2. insertar la ronda ------------------------------------------
        # La fila va ANTES del score a propósito: si scoreáramos primero, el usuario
        # miraría un spinner de 20s y un doble click crearía dos rondas. El costo es que
        # un reviewer que abra la cola en esos segundos ve "scoring…".
        inserted = None
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
                    RETURNING """ + _SELECT_COLS.replace("r.", ""),
                    (candidate_id, opportunity_id, actor, hr_lead, sales_lead, note,
                     Json(snapshot), resume_hash, candidate_id, opportunity_id),
                )
                inserted = cur.fetchone()
                conn.commit()
                break
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
                    (candidate_id, opportunity_id),
                )
                existing = cur.fetchone()
                if existing:
                    return jsonify({
                        "error": "This CV is already waiting for a sales review.",
                        "code": "already_pending",
                        "review": _serialize(existing),
                    }), 409
                if attempt == 2:
                    raise  # choque de round contra round: ya reintentamos una vez
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
    review_id = inserted["review_id"]

    # --- 3. score AI + mail, EN BACKGROUND --------------------------------
    # Antes esto corría dentro del request y la recruiter se quedaba mirando "Sending…":
    # gpt-4o con este prompt tarda entre 20 y 60 s, y encima _send_email hace un POST con
    # timeout=30. Sumados pasan cualquier paciencia razonable y el timeout del proxy.
    #
    # Lo que importa para el gate es que la FILA exista, y ya existe y está commiteada.
    # El score y el mail son enriquecimiento: se hacen en un hilo daemon y la UI muestra
    # "scoring…" mientras (ai_pending) hasta que la fila se actualiza.
    _spawn_scoring(
        review_id=review_id,
        has_jd=has_jd,
        snapshot=snapshot,
        jd_block=jd_block,
        source_text=source_text,
        resume_hash=resume_hash,
    )

    payload = _serialize(inserted)
    return jsonify({
        "review": payload,
        "ai_pending": True,
        # El mail sale del hilo, así que en este punto todavía no se sabe. La UI no debe
        # afirmar que se mandó.
        "email_queued": True,
    }), 201


def _score_and_notify(*, review_id, has_jd, snapshot, jd_block, source_text, resume_hash):
    """Scorea y avisa. Corre fuera del request: nada de `request` ni de Flask acá."""
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
        reasons = _load_reasons(cur, [r["review_id"] for r in rows])

        cur.execute("SELECT * FROM resume WHERE candidate_id = %s LIMIT 1", (candidate_id,))
        live = cur.fetchone()
        live_hash = cv_review_ai.snapshot_hash(cv_review_ai.resume_snapshot(live)) if live else None
    finally:
        cur.close()
        conn.close()

    return jsonify({
        "reviews": [_serialize(r, reasons=reasons.get(r["review_id"]), live_hash=live_hash)
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
        if status not in ("pending", "approved", "rejected", "cancelled"):
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
        reasons = _load_reasons(cur, [r["review_id"] for r in rows])
    finally:
        cur.close()
        conn.close()

    return jsonify({
        "reviews": [_serialize(r, reasons=reasons.get(r["review_id"])) for r in rows],
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

        cur.execute("SELECT * FROM resume WHERE candidate_id = %s LIMIT 1", (row["candidate_id"],))
        live = cur.fetchone()
        live_hash = cv_review_ai.snapshot_hash(cv_review_ai.resume_snapshot(live)) if live else None
    finally:
        cur.close()
        conn.close()

    payload = _serialize(row, reasons=reasons, analysis=row.get("ai_analysis"), live_hash=live_hash)
    payload["resume_snapshot"] = row.get("resume_snapshot")
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
    if decision not in ("approved", "rejected"):
        return jsonify({"error": "decision must be 'approved' or 'rejected'"}), 400

    reasons = [str(r).strip().lower() for r in (data.get("reasons") or []) if str(r).strip()]
    reasons = list(dict.fromkeys(reasons))  # dedupe, conservando el orden
    reason_other = (data.get("reason_other") or "").strip() or None
    comment = (data.get("reviewer_comment") or data.get("comment") or "").strip() or None

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
                                     "what to fix.", "code": "no_comment"}), 422
        if "other" in reasons and not reason_other:
            return jsonify({"error": "Describe the 'Other' reason.",
                            "code": "no_reason_other"}), 422
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
                   reviewer_comment = %s, reject_other = %s, updated_at = NOW()
             WHERE review_id = %s AND status = 'pending'
            RETURNING """ + _SELECT_COLS.replace("r.", ""),
            (decision, actor, comment, reason_other, review_id),
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

        batch_synced = False
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
        "review": _serialize(row, reasons=reasons),
        "batch_synced": batch_synced,
        "email_sent": bool(email_sent),
    })


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
           candidate_id, opportunity_id, review_id AS decided_review_id, status, reviewed_at
    FROM live
    WHERE status IN ('approved', 'rejected')
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
    denied = _require_reviewer()
    if denied:
        return denied

    ensure_cv_review_tables()

    from dashboards.datasets._periods import window_bounds
    from dashboards.datasets._recruiters import RECRUITERS_CTE

    lo, hi = window_bounds(request.args.to_dict())
    # `mine=1` acota a las oportunidades de quien mira, igual que en la cola, para que la
    # métrica y la lista de abajo no cuenten universos distintos.
    sales_lead = (request.args.get("sales_lead") or "").strip().lower()
    if request.args.get("mine") == "1":
        sales_lead = _user_email() or sales_lead
    params = {
        "w_lo": lo, "w_hi": hi,
        "recruiter": (request.args.get("recruiter") or "").strip().lower(),
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

    out_rows = []
    for r in rows:
        decided = r["profiles_decided"]
        reasons = by_recruiter.get(r["recruiter_email"], [])
        for item in reasons:
            item["pct"] = _pct(item["profiles"], decided)
        out_rows.append({
            **r,
            "quality_avg": float(r["quality_avg"]) if r["quality_avg"] is not None else None,
            "rejected_first_try_pct": _pct(r["rejected_first_try"], decided),
            "approved_first_try_pct": _pct(r["approved_first_try"], decided),
            "reasons": reasons,
        })

    totals = {
        "profiles_sent": sum(r["profiles_sent"] for r in rows),
        "profiles_decided": sum(r["profiles_decided"] for r in rows),
        "profiles_pending": sum(r["profiles_pending"] for r in rows),
        "rejected_first_try": sum(r["rejected_first_try"] for r in rows),
        "approved_first_try": sum(r["approved_first_try"] for r in rows),
        "quality_n": sum(r["quality_n"] for r in rows),
        "stale_version_profiles": sum(r["stale_version_profiles"] for r in rows),
    }
    weighted = sum(
        float(r["quality_avg"]) * r["quality_n"] for r in rows if r["quality_avg"] is not None
    )
    totals["quality_avg"] = round(weighted / totals["quality_n"], 1) if totals["quality_n"] else None
    totals["rejected_first_try_pct"] = _pct(totals["rejected_first_try"], totals["profiles_decided"])
    totals["approved_first_try_pct"] = _pct(totals["approved_first_try"], totals["profiles_decided"])

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
                   o.opp_position_name, COALESCE(a.client_name, 'Client') AS client_name
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


def _score_pill(score):
    if score is None:
        return ('<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
                'background:#eceff5;color:#50607f;font-weight:700;font-size:12px;">'
                'Not scored</span>')
    # Lima de marca para lo bueno, ámbar para el medio, rojo para lo flojo.
    bg, fg = ("#c1ff72", "#3a6b00") if score >= 75 else \
             ("#ffe4a3", "#7a5200") if score >= 50 else ("#ffd9d9", "#a01111")
    return (f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
            f'background:{bg};color:{fg};font-weight:700;font-size:12px;">'
            f'CV quality {score}/100</span>')


def submitted_recipients(row):
    """Quién se entera de que hay un CV para revisar.

    Cada sales lead recibe SÓLO los CVs de sus oportunidades; el par de supervisión
    (OVERSIGHT_EMAILS) recibe TODOS.

    `opp_sales_lead` es texto libre y a veces está vacío. Si de ahí saliera una lista
    vacía el review sería invisible y el gate no serviría de nada, así que la supervisión
    va SIEMPRE, y con la opp sin sales lead se suma el hr_lead para que al menos alguien
    del proceso lo vea.
    """
    recipients = []
    sales_lead = str(row.get("sales_lead_email") or "").strip().lower()
    hr_lead = str(row.get("hr_lead_email") or "").strip().lower()
    if sales_lead:
        recipients.append(sales_lead)
    elif hr_lead:
        recipients.append(hr_lead)
    recipients.extend(OVERSIGHT_EMAILS)
    # _send_email deduplica y filtra vacíos, pero no le pasamos basura igual. dict.fromkeys
    # en vez de set() para no perder el orden: el sales lead va primero en el "To".
    return list(dict.fromkeys(r for r in recipients if r))


def _notify_submitted(review_id):
    from routes.public_reference_feedback_routes import _escape_html, _send_email
    row, _ = _review_email_context(review_id)
    if not row:
        return False

    recipients = submitted_recipients(row)
    orphan = not str(row.get("sales_lead_email") or "").strip()
    orphan_note = ('<p style="padding:12px 16px;background:#fff4dc;border-left:5px solid '
                   '#e0a300;border-radius:12px;color:#6b4700;font-weight:700;">'
                   '⚠️ This opportunity has no sales lead assigned, so there was nobody to '
                   'route this to. Assign one on the opportunity, or review it yourself.</p>'
                   ) if orphan else ''

    analysis = row.get("ai_analysis") or {}
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
                '⚠️ The AI flagged claims in this CV that the source material does not '
                'support. Check them before this goes out.</p>')
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
      <p style="margin:0 0 6px;"><b>Client:</b> {_escape_html(row['client_name'] or '—')}</p>
      <p style="margin:0 0 6px;"><b>Recruiter:</b> {_escape_html(row['recruiter_email'] or '—')}</p>
      <p style="margin:0 0 16px;"><b>Round:</b> {row['round']} &nbsp; {_score_pill(row.get('ai_score'))}</p>
      {orphan_note}
      {warn}
      {f'<p style="margin:0 0 6px;"><b>Note from the recruiter:</b> {_escape_html(row["recruiter_note"])}</p>' if row.get('recruiter_note') else ''}
      {f'<p style="margin:0 0 6px;"><b>Top AI suggestions:</b></p><ul>{fixes_html}</ul>' if fixes_html else ''}
      {_review_cta_block(review_id, '✅ Approve or reject this CV',
                         'The score is a hint, not a verdict — read the CV, then approve it '
                         'or reject it with the reason so the recruiter knows what to fix.')}
    </div>
    """
    subject = (f"CV to review – {row['candidate_name'] or 'Candidate'} • "
               f"{row['opp_position_name'] or 'Opportunity'}")
    return _send_email(subject, html, recipients)


def _notify_decided(review_id):
    from routes.public_reference_feedback_routes import _escape_html, _send_email
    row, reasons = _review_email_context(review_id)
    if not row:
        return False

    labels = dict(cv_review_ai.REJECT_REASONS)
    approved = row["status"] == "approved"
    reasons_html = "".join(f"<li>{_escape_html(labels.get(c, c))}</li>" for c in reasons)

    if approved:
        banner = ('<p style="padding:12px 16px;background:#eefbdd;border-left:5px solid #7aa23c;'
                  'border-radius:12px;color:#33600a;font-weight:700;">'
                  '✅ Approved — you can send this CV to the client.</p>')
    else:
        banner = ('<p style="padding:12px 16px;background:#ffeaea;border-left:5px solid #d84343;'
                  'border-radius:12px;color:#8f0f0f;font-weight:700;">'
                  '❌ Rejected — fix it and send it back for another round.</p>')

    html = f"""
    <div style="font-family:Arial,sans-serif;color:#172036;line-height:1.5;">
      <h2 style="margin:0 0 12px;">Your CV review is back</h2>
      {banner}
      <p style="margin:0 0 6px;"><b>Candidate:</b> {_escape_html(row['candidate_name'] or '—')}</p>
      <p style="margin:0 0 6px;"><b>Position:</b> {_escape_html(row['opp_position_name'] or '—')}</p>
      <p style="margin:0 0 6px;"><b>Client:</b> {_escape_html(row['client_name'] or '—')}</p>
      <p style="margin:0 0 16px;"><b>Reviewed by:</b> {_escape_html(row.get('reviewed_by') or '—')}
         &nbsp;·&nbsp; Round {row['round']}</p>
      {f'<p style="margin:0 0 6px;"><b>Reasons:</b></p><ul>{reasons_html}</ul>' if reasons_html else ''}
      {f'<p style="margin:0 0 6px;"><b>Other:</b> {_escape_html(row["reject_other"])}</p>' if row.get('reject_other') else ''}
      {f'<p style="margin:0 0 16px;"><b>Comment:</b> {_escape_html(row["reviewer_comment"])}</p>' if row.get('reviewer_comment') else ''}
    </div>
    """
    subject = ("CV approved" if approved else "CV rejected") + \
        f" – {row['candidate_name'] or 'Candidate'} • {row['opp_position_name'] or 'Opportunity'}"
    # La recruiter que lo mandó es la destinataria; la supervisión ve cerrarse el circuito.
    recipients = [row.get("recruiter_email")]
    if row.get("hr_lead_email"):
        recipients.append(row["hr_lead_email"])
    recipients.extend(OVERSIGHT_EMAILS)
    return _send_email(subject, html, list(dict.fromkeys(r for r in recipients if r)))
