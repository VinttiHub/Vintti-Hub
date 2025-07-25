from flask import Flask, jsonify, request
import os
from dotenv import load_dotenv
import boto3
import uuid
from botocore.exceptions import NoCredentialsError
from affinda import AffindaAPI, TokenCredential
import openai
import traceback
import logging
import psycopg2
import requests
from datetime import datetime
import json
from ai_routes import register_ai_routes
from db import get_connection 
import re

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

openai.api_key = os.getenv("OPENAI_API_KEY")
affinda = AffindaAPI(
  credential=TokenCredential(token=os.getenv('AFFINDA_API_KEY'))
)
WORKSPACE_ID = os.getenv('AFFINDA_WORKSPACE_ID')
DOC_TYPE_ID = os.getenv('AFFINDA_DOCUMENT_TYPE_ID')

load_dotenv()

# Configurar cliente S3
s3_client = boto3.client(
    's3',
    region_name=os.getenv('AWS_REGION'),
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)

S3_BUCKET = os.getenv('S3_BUCKET_NAME')

app = Flask(__name__)

register_ai_routes(app)

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
    except Exception as e:
        return {"error": str(e)}

@app.route('/')
def home():
    return 'API running 🎉'
@app.route('/candidates/light', methods=['GET'])
def get_candidates_light():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                candidate_id,
                name,
                country,
                phone,
                linkedin,
                condition
            FROM candidates
        """)
        rows = cursor.fetchall()
        candidates = [dict(zip(
            ['candidate_id', 'full_name', 'country', 'phone', 'linkedin', 'condition'],
            row
        )) for row in rows]

        cursor.close()
        conn.close()
        return jsonify(candidates)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/opportunities/light')
def get_opportunities_light():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                o.opportunity_id,
                o.opp_stage,
                o.opp_position_name,
                o.opp_type,
                o.opp_model,
                o.opp_hr_lead,
                o.comments,
                o.nda_signature_or_start_date,
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

@app.route('/data/light')
def get_accounts_light():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                a.account_id,
                a.client_name,
                a.account_manager,
                a.contract,
                a.priority
            FROM account a
        """)
        rows = cursor.fetchall()
        accounts = [dict(zip(['account_id', 'client_name', 'account_manager', 'contract', 'priority'], row)) for row in rows]
        cursor.close()
        conn.close()
        return jsonify(accounts)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/data')
