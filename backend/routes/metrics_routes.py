import logging
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from psycopg2.extras import execute_values

from db import get_connection

bp = Blueprint('metrics', __name__)


@bp.route('/data/light', methods=['GET'])
def data_light():
    """
    Devuelve un resumen ligero por cuenta:
      - trr: Recruiting revenue (solo hires activos)
      - tsf: Staffing fee       (solo hires activos)
      - tsr: Staffing (salary + fee)
    """
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            WITH h_active AS (
              SELECT DISTINCT ON (opportunity_id, candidate_id)
                     opportunity_id,
                     candidate_id,
                     salary,
                     fee,
                     revenue,
                     start_date
              FROM hire_opportunity
              WHERE end_date IS NULL
              ORDER BY opportunity_id, candidate_id, start_date DESC NULLS LAST
            )
            SELECT
              a.account_id,
              a.client_name,
              a.priority,
              COALESCE(SUM(CASE WHEN o.opp_model ILIKE 'recruiting' THEN COALESCE(h.revenue,0) END), 0) AS trr,
              COALESCE(SUM(CASE WHEN o.opp_model ILIKE 'staffing'   THEN COALESCE(h.fee,    0) END), 0) AS tsf,
              COALESCE(SUM(CASE WHEN o.opp_model ILIKE 'staffing'   THEN COALESCE(h.salary, 0) + COALESCE(h.fee, 0) END), 0) AS tsr
            FROM account a
            LEFT JOIN opportunity o ON o.account_id = a.account_id
            LEFT JOIN h_active h     ON h.opportunity_id = o.opportunity_id
            GROUP BY a.account_id, a.client_name
            ORDER BY LOWER(a.client_name) ASC;
        """)

        rows = cur.fetchall()
        cols = [c[0] for c in cur.description]
        data = [dict(zip(cols, row)) for row in rows]

        cur.close()
        conn.close()
        return jsonify(data)
    except Exception as exc:
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(exc)}), 500


@bp.route('/opportunities/light')
def get_opportunities_light():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                o.opportunity_id,
                o.account_id,
                o.opp_stage,
                o.opp_position_name,
                o.opp_type,
                o.opp_model,
                o.opp_hr_lead,
                o.comments,
                o.nda_signature_or_start_date,
                o.opp_close_date,
                o.expected_fee,
                o.expected_revenue,
                u.user_name AS sales_lead_name,
                a.client_name AS client_name
            FROM opportunity o
            LEFT JOIN users u ON o.opp_sales_lead = u.email_vintti
            LEFT JOIN account a ON o.account_id = a.account_id
        """)
        rows = cursor.fetchall()
        colnames = [desc[0] for desc in cursor.description]
        data = [dict(zip(colnames, row)) for row in rows]

        cursor.close()
        conn.close()

        return jsonify(data)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route('/data')
