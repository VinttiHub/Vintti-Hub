"""Listas cerradas del CRM de prospección. Única definición: la página las pide
por `GET /prospecting/options`, así que no hay una segunda copia en el JS."""

# Prospecting Status. '' (vacío) = todavía nadie la tomó.
STATUS_IN_PROGRESS = "In Progress"
STATUS_DQL = "DQL"
STATUS_RECYCLED = "Recycled"
STATUS_QUALIFIED = "Qualified"
STATUS_SQL = "SQL"
STATUSES = [STATUS_IN_PROGRESS, STATUS_DQL, STATUS_RECYCLED, STATUS_QUALIFIED, STATUS_SQL]

# Not ICP Reason. Las dos primeras salen de HubSpot; el resto se completa
# cuando pasen la lista entera.
NOT_ICP_REASONS = [
    "Equipo en Asia",
    "+500 empleados",
    "Other",
]

SIZES = [
    "1-10",
    "11-50",
    "51-200",
    "201-500",
    "501-1000",
    "1001-5000",
    "5000+",
]

# Siempre tiene acceso y ve el panel de pruebas, además de quien tenga rol BDR.
ADMIN_EMAILS = {"pgonzales@vintti.com"}

# `users.role` es texto libre: cuenta como BDR cualquier rol que contenga esto.
BDR_ROLE_PATTERN = "%BDR%"

# Campos que trabaja el BDR. Un re-envío de Clay NUNCA los pisa.
BDR_FIELDS = (
    "prospecting_status",
    "prospecting_owner_email",
    "prospecting_start_date",
    "not_icp_reason",
    "week_label",
)

# Campos de enriquecimiento: los manda Clay y un re-envío los actualiza.
CLAY_FIELDS = (
    "name",
    "hubspot_company_id",
    "website",
    "linkedin_url",
    "description",
    "industry",
    "keywords",
    "technologies",
    "job_types",
    "open_jobs",
    "founded_year",
    "size",
    "city",
    "state",
    "country",
    "lead_source",
)

# Lo que se puede editar desde la página.
EDITABLE_FIELDS = BDR_FIELDS + ("lead_source",)


# --------------------------------------------------------------------------- #
# Workflows editables desde la página
# --------------------------------------------------------------------------- #
# Pueden crear, editar, activar y borrar workflows (decisión de la owner,
# 2026-10-05). También tienen acceso a la página y ven las dummies aunque no
# sean BDR: las necesitan para probar lo que arman. Los BDRs ven la lista en
# modo lectura.
WORKFLOW_EDITORS = {
    "pgonzales@vintti.com",
    "manuela@vintti.com",
    "mia@vintti.com",
}

# Freno de la fase de prueba. Mientras sea False, lo AUTOMÁTICO (al editar una
# empresa, al llegar de Clay y el cron diario) sólo toca empresas dummy; sobre
# datos reales un workflow corre únicamente con el botón Apply. Se pasa a True
# con el OK de la owner, junto con descomentar el schedule de
# .github/workflows/prospecting-workflows.yml.
AUTOMATION_REAL_DATA = False

