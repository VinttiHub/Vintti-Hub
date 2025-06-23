from flask import Blueprint, request, jsonify
import os
import openai
import logging

openai.api_key = os.getenv("OPENAI_API_KEY")

bp_ai = Blueprint('bp_ai', __name__)

@bp_ai.route('/ai/hello', methods=['POST'])
def say_hello():
    logging.info("🟢 POST /ai/hello received")

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
        return jsonify({"message": text})
    
    except Exception as e:
        logging.error(f"❌ Error: {e}")
        return jsonify({"error": str(e)}), 500