def get_accounts():
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM account")
        accounts_rows = cursor.fetchall()
        accounts_columns = [desc[0] for desc in cursor.description]
        accounts = [dict(zip(accounts_columns, row)) for row in accounts_rows]

        for account in accounts:
            account_id = account['account_id']

            cursor.execute("SELECT opportunity_id, opp_model FROM opportunity WHERE account_id = %s", (account_id,))
            opp_rows = cursor.fetchall()
            if not opp_rows:
                continue

            opp_ids = [r[0] for r in opp_rows]
            opp_model_map = {r[0]: r[1] for r in opp_rows}

            cursor.execute("""
                SELECT h.opportunity_id, h.salary, h.fee, h.revenue
                FROM hire_opportunity h
                WHERE h.opportunity_id = ANY(%s) AND h.end_date IS NULL
            """, (opp_ids,))

            trr = tsf = tsr = 0
            for opp_id, salary, fee, revenue in cursor.fetchall():
                model = opp_model_map.get(opp_id)
                if model == 'Recruiting':
                    trr += (revenue or 0)
                elif model == 'Staffing':
                    tsf += (fee or 0)
                    tsr += ((salary or 0) + (fee or 0))

            cursor.execute("""
                UPDATE account
                SET trr = %s, tsf = %s, tsr = %s
                WHERE account_id = %s
            """, (trr, tsf, tsr, account_id))

            account['trr'] = trr
            account['tsf'] = tsf
            account['tsr'] = tsr

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify(accounts)

    except Exception as exc:
        print("Error en /data:", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route('/accounts/status/summary', methods=['POST', 'OPTIONS'])
def accounts_status_summary():
    if request.method == 'OPTIONS':
        return ('', 204)

    payload = request.get_json(silent=True) or {}
    account_ids = payload.get('account_ids') or []
    if not account_ids:
        return jsonify([])

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            WITH opps AS (
              SELECT
                account_id,
                COUNT(*)                    AS total_opps,
                COUNT(*) FILTER (WHERE lower(opp_stage) LIKE '%%lost%%') AS lost_opps,
                BOOL_OR(
                  lower(opp_stage) LIKE '%%sourc%%'
                  OR lower(opp_stage) LIKE '%%interview%%'
                  OR lower(opp_stage) LIKE '%%negotiat%%'
                  OR lower(opp_stage) LIKE '%%deep%%'
                ) AS has_pipeline
              FROM opportunity
              WHERE account_id = ANY(%s)
              GROUP BY account_id
            ),
            hires AS (
              SELECT
                o.account_id,
                COUNT(*) > 0 AS has_candidates,
                BOOL_OR(COALESCE(lower(h.status)='active', h.end_date IS NULL)) AS any_active
              FROM opportunity o
              JOIN hire_opportunity h ON h.opportunity_id = o.opportunity_id
              WHERE o.account_id = ANY(%s)
              GROUP BY o.account_id
            )
            SELECT
              a.account_id,
              COALESCE(hi.has_candidates, FALSE) AS has_candidates,
              COALESCE(hi.any_active, FALSE)     AS any_active_candidate,
              COALESCE(op.total_opps, 0) > 0     AS has_opps,
              COALESCE(op.has_pipeline, FALSE)   AS has_pipeline,
              (COALESCE(op.total_opps,0) > 0 AND COALESCE(op.lost_opps,0) = COALESCE(op.total_opps,0)) AS all_lost
            FROM account a
            LEFT JOIN opps  op ON op.account_id = a.account_id
            LEFT JOIN hires hi ON hi.account_id = a.account_id
            WHERE a.account_id = ANY(%s)
            ORDER BY a.account_id
        """, (account_ids, account_ids, account_ids))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        def decide(has_candidates, any_active, has_opps, has_pipeline, all_lost):
            if any_active:
                return 'Active Client'
            if has_candidates and not any_active:
                return 'Inactive Client'
            if (not has_opps) and (not has_candidates):
                return 'Lead'
            if all_lost and not has_candidates:
                return 'Lead Lost'
            if has_pipeline:
                return 'Lead in Process'
            if (not has_opps) and has_candidates:
                return 'Inactive Client'
            return 'Lead in Process'

        out = []
        for (acc_id, has_candidates, any_active, has_opps, has_pipeline, all_lost) in rows:
            out.append({
                "account_id": acc_id,
                "status": decide(has_candidates, any_active, has_opps, has_pipeline, all_lost)
            })
        return jsonify(out)
    except Exception as exc:
        import traceback
        logging.error("summary failed: %s\n%s", exc, traceback.format_exc())
        return jsonify([]), 200


@bp.route('/accounts/status/bulk_update', methods=['POST', 'OPTIONS', 'GET'])
def accounts_status_bulk_update():
    if request.method == 'OPTIONS':
        return ('', 204)
    if request.method == 'GET':
        return jsonify({"updated": 0}), 200

    payload = request.get_json(silent=True) or {}
    updates = payload.get('updates') or []
    if not updates:
        return jsonify({"updated": 0, "persisted": False}), 200

    rows_status = []
    rows_calc = []
    for item in updates:
        try:
            acc_id = int(item.get('account_id') or item.get('id') or item.get('accountId'))
        except (TypeError, ValueError):
            continue
        status = (item.get('status') or item.get('value') or '').strip() or None
        calc_status = (item.get('calculated_status') or '').strip() or None
        if status is not None:
            rows_status.append((acc_id, status))
        if calc_status is not None:
            rows_calc.append((acc_id, calc_status))

    updated_status = 0
    updated_calc = 0

    conn = get_connection()
    try:
        if rows_status:
            with conn:
                with conn.cursor() as cur:
                    execute_values(cur, "CREATE TEMP TABLE _upd_status(account_id INT, status TEXT) ON COMMIT DROP;", [])
                    execute_values(cur, "INSERT INTO _upd_status(account_id, status) VALUES %s", rows_status)
                    cur.execute("""
                        UPDATE account a
                           SET account_status = u.status,
                               account_status_updated_at = NOW(),
                               status_needs_refresh = FALSE
                          FROM _upd_status u
                         WHERE a.account_id = u.account_id;
                    """)
                    updated_status = cur.rowcount

        if rows_calc:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'account' AND column_name = 'calculated_status'
                    LIMIT 1
                """)
                has_col = cur.fetchone() is not None
                if has_col:
                    for acc_id, status in rows_calc:
                        cur.execute(
                            "UPDATE account SET calculated_status = %s WHERE account_id = %s",
                            (status, acc_id)
                        )
                        updated_calc += cur.rowcount
                    conn.commit()
        return jsonify({
            "updated": updated_status,
            "calculated_updated": updated_calc,
            "persisted": bool(rows_calc),
        }), 200
    except Exception as exc:
        conn.rollback()
        return jsonify({"updated": 0, "persisted": False, "note": str(exc)}), 200
    finally:
        conn.close()


