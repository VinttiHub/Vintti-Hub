"""Propiedades de NEGOCIO (deal) del CRM de prospección — única definición (2026-11-04).

Los negocios son el pipeline de ventas que hoy vive en HubSpot (*Proceso de
Contratación* y *Vintti AI Pipeline*). De acá salen la ficha y el formulario de la
página, la validación y el mapeo de la importación/sync de HubSpot
(`hubspot_deals.py`). Igual que en contactos: las que no son columna propia viven en
`prospect_deals.props` (JSONB), así que sumar una no requiere ALTER.

`pipeline_key` y `stage_key` NO están en este catálogo: son columnas que se mueven con
el tablero (`deals.move_stage`) y se validan contra `prospect_deal_stages`.

`hubspot`: nombres internos / labels de la propiedad en HubSpot, en orden de
preferencia (los mismos alias que usa el sync de oportunidades,
`utils/hubspot_opportunities.OPPORTUNITY_FIELD_ALIASES`).
"""
from __future__ import annotations

MODELS = ["Staffing", "Recruiting"]
# Los motivos del popup Closed Lost del hub (`#closeLostReason` de opportunities.html):
# mismos textos, así un negocio y su oportunidad hablan igual.
LOST_REASONS = ["Ghosting", "Pricing", "Shopping", "Internal Competition", "External Competition",
                "Timing", "Vintti's Fault", "Other"]

DEAL_GROUPS = ["Negocio", "Calificación (SQL)", "Empresa y contacto", "Origen", "NDA", "Candidate Signed",
               "Closed Won", "Closed Lost"]

# Fallback de las listas cuando todavía no se leyeron de HubSpot (las de verdad las guarda
# deals.seed_stages_from_hubspot() en prospect_deal_field_options, desde la definición de
# cada propiedad de deal en HubSpot: así los desplegables son iguales a los de HubSpot).
from prospecting.contact_fields import CONTACT_FIELDS_BY_KEY as _CF, LEAD_LIFE as _LEAD_LIFE  # noqa: E402

_POSITIONS = _CF["position"]["options"]
_COMPANY_TYPES = _CF["company_type"]["options"]
_INDUSTRIES = _CF["industria"]["options"]
_ORIGINS = _CF["origin"]["options"]
_CHANNELS = _CF["conversion_channel"]["options"]
_OUTSOURCED = _CF["outsourced_before"]["options"]
# Opciones de «MQL (AE) Lost Reason (Deal)» en HubSpot (deal_lost_reason, 2026-11-06).
MQL_LOST_REASONS = ["Ghosting", "Internal Competition", "Shopping", "Pricing", "Blacklist", "Timing",
                    "Vintti's Fault", "Other", "External Competition", "Vendor", "Challenge", "Role Fit",
                    "Not decision maker"]
_SIZES = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5001-10000", "10001+"]


def _f(key, label, type_, group, options=None, storage="props", hubspot=None, description=None):
    d = {"key": key, "label": label, "type": type_, "group": group, "storage": storage,
         "hubspot": hubspot or []}
    if options is not None:
        d["options"] = options
    if description:
        d["description"] = description
    return d


