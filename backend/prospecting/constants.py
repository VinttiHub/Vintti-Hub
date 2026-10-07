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
    "prospecting_owner_apollo",
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
    {"key": "prospecting_owner_email", "label": "Prospecting Owner", "type": "owner"},
    {"key": "prospecting_owner_apollo", "label": "Prospecting Owner Apollo", "type": "text"},
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

# Operadores por tipo. `value`: qué pide el operador —
#   None = nada, "list" = varios valores de la lista, "text", "number",
#   "days" = cantidad de días, "date" = una fecha,
#   "number_range" / "date_range" = [desde, hasta].
# `history`: se responde con el historial (prospect_company_events), no con el
# valor actual. Ojo: sólo hay historial de los campos que se editan en el Hub.
OPERATORS = {
    "is_any":               {"label": "es cualquiera de",              "value": "list"},
    "is_none_of":           {"label": "no es ninguno de",              "value": "list"},
    "ever_was":             {"label": "alguna vez fue",                "value": "list", "history": True},
    "never_was":            {"label": "nunca fue",                     "value": "list", "history": True},
    "equals":               {"label": "es igual a",                    "value": "text"},
    "contains":             {"label": "contiene",                      "value": "text"},
    "not_contains":         {"label": "no contiene",                   "value": "text"},
    "starts_with":          {"label": "empieza con",                   "value": "text"},
    "ends_with":            {"label": "termina con",                   "value": "text"},
    "eq":                   {"label": "es igual a",                    "value": "number"},
    "gt":                   {"label": "es mayor que",                  "value": "number"},
    "gte":                  {"label": "es mayor o igual que",          "value": "number"},
    "lt":                   {"label": "es menor que",                  "value": "number"},
    "lte":                  {"label": "es menor o igual que",          "value": "number"},
    "between":              {"label": "está entre",                    "value": "number_range"},
    "is_today":             {"label": "es hoy",                        "value": None},
    "is_on":                {"label": "es el día",                     "value": "date"},
    "before":               {"label": "es antes del",                  "value": "date"},
    "after":                {"label": "es después del",                "value": "date"},
    "between_dates":        {"label": "está entre las fechas",         "value": "date_range"},
    "older_than_days":      {"label": "es de hace más de",             "value": "days"},
    "within_last_days":     {"label": "es de los últimos",             "value": "days"},
    "in_next_days":         {"label": "es en los próximos",            "value": "days"},
    "changed_in_last_days": {"label": "cambió en los últimos",         "value": "days", "history": True},
    "not_changed_in_days":  {"label": "no cambió en los últimos",      "value": "days", "history": True},
    "known":                {"label": "tiene un valor",                "value": None},
    "unknown":              {"label": "está vacío",                    "value": None},
}
_CHANGED = ["changed_in_last_days", "not_changed_in_days"]
OPERATORS_BY_TYPE = {
    "enum":     ["is_any", "is_none_of", "ever_was", "never_was", "known", "unknown"] + _CHANGED,
    "owner":    ["is_any", "is_none_of", "ever_was", "never_was", "known", "unknown"] + _CHANGED,
    "text":     ["equals", "contains", "not_contains", "starts_with", "ends_with", "known", "unknown"] + _CHANGED,
    "longtext": ["contains", "not_contains", "known", "unknown"],
    "url":      ["contains", "not_contains", "starts_with", "ends_with", "known", "unknown"],
    "number":   ["eq", "gt", "gte", "lt", "lte", "between", "known", "unknown"] + _CHANGED,
    "date":     ["is_today", "is_on", "before", "after", "between_dates", "older_than_days",
                 "within_last_days", "in_next_days", "known", "unknown"] + _CHANGED,
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
    "filter":   {"label": "Cuando la empresa cumple condiciones"},
    "event":    {"label": "Cuando pasa algo"},
    "schedule": {"label": "En un horario"},
    "manual":   {"label": "Sólo inscripción manual"},
}
EVENTS = {
    "created":          {"label": "Se crea la empresa (llega de Clay)"},
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
            "n1": {"type": "action", "action": {"type": "clear", "field": "prospecting_owner_email"}, "next": "n2"},
            "n2": {"type": "action", "action": {"type": "clear", "field": "prospecting_owner_apollo"}, "next": "n3"},
            "n3": {"type": "action", "action": {"type": "clear", "field": "prospecting_start_date"}, "next": "n4"},
            "n4": {"type": "action", "action": {"type": "set", "field": "prospecting_status", "value": STATUS_RECYCLED}, "next": None},
        }},
    },
]
