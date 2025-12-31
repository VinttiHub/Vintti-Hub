import json
import logging
import re
import traceback
import uuid
from datetime import date, datetime

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_connection
from utils import services
from utils.storage_utils import get_cv_keys, list_s3_with_prefix, make_cv_payload, set_cv_keys
from utils.types import to_bool

bp = Blueprint('candidates', __name__)

_LINKEDIN_SCHEME_RE = re.compile(r'^https?://', flags=re.I)
_WHITESPACE_RE = re.compile(r'\s+')
_BLACKLIST_COLUMN_CACHE = None


def _normalize_name(value):
    return (value or '').strip().lower()


def _normalize_phone_digits(value):
    return re.sub(r'\D', '', value or '')


def _clean_linkedin_for_storage(value):
    if not value:
        return ''
    clean = value.strip()
    if not clean:
        return ''
    if not _LINKEDIN_SCHEME_RE.match(clean):
        clean = f"https://{clean.lstrip('/')}"
    clean = clean.rstrip('/')
    return clean


def _normalize_linkedin(value):
    if not value:
        return ''
    clean = value.strip().lower()
    clean = _WHITESPACE_RE.sub(' ', clean)
    clean = clean.rstrip('/')
    clean = clean.strip()
    return clean


def _linkedin_normalize_sql(column):
    return f"""
        NULLIF(
            BTRIM(
                LOWER(
                    REGEXP_REPLACE(
                        REGEXP_REPLACE(
                            TRIM(COALESCE({column}, '')),
                            '\\s+',
                            ' ',
                            'g'
                        ),
                        '/+$',
                        '',
                        'g'
                    )
                ),
                ' '
            ),
            ''
        )
    """


def _get_blacklist_columns(conn):
    global _BLACKLIST_COLUMN_CACHE
    if _BLACKLIST_COLUMN_CACHE is not None:
        return _BLACKLIST_COLUMN_CACHE

    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'blacklist'
              AND table_schema = 'public'
            ORDER BY ordinal_position
        """)
        rows = cur.fetchall()
        columns = [row[0] for row in rows]
        _BLACKLIST_COLUMN_CACHE = columns
        return columns
    finally:
        cur.close()


def _build_blacklist_insert_payload(conn, candidate_row, linkedin_norm):
    columns = _get_blacklist_columns(conn)
    insert_columns = []
    values = []

    for column in columns:
        if column == 'blacklist_id':
            continue

        value = None
        if column == 'linkedin_normalized':
            value = linkedin_norm or None
        elif column == 'notes' and 'comments' in candidate_row:
            value = candidate_row.get('comments')
        else:
            value = candidate_row.get(column)

        insert_columns.append(column)
        values.append(value)

    return insert_columns, values


def _find_blacklist_match(cursor, candidate_id, linkedin_value, fallback_to_candidate_id=False):
    linkedin_norm = _normalize_linkedin(linkedin_value)
    match = None

    if linkedin_norm:
        cursor.execute(
            f"""
            SELECT *
            FROM blacklist
            WHERE {_linkedin_normalize_sql('linkedin')} = %s
            LIMIT 1
            """,
            (linkedin_norm,)
        )
        match = cursor.fetchone()

    if (fallback_to_candidate_id or not linkedin_norm) and candidate_id is not None and not match:
        cursor.execute(
            """
            SELECT *
            FROM blacklist
            WHERE candidate_id = %s
            LIMIT 1
            """,
            (candidate_id,)
        )
        match = cursor.fetchone()

    return match, linkedin_norm

@bp.route('/candidates/light')
def get_candidates_light():
    try:
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        c_linkedin_norm = _linkedin_normalize_sql('c.linkedin')
        b_linkedin_norm = _linkedin_normalize_sql('b.linkedin')
        cursor.execute(f"""
            WITH normalized_candidates AS (
              SELECT
                c.candidate_id,
                c.name,
                c.country,
                c.phone,
                c.linkedin,
                {c_linkedin_norm} AS linkedin_norm
              FROM candidates c
            ),
            normalized_blacklist AS (
              SELECT
                b.blacklist_id,
                {b_linkedin_norm} AS linkedin_norm,
                b.candidate_id
              FROM blacklist b
            )
            SELECT
              nc.candidate_id,
              nc.name,
              nc.country,
              nc.phone,
              nc.linkedin,
              CASE
                WHEN EXISTS (
                  SELECT 1
                  FROM opportunity o
                  WHERE o.candidato_contratado = nc.candidate_id
                ) THEN '✔️'
                ELSE '❌'
              END AS employee,
              COALESCE(bl.is_blacklisted, FALSE) AS is_blacklisted
            FROM normalized_candidates nc
            LEFT JOIN LATERAL (
              SELECT TRUE AS is_blacklisted
              FROM normalized_blacklist nb
              WHERE (
                      nb.linkedin_norm IS NOT NULL
                  AND nc.linkedin_norm IS NOT NULL
                  AND nb.linkedin_norm = nc.linkedin_norm
              )
              OR (
                  nb.candidate_id IS NOT NULL
                  AND nc.candidate_id IS NOT NULL
                  AND nb.candidate_id = nc.candidate_id
              )
              LIMIT 1
            ) bl ON TRUE
            ORDER BY nc.candidate_id DESC;
        """)

        rows = cursor.fetchall()
        cursor.close(); conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/candidates', methods=['GET'])
def get_candidates():
    search = request.args.get('search')
    if search:
        return search_candidates()
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        c_linkedin_norm = _linkedin_normalize_sql('c.linkedin')
        b_linkedin_norm = _linkedin_normalize_sql('b.linkedin')
        cur.execute(f"""
            WITH normalized_candidates AS (
              SELECT
                c.*,
                {c_linkedin_norm} AS linkedin_norm
              FROM candidates c
            ),
            normalized_blacklist AS (
              SELECT
                b.blacklist_id,
                {b_linkedin_norm} AS linkedin_norm,
                b.candidate_id
              FROM blacklist b
            )
            SELECT
              nc.*,
              CASE
                WHEN EXISTS (
                  SELECT 1
                  FROM opportunity o
                  JOIN opportunity_candidates oc ON o.opportunity_id = oc.opportunity_id
                  WHERE oc.candidate_id = nc.candidate_id
                    AND o.candidato_contratado = nc.candidate_id
                  LIMIT 1
                )
                THEN '✔️'
                ELSE '❌'
              END AS employee,
              COALESCE(bl.is_blacklisted, FALSE) AS is_blacklisted
            FROM normalized_candidates nc
            LEFT JOIN LATERAL (
              SELECT TRUE AS is_blacklisted
              FROM normalized_blacklist nb
              WHERE (
                      nb.linkedin_norm IS NOT NULL
                  AND nc.linkedin_norm IS NOT NULL
                  AND nb.linkedin_norm = nc.linkedin_norm
              )
              OR (
                  nb.candidate_id IS NOT NULL
                  AND nc.candidate_id IS NOT NULL
                  AND nb.candidate_id = nc.candidate_id
              )
              LIMIT 1
            ) bl ON TRUE
            ORDER BY nc.candidate_id DESC;
        """)

        rows = cur.fetchall()
        cur.close(); conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/candidates', methods=['POST'])
def create_candidate_without_opportunity():
    data = request.get_json() or {}

    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    phone_raw = (data.get('phone') or '').strip()
    linkedin_raw = (data.get('linkedin') or '').strip()
    linkedin_clean = _clean_linkedin_for_storage(linkedin_raw)
    linkedin_normalized = _normalize_linkedin(linkedin_clean)
    phone_digits = _normalize_phone_digits(phone_raw)
    country = (data.get('country') or '').strip() or None
    red_flags = data.get('red_flags')
    comments = data.get('comments')
    english_level = data.get('english_level')
    salary_range = data.get('salary_range')
    stage = (data.get('stage') or 'Contactado').strip() or 'Contactado'
    created_by = (data.get('created_by') or '').strip().lower() or None

    if not email or not phone_digits or not linkedin_clean:
        return jsonify({"error": "Missing required fields: email, phone and linkedin"}), 400

    name_db = name or None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        if linkedin_normalized:
            cursor.execute(
                f"""
                SELECT blacklist_id, candidate_id, name, linkedin
                FROM blacklist
                WHERE {_linkedin_normalize_sql('linkedin')} = %s
                LIMIT 1
                """,
                (linkedin_normalized,)
            )
            blacklist_row = cursor.fetchone()
            if blacklist_row:
                cursor.close()
                conn.close()
                return jsonify({
                    "error": "Blacklisted candidate",
                    "reason": "blacklisted candidate",
                    "blacklist_entry": {
                        "blacklist_id": blacklist_row[0],
                        "candidate_id": blacklist_row[1],
                        "name": blacklist_row[2],
                        "linkedin": blacklist_row[3],
                    }
                }), 409

        conflict_clauses = []
        params = []

        normalized_name = _normalize_name(name)
        if normalized_name:
            conflict_clauses.append("LOWER(TRIM(COALESCE(name,''))) = %s")
            params.append(normalized_name)
        if phone_digits:
            conflict_clauses.append("regexp_replace(COALESCE(phone,''), '[^0-9]', '', 'g') = %s")
            params.append(phone_digits)
        if linkedin_normalized:
            conflict_clauses.append(f"{_linkedin_normalize_sql('linkedin')} = %s")
            params.append(linkedin_normalized)

        if conflict_clauses:
            where_sql = " OR ".join(conflict_clauses)
            cursor.execute(
                f"""
                SELECT candidate_id, name, email, phone, linkedin
                FROM candidates
                WHERE {where_sql}
                LIMIT 1
                """,
                tuple(params)
            )
            existing = cursor.fetchone()
            if existing:
                existing_candidate = {
                    "candidate_id": existing[0],
                    "name": existing[1],
                    "email": existing[2],
                    "phone": existing[3],
                    "linkedin": existing[4],
                }
                conflict_fields = []
                if normalized_name and _normalize_name(existing_candidate["name"]) == normalized_name:
                    conflict_fields.append("name")
                if phone_digits and _normalize_phone_digits(existing_candidate["phone"]) == phone_digits:
                    conflict_fields.append("phone")
                if linkedin_normalized and _normalize_linkedin(existing_candidate["linkedin"]) == linkedin_normalized:
                    conflict_fields.append("linkedin")
                label_map = {
                    "name": "duplicate name",
                    "phone": "duplicate phone",
                    "linkedin": "duplicate LinkedIn",
                }
                reason_labels = [label_map.get(field, field) for field in conflict_fields]
                reason_text = " / ".join(reason_labels) if reason_labels else "duplicate candidate data"
                if reason_text:
                    reason_text = reason_text[0].upper() + reason_text[1:]
                cursor.close()
                conn.close()
                return jsonify({
                    "error": reason_text,
                    "conflict_fields": conflict_fields,
                    "candidate": existing_candidate,
                }), 409

        cursor.execute("SELECT COALESCE(MAX(candidate_id), 0) + 1 FROM candidates")
        new_candidate_id = cursor.fetchone()[0]

        cursor.execute("""
            INSERT INTO candidates (
                candidate_id, name, email, phone, linkedin,
                red_flags, comments, english_level, salary_range,
                country, stage, created_by, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (
            new_candidate_id, name_db, email, phone_digits, linkedin_clean,
            red_flags, comments, english_level, salary_range,
            country, stage, created_by
        ))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            "message": "Candidate created successfully",
            "candidate_id": new_candidate_id
        }), 201
    except Exception as exc:
        logging.exception("❌ Error creating candidate without opportunity")
        return jsonify({"error": str(exc)}), 500

