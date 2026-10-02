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
