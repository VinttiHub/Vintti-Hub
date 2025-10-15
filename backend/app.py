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
from psycopg2.extras import RealDictCursor
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
from psycopg2.extras import RealDictCursor, execute_values

# Affinda (opcional)
from affinda import AffindaAPI, TokenCredential

import re, html as _html
from reminders_routes import bp as reminders_bp
from profile_routes import bp as profile_bp 
from profile_routes import users_bp

_ALLOWED_TAGS = ('p','ul','ol','li','br','b','strong','i','em','a')

def _strip_attrs_keep_href(tag_html: str) -> str:
    """
    Devuelve la misma etiqueta pero sin atributos, salvo <a href="..."> (solo http/https/mailto).
    """
    tag = tag_html
    m = re.match(r'<\s*([a-z0-9]+)(\s[^>]*)?>', tag, flags=re.I)
    if not m:
        return tag

    name = m.group(1).lower()
    if name == 'a':
        href_m = re.search(r'href="([^"]*)"', tag, flags=re.I)
        href = href_m.group(1).strip() if href_m else ''
        if href and (href.lower().startswith(('http://','https://','mailto:'))):
            return f'<a href="{href}">'
        return '<a>'
    if name in _ALLOWED_TAGS:
        return f'<{name}>'
    return tag

def _clean_html_for_webflow(s: str, output: str = 'html') -> str:
    """
    Limpia HTML ruidoso de editores (Webflow/Greenhouse/Notion/etc.) y lo deja
    en un subset seguro:
      - allowed: p, ul, ol, li, br, b/strong, i/em, a[href]
      - convierte <div> en <p>
      - elimina spans, estilos inline, data-*, on*, clases raras
      - normaliza listas 'custom' a <ul><li>
      - elimina etiquetas vacías
    output:
      - 'html'  -> HTML limpio (para Webflow/tu site)
      - 'text'  -> texto plano con saltos de línea (para Sheets si prefieres)
    """
    if not s:
        return ""

    # Asegura str y desescapa entidades comunes
    s = _html.unescape(str(s))

    # Normaliza NBSP
    s = s.replace('\u00A0', ' ').replace('&nbsp;', ' ')

    # Quita <script>/<style> completos
    s = re.sub(r'<\s*(script|style)[^>]*>.*?</\s*\1\s*>', '', s, flags=re.I|re.S)

    # Greenhouse/Webflow meten listas custom: ul/li anidados en contenedores con clases raras.
    # Convierte cualquier "list---xxxxx" o "discList---xxxxx" en <ul> básico
    s = re.sub(r'<ul[^>]*class="[^"]*(?:list---|discList---)[^"]*"[^>]*>', '<ul>', s, flags=re.I)
    s = re.sub(r'<ol[^>]*class="[^"]*list---[^"]*"[^>]*>', '<ol>', s, flags=re.I)
    s = re.sub(r'<li[^>]*class="[^"]*"[^>]*>', '<li>', s, flags=re.I)

    # Convierte <div> en <p> (bloques de párrafo)
    s = re.sub(r'<\s*div[^>]*>', '<p>', s, flags=re.I)
    s = re.sub(r'</\s*div\s*>', '</p>', s, flags=re.I)

    # Quita <span ...> y </span>
    s = re.sub(r'<\s*span[^>]*>', '', s, flags=re.I)
    s = re.sub(r'</\s*span\s*>', '', s, flags=re.I)

    # Quita atributos style=..., class=..., id=..., data-..., y on*=
    s = re.sub(r'\sstyle="[^"]*"', '', s, flags=re.I)
    s = re.sub(r'\sclass="[^"]*"', '', s, flags=re.I)
    s = re.sub(r'\sid="[^"]*"', '', s, flags=re.I)
    s = re.sub(r'\sdata-[a-z0-9_-]+="[^"]*"', '', s, flags=re.I)
    s = re.sub(r'\son[a-z]+\s*=\s*"[^"]*"', '', s, flags=re.I)

    # Limpia <a> conservando solo href válido
    s = re.sub(r'<a[^>]*>', _strip_attrs_keep_href, s, flags=re.I)

    # Whitelist: permite solo _ALLOWED_TAGS (deja su contenido si la etiqueta no está permitida)
    def _whitelist_tags(m):
        tag = m.group(1).lower()
        if tag in _ALLOWED_TAGS:
            # reinyecta etiqueta sin atributos
            full = m.group(0)
            # Apertura o cierre
            if full.strip().startswith('</'):
                return f'</{tag}>'
            # apertura: ya saneada arriba, pero por si acaso…
            return _strip_attrs_keep_href(f'<{tag}>')
        return ''
    s = re.sub(r'</?([a-z0-9]+)(\s[^>]*)?>', _whitelist_tags, s, flags=re.I)

    # Quita párrafos vacíos y <li> vacíos
    s = re.sub(r'<p>\s*(<br\s*/?>)?\s*</p>', '', s, flags=re.I)
    s = re.sub(r'<li>\s*</li>', '', s, flags=re.I)

    # Junta <br> duplicados y corrige espacios
    s = re.sub(r'(<br\s*/?>\s*){2,}', '<br>', s, flags=re.I)
    s = re.sub(r'[ \t]{2,}', ' ', s).strip()

    # Si quedaron <p> consecutivos sin nada entre medio, déjalos
    # (opcional) añade salto de línea tras </p> para texto plano
    if output == 'text':
        tmp = s
        # reemplaza <li> por "- " al inicio de línea
        tmp = re.sub(r'\s*<li>\s*', '- ', tmp, flags=re.I)
        tmp = re.sub(r'\s*</li>\s*', '\n', tmp, flags=re.I)
        # reemplaza cierres de párrafo y <br> por saltos
        tmp = re.sub(r'\s*</p>\s*', '\n', tmp, flags=re.I)
        tmp = re.sub(r'\s*<br\s*/?>\s*', '\n', tmp, flags=re.I)
        # elimina el resto de etiquetas permitidas dejando su texto
        tmp = re.sub(r'</?(p|ul|ol|strong|b|em|i)>', '', tmp, flags=re.I)
        # enlaces: deja "texto (url)" si hubiera
        tmp = re.sub(r'<a href="([^"]*)">([^<]*)</a>', r'\2 (\1)', tmp, flags=re.I)
        # elimina cualquier otra etiqueta residual por seguridad
        tmp = re.sub(r'</?[^>]+>', '', tmp)
        # normaliza saltos y espacios
        lines = [ln.strip() for ln in tmp.splitlines()]
        return '\n'.join([ln for ln in lines if ln])

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
app.register_blueprint(reminders_bp)
app.register_blueprint(coresignal_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(users_bp)
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


@app.route('/data/light', methods=['GET'])
def data_light():
    """
    Devuelve un resumen ligero por cuenta:
      - trr: Recruiting revenue (solo hires activos)
      - tsf: Staffing fee       (solo hires activos)
      - tsr: Staffing (salary + fee)  👈 NUEVO
    Nota: 'activo' = hire_opportunity.end_date IS NULL
    (no dependemos del campo 'status' por seguridad).
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
              WHERE end_date IS NULL           -- 👈 solo activos
              ORDER BY opportunity_id, candidate_id, start_date DESC NULLS LAST
            )
            SELECT
              a.account_id,
              a.client_name,
              -- Recruiting (TRR)
              COALESCE(SUM(CASE WHEN o.opp_model ILIKE 'recruiting' THEN COALESCE(h.revenue,0) END), 0) AS trr,
              -- Staffing (TSF / TSR)
              COALESCE(SUM(CASE WHEN o.opp_model ILIKE 'staffing'   THEN COALESCE(h.fee,    0) END), 0) AS tsf,
              COALESCE(SUM(CASE WHEN o.opp_model ILIKE 'staffing'   THEN COALESCE(h.salary, 0) + COALESCE(h.fee, 0) END), 0) AS tsr  -- 👈 NUEVO
            FROM account a
            LEFT JOIN opportunity o ON o.account_id = a.account_id
            LEFT JOIN h_active h     ON h.opportunity_id = o.opportunity_id
            GROUP BY a.account_id, a.client_name
            ORDER BY LOWER(a.client_name) ASC;
        """)

        rows = cur.fetchall()
        cols = [c[0] for c in cur.description]
        data = [dict(zip(cols, r)) for r in rows]

        cur.close(); conn.close()
        return jsonify(data)
    except Exception as e:
        import traceback; print(traceback.format_exc())
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
                o.opp_close_date,
                -- 👇👇 AÑADIR ESTO
                o.expected_fee,
                o.expected_revenue,
                -- 👆👆
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
                WHERE h.opportunity_id = ANY(%s) AND h.end_date IS NULL
            """, (opp_ids,))

            trr = tsf = tsr = 0
            for opp_id, salary, fee, revenue in cursor.fetchall():
                model = opp_model_map.get(opp_id)
                if model == 'Recruiting':
                    trr += (revenue or 0)
                elif model == 'Staffing':
                    tsf += (fee or 0)
                    tsr += ((salary or 0) + (fee or 0))  # TSR = salary + fee


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
def users_list_or_by_email():
    """
    GET /users
    - sin params -> lista usuarios (campos clave, incluye user_id)
    - ?email=foo@bar.com -> filtra por email exacto (case-insensitive)
    """
    email = request.args.get("email")

    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            base_select = """
                SELECT
                  user_id,
                  user_name,
                  email_vintti,
                  role,
                  emergency_contact,
                  ingreso_vintti_date,
                  fecha_nacimiento,
                  avatar_url
                FROM users
            """

            if email:
                cur.execute(base_select + " WHERE LOWER(email_vintti) = LOWER(%s)", (email,))
            else:
                cur.execute(base_select)

            rows = cur.fetchall()

        conn.close()

        # normaliza fechas a 'YYYY-MM-DD'
        def _normalize_dates(row):
            for k in ("ingreso_vintti_date", "fecha_nacimiento"):
                v = row.get(k)
                if hasattr(v, "isoformat"):
                    row[k] = v.isoformat()
                elif isinstance(v, str) and len(v) >= 10:
                    row[k] = v[:10]  # fallback por si viene como string ISO con hora
            return row

        return jsonify([_normalize_dates(dict(r)) for r in rows])

    except Exception as e:
        import traceback; print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500



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
                    where_come_from, referal_source
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                data.get("where_come_from"),
                data.get("referal_source")    # 👈 NUEVO
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
                coresignal_scrapper,
                candidate_succes
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

        # 👇 Career Site
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
        'expected_revenue'
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

@app.route('/accounts/status/bulk_update', methods=['POST'])
def bulk_update_account_status():
    """
    Body: { "updates": [ { "account_id": 123, "status": "Active Client" }, ... ] }
    Persists to account.account_status and stamps account_status_updated_at.
    Also clears status_needs_refresh for those accounts.
    """
    payload = request.get_json(silent=True) or {}
    items = payload.get('updates') or []

    rows = []
    for it in items:
        try:
            acc_id = int(it.get('account_id') or it.get('id') or it.get('accountId'))
        except (TypeError, ValueError):
            continue
        status = (it.get('status') or it.get('calculated_status') or it.get('value') or '').strip() or None
        if acc_id:
            rows.append((acc_id, status))

    if not rows:
        return jsonify({"updated": 0}), 200

    try:
        conn = get_connection()
        with conn:
            with conn.cursor() as cur:
                # Faster than looping UPDATEs: one VALUES list + join
                execute_values(cur, """
                    CREATE TEMP TABLE _upd_status(account_id INT, status TEXT) ON COMMIT DROP;
                    """, [])

                execute_values(cur, "INSERT INTO _upd_status(account_id, status) VALUES %s", rows)

                cur.execute("""
                    UPDATE account a
                       SET account_status = u.status,
                           account_status_updated_at = NOW(),
                           status_needs_refresh = FALSE
                      FROM _upd_status u
                     WHERE a.account_id = u.account_id;
                """)
                updated = cur.rowcount

        return jsonify({"updated": updated}), 200

    except Exception as e:
        import traceback; print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


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

@app.route('/candidates/<int:candidate_id>/equipments')
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
        'discount_daterange',
        'candidate_succes'
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
                    buyout_daterange,
                    carga_inactive           -- <--- AÑADIR
                FROM hire_opportunity
                WHERE candidate_id = %s AND opportunity_id = %s
                LIMIT 1
            """, (candidate_id, opportunity_id))
            row = cursor.fetchone()

            # ...
            (references_notes, salary, fee, setup_fee, computer, extra_perks, working_schedule,
            pto, discount_dolar, discount_daterange, start_date, end_date, revenue,
            referral_dolar, referral_daterange, buyout_dolar, buyout_daterange,
            carga_inactive) = row  # <--- AÑADIR VARIABLE

            return jsonify({
                'references_notes': references_notes,
                'employee_salary': salary,
                'employee_fee': fee,
                'computer': computer,
                'setup_fee': setup_fee,
                'extraperks': extra_perks,
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
                'buyout_daterange': buyout_daterange,
                'carga_inactive': carga_inactive   # <--- AÑADIR (opcional)
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

            if ('end_date' in data) and data.get('end_date'):
                cursor.execute("""
                    UPDATE hire_opportunity
                    SET carga_inactive = COALESCE(carga_inactive, CURRENT_DATE)
                    WHERE candidate_id = %s AND opportunity_id = %s
                    AND end_date IS NOT NULL
                """, (candidate_id, opportunity_id))

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
                    # ✅ Si el end_date fue inferido por buyout, fija carga_inactive si aún es NULL
                    cursor.execute("""
                        UPDATE hire_opportunity
                        SET carga_inactive = COALESCE(carga_inactive, CURRENT_DATE)
                        WHERE candidate_id = %s AND opportunity_id = %s
                        AND end_date IS NOT NULL
                    """, (candidate_id, opportunity_id))

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
        s3_client.upload_fileobj(
            f, S3_BUCKET, s3_key,
            ExtraArgs={
                'ContentType': 'application/pdf',
                # 👇 ayuda a que el navegador lo abra inline:
                'ContentDisposition': 'inline; filename="resignation-letter.pdf"'
            }
        )
        prefix = f"resignations/resignation-letter_{candidate_id}_"
        items = _list_s3_with_prefix(prefix)  # asegúrate que devuelva name,url,key
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

def _list_s3_with_prefix(prefix, expires=3600):
    out = []
    resp = s3_client.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
    for obj in resp.get('Contents', []):
        key = obj['Key']
        # URL presignada con inline (Safari-friendly)
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': S3_BUCKET,
                'Key': key,
                'ResponseContentType': 'application/pdf',
                'ResponseContentDisposition': 'inline; filename="resignation-letter.pdf"'
            },
            ExpiresIn=expires
        )
        out.append({
            "name": key.split('/')[-1],
            "key": key,
            "url": url
        })
    return out

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
# === Lista oficial de slugs para Tools & Skills (para Dropdown chips) ===
CAREER_TOOL_SLUGS = [
    "problem-solving",
    "teamwork",
    "time-management",
    "adaptability",
    "critical-thinking",
    "leadership",
    "creativity",
    "technical-skills",
    "interpersonal-skills",
    "communication-skills",
]

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
GOOGLE_SHEETS_RANGE = os.getenv("GOOGLE_SHEETS_RANGE") or "Open Positions!A:Z"

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
# === Import de librerías que ya usas arriba ===
# from googleapiclient.discovery import build  # ya importado
# from google.oauth2.service_account import Credentials  # ya importado
import hashlib

