"""Sales funnel — SQL → NDA Sent → Sourcing → Close Win (Last 30 days).

Hybrid source:
  - SQL:        HubSpot contacts with `lead_life='SQL (AE)'`, owned by
                Mariano or Bahia, `createdate` in 30d window.
  - NDA Sent:   Local `opportunity` table — opps with sales_lead in (M,B)
                that progressed past `Deep Dive`, with `nda_sent_date`
                in 30d window (falls back to old NDA/close dates).
  - Sourcing:   subset above with `nda_signature_or_start_date` populated.
  - Close Win:  opps with `opp_close_date` in 30d AND `opp_stage='Close Win'`.

This way the SQL denominator captures leads that never made it to an opp
in the CRM, so the funnel ratios show genuine dropoff.
"""
from __future__ import annotations

from ._sales_scope import sales_leads as _sales_leads

import logging
import os
import threading
from datetime import date, datetime, timedelta

from ._periods import window_bounds
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


def _fetch_sql_count(win_ini: date, win_fin: date, owner_emails: list[str]) -> int:
    cache_key = f"sales__{'+'.join(owner_emails)}__{win_ini.isoformat()}__{win_fin.isoformat()}"
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
        owner_ids: list[str] = []
        for email in owner_emails:
            try:
                oid = client.get_owner_id_by_email(email)
                if oid:
                    owner_ids.append(str(oid))
            except Exception as exc:  # noqa: BLE001
                log.warning("HubSpot owner lookup failed for %s: %s", email, exc)

        filters = [
            {"propertyName": lead_life_property, "operator": "EQ", "value": lead_life_value},
        ]
        if owner_ids:
            filters.append(
                {"propertyName": "hubspot_owner_id", "operator": "IN", "values": owner_ids}
            )

        contacts = client.search_contacts(filters, extra_properties=[lead_life_property])
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
        or datetime.utcnow().date()
    )
    win_ini, win_fin = window_bounds(filters)
    sales_leads = _sales_leads()

    sql_count = _fetch_sql_count(win_ini, win_fin, sales_leads)

    sql = """
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini, %(win_fin)s::date AS win_fin
        ),
        base AS (
          SELECT
            o.opportunity_id,
            TRIM(o.opp_stage) AS opp_stage,
            COALESCE(
              NULLIF(o.nda_sent_date::text, '')::date,
              NULLIF(o.nda_signature_or_start_date::text, '')::date,
              NULLIF(o.opp_close_date::text, '')::date
            ) AS opp_date,
            NULLIF(o.opp_close_date::text, '')::date AS close_d
          FROM opportunity o
          WHERE TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
            AND o.opp_stage IS NOT NULL
        ),
        scoped AS (
          SELECT b.*
          FROM base b
          CROSS JOIN ventana v
          WHERE b.opp_date BETWEEN v.win_ini AND v.win_fin
        ),
        counts AS (
          SELECT
            COUNT(*) FILTER (
              WHERE opp_stage IN ('NDA Sent','Sourcing','Interviewing','Negotiating',
                                  'Close Win','Closed Lost')
            )::int  AS nda_sent_count,
            COUNT(*) FILTER (
              WHERE opp_stage IN ('Sourcing','Interviewing','Negotiating',
                                  'Close Win','Closed Lost')
            )::int  AS sourcing_count,
            COUNT(*) FILTER (
              WHERE opp_stage = 'Close Win'
                AND close_d IS NOT NULL
                AND close_d BETWEEN (SELECT win_ini FROM ventana) AND (SELECT win_fin FROM ventana)
            )::int  AS close_win_count
          FROM scoped
        )
        SELECT
          (SELECT win_ini FROM ventana) AS ventana_desde,
          (SELECT win_fin FROM ventana) AS ventana_hasta,
          %(sql_count)s::int            AS sql_count,
          nda_sent_count,
          sourcing_count,
          close_win_count,
          ROUND(CASE WHEN %(sql_count)s::int = 0 THEN NULL
                     ELSE 100.0 * nda_sent_count::numeric / %(sql_count)s::int END, 2)::float    AS sql_to_nda_sent_pct,
          ROUND(CASE WHEN nda_sent_count = 0 THEN NULL
                     ELSE 100.0 * sourcing_count::numeric / nda_sent_count END, 2)::float        AS nda_sent_to_sourcing_pct,
          ROUND(CASE WHEN sourcing_count = 0 THEN NULL
                     ELSE 100.0 * close_win_count::numeric / sourcing_count END, 2)::float       AS sourcing_to_close_win_pct,
          ROUND(CASE WHEN %(sql_count)s::int = 0 THEN NULL
                     ELSE 100.0 * close_win_count::numeric / %(sql_count)s::int END, 2)::float   AS sql_to_close_win_pct
        FROM counts;
    """

    return sql, {
        "win_ini": win_ini,
        "win_fin": win_fin,
        "sales_leads": sales_leads,
        "sql_count": sql_count,
    }


DATASET = {
    "key": "sales_funnel_snapshot",
    "label": "Sales funnel — Mariano + Bahia (30d · HubSpot SQL + CRM stages)",
    "dimensions": [
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "sql_count", "label": "SQL (HubSpot)", "type": "number"},
        {"key": "nda_sent_count", "label": "NDA Sent (CRM)", "type": "number"},
        {"key": "sourcing_count", "label": "Sourcing (CRM)", "type": "number"},
        {"key": "close_win_count", "label": "Close Win (CRM)", "type": "number"},
        {"key": "sql_to_nda_sent_pct", "label": "SQL → NDA Sent %", "type": "percent"},
        {"key": "nda_sent_to_sourcing_pct", "label": "NDA Sent → Sourcing %", "type": "percent"},
        {"key": "sourcing_to_close_win_pct", "label": "Sourcing → Close Win %", "type": "percent"},
        {"key": "sql_to_close_win_pct", "label": "SQL → Close Win %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
