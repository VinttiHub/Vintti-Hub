import json
import logging
import re
import traceback
import uuid
from datetime import date, datetime

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor, execute_values

from db import get_connection
from utils import services
from utils.storage_utils import (
    get_account_pdf_keys,
    make_account_pdf_payload,
    set_account_pdf_keys,
)

bp = Blueprint('accounts', __name__)


def normalize_overview_stage(value):
    stage = str(value or '').strip().lower()
    if stage == 'closed':
        return 'closed'
    return 'open'


def has_active_hire(cursor, opportunity_id):
    """Return True if an opportunity still has an active hire."""
    if opportunity_id is None:
        return False
    cursor.execute(
        """
            SELECT 1
            FROM hire_opportunity
            WHERE opportunity_id = %s
              AND (
                    end_date IS NULL
                    OR LOWER(COALESCE(status, '')) = 'active'
                  )
            LIMIT 1
        """,
        (opportunity_id,),
    )
    return cursor.fetchone() is not None


def has_buyout_info(cursor, opportunity_id):
    """Return True if an opportunity has buyout info in hire_opportunity or buyouts."""
    if opportunity_id is None:
        return False
    cursor.execute(
        """
            SELECT 1
            FROM hire_opportunity
            WHERE opportunity_id = %s
              AND (
                    (buyout_dolar IS NOT NULL AND NULLIF(TRIM(CAST(buyout_dolar AS TEXT)), '') IS NOT NULL)
                    OR (buyout_daterange IS NOT NULL AND NULLIF(TRIM(CAST(buyout_daterange AS TEXT)), '') IS NOT NULL)
                  )
            LIMIT 1
        """,
        (opportunity_id,),
    )
    if cursor.fetchone() is not None:
        return True
    cursor.execute(
        """
            SELECT 1
            FROM buyouts b
            JOIN opportunity o
              ON o.account_id = b.account_id
             AND o.candidato_contratado = b.candidate_id
            WHERE o.opportunity_id = %s
            LIMIT 1
        """,
        (opportunity_id,),
    )
    return cursor.fetchone() is not None


def fetch_data_from_table(table_name):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {table_name}")
        colnames = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        data = [dict(zip(colnames, row)) for row in rows]
        cursor.close()
        conn.close()
        return data
    except Exception as exc:
        return {"error": str(exc)}

@bp.route('/opportunities')
def get_opportunities():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*, 
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
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/accounts/<account_id>')
def get_account_by_id(account_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            WITH h_active AS (
            SELECT DISTINCT ON (opportunity_id, candidate_id)
                    opportunity_id, candidate_id, salary, fee, revenue, start_date
            FROM hire_opportunity
            WHERE end_date IS NULL          -- activos
            ORDER BY opportunity_id, candidate_id, start_date DESC NULLS LAST
            )
            SELECT
            COALESCE(SUM(CASE WHEN o.opp_model ILIKE 'recruiting'
                                THEN COALESCE(h.revenue,0) END), 0) AS trr,
            COALESCE(SUM(CASE WHEN o.opp_model ILIKE 'staffing'
                                THEN COALESCE(h.fee,0) END), 0)     AS tsf,
            COALESCE(SUM(CASE WHEN o.opp_model ILIKE 'staffing'
                                THEN COALESCE(h.salary,0)+COALESCE(h.fee,0) END), 0) AS tsr
            FROM opportunity o
            LEFT JOIN h_active h ON h.opportunity_id = o.opportunity_id
            WHERE o.account_id = %s;
        """, (account_id,))
        trr, tsf, tsr = cursor.fetchone() or (0,0,0)

        # persiste si querés mantener cacheado en 'account'
        cursor.execute("""
            UPDATE account
            SET trr = %s, tsf = %s, tsr = %s
            WHERE account_id = %s
        """, (trr, tsf, tsr, account_id))
        conn.commit()

        cursor.execute("SELECT * FROM account WHERE account_id = %s", (account_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close(); conn.close()
            return jsonify({"error": "Account not found"}), 404

        colnames = [d[0] for d in cursor.description]
        account = dict(zip(colnames, row))
        cursor.close(); conn.close()
        return jsonify(account)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/accounts/<account_id>/opportunities')
def get_opportunities_by_account(account_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
                SELECT 
                    o.*, 
                    c.name AS candidate_name
                FROM opportunity o
                LEFT JOIN candidates c ON o.candidato_contratado = c.candidate_id
                WHERE o.account_id = %s
            """, (account_id,))
        rows = cursor.fetchall()
        if not rows:
            return jsonify([])

        colnames = [desc[0] for desc in cursor.description]
        data = [dict(zip(colnames, row)) for row in rows]

        cursor.close()
        conn.close()

        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route('/accounts/<int:account_id>/overview-cache', methods=['GET'])
def get_account_overview_cache(account_id):
    """Return cached payloads for closed opportunities in client_overview."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
                SELECT client_overview_id, account_id, opportunity_id, candidates_batches, updated_at
                FROM client_overview
                WHERE account_id = %s
                ORDER BY client_overview_id ASC
            """,
            (account_id,),
        )
        rows = cursor.fetchall() or []
        payload = []
        for row in rows:
            client_overview_id, acc_id, opportunity_id, data, updated_at = row
            decoded = None
            stage = None
            if data:
                try:
                    decoded = json.loads(data)
                except Exception:
                    logging.warning(
                        "Failed to decode candidates_batches for account %s opportunity %s",
                        account_id,
                        opportunity_id,
                )
            if isinstance(decoded, dict):
                raw_stage = decoded.get('stage')
                if raw_stage is not None:
                    normalized = str(raw_stage).strip().lower()
                    if normalized in ('open', 'closed'):
                        stage = normalized
            payload.append(
                {
                    "client_overview_id": client_overview_id,
                    "account_id": acc_id,
                    "opportunity_id": opportunity_id,
                    "snapshot": decoded,
                    "stage": stage,
                    "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else None,
                }
            )
        cursor.close()
        conn.close()
        return jsonify(payload)
    except Exception as e:
        logging.exception("❌ get_account_overview_cache failed")
        return jsonify({"error": str(e)}), 500