# === Config import Sheet (con defaults al sheet que pasaste) ===
IMPORT_SPREADSHEET_ID = os.getenv("IMPORT_SPREADSHEET_ID") or "1Jn9xDhu08-eEL2zn9mg_VCXqCdYBdYWiy2FenU2Lmf8"
IMPORT_SHEET_GID      = os.getenv("IMPORT_SHEET_GID") or "0"
IMPORT_SHEET_TITLE    = os.getenv("IMPORT_SHEET_TITLE") or ""

_IMPORT_HEADERS = [
    # Excel (izquierda) -> DB (derecha)
    # job_id -> opportunity_candidates.opportunity_id (vía tabla opportunity)
    "job_id",
    "first_name",
    "last_name",
    "email_address",
    "phone_number",
    "location",
    "role",
    "area",
    "linkedin_url",
    "english_level",
]

def _norm_phone_digits(s: str | None) -> str:
    if not s: return ""
    return "".join(ch for ch in str(s) if ch.isdigit())

def _norm_linkedin(s: str | None) -> str:
    if not s: return ""
    s = s.strip()
    # normaliza eliminando trailing slashes y query
    s = s.split("?")[0].rstrip("/")
    return s.lower()

def _norm_email(s: str | None) -> str:
    return (s or "").strip().lower()

