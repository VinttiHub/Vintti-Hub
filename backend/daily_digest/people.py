"""Quien es quien en Slack, y los umbrales de las reglas.

Todo literal y hardcodeado, mismo criterio que `dashboards/audit/service.py` y
`ae_commissions/service.py`. Aca la razon es mas fuerte todavia: el costo de una
env var mal seteada no es un mail de mas, es **mencionar a la persona
equivocada** delante de todo el equipo, y eso no se deshace.

Para llenar SLACK_MEMBER_IDS no hay que tipear nada a mano: con la app de Slack
ya instalada, `GET /daily-digest/slack-users` devuelve el mapa listo para pegar.
"""
from __future__ import annotations

from datetime import date

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

# Raya en la arena para la regla de PRICING: solo se reclaman hires que arrancaron
# en esta fecha o despues.
#
# Decision de Lara (AM) y la owner, 2026-09-10, con el digest ya andando: los 11
# hires incompletos que habia iban de 16 a 177 dias de antiguedad y varios son
# irrecuperables. Textual: "estas q quedaron incompletas ya esta, a partir d ahora
# no deberian quedar incompletas". Reclamarlos todos los dias no los completa, solo
# entrena a la gente a ignorar el mensaje.
#
# Es una FECHA FIJA, no una ventana movil de N dias, y la diferencia importa: con
# una ventana, un pendiente que se ignora lo suficiente se cae solo de la lista, que
# es exactamente el incentivo que este digest tiene que evitar. Con una fecha fija,
# lo que entra no se va hasta que alguien carga el dato.
#
# Mover esta fecha hacia adelante = perdonar otra tanda. Que lo pida la owner.
PRICING_DESDE = date(2026, 9, 10)

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

# Stages del pipeline ACTIVO, para las reglas de JD y datos base.
#
# `Deep Dive` y `NDA Sent` estan afuera por decision de la owner (2026-09-10): en
# esas dos la vacante todavia se esta negociando y reclamar el budget o la job
# description es reclamar algo que legitimamente no existe. Sacarlas bajo el
# ruido de 27 avisos a 10.
#
# `Interviewing` es el stage mas poblado del pipeline y es facil de olvidar al
# escribir una lista a mano; los datasets de dashboards que si lo contemplan son
# la referencia (batch_delivery_time_*.py, sales_funnel_*.py).
# `Stop` queda afuera a proposito: pausada, no atrasada.
STAGES_ABIERTOS = ("Sourcing", "Interviewing", "Negotiating")

# Stages donde el hire ya existe y el pricing tiene que estar cargado.
#
# Incluye `Close Win` y NO sigue el filtro de STAGES_ABIERTOS, a proposito: al
# firmar, la opp pasa a Close Win casi enseguida (en la base hay 1 sola opp en
# `Signed` contra 353 en `Close Win`), asi que TODOS los hires con pricing sin
# cargar viven ahi. Limitar esta regla al pipeline activo la deja en cero.
#
# El "activo" de esta regla pasa por otro lado y ya esta aplicado en
# queries.pricing(): se excluyen los hires con baja cargada, con fecha de salida
# pasada o con status inactivo. O sea, gente que hoy trabaja y no tiene el
# numero cargado.
STAGES_CON_HIRE = ("Signed", "Close Win")

# Valores basura que el form guarda cuando nadie toca el select. El primer
# <option> es truthy, asi que `el.value || DEFAULT` nunca aplica el default y el
# placeholder termina en la base como si fuera un mail.
PLACEHOLDERS = ("select sales lead", "select hr lead", "select", "-", "n/a")

# Topes del mensaje. Slack corta en 50 bloques y 3000 chars por section.
MAX_ITEMS_PER_PERSON = 5
MAX_PEOPLE = 12

# Postear tambien los dias sin pendientes, con un "todo al dia".
#
# Arranco al reves (silencio salvo los lunes) para no hacer ruido, pero la owner
# lo cambio el 2026-09-10: prefiere el mensaje siempre. Tiene sentido por dos
# motivos, y el segundo es el que importa: un dia limpio es una buena noticia que
# vale la pena mostrar, y sobre todo el silencio es ambiguo — "no hay nada
# pendiente" y "el cron se murio" se ven exactamente igual. Con esto, si un dia
# no llega nada al canal, es un problema.
POSTEAR_SIN_PENDIENTES = True

# Emoji del mensaje de "todo al dia".
#
# Solo emoji ESTANDAR de Slack. Uno custom (un GIF subido al workspace) se
# escribe igual, `:nombre:`, pero si alguien lo borra Slack no lo esconde: lo
# muestra como texto literal ":nombre:" en el medio del mensaje. No vale la pena
# esa dependencia para un adorno.
EMOJI_TODO_AL_DIA = ":tada:"


def slack_id(email: str) -> str | None:
    return SLACK_MEMBER_IDS.get((email or "").strip().lower())