@bp.route('/accounts/<int:account_id>/overview-cache', methods=['PUT'])
def upsert_account_overview_cache(account_id):
    """Persist the provided closed opportunity payload into client_overview."""
    try:
        body = request.get_json(silent=True) or {}
        entries = body.get('opportunities')
        if not isinstance(entries, list):
            return jsonify({'error': 'opportunities array is required'}), 400

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(client_overview_id), 0) FROM client_overview")
        next_id = cursor.fetchone()[0] or 0

        saved, updated, skipped, deleted = 0, 0, 0, 0
        for entry in entries:
            try:
                opportunity_id = int(entry.get('opportunity_id'))
            except (TypeError, ValueError):
                skipped += 1
                continue

            snapshot = entry.get('snapshot') or entry.get('candidates_batches') or {}
            if not isinstance(snapshot, dict):
                skipped += 1
                continue
            stage = normalize_overview_stage(entry.get('stage') or snapshot.get('stage'))
            snapshot['stage'] = stage
            updated_at = entry.get('updated_at')
            snapshot['updated_at'] = updated_at

            cursor.execute(
                """
                    SELECT client_overview_id, candidates_batches
                    FROM client_overview
                    WHERE account_id = %s AND opportunity_id = %s
                """,
                (account_id, opportunity_id),
            )
            row = cursor.fetchone()
            existing_id = None
            existing_snapshot = None
            if row:
                existing_id, existing_payload = row
                if existing_payload:
                    try:
                        existing_snapshot = json.loads(existing_payload)
                    except Exception:
                        existing_snapshot = None
                if isinstance(existing_snapshot, dict):
                    existing_snapshot.setdefault('client_overview_id', existing_id)
                    opp_snapshot = existing_snapshot.get('opportunity')
                    if isinstance(opp_snapshot, dict):
                        opp_snapshot.setdefault('client_overview_id', existing_id)
                else:
                    existing_snapshot = None

            if existing_id is None:
                next_id += 1
                target_id = next_id
            else:
                target_id = existing_id

            snapshot['client_overview_id'] = target_id
            snapshot['opportunity_id'] = opportunity_id
            snapshot['account_id'] = account_id
            opportunity_snapshot = snapshot.get('opportunity')
            if isinstance(opportunity_snapshot, dict):
                opportunity_snapshot.setdefault('client_overview_id', target_id)

            payload_json = json.dumps(snapshot, sort_keys=True)

            should_remove_for_inactive_hire = (
                stage == 'closed'
                and not has_active_hire(cursor, opportunity_id)
                and not has_buyout_info(cursor, opportunity_id)
            )
            if should_remove_for_inactive_hire:
                if existing_id is not None:
                    cursor.execute(
                        "DELETE FROM client_overview WHERE client_overview_id = %s",
                        (existing_id,),
                    )
                    deleted += 1
                skipped += 1
                continue

            if existing_id is not None:
                existing_serialized = (
                    json.dumps(existing_snapshot, sort_keys=True)
                    if isinstance(existing_snapshot, dict)
                    else None
                )
                if existing_serialized == payload_json:
                    skipped += 1
                    continue
                cursor.execute(
                    """
                        UPDATE client_overview
                        SET candidates_batches = %s,
                            updated_at = COALESCE(%s::timestamptz, timezone('America/New_York', now()))
                        WHERE client_overview_id = %s
                    """,
                    (payload_json, updated_at, target_id),
                )
                updated += 1
            else:
                cursor.execute(
                    """
                        INSERT INTO client_overview (client_overview_id, account_id, opportunity_id, candidates_batches, updated_at)
                        VALUES (
                            %s, %s, %s, %s,
                            COALESCE(%s::timestamptz, timezone('America/New_York', now()))
                        )
                    """,
                    (target_id, account_id, opportunity_id, payload_json, updated_at),
                )
                saved += 1

        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'inserted': saved, 'updated': updated, 'deleted': deleted, 'skipped': skipped}), 200
    except Exception as e:
        logging.exception("❌ upsert_account_overview_cache failed")
        return jsonify({'error': str(e)}), 500


@bp.route('/accounts/<int:account_id>/overview-cache/prune-inactive', methods=['POST'])
def prune_inactive_client_overview(account_id):
    """Remove client_overview rows whose hires are no longer active."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
                SELECT client_overview_id, opportunity_id, candidates_batches
                FROM client_overview
                WHERE account_id = %s
            """,
            (account_id,),
        )
        rows = cursor.fetchall() or []
        stale_ids = []
        for client_overview_id, opportunity_id, payload in rows:
            if not opportunity_id:
                stale_ids.append(client_overview_id)
                continue
            stage = None
            if payload:
                try:
                    decoded = json.loads(payload)
                except Exception:
                    decoded = None
                if isinstance(decoded, dict):
                    stage = normalize_overview_stage(decoded.get('stage'))
            if stage != 'closed':
                continue
            if not has_active_hire(cursor, opportunity_id) and not has_buyout_info(cursor, opportunity_id):
                stale_ids.append(client_overview_id)
        deleted = 0
        if stale_ids:
            cursor.execute(
                "DELETE FROM client_overview WHERE client_overview_id = ANY(%s)",
                (stale_ids,),
            )
            deleted = cursor.rowcount or len(stale_ids)
            conn.commit()
        else:
            conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'deleted': deleted})
    except Exception as e:
        logging.exception("❌ prune_inactive_client_overview failed")
        return jsonify({'error': str(e)}), 500