def search_candidates():
    q = (request.args.get('search') or '').strip()
    if len(q) < 2:
        return jsonify([])

    conn = get_connection()
    cur = conn.cursor()
    try:
        pattern = f"%{q}%"
        cur.execute("""
            SELECT candidate_id, name
            FROM candidates
            WHERE name ILIKE %s
            ORDER BY LOWER(name) ASC
            LIMIT 10;
        """, (pattern,))
        rows = cur.fetchall()
        return jsonify([{"candidate_id": r[0], "name": r[1]} for r in rows])
    except Exception as exc:
        logging.error("search_candidates failed: %s\n%s", exc, traceback.format_exc())
        return jsonify([]), 200
    finally:
        cur.close(); conn.close()

@bp.route('/candidates/<int:candidate_id>/cvs', methods=['GET'])
def list_candidate_cvs(candidate_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        keys = get_cv_keys(cursor, candidate_id)
        # Normaliza a JSON list si era legacy
        set_cv_keys(cursor, candidate_id, keys)
        conn.commit()

        items = make_cv_payload(keys)

        cursor.close(); conn.close()
        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/candidates/<int:candidate_id>/cvs', methods=['POST'])
def upload_candidate_cv(candidate_id):
    """
    FormData: file=<archivo> (pdf o imagen)
    """
    f = request.files.get('file')
    if not f:
        return jsonify({"error": "Missing file"}), 400

    # Validaciones básicas de tipo
    allowed_ext = ('pdf', 'png', 'jpg', 'jpeg', 'webp')
    filename_orig = (f.filename or '').lower()
    ext = filename_orig.rsplit('.', 1)[-1] if '.' in filename_orig else ''
    if ext not in allowed_ext:
        return jsonify({"error": f"Unsupported file type .{ext}. Allowed: {', '.join(allowed_ext)}"}), 400

    try:
        s3_key = f"cvs/resume_{candidate_id}_{uuid.uuid4()}.{ext}"
        content_type = f.mimetype or {
            'pdf': 'application/pdf',
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'webp': 'image/webp'
        }.get(ext, 'application/octet-stream')

        # Subir a S3
        services.s3_client.upload_fileobj(
            f,
            services.S3_BUCKET,
            s3_key,
            ExtraArgs={'ContentType': content_type}
        )

        # =========================
        # 🆕 NUEVO: correr Affinda y guardar en candidates.affinda_scrapper
        # =========================
        affinda_json = None
        if ext == 'pdf' and services.affinda_client:
            try:
                try:
                    f.stream.seek(0)
                    file_for_affinda = f.stream
                except Exception:
                    f.seek(0)
                    file_for_affinda = f

                doc = services.affinda_client.create_document(
                    file=file_for_affinda,
                    workspace=services.WORKSPACE_ID,
                    document_type=services.DOC_TYPE_ID,
                    wait=True
                )
                data = doc.data
                try:
                    affinda_json = json.dumps(data)
                except TypeError:
                    try:
                        affinda_json = json.dumps(doc.as_dict())
                    except Exception:
                        affinda_json = json.dumps(getattr(data, "__dict__", {"raw": str(data)}))
            except Exception:
                logging.exception("Affinda extraction failed (candidate_id=%s, key=%s)", candidate_id, s3_key)
        elif ext == 'pdf' and not services.affinda_client:
            logging.warning("Affinda no configurado; omitiendo extracción.")
        # =========================


        conn = get_connection()
        cursor = conn.cursor()

        # 🆕 Guardar resultado de Affinda si lo obtuvimos
        if affinda_json:
            cursor.execute(
                "UPDATE candidates SET affinda_scrapper = %s WHERE candidate_id = %s",
                (affinda_json, candidate_id)
            )

        # Mantener tu lógica de almacenar la lista de CVs en resume.cv_pdf_s3
        keys = get_cv_keys(cursor, candidate_id)
        if s3_key not in keys:
            keys.append(s3_key)
        set_cv_keys(cursor, candidate_id, keys)
        conn.commit()

        items = make_cv_payload(keys)

        cursor.close(); conn.close()
        return jsonify({"message": "CV uploaded", "items": items}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/candidates/<int:candidate_id>/cvs', methods=['DELETE'])
def delete_candidate_cv(candidate_id):
    """
    JSON body: { "key": "cvs/<candidate_id>_<uuid>.<ext>" }
    """
    data = request.get_json(silent=True) or {}
    key = data.get("key")
    if not key or not key.startswith("cvs/"):
        return jsonify({"error": "Missing or invalid key"}), 400

    try:
        conn = get_connection()
        cursor = conn.cursor()

        keys = get_cv_keys(cursor, candidate_id)
        if key not in keys:
            cursor.close(); conn.close()
            return jsonify({"error": "Key not found for this candidate"}), 404

        # Eliminar en S3
        services.s3_client.delete_object(Bucket=services.S3_BUCKET, Key=key)

        # Actualizar lista
        keys = [k for k in keys if k != key]
        set_cv_keys(cursor, candidate_id, keys)
        conn.commit()

        items = make_cv_payload(keys)

        cursor.close(); conn.close()
        return jsonify({"message": "CV deleted", "items": items}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/candidates/<int:candidate_id>')
def get_candidate_by_id(candidate_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                name,
                country,
                phone,
                email,
                linkedin,
                english_level,
                salary_range,
                red_flags,
                comments,
                created_by,
                created_at,
                linkedin_scrapper,
                cv_pdf_scrapper,
                discount_dolar,
                discount_daterange,
                affinda_scrapper,
                coresignal_scrapper,
                candidate_succes,
                check_hr_lead,
                address,
                dni
            FROM candidates
            WHERE candidate_id = %s
        """, (candidate_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Candidate not found"}), 404

        colnames = [desc[0] for desc in cursor.description]
        candidate = dict(zip(colnames, row))

        cursor.close()
        conn.close()

        return jsonify(candidate)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/candidates/<int:candidate_id>/hire_opportunity', methods=['GET'])
def get_hire_opportunity(candidate_id):
    """
    Returns the opportunity_id and opp_model for the candidate based on the
    hire_opportunity table, not the opportunity.candidato_contratado column.
    If multiple hire_opportunity rows exist for the candidate, the most recent
    one is returned (by hire_opportunity_id DESC).
    """
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT o.opportunity_id, o.opp_model
            FROM hire_opportunity h
            JOIN opportunity o ON o.opportunity_id = h.opportunity_id
            WHERE h.candidate_id = %s
            LIMIT 1;
        """, (candidate_id,))

        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            return jsonify({}), 404

        colnames = [desc[0] for desc in cur.description]
        out = dict(zip(colnames, row))

        cur.close()
        conn.close()
        return jsonify(out)

    except Exception as e:
        import traceback
        print("❌ Error en GET /candidates/<candidate_id>/hire_opportunity:")
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@bp.route('/candidates/<int:candidate_id>/equipments')
def get_candidate_equipments(candidate_id):
    """
    Devuelve los equipos del candidato como array de strings.
    Lee de la tabla 'equipments' la columna 'equipos' que puede venir:
      - como texto "Laptop"
      - como JSON texto '["Laptop","Chair"]'
    Si hay varias filas para el candidato, toma la más reciente (por id/fecha si existiera),
    si no, la primera que encuentre.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Ajusta el ORDER BY si tienes un campo 'updated_at' o similar
        cur.execute("""
            SELECT equipos
            FROM equipments
            WHERE candidate_id = %s
            ORDER BY equipment_id DESC
            LIMIT 1
        """, (candidate_id,))

        row = cur.fetchone()
        cur.close(); conn.close()

        if not row or row[0] is None:
            return jsonify([])

        raw = row[0]
        items = []

        # Normaliza: si ya es lista, devuélvela; si es string JSON, parsea; si es string plano, envuélvelo.
        try:
            parsed = raw if isinstance(raw, list) else json.loads(raw)
            if isinstance(parsed, list):
                items = [str(x) for x in parsed]
            elif isinstance(parsed, str) and parsed.strip():
                items = [parsed.strip()]
        except Exception:
            # No era JSON válido: tratamos como string plano
            if isinstance(raw, str) and raw.strip():
                items = [raw.strip()]

        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/candidates/<int:candidate_id>', methods=['PATCH'])
def update_candidate_fields(candidate_id):
    data = request.get_json()
    print("🟡 PATCH recibido:", data)

    allowed_fields = [
        'name',
        'country',
        'phone',
        'email',
        'linkedin',
        'english_level',
        'salary_range',
        'red_flags',
        'comments',
        'sign_off',
        'linkedin_scrapper',
        'cv_pdf_scrapper',
        'discount_dolar', 
        'discount_daterange',
        'candidate_succes',
        'check_hr_lead',
        'address',
        'dni'
    ]

    updates = []
    values = []

    for field in allowed_fields:
        if field in data:
            val = data[field]
            # 👉 fuerza tipos especiales
            if field == 'check_hr_lead':
                val = to_bool(val)
            updates.append(f"{field} = %s")
            values.append(val)

    if not updates:
        return jsonify({'error': 'No valid fields provided'}), 400

    values.append(candidate_id)

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            UPDATE candidates
            SET {', '.join(updates)}
            WHERE candidate_id = %s
        """, values)
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/candidates_batches', methods=['POST'])
def link_candidate_to_batch():
    data = request.get_json()
    candidate_id = data.get('candidate_id')
    batch_id = data.get('batch_id')

    if not candidate_id or not batch_id:
        return jsonify({'error': 'Missing candidate_id or batch_id'}), 400

    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO candidates_batches (candidate_id, batch_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
        """, (candidate_id, batch_id))

        conn.commit()
        cur.close(); conn.close()
        return jsonify({'success': True}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/candidates/<int:candidate_id>/opportunities')
def get_opportunities_by_candidate(candidate_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                o.opportunity_id,
                o.opp_model,
                o.opp_position_name,
                o.opp_sales_lead,
                o.opp_stage,
                o.opp_hr_lead,
                a.client_name
            FROM opportunity o
            JOIN opportunity_candidates oc ON o.opportunity_id = oc.opportunity_id
            LEFT JOIN account a ON o.account_id = a.account_id
            WHERE oc.candidate_id = %s
        """, (candidate_id,))
        
        rows = cursor.fetchall()
        colnames = [desc[0] for desc in cursor.description]
        data = [dict(zip(colnames, row)) for row in rows]

        return jsonify(data)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
    finally:
        cursor.close()
        conn.close()

@bp.route('/candidates/<int:candidate_id>/hire', methods=['GET', 'PATCH'])
def handle_candidate_hire_data(candidate_id):
    """
    GET:
      - If ?opportunity_id= is provided, read that hire row.
      - Else try to use the opportunity where this candidate is marcado como contratado,
        prioritizing the most recently closed one.
    PATCH:
      - MUST receive JSON with {"opportunity_id": <clicked id>} from the frontend.
      - Creates/updates hire_opportunity for (candidate_id, opportunity_id) exactly.
    """
    from psycopg2.extras import RealDictCursor
    import re, calendar

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if request.method == 'GET':
            # 1) pick the opportunity
            opp_id_param = request.args.get('opportunity_id', type=int)

            if opp_id_param:
                cur.execute("""
                    SELECT opportunity_id, opp_model, account_id
                    FROM opportunity
                    WHERE opportunity_id = %s
                """, (opp_id_param,))
                opp = cur.fetchone()
            else:
                # fallback: the latest opp where this candidate is the hired one
                cur.execute("""
                    SELECT opportunity_id, opp_model, account_id
                    FROM opportunity
                    WHERE candidato_contratado = %s
                    ORDER BY COALESCE(opp_close_date, '1900-01-01') DESC, opportunity_id DESC
                    LIMIT 1
                """, (candidate_id,))
                opp = cur.fetchone()

            if not opp:
                return jsonify({'error': 'No hired opportunity found for this candidate'}), 404

            opportunity_id = opp['opportunity_id']
            opp_model     = opp.get('opp_model')
            account_id    = opp.get('account_id')

            # 2) read hire_opportunity
            cur.execute("""
                SELECT
                    references_notes,
                    salary,
                    fee,
                    setup_fee,
                    computer,
                    extra_perks,
                    working_schedule,
                    pto,
                    discount_dolar,
                    discount_daterange,
                    start_date,
                    end_date,
                    revenue,
                    referral_dolar,
                    referral_daterange,
                    buyout_dolar,
                    buyout_daterange,
                    carga_active,
                    carga_inactive
                FROM hire_opportunity
                WHERE candidate_id = %s AND opportunity_id = %s
                LIMIT 1
            """, (candidate_id, opportunity_id))
            row = cur.fetchone()
            if not row:
                # return an empty shell so the UI can render cleanly
                return jsonify({
                    'references_notes': None,
                    'employee_salary': None,
                    'employee_fee': None,
                    'computer': None,
                    'setup_fee': None,
                    'extraperks': None,
                    'working_schedule': None,
                    'pto': None,
                    'discount_dolar': None,
                    'discount_daterange': None,
                    'start_date': None,
                    'end_date': None,
                    'employee_revenue': None,
                    'employee_revenue_recruiting': None,
                    'referral_dolar': None,
                    'referral_daterange': None,
                    'buyout_dolar': None,
                    'buyout_daterange': None,
                    'carga_inactive': None
                })

            return jsonify({
                'references_notes': row['references_notes'],
                'employee_salary': row['salary'],
                'employee_fee': row['fee'],
                'computer': row['computer'],
                'setup_fee': row['setup_fee'],
                'extraperks': row['extra_perks'],
                'working_schedule': row['working_schedule'],
                'pto': row['pto'],
                'discount_dolar': row['discount_dolar'],
                'discount_daterange': row['discount_daterange'],
                'start_date': row['start_date'],
                'end_date': row['end_date'],
                'employee_revenue': row['revenue'] if (opp_model or '').lower() == 'staffing' else None,
                'employee_revenue_recruiting': row['revenue'] if (opp_model or '').lower() == 'recruiting' else None,
                'referral_dolar': row['referral_dolar'],
                'referral_daterange': row['referral_daterange'],
                'buyout_dolar': row['buyout_dolar'],
                'buyout_daterange': row['buyout_daterange'],
                'carga_active': row['carga_active'],
                'carga_inactive': row['carga_inactive']
            })

        # ---------- PATCH ----------
        data = request.get_json() or {}
        opportunity_id = data.get('opportunity_id', None)
        # --- helpers date-only ---
        def _clean_date(v):
            # acepta 'YYYY-MM-DD', '' o None
            if v is None: 
                return None
            s = str(v).strip()
            if s == "" or s.lower() == "null":
                return None
            # no rompas si viene un datetime; corta a YYYY-MM-DD si empieza así
            if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
                return s
            if re.match(r"^\d{4}-\d{2}-\d{2}T", s):
                return s[:10]
            # si viene algo raro, mejor error 400 (para que no se guarde basura)
            raise ValueError("Date must be YYYY-MM-DD or null")

        if not opportunity_id:
            return jsonify({'error': 'opportunity_id is required in PATCH body'}), 400

        # 1) fetch account/model for THIS opportunity
        cur.execute("""
            SELECT opp_model, account_id, candidato_contratado
            FROM opportunity
            WHERE opportunity_id = %s
            LIMIT 1
        """, (opportunity_id,))
        opp = cur.fetchone()
        if not opp:
            return jsonify({'error': f'opportunity {opportunity_id} not found'}), 404

        opp_model  = opp.get('opp_model')
        account_id = opp.get('account_id')

        # 2) be robust: ensure this opportunity actually points to this candidate
        if opp.get('candidato_contratado') != candidate_id:
            # if frontend called /opportunities/<id>/fields first, this should already be set,
            # but just in case, align it here:
            cur.execute("""
                UPDATE opportunity
                SET candidato_contratado = %s
                WHERE opportunity_id = %s
            """, (candidate_id, opportunity_id))

        # 3) upsert into hire_opportunity for this exact (candidate_id, opportunity_id)
        cur.execute("""
            INSERT INTO hire_opportunity (candidate_id, opportunity_id, account_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (candidate_id, opportunity_id) DO NOTHING
        """, (candidate_id, opportunity_id, account_id))

        # mapping of incoming JSON → columns
        mapping = {
            'references_notes': 'references_notes',
            'employee_salary': 'salary',
            'employee_fee': 'fee',
            'setup_fee': 'setup_fee',
            'computer': 'computer',
            'extraperks': 'extra_perks',
            'working_schedule': 'working_schedule',
            'pto': 'pto',
            'start_date': 'start_date',
            'end_date': 'end_date',
            'employee_revenue': 'revenue',                 # staffing
            'employee_revenue_recruiting': 'revenue',      # recruiting
            'discount_dolar': 'discount_dolar',
            'discount_daterange': 'discount_daterange',
            'referral_dolar': 'referral_dolar',
            'referral_daterange': 'referral_daterange',
            'buyout_dolar': 'buyout_dolar',
            'buyout_daterange': 'buyout_daterange'
        }

        set_cols, set_vals = [], []

        for k, col in mapping.items():
            if k in data:
                v = data.get(k)

                # normaliza start_date / end_date
                if k in ("start_date", "end_date"):
                    try:
                        v = _clean_date(v)
                    except ValueError as ve:
                        return jsonify({"error": str(ve)}), 400

                set_cols.append(f"{col} = %s")
                set_vals.append(v)

        # 👇 lógica especial para las fechas de carga (solo cuando hay start/end en el payload)
        if "start_date" in data:
            # si setean start_date a una fecha real -> marca carga_active, si lo limpian -> null
            if _clean_date(data.get("start_date")) is not None:
                set_cols.append("carga_active = %s")
                set_vals.append(date.today())
            else:
                set_cols.append("carga_active = %s")
                set_vals.append(None)

        if "end_date" in data:
            # si setean end_date a una fecha real -> marca carga_inactive, si lo limpian -> null
            if _clean_date(data.get("end_date")) is not None:
                set_cols.append("carga_inactive = %s")
                set_vals.append(date.today())
            else:
                set_cols.append("carga_inactive = %s")
                set_vals.append(None)


        created = False
        updated = False

        # if nothing else is being set, we still guaranteed the row exists (via insert above)
        if set_cols:
            set_vals.extend([candidate_id, opportunity_id])
            cur.execute(f"""
                UPDATE hire_opportunity
                SET {", ".join(set_cols)}
                WHERE candidate_id = %s AND opportunity_id = %s
            """, set_vals)
            updated = True

        # if row didn’t exist before, mark created
        cur.execute("""
            SELECT 1 FROM hire_opportunity
            WHERE candidate_id = %s AND opportunity_id = %s
            LIMIT 1
        """, (candidate_id, opportunity_id))
        if cur.fetchone():
            # row exists; assume created or updated above
            pass
        else:
            # extremely rare (race), ensure it
            cur.execute("""
                INSERT INTO hire_opportunity (candidate_id, opportunity_id, account_id)
                VALUES (%s, %s, %s)
            """, (candidate_id, opportunity_id, account_id))
            created = True

        # status alignment for batches
        cur.execute("""
            UPDATE candidates_batches cb
               SET status = %s
             WHERE cb.candidate_id = %s
               AND EXISTS (
                 SELECT 1
                   FROM batch b
                  WHERE b.batch_id = cb.batch_id
                    AND b.opportunity_id = %s
               )
        """, ('Client hired', candidate_id, opportunity_id))
        if cur.rowcount == 0:
            cur.execute("""
                UPDATE candidates_batches
                   SET status = %s
                 WHERE candidate_id = %s
            """, ('Client hired', candidate_id))

        # derive end_date from buyout if needed (only if caller didn’t set end_date)
        if ('buyout_dolar' in data or 'buyout_daterange' in data) and ('end_date' not in data):
            def _end_date_from_buyout(val):
                if not val:
                    return None
                s = str(val)
                m_full = re.findall(r'\d{4}-\d{2}-\d{2}', s)
                if m_full:
                    y, mo, d = map(int, m_full[-1].split('-'))
                    last = calendar.monthrange(y, mo)[1]
                    return f"{y:04d}-{mo:02d}-{last:02d}"
                m_ym = re.search(r'(\d{4})-(\d{2})', s)
                if m_ym:
                    y = int(m_ym.group(1)); mo = int(m_ym.group(2))
                    last = calendar.monthrange(y, mo)[1]
                    return f"{y:04d}-{mo:02d}-{last:02d}"
                return None

            cur.execute("""
                SELECT buyout_daterange
                  FROM hire_opportunity
                 WHERE candidate_id = %s AND opportunity_id = %s
                 LIMIT 1
            """, (candidate_id, opportunity_id))
            row = cur.fetchone()
            bo_val = data.get('buyout_daterange') or (row and row['buyout_daterange'])
            computed_end = _end_date_from_buyout(bo_val)
            if computed_end:
                cur.execute("""
                    UPDATE hire_opportunity
                       SET end_date = %s
                     WHERE candidate_id = %s AND opportunity_id = %s
                """, (computed_end, candidate_id, opportunity_id))

        # align status based on end_date
        cur.execute("""
            UPDATE hire_opportunity
               SET status = CASE WHEN end_date IS NULL THEN 'active' ELSE 'inactive' END
             WHERE candidate_id = %s AND opportunity_id = %s
        """, (candidate_id, opportunity_id))

        conn.commit()
        return jsonify({'success': True, 'created': created, 'updated': updated})

    except Exception as e:
        conn.rollback()
        import traceback
        print("❌ Error in /candidates/<id>/hire:")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@bp.route('/candidates/<int:candidate_id>/salary_updates', methods=['GET'])
def get_salary_updates(candidate_id):
    try:
        logging.info(f"📤 GET /candidates/{candidate_id}/salary_updates")

        conn = get_connection()
        logging.info("✅ DB connected")

        cur = conn.cursor()
        cur.execute("""
            SELECT update_id, salary, fee, date
            FROM salary_updates
            WHERE candidate_id = %s
            ORDER BY date DESC
        """, (candidate_id,))
        logging.info("🟢 Query executed")

        updates = cur.fetchall()
        colnames = [desc[0] for desc in cur.description]
        result = [dict(zip(colnames, row)) for row in updates]
        logging.info(f"📦 Data: {result}")

        cur.close()
        conn.close()

        return jsonify(result)

    except Exception as e:
        logging.error("❌ ERROR en GET /salary_updates")
        logging.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/candidates/<int:candidate_id>/salary_updates', methods=['POST'])
def create_salary_update(candidate_id):
    try:
        logging.info(f"📩 POST /candidates/{candidate_id}/salary_updates")

        data = request.get_json()
        logging.info(f"📥 Datos recibidos: {data}")

        salary = data.get('salary')
        fee = data.get('fee')
        date = data.get('date') or datetime.now().strftime('%Y-%m-%d')

        if salary is None or fee is None:
            logging.error("❌ Faltan salary o fee en la solicitud")
            return jsonify({'error': 'Missing salary or fee'}), 400

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT COALESCE(MAX(update_id), 0) FROM salary_updates")
        new_id = cur.fetchone()[0] + 1

        cur.execute("""
            INSERT INTO salary_updates (update_id, candidate_id, salary, fee, date)
            VALUES (%s, %s, %s, %s, %s)
        """, (new_id, candidate_id, salary, fee, date))

        conn.commit()
        cur.close()
        conn.close()

        logging.info(f"✅ Update creado: ID {new_id}, salary {salary}, fee {fee}, date {date}")
        return jsonify({'success': True, 'update_id': new_id})

    except Exception as e:
        logging.error("❌ ERROR en POST /salary_updates:")
        logging.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/salary_updates/<int:update_id>', methods=['DELETE'])
def delete_salary_update(update_id):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM salary_updates WHERE update_id = %s", (update_id,))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/candidates/<int:candidate_id>/is_hired')
def is_candidate_hired(candidate_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 1 FROM opportunity WHERE candidato_contratado = %s LIMIT 1
        """, (candidate_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return jsonify({'is_hired': bool(result)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/candidates/<int:candidate_id>/batch', methods=['PATCH'])
def assign_candidate_to_batch(candidate_id):
    print(f"🔄 PATCH /candidates/{candidate_id}/batch")

    try:
        data = request.get_json()
        print(f"📥 Received data: {data}")

        batch_id = data.get('batch_id')
        if not batch_id:
            print("❌ Missing batch_id in request")
            return jsonify({'error': 'Missing batch_id'}), 400

        print(f"✅ Assigning candidate {candidate_id} to batch {batch_id}")

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO candidates_batches (candidate_id, batch_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
        """, (candidate_id, batch_id))

        conn.commit()
        print(f"✅ Insert successful")

        cursor.close()
        conn.close()

        return jsonify({'success': True}), 200

    except Exception as e:
        print(f"❌ Error assigning candidate to batch: {str(e)}")
        return jsonify({'error': str(e)}), 500

@bp.route('/candidates_batches/status', methods=['GET','PATCH'])
def update_candidate_batch_status():
    data = request.get_json()
    candidate_id = data.get('candidate_id')
    batch_id = data.get('batch_id')
    status = data.get('status')

    print("📥 PATCH /candidates_batches/status")
    print("📌 candidate_id:", candidate_id)
    print("📌 batch_id:", batch_id)
    print("📌 status:", status)

    if not all([candidate_id, batch_id, status]):
        print("❌ Missing required fields")
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE candidates_batches
            SET status = %s
            WHERE candidate_id = %s AND batch_id = %s
        """, (status, candidate_id, batch_id))
        conn.commit()
        cursor.close()
        conn.close()

        print("✅ Status updated successfully")
        return jsonify({'success': True}), 200
    except Exception as e:
        print("❌ Exception:", str(e))
        return jsonify({'error': str(e)}), 500

@bp.route('/candidates_batches', methods=['DELETE'])
def delete_candidate_from_batch():
    data = request.get_json()
    candidate_id = data.get('candidate_id')
    batch_id = data.get('batch_id')

    if not candidate_id or not batch_id:
        return jsonify({'error': 'Missing candidate_id or batch_id'}), 400

    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            DELETE FROM candidates_batches
            WHERE candidate_id = %s AND batch_id = %s
        """, (candidate_id, batch_id))

        conn.commit()
        cur.close(); conn.close()
        return jsonify({'success': True}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/candidates/light_fast')
def get_candidates_light_fast():
    """
    Devuelve candidatos + status (unhired/active) y opp_model del hire ACTIVO.
    Regla:
      - Hay hire_opportunity con end_date IS NULL => status='active' y opp_model viene de opportunity.
      - No hay hire activo (o solo cerrados)     => status='unhired' y opp_model=NULL.
    """
    blacklist_filter = (request.args.get('blacklist_filter') or 'all').strip().lower()
    if blacklist_filter not in ('all', 'only', 'exclude'):
        blacklist_filter = 'all'

    try:
        conn = get_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        blacklist_columns = set(_get_blacklist_columns(conn))
        has_normalized_column = 'linkedin_normalized' in blacklist_columns

        c_linkedin_norm = _linkedin_normalize_sql('c.linkedin')
        b_column = 'b.linkedin_normalized' if has_normalized_column else 'b.linkedin'
        b_linkedin_norm = _linkedin_normalize_sql(b_column)

        params = [blacklist_filter, blacklist_filter, blacklist_filter]
        cur.execute(f"""
            WITH active_or_latest AS (
              -- Prioriza la fila ACTIVA (end_date IS NULL). Si no hay, toma la más reciente por start_date.
              SELECT DISTINCT ON (h.candidate_id)
                     h.candidate_id,
                     h.opportunity_id,
                     h.end_date,
                     h.start_date
              FROM hire_opportunity h
              ORDER BY h.candidate_id,
                       (h.end_date IS NULL) DESC,
                       h.start_date DESC NULLS LAST
            ),
            normalized_candidates AS (
              SELECT
                c.candidate_id,
                c.name,
                c.country,
                c.phone,
                c.linkedin,
                {c_linkedin_norm} AS linkedin_norm
              FROM candidates c
            ),
            normalized_blacklist AS (
              SELECT
                b.blacklist_id,
                {b_linkedin_norm} AS linkedin_norm,
                b.candidate_id
              FROM blacklist b
            ),
            candidates_with_flags AS (
              SELECT
                nc.candidate_id,
                nc.name,
                nc.country,
                nc.phone,
                nc.linkedin,
                CASE
                  WHEN a.candidate_id IS NULL THEN 'unhired'
                  WHEN a.end_date IS NULL      THEN 'active'
                  ELSE 'unhired'
                END AS status,
                CASE
                  WHEN a.end_date IS NULL THEN o.opp_model
                  ELSE NULL
                END AS opp_model,
                COALESCE(bl.is_blacklisted, FALSE) AS is_blacklisted
              FROM normalized_candidates nc
              LEFT JOIN active_or_latest a ON a.candidate_id = nc.candidate_id
              LEFT JOIN opportunity o      ON o.opportunity_id = a.opportunity_id
              LEFT JOIN LATERAL (
                SELECT TRUE AS is_blacklisted
                FROM normalized_blacklist nb
                WHERE (
                        nb.linkedin_norm IS NOT NULL
                    AND nc.linkedin_norm IS NOT NULL
                    AND nb.linkedin_norm = nc.linkedin_norm
                )
                OR (
                    nb.candidate_id IS NOT NULL
                    AND nc.candidate_id IS NOT NULL
                    AND nb.candidate_id = nc.candidate_id
                )
                LIMIT 1
              ) bl ON TRUE
            )
            SELECT
              candidate_id,
              name,
              country,
              phone,
              linkedin,
              status,
              opp_model,
              is_blacklisted
            FROM candidates_with_flags
            WHERE (%s = 'all')
               OR (%s = 'only' AND is_blacklisted)
               OR (%s = 'exclude' AND NOT is_blacklisted)
            ORDER BY candidate_id DESC;
        """, params)

        rows = cur.fetchall()
        cur.close(); conn.close()
        return jsonify(rows)
    except Exception as e:
        import traceback; print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@bp.route('/candidates/<int:candidate_id>/resignations', methods=['GET'])
def list_resignations(candidate_id):
    try:
        prefix = f"resignations/resignation-letter_{candidate_id}_"
        items = list_s3_with_prefix(prefix)
        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/candidates/<int:candidate_id>/resignations', methods=['POST'])
def upload_resignation(candidate_id):
    f = request.files.get('file')
    if not f:
        return jsonify({"error": "Missing file"}), 400

    filename_orig = (f.filename or '')
    mime = (f.mimetype or '').lower()

    # --- Robustez Safari: valida por encabezado "%PDF-"
    try:
        head = f.stream.read(5)
        f.stream.seek(0)
    except Exception:
        head = b''

    looks_like_pdf = head.startswith(b'%PDF-')
    has_pdf_ext    = filename_orig.lower().endswith('.pdf')
    is_pdf_mime    = (mime.startswith('application/pdf') or mime == 'application/octet-stream')

    if not (looks_like_pdf or has_pdf_ext or is_pdf_mime):
        return jsonify({"error": "Only PDF is allowed for resignation letters"}), 400

    try:
        s3_key = f"resignations/resignation-letter_{candidate_id}_{uuid.uuid4()}.pdf"
        services.s3_client.upload_fileobj(
            f, services.S3_BUCKET, s3_key,
            ExtraArgs={
                'ContentType': 'application/pdf',
                # 👇 ayuda a que el navegador lo abra inline:
                'ContentDisposition': 'inline; filename="resignation-letter.pdf"'
            }
        )
        prefix = f"resignations/resignation-letter_{candidate_id}_"
        items = list_s3_with_prefix(prefix)  # asegúrate que devuelva name,url,key
        return jsonify({"message": "Resignation letter uploaded", "items": items})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/candidates/<int:candidate_id>/resignations', methods=['DELETE'])
def delete_resignation(candidate_id):
    data = request.get_json(silent=True) or {}
    key = data.get("key")
    if not key or not key.startswith(f"resignations/resignation-letter_{candidate_id}_"):
        return jsonify({"error": "Missing or invalid key"}), 400
    try:
        services.s3_client.delete_object(Bucket=services.S3_BUCKET, Key=key)
        # devolver lista actualizada
        prefix = f"resignations/resignation-letter_{candidate_id}_"
        items = list_s3_with_prefix(prefix)
        return jsonify({"message": "Resignation letter deleted", "items": items})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _normalize_equipos(val):
    if val is None:
        return None
    if isinstance(val, list):
        return json.dumps([str(x).strip() for x in val if str(x).strip()])
    s = str(val).strip()
    if not s:
        return None
    try:
        loaded = json.loads(s)
        if isinstance(loaded, list):
            return json.dumps([str(x).strip() for x in loaded if str(x).strip()])
    except Exception:
        pass
    parts = [p.strip() for p in s.split(',') if p.strip()]
    return json.dumps(parts) if parts else None


@bp.route('/equipments', methods=['GET', 'POST'])
def equipments_route():
    try:
        if request.method == 'GET':
            conn = get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT
                    equipment_id,
                    candidate_id,
                    account_id,
                    TO_CHAR(pedido, 'YYYY-MM-DD')          AS pedido,
                    proveedor,
                    TO_CHAR(entrega, 'YYYY-MM-DD')         AS entrega,
                    TO_CHAR(retiro, 'YYYY-MM-DD')          AS retiro,
                    TO_CHAR(almacenamiento, 'YYYY-MM-DD')  AS almacenamiento,
                    estado,
                    pais,
                    costo,
                    equipos
                FROM equipments
                ORDER BY pedido DESC NULLS LAST, entrega DESC NULLS LAST, equipment_id DESC
            """)
            rows = cur.fetchall()
            cur.close(); conn.close()
            return jsonify(rows)

        # POST
        data = request.get_json() or {}

        def _none_if_empty(v):
            if v is None: return None
            if isinstance(v, str) and v.strip() == '': return None
            return v

        candidate_id    = data.get('candidate_id')
        account_id      = data.get('account_id')
        proveedor       = _none_if_empty(data.get('proveedor'))         # 'quipteams' | 'bord'
        estado          = _none_if_empty(data.get('estado'))            # 'nueva' | 'vieja' | 'stockeada'
        pedido          = _none_if_empty(data.get('pedido'))            # 'YYYY-MM-DD' o None
        entrega         = _none_if_empty(data.get('entrega'))
        retiro          = _none_if_empty(data.get('retiro'))
        almacenamiento  = _none_if_empty(data.get('almacenamiento'))
        pais            = _none_if_empty(data.get('pais'))
        costo           = data.get('costo') if data.get('costo') not in ('', None) else None
        equipos         = _normalize_equipos(data.get('equipos'))

        missing = []
        if not candidate_id: missing.append('candidate_id')
        if not account_id:   missing.append('account_id')
        if not proveedor:    missing.append('proveedor')
        if not estado:       missing.append('estado')
        if missing:
            return jsonify({'error': f"Missing required fields: {', '.join(missing)}"}), 400

        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            INSERT INTO equipments (
                candidate_id, account_id, pedido, proveedor, entrega, retiro,
                almacenamiento, estado, pais, costo, equipos
            )
            VALUES (%s, %s, %s::date, %s, %s::date, %s::date,
                    %s::date, %s, %s, %s, %s)
            RETURNING
                equipment_id,
                candidate_id,
                account_id,
                TO_CHAR(pedido, 'YYYY-MM-DD')          AS pedido,
                proveedor,
                TO_CHAR(entrega, 'YYYY-MM-DD')         AS entrega,
                TO_CHAR(retiro, 'YYYY-MM-DD')          AS retiro,
                TO_CHAR(almacenamiento, 'YYYY-MM-DD')  AS almacenamiento,
                estado,
                pais,
                costo,
                equipos
        """, (
            int(candidate_id), int(account_id), pedido, proveedor, entrega, retiro,
            almacenamiento, estado, pais, costo, equipos
        ))
        created = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        return jsonify(created), 201

    except Exception as e:
        import traceback; print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/equipments/<int:equipment_id>', methods=['GET', 'PATCH', 'DELETE'])
def equipment_item(equipment_id):
    try:
        if request.method == 'GET':
            conn = get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT
                    equipment_id,
                    candidate_id,
                    account_id,
                    TO_CHAR(pedido, 'YYYY-MM-DD')          AS pedido,
                    proveedor,
                    TO_CHAR(entrega, 'YYYY-MM-DD')         AS entrega,
                    TO_CHAR(retiro, 'YYYY-MM-DD')          AS retiro,
                    TO_CHAR(almacenamiento, 'YYYY-MM-DD')  AS almacenamiento,
                    estado,
                    pais,
                    costo,
                    equipos
                FROM equipments
                WHERE equipment_id = %s
            """, (equipment_id,))
            row = cur.fetchone()
            cur.close(); conn.close()
            if not row:
                return jsonify({"error": "Not found"}), 404
            return jsonify(row)

        if request.method == 'DELETE':
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM equipments WHERE equipment_id = %s", (equipment_id,))
            deleted = cur.rowcount
            conn.commit()
            cur.close(); conn.close()
            if deleted == 0:
                return jsonify({"error":"Not found"}), 404
            return jsonify({"success": True})

        # PATCH
        data = request.get_json(silent=True) or {}

        mapping = {
            'pedido': 'pedido',
            'entrega': 'entrega',
            'retiro': 'retiro',
            'almacenamiento': 'almacenamiento',
            'estado': 'estado',
            'pais': 'pais',
            'costo': 'costo',
            'equipos': 'equipos'
        }

        set_cols, set_vals = [], []
        for k, col in mapping.items():
            if k in data:
                if k in ('pedido','entrega','retiro','almacenamiento'):
                    set_cols.append(f"{col} = %s::date")
                    set_vals.append(data[k])
                elif k == 'equipos':
                    set_cols.append(f"{col} = %s")
                    set_vals.append(_normalize_equipos(data[k]))
                else:
                    set_cols.append(f"{col} = %s")
                    set_vals.append(data[k])

        if not set_cols:
            return jsonify({"error": "No valid fields provided"}), 400

        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        set_vals.append(equipment_id)
        cur.execute(f"""
            UPDATE equipments
            SET {', '.join(set_cols)}
            WHERE equipment_id = %s
        """, set_vals)
        if cur.rowcount == 0:
            cur.close(); conn.close()
            return jsonify({"error":"Not found"}), 404

        # ⬇️  SIN recursión: devolvemos la fila actualizada ya formateada
        cur.execute("""
            SELECT
                equipment_id,
                candidate_id,
                account_id,
                TO_CHAR(pedido, 'YYYY-MM-DD')          AS pedido,
                proveedor,
                TO_CHAR(entrega, 'YYYY-MM-DD')         AS entrega,
                TO_CHAR(retiro, 'YYYY-MM-DD')          AS retiro,
                TO_CHAR(almacenamiento, 'YYYY-MM-DD')  AS almacenamiento,
                estado,
                pais,
                costo,
                equipos
            FROM equipments
            WHERE equipment_id = %s
        """, (equipment_id,))
        updated = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        return jsonify(updated)

    except Exception as e:
        import traceback; print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/hire_opportunity', methods=['GET'])
def list_hire_opportunity():
    """
    Uso principal: /hire_opportunity?candidate_id=123
    Devuelve todas las filas de hire_opportunity para ese candidato.
    El front elegirá la fila con end_date NULL como 'activa'.
    """
    try:
        candidate_id = request.args.get('candidate_id', type=int)
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if candidate_id:
            cur.execute("""
                SELECT candidate_id, opportunity_id, account_id, start_date, end_date, status
                FROM hire_opportunity
                WHERE candidate_id = %s
                ORDER BY (end_date IS NULL) DESC,
                         start_date DESC NULLS LAST
            """, (candidate_id,))
        else:
            # opcional: listado acotado si no pasan candidate_id
            cur.execute("""
                SELECT candidate_id, opportunity_id, account_id, start_date, end_date, status
                FROM hire_opportunity
                ORDER BY candidate_id DESC
                LIMIT 200
            """)

        rows = cur.fetchall()
        cur.close(); conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/search/candidates-in-hire', methods=['GET'])
def search_candidates_in_hire():
    """
    Devuelve: [{candidate_id, name, account_id, account_name}]
    - Solo candidatos presentes en hire_opportunity
    - account_id: la fila activa (end_date NULL) o, si no hay activa, la más reciente por start_date
    """
    try:
        q = (request.args.get('q') or '').strip()
        if len(q) < 2:
            return jsonify([])

        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            WITH ranked AS (
              SELECT
                c.candidate_id,
                c.name,
                h.account_id,
                h.start_date,
                h.end_date,
                ROW_NUMBER() OVER (
                  PARTITION BY c.candidate_id
                  ORDER BY (h.end_date IS NULL) DESC,
                           h.start_date DESC NULLS LAST
                ) AS rn
              FROM candidates c
              JOIN hire_opportunity h
                ON h.candidate_id = c.candidate_id
              WHERE c.name ILIKE %s
            )
            SELECT
              r.candidate_id,
              r.name,
              r.account_id,
              a.client_name AS account_name
            FROM ranked r
            LEFT JOIN account a ON a.account_id = r.account_id
            WHERE r.rn = 1
            ORDER BY LOWER(r.name) ASC
            LIMIT 20;
        """, (f"%{q}%",))
        items = cur.fetchall()
        cur.close(); conn.close()
        return jsonify(items)
    except Exception as e:
        import traceback; print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/candidates/search')
