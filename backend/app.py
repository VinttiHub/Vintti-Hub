from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg2
import os
from dotenv import load_dotenv
import boto3
import os
import uuid
from botocore.exceptions import NoCredentialsError
from affinda import AffindaAPI, TokenCredential
import openai
from openai import OpenAI

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
CORS(app)

def get_connection():
    return psycopg2.connect(
        host="vintti-hub-db.ctia0ga4u82m.us-east-2.rds.amazonaws.com",
        port="5432",
        database="postgres",
        user="adminuser",
        password="Elementum54!"
    )

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
    result = fetch_data_from_table("opportunity")
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)

@app.route('/candidates', methods=['GET'])
def get_candidates():
    search = request.args.get('search')
    if search:
        return search_candidates()
    else:
        result = fetch_data_from_table("candidates")
        if "error" in result:
            return jsonify(result), 500
        return jsonify(result)
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
        query = """
            INSERT INTO opportunity (
                account_id, opp_model, opp_position_name, opp_sales_lead, opp_type, opp_stage
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """
        cursor.execute(query, (account_id, opp_model, position_name, sales_lead, opp_type, 'Deep Dive'))


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
                    c.employee_salary,
                    c.batch_id,
                    oc.stage_batch
                FROM candidates c
                INNER JOIN opportunity_candidates oc ON c.candidate_id = oc.candidate_id
                WHERE oc.opportunity_id = %s
        """, (opportunity_id,))

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
                comments
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
        'candidato_contratado'
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
        'timezone'
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
@app.route('/candidates/<int:candidate_id>/stage', methods=['PATCH'])
def update_candidate_stage(candidate_id):
    data = request.get_json()
    new_stage = data.get('stage')

    if new_stage is None:
        return jsonify({'error': 'stage is required'}), 400

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE candidates
            SET stage = %s
            WHERE candidate_id = %s
        """, (new_stage, candidate_id))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True}), 200

    except Exception as e:
        print("Error updating candidate stage:", e)
        return jsonify({'error': str(e)}), 500