@bp.route('/opportunities/<int:opportunity_id>')
def get_opportunity_by_id(opportunity_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                o.*, 
                a.client_name AS account_name,
                a.size AS account_size,
                a.state AS account_state,
                a.linkedin AS account_linkedin,
                a.website AS account_website,
                a.mail AS account_mail,
                a.comments AS account_about,
                a.timezone AS account_timezone
            FROM opportunity o
            LEFT JOIN account a ON o.account_id = a.account_id
            WHERE o.opportunity_id = %s
            """, (opportunity_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Opportunity not found"}), 404

        colnames = [desc[0] for desc in cursor.description]
        opportunity = dict(zip(colnames, row))

        cursor.close()
        conn.close()

        return jsonify(opportunity)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route('/opportunities/<int:opportunity_id>', methods=['DELETE'])
def delete_opportunity(opportunity_id):
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM opportunity WHERE opportunity_id = %s",
            (opportunity_id,),
        )
        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({"error": "Opportunity not found"}), 404

        conn.commit()
        return jsonify({"message": "Opportunity deleted"}), 200
    except Exception as e:
        logging.exception("❌ delete_opportunity failed")
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@bp.route('/opportunities', methods=['POST'])
def create_opportunity():
    data = request.get_json()
    client_name = data.get('client_name')
    opp_model = data.get('opp_model')
    position_name = data.get('position_name')
    sales_lead = data.get('sales_lead')
    opp_type = data.get('opp_type')

    # 🆕 opcionales para Replacement
    replacement_of = data.get('replacement_of')              # candidate_id
    replacement_end_date = data.get('replacement_end_date')  # 'YYYY-MM-DD'

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT account_id FROM account WHERE client_name = %s LIMIT 1", (client_name,))
        account_row = cursor.fetchone()
        if not account_row:
            return jsonify({'error': f'No account found for client_name: {client_name}'}), 400
        account_id = account_row[0]

        cursor.execute("SELECT COALESCE(MAX(opportunity_id), 0) + 1 FROM opportunity")
        new_opportunity_id = cursor.fetchone()[0]

        cursor.execute("""
            INSERT INTO opportunity (
                opportunity_id, account_id, opp_model, opp_position_name, opp_sales_lead,
                opp_type, opp_stage, replacement_of, replacement_end_date
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            new_opportunity_id, account_id, opp_model, position_name, sales_lead,
            opp_type, 'Deep Dive', replacement_of, replacement_end_date
        ))

        conn.commit()
        cursor.close(); conn.close()
        return jsonify({'message': 'Opportunity created successfully'}), 201

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/accounts', methods=['GET', 'POST'])
def accounts():
    if request.method == 'GET':
        result = fetch_data_from_table("account")
        if "error" in result:
            return jsonify(result), 500
        return jsonify([{"account_name": row["client_name"]} for row in result])

    elif request.method == 'POST':
        try:
            data = request.get_json()
            print("🟢 Datos recibidos en POST /accounts:", data)

            conn = get_connection()
            cursor = conn.cursor()

            # 👉 Normalizar boolean de outsource (yes/no -> True/False/None)
            raw_outsource = str(data.get("outsource") or "").strip().lower()
            if raw_outsource in ("yes", "true", "1"):
                outsource = True
            elif raw_outsource in ("no", "false", "0"):
                outsource = False
            else:
                outsource = None

            query = """
                INSERT INTO account (
                    client_name, Size, timezone, state,
                    website, linkedin, comments, mail,
                    where_come_from, referal_source,
                    industry, outsource, pain_points, position, type,
                    name, surname
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s
                )
            """

            cursor.execute(query, (
                data.get("name"),             # client_name (nombre de la cuenta)
                data.get("size"),
                data.get("timezone"),
                data.get("state"),
                data.get("website"),
                data.get("linkedin"),
                data.get("about"),
                data.get("mail"),
                data.get("where_come_from"),
                data.get("referal_source"),

                # 🆕 Nuevos campos
                data.get("industry"),         # industry
                outsource,                    # boolean
                data.get("pain_points"),      # pain_points
                data.get("position"),         # position
                data.get("type"),             # type
                data.get("contact_name"),     # name (en la tabla)
                data.get("contact_surname")   # surname (en la tabla)
            ))

            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"message": "Account created successfully"}), 201

        except Exception as e:
            import traceback
            print(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

@bp.route('/opportunities/<int:opportunity_id>', methods=['PATCH'])
def update_opportunity_stage(opportunity_id):
    data = request.get_json()
    new_stage = data.get('opp_stage')

    if new_stage is None:
        return jsonify({'error': 'opp_stage is required'}), 400

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE opportunity
            SET opp_stage = %s
            WHERE opportunity_id = %s
        """, (new_stage, opportunity_id))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True}), 200

    except Exception as e:
        print("Error updating stage:", e)
        return jsonify({'error': str(e)}), 500

@bp.route('/accounts/<account_id>/candidates')
def get_candidates_by_account(account_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT Name, employee_revenue, employee_fee, employee_salary, employee_type, peoplemodel
            FROM candidates
            WHERE account_id = %s
        """, (account_id,))
        rows = cursor.fetchall()
        if not rows:
            return jsonify([])

        colnames = [desc[0] for desc in cursor.description]
        data = [dict(zip(colnames, row)) for row in rows]

        cursor.close()
        conn.close()

        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/opportunities/<int:opportunity_id>/candidates')