# Campos que se pueden usar en un workflow, con su tipo. El tipo decide qué
# operadores admite la condición y qué valor acepta una acción.
#   enum / owner -> lista cerrada (owner = BDRs del Hub)
#   text / longtext / url -> texto libre
#   number, date
# `options` de un enum se completa en options() con la lista de arriba.
FIELDS = [
    {"key": "name", "label": "Nombre de la empresa", "type": "text"},
    {"key": "prospecting_status", "label": "Prospecting Status", "type": "enum", "options": STATUSES},
    # Un solo owner (2026-10-28): "Prospecting Owner Apollo" venía de HubSpot y se
    # sacó. La columna sigue en la tabla, sin uso.
    {"key": "prospecting_owner_email", "label": "Prospecting Owner", "type": "owner"},
    {"key": "prospecting_start_date", "label": "Prospecting Start Date", "type": "date"},
    {"key": "not_icp_reason", "label": "Not ICP Reason", "type": "enum", "options": NOT_ICP_REASONS},
    {"key": "week_label", "label": "Semana", "type": "text"},
    {"key": "lead_source", "label": "Lead Source", "type": "text"},
    {"key": "keywords", "label": "Keywords of the company", "type": "longtext"},
    {"key": "technologies", "label": "Technologies", "type": "longtext"},
    {"key": "job_types", "label": "Tipo de vacantes", "type": "longtext"},
    {"key": "open_jobs", "label": "Numero de vacantes abiertas", "type": "number"},
    {"key": "industry", "label": "Industria", "type": "longtext"},
    {"key": "founded_year", "label": "Founded Year", "type": "number"},
    {"key": "website", "label": "URL del sitio web", "type": "url"},
    {"key": "linkedin_url", "label": "Pagina Corporativa de LinkedIn", "type": "url"},
    {"key": "description", "label": "Descripcion", "type": "longtext"},
    {"key": "size", "label": "Size", "type": "enum", "options": SIZES},
    {"key": "city", "label": "Ciudad", "type": "text"},
    {"key": "state", "label": "Estado", "type": "text"},
    {"key": "country", "label": "Pais", "type": "text"},
    {"key": "hubspot_company_id", "label": "Id de la empresa (HubSpot)", "type": "text"},
    {"key": "created_at", "label": "Fecha de creación", "type": "date"},
]
FIELDS_BY_KEY = {f["key"]: f for f in FIELDS}

# Operadores por tipo. Los nombres y lo que hace cada uno salen del doc de la owner
# («Hubspot - Hub : NUEVO CRM», sección filtros avanzados): se copian LITERALES. Los
# del hub que el doc no tiene van al final de cada menú con su nombre de antes.
# `value`: qué pide el operador —
#   None = nada, "list" = varios valores (de la lista si la propiedad tiene opciones;
#   si no, textos libres), "text", "number", "days" = cantidad de días,
#   "date" = una fecha, "number_range" / "date_range" = [desde, hasta],
#   "period" = una clave de PERIODS, "field" = otra propiedad del mismo registro.
# `history`: se responde con el historial (prospect_company_events), no con el
# valor actual. Ojo: sólo hay historial de los campos que se editan en el Hub.
OPERATORS = {
    # 1. Texto
    "equals":                  {"label": "Es igual a",                          "value": "text"},
    "not_equals":              {"label": "No es igual a",                       "value": "text"},
    "equals_any":              {"label": "Es igual a cualquiera de",            "value": "list"},
    "not_equals_any":          {"label": "No es igual a ninguno de",            "value": "list"},
    "contains":                {"label": "Contiene cualquiera de",              "value": "list"},
    # También en selección: "excluye los registros que tienen cualquiera de los valores".
    "not_contains":            {"label": "No contiene ninguno de",              "value": "list"},
    "contains_exactly":        {"label": "Contiene exactamente",                "value": "text"},
    "not_contains_exactly":    {"label": "No contiene exactamente",             "value": "text"},
    "starts_with":             {"label": "Comienza con cualquiera de",          "value": "list"},
    "ends_with":               {"label": "Termina con cualquiera de",           "value": "list"},
    # 2. Selección
    "is_any":                  {"label": "Es cualquiera de",                    "value": "list"},
    "is_none_of":              {"label": "No es ninguno de",                    "value": "list"},
    "contains_all":            {"label": "Contiene todos de",                   "value": "list"},
    "not_contains_all":        {"label": "No contiene todos de",                "value": "list"},
    "equals_all":              {"label": "Es igual a todos de",                 "value": "list"},
    "not_equals_all":          {"label": "No es igual a todos de",              "value": "list"},
    # 3. Número
    "eq":                      {"label": "Es igual a",                          "value": "number"},
    "not_eq":                  {"label": "No es igual a",                       "value": "number"},
    "gt":                      {"label": "Es mayor que",                        "value": "number"},
    "gte":                     {"label": "Es mayor o igual que",                "value": "number"},
    "lt":                      {"label": "Es menor que",                        "value": "number"},
    "lte":                     {"label": "Es menor o igual que",                "value": "number"},
    "gt_field":                {"label": "Es mayor que otra propiedad",         "value": "field"},
    "lt_field":                {"label": "Es menor que otra propiedad",         "value": "field"},
    # 4. Fecha
    "is_period":               {"label": "Es",                                  "value": "period"},
    "before":                  {"label": "Es anterior a",                       "value": "date"},
    "after":                   {"label": "Es posterior a",                      "value": "date"},
    "between_dates":           {"label": "Está entre",                          "value": "date_range"},
    "not_between_dates":       {"label": "No está entre",                       "value": "date_range"},
    "older_than_days":         {"label": "Hace más de",                         "value": "days"},
    "more_than_days_ahead":    {"label": "Dentro de más de",                    "value": "days"},
    # 5. Históricos
    "ever_was":                {"label": "Alguna vez fue cualquiera de",        "value": "list", "history": True},
    "never_was":               {"label": "Nunca fue ninguno de",                "value": "list", "history": True},
    "ever_equals":             {"label": "Alguna vez fue igual a",              "value": "text", "history": True},
    "never_equals":            {"label": "Nunca fue igual a",                   "value": "text", "history": True},
    "ever_equals_any":         {"label": "Alguna vez fue igual a cualquiera de", "value": "list", "history": True},
    "never_equals_any":        {"label": "Nunca fue igual a ninguno de",        "value": "list", "history": True},
    "ever_contained_exactly":  {"label": "Alguna vez contuvo exactamente",      "value": "text", "history": True},
    "never_contained_exactly": {"label": "Nunca contuvo exactamente",           "value": "text", "history": True},
    # 6. Valor vacío y actualización (cualquier tipo). «Actualizado en los últimos» de
    # la sección 5 es esta misma función: se muestra sólo el nombre de la sección 6.
    "known":                   {"label": "Es conocido",                         "value": None},
    "unknown":                 {"label": "Es desconocido",                      "value": None},
    "changed_in_last_days":    {"label": "Se actualizó en los últimos…",        "value": "days", "history": True},
    "not_changed_in_days":     {"label": "No se actualizó en los últimos…",     "value": "days", "history": True},
    "updated_after_field":     {"label": "Se actualizó después de otra propiedad", "value": "field", "history": True},
    "updated_before_field":    {"label": "Se actualizó antes de otra propiedad",   "value": "field", "history": True},
    # Del hub, no están en el doc: al final del menú, con su nombre de siempre.
    "is_on":                   {"label": "es el día",                           "value": "date"},
    "between":                 {"label": "está entre",                          "value": "number_range"},
    "within_last_days":        {"label": "es de los últimos",                   "value": "days"},
    "in_next_days":            {"label": "es en los próximos",                  "value": "days"},
    "is_true":                 {"label": "está marcada",                        "value": None},
    "is_false":                {"label": "no está marcada",                     "value": None},
    # Sólo para leer reglas guardadas antes del cambio: rules.normalize_rule() las
    # traduce (has_any → is_any, has_none → not_contains, is_today → is_period "today").
    "has_any":                 {"label": "Es cualquiera de",                    "value": "list"},
    "has_none":                {"label": "No contiene ninguno de",              "value": "list"},
    "is_today":                {"label": "Es hoy",                              "value": None},
}
LEGACY_OPERATORS = {"has_any", "has_none", "is_today"}

