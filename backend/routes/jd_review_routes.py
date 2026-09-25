"""JD Review: el sales lead revisa la Job Description antes de que salga.

Es el CV Review (routes/cv_review_routes.py) aplicado a la JD. La JD la escribe la AI desde
los transcripts de Grain de la Intro Call y la Deep Dive, y nadie la contrastaba con lo que
se habló. El circuito:

  1. La recruiter aprieta "Send JD to review" en la pestaña Job Description
     (POST /opportunities/<id>/jd_reviews). Se congela la JD y se abre la ronda N.
  2. En un hilo: se traen los transcripts de los links guardados en la opp
     (first_meeting_recording / deepdive_recording), se congelan, y utils/jd_review_ai
     scorea cobertura / contradicciones / inventado. El mail al sales lead sale SIEMPRE,
     con o sin score.
  3. El sales lead, desde docs/jd-review.html, aprueba o pide cambios, con checklist
     obligatorio. No hay "rejected": una JD no se descarta, se corrige.

Quién revisa y quién supervisa se importa de cv_review_routes a propósito: una sola lista.
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timezone

import psycopg2
from flask import Blueprint, jsonify, request
from psycopg2 import errors as pg_errors
from psycopg2.extras import Json, RealDictCursor

from db import get_connection
from jd_review_store import ensure_jd_review_tables
from routes.cv_review_routes import (
    FRONT_BASE_URL,
    OVERSIGHT_EMAILS,
    REVIEW_OVERRIDE_EMAILS,
    _as_email,
    _require_actor,
    _require_reviewer,
    _sales_lead_emails,
    _user_email,
    clean_emails,
)
from utils import jd_review_ai

bp = Blueprint("jd_review", __name__)

AI_PENDING_GRACE_SECONDS = 600

_STATUSES = ("pending", "approved", "changes_requested", "cancelled")

_SELECT_COLS = """
    r.review_id, r.opportunity_id, r.round, r.status,
    r.recruiter_email, r.hr_lead_email, r.sales_lead_email, r.reviewed_by,
    r.requested_at, r.reviewed_at, r.reviewer_comment, r.recruiter_note,
    r.ai_score, r.ai_analyzed_at, r.ai_error, r.jd_hash, r.checklist_done, r.updated_at
"""

_NO_SCORE_LABEL = {
    "no_transcripts": "No call recordings",
    "no_jd": "No JD",
    "no_facts": "Nothing to measure",
}


# --- serialización --------------------------------------------------------------------

def _iso(value):
    return value.isoformat() if value else None


def _within(ts, seconds):
    if not ts:
        return False
    try:
        now = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            now = now.replace(tzinfo=None)
        return (now - ts).total_seconds() < seconds
    except (TypeError, AttributeError):
        return False


def _serialize(row, *, checklist=None, analysis=None, live_hash=None):
    out = {
        "review_id": row["review_id"],
        "opportunity_id": row["opportunity_id"],
        "round": row["round"],
        "status": row["status"],
        "recruiter_email": row["recruiter_email"],
        "hr_lead_email": row.get("hr_lead_email"),
        "sales_lead_email": row.get("sales_lead_email"),
        "reviewed_by": row.get("reviewed_by"),
        "requested_at": _iso(row["requested_at"]),
        "reviewed_at": _iso(row.get("reviewed_at")),
        "reviewer_comment": row.get("reviewer_comment"),
        "recruiter_note": row.get("recruiter_note"),
        "ai_score": row.get("ai_score"),
        "ai_analyzed_at": _iso(row.get("ai_analyzed_at")),
        "ai_error": row.get("ai_error"),
        "checklist": list(checklist or []),
        "checklist_done": bool(row.get("checklist_done")),
        # Sin análisis ni error y dentro de la gracia: el hilo todavía está corriendo.
        # La gracia corre desde updated_at y no desde requested_at: un Re-run de una ronda
        # vieja limpia el análisis y, contando desde el envío, se leía como "sin análisis" en
        # vez de "scoring…" y la página dejaba de refrescar.
        "ai_pending": (row.get("ai_analyzed_at") is None and not row.get("ai_error")
                       and _within(row.get("updated_at") or row.get("requested_at"),
                                   AI_PENDING_GRACE_SECONDS)),
    }
    for key in ("opp_position_name", "opp_stage", "client_name"):
        if key in row:
            out[key] = row.get(key)
    if analysis is not None:
        out["ai_analysis"] = analysis
    if live_hash is not None:
        # ¿La JD de la vacante cambió desde que se envió esta ronda?
        out["jd_changed_since"] = live_hash != row.get("jd_hash")
    return out


def _load_checklist(cur, review_ids):
    if not review_ids:
        return {}
    cur.execute(
        "SELECT review_id, item_code FROM jd_review_checklist WHERE review_id = ANY(%s) "
        "ORDER BY item_code",
        (list(review_ids),),
    )
    out = {}
    for r in cur.fetchall():
        rid = r["review_id"] if isinstance(r, dict) else r[0]
        code = r["item_code"] if isinstance(r, dict) else r[1]
        out.setdefault(rid, []).append(code)
    return out


# --- transcripts ------------------------------------------------------------------------

def _looks_like_pasted_transcript(value):
    """Alguien llegó a pegar un transcript de 29 KB en el campo del link (CLAUDE.md). Si
    eso es lo que hay, se usa como texto en vez de pedirle a Grain un id inventado."""
    v = (value or "").strip()
    return len(v) > 400 and "grain.com" not in v.lower() and len(v.split()) > 60


def _fetch_transcripts(intro_link, deep_dive_link):
    """{intro: {...}, deep_dive: {...}}. Nunca levanta: un Grain caído deja el error en la
    fuente y el review sigue sin score."""
    from ai_routes import _fetch_grain_transcript_from_link

    out = {}
    now = datetime.now(timezone.utc).isoformat()
    for key, value in (("intro", intro_link), ("deep_dive", deep_dive_link)):
        v = (value or "").strip()
        entry = {"link": "", "text": "", "fetched_at": now, "error": None}
        if not v:
            entry["error"] = "no_link"
        elif _looks_like_pasted_transcript(v):
            entry["text"] = v
            entry["error"] = None
            entry["pasted"] = True
        else:
            entry["link"] = v[:500]
            try:
                entry["text"] = _fetch_grain_transcript_from_link(v)
            except Exception as exc:
                logging.warning("jd_review: Grain %s falló: %s", key, exc)
                entry["error"] = str(exc)[:300]
        out[key] = entry
    return out


# --- scoring en hilo ----------------------------------------------------------------------

def _load_or_extract_facts(opportunity_id, transcripts, position, client_name, rebuild=False,
                           actor=None):
    """La lista de puntos de esta vacante para ESTOS transcripts: la guardada, o una nueva que
    queda guardada. Devuelve (facts, key, reused, error_code, meta). Nunca levanta.

    `meta` = {"rebuilt_by", "rebuilt_at"} de la lista usada (vacío si es la automática).
    Con `rebuild=True` la lista nueva se guarda firmada por `actor`.

    Guardarla es lo que hace que el score sólo se mueva cuando cambia la JD: extraer de nuevo en
    cada corrida agrupaba distinto las tareas y el número saltaba ±10 (opp 844: 68 y 80).
    """
    key = jd_review_ai.facts_key(transcripts, position)
    if not rebuild:
        try:
            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT facts, rebuilt_by, rebuilt_at FROM jd_review_facts "
                                "WHERE opportunity_id = %s AND facts_key = %s",
                                (opportunity_id, key))
                    hit = cur.fetchone()
            finally:
                conn.close()
            if hit and isinstance(hit[0], list) and hit[0]:
                meta = {"rebuilt_by": hit[1], "rebuilt_at": hit[2].isoformat() if hit[2] else None}
                return hit[0], key, True, None, meta
        except Exception:
            logging.exception("jd_review: no se pudo leer la lista de puntos guardada")

    facts, err = jd_review_ai.extract_facts(transcripts=transcripts, position=position,
                                            client_name=client_name)
    if err or not facts:
        return facts, key, False, err, {}
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO jd_review_facts
                           (opportunity_id, facts_key, facts, rebuilt_by, rebuilt_at)
                       VALUES (%s, %s, %s, %s, CASE WHEN %s THEN NOW() END)
                       ON CONFLICT (opportunity_id, facts_key)
                       DO UPDATE SET facts = EXCLUDED.facts, created_at = NOW(),
                                     rebuilt_by = EXCLUDED.rebuilt_by,
                                     rebuilt_at = EXCLUDED.rebuilt_at""",
                    (opportunity_id, key, Json(facts), actor if rebuild else None, rebuild),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        # Sin guardar igual se scorea: sólo se pierde la estabilidad de la próxima corrida.
        logging.exception("jd_review: no se pudo guardar la lista de puntos")
    meta = ({"rebuilt_by": actor, "rebuilt_at": datetime.now(timezone.utc).isoformat()}
            if rebuild else {})
    return facts, key, False, None, meta