@app.route('/accounts/<account_id>/opportunities/candidates')
def get_candidates_by_account_opportunities(account_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # 1️⃣ Primero obtener las opportunities asociadas al account
        cursor.execute("""
            SELECT opportunity_id
            FROM opportunity
            WHERE account_id = %s
        """, (account_id,))
        opportunity_rows = cursor.fetchall()

        # Si no hay opportunities → retornar vacío
        if not opportunity_rows:
            return jsonify([])

        opportunity_ids = [row[0] for row in opportunity_rows]

        # 2️⃣ Ahora obtener los candidates cuyo opportunity_id esté en esa lista
        query = """
            SELECT 
                candidate_id,
                name,
                stage,
                opportunity_id,
                peoplemodel,
                employee_salary,
                employee_fee,
                employee_revenue,
                employee_type,
                startingdate,
                enddate,
                status
            FROM candidates
            WHERE opportunity_id = ANY(%s)
        """
        cursor.execute(query, (opportunity_ids,))
        rows = cursor.fetchall()

        colnames = [desc[0] for desc in cursor.description]
        data = [dict(zip(colnames, row)) for row in rows]

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
    data = request.get_json()

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
            values.append(data[field])

    if not updates:
        return jsonify({'error': 'No valid fields provided'}), 400

    values.append(candidate_id)

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Si el resume no existe aún → INSERT
        cursor.execute("""
            SELECT 1 FROM resume WHERE candidate_id = %s
        """, (candidate_id,))
        exists = cursor.fetchone()

        if exists:
            # UPDATE
            cursor.execute(f"""
                UPDATE resume
                SET {', '.join(updates)}
                WHERE candidate_id = %s
            """, values)
        else:
            # INSERT
            insert_fields = ", ".join(["candidate_id"] + [f for f in allowed_fields if f in data])
            insert_values = ", ".join(["%s"] * (1 + len(updates)))
            cursor.execute(f"""
                INSERT INTO resume ({insert_fields})
                VALUES ({insert_values})
            """, [candidate_id] + values[:-1])  # values[:-1] → no repetimos candidate_id al final

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/extract_linkedin', methods=['POST'])
def extract_linkedin():
    try:
        data = request.json
        resume_id = data.get('resume_id')  # el id de la fila en tu tabla resume

        if not resume_id:
            return jsonify({'error': 'resume_id is required'}), 400

        conn = get_connection()
        cursor = conn.cursor()

        # Obtener el candidate_id asociado al resume
        cursor.execute("""
            SELECT candidate_id FROM resume WHERE id = %s
        """, (resume_id,))
        result = cursor.fetchone()

        if not result:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Resume not found'}), 404

        candidate_id = result[0]

        # Obtener el linkedin_url del candidate
        cursor.execute("""
            SELECT linkedin FROM candidates WHERE id = %s
        """, (candidate_id,))
        result = cursor.fetchone()

        if not result or not result[0]:
            cursor.close()
            conn.close()
            return jsonify({'error': 'LinkedIn URL not found for candidate'}), 404

        linkedin_url = result[0]

        # Llamar a Outscraper
        api_key = 'TU_API_KEY'  # reemplaza por tu API key real

        response = requests.get(
            'https://api.app.outscraper.com/v1/linkedin-profiles',
            params={
                'queries': linkedin_url,
                'api_key': api_key
            }
        )

        if response.status_code != 200:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Error calling Outscraper', 'status_code': response.status_code}), 500

        linkedin_data = response.json()

        # Guardar el JSON en extract_linkedin
        cursor.execute("""
            UPDATE resume
            SET extract_linkedin = %s
            WHERE id = %s
        """, (json.dumps(linkedin_data), resume_id))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True, 'linkedin_data': linkedin_data})

    except Exception as e:
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
    return jsonify({"error": "candidate_id and pdf required"}), 400

  try:
    # 1. Cargar a Affinda
    doc = affinda.create_document(
      file=pdf_file,
      workspace=WORKSPACE_ID,
      document_type=DOC_TYPE_ID,
      wait=True
    )
    data = doc.data  # JSON con campos extraídos

    # 2. Convertir JSON a string
    data_str = json.dumps(data)

    # 3. Guardar en base de datos
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
      UPDATE resume
      SET extract_cv_pdf = %s
      WHERE candidate_id = %s
    """, (data_str, candidate_id))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"success": True, "extracted": data}), 200

  except Exception as e:
    return jsonify({"error": str(e)}), 500
@app.route('/generate_resume_fields', methods=['POST'])
def generate_resume_fields():
    data = request.json
    candidate_id = data.get('candidate_id')
    extract_cv_pdf = data.get('extract_cv_pdf', '')
    cv_pdf_s3 = data.get('cv_pdf_s3', '')
    comments = data.get('comments', '')

    # Construir el prompt
    prompt = f"""
You are an expert resume assistant. You will generate structured resume data in JSON format based on the following information:

EXTRACTED_CV_PDF (Affinda or other CV extract): 
{extract_cv_pdf}

CV_PDF_S3 (LinkedIn or PDF extract):
{cv_pdf_s3}

Additional user comments:
{comments}

Please generate the following in ENGLISH:
1. ABOUT: a professional summary paragraph.
2. WORK_EXPERIENCE: a JSON array of objects with fields:
   - title
   - company
   - start_date (YYYY-MM-DD or empty)
   - end_date (YYYY-MM-DD or empty)
   - current (true or false)
   - description

3. EDUCATION: a JSON array of objects with fields:
   - institution
   - start_date (YYYY-MM-DD or empty)
   - end_date (YYYY-MM-DD or empty)
   - current (true or false)
   - description

4. TOOLS: a JSON array of objects with fields:
   - tool
   - level (Basic, Intermediate, Advanced)