# Explicación del «?» de cada operador: columna «Qué comprueba» del doc, LITERAL. Un par
# que el doc agrupa en una fila («Es igual a / No es igual a») lleva la misma frase.
_UPDATED_NOTE = (" La actualización refiere a la fecha en la que la propiedad fue editada, ya sea "
                 "manualmente por alguien del equipo o de forma automática por medio de un workflow.")
OPERATOR_HELP = {
    "equals": "Coincidencia exacta con el valor completo.",
    "not_equals": "Coincidencia exacta con el valor completo.",
    "equals_any": "Coincidencia exacta con alguno de los textos indicados, o su exclusión.",
    "not_equals_any": "Coincidencia exacta con alguno de los textos indicados, o su exclusión.",
    "contains": "El texto aparece dentro del valor, incluso como parte de una palabra.",
    "not_contains": "El valor no contiene ninguno de los textos indicados.",
    "contains_exactly": "Busca palabras completas dentro del valor, sin exigir que todo el campo sea idéntico.",
    "not_contains_exactly": "Excluye los registros que contienen esas palabras completas.",
    "starts_with": "El valor empieza con alguno de los textos indicados.",
    "ends_with": "El valor termina con alguno de los textos indicados.",
    "is_any": "Tiene al menos uno de los valores seleccionados.",
    "is_none_of": "No coincide con ninguno de los valores seleccionados.",
    "contains_all": "Tiene todos los valores seleccionados, aunque tenga otros más.",
    "not_contains_all": "Excluye los registros que tienen todos los valores seleccionados juntos.",
    "equals_all": "Compara los valores de la propiedad con el conjunto exacto de valores indicados.",
    "not_equals_all": "Compara los valores de la propiedad con el conjunto exacto de valores indicados.",
    "eq": "El número coincide o no con el valor indicado.",
    "not_eq": "El número coincide o no con el valor indicado.",
    "gt": "El número supera (o iguala) el valor indicado.",
    "gte": "El número supera (o iguala) el valor indicado.",
    "lt": "El número está por debajo (o iguala) el valor indicado.",
    "lte": "El número está por debajo (o iguala) el valor indicado.",
    "gt_field": "Compara contra otra propiedad numérica del mismo registro.",
    "lt_field": "Compara contra otra propiedad numérica del mismo registro.",
    "is_period": "Un período relativo: hoy, la semana pasada, este año hasta la fecha, etc.",
    "before": "Una fecha anterior a la indicada.",
    "after": "Una fecha posterior a la indicada.",
    "between_dates": "Una fecha dentro de un intervalo, incluidos los extremos.",
    "not_between_dates": "Una fecha fuera del intervalo.",
    "ever_was": "Tuvo alguno de los valores seleccionados.",
    "never_was": "Nunca tuvo esos valores.",
    "ever_equals": "Tuvo, o nunca tuvo, un valor exacto.",
    "never_equals": "Tuvo, o nunca tuvo, un valor exacto.",
    "ever_equals_any": "Compara los valores históricos completos con los indicados.",
    "never_equals_any": "Compara los valores históricos completos con los indicados.",
    "ever_contained_exactly": "Busca coincidencias históricas con el texto indicado.",
    "never_contained_exactly": "Busca coincidencias históricas con el texto indicado.",
    "known": "La propiedad tiene un valor.",
    "unknown": "La propiedad está vacía.",
    "changed_in_last_days": "La propiedad cambió dentro de la cantidad de días indicada." + _UPDATED_NOTE,
    "not_changed_in_days": "La propiedad no cambió en ese período." + _UPDATED_NOTE,
    "updated_after_field": "Su última actualización es posterior a la de otra propiedad.",
    "updated_before_field": "Su última actualización es anterior a la de otra propiedad.",
}
# En selección, «No contiene ninguno de» tiene su propia fila en el doc.
OPERATOR_HELP_SELECT = {
    "not_contains": "Excluye los registros que tienen cualquiera de los valores seleccionados.",
}
# Sin texto en el doc: «Hace más de / Dentro de más de» (su fila está desarmada) y los
# sobrantes del hub. Redacción nuestra; el «?» lo marca como «no está en el doc».
OPERATOR_HELP_HUB = {
    "older_than_days": "La fecha es de hace más de la cantidad de días indicada.",
    "more_than_days_ahead": "La fecha es dentro de más de la cantidad de días indicada.",
    "is_on": "La fecha es exactamente el día indicado.",
    "between": "El número está entre los dos valores indicados, incluidos los extremos.",
    "within_last_days": "La fecha cae entre hoy y la cantidad de días indicada hacia atrás.",
    "in_next_days": "La fecha cae entre hoy y la cantidad de días indicada hacia adelante.",
    "is_true": "La casilla está marcada.",
    "is_false": "La casilla no está marcada (o está vacía).",
}
for _k, _op in OPERATORS.items():
    if _k in OPERATOR_HELP:
        _op["help"] = OPERATOR_HELP[_k]
    elif _k in OPERATOR_HELP_HUB:
        _op["help"], _op["help_src"] = OPERATOR_HELP_HUB[_k], "hub"
    if _k in OPERATOR_HELP_SELECT:
        _op["help_select"] = OPERATOR_HELP_SELECT[_k]

