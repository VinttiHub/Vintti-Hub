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
    def resumir_fuente(nombre, contenido):
        prompt = f"""
        Resume solo la información profesional más útil para armar un CV a partir de este bloque de texto JSON o plano.
        Elimina cosas irrelevantes o duplicadas.
        
        Fuente: {nombre.upper()}
        ---
        {contenido[:8000]}  # recortamos para evitar token overflow
        ---
        Devuelve solo texto limpio y resumido, en inglés.
        """
        print(f"✂️ Resumiendo fuente: {nombre}")
        respuesta = call_openai_with_retry(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert resume cleaner."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=700
        )
        return respuesta.choices[0].message.content.strip()

    def generate_resume_fields():
        print("🔍 Headers recibidos:", dict(request.headers))
        print("🔍 Content-Type:", request.content_type)
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
        linkedin_resumido = resumir_fuente("LinkedIn", linkedin_json)
        extract_resumido = resumir_fuente("Extracted CV PDF", extract_cv_pdf)

        cursor.close()
        conn.close()
        print("🧾 extract_cv_pdf:", repr(extract_cv_pdf[:200]))
        print("🧾 cv_pdf_s3:", repr(cv_pdf_s3))
        print("🧾 linkedin_json:", repr(linkedin_json[:200]))
        print("🧾 comments:", repr(comments[:200]))


        import html

        prompt = f"""
        Extract resume fields in JSON format using only the provided data.

        CV_EXTRACT_SUMMARY:
        {extract_resumido}

        LINKEDIN_SUMMARY:
        {linkedin_resumido}

        COMMENTS:
        {html.escape(comments)}

        Respond in valid ENGLISH JSON with:
        - about
        - work_experience (title, company, start_date, end_date, current, description)
        - education (institution, start_date, end_date, current, description)
        - tools (tool, level)

        Do NOT invent data.
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
                print("🟢 Intentando hacer json.loads sobre:")
                print(response_text[:1000])  # solo por seguridad
                ai_data = json.loads(response_text)
            except json.JSONDecodeError as e:
                print("❌ JSONDecodeError:", str(e))
                print("Contenido bruto:")
                print(response_text)
                response_text_clean = response_text.strip('```json').strip('```').strip()
                try:
                    ai_data = json.loads(response_text_clean)
                except Exception as inner:
                    print("❌ Falla también al limpiar el prompt:", str(inner))
                    print(traceback.format_exc())
                    return jsonify({"error": f"Invalid JSON response: {inner}"}), 500

            print("🟢 JSON generado por OpenAI:")
            print(ai_data)

            return jsonify(ai_data)

        except Exception as e:
            print("❌ Error in generate_resume_fields:", str(e))
            print("❌ Error en generate_resume_fields:")
            print(traceback.format_exc())
            return jsonify({"error": str(e)}), 500
        
    @app.route('/extract_linkedin_proxycurl', methods=['POST'])
    def extract_linkedin_proxycurl():
        try:
            print("📥 Recibiendo request en /extract_linkedin_proxycurl")

            # Validación de tipo de contenido
            if not request.is_json:
                print("❌ Content-Type inválido:", request.content_type)
                return jsonify({"error": "Request must be JSON"}), 400

            data = request.get_json()
            print("📄 Body recibido:", data)

            linkedin_url = data.get("linkedin_url", "").strip()
            if not linkedin_url:
                print("❌ Error: No se proporcionó URL de LinkedIn")
                return jsonify({"error": "Missing LinkedIn URL"}), 400
            
            if "/in/" not in linkedin_url:
                print("❌ URL malformada:", linkedin_url)
                return jsonify({"error": "Malformed LinkedIn URL"}), 400

            # Configuración del request a Proxycurl
            proxycurl_api_key = os.getenv("PROXYCURL_API_KEY")
            if not proxycurl_api_key:
                print("❌ PROXYCURL_API_KEY no está configurado")
                return jsonify({"error": "API key not set"}), 500

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
                params=params,
                timeout=30  # ⏱️ Evita que se quede colgado si Proxycurl no responde
            )

            print("📡 Proxycurl status code:", response.status_code)

            if response.status_code != 200:
                print("❌ Error al llamar Proxycurl:", response.text)
                return jsonify({"error": "Proxycurl request failed", "details": response.text}), response.status_code

            linkedin_data = response.json()
            print("✅ LinkedIn JSON recibido (preview):", json.dumps(linkedin_data, indent=2)[:800])

            return jsonify(linkedin_data)

        except requests.exceptions.Timeout:
            print("⏱️ Timeout al llamar Proxycurl")
            return jsonify({"error": "Request to Proxycurl timed out"}), 504

        except Exception as e:
            import traceback
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

