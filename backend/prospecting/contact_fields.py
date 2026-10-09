"""Propiedades de CONTACTO del CRM de prospección — única definición.

Sale de la planilla "Propiedades HubSpot Contactos" que pasó la owner (2026-10-07).
De acá salen la ficha y el formulario de la página, la validación y el editor de
workflows (vía GET /prospecting/options). Para sumar una propiedad alcanza con
una línea acá: las que no son columna propia viven en `prospect_contacts.props`
(JSONB), así que no hace falta ALTER.

Quedan afuera, a propósito, las que la planilla marca DESACTIVADO o "ya no se
usa": Painpoint (Intro Call), Pain Point y Headcount.

`storage`: "col" = columna de prospect_contacts (las que se filtran / ordenan
seguido); por defecto, "props".

Tipos (además de los de empresas): datetime, bool (casilla única), multi
(casillas múltiples), email, phone, user (cualquier usuario activo del Hub; el
`owner` es sólo BDRs).
"""
from __future__ import annotations

LEAD_LIFE = [
    "MQL (MKT) - TOFU",
    "MQL (MKT) - MOFU",
    "MQL (MKT) - BOFU",
    "MQL (BDRs)",
    "MQL (AE)",
    "SQL (AE)",
    # No estaba en la planilla, pero lo usa el workflow 5 de HubSpot (2026-10-09).
    "Closed Lost",
    "DQL",
    "Active Client",
    "Archived Lead",
    "Inactive Client",
]
_ORIGINS = ["Outbound", "Website Organic", "Referral", "Social Media", "AI", "Webinar",
            "Paid Media", "Event", "Connected Inbox", "NA", "Import", "Press Action"]
_FOLLOW_UP = ["Bad Timing", "No Response", "Explicitly Not Interested", "Not a Fit"]
_INDUSTRIES = [
    "Technology", "Accounting", "Law", "Automotor", "Common Goods", "Music", "Furniture",
    "Energy", "HR", "Retail", "Agriculture", "Marketing", "Healthcare", "Construction",
    "Finance", "Ecommerce", "Consulting", "Manufacture", "Medicine", "Entretainment",
    "Pharmaceuticals", "Animation", "Beauty", "Education", "Transportation", "Art",
    "Insurance", "Fashion", "Design", "Consumer Services", "Food", "Pets", "Travel",
    "Sports", "Security", "Real Estate",
]

# Orden de las secciones de la ficha.
CONTACT_GROUPS = [
    "Contacto",
    "Calificación",
    "Empresa (según el contacto)",
    "Seguimiento BDR",
    "Llamadas",
    "Origen",
    "Funnel",
    "Eventos",
    "Atribución / UTMs",
    "Email marketing",
    "Referidos y créditos",
]


def _f(key, label, type_, group, options=None, description=None, storage="props"):
    d = {"key": key, "label": label, "type": type_, "group": group, "storage": storage}
    if options is not None:
        d["options"] = options
    if description:
        d["description"] = description
    return d