G = DEAL_GROUPS
DEAL_FIELDS = [
    # ---- Negocio ------------------------------------------------------------ #
    _f("name", "Nombre del negocio", "text", G[0], storage="col", hubspot=["dealname"]),
    _f("owner_email", "Propietario del negocio", "user", G[0], storage="col", hubspot=["hubspot_owner_id"]),
    _f("amount", "Cantidad (US$)", "number", G[0], storage="col", hubspot=["amount"]),
    _f("close_date", "Fecha de cierre", "date", G[0], storage="col", hubspot=["closedate"]),
    _f("description", "Descripción", "longtext", G[0], hubspot=["description"]),
    # ---- Calificación (lo que HubSpot pide al pasar a SQL) ------------------ #
    _f("role_to_hire", "Role to hire", "text", G[1],
       hubspot=["role_to_hire", "Role to hire", "Role To Hire (Deal)"],
       description="Pasa a ser el puesto de la oportunidad del hub en Deep Dive."),
    _f("model", "Model", "enum", G[1], MODELS, hubspot=["model", "Model"]),
    _f("intro_call_recording", "Intro Call Recording", "text", G[1],
       hubspot=["intro_call_recording", "Intro Call Recording"]),
    _f("sql_date", "SQL Date", "date", G[1], hubspot=["sql_date_deal", "SQL Date (Deal)"],
       description="Se sella en la cuenta del CRM (account.sql_date) al pasar a SQL."),
    # Sin opciones propias: salen de HubSpot (si no hay, se carga como texto).
    _f("pain_point", "Pain Point", "enum", G[1], [], hubspot=["pain_point_deal", "Pain Point - Deal", "Pain Point (Deal)"]),
    # ---- Empresa y contacto (copias «(Deal)» de HubSpot; se prellenan) ------ #
    _f("company_name_deal", "Company Name", "text", G[2], hubspot=["company_name_deal", "Company Name (Deal)", "Company Name"]),
    _f("state_region", "State/Region", "text", G[2], hubspot=["state_region_deal", "State/Region (Deal)", "State/Region"]),
    _f("industry", "Industria", "enum", G[2], _INDUSTRIES, hubspot=["industria_deal", "Industria (Deal)", "Industria"]),
    _f("company_type", "Company Type", "enum", G[2], _COMPANY_TYPES,
       hubspot=["company_type_deal", "Company Type (Deal)", "Company Type"]),
    _f("headcount", "Headcount", "enum", G[2], _SIZES, hubspot=["headcount_deal", "Headcount (Deal)", "Headcount"]),
    _f("outsourced_before", "Outsourced before", "enum", G[2], _OUTSOURCED,
       hubspot=["outsourced_before_deal", "Outsourced before (Deal)", "Outsourced before"]),
    _f("position", "Position", "enum", G[2], _POSITIONS, hubspot=["position_deal", "Position (Deal)", "Position"]),
    _f("linkedin_company", "LinkedIn URL - Company", "url", G[2],
       hubspot=["linkedin_url___company_deal", "LinkedIn URL - Company (Deal)", "LinkedIn URL - Company"]),
    _f("linkedin_contact", "LinkedIn URL (contacto)", "url", G[2],
       hubspot=["linkedin_url_deal", "LinkedIn URL (Deal)"]),
    _f("website", "Website URL", "url", G[2], hubspot=["website_url_deal", "Website URL (Deal)", "Website URL"]),
    # ---- Origen ------------------------------------------------------------- #
    _f("conversion_channel", "Conversion Channel", "enum", G[3], _CHANNELS,
       hubspot=["conversion_channel_deal", "Conversion Channel (Deal)", "Conversion Channel"]),
    _f("origin", "Origin", "enum", G[3], _ORIGINS, hubspot=["origin_deal", "Origin (Deal)", "Origin"]),
    _f("origin_detail", "Origin detail", "enum", G[3], [],
       hubspot=["origin_detail_deal", "Origin detail (Deal)", "Origin detail"]),
    # ---- NDA (lo que HubSpot pide al pasar a NDA Sent / NDA Signed) --------- #
    _f("deep_dive_recording", "Deep Dive Recording", "text", G[4],
       hubspot=["deep_dive_recording", "Deep Dive Recording"]),
    _f("min_budget", "Min Client Budget", "number", G[4], hubspot=["min_client_budget", "Min Client Budget"]),
    _f("max_budget", "Max Client Budget", "number", G[4], hubspot=["max_client_budget", "Max Client Budget"]),
    _f("min_salary", "Min Candidate Salary", "number", G[4], hubspot=["min_candidate_salary", "Min Candidate Salary"]),
    _f("max_salary", "Max Candidate Salary", "number", G[4], hubspot=["max_candidate_salary", "Max Candidate Salary"]),
    _f("years_experience", "Candidate's Years of Experience", "number", G[4],
       hubspot=["candidates_years_of_experience", "Candidate's Years of Experience"]),
    _f("expected_fee", "Expected Fee", "number", G[4], hubspot=["expected_fee", "Expected Fee"]),
    _f("expected_revenue", "Expected Revenue", "number", G[4], hubspot=["expected_revenue", "Expected Revenue"]),
    _f("expected_setup_fee", "Expected Set Up Fee", "number", G[4],
       hubspot=["expected_set_up_fee", "Expected Set Up Fee"]),
    _f("nda_sent_date", "NDA Sent Date", "date", G[4], hubspot=["nda_sent_date_deal", "NDA Sent Date (Deal)"]),
    _f("nda_signed_date", "NDA Signed Date", "date", G[4], hubspot=["nda_signed_date_deal", "NDA Signed Date (Deal)"]),
    # ---- Candidate Signed / Closed Won / Closed Lost -------------------------- #
    # Estos NO los carga nadie en el negocio: nacen en la oportunidad del hub (solapa Hire,
    # ficha del candidato, popups de Close Win / Closed Lost), los mismos valores que el hub
    # le empuja a HubSpot (utils/hubspot_push_values.hire_values_for_opportunity) y
    # deals.reflect() los copia con la misma regla. Por eso son texto: van tal cual el push.
    _f("candidate_signed_date", "Candidate Signed Date", "date", G[5],
       hubspot=["candidate_signed_date_deal", "Candidate Signed Date (Deal)"]),
    _f("final_salary", "Candidate's Final Salary", "number", G[5], hubspot=["candidates_final_salary", "Candidate's Final Salary"]),
    _f("final_fee", "Final Fee", "number", G[5], hubspot=["final_fee", "Final Fee"]),
    _f("setup_fee", "Set Up Fee", "number", G[5], hubspot=["set_up_fee", "Set Up Fee"]),
    _f("role_hired", "Role Hired", "text", G[5], hubspot=["role_hired_deal", "Role Hired"]),
    _f("price_type", "Price Type", "text", G[5], hubspot=["price_type", "Price Type"]),
    _f("computer", "Computer", "text", G[5], hubspot=["computer", "Computer"]),
    _f("candidate_start_date", "Candidate's Start Date", "date", G[5], hubspot=["candidates_start_date", "Candidate's Start Date"]),
    _f("candidate_end_date", "Candidate's End Date", "date", G[5], hubspot=["candidates_end_date", "Candidate's End Date"]),
    _f("candidate_address", "Candidate's Address", "text", G[5], hubspot=["candidates_address", "Candidate's Address"]),
    _f("candidate_dni", "Candidate's DNI", "text", G[5], hubspot=["dni", "Candidate's DNI"]),
    _f("candidate_location", "Candidate's Location", "text", G[5], hubspot=["candidates_location", "Candidate's Location"]),
    _f("mkt_collab", "MKT Collab", "text", G[6], hubspot=["mkt_collab", "MKT Collab"]),
    _f("closed_win_date", "Closed Win Date", "date", G[6], hubspot=["closed_win_date_deal", "Closed Win Date (Deal)"]),
    _f("lost_reason", "Lost Reason", "enum", G[7], LOST_REASONS, hubspot=["sql_ae_lost_reason"]),
    _f("lost_reason_detail", "Lost Reason Detail", "longtext", G[7], hubspot=["lost_reason_detail_deal"]),
    _f("closed_lost_date", "Closed Lost Date", "date", G[7], hubspot=["closed_lost_date_deal", "Closed Lost Date (Deal)"]),
    # ---- 2026-11-06: las que copiaban los workflows «negocio ↔ contacto» de HubSpot ----- #
    # (prop_sync.py las mantiene iguales; las del Hub se llenan solas, ver deals.py).
    _f("mql_lost_reason", "MQL (AE) Lost Reason", "enum", G[7], MQL_LOST_REASONS,
       hubspot=["deal_lost_reason", "MQL (AE) Lost Reason"],
       description="Se pide en Closed Lost si el negocio se perdió antes de llegar a SQL."),
    _f("lead_life_deal", "Lead Life (Deal)", "enum", G[0], _LEAD_LIFE, hubspot=["lead_life_deal", "Lead Life (Deal)"],
       description="Se pone sola según la etapa (deals.LEAD_LIFE_BY_STAGE)."),
    _f("first_deep_dive_date", "First Deep Dive Date (Deal)", "datetime", G[4],
       hubspot=["deep_dive_date", "First Deep Dive Date (Deal)"],
       description="La primera vez que el negocio entró a Deep Dive."),
    _f("follow_up_date", "Follow Up Date", "date", G[2], hubspot=["follow_up_date", "Follow Up Date"]),
    _f("credit_loop", "Credit Loop?", "bool", G[6], hubspot=["credit_loop", "Credit Loop?"]),
    _f("credits_won", "Credits Won", "number", G[6], hubspot=["credits_won", "Credits Won"]),
    _f("credits_expiring_date", "Credits Expiring Date", "date", G[6],
       hubspot=["credits_expiring_date", "Credits Expiring Date"]),
]
DEAL_FIELDS_BY_KEY = {f["key"]: f for f in DEAL_FIELDS}
# Opciones que existen sólo en el Hub: se suman a las de HubSpot (deals.field_defs), que si
# no las reemplazarían. Las mismas que se agregaron al contacto (pedido de la owner, 2026-11-06).
HUB_EXTRA_OPTIONS = {
    "conversion_channel": ["Outbound - Instagram", "Outbound - TikTok", "Outbound - Facebook"],
}
DEAL_COLUMNS = [f["key"] for f in DEAL_FIELDS if f["storage"] == "col"]