def _row_fingerprint(row: dict) -> str:
    """
    Hash estable por fila basándonos en columnas clave.
    """
    parts = [
        str(row.get("job_id") or "").strip(),
        _norm_email(row.get("email_address")),
        _norm_linkedin(row.get("linkedin_url")),
        _norm_phone_digits(row.get("phone_number")),
        (str(row.get("first_name") or "").strip() + " " + str(row.get("last_name") or "").strip()).strip(),
    ]
    base = "||".join(parts)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

def _get_sheet_title_by_gid(service, spreadsheet_id: str, gid: str) -> str:
    """
    Si no viene IMPORT_SHEET_TITLE, resuelve el nombre de la pestaña por GID.
    """
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for s in meta.get("sheets", []):
        props = s.get("properties", {})
        if str(props.get("sheetId")) == str(gid):
            return props.get("title")
    # fallback: primera pestaña
    return meta.get("sheets", [])[0].get("properties", {}).get("title")

def _get_rows_with_headers(service, spreadsheet_id: str, sheet_title: str) -> list[dict]:
    """
    Devuelve una lista de dicts por fila con keys = headers normalizados (snake_case).
    Asume fila 1 = encabezados.
    """
    quoted = _a1_quote(sheet_title)
    resp = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{quoted}!A:Z"
    ).execute()
    values = resp.get("values", [])
    if not values:
        return []

    headers = [ (h or "").strip() for h in values[0] ]
    # normaliza headers del sheet a snake_case simple para mapear
    def _to_key(h):
        return re.sub(r'[^a-z0-9]+', '_', h.strip().lower()).strip('_')

    head_norm = [_to_key(h) for h in headers]

    out = []
    for idx, row in enumerate(values[1:], start=2):  # data desde fila 2
        d = {}
        for j, v in enumerate(row):
            key = head_norm[j] if j < len(head_norm) else f"col_{j+1}"
            d[key] = v
        d["_row_number"] = idx  # útil para logs
        out.append(d)
    return out