def candidates_search_alias():
    """
    Alias compatible con el fallback del front:
    /candidates/search?q=ana -> devuelve [{candidate_id, name}]
    """
    try:
        q = (request.args.get('q') or '').strip()
        if len(q) < 2:
            return jsonify([])

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT candidate_id, name, email, linkedin, country
            FROM candidates
            WHERE name ILIKE %s OR linkedin ILIKE %s
            ORDER BY LOWER(name) ASC
            LIMIT 15
        """, (f"%{q}%", f"%{q}%"))
        rows = cur.fetchall()
        cur.close(); conn.close()
        return jsonify([
            {
                "candidate_id": r[0],
                "name": r[1],
                "email": r[2],
                "linkedin": r[3],
                "country": r[4]
            }
            for r in rows
        ])
    except Exception as e:
        return jsonify([]), 200

@bp.route('/resumes/<int:candidate_id>', methods=['GET', 'PATCH', 'OPTIONS'])
def resumes(candidate_id):
    if request.method == 'OPTIONS':
        return ('', 204)

    if request.method == 'GET':
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    about, 
                    work_experience, 
                    education, 
                    tools, 
                    languages,
                    video_link,
                    extract_cv_pdf,
                    cv_pdf_s3
                FROM resume
                WHERE candidate_id = %s
            """, (candidate_id,))
            row = cursor.fetchone()

            if not row:
                return jsonify({
                    "about": "",
                    "work_experience": "[]",
                    "education": "[]",
                    "tools": "[]",
                    "languages": "[]",
                    "video_link": "",
                    "extract_cv_pdf": "",
                    "cv_pdf_s3": ""
                })

            colnames = [desc[0] for desc in cursor.description]
            resume = dict(zip(colnames, row))
            cursor.close(); conn.close()
            return jsonify(resume)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ---------- PATCH ----------
    try:
        logging.info("📥 PATCH /resumes/%s", candidate_id)
        data = request.get_json(silent=True) or {}
        allow_clear = (request.args.get('allow_clear', 'false').lower() == 'true')

        def _is_blank(v):
            if v is None: return True
            if isinstance(v, str):
                s = v.strip()
                if s in ("", "[]", "{}"): 
                    return True
                try:
                    j = json.loads(s)
                    return j == [] or j == {}
                except Exception:
                    return False
            if isinstance(v, (list, dict)):
                return len(v) == 0
            return False

        # normaliza 'education' para asegurar 'country'
        if 'education' in data:
            try:
                edu = json.loads(data['education']) if isinstance(data['education'], str) else data['education']
                if isinstance(edu, list):
                    for item in edu:
                        if isinstance(item, dict) and 'country' not in item:
                            item['country'] = ''
                data['education'] = edu
            except Exception:
                pass

        allowed_fields = ['about','work_experience','education','tools','languages','video_link']

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT 1 FROM resume WHERE candidate_id = %s", (candidate_id,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO resume (candidate_id) VALUES (%s)", (candidate_id,))
            conn.commit()

        updates, values = [], []
        for field in allowed_fields:
            if field in data:
                val = data[field]
                if not allow_clear and _is_blank(val):
                    continue
                if isinstance(val, (dict, list)):
                    val = json.dumps(val)
                updates.append(f"{field} = %s")
                values.append(val)

        if not updates:
            cursor.close(); conn.close()
            return jsonify({'success': True, 'skipped': True})

        values.append(candidate_id)
        cursor.execute(f"""
            UPDATE resume
            SET {', '.join(updates)}
            WHERE candidate_id = %s
        """, values)
        conn.commit()
        cursor.close(); conn.close()
        return jsonify({'success': True}), 200

    except Exception as e:
        logging.exception("❌ Error en PATCH /resumes")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/blacklist/status', methods=['GET'])