# Orden del pipeline (ranking para "sólo hacia adelante"). Las etapas que HubSpot tenga
# además de éstas (p. ej. DQL) entran al tablero como `hs_<id>`, sin rank y sin efectos.
STAGE_ORDER = ["intro_call", "sql", "deep_dive", "nda_sent", "nda_signed", "signed", "closed_won"]
STAGE_RANK = {k: i for i, k in enumerate(STAGE_ORDER)}
CLOSED_LOST = "closed_lost"

# «Propiedades dependientes»: lo que HubSpot pide al pasar a cada etapa, en su orden.
# (campo, obligatorio). El popup muestra TODOS (prellenados), como HubSpot; sólo los
# obligatorios frenan. SQL y NDA Sent salen de las capturas de la owner (2026-11-04); las
# demás etapas, de lo que el sync de oportunidades ya sabía que HubSpot exige.
STAGE_FORMS = {
    "sql": [
        ("sql_date", True), ("model", True), ("pain_point", True), ("role_to_hire", True),
        ("state_region", True), ("industry", True), ("company_name_deal", True), ("company_type", True),
        ("conversion_channel", True), ("outsourced_before", True), ("position", True), ("headcount", True),
        ("linkedin_company", True), ("linkedin_contact", True), ("origin", False), ("origin_detail", False),
        ("intro_call_recording", False), ("website", True),
    ],
    # De las capturas de la owner (2026-11-04), en el orden de HubSpot.
    "nda_sent": [
        ("nda_sent_date", True), ("min_budget", True), ("max_budget", True), ("min_salary", True),
        ("max_salary", True), ("expected_fee", False), ("expected_setup_fee", False),
        ("years_experience", True), ("deep_dive_recording", False), ("expected_revenue", True),
    ],
    "nda_signed": [("nda_signed_date", True)],
    # Lo que HubSpot exige al pasar a Closed Lost (lo empuja hoy el hub desde Opportunities:
    # utils/hubspot_push.build_closed_lost_payload). En el tablero sólo se usa para un negocio
    # SIN oportunidad; con oportunidad se cierra en Opportunities.
    "closed_lost": [("closed_lost_date", True), ("lost_reason", True), ("lost_reason_detail", False)],
}

