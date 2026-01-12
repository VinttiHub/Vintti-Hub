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


def _float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def register_recruiter_metrics_routes(app):
    @app.route("/recruiter-metrics", methods=["GET"])
    def api_recruiter_metrics():
        window_start, window_end, prev_start, prev_end, disp_start, disp_end, err = _parse_date_range_args()
        if err:
            return jsonify({"status": "error", "message": err}), 400

        if disp_end is None:
            # fallback: display end defaults to the inclusive day before window_end
            disp_end = window_end - timedelta(days=1)

        left90_window_start = window_start
        left90_window_end = window_end
        left90_display_start = disp_start
        left90_display_end = disp_end

        sql = """
        WITH base AS (
            SELECT
                o.opportunity_id,
                o.opp_hr_lead,
                u.user_name,
                o.opp_stage,
                o.cantidad_entrevistados,
                (o.opp_close_date)::date AS close_date,
                -- usamos NDA/start_date como proxy de inicio y caemos al close_date si no existe
                COALESCE(
                    o.nda_signature_or_start_date::date,
                    o.opp_close_date::date
                ) AS start_reference_date
            FROM opportunity o
            LEFT JOIN users u
                ON u.email_vintti = o.opp_hr_lead
            WHERE o.opp_hr_lead IS NOT NULL
        ),
        first_batches AS (
            SELECT
                b.opportunity_id,
                MIN(b.presentation_date)::date AS first_batch_date
            FROM batch b
            WHERE b.presentation_date IS NOT NULL
            GROUP BY b.opportunity_id
        ),
        sent_candidates AS (
            SELECT
                b.opp_hr_lead,
                b.opportunity_id,
                b.cantidad_entrevistados,
                cb.candidate_id,
                cb.batch_id,
                bt.batch_number,
                bt.presentation_date::date AS sent_date,
                cb.status AS candidate_status
            FROM base b
            JOIN batch bt
                ON bt.opportunity_id = b.opportunity_id
            JOIN candidates_batches cb
                ON cb.batch_id = bt.batch_id
            WHERE cb.candidate_id IS NOT NULL
              AND bt.presentation_date IS NOT NULL
        ),
        sent_in_window AS (
            SELECT
                *
            FROM sent_candidates
            WHERE sent_date >= %(win_start)s
              AND sent_date <  %(win_end)s  -- rango aplicado al evento “batch enviado”
        ),
        ratio_per_opportunity AS (
            SELECT
                s.opp_hr_lead,
                s.opportunity_id,
                MAX(s.cantidad_entrevistados) AS cantidad_entrevistados,
                COUNT(DISTINCT s.candidate_id) AS sent_candidate_count,
                CASE
                    WHEN COALESCE(MAX(s.cantidad_entrevistados), 0) <= 0 THEN NULL
                    ELSE COUNT(DISTINCT s.candidate_id)::decimal
                         / NULLIF(MAX(s.cantidad_entrevistados), 0)
                END AS sent_vs_interview_ratio
            FROM sent_in_window s
            GROUP BY s.opp_hr_lead, s.opportunity_id
        ),
        ratio_by_lead AS (
            SELECT
                opp_hr_lead,
                AVG(sent_vs_interview_ratio) AS avg_sent_vs_interview_ratio,
                COUNT(*) FILTER (WHERE sent_vs_interview_ratio IS NOT NULL) AS ratio_sample_count,
                SUM(sent_candidate_count) AS ratio_total_sent_candidates,
                SUM(cantidad_entrevistados) AS ratio_total_interviewed
            FROM ratio_per_opportunity
            GROUP BY opp_hr_lead
        ),
        pipeline_rates AS (
            SELECT
                opp_hr_lead,
                COUNT(*) AS sent_candidate_count,
                COUNT(*) FILTER (
                    WHERE COALESCE(candidate_status, '') <> 'Client rejected CV'
                ) AS interview_eligible_candidate_count,
                COUNT(*) FILTER (
                    WHERE candidate_status IN (
                        'Client hired',
                        'Client rejected after interviewing',
                        'Client interviewing/testing'
                    )
                ) AS interviewed_candidate_count
            FROM sent_in_window
            GROUP BY opp_hr_lead
        ),
        hired_by_lead AS (
            SELECT
                s.opp_hr_lead,
                COUNT(DISTINCT (s.opportunity_id::text || '-' || s.candidate_id::text)) AS hired_candidate_count
            FROM sent_in_window s
            JOIN hire_opportunity h
                ON h.opportunity_id = s.opportunity_id
               AND h.candidate_id = s.candidate_id
            GROUP BY s.opp_hr_lead
        ),
        agg AS (
            SELECT
                b.opp_hr_lead,
                MAX(b.user_name) AS user_name,

                -- ✅ RANGO SELECCIONADO
                COUNT(*) FILTER (
                    WHERE b.close_date >= %(win_start)s
                      AND b.close_date <  %(win_end)s
                      AND b.opp_stage = 'Close Win'
                ) AS closed_win_month,

                COUNT(*) FILTER (
                    WHERE b.close_date >= %(win_start)s
                      AND b.close_date <  %(win_end)s
                      AND b.opp_stage = 'Closed Lost'
                ) AS closed_lost_month,

                -- ✅ RANGO ANTERIOR (mismo tamaño) para comparación
                COUNT(*) FILTER (
                    WHERE b.close_date >= %(prev_start)s
                      AND b.close_date <  %(prev_end)s
                      AND b.opp_stage = 'Close Win'
                ) AS prev_closed_win_month,

                COUNT(*) FILTER (
                    WHERE b.close_date >= %(prev_start)s
                      AND b.close_date <  %(prev_end)s
                      AND b.opp_stage = 'Closed Lost'
                ) AS prev_closed_lost_month,

                -- ✅ TOTALES LIFETIME
                COUNT(*) FILTER (WHERE b.opp_stage = 'Close Win')  AS closed_win_total,
                COUNT(*) FILTER (WHERE b.opp_stage = 'Closed Lost') AS closed_lost_total,

                -- Promedios: close date usa el mismo filtro del dashboard; open cae al start_date documentado
                AVG(
                    (b.close_date - b.start_reference_date)::numeric
                ) FILTER (
                    WHERE b.close_date >= %(win_start)s
                      AND b.close_date <  %(win_end)s
                      AND b.opp_stage = 'Close Win'
                      AND b.close_date IS NOT NULL
                      AND b.start_reference_date IS NOT NULL
                ) AS avg_days_to_close_win,

                AVG(
                    (b.close_date - b.start_reference_date)::numeric
                ) FILTER (
                    WHERE b.close_date >= %(win_start)s
                      AND b.close_date <  %(win_end)s
                      AND b.opp_stage = 'Closed Lost'
                      AND b.close_date IS NOT NULL
                      AND b.start_reference_date IS NOT NULL
                ) AS avg_days_to_close_lost,

                AVG(
                    (fb.first_batch_date - b.start_reference_date)::numeric
                ) FILTER (
                    WHERE fb.first_batch_date IS NOT NULL
                      AND b.start_reference_date IS NOT NULL
                      AND b.opp_stage NOT IN ('Close Win', 'Closed Lost')
                      AND b.start_reference_date >= %(win_start)s
                      AND b.start_reference_date <  %(win_end)s
                ) AS avg_days_to_first_batch_open,

                AVG(
                    (fb.first_batch_date - b.start_reference_date)::numeric
                ) FILTER (
                    WHERE fb.first_batch_date IS NOT NULL
                      AND b.start_reference_date IS NOT NULL
                      AND b.opp_stage IN ('Close Win', 'Closed Lost')
                      AND b.close_date >= %(win_start)s
                      AND b.close_date <  %(win_end)s
                ) AS avg_days_to_first_batch_closed

            FROM base b
            LEFT JOIN first_batches fb
                ON fb.opportunity_id = b.opportunity_id
            GROUP BY b.opp_hr_lead
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
            a.avg_days_to_close_win,
            a.avg_days_to_close_lost,
            a.avg_days_to_first_batch_open,
            a.avg_days_to_first_batch_closed,
            c.last_20_count,
            c.last_20_win,
            pr.sent_candidate_count,
            pr.interview_eligible_candidate_count,
            pr.interviewed_candidate_count,
            hb.hired_candidate_count,
            rbl.avg_sent_vs_interview_ratio,
            rbl.ratio_sample_count,
            rbl.ratio_total_sent_candidates,
            rbl.ratio_total_interviewed,
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
        LEFT JOIN pipeline_rates pr
            ON pr.opp_hr_lead = a.opp_hr_lead
        LEFT JOIN hired_by_lead hb
            ON hb.opp_hr_lead = a.opp_hr_lead
        LEFT JOIN ratio_by_lead rbl
            ON rbl.opp_hr_lead = a.opp_hr_lead
        ORDER BY a.opp_hr_lead;
        """

        churn_details_sql = """
        WITH churned AS (
            SELECT
                h.hire_opp_id AS hire_opportunity_id,
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
              AND h.end_date::date >= %(win_start)s
              AND h.end_date::date <  %(win_end)s
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

        left90_summary_sql = """
        WITH churned AS (
            SELECT
                h.hire_opp_id AS hire_opportunity_id,
                h.opportunity_id,
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
              AND h.end_date::date >= %(left90_start)s
              AND h.end_date::date <  %(left90_end)s
        )
        SELECT
            LOWER(o.opp_hr_lead) AS hr_lead_email,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE c.tenure_days IS NOT NULL) AS tenure_known,
            COUNT(*) FILTER (WHERE c.tenure_days IS NULL) AS tenure_unknown
        FROM churned c
        LEFT JOIN opportunity o
            ON o.opportunity_id = c.opportunity_id
        WHERE o.opp_hr_lead IS NOT NULL
        GROUP BY LOWER(o.opp_hr_lead);
        """

        opportunity_details_sql = """
        SELECT
            o.opportunity_id,
            o.opp_hr_lead AS hr_lead_email,
            u.user_name AS hr_lead_name,
            o.opp_stage AS opportunity_stage,
            o.opp_close_date::date AS close_date,
            o.opp_position_name AS opportunity_title,
            a.client_name AS opportunity_client_name
        FROM opportunity o
        LEFT JOIN users u
            ON LOWER(u.email_vintti) = LOWER(o.opp_hr_lead)
        LEFT JOIN account a
            ON a.account_id = o.account_id
        WHERE o.opp_hr_lead IS NOT NULL
          AND o.opp_stage IN ('Close Win', 'Closed Lost')
        ORDER BY o.opp_close_date DESC NULLS LAST, o.opportunity_id;
        """

        duration_details_sql = """
        WITH base AS (
            SELECT
                o.opportunity_id,
                LOWER(o.opp_hr_lead) AS hr_lead_email,
                o.opp_hr_lead,
                o.opp_stage,
                o.opp_close_date::date AS close_date,
                COALESCE(
                    o.nda_signature_or_start_date::date,
                    o.opp_close_date::date
                ) AS start_reference_date,
                o.opp_position_name AS opportunity_title,
                a.client_name AS opportunity_client_name
            FROM opportunity o
            LEFT JOIN account a
                ON a.account_id = o.account_id
            WHERE o.opp_hr_lead IS NOT NULL
        ),
        first_batches AS (
            SELECT
                b.opportunity_id,
                MIN(b.presentation_date)::date AS first_batch_date
            FROM batch b
            WHERE b.presentation_date IS NOT NULL
            GROUP BY b.opportunity_id
        )
        SELECT
            b.hr_lead_email,
            b.opportunity_id,
            b.opportunity_title,
            b.opportunity_client_name,
            b.opp_stage,
            b.close_date,
            b.start_reference_date,
            fb.first_batch_date,
            d.metric_type,
            d.duration_days
        FROM base b
        LEFT JOIN first_batches fb
            ON fb.opportunity_id = b.opportunity_id
        CROSS JOIN LATERAL (
            VALUES
                (
                    'avgCloseWin',
                    CASE
                        WHEN b.opp_stage = 'Close Win'
                          AND b.close_date >= %(win_start)s
                          AND b.close_date <  %(win_end)s
                          AND b.close_date IS NOT NULL
                          AND b.start_reference_date IS NOT NULL
                        THEN (b.close_date - b.start_reference_date)::int
                        ELSE NULL
                    END
                ),
                (
                    'avgCloseLost',
                    CASE
                        WHEN b.opp_stage = 'Closed Lost'
                          AND b.close_date >= %(win_start)s
                          AND b.close_date <  %(win_end)s
                          AND b.close_date IS NOT NULL
                          AND b.start_reference_date IS NOT NULL
                        THEN (b.close_date - b.start_reference_date)::int
                        ELSE NULL
                    END
                ),
                (
                    'avgBatchOpen',
                    CASE
                        WHEN b.opp_stage NOT IN ('Close Win', 'Closed Lost')
                          AND b.start_reference_date IS NOT NULL
                          AND b.start_reference_date >= %(win_start)s
                          AND b.start_reference_date <  %(win_end)s
                          AND fb.first_batch_date IS NOT NULL
                        THEN (fb.first_batch_date - b.start_reference_date)::int
                        ELSE NULL
                    END
                ),
                (
                    'avgBatchClosed',
                    CASE
                        WHEN b.opp_stage IN ('Close Win', 'Closed Lost')
                          AND b.close_date >= %(win_start)s
                          AND b.close_date <  %(win_end)s
                          AND fb.first_batch_date IS NOT NULL
                          AND b.start_reference_date IS NOT NULL
                        THEN (fb.first_batch_date - b.start_reference_date)::int
                        ELSE NULL
                    END
                )
        ) AS d(metric_type, duration_days)
        WHERE d.duration_days IS NOT NULL
        ORDER BY b.close_date DESC NULLS LAST, b.opportunity_id;
        """

        pipeline_details_sql = """
        WITH base AS (
            SELECT
                o.opportunity_id,
                LOWER(o.opp_hr_lead) AS hr_lead_email,
                o.opp_hr_lead,
                u.user_name AS hr_lead_name,
                o.opp_position_name AS opportunity_title,
                a.client_name AS opportunity_client_name
            FROM opportunity o
            LEFT JOIN users u
                ON LOWER(u.email_vintti) = LOWER(o.opp_hr_lead)
            LEFT JOIN account a
                ON a.account_id = o.account_id
            WHERE o.opp_hr_lead IS NOT NULL
        ),
        batches AS (
            SELECT
                b.batch_id,
                b.batch_number,
                b.opportunity_id,
                b.presentation_date::date AS sent_date
            FROM batch b
            WHERE b.presentation_date IS NOT NULL
        ),
        sent_candidates AS (
            SELECT
                b.hr_lead_email,
                b.opp_hr_lead,
                b.hr_lead_name,
                b.opportunity_id,
                b.opportunity_title,
                b.opportunity_client_name,
                cb.candidate_id,
                cb.batch_id,
                bt.batch_number,
                bt.sent_date,
                cb.status AS candidate_status
            FROM base b
            JOIN batches bt
                ON bt.opportunity_id = b.opportunity_id
            JOIN candidates_batches cb
                ON cb.batch_id = bt.batch_id
            WHERE cb.candidate_id IS NOT NULL
        )
        SELECT
            sc.hr_lead_email,
            sc.opp_hr_lead AS hr_lead_raw,
            sc.hr_lead_name,
            sc.opportunity_id,
            sc.opportunity_title,
            sc.opportunity_client_name,
            sc.candidate_id,
            c.name AS candidate_name,
            c.email AS candidate_email,
            sc.batch_id,
            sc.batch_number,
            sc.sent_date,
            sc.candidate_status,
            CASE
                WHEN COALESCE(sc.candidate_status, '') <> 'Client rejected CV'
                THEN TRUE
                ELSE FALSE
            END AS is_interview_eligible,
            CASE
                WHEN sc.candidate_status IN (
                    'Client hired',
                    'Client rejected after interviewing',
                    'Client interviewing/testing'
                )
                THEN TRUE
                ELSE FALSE
            END AS is_interviewed,
            CASE
                WHEN h.hire_opp_id IS NOT NULL THEN TRUE
                ELSE FALSE
            END AS is_hired
        FROM sent_candidates sc
        LEFT JOIN candidates c
            ON c.candidate_id = sc.candidate_id
        LEFT JOIN hire_opportunity h
            ON h.opportunity_id = sc.opportunity_id
           AND h.candidate_id = sc.candidate_id
        WHERE sc.sent_date >= %(win_start)s
          AND sc.sent_date <  %(win_end)s
        ORDER BY sc.hr_lead_email, sc.sent_date DESC NULLS LAST, sc.opportunity_id, sc.candidate_id;
        """

        sent_vs_interview_details_sql = """
        WITH base AS (
            SELECT
                o.opportunity_id,
                LOWER(o.opp_hr_lead) AS hr_lead_email,
                o.opp_hr_lead AS hr_lead_raw,
                o.opp_position_name AS opportunity_title,
                a.client_name AS opportunity_client_name,
                o.cantidad_entrevistados
            FROM opportunity o
            LEFT JOIN account a
                ON a.account_id = o.account_id
            WHERE o.opp_hr_lead IS NOT NULL
        ),
        sent_counts AS (
            SELECT
                bt.opportunity_id,
                COUNT(DISTINCT cb.candidate_id) AS sent_candidate_count
            FROM batch bt
            JOIN candidates_batches cb
                ON cb.batch_id = bt.batch_id
            WHERE cb.candidate_id IS NOT NULL
              AND bt.presentation_date IS NOT NULL
              AND bt.presentation_date::date >= %(win_start)s
              AND bt.presentation_date::date <  %(win_end)s
            GROUP BY bt.opportunity_id
        )
        SELECT
            b.hr_lead_email,
            b.hr_lead_raw,
            b.opportunity_id,
            b.opportunity_title,
            b.opportunity_client_name,
            b.cantidad_entrevistados,
            sc.sent_candidate_count,
            CASE
                WHEN COALESCE(b.cantidad_entrevistados, 0) <= 0 THEN NULL
                ELSE sc.sent_candidate_count::decimal
                     / NULLIF(b.cantidad_entrevistados, 0)
            END AS ratio
        FROM base b
        JOIN sent_counts sc
            ON sc.opportunity_id = b.opportunity_id
        ORDER BY b.hr_lead_email, sc.sent_candidate_count DESC, b.opportunity_id;
        """

        churn_detail_rows = []
        opportunity_detail_rows = []
        left90_summary_rows = []
        duration_detail_rows = []
        pipeline_detail_rows = []
        sent_vs_interview_detail_rows = []
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
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    left90_summary_sql,
                    {
                        "left90_start": left90_window_start,
                        "left90_end": left90_window_end,
                    },
                )
                left90_summary_rows = cur.fetchall()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(opportunity_details_sql)
                opportunity_detail_rows = cur.fetchall()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    duration_details_sql,
                    {
                        "win_start": window_start,
                        "win_end": window_end,
                    },
                )
                duration_detail_rows = cur.fetchall()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    pipeline_details_sql,
                    {
                        "win_start": window_start,
                        "win_end": window_end,
                    },
                )
                pipeline_detail_rows = cur.fetchall()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    sent_vs_interview_details_sql,
                    {
                        "win_start": window_start,
                        "win_end": window_end,
                    },
                )
                sent_vs_interview_detail_rows = cur.fetchall()
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

            avg_days_close_win = _float_or_none(r.get("avg_days_to_close_win"))
            avg_days_close_lost = _float_or_none(r.get("avg_days_to_close_lost"))
            avg_days_batch_open = _float_or_none(r.get("avg_days_to_first_batch_open"))
            avg_days_batch_closed = _float_or_none(r.get("avg_days_to_first_batch_closed"))

            sent_candidates = int(r.get("sent_candidate_count") or 0)
            interview_eligible_candidates = int(r.get("interview_eligible_candidate_count") or 0)
            interviewed_candidates = int(r.get("interviewed_candidate_count") or 0)
            hired_candidates = int(r.get("hired_candidate_count") or 0)
            avg_sent_vs_interview_ratio = _float_or_none(r.get("avg_sent_vs_interview_ratio"))
            ratio_sample_count = int(r.get("ratio_sample_count") or 0)
            ratio_total_sent = int(r.get("ratio_total_sent_candidates") or 0)
            ratio_total_interviewed_raw = r.get("ratio_total_interviewed")
            if ratio_total_interviewed_raw is None:
                ratio_total_interviewed = None
            else:
                try:
                    ratio_total_interviewed = int(ratio_total_interviewed_raw)
                except (TypeError, ValueError):
                    ratio_total_interviewed = _float_or_none(ratio_total_interviewed_raw)

            interview_pct = (
                interviewed_candidates / interview_eligible_candidates
                if interview_eligible_candidates
                else None
            )
            hire_pct = (hired_candidates / sent_candidates) if sent_candidates else None

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
                    "avg_days_to_close_win": avg_days_close_win,
                    "avg_days_to_close_lost": avg_days_close_lost,
                    "avg_days_to_first_batch_open": avg_days_batch_open,
                    "avg_days_to_first_batch_closed": avg_days_batch_closed,
                    "interview_rate": {
                        "pct": interview_pct,
                        "interviewed": interviewed_candidates,
                        "sent": interview_eligible_candidates,
                    },
                    "hire_rate": {
                        "pct": hire_pct,
                        "hired": hired_candidates,
                        "sent": sent_candidates,
                    },
                    "avg_sent_vs_interview_ratio": avg_sent_vs_interview_ratio,
                    "sent_vs_interview_sample_count": ratio_sample_count,
                    "sent_vs_interview_totals": {
                        "sent": ratio_total_sent,
                        "interviewed": ratio_total_interviewed,
                    },

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
        opportunity_details_by_lead = {}
        left90_summary_by_lead = {}
        duration_details_by_lead = {}
        pipeline_details_by_lead = {}
        sent_vs_interview_details_by_lead = {}

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

        for row in left90_summary_rows:
            lead_key = (row.get("hr_lead_email") or "").lower()
            if not lead_key:
                continue
            left90_summary_by_lead[lead_key] = {
                "total": int(row.get("total") or 0),
                "tenure_known": int(row.get("tenure_known") or 0),
                "tenure_unknown": int(row.get("tenure_unknown") or 0),
            }

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

        for item in metrics:
            lead_key = (item.get("hr_lead_email") or item.get("hr_lead") or "").lower()
            left90_summary = left90_summary_by_lead.get(lead_key, None)
            if not left90_summary:
                item["left90_total"] = 0
                item["left90_within_90"] = 0
                item["left90_tenure_known"] = 0
                item["left90_tenure_unknown"] = 0
                item["left90_rate"] = None
                continue
            item["left90_total"] = left90_summary["total"]
            item["left90_within_90"] = left90_summary["total"]
            item["left90_tenure_known"] = left90_summary["tenure_known"]
            item["left90_tenure_unknown"] = left90_summary["tenure_unknown"]
            item["left90_rate"] = None

        if overall_churn_summary["tenure_known"]:
            overall_churn_summary["within_90_rate"] = (
                overall_churn_summary["within_90"] / overall_churn_summary["tenure_known"]
            )
        else:
            overall_churn_summary["within_90_rate"] = None

        current_user_email = getattr(g, "user_email", None)

        for row in opportunity_detail_rows:
            lead_key = (row.get("hr_lead_email") or "").lower()
            if not lead_key:
                continue
            details = opportunity_details_by_lead.setdefault(lead_key, [])
            details.append(
                {
                    "opportunity_id": row.get("opportunity_id"),
                    "opportunity_title": row.get("opportunity_title"),
                    "opportunity_client_name": row.get("opportunity_client_name"),
                    "opportunity_stage": row.get("opportunity_stage"),
                    "close_date": _iso_date_or_none(row.get("close_date")),
                }
            )
        for row in duration_detail_rows:
            lead_key = (row.get("hr_lead_email") or row.get("opp_hr_lead") or "").lower()
            if not lead_key:
                continue
            metric_type = row.get("metric_type")
            if not metric_type:
                continue
            lead_bucket = duration_details_by_lead.setdefault(lead_key, {})
            metric_bucket = lead_bucket.setdefault(metric_type, [])
            duration_days = row.get("duration_days")
            try:
                duration_days = int(duration_days) if duration_days is not None else None
            except (TypeError, ValueError):
                duration_days = None
            metric_bucket.append(
                {
                    "opportunity_id": row.get("opportunity_id"),
                    "opportunity_title": row.get("opportunity_title"),
                    "opportunity_client_name": row.get("opportunity_client_name"),
                    "opportunity_stage": row.get("opp_stage") or row.get("opportunity_stage"),
                    "close_date": _iso_date_or_none(row.get("close_date")),
                    "start_reference_date": _iso_date_or_none(row.get("start_reference_date")),
                    "first_batch_date": _iso_date_or_none(row.get("first_batch_date")),
                    "duration_days": duration_days,
                }
            )

        for row in pipeline_detail_rows:
            lead_key = (row.get("hr_lead_email") or "").lower()
            if not lead_key:
                continue
            details = pipeline_details_by_lead.setdefault(lead_key, [])
            batch_number = row.get("batch_number")
            try:
                batch_number = int(batch_number) if batch_number is not None else None
            except (TypeError, ValueError):
                batch_number = None
            details.append(
                {
                    "candidate_id": row.get("candidate_id"),
                    "candidate_name": row.get("candidate_name"),
                    "candidate_email": row.get("candidate_email"),
                    "candidate_status": row.get("candidate_status"),
                    "opportunity_id": row.get("opportunity_id"),
                    "opportunity_title": row.get("opportunity_title"),
                    "opportunity_client_name": row.get("opportunity_client_name"),
                    "batch_id": row.get("batch_id"),
                    "batch_number": batch_number,
                    "sent_date": _iso_date_or_none(row.get("sent_date")),
                    "is_interview_eligible": bool(row.get("is_interview_eligible")),
                    "is_interviewed": bool(row.get("is_interviewed")),
                    "is_hired": bool(row.get("is_hired")),
                }
            )
        for row in sent_vs_interview_detail_rows:
            lead_key = (row.get("hr_lead_email") or "").lower()
            if not lead_key:
                continue
            details = sent_vs_interview_details_by_lead.setdefault(lead_key, [])
            interviewed_raw = row.get("cantidad_entrevistados")
            try:
                interviewed_val = int(interviewed_raw) if interviewed_raw is not None else None
            except (TypeError, ValueError):
                interviewed_val = None
            sent_count = int(row.get("sent_candidate_count") or 0)
            details.append(
                {
                    "opportunity_id": row.get("opportunity_id"),
                    "opportunity_title": row.get("opportunity_title"),
                    "opportunity_client_name": row.get("opportunity_client_name"),
                    "sent_candidate_count": sent_count,
                    "interviewed_count": interviewed_val,
                    "ratio": _float_or_none(row.get("ratio")),
                }
            )

        return jsonify(
            {
                "status": "ok",
                # compatibilidad con tu JS
                "month_start": window_start.isoformat(),
                "month_end": window_end.isoformat(),  # exclusivo
                # 👇 para pintar el picker bonito
                "range_start": disp_start.isoformat(),
                "range_end": disp_end.isoformat(),  # inclusive
                "left90_range_start": left90_display_start.isoformat(),
                "left90_range_end": left90_display_end.isoformat(),
                "metrics": metrics,
                # Churn data is requested by the non-React Recruiter Power UI:
                #  - summary counts live in each metric row (per recruiter)
                #  - churn_details drives the detail table (per hire/opportunity)
                #  - churn_summary gives overall totals for the selected window
                "churn_details": churn_details,
                "churn_summary": overall_churn_summary,
                "opportunity_details": opportunity_details_by_lead,
                "duration_details": duration_details_by_lead,
                "pipeline_details": pipeline_details_by_lead,
                "sent_vs_interview_details": sent_vs_interview_details_by_lead,
                "current_user_email": current_user_email,
            }
        )