def get_candidates_by_opportunity(opportunity_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                c.candidate_id,
                c.name,
                c.email,
                c.stage,
                c.country,
                c.employee_salary,
                c.salary_range,
                COALESCE(c.blacklist, FALSE) AS is_blacklisted,
                oc.stage_batch,
                oc.stage_pipeline AS stage,
                oc.sign_off,
                oc.star
            FROM candidates c
            INNER JOIN opportunity_candidates oc ON c.candidate_id = oc.candidate_id
            WHERE oc.opportunity_id = %s
        """, (opportunity_id,))

        rows = cursor.fetchall()
        colnames = [desc[0] for desc in cursor.description]
        data = [dict(zip(colnames, row)) for row in rows]

        cursor.close()
        conn.close()

        return jsonify(data)

    except Exception as e:
        import traceback
        print("❌ ERROR EN GET /opportunities/<id>/candidates")
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@bp.route('/batches/<int:batch_id>/candidates', methods=['GET'])
def get_candidates_by_batch(batch_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        query = """
            SELECT c.*, cb.status
            FROM candidates_batches cb
            JOIN candidates c ON cb.candidate_id = c.candidate_id
            WHERE cb.batch_id = %s
        """
        cursor.execute(query, (batch_id,))
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        candidates = [dict(zip(columns, row)) for row in rows]

        return jsonify(candidates)
    except Exception as e:
        logging.error(f"Error al obtener candidatos del batch {batch_id}: {e}")
        return jsonify({'error': 'Error al obtener los candidatos del batch'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@bp.route('/opportunities/<int:opportunity_id>/fields', methods=['PATCH'])
def update_opportunity_fields(opportunity_id):
    from datetime import date, datetime
    import logging, json

    def _to_date_or_none(v):
        """Soporta 'YYYY-MM-DD' o cualquier string con 'T' (toma solo la fecha)."""
        if v in (None, '', 'null'):
            return None
        if isinstance(v, date) and not isinstance(v, datetime):
            return v  # ya es date
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, str):
            s = v.strip()
            # caso ideal: 'YYYY-MM-DD'
            try:
                if len(s) == 10 and s[4] == '-' and s[7] == '-':
                    return date.fromisoformat(s)
            except Exception:
                pass
            # si vino como ISO con hora: 'YYYY-MM-DDTHH:MM:SSZ'
            try:
                # no usamos dateutil para no agregar dependencia: cortamos a 10
                return date.fromisoformat(s[:10])
            except Exception:
                raise ValueError(f"Invalid date format for value: {v!r}")
        raise ValueError(f"Unsupported date type for value: {type(v)}")

    data = request.get_json() or {}
    logging.info("📥 PATCH /opportunities/%s/fields payload=%s",
                 opportunity_id, json.dumps(data, default=str))

    candidate_hired_id = data.get('candidato_contratado')

    updatable_fields = [
        'nda_signature_or_start_date',
        'since_sourcing',
        'opp_position_name',
        'opp_model',
        'min_budget',
        'max_budget',
        'min_salary',
        'max_salary',
        'years_experience',
        'fee',
        'opp_comments',
        'first_meeting_recording',
        'opp_close_date',
        'opp_sales_lead',
        'opp_hr_lead',
        'hr_job_description',
        'comments',
        'motive_close_lost',
        'client_interviewing_process',
        'replacement_of',
        'replacement_end_date',        # 👈 asegúrate de tratarla como DATE
        'candidato_contratado',
        'cantidad_entrevistados',

        # Career Site
        'career_job_id',
        'career_job',
        'career_country',
        'career_city',
        'career_job_type',
        'career_seniority',
        'career_years_experience',
        'career_experience_level',
        'career_field',
        'career_modality',
        'career_tools',   # JSON/text
        'career_description',
        'career_requirements',
        'career_additional_info',
        'career_published',
        'expected_fee',
        'expected_revenue',
        'details_close_lost'
    ]

    # 🔹 Normaliza HTML ruidoso de Career Site / Webflow antes de persistir
    for key in ('career_description', 'career_requirements', 'career_additional_info'):
        if key in data and isinstance(data[key], str):
            data[key] = _clean_html_for_webflow(data[key], output='html')

    # 👉 Campos que deben guardarse como DATE puro (sin hora)
    DATE_FIELDS = {
        'opp_close_date',
        'nda_signature_or_start_date',
        'since_sourcing',
        'replacement_end_date',
    }

    updates, values = [], []
    for field in updatable_fields:
        if field in data:
            val = data[field]
            if field in DATE_FIELDS:
                try:
                    val = _to_date_or_none(val)
                except ValueError as e:
                    return jsonify({'error': str(e), 'field': field}), 400
            updates.append(f"{field} = %s")
            values.append(val)

    if not updates and candidate_hired_id is None:
        logging.warning("⚠️ Nada que actualizar y sin candidato_contratado")
        return jsonify({'error': 'No valid fields provided'}), 400

    try:
        conn = get_connection()
        with conn:
            with conn.cursor() as cursor:
                # 1) Update de opportunity (sin ::date — ya enviamos objetos date)
                if updates:
                    logging.info("🛠 SET %s", ', '.join(updates))
                    values.append(opportunity_id)
                    cursor.execute(f"""
                        UPDATE opportunity
                           SET {', '.join(updates)}
                         WHERE opportunity_id = %s
                    """, values)
                    logging.info("✅ UPDATE opportunity (%s filas)", cursor.rowcount)

                # 2) Efectos de Close Win (si vino candidato_contratado)
                if candidate_hired_id is not None:
                    try:
                        candidate_hired_id = int(candidate_hired_id)
                    except (TypeError, ValueError):
                        return jsonify({'error': 'candidato_contratado must be an integer'}), 400

                    cursor.execute("""
                        UPDATE candidates_batches cb
                           SET status = %s
                         WHERE cb.candidate_id = %s
                           AND EXISTS (
                                 SELECT 1
                                   FROM batch b
                                  WHERE b.batch_id = cb.batch_id
                                    AND b.opportunity_id = %s
                           )
                    """, ('Client hired', candidate_hired_id, opportunity_id))
                    if cursor.rowcount == 0:
                        cursor.execute("""
                            UPDATE candidates_batches
                               SET status = %s
                             WHERE candidate_id = %s
                        """, ('Client hired', candidate_hired_id))
                    logging.info("🟢 candidates_batches actualizado")

        return jsonify({'success': True}), 200

    except Exception as e:
        logging.exception("❌ Error updating opportunity fields (opp=%s)", opportunity_id)
        return jsonify({'error': str(e)}), 500

@bp.route('/accounts/<account_id>', methods=['PATCH'])
def update_account_fields(account_id):
    data = request.get_json()

    allowed_fields = [
        'client_name',
        'size',
        'state',
        'linkedin',
        'website',
        'mail',
        'comments',
        'timezone',
        'pain_points',
        'priority',
        'contract',
        'where_come_from',
        'calculated_status',
        'account_manager',
        'account_status', 
        'referal_source'  
    ]


    updates = []
    values = []

    for field in allowed_fields:
        if field in data:
            updates.append(f"{field} = %s")
            values.append(data[field])

    if not updates:
        return jsonify({'error': 'No valid fields provided'}), 400

    values.append(account_id)

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(f"""
            UPDATE account
            SET {', '.join(updates)}
            WHERE account_id = %s
        """, values)

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True}), 200

    except Exception as e:
        print("Error updating account fields:", e)
        return jsonify({'error': str(e)}), 500

@bp.route('/accounts/sales-lead/suggest/bulk', methods=['POST'])
def suggest_sales_lead_bulk():
    payload = request.get_json(silent=True) or {}
    account_ids = payload.get("account_ids") or []
    # normaliza ints
    ids = []
    for x in account_ids:
        try:
            ids.append(int(x))
        except Exception:
            pass

    if not ids:
        return jsonify({}), 200

    try:
        conn = get_connection()
        out = {}

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1) breakdown completo por account
            cur.execute("""
                SELECT
                    o.account_id::int AS account_id,
                    LOWER(TRIM(o.opp_sales_lead)) AS opp_sales_lead,
                    COUNT(*)::int AS cnt,
                    MAX(o.opportunity_id)::int AS last_opportunity_id
                FROM opportunity o
                WHERE o.account_id = ANY(%s)
                  AND o.opp_sales_lead IS NOT NULL
                  AND TRIM(o.opp_sales_lead) <> ''
                GROUP BY 1, 2
                ORDER BY account_id ASC, cnt DESC, last_opportunity_id DESC, opp_sales_lead ASC;
            """, (ids,))
            rows = cur.fetchall() or []

        conn.close()

        # arma breakdown por account y elige top1
        by_acc = {}
        for r in rows:
            acc = r["account_id"]
            by_acc.setdefault(acc, []).append({
                "opp_sales_lead": r["opp_sales_lead"],
                "cnt": r["cnt"],
                "last_opportunity_id": r["last_opportunity_id"],
            })

        for acc_id in ids:
            br = by_acc.get(acc_id, [])
            suggested = br[0]["opp_sales_lead"] if br else None
            out[str(acc_id)] = {
                "suggested_sales_lead": suggested,
                "breakdown": br
            }

        return jsonify(out), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/accounts/<int:account_id>/sales-lead/suggest', methods=['GET'])
def suggest_sales_lead_for_account(account_id: int):
    """
    Devuelve el sales lead sugerido basado en las opportunities del account:
    - majority winner por opp_sales_lead
    - tie-break: last_opportunity_id más alto
    Response:
      {
        "account_id": 123,
        "suggested_sales_lead": "bahia@vintti.com",
        "breakdown": [
          {"opp_sales_lead":"bahia@vintti.com","cnt":4,"last_opportunity_id":98},
          {"opp_sales_lead":"lara@vintti.com","cnt":2,"last_opportunity_id":77}
        ]
      }
    """
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    LOWER(TRIM(o.opp_sales_lead)) AS opp_sales_lead,
                    COUNT(*)::int AS cnt,
                    MAX(o.opportunity_id)::int AS last_opportunity_id
                FROM opportunity o
                WHERE o.account_id = %s
                  AND o.opp_sales_lead IS NOT NULL
                  AND TRIM(o.opp_sales_lead) <> ''
                GROUP BY 1
                ORDER BY cnt DESC, last_opportunity_id DESC, opp_sales_lead ASC;
            """, (account_id,))
            rows = cur.fetchall() or []

        conn.close()

        suggested = rows[0]["opp_sales_lead"] if rows else None
        return jsonify({
            "account_id": account_id,
            "suggested_sales_lead": suggested,
            "breakdown": rows
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/opportunities/<int:opportunity_id>/candidates/<int:candidate_id>/stage', methods=['PATCH'])
def update_stage_pipeline(opportunity_id, candidate_id):
    data = request.get_json()
    print("📥 PATCH /stage recibido")
    print("🟡 opportunity_id:", opportunity_id)
    print("🟡 candidate_id:", candidate_id)
    print("🟡 payload:", data)

    stage_pipeline = data.get('stage_pipeline')

    if stage_pipeline is None:
        print("❌ stage_pipeline no recibido")
        return jsonify({'error': 'stage_pipeline is required'}), 400

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE opportunity_candidates
            SET stage_pipeline = %s
            WHERE opportunity_id = %s AND candidate_id = %s
        """, (stage_pipeline, opportunity_id, candidate_id))
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ stage_pipeline actualizado")
        return jsonify({'success': True}), 200
    except Exception as e:
        print("❌ ERROR DB:", e)
        return jsonify({'error': str(e)}), 500

@bp.route('/opportunities/<int:opportunity_id>/candidates/<int:candidate_id>/signoff', methods=['PATCH'])
def update_signoff_status(opportunity_id, candidate_id):
    data = request.get_json()
    sign_off = data.get('sign_off')

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE opportunity_candidates
            SET sign_off = %s
            WHERE opportunity_id = %s AND candidate_id = %s
        """, (sign_off, opportunity_id, candidate_id))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/opportunities/<int:opportunity_id>/candidates/<int:candidate_id>/star', methods=['PATCH'])
def update_candidate_star(opportunity_id, candidate_id):
    try:
        data = request.get_json()
        star_value = data.get('star')

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE opportunity_candidates
            SET star = %s
            WHERE opportunity_id = %s AND candidate_id = %s
        """, (star_value, opportunity_id, candidate_id))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"message": "Star updated successfully"})
    except Exception as e:
        print(f"Error updating star: {e}")
        return jsonify({"error": str(e)}), 500

@bp.route('/accounts/<account_id>/opportunities/candidates')
def get_candidates_by_account_opportunities(account_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
        SELECT 
            c.candidate_id,
            c.name,
            c.stage,
            COALESCE(c.blacklist, FALSE) AS is_blacklisted,
            o.opportunity_id,
            o.opp_model,
            o.opp_position_name,
            o.replacement_of,
            h.salary  AS employee_salary,
            h.fee     AS employee_fee,
            h.revenue AS employee_revenue,
            h.start_date,
            h.end_date,
            COALESCE(h.status, CASE WHEN h.end_date IS NULL THEN 'active' ELSE 'inactive' END) AS status,
            h.discount_dolar,
            h.discount_daterange,
            h.referral_dolar,
            h.referral_daterange,
            h.buyout_dolar,
            h.buyout_daterange
            FROM opportunity o
            LEFT JOIN candidates c
                ON o.candidato_contratado = c.candidate_id
            LEFT JOIN hire_opportunity h
                ON h.opportunity_id = o.opportunity_id
            AND h.candidate_id   = c.candidate_id
            WHERE o.account_id = %s
        """, (account_id,))

        
        rows = cursor.fetchall()
        colnames = [desc[0] for desc in cursor.description]
        data = [dict(zip(colnames, row)) for row in rows if row[colnames.index("candidate_id")] is not None]

        cursor.close()
        conn.close()

        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route('/accounts/<account_id>/buyouts', methods=['GET'])