# Etapas que, si el negocio ya tiene oportunidad del hub, se mueven SOLO desde Opportunities:
# ahí se cargan el hire, el MKT Collab y el motivo (con sus efectos: hire activo, créditos,
# cliente inactivo, push a HubSpot), y deals.reflect() trae etapa y valores al negocio.
OPPORTUNITY_OWNED_STAGES = ("signed", "closed_won", "closed_lost")
# Sin esto no se puede crear la oportunidad: se exige también si se salta SQL.
MIN_FOR_OPPORTUNITY = ["role_to_hire", "model"]

# Valor de la empresa / contacto asociado con el que se PRELLENA el popup (en orden de
# preferencia) y que se RELLENA de vuelta si estaba vacío (decisión de la owner).
PREFILL = {
    # Ojo: la clave no es `company_name`, que en las lecturas es la empresa asociada del Hub.
    "company_name_deal": [("company", "name"), ("contact", "company_name")],
    "state_region": [("contact", "state_region"), ("company", "state")],
    "industry": [("contact", "industria")],
    "company_type": [("contact", "company_type")],
    "headcount": [("company", "size"), ("contact", "company_size")],
    "outsourced_before": [("contact", "outsourced_before")],
    "position": [("contact", "position")],
    "linkedin_company": [("company", "linkedin_url"), ("contact", "company_linkedin_url")],
    "linkedin_contact": [("contact", "linkedin_url")],
    "website": [("company", "website")],
    "conversion_channel": [("contact", "conversion_channel")],
    "origin": [("contact", "origin")],
    "origin_detail": [("contact", "origin_detail")],
}