def _score_and_notify(review_id, *, refetch=True, notify=True, rebuild=False, actor=None):
    """Trae transcripts (o usa los congelados), scorea, guarda y avisa. Fuera del request."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """
            SELECT r.review_id, r.opportunity_id, r.jd_snapshot, r.transcript_snapshot,
                   o.first_meeting_recording, o.deepdive_recording, o.opp_position_name,
                   COALESCE(a.client_name, '') AS client_name
            FROM jd_reviews r
            LEFT JOIN opportunity o ON o.opportunity_id = r.opportunity_id
            LEFT JOIN account a     ON a.account_id     = o.account_id
            WHERE r.review_id = %s
            """,
            (review_id,),
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()
    if not row:
        return

    transcripts = row.get("transcript_snapshot") or {}
    has_text = any((transcripts.get(k) or {}).get("text") for k in ("intro", "deep_dive"))
    if refetch or not has_text:
        transcripts = _fetch_transcripts(row.get("first_meeting_recording"),
                                         row.get("deepdive_recording"))

    position = row.get("opp_position_name") or ""
    client_name = row.get("client_name") or ""
    facts, fkey, reused, ai_error, fmeta = None, None, False, None, {}
    if jd_review_ai.jd_html_to_text(row["jd_snapshot"]):
        facts, fkey, reused, ai_error, fmeta = _load_or_extract_facts(
            row["opportunity_id"], transcripts, position, client_name, rebuild=rebuild,
            actor=actor)
    if ai_error:
        score, analysis = None, None
    else:
        score, analysis, ai_error = jd_review_ai.score_jd(
            jd_html=row["jd_snapshot"], transcripts=transcripts,
            position=position, client_name=client_name, facts=facts,
        )
    if analysis is not None:
        analysis["_facts_key"] = fkey
        # Para que el drawer pueda decir "misma lista de puntos que la ronda anterior".
        analysis["_facts_reused"] = reused
        analysis["_facts_rebuilt_by"] = fmeta.get("rebuilt_by")
        analysis["_facts_rebuilt_at"] = fmeta.get("rebuilt_at")
        # Qué falló de cada lado, para que el drawer diga "Deep Dive: no link" en vez de
        # un score que parece completo.
        analysis["transcript_status"] = {
            k: {"error": (transcripts.get(k) or {}).get("error"),
                "chars": len((transcripts.get(k) or {}).get("text") or ""),
                "link": (transcripts.get(k) or {}).get("link") or ""}
            for k in ("intro", "deep_dive")
        }
    _store_analysis(review_id, score, analysis, ai_error, transcripts)
    if notify:
        _notify_submitted(review_id)


def _rebuild_and_rescore(review_id, round_ids, *, refetch, actor):
    """Rebuild: lista nueva desde esta ronda, y después TODAS las rondas de la vacante contra
    esa lista. Si sólo se re-scoreara la ronda actual, la 1 quedaría medida con la lista vieja y
    la 2 con la nueva, y la diferencia entre rondas dejaría de decir qué corrigió la recruiter.
    Las otras rondas reusan la lista recién guardada (misma vacante, mismos transcripts)."""
    _score_and_notify(review_id, refetch=refetch, notify=False, rebuild=True, actor=actor)
    for rid in round_ids:
        if rid != review_id:
            _score_and_notify(rid, refetch=False, notify=False)


def _spawn_rebuild(review_id, round_ids, **kwargs):
    def _run():
        try:
            _rebuild_and_rescore(review_id, round_ids, **kwargs)
        except Exception:
            logging.exception("jd_review: rebuild failed")

    threading.Thread(target=_run, name=f"jd-review-rebuild-{review_id}", daemon=True).start()


def _spawn_scoring(review_id, **kwargs):
    def _run():
        try:
            _score_and_notify(review_id, **kwargs)
        except Exception:
            logging.exception("jd_review: background scoring/notification failed")

    threading.Thread(target=_run, name=f"jd-review-score-{review_id}", daemon=True).start()


def _store_analysis(review_id, score, analysis, ai_error, transcripts):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE jd_reviews
               SET ai_score = %s,
                   ai_analysis = %s,
                   ai_analyzed_at = CASE WHEN %s THEN NOW() ELSE NULL END,
                   ai_error = %s,
                   transcript_snapshot = %s,
                   updated_at = NOW()
             WHERE review_id = %s
            """,
            (score, Json(analysis) if analysis is not None else None,
             analysis is not None and not ai_error, ai_error,
             Json(transcripts) if transcripts else None, review_id),
        )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        logging.exception("jd_review: no se pudo guardar el análisis")
    finally:
        cur.close()
        conn.close()


