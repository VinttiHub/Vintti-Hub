"""Hirex ATS — Slice 4: Scorecards (structured human evaluation).

One scorecard per (application, reviewer); per-competency ratings (1-4) in JSONB.
The human counterpart to the AI analysis: interviewers score competencies and give
an overall recommendation; the backend computes a consensus across all reviewers.

Depends on 20260724_add_hirex_scorecards.sql (auto-applied on startup).
"""
from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor, Json

from db import get_connection

bp = Blueprint("hirex_scorecards", __name__, url_prefix="/hirex")

RECOMMENDATIONS = ["strong_no", "no", "yes", "strong_yes"]
REC_VALUE = {"strong_no": 1, "no": 2, "yes": 3, "strong_yes": 4}


def _actor_email():
    data = request.get_json(silent=True) or {}
    return (data.get("actor_email")
            or request.headers.get("X-User-Email")
            or "").strip().lower() or None


def _clean_ratings(raw):
    """Normalize the incoming ratings array; keep only well-formed entries."""
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        comp = (item.get("competency") or "").strip()
        if not comp:
            continue
        rating = item.get("rating")
        if rating is not None:
            try:
                rating = int(rating)
                rating = rating if 1 <= rating <= 4 else None
            except (TypeError, ValueError):
                rating = None
        out.append({"competency": comp, "rating": rating,
                    "comment": (item.get("comment") or "").strip() or None})
    return out


def _summary(cards):
    """Consensus across all reviewers: rec distribution + per-competency averages."""
    if not cards:
        return {"count": 0, "recommendations": {}, "avg_recommendation": None,
                "consensus": None, "competencies": []}

    dist = {r: 0 for r in RECOMMENDATIONS}
    rec_vals = []
    comp_acc = {}   # competency -> [sum, n]
    for c in cards:
        rec = c.get("recommendation")
        if rec in dist:
            dist[rec] += 1
            rec_vals.append(REC_VALUE[rec])
        for r in (c.get("ratings") or []):
            if r.get("rating") is None:
                continue
            comp = r["competency"]
            acc = comp_acc.setdefault(comp, [0, 0])
            acc[0] += r["rating"]
            acc[1] += 1

    avg_rec = round(sum(rec_vals) / len(rec_vals), 2) if rec_vals else None
    consensus = None
    if avg_rec is not None:
        consensus = ("strong_no" if avg_rec < 1.75 else
                     "no" if avg_rec < 2.5 else
                     "yes" if avg_rec < 3.25 else "strong_yes")

    competencies = [
        {"competency": comp, "avg": round(acc[0] / acc[1], 2), "count": acc[1]}
        for comp, acc in sorted(comp_acc.items())
    ]
    return {"count": len(cards), "recommendations": dist, "avg_recommendation": avg_rec,
            "consensus": consensus, "competencies": competencies}


@bp.route("/applications/<int:app_id>/scorecards", methods=["GET"])
def list_scorecards(app_id):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT scorecard_id, application_id, job_id, reviewer_email, recommendation, "
            "overall_comment, ratings, created_at, updated_at "
            "FROM hirex_scorecards WHERE application_id = %s ORDER BY updated_at DESC;",
            (app_id,),
        )
        cards = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({"scorecards": cards, "summary": _summary(cards)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/applications/<int:app_id>/scorecards", methods=["POST"])
def upsert_scorecard(app_id):
    data = request.get_json(silent=True) or {}
    reviewer = _actor_email()
    if not reviewer:
        return jsonify({"error": "Missing reviewer identity."}), 400

    rec = data.get("recommendation")
    if rec is not None and rec not in REC_VALUE:
        return jsonify({"error": f"invalid recommendation '{rec}'"}), 400

    ratings = _clean_ratings(data.get("ratings"))
    overall_comment = (data.get("overall_comment") or "").strip() or None

    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout = '5s';")
            cur.execute("SET LOCAL statement_timeout = '10s';")
            cur.execute("SELECT job_id FROM hirex_applications WHERE application_id = %s;", (app_id,))
            app_row = cur.fetchone()
            if not app_row:
                conn.rollback()
                return jsonify({"error": "application not found"}), 404
            job_id = app_row["job_id"]

            cur.execute(
                """INSERT INTO hirex_scorecards
                       (application_id, job_id, reviewer_email, recommendation, overall_comment, ratings)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (application_id, reviewer_email) DO UPDATE
                       SET recommendation = EXCLUDED.recommendation,
                           overall_comment = EXCLUDED.overall_comment,
                           ratings = EXCLUDED.ratings,
                           updated_at = NOW()
                   RETURNING scorecard_id, application_id, job_id, reviewer_email,
                             recommendation, overall_comment, ratings, created_at, updated_at;""",
                (app_id, job_id, reviewer, rec, overall_comment, Json(ratings)),
            )
            card = cur.fetchone()
            cur.execute(
                "INSERT INTO hirex_job_activity (job_id, actor_email, action, detail) VALUES (%s,%s,%s,%s);",
                (job_id, reviewer, "scorecard_submitted", Json({"recommendation": rec})),
            )
            conn.commit()
        return jsonify(card), 201
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


@bp.route("/scorecards/<int:scorecard_id>", methods=["DELETE"])
def delete_scorecard(scorecard_id):
    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("DELETE FROM hirex_scorecards WHERE scorecard_id = %s RETURNING scorecard_id;",
                        (scorecard_id,))
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return jsonify({"error": "scorecard not found"}), 404
            conn.commit()
        return jsonify({"deleted": True, "scorecard_id": scorecard_id})
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()
