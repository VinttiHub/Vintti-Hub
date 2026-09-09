"""Quien es quien en Slack, y los umbrales de las reglas.

Todo literal y hardcodeado, mismo criterio que `dashboards/audit/service.py` y
`ae_commissions/service.py`. Aca la razon es mas fuerte todavia: el costo de una
env var mal seteada no es un mail de mas, es **mencionar a la persona
equivocada** delante de todo el equipo, y eso no se deshace.

Para llenar SLACK_MEMBER_IDS no hay que tipear nada a mano: con la app de Slack
ya instalada, `GET /daily-digest/slack-users` devuelve el mapa listo para pegar.
"""
from __future__ import annotations

# mail Vintti -> Slack member ID (el `U...` de "View full profile / Copy member ID").
# Cosechado del directorio del workspace el 2026-09-09 con
# `python3 -m daily_digest --members`, no tipeado a mano: el costo de un typo aca
# no es un mail de mas, es mencionar a la persona equivocada delante del equipo.
#
# Estan TODOS los de @vintti.com, no solo los que hoy tienen pendientes: cuando una
# opp cambie de duenio la mencion tiene que salir bien sin tocar codigo. Quien no
# figure se renderiza con el nombre en negrita (se ve, no notifica) y aparece
# listado al pie del mensaje.
SLACK_MEMBER_IDS: dict[str, str] = {
    "abril@vintti.com": "U09CDE89WJZ",
    "agostina@vintti.com": "U075E47TYE9",
    "agustin@vintti.com": "U075KFE1GUU",
    "agustina@vintti.com": "U0A9MKCB1MK",
    "agustinmorrone@vintti.com": "U092RE4PV7S",
    "ana@vintti.com": "U0AA1FKQDBP",
    "bahia@vintti.com": "U075E47MNGM",
    "bartolome@vintti.com": "U0B7W1ZR95W",
    "benjamin@vintti.com": "U0BV3BKP57T",
    "camila@vintti.com": "U075AC82WR4",
    "catalina@vintti.com": "U0BTE80CJ0P",
    "constanza@vintti.com": "U09Q501020L",
    "emilia@vintti.com": "U09NU0RDH8E",
    "jazmin@vintti.com": "U07K4RBN9L7",
    "joel@vintti.com": "U0BMB23H9HA",
    "julieta@vintti.com": "U0A0NG9KHMY",
    "justo@vintti.com": "U0AK3UKR5TJ",
    "lara@vintti.com": "U076J953U03",
    "luca.garegnani@vintti.com": "U0BRWQ89S5P",
    "lucia@vintti.com": "U09R9BQ48DN",
    "luisa@vintti.com": "U08NMKCUFB6",
    "lunaberto@vintti.com": "U0BABEL1Q3E",
    "magali@vintti.com": "U0AJ954EL7K",
    "manuela@vintti.com": "U0AAHUG75FB",
    "mariano@vintti.com": "U09S4PGFQQ3",
    "matias@vintti.com": "U0BTXGNA49F",
    "mia@vintti.com": "U09JRC26L4S",
    "mora@vintti.com": "U0972LC3APR",
    "paz@vintti.com": "U0A9GT8BMUM",
    "pgonzales@vintti.com": "U092JL5E479",
    "pilar@vintti.com": "U083WH597AL",
    "santiago.botana@vintti.com": "U0BRNKYPGCB",
    "valentina@vintti.com": "U0AD36G7JP9",
    "valeria@vintti.com": "U0AHZRSARUL",
}

# Quien recibe el mail cuando el digest NO puede postear a Slack. Dos canales
# independientes a proposito: si lo roto es Slack, avisar por Slack no sirve.
RECIPIENTS = ["pgonzales@vintti.com"]

# Quien puede abrir GET /daily-digest/preview desde el Hub. No confundir con
# RECIPIENTS ni con quien aparece mencionado en el canal.
DAILY_DIGEST_ALLOWED = {
    "pgonzales@vintti.com",
}

# --------------------------------------------------------------------------- #
# Umbrales. Se calibran leyendo la corrida en seco, no de memoria.
# --------------------------------------------------------------------------- #

# Dias de gracia por regla: nadie recibe un tiron de orejas el mismo dia que
# tiene que cargar el dato.
GRACIA_DIAS = {
    "pricing": 2,
    "jd": 3,
    "base": 3,
}

# Backlog maximo. Mas viejo que esto ya no es "te falta cargar", es arqueologia.
BACKLOG_DIAS = 180

# Menos de estos caracteres de TEXTO PLANO (ya sin tags) = no hay job
# description. No es 0 porque `<p></p>` y `<p>-</p>` limpian a 0-3 caracteres,
# pero un "igual que la anterior" tambien, y tampoco es una JD.
JD_MIN_CHARS = 80

# Campos de "datos base" que se reclaman. Se sacaron del form real de
# opportunity-detail.html, pero la lista la decide la data, no el form:
#
#   `years_experience` esta vacio en 55 de las 65 opps abiertas (85 por ciento,
#   medido 2026-09-09). Reclamarlo convertiria a esta regla en "a todos les
#   falta years_experience" y el equipo silenciaria el canal en una semana.
#   Queda APAGADO. Si algun dia se empieza a cargar, se prende aca y listo.
#
# `fee` (Set Up Fee) tampoco esta: un setup fee en cero es un resultado
# comercial legitimo, no un dato faltante (mismo criterio que
# `docs/assets/js/ae-commissions.js:175-180`).
CAMPOS_BASE = {
    "position": True,       # opp_position_name
    "model": True,          # opp_model
    "sales_lead": True,     # opp_sales_lead
    "type": True,           # opp_type
    "budget": True,         # min_budget / max_budget
    "salary_range": True,   # min_salary / max_salary
    "years_experience": False,
}

# Stages con trabajo abierto. `Interviewing` es el mas poblado del pipeline (28
# opps de 65) y es facil de olvidar al escribir una lista a mano; los datasets de
# dashboards que si lo contemplan son la referencia (batch_delivery_time_*.py,
# sales_funnel_*.py). `Stop` queda afuera a proposito: pausada, no atrasada.
STAGES_ABIERTOS = ("Deep Dive", "NDA Sent", "Sourcing", "Interviewing", "Negotiating")

# Stages donde el hire ya existe y el pricing tiene que estar cargado.
STAGES_CON_HIRE = ("Signed", "Close Win")

# Valores basura que el form guarda cuando nadie toca el select. El primer
# <option> es truthy, asi que `el.value || DEFAULT` nunca aplica el default y el
# placeholder termina en la base como si fuera un mail.
PLACEHOLDERS = ("select sales lead", "select hr lead", "select", "-", "n/a")

# Topes del mensaje. Slack corta en 50 bloques y 3000 chars por section.
MAX_ITEMS_PER_PERSON = 5
MAX_PEOPLE = 12

# Lunes. El unico dia que se postea aunque no haya nada, para que "no hay
# pendientes" no se confunda con "el cron murio".
HEARTBEAT_WEEKDAY = 0


def slack_id(email: str) -> str | None:
    return SLACK_MEMBER_IDS.get((email or "").strip().lower())
