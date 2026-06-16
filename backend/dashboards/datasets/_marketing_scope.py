"""Marketing scope = INBOUND only, definido por Booking Source (`conversion_channel`).

Reemplaza la vieja lista negra (`where_come_from NOT IN (outbound, connected inbox,
referral)`), que era incompleta: dejaba colar Import / NA / Other en los números de
marketing. La forma correcta es una lista BLANCA de canales Inbound sobre
`conversion_channel` (Booking Source = por dónde agendó el contacto), que es la
fuente de verdad. Ver memoria project-mql-source-booking-source.

Booking Source → Inbound MQL cuando conversion_channel ∈:
  Website Organic, Social Media, AI, Webinar, Paid Media, Event,
  Email Marketing, Newsletter
(todo lo demás — Outbound, Referral, NA, Other — queda FUERA del scope de marketing.)

OJO con Outbound: en HubSpot su valor interno es `Outbound - Linkedin` (label
`Outbound`). Como acá usamos lista blanca de Inbound, Outbound queda excluido por
no estar en la lista — así que el gotcha de value/label no nos afecta.

Sobre HubSpot, `conversion_channel` se lee con `_first_mapped_value(pm,
"conversion_channel", ...)`, que devuelve el LABEL (convierte value→label). Sobre
Postgres, `account.conversion_channel` guarda el label (el sync ya convierte).
"""
from __future__ import annotations

# Labels de conversion_channel (Booking Source) que cuentan como Inbound.
INBOUND_CHANNELS = (
    "website organic",
    "social media",
    "ai",
    "webinar",
    "paid media",
    "event",
    "email marketing",
    "newsletter",
)

# Labels de origin (MQL Source) que cuentan como Inbound. OJO: NO es igual al de
# Booking Source — origin tiene "Press Action" y NO tiene Email Marketing/Newsletter.
INBOUND_ORIGINS = (
    "website organic",
    "social media",
    "ai",
    "webinar",
    "paid media",
    "event",
    "press action",
)


def is_inbound_channel(value) -> bool:
    """True si un valor de conversion_channel (Booking Source) es Inbound."""
    return str(value or "").strip().lower() in INBOUND_CHANNELS


def is_inbound_origin(value) -> bool:
    """True si un valor de origin / where_come_from (MQL Source) es Inbound."""
    return str(value or "").strip().lower() in INBOUND_ORIGINS


def is_inbound_lead(origin, channel) -> bool:
    """Marketing-scope = Inbound en AMBAS dimensiones: el lead entró por un canal
    inbound (MQL Source) Y agendó por un canal inbound (Booking Source). Saca
    Referral / Import / Outbound / Other por cualquiera de las dos puntas."""
    return is_inbound_origin(origin) and is_inbound_channel(channel)


# Denylist de origin (MQL Source): SOLO saca lo no-inbound conocido y deja pasar el
# resto (incluido '(Sin origen)'). Es la regla "quitar import (+ los de siempre) y
# nada más" — no sobre-filtra como el allowlist/inbound-both, que tira canales
# inbound legítimos cuando el conversion_channel está vacío.
EXCLUDED_ORIGINS = ("outbound", "connected inbox", "referral", "import")


def is_marketing_origin(value) -> bool:
    """True si el origin NO está excluido (denylist + import). Saca Outbound,
    Connected Inbox, Referral e Import; deja el resto (Website Organic, Event, AI,
    Social Media, Paid Media, Webinar, Press Action, '(Sin origen)', etc.)."""
    return str(value or "").strip().lower() not in EXCLUDED_ORIGINS


# Filtro de marketing OFICIAL del equipo (HubSpot), confirmado con sus listas
# (MQL 9/8/13 en Mar/Abr/May 2026): la propiedad de contacto `mql_source` ∈
# {Inbound MQL, Event MQL}. Es propiedad PROPIA, NO derivada del origin. Reemplaza
# is_marketing_origin como filtro de cohorte en las métricas de contacto (MQL/SQL).
MARKETING_MQL_SOURCES = ("inbound mql", "event mql")


def is_marketing_mql_source(value) -> bool:
    """True si el contacto cuenta como marketing: mql_source ∈ {Inbound MQL, Event MQL}."""
    return str(value or "").strip().lower() in MARKETING_MQL_SOURCES


def norm_group_by(filters) -> str:
    """Normaliza el filtro `group_by` del toggle global Origin/Booking del tab de
    marketing → 'origin' | 'booking'. Los datasets SQL lo pasan como %(group_by)s
    para elegir entre agrupar por where_come_from (origin) o conversion_channel
    (booking), y excluir los canales no-marketing de la dimensión que se muestra."""
    gb = str((filters or {}).get("group_by") or (filters or {}).get("groupby") or "origin").strip().lower()
    return "booking" if gb in ("booking", "conversion_channel", "booking_source") else "origin"


def inbound_sql_clause(alias: str = "a", col: str = "conversion_channel") -> str:
    """Predicado SQL que deja solo filas Inbound por conversion_channel.

    Uso dentro de un WHERE:  f"AND {inbound_sql_clause('a')}".
    Los valores son constantes controladas (no input de usuario) → seguro inline.
    """
    values = ", ".join("'%s'" % c for c in INBOUND_CHANNELS)
    return "LOWER(TRIM(COALESCE(%s.%s, ''))) IN (%s)" % (alias, col, values)