# «Es» de fechas: período relativo a hoy (hora Argentina). Semana = lunes a domingo.
# Los límites los calcula rules.period_bounds(), el mismo para SQL y Python.
PERIODS = {
    "today":              "Hoy",
    "yesterday":          "Ayer",
    "tomorrow":           "Mañana",
    "this_week":          "Esta semana",
    "this_week_to_date":  "Esta semana hasta la fecha",
    "last_week":          "La semana pasada",
    "next_week":          "La próxima semana",
    "this_month":         "Este mes",
    "this_month_to_date": "Este mes hasta la fecha",
    "last_month":         "El mes pasado",
    "next_month":         "El próximo mes",
    "this_quarter":       "Este trimestre",
    "last_quarter":       "El trimestre pasado",
    "this_year":          "Este año",
    "this_year_to_date":  "Este año hasta la fecha",
    "last_year":          "El año pasado",
    "last_7_days":        "Últimos 7 días",
    "last_30_days":       "Últimos 30 días",
    "last_90_days":       "Últimos 90 días",
}

# Orden de cada menú = el del doc: los del tipo → históricos → sección 6 → sobrantes.
_TEXT = ["equals", "not_equals", "equals_any", "not_equals_any", "contains", "not_contains",
         "contains_exactly", "not_contains_exactly", "starts_with", "ends_with"]
