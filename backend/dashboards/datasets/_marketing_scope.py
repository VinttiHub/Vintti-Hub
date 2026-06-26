"""Marketing scope = cohorte de contactos MQL/SQL.

Filtro OFICIAL del equipo (HubSpot): la propiedad de contacto `mql_source` ∈
{Inbound MQL, Event MQL}. Es propiedad PROPIA, NO derivada del origin.
Confirmado con sus listas (MQL 9/8/13 en Mar/Abr/May 2026).

R15: se removieron helpers muertos (INBOUND_CHANNELS/ORIGINS, is_inbound_*,
is_marketing_origin, EXCLUDED_ORIGINS, norm_group_by, inbound_sql_clause) — eran
de la vieja lista blanca/negra por origin, ya reemplazada por mql_source y sin uso.
Ver memoria project-mql-source-booking-source.
"""
from __future__ import annotations

# Filtro de marketing OFICIAL: mql_source ∈ {Inbound MQL, Event MQL}.
MARKETING_MQL_SOURCES = ("inbound mql", "event mql")


def is_marketing_mql_source(value) -> bool:
    """True si el contacto cuenta como marketing: mql_source ∈ {Inbound MQL, Event MQL}."""
    return str(value or "").strip().lower() in MARKETING_MQL_SOURCES
