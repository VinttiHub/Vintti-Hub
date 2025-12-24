# recruiter_metrics_routes.py
import logging
from datetime import date, datetime, timedelta, timezone

from flask import jsonify, render_template, g, request
from psycopg2.extras import RealDictCursor

from db import get_connection

logger = logging.getLogger(__name__)
BOGOTA_TZ = timezone(timedelta(hours=-5))


def _default_rolling_30d():
    today = datetime.now(BOGOTA_TZ).date()
    end_inclusive = today
    start = today - timedelta(days=29)
    return start, end_inclusive


def _parse_date_range_args():
    """
    start/end vienen como YYYY-MM-DD (end inclusive).
    Si no vienen, usamos rolling 30d.
    Retorna:
      window_start (date)
      window_end_excl (date)  # exclusivo
      prev_start (date)
      prev_end_excl (date)
      display_start (date)
      display_end_inclusive (date)
    """
    start_s = request.args.get("start")
    end_s = request.args.get("end")

    if start_s and end_s:
      try:
        start = date.fromisoformat(start_s)
        end_inclusive = date.fromisoformat(end_s)
      except Exception:
        return None, None, None, None, None, None, "Invalid date format. Use YYYY-MM-DD."

      if end_inclusive < start:
        return None, None, None, None, None, None, "End date must be >= start date."

    else:
      start, end_inclusive = _default_rolling_30d()

    window_end_excl = end_inclusive + timedelta(days=1)
    window_days = (window_end_excl - start).days  # tamaño del rango en días

    prev_end_excl = start
    prev_start = start - timedelta(days=window_days)

    return start, window_end_excl, prev_start, prev_end_excl, start, end_inclusive, None


