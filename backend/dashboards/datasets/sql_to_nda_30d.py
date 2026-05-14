"""SQL → NDA signed conversion (Last 30d, Staffing).

This dataset combines two sources:
  - Numerator:    count of opportunities with `nda_signature_or_start_date`
                  in the 30d window where `opp_model = 'Staffing'`.
                  (Read from the local Postgres `opportunity` table.)
  - Denominator:  count of HubSpot contacts whose `lead_life = "SQL (AE)"`
                  and `createdate` falls in the 30d window.
                  (Read live from the HubSpot API via `HubSpotClient`,
                  cached in-memory for 5 min — same pattern as
                  `sql_leads_windows.py`.)

The dashboard runtime calls `query(filters)` expecting `(sql, params)`. The
HubSpot count is computed in Python before the SQL is returned, then baked
into the SQL as a literal parameter so the single round-trip still produces
all three measures (sql_count, nda_count, sql_to_nda_pct).
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, int]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SECONDS = 300  # 5 min


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


def _parse_hubspot_date(raw: Any) -> date | None:
    if raw in (None, ""):
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _fetch_sql_count(win_ini: date, win_fin: date) -> int:
    """Count HubSpot contacts with lead_life='SQL (AE)' and createdate in window.

    Cached for 5 min keyed by (win_ini, win_fin).
    """
    cache_key = f"{win_ini.isoformat()}__{win_fin.isoformat()}"
    now = datetime.utcnow().timestamp()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

    try:
        from backend.utils.hubspot import HubSpotClient  # type: ignore
    except ImportError:
        try:
            from utils.hubspot import HubSpotClient  # type: ignore
        except ImportError:
            log.warning("HubSpotClient unavailable; SQL→NDA will use sql_count=0")
            with _CACHE_LOCK:
                _CACHE[cache_key] = (now, 0)
            return 0

    lead_life_property = (
        os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life"
    ).strip()
    lead_life_value = (
        os.environ.get("HUBSPOT_LEAD_LIFE_SQL_VALUE") or "SQL (AE)"
    ).strip()

    count = 0
    try:
        client = HubSpotClient()
        contacts = client.search_contacts(
            [{"propertyName": lead_life_property, "operator": "EQ", "value": lead_life_value}],
            extra_properties=[lead_life_property],
        )
        for contact in contacts or []:
            props = (contact or {}).get("properties", {}) or {}
            d = _parse_hubspot_date(props.get("createdate"))
            if d is not None and win_ini <= d <= win_fin:
                count += 1
    except Exception as exc:  # noqa: BLE001 — keep the dashboard alive on outages
        log.warning("HubSpot SQL count fetch failed: %s", exc)

    with _CACHE_LOCK:
        _CACHE[cache_key] = (now, count)
    return count


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or datetime.utcnow().date()
    )
    win_ini = corte - timedelta(days=29)  # 30 days inclusive — matches all *_30d datasets
    win_fin = corte

    sql_count = _fetch_sql_count(win_ini, win_fin)

    sql = """
        WITH ventana AS (
          SELECT
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin
        ),
        ndas_signed AS (
          SELECT COUNT(*)::int AS nda_count
          FROM opportunity o
          CROSS JOIN ventana v
          WHERE o.opp_model = 'Staffing'
            AND NULLIF(o.nda_signature_or_start_date::text, '') IS NOT NULL
            AND NULLIF(o.nda_signature_or_start_date::text, '')::date
                BETWEEN v.win_ini AND v.win_fin
        )
        SELECT
          (SELECT win_ini FROM ventana)            AS ventana_desde,
          (SELECT win_fin FROM ventana)            AS ventana_hasta,
          %(sql_count)s::int                       AS sql_count,
          n.nda_count,
          ROUND(
            CASE
              WHEN %(sql_count)s::int = 0 THEN NULL
              ELSE 100.0 * n.nda_count::numeric / %(sql_count)s::int
            END, 2
          )::float                                 AS sql_to_nda_pct
        FROM ndas_signed n;
    """

    return sql, {
        "win_ini": win_ini,
        "win_fin": win_fin,
        "sql_count": sql_count,
    }


DATASET = {
    "key": "sql_to_nda_30d",
    "label": "SQL → NDA signed (Staffing, 30d)",
    "dimensions": [
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "sql_count", "label": "SQL leads (HubSpot)", "type": "number"},
        {"key": "nda_count", "label": "NDAs signed Staffing", "type": "number"},
        {"key": "sql_to_nda_pct", "label": "% SQL → NDA signed", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