# --- envío ------------------------------------------------------------------------------

@bp.route("/jd_reviews/checklist_items", methods=["GET"])
def list_jd_checklist_items():
    return jsonify({"items": [{"code": c, "label": l} for c, l in jd_review_ai.CHECKLIST_ITEMS]})


@bp.route("/opportunities/<int:opportunity_id>/jd_reviews", methods=["POST", "OPTIONS"])
def submit_jd_review(opportunity_id):
    if request.method == "OPTIONS":
        return ("", 204)
    denied = _require_actor()
    if denied:
        return denied
    actor = _user_email()
    body = request.get_json(silent=True) or {}
    note = (str(body.get("note") or "").strip() or None)
    if note:
        note = note[:2000]

    ensure_jd_review_tables()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """SELECT opportunity_id, hr_job_description, opp_sales_lead, opp_hr_lead
                 FROM opportunity WHERE opportunity_id = %s""",
            (opportunity_id,),
        )
        opp = cur.fetchone()
        if not opp:
            return jsonify({"error": "opportunity not found"}), 404
        jd_html = opp.get("hr_job_description") or ""
        if not jd_review_ai.jd_html_to_text(jd_html):
            return jsonify({"error": "This opportunity has no job description yet.",
                            "code": "no_jd"}), 422
        jhash = jd_review_ai.jd_hash(jd_html)

        # Resend guard: la misma JD que ya se aprobó, o la misma que volvió con cambios
        # pedidos, no abre otra ronda.
        cur.execute(
            "SELECT " + _SELECT_COLS + """ FROM jd_reviews r
              WHERE r.opportunity_id = %s AND r.status <> 'cancelled'
              ORDER BY r.round DESC LIMIT 1""",
            (opportunity_id,),
        )
        last = cur.fetchone()
        if last and last["status"] == "pending":
            return jsonify({"error": "This JD is already waiting for review.",
                            "code": "already_pending", "review": _serialize(last)}), 409
        if last and last["jd_hash"] == jhash:
            if last["status"] == "approved":
                return jsonify({"error": "This exact JD was already approved.",
                                "code": "already_approved", "review": _serialize(last)}), 409
            if last["status"] == "changes_requested":
                return jsonify({"error": "The JD hasn't changed since the sales lead asked "
                                         "for changes. Edit it first.",
                                "code": "unchanged", "review": _serialize(last)}), 409

        try:
            cur.execute(
                """
                INSERT INTO jd_reviews (
                    opportunity_id, round, recruiter_email, hr_lead_email, sales_lead_email,
                    recruiter_note, jd_snapshot, jd_hash
                )
                SELECT %s, COALESCE(MAX(round), 0) + 1, %s, %s, %s, %s, %s, %s
                  FROM jd_reviews WHERE opportunity_id = %s
                RETURNING """ + _SELECT_COLS.replace("r.", ""),
                (opportunity_id, actor, _as_email(opp.get("opp_hr_lead")),
                 _as_email(opp.get("opp_sales_lead")), note, jd_html, jhash, opportunity_id),
            )
            row = cur.fetchone()
            conn.commit()
        except pg_errors.UniqueViolation:
            # Doble click / dos pestañas: el índice parcial dejó pasar sólo una.
            conn.rollback()
            cur.execute(
                "SELECT " + _SELECT_COLS + """ FROM jd_reviews r
                  WHERE r.opportunity_id = %s AND r.status = 'pending' LIMIT 1""",
                (opportunity_id,),
            )
            existing = cur.fetchone()
            return jsonify({"error": "This JD is already waiting for review.",
                            "code": "already_pending",
                            "review": _serialize(existing) if existing else None}), 409
    except psycopg2.Error:
        conn.rollback()
        logging.exception("jd_review submit failed")
        return jsonify({"error": "Could not create the review."}), 500
    finally:
        cur.close()
        conn.close()

    _spawn_scoring(row["review_id"])
    return jsonify({"review": _serialize(row)}), 201


