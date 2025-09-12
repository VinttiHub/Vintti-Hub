from __future__ import annotations

import os
import re
import json
import uuid
import calendar
import logging
import traceback
from datetime import datetime
from typing import List

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from botocore.exceptions import NoCredentialsError
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import boto3
import openai
import psycopg2
import psycopg2.extras
import requests
import html as _html

from ai_routes import register_ai_routes
from db import get_connection
from coresignal_routes import bp as coresignal_bp

# Affinda (opcional)
from affinda import AffindaAPI, TokenCredential

# --- Helper: limpiar HTML para Webflow (quita <span>, styles y normaliza nbsp) ---
import re, html as _html

_ALLOWED_TAGS = ('ul','ol','li','p','br','b','strong','i','em','a')

def _clean_html_for_webflow(s: str) -> str:
    if not s:
        return ""
    s = str(s)

    # normaliza NBSP
    s = s.replace('\u00A0', ' ').replace('&nbsp;', ' ')

    # quita <span ...> y </span>
    s = re.sub(r'<\s*span[^>]*>', '', s, flags=re.I)
    s = re.sub(r'</\s*span\s*>', '', s, flags=re.I)

    # quita atributos style="..."
    s = re.sub(r'\sstyle="[^"]*"', '', s, flags=re.I)

    # quita on*="..." (onClick, onMouseOver, etc.)
    s = re.sub(r'\son[a-z]+\s*=\s*"[^"]*"', '', s, flags=re.I)

    # limpia <a> con javascript:
    def _sanitize_a(m):
        tag = m.group(0)
        # si no hay href, deja <a>
        href_m = re.search(r'href="([^"]*)"', tag, flags=re.I)
        href = href_m.group(1) if href_m else ''
        if not href or href.lower().startswith('javascript:'):
            return '<a>'
        # deja solo href/target/rel
        safe = f'<a href="{href}" target="_blank" rel="noopener">'
        return safe
    s = re.sub(r'<a[^>]*>', _sanitize_a, s, flags=re.I)

    # whitelist de etiquetas: reemplaza cualquier otra etiqueta por su contenido
    def _whitelist_tags(m):
        tag = m.group(1).lower()
        if tag in _ALLOWED_TAGS:
            return m.group(0)
        # elimina etiqueta, deja contenido si es de cierre/apertura desconocida
        return ''
    s = re.sub(r'</?([a-z0-9]+)(\s[^>]*)?>', _whitelist_tags, s, flags=re.I)

    # pequeños trims
    s = re.sub(r'[ \t]{2,}', ' ', s).strip()
    s = s.replace('<li> ', '<li>').replace(' </li>', '</li>')
    return s


# 👇 MOVER ARRIBA: cargar .env ANTES de leer cualquier variable
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# --- ENV KEYS (safe) ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

AFFINDA_API_KEY = os.getenv('AFFINDA_API_KEY')
WORKSPACE_ID = os.getenv('AFFINDA_WORKSPACE_ID')
DOC_TYPE_ID   = os.getenv('AFFINDA_DOCUMENT_TYPE_ID')

# Inicialización perezosa/segura de Affinda
affinda = None
if AFFINDA_API_KEY:
    try:
        affinda = AffindaAPI(credential=TokenCredential(token=AFFINDA_API_KEY))
    except Exception:
        logging.exception("❌ No se pudo inicializar Affinda; continuaré sin Affinda.")

# Configurar cliente S3 DESPUÉS de load_dotenv()
s3_client = boto3.client(
    's3',
    region_name=os.getenv('AWS_REGION'),
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)
S3_BUCKET = os.getenv('S3_BUCKET_NAME')

app = Flask(__name__)
register_ai_routes(app)
app.register_blueprint(coresignal_bp)
# --- enum canonicals para el Sheet ---
_CANON = {
    "career_job_type": {
        "full-time": "Full-time", "full time":"Full-time", "fulltime":"Full-time",
        "part-time": "part-time", "part time":"part-time",
        "contract": "Contract", "freelance":"Contract", "temporary":"Contract",
        "internship":"Internship"
    },
    "career_seniority": {
        "junior":"Junior",
        "semi-senior":"Semi-senior", "semisenior":"Semi-senior", "semi senior":"Semi-senior",
        "senior":"Senior",
        "entry-level":"Entry-level", "entry level":"Entry-level"
    },
    "career_experience_level": {
        "entry-level job":"Entry-level Job", "entry level job":"Entry-level Job",
        "experienced":"Experienced"
    },
    "career_field": {
        "it":"IT", "tech":"IT",
        "marketing":"Marketing", "sales":"Sales", "accounting":"Accounting",
        "virtual assistant":"Virtual Assistant", "virtual…":"Virtual Assistant", "virtual":"Virtual Assistant"
    },
    "career_modality": {
        "remote":"Remote", "on-site":"On-site", "onsite":"On-site", "hybrid":"Hybrid"
    },
}

def _titlecase_city(s: str) -> str:
    if not s: return ""
    return " ".join(p.capitalize() for p in s.strip().split())

def _canon_enum(field: str, val: str) -> str:
    if not val: return ""
    v = val.strip().lower()
    m = _CANON.get(field, {})
    return m.get(v, val.strip().capitalize() if field!="career_field" else val.strip())

def _canon_country(s: str) -> str:
    if not s: return ""
    # casos típicos
    if s.strip().lower() in ("any country","anycountry","any"):
        return "Any Country"
    # title case genérico (respetando acrónimos como "USA" si quieres extenderlo)
    return " ".join(p.capitalize() for p in s.strip().split())

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