@bp.route('/metrics/ts_history', methods=['GET'])
def ts_history():
    try:
        qs_from = (request.args.get('from') or '').strip()
        qs_to = (request.args.get('to') or '').strip()

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT date_trunc('month', MIN(start_date::timestamp))::date
            FROM hire_opportunity
            WHERE start_date IS NOT NULL;
        """)
        min_month = cur.fetchone()[0]

        today = datetime.utcnow().date().replace(day=1)
        last_full_month = (today - timedelta(days=1)).replace(day=1)

        def _ym_to_date(value):
            if not value:
                return None
            y, m = value.split('-')[:2]
            return datetime(int(y), int(m), 1).date()

        from_month = _ym_to_date(qs_from) or (min_month or last_full_month)
        to_month = _ym_to_date(qs_to) or last_full_month

        if to_month < from_month:
            cur.close(); conn.close()
            return jsonify([])

        cur.execute("""
            WITH params AS (
              SELECT %s::date AS from_month, %s::date AS to_month
            ),
            months AS (
              SELECT date_trunc('month', gs)::date AS month
              FROM params p,
                   generate_series(p.from_month, p.to_month, interval '1 month') gs
            ),
            staffing AS (
              SELECT
                h.candidate_id,
                h.opportunity_id,
                COALESCE(h.salary, 0)::numeric AS salary,
                COALESCE(h.fee, 0)::numeric AS fee,
                h.start_date::date AS start_date,
                h.end_date::date AS end_date
              FROM hire_opportunity h
              JOIN opportunity o ON o.opportunity_id = h.opportunity_id
              WHERE lower(o.opp_model) LIKE 'staffing%%'
                AND h.start_date IS NOT NULL
            ),
            eom AS (
              SELECT
                m.month,
                (m.month + INTERVAL '1 month' - INTERVAL '1 day')::date AS month_end
              FROM months m
            )
            SELECT
              to_char(e.month, 'YYYY-MM') AS month,
              COALESCE(SUM(CASE
                WHEN s.start_date <= e.month_end
                 AND (s.end_date IS NULL OR s.end_date > e.month_end)
                THEN s.salary + s.fee END), 0)::bigint AS tsr,
              COALESCE(SUM(CASE
                WHEN s.start_date <= e.month_end
                 AND (s.end_date IS NULL OR s.end_date > e.month_end)
                THEN s.fee END), 0)::bigint AS tsf,
              COALESCE(COUNT(*) FILTER (
                WHERE s.start_date <= e.month_end
                  AND (s.end_date IS NULL OR s.end_date > e.month_end)
              ), 0) AS active_count
            FROM eom e
            LEFT JOIN staffing s ON TRUE
            GROUP BY e.month
            ORDER BY e.month;
        """, (from_month, to_month))

        rows = cur.fetchall()
        cur.close(); conn.close()

        out = [
            {"month": r[0], "tsr": int(r[1]), "tsf": int(r[2]), "active_count": int(r[3])}
            for r in rows
        ]
        return jsonify(out)

    except Exception as exc:
        import traceback
        logging.error("❌ ts_history failed: %s\n%s", exc, traceback.format_exc())
        return jsonify({"error": str(exc)}), 500