def get_accounts():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        # Traer todas las accounts
        cursor.execute("SELECT * FROM account")
        accounts_rows = cursor.fetchall()
        accounts_columns = [desc[0] for desc in cursor.description]

        accounts = [dict(zip(accounts_columns, row)) for row in accounts_rows]

        for account in accounts:
            account_id = account['account_id']

            # Calcular TRR, TSF, TSR
            cursor.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN peoplemodel = 'Recruiting' THEN employee_revenue ELSE 0 END), 0) AS trr,
                    COALESCE(SUM(CASE WHEN peoplemodel = 'Staffing' THEN employee_fee ELSE 0 END), 0) AS tsf,
                    COALESCE(SUM(CASE WHEN peoplemodel = 'Staffing' THEN employee_revenue ELSE 0 END), 0) AS tsr
                FROM candidates
                WHERE account_id = %s
            """, (account_id,))
            
            sums_row = cursor.fetchone()
            account['trr'] = sums_row[0]
            account['tsf'] = sums_row[1]
            account['tsr'] = sums_row[2]

            ### Calcular Status:
            # 1️⃣ Traer opportunities
            cursor.execute("""
                SELECT opportunity_id, opp_stage
                FROM opportunity
                WHERE account_id = %s
            """, (account_id,))
            opp_rows = cursor.fetchall()
            if not opp_rows:
                # Si no hay opportunities, entonces Pending
                account['calculated_status'] = 'Pending'
                continue

            opp_ids = [row[0] for row in opp_rows]
            opp_stages = [row[1] for row in opp_rows]

            # 2️⃣ Traer candidates de esas opportunities
            cursor.execute("""
                SELECT condition
                FROM candidates
                WHERE opportunity_id = ANY(%s)
                """, ([*opp_ids],))  # o simplemente (opp_ids,) si ya es una lista
            candidate_rows = cursor.fetchall()
            candidate_stages = [row[0] for row in candidate_rows]

            # 3️⃣ Aplicar reglas:
            status = 'Pending'

            # Priority order:
            if any((s or '').lower() == 'active' for s in candidate_stages):
                status = 'Active'
            elif any((s or '').lower() == 'inactive' for s in candidate_stages):
                status = 'Inactive'
            elif any((stage or '').lower() in ['interviewing', 'sourcing', 'nda sent', 'negotiating'] for stage in opp_stages):
                status = 'In Process'

            account['calculated_status'] = status

        cursor.close()
        conn.close()

        return jsonify(accounts)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/opportunities')
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

@app.route('/candidates', methods=['GET'])
def get_candidates():
    search = request.args.get('search')
    if search:
        return search_candidates()
    
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Obtener todos los candidatos
        cur.execute("SELECT * FROM candidates")
        candidates_rows = cur.fetchall()
        candidate_cols = [desc[0] for desc in cur.description]
        candidates = [dict(zip(candidate_cols, row)) for row in candidates_rows]

        # Para cada candidato, verificar si es empleado (si está en candidato_contratado)
        for candidate in candidates:
            candidate_id = candidate['candidate_id']

            cur.execute("""
                SELECT 1
                FROM opportunity o
                JOIN opportunity_candidates oc ON o.opportunity_id = oc.opportunity_id
                WHERE oc.candidate_id = %s AND o.candidato_contratado = %s
                LIMIT 1
            """, (candidate_id, candidate_id))
            result = cur.fetchone()
            candidate['employee'] = '✔️' if result else '❌'

        cur.close()
        conn.close()
        return jsonify(candidates)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

def search_candidates():
    q = request.args.get('search', '').strip()
    conn = get_connection()
    cur = conn.cursor()
    # fuzzy match en nombre
    cur.execute("""
      SELECT candidate_id, name 
      FROM candidates
      WHERE name ILIKE %s
      ORDER BY similarity(name, %s) DESC
      LIMIT 5;
    """, (f'%{q}%', q))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify([{"candidate_id": r[0], "name": r[1]} for r in rows])


@app.route('/login', methods=['POST'])
def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    try:
        conn = get_connection()
        cursor = conn.cursor()
        query = """
            SELECT nickname FROM users 
            WHERE email_vintti = %s AND password = %s
        """
        cursor.execute(query, (email, password))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            return jsonify({"success": True, "nickname": result[0]})
        else:
            return jsonify({"success": False, "message": "Correo o contraseña incorrectos"}), 401

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    
@app.route('/accounts/<account_id>')
def get_account_by_id(account_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM account WHERE account_id = %s", (account_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Account not found"}), 404

        colnames = [desc[0] for desc in cursor.description]
        account = dict(zip(colnames, row))

        cursor.close()
        conn.close()

        return jsonify(account)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/accounts/<account_id>/opportunities')
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

@app.route('/opportunities/<int:opportunity_id>')
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

@app.route('/users')
def get_users():
    result = fetch_data_from_table("users")
    if "error" in result:
        return jsonify(result), 500
    return jsonify([
        {
            "user_name": row["user_name"],
            "email_vintti": row["email_vintti"]
        }
        for row in result
    ])


@app.route('/opportunities', methods=['POST'])
def create_opportunity():
    data = request.get_json()
    client_name = data.get('client_name')
    opp_model = data.get('opp_model')
    position_name = data.get('position_name')
    sales_lead = data.get('sales_lead')
    opp_type = data.get('opp_type')

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # 🔍 Buscar el account_id según el client_name
        cursor.execute("SELECT account_id FROM account WHERE client_name = %s LIMIT 1", (client_name,))
        account_row = cursor.fetchone()

        if not account_row:
            return jsonify({'error': f'No account found for client_name: {client_name}'}), 400

        account_id = account_row[0]
        # 🔍 Obtener el siguiente opportunity_id
        cursor.execute("SELECT COALESCE(MAX(opportunity_id), 0) + 1 FROM opportunity")
        new_opportunity_id = cursor.fetchone()[0]

        # 🔽 Insertar con ID manual
        cursor.execute("""
            INSERT INTO opportunity (
                opportunity_id, account_id, opp_model, opp_position_name, opp_sales_lead, opp_type, opp_stage
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (new_opportunity_id, account_id, opp_model, position_name, sales_lead, opp_type, 'Deep Dive'))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({'message': 'Opportunity created successfully'}), 201

    except Exception as e:
        import traceback
        print(traceback.format_exc())  # También útil por si miras logs luego
        return jsonify({'error': str(e)}), 500
    