# Etapas por defecto (antes de leer los pipelines de HubSpot, o en un entorno sin token).
# La importación / el sync las reemplazan por las de HubSpot (labels, orden y %).
DEFAULT_PIPELINES = [
    ("hiring", "Proceso De Contratación"),
    ("vintti_ai", "Vintti AI Pipeline"),
]
DEFAULT_STAGES = [
    ("intro_call", "Intro Call", 0.3, False, False),
    ("sql", "SQL", 0.2, False, False),
    ("deep_dive", "Deep Dive Call", 0.4, False, False),
    ("nda_sent", "NDA Sent", 0.2, False, False),
    ("nda_signed", "NDA Signed", 0.6, False, False),
    ("signed", "Candidate Signed", 0.9, False, False),
    ("closed_won", "Closed Won", 1.0, True, True),
    ("closed_lost", "Closed Lost", 0.0, True, False),
]


def _form_rows(stage_key: str, before_sql: bool = False) -> list[tuple]:
    rows = STAGE_FORMS.get(stage_key, [])
    # Perdido antes de SQL (en Intro Call): el motivo es el de MQL, como en HubSpot.
    if stage_key == "closed_lost" and before_sql:
        rows = [("mql_lost_reason", r) if k == "lost_reason" else (k, r) for k, r in rows]
    return rows


def form_for(stage_key: str, before_sql: bool = False) -> list[dict]:
    return [{"key": k, "required": r} for k, r in _form_rows(stage_key, before_sql)]


def required_for(stage_key: str, from_stage: str | None = None, before_sql: bool = False) -> list[str]:
    """Campos obligatorios para llegar a `stage_key`."""
    out = [k for k, r in _form_rows(stage_key, before_sql) if r]
    rank = STAGE_RANK.get(stage_key)
    if rank is not None and rank >= STAGE_RANK["deep_dive"]:
        out += [k for k in MIN_FOR_OPPORTUNITY if k not in out]
    return out