@app.route('/candidates/light')
def get_candidates_light():
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                c.candidate_id,
                c.name,
                c.country,
                c.phone,
                c.linkedin,
                CASE WHEN EXISTS (
                    SELECT 1 
                    FROM opportunity o 
                    WHERE o.candidato_contratado = c.candidate_id
                ) THEN '✔️' ELSE NULL END AS employee
            FROM candidates c
            ORDER BY c.candidate_id DESC
        """)

        rows = cursor.fetchall()
        colnames = [desc[0] for desc in cursor.description]
        candidates = [dict(zip(colnames, row)) for row in rows]

        cursor.close(); conn.close()
        return jsonify(candidates)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/data/light')
def get_accounts_light():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                a.account_id,
                a.client_name,
                COALESCE(u.user_name, a.account_manager) AS account_manager_name,
                a.priority,

                -- 🔵 contract (sin contar hires): basado SOLO en modelos de oportunidades
                CASE
                WHEN MAX(CASE WHEN o.opp_model = 'Staffing'   THEN 1 ELSE 0 END) = 1
                AND MAX(CASE WHEN o.opp_model = 'Recruiting' THEN 1 ELSE 0 END) = 1
                    THEN 'Mix'
                WHEN MAX(CASE WHEN o.opp_model = 'Staffing'   THEN 1 ELSE 0 END) = 1
                    THEN 'Staffing'
                WHEN MAX(CASE WHEN o.opp_model = 'Recruiting' THEN 1 ELSE 0 END) = 1
                    THEN 'Recruiting'
                ELSE NULL
                END AS contract,

                -- 🔶 TRR/TSF/TSR ahora desde hire_opportunity (agregada por opp para evitar duplicados)
                COALESCE(SUM(CASE WHEN o.opp_model = 'Recruiting' THEN COALESCE(h.revenue, 0) ELSE 0 END), 0) AS trr,
                COALESCE(SUM(CASE WHEN o.opp_model = 'Staffing'   THEN COALESCE(h.fee,     0) ELSE 0 END), 0) AS tsf,
                COALESCE(SUM(CASE WHEN o.opp_model = 'Staffing'   THEN COALESCE(h.salary,  0) ELSE 0 END), 0) AS tsr

            FROM account a
            LEFT JOIN users u ON a.account_manager = u.email_vintti
            LEFT JOIN opportunity o ON o.account_id = a.account_id
            LEFT JOIN (
                SELECT
                    opportunity_id,
                    MAX(salary)  AS salary,
                    MAX(fee)     AS fee,
                    MAX(revenue) AS revenue
                FROM hire_opportunity
                GROUP BY opportunity_id
            ) h ON h.opportunity_id = o.opportunity_id
            GROUP BY a.account_id, a.client_name, u.user_name, a.account_manager, a.priority
            ORDER BY a.client_name ASC
        """)



        rows = cursor.fetchall()
        colnames = [desc[0] for desc in cursor.description]
        accounts = [dict(zip(colnames, row)) for row in rows]

        cursor.close()
        conn.close()
        return jsonify(accounts)
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
                o.account_id,
                o.opp_stage,
                o.opp_position_name,
                o.opp_type,
                o.opp_model,
                o.opp_hr_lead,
                o.comments,
                o.nda_signature_or_start_date,
                o.opp_close_date,  -- <== agrega esta línea
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
    
@app.route('/data')
def get_accounts():
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Traer todas las cuentas
        cursor.execute("SELECT * FROM account")
        accounts_rows = cursor.fetchall()
        accounts_columns = [desc[0] for desc in cursor.description]
        accounts = [dict(zip(accounts_columns, row)) for row in accounts_rows]

        for account in accounts:
            account_id = account['account_id']

            # Obtener opportunity_id de esta cuenta
            cursor.execute("SELECT opportunity_id, opp_model FROM opportunity WHERE account_id = %s", (account_id,))
            opp_rows = cursor.fetchall()
            if not opp_rows:
                continue

            opp_ids = [r[0] for r in opp_rows]
            opp_model_map = {r[0]: r[1] for r in opp_rows}

            # Obtener candidatos/hire data desde hire_opportunity
            cursor.execute("""
                SELECT h.opportunity_id, h.salary, h.fee, h.revenue
                FROM hire_opportunity h
                WHERE h.opportunity_id = ANY(%s)
            """, (opp_ids,))

            trr = tsf = tsr = 0
            for opp_id, salary, fee, revenue in cursor.fetchall():
                model = opp_model_map.get(opp_id)
                if model == 'Recruiting':
                    trr += (revenue or 0)
                elif model == 'Staffing':
                    tsf += (fee or 0)
                    tsr += (salary or 0)


            # Guardar los valores en la tabla account
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

    except Exception as e:
        print("Error en /data:", e)
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
    q = (request.args.get('search') or '').strip()
    # evita búsquedas vacías o de 1 char para no cargar DB
    if len(q) < 2:
        return jsonify([])

    conn = get_connection()
    cur = conn.cursor()
    try:
        # ✅ sin pg_trgm, ranking básico por nombre
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
    except Exception as e:
        # log y respuesta controlada
        import logging, traceback
        logging.error("search_candidates failed: %s\n%s", e, traceback.format_exc())
        return jsonify([]), 200
    finally:
        cur.close(); conn.close()



@app.route('/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        return ('', 204)
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
    

def _extract_key_from_url(presigned_or_s3_url: str):
    """
    Convierte un URL (incluso presignado) a una S3 key 'accounts/<file>.pdf'
    """
    if not presigned_or_s3_url:
        return None
    m = re.search(r"accounts%2F(.+?\.pdf)", presigned_or_s3_url)
    if not m:
        m = re.search(r"accounts/(.+?\.pdf)", presigned_or_s3_url)
    return f"accounts/{m.group(1)}" if m else None

def _get_account_pdf_keys(cursor, account_id):
    """
    Lee account.pdf_s3 y devuelve una lista de keys S3.
    Soporta formato legacy (una sola URL presignada en texto).
    """
    cursor.execute("SELECT pdf_s3 FROM account WHERE account_id = %s", (account_id,))
    row = cursor.fetchone()
    keys = []
    if row and row[0]:
        raw = row[0]
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                keys = [k for k in data if isinstance(k, str)]
            elif isinstance(data, str):
                # legacy string -> lo tratamos abajo
                raise ValueError("legacy string")
        except Exception:
            # legacy: valor único en texto (posible URL presignada)
            k = _extract_key_from_url(raw)
            if k:
                keys = [k]
    return keys

def _set_account_pdf_keys(cursor, account_id, keys):
    cursor.execute(
        "UPDATE account SET pdf_s3 = %s WHERE account_id = %s",
        (json.dumps(keys), account_id)
    )

def _make_pdf_payload(keys):
    """ Genera URLs presignadas frescas (7 días) para cada key. """
    pdfs = []
    for key in keys:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET, 'Key': key},
            ExpiresIn=604800  # 7 días
        )
        pdfs.append({
            "key": key,
            "url": url,
            "name": key.split('/')[-1]
        })
    return pdfs