@bp.route("/opportunities/<int:opportunity_id>/jd_reviews", methods=["GET"])
def list_opportunity_jd_reviews(opportunity_id):
    denied = _require_actor()
    if denied:
        return denied
    ensure_jd_review_tables()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT " + _SELECT_COLS + """ FROM jd_reviews r
              WHERE r.opportunity_id = %s ORDER BY r.round DESC""",
            (opportunity_id,),
        )
        rows = cur.fetchall()
        checklist = _load_checklist(cur, [r["review_id"] for r in rows])
        cur.execute("SELECT hr_job_description FROM opportunity WHERE opportunity_id = %s",
                    (opportunity_id,))
        opp = cur.fetchone()
        live_hash = jd_review_ai.jd_hash((opp or {}).get("hr_job_description") or "")
    finally:
        cur.close()
        conn.close()
    return jsonify({
        "reviews": [_serialize(r, checklist=checklist.get(r["review_id"]), live_hash=live_hash)
                    for r in rows],
        "live_jd_hash": live_hash,
    })


# --- cola -------------------------------------------------------------------------------

def _queue_filters():
    status = (request.args.get("status") or "").strip().lower()
    recruiter = (request.args.get("recruiter") or "").strip().lower()
    sales_lead = (request.args.get("sales_lead") or "").strip().lower()
    if request.args.get("mine") == "1":
        sales_lead = _user_email() or sales_lead
    where = ["TRUE"]
    params = {}
    if status:
        if status not in _STATUSES:
            return None, None, (jsonify({"error": "unknown status"}), 400)
        where.append("r.status = %(status)s")
        params["status"] = status
    if recruiter:
        where.append("LOWER(TRIM(r.recruiter_email)) = %(recruiter)s")
        params["recruiter"] = recruiter
    if sales_lead:
        where.append("LOWER(TRIM(COALESCE(r.sales_lead_email, ''))) = %(sales_lead)s")
        params["sales_lead"] = sales_lead
    for key, op in (("from", ">="), ("to", "<=")):
        raw = (request.args.get(key) or "").strip()
        if raw:
            try:
                params[key] = date.fromisoformat(raw)
            except ValueError:
                return None, None, (jsonify({"error": f"bad {key} date"}), 400)
            where.append("(r.requested_at AT TIME ZONE 'America/Argentina/Buenos_Aires')::date "
                         f"{op} %({key})s")
    return where, params, None


@bp.route("/jd_reviews", methods=["GET"])
def list_jd_reviews():
    denied = _require_reviewer()
    if denied:
        return denied
    ensure_jd_review_tables()
    where, params, err = _queue_filters()
    if err:
        return err
    try:
        params["limit"] = min(int(request.args.get("limit", 100)), 500)
        params["offset"] = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        return jsonify({"error": "limit and offset must be integers"}), 400

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT COUNT(*) AS total FROM jd_reviews r WHERE " + " AND ".join(where),
                    params)
        total = cur.fetchone()["total"]
        cur.execute(
            "SELECT " + _SELECT_COLS + """,
                   o.opp_position_name, o.opp_stage,
                   COALESCE(a.client_name, '') AS client_name
            FROM jd_reviews r
            LEFT JOIN opportunity o ON o.opportunity_id = r.opportunity_id
            LEFT JOIN account a     ON a.account_id     = o.account_id
            WHERE """ + " AND ".join(where) + """
            ORDER BY (r.status = 'pending') DESC,
                     CASE WHEN r.status = 'pending' THEN r.requested_at END ASC,
                     r.requested_at DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            params,
        )
        rows = cur.fetchall()
        checklist = _load_checklist(cur, [r["review_id"] for r in rows])
    finally:
        cur.close()
        conn.close()
    return jsonify({
        "reviews": [_serialize(r, checklist=checklist.get(r["review_id"])) for r in rows],
        "total": total,
    })