_TEXT_HISTORY = ["ever_equals", "never_equals", "ever_equals_any", "never_equals_any",
                 "ever_contained_exactly", "never_contained_exactly"]
_SELECT = ["is_any", "is_none_of", "not_contains"]
_SELECT_HISTORY = ["ever_was", "never_was"]
_EMPTY_UPDATED = ["known", "unknown", "changed_in_last_days", "not_changed_in_days",
                  "updated_after_field", "updated_before_field"]
_DATE = ["is_period", "before", "after", "between_dates", "not_between_dates",
         "older_than_days", "more_than_days_ahead"] + _EMPTY_UPDATED + ["is_on", "within_last_days", "in_next_days"]
OPERATORS_BY_TYPE = {
    "enum":     _SELECT + _SELECT_HISTORY + _EMPTY_UPDATED,
    "owner":    _SELECT + _SELECT_HISTORY + _EMPTY_UPDATED,
    "text":     _TEXT + _TEXT_HISTORY + _EMPTY_UPDATED,
    "longtext": _TEXT + _TEXT_HISTORY + _EMPTY_UPDATED,
    "url":      _TEXT + _TEXT_HISTORY + _EMPTY_UPDATED,
    "number":   ["eq", "not_eq", "gt", "gte", "lt", "lte", "gt_field", "lt_field"] + _EMPTY_UPDATED + ["between"],
    "date":     _DATE,
    # Tipos que usan los contactos (prospecting/contact_fields.py).
    "user":     _SELECT + _SELECT_HISTORY + _EMPTY_UPDATED,
    "email":    _TEXT + _TEXT_HISTORY + _EMPTY_UPDATED,
    "phone":    _TEXT + _TEXT_HISTORY + _EMPTY_UPDATED,
    "bool":     _EMPTY_UPDATED + ["is_true", "is_false"],
    # Casillas múltiples: la sección Selección completa («todos de» sólo tiene sentido acá).
    "multi":    _SELECT + ["contains_all", "not_contains_all", "equals_all", "not_equals_all"] + _EMPTY_UPDATED,
    "datetime": _DATE,
}

# --------------------------------------------------------------------------- #
# Acciones. `group` las ordena en el menú del editor; `field` dice si piden una
# propiedad editable (y de qué tipos). Los parámetros de cada una los valida
# rules._check_action().
# --------------------------------------------------------------------------- #
ACTIONS = {
    # Editar registro
    "set":            {"label": "Definir",                      "group": "Editar registro", "field": True},
    "clear":          {"label": "Borrar",                       "group": "Editar registro", "field": True},
    "set_today":      {"label": "Poner la fecha de hoy",        "group": "Editar registro", "field": True, "types": ["date"]},
    "set_date_offset": {"label": "Poner hoy ± N días",          "group": "Editar registro", "field": True, "types": ["date"]},
    "copy":           {"label": "Copiar el valor de otra propiedad", "group": "Editar registro", "field": True},
    "increment":      {"label": "Sumar o restar",               "group": "Editar registro", "field": True, "types": ["number"]},
    # Asignación
    "rotate_owner":   {"label": "Repartir entre BDRs (por turnos)", "group": "Asignación"},
    # Sólo workflows de contacto: el "Crear asociaciones" de HubSpot. Hoy el BDR crea
    # el contacto dentro de su empresa (ya nace asociado); sirve cuando lleguen
    # contactos de Clay o haya que moverlos a la empresa de su dominio.
    "associate_company": {"label": "Crear asociación con la empresa (por dominio del email)", "group": "Asociaciones", "objects": ["contact"]},
    # Comunicación interna
    "create_todo":    {"label": "Crear To-Do",                  "group": "Comunicación"},
    "send_email":     {"label": "Mandar mail interno",          "group": "Comunicación"},
    "send_slack":     {"label": "Avisar por Slack",             "group": "Comunicación"},
    "add_note":       {"label": "Agregar nota",                 "group": "Comunicación"},
    # Otros
    "webhook":        {"label": "Mandar webhook",               "group": "Otros"},
    "enroll_workflow":   {"label": "Inscribir en otro workflow", "group": "Otros"},
    "unenroll_workflow": {"label": "Sacar de otro workflow",     "group": "Otros"},
}