def _find_opportunity_id(cursor, job_id: str | None) -> int | None:
    if not job_id:
        return None
    cursor.execute("SELECT opportunity_id FROM opportunity WHERE CAST(opportunity_id AS TEXT) = %s OR CAST(career_job_id AS TEXT) = %s LIMIT 1",
                   (str(job_id), str(job_id)))
    r = cursor.fetchone()
    return r[0] if r else None

def _find_existing_candidate(cursor, email: str, linkedin: str, phone_norm: str) -> int | None:
    """
    Busca por email OR linkedin OR phone normalizado (solo dígitos).
    """
    # 1) email
    if email:
        cursor.execute("SELECT candidate_id FROM candidates WHERE lower(email) = %s LIMIT 1", (email,))
        r = cursor.fetchone()
        if r: return r[0]
    # 2) linkedin (comparación normalizada)
    if linkedin:
        cursor.execute("""
            SELECT candidate_id
            FROM candidates
            WHERE lower(regexp_replace(COALESCE(linkedin,''), '/+$', '')) = %s
            LIMIT 1
        """, (linkedin.rstrip('/'),))
        r = cursor.fetchone()
        if r: return r[0]
    # 3) teléfono (solo dígitos)
    if phone_norm:
        cursor.execute("""
            SELECT candidate_id
            FROM candidates
            WHERE regexp_replace(COALESCE(phone,''), '[^0-9]', '', 'g') = %s
            LIMIT 1
        """, (phone_norm,))
        r = cursor.fetchone()
        if r: return r[0]
    return None


