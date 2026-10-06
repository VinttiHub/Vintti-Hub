"""Listas cerradas del CRM de prospección. Única definición: la página las pide
por `GET /prospecting/options`, así que no hay una segunda copia en el JS."""

# Prospecting Status. '' (vacío) = todavía nadie la tomó.
STATUS_IN_PROGRESS = "In Progress"
STATUS_DQL = "DQL"
STATUS_RECYCLED = "Recycled"
STATUSES = [STATUS_IN_PROGRESS, STATUS_DQL, STATUS_RECYCLED]

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
    {"key": "created_at", "label": "Create date", "type": "date"},
]
FIELDS_BY_KEY = {f["key"]: f for f in FIELDS}

# Operadores por tipo. `value`: qué pide el operador —
#   None = nada, "list" = varios valores de la lista, "text", "number",
#   "days" = cantidad de días, "date" = una fecha.
OPERATORS = {
    "is_any":           {"label": "is any of",            "value": "list"},
    "is_none_of":       {"label": "is none of",           "value": "list"},
    "contains":         {"label": "contains",             "value": "text"},
    "not_contains":     {"label": "doesn't contain",      "value": "text"},
    "equals":           {"label": "is equal to",          "value": "text"},
    "eq":               {"label": "is equal to",          "value": "number"},
    "gt":               {"label": "is greater than",      "value": "number"},
    "lt":               {"label": "is less than",         "value": "number"},
    "older_than_days":  {"label": "is more than",         "value": "days"},
    "within_last_days": {"label": "is within the last",   "value": "days"},
    "before":           {"label": "is before",            "value": "date"},
    "after":            {"label": "is after",             "value": "date"},
    "known":            {"label": "is known",             "value": None},
    "unknown":          {"label": "is unknown",           "value": None},
}
OPERATORS_BY_TYPE = {
    "enum":     ["is_any", "is_none_of", "known", "unknown"],
    "owner":    ["is_any", "is_none_of", "known", "unknown"],
    "text":     ["equals", "contains", "not_contains", "known", "unknown"],
    "longtext": ["contains", "not_contains", "known", "unknown"],
    "url":      ["contains", "not_contains", "known", "unknown"],
    "number":   ["eq", "gt", "lt", "known", "unknown"],
    "date":     ["older_than_days", "within_last_days", "before", "after", "known", "unknown"],
}

# Acciones ("Editar registro"). Sólo sobre campos editables desde la página.
ACTIONS = {
    "set":       {"label": "Set",          "needs_value": True},
    "clear":     {"label": "Clear",        "needs_value": False},
    "set_today": {"label": "Set to today", "needs_value": False, "types": ["date"]},
}

# El workflow que vino de HubSpot. Se siembra como primera fila de
# prospect_workflows la primera vez que se crea la tabla.
DEFAULT_WORKFLOWS = [
    {
        "name": "Recycle: In Progress for more than 60 days",
        "description": "Copy of the HubSpot workflow: frees the company so another BDR can take it.",
        "enabled": False,
        "reenroll": True,
        "conditions": {"groups": [{"rules": [
            {"field": "prospecting_start_date", "op": "older_than_days", "value": 60},
            {"field": "prospecting_status", "op": "is_any", "value": [STATUS_IN_PROGRESS]},
        ]}]},
        "actions": [
            {"type": "clear", "field": "prospecting_owner_email"},
            {"type": "clear", "field": "prospecting_owner_apollo"},
            {"type": "clear", "field": "prospecting_start_date"},
            {"type": "set", "field": "prospecting_status", "value": STATUS_RECYCLED},
        ],
    },
]