@app.route('/accounts', methods=['GET', 'POST'])
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

            query = """
                INSERT INTO account (
                    client_name, Size, timezone, state,
                    website, linkedin, comments, mail
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """

            cursor.execute(query, (
                data.get("name"),
                data.get("size"),
                data.get("timezone"),
                data.get("state"),
                data.get("website"),
                data.get("linkedin"),
                data.get("about"),
                data.get("mail")  # ✅ Nuevo campo mail
            ))

            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"message": "Account created successfully"}), 201

        except Exception as e:
            import traceback
            print(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

@app.route('/opportunities/<int:opportunity_id>', methods=['PATCH'])
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

@app.route('/accounts/<account_id>/candidates')
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
    
@app.route('/opportunities/<int:opportunity_id>/candidates')
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
                oc.stage_batch,
                oc.stage_pipeline AS stage,
                oc.sign_off
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
    
@app.route('/batches/<int:batch_id>/candidates', methods=['GET'])
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



@app.route('/candidates/<int:candidate_id>')
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
                cv_pdf_scrapper
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
    

@app.route('/opportunities/<int:opportunity_id>/fields', methods=['PATCH'])
def update_opportunity_fields(opportunity_id):
    data = request.get_json()

    allowed_fields = [
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
        'candidato_contratado',
        'comments',
        'motive_close_lost'
    ]

    updates = []
    values = []

    for field in allowed_fields:
        if field in data:
            updates.append(f"{field} = %s")
            values.append(data[field])

    if not updates:
        return jsonify({'error': 'No valid fields provided'}), 400

    values.append(opportunity_id)

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(f"""
            UPDATE opportunity
            SET {', '.join(updates)}
            WHERE opportunity_id = %s
        """, values)

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True}), 200

    except Exception as e:
        print("Error updating opportunity fields:", e)
        return jsonify({'error': str(e)}), 500

@app.route('/accounts/<account_id>', methods=['PATCH'])
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
        'priority'
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

@app.route('/opportunities/<int:opportunity_id>/candidates/<int:candidate_id>/stage', methods=['PATCH'])
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

