"""SQL Sales — per-lead breakdown by window.

Sibling of sql_leads_windows. Both pull from HubSpot (contacts with
`lead_life = "SQL (AE)"`) and bucket them by the same 4 windows: last_week,
wtd, last_month, mtd. While sql_leads_windows returns 4 aggregate counts,
this dataset returns one row per lead inside the selected window so the
drawer can list them with name + email + company + createdate.

The `event_window` filter selects which window (last_week, wtd, last_month,
mtd) the rows should belong to. Defaults to last_week to match the hero.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
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


def _windows(corte: date) -> dict[str, tuple[date, date]]:
    this_week_monday = corte - timedelta(days=corte.weekday())
    prev_week_sunday = this_week_monday - timedelta(days=1)
    prev_week_monday = prev_week_sunday - timedelta(days=6)

    month_start = corte.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    return {
        "last_week":  (prev_week_monday,  prev_week_sunday),
        "wtd":        (this_week_monday,  corte),
        "last_month": (last_month_start,  last_month_end),
        "mtd":        (month_start,       corte),
    }


def _resolve_window_key(filters: dict) -> str:
    raw = str(
        filters.get("event_window")
        or filters.get("window")
        or filters.get("ventana")
        or "last_week"
    ).strip().lower().replace("-", "_")
    if raw == "week":
        return "last_week"
    if raw in {"month", "prev_month"}:
        return "last_month"
    if raw in {"last_week", "wtd", "last_month", "mtd"}:
        return raw
    return "last_week"


def _fetch_sql_contacts(corte: date) -> list[dict[str, Any]]:
    """All SQL contacts from HubSpot with normalized name/email/company/createdate."""
    cache_key = corte.isoformat()
    now = datetime.utcnow().timestamp()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

    rows: list[dict[str, Any]] = []
    try:
        from backend.utils.hubspot import HubSpotClient  # type: ignore
    except ImportError:
        try:
            from utils.hubspot import HubSpotClient  # type: ignore
        except ImportError:
            log.warning("HubSpotClient unavailable; SQL leads detail returning empty")
            with _CACHE_LOCK:
                _CACHE[cache_key] = (now, rows)
            return rows

    lead_life_property = (
        os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life"
    ).strip()
    lead_life_value = (
        os.environ.get("HUBSPOT_LEAD_LIFE_SQL_VALUE") or "SQL (AE)"
    ).strip()

    try:
        client = HubSpotClient()
        contacts = client.search_contacts(
            [{"propertyName": lead_life_property, "operator": "EQ", "value": lead_life_value}],
            extra_properties=[lead_life_property, "firstname", "lastname", "email", "company", "createdate"],
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("HubSpot SQL leads detail fetch failed: %s", exc)
        with _CACHE_LOCK:
            _CACHE[cache_key] = (now, rows)
        return rows

    for contact in contacts or []:
        props = (contact or {}).get("properties", {}) or {}
        d = _parse_hubspot_date(props.get("createdate"))
        if d is None:
            continue
        first = (props.get("firstname") or "").strip()
        last = (props.get("lastname") or "").strip()
        name = (first + " " + last).strip() or (props.get("email") or "").strip() or "—"
        rows.append({
            "name": name,
            "email": (props.get("email") or "").strip(),
            "company": (props.get("company") or "").strip(),
            "createdate": d.isoformat(),
        })

    with _CACHE_LOCK:
        _CACHE[cache_key] = (now, rows)
    return rows


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or datetime.utcnow().date()
    )
    window_key = _resolve_window_key(filters)

    contacts = _fetch_sql_contacts(corte)
    win_ini, win_fin = _windows(corte)[window_key]

    rows: list[dict[str, Any]] = []
    for c in contacts:
        d = _parse_hubspot_date(c.get("createdate"))
        if d and win_ini <= d <= win_fin:
            rows.append(c)
    # Sort by createdate descending (most recent first)
    rows.sort(key=lambda r: r.get("createdate", ""), reverse=True)

    # Wrap the in-memory rows as a literal-row VALUES query so it composes with
    # the existing /charts/.../data executor (which expects (sql, params)).
    if not rows:
        sql = "SELECT NULL::text AS name, NULL::text AS email, NULL::text AS company, NULL::date AS createdate WHERE FALSE;"
        return sql, {}

    # Build a UNION ALL of literal rows. Params are bound by psycopg2 so values
    # are safe from injection.
    pieces = []
    params: dict[str, Any] = {}
    for i, r in enumerate(rows):
        pieces.append(
            f"SELECT %(n_{i})s::text AS name, %(e_{i})s::text AS email, "
            f"%(c_{i})s::text AS company, %(d_{i})s::date AS createdate"
        )
        params[f"n_{i}"] = r["name"] or "—"
        params[f"e_{i}"] = r["email"] or ""
        params[f"c_{i}"] = r["company"] or ""
        params[f"d_{i}"] = r["createdate"]
    sql = " UNION ALL ".join(pieces) + " ORDER BY createdate DESC;"
    return sql, params


DATASET = {
    "key": "sql_leads_detail",
    "label": "SQL Sales — Detalle por ventana (HubSpot)",
    "dimensions": [
        {"key": "name", "label": "Lead", "type": "string"},
        {"key": "email", "label": "Email", "type": "string"},
        {"key": "company", "label": "Empresa", "type": "string"},
        {"key": "createdate", "label": "Fecha", "type": "date"},
    ],
    "measures": [],
    "default_filters": {"event_window": "last_week"},
    "query": query,
}