def list_account_buyouts(account_id):
    """Return every buyout row associated to an account."""
    try:
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT
                b.buyout_id,
                b.account_id,
                b.candidate_id,
                b.salary,
                b.revenue,
                b.referral,
                b.referral_date_range,
                b.start_date,
                b.end_date,
                b.probation,
                c.name AS candidate_name
            FROM buyouts b
            LEFT JOIN candidates c ON c.candidate_id = b.candidate_id
            WHERE b.account_id = %s
            ORDER BY b.buyout_id
            """,
            (account_id,),
        )
        rows = cursor.fetchall() or []
        cursor.close()
        conn.close()
        return jsonify(rows)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route('/accounts/<account_id>/buyouts', methods=['POST'])
def create_account_buyout(account_id):
    """Create a buyout row ensuring incremental buyout_id values."""
    try:
        payload = request.get_json() or {}
        candidate_id = payload.get('candidate_id')
        if not candidate_id:
            return jsonify({"error": "candidate_id is required"}), 400

        conn = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute(
            """
            SELECT
                buyout_id,
                account_id,
                candidate_id,
                salary,
                revenue,
                referral,
                referral_date_range,
                start_date,
                end_date,
                probation
            FROM buyouts
            WHERE account_id = %s AND candidate_id = %s
            LIMIT 1
            """,
            (account_id, candidate_id),
        )
        existing = cursor.fetchone()
        if existing:
            cursor.close()
            conn.close()
            return jsonify(existing), 200

        cursor.execute("SELECT COALESCE(MAX(buyout_id), 0) AS max_id FROM buyouts")
        max_row = cursor.fetchone()
        next_id = ((max_row or {}).get('max_id') or 0) + 1

        salary = payload.get('salary')
        revenue = payload.get('revenue')
        referral = payload.get('referral')
        referral_date_range = payload.get('referral_date_range')
        start_date = payload.get('start_date')
        end_date = payload.get('end_date')
        probation = payload.get('probation')

        cursor.execute(
            """
            INSERT INTO buyouts (
                buyout_id,
                account_id,
                candidate_id,
                salary,
                revenue,
                referral,
                referral_date_range,
                start_date,
                end_date,
                probation
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING
                buyout_id,
                account_id,
                candidate_id,
                salary,
                revenue,
                referral,
                referral_date_range,
                start_date,
                end_date,
                probation
            """,
            (
                next_id,
                account_id,
                candidate_id,
                salary,
                revenue,
                referral,
                referral_date_range,
                start_date,
                end_date,
                probation,
            ),
        )
        created = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify(created), 201
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route('/buyouts/<int:buyout_id>', methods=['PATCH'])
def update_buyout_row(buyout_id):
    """Allow editing any editable column in the buyouts table."""
    try:
        payload = request.get_json() or {}
        editable_fields = (
            'account_id',
            'candidate_id',
            'salary',
            'revenue',
            'referral',
            'referral_date_range',
            'start_date',
            'end_date',
            'probation',
        )
        sets = []
        params = []
        for field in editable_fields:
            if field in payload:
                sets.append(f"{field} = %s")
                params.append(payload[field])

        if not sets:
            return jsonify({"error": "No valid fields to update"}), 400

        params.append(buyout_id)

        conn = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            f"""
            UPDATE buyouts
            SET {', '.join(sets)}
            WHERE buyout_id = %s
            RETURNING
                buyout_id,
                account_id,
                candidate_id,
                salary,
                revenue,
                referral,
                referral_date_range,
                start_date,
                end_date,
                probation
            """,
            params,
        )
        updated = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()

        if not updated:
            return jsonify({"error": "Buyout not found"}), 404

        return jsonify(updated)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route('/opportunities/<opportunity_id>/batches', methods=['POST'])
def create_batch(opportunity_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Leer fecha desde el JSON recibido
        data = request.get_json()
        presentation_date = data.get('presentation_date')  # formato YYYY-MM-DD

        # Obtener el batch_id más alto actual
        cursor.execute("SELECT COALESCE(MAX(batch_id), 0) FROM batch")
        current_max_batch_id = cursor.fetchone()[0]
        new_batch_id = current_max_batch_id + 1

        # Obtener cuántos batches tiene esta oportunidad
        cursor.execute("SELECT COUNT(*) FROM batch WHERE opportunity_id = %s", (opportunity_id,))
        batch_count = cursor.fetchone()[0]
        batch_number = batch_count + 1

        # Insertar el nuevo batch con fecha
        cursor.execute("""
            INSERT INTO batch (batch_id, batch_number, opportunity_id, presentation_date)
            VALUES (%s, %s, %s, %s)
        """, (new_batch_id, batch_number, opportunity_id, presentation_date))
        
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            "batch_id": new_batch_id,
            "batch_number": batch_number,
            "opportunity_id": opportunity_id
        }), 201

    except Exception as e:
        print("Error creating batch:", e)
        return jsonify({"error": str(e)}), 500

@bp.route('/opportunities/<int:opportunity_id>/candidates', methods=['POST'])
def link_or_create_candidate(opportunity_id):
    data = request.get_json()
    candidate_id = data.get('candidate_id')
    if candidate_id:
        conn = get_connection()
        cur = conn.cursor()

        # Verificar si ya está relacionado
        cur.execute("""
            SELECT 1 FROM opportunity_candidates
            WHERE opportunity_id = %s AND candidate_id = %s
        """, (opportunity_id, candidate_id))

        if cur.fetchone():
            cur.close(); conn.close()
            return jsonify({"error": "This candidate is already linked to this opportunity."}), 400

        # Si no existe la relación, insertarla
        cur.execute("""
            INSERT INTO opportunity_candidates (opportunity_id, candidate_id)
            VALUES (%s, %s)
        """, (opportunity_id, candidate_id))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({"message": "Linked existing candidate"}), 200

    else:
        data = request.get_json()
        name = data.get('name')
        email = data.get('email')
        phone = data.get('phone')
        linkedin = data.get('linkedin')
        red_flags = data.get('red_flags')
        comments = data.get('comments')
        english_level = data.get('english_level')
        salary_range = data.get('salary_range')
        stage = data.get('stage', 'Contactado')
        country = data.get('country')

        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Obtener el siguiente candidate_id
            cursor.execute("SELECT COALESCE(MAX(candidate_id), 0) FROM candidates")
            max_id = cursor.fetchone()[0]
            new_candidate_id = max_id + 1
            created_by = data.get('created_by')
            # Insertar en tabla candidates SIN opportunity_id
            created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("""
                INSERT INTO candidates (
                    candidate_id, name, email, phone, linkedin,
                    red_flags, comments, english_level, salary_range, country, stage, created_by, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                new_candidate_id, name, email, phone, linkedin,
                red_flags, comments, english_level, salary_range, country, stage, created_by, created_at
            ))
            # Insertar en tabla intermedia
            cursor.execute("""
                INSERT INTO opportunity_candidates (opportunity_id, candidate_id)
                VALUES (%s, %s)
            """, (opportunity_id, new_candidate_id))

            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"message": "Candidate created and linked successfully", "candidate_id": new_candidate_id}), 201

        except Exception as e:
            return jsonify({"error": str(e)}), 500