# Disparadores (tarjeta de inscripción).
TRIGGERS = {
    "filter":   {"label": "Cuando cumple condiciones"},
    "event":    {"label": "Cuando pasa algo"},
    "schedule": {"label": "En un horario"},
    "manual":   {"label": "Sólo inscripción manual"},
}
EVENTS = {
    "created":          {"label": "Se crea (empresa: llega de Clay · contacto: lo agrega un BDR)"},
    "property_changed": {"label": "Cambia una propiedad"},
}
SCHEDULES = {
    "daily":  {"label": "Todos los días"},
    "weekly": {"label": "Ciertos días de la semana"},
    "date":   {"label": "Una fecha"},
}
DELAYS = {
    "duration":       {"label": "Un tiempo"},
    "until_date":     {"label": "Hasta una fecha"},
    "until_property": {"label": "Hasta la fecha de una propiedad"},
    "until_weekday":  {"label": "Hasta ciertos días de la semana"},
    "until_time":     {"label": "Hasta una hora del día"},
    "until_condition": {"label": "Hasta que se cumpla algo"},
}
BRANCHES = {
    "value":      {"label": "Según el valor de una propiedad"},
    "conditions": {"label": "Según condiciones (Y/O)"},
    "random":     {"label": "Reparto al azar por %"},
}
WEEKDAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# Zona horaria de los horarios, días hábiles y esperas "hasta las 9".
TIMEZONE = "America/Argentina/Buenos_Aires"

# Tope de pasos por corrida de una inscripción: corta los loops de "ir a".
MAX_STEPS_PER_RUN = 50

# Destinos de prueba: un workflow que corre sobre una empresa DUMMY nunca le
# escribe a una persona real. Mails y To-Dos van a la owner, Slack al canal de
# prueba (el que usó stale_opps_slack antes de pasar a Sales & Opps), y los
# webhooks se registran sin mandarse.
TEST_EMAIL = "pgonzales@vintti.com"
TEST_SLACK_CHANNEL = "C0C0UQ7SYBW"

# Mails internos: sólo a direcciones de la empresa.
INTERNAL_EMAIL_DOMAIN = "@vintti.com"

# El workflow que vino de HubSpot. Se siembra como primera fila de
# prospect_workflows la primera vez que se crea la tabla.
DEFAULT_WORKFLOWS = [
    {
        "name": "Recycle: In Progress hace más de 60 días",
        "description": "Copia del workflow de HubSpot: libera la empresa para que otro BDR la tome.",
        "enabled": False,
        "reenroll": True,
        "trigger": {"type": "filter", "conditions": {"groups": [{"rules": [
            {"field": "prospecting_start_date", "op": "older_than_days", "value": 60},
            {"field": "prospecting_status", "op": "is_any", "value": [STATUS_IN_PROGRESS]},
        ]}]}},
        "steps": {"start": "n1", "nodes": {
            "n1": {"type": "action", "action": {"type": "clear", "field": "prospecting_owner_email"}, "next": "n3"},
            "n3": {"type": "action", "action": {"type": "clear", "field": "prospecting_start_date"}, "next": "n4"},
            "n4": {"type": "action", "action": {"type": "set", "field": "prospecting_status", "value": STATUS_RECYCLED}, "next": None},
        }},
    },
]