@app.route('/careers/<int:opportunity_id>/publish', methods=['POST'])
def publish_career_to_sheet(opportunity_id):
    """
    Inserta UNA fila en el Google Sheet usando los encabezados reales del sheet:
    - 'Job ID'
    - 'Location Country', 'Location City'
    - 'Job Type', 'Seniority', 'Years of Experience', 'Experience Level', 'Field'
    - 'Remote Type'
    - 'Tools & Skills'
    - 'Description', 'Requirements', 'Additional Information' (HTML limpio)
    Aplica WRAP solo a la fila insertada. No toca otras filas.
    """
    try:
        if not GOOGLE_SHEETS_SPREADSHEET_ID:
            return jsonify({"error": "Missing GOOGLE_SHEETS_SPREADSHEET_ID"}), 500

        svc = _sheets_service()
        data = request.get_json(silent=True) or {}

        # --------- Normalizadores / mapeos (usa tu dict CANON ya cargado) ----------
        def _norm(s):
            return (s or '').strip()

        def _canon(kind, val):
            v = _norm(val)
            table = CANON.get(kind, {})
            # comparación case-insensitive en keys
            for k, tgt in table.items():
                if k.lower() == v.lower():
                    return tgt
            return v  # si no matchea, deja tal cual

        job_id     = str(data.get("career_job_id") or opportunity_id)

        country    = _norm(data.get("career_country"))
        city       = _norm(data.get("career_city"))

        job_type   = _canon("job_type", data.get("career_job_type"))
        seniority  = _canon("seniority", data.get("career_seniority"))
        years_exp  = _norm(data.get("career_years_experience"))
        exp_level  = _canon("experience_level", data.get("career_experience_level"))
        field_     = _canon("field", data.get("career_field"))
        remote     = _canon("modality", data.get("career_modality"))  # en sheet se llama "Remote Type"
        tools_arr  = data.get("career_tools") or []
        tools_txt  = ", ".join([str(t).strip() for t in tools_arr if str(t).strip()])

        job_title  = _norm(data.get("career_job"))

        # HTML limpio (para Webflow) -> se envía como HTML
        desc_html = _clean_html_for_webflow(data.get("sheet_description_html", ""))
        reqs_html = _clean_html_for_webflow(data.get("sheet_requirements_html", ""))
        addi_html = _clean_html_for_webflow(data.get("sheet_additional_html", ""))

        # --------- Resuelve sheet y headers reales ----------
        _sheet_part = (GOOGLE_SHEETS_RANGE or "Open Positions!A:Z").split("!")[0].strip()
        if len(_sheet_part) >= 2 and _sheet_part[0] == _sheet_part[-1] == "'":
            _sheet_part = _sheet_part[1:-1]
        sheet_title = _sheet_part

        headers = _get_sheet_headers(svc, GOOGLE_SHEETS_SPREADSHEET_ID, sheet_title)

        # Alias por si el sheet tiene variantes mínimas de nombre
        HDR = {
            "JOB_ID":            ["Job ID", "Item ID"],
            "JOB":               ["Job", "Position", "Role"],
            "COUNTRY":           ["Location Country", "Country"],
            "CITY":              ["Location City", "City"],
            "JOB_TYPE":          ["Job Type"],
            "SENIORITY":         ["Seniority"],
            "YOE":               ["Years of Experience"],
            "EXP_LEVEL":         ["Experience Level"],
            "FIELD":             ["Field"],
            "REMOTE":            ["Remote Type", "Modality"],
            "TOOLS":             ["Tools & Skills", "Tools"],
            "DESC":              ["Description"],
            "REQS":              ["Requirements"],
            "ADDI":              ["Additional Information"],
        }

        def find_col(names):
            for n in names:
                try:
                    return headers.index(n)
                except ValueError:
                    continue
            return -1

        # Calcula longitud de la fila a partir del mayor índice usado
        targets = {
            "JOB_ID": find_col(HDR["JOB_ID"]),
            "JOB":    find_col(HDR["JOB"]),
            "COUNTRY":find_col(HDR["COUNTRY"]),
            "CITY":   find_col(HDR["CITY"]),
            "JOB_TYPE":find_col(HDR["JOB_TYPE"]),
            "SENIORITY":find_col(HDR["SENIORITY"]),
            "YOE":    find_col(HDR["YOE"]),
            "EXP_LEVEL":find_col(HDR["EXP_LEVEL"]),
            "FIELD":  find_col(HDR["FIELD"]),
            "REMOTE": find_col(HDR["REMOTE"]),
            "TOOLS":  find_col(HDR["TOOLS"]),
            "DESC":   find_col(HDR["DESC"]),
            "REQS":   find_col(HDR["REQS"]),
            "ADDI":   find_col(HDR["ADDI"]),
        }

        if all(v < 0 for v in targets.values()):
            return jsonify({"error": "Sheet headers not found or misnamed"}), 500

        row_len = max([i for i in targets.values() if i >= 0]) + 1
        new_row = [""] * row_len

        def put(key, value):
            j = targets.get(key, -1)
            if j >= 0:
                if j >= len(new_row):
                    new_row.extend([""] * (j - len(new_row) + 1))
                new_row[j] = value

        # ---- Escribe TODOS los campos con los nombres correctos del sheet ----
        put("JOB_ID", job_id)
        put("JOB", job_title)
        put("COUNTRY", country)
        put("CITY", city)
        put("JOB_TYPE", job_type)
        put("SENIORITY", seniority)
        put("YOE", years_exp)        # se enviará como USER_ENTERED (lo verá como número si aplica)
        put("EXP_LEVEL", exp_level)
        put("FIELD", field_)
        put("REMOTE", remote)        # <- coincide con dropdown “Remote Type”
        put("TOOLS", tools_txt)      # <- “Tools & Skills”
        put("DESC", desc_html)
        put("REQS", reqs_html)
        put("ADDI", addi_html)

        quoted_title = _a1_quote(sheet_title)
        target_range = f"{quoted_title}!A:Z"

        append = svc.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID,
            range=target_range,
            valueInputOption="USER_ENTERED",      # ← importante para números/dropdowns
            insertDataOption="INSERT_ROWS",
            body={"values": [new_row]}
        ).execute()

        # ---- Aplica WRAP SOLO a la fila insertada ----
        meta = svc.spreadsheets().get(spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID).execute()
        sheet_id = None
        for s in meta.get("sheets", []):
            if s.get("properties", {}).get("title") == sheet_title:
                sheet_id = s.get("properties", {}).get("sheetId")
                break

        updated_range = (append.get("updates", {}) or {}).get("updatedRange")
        if sheet_id is not None and updated_range:
            import re
            m = re.search(r'!([A-Z]+)(\d+):([A-Z]+)(\d+)$', updated_range)
            if m:
                start_row = int(m.group(2)) - 1  # 0-based
                end_row   = int(m.group(4))      # exclusivo

                requests = []

                # 1) WRAP a toda la fila insertada
                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": start_row,
                            "endRowIndex": end_row
                        },
                        "cell": { "userEnteredFormat": { "wrapStrategy": "WRAP" } },
                        "fields": "userEnteredFormat.wrapStrategy"
                    }
                })

                # 2) Data validation tipo Dropdown (chips) SOLO para la celda de Tools
                tools_col = targets.get("TOOLS", -1)
                if tools_col >= 0:
                    requests.append({
                        "setDataValidation": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": start_row,
                                "endRowIndex": end_row,
                                "startColumnIndex": tools_col,
                                "endColumnIndex": tools_col + 1
                            },
                            "rule": {
                                "condition": {
                                    "type": "ONE_OF_LIST",
                                    "values": [{"userEnteredValue": v} for v in CAREER_TOOL_SLUGS]
                                },
                                "strict": True,
                                # Muy importante para “Dropdown (chips)”
                                "showCustomUi": True
                            }
                        }
                    })

                if requests:
                    svc.spreadsheets().batchUpdate(
                        spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID,
                        body={ "requests": requests }
                    ).execute()


        return jsonify({"career_id": job_id}), 200

    except Exception as e:
        logging.exception("❌ publish_career_to_sheet failed")
        return jsonify({"error": str(e)}), 500

