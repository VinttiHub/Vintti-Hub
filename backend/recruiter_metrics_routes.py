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
                }
            )

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
                "current_user_email": current_user_email,
            }
        )