@bp.route('/opportunities/<int:opportunity_id>/candidates/link', methods=['POST'])
def link_existing_candidate_to_opportunity(opportunity_id):
    """
    Inserta exclusivamente en opportunity_candidates sin crear registros nuevos.
    Se utiliza desde el pipeline cuando se selecciona un candidato ya existente.
    """
    data = request.get_json() or {}
    candidate_id = data.get('candidate_id')
    stage_pipeline = (data.get('stage') or data.get('stage_pipeline') or 'Contactado').strip() or 'Contactado'

    if not candidate_id:
        return jsonify({"error": "candidate_id is required"}), 400

    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 1
            FROM opportunity_candidates
            WHERE opportunity_id = %s AND candidate_id = %s
        """, (opportunity_id, candidate_id))
        if cursor.fetchone():
            return jsonify({"error": "Candidate is already linked to this opportunity."}), 409

        cursor.execute("""
            INSERT INTO opportunity_candidates (opportunity_id, candidate_id, stage_pipeline)
            VALUES (%s, %s, %s)
        """, (opportunity_id, candidate_id, stage_pipeline))

        conn.commit()
        return jsonify({"message": "Candidate linked successfully"}), 201
    except Exception as exc:
        if conn:
            conn.rollback()
        return jsonify({"error": str(exc)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@bp.route('/opportunity_candidates/stage_batch', methods=['PATCH'])
def update_stage_batch():
    data = request.get_json()
    opportunity_id = data.get('opportunity_id')
    candidate_id = data.get('candidate_id')
    stage_batch = data.get('stage_batch')

    if not all([opportunity_id, candidate_id, stage_batch]):
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE opportunity_candidates
            SET stage_batch = %s
            WHERE opportunity_id = %s AND candidate_id = %s
        """, (stage_batch, opportunity_id, candidate_id))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/opportunities/<int:opportunity_id>/candidates/<int:candidate_id>', methods=['DELETE'])