# === Quick actions para Career Sheet: setear Action = Archived / Borrar ===
def _col_index_to_a1(col_idx_0based: int) -> str:
    """0 -> A, 1 -> B, ..."""
    n = col_idx_0based + 1
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s

@app.route('/careers/<int:opportunity_id>/sheet_action', methods=['POST'])
def set_career_sheet_action(opportunity_id):
    """
    Body JSON: { "action": "Archived" | "Borrar" }
    Cambia la columna 'Action' del Sheet para TODAS las filas cuyo 'Job ID'
    (o 'Item ID') coincida con opportunity_id.
    """
    try:
        payload = request.get_json(silent=True) or {}
        action = (payload.get('action') or '').strip()
        if action not in ('Archived', 'Borrar'):
            return jsonify({"error": "Invalid action. Use 'Archived' or 'Borrar'."}), 400

        if not GOOGLE_SHEETS_SPREADSHEET_ID:
            return jsonify({"error": "Missing GOOGLE_SHEETS_SPREADSHEET_ID"}), 500

        svc = _sheets_service()

        # Resolver pestaña desde GOOGLE_SHEETS_RANGE (misma que usas al publicar)
        sheet_part = (GOOGLE_SHEETS_RANGE or "Open Positions!A:Z").split('!')[0].strip()
        if len(sheet_part) >= 2 and sheet_part[0] == sheet_part[-1] == "'":
            sheet_part = sheet_part[1:-1]
        sheet_title = sheet_part
        quoted_title = _a1_quote(sheet_title)

        # Leer headers reales (fila 1)
        headers = _get_sheet_headers(svc, GOOGLE_SHEETS_SPREADSHEET_ID, sheet_title)

        # Toleramos variantes mínimas de nombres de columnas
        def find_col(candidates):
            for name in candidates:
                try:
                    return headers.index(name)
                except ValueError:
                    continue
            return -1

        job_col    = find_col(["Job ID", "Item ID", "JOB ID", "JobID"])
        action_col = find_col(["Action", "Acción", "ACTION"])
        if job_col < 0 or action_col < 0:
            return jsonify({"error": "Sheet must contain 'Job ID' (o 'Item ID') y 'Action' headers"}), 500

        # Traer todas las filas (A:Z) para localizar coincidencias por Job ID
        get_resp = svc.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID,
            range=f"{quoted_title}!A:Z"
        ).execute()
        rows = get_resp.get('values', [])

        if not rows or len(rows) < 2:
            return jsonify({"updated": 0, "action": action})

        # Preparar batchUpdate de valores a la columna Action en cada fila match
        data_updates = []
        opp_str = str(opportunity_id).strip()

        for idx, row in enumerate(rows[1:], start=2):  # data desde fila 2
            job_val = row[job_col].strip() if job_col < len(row) and isinstance(row[job_col], str) else str(row[job_col]) if job_col < len(row) else ""
            if job_val == opp_str:
                col_letter = _col_index_to_a1(action_col)
                a1 = f"{quoted_title}!{col_letter}{idx}"
                data_updates.append({"range": a1, "values": [[action]]})

        updated = 0
        if data_updates:
            svc.spreadsheets().values().batchUpdate(
                spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID,
                body={
                    "valueInputOption": "USER_ENTERED",  # respeta el dropdown
                    "data": data_updates
                }
            ).execute()
            updated = len(data_updates)

        return jsonify({"updated": updated, "action": action}), 200

    except Exception as e:
        logging.exception("❌ set_career_sheet_action failed")
        return jsonify({"error": str(e)}), 500