Please respond in strict JSON format. Example:

{
  "about": "Experienced software engineer with a strong background in full-stack development and cloud technologies.",
  "work_experience": [
    {
      "title": "Software Engineer",
      "company": "Tech Corp",
      "start_date": "2022-01-01",
      "end_date": "",
      "current": true,
      "description": "Developed and maintained web applications using Python and React."
    }
  ],
  "education": [
    {
      "institution": "University of Technology",
      "start_date": "2018-09-01",
      "end_date": "2022-06-01",
      "current": false,
      "description": "Bachelor's Degree in Computer Science."
    }
  ],
  "tools": [
    {
      "tool": "Python",
      "level": "Advanced"
    },
    {
      "tool": "React",
      "level": "Intermediate"
    }
  ]
}

"""

    try:
        completion = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert assistant specialized in resume generation."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=2000
        )

        response_text = completion['choices'][0]['message']['content']

        # intentar parsear como JSON
        try:
            ai_data = json.loads(response_text)
        except json.JSONDecodeError:
            # fallback simple por si responde con ```json ... ```
            response_text_clean = response_text.strip('```json').strip('```').strip()
            ai_data = json.loads(response_text_clean)

        return jsonify(ai_data)

    except Exception as e:
        print("❌ Error in generate_resume_fields:", str(e))
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

    allowed_fields = [
        'name',
        'country',
        'phone',
        'email',
        'linkedin',
        'english_level',
        'salary_range',
        'red_flags',
        'comments'
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
        cur.execute("INSERT INTO opportunity_candidates (opportunity_id, candidate_id) VALUES (%s, %s)", (opportunity_id, candidate_id))
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

            # Insertar en tabla candidates SIN opportunity_id
            cursor.execute("""
                INSERT INTO candidates (
                    candidate_id, name, email, phone, linkedin,
                    red_flags, comments, english_level, salary_range, country, stage
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                new_candidate_id, name, email, phone, linkedin,
                red_flags, comments, english_level, salary_range, country, stage
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


@app.route('/candidates/<int:candidate_id>/batch', methods=['PATCH'])
def update_candidate_batch(candidate_id):
    data = request.get_json()
    batch_id = data.get('batch_id')

    if batch_id is None:
        return jsonify({'error': 'batch_id is required'}), 400

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE candidates
            SET batch_id = %s
            WHERE candidate_id = %s
        """, (batch_id, candidate_id))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
@app.route('/candidates/<int:candidate_id>/opportunities')
def get_opportunities_by_candidate(candidate_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*
            FROM opportunity o
            JOIN opportunity_candidates oc ON o.opportunity_id = oc.opportunity_id
            WHERE oc.candidate_id = %s
        """, (candidate_id,))
        rows = cursor.fetchall()
        colnames = [desc[0] for desc in cursor.description]
        data = [dict(zip(colnames, row)) for row in rows]
        cursor.close()
        conn.close()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
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
    
@app.route('/ai/generate_jd', methods=['POST'])
def generate_job_description():
    try:
        data = request.get_json()
        intro = data.get('intro', '')
        deep_dive = data.get('deepDive', '')
        notes = data.get('notes', '')

        prompt = f"""
You are a job posting assistant. Based on the following input, generate a complete and professional **Job Description** for LinkedIn that includes sections such as Role Summary, Key Responsibilities, Requirements, and Nice to Haves. Use clear and inclusive language.

INTRO CALL TRANSCRIPT:
{intro}

DEEP DIVE NOTES:
{deep_dive}

EMAILS AND COMMENTS:
{notes}

Please respond with only the job description in markdown-style plain text.
"""

        client = OpenAI()

        chat = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert recruiter and job description writer."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1200
        )

        response_text = chat.choices[0].message.content


        content = completion['choices'][0]['message']['content']

        return jsonify({"job_description": content})

    except Exception as e:
        print("❌ AI Job Description Error:", e)
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)