from flask import Flask, jsonify
from flask_cors import CORS
import psycopg2
import os

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
    result = fetch_data_from_table("account")
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)

@app.route('/opportunities')
def get_opportunities():
    result = fetch_data_from_table("opportunity")
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)

@app.route('/candidates')
def get_candidates():
    result = fetch_data_from_table("candidates")
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
