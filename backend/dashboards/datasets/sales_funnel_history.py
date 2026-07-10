"""Sales funnel — monthly history of conversion rates (Mariano + Bahia).

Hybrid source per month:
  - SQL:        HubSpot contacts with `lead_life='SQL (AE)'`, owned by
                Mariano or Bahia, bucketed by `createdate` month.
  - NDA Sent / Sourcing / Close Win: local `opportunity` table per month.

Returns 4 conversion %s per month so each chart can render its own line.
"""
from __future__ import annotations

from ._sales_scope import sales_leads as _sales_leads

import logging
import os
import threading
from datetime import date, datetime
from typing import Any

log = logging.getLogger(__name__)


_CACHE: dict[str, tuple[float, dict[str, int]]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SECONDS = 300


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


def _fetch_sql_by_month(owner_emails: list[str]) -> dict[str, int]:
    """Returns {'YYYY-MM-01': count, ...} for the entire HubSpot SQL history
    owned by the given emails, bucketed by createdate month."""
    cache_key = f"hist__{'+'.join(owner_emails)}"
    now = datetime.utcnow().timestamp()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

    counts: dict[str, int] = {}
    try:
        from backend.utils.hubspot import HubSpotClient  # type: ignore
    except ImportError:
        try:
            from utils.hubspot import HubSpotClient  # type: ignore
        except ImportError:
            log.warning("HubSpotClient unavailable; SQL counts will be empty")
            with _CACHE_LOCK:
                _CACHE[cache_key] = (now, counts)
            return counts

    lead_life_property = (os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life").strip()
    lead_life_value = (os.environ.get("HUBSPOT_LEAD_LIFE_SQL_VALUE") or "SQL (AE)").strip()

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
            if d is None:
                continue
            key = d.replace(day=1).isoformat()  # 'YYYY-MM-01'
            counts[key] = counts.get(key, 0) + 1
    except Exception as exc:  # noqa: BLE001
        log.warning("HubSpot SQL monthly fetch failed: %s", exc)

    with _CACHE_LOCK:
        _CACHE[cache_key] = (now, counts)
    return counts


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    sales_leads = _sales_leads()
    sql_by_month = _fetch_sql_by_month(sales_leads)

    # Flatten the dict for psycopg2: use parallel arrays so the SQL can JOIN.
    months_list = sorted(sql_by_month.keys())
    counts_list = [sql_by_month[m] for m in months_list]

    sql = """
        WITH base AS (
          SELECT
            TRIM(o.opp_stage) AS opp_stage,
            COALESCE(
              NULLIF(o.nda_signature_or_start_date::text, '')::date,
              NULLIF(o.opp_close_date::text, '')::date
            ) AS opp_date,
            NULLIF(o.opp_close_date::text, '')::date AS close_d
          FROM opportunity o
          LEFT JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND o.opp_stage IS NOT NULL
        ),
        hubspot_sql AS (
          SELECT mes::date AS mes, count::int AS sql_count
          FROM UNNEST(%(hs_months)s::date[], %(hs_counts)s::int[]) AS t(mes, count)
        ),
        bounds AS (
          SELECT
            LEAST(
              COALESCE((SELECT MIN(mes) FROM hubspot_sql), DATE_TRUNC('month', CURRENT_DATE)::date),
              COALESCE(DATE_TRUNC('month', (SELECT MIN(opp_date) FROM base))::date,
                       DATE_TRUNC('month', CURRENT_DATE)::date)
            ) AS first_month,
            DATE_TRUNC('month', CURRENT_DATE)::date AS last_month
        ),
        meses AS (
          SELECT
            DATE_TRUNC('month', gs)::date AS mes,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS mes_fin
          FROM bounds b,
               generate_series(b.first_month, b.last_month, INTERVAL '1 month') gs
        ),
        per_month AS (
          SELECT
            m.mes,
            COALESCE((SELECT sql_count FROM hubspot_sql h WHERE h.mes = m.mes), 0)::int       AS sql_count,
            COUNT(*) FILTER (
              WHERE b.opp_date IS NOT NULL
                AND b.opp_stage IN ('NDA Sent','Sourcing','Interviewing','Negotiating',
                                    'Close Win','Closed Lost')
            )::int                                                                              AS nda_sent_count,
            COUNT(*) FILTER (
              WHERE b.opp_date IS NOT NULL
                AND b.opp_stage IN ('Sourcing','Interviewing','Negotiating',
                                    'Close Win','Closed Lost')
            )::int                                                                              AS sourcing_count,
            COUNT(*) FILTER (
              WHERE b.opp_stage = 'Close Win'
                AND b.close_d IS NOT NULL
                AND b.close_d BETWEEN m.mes AND m.mes_fin
            )::int                                                                              AS close_win_count
          FROM meses m
          LEFT JOIN base b ON b.opp_date BETWEEN m.mes AND m.mes_fin
          GROUP BY m.mes
        )
        SELECT
          TO_CHAR(mes, 'YYYY-MM-DD')                                                            AS mes,
          sql_count,
          nda_sent_count,
          sourcing_count,
          close_win_count,
          ROUND(CASE WHEN sql_count = 0 THEN NULL
                     ELSE 100.0 * nda_sent_count::numeric / sql_count END, 2)::float            AS sql_to_nda_sent_pct,
          ROUND(CASE WHEN nda_sent_count = 0 THEN NULL
                     ELSE 100.0 * sourcing_count::numeric / nda_sent_count END, 2)::float       AS nda_sent_to_sourcing_pct,
          ROUND(CASE WHEN sourcing_count = 0 THEN NULL
                     ELSE 100.0 * close_win_count::numeric / sourcing_count END, 2)::float      AS sourcing_to_close_win_pct,
          ROUND(CASE WHEN sql_count = 0 THEN NULL
                     ELSE 100.0 * close_win_count::numeric / sql_count END, 2)::float           AS sql_to_close_win_pct
        FROM per_month
        ORDER BY mes;
    """

    return sql, {
        "sales_leads": sales_leads,
        "hs_months": months_list,
        "hs_counts": counts_list,
    }


DATASET = {
    "key": "sales_funnel_history",
    "label": "Sales funnel — monthly (Mariano + Bahia · HubSpot SQL + CRM stages)",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
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