@bp.route("/jd_reviews/pending_count", methods=["GET"])
def jd_review_pending_count():
    denied = _require_reviewer()
    if denied:
        return denied
    ensure_jd_review_tables()
    sales_lead = (request.args.get("sales_lead") or "").strip().lower()
    if request.args.get("mine") == "1":
        sales_lead = _user_email() or sales_lead
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT COUNT(*) FROM jd_reviews
                WHERE status = 'pending'
                  AND (%s = '' OR LOWER(TRIM(COALESCE(sales_lead_email, ''))) = %s)""",
            (sales_lead, sales_lead),
        )
        count = cur.fetchone()[0]
    finally:
        cur.close()
        conn.close()
    return jsonify({"count": count, "sales_lead": sales_lead})


@bp.route("/jd_reviews/<int:review_id>", methods=["GET"])
def get_jd_review(review_id):
    denied = _require_reviewer()
    if denied:
        return denied
    ensure_jd_review_tables()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT " + _SELECT_COLS + """,
                   r.ai_analysis, r.jd_snapshot, r.transcript_snapshot,
                   o.opp_position_name, o.opp_stage, o.hr_job_description,
                   COALESCE(a.client_name, '') AS client_name
            FROM jd_reviews r
            LEFT JOIN opportunity o ON o.opportunity_id = r.opportunity_id
            LEFT JOIN account a     ON a.account_id     = o.account_id
            WHERE r.review_id = %s LIMIT 1
            """,
            (review_id,),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "review not found"}), 404
        checklist = _load_checklist(cur, [review_id]).get(review_id)
        cur.execute(
            "SELECT " + _SELECT_COLS + """ FROM jd_reviews r
              WHERE r.opportunity_id = %s ORDER BY r.round DESC""",
            (row["opportunity_id"],),
        )
        rounds = cur.fetchall()
        rounds_checklist = _load_checklist(cur, [r["review_id"] for r in rounds])
    finally:
        cur.close()
        conn.close()

    live_hash = jd_review_ai.jd_hash(row.get("hr_job_description") or "")
    out = _serialize(row, checklist=checklist, analysis=row.get("ai_analysis"),
                     live_hash=live_hash)
    out["jd_snapshot"] = row["jd_snapshot"]
    ts = row.get("transcript_snapshot") or {}
    # El texto entero de los transcripts no viaja: son decenas de KB y el drawer sólo
    # necesita saber de dónde salió cada cita y si hubo error.
    out["transcripts"] = {
        k: {"link": (ts.get(k) or {}).get("link") or "",
            "chars": len((ts.get(k) or {}).get("text") or ""),
            "error": (ts.get(k) or {}).get("error"),
            "pasted": bool((ts.get(k) or {}).get("pasted"))}
        for k in ("intro", "deep_dive")
    }
    out["rounds"] = [_serialize(r, checklist=rounds_checklist.get(r["review_id"]))
                     for r in rounds]
    return jsonify(out)


# --- decisión ---------------------------------------------------------------------------

@bp.route("/jd_reviews/<int:review_id>/decision", methods=["POST", "OPTIONS"])
def decide_jd_review(review_id):
    if request.method == "OPTIONS":
        return ("", 204)
    denied = _require_reviewer()
    if denied:
        return denied
    actor = _user_email()
    body = request.get_json(silent=True) or {}
    decision = str(body.get("decision") or "").strip().lower()
    if decision not in ("approved", "changes_requested"):
        return jsonify({"error": "decision must be approved or changes_requested"}), 400
    comment = (str(body.get("comment") or "").strip() or None)
    checklist = [c for c in dict.fromkeys(body.get("checklist") or [])
                 if c in jd_review_ai.CHECKLIST_CODES]
    clean = bool(body.get("checklist_clean"))
    # Mismo contrato que el CV: o tildaste defectos, o marcaste que está limpia. Sin eso la
    # métrica de checklist no tiene denominador honesto.
    if not checklist and not clean:
        return jsonify({"error": "Go through the checklist first: tick what's wrong, or mark "
                                 "the JD as clean.", "code": "no_checklist"}), 422
    if checklist and clean:
        return jsonify({"error": "A JD can't be clean and have defects at once.",
                        "code": "checklist_conflict"}), 422
    if decision == "changes_requested" and not comment:
        return jsonify({"error": "Say what needs changing — the comment is the only thing the "
                                 "recruiter gets.", "code": "no_comment"}), 422

    ensure_jd_review_tables()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """
            UPDATE jd_reviews
               SET status = %s, reviewed_by = %s, reviewed_at = NOW(),
                   reviewer_comment = %s, checklist_done = TRUE, updated_at = NOW()
             WHERE review_id = %s AND status = 'pending'
            RETURNING """ + _SELECT_COLS.replace("r.", ""),
            (decision, actor, comment, review_id),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            cur.execute("SELECT " + _SELECT_COLS + " FROM jd_reviews r WHERE r.review_id = %s",
                        (review_id,))
            existing = cur.fetchone()
            if not existing:
                return jsonify({"error": "review not found"}), 404
            return jsonify({"error": "This review was already decided.",
                            "code": "already_decided", "review": _serialize(existing)}), 409
        if checklist:
            cur.executemany(
                "INSERT INTO jd_review_checklist (review_id, item_code) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                [(review_id, c) for c in checklist],
            )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        logging.exception("jd_review decision failed")
        return jsonify({"error": "Could not store the decision."}), 500
    finally:
        cur.close()
        conn.close()

    email_sent = _notify_decided(review_id)
    return jsonify({"review": _serialize(row, checklist=checklist),
                    "email_sent": bool(email_sent)})


@bp.route("/jd_reviews/<int:review_id>/cancel", methods=["POST", "OPTIONS"])
def cancel_jd_review(review_id):
    if request.method == "OPTIONS":
        return ("", 204)
    denied = _require_actor()
    if denied:
        return denied
    ensure_jd_review_tables()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """UPDATE jd_reviews SET status = 'cancelled', updated_at = NOW()
                WHERE review_id = %s AND status = 'pending'
            RETURNING """ + _SELECT_COLS.replace("r.", ""),
            (review_id,),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return jsonify({"error": "Only a pending review can be cancelled.",
                            "code": "not_pending"}), 409
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return jsonify({"review": _serialize(row)})


@bp.route("/jd_reviews/<int:review_id>/analyze", methods=["POST", "OPTIONS"])
def reanalyze_jd_review(review_id):
    """Re-scorea la JD congelada. `refetch=1` vuelve a pedirle los transcripts a Grain (por
    si se cargó un link que faltaba); sin eso usa los congelados. Reusa la lista de puntos
    guardada salvo `rebuild=1`, que la vuelve a extraer (y la guarda en lugar de la vieja)."""
    if request.method == "OPTIONS":
        return ("", 204)
    denied = _require_actor()
    if denied:
        return denied
    ensure_jd_review_tables()
    body = request.get_json(silent=True) or {}
    refetch = bool(body.get("refetch")) or request.args.get("refetch") == "1"
    rebuild = bool(body.get("rebuild")) or request.args.get("rebuild") == "1"
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Con rebuild se limpian TODAS las rondas no canceladas de la vacante: todas se vuelven
        # a medir contra la lista nueva y la página las tiene que mostrar como "scoring…".
        cur.execute(
            """UPDATE jd_reviews
                  SET ai_score = NULL, ai_analysis = NULL, ai_analyzed_at = NULL,
                      ai_error = NULL, updated_at = NOW()
                WHERE review_id = %s
                   OR (%s AND status <> 'cancelled' AND opportunity_id =
                         (SELECT opportunity_id FROM jd_reviews WHERE review_id = %s))
            RETURNING review_id""",
            (review_id, rebuild, review_id),
        )
        round_ids = [r[0] for r in cur.fetchall()]
        if review_id not in round_ids:
            conn.rollback()
            return jsonify({"error": "review not found"}), 404
        conn.commit()
    finally:
        cur.close()
        conn.close()
    if rebuild:
        _spawn_rebuild(review_id, sorted(round_ids), refetch=refetch, actor=_user_email())
    else:
        _spawn_scoring(review_id, refetch=refetch, notify=False)
    return jsonify({"ok": True, "refetch": refetch, "rebuild": rebuild,
                    "rescored_rounds": len(round_ids)}), 202


# --- métricas ---------------------------------------------------------------------------

_METRICS_CTES = """
live AS (
    SELECT r.*
    FROM jd_reviews r
    JOIN opportunity o  ON o.opportunity_id = r.opportunity_id
    LEFT JOIN account a ON a.account_id     = o.account_id
    WHERE r.status <> 'cancelled'
      AND COALESCE(a.vintti_internal, FALSE) = FALSE
),
first_sub AS (
    -- El primer envío define la JD: mide cómo llegó la primera vez, no después de corregir.
    SELECT DISTINCT ON (opportunity_id)
           opportunity_id, review_id, recruiter_email, sales_lead_email, requested_at,
           ai_score, ai_analysis, ai_error
    FROM live
    ORDER BY opportunity_id, requested_at, review_id
),
first_dec AS (
    SELECT DISTINCT ON (opportunity_id)
           opportunity_id, review_id AS decided_review_id, status, checklist_done,
           EXISTS (SELECT 1 FROM jd_review_checklist ck
                    WHERE ck.review_id = live.review_id) AS flagged
    FROM live
    WHERE status IN ('approved', 'changes_requested')
    ORDER BY opportunity_id, requested_at, review_id
),
scope AS (
    SELECT f.*, COALESCE(rc.label, LOWER(TRIM(f.recruiter_email))) AS recruiter_label
    FROM first_sub f
    LEFT JOIN recruiters rc ON rc.email = LOWER(TRIM(f.recruiter_email))
    WHERE (f.requested_at AT TIME ZONE 'America/Argentina/Buenos_Aires')::date
            BETWEEN %(w_lo)s AND %(w_hi)s
      AND (%(recruiter)s = '' OR LOWER(TRIM(f.recruiter_email)) = %(recruiter)s)
      AND (%(sales_lead)s = '' OR LOWER(TRIM(COALESCE(f.sales_lead_email, ''))) = %(sales_lead)s)
)
"""


def _pct(n, d):
    return round(100.0 * n / d, 1) if d else None


@bp.route("/jd_reviews/metrics", methods=["GET"])
def jd_review_metrics():
    """Mismo gate que las métricas de CV: quien no es reviewer ve sólo su fila."""
    denied = _require_actor()
    if denied:
        return denied
    ensure_jd_review_tables()

    from dashboards.datasets._periods import window_bounds
    from dashboards.datasets._recruiters import RECRUITERS_CTE

    lo, hi = window_bounds(request.args.to_dict())
    sales_lead = (request.args.get("sales_lead") or "").strip().lower()
    if request.args.get("mine") == "1":
        sales_lead = _user_email() or sales_lead
    recruiter = (request.args.get("recruiter") or "").strip().lower()
    me = _user_email()
    is_reviewer = me in REVIEW_OVERRIDE_EMAILS or me in _sales_lead_emails()
    if not is_reviewer:
        recruiter = me or ""
        sales_lead = ""

    params = {"w_lo": lo, "w_hi": hi, "recruiter": recruiter, "sales_lead": sales_lead,
              "ai_version": str(jd_review_ai.ANALYSIS_VERSION)}

    # OJO: en este SQL no puede haber un signo de porcentaje suelto, ni en un comentario
    # (psycopg2: "argument formats can't be mixed").
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "WITH " + RECRUITERS_CTE + ", " + _METRICS_CTES + """
            SELECT
                LOWER(TRIM(s.recruiter_email))                 AS recruiter_email,
                MIN(s.recruiter_label)                         AS recruiter_label,
                COUNT(*)                                       AS jds_sent,
                COUNT(d.decided_review_id)                     AS jds_decided,
                COUNT(*) - COUNT(d.decided_review_id)          AS jds_pending,
                COUNT(*) FILTER (WHERE d.status = 'approved')  AS approved_first_try,
                COUNT(*) FILTER (WHERE d.status = 'changes_requested') AS changes_first_try,
                COUNT(*) FILTER (WHERE d.checklist_done)       AS jds_checklisted,
                COUNT(*) FILTER (WHERE d.checklist_done AND NOT d.flagged) AS jds_clean,
                COUNT(s.ai_score) FILTER (
                    WHERE COALESCE(s.ai_analysis->>'_version', '0') = %(ai_version)s
                )                                              AS quality_n,
                ROUND(AVG(s.ai_score) FILTER (
                    WHERE COALESCE(s.ai_analysis->>'_version', '0') = %(ai_version)s
                ), 1)                                          AS quality_avg,
                ROUND(AVG((s.ai_analysis->'summary'->'counts'->>'missing')::numeric) FILTER (
                    WHERE s.ai_score IS NOT NULL
                      AND COALESCE(s.ai_analysis->>'_version', '0') = %(ai_version)s
                ), 1)                                          AS missing_avg,
                COUNT(*) FILTER (
                    WHERE s.ai_score IS NOT NULL
                      AND COALESCE((s.ai_analysis->'summary'->>'hard_unsupported')::int, 0) > 0
                )                                              AS with_invented,
                COUNT(*) FILTER (
                    WHERE s.ai_score IS NOT NULL
                      AND COALESCE((s.ai_analysis->'summary'->'counts'->>'contradicted')::int, 0) > 0
                )                                              AS with_contradictions,
                COUNT(*) FILTER (WHERE s.ai_error = 'no_transcripts') AS no_transcripts,
                COUNT(*) FILTER (
                    WHERE s.ai_score IS NOT NULL
                      AND COALESCE(s.ai_analysis->>'_version', '0') <> %(ai_version)s
                )                                              AS stale_version_jds
            FROM scope s
            LEFT JOIN first_dec d ON d.opportunity_id = s.opportunity_id
            GROUP BY 1
            ORDER BY 2
            """,
            params,
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "WITH " + RECRUITERS_CTE + ", " + _METRICS_CTES + """
            SELECT LOWER(TRIM(s.recruiter_email)) AS recruiter_email, ck.item_code,
                   COUNT(*) AS jds
            FROM scope s
            JOIN first_dec d            ON d.opportunity_id = s.opportunity_id
            JOIN jd_review_checklist ck ON ck.review_id = d.decided_review_id
            GROUP BY 1, 2
            ORDER BY 1, 3 DESC
            """,
            params,
        )
        checklist_rows = [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

    labels = dict(jd_review_ai.CHECKLIST_ITEMS)
    ck_by = {}
    for r in checklist_rows:
        ck_by.setdefault(r["recruiter_email"], []).append({
            "item_code": r["item_code"], "item_label": labels.get(r["item_code"], r["item_code"]),
            "jds": r["jds"],
        })

    def _derive(r, checklist):
        decided, scored = r["jds_decided"], r["quality_n"]
        for item in checklist:
            item["pct"] = _pct(item["jds"], r["jds_checklisted"])
        return {
            **r,
            "quality_avg": float(r["quality_avg"]) if r["quality_avg"] is not None else None,
            "missing_avg": float(r["missing_avg"]) if r.get("missing_avg") is not None else None,
            "approved_first_try_pct": _pct(r["approved_first_try"], decided),
            "changes_first_try_pct": _pct(r["changes_first_try"], decided),
            "with_invented_pct": _pct(r["with_invented"], scored),
            "with_contradictions_pct": _pct(r["with_contradictions"], scored),
            "no_transcripts_pct": _pct(r["no_transcripts"], r["jds_sent"]),
            "clean_pct": _pct(r["jds_clean"], r["jds_checklisted"]),
            "checklisted_pct": _pct(r["jds_checklisted"], decided),
            "checklist": checklist,
        }

    out_rows = [_derive(r, ck_by.get(r["recruiter_email"], [])) for r in rows]

    sum_keys = ("jds_sent", "jds_decided", "jds_pending", "approved_first_try",
                "changes_first_try", "jds_checklisted", "jds_clean", "quality_n",
                "with_invented", "with_contradictions", "no_transcripts", "stale_version_jds")
    totals = {k: sum(r[k] for r in rows) for k in sum_keys}
    qn = totals["quality_n"]
    totals["quality_avg"] = (round(sum(float(r["quality_avg"]) * r["quality_n"]
                                       for r in rows if r["quality_avg"] is not None) / qn, 1)
                             if qn else None)
    totals["missing_avg"] = (round(sum(float(r["missing_avg"]) * r["quality_n"]
                                       for r in rows if r["missing_avg"] is not None) / qn, 1)
                             if qn else None)
    agg = {}
    for r in checklist_rows:
        e = agg.setdefault(r["item_code"], {"item_code": r["item_code"],
                                            "item_label": labels.get(r["item_code"], r["item_code"]),
                                            "jds": 0})
        e["jds"] += r["jds"]
    totals = _derive(totals, sorted(agg.values(), key=lambda e: e["jds"], reverse=True))

    return jsonify({
        "rows": out_rows,
        "totals": totals,
        "meta": {
            "desde": lo.isoformat(),
            "hasta": hi.isoformat(),
            "scoped_to_self": not is_reviewer,
            "ai_version": jd_review_ai.ANALYSIS_VERSION,
            "checklist_is_not_exclusive": True,
            "checklist_denominator": "jds_checklisted",
        },
    })


# --- mails ------------------------------------------------------------------------------

def _email_context(review_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT " + _SELECT_COLS + """,
                   r.ai_analysis,
                   o.opp_position_name, COALESCE(a.client_name, 'Client') AS client_name
            FROM jd_reviews r
            LEFT JOIN opportunity o ON o.opportunity_id = r.opportunity_id
            LEFT JOIN account a     ON a.account_id     = o.account_id
            WHERE r.review_id = %s LIMIT 1
            """,
            (review_id,),
        )
        row = cur.fetchone()
        checklist = _load_checklist(cur, [review_id]).get(review_id, []) if row else []
    finally:
        cur.close()
        conn.close()
    return row, checklist


def submitted_recipients(row):
    """El sales lead de la vacante (o el HR lead si no hay uno usable) + la supervisión.
    Misma regla que el CV Review (cv_review_routes.submitted_recipients)."""
    recipients = []
    sales_lead = _as_email(row.get("sales_lead_email"))
    hr_lead = _as_email(row.get("hr_lead_email"))
    if sales_lead:
        recipients.append(sales_lead)
    elif hr_lead:
        recipients.append(hr_lead)
    recipients.extend(OVERSIGHT_EMAILS)
    return clean_emails(recipients)


def _score_pill(score, error=None, basis=None):
    if score is None:
        label = _NO_SCORE_LABEL.get(error or basis) or ("Not scored" if error else "No score")
        return ('<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
                'background:#eceff5;color:#50607f;font-weight:700;font-size:12px;">'
                f'{label}</span>')
    bg, fg = ("#c1ff72", "#3a6b00") if score >= 75 else \
             ("#ffe4a3", "#7a5200") if score >= 50 else ("#ffd9d9", "#a01111")
    return (f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
            f'background:{bg};color:{fg};font-weight:700;font-size:12px;">'
            f'Call coverage {score}/100</span>')


_SOURCE_LABEL = {"intro": "Intro Call", "deep_dive": "Deep Dive"}


def _cta(review_id, title, body):
    from routes.public_reference_feedback_routes import _escape_html
    url = f"{FRONT_BASE_URL}/jd-review.html?review_id={review_id}"
    return f"""
    <div style="margin:0 0 20px;padding:18px 20px;border-radius:16px;
                background:#eef2ff;border:1px solid #c7d2fe;">
      <div style="font-size:16px;font-weight:800;color:#312e81;margin-bottom:6px;">
        {_escape_html(title)}
      </div>
      <div style="color:#3730a3;margin-bottom:14px;">{_escape_html(body)}</div>
      <a href="{url}" style="display:inline-block;padding:11px 20px;border-radius:12px;
         background:#4f46e5;color:#ffffff;text-decoration:none;font-weight:700;font-size:14px;">
        Open the JD review →
      </a>
    </div>
    """


def _notify_submitted(review_id):
    from routes.public_reference_feedback_routes import _escape_html, _send_email
    row, _ = _email_context(review_id)
    if not row:
        return False
    recipients = submitted_recipients(row)
    analysis = row.get("ai_analysis") or {}
    e = _escape_html

    notes = ""
    if not _as_email(row.get("sales_lead_email")):
        notes += ('<p style="padding:12px 16px;background:#fff4dc;border-left:5px solid '
                  '#e0a300;border-radius:12px;color:#6b4700;font-weight:700;">'
                  '⚠️ This opportunity has no usable sales lead on file. Assign one on the '
                  'opportunity, or review it yourself.</p>')
    if row.get("ai_error") == "no_transcripts":
        notes += ('<p style="padding:12px 16px;background:#eef2ff;border-left:5px solid '
                  '#4f46e5;border-radius:12px;color:#312e81;">The opportunity has no usable '
                  'Grain recording (Intro Call / Deep Dive), so the AI could not check this JD '
                  'against the calls. Review it by hand.</p>')
    elif analysis.get("_partial") and analysis.get("sources"):
        have = ", ".join(_SOURCE_LABEL.get(s, s) for s in analysis["sources"])
        notes += ('<p style="padding:12px 16px;background:#fff4dc;border-left:5px solid '
                  '#e0a300;border-radius:12px;color:#6b4700;">'
                  f'Only the {e(have)} recording was available, so the score only covers that call.</p>')

    facts = analysis.get("facts") or []
    contradicted = [f for f in facts if f.get("status") == "contradicted"]
    missing = [f for f in facts if f.get("status") == "missing" and f.get("importance") == "must"]
    invented = [u for u in (analysis.get("unsupported") or []) if u.get("severity") == "hard"]

    def _li_fact(f, extra=""):
        src = _SOURCE_LABEL.get(f.get("source"), "")
        src_html = f' <span style="color:#50607f;">({e(src)})</span>' if src else ""
        quote = f' <i style="color:#50607f;">“{e(f.get("quote") or "")}”</i>' if f.get("quote") else ""
        return f'<li><b>{e(f.get("fact") or "")}</b>{extra}{src_html}{quote}</li>'

    blocks = ""
    if contradicted:
        blocks += ('<p style="margin:12px 0 4px;color:#a01111;"><b>Says something different '
                   'from the calls:</b></p><ul>'
                   + "".join(_li_fact(f, f' — JD: “{e(f.get("jd_quote") or "")}”') for f in contradicted[:5])
                   + '</ul>')
    if missing:
        blocks += ('<p style="margin:12px 0 4px;"><b>Discussed in the calls, missing from the JD:</b></p><ul>'
                   + "".join(_li_fact(f) for f in missing[:6]) + '</ul>')
        if len(missing) > 6:
            blocks += f'<p style="margin:0;color:#50607f;">…and {len(missing) - 6} more.</p>'
    if invented:
        blocks += ('<p style="margin:12px 0 4px;color:#7a5200;"><b>In the JD, but nobody said it:</b></p><ul>'
                   + "".join(f'<li>“{e(u.get("jd_quote") or "")}” — {e(u.get("why") or "")}</li>'
                             for u in invented[:5]) + '</ul>')

    note = (f'<p style="margin:0 0 6px;"><b>Note from the recruiter:</b> {e(row["recruiter_note"])}</p>'
            if row.get("recruiter_note") else "")
    html = f"""
    <div style="font-family:Arial,sans-serif;color:#172036;line-height:1.5;">
      <h2 style="margin:0 0 12px;">Job description ready for your review</h2>
      <p style="margin:0 0 6px;"><b>Position:</b> {e(row['opp_position_name'] or '—')}</p>
      <p style="margin:0 0 6px;"><b>Client:</b> {e(row['client_name'] or '—')}</p>
      <p style="margin:0 0 6px;"><b>Sent by:</b> {e(row['recruiter_email'] or '—')} &nbsp;·&nbsp; Round {row['round']}</p>
      <p style="margin:0 0 16px;">{_score_pill(row.get('ai_score'), row.get('ai_error'), analysis.get('_score_basis'))}
         {f'<span style="margin-left:8px;color:#50607f;">{e(analysis.get("verdict_why") or "")}</span>' if analysis.get('verdict_why') else ''}</p>
      {notes}
      {note}
      {blocks}
      {_cta(review_id, '✅ Decide on this JD',
            'The score is how much of what the client said in the Intro Call and the Deep Dive '
            'made it into the JD. Read it, then approve it or ask for changes.')}
    </div>
    """
    subject = (f"JD to review – {row['opp_position_name'] or 'Opportunity'} • "
               f"{row['client_name'] or 'Client'}")
    return _send_email(subject, html, recipients)


def _notify_decided(review_id):
    from routes.public_reference_feedback_routes import _escape_html, _send_email
    row, checklist = _email_context(review_id)
    if not row:
        return False
    e = _escape_html
    labels = dict(jd_review_ai.CHECKLIST_ITEMS)
    status = row["status"]
    if status == "approved":
        banner = ('<p style="padding:12px 16px;background:#eefbdd;border-left:5px solid #7aa23c;'
                  'border-radius:12px;color:#33600a;font-weight:700;">'
                  '✅ Approved — the JD is good to go.</p>')
    else:
        banner = ('<p style="padding:12px 16px;background:#eef2ff;border-left:5px solid #4f46e5;'
                  'border-radius:12px;color:#312e81;font-weight:700;">'
                  '✏️ Changes requested — fix what the comment asks for and send it back for '
                  'another round.</p>')
    ck_html = "".join(f"<li>{e(labels.get(c, c))}</li>" for c in checklist)
    url = f"{FRONT_BASE_URL}/opportunity-detail.html?id={row['opportunity_id']}&tab=job%20description"
    html = f"""
    <div style="font-family:Arial,sans-serif;color:#172036;line-height:1.5;">
      <h2 style="margin:0 0 12px;">Your JD review is back</h2>
      {banner}
      <p style="margin:0 0 6px;"><b>Position:</b> {e(row['opp_position_name'] or '—')}</p>
      <p style="margin:0 0 6px;"><b>Client:</b> {e(row['client_name'] or '—')}</p>
      <p style="margin:0 0 16px;"><b>Reviewed by:</b> {e(row.get('reviewed_by') or '—')}
         &nbsp;·&nbsp; Round {row['round']}</p>
      {f'<p style="margin:0 0 6px;"><b>Flagged:</b></p><ul>{ck_html}</ul>' if ck_html else ''}
      {f'<p style="margin:0 0 16px;"><b>{"What to change" if status == "changes_requested" else "Comment"}:</b> {e(row["reviewer_comment"])}</p>' if row.get('reviewer_comment') else ''}
      <a href="{url}" style="display:inline-block;padding:11px 20px;border-radius:12px;
         background:#4f46e5;color:#ffffff;text-decoration:none;font-weight:700;font-size:14px;">
        Open the job description →</a>
    </div>
    """
    subject = ("JD approved" if status == "approved" else "JD needs changes") + \
        f" – {row['opp_position_name'] or 'Opportunity'} • {row['client_name'] or 'Client'}"
    recipients = clean_emails([row.get("recruiter_email"), row.get("hr_lead_email"),
                               *OVERSIGHT_EMAILS])
    return _send_email(subject, html, recipients)