def _iso_date_or_none(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def register_recruiter_metrics_routes(app):
    @app.route("/recruiter-metrics", methods=["GET"])
    def api_recruiter_metrics():
        window_start, window_end, prev_start, prev_end, disp_start, disp_end, err = _parse_date_range_args()
        if err:
            return jsonify({"status": "error", "message": err}), 400

        sql = """
        WITH base AS (
            SELECT
                o.opportunity_id,
                o.opp_hr_lead,
                u.user_name,
                o.opp_stage,
                (o.opp_close_date)::date AS close_date
            FROM opportunity o
            LEFT JOIN users u
                ON u.email_vintti = o.opp_hr_lead
            WHERE o.opp_hr_lead IS NOT NULL
        ),
        agg AS (
            SELECT
                opp_hr_lead,
                MAX(user_name) AS user_name,

                -- ✅ RANGO SELECCIONADO
                COUNT(*) FILTER (
                    WHERE close_date >= %(win_start)s
                      AND close_date <  %(win_end)s
                      AND opp_stage = 'Close Win'
                ) AS closed_win_month,

                COUNT(*) FILTER (
                    WHERE close_date >= %(win_start)s
                      AND close_date <  %(win_end)s
                      AND opp_stage = 'Closed Lost'
                ) AS closed_lost_month,

                -- ✅ RANGO ANTERIOR (mismo tamaño) para comparación
                COUNT(*) FILTER (
                    WHERE close_date >= %(prev_start)s
                      AND close_date <  %(prev_end)s
                      AND opp_stage = 'Close Win'
                ) AS prev_closed_win_month,

                COUNT(*) FILTER (
                    WHERE close_date >= %(prev_start)s
                      AND close_date <  %(prev_end)s
                      AND opp_stage = 'Closed Lost'
                ) AS prev_closed_lost_month,

                -- ✅ TOTALES LIFETIME
                COUNT(*) FILTER (WHERE opp_stage = 'Close Win')  AS closed_win_total,
                COUNT(*) FILTER (WHERE opp_stage = 'Closed Lost') AS closed_lost_total

            FROM base
            GROUP BY opp_hr_lead
        ),
        conv AS (
            -- ✅ Conversión sobre oportunidades cerradas en el rango seleccionado
            SELECT
                opp_hr_lead,
                COUNT(*) FILTER (
                    WHERE close_date >= %(win_start)s
                      AND close_date <  %(win_end)s
                ) AS last_20_count,
                COUNT(*) FILTER (
                    WHERE close_date >= %(win_start)s
                      AND close_date <  %(win_end)s
                      AND opp_stage = 'Close Win'
                ) AS last_20_win
            FROM base
            GROUP BY opp_hr_lead
        )
        SELECT
            a.opp_hr_lead,
            a.user_name,
            a.closed_win_month,
            a.closed_lost_month,
            a.prev_closed_win_month,
            a.prev_closed_lost_month,
            a.closed_win_total,
            a.closed_lost_total,
            c.last_20_count,
            c.last_20_win,
            CASE
                WHEN c.last_20_count = 0 THEN NULL
                ELSE c.last_20_win::decimal / c.last_20_count
            END AS conversion_rate_last_20,
            CASE
                WHEN (a.closed_win_total + a.closed_lost_total) = 0 THEN NULL
                ELSE a.closed_win_total::decimal
                     / (a.closed_win_total + a.closed_lost_total)
            END AS conversion_rate_lifetime
        FROM agg a
        LEFT JOIN conv c
            ON c.opp_hr_lead = a.opp_hr_lead
        ORDER BY a.opp_hr_lead;
        """

        churn_details_sql = """
        WITH churned AS (
            SELECT
                h.hire_opportunity_id,
                h.candidate_id,
                h.opportunity_id,
                h.account_id,
                h.start_date::date AS start_date,
                h.end_date::date AS end_date,
                CASE
                    WHEN h.start_date IS NOT NULL
                         AND h.end_date IS NOT NULL
                    THEN GREATEST(0, (h.end_date::date - h.start_date::date))::int
                    ELSE NULL
                END AS tenure_days
            FROM hire_opportunity h
            WHERE h.end_date IS NOT NULL
              AND h.end_date >= %(win_start)s
              AND h.end_date <  %(win_end)s
        )
        SELECT
            cd.hire_opportunity_id,
            cd.candidate_id,
            c.name AS candidate_name,
            c.email AS candidate_email,
            cd.opportunity_id,
            o.opp_hr_lead AS hr_lead_email,
            u.user_name AS hr_lead_name,
            cd.start_date,
            cd.end_date,
            cd.tenure_days,
            CASE
                WHEN cd.tenure_days IS NOT NULL
                     AND cd.tenure_days < 90
                THEN TRUE
                ELSE FALSE
            END AS left_within_90_days,
            o.opp_stage AS opportunity_stage,
            o.opp_stage AS opportunity_status,
            o.opp_model AS opportunity_model,
            o.opp_type AS opportunity_type,
            COALESCE(
                o.nda_signature_or_start_date::date,
                o.opp_close_date::date
            ) AS opportunity_created_date,
            a.client_name AS opportunity_client_name,
            o.opp_position_name AS opportunity_title
        FROM churned cd
        LEFT JOIN candidates c
            ON c.candidate_id = cd.candidate_id
        LEFT JOIN opportunity o
            ON o.opportunity_id = cd.opportunity_id
        LEFT JOIN account a
            ON a.account_id = o.account_id
        LEFT JOIN users u
            ON LOWER(u.email_vintti) = LOWER(o.opp_hr_lead)
        ORDER BY cd.end_date DESC NULLS LAST, cd.hire_opportunity_id DESC;
        """

        churn_detail_rows = []
        try:
            conn = get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    sql,
                    {
                        "win_start": window_start,
                        "win_end": window_end,
                        "prev_start": prev_start,
                        "prev_end": prev_end,
                    },
                )
                rows = cur.fetchall()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    churn_details_sql,
                    {
                        "win_start": window_start,
                        "win_end": window_end,
                    },
                )
                churn_detail_rows = cur.fetchall()
        except Exception as e:
            logger.exception("Error fetching recruiter metrics")
            return jsonify({"status": "error", "message": str(e)}), 500
        finally:
            try:
                conn.close()
            except Exception:
                pass

        metrics = []
        for r in rows:
            conversion_range = float(r["conversion_rate_last_20"]) if r["conversion_rate_last_20"] is not None else None
            conversion_lifetime = float(r["conversion_rate_lifetime"]) if r["conversion_rate_lifetime"] is not None else None

            email = r["opp_hr_lead"]
            name = r.get("user_name") or email

            metrics.append(
                {
                    "hr_lead_email": email,
                    "hr_lead_name": name,
                    "hr_lead": email,

                    "closed_win_month": r["closed_win_month"] or 0,
                    "closed_lost_month": r["closed_lost_month"] or 0,
                    "closed_win_total": r["closed_win_total"] or 0,
                    "closed_lost_total": r["closed_lost_total"] or 0,

                    "last_20_count": r["last_20_count"] or 0,
                    "last_20_win": r["last_20_win"] or 0,
                    "conversion_rate_last_20": conversion_range,

                    "prev_closed_win_month": r["prev_closed_win_month"] or 0,
                    "prev_closed_lost_month": r["prev_closed_lost_month"] or 0,

                    "conversion_rate_lifetime": conversion_lifetime,
                    # placeholders updated once churn details are computed
                    "churn_total": 0,
                    "churn_within_90": 0,
                    "churn_tenure_known": 0,
                    "churn_tenure_unknown": 0,
                    "churn_within_90_rate": None,
                }
            )

        churn_details = []
        churn_summary_by_lead = {}
        overall_churn_summary = {
            "total": 0,
            "within_90": 0,
            "tenure_known": 0,
            "tenure_unknown": 0,
        }

        for row in churn_detail_rows:
            tenure_days = row.get("tenure_days")
            if tenure_days is not None:
                try:
                    tenure_days = int(tenure_days)
                except (TypeError, ValueError):
                    pass

            detail = {
                "hire_opportunity_id": row.get("hire_opportunity_id"),
                "candidate_id": row.get("candidate_id"),
                "candidate_name": row.get("candidate_name"),
                "candidate_email": row.get("candidate_email"),
                "opportunity_id": row.get("opportunity_id"),
                "opportunity_title": row.get("opportunity_title"),
                "opportunity_stage": row.get("opportunity_stage"),
                "opportunity_status": row.get("opportunity_status"),
                "opportunity_model": row.get("opportunity_model"),
                "opportunity_type": row.get("opportunity_type"),
                "opportunity_created_at": _iso_date_or_none(row.get("opportunity_created_date")),
                "opportunity_client_name": row.get("opportunity_client_name"),
                "hr_lead_email": row.get("hr_lead_email"),
                "hr_lead_name": row.get("hr_lead_name"),
                "start_date": _iso_date_or_none(row.get("start_date")),
                "end_date": _iso_date_or_none(row.get("end_date")),
                "tenure_days": tenure_days,
                "left_within_90_days": bool(row.get("left_within_90_days")),
            }
            churn_details.append(detail)

            overall_churn_summary["total"] += 1
            if tenure_days is not None:
                overall_churn_summary["tenure_known"] += 1
                if detail["left_within_90_days"]:
                    overall_churn_summary["within_90"] += 1
            else:
                overall_churn_summary["tenure_unknown"] += 1

            lead_key = (detail["hr_lead_email"] or "").lower()
            if not lead_key:
                continue
            summary = churn_summary_by_lead.setdefault(
                lead_key,
                {"total": 0, "within_90": 0, "tenure_known": 0, "tenure_unknown": 0},
            )
            summary["total"] += 1
            if tenure_days is not None:
                summary["tenure_known"] += 1
                if detail["left_within_90_days"]:
                    summary["within_90"] += 1
            else:
                summary["tenure_unknown"] += 1

        for item in metrics:
            lead_key = (item.get("hr_lead_email") or item.get("hr_lead") or "").lower()
            summary = churn_summary_by_lead.get(lead_key)
            if not summary:
                continue
            item["churn_total"] = summary["total"]
            item["churn_within_90"] = summary["within_90"]
            item["churn_tenure_known"] = summary["tenure_known"]
            item["churn_tenure_unknown"] = summary["tenure_unknown"]
            if summary["tenure_known"]:
                item["churn_within_90_rate"] = summary["within_90"] / summary["tenure_known"]
            else:
                item["churn_within_90_rate"] = None

        if overall_churn_summary["tenure_known"]:
            overall_churn_summary["within_90_rate"] = (
                overall_churn_summary["within_90"] / overall_churn_summary["tenure_known"]
            )
        else:
            overall_churn_summary["within_90_rate"] = None

        current_user_email = getattr(g, "user_email", None)

        return jsonify(
            {
                "status": "ok",
                # compatibilidad con tu JS
                "month_start": window_start.isoformat(),
                "month_end": window_end.isoformat(),  # exclusivo
                # 👇 para pintar el picker bonito
                "range_start": disp_start.isoformat(),
                "range_end": disp_end.isoformat(),  # inclusive
                "metrics": metrics,
                # Churn data is requested by the non-React Recruiter Power UI:
                #  - summary counts live in each metric row (per recruiter)
                #  - churn_details drives the detail table (per hire/opportunity)
                #  - churn_summary gives overall totals for the selected window
                "churn_details": churn_details,
                "churn_summary": overall_churn_summary,
                "current_user_email": current_user_email,
            }
        )