def delete_candidate_from_pipeline(opportunity_id, candidate_id):
    try:
        conn = get_connection()
        cur = conn.cursor()

        # ¿cuántas oportunidades tiene este candidato?
        cur.execute("""
            SELECT COUNT(*) FROM opportunity_candidates
            WHERE candidate_id = %s
        """, (candidate_id,))
        count = cur.fetchone()[0]

        if count == 1:
            # Borrar completamente al candidato
            cur.execute("DELETE FROM candidates WHERE candidate_id = %s", (candidate_id,))
        else:
            # Solo eliminar relación
            cur.execute("""
                DELETE FROM opportunity_candidates
                WHERE opportunity_id = %s AND candidate_id = %s
            """, (opportunity_id, candidate_id))

        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/batches/<int:batch_id>', methods=['DELETE'])
def delete_batch(batch_id):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM batch WHERE batch_id = %s", (batch_id,))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/sourcing', methods=['POST'])
def create_sourcing_entry():
    try:
        data = request.get_json()
        print("🟡 Recibido en /sourcing:", data)

        opportunity_id = data.get('opportunity_id')
        user_id = data.get('user_id')
        since_sourcing = data.get('since_sourcing')

        if not all([opportunity_id, user_id, since_sourcing]):
            return jsonify({'error': 'Missing required fields'}), 400

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COALESCE(MAX(sourcing_id), 0) FROM sourcing")
        new_id = cursor.fetchone()[0] + 1

        cursor.execute("""
            INSERT INTO sourcing (sourcing_id, opportunity_id, user_id, since_sourcing)
            VALUES (%s, %s, %s, %s)
        """, (new_id, opportunity_id, user_id, since_sourcing))

        conn.commit()
        cursor.close()
        conn.close()

        print("🟢 Sourcing insertado con ID:", new_id)
        return jsonify({'success': True, 'sourcing_id': new_id})

    except Exception as e:
        print("❌ ERROR en /sourcing:", str(e))
        return jsonify({'error': str(e)}), 500

@bp.route('/opportunities/<int:opportunity_id>/latest_sourcing_date')
def get_latest_sourcing_date(opportunity_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT MAX(since_sourcing)
            FROM sourcing
            WHERE opportunity_id = %s
        """, (opportunity_id,))
        result = cursor.fetchone()[0]

        cursor.close()
        conn.close()

        return jsonify({'latest_sourcing_date': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/opportunities/<int:opp_id>/pause_days_since_batch', methods=['GET'])
def should_pause_days_since_batch(opp_id):
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT MAX(since_sourcing)
            FROM sourcing
            WHERE opportunity_id = %s
        """, (opp_id,))
        sourcing_date = cur.fetchone()[0]

        cur.execute("""
            SELECT presentation_date
            FROM batch
            WHERE opportunity_id = %s
        """, (opp_id,))
        presentation_dates = [row[0] for row in cur.fetchall() if row[0]]

        if not sourcing_date:
            return jsonify({"pause": False})

        pause = any(p > sourcing_date for p in presentation_dates)
        return jsonify({"pause": pause})

    except Exception as e:
        print("Error:", e)
        return jsonify({"error": "Internal server error"}), 500

    finally:
        cur.close()
        conn.close()

