"""SQL → NDA signed conversion (Last 30d, Staffing).

Hybrid source:
  - SQL (denominator):  HubSpot contacts with `lead_life = "SQL (AE)"` whose
                        `createdate` falls in the 30d window. This captures
                        the REAL top-of-funnel — leads that never made it
                        to an opp in the CRM.
  - NDA (numerator):    Local `opportunity` table — opps with
                        `opp_model='Staffing'` AND `nda_signature_or_start_date`
                        in the same 30d window.

The HubSpot count is computed in Python (cached 5 min) before SQL runs, then
passed in as a literal param.
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
_CACHE_TTL_SECONDS = 300


def _parse_date(value):
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
    cache_key = f"global__{win_ini.isoformat()}__{win_fin.isoformat()}"
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
            log.warning("HubSpotClient unavailable; SQL count = 0")
            with _CACHE_LOCK:
                _CACHE[cache_key] = (now, 0)
            return 0

    lead_life_property = (os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life").strip()
    lead_life_value = (os.environ.get("HUBSPOT_LEAD_LIFE_SQL_VALUE") or "SQL (AE)").strip()

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
    except Exception as exc:  # noqa: BLE001
        log.warning("HubSpot SQL fetch failed: %s", exc)

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
    win_ini = corte - timedelta(days=29)
    win_fin = corte

    sql_count = _fetch_sql_count(win_ini, win_fin)

    sql = """
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini, %(win_fin)s::date AS win_fin
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
    "label": "SQL → NDA signed (Staffing, 30d) — HubSpot SQL + CRM NDA",
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