@app.route('/sheets/candidates/import', methods=['POST'])
def import_candidates_from_sheet():
    """
    Lee el Sheet de candidatos y crea/relaciona filas nuevas.
    Reglas:
      - Si ya existe (email OR linkedin OR phone) => skip creación de candidato, pero si corresponde, relaciona con la opp si no estaba.
      - Si job_id no matchea con opportunity => skip.
      - Loggea cada fila insertada en sheet_import_log con fingerprint para idempotencia.
    Body opcional:
      {
        "spreadsheet_id": "...",  # si no, usa IMPORT_SPREADSHEET_ID
        "sheet_gid": "0",         # si no, usa IMPORT_SHEET_GID
        "sheet_title": "Candidates",  # si no, se resuelve por GID
        "dry_run": false          # si true, no hace writes en DB, solo preview
      }
    """
    try:
        payload = request.get_json(silent=True) or {}
        spreadsheet_id = payload.get("spreadsheet_id") or IMPORT_SPREADSHEET_ID
        sheet_gid      = str(payload.get("sheet_gid") or IMPORT_SHEET_GID)
        sheet_title    = (payload.get("sheet_title") or IMPORT_SHEET_TITLE).strip()
        dry_run        = bool(payload.get("dry_run", False))

        svc = _sheets_service()
        if not sheet_title:
            sheet_title = _get_sheet_title_by_gid(svc, spreadsheet_id, sheet_gid)

        rows = _get_rows_with_headers(svc, spreadsheet_id, sheet_title)

        # Mapea headers del sheet a los que esperamos (tolerante a variaciones)
        def getv(r, *aliases):
            # intenta por varias llaves (snake_case) habituales
            for k in aliases:
                if k in r and r[k] != "":
                    return r[k]
            return ""

        to_process = []
        for r in rows:
            rec = {
                "job_id":        getv(r, "job_id", "job", "opportunity_id"),
                "first_name":    getv(r, "first_name", "name", "nombre"),
                "last_name":     getv(r, "last_name", "apellido"),
                "email_address": getv(r, "email_address", "email"),
                "phone_number":  getv(r, "phone_number", "phone", "telefono"),
                "location":      getv(r, "location", "country", "pais"),
                "role":          getv(r, "role"),
                "area":          getv(r, "area"),
                "linkedin_url":  getv(r, "linkedin_url", "linkedin"),
                "english_level": getv(r, "english_level", "englishlevel", "ingles"),
                "_row_number":   r.get("_row_number"),
            }
            # solo consideramos filas con al menos job_id y (email o linkedin o phone)
            has_contact = any([rec["email_address"], rec["linkedin_url"], rec["phone_number"]])
            if rec["job_id"] and has_contact:
                to_process.append(rec)

        conn = get_connection()
        cur = conn.cursor()

        report = {
            "sheet": {"spreadsheet_id": spreadsheet_id, "sheet_title": sheet_title, "gid": sheet_gid},
            "checked": len(to_process),
            "created_candidates": 0,
            "linked_existing": 0,
            "skipped_no_opportunity": 0,
            "skipped_already_logged": 0,
            "skipped_missing_contact": 0,
            "details": []
        }

        for rec in to_process:
            email_norm   = _norm_email(rec["email_address"])
            phone_norm   = _norm_phone_digits(rec["phone_number"])
            linkedin_norm= _norm_linkedin(rec["linkedin_url"])
            fp           = _row_fingerprint(rec)

            # ¿ya importamos esta fila?
            cur.execute("""
                SELECT 1 FROM sheet_import_log
                WHERE spreadsheet_id = %s AND sheet_gid = %s AND fingerprint = %s
                LIMIT 1
            """, (spreadsheet_id, sheet_gid, fp))
            if cur.fetchone():
                report["skipped_already_logged"] += 1
                report["details"].append({"row": rec["_row_number"], "result": "already-logged"})
                continue

            # ¿existe opportunity?
            opp_id = _find_opportunity_id(cur, rec["job_id"])
            if not opp_id:
                report["skipped_no_opportunity"] += 1
                report["details"].append({"row": rec["_row_number"], "result": "no-opportunity", "job_id": rec["job_id"]})
                continue

            # ¿existe candidato?
            existing_id = _find_existing_candidate(cur, email_norm, linkedin_norm, phone_norm)

            # Construye nombre y mapea location -> country
            name = (f"{rec['first_name'].strip()} {rec['last_name'].strip()}").strip() or (email_norm or linkedin_norm or "Unknown")
            country = (rec["location"] or "").strip() or None
            english_level = (rec["english_level"] or "").strip() or None

            if dry_run:
                # solo reporte
                action = "link-existing" if existing_id else "create-and-link"
                report["details"].append({"row": rec["_row_number"], "result": f"dry-run:{action}", "opportunity_id": opp_id, "candidate_id": existing_id})
                continue

            # Si no existe => crear
            if not existing_id:
                # siguiente candidate_id
                cur.execute("SELECT COALESCE(MAX(candidate_id), 0) FROM candidates")
                new_id = (cur.fetchone()[0] or 0) + 1

                cur.execute("""
                    INSERT INTO candidates (
                        candidate_id, name, email, phone, linkedin, english_level, country, stage, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        NOW()
                    )
                """, (
                    new_id, name, email_norm or None, rec["phone_number"] or None, linkedin_norm or rec["linkedin_url"] or None,
                    english_level, country, 'Contactado'  # tu default actual
                ))
                candidate_id = new_id
                report["created_candidates"] += 1
                action = "created"
            else:
                candidate_id = existing_id
                action = "found-existing"

            # Relacionar en opportunity_candidates si no estaba
            cur.execute("""
                SELECT 1 FROM opportunity_candidates
                WHERE opportunity_id = %s AND candidate_id = %s
                LIMIT 1
            """, (opp_id, candidate_id))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO opportunity_candidates (opportunity_id, candidate_id, stage_pipeline)
                    VALUES (%s, %s, %s)
                """, (opp_id, candidate_id, 'Applicant'))
                if action == "found-existing":
                    report["linked_existing"] += 1

            # Log de import
            cur.execute("""
                INSERT INTO sheet_import_log (
                    spreadsheet_id, sheet_gid, row_number, job_id, email, linkedin, phone_norm, fingerprint
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, (
                spreadsheet_id, sheet_gid, rec["_row_number"], str(rec["job_id"]),
                email_norm or None, linkedin_norm or None, phone_norm or None, fp
            ))

            report["details"].append({
                "row": rec["_row_number"],
                "result": action + "+linked",
                "opportunity_id": opp_id,
                "candidate_id": candidate_id
            })

        if not dry_run:
            conn.commit()
        cur.close(); conn.close()
        return jsonify(report), 200

    except Exception as e:
        logging.exception("❌ import_candidates_from_sheet failed")
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
    
