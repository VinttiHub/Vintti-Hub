# Configuración de gunicorn para App Runner.
#
# Se arranca con:  gunicorn -c gunicorn.conf.py app:app
#
# Reemplaza al servidor de desarrollo de Werkzeug (`python app.py`), que Flask
# mismo desaconseja para producción.
import os

# App Runner inyecta PORT; 8080 es el default que ya usaba app.py.
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"

# --- Concurrencia -----------------------------------------------------------
# El límite real NO es la CPU ni la memoria: es RDS.
#
#   max_connections de RDS = 81
#   backend/db.py abre una conexión NUEVA por request y no hay pool,
#   así que cada request en vuelo = 1 conexión a Postgres.
#
# App Runner escala hasta 5 instancias (Max size) con Concurrency 20, o sea
# hasta 100 requests simultáneos => 100 conexiones => se pasa de 81 y Postgres
# empieza a rechazar con "too many connections".
#
# Con 3 workers x 4 threads = 12 en vuelo por instancia:
#   5 instancias x 12 = 60 conexiones pico, con margen bajo las 81.
#
# Si App Runner manda más de 12 a la vez, gunicorn los encola unos milisegundos
# en vez de reventar la base. Encolar es preferible a un 500.
workers = 3
threads = 4

# gthread en vez de sync: la app pasa casi todo el tiempo esperando I/O
# (Postgres, OpenAI, Google Sheets, HubSpot, Coresignal). Con workers sync cada
# request bloquearía un proceso entero mientras espera la red.
worker_class = "gthread"

# --- Timeouts ---------------------------------------------------------------
# El default de gunicorn son 30 s, que mataría operaciones legítimas y largas:
# el snapshot de OKRs encadena ~31 métricas contra Google Sheets, y las rutas de
# IA hacen llamadas con timeout propio de hasta 45 s. 300 s da aire de sobra;
# esto es un detector de workers colgados, no un SLA de request.
timeout = 300
graceful_timeout = 30

# Debe superar el idle timeout del balanceador de App Runner para que no corte
# conexiones que el proxy todavía cree vivas.
keepalive = 75

# --- Arranque ---------------------------------------------------------------
# preload_app queda en False A PROPÓSITO, aunque activarlo aceleraría el arranque
# (importaría la app una vez en vez de una por worker).
#
# Con preload_app = True, medido en la Mac: de 36 requests concurrentes contra
# /opportunities/<id>, 9 fallaron y los workers murieron con SIGTRAP. Es el
# problema de fork-safety de macOS: el master inicializa el stack SSL al importar
# y los hijos forkeados revientan al usarlo para conectarse a RDS. Con
# preload_app = False el mismo test dio 36/36 en 200 y cero SIGTRAP.
#
# Es muy probable que en Linux (App Runner) preload funcione bien, pero no hay
# forma de comprobarlo desde acá, y lo que se gana son unos cientos de ms de
# arranque. No vale arriesgar producción por eso. Si algún día querés probarlo,
# hacelo en un entorno Linux y mirá que no aparezcan SIGTRAP bajo concurrencia.
#
# Efecto colateral aceptado: cada worker corre create_app() por su cuenta, así
# que el bootstrap en background de admin_user_access se dispara 3 veces al
# arrancar. Es idempotente (CREATE TABLE IF NOT EXISTS) y va en un hilo aparte,
# así que no frena el arranque.
preload_app = False

# Logs a stdout/stderr, que es de donde App Runner los recoge.
accesslog = "-"
errorlog = "-"
loglevel = "info"
