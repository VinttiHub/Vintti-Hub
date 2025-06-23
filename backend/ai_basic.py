from flask import Blueprint, request, jsonify
import os
import openai
import logging

openai.api_key = os.getenv("OPENAI_API_KEY")

bp_ai = Blueprint('bp_ai', __name__)

@bp_ai.route('/ai/hello', methods=['POST', 'OPTIONS'])
def say_hello():
    logging.info("🟢 /ai/hello recibido con método: %s", request.method)

    # Manejo del preflight
    if request.method == 'OPTIONS':
        logging.info("🟡 Preflight OPTIONS para /ai/hello")
        response = jsonify({'status': 'ok'})
        response.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,PATCH,OPTIONS'
        return response, 204

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say hello!"}
            ],
            temperature=0.5,
            max_tokens=50
        )

        text = response['choices'][0]['message']['content']
        logging.info(f"✅ OpenAI responded: {text}")
        final_response = jsonify({"message": text})
        final_response.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
        final_response.headers['Access-Control-Allow-Credentials'] = 'true'
        return final_response

    except Exception as e:
        logging.error(f"❌ Error: {e}")
        response = jsonify({"error": str(e)})
        response.headers['Access-Control-Allow-Origin'] = 'https://vinttihub.vintti.com'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        return response, 500