@app.route('/metrics/ts_history', methods=['GET'])
def ts_history():
    """
    Serie mensual de TSF (fee) y TSR (salary + fee) para Staffing,
    contando SOLO hires activos al final de cada mes.
    Params opcionales:
      - from: 'YYYY-MM'  (inclusive, mes calendario)
      - to:   'YYYY-MM'  (inclusive, mes calendario; por defecto último mes completo)
    Respuesta: [{ month: 'YYYY-MM', tsr: 0, tsf: 0, active_count: 0 }]
    """
    try:
        import datetime as _dt
        from flask import request, jsonify

        qs_from = (request.args.get('from') or '').strip()
        qs_to   = (request.args.get('to') or '').strip()

        conn = get_connection()
        cur = conn.cursor()

        # from_default: primer start_date registrado (a mes)
        cur.execute("""
            SELECT date_trunc('month', MIN(start_date::timestamp))::date
            FROM hire_opportunity
            WHERE start_date IS NOT NULL;
        """)
        min_month = cur.fetchone()[0]

        # to_default: último mes COMPLETO
        today = _dt.date.today().replace(day=1)             # 1er día del mes actual
        last_full_month = (today - _dt.timedelta(days=1)).replace(day=1)  # 1er día del mes anterior

        def _ym_to_date(s):
            if not s: return None
            y, m = s.split('-')[:2]
            return _dt.date(int(y), int(m), 1)

        from_month = _ym_to_date(qs_from) or (min_month or last_full_month)
        to_month   = _ym_to_date(qs_to)   or last_full_month

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
                COALESCE(h.fee,    0)::numeric AS fee,
                h.start_date::date            AS start_date,
                h.end_date::date              AS end_date
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
              -- TSR = salary + fee de los activos al final del mes
              COALESCE(SUM(CASE
                WHEN s.start_date <= e.month_end
                 AND (s.end_date IS NULL OR s.end_date > e.month_end)
                THEN s.salary + s.fee END), 0)::bigint AS tsr,
              -- TSF = solo fee (para ver su componente)
              COALESCE(SUM(CASE
                WHEN s.start_date <= e.month_end
                 AND (s.end_date IS NULL OR s.end_date > e.month_end)
                THEN s.fee END), 0)::bigint AS tsf,
              -- conteo de hires activos al cierre del mes
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

    except Exception as e:
        import traceback, logging
        logging.error("❌ ts_history failed: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)