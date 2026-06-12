"""Marketing · MQLs por origin (en vivo desde HubSpot).

Paralelo a `mkt_sqls_by_origin`, pero los MQLs NO están en Postgres: viven solo en
HubSpot. Este dataset es **calculado** (expone `compute`, no `query`): consulta
HubSpot en vivo, agrupa por origin (`where_come_from`) en el período y devuelve
filas con la MISMA forma que `mkt_sqls_by_origin` (origin, count, share_pct, total,
period_label) para reusar el renderer de ranking, los chips y el toggle de período
sin tocar el front.

- MQL = contacto con `lead_life = "MQL (AE)"` (override por env HUBSPOT_LEAD_LIFE_MQL_VALUE).
- Todos los owners (sin filtro de owner).
- Ventana por `date_of_meeting_scheduled` (override por env HUBSPOT_MQL_DATE_PROPERTY).
- Origin normalizado igual que el sync de SQL (option labels + _normalize_lead_source)
  para que los labels/colores coincidan con el card de SQLs. Excluye 'outbound'
  (espejo de mkt_sqls_by_origin).
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.split("-")
    try:
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def period_bounds(filters: dict) -> tuple[date, date, str]:
    """(ini, fin=corte, label) para el período en curso a la fecha. Espejo de
    mkt_sqls_by_origin.period_bounds."""
    corte = (_parse_date(filters.get("corte")) or _parse_date(filters.get("hasta"))
             or datetime.utcnow().date())
    p = str(filters.get("periodo") or filters.get("period") or "mes").strip().lower()
    if p in ("semana", "week", "w"):
        return corte - timedelta(days=corte.weekday()), corte, "Semana"
    if p in ("q", "trimestre", "quarter"):
        q_month = ((corte.month - 1) // 3) * 3 + 1
        return date(corte.year, q_month, 1), corte, "Trimestre"
    if p in ("anio", "año", "year", "anual", "ytd"):
        return date(corte.year, 1, 1), corte, "Año"
    return date(corte.year, corte.month, 1), corte, "Mes"


# Snapshot mode (verificación): si True, ignora el filtro de fecha Y la exclusión de
# outbound (muestra TODOS los MQLs actuales). False = cohorte por período (createdate)
# excluyendo outbound, igual que el card de SQLs.
SNAPSHOT_MODE = False

# MQL = etapa ALCANZADA MQL (AE) o más allá (agendó reunión), excluye DQL y los
# MQL pre-meeting (BDRs / MKT TOFU-MOFU-BOFU). Mismo criterio que el card de MQLs
# totales (mkt_mqls_business_metric).
_WON = {"active client", "inactive client"}
_REACHED_MQL = _WON | {"sql (ae)", "closed lost", "mql (ae)"}
_IN_VALUES = ["MQL (AE)", "SQL (AE)", "Active Client", "Inactive Client", "Closed Lost"]


def _parse_hs_date_ms(raw) -> date | None:
    """date_of_meeting_scheduled puede venir como epoch-millis (str/int) o ISO."""
    if raw in (None, ""):
        return None
    s = str(raw).strip()
    if s.isdigit():
        try:
            return datetime.fromtimestamp(int(s) / 1000, tz=timezone.utc).date()
        except (ValueError, OverflowError, OSError):
            return None
    return _parse_date(s.split("T")[0])


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    # Imports lazy: evita acoplar el registro de datasets a las rutas/HubSpot.
    from utils.hubspot import HubSpotClient
    from routes.hubspot_routes import (
        _resolve_account_property_maps,
        _first_mapped_value,
        _normalize_lead_source,
    )

    ini, fin, label = period_bounds(filters)

    lead_life_property = (os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life").strip()
    # "MQL aperturado" = agendó reunión → ancla `date_of_meeting_scheduled`.
    # Override por HUBSPOT_MQL_ANCHOR_PROPERTY.
    anchor_property = (os.environ.get("HUBSPOT_MQL_ANCHOR_PROPERTY") or "date_of_meeting_scheduled").strip()

    client = HubSpotClient()
    property_maps = _resolve_account_property_maps(client)
    origin_prop = (property_maps.get("contacts") or {}).get("where_come_from") or "origin"

    # Cohorte por etapa alcanzada: filtramos lead_life ∈ {MQL(AE) o más allá} en el
    # search; la ventana de fechas se aplica en Python a partir del ancla.
    search_filters = [
        {"propertyName": lead_life_property, "operator": "IN", "values": _IN_VALUES},
    ]
    contacts = client.search_contacts(
        search_filters,
        extra_properties=[lead_life_property, anchor_property, origin_prop],
    )

    counts: dict[str, int] = {}
    for c in contacts:
        # Tiene que haber ALCANZADO MQL (AE) o más allá (excluye DQL).
        ll = str((c.get("properties") or {}).get(lead_life_property) or "").strip().lower()
        if ll not in _REACHED_MQL:
            continue
        if not SNAPSHOT_MODE:
            d = _parse_hs_date_ms((c.get("properties") or {}).get(anchor_property))
            if d is None or d < ini or d > fin:
                continue
        origin = _normalize_lead_source(
            _first_mapped_value(property_maps, "where_come_from", contact=c)
        )
        origin = (str(origin or "").strip()) or "(Sin origen)"
        if not SNAPSHOT_MODE and origin.lower() in ("outbound", "connected inbox", "referral"):  # espejo del card de SQLs
            continue
        counts[origin] = counts.get(origin, 0) + 1

    total = sum(counts.values())
    label = "Snapshot (todos)" if SNAPSHOT_MODE else label
    rows = [
        {
            "origin": origin,
            "count": n,
            "share_pct": round(100.0 * n / total, 1) if total else 0.0,
            "total": total,
            "period_label": label,
        }
        for origin, n in counts.items()
    ]
    rows.sort(key=lambda r: (-r["count"], r["origin"]))
    return rows


DATASET = {
    "key": "mkt_mqls_by_origin",
    "label": "Marketing · MQLs por origin (live HubSpot, período)",
    "dimensions": [
        {"key": "origin", "label": "Origin", "type": "string"},
        {"key": "period_label", "label": "Período", "type": "string"},
    ],
    "measures": [
        {"key": "count", "label": "MQLs", "type": "number"},
        {"key": "share_pct", "label": "% del total", "type": "percent"},
        {"key": "total", "label": "Total MQLs", "type": "number"},
    ],
    "default_filters": {"periodo": "mes"},
    "compute": compute,
}
