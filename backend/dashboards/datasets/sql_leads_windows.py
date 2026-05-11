"""SQL Sales — leads count by window (Last week / WTD / Last month / MTD).

This dataset is *not* SQL-backed. It pulls from HubSpot via `HubSpotClient`
because the SQL lead lifecycle stage lives on contacts in HubSpot (custom
property `lead_life = "SQL (AE)"`). Results are cached in-memory for 5 min
to avoid hammering the HubSpot API on every dashboard refresh.

The dashboard runtime calls `query(filters)` expecting `(sql, params)`. To
keep that contract intact while sourcing from an API, `query` returns a
trivial `SELECT` that wraps the computed values as a literal row, and the
real work happens inside `query` (HubSpot fetch + bucketing).
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, dict[str, int]]] = {}
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
    # HubSpot returns ISO-8601 strings like "2026-04-12T13:45:00.000Z".
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _windows(corte: date) -> dict[str, tuple[date, date]]:
    # ISO week starts on Monday. Python date.weekday() returns 0..6 with Monday=0.
    week_start = corte - timedelta(days=corte.weekday())
    month_start = corte.replace(day=1)
    return {
        "last_week":  (corte - timedelta(days=6),  corte),
        "wtd":        (week_start,                 corte),
        "last_month": (corte - timedelta(days=29), corte),
        "mtd":        (month_start,                corte),
    }


def _fetch_sql_dates(corte: date) -> dict[str, int]:
    """Return counts per window. Uses module-level cache keyed by corte."""
    cache_key = corte.isoformat()
    now = datetime.utcnow().timestamp()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

    counts = {"last_week": 0, "wtd": 0, "last_month": 0, "mtd": 0}
    try:
        from backend.utils.hubspot import HubSpotClient  # type: ignore
    except ImportError:
        try:
            from utils.hubspot import HubSpotClient  # type: ignore
        except ImportError:
            log.warning("HubSpotClient unavailable; SQL leads will return zeros")
            with _CACHE_LOCK:
                _CACHE[cache_key] = (now, counts)
            return counts

    lead_life_property = (
        os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life"
    ).strip()
    lead_life_value = (
        os.environ.get("HUBSPOT_LEAD_LIFE_SQL_VALUE") or "SQL (AE)"
    ).strip()

    try:
        client = HubSpotClient()
        # Pull all contacts tagged with the SQL lifecycle. createdate comes
        # back automatically (it's in the default property set inside
        # HubSpotClient.search_contacts).
        contacts = client.search_contacts(
            [{"propertyName": lead_life_property, "operator": "EQ", "value": lead_life_value}],
            extra_properties=[lead_life_property],
        )
    except Exception as exc:  # noqa: BLE001 — keep the dashboard alive on outages
        log.warning("HubSpot SQL leads fetch failed: %s", exc)
        with _CACHE_LOCK:
            _CACHE[cache_key] = (now, counts)
        return counts

    windows = _windows(corte)
    for contact in contacts or []:
        props = (contact or {}).get("properties", {}) or {}
        d = _parse_hubspot_date(props.get("createdate"))
        if d is None:
            continue
        for key, (ini, fin) in windows.items():
            if ini <= d <= fin:
                counts[key] += 1

    with _CACHE_LOCK:
        _CACHE[cache_key] = (now, counts)
    return counts


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or datetime.utcnow().date()
    )
    counts = _fetch_sql_dates(corte)

    sql = """
        SELECT
          %(corte)s::date     AS corte,
          %(last_week)s::int  AS sql_last_week,
          %(wtd)s::int        AS sql_wtd,
          %(last_month)s::int AS sql_last_month,
          %(mtd)s::int        AS sql_mtd
    """
    return sql, {
        "corte": corte,
        "last_week":  counts["last_week"],
        "wtd":        counts["wtd"],
        "last_month": counts["last_month"],
        "mtd":        counts["mtd"],
    }


DATASET = {
    "key": "sql_leads_windows",
    "label": "SQL Sales — Leads por ventana (HubSpot)",
    "dimensions": [
        {"key": "corte", "label": "Corte", "type": "date"},
    ],
    "measures": [
        {"key": "sql_last_week",  "label": "Last week",  "type": "number"},
        {"key": "sql_wtd",        "label": "WTD",        "type": "number"},
        {"key": "sql_last_month", "label": "Last month", "type": "number"},
        {"key": "sql_mtd",        "label": "MTD",        "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
