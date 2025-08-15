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
import io, tempfile
from openai import OpenAI
from flask import request, jsonify
import logging
import traceback
import openai
import json
from db import get_connection 
import time

openai.api_key = os.getenv("OPENAI_API_KEY")

def _extract_pdf_text_with_openai(pdf_bytes: bytes, prompt_hint: str = "") -> str:
    """
    Sube el PDF a OpenAI Files y lo pasa al modelo como `input_file`.
    Devuelve el texto extraído en inglés, limpio y en formato plano.
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # 1) Subir el PDF a Files (purpose=user_data)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        up = client.files.create(file=open(tmp.name, "rb"), purpose="user_data")

    # 2) Pedir extracción de texto útil para CV
    prompt = (
        "Extract every resume-relevant fact from the attached PDF. "
        "Return clean plain text in English, no markdown, no tables, no JSON. "
        "Include: full name (if present), contacts, headline/summary, skills/tools, "
        "work experience with titles, companies, locations, date ranges, responsibilities, "
        "education (degrees, institutions, dates), certifications, languages. "
        "Do not invent information. " + (prompt_hint or "")
    )

    resp = client.responses.create(
        model="gpt-4o-mini",
        input=[{
            "role": "user",
            "content": [
                {"type": "input_file", "file_id": up.id},
                {"type": "input_text", "text": prompt}
            ]
        }],
        max_output_tokens=4000,
    )

    # SDK nuevo suele exponer .output_text; si no, armamos desde .output
    text = getattr(resp, "output_text", None)
    if not text:
        parts = []
        try:
            for item in (resp.output or []):
                # Mensajes con contenido textual
                for c in getattr(item, "content", []) or []:
                    t = getattr(c, "text", None)
                    if t:
                        parts.append(t)
        except Exception:
            pass
        text = "\n".join(p for p in parts if p)

    return (text or "").strip()

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
    - translate everything to english
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
    - translate everything to english
    """

            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=7000
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
    - translate everything to english
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

            # Extraer información de la base
            cursor.execute("SELECT about, education, work_experience, tools FROM resume WHERE candidate_id = %s", (candidate_id,))
            result = cursor.fetchone()
            about, education, work_experience, tools = result if result else ("", "[]", "[]", "[]")

            prompt = f"""
            You are a professional resume editor.

            Your task is to rewrite the candidate's "About" section (also known as Summary or Profile) using only the following information.

            --- CANDIDATE NAME ---
            {data.get("candidate_name", "")}

            --- EDUCATION ---
            {education}

            --- WORK EXPERIENCE ---
            {work_experience}

            --- TOOLS ---
            {tools}

            --- USER COMMENT ---
            {user_prompt}

            Instructions:
            - Write a **concise and professional summary (5–7 lines)** in the **third person**.
            - Deduce the candidate’s gender based on the name and context. If unclear, use **gender-neutral language without inventing names or making assumptions**.
            - If the user comment asks to focus on a particular skill, role, industry, or experience, **do not just repeat the comment**. Instead:
                - **Identify a relevant experience or education entry** that supports that focus.
                - **Reorganize and highlight that experience** naturally within the summary.
                - Do not start the summary with the explicit comment the user wrote.
            - Emphasize skills, tools, industries, strengths, and years of experience according to the user comment.
            - Do **not** invent any information. Use only what is available.
            - Return only the final text, no formatting, no explanation, no markdown.
            - Translate everything into English.
            """


            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=300
            )

            new_about = chat.choices[0].message.content.strip()

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
            - translate everything to english
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
            You are a resume generation assistant. Based only on the following data, generate a resume in valid JSON format. Do NOT invent or assume any information.

            LINKEDIN SCRAPER:
            {linkedin_scrapper}

            CV PDF SCRAPER:
            {cv_pdf_scrapper}

            You must always return all 3 fields, even if any of them are empty. Return a complete valid JSON.

            - education: [
                {{
                    "institution": "...", \\translate everything to english
                    "title": "...", \\translate everything to english
                    "start_date": "YYYY-MM-DD",
                    "end_date": "YYYY-MM-DD",
                    "current": true/false,
                    "description": "- Bullet 1\\n- Bullet 2\\n- Bullet 3\\n- Bullet 4\\n..."  // Use all available details. Each description must include at least 5-8 bullet points, written in professional tone. Bullets must cover responsibilities, methods, tools, skills applied, outcomes (if mentioned), and relevant context. Do not add or assume anything that is not clearly present in the input."
                }}
            ]
            - work_experience: [
                {{
                    "title": "...", \\translate everything to english
                    "company": "...", \\translate everything to english
                    "start_date": "YYYY-MM-DD",
                    "end_date": "YYYY-MM-DD",
                    "current": true/false,
                    "description": "In this role I did (short summary). \\n- Bullet 1\\n- Bullet 2\\n- Bullet 3\\n..."  // Start with a simple summary sentence finished with dot, then detailed bullet points using all available data. No extra info.
                }}
            ]
            - tools: [{{"tool":"Excel", "level":"Advanced"}}, ...]

            Rules:
            - Do NOT invent or assume any data. Only use what is explicitly or implicitly present.
            - Use all possible details found in the source to make the descriptions **long, rich and specific**.
            - The descriptions in both education and work experience must be **very detailed bullet points** using `- ` for each bullet.
            - If there is too little info, still write one or two bullets summarizing the available data — but do not fabricate anything.
            - Expand acronyms and explain concepts if mentioned.
            - translate everything to english
            Return only the full JSON object. Do not return only partial content or text outside of the JSON.
            DO NOT merge bullet points into paragraphs. Keep each bullet on a separate line starting with "- ".

            """

            completion = call_openai_with_retry(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a resume generation assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=7000
            )

            if not completion.choices or not hasattr(completion.choices[0], "message"):
                raise Exception("❌ OpenAI response missing 'choices[0].message'")

            content = completion.choices[0].message.content
            print("📥 Resume raw response content:", content)


            try:
                print("🔍 Raw OpenAI response content:", repr(content[:500]))
                json_data = json.loads(content)
                def format_description_to_html(description):
                    if not description:
                        return ""

                    # Separar por líneas
                    lines = description.strip().split("\n")
                    first_sentence = ""
                    bullet_lines = []

                    for line in lines:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        if stripped.startswith("-") or stripped.startswith("•") or stripped.startswith("–"):
                            bullet_lines.append(stripped.lstrip("-•–").strip())
                        elif not first_sentence:
                            first_sentence = stripped

                    html = ""
                    if first_sentence:
                        html += f"<p>{first_sentence}</p>"

                    if bullet_lines:
                        html += "<ul>" + "".join(f"<li>{b}</li>" for b in bullet_lines) + "</ul>"

                    return html

                for entry in json_data.get("education", []):
                    entry["description"] = format_description_to_html(entry.get("description", ""))

                for entry in json_data.get("work_experience", []):
                    entry["description"] = format_description_to_html(entry.get("description", ""))

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

            except Exception as e1:
                try:
                    cleaned = re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', content.strip())
                    json_data = json.loads(cleaned)
                    # 🔄 Convertir bullets a HTML incluso en el segundo intento
                    def format_description_to_html(description):
                        if not description:
                            return ""
                        lines = description.strip().split("\n")
                        first_sentence = ""
                        bullet_lines = []
                        for line in lines:
                            stripped = line.strip()
                            if not stripped:
                                continue
                            if stripped.startswith("-") or stripped.startswith("•") or stripped.startswith("–"):
                                bullet_lines.append(stripped.lstrip("-•–").strip())
                            elif not first_sentence:
                                first_sentence = stripped
                        html = ""
                        if first_sentence:
                            html += f"<p>{first_sentence}</p>"
                        if bullet_lines:
                            html += "<ul>" + "".join(f"<li>{b}</li>" for b in bullet_lines) + "</ul>"
                        return html

                    for entry in json_data.get("education", []):
                        entry["description"] = format_description_to_html(entry.get("description", ""))

                    for entry in json_data.get("work_experience", []):
                        entry["description"] = format_description_to_html(entry.get("description", ""))

                except Exception as e2:
                    raise Exception(f"❌ Error parsing JSON. First attempt: {str(e1)} | Second attempt: {str(e2)} | Content: {content[:300]}")

            education = json.dumps(json_data.get('education', []))
            work_experience = json.dumps(json_data.get('work_experience', []))
            tools = json.dumps(json_data.get('tools', []))

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT 1 FROM resume WHERE candidate_id = %s", (candidate_id,))
            result = cursor.fetchone()
            exists = result is not None


            if exists:
                cursor.execute("""
                    UPDATE resume SET education=%s, work_experience=%s, tools=%s
                    WHERE candidate_id=%s
                """, (education, work_experience, tools, candidate_id))
            else:
                cursor.execute("""
                    INSERT INTO resume (candidate_id, education, work_experience, tools)
                    VALUES (%s, %s, %s, %s)
                """, (candidate_id, education, work_experience, tools))

            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"success": True, "education": education, "work_experience": work_experience, "tools": tools})

        except Exception as e:
            logging.error("❌ Error en /generate_resume_fields:")
            logging.error(traceback.format_exc())
            return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500
        
    @app.route('/ai/coresignal_to_linkedin_scrapper', methods=['POST'])
    def coresignal_to_linkedin_scrapper():
        """
        Genera y guarda en candidates.linkedin_scrapper un texto en inglés,
        bien estructurado (secciones), a partir de candidates.coresignal_scrapper,
        SOLO si coresignal_scrapper tiene contenido y linkedin_scrapper está vacío.
        """
        try:
            data = request.get_json(force=True)
            candidate_id = str(data.get('candidate_id')).strip()
            if not candidate_id:
                return jsonify({"error": "candidate_id is required"}), 400

            conn = get_connection()
            cur = conn.cursor()

            # Lee estado actual
            cur.execute("""
                SELECT COALESCE(coresignal_scrapper, ''), COALESCE(linkedin_scrapper, ''), COALESCE(name, '')
                FROM candidates
                WHERE candidate_id = %s
            """, (candidate_id,))
            row = cur.fetchone()
            if not row:
                cur.close(); conn.close()
                return jsonify({"error": "Candidate not found"}), 404

            coresignal_raw, linkedin_scrap_current, db_name = row
            coresignal_raw = (coresignal_raw or "").strip()
            linkedin_scrap_current = (linkedin_scrap_current or "").strip()

            # Reglas de activación
            if not coresignal_raw:
                cur.close(); conn.close()
                return jsonify({"skipped": True, "reason": "coresignal_scrapper vacío"}), 200
            if linkedin_scrap_current:
                cur.close(); conn.close()
                return jsonify({"skipped": True, "reason": "linkedin_scrapper ya tiene valor"}), 200

            import json, re

            # --- Helpers ---
            def _clean_html(txt: str) -> str:
                txt = re.sub(r'<[^>]+>', ' ', txt)       # quita tags HTML
                txt = re.sub(r'\s+', ' ', txt).strip()   # colapsa espacios
                return txt

            def _prune_deleted_and_empty(text: str) -> str:
                """
                Si el texto es JSON válido, elimina recursivamente items con deleted=1 y entradas vacías.
                Devuelve JSON compacto; si no es JSON válido, retorna el texto original.
                """
                try:
                    obj = json.loads(text)
                except Exception:
                    return text

                def prune(x):
                    if isinstance(x, dict):
                        if str(x.get('deleted', 0)) in ('1', 'true', 'True', 'TRUE', 1):
                            return None
                        out = {}
                        for k, v in x.items():
                            pv = prune(v)
                            if pv in (None, '', [], {}):
                                continue
                            out[k] = pv
                        return out
                    elif isinstance(x, list):
                        out = []
                        for item in x:
                            pv = prune(item)
                            if pv not in (None, '', [], {}):
                                out.append(pv)
                        return out
                    else:
                        return x

                pruned = prune(obj)
                try:
                    return json.dumps(pruned, ensure_ascii=False)
                except Exception:
                    return text

            # Limpieza de origen
            raw = _clean_html(coresignal_raw)
            source = _prune_deleted_and_empty(raw)
            source = source[:15000]  # corte de seguridad

            # ---------- PROMPT NUEVO (plantilla con secciones) ----------
            prompt = f"""
    You are a STRICT CV/LinkedIn extractor. Input is a noisy JSON-like block (often Spanish). Your job:
    - Extract EVERY job-relevant fact that exists in the source.
    - Translate to English.
    - DO NOT invent. If something is missing, omit it.
    - Deduplicate across arrays/variants. Prefer items that include richer fields (e.g., issuer_url, company_industry).
    - Respect that any entries previously marked as deleted=1 have already been filtered out.

    DATE & TEXT NORMALIZATION
    - Dates: use "MMM YYYY" if month exists (Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec); otherwise "YYYY".
    - Current roles end with "Present".
    - Company size: print "Company size: <range or employees_count>" only if present.
    - Industry: use company_industry if present.
    - Languages: normalize proficiency to one of:
    "Native or bilingual", "Full professional", "Professional working", "Limited working", "Elementary".
    - Remove tracking params from URLs (strip the query string).
    - No placeholders or dashes when a field is unknown: just omit that part of the line.

    OUTPUT FORMAT — EXACTLY this sectioned template in plain text (no markdown). Omit any entire section if empty. No extra commentary.

    {{
    FullName}}
    {{City, Country}} • LinkedIn: {{ProfileURL}}

    Professional Headline
    {{Headline}}

    Summary
    {{ShortSummary}}

    Experience
    {{For each role, most recent first:}}
    {{Title}} — {{Company}} {{(Industry in parentheses if available)}}
    {{If location exists, start the line with it followed by " • "}} {{Start}} – {{EndOrPresent}}
    {{If any of these exist on the same line, separate with " • " (and omit missing ones): Duration, Company size}}

    Education
    {{Degree/Program}} — {{Institution}}
    {{Dates line (Start–End)}}

    Certifications
    {{Title}} — {{Issuer}} {{• Date or Date range if any}} {{• Credential: URL if any}}

    Awards
    {{Title}} — {{Issuer if any}} {{• Date if any}}
    {{One short sentence if description exists}}

    Volunteering
    {{Role}} — {{Organization}} {{• Cause if any}}
    {{Dates line (Start–End)}}

    Languages
    {{Language}} — {{Proficiency}}

    Additional Links
    {{Profile photo (URL): <photo_url>}}
    {{Stats: <connections_count> connections • <follower_count> followers}}  {{(only if available)}}

    IMPORTANT
    - Plain text only. No bullets, no JSON, no markdown, no table formatting.
    - Keep spacing tidy. No empty headings. Do not output empty lines at the end.

    SOURCE
    ---
    {source}
    ---
            """.strip()

            # Llamada al modelo
            chat = call_openai_with_retry(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an expert resume writer and information extractor. Output plain text following the exact sectioned template, and never invent facts."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=7000
            )

            out_text = (chat.choices[0].message.content or "").strip()

            # Guarda en candidates.linkedin_scrapper
            cur.execute("""
                UPDATE candidates
                SET linkedin_scrapper = %s
                WHERE candidate_id = %s
            """, (out_text, candidate_id))
            conn.commit()
            cur.close(); conn.close()

            return jsonify({"linkedin_scrapper": out_text, "updated": True}), 200

        except Exception as e:
            logging.error("❌ /ai/coresignal_to_linkedin_scrapper failed\n" + traceback.format_exc())
            return jsonify({"error": str(e)}), 500
    @app.route('/ai/extract_cv_from_pdf', methods=['POST'])
    def extract_cv_from_pdf():
        """
        Extrae texto del último CV (PDF) y lo guarda en candidates.affinda_scrapper y candidates.cv_pdf_scrapper
        Solo corre si affinda_scrapper está vacío.
        Body: { "candidate_id": "<id>", "pdf_url": "<https://.../cv.pdf>" }
        """
        try:
            data = request.get_json(force=True) or {}
            candidate_id = str(data.get('candidate_id', '')).strip()
            pdf_url = (data.get('pdf_url') or '').strip()

            if not candidate_id:
                return jsonify({"error": "candidate_id is required"}), 400

            conn = get_connection()
            cur = conn.cursor()

            # 1) Verificar estado actual
            cur.execute("""
                SELECT COALESCE(affinda_scrapper, ''), COALESCE(cv_pdf_scrapper, '')
                FROM candidates WHERE candidate_id = %s
            """, (candidate_id,))
            row = cur.fetchone()
            if not row:
                cur.close(); conn.close()
                return jsonify({"error": "Candidate not found"}), 404

            affinda_now, cv_pdf_now = row
            if (affinda_now or "").strip():
                cur.close(); conn.close()
                return jsonify({"skipped": True, "reason": "affinda_scrapper already has content"}), 200

            if not pdf_url:
                cur.close(); conn.close()
                return jsonify({"skipped": True, "reason": "pdf_url missing"}), 200

            # 2) Descargar PDF
            r = requests.get(pdf_url, timeout=45)
            if not r.ok or not r.content:
                cur.close(); conn.close()
                return jsonify({"error": f"Failed to download PDF ({r.status_code})"}), 502

            # 3) Enviar a OpenAI para extraer texto
            extracted = _extract_pdf_text_with_openai(r.content)

            if not extracted:
                cur.close(); conn.close()
                return jsonify({"error": "Empty extraction from OpenAI"}), 500

            # 4) Guardar en ambas columnas
            cur.execute("""
                UPDATE candidates
                SET affinda_scrapper = %s, cv_pdf_scrapper = %s
                WHERE candidate_id = %s
            """, (extracted, extracted, candidate_id))
            conn.commit()
            cur.close(); conn.close()

            # Devolvemos el texto por si lo quieres pintar en UI
            return jsonify({"updated": True, "extracted_text": extracted}), 200

        except Exception as e:
            logging.error("❌ /ai/extract_cv_from_pdf failed\n" + traceback.format_exc())
            return jsonify({"error": str(e)}), 500


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

    