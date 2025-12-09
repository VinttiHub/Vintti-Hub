# recruiter_metrics_routes.py
import logging
from datetime import date, datetime, timedelta, timezone

from flask import jsonify, render_template
from psycopg2.extras import RealDictCursor

from db import get_connection

logger = logging.getLogger(__name__)

BOGOTA_TZ = timezone(timedelta(hours=-5))


def _current_month_bounds():
    """Devuelve (month_start, month_end) en fecha (no datetime)."""
    now = datetime.now(BOGOTA_TZ).date()
    month_start = date(now.year, now.month, 1)
    if now.month == 12:
        month_end = date(now.year + 1, 1, 1)
    else:
        month_end = date(now.year, now.month + 1, 1)
    return month_start, month_end

def _previous_month_bounds():
    """Devuelve (prev_month_start, prev_month_end) en fecha."""
    now = datetime.now(BOGOTA_TZ).date()
    first_of_this_month = date(now.year, now.month, 1)
    prev_month_end = first_of_this_month
    if now.month == 1:
        prev_month_start = date(now.year - 1, 12, 1)
    else:
        prev_month_start = date(now.year, now.month - 1, 1)
    return prev_month_start, prev_month_end


def register_recruiter_metrics_routes(app):
    @app.route("/recruiter-metrics", methods=["GET"])
    def api_recruiter_metrics():
        """
        Devuelve métricas agregadas por opp_hr_lead:

        - closed_win_month
        - closed_lost_month
        - closed_win_total
        - closed_lost_total
        - last_20_count
        - last_20_win
        - conversion_rate_last_20 (0-1)
        """
        month_start, month_end = _current_month_bounds()
        prev_month_start, prev_month_end = _previous_month_bounds()

        sql = """
        WITH base AS (
            SELECT
                opportunity_id,
                opp_hr_lead,
                opp_stage,
                (opp_close_date)::date AS close_date,
                ROW_NUMBER() OVER (
                    PARTITION BY opp_hr_lead
                    ORDER BY (opp_close_date) DESC
                ) AS rn
            FROM opportunity
            WHERE opp_hr_lead IS NOT NULL
        ),
        agg AS (
            SELECT
                opp_hr_lead,

                -- ✅ MES ACTUAL
                COUNT(*) FILTER (
                    WHERE close_date >= %(month_start)s
                    AND close_date < %(month_end)s
                    AND opp_stage = 'Closed Win'
                ) AS closed_win_month,

                COUNT(*) FILTER (
                    WHERE close_date >= %(month_start)s
                    AND close_date < %(month_end)s
                    AND opp_stage = 'Closed Lost'
                ) AS closed_lost_month,

                -- ✅ MES ANTERIOR (NUEVO)
                COUNT(*) FILTER (
                    WHERE close_date >= %(prev_month_start)s
                    AND close_date < %(prev_month_end)s
                    AND opp_stage = 'Closed Win'
                ) AS prev_closed_win_month,

                COUNT(*) FILTER (
                    WHERE close_date >= %(prev_month_start)s
                    AND close_date < %(prev_month_end)s
                    AND opp_stage = 'Closed Lost'
                ) AS prev_closed_lost_month,

                -- ✅ TOTALES
                COUNT(*) FILTER (
                    WHERE opp_stage = 'Closed Win'
                ) AS closed_win_total,

                COUNT(*) FILTER (
                    WHERE opp_stage = 'Closed Lost'
                ) AS closed_lost_total

            FROM base
            GROUP BY opp_hr_lead
        ),
        last_20 AS (
            SELECT *
            FROM base
            WHERE rn <= 20
        ),
        conv AS (
            SELECT
                opp_hr_lead,
                COUNT(*) AS last_20_count,
                COUNT(*) FILTER (WHERE opp_stage = 'Closed Win') AS last_20_win,
                CASE
                    WHEN COUNT(*) = 0 THEN NULL
                    ELSE COUNT(*) FILTER (WHERE opp_stage = 'Closed Win')::decimal
                        / COUNT(*)
                END AS conversion_rate_last_20
            FROM last_20
            GROUP BY opp_hr_lead
        )
        SELECT
            a.opp_hr_lead,
            a.closed_win_month,
            a.closed_lost_month,
            a.prev_closed_win_month,
            a.prev_closed_lost_month,
            a.closed_win_total,
            a.closed_lost_total,
            c.last_20_count,
            c.last_20_win,
            c.conversion_rate_last_20
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
                        "month_start": month_start,
                        "month_end": month_end,
                        "prev_month_start": prev_month_start,
                        "prev_month_end": prev_month_end,
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
            conversion = (
                float(r["conversion_rate_last_20"])
                if r["conversion_rate_last_20"] is not None
                else None
            )
            metrics.append(
                {
                    "hr_lead": r["opp_hr_lead"],
                    "closed_win_month": r["closed_win_month"] or 0,
                    "closed_lost_month": r["closed_lost_month"] or 0,
                    "closed_win_total": r["closed_win_total"] or 0,
                    "closed_lost_total": r["closed_lost_total"] or 0,
                    "last_20_count": r["last_20_count"] or 0,
                    "last_20_win": r["last_20_win"] or 0,
                    "conversion_rate_last_20": conversion, 
                    "prev_closed_win_month": r["prev_closed_win_month"] or 0,
                    "prev_closed_lost_month": r["prev_closed_lost_month"] or 0,
                }
            )

        return jsonify(
            {
                "status": "ok",
                "month_start": month_start.isoformat(),
                "month_end": month_end.isoformat(),
                "metrics": metrics,
            }
        )
    