def get_blacklist_status():
    candidate_id = request.args.get('candidate_id', type=int)
    if not candidate_id:
        return jsonify({'error': 'candidate_id is required'}), 400

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(
            "SELECT candidate_id, linkedin FROM candidates WHERE candidate_id = %s",
            (candidate_id,)
        )
        candidate = cursor.fetchone()
        if not candidate:
            return jsonify({'error': 'Candidate not found'}), 404

        existing, _ = _find_blacklist_match(
            cursor,
            candidate_id=candidate['candidate_id'],
            linkedin_value=candidate.get('linkedin'),
            fallback_to_candidate_id=True
        )
        payload = {
            'is_blacklisted': bool(existing),
            'blacklist_id': existing['blacklist_id'] if existing else None
        }
        return jsonify(payload)
    except Exception as exc:
        logging.exception("❌ Failed to fetch blacklist status for candidate %s", candidate_id)
        return jsonify({'error': str(exc)}), 500
    finally:
        cursor.close()
        conn.close()


@bp.route('/api/blacklist', methods=['POST'])
def create_blacklist_entry():
    data = request.get_json(silent=True) or {}
    candidate_id = data.get('candidate_id')
    try:
        candidate_id = int(candidate_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'candidate_id is required'}), 400

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT * FROM candidates WHERE candidate_id = %s", (candidate_id,))
        candidate = cursor.fetchone()
        if not candidate:
            return jsonify({'error': 'Candidate not found'}), 404

        existing, linkedin_norm = _find_blacklist_match(
            cursor,
            candidate_id=candidate_id,
            linkedin_value=candidate.get('linkedin'),
            fallback_to_candidate_id=True
        )
        if existing:
            return jsonify(existing), 200

        insert_columns, values = _build_blacklist_insert_payload(conn, candidate, linkedin_norm)
        if not insert_columns:
            return jsonify({'error': 'Blacklist table has no columns to insert'}), 500

        placeholders = ', '.join(['%s'] * len(insert_columns))
        cursor.execute(
            f"INSERT INTO blacklist ({', '.join(insert_columns)}) VALUES ({placeholders}) RETURNING *",
            values
        )
        created_row = cursor.fetchone()
        conn.commit()
        return jsonify(created_row), 201
    except Exception as exc:
        conn.rollback()
        logging.exception("❌ Failed to add candidate %s to blacklist", candidate_id)
        return jsonify({'error': str(exc)}), 500
    finally:
        cursor.close()
        conn.close()


@bp.route('/api/blacklist/<int:blacklist_id>', methods=['DELETE'])
def delete_blacklist_entry(blacklist_id):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(
            "DELETE FROM blacklist WHERE blacklist_id = %s RETURNING blacklist_id",
            (blacklist_id,)
        )
        deleted = cursor.fetchone()
        if not deleted:
            conn.rollback()
            return jsonify({'error': 'Blacklist entry not found'}), 404

        conn.commit()
        return jsonify({'status': 'deleted', 'blacklist_id': deleted['blacklist_id']})
    except Exception as exc:
        conn.rollback()
        logging.exception("❌ Failed to delete blacklist entry %s", blacklist_id)
        return jsonify({'error': str(exc)}), 500
    finally:
        cursor.close()
        conn.close()


__all__ = ['bp']