# ---------- CANDIDATE CVS (PDFs/Imágenes) ----------
def _extract_cv_key_from_url(presigned_or_s3_url: str):
    """
    Convierte cualquier URL (incluso presignada) a una S3 key 'cvs/<file>'
    Soporta .pdf, .png, .jpg, .jpeg, .webp
    """
    if not presigned_or_s3_url:
        return None
    m = re.search(r"cvs%2F(.+?\.(?:pdf|png|jpg|jpeg|webp))", presigned_or_s3_url, re.IGNORECASE)
    if not m:
        m = re.search(r"cvs/(.+?\.(?:pdf|png|jpg|jpeg|webp))", presigned_or_s3_url, re.IGNORECASE)
    return f"cvs/{m.group(1)}" if m else None

def _get_cv_keys(cursor, candidate_id: int):
    """
    Lee resume.cv_pdf_s3 y devuelve lista de keys S3.
    Soporta legacy: string con URL en vez de JSON list.
    """
    cursor.execute("SELECT cv_pdf_s3 FROM resume WHERE candidate_id = %s", (candidate_id,))
    row = cursor.fetchone()
    keys = []
    if row and row[0]:
        raw = row[0]
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                keys = [k for k in data if isinstance(k, str)]
            elif isinstance(data, str):
                raise ValueError("legacy string")
        except Exception:
            k = _extract_cv_key_from_url(raw)
            if k:
                keys = [k]
    return keys

def _ensure_resume_row(cursor, candidate_id: int):
    cursor.execute("SELECT 1 FROM resume WHERE candidate_id = %s", (candidate_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO resume (candidate_id) VALUES (%s)", (candidate_id,))

def _set_cv_keys(cursor, candidate_id: int, keys: List[str]):
    _ensure_resume_row(cursor, candidate_id)
    cursor.execute(
        "UPDATE resume SET cv_pdf_s3 = %s WHERE candidate_id = %s",
        (json.dumps(keys), candidate_id)
    )

def _make_cv_payload(keys: List[str]):
    """
    Genera URLs presignadas (7 días) para cada key, con nombre bonito.
    """
    items = []
    for key in keys:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET, 'Key': key},
            ExpiresIn=604800  # 7 días
        )
        items.append({
            "key": key,
            "url": url,
            "name": key.split('/')[-1]
        })
    return items