@bp.route('/accounts/<account_id>/upload_pdf', methods=['POST'])
def upload_account_pdf(account_id):
    pdf_file = request.files.get('pdf')
    if not pdf_file:
        return jsonify({"error": "Missing PDF file"}), 400

    try:
        # S3 key única
        filename = f"accounts/{account_id}_{uuid.uuid4()}.pdf"

        # Subir a S3
        services.s3_client.upload_fileobj(
            pdf_file,
            services.S3_BUCKET,
            filename,
            ExtraArgs={'ContentType': 'application/pdf'}
        )

        # Actualizar lista de keys en account.pdf_s3 (JSON array)
        conn = get_connection()
        cursor = conn.cursor()

        keys = get_account_pdf_keys(cursor, account_id)
        if filename not in keys:
            keys.append(filename)
        set_account_pdf_keys(cursor, account_id, keys)
        conn.commit()

        # Devolver lista completa con URLs presignadas frescas
        pdfs = make_account_pdf_payload(keys)

        cursor.close()
        conn.close()

        return jsonify({"message": "PDF uploaded", "pdfs": pdfs}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/accounts/<account_id>/pdfs', methods=['GET'])
def list_account_pdfs(account_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        keys = get_account_pdf_keys(cursor, account_id)
        # Normaliza a JSON array si venía en legacy
        set_account_pdf_keys(cursor, account_id, keys)
        conn.commit()

        pdfs = make_account_pdf_payload(keys)

        cursor.close()
        conn.close()
        return jsonify(pdfs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/accounts/<account_id>/pdfs', methods=['DELETE'])
def delete_account_pdf_v2(account_id):
    try:
        data = request.get_json(silent=True) or {}
        key = data.get("key")  # Debe venir tipo "accounts/<account_id>_<uuid>.pdf"
        if not key or not key.startswith("accounts/"):
            return jsonify({"error": "Missing or invalid key"}), 400

        conn = get_connection()
        cursor = conn.cursor()

        # Leer keys actuales
        keys = get_account_pdf_keys(cursor, account_id)

        if key not in keys:
            cursor.close(); conn.close()
            return jsonify({"error": "Key not found for this account"}), 404

        # Eliminar de S3
        services.s3_client.delete_object(Bucket=services.S3_BUCKET, Key=key)

        # Quitar de la lista y persistir
        keys = [k for k in keys if k != key]
        set_account_pdf_keys(cursor, account_id, keys)
        conn.commit()

        pdfs = make_account_pdf_payload(keys)

        cursor.close()
        conn.close()

        return jsonify({"message": "PDF deleted", "pdfs": pdfs}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/accounts/<account_id>/delete_pdf', methods=['DELETE'])
def delete_account_pdf(account_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT pdf_s3 FROM account WHERE account_id = %s", (account_id,))
        row = cursor.fetchone()
        if not row or not row[0]:
            return jsonify({"error": "No PDF found"}), 404

        pdf_url = row[0]
        match = re.search(r"accounts%2F(.+?)\.pdf", pdf_url) or re.search(r"accounts/(.+?\.pdf)", pdf_url)
        if not match:
            return jsonify({"error": "Invalid S3 key"}), 400

        s3_key = f"accounts/{match.group(1)}"
        services.s3_client.delete_object(Bucket=services.S3_BUCKET, Key=s3_key)

        cursor.execute("UPDATE account SET pdf_s3 = NULL WHERE account_id = %s", (account_id,))
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"message": "PDF deleted"}), 200

    except Exception as e:
        print("❌ Error deleting PDF:", str(e))
        return jsonify({"error": str(e)}), 500

@bp.route('/accounts/<account_id>/pdfs', methods=['PATCH'])
def rename_account_pdf(account_id):
    """
    JSON body: { "key": "accounts/<old>.pdf", "new_name": "Nuevo nombre.pdf" }
    - Copia el objeto a una nueva key y borra la vieja.
    - Actualiza la lista guardada en account.pdf_s3 (JSON array).
    """
    try:
        data = request.get_json(silent=True) or {}
        key = data.get("key")
        new_name = (data.get("new_name") or "").strip()

        if not key or not key.startswith("accounts/"):
            return jsonify({"error": "Missing or invalid key"}), 400
        if not new_name:
            return jsonify({"error": "Missing new_name"}), 400

        # Sanitizar nombre
        new_name = re.sub(r"[\\/]", "-", new_name)  # sin slashes
        if not new_name.lower().endswith(".pdf"):
            new_name += ".pdf"

        dest_key = f"accounts/{new_name}"

        conn = get_connection()
        cursor = conn.cursor()

        # Leer keys actuales de la cuenta y validar pertenencia
        keys = get_account_pdf_keys(cursor, account_id)
        if key not in keys:
            cursor.close(); conn.close()
            return jsonify({"error": "Key not found for this account"}), 404

        # Evitar colisiones de nombre
        if dest_key in keys and dest_key != key:
            cursor.close(); conn.close()
            return jsonify({"error": "A file with that name already exists"}), 409

        # Renombrar en S3: copy -> delete
        services.s3_client.copy_object(
            Bucket=services.S3_BUCKET,
            CopySource={'Bucket': services.S3_BUCKET, 'Key': key},
            Key=dest_key,
            ContentType='application/pdf',
            MetadataDirective='REPLACE'
        )
        services.s3_client.delete_object(Bucket=services.S3_BUCKET, Key=key)

        # Reemplazar en la lista persistida
        new_keys = [dest_key if k == key else k for k in keys]
        set_account_pdf_keys(cursor, account_id, new_keys)
        conn.commit()

        # Devolver lista con URLs presignadas frescas
        pdfs = make_account_pdf_payload(new_keys)

        cursor.close(); conn.close()
        return jsonify({"message": "PDF renamed", "pdfs": pdfs}), 200

    except Exception as e:
        logging.exception("❌ rename_account_pdf failed")
        return jsonify({"error": str(e)}), 500

@bp.route('/opportunities/<opportunity_id>/batches', methods=['GET'])
def get_batches(opportunity_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT batch_id, batch_number, opportunity_id, presentation_date
            FROM batch
            WHERE opportunity_id = %s
            ORDER BY batch_number ASC
        """, (opportunity_id,))
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        data = [dict(zip(cols, r)) for r in rows]
        cursor.close(); conn.close()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/batches/<int:batch_id>', methods=['PATCH'])
def update_batch(batch_id):
    try:
        data = request.get_json(silent=True) or {}
        pres = (data.get('presentation_date') or '').strip()
        if not pres:
            return jsonify({'error':'presentation_date is required'}), 400

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE batch
            SET presentation_date = %s::date
            WHERE batch_id = %s
        """, (pres, batch_id))
        if cur.rowcount == 0:
            cur.close(); conn.close()
            return jsonify({'error':'Not found'}), 404
        conn.commit()

        # devolver la fila actualizada (opcional)
        cur.execute("""
            SELECT batch_id, batch_number, opportunity_id, presentation_date
            FROM batch WHERE batch_id = %s
        """, (batch_id,))
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
        cur.close(); conn.close()
        return jsonify(dict(zip(cols, row)))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

__all__ = ['bp']