@app.route('/opportunities/<int:opportunity_id>/candidates/<int:candidate_id>/signoff', methods=['PATCH'])
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

    
@app.route('/accounts/<account_id>/opportunities/candidates')
def get_candidates_by_account_opportunities(account_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                c.candidate_id,
                c.name,
                c.stage,
                o.opportunity_id,
                o.opp_model,
                c.employee_salary,
                c.employee_fee,
                c.employee_revenue,
                c.start_date,
                c.enddate,
                c.status
            FROM opportunity o
            LEFT JOIN candidates c ON o.candidato_contratado = c.candidate_id
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


@app.route('/resumes/<int:candidate_id>', methods=['GET'])
def get_resume(candidate_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                about, 
                work_experience, 
                education, 
                tools, 
                video_link,
                extract_cv_pdf,
                cv_pdf_s3
            FROM resume
            WHERE candidate_id = %s
        """, (candidate_id,))
        row = cursor.fetchone()

        if not row:
            # Si no hay resume creado aún, retornar vacío
            return jsonify({
                    "about": "",
                    "work_experience": "[]",
                    "education": "[]",
                    "tools": "[]",
                    "video_link": "[]",
                    "extract_cv_pdf": "",
                    "cv_pdf_s3": ""
                })

        colnames = [desc[0] for desc in cursor.description]
        resume = dict(zip(colnames, row))

        cursor.close()
        conn.close()

        return jsonify(resume)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/resumes/<int:candidate_id>', methods=['POST', 'PATCH'])
def update_resume(candidate_id):
    try:
        print("📥 PATCH recibido para candidate_id:", candidate_id)
        data = request.get_json()
        print("📦 JSON recibido:", data)

        allowed_fields = [
            'about',
            'work_experience',
            'education',
            'tools',
            'video_link'
        ]

        updates = []
        values = []

        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = %s")
                value = data[field]
                if isinstance(value, (dict, list)):
                    values.append(json.dumps(value))
                else:
                    values.append(value)


        if not updates:
            print("❌ No valid fields in data:", data)
            return jsonify({'error': 'No valid fields provided'}), 400

        values.append(candidate_id)

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT 1 FROM resume WHERE candidate_id = %s", (candidate_id,))
        exists = cursor.fetchone()
        print("🔎 Resume exists?", exists)

        if exists:
            print("🛠 Ejecutando UPDATE")
            cursor.execute(f"""
                UPDATE resume
                SET {', '.join(updates)}
                WHERE candidate_id = %s
            """, values)
        else:
            print("➕ Ejecutando INSERT")
            insert_fields = ", ".join(["candidate_id"] + [f for f in allowed_fields if f in data])
            insert_values = ", ".join(["%s"] * (1 + len(updates)))
            cursor.execute(f"""
                INSERT INTO resume ({insert_fields})
                VALUES ({insert_values})
            """, [candidate_id] + values[:-1])

        conn.commit()
        cursor.close()
        conn.close()

        print("✅ Resume actualizado correctamente")
        return jsonify({'success': True}), 200

    except Exception as e:
        import traceback
        print("❌ Error en PATCH /resumes:")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

    
@app.route('/upload_pdf', methods=['POST'])
def upload_pdf():
    candidate_id = request.form.get('candidate_id')
    pdf_file = request.files.get('pdf')

    if not candidate_id or not pdf_file:
        return jsonify({"error": "Missing candidate_id or pdf file"}), 400

    try:
        # Nombre único en S3
        filename = f"cvs/{candidate_id}_{uuid.uuid4()}.pdf"

        # Subir a S3
        s3_client.upload_fileobj(
            pdf_file,
            S3_BUCKET,
            filename,
            ExtraArgs={'ContentType': 'application/pdf'}
        )

        # Generar signed URL (válida por 1 hora)
        signed_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET, 'Key': filename},
            ExpiresIn=3600
        )

        # Guardar en base de datos
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE resume
            SET cv_pdf_s3 = %s
            WHERE candidate_id = %s
        """, (signed_url, candidate_id))
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"message": "PDF uploaded", "pdf_url": signed_url}), 200

    except NoCredentialsError:
        return jsonify({"error": "AWS credentials not available"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/extract_pdf_affinda', methods=['POST'])
def extract_pdf_affinda():
    candidate_id = request.form.get('candidate_id')
    pdf_file = request.files.get('pdf')

    if not candidate_id or not pdf_file:
        print("❌ candidate_id o PDF faltante")
        return jsonify({"error": "candidate_id and pdf required"}), 400

    try:
        print("📤 Subiendo PDF a Affinda...")
        doc = affinda.create_document(
            file=pdf_file,
            workspace=WORKSPACE_ID,
            document_type=DOC_TYPE_ID,
            wait=True
        )
        data = doc.data
        print("✅ Extracción exitosa:")
        print(str(data)[:1000])  # limitar por si es muy largo

        # Guardar en base de datos
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE resume
            SET extract_cv_pdf = %s
            WHERE candidate_id = %s
        """, (json.dumps(data), candidate_id))
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"success": True, "extracted": data}), 200

    except Exception as e:
        print("❌ ERROR en Affinda:")
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/opportunities/<opportunity_id>/batches', methods=['POST'])
def create_batch(opportunity_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Obtener el batch_id más alto actual
        cursor.execute("SELECT COALESCE(MAX(batch_id), 0) FROM batch")
        current_max_batch_id = cursor.fetchone()[0]
        new_batch_id = current_max_batch_id + 1

        # Obtener cuántos batches tiene esta oportunidad
        cursor.execute("SELECT COUNT(*) FROM batch WHERE opportunity_id = %s", (opportunity_id,))
        batch_count = cursor.fetchone()[0]
        batch_number = batch_count + 1

        # Insertar el nuevo batch
        cursor.execute("""
            INSERT INTO batch (batch_id, batch_number, opportunity_id)
            VALUES (%s, %s, %s)
        """, (new_batch_id, batch_number, opportunity_id))
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
    
@app.route('/opportunities/<opportunity_id>/batches', methods=['GET'])
def get_batches(opportunity_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT batch_id, batch_number, opportunity_id
            FROM batch
            WHERE opportunity_id = %s
            ORDER BY batch_number ASC
        """, (opportunity_id,))
        rows = cursor.fetchall()
        colnames = [desc[0] for desc in cursor.description]
        data = [dict(zip(colnames, row)) for row in rows]

        cursor.close()
        conn.close()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/candidates/<int:candidate_id>', methods=['PATCH'])
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
        'cv_pdf_scrapper'
    ]

    updates = []
    values = []

    for field in allowed_fields:
        if field in data:
            updates.append(f"{field} = %s")
            values.append(data[field])

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
    