G = CONTACT_GROUPS
CONTACT_FIELDS = [
    # ---- Contacto ---------------------------------------------------------- #
    _f("email", "Email", "email", G[0], storage="col"),
    _f("first_name", "First Name", "text", G[0], storage="col"),
    _f("last_name", "Last Name", "text", G[0], storage="col"),
    _f("position", "Position", "enum", G[0], [
        "Founder/Co-Founder", "President", "Vice President", "CEO", "COO", "CFO/Finance Manager",
        "CTO", "Partner", "General Manager", "Hiring Manager", "Talent Acquisition/Recruiter",
        "Student/Freelancer", "Unemployed", "Other", "Unknown"], "La posición por categorías."),
    _f("in_current_position", "In current position", "text", G[0],
       description="La posición específica: exactamente el rol que tiene."),
    _f("linkedin_url", "URL de LinkedIn", "url", G[0]),
    _f("phone_number", "Phone Number", "phone", G[0]),
    _f("corporate_phone", "Corporate Phone", "phone", G[0]),
    _f("owner_email", "Contact Owner", "owner", G[0], storage="col",
       description="La persona a cargo del contacto (follow up u otra razón)."),
    _f("state_region", "State/Region", "text", G[0]),
    # ---- Calificación ------------------------------------------------------ #
    _f("lead_life", "Lead Life", "enum", G[1], LEAD_LIFE, storage="col",
       description="Estado de calificación del contacto en el funnel de marketing y ventas."),
    _f("meeting_datetime", "Meeting Date & Time", "datetime", G[1],
       description="Fecha y hora de la reunión agendada."),
    _f("combined_lead_scoring", "Combined Lead Scoring", "number", G[1]),
    _f("intent", "Intent", "text", G[1], description="(Antes: Contact Reason)"),
    _f("role_to_hire", "Role to Hire", "longtext", G[1], description="Qué rol busca contratar este contacto."),
    _f("what_looking_for", "What are you looking for?", "text", G[1],
       description="Sólo leads de Vintti AI, al agendar la Intro Call."),
    _f("hiring_situation", "What best describes your current hiring situation?", "enum", G[1], [
        "Actively hiring right now", "Planning to hire in the next 3 - 6 months",
        "Exploring ways to scale my team", "Not hiring right now", "Looking for a job", "Other"]),
    _f("model", "Model", "enum", G[1], ["Staffing", "Recruiting"], "Sólo para active clients."),
    # ---- Empresa (según el contacto) -------------------------------------- #
    _f("company_name", "Company name", "text", G[2]),
    _f("company_type", "Company Type", "enum", G[2], ["Firm", "SMB", "Startup", "NA"]),
    _f("industria", "Industria", "enum", G[2], _INDUSTRIES),
    _f("exact_company_size", "Exact Company Size", "number", G[2]),
    _f("company_size", "Company size", "enum", G[2],
       ["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5001-10000", "10001+"],
       "Rango de tamaño de la empresa según LinkedIn."),
    _f("outsourced_before", "Outsourced before", "multi", G[2],
       ["NA", "No", "Philippines", "India", "LATAM", "South Africa", "Yes", "No Info"]),
    _f("company_linkedin_url", "Linkedin URL - Company", "url", G[2]),
    # ---- Seguimiento BDR --------------------------------------------------- #
    _f("bdr_follow_up_result", "BDR Follow Up Result", "enum", G[3], _FOLLOW_UP,
       "Resultado del último follow up del BDR."),
    _f("follow_up_task_owner", "Follow Up Task Owner", "owner", G[3]),
    _f("follow_up_date", "Follow Up Date", "date", G[3], description="Fecha en la que el BDR tiene que hacer follow up."),
    _f("bdr_notes", "BDR notes", "longtext", G[3]),
    _f("bdr_insight", "BDR Insight", "longtext", G[3], description="Qué pasó con el lead al hacerle follow up."),
    _f("contact_insight", "Contact Insight", "longtext", G[3], description="Por dónde entró el contacto, para el follow up."),
    # ---- Llamadas ---------------------------------------------------------- #
    _f("total_calls", "Total Calls", "number", G[4]),
    _f("last_call_date", "Last Call Date", "date", G[4]),
    _f("cold_call_result", "Cold Call Result", "enum", G[4],
       ["Call Scheduled", "No Response", "Explicitly Not Interested", "Not a Fit", "Bad Timing"]),
    # ---- Origen ------------------------------------------------------------ #
    _f("origin", "Origin", "enum", G[5], _ORIGINS, "Origen del lead."),
    _f("origin_detail", "Origin detail", "text", G[5],
       description="Punto exacto de entrada (Meta Ads, Google Ads, Lead Magnet, Chatbot, Live Chat…)."),
    _f("conversion_channel", "Conversion Channel", "enum", G[5],
       _ORIGINS + ["Email Marketing", "Other", "Newsletter"], "Canal por el que agendó la reunión."),
    _f("mql_source", "MQL Source", "enum", G[5],
       ["Inbound MQL", "Outbound MQL", "Import", "Event MQL", "Referral MQL", "NA"]),
    _f("booking_source", "Booking Source", "enum", G[5],
       ["Inbound MQL", "Outbound MQL", "Referral MQL", "Event MQL", "NA"]),
    _f("scheduled_by", "Scheduled By", "user", G[5], description="Quién del equipo agendó la reunión."),
    # ---- Funnel ------------------------------------------------------------ #
    _f("first_intro_call_completed", "First Intro Call Completed", "bool", G[6]),
    _f("deep_dive_completed", "Deep Dive Completed", "bool", G[6]),
    _f("nda_signed", "NDA Signed", "bool", G[6]),
    _f("first_deep_dive_date", "First Deep Dive Date", "datetime", G[6]),
    _f("last_deep_dive_date", "Last Deep Dive Date", "datetime", G[6]),
    _f("sql_date", "SQL Date", "date", G[6]),
    _f("first_closed_win_date", "First Closed Win Date", "date", G[6]),
    _f("first_closed_lost_date", "First Closed Lost Date", "date", G[6]),
    _f("last_closed_win_date", "Last Closed Win Date", "date", G[6]),
    _f("last_closed_lost_date", "Last Closed Lost Date", "date", G[6]),
    _f("lost_reason_detail", "Lost Reason Detail", "longtext", G[6]),
    # Tampoco estaba en la planilla; la usa el workflow 5 de HubSpot. Texto libre
    # hasta que pasen sus opciones (en HubSpot es probablemente una lista).
    _f("mql_ae_lost_reason", "MQL (AE) Lost Reason", "text", G[6],
       description="Por qué se perdió el lead después de la reunión con el AE."),
    # ---- Eventos ----------------------------------------------------------- #
    _f("event_name", "Event Name", "enum", G[7],
       ["F&M - Hal Smith", "F&M - Mason Brady", "F&M - Rubik", "F&M - Founder's Network"]),
    _f("event_attendance", "Event Attendance", "enum", G[7],
       ["Attended - Intent", "Attended - No Intent", "No Show"]),
    _f("event_follow_up_result", "Event Follow Up Result", "enum", G[7],
       ["Bad Timing", "No Response", "Explicitly Not Interested", "Interested"]),
    # ---- Atribución / UTMs ------------------------------------------------- #
    *[_f(f"utm_{k}", f"UTM {k.title()}", "text", G[8]) for k in ("source", "medium", "campaign", "term", "content")],
    *[_f(f"utm_{k}_origin", f"UTM {k.title()} Origin", "text", G[8]) for k in ("campaign", "medium", "content", "term")],
    # ---- Email marketing --------------------------------------------------- #
    _f("newsletter_subscription", "Newsletter Subscription", "enum", G[9], ["Yes", "No"]),
    _f("talent_drop_subscription", "Talent Drop Subscription", "enum", G[9], ["Admitted", "Denied"]),
    _f("marketing_contact_status", "Marketing contact status", "enum", G[9],
       ["Marketing contact", "Non-marketing contact"]),
    *[_f(f"new_tofu_{i}_sent", f"new_tofu_{i}_sent", "bool", G[9]) for i in range(1, 5)],
    *[_f(f"new_mofu_{i}_sent", f"new_mofu_{i}_sent", "bool", G[9]) for i in range(1, 6)],
    *[_f(f"new_bofu_{i}_sent", f"new_bofu_{i}_sent", "bool", G[9]) for i in range(1, 6)],
    # ---- Referidos y créditos ---------------------------------------------- #
    _f("referred_by", "Referred By", "text", G[10]),
    _f("referred_by_company", "Referred By (Company)", "text", G[10]),
    _f("referrer_email", "Referrer Email", "email", G[10]),
    _f("credits_won", "Credits Won", "number", G[10]),
    _f("credits_expiring_date", "Credits Expiring Date", "date", G[10]),
    # Casillas múltiples en HubSpot, pero la planilla no trae sus opciones: texto
    # libre hasta que las pasen.
    _f("mkt_collab", "MKT Collab", "longtext", G[10]),
]
CONTACT_FIELDS_BY_KEY = {f["key"]: f for f in CONTACT_FIELDS}
CONTACT_COLUMNS = [f["key"] for f in CONTACT_FIELDS if f["storage"] == "col"]

# Obligatorios del formulario que se abre al pasar una empresa a Qualified / SQL
# (decisión de la owner, 2026-10-07). Una empresa en esos status sin al menos un
# contacto con todos estos campos queda marcada "Contacto incompleto".
REQUIRED_ON_QUALIFIED = ["first_name", "last_name", "email", "position", "lead_life", "meeting_datetime"]
