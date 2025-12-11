# recruiter_metrics_routes.py
import logging
from datetime import date, datetime, timedelta, timezone

from flask import jsonify, render_template, g
from psycopg2.extras import RealDictCursor

from db import get_connection

logger = logging.getLogger(__name__)

BOGOTA_TZ = timezone(timedelta(hours=-5))


def _current_month_bounds():
    """(legacy) Mes actual – ya no se usa, pero lo dejamos por si se requiere luego."""
    now = datetime.now(BOGOTA_TZ).date()
    month_start = date(now.year, now.month, 1)
    if now.month == 12:
        month_end = date(now.year + 1, 1, 1)
    else:
        month_end = date(now.year, now.month + 1, 1)
    return month_start, month_end


def _previous_month_bounds():
    """(legacy) Mes anterior – ya no se usa, pero lo dejamos por si se requiere luego."""
    now = datetime.now(BOGOTA_TZ).date()
    first_of_this_month = date(now.year, now.month, 1)
    prev_month_end = first_of_this_month
    if now.month == 1:
        prev_month_start = date(now.year - 1, 12, 1)
    else:
        prev_month_start = date(now.year, now.month - 1, 1)
    return prev_month_start, prev_month_end


def _rolling_30d_bounds():
    """
    Devuelve (window_start, window_end, prev_window_start, prev_window_end) en fecha.

    - window_start: hace 29 días (inclusive) → incluye hoy (30 días en total)
    - window_end: mañana (exclusivo)
    - prev_window: los 30 días inmediatamente anteriores a window_start
    """
    today = datetime.now(BOGOTA_TZ).date()
    window_end = today + timedelta(days=1)       # exclusivo
    window_start = today - timedelta(days=29)    # 30 días incluyendo hoy

    prev_window_end = window_start               # exclusivo
    prev_window_start = window_start - timedelta(days=30)

    return window_start, window_end, prev_window_start, prev_window_end


def register_recruiter_metrics_routes(app):
    @app.route("/recruiter-metrics", methods=["GET"])
    def api_recruiter_metrics():
        """
        Métricas agregadas por opp_hr_lead (+ nombre de la tabla users), usando
        una ventana móvil de 30 días:

        - hr_lead_email (correo de opp_hr_lead)
        - hr_lead_name  (users.user_name)

        Ventana 30 días (antes "mes actual"):
        - closed_win_month
        - closed_lost_month

        Ventana 30 días previa (antes "mes anterior"):
        - prev_closed_win_month
        - prev_closed_lost_month

        Totales lifetime:
        - closed_win_total
        - closed_lost_total

        Conversión últimos 30 días:
        - last_20_count        (total de oportunidades cerradas en últimos 30 días)
        - last_20_win          (cuántas de esas son Close Win)
        - conversion_rate_last_20  (0–1)  → % de Close Win en últimos 30 días

        Conversión lifetime:
        - conversion_rate_lifetime (0–1) Close Win / (Close Win + Closed Lost)
        """

        window_start, window_end, prev_window_start, prev_window_end = _rolling_30d_bounds()

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

                -- ✅ ÚLTIMOS 30 DÍAS (antes "mes actual")
                COUNT(*) FILTER (
                    WHERE close_date >= %(month_start)s
                      AND close_date < %(month_end)s
                      AND opp_stage = 'Close Win'
                ) AS closed_win_month,

                COUNT(*) FILTER (
                    WHERE close_date >= %(month_start)s
                      AND close_date < %(month_end)s
                      AND opp_stage = 'Closed Lost'
                ) AS closed_lost_month,

                -- ✅ 30 DÍAS PREVIOS (antes "mes anterior")
                COUNT(*) FILTER (
                    WHERE close_date >= %(prev_month_start)s
                      AND close_date < %(prev_month_end)s
                      AND opp_stage = 'Close Win'
                ) AS prev_closed_win_month,

                COUNT(*) FILTER (
                    WHERE close_date >= %(prev_month_start)s
                      AND close_date < %(prev_month_end)s
                      AND opp_stage = 'Closed Lost'
                ) AS prev_closed_lost_month,

                -- ✅ TOTALES LIFETIME
                COUNT(*) FILTER (
                    WHERE opp_stage = 'Close Win'
                ) AS closed_win_total,

                COUNT(*) FILTER (
                    WHERE opp_stage = 'Closed Lost'
                ) AS closed_lost_total

            FROM base
            GROUP BY opp_hr_lead
        ),
        conv AS (
            -- ✅ Conversión sobre oportunidades cerradas en los últimos 30 días
            SELECT
                opp_hr_lead,
                COUNT(*) FILTER (
                    WHERE close_date >= %(month_start)s
                      AND close_date < %(month_end)s
                ) AS last_20_count,
                COUNT(*) FILTER (
                    WHERE close_date >= %(month_start)s
                      AND close_date < %(month_end)s
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
                        # 🔹 Estos params ahora representan la ventana de 30 días
                        "month_start": window_start,
                        "month_end": window_end,
                        "prev_month_start": prev_window_start,
                        "prev_month_end": prev_window_end,
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
            conversion_30d = (
                float(r["conversion_rate_last_20"])
                if r["conversion_rate_last_20"] is not None
                else None
            )
            conversion_lifetime = (
                float(r["conversion_rate_lifetime"])
                if r["conversion_rate_lifetime"] is not None
                else None
            )

            email = r["opp_hr_lead"]
            name = r.get("user_name") or email  # fallback al correo si no hay nombre

            metrics.append(
                {
                    "hr_lead_email": email,
                    "hr_lead_name": name,
                    "hr_lead": email,  # compatibilidad JS

                    "closed_win_month": r["closed_win_month"] or 0,
                    "closed_lost_month": r["closed_lost_month"] or 0,
                    "closed_win_total": r["closed_win_total"] or 0,
                    "closed_lost_total": r["closed_lost_total"] or 0,

                    # ahora significan "últimos 30 días"
                    "last_20_count": r["last_20_count"] or 0,
                    "last_20_win": r["last_20_win"] or 0,
                    "conversion_rate_last_20": conversion_30d,

                    # comparación con ventana anterior de 30 días
                    "prev_closed_win_month": r["prev_closed_win_month"] or 0,
                    "prev_closed_lost_month": r["prev_closed_lost_month"] or 0,

                    # 🎯 NUEVO: conversión lifetime
                    "conversion_rate_lifetime": conversion_lifetime,
                }
            )

        current_user_email = getattr(g, "user_email", None)

        return jsonify(
            {
                "status": "ok",
                "month_start": window_start.isoformat(),
                "month_end": window_end.isoformat(),
                "metrics": metrics,
                "current_user_email": current_user_email,
            }
        )