@app.route('/opportunities/<int:opportunity_id>/candidates', methods=['POST'])
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


@app.route('/candidates_batches', methods=['POST'])
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

    
@app.route('/candidates/<int:candidate_id>/opportunities')
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

@app.route('/opportunity_candidates/stage_batch', methods=['PATCH'])
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
    
@app.route('/candidates/<int:candidate_id>/hire', methods=['GET', 'PATCH'])
def handle_candidate_hire_data(candidate_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        if request.method == 'GET':
            cursor.execute("""
                SELECT references_notes, employee_salary, employee_fee, computer, extraperks, working_schedule, pto, start_date
                FROM candidates
                WHERE candidate_id = %s
            """, (candidate_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Candidate not found'}), 404
            return jsonify({
                'references_notes': row[0],
                'employee_salary': row[1],
                'employee_fee': row[2],
                'computer': row[3],
                'extraperks': row[4],
                'working_schedule': row[5],
                'pto': row[6],
                'employee_revenue': (row[1] or 0) + (row[2] or 0),
                'start_date': row[7]
            })

        if request.method == 'PATCH':
            data = request.get_json()
            allowed_fields = ['references_notes', 'employee_salary', 'employee_fee', 'employee_revenue', 'computer', 'extraperks', 'working_schedule', 'pto', 'start_date']
            updates = []
            values = []

            for field in allowed_fields:
                if field in data:
                    updates.append(f"{field} = %s")
                    values.append(data[field])

            if not updates:
                return jsonify({'error': 'No valid fields provided'}), 400

            values.append(candidate_id)
            cursor.execute(f"""
                UPDATE candidates
                SET {', '.join(updates)}
                WHERE candidate_id = %s
            """, values)
            conn.commit()
            return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.after_request
def apply_cors_headers(response):
    origin = request.headers.get('Origin')
    allowed_origins = ['https://vinttihub.vintti.com', 'http://localhost:5500', 'http://127.0.0.1:5500']
    
    if origin in allowed_origins:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'

    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS,PATCH,DELETE'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    return response


from send_email_endpoint import register_send_email_route
register_send_email_route(app)

@app.route('/candidates/<int:candidate_id>/salary_updates', methods=['GET'])
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



@app.route('/candidates/<int:candidate_id>/salary_updates', methods=['POST'])
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


@app.route('/salary_updates/<int:update_id>', methods=['DELETE'])
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
    
@app.route('/candidates/<int:candidate_id>/is_hired')
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
    
@app.route('/opportunities/<int:opportunity_id>/candidates/<int:candidate_id>', methods=['DELETE'])
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
    
@app.route('/batches/<int:batch_id>', methods=['DELETE'])
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
    
@app.route('/candidates/<int:candidate_id>/batch', methods=['PATCH'])
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
    
@app.route('/sourcing', methods=['POST'])
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
@app.route('/opportunities/<int:opportunity_id>/latest_sourcing_date')
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

@app.route('/candidates_batches/status', methods=['GET','PATCH'])
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
    
@app.route('/debug/routes')
def debug_routes():
    return jsonify([str(rule) for rule in app.url_map.iter_rules()])

@app.route('/opportunities/<int:opp_id>/pause_days_since_batch', methods=['GET'])
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)