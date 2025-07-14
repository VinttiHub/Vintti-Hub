from flask import Flask, jsonify, request
import os
from dotenv import load_dotenv
from botocore.exceptions import NoCredentialsError
from affinda import AffindaAPI, TokenCredential
import openai
import traceback
import logging
import json
import time
from flask import Flask, jsonify, request
import requests

openai.api_key = os.getenv("OPENAI_API_KEY")

# ai_routes.py
from flask import request, jsonify
import logging
import traceback
import openai
import json
from db import get_connection 

openai.api_key = os.getenv("OPENAI_API_KEY")

def register_ai_routes(app):
    @app.route('/ai/generate_jd', methods=['POST', 'OPTIONS'])
    def generate_job_description():
        logging.info("🔁 Entrando a /ai/generate_jd")

        if request.method == 'OPTIONS':
            logging.info("🔁 OPTIONS request recibida para /ai/generate_jd")
            response = app.response_class(status=204)
            response.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
            response.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,PATCH,OPTIONS'
            return response

        logging.info("📡 POST request recibida en /ai/generate_jd")

        try:
            data = request.get_json()
            if not data:
                logging.warning("❗ No se recibió JSON o está vacío")
                raise ValueError("No JSON payload received")

            intro = data.get('intro', '')
            deep_dive = data.get('deepDive', '')
            notes = data.get('notes', '')

            logging.info("📥 Datos recibidos:")
            logging.info(f"   - Intro: {intro[:100] + '...' if intro else 'VACÍO'}")
            logging.info(f"   - DeepDive: {deep_dive[:100] + '...' if deep_dive else 'VACÍO'}")
            logging.info(f"   - Notes: {notes[:100] + '...' if notes else 'VACÍO'}")

            prompt = f"""
            You are a job posting assistant. Based on the following input, generate a complete and professional **Job Description** suitable for LinkedIn.

            Your response must include the following structured sections:

            - Job Title (if applicable)
            - Role Summary (1 short paragraph)
            - Key Responsibilities (as a bulleted list)
            - Requirements (as a bulleted list)
            - Nice to Haves (as a bulleted list)
            - Additional Information (optional – if relevant)

            Use:
            - Clear, inclusive, and engaging language.
            - titles (no hashtags, no **bold**).
            - Bullet points (`-`) for lists.
            - A plain text markdown format (no HTML, no hashtags, no headings with `#`).

            SOURCE MATERIAL:
            ---
            **INTRO CALL TRANSCRIPT:**
            {intro}

            **DEEP DIVE NOTES:**
            {deep_dive}

            **EMAILS AND COMMENTS:**
            {notes}
            ---
            Please output only the job description, fully formatted and ready to copy into LinkedIn.you cannot add info
            that is not explicity said in the source material
            """

            logging.info("🧠 Prompt construido correctamente, conectando con OpenAI...")

            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an expert recruiter and job description writer."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=1200
            )

            logging.info("✅ OpenAI respondió sin errores")
            content = chat.choices[0].message.content
            logging.info(f"📝 Respuesta de OpenAI (primeros 200 caracteres): {content[:200] + '...' if content else 'VACÍO'}")

            response = jsonify({"job_description": content})
            response.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            return response, 200

        except Exception as e:
            logging.error("❌ ERROR al generar la job description:")
            logging.error(traceback.format_exc())
            response = jsonify({"error": str(e)})
            response.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            return response, 500
    
    @app.route('/generate_resume_fields', methods=['POST','GET'])
    def generate_resume_fields():
        data = request.json
        candidate_id = data.get('candidate_id')
        extract_cv_pdf = data.get('extract_cv_pdf', '')
        cv_pdf_s3 = data.get('cv_pdf_s3', '')
        comments = data.get('comments', '')
        # Obtener extract_linkedin desde la base de datos
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT extract_linkedin FROM resume WHERE candidate_id = %s
        """, (candidate_id,))
        linkedin_row = cursor.fetchone()
        if linkedin_row is None or linkedin_row[0] is None:
            linkedin_json = ''
        else:
            linkedin_json = linkedin_row[0]

        linkedin_row = cursor.fetchone()
        linkedin_json = linkedin_row[0] if linkedin_row else ''
        cursor.close()
        conn.close()
        print("🧾 extract_cv_pdf:", repr(extract_cv_pdf[:200]))
        print("🧾 cv_pdf_s3:", repr(cv_pdf_s3))
        print("🧾 linkedin_json:", repr(linkedin_json[:200]))
        print("🧾 comments:", repr(comments[:200]))


        import html

        prompt = f"""
        You are an expert resume assistant. You will generate structured resume data in JSON format based on the following information:
        you cannot add info that is not explicity said in this inputs

        EXTRACTED_CV_PDF (Affinda or other CV extract): 
        {html.escape(extract_cv_pdf)}

        CV_PDF_S3 (Link to the original PDF):
        {html.escape(cv_pdf_s3)}

        LINKEDIN_JSON (Extracted using Proxycurl):
        {html.escape(linkedin_json)}

        Additional user comments:
        {html.escape(comments)}

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

        {{  
        "about": "Experienced software engineer with a strong background in full-stack development and cloud technologies.",
        "work_experience": [
            {{
            "title": "Software Engineer",
            "company": "Tech Corp",
            "start_date": "2022-01-01",
            "end_date": "",
            "current": true,
            "description": "Developed and maintained web applications using Python and React."
            }}
        ],
        "education": [
            {{
            "institution": "University of Technology",
            "start_date": "2018-09-01",
            "end_date": "2022-06-01",
            "current": false,
            "description": "Bachelor's Degree in Computer Science."
            }}
        ],
        "tools": [
            {{
            "tool": "Python",
            "level": "Advanced"
            }},
            {{
            "tool": "React",
            "level": "Intermediate"
            }}
        ]
        }} 
        """
        print("🧠 Prompt construido para resume:")
        print(prompt[:1000])  # solo para evitar saturar logs

        try:
            print("🟡 Enviando prompt a OpenAI...")
            print("Prompt preview:")
            print(prompt[:500])
            max_chars = 10000
            extract_cv_pdf = extract_cv_pdf[:max_chars]
            linkedin_json = linkedin_json[:max_chars]
            comments = comments[:max_chars]
            completion = openai.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an expert assistant specialized in resume generation."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=800
            )
            print("🟢 OpenAI respondió:")
            print(completion)
            response_text = completion.choices[0].message.content
            print("🟢 Respuesta de OpenAI:")
            print(response_text)

            # intentar parsear como JSON
            try:
                ai_data = json.loads(response_text)
            except json.JSONDecodeError:
                print("❌ Error al parsear JSON:")
                print(response_text)
                response_text_clean = response_text.strip('```json').strip('```').strip()
                ai_data = json.loads(response_text_clean)
            print("🟢 JSON generado por OpenAI:")
            print(ai_data)

            return jsonify(ai_data)

        except Exception as e:
            print("❌ Error in generate_resume_fields:", str(e))
            print("❌ Error en generate_resume_fields:")
            print(traceback.format_exc())
            return jsonify({"error": str(e)}), 500
        
    @app.route('/extract_linkedin_proxycurl', methods=['POST','GET'])
    def extract_linkedin_proxycurl():
        try:
            print("📥 Recibiendo request en /extract_linkedin_proxycurl")
            data = request.get_json()
            print("📄 Body recibido:", data)

            linkedin_url = data.get("linkedin_url", "").strip()
            if not linkedin_url:
                print("❌ Error: No se proporcionó URL de LinkedIn")
                return jsonify({"error": "Missing LinkedIn URL"}), 400
            
            if "/in/" not in linkedin_url:
                print("❌ Error: URL de LinkedIn malformada:", linkedin_url)
                return jsonify({"error": "Malformed LinkedIn URL"}), 400

            # Configuración del request a Proxycurl
            proxycurl_api_key = os.getenv("PROXYCURL_API_KEY")
            headers = {
                "Authorization": f"Bearer {proxycurl_api_key}"
            }
            params = {
                "url": linkedin_url,
                "use_cache": "if-present",
                "skills": "include",
                "inferred_salary": "include"
            }

            print(f"🔗 Llamando a Proxycurl con URL: {linkedin_url}")
            response = requests.get(
                "https://nubela.co/proxycurl/api/v2/linkedin",
                headers=headers,
                params=params
            )

            print("📡 Proxycurl status code:", response.status_code)
            if response.status_code != 200:
                print("❌ Error al llamar Proxycurl:", response.text)
                return jsonify({"error": response.text}), response.status_code

            linkedin_data = response.json()
            print("✅ LinkedIn JSON recibido (preview):", json.dumps(linkedin_data, indent=2)[:1000])

            return jsonify(linkedin_data)

        except Exception as e:
            print("❌ Excepción en /extract_linkedin_proxycurl:", str(e))
            print(traceback.format_exc())
            return jsonify({"error": str(e)}), 500
    import time

def call_openai_with_retry(model, messages, temperature=0.7, max_tokens=1200, retries=3):
    for attempt in range(retries):
        try:
            response = openai.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response
        except openai.RateLimitError as e:
            logging.warning(f"⏳ Rate limit reached, retrying in 10s... (Attempt {attempt + 1})")
            if hasattr(e, 'response') and e.response is not None:
                logging.warning("🔎 Response headers: %s", e.response.headers)
            time.sleep(10)
        except Exception as e:
            logging.error("❌ Error en llamada a OpenAI: " + str(e))
            raise e
    raise Exception("Exceeded maximum retries due to rate limit")