# ---------------------------------------------------
@app.route('/candidates/<int:candidate_id>/cvs', methods=['GET'])
def list_candidate_cvs(candidate_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        keys = _get_cv_keys(cursor, candidate_id)
        # Normaliza a JSON list si era legacy
        _set_cv_keys(cursor, candidate_id, keys)
        conn.commit()

        items = _make_cv_payload(keys)

        cursor.close(); conn.close()
        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/candidates/<int:candidate_id>/cvs', methods=['POST'])
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
        s3_client.upload_fileobj(
            f,
            S3_BUCKET,
            s3_key,
            ExtraArgs={'ContentType': content_type}
        )

        # =========================
        # 🆕 NUEVO: correr Affinda y guardar en candidates.affinda_scrapper
        # =========================
        affinda_json = None
        if ext == 'pdf' and affinda:
            try:
                # Rebobinar el stream para Affinda
                try:
                    f.stream.seek(0)
                    file_for_affinda = f.stream
                except Exception:
                    f.seek(0)
                    file_for_affinda = f

                doc = affinda.create_document(
                    file=file_for_affinda,
                    workspace=WORKSPACE_ID,
                    document_type=DOC_TYPE_ID,
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
        elif ext == 'pdf' and not affinda:
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
        keys = _get_cv_keys(cursor, candidate_id)
        if s3_key not in keys:
            keys.append(s3_key)
        _set_cv_keys(cursor, candidate_id, keys)
        conn.commit()

        items = _make_cv_payload(keys)

        cursor.close(); conn.close()
        return jsonify({"message": "CV uploaded", "items": items}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/candidates/<int:candidate_id>/cvs', methods=['DELETE'])
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

        keys = _get_cv_keys(cursor, candidate_id)
        if key not in keys:
            cursor.close(); conn.close()
            return jsonify({"error": "Key not found for this candidate"}), 404

        # Eliminar en S3
        s3_client.delete_object(Bucket=S3_BUCKET, Key=key)

        # Actualizar lista
        keys = [k for k in keys if k != key]
        _set_cv_keys(cursor, candidate_id, keys)
        conn.commit()

        items = _make_cv_payload(keys)

        cursor.close(); conn.close()
        return jsonify({"message": "CV deleted", "items": items}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/accounts/<account_id>')
def get_account_by_id(account_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # 1) Calcular TRR/TSF/TSR para ESTA cuenta (solo hires), en una sola query
        cursor.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN o.opp_model = 'Recruiting' THEN COALESCE(h.revenue, 0) ELSE 0 END), 0) AS trr,
                COALESCE(SUM(CASE WHEN o.opp_model = 'Staffing'   THEN COALESCE(h.fee,     0) ELSE 0 END), 0) AS tsf,
                COALESCE(SUM(CASE WHEN o.opp_model = 'Staffing'   THEN COALESCE(h.salary,  0) ELSE 0 END), 0) AS tsr
            FROM opportunity o
            LEFT JOIN (
                SELECT
                    opportunity_id,
                    MAX(salary)  AS salary,
                    MAX(fee)     AS fee,
                    MAX(revenue) AS revenue
                FROM hire_opportunity
                GROUP BY opportunity_id
            ) h ON h.opportunity_id = o.opportunity_id
            WHERE o.account_id = %s
        """, (account_id,))

        sums = cursor.fetchone()
        trr = sums[0] or 0
        tsf = sums[1] or 0
        tsr = sums[2] or 0

        # 2) Persistir en la tabla account
        cursor.execute("""
            UPDATE account
            SET trr = %s, tsf = %s, tsr = %s
            WHERE account_id = %s
        """, (trr, tsf, tsr, account_id))
        conn.commit()

        # 3) Devolver la cuenta (ya con los valores actualizados)
        cursor.execute("SELECT * FROM account WHERE account_id = %s", (account_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            conn.close()
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
                    website, linkedin, comments, mail,
                    where_come_from
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

            cursor.execute(query, (
                data.get("name"),
                data.get("size"),
                data.get("timezone"),
                data.get("state"),
                data.get("website"),
                data.get("linkedin"),
                data.get("about"),
                data.get("mail"),
                data.get("where_come_from")  # ✅ nuevo
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
                cv_pdf_scrapper,
                discount_dolar,
                discount_daterange,
                affinda_scrapper,
                coresignal_scrapper
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
    data = request.get_json() or {}
    logging.info("📥 PATCH /opportunities/%s/fields payload=%s", opportunity_id, json.dumps(data, default=str))

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
        'replacement_end_date',
        'candidato_contratado',

        # 👇 NUEVOS (Career Site)
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
        'career_tools',  # JSON/text
        'career_description',
        'career_requirements',
        'career_additional_info',
        'career_published'  # boolean/text
    ]


    updates, values = [], []
    for field in updatable_fields:
        if field in data:
            if field in ('opp_close_date', 'nda_signature_or_start_date', 'since_sourcing'):
                updates.append(f"{field} = %s::date")
            else:
                updates.append(f"{field} = %s")
            values.append(data[field])

    if not updates and candidate_hired_id is None:
        logging.warning("⚠️ Nada que actualizar y sin candidato_contratado")
        return jsonify({'error': 'No valid fields provided'}), 400

    try:
        conn = get_connection()
        with conn:
            with conn.cursor() as cursor:
                # 1) Update de opportunity
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

                    # Marcar status "Client hired" en batches vinculados a esta opp
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
        'priority',
        'contract',
        'where_come_from',
        'calculated_status',
        'account_manager' 
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
@app.route('/opportunities/<int:opportunity_id>/candidates/<int:candidate_id>/star', methods=['PATCH'])
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
            o.opp_position_name,
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

@app.route('/candidates/<int:candidate_id>/hire_opportunity', methods=['GET'])
def get_hire_opportunity(candidate_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT o.opportunity_id, o.opp_model
            FROM opportunity o
            WHERE o.candidato_contratado = %s
            LIMIT 1;
        """, (candidate_id,))

        row = cursor.fetchone()

        if not row:
            cursor.close()
            conn.close()
            return jsonify({}), 404

        colnames = [desc[0] for desc in cursor.description]
        opportunity = dict(zip(colnames, row))

        cursor.close()
        conn.close()

        return jsonify(opportunity)
    except Exception as e:
        import traceback
        print("❌ Error en GET /candidates/<candidate_id>/hire_opportunity:")
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

    
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
        if not affinda:
            return jsonify({"error": "Affinda no está configurado (faltan variables de entorno)."}), 500
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
        'cv_pdf_scrapper',
        'discount_dolar', 
        'discount_daterange'
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
        
@app.route('/opportunities/<int:opportunity_id>/candidates', methods=['GET'])
def get_candidates_for_opportunity(opportunity_id):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT 
                c.candidate_id,
                c.name,
                c.linkedin,
                c.salary_range,
                c.country,
                oc.stage_pipeline
            FROM opportunity_candidates oc
            JOIN candidates c ON c.candidate_id = oc.candidate_id
            WHERE oc.opportunity_id = %s
        """, (opportunity_id,))

        results = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(results)

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
        # 1) Oportunidad donde este candidato fue contratado (tomamos también account_id)
        cursor.execute("""
            SELECT opportunity_id, opp_model, account_id
            FROM opportunity
            WHERE candidato_contratado = %s
            LIMIT 1
        """, (candidate_id,))
        opp = cursor.fetchone()
        if not opp:
            return jsonify({'error': 'Candidate is not linked to a hired opportunity'}), 404

        opportunity_id, opp_model, account_id = opp

        if request.method == 'GET':
            # 2) Traer datos desde hire_opportunity
            cursor.execute("""
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
                    -- NUEVO 👇
                    referral_dolar,
                    referral_daterange,
                    buyout_dolar,
                    buyout_daterange
                FROM hire_opportunity
                WHERE candidate_id = %s AND opportunity_id = %s
                LIMIT 1
            """, (candidate_id, opportunity_id))
            row = cursor.fetchone()

            if not row:
                return jsonify({
                    'references_notes': '',
                    'employee_salary': None,
                    'employee_fee': None,
                    'computer': '',
                    'setup_fee': None,  
                    'extraperks': '',
                    'working_schedule': '',
                    'pto': '',
                    'discount_dolar': None,
                    'discount_daterange': None,
                    'start_date': None,
                    'end_date': None,
                    'employee_revenue': None,
                    'employee_revenue_recruiting': None,
                    # NUEVO 👇
                    'referral_dolar': None,
                    'referral_daterange': None,
                    'buyout_dolar': None,
                    'buyout_daterange': None
                })
            
            (references_notes, salary, fee, setup_fee, computer, extra_perks, working_schedule,
            pto, discount_dolar, discount_daterange, start_date, end_date, revenue,
            referral_dolar, referral_daterange, buyout_dolar, buyout_daterange) = row

            return jsonify({
                'references_notes': references_notes,
                'employee_salary': salary,
                'employee_fee': fee,
                'computer': computer,
                'setup_fee': setup_fee,
                'extraperks': extra_perks,  # <- tu key de front
                'working_schedule': working_schedule,
                'pto': pto,
                'discount_dolar': discount_dolar,
                'discount_daterange': discount_daterange,
                'start_date': start_date,
                'end_date': end_date,
                'employee_revenue': revenue if (opp_model or '').lower() == 'staffing' else None,
                'employee_revenue_recruiting': revenue if (opp_model or '').lower() == 'recruiting' else None,
                'referral_dolar': referral_dolar,
                'referral_daterange': referral_daterange,
                'buyout_dolar': buyout_dolar,
                'buyout_daterange': buyout_daterange
            })



        # PATCH -> asegurar/actualizar fila en hire_opportunity
        if request.method == 'PATCH':
            data = request.get_json() or {}

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
                'employee_revenue': 'revenue',
                'employee_revenue_recruiting': 'revenue',
                'discount_dolar': 'discount_dolar',
                'discount_daterange': 'discount_daterange',
                # NUEVO 👇
                'referral_dolar': 'referral_dolar',
                'referral_daterange': 'referral_daterange',
                'buyout_dolar': 'buyout_dolar',
                'buyout_daterange': 'buyout_daterange'
            }


            set_cols, set_vals = [], []
            # 👇 Siempre insertamos candidate_id, opportunity_id y account_id si no existe
            insert_cols, insert_vals = ['candidate_id', 'opportunity_id', 'account_id'], [candidate_id, opportunity_id, account_id]
            cursor.execute("""
                INSERT INTO hire_opportunity (candidate_id, opportunity_id, account_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (candidate_id, opportunity_id) DO NOTHING
            """, (candidate_id, opportunity_id, account_id))

            for k, col in mapping.items():
                if k in data:
                    set_cols.append(f"{col} = %s")
                    set_vals.append(data[k])
                    insert_cols.append(col)
                    insert_vals.append(data[k])

            # ¿Existe ya?
            cursor.execute("""
                SELECT 1 FROM hire_opportunity
                WHERE candidate_id = %s AND opportunity_id = %s
                LIMIT 1
            """, (candidate_id, opportunity_id))
            exists = cursor.fetchone()

            created = False
            updated = False

            if not exists:
                placeholders = ", ".join(["%s"] * len(insert_cols))
                cursor.execute(f"""
                    INSERT INTO hire_opportunity ({", ".join(insert_cols)})
                    VALUES ({placeholders})
                """, insert_vals)
                created = True

            if set_cols:
                set_vals.extend([candidate_id, opportunity_id])
                cursor.execute(f"""
                    UPDATE hire_opportunity
                    SET {", ".join(set_cols)}
                    WHERE candidate_id = %s AND opportunity_id = %s
                """, set_vals)
                updated = True
                            # --- Sincronizar end_date con buyout_daterange cuando se edita buyout_* ---
            # Regla: si viene buyout_dolar o buyout_daterange (y NO nos mandaron end_date manual),
            # ponemos end_date = último día del mes indicado por buyout_daterange.
            if ('buyout_dolar' in data or 'buyout_daterange' in data) and ('end_date' not in data):
                def _end_date_from_buyout(val) -> str | None:
                    """
                    Acepta formatos:
                    - 'YYYY-MM'
                    - 'YYYY-MM-DD'
                    - '[YYYY-MM-DD,YYYY-MM-DD]' (tomamos el último)
                    Devuelve 'YYYY-MM-DD' (último día de ese mes) o None.
                    """
                    if not val:
                        return None
                    s = str(val)

                    # 1) Si hay fechas completas en la cadena, toma la ÚLTIMA
                    m_full = re.findall(r'\d{4}-\d{2}-\d{2}', s)
                    if m_full:
                        # toma la última aparición
                        y, mo, d = map(int, m_full[-1].split('-'))
                        last = calendar.monthrange(y, mo)[1]
                        return f"{y:04d}-{mo:02d}-{last:02d}"

                    # 2) Si viene 'YYYY-MM'
                    m_ym = re.search(r'(\d{4})-(\d{2})', s)
                    if m_ym:
                        y = int(m_ym.group(1)); mo = int(m_ym.group(2))
                        last = calendar.monthrange(y, mo)[1]
                        return f"{y:04d}-{mo:02d}-{last:02d}"
                    return None

                # valor prioritario: lo que viene en el PATCH; si no, lo que ya hay en DB
                bo_val = data.get('buyout_daterange')
                if not bo_val:
                    cursor.execute("""
                        SELECT buyout_daterange
                        FROM hire_opportunity
                        WHERE candidate_id = %s AND opportunity_id = %s
                        LIMIT 1
                    """, (candidate_id, opportunity_id))
                    row = cursor.fetchone()
                    bo_val = row[0] if row else None

                computed_end = _end_date_from_buyout(bo_val)
                if computed_end:
                    cursor.execute("""
                        UPDATE hire_opportunity
                        SET end_date = %s
                        WHERE candidate_id = %s AND opportunity_id = %s
                    """, (computed_end, candidate_id, opportunity_id))

            # 2.5) Marcar al candidato como "Client hired" en candidates_batches (vía batch)
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
            """, ('Client hired', candidate_id, opportunity_id))

            # Fallback: si no hay batches ligados a esta opp, marcar cualquier batch del candidato
            if cursor.rowcount == 0:
                cursor.execute("""
                    UPDATE candidates_batches
                    SET status = %s
                    WHERE candidate_id = %s
                """, ('Client hired', candidate_id))

            # Después de insertar/actualizar hire_opportunity, forzamos el status
            cursor.execute("""
                UPDATE hire_opportunity
                SET status = CASE WHEN end_date IS NULL THEN 'active' ELSE 'inactive' END
                WHERE candidate_id = %s AND opportunity_id = %s
            """, (candidate_id, opportunity_id))

            conn.commit()
            return jsonify({'success': True, 'created': created, 'updated': updated})

    except Exception as e:
        import traceback
        print("❌ Error in /candidates/<id>/hire (hire_opportunity version):")
        print(traceback.format_exc())
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
@app.route('/candidates_batches', methods=['DELETE'])
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
    
@app.route('/accounts/<account_id>/upload_pdf', methods=['POST'])
def upload_account_pdf(account_id):
    pdf_file = request.files.get('pdf')
    if not pdf_file:
        return jsonify({"error": "Missing PDF file"}), 400

    try:
        # S3 key única
        filename = f"accounts/{account_id}_{uuid.uuid4()}.pdf"

        # Subir a S3
        s3_client.upload_fileobj(
            pdf_file,
            S3_BUCKET,
            filename,
            ExtraArgs={'ContentType': 'application/pdf'}
        )

        # Actualizar lista de keys en account.pdf_s3 (JSON array)
        conn = get_connection()
        cursor = conn.cursor()

        keys = _get_account_pdf_keys(cursor, account_id)
        if filename not in keys:
            keys.append(filename)
        _set_account_pdf_keys(cursor, account_id, keys)
        conn.commit()

        # Devolver lista completa con URLs presignadas frescas
        pdfs = _make_pdf_payload(keys)

        cursor.close()
        conn.close()

        return jsonify({"message": "PDF uploaded", "pdfs": pdfs}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    
@app.route('/accounts/<account_id>/pdfs', methods=['GET'])
def list_account_pdfs(account_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        keys = _get_account_pdf_keys(cursor, account_id)
        # Normaliza a JSON array si venía en legacy
        _set_account_pdf_keys(cursor, account_id, keys)
        conn.commit()

        pdfs = _make_pdf_payload(keys)

        cursor.close()
        conn.close()
        return jsonify(pdfs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/accounts/<account_id>/pdfs', methods=['DELETE'])
def delete_account_pdf_v2(account_id):
    try:
        data = request.get_json(silent=True) or {}
        key = data.get("key")  # Debe venir tipo "accounts/<account_id>_<uuid>.pdf"
        if not key or not key.startswith("accounts/"):
            return jsonify({"error": "Missing or invalid key"}), 400

        conn = get_connection()
        cursor = conn.cursor()

        # Leer keys actuales
        keys = _get_account_pdf_keys(cursor, account_id)

        if key not in keys:
            cursor.close(); conn.close()
            return jsonify({"error": "Key not found for this account"}), 404

        # Eliminar de S3
        s3_client.delete_object(Bucket=S3_BUCKET, Key=key)

        # Quitar de la lista y persistir
        keys = [k for k in keys if k != key]
        _set_account_pdf_keys(cursor, account_id, keys)
        conn.commit()

        pdfs = _make_pdf_payload(keys)

        cursor.close()
        conn.close()

        return jsonify({"message": "PDF deleted", "pdfs": pdfs}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/accounts/<account_id>/delete_pdf', methods=['DELETE'])
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
        s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key)

        cursor.execute("UPDATE account SET pdf_s3 = NULL WHERE account_id = %s", (account_id,))
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"message": "PDF deleted"}), 200

    except Exception as e:
        print("❌ Error deleting PDF:", str(e))
        return jsonify({"error": str(e)}), 500
@app.route('/accounts/<account_id>/pdfs', methods=['PATCH'])
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
        keys = _get_account_pdf_keys(cursor, account_id)
        if key not in keys:
            cursor.close(); conn.close()
            return jsonify({"error": "Key not found for this account"}), 404

        # Evitar colisiones de nombre
        if dest_key in keys and dest_key != key:
            cursor.close(); conn.close()
            return jsonify({"error": "A file with that name already exists"}), 409

        # Renombrar en S3: copy -> delete
        s3_client.copy_object(
            Bucket=S3_BUCKET,
            CopySource={'Bucket': S3_BUCKET, 'Key': key},
            Key=dest_key,
            ContentType='application/pdf',
            MetadataDirective='REPLACE'
        )
        s3_client.delete_object(Bucket=S3_BUCKET, Key=key)

        # Reemplazar en la lista persistida
        new_keys = [dest_key if k == key else k for k in keys]
        _set_account_pdf_keys(cursor, account_id, new_keys)
        conn.commit()

        # Devolver lista con URLs presignadas frescas
        pdfs = _make_pdf_payload(new_keys)

        cursor.close(); conn.close()
        return jsonify({"message": "PDF renamed", "pdfs": pdfs}), 200

    except Exception as e:
        logging.exception("❌ rename_account_pdf failed")
        return jsonify({"error": str(e)}), 500
    

@app.route('/candidates/light_fast', methods=['GET'])
def candidates_light_fast():
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT
              c.candidate_id,
              c.name,
              c.country,
              c.phone,
              c.linkedin,
              h.start_date,
              h.end_date,
              h.has_hire,
              CASE
                WHEN h.has_hire IS NULL THEN 'unhired'                -- no hay fila en hire_opportunity
                WHEN h.end_date IS NULL    THEN 'active'              -- hay fila y no tiene end_date
                ELSE 'inactive'                                       -- hay fila y sí tiene end_date
              END AS condition
            FROM candidates c
            LEFT JOIN LATERAL (
              SELECT TRUE AS has_hire, start_date, end_date
              FROM hire_opportunity h
              WHERE h.candidate_id = c.candidate_id
              -- prioriza activo (end_date NULL); si no hay, el más reciente por start_date
              ORDER BY (h.end_date IS NULL) DESC,
                       h.start_date DESC NULLS LAST
              LIMIT 1
            ) h ON TRUE
            ORDER BY c.name ASC;
        """)

        rows = cur.fetchall()
        cur.close(); conn.close()
        return jsonify(rows)
    except Exception as e:
        import logging; logging.exception("Error in /candidates/light_fast")
        return jsonify({"error": str(e)}), 500
# ---------- RESIGNATION LETTERS (PDF en S3, sin DB) ----------
@app.route('/candidates/<int:candidate_id>/resignations', methods=['GET'])
def list_resignations(candidate_id):
    try:
        prefix = f"resignations/resignation-letter_{candidate_id}_"
        items = _list_s3_with_prefix(prefix)
        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/candidates/<int:candidate_id>/resignations', methods=['POST'])
def upload_resignation(candidate_id):
    f = request.files.get('file')
    if not f:
        return jsonify({"error": "Missing file"}), 400

    filename_orig = (f.filename or '').lower()
    if not (filename_orig.endswith('.pdf') or f.mimetype == 'application/pdf'):
        return jsonify({"error": "Only PDF is allowed for resignation letters"}), 400

    try:
        s3_key = f"resignations/resignation-letter_{candidate_id}_{uuid.uuid4()}.pdf"
        s3_client.upload_fileobj(
            f, S3_BUCKET, s3_key,
            ExtraArgs={'ContentType': 'application/pdf'}
        )
        # devolver lista actualizada
        prefix = f"resignations/resignation-letter_{candidate_id}_"
        items = _list_s3_with_prefix(prefix)
        return jsonify({"message": "Resignation letter uploaded", "items": items})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/candidates/<int:candidate_id>/resignations', methods=['DELETE'])
def delete_resignation(candidate_id):
    data = request.get_json(silent=True) or {}
    key = data.get("key")
    if not key or not key.startswith(f"resignations/resignation-letter_{candidate_id}_"):
        return jsonify({"error": "Missing or invalid key"}), 400
    try:
        s3_client.delete_object(Bucket=S3_BUCKET, Key=key)
        # devolver lista actualizada
        prefix = f"resignations/resignation-letter_{candidate_id}_"
        items = _list_s3_with_prefix(prefix)
        return jsonify({"message": "Resignation letter deleted", "items": items})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
# --------------------------------------------------------------

def _list_s3_with_prefix(prefix: str):
    """Devuelve [{'key','url','name'}] para objetos bajo un prefijo S3."""
    items = []
    continuation = None
    while True:
        kw = {'Bucket': S3_BUCKET, 'Prefix': prefix}
        if continuation:
            kw['ContinuationToken'] = continuation
        resp = s3_client.list_objects_v2(**kw)
        for obj in resp.get('Contents', []):
            key = obj['Key']
            url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': S3_BUCKET, 'Key': key},
                ExpiresIn=604800  # 7 días
            )
            items.append({
                'key': key,
                'url': url,
                'name': key.split('/')[-1]
            })
        if resp.get('IsTruncated'):
            continuation = resp.get('NextContinuationToken')
        else:
            break
    return items

# ---------- EQUIPMENTS (list, create, read, update, delete) ----------
def _normalize_equipos(val):
    """
    Acepta:
      - list -> se json.dumps
      - str JSON -> se carga; si es list se json.dumps
      - 'a, b, c' -> ['a','b','c'] -> json.dumps
      - '', None -> None
    Devuelve (json_str or None)
    """
    if val is None:
        return None
    if isinstance(val, list):
        return json.dumps([str(x).strip() for x in val if str(x).strip()])
    s = str(val).strip()
    if not s:
        return None
    # ¿ya es JSON?
    try:
        j = json.loads(s)
        if isinstance(j, list):
            return json.dumps([str(x).strip() for x in j if str(x).strip()])
    except Exception:
        pass
    # coma-separado
    parts = [p.strip() for p in s.split(',') if p.strip()]
    return json.dumps(parts) if parts else None


@app.route('/equipments', methods=['GET', 'POST'])
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


@app.route('/equipments/<int:equipment_id>', methods=['GET', 'PATCH', 'DELETE'])
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

    
# ---------- HIRE_OPPORTUNITY helper (used by front to resolver account activo) ----------
@app.route('/hire_opportunity', methods=['GET'])
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


# ---------- SEARCH: candidates that are in hire_opportunity (with active account) ----------
@app.route('/search/candidates-in-hire', methods=['GET'])
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


# ---------- Alias opcional para el fallback del front ----------
@app.route('/candidates/search')
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
            SELECT candidate_id, name
            FROM candidates
            WHERE name ILIKE %s
            ORDER BY LOWER(name) ASC
            LIMIT 10
        """, (f"%{q}%",))
        rows = cur.fetchall()
        cur.close(); conn.close()
        return jsonify([{"candidate_id": r[0], "name": r[1]} for r in rows])
    except Exception as e:
        return jsonify([]), 200
    
@app.route('/resumes/<int:candidate_id>', methods=['GET', 'PATCH', 'OPTIONS'])
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
# === NEW: Summary por cuentas (POST) ===
@app.route('/accounts/status/summary', methods=['POST', 'OPTIONS'])
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

        # Booleans por cuenta para decidir el status final
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
        cur.close(); conn.close()

        def decide(has_candidates, any_active, has_opps, has_pipeline, all_lost):
            if any_active:                     return 'Active Client'
            if has_candidates and not any_active: return 'Inactive Client'
            if (not has_opps) and (not has_candidates): return 'Lead'
            if all_lost and not has_candidates: return 'Lead Lost'
            if has_pipeline:                   return 'Lead in Process'
            if (not has_opps) and has_candidates: return 'Inactive Client'
            return 'Lead in Process'

        out = []
        for (acc_id, has_candidates, any_active, has_opps, has_pipeline, all_lost) in rows:
            out.append({
                "account_id": acc_id,
                "status": decide(has_candidates, any_active, has_opps, has_pipeline, all_lost)
            })
        return jsonify(out)
    except Exception as e:
        # Si algo falla, devolvemos vacío para que el front use el fallback
        import logging, traceback
        logging.error("summary failed: %s\n%s", e, traceback.format_exc())
        return jsonify([]), 200


# === NEW: Bulk update de calculated_status (POST) ===
@app.route('/accounts/status/bulk_update', methods=['POST', 'OPTIONS'])
def accounts_status_bulk_update():
    if request.method == 'OPTIONS':
        return ('', 204)

    payload = request.get_json(silent=True) or {}
    updates = payload.get('updates') or []
    if not updates:
        return jsonify({"updated": 0, "persisted": False}), 200

    try:
        conn = get_connection()
        cur = conn.cursor()
        # ¿Existe la columna?
        cur.execute("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'account' AND column_name = 'calculated_status'
            LIMIT 1
        """)
        has_col = cur.fetchone() is not None

        updated = 0
        if has_col:
            for it in updates:
                acc_id = it.get('account_id') or it.get('id')
                status = it.get('calculated_status') or it.get('status') or it.get('value')
                if not acc_id:
                    continue
                cur.execute("UPDATE account SET calculated_status = %s WHERE account_id = %s",
                            (status, acc_id))
                updated += cur.rowcount
            conn.commit()

        cur.close(); conn.close()
        return jsonify({"updated": updated, "persisted": has_col}), 200
    except Exception as e:
        # No rompemos el flujo del front (solo informamos)
        return jsonify({"updated": 0, "persisted": False, "note": str(e)}), 200
from flask import request, jsonify
import re, html as _html, logging

# Mapas mínimos (1:1) según tu HTML y las opciones del Sheet
CANON = {
    "job_type": {
        "full-time": "Full-time",
        "part-time": "Part-time",
    },
    "seniority": {
        "entry-level": "Entry-level",
        "junior": "Junior",
        "semi-senior": "Semi-senior",
        "senior": "Senior",
        "manager": "Manager",
    },
    "experience_level": {
        "entry level job": "Entry-level Job",
        "experienced": "Experienced",
    },
    "field": {
        "accounting": "Accounting",
        "it": "IT",
        "legal": "Legal",
        "marketing": "Marketing",
        "virtual assistant": "Virtual Assistant",
    },
    "modality": {
        "remote": "Remote",
        "hybrid": "Hybrid",
        "on site": "On-site",
    },
}
# === Google Sheets: helpers unificados (JSON inline o archivo) ===
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
GOOGLE_SHEETS_RANGE = os.getenv("GOOGLE_SHEETS_RANGE", "Careers!A:Z")

def _sheets_credentials():
    """
    Crea credenciales desde:
    - GOOGLE_SERVICE_ACCOUNT_JSON (contenido JSON inline; normaliza private_key),
    - o GOOGLE_SERVICE_ACCOUNT_FILE (ruta a .json en disco).
    """
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    sa_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")

    if sa_json:
        import json as _json
        info = _json.loads(sa_json)
        # normaliza saltos en private_key si vienen escapados
        pk = info.get("private_key")
        if isinstance(pk, str) and "\\n" in pk:
            info["private_key"] = pk.replace("\\n", "\n")
        return Credentials.from_service_account_info(info, scopes=SHEETS_SCOPES)

    if sa_file:
        return Credentials.from_service_account_file(sa_file, scopes=SHEETS_SCOPES)

    raise RuntimeError("Service Account credentials not configured (set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE)")

def _sheets_service():
    creds = _sheets_credentials()
    # cache_discovery=False evita warnings en serverless
    return build("sheets", "v4", credentials=creds, cache_discovery=False)
# --- A1 helpers seguros ---
def _a1_quote(sheet_name: str) -> str:
    """
    Devuelve el nombre de pestaña en A1 correctamente citado:
    - Envuelve con comillas simples.
    - Escapa comillas simples internas (' -> '')
    - Permite nombres con espacios, emojis, paréntesis, etc.
    """
    s = (sheet_name or "").strip()
    # si ya viene citado ('...'), quita las comillas para normalizar
    if len(s) >= 2 and s[0] == s[-1] == "'":
        s = s[1:-1]
    s = s.replace("'", "''")
    return f"'{s}'"

def _get_sheet_headers(service, spreadsheet_id, sheet_name):
    """
    Lee la fila 1 de la pestaña `sheet_name` (citado en A1) y devuelve los encabezados.
    Si la pestaña no existe, intenta con la primera del libro.
    """
    # 1) normaliza y cita el nombre
    quoted = _a1_quote(sheet_name)

    try:
        resp = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{quoted}!1:1"
        ).execute()
        values = resp.get("values", [[]])
        headers = values[0] if values else []
        return [h.strip() for h in headers]
    except Exception:
        # Fallback: usa la primera pestaña disponible
        meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = meta.get("sheets", [])
        if not sheets:
            raise
        first_title = sheets[0]["properties"]["title"]
        resp = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{_a1_quote(first_title)}!1:1"
        ).execute()
        values = resp.get("values", [[]])
        headers = values[0] if values else []
        return [h.strip() for h in headers]


@app.route('/careers/<int:opportunity_id>/publish', methods=['POST'])
def publish_career_to_sheet(opportunity_id):
    """
    Inserta UNA fila en el Google Sheet con Description/Requirements/Additional en HTML limpio.
    No modifica otras filas ni borra nada. Aplica WRAP solo a la fila insertada.
    """
    try:
        if not GOOGLE_SHEETS_SPREADSHEET_ID:
            return jsonify({"error": "Missing GOOGLE_SHEETS_SPREADSHEET_ID"}), 500

        data = request.get_json(silent=True) or {}

        # --- HTML limpio (quita spans/estilos/nbsp) ---
        desc_html = _clean_html_for_webflow(data.get("sheet_description_html", ""))
        reqs_html = _clean_html_for_webflow(data.get("sheet_requirements_html", ""))
        addi_html = _clean_html_for_webflow(data.get("sheet_additional_html", ""))

        # --- Otros campos (tal cual los recibes) ---
        job_id     = str(data.get("career_job_id") or opportunity_id)
        job_title  = data.get("career_job", "") or ""
        country    = data.get("career_country", "") or ""
        city       = data.get("career_city", "") or ""
        job_type   = data.get("career_job_type", "") or ""
        seniority  = data.get("career_seniority", "") or ""
        years_exp  = data.get("career_years_experience", "") or ""
        exp_level  = data.get("career_experience_level", "") or ""
        field_     = data.get("career_field", "") or ""
        modality   = data.get("career_modality", "") or ""
        tools      = ", ".join(data.get("career_tools") or [])

        svc = _sheets_service()

        # Título de pestaña a partir del RANGE (sin comillas, sin espacios extras)
        _sheet_part = (GOOGLE_SHEETS_RANGE or "Careers!A:Z").split("!")[0].strip()
        # si venía citado, quítale las comillas para pasarlo a _get_sheet_headers
        if len(_sheet_part) >= 2 and _sheet_part[0] == _sheet_part[-1] == "'":
            _sheet_part = _sheet_part[1:-1]
        sheet_title = _sheet_part

        headers = _get_sheet_headers(svc, GOOGLE_SHEETS_SPREADSHEET_ID, sheet_title)


        def idx(col_name: str) -> int:
            try:
                return headers.index(col_name)
            except ValueError:
                return -1

        cols_needed = [
            "Item ID","Job","Country","City","Job Type","Seniority",
            "Years of Experience","Experience Level","Field","Modality",
            "Tools","Description","Requirements","Additional Information"
        ]
        row_len = max((idx(c) for c in cols_needed if idx(c) >= 0), default=-1) + 1
        if row_len <= 0:
            return jsonify({"error": "Sheet headers not found or misnamed"}), 500

        new_row = [""] * row_len

        def put(col: str, val: str):
            j = idx(col)
            if j >= 0:
                if j >= len(new_row):
                    new_row.extend([""] * (j - len(new_row) + 1))
                new_row[j] = val

        put("Item ID", job_id)
        put("Job", job_title)
        put("Country", country)
        put("City", city)
        put("Job Type", job_type)
        put("Seniority", seniority)
        put("Years of Experience", years_exp)
        put("Experience Level", exp_level)
        put("Field", field_)
        put("Modality", modality)
        put("Tools", tools)

        # 🔹 Estas 3 van en HTML
        put("Description", desc_html)
        put("Requirements", reqs_html)
        put("Additional Information", addi_html)

        # --- Append UNA fila ---
        append = svc.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID,
            range=GOOGLE_SHEETS_RANGE,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [new_row]}
        ).execute()

        # --- sheetId real (no None) para formatear WRAP a la fila insertada ---
        meta = svc.spreadsheets().get(spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID).execute()
        sheet_id = None
        for s in meta.get("sheets", []):
            props = s.get("properties", {})
            if props.get("title") == sheet_title:
                sheet_id = props.get("sheetId")
                break

        # updatedRange ej: "Careers!A123:Z123"
        updated_range = (append.get("updates", {}) or {}).get("updatedRange")
        if sheet_id is not None and updated_range:
            import re
            # Extrae 123 y 123 de A123:Z123
            m = re.search(r'!([A-Z]+)(\d+):([A-Z]+)(\d+)$', updated_range)
            if m:
                start_row = int(m.group(2)) - 1  # 0-based
                end_row   = int(m.group(4))      # exclusivo
                # Aplica WRAP sólo a esa fila
                svc.spreadsheets().batchUpdate(
                    spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID,
                    body={
                        "requests": [{
                            "repeatCell": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "startRowIndex": start_row,
                                    "endRowIndex": end_row
                                },
                                "cell": {
                                    "userEnteredFormat": { "wrapStrategy": "WRAP" }
                                },
                                "fields": "userEnteredFormat.wrapStrategy"
                            }
                        }]
                    }
                ).execute()

        # (Opcional) Persistir flags en DB
        # with get_connection() as conn, conn.cursor() as cur:
        #     cur.execute(
        #         "UPDATE opportunity SET career_id=%s, career_published=TRUE WHERE opportunity_id=%s",
        #         (job_id, opportunity_id)
        #     )
        #     conn.commit()

        return jsonify({"career_id": job_id}), 200

    except Exception as e:
        logging.exception("❌ publish_career_to_sheet failed")
        # Devuelve mensaje controlado para ver el error exacto en el front
        return jsonify({"error": str(e)}), 500



@app.route('/opportunities/<opportunity_id>/batches', methods=['GET'])
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
@app.route('/batches/<int:batch_id>', methods=['PATCH'])
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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

    