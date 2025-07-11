# db.py
import psycopg2

def get_connection():
    return psycopg2.connect(
        host="vintti-hub-db.ctia0ga4u82m.us-east-2.rds.amazonaws.com",
        port="5432",
        database="postgres",
        user="adminuser",
        password="Elementum54!"
    )
