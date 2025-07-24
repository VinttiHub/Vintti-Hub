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
import re
import datetime

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
    @app.route('/ai/improve_tools', methods=['POST'])
    def improve_tools_section():
        try:
            data = request.json
            candidate_id = data['candidate_id']
            user_prompt = data.get('user_prompt', '').strip()

            conn = get_connection()
            cursor = conn.cursor()

            # Obtener tools actuales
            cursor.execute("SELECT tools FROM resume WHERE candidate_id = %s", (candidate_id,))
            tools = cursor.fetchone()[0] or "[]"

            # Obtener scraps
            cursor.execute("SELECT linkedin_scrapper, cv_pdf_scrapper FROM candidates WHERE candidate_id = %s", (candidate_id,))
            linkedin_scrapper, cv_pdf_scrapper = cursor.fetchone()

            prompt = f"""
    You are a resume tools editor.

    --- CURRENT TOOLS ---
    {tools}

    --- LINKEDIN SCRAP ---
    {linkedin_scrapper[:2000]}

    --- PDF SCRAP ---
    {cv_pdf_scrapper[:2000]}

    --- USER COMMENTS ---
    {user_prompt}

    Improve the tools section using this info. Output must be a JSON array of this format:
    [{{"tool":"Excel","level":"Advanced"}},{{"tool":"QuickBooks","level":"Intermediate"}},{{"tool":"SAP","level":"Intermediate"}}]

    - Infer the level (Basic, Intermediate, Advanced) based on context.
    - Do NOT invent tools.
    - If no level is specified, infer from experience.
    Return only the JSON array.
    """

            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=800
            )

            content = chat.choices[0].message.content.strip()
            tools_json = json.loads(re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', content))

            cursor.execute("UPDATE resume SET tools = %s WHERE candidate_id = %s", (json.dumps(tools_json), candidate_id))
            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"tools": json.dumps(tools_json)})
        except Exception as e:
            logging.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route('/ai/improve_work_experience', methods=['POST'])
    def improve_work_experience_section():
        try:
            data = request.json
            candidate_id = data['candidate_id']
            user_prompt = data.get('user_prompt', '').strip()

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT work_experience FROM resume WHERE candidate_id = %s", (candidate_id,))
            work_experience = cursor.fetchone()[0] or "[]"

            cursor.execute("SELECT linkedin_scrapper, cv_pdf_scrapper FROM candidates WHERE candidate_id = %s", (candidate_id,))
            linkedin_scrapper, cv_pdf_scrapper = cursor.fetchone()

            prompt = f"""
    You are a resume work experience editor.

    --- CURRENT WORK EXPERIENCE ---
    {work_experience}

    --- LINKEDIN SCRAP ---
    {linkedin_scrapper[:2000]}

    --- PDF SCRAP ---
    {cv_pdf_scrapper[:2000]}

    --- USER COMMENTS ---
    {user_prompt}

    Improve the work experience section using this info. Output must be a JSON array with objects of this format:
    [{{"title":"...", "company":"...", "start_date":"YYYY-MM-DD", "end_date":"YYYY-MM-DD", "current":true/false, "description":"..."}}]

    - If month or day is missing, complete with 01
    - If end_date is missing or says "present", set current = true
    - Else set current = false
    Return only the JSON array.
    """

            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=1000
            )

            content = chat.choices[0].message.content.strip()
            work_json = json.loads(re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', content))

            today = datetime.date.today()
            for entry in work_json:
                if entry.get("start_date", "").count("-") == 0:
                    entry["start_date"] += "-01-01"
                elif entry.get("start_date", "").count("-") == 1:
                    entry["start_date"] += "-01"

                if entry.get("end_date", "") in ["", None, "present", "Present"]:
                    entry["end_date"] = ""
                    entry["current"] = True
                else:
                    if entry["end_date"].count("-") == 0:
                        entry["end_date"] += "-01-01"
                    elif entry["end_date"].count("-") == 1:
                        entry["end_date"] += "-01"
                    try:
                        end = datetime.datetime.strptime(entry["end_date"], "%Y-%m-%d").date()
                        entry["current"] = end > today
                    except:
                        entry["current"] = False

            cursor.execute("UPDATE resume SET work_experience = %s WHERE candidate_id = %s", (json.dumps(work_json), candidate_id))
            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"work_experience": json.dumps(work_json)})

        except Exception as e:
            logging.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500




    @app.route('/ai/improve_education', methods=['POST'])
    def improve_education_section():
        try:
            data = request.json
            candidate_id = data['candidate_id']
            user_prompt = data.get('user_prompt', '').strip()

            conn = get_connection()
            cursor = conn.cursor()

            # Obtener education actual
            cursor.execute("SELECT education FROM resume WHERE candidate_id = %s", (candidate_id,))
            education = cursor.fetchone()[0] or "[]"

            # Obtener scraps
            cursor.execute("SELECT linkedin_scrapper, cv_pdf_scrapper FROM candidates WHERE candidate_id = %s", (candidate_id,))
            linkedin_scrapper, cv_pdf_scrapper = cursor.fetchone()

            prompt = f"""
    You are a resume education editor.

    --- CURRENT EDUCATION SECTION ---
    {education}

    --- LINKEDIN SCRAP ---
    {linkedin_scrapper[:2000]}

    --- PDF SCRAP ---
    {cv_pdf_scrapper[:2000]}

    --- USER COMMENTS ---
    {user_prompt}

    Improve the education section using this info. Output must be a JSON array with objects of this format:
    [{{"institution":"...", "start_date":"YYYY-MM-DD", "end_date":"YYYY-MM-DD", "current":true/false, "description":"..."}}]

    - If month or day is missing, complete with 01
    - If end_date is missing or says "present", set current = true
    - Else set current = false
    Return only the JSON array.
    """

            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=700
            )

            content = chat.choices[0].message.content.strip()
            education_json = json.loads(re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', content))

            today = datetime.date.today()
            for entry in education_json:
                if entry.get("start_date", "").count("-") == 0:
                    entry["start_date"] += "-01-01"
                elif entry.get("start_date", "").count("-") == 1:
                    entry["start_date"] += "-01"

                if entry.get("end_date", "") in ["", None, "present", "Present"]:
                    entry["end_date"] = ""
                    entry["current"] = True
                else:
                    if entry["end_date"].count("-") == 0:
                        entry["end_date"] += "-01-01"
                    elif entry["end_date"].count("-") == 1:
                        entry["end_date"] += "-01"
                    try:
                        end = datetime.datetime.strptime(entry["end_date"], "%Y-%m-%d").date()
                        entry["current"] = end > today
                    except:
                        entry["current"] = False

            cursor.execute("UPDATE resume SET education = %s WHERE candidate_id = %s", (json.dumps(education_json), candidate_id))
            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"education": json.dumps(education_json)})

        except Exception as e:
            logging.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500



    @app.route('/ai/improve_about', methods=['POST'])
    def improve_about_section():
        try:
            data = request.json
            candidate_id = data['candidate_id']
            user_prompt = data.get('user_prompt', '').strip()

            conn = get_connection()
            cursor = conn.cursor()

            # Obtener datos de DB
            cursor.execute("SELECT about FROM resume WHERE candidate_id = %s", (candidate_id,))
            about = cursor.fetchone()[0] or ""

            cursor.execute("SELECT linkedin_scrapper, cv_pdf_scrapper FROM candidates WHERE candidate_id = %s", (candidate_id,))
            linkedin_scrapper, cv_pdf_scrapper = cursor.fetchone()

            prompt = f"""
    You are an expert resume editor. Here's the current "About" section for a candidate:

    --- CURRENT ABOUT ---
    {about}

    --- SCRAPED LINKEDIN ---
    {linkedin_scrapper[:2000]}

    --- SCRAPED PDF ---
    {cv_pdf_scrapper[:2000]}

    --- USER COMMENTS ---
    {user_prompt}

    Based on all this, improve the "About" section. It should be short (2-4 lines), professional, and accurate. Only include real info. Return only the improved version, no intro, no comments.
    """

            completion = call_openai_with_retry(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=300
            )

            new_about = completion.choices[0].message.content.strip()

            cursor.execute("UPDATE resume SET about = %s WHERE candidate_id = %s", (new_about, candidate_id))
            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"about": new_about})
        except Exception as e:
            logging.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500



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
    
    @app.route('/generate_resume_fields', methods=['POST'])
    def generate_resume_fields():
        try:
            data = request.json
            candidate_id = data.get('candidate_id')
            linkedin_scrapper = data.get('linkedin_scrapper', '')[:8000]
            cv_pdf_scrapper = data.get('cv_pdf_scrapper', '')[:8000]

            prompt = f"""
            You are a resume generation assistant. Based strictly and only on the following information, generate a detailed and professional resume in valid JSON format.

            LINKEDIN SCRAPER:
            {linkedin_scrapper}

            CV PDF SCRAPER:
            {cv_pdf_scrapper}

            Your response must be a single valid JSON object with the following structure:

            - about: A third-person summary written in a professional tone using only the data provided. It should be comprehensive, not generic.
            - education: [
                {{
                    "institution": "...",
                    "title": "...",
                    "start_date": "YYYY-MM-DD",
                    "end_date": "YYYY-MM-DD",
                    "current": true/false,
                    "description": "- Bullet 1\\n- Bullet 2\\n..."  // Must be long, detailed and specific to the institution or program
                }}
            ]
            - work_experience: [
                {{
                    "title": "...",
                    "company": "...",
                    "start_date": "YYYY-MM-DD",
                    "end_date": "YYYY-MM-DD",
                    "current": true/false,
                    "description": "- Bullet 1\\n- Bullet 2\\n..."  // Must be detailed with accomplishments, tools used, responsibilities, methods, etc.
                }}
            ]
            - tools: [{{"tool":"Excel", "level":"Advanced"}}, ...]

            Important rules:
            - Do NOT invent or assume any data. Only use what is explicitly or implicitly present.
            - Use all possible details found in the source to make the descriptions **long, rich and specific**.
            - The descriptions in both education and work experience must be **very detailed bullet points** using `- ` for each bullet.
            - If there is too little info, still write one or two bullets using the available data — but do not fabricate anything.
            - Expand acronyms and explain concepts if mentioned.

            Return only valid JSON. Do not wrap in markdown, do not add any explanation or comments.
            """

            completion = call_openai_with_retry(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a resume generation assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=1000
            )

            content = completion.choices[0].message.content
            print("📥 Resume JSON:", content)

            try:
                json_data = json.loads(content)
                def format_description(description):
                    if not description:
                        return ""
                    lines = re.split(r'\n|•|–|-', description)
                    bullets = ['- ' + line.strip() for line in lines if line.strip()]
                    return '\n'.join(bullets)

                for entry in json_data.get("education", []):
                    entry["description"] = format_description(entry.get("description", ""))

                for entry in json_data.get("work_experience", []):
                    entry["description"] = format_description(entry.get("description", ""))

                today = datetime.date.today()

                # Preprocesar fechas en work_experience
                for entry in json_data.get("work_experience", []):
                    # Formatear fechas incompletas
                    start = entry.get("start_date", "")
                    end = entry.get("end_date", "")

                    if start and len(start) == 4:
                        entry["start_date"] = f"{start}-01-01"
                    elif start and len(start) == 7:
                        entry["start_date"] = f"{start}-01"

                    if end and len(end) == 4:
                        entry["end_date"] = f"{end}-01-01"
                    elif end and len(end) == 7:
                        entry["end_date"] = f"{end}-01"

                    # Evaluar si es actual
                    if not entry.get("end_date"):
                        entry["current"] = True
                    else:
                        try:
                            end_date_obj = datetime.datetime.strptime(entry["end_date"], "%Y-%m-%d").date()
                            entry["current"] = end_date_obj > today
                        except:
                            entry["current"] = False

                # Preprocesar fechas en education
                for entry in json_data.get("education", []):
                    start = entry.get("start_date", "")
                    end = entry.get("end_date", "")

                    if start and len(start) == 4:
                        entry["start_date"] = f"{start}-01-01"
                    elif start and len(start) == 7:
                        entry["start_date"] = f"{start}-01"

                    if end and len(end) == 4:
                        entry["end_date"] = f"{end}-01-01"
                    elif end and len(end) == 7:
                        entry["end_date"] = f"{end}-01"

                    if not entry.get("end_date"):
                        entry["current"] = True
                    else:
                        try:
                            end_date_obj = datetime.datetime.strptime(entry["end_date"], "%Y-%m-%d").date()
                            entry["current"] = end_date_obj > today
                        except:
                            entry["current"] = False

            except:
                json_data = json.loads(re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', content.strip()))

            about = json_data.get('about', '')
            education = json.dumps(json_data.get('education', []))
            work_experience = json.dumps(json_data.get('work_experience', []))
            tools = json.dumps(json_data.get('tools', []))

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT 1 FROM resume WHERE candidate_id = %s", (candidate_id,))
            exists = cursor.fetchone()

            if exists:
                cursor.execute("""
                    UPDATE resume SET about=%s, education=%s, work_experience=%s, tools=%s
                    WHERE candidate_id=%s
                """, (about, education, work_experience, tools, candidate_id))
            else:
                cursor.execute("""
                    INSERT INTO resume (candidate_id, about, education, work_experience, tools)
                    VALUES (%s, %s, %s, %s, %s)
                """, (candidate_id, about, education, work_experience, tools))

            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"success": True, "about": about, "education": education, "work_experience": work_experience, "tools": tools})

        except Exception as e:
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

 