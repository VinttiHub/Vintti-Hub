import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone

import psycopg2
from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_connection
from utils.credit_loop import maybe_send_credit_available_email_for_new_opportunity
from utils.hr_lead_todo import create_stage_todos
from utils.hubspot import (
    DEFAULT_MARIANO_EMAIL,
    HubSpotClient,
    HubSpotError,
    association_ids,
    build_account_payload,
    clip,
    comma_env,
    hubspot_datetime_to_ms,
    strip_tracking_params,
)
from utils import hubspot_opportunities as hs_opps
from dashboards.datasets._now import today_ar


bp = Blueprint("hubspot", __name__)

# Anchos REALES de las columnas angostas de `account` (information_schema, 2026-09-03).
# HubSpot no valida largos: un website de 213 caracteres (una URL de campana con
# gclid) contra website varchar(128) tira StringDataRightTruncation, y eso ABORTA la
# transaccion de Postgres. Las columnas que no estan aca son varchar sin limite.
ACCOUNT_COLUMN_LIMITS = {
    "client_name": 50,
    "account_manager": 50,
    "contract": 50,
    "mail": 50,
    "size": 50,
    "state": 50,
    "timezone": 50,
    "website": 128,
    "linkedin": 256,
}


HUBSPOT_NDA_SENT_DATE_PROPERTY = "hs_v2_date_entered_1226596718"
HUBSPOT_DEEP_DIVE_DATE_PROPERTY = "hs_v2_date_entered_1226596717"
DEEP_DIVE_OR_LATER_STAGES = (
    "Deep Dive",
    "NDA Sent",
    "Sourcing",
    "Interviewing",
    "Negotiating",
    "Close Win",
    "Closed Lost",
)
NDA_SENT_OR_LATER_STAGES = (
    "NDA Sent",
    "Sourcing",
    "Interviewing",
    "Negotiating",
    "Close Win",
    "Closed Lost",
)

PAIN_POINT_NORMALIZATION = {
    'high salary': 'High salary',
    'no real pain point': 'No real pain point',
    'cultural': 'Cultural fit',
    'cultural fit': 'Cultural fit',
    'time zone': 'Time zone',
    'knowledge': 'No knowledge/time to search',
    'no knowledge': 'No knowledge/time to search',
    'no time': 'No knowledge/time to search',
    'no time to hire': 'No knowledge/time to search',
    'slow hiring processes': 'No knowledge/time to search',
    'workload': 'No knowledge/time to search',
    'no knowledge/time to search': 'No knowledge/time to search',
}

LEAD_SOURCE_NORMALIZATION = {
    'seo': 'Website Organic',
    'website organic': 'Website Organic',
    'event': 'Event',
    'linkedin - agus': 'Social Media',
    'linkedin': 'Social Media',
    'social media': 'Social Media',
    'events': 'Event',
    'outbound': 'Outbound',
    'outbound - linkedin': 'Outbound',
    'outbound – linkedin': 'Outbound',
    'other': 'Other',
    'ai': 'AI',
    'webinar': 'Webinar',
    'paid media': 'Paid Media',
    'referral': 'Referral',
    'connected inbox': 'Connected Inbox',
    'press action': 'Press Action',
    'import': 'Import',
    'na': 'NA',
    'n/a': 'NA',
}

OUTSOURCE_NORMALIZATION = {
    'yes': 'Yes - No info',
    'true': 'Yes - No info',
    '1': 'Yes - No info',
    'y': 'Yes - No info',
    'si': 'Yes - No info',
    'sí': 'Yes - No info',
    'outsourced': 'Yes - No info',
    'outsourced before': 'Yes - No info',
    'yes - no info': 'Yes - No info',
    'no': 'No',
    'false': 'No',
    '0': 'No',
    'n': 'No',
    'not outsourced': 'No',
    'never': 'No',
    'na': 'NA',
    'n/a': 'NA',
    'philippines': 'Philippines',
    'india': 'India',
    'latam': 'LATAM',
    'south africa': 'South Africa',
}


def _clip_account_values(values):
    """Recorta cada valor al ancho de su columna. Las claves son nombres de columna."""
    return {
        key: clip(value, ACCOUNT_COLUMN_LIMITS.get(key))
        for key, value in values.items()
    }


def _rollback_quietly(conn, label):
    """Deja la conexion usable para el siguiente registro del loop."""
    try:
        conn.rollback()
    except Exception:
        logging.exception("HubSpot sync: rollback fallido despues de %s", label)


def _error_record(exc, **fields):
    """Error con el diagnostico de psycopg2 (pgcode / columna / constraint).

    Sin esto el front solo mostraba "Errors: N" y habia que ir a CloudWatch para
    enterarse de que columna rebotaba.
    """
    diag = getattr(exc, "diag", None)
    record = dict(fields)
    record["error"] = str(exc)
    record["pgcode"] = getattr(exc, "pgcode", None)
    record["column"] = getattr(diag, "column_name", None)
    record["constraint"] = getattr(diag, "constraint_name", None)
    return record


def _require_sync_secret():
    expected = os.environ.get("HUBSPOT_SYNC_SECRET")
    if not expected:
        return None
    received = request.headers.get("X-HubSpot-Sync-Secret") or request.args.get("secret")
    if received != expected:
        return jsonify({"error": "Unauthorized"}), 401
    return None


# Se cachea por proceso: en regimen el schema ya esta aplicado y no hace falta ni
# consultar el catalogo de nuevo.
_HUBSPOT_ACCOUNT_COLUMNS = (
    "hubspot_deal_id",
    "hubspot_company_id",
    "hubspot_contact_id",
    "hubspot_synced_at",
    "vintti_ai",
    "lead_source_detail",
    "conversion_channel",
    "credit_loop",
    "sql_meeting_date",
)
_HUBSPOT_ACCOUNT_SCHEMA_READY = None


def _hubspot_account_schema_is_ready(cursor):
    """True si ya estan todas las columnas y el indice. Solo lee el catalogo."""
    cursor.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_name = 'account' AND column_name = ANY(%s)
        """,
        (list(_HUBSPOT_ACCOUNT_COLUMNS),),
    )
    present = {
        (row["column_name"] if isinstance(row, dict) else row[0])
        for row in cursor.fetchall()
    }
    if len(present) < len(_HUBSPOT_ACCOUNT_COLUMNS):
        return False
    cursor.execute(
        """
        SELECT 1
          FROM pg_indexes
         WHERE tablename = 'account' AND indexname = 'idx_account_hubspot_deal_id'
         LIMIT 1
        """
    )
    return cursor.fetchone() is not None


def _ensure_hubspot_account_columns(cursor):
    """Idempotente y BARATO en regimen.

    Antes corria 9 ALTER TABLE + 1 CREATE INDEX en CADA request de 8 endpoints. Un
    ALTER TABLE toma ACCESS EXCLUSIVE sobre `account` aunque el IF NOT EXISTS no haga
    nada, y aca corre justo antes de un loop que tarda minutos: la tabla quedaba
    trabada todo ese rato para cualquier otra request. Ver el comentario de
    backend/db.py:32 y el patron de users_has_color().
    """
    global _HUBSPOT_ACCOUNT_SCHEMA_READY
    if _HUBSPOT_ACCOUNT_SCHEMA_READY:
        return
    if _hubspot_account_schema_is_ready(cursor):
        _HUBSPOT_ACCOUNT_SCHEMA_READY = True
        return

    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS hubspot_deal_id TEXT")
    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS hubspot_company_id TEXT")
    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS hubspot_contact_id TEXT")
    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS hubspot_synced_at TIMESTAMPTZ")
    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS vintti_ai BOOLEAN NOT NULL DEFAULT FALSE")
    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS lead_source_detail TEXT")
    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS conversion_channel TEXT")
    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS credit_loop TEXT")
    # R1: fecha REAL del meeting (meeting_date___time de HubSpot) con la que el contacto
    # se volvió SQL. La escribe el sync de SQL contacts; las cards de Ventas anclan el
    # SQL en esta fecha (COALESCE a creation_date para cuentas aún sin backfill), igual
    # que Marketing. Ver [[project_dashboard_audit]] R1.
    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS sql_meeting_date DATE")
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_account_hubspot_deal_id
        ON account (hubspot_deal_id)
        WHERE hubspot_deal_id IS NOT NULL AND hubspot_deal_id <> ''
        """
    )
    _HUBSPOT_ACCOUNT_SCHEMA_READY = True


def _ensure_opportunity_stage_date_columns(cursor):
    cursor.execute("ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS deep_dive_date DATE")
    cursor.execute("ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS nda_sent_date DATE")


# ---------------------------------------------------------------------------
# Sync de opportunities: esquema y marca de agua.
# Ver backend/sql/20260910_hubspot_opportunity_sync.sql y CLAUDE.md.
# ---------------------------------------------------------------------------

HUBSPOT_OPP_SYNC_KEY = "opportunities"
# Clave del advisory lock: el cron cada 30 min y el boton pueden solaparse, y como
# commiteamos por deal dos corridas simultaneas podrian crear la misma opp dos veces.
HUBSPOT_OPP_SYNC_LOCK_KEY = 761_020_910

_HUBSPOT_OPPORTUNITY_COLUMNS = (
    "hubspot_deal_id",
    "hubspot_pipeline_id",
    "hubspot_dealstage_id",
    "hubspot_synced_at",
    "hubspot_setup_fee",
    "hubspot_final_fee",
    "hubspot_final_salary",
    "hubspot_role_hired",
    "hubspot_mkt_collab",
    "hubspot_hire_applied_at",
    "deep_dive_date",
    "nda_sent_date",
)
_HUBSPOT_OPPORTUNITY_SCHEMA_READY = None
_HUBSPOT_SYNC_STATE_READY = None


def _hubspot_opportunity_schema_is_ready(cursor):
    """True si estan las columnas y el indice unico. Solo lee el catalogo."""
    cursor.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_name = 'opportunity' AND column_name = ANY(%s)
        """,
        (list(_HUBSPOT_OPPORTUNITY_COLUMNS),),
    )
    present = {
        (row["column_name"] if isinstance(row, dict) else row[0])
        for row in cursor.fetchall()
    }
    if len(present) < len(_HUBSPOT_OPPORTUNITY_COLUMNS):
        return False
    cursor.execute(
        """
        SELECT 1
          FROM pg_indexes
         WHERE tablename = 'opportunity'
           AND indexname = 'idx_opportunity_hubspot_deal_id'
         LIMIT 1
        """
    )
    return cursor.fetchone() is not None


def _ensure_hubspot_opportunity_columns(cursor):
    """Idempotente y BARATO en regimen, igual que _ensure_hubspot_account_columns.

    Un ALTER TABLE toma ACCESS EXCLUSIVE sobre `opportunity` aunque el IF NOT
    EXISTS no haga nada, y aca corre justo antes de un loop que puede tardar
    minutos: sin el chequeo previo la tabla quedaria trabada todo ese rato.
    """
    global _HUBSPOT_OPPORTUNITY_SCHEMA_READY
    if _HUBSPOT_OPPORTUNITY_SCHEMA_READY:
        return
    if _hubspot_opportunity_schema_is_ready(cursor):
        _HUBSPOT_OPPORTUNITY_SCHEMA_READY = True
        return

    cursor.execute("ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS hubspot_deal_id TEXT")
    cursor.execute("ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS hubspot_pipeline_id TEXT")
    cursor.execute("ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS hubspot_dealstage_id TEXT")
    cursor.execute("ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS hubspot_synced_at TIMESTAMPTZ")
    cursor.execute("ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS hubspot_setup_fee NUMERIC(12,2)")
    cursor.execute("ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS hubspot_final_fee NUMERIC(12,2)")
    cursor.execute("ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS hubspot_final_salary NUMERIC(12,2)")
    cursor.execute("ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS hubspot_role_hired TEXT")
    cursor.execute("ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS hubspot_mkt_collab TEXT")
    cursor.execute("ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS hubspot_hire_applied_at TIMESTAMPTZ")
    cursor.execute("ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS deep_dive_date DATE")
    cursor.execute("ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS nda_sent_date DATE")
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_opportunity_hubspot_deal_id
        ON opportunity (hubspot_deal_id)
        WHERE hubspot_deal_id IS NOT NULL AND hubspot_deal_id <> ''
        """
    )
    cursor.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_opportunity_account_position_norm
        ON opportunity (
            account_id,
            (regexp_replace(lower(btrim(coalesce(opp_position_name, ''))), '\s+', ' ', 'g'))
        )
        """
    )
    _HUBSPOT_OPPORTUNITY_SCHEMA_READY = True


def _ensure_hubspot_sync_state_table(cursor):
    """Marca de agua del sync incremental.

    Tabla propia y NO app_cache: app_cache vence y se borra solo, y su contrato es
    "fallar en silencio". Un watermark que se evapora hace que el sync se saltee
    deals para siempre.
    """
    global _HUBSPOT_SYNC_STATE_READY
    if _HUBSPOT_SYNC_STATE_READY:
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS hubspot_sync_state (
            sync_key     TEXT PRIMARY KEY,
            watermark_ms BIGINT,
            last_run_at  TIMESTAMPTZ,
            last_status  TEXT,
            last_report  JSONB
        )
        """
    )
    _HUBSPOT_SYNC_STATE_READY = True


def _read_sync_watermark_ms(cursor, sync_key=HUBSPOT_OPP_SYNC_KEY):
    cursor.execute(
        "SELECT watermark_ms FROM hubspot_sync_state WHERE sync_key = %s",
        (sync_key,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    value = row["watermark_ms"] if isinstance(row, dict) else row[0]
    return int(value) if value is not None else None


def _write_sync_state(cursor, sync_key, watermark_ms, status, report):
    """Guarda el ultimo reporte siempre; el watermark solo si vino un valor.

    COALESCE en watermark_ms para que una corrida con errores (que NO debe avanzar
    la marca) igual deje su reporte para triage sin pisar la marca buena.
    """
    cursor.execute(
        """
        INSERT INTO hubspot_sync_state (sync_key, watermark_ms, last_run_at, last_status, last_report)
        VALUES (%s, %s, NOW(), %s, %s::jsonb)
        ON CONFLICT (sync_key) DO UPDATE
           SET watermark_ms = COALESCE(EXCLUDED.watermark_ms, hubspot_sync_state.watermark_ms),
               last_run_at  = EXCLUDED.last_run_at,
               last_status  = EXCLUDED.last_status,
               last_report  = EXCLUDED.last_report
        """,
        (sync_key, watermark_ms, status, json.dumps(report, default=str)),
    )


def _parse_hubspot_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()

    raw = str(value).strip()
    if not raw:
        return None

    if raw.isdigit():
        try:
            timestamp = int(raw)
            if timestamp > 10_000_000_000:
                timestamp = timestamp / 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
        except (OverflowError, ValueError, OSError):
            return None

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        pass

    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _normalize_pain_point(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        items = []
        seen = set()
        for item in value:
            normalized = _normalize_pain_point(item)
            if not normalized:
                continue
            for part in [segment.strip() for segment in str(normalized).split(',') if segment.strip()]:
                key = part.lower()
                if key not in seen:
                    seen.add(key)
                    items.append(part)
        return ", ".join(items) if items else None

    raw = str(value or "").strip()
    if not raw:
        return None
    if "," in raw:
        parts = [segment.strip() for segment in raw.split(",") if segment.strip()]
        if len(parts) > 1:
            return _normalize_pain_point(parts)
    return PAIN_POINT_NORMALIZATION.get(raw.lower(), raw)


def _normalize_lead_source(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    return LEAD_SOURCE_NORMALIZATION.get(raw.lower(), raw)


def _normalize_outsource_value(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    return OUTSOURCE_NORMALIZATION.get(raw.lower(), raw)


def _normalize_credit_loop_value(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.lower()
    if normalized in ("sí", "si", "yes", "true", "1", "y"):
        return "Sí"
    if normalized in ("no", "false", "0", "n"):
        return "No"
    return raw


def _normalize_boolean_value(value):
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    if raw in ("yes", "true", "1", "y", "si", "sí"):
        return True
    return False


def _account_name_candidates(value):
    raw = str(value or "").strip()
    if not raw:
        return []
    candidates = [raw]
    for separator in (" - ", " – ", " — "):
        if separator in raw:
            before = raw.split(separator, 1)[0].strip()
            if before:
                candidates.append(before)
    seen = set()
    unique = []
    for candidate in candidates:
        key = " ".join(candidate.lower().split())
        if key and key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _normalize_hubspot_label(value):
    text = str(value or "").lower().replace("_", " ")
    for char in ("/", "-", "–", "—", "(", ")", ":", "?"):
        text = text.replace(char, " ")
    return " ".join(text.split())


HUBSPOT_ACCOUNT_FIELD_ALIASES = {
    "client_name": ["company", "Company"],
    "contract": ["model", "Model"],
    "linkedin": ["hs_linkedin_url", "LinkedIn URL"],
    "mail": ["email", "Correo", "Email"],
    "size": ["headcount", "Headcount"],
    "state": ["state", "State/Region"],
    "website": ["website", "URL del sitio web"],
    "pain_points": ["pain_point", "Pain Point"],
    "where_come_from": ["origin", "Origin"],
    "referal_source": ["referred_by", "Referred by"],
    "contact_name": ["firstname", "Nombre", "First Name"],
    "contact_surname": ["lastname", "Apellidos", "Last Name"],
    "industry": ["sector", "Industria"],
    "outsource": ["outsourced_before", "Outsourced before"],
    "position": ["position", "Position"],
    "type": ["company_type", "Company Type"],
    "lead_source_detail": ["origin_detail", "Origin detail"],
    "conversion_channel": ["conversion_channel", "Conversion Channel"],
    "credit_loop": ["credit_loop", "Credit Loop?", "Credit Loop"],
    "vintti_ai": ["vintti_ai", "Vintti AI"],
}

MEETING_DATE_TIME_ALIASES = [
    "Meeting date & time",
    "Meeting Date & Time",
    "Meeting date and time",
    "Meeting Date and Time",
]


def _parse_stage_ids(value, default):
    raw = value if value not in (None, "") else default
    if isinstance(raw, str):
        if raw.strip().lower() in ("all", "*"):
            return []
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, (list, tuple)):
        if any(str(part).strip().lower() in ("all", "*") for part in raw):
            return []
        return [str(part).strip() for part in raw if str(part).strip()]
    return []


def _resolve_property_map_for_object(client, object_type):
    props = client.get_properties(object_type)
    by_alias = {}
    option_labels = {}
    normalized_props = []
    for prop in props:
        name = prop.get("name") or ""
        label = prop.get("label") or ""
        normalized_props.append(
            {
                "name": name,
                "options": {
                    str(option.get("value") or ""): str(option.get("label") or "")
                    for option in prop.get("options", [])
                    if option.get("value") not in (None, "") and option.get("label") not in (None, "")
                },
                "keys": {
                    _normalize_hubspot_label(name),
                    _normalize_hubspot_label(label),
                },
            }
        )

    for field, aliases in HUBSPOT_ACCOUNT_FIELD_ALIASES.items():
        for alias in aliases:
            normalized_alias = _normalize_hubspot_label(alias)
            match = next(
                (
                    prop
                    for prop in normalized_props
                    if normalized_alias in prop["keys"]
                ),
                None,
            )
            if match:
                by_alias[field] = match["name"]
                if match["options"]:
                    option_labels[field] = match["options"]
                break
    return by_alias, option_labels


# Cache (TTL) de los property maps: se resuelven con 3 llamadas a get_properties
# (contacts/companies/deals) y son idénticos para TODOS los datasets de cada request.
# Sin cache, cada chart del tab de Marketing las repetía → ráfaga que rate-limitea
# HubSpot. Los nombres/opciones de propiedades casi no cambian → TTL holgado.
_PROPERTY_MAPS_CACHE = {"data": None, "ts": 0.0}
_PROPERTY_MAPS_TTL = 600  # 10 minutos


def _resolve_account_property_maps(client):
    cache = _PROPERTY_MAPS_CACHE
    now = time.time()
    if cache["data"] is not None and (now - cache["ts"]) < _PROPERTY_MAPS_TTL:
        return cache["data"]
    contacts, contact_options = _resolve_property_map_for_object(client, "contacts")
    companies, company_options = _resolve_property_map_for_object(client, "companies")
    deals, deal_options = _resolve_property_map_for_object(client, "deals")
    result = {
        "contacts": contacts,
        "companies": companies,
        "deals": deals,
        "_option_labels": {
            "contacts": contact_options,
            "companies": company_options,
            "deals": deal_options,
        },
    }
    cache["data"] = result
    cache["ts"] = now
    return result


def _resolve_named_property(client, object_type, aliases):
    normalized_aliases = {_normalize_hubspot_label(alias) for alias in aliases}
    for prop in client.get_properties(object_type):
        name = prop.get("name") or ""
        label = prop.get("label") or ""
        keys = {
            _normalize_hubspot_label(name),
            _normalize_hubspot_label(label),
        }
        if keys & normalized_aliases:
            return name
    return None


def _resolve_meeting_datetime_property(client):
    return _resolve_named_property(client, "contacts", MEETING_DATE_TIME_ALIASES)


def _mapped_property_names(property_maps, object_type):
    return [
        prop
        for prop in property_maps.get(object_type, {}).values()
        if prop
    ]


def _record_prop(record, prop_name):
    if not prop_name:
        return ""
    return ((record or {}).get("properties") or {}).get(prop_name) or ""


def _hubspot_option_label(property_maps, object_type, field, value):
    if value in (None, ""):
        return value
    labels = (
        property_maps
        .get("_option_labels", {})
        .get(object_type, {})
        .get(field, {})
    )
    return labels.get(str(value), value)


def _first_mapped_value(property_maps, field, contact=None, company=None, deal=None):
    for object_type, record in (
        ("contacts", contact),
        ("companies", company),
        ("deals", deal),
    ):
        value = _record_prop(record, property_maps.get(object_type, {}).get(field))
        if value not in (None, ""):
            return _hubspot_option_label(property_maps, object_type, field, value)
    return ""


def _append_comment_line(payload, label, value):
    text = str(value or "").strip()
    if not text:
        return
    current = str(payload.get("about") or "").strip()
    line = f"{label}: {text}"
    payload["about"] = f"{current}\n{line}".strip() if current else line


def _preview_account_fields(payload):
    keys = [
        "name",
        "mail",
        "contact_name",
        "contact_surname",
        "where_come_from",
        "lead_source_detail",
        "conversion_channel",
        "website",
        "linkedin",
        "contract",
        "type",
        "industry",
        "state",
        "outsource",
        "size",
        "pain_points",
        "position",
        "about",
        "account_manager",
        "hubspot_deal_id",
        "hubspot_company_id",
        "hubspot_contact_id",
        "credit_loop",
        "vintti_ai",
    ]
    return {key: payload.get(key) for key in keys}


def _apply_account_field_overrides(payload, contact=None, company=None, deal=None, property_maps=None):
    property_maps = property_maps or {}
    field_to_payload = {
        "client_name": "name",
        "contract": "contract",
        "mail": "mail",
        "website": "website",
        "type": "type",
        "industry": "industry",
        "state": "state",
        "outsource": "outsource",
        "size": "size",
        "where_come_from": "where_come_from",
        "referal_source": "referal_source",
        "contact_name": "contact_name",
        "contact_surname": "contact_surname",
        "lead_source_detail": "lead_source_detail",
        "conversion_channel": "conversion_channel",
        "linkedin": "linkedin",
        "pain_points": "pain_points",
        "position": "position",
        "credit_loop": "credit_loop",
        "vintti_ai": "vintti_ai",
    }
    for field, payload_key in field_to_payload.items():
        value = _first_mapped_value(property_maps, field, contact=contact, company=company, deal=deal)
        if value not in (None, ""):
            payload[payload_key] = value
    payload["outsource"] = _normalize_outsource_value(payload.get("outsource"))
    payload["pain_points"] = _normalize_pain_point(payload.get("pain_points"))
    payload["where_come_from"] = _normalize_lead_source(payload.get("where_come_from"))
    payload["credit_loop"] = _normalize_credit_loop_value(payload.get("credit_loop"))
    payload["vintti_ai"] = _normalize_boolean_value(payload.get("vintti_ai"))
    # El website mapeado desde HubSpot puede venir como URL de campana (?gclid=...) y
    # pasarse de los 128 chars de la columna. Se limpia ACA y no solo en el INSERT para
    # que el preview muestre exactamente lo que se va a guardar.
    payload["website"] = strip_tracking_params(payload.get("website"))

    return payload


@bp.route("/hubspot/debug/properties", methods=["GET", "OPTIONS"])
def debug_hubspot_properties():
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        query = (request.args.get("q") or "lead life").strip().lower()
        object_types = [
            part.strip()
            for part in (request.args.get("objects") or "deals,contacts,companies").split(",")
            if part.strip()
        ]
        terms = [term for term in query.replace("_", " ").split() if term]
        client = HubSpotClient()
        matches = {}

        for object_type in object_types:
            object_matches = []
            for prop in client.get_properties(object_type):
                name = str(prop.get("name") or "")
                label = str(prop.get("label") or "")
                description = str(prop.get("description") or "")
                haystack = f"{name} {label} {description}".lower().replace("_", " ")
                if all(term in haystack for term in terms) or query in haystack:
                    object_matches.append({
                        "object_type": object_type,
                        "name": name,
                        "label": label,
                        "type": prop.get("type"),
                        "fieldType": prop.get("fieldType"),
                        "groupName": prop.get("groupName"),
                        "options": [
                            {
                                "label": option.get("label"),
                                "value": option.get("value"),
                            }
                            for option in prop.get("options", [])
                        ],
                    })
            matches[object_type] = object_matches

        return jsonify({
            "success": True,
            "query": query,
            "objects": object_types,
            "matches": matches,
        })
    except HubSpotError as exc:
        return jsonify({
            "success": False,
            "token_configured": bool(os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")),
            "error": str(exc),
        }), 502
    except Exception as exc:
        logging.exception("HubSpot properties debug failed")
        return jsonify({
            "success": False,
            "token_configured": bool(os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")),
            "error": str(exc),
        }), 500


@bp.route("/hubspot/debug/mariano", methods=["GET", "OPTIONS"])
def debug_mariano_hubspot():
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        owner_email = (
            request.args.get("owner_email")
            or os.environ.get("HUBSPOT_MARIANO_EMAIL")
            or DEFAULT_MARIANO_EMAIL
        ).strip().lower()
        stage_ids = _parse_stage_ids(
            request.args.get("stage_ids"),
            os.environ.get("HUBSPOT_CLOSED_DEAL_STAGE_IDS", "closedwon"),
        )
        pipeline_id = request.args.get("pipeline_id") or os.environ.get("HUBSPOT_PIPELINE_ID")

        token_configured = bool(os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN"))
        client = HubSpotClient()
        owner_id = client.get_owner_id_by_email(owner_email)
        deals = client.search_closed_deals(
            owner_id,
            stage_ids=stage_ids,
            pipeline_id=pipeline_id,
        )
        samples = []
        for deal in deals[:5]:
            props = deal.get("properties") or {}
            samples.append({
                "deal_id": deal.get("id"),
                "dealname": props.get("dealname"),
                "dealstage": props.get("dealstage"),
                "pipeline": props.get("pipeline"),
                "closedate": props.get("closedate"),
                "lastmodified": props.get("hs_lastmodifieddate"),
            })

        return jsonify({
            "success": True,
            "token_configured": token_configured,
            "owner_email": owner_email,
            "owner_id": owner_id,
            "stage_ids": stage_ids,
            "pipeline_id": pipeline_id,
            "deals_found": len(deals),
            "sample_deals": samples,
        })
    except HubSpotError as exc:
        return jsonify({
            "success": False,
            "token_configured": bool(os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")),
            "error": str(exc),
        }), 502
    except Exception as exc:
        logging.exception("HubSpot debug failed")
        return jsonify({
            "success": False,
            "token_configured": bool(os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")),
            "error": str(exc),
        }), 500


@bp.route("/hubspot/debug/mariano/deals", methods=["GET", "OPTIONS"])
def debug_mariano_hubspot_deals():
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        owner_email = (
            request.args.get("owner_email")
            or os.environ.get("HUBSPOT_MARIANO_EMAIL")
            or DEFAULT_MARIANO_EMAIL
        ).strip().lower()
        limit = int(request.args.get("limit") or 25)
        limit = max(1, min(limit, 100))

        client = HubSpotClient()
        owner_id = client.get_owner_id_by_email(owner_email)
        deals = client.search_closed_deals(owner_id, stage_ids=[])
        samples = []
        stages = {}
        pipelines = {}
        for deal in deals[:limit]:
            props = deal.get("properties") or {}
            stage = props.get("dealstage") or ""
            pipeline = props.get("pipeline") or ""
            if stage:
                stages[stage] = stages.get(stage, 0) + 1
            if pipeline:
                pipelines[pipeline] = pipelines.get(pipeline, 0) + 1
            samples.append({
                "deal_id": deal.get("id"),
                "dealname": props.get("dealname"),
                "dealstage": stage,
                "pipeline": pipeline,
                "closedate": props.get("closedate"),
                "lastmodified": props.get("hs_lastmodifieddate"),
            })

        return jsonify({
            "success": True,
            "owner_email": owner_email,
            "owner_id": owner_id,
            "deals_found": len(deals),
            "stages": stages,
            "pipelines": pipelines,
            "sample_deals": samples,
        })
    except HubSpotError as exc:
        return jsonify({
            "success": False,
            "token_configured": bool(os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")),
            "error": str(exc),
        }), 502
    except Exception as exc:
        logging.exception("HubSpot deals debug failed")
        return jsonify({
            "success": False,
            "token_configured": bool(os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")),
            "error": str(exc),
        }), 500


def _find_existing_account(cursor, payload):
    hubspot_deal_id = (payload.get("hubspot_deal_id") or "").strip()
    hubspot_company_id = (payload.get("hubspot_company_id") or "").strip()
    hubspot_contact_id = (payload.get("hubspot_contact_id") or "").strip()
    contact_email = (payload.get("mail") or "").strip().lower()
    client_name_candidates = _account_name_candidates(payload.get("name"))

    if hubspot_deal_id:
        cursor.execute(
            "SELECT account_id FROM account WHERE hubspot_deal_id = %s LIMIT 1",
            (hubspot_deal_id,),
        )
        row = cursor.fetchone()
        if row:
            return row

    if hubspot_company_id:
        cursor.execute(
            "SELECT account_id FROM account WHERE hubspot_company_id = %s LIMIT 1",
            (hubspot_company_id,),
        )
        row = cursor.fetchone()
        if row:
            return row

    if hubspot_contact_id:
        cursor.execute(
            "SELECT account_id FROM account WHERE hubspot_contact_id = %s LIMIT 1",
            (hubspot_contact_id,),
        )
        row = cursor.fetchone()
        if row:
            return row

    if contact_email:
        cursor.execute(
            """
            SELECT account_id
            FROM account
            WHERE LOWER(TRIM(mail)) = LOWER(TRIM(%s))
            LIMIT 1
            """,
            (contact_email,),
        )
        row = cursor.fetchone()
        if row:
            return row

    for client_name in client_name_candidates:
        cursor.execute(
            """
            SELECT account_id
            FROM account
            WHERE LOWER(TRIM(client_name)) = LOWER(TRIM(%s))
            LIMIT 1
            """,
            (client_name,),
        )
        row = cursor.fetchone()
        if row:
            return row
    return None


def _preview_existing_account(cursor, payload):
    existing = _find_existing_account(cursor, payload)
    if not existing:
        return None
    account_id = existing["account_id"] if isinstance(existing, dict) else existing[0]
    cursor.execute(
        """
        SELECT account_id, client_name, account_manager, where_come_from,
               hubspot_deal_id, hubspot_company_id, hubspot_contact_id
        FROM account
        WHERE account_id = %s
        """,
        (account_id,),
    )
    return cursor.fetchone()


def _link_existing_account_to_hubspot(cursor, account_id, payload):
    now = datetime.now(timezone.utc)
    # Los ids se guardan .strip()eados porque _find_existing_account los BUSCA
    # .strip()eados: escribir el valor crudo hace que la proxima corrida busque en una
    # fila y escriba en otra.
    values = _clip_account_values({
        "size": payload.get("size"),
        "timezone": payload.get("timezone"),
        "state": payload.get("state"),
        "website": payload.get("website"),
        "linkedin": payload.get("linkedin"),
        "comments": payload.get("about"),
        "mail": payload.get("mail"),
        "where_come_from": _normalize_lead_source(payload.get("where_come_from")),
        "lead_source_detail": payload.get("lead_source_detail"),
        "conversion_channel": payload.get("conversion_channel"),
        "referal_source": payload.get("referal_source"),
        "industry": payload.get("industry"),
        "outsource": _normalize_outsource_value(payload.get("outsource")),
        "pain_points": payload.get("pain_points"),
        "contract": payload.get("contract"),
        "position": payload.get("position"),
        "type": payload.get("type"),
        "name": payload.get("contact_name"),
        "surname": payload.get("contact_surname"),
        "account_manager": payload.get("account_manager"),
        "credit_loop": _normalize_credit_loop_value(payload.get("credit_loop")),
        "vintti_ai": _normalize_boolean_value(payload.get("vintti_ai")),
        "hubspot_deal_id": (payload.get("hubspot_deal_id") or "").strip(),
        "hubspot_company_id": (payload.get("hubspot_company_id") or "").strip(),
        "hubspot_contact_id": (payload.get("hubspot_contact_id") or "").strip(),
    })
    cursor.execute(
        """
        UPDATE account
        SET size = COALESCE(NULLIF(%s, ''), size),
            timezone = COALESCE(NULLIF(%s, ''), timezone),
            state = COALESCE(NULLIF(%s, ''), state),
            website = COALESCE(NULLIF(%s, ''), website),
            linkedin = COALESCE(NULLIF(%s, ''), linkedin),
            comments = COALESCE(NULLIF(%s, ''), comments),
            mail = COALESCE(NULLIF(%s, ''), mail),
            where_come_from = COALESCE(NULLIF(%s, ''), where_come_from),
            lead_source_detail = COALESCE(NULLIF(%s, ''), lead_source_detail),
            conversion_channel = COALESCE(NULLIF(%s, ''), conversion_channel),
            referal_source = COALESCE(NULLIF(%s, ''), referal_source),
            industry = COALESCE(NULLIF(%s, ''), industry),
            outsource = COALESCE(NULLIF(%s, ''), outsource),
            pain_points = COALESCE(NULLIF(%s, ''), pain_points),
            contract = COALESCE(NULLIF(%s, ''), contract),
            position = COALESCE(NULLIF(%s, ''), position),
            type = COALESCE(NULLIF(%s, ''), type),
            name = COALESCE(NULLIF(%s, ''), name),
            surname = COALESCE(NULLIF(%s, ''), surname),
            account_manager = COALESCE(NULLIF(%s, ''), account_manager),
            credit_loop = COALESCE(NULLIF(%s, ''), credit_loop),
            vintti_ai = %s,
            hubspot_deal_id = COALESCE(NULLIF(hubspot_deal_id, ''), NULLIF(%s, '')),
            hubspot_company_id = COALESCE(NULLIF(hubspot_company_id, ''), NULLIF(%s, '')),
            hubspot_contact_id = COALESCE(NULLIF(hubspot_contact_id, ''), NULLIF(%s, '')),
            hubspot_synced_at = %s
        WHERE account_id = %s
        """,
        (
            values["size"],
            values["timezone"],
            values["state"],
            values["website"],
            values["linkedin"],
            values["comments"],
            values["mail"],
            values["where_come_from"],
            values["lead_source_detail"],
            values["conversion_channel"],
            values["referal_source"],
            values["industry"],
            values["outsource"],
            values["pain_points"],
            values["contract"],
            values["position"],
            values["type"],
            values["name"],
            values["surname"],
            values["account_manager"],
            values["credit_loop"],
            values["vintti_ai"],
            values["hubspot_deal_id"],
            values["hubspot_company_id"],
            values["hubspot_contact_id"],
            now,
            account_id,
        ),
    )


def _normalize_preview_row(deal, payload, existing, lead_life_property=None):
    deal_props = deal.get("properties") or {}
    return {
        "action": "already_exists" if existing else "would_create",
        "hubspot_deal_id": payload.get("hubspot_deal_id"),
        "hubspot_company_id": payload.get("hubspot_company_id"),
        "client_name": payload.get("name"),
        "hubspot_company_name": payload.get("_hubspot_company_name") or None,
        "crm_account_id": existing.get("account_id") if existing else None,
        "crm_client_name": existing.get("client_name") if existing else None,
        "account_fields": _preview_account_fields(payload),
        "dealname": deal_props.get("dealname"),
        "dealstage": deal_props.get("dealstage"),
        "pipeline": deal_props.get("pipeline"),
        "closedate": deal_props.get("closedate"),
        "lead_life_property": lead_life_property,
        "lead_life": deal_props.get(lead_life_property) if lead_life_property else None,
        "existing_account": existing,
    }


def _normalize_contact_preview_row(contact, deal, payload, existing, lead_life_property, meeting_datetime_property=None):
    contact_props = contact.get("properties") or {}
    deal_props = (deal or {}).get("properties") or {}
    client_name = payload.get("name")
    hubspot_company_name = payload.get("_hubspot_company_name") or None
    contact_name = " ".join(
        part for part in [
            contact_props.get("firstname") or "",
            contact_props.get("lastname") or "",
        ]
        if part
    ).strip()
    return {
        "action": "already_exists" if existing else "would_create",
        "hubspot_contact_record_id": contact.get("id"),
        "hubspot_deal_record_id": (deal or {}).get("id"),
        "hubspot_contact_id": payload.get("hubspot_contact_id"),
        "hubspot_company_id": payload.get("hubspot_company_id"),
        "hubspot_deal_id": payload.get("hubspot_deal_id"),
        "client_name": client_name,
        "hubspot_company_name": hubspot_company_name,
        "crm_account_id": existing.get("account_id") if existing else None,
        "crm_client_name": existing.get("client_name") if existing else None,
        "account_fields": _preview_account_fields(payload),
        "contact_email": contact_props.get("email"),
        "contact_name": contact_name,
        "dealname": deal_props.get("dealname"),
        "dealstage": deal_props.get("dealstage"),
        "pipeline": deal_props.get("pipeline"),
        "meeting_datetime_property": meeting_datetime_property,
        "meeting_datetime": contact_props.get(meeting_datetime_property) if meeting_datetime_property else None,
        "lead_life_property": lead_life_property,
        "lead_life": contact_props.get(lead_life_property),
        "existing_account": existing,
    }


@bp.route("/hubspot/preview/mariano-sql-contacts", methods=["GET", "OPTIONS"])
def preview_mariano_sql_contacts():
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        owner_email = (
            request.args.get("owner_email")
            or os.environ.get("HUBSPOT_MARIANO_EMAIL")
            or DEFAULT_MARIANO_EMAIL
        ).strip().lower()
        lead_life_property = (
            request.args.get("lead_life_property")
            or os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY")
            or "lead_life"
        ).strip()
        lead_life_value = (
            request.args.get("lead_life_value")
            or os.environ.get("HUBSPOT_LEAD_LIFE_SQL_VALUE")
            or "SQL (AE)"
        ).strip()

        client = HubSpotClient()
        property_maps = _resolve_account_property_maps(client)
        meeting_datetime_property = (
            request.args.get("meeting_datetime_property")
            or os.environ.get("HUBSPOT_MEETING_DATETIME_PROPERTY")
            or _resolve_meeting_datetime_property(client)
            or ""
        ).strip()
        if not meeting_datetime_property:
            raise HubSpotError("Could not resolve HubSpot meeting date & time property on contacts")

        contact_extra_properties = [lead_life_property, meeting_datetime_property] + _mapped_property_names(property_maps, "contacts")
        company_extra_properties = _mapped_property_names(property_maps, "companies")
        deal_extra_properties = _mapped_property_names(property_maps, "deals")
        owner_id = client.get_owner_id_by_email(owner_email)
        contacts = client.search_contacts(
            [
                {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(owner_id)},
                {"propertyName": lead_life_property, "operator": "EQ", "value": lead_life_value},
                {"propertyName": meeting_datetime_property, "operator": "HAS_PROPERTY"},
            ],
            extra_properties=contact_extra_properties,
        )

        rows = []
        conn = get_connection()
        try:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    _ensure_hubspot_account_columns(cursor)
                    for contact_summary in contacts:
                        contact_id = str(contact_summary.get("id") or "")
                        contact = client.get_contact(
                            contact_id,
                            extra_properties=contact_extra_properties,
                            associations=["companies", "deals"],
                        )
                        company_ids = association_ids(contact, "companies")
                        deal_ids = association_ids(contact, "deals")
                        company = client.get_company(company_ids[0], extra_properties=company_extra_properties) if company_ids else None
                        deal = client.get_deal_with_associations(deal_ids[0], extra_properties=deal_extra_properties) if deal_ids else {}
                        payload = build_account_payload(
                            deal,
                            company=company,
                            contact=contact,
                            owner_email=owner_email,
                        )
                        payload = _apply_account_field_overrides(
                            payload,
                            contact=contact,
                            company=company,
                            deal=deal,
                            property_maps=property_maps,
                        )
                        existing = _preview_existing_account(cursor, payload)
                        rows.append(_normalize_contact_preview_row(
                            contact,
                            deal,
                            payload,
                            existing,
                            lead_life_property,
                            meeting_datetime_property,
                        ))
        finally:
            conn.close()

        return jsonify({
            "success": True,
            "owner_email": owner_email,
            "owner_id": owner_id,
            "meeting_datetime_property": meeting_datetime_property,
            "lead_life_property": lead_life_property,
            "lead_life_value": lead_life_value,
            "property_maps": property_maps,
            "contacts_found": len(contacts),
            "would_create": sum(1 for row in rows if row["action"] == "would_create"),
            "already_exists": sum(1 for row in rows if row["action"] == "already_exists"),
            "items": rows,
        })
    except HubSpotError as exc:
        return jsonify({
            "success": False,
            "token_configured": bool(os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")),
            "error": str(exc),
        }), 502
    except Exception as exc:
        logging.exception("HubSpot SQL contact preview failed")
        return jsonify({
            "success": False,
            "token_configured": bool(os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")),
            "error": str(exc),
        }), 500


@bp.route("/hubspot/preview/mql-contacts", methods=["GET", "OPTIONS"])
def preview_mql_contacts():
    """Read-only preview de MQLs desde HubSpot (todos los owners por defecto).

    Espejo de preview_mariano_sql_contacts con tres diferencias:
      - lead_life = "MQL (AE)" (override por ?lead_life_value=).
      - SIN filtro HAS_PROPERTY de meeting (un MQL puede no tener meeting aún).
      - owner opcional: filtra por owner solo si llega ?owner_email=.
    Agrega las propiedades MQL (date_of_meeting_scheduled, mql_ae_lost_reason)
    a las pedidas y las expone por fila. No escribe a la DB.
    """
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        owner_email = (request.args.get("owner_email") or "").strip().lower()
        lead_life_property = (
            request.args.get("lead_life_property")
            or os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY")
            or "lead_life"
        ).strip()
        lead_life_value = (
            request.args.get("lead_life_value")
            or os.environ.get("HUBSPOT_LEAD_LIFE_MQL_VALUE")
            or "MQL (AE)"
        ).strip()
        mql_date_property = (
            request.args.get("mql_date_property")
            or os.environ.get("HUBSPOT_MQL_DATE_PROPERTY")
            or "date_of_meeting_scheduled"
        ).strip()
        mql_lost_reason_property = (
            request.args.get("mql_lost_reason_property")
            or os.environ.get("HUBSPOT_MQL_LOST_REASON_PROPERTY")
            or "mql_ae_lost_reason"
        ).strip()

        client = HubSpotClient()
        property_maps = _resolve_account_property_maps(client)

        contact_extra_properties = (
            [lead_life_property, mql_date_property, mql_lost_reason_property]
            + _mapped_property_names(property_maps, "contacts")
        )
        company_extra_properties = _mapped_property_names(property_maps, "companies")
        deal_extra_properties = _mapped_property_names(property_maps, "deals")

        search_filters = [
            {"propertyName": lead_life_property, "operator": "EQ", "value": lead_life_value},
        ]
        owner_id = None
        if owner_email:
            owner_id = client.get_owner_id_by_email(owner_email)
            search_filters.insert(0, {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(owner_id)})

        contacts = client.search_contacts(
            search_filters,
            extra_properties=contact_extra_properties,
        )

        rows = []
        conn = get_connection()
        try:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    _ensure_hubspot_account_columns(cursor)
                    for contact_summary in contacts:
                        contact_id = str(contact_summary.get("id") or "")
                        contact = client.get_contact(
                            contact_id,
                            extra_properties=contact_extra_properties,
                            associations=["companies", "deals"],
                        )
                        company_ids = association_ids(contact, "companies")
                        deal_ids = association_ids(contact, "deals")
                        company = client.get_company(company_ids[0], extra_properties=company_extra_properties) if company_ids else None
                        deal = client.get_deal_with_associations(deal_ids[0], extra_properties=deal_extra_properties) if deal_ids else {}
                        payload = build_account_payload(
                            deal,
                            company=company,
                            contact=contact,
                            owner_email=owner_email or None,
                        )
                        payload = _apply_account_field_overrides(
                            payload,
                            contact=contact,
                            company=company,
                            deal=deal,
                            property_maps=property_maps,
                        )
                        existing = _preview_existing_account(cursor, payload)
                        row = _normalize_contact_preview_row(
                            contact,
                            deal,
                            payload,
                            existing,
                            lead_life_property,
                        )
                        contact_props = contact.get("properties") or {}
                        row["mql_date_property"] = mql_date_property
                        row["mql_date_of_meeting_scheduled"] = contact_props.get(mql_date_property)
                        row["mql_lost_reason_property"] = mql_lost_reason_property
                        row["mql_ae_lost_reason"] = contact_props.get(mql_lost_reason_property)
                        rows.append(row)
        finally:
            conn.close()

        return jsonify({
            "success": True,
            "owner_email": owner_email or None,
            "owner_id": owner_id,
            "lead_life_property": lead_life_property,
            "lead_life_value": lead_life_value,
            "mql_date_property": mql_date_property,
            "mql_lost_reason_property": mql_lost_reason_property,
            "property_maps": property_maps,
            "contacts_found": len(contacts),
            "would_create": sum(1 for row in rows if row["action"] == "would_create"),
            "already_exists": sum(1 for row in rows if row["action"] == "already_exists"),
            "items": rows,
        })
    except HubSpotError as exc:
        return jsonify({
            "success": False,
            "token_configured": bool(os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")),
            "error": str(exc),
        }), 502
    except Exception as exc:
        logging.exception("HubSpot MQL contact preview failed")
        return jsonify({
            "success": False,
            "token_configured": bool(os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")),
            "error": str(exc),
        }), 500


@bp.route("/hubspot/sync/mariano-sql-contacts", methods=["POST", "OPTIONS"])
def sync_mariano_sql_contacts():
    if request.method == "OPTIONS":
        return ("", 204)

    unauthorized = _require_sync_secret()
    if unauthorized:
        return unauthorized

    try:
        body = request.get_json(silent=True) or {}
        owner_email = (
            body.get("owner_email")
            or os.environ.get("HUBSPOT_MARIANO_EMAIL")
            or DEFAULT_MARIANO_EMAIL
        ).strip().lower()
        lead_life_property = (
            body.get("lead_life_property")
            or os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY")
            or "lead_life"
        ).strip()
        lead_life_value = (
            body.get("lead_life_value")
            or os.environ.get("HUBSPOT_LEAD_LIFE_SQL_VALUE")
            or "SQL (AE)"
        ).strip()

        client = HubSpotClient()
        property_maps = _resolve_account_property_maps(client)
        meeting_datetime_property = (
            body.get("meeting_datetime_property")
            or os.environ.get("HUBSPOT_MEETING_DATETIME_PROPERTY")
            or _resolve_meeting_datetime_property(client)
            or ""
        ).strip()
        if not meeting_datetime_property:
            raise HubSpotError("Could not resolve HubSpot meeting date & time property on contacts")

        contact_extra_properties = [lead_life_property, meeting_datetime_property] + _mapped_property_names(property_maps, "contacts")
        company_extra_properties = _mapped_property_names(property_maps, "companies")
        deal_extra_properties = _mapped_property_names(property_maps, "deals")
        owner_id = client.get_owner_id_by_email(owner_email)
        contacts = client.search_contacts(
            [
                {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(owner_id)},
                {"propertyName": lead_life_property, "operator": "EQ", "value": lead_life_value},
                {"propertyName": meeting_datetime_property, "operator": "HAS_PROPERTY"},
            ],
            extra_properties=contact_extra_properties,
        )

        synced = []
        errors = []
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                _ensure_hubspot_account_columns(cursor)
                # Commitear el DDL YA. Si queda abierto dentro de la transaccion del
                # loop, el ACCESS EXCLUSIVE sobre `account` se retiene los minutos que
                # dura el sync y traba cualquier otra request que toque la tabla.
                conn.commit()

                for contact_summary in contacts:
                    contact_id = str(contact_summary.get("id") or "")
                    # Sin este reset, si falla antes de armarse, el except leeria el
                    # payload del contacto ANTERIOR (o tiraria NameError en la 1ra vuelta).
                    payload = None
                    try:
                        contact = client.get_contact(
                            contact_id,
                            extra_properties=contact_extra_properties,
                            associations=["companies", "deals"],
                        )
                        company_ids = association_ids(contact, "companies")
                        deal_ids = association_ids(contact, "deals")
                        company = client.get_company(company_ids[0], extra_properties=company_extra_properties) if company_ids else None
                        deal = client.get_deal_with_associations(deal_ids[0], extra_properties=deal_extra_properties) if deal_ids else {}
                        payload = build_account_payload(
                            deal,
                            company=company,
                            contact=contact,
                            owner_email=owner_email,
                        )
                        payload = _apply_account_field_overrides(
                            payload,
                            contact=contact,
                            company=company,
                            deal=deal,
                            property_maps=property_maps,
                        )
                        existing = _preview_existing_account(cursor, payload)
                        if existing:
                            account_id = existing["account_id"]
                            _link_existing_account_to_hubspot(cursor, account_id, payload)
                            action = "linked"
                        else:
                            result = _insert_or_update_account(cursor, payload)
                            account_id = result["account_id"]
                            # _insert_or_update_account rehace la busqueda por su cuenta
                            # y puede devolver "updated"; hardcodear "created" inflaba el
                            # numero que ve la owner en el alert.
                            action = result["action"]

                        contact_props = contact.get("properties") or {}
                        # R1: anclar el SQL por la fecha REAL del meeting (igual que
                        # Marketing). Guardamos meeting_date___time en account.sql_meeting_date
                        # para AMBAS ramas (creado y linkeado), porque el path "linked" no
                        # pasa por _insert_or_update_account.
                        sql_meeting_d = _parse_hubspot_date(contact_props.get(meeting_datetime_property))
                        if sql_meeting_d is not None:
                            cursor.execute(
                                "UPDATE account SET sql_meeting_date = %s WHERE account_id = %s",
                                (sql_meeting_d, account_id),
                            )
                        # UNA TRANSACCION POR CONTACTO. Antes todo el loop compartia una
                        # sola: el primer error de Postgres abortaba la transaccion, los
                        # contactos siguientes morian con InFailedSqlTransaction, y el
                        # COMMIT final sobre una transaccion abortada equivale a ROLLBACK,
                        # asi que hasta los que habian funcionado se perdian en silencio.
                        conn.commit()
                        synced.append({
                            "contact_id": contact_id,
                            "deal_id": payload.get("hubspot_deal_id"),
                            "account_id": account_id,
                            "action": action,
                            "client_name": payload.get("name"),
                            "contact_email": contact_props.get("email"),
                            "meeting_datetime": contact_props.get(meeting_datetime_property),
                            "sql_meeting_date": sql_meeting_d.isoformat() if sql_meeting_d else None,
                            "lead_life": contact_props.get(lead_life_property),
                        })
                    except Exception as exc:
                        _rollback_quietly(conn, "contact %s" % contact_id)
                        logging.exception("HubSpot contact sync failed for contact %s", contact_id)
                        errors.append(_error_record(
                            exc,
                            contact_id=contact_id,
                            client_name=(payload or {}).get("name"),
                        ))
        finally:
            conn.close()

        return jsonify({
            "success": True,
            "owner_email": owner_email,
            "owner_id": owner_id,
            "meeting_datetime_property": meeting_datetime_property,
            "lead_life_property": lead_life_property,
            "lead_life_value": lead_life_value,
            "property_maps": property_maps,
            "contacts_found": len(contacts),
            "created": sum(1 for item in synced if item["action"] == "created"),
            "linked": sum(1 for item in synced if item["action"] == "linked"),
            "updated": sum(1 for item in synced if item["action"] == "updated"),
            "errors": errors,
            "synced": synced,
        })
    except HubSpotError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502
    except Exception as exc:
        logging.exception("HubSpot SQL contact sync failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/hubspot/preview/mariano-closed-leads", methods=["GET", "OPTIONS"])
def preview_mariano_closed_leads():
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        owner_email = (
            request.args.get("owner_email")
            or os.environ.get("HUBSPOT_MARIANO_EMAIL")
            or DEFAULT_MARIANO_EMAIL
        ).strip().lower()
        stage_ids = _parse_stage_ids(
            request.args.get("stage_ids"),
            os.environ.get("HUBSPOT_CLOSED_DEAL_STAGE_IDS", "closedwon"),
        )
        pipeline_id = request.args.get("pipeline_id") or os.environ.get("HUBSPOT_PIPELINE_ID")

        client = HubSpotClient()
        property_maps = _resolve_account_property_maps(client)
        contact_extra_properties = _mapped_property_names(property_maps, "contacts")
        company_extra_properties = _mapped_property_names(property_maps, "companies")
        deal_extra_properties = _mapped_property_names(property_maps, "deals")
        owner_id = client.get_owner_id_by_email(owner_email)
        deals = client.search_closed_deals(
            owner_id,
            stage_ids=stage_ids,
            pipeline_id=pipeline_id,
            extra_properties=deal_extra_properties,
        )

        rows = []
        conn = get_connection()
        try:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    _ensure_hubspot_account_columns(cursor)
                    for deal_summary in deals:
                        deal_id = str(deal_summary.get("id") or "")
                        deal = client.get_deal_with_associations(deal_id, extra_properties=deal_extra_properties)
                        company_ids = association_ids(deal, "companies")
                        contact_ids = association_ids(deal, "contacts")
                        company = client.get_company(company_ids[0], extra_properties=company_extra_properties) if company_ids else None
                        contact = client.get_contact(contact_ids[0], extra_properties=contact_extra_properties) if contact_ids else None
                        payload = build_account_payload(
                            deal,
                            company=company,
                            contact=contact,
                            owner_email=owner_email,
                        )
                        payload = _apply_account_field_overrides(
                            payload,
                            contact=contact,
                            company=company,
                            deal=deal,
                            property_maps=property_maps,
                        )
                        existing = _preview_existing_account(cursor, payload)
                        rows.append(_normalize_preview_row(deal, payload, existing))
        finally:
            conn.close()

        return jsonify({
            "success": True,
            "owner_email": owner_email,
            "owner_id": owner_id,
            "stage_ids": stage_ids,
            "pipeline_id": pipeline_id,
            "deals_found": len(deals),
            "would_create": sum(1 for row in rows if row["action"] == "would_create"),
            "already_exists": sum(1 for row in rows if row["action"] == "already_exists"),
            "items": rows,
        })
    except HubSpotError as exc:
        return jsonify({
            "success": False,
            "token_configured": bool(os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")),
            "error": str(exc),
        }), 502
    except Exception as exc:
        logging.exception("HubSpot preview failed")
        return jsonify({
            "success": False,
            "token_configured": bool(os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")),
            "error": str(exc),
        }), 500


@bp.route("/hubspot/preview/mariano-sql-leads", methods=["GET", "OPTIONS"])
def preview_mariano_sql_leads():
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        owner_email = (
            request.args.get("owner_email")
            or os.environ.get("HUBSPOT_MARIANO_EMAIL")
            or DEFAULT_MARIANO_EMAIL
        ).strip().lower()
        lead_life_property = (
            request.args.get("lead_life_property")
            or os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY")
            or "lead_life"
        ).strip()
        lead_life_value = (
            request.args.get("lead_life_value")
            or os.environ.get("HUBSPOT_LEAD_LIFE_SQL_VALUE")
            or "SQL"
        ).strip()
        pipeline_id = request.args.get("pipeline_id") or os.environ.get("HUBSPOT_PIPELINE_ID")

        client = HubSpotClient()
        property_maps = _resolve_account_property_maps(client)
        contact_extra_properties = _mapped_property_names(property_maps, "contacts")
        company_extra_properties = _mapped_property_names(property_maps, "companies")
        deal_extra_properties = [lead_life_property] + _mapped_property_names(property_maps, "deals")
        owner_id = client.get_owner_id_by_email(owner_email)
        filters = [
            {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(owner_id)},
            {"propertyName": lead_life_property, "operator": "EQ", "value": lead_life_value},
        ]
        if pipeline_id:
            filters.append({"propertyName": "pipeline", "operator": "EQ", "value": str(pipeline_id)})
        deals = client.search_deals(filters, extra_properties=deal_extra_properties)

        rows = []
        conn = get_connection()
        try:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    _ensure_hubspot_account_columns(cursor)
                    for deal_summary in deals:
                        deal_id = str(deal_summary.get("id") or "")
                        deal = client.get_deal_with_associations(
                            deal_id,
                            extra_properties=deal_extra_properties,
                        )
                        company_ids = association_ids(deal, "companies")
                        contact_ids = association_ids(deal, "contacts")
                        company = client.get_company(company_ids[0], extra_properties=company_extra_properties) if company_ids else None
                        contact = client.get_contact(contact_ids[0], extra_properties=contact_extra_properties) if contact_ids else None
                        payload = build_account_payload(
                            deal,
                            company=company,
                            contact=contact,
                            owner_email=owner_email,
                        )
                        payload = _apply_account_field_overrides(
                            payload,
                            contact=contact,
                            company=company,
                            deal=deal,
                            property_maps=property_maps,
                        )
                        existing = _preview_existing_account(cursor, payload)
                        rows.append(_normalize_preview_row(
                            deal,
                            payload,
                            existing,
                            lead_life_property=lead_life_property,
                        ))
        finally:
            conn.close()

        return jsonify({
            "success": True,
            "owner_email": owner_email,
            "owner_id": owner_id,
            "lead_life_property": lead_life_property,
            "lead_life_value": lead_life_value,
            "pipeline_id": pipeline_id,
            "deals_found": len(deals),
            "would_create": sum(1 for row in rows if row["action"] == "would_create"),
            "already_exists": sum(1 for row in rows if row["action"] == "already_exists"),
            "items": rows,
        })
    except HubSpotError as exc:
        return jsonify({
            "success": False,
            "token_configured": bool(os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")),
            "error": str(exc),
            "hint": "If HubSpot says a property does not exist, try the internal property name with ?lead_life_property=...",
        }), 502
    except Exception as exc:
        logging.exception("HubSpot SQL lead preview failed")
        return jsonify({
            "success": False,
            "token_configured": bool(os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")),
            "error": str(exc),
        }), 500


def _insert_or_update_account(cursor, payload):
    existing = _find_existing_account(cursor, payload)
    now = datetime.now(timezone.utc)
    values = {
        "client_name": payload.get("name"),
        "size": payload.get("size"),
        "timezone": payload.get("timezone"),
        "state": payload.get("state"),
        "website": payload.get("website"),
        "linkedin": payload.get("linkedin"),
        "comments": payload.get("about"),
        "mail": payload.get("mail"),
        "where_come_from": _normalize_lead_source(payload.get("where_come_from")),
        "lead_source_detail": payload.get("lead_source_detail"),
        "conversion_channel": payload.get("conversion_channel"),
        "referal_source": payload.get("referal_source"),
        "industry": payload.get("industry"),
        "outsource": _normalize_outsource_value(payload.get("outsource")),
        "pain_points": payload.get("pain_points"),
        "contract": payload.get("contract"),
        "position": payload.get("position"),
        "type": payload.get("type"),
        "name": payload.get("contact_name"),
        "surname": payload.get("contact_surname"),
        "account_manager": payload.get("account_manager"),
        # .strip() para que coincida con como los BUSCA _find_existing_account.
        "hubspot_deal_id": (payload.get("hubspot_deal_id") or "").strip(),
        "hubspot_company_id": (payload.get("hubspot_company_id") or "").strip(),
        "hubspot_contact_id": (payload.get("hubspot_contact_id") or "").strip(),
        "credit_loop": _normalize_credit_loop_value(payload.get("credit_loop")),
        "vintti_ai": _normalize_boolean_value(payload.get("vintti_ai")),
        "hubspot_synced_at": now,
    }
    values = _clip_account_values(values)

    if existing:
        account_id = existing["account_id"] if isinstance(existing, dict) else existing[0]
        cursor.execute(
            """
            UPDATE account
            SET size = COALESCE(NULLIF(%(size)s, ''), size),
                timezone = COALESCE(NULLIF(%(timezone)s, ''), timezone),
                state = COALESCE(NULLIF(%(state)s, ''), state),
                website = COALESCE(NULLIF(%(website)s, ''), website),
                linkedin = COALESCE(NULLIF(%(linkedin)s, ''), linkedin),
                comments = COALESCE(NULLIF(%(comments)s, ''), comments),
                mail = COALESCE(NULLIF(%(mail)s, ''), mail),
                where_come_from = COALESCE(NULLIF(%(where_come_from)s, ''), where_come_from),
                lead_source_detail = COALESCE(NULLIF(%(lead_source_detail)s, ''), lead_source_detail),
                conversion_channel = COALESCE(NULLIF(%(conversion_channel)s, ''), conversion_channel),
                referal_source = COALESCE(NULLIF(%(referal_source)s, ''), referal_source),
                industry = COALESCE(NULLIF(%(industry)s, ''), industry),
                outsource = COALESCE(NULLIF(%(outsource)s, ''), outsource),
                pain_points = COALESCE(NULLIF(%(pain_points)s, ''), pain_points),
                contract = COALESCE(NULLIF(%(contract)s, ''), contract),
                position = COALESCE(NULLIF(%(position)s, ''), position),
                type = COALESCE(NULLIF(%(type)s, ''), type),
                name = COALESCE(NULLIF(%(name)s, ''), name),
                surname = COALESCE(NULLIF(%(surname)s, ''), surname),
                account_manager = COALESCE(NULLIF(%(account_manager)s, ''), account_manager),
                credit_loop = COALESCE(NULLIF(%(credit_loop)s, ''), credit_loop),
                vintti_ai = %(vintti_ai)s,
                hubspot_deal_id = COALESCE(NULLIF(%(hubspot_deal_id)s, ''), hubspot_deal_id),
                hubspot_company_id = COALESCE(NULLIF(%(hubspot_company_id)s, ''), hubspot_company_id),
                hubspot_contact_id = COALESCE(NULLIF(%(hubspot_contact_id)s, ''), hubspot_contact_id),
                hubspot_synced_at = %(hubspot_synced_at)s
            WHERE account_id = %(account_id)s
            """,
            {**values, "account_id": account_id},
        )
        return {"account_id": account_id, "action": "updated"}

    cursor.execute(
        """
        INSERT INTO account (
            client_name, size, timezone, state,
            website, linkedin, comments, mail,
            where_come_from, lead_source_detail, conversion_channel, referal_source,
            industry, outsource, pain_points, contract, position, type,
            name, surname, account_manager, credit_loop, vintti_ai,
            hubspot_deal_id, hubspot_company_id, hubspot_contact_id, hubspot_synced_at
        ) VALUES (
            %(client_name)s, %(size)s, %(timezone)s, %(state)s,
            %(website)s, %(linkedin)s, %(comments)s, %(mail)s,
            COALESCE(%(where_come_from)s, 'HubSpot'), %(lead_source_detail)s, %(conversion_channel)s, %(referal_source)s,
            %(industry)s, %(outsource)s, %(pain_points)s, %(contract)s, %(position)s, COALESCE(%(type)s, 'NA'),
            %(name)s, %(surname)s, COALESCE(%(account_manager)s, %(default_account_manager)s), %(credit_loop)s, %(vintti_ai)s,
            %(hubspot_deal_id)s, %(hubspot_company_id)s, %(hubspot_contact_id)s, %(hubspot_synced_at)s
        )
        RETURNING account_id
        """,
        {**values, "default_account_manager": DEFAULT_MARIANO_EMAIL},
    )
    row = cursor.fetchone()
    account_id = row["account_id"] if isinstance(row, dict) else row[0]
    return {"account_id": account_id, "action": "created"}


@bp.route("/hubspot/sync/mariano-closed-leads", methods=["POST", "OPTIONS"])
def sync_mariano_closed_leads():
    if request.method == "OPTIONS":
        return ("", 204)

    unauthorized = _require_sync_secret()
    if unauthorized:
        return unauthorized

    try:
        body = request.get_json(silent=True) or {}
        owner_email = (
            body.get("owner_email")
            or os.environ.get("HUBSPOT_MARIANO_EMAIL")
            or DEFAULT_MARIANO_EMAIL
        ).strip().lower()
        stage_ids = _parse_stage_ids(
            body.get("stage_ids"),
            os.environ.get("HUBSPOT_CLOSED_DEAL_STAGE_IDS", "closedwon"),
        )
        pipeline_id = body.get("pipeline_id") or os.environ.get("HUBSPOT_PIPELINE_ID")
        modified_after_ms = hubspot_datetime_to_ms(
            body.get("modified_after") or os.environ.get("HUBSPOT_SYNC_MODIFIED_AFTER")
        )

        client = HubSpotClient()
        property_maps = _resolve_account_property_maps(client)
        contact_extra_properties = _mapped_property_names(property_maps, "contacts")
        company_extra_properties = _mapped_property_names(property_maps, "companies")
        deal_extra_properties = _mapped_property_names(property_maps, "deals")
        owner_id = client.get_owner_id_by_email(owner_email)
        deals = client.search_closed_deals(
            owner_id,
            stage_ids=stage_ids,
            pipeline_id=pipeline_id,
            modified_after_ms=modified_after_ms,
            extra_properties=deal_extra_properties,
        )

        synced = []
        errors = []
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                _ensure_hubspot_account_columns(cursor)
                conn.commit()   # soltar el ACCESS EXCLUSIVE antes del loop

                for deal_summary in deals:
                    deal_id = str(deal_summary.get("id") or "")
                    payload = None
                    try:
                        deal = client.get_deal_with_associations(deal_id, extra_properties=deal_extra_properties)
                        company_ids = association_ids(deal, "companies")
                        contact_ids = association_ids(deal, "contacts")
                        company = client.get_company(company_ids[0], extra_properties=company_extra_properties) if company_ids else None
                        contact = client.get_contact(contact_ids[0], extra_properties=contact_extra_properties) if contact_ids else None
                        payload = build_account_payload(
                            deal,
                            company=company,
                            contact=contact,
                            owner_email=owner_email,
                        )
                        payload = _apply_account_field_overrides(
                            payload,
                            contact=contact,
                            company=company,
                            deal=deal,
                            property_maps=property_maps,
                        )
                        result = _insert_or_update_account(cursor, payload)
                        # Una transaccion por deal: un error no puede abortar el resto
                        # del lote ni descartar lo ya hecho. Ver sync_mariano_sql_contacts.
                        conn.commit()
                        synced.append({
                            "deal_id": deal_id,
                            "account_id": result["account_id"],
                            "action": result["action"],
                            "client_name": payload.get("name"),
                        })
                    except Exception as exc:
                        _rollback_quietly(conn, "deal %s" % deal_id)
                        logging.exception("HubSpot deal sync failed for deal %s", deal_id)
                        errors.append(_error_record(
                            exc,
                            deal_id=deal_id,
                            client_name=(payload or {}).get("name"),
                        ))
        finally:
            conn.close()

        return jsonify({
            "success": True,
            "owner_email": owner_email,
            "owner_id": owner_id,
            "deals_found": len(deals),
            "created": sum(1 for item in synced if item["action"] == "created"),
            "updated": sum(1 for item in synced if item["action"] == "updated"),
            "errors": errors,
            "synced": synced,
        })
    except HubSpotError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502
    except Exception as exc:
        logging.exception("HubSpot sync failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/hubspot/backfill/opportunity-nda-sent-dates", methods=["POST", "OPTIONS"])
def backfill_opportunity_nda_sent_dates():
    if request.method == "OPTIONS":
        return ("", 204)

    unauthorized = _require_sync_secret()
    if unauthorized:
        return unauthorized

    body = request.get_json(silent=True) or {}
    property_name = (
        body.get("property_name")
        or os.environ.get("HUBSPOT_NDA_SENT_DATE_PROPERTY")
        or HUBSPOT_NDA_SENT_DATE_PROPERTY
    ).strip()
    limit = body.get("limit")
    dry_run = bool(body.get("dry_run", False))
    allow_ambiguous = bool(body.get("allow_ambiguous", False))

    try:
        limit = int(limit) if limit not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "limit must be an integer"}), 400

    try:
        client = HubSpotClient()
        conn = get_connection()
        updated = []
        skipped = []
        errors = []

        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                _ensure_opportunity_stage_date_columns(cursor)
                _ensure_hubspot_account_columns(cursor)
                conn.commit()   # soltar el ACCESS EXCLUSIVE antes del loop

                query = """
                    WITH candidates AS (
                        SELECT
                            o.opportunity_id,
                            o.opp_stage,
                            a.account_id,
                            a.client_name,
                            a.hubspot_deal_id,
                            COUNT(*) OVER (PARTITION BY a.hubspot_deal_id) AS deal_candidate_count
                        FROM opportunity o
                        JOIN account a ON a.account_id = o.account_id
                        WHERE o.nda_sent_date IS NULL
                          AND NULLIF(a.hubspot_deal_id, '') IS NOT NULL
                          AND TRIM(COALESCE(o.opp_stage, '')) = ANY(%s)
                    )
                    SELECT *
                    FROM candidates
                    ORDER BY hubspot_deal_id, opportunity_id
                """
                params = [list(NDA_SENT_OR_LATER_STAGES)]
                if limit:
                    query += " LIMIT %s"
                    params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()
                date_by_deal = {}

                for row in rows:
                    deal_id = str(row.get("hubspot_deal_id") or "").strip()
                    if not deal_id:
                        continue
                    if not allow_ambiguous and int(row.get("deal_candidate_count") or 0) > 1:
                        skipped.append({
                            "opportunity_id": row.get("opportunity_id"),
                            "account_id": row.get("account_id"),
                            "client_name": row.get("client_name"),
                            "deal_id": deal_id,
                            "reason": "ambiguous_hubspot_deal_maps_to_multiple_opportunities",
                            "deal_candidate_count": row.get("deal_candidate_count"),
                        })
                        continue
                    try:
                        if deal_id not in date_by_deal:
                            deal = client.get_deal_with_associations(
                                deal_id,
                                extra_properties=[property_name],
                            )
                            props = deal.get("properties") or {}
                            date_by_deal[deal_id] = _parse_hubspot_date(props.get(property_name))

                        nda_sent_date = date_by_deal[deal_id]
                        if not nda_sent_date:
                            skipped.append({
                                "opportunity_id": row.get("opportunity_id"),
                                "deal_id": deal_id,
                                "reason": "missing_hubspot_date",
                            })
                            continue

                        if not dry_run:
                            cursor.execute(
                                """
                                UPDATE opportunity
                                SET nda_sent_date = %s
                                WHERE opportunity_id = %s
                                  AND nda_sent_date IS NULL
                                """,
                                (nda_sent_date, row.get("opportunity_id")),
                            )

                        # Una transaccion por fila: un error no aborta el resto del
                        # backfill ni descarta lo ya escrito.
                        conn.commit()
                        updated.append({
                            "opportunity_id": row.get("opportunity_id"),
                            "deal_id": deal_id,
                            "nda_sent_date": nda_sent_date.isoformat(),
                        })
                    except Exception as exc:  # noqa: BLE001
                        _rollback_quietly(conn, "deal %s" % deal_id)
                        logging.exception(
                            "HubSpot NDA sent date backfill failed for deal %s",
                            deal_id,
                        )
                        errors.append(_error_record(
                            exc,
                            opportunity_id=row.get("opportunity_id"),
                            deal_id=deal_id,
                        ))
        finally:
            conn.close()

        return jsonify({
            "success": True,
            "dry_run": dry_run,
            "allow_ambiguous": allow_ambiguous,
            "property_name": property_name,
            "checked": len(updated) + len(skipped) + len(errors),
            "updated": len(updated),
            "skipped": skipped,
            "errors": errors,
            "items": updated,
        })
    except HubSpotError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502
    except Exception as exc:
        logging.exception("HubSpot opportunity NDA sent date backfill failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/hubspot/backfill/opportunity-deep-dive-dates", methods=["POST", "OPTIONS"])
def backfill_opportunity_deep_dive_dates():
    if request.method == "OPTIONS":
        return ("", 204)

    unauthorized = _require_sync_secret()
    if unauthorized:
        return unauthorized

    body = request.get_json(silent=True) or {}
    property_name = (
        body.get("property_name")
        or os.environ.get("HUBSPOT_DEEP_DIVE_DATE_PROPERTY")
        or HUBSPOT_DEEP_DIVE_DATE_PROPERTY
    ).strip()
    limit = body.get("limit")
    dry_run = bool(body.get("dry_run", False))
    allow_ambiguous = bool(body.get("allow_ambiguous", False))

    try:
        limit = int(limit) if limit not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "limit must be an integer"}), 400

    try:
        client = HubSpotClient()
        conn = get_connection()
        updated = []
        skipped = []
        errors = []

        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                _ensure_opportunity_stage_date_columns(cursor)
                _ensure_hubspot_account_columns(cursor)
                conn.commit()   # soltar el ACCESS EXCLUSIVE antes del loop

                query = """
                    WITH candidates AS (
                        SELECT
                            o.opportunity_id,
                            o.opp_stage,
                            a.account_id,
                            a.client_name,
                            a.hubspot_deal_id,
                            COUNT(*) OVER (PARTITION BY a.hubspot_deal_id) AS deal_candidate_count
                        FROM opportunity o
                        JOIN account a ON a.account_id = o.account_id
                        WHERE o.deep_dive_date IS NULL
                          AND NULLIF(a.hubspot_deal_id, '') IS NOT NULL
                          AND TRIM(COALESCE(o.opp_stage, '')) = ANY(%s)
                    )
                    SELECT *
                    FROM candidates
                    ORDER BY hubspot_deal_id, opportunity_id
                """
                params = [list(DEEP_DIVE_OR_LATER_STAGES)]
                if limit:
                    query += " LIMIT %s"
                    params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()
                date_by_deal = {}

                for row in rows:
                    deal_id = str(row.get("hubspot_deal_id") or "").strip()
                    if not deal_id:
                        continue
                    if not allow_ambiguous and int(row.get("deal_candidate_count") or 0) > 1:
                        skipped.append({
                            "opportunity_id": row.get("opportunity_id"),
                            "account_id": row.get("account_id"),
                            "client_name": row.get("client_name"),
                            "deal_id": deal_id,
                            "reason": "ambiguous_hubspot_deal_maps_to_multiple_opportunities",
                            "deal_candidate_count": row.get("deal_candidate_count"),
                        })
                        continue
                    try:
                        if deal_id not in date_by_deal:
                            deal = client.get_deal_with_associations(
                                deal_id,
                                extra_properties=[property_name],
                            )
                            props = deal.get("properties") or {}
                            date_by_deal[deal_id] = _parse_hubspot_date(props.get(property_name))

                        deep_dive_date = date_by_deal[deal_id]
                        if not deep_dive_date:
                            skipped.append({
                                "opportunity_id": row.get("opportunity_id"),
                                "deal_id": deal_id,
                                "reason": "missing_hubspot_date",
                            })
                            continue

                        if not dry_run:
                            cursor.execute(
                                """
                                UPDATE opportunity
                                SET deep_dive_date = %s
                                WHERE opportunity_id = %s
                                  AND deep_dive_date IS NULL
                                """,
                                (deep_dive_date, row.get("opportunity_id")),
                            )

                        # Una transaccion por fila: un error no aborta el resto del
                        # backfill ni descarta lo ya escrito.
                        conn.commit()
                        updated.append({
                            "opportunity_id": row.get("opportunity_id"),
                            "deal_id": deal_id,
                            "deep_dive_date": deep_dive_date.isoformat(),
                        })
                    except Exception as exc:  # noqa: BLE001
                        _rollback_quietly(conn, "deal %s" % deal_id)
                        logging.exception(
                            "HubSpot Deep Dive date backfill failed for deal %s",
                            deal_id,
                        )
                        errors.append(_error_record(
                            exc,
                            opportunity_id=row.get("opportunity_id"),
                            deal_id=deal_id,
                        ))
        finally:
            conn.close()

        return jsonify({
            "success": True,
            "dry_run": dry_run,
            "allow_ambiguous": allow_ambiguous,
            "property_name": property_name,
            "checked": len(updated) + len(skipped) + len(errors),
            "updated": len(updated),
            "skipped": skipped,
            "errors": errors,
            "items": updated,
        })
    except HubSpotError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502
    except Exception as exc:
        logging.exception("HubSpot opportunity Deep Dive date backfill failed")
        return jsonify({"success": False, "error": str(exc)}), 500


# ===========================================================================
# Sync HubSpot -> opportunities del hub
#
# Spec: doc "AUTOMATIZACIONES HUBSPOT - HUB".
#   Intro Call -> Deep Dive  ==> crear la opportunity
#   Deep Dive  -> NDA Sent   ==> stage 'NDA Sent'
#   NDA Sent   -> NDA Signed ==> stage 'Sourcing'
#   Closed Won               ==> solo Set Up Fee / Final Fee, NO mueve el stage
#
# La invariante que sostiene todo: una opportunity con hubspot_deal_id NULL fue
# creada a mano desde el modal y el sync NO la toca nunca.
# ===========================================================================


def _opp_sync_env_flag(name, default=True):
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def _opp_sync_bootstrap_ms():
    """Desde cuando mirar deals en la PRIMERA corrida (sin watermark todavia).

    Default deliberadamente corto (24 h): un bootstrap ancho crearia de golpe
    una opportunity por cada deal historico que este en Deep Dive o mas adelante.
    Para traer historia hay que setear HUBSPOT_OPP_SYNC_BOOTSTRAP a conciencia.
    """
    raw = (os.environ.get("HUBSPOT_OPP_SYNC_BOOTSTRAP") or "").strip()
    parsed = _parse_hubspot_date(raw) if raw else None
    if parsed:
        moment = datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)
        return int(moment.timestamp() * 1000)
    return int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp() * 1000)


def _opp_sync_overlap_ms():
    raw = (os.environ.get("HUBSPOT_OPP_SYNC_OVERLAP_MINUTES") or "").strip()
    try:
        minutes = int(raw) if raw else 10
    except ValueError:
        minutes = 10
    return max(minutes, 0) * 60 * 1000


def _iso_dates(mapping):
    """Fechas -> 'YYYY-MM-DD' para que el reporte se vea igual en todos los caminos."""
    return {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in mapping.items()
        if value is not None
    }


def _skip(deal, reason, **extra):
    props = (deal or {}).get("properties") or {}
    record = {
        "deal_id": str((deal or {}).get("id") or ""),
        "dealname": props.get("dealname"),
    }
    record.update(extra)
    # Al final: `extra` suele ser el item en construccion y puede traer un
    # "action" de un paso anterior (p. ej. "adopted") que pisaria el skip.
    record["action"] = "skipped"
    record["reason"] = reason
    return record


def _adopt_existing_opportunity(cursor, account_id, position, allow_ambiguous, schema_ready=True):
    """Busca una opp abierta de esa cuenta con la misma posicion, sin deal atado.

    Existe porque Mariano ya venia cargando estas opps a mano: sin esto el sync
    crearia un duplicado por cada una y ensuciaria funnel y revenue.
    """
    # Sin la migracion no hay hubspot_deal_id, y entonces NINGUNA opp lo tiene: el
    # predicado sobra y hay que sacarlo para que el dry run pueda correr igual.
    sin_deal = "AND NULLIF(hubspot_deal_id, '') IS NULL" if schema_ready else ""
    cursor.execute(
        r"""
        SELECT opportunity_id, opp_stage, opp_position_name
          FROM opportunity
         WHERE account_id = %%s
           %s
           AND LOWER(BTRIM(COALESCE(opp_stage, ''))) NOT IN ('closed lost', 'stop', 'close win')
           AND regexp_replace(LOWER(BTRIM(COALESCE(opp_position_name, ''))), '\s+', ' ', 'g') = %%s
         ORDER BY opportunity_id DESC
        """ % sin_deal,
        (account_id, hs_opps.normalize_position_name(position)),
    )
    rows = cursor.fetchall()
    if not rows:
        return None, None
    if len(rows) > 1 and not allow_ambiguous:
        return None, [r["opportunity_id"] for r in rows]
    return rows[0], None


# Sin la migracion corrida no existen hubspot_deal_id ni las dos de fees. Un dry run
# tiene que poder correr igual: es justamente lo que se mira ANTES de migrar.
_OPP_BASE_COLUMNS = """opportunity_id, account_id, opp_stage, opp_position_name, opp_model,
               deep_dive_date, nda_sent_date, nda_signature_or_start_date,
               min_budget, max_budget, min_salary, max_salary, years_experience,
               fee, expected_fee"""
_OPP_HUBSPOT_COLUMNS = """,
               hubspot_setup_fee, hubspot_final_fee, hubspot_final_salary,
               hubspot_role_hired, hubspot_mkt_collab"""


def _opp_select_columns(schema_ready):
    return _OPP_BASE_COLUMNS + (_OPP_HUBSPOT_COLUMNS if schema_ready else "")


def _load_opportunity_by_deal(cursor, deal_id, schema_ready=True):
    if not schema_ready:
        # La columna no existe todavia, asi que ninguna opp puede estar amarrada.
        return None
    cursor.execute(
        """
        SELECT %s
          FROM opportunity
         WHERE NULLIF(hubspot_deal_id, '') = %%s
         LIMIT 1
        """ % _opp_select_columns(True),
        (deal_id,),
    )
    return cursor.fetchone()


def _load_opportunity_by_id(cursor, opportunity_id, schema_ready=True):
    cursor.execute(
        """
        SELECT %s
          FROM opportunity
         WHERE opportunity_id = %%s
        """ % _opp_select_columns(schema_ready),
        (opportunity_id,),
    )
    return cursor.fetchone()


def _apply_business_fields(cursor, opportunity_id, business, opp_row, dry_run):
    """Completa budget/salario/experiencia/fees con lo que trae HubSpot.

    Solo llena columnas en NULL y NUNCA pisa: esos numeros se renegocian dentro
    del hub y el dato mas fresco suele ser el de la recruiter (decision de la
    owner). Mismo criterio que usa el sync del CRM con las cuentas.

    `fee` es la que el hub muestra como "Set Up Fee" y no la lee ningun dataset;
    el fee del MRR sale de hire_opportunity. La unica con impacto en un card es
    expected_fee (Active Pipeline).
    """
    faltantes = {
        column: value
        for column, value in business.items()
        if (opp_row or {}).get(column) is None
    }
    if not faltantes or dry_run:
        return faltantes
    sets = ", ".join(f"{col} = COALESCE({col}, %s)" for col in faltantes)
    cursor.execute(
        f"UPDATE opportunity SET {sets}, hubspot_synced_at = NOW() "
        f"WHERE opportunity_id = %s AND NULLIF(hubspot_deal_id, '') IS NOT NULL",
        list(faltantes.values()) + [opportunity_id],
    )
    return faltantes


def _insert_opportunity_from_deal(cursor, values):
    """INSERT con opportunity_id = MAX+1 en UNA sentencia, con reintento.

    La tabla no tiene secuencia (ver create_opportunity en accounts_routes.py:975),
    asi que la carrera ya existe hoy; calcularlo dentro del propio INSERT deja la
    ventana en el minimo posible y el SAVEPOINT permite reintentar sin abortar la
    transaccion del deal.
    """
    for attempt in range(3):
        cursor.execute("SAVEPOINT hs_opp_insert")
        try:
            cursor.execute(
                """
                INSERT INTO opportunity (
                    opportunity_id, account_id, opp_model, opp_position_name, opp_sales_lead,
                    opp_type, opp_stage, deep_dive_date, nda_sent_date, nda_signature_or_start_date,
                    hubspot_deal_id, hubspot_pipeline_id, hubspot_dealstage_id, hubspot_synced_at
                )
                SELECT COALESCE(MAX(opportunity_id), 0) + 1,
                       %(account_id)s, %(opp_model)s, %(position)s, %(sales_lead)s,
                       'New', %(opp_stage)s,
                       %(deep_dive_date)s, %(nda_sent_date)s, %(nda_signed_date)s,
                       %(deal_id)s, %(pipeline_id)s, %(dealstage_id)s, NOW()
                  FROM opportunity
                RETURNING opportunity_id
                """,
                values,
            )
            row = cursor.fetchone()
            cursor.execute("RELEASE SAVEPOINT hs_opp_insert")
            return row["opportunity_id"]
        except psycopg2.errors.UniqueViolation:
            cursor.execute("ROLLBACK TO SAVEPOINT hs_opp_insert")
            if attempt == 2:
                raise
    return None


def _process_hubspot_deal(client, cursor, deal, ctx):
    """Procesa UN deal. No commitea: el caller commitea por deal."""
    pipeline_map = ctx["pipeline_map"]
    property_maps = ctx["property_maps"]
    opp_property_map = ctx["opp_property_map"]
    dry_run = ctx["dry_run"]

    deal_id = str(deal.get("id") or "")
    props = deal.get("properties") or {}
    pipeline_id = str(props.get("pipeline") or "")
    dealstage_id = str(props.get("dealstage") or "")

    entry = hs_opps.pipeline_entry(pipeline_map, pipeline_id)
    if not entry:
        return _skip(deal, "pipeline_not_tracked", pipeline_id=pipeline_id)

    stage_key = hs_opps.deal_stage_key(pipeline_map, pipeline_id, dealstage_id)
    if not stage_key:
        return _skip(deal, "unmapped_stage", pipeline_key=entry["key"],
                     dealstage_id=dealstage_id,
                     dealstage_label=entry["stage_labels"].get(dealstage_id))

    # Se detecta ANTES de los saltos tempranos: el caso mas comun de retroceso es
    # justamente un deal que volvio a Intro Call, y ese se saltea dos lineas abajo.
    # No se actua, solo se reporta (decision de la owner).
    retroceso = hs_opps.detect_hubspot_regression(
        pipeline_map, pipeline_id, props, stage_key, _parse_hubspot_date
    )

    if stage_key == "intro_call":
        return _skip(deal, "not_yet_deep_dive", pipeline_key=entry["key"],
                     stage_key=stage_key,
                     **({"hubspot_retrocedio": retroceso} if retroceso else {}))

    stage_dates = hs_opps.stage_dates_from_deal(
        pipeline_map, pipeline_id, props, _parse_hubspot_date
    )
    # HubSpot no tiene propiedad de fecha para las dos etapas "NDA Sent": si falta
    # la del stage donde esta el deal, se usa la fecha en que el sync lo detecta
    # (misma semantica que el CURRENT_DATE del hub al mover el stage a mano).
    inferida = hs_opps.fill_missing_entry_date(stage_dates, stage_key, today_ar())
    role = str(props.get(opp_property_map.get("role_to_hire") or "") or "").strip()
    model = _first_mapped_value(property_maps, "contract", deal=deal) or None
    # Budget, salario, experiencia y fees esperados: HubSpot los pide al pasar a
    # NDA Sent, y son los mismos campos que el hub muestra en Opportunity Detail.
    business = hs_opps.business_fields_from_deal(props, opp_property_map)

    item = {
        "deal_id": deal_id,
        "dealname": props.get("dealname"),
        "pipeline_key": entry["key"],
        "stage_key": stage_key,
        "role_to_hire": role or None,
        "opp_model": model,
    }
    if inferida:
        # Se marca aparte para no hacer pasar por dato de HubSpot algo que no lo es.
        item["fechas_inferidas"] = [inferida]
    if retroceso:
        item["hubspot_retrocedio"] = retroceso

    schema_ready = ctx.get("schema_ready", True)
    opp = _load_opportunity_by_deal(cursor, deal_id, schema_ready=schema_ready)
    account_action = None

    # --- la opp todavia no existe: resolver cuenta, adoptar o crear ------------
    if not opp:
        if not role:
            # opp_position_name es la llave de adopcion: no se inventa.
            return _skip(deal, "no_role_to_hire", **item)

        full_deal = client.get_deal_with_associations(
            deal_id, extra_properties=ctx["deal_extra_properties"]
        )
        company_ids = association_ids(full_deal, "companies")
        contact_ids = association_ids(full_deal, "contacts")
        company = (
            client.get_company(company_ids[0], extra_properties=ctx["company_extra_properties"])
            if company_ids else None
        )
        contact = (
            client.get_contact(contact_ids[0], extra_properties=ctx["contact_extra_properties"])
            if contact_ids else None
        )
        payload = build_account_payload(
            full_deal, company=company, contact=contact, owner_email=entry["sales_lead"],
        )
        payload = _apply_account_field_overrides(
            payload, contact=contact, company=company, deal=full_deal,
            property_maps=property_maps,
        )

        existing_account = _preview_existing_account(cursor, payload)
        if existing_account:
            account_id = existing_account["account_id"]
            account_action = "found"
            if not dry_run:
                _link_existing_account_to_hubspot(cursor, account_id, payload)
                account_action = "linked"
        elif dry_run:
            item["account_action"] = "would_create"
            item["would_action"] = "created"
            item["reason"] = "advanced"
            item["hub_stage_after"] = hs_opps.initial_stage_for_new_opportunity(stage_key, stage_dates)
            item["dates_written"] = _iso_dates(stage_dates)
            return item
        else:
            result = _insert_or_update_account(cursor, payload)
            account_id = result["account_id"]
            account_action = result["action"]

        item["account_id"] = account_id
        item["account_action"] = account_action

        adopted, ambiguous = _adopt_existing_opportunity(
            cursor, account_id, role, ctx["allow_ambiguous"], schema_ready=schema_ready
        )
        if ambiguous:
            return _skip(deal, "ambiguous_position_match", candidates=ambiguous, **item)

        if adopted:
            if not dry_run:
                cursor.execute(
                    """
                    UPDATE opportunity
                       SET hubspot_deal_id = %s,
                           hubspot_pipeline_id = %s,
                           hubspot_dealstage_id = %s,
                           hubspot_synced_at = NOW()
                     WHERE opportunity_id = %s
                       AND NULLIF(hubspot_deal_id, '') IS NULL
                    """,
                    (deal_id, pipeline_id, dealstage_id, adopted["opportunity_id"]),
                )
                if cursor.rowcount == 0:
                    # Otra corrida la agarro entre el SELECT y el UPDATE.
                    return _skip(deal, "adopted_concurrently", **item)
            item["would_action" if dry_run else "action"] = "adopted"
            item["opportunity_id"] = adopted["opportunity_id"]
            item["hub_stage_before"] = adopted["opp_stage"]
            # Se recarga en ambos casos: el resto del flujo calcula que stage y
            # que fechas CAMBIARIAN, y en dry run eso es justo lo que hay que ver.
            opp = _load_opportunity_by_id(
                cursor, adopted["opportunity_id"], schema_ready=schema_ready
            )
            if not opp:
                # En una corrida real la adopcion ya quedo escrita; sin la fila no
                # se puede seguir con stage/fechas, pero el deal quedo amarrado.
                item["reason"] = "adopted_reload_failed"
                return item
        else:
            initial_stage = hs_opps.initial_stage_for_new_opportunity(stage_key, stage_dates)
            if dry_run:
                item["would_action"] = "created"
                item["reason"] = "advanced"
                item["hub_stage_after"] = initial_stage
                item["dates_written"] = _iso_dates(stage_dates)
                return item
            new_id = _insert_opportunity_from_deal(cursor, {
                "account_id": account_id,
                "opp_model": model,
                "position": role,
                "sales_lead": entry["sales_lead"],
                "opp_stage": initial_stage,
                "deep_dive_date": stage_dates["deep_dive_date"],
                "nda_sent_date": stage_dates["nda_sent_date"],
                "nda_signed_date": stage_dates["nda_signature_or_start_date"],
                "deal_id": deal_id,
                "pipeline_id": pipeline_id,
                "dealstage_id": dealstage_id,
            })
            item["action"] = "created"
            item["reason"] = "advanced"
            item["opportunity_id"] = new_id
            item["hub_stage_after"] = initial_stage
            item["dates_written"] = _iso_dates(stage_dates)
            # La opp recien nacida tiene todo en NULL, asi que entra todo lo que
            # HubSpot tenga cargado.
            completados = _apply_business_fields(cursor, new_id, business, None, dry_run)
            if completados:
                item["campos_completados"] = completados

            try:
                create_stage_todos(cursor, new_id, initial_stage)
            except Exception:  # noqa: BLE001
                logging.exception("create_stage_todos fallo para la opp %s", new_id)

            if ctx["send_emails"]:
                try:
                    item["credit_loop_notice"] = (
                        maybe_send_credit_available_email_for_new_opportunity(
                            cursor,
                            account_id=account_id,
                            opportunity_id=new_id,
                            opp_model=model,
                            opp_position_name=role,
                            client_name=payload.get("name"),
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logging.exception("credit loop email fallo para la opp %s", new_id)
                    item["credit_loop_notice"] = {"sent": False, "error": str(exc)}
            else:
                item["credit_loop_notice"] = {"sent": False, "reason": "suppressed_by_sync"}
            return item

    if not opp:
        return _skip(deal, "opportunity_not_resolvable", **item)

    # --- la opp ya existe: stage, fechas y fees -------------------------------
    opportunity_id = opp["opportunity_id"]
    item["opportunity_id"] = opportunity_id
    item.setdefault("account_id", opp.get("account_id"))
    item["hub_stage_before"] = opp.get("opp_stage")

    changed = False
    target_stage = hs_opps.STAGE_KEY_TO_HUB_STAGE.get(stage_key)
    new_stage, reason = hs_opps.decide_stage_transition(opp.get("opp_stage"), target_stage)
    item["reason"] = reason

    if new_stage and not dry_run:
        cursor.execute(
            """
            UPDATE opportunity
               SET opp_stage = %s,
                   hubspot_dealstage_id = %s,
                   hubspot_pipeline_id = %s,
                   hubspot_synced_at = NOW()
             WHERE opportunity_id = %s
               AND COALESCE(opp_stage, '') = %s
            """,
            (new_stage, dealstage_id, pipeline_id, opportunity_id, opp.get("opp_stage") or ""),
        )
        if cursor.rowcount == 0:
            return _skip(deal, "stage_changed_concurrently", **item)
        item["hub_stage_after"] = new_stage
        changed = True
        try:
            create_stage_todos(cursor, opportunity_id, new_stage)
        except Exception:  # noqa: BLE001
            logging.exception("create_stage_todos fallo para la opp %s", opportunity_id)
    elif new_stage:
        item["hub_stage_after"] = new_stage
        changed = True

    # Fechas: HubSpot pisa el CURRENT_DATE que estampo el hub, pero nunca borra.
    dates_written = {
        column: value
        for column, value in stage_dates.items()
        if value is not None and opp.get(column) != value
    }
    if dates_written:
        item["dates_written"] = _iso_dates(dates_written)
        changed = True
        if not dry_run:
            cursor.execute(
                """
                UPDATE opportunity
                   SET deep_dive_date = COALESCE(%s, deep_dive_date),
                       nda_sent_date  = COALESCE(%s, nda_sent_date),
                       nda_signature_or_start_date = COALESCE(%s, nda_signature_or_start_date),
                       hubspot_synced_at = NOW()
                 WHERE opportunity_id = %s
                   AND NULLIF(hubspot_deal_id, '') IS NOT NULL
                """,
                (
                    dates_written.get("deep_dive_date"),
                    dates_written.get("nda_sent_date"),
                    dates_written.get("nda_signature_or_start_date"),
                    opportunity_id,
                ),
            )

    completados = _apply_business_fields(cursor, opportunity_id, business, opp, dry_run)
    if completados:
        item["campos_completados"] = completados
        changed = True

    # Los 5 campos de Closed Win, todos a columnas ESPEJO de `opportunity`.
    #
    # A proposito NO se escribe hire_opportunity: esos montos viven por
    # (candidate_id, opportunity_id) y HubSpot no tiene identidad de candidato. Ademas
    # `revenue` es polisemica segun opp_model y se calcula en el navegador, el fee de
    # Staffing pasa por salary_updates, el Credit Loop pisa fee/revenue, y estos numeros
    # son el insumo del mail de comisiones. Los aplica una persona desde la solapa Hire.
    if stage_key == "closed_won":
        espejo = hs_opps.closed_win_fields_from_deal(props, opp_property_map)
        nuevos = {
            column: value
            for column, value in espejo.items()
            if opp.get(column) != value
        }
        if nuevos:
            item["closed_win_written"] = {k: str(v) for k, v in nuevos.items()}
            changed = True
            if not dry_run:
                sets = ", ".join(f"{col} = COALESCE({col}, %s)" for col in nuevos)
                cursor.execute(
                    f"UPDATE opportunity SET {sets}, hubspot_synced_at = NOW() "
                    f"WHERE opportunity_id = %s AND NULLIF(hubspot_deal_id, '') IS NOT NULL",
                    list(nuevos.values()) + [opportunity_id],
                )

    if "adopted" in (item.get("action"), item.get("would_action")):
        return item
    if not changed:
        item["action"] = "skipped"
        # El motivo por el que no se movio el stage se guarda aparte: sirve para
        # el triage (hub_ahead_or_equal no es lo mismo que unknown_hub_stage).
        item["stage_reason"] = item.get("reason")
        item["reason"] = "nothing_to_change"
        return item

    item["would_action" if dry_run else "action"] = "updated"
    return item


@bp.route("/hubspot/debug/deal-pipelines", methods=["GET", "OPTIONS"])
def debug_hubspot_deal_pipelines():
    """Que stage ids resolvio el sync, y contra que labels reales de HubSpot.

    Es lo primero que hay que mirar: si aca un stage sale en `unresolved`, el
    sync lo va a ignorar en vez de adivinar.
    """
    if request.method == "OPTIONS":
        return ("", 204)

    refresh = str(request.args.get("refresh") or "").strip().lower() in ("1", "true", "yes")
    try:
        client = HubSpotClient()
        pipeline_map = hs_opps.resolve_pipeline_stage_map(client, force_refresh=refresh)
        opp_property_map = hs_opps.resolve_opportunity_property_map(client, force_refresh=refresh)

        pipelines = []
        for entry in pipeline_map["by_pipeline_id"].values():
            pipelines.append({
                "key": entry["key"],
                "id": entry["id"],
                "label": entry["label"],
                "sales_lead": entry["sales_lead"],
                "stages": [
                    {
                        "stage_key": stage_key,
                        "stage_id": stage_id,
                        "label": entry["stage_labels"].get(stage_id),
                        "date_property": entry["date_property_by_key"].get(stage_key),
                    }
                    for stage_key, stage_id in entry["stage_id_by_key"].items()
                ],
                "unresolved": entry["unresolved"],
            })

        # Las constantes viejas son de UN pipeline. Si HubSpot renumera los stages
        # este bloque lo hace visible en vez de dejar los backfills mintiendo.
        hiring_id = pipeline_map["pipeline_id_by_key"].get("hiring")
        hiring = pipeline_map["by_pipeline_id"].get(hiring_id) or {}
        hiring_stages = hiring.get("stage_id_by_key") or {}
        constants_check = {
            "deep_dive": {
                "constant": HUBSPOT_DEEP_DIVE_DATE_PROPERTY,
                "resolved": hs_opps.stage_date_property(hiring_stages["deep_dive"])
                if hiring_stages.get("deep_dive") else None,
            },
            "nda_sent": {
                "constant": HUBSPOT_NDA_SENT_DATE_PROPERTY,
                "resolved": hs_opps.stage_date_property(hiring_stages["nda_sent"])
                if hiring_stages.get("nda_sent") else None,
            },
        }
        for check in constants_check.values():
            check["matches"] = check["constant"] == check["resolved"]

        return jsonify({
            "success": True,
            "pipelines": pipelines,
            "date_properties": pipeline_map["date_properties"],
            "deal_properties": opp_property_map,
            "warnings": pipeline_map["warnings"],
            "constants_check": constants_check,
        })
    except HubSpotError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502
    except Exception as exc:  # noqa: BLE001
        logging.exception("HubSpot deal pipelines debug failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/hubspot/sync/opportunities", methods=["POST", "OPTIONS"])
def sync_hubspot_opportunities():
    if request.method == "OPTIONS":
        return ("", 204)

    unauthorized = _require_sync_secret()
    if unauthorized:
        return unauthorized

    body = request.get_json(silent=True) or {}
    dry_run = bool(body.get("dry_run", False))
    allow_ambiguous = bool(body.get("allow_ambiguous", False))
    refresh = bool(body.get("refresh", False))
    deal_ids = [str(d).strip() for d in (body.get("deal_ids") or []) if str(d).strip()]
    send_emails = bool(body.get("send_emails", _opp_sync_env_flag("HUBSPOT_OPP_SYNC_SEND_EMAILS")))
    if dry_run:
        send_emails = False

    limit = body.get("limit")
    try:
        limit = int(limit) if limit not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "limit must be an integer"}), 400

    conn = None
    locked = False
    try:
        client = HubSpotClient()
        pipeline_map = hs_opps.resolve_pipeline_stage_map(client, force_refresh=refresh)
        if not pipeline_map["pipeline_id_by_key"]:
            return jsonify({
                "success": False,
                "error": "no se pudo resolver ningun pipeline de HubSpot",
                "warnings": pipeline_map["warnings"],
            }), 502

        property_maps = _resolve_account_property_maps(client)
        opp_property_map = hs_opps.resolve_opportunity_property_map(client, force_refresh=refresh)

        deal_extra_properties = list(pipeline_map["date_properties"])
        for field, prop in opp_property_map.items():
            if field == "_unresolved" or not prop:
                continue
            if prop not in deal_extra_properties:
                deal_extra_properties.append(prop)
        for prop in _mapped_property_names(property_maps, "deals"):
            if prop not in deal_extra_properties:
                deal_extra_properties.append(prop)
        company_extra_properties = _mapped_property_names(property_maps, "companies")
        contact_extra_properties = _mapped_property_names(property_maps, "contacts")

        conn = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # El cron cada 30 min y el boton pueden solaparse; como commiteamos por
        # deal, dos corridas a la vez podrian crear la misma opportunity dos veces.
        cursor.execute("SELECT pg_try_advisory_lock(%s) AS got", (HUBSPOT_OPP_SYNC_LOCK_KEY,))
        if not cursor.fetchone()["got"]:
            return jsonify({"success": False, "error": "sync_already_running"}), 409
        locked = True

        if dry_run:
            # Un dry run tiene que ser 100% de solo lectura: sin ALTER TABLE, sin
            # CREATE TABLE y sin la fila del reporte. Es lo que se corre ANTES de
            # decidir aplicar la migracion, y db.py apunta a la RDS de produccion
            # aunque el backend corra local.
            schema_ready = _hubspot_opportunity_schema_is_ready(cursor)
        else:
            _ensure_hubspot_opportunity_columns(cursor)
            _ensure_hubspot_account_columns(cursor)
            _ensure_hubspot_sync_state_table(cursor)
            schema_ready = True
        conn.commit()   # soltar el ACCESS EXCLUSIVE antes del loop

        run_started_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        if deal_ids:
            since_ms = None
            deals = [
                client.get_deal_with_associations(deal_id, extra_properties=deal_extra_properties)
                for deal_id in deal_ids
            ]
        else:
            requested_after = body.get("modified_after")
            since_ms = (
                hubspot_datetime_to_ms(requested_after)
                if requested_after not in (None, "") else None
            )
            if requested_after not in (None, "") and since_ms is None:
                return jsonify({
                    "success": False,
                    "error": "modified_after no se pudo interpretar como fecha",
                }), 400
            if since_ms is None:
                # En dry run no se lee la marca: la tabla puede no existir todavia.
                watermark = _read_sync_watermark_ms(cursor) if not dry_run else None
                since_ms = (
                    max(watermark - _opp_sync_overlap_ms(), 0)
                    if watermark else _opp_sync_bootstrap_ms()
                )
            deals = []
            # search_deals acepta UN filterGroup (= AND), asi que va una llamada
            # por pipeline. Sin filtro de dealstage a proposito: queremos ver
            # tambien los deals que saltearon etapas.
            for pipeline_key, pipeline_id in pipeline_map["pipeline_id_by_key"].items():
                deals.extend(client.search_deals(
                    [
                        {"propertyName": "pipeline", "operator": "EQ", "value": pipeline_id},
                        {"propertyName": "hs_lastmodifieddate", "operator": "GTE", "value": str(since_ms)},
                    ],
                    extra_properties=deal_extra_properties,
                ))

        ctx = {
            "pipeline_map": pipeline_map,
            "property_maps": property_maps,
            "opp_property_map": opp_property_map,
            "dry_run": dry_run,
            "schema_ready": schema_ready,
            "allow_ambiguous": allow_ambiguous,
            "send_emails": send_emails,
            "deal_extra_properties": deal_extra_properties,
            "company_extra_properties": company_extra_properties,
            "contact_extra_properties": contact_extra_properties,
        }

        items = []
        errors = []
        limit_truncated = False
        processed = 0

        for deal in deals:
            if limit and processed >= limit:
                limit_truncated = True
                break
            processed += 1
            deal_id = str(deal.get("id") or "")
            try:
                items.append(_process_hubspot_deal(client, cursor, deal, ctx))
                # Una transaccion por deal: un error no aborta el resto ni
                # descarta lo ya escrito. En dry run se descarta a proposito, para
                # que ni un write accidental pueda quedar.
                conn.rollback() if dry_run else conn.commit()
            except Exception as exc:  # noqa: BLE001
                _rollback_quietly(conn, "deal %s" % deal_id)
                logging.exception("HubSpot opportunity sync fallo en el deal %s", deal_id)
                errors.append(_error_record(exc, deal_id=deal_id))

        counts = {"created": 0, "adopted": 0, "updated": 0, "skipped": 0}
        for item in items:
            action = item.get("action") or item.get("would_action") or "skipped"
            if action in counts:
                counts[action] += 1
        retrocesos = [i for i in items if i.get("hubspot_retrocedio")]

        # La marca solo avanza si la corrida vio TODO lo que pidio y no fallo nada:
        # si no, la proxima reprocesa (todo es idempotente).
        can_advance = (
            not dry_run and not errors and not limit_truncated
            and not deal_ids and body.get("modified_after") in (None, "")
        )
        watermark_advanced_to = run_started_ms if can_advance else None

        report = {
            "success": True,
            "dry_run": dry_run,
            "since_ms": since_ms,
            "since": datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc).isoformat()
            if since_ms else None,
            "pipelines": [
                {"key": e["key"], "id": e["id"], "label": e["label"], "unresolved": e["unresolved"]}
                for e in pipeline_map["by_pipeline_id"].values()
            ],
            "warnings": pipeline_map["warnings"],
            "migracion_aplicada": schema_ready,
            "retrocesos": retrocesos,
            "deals_found": len(deals),
            "limit_truncated": limit_truncated,
            "send_emails": send_emails,
            "watermark_advanced_to": watermark_advanced_to,
            "errors": errors,
            "items": items,
        }
        report.update(counts)

        if not dry_run:
            try:
                _write_sync_state(
                    cursor,
                    HUBSPOT_OPP_SYNC_KEY,
                    watermark_advanced_to,
                    "error" if errors else "ok",
                    report,
                )
                conn.commit()
            except Exception:  # noqa: BLE001
                _rollback_quietly(conn, "sync state")
                logging.exception("No se pudo guardar hubspot_sync_state")

        return jsonify(report)
    except HubSpotError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502
    except Exception as exc:  # noqa: BLE001
        logging.exception("HubSpot opportunity sync failed")
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        if conn:
            if locked:
                try:
                    with conn.cursor() as unlock_cursor:
                        unlock_cursor.execute(
                            "SELECT pg_advisory_unlock(%s)", (HUBSPOT_OPP_SYNC_LOCK_KEY,)
                        )
                    conn.commit()
                except Exception:  # noqa: BLE001
                    logging.exception("No se pudo soltar el advisory lock del sync")
            conn.close()


@bp.route("/hubspot/sync/opportunities/last", methods=["GET", "OPTIONS"])
def last_hubspot_opportunity_sync():
    if request.method == "OPTIONS":
        return ("", 204)

    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            _ensure_hubspot_sync_state_table(cursor)
            conn.commit()
            cursor.execute(
                """
                SELECT sync_key, watermark_ms, last_run_at, last_status, last_report
                  FROM hubspot_sync_state
                 WHERE sync_key = %s
                """,
                (HUBSPOT_OPP_SYNC_KEY,),
            )
            row = cursor.fetchone()
        if not row:
            return jsonify({"success": True, "last_run_at": None, "report": None})
        return jsonify({
            "success": True,
            "watermark_ms": row["watermark_ms"],
            "last_run_at": row["last_run_at"],
            "last_status": row["last_status"],
            "report": row["last_report"],
        })
    except Exception as exc:  # noqa: BLE001
        logging.exception("No se pudo leer hubspot_sync_state")
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        if conn:
            conn.close()


@bp.route("/hubspot/preview/opportunities", methods=["GET", "OPTIONS"])
def preview_hubspot_opportunities():
    """Que campo de HubSpot se lee para cada columna del hub, con valores reales.

    Es la respuesta a "como se que estamos leyendo bien los campos": el dry run
    dice QUE va a pasar, esto dice DE DONDE sale cada dato. No escribe nada y no
    depende de que la migracion este corrida.

    GET /hubspot/preview/opportunities?limit=10&days=90[&deal_id=123][&pipeline=hiring]
    """
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        limit = int(request.args.get("limit") or 10)
    except ValueError:
        return jsonify({"success": False, "error": "limit must be an integer"}), 400
    try:
        days = int(request.args.get("days") or 90)
    except ValueError:
        return jsonify({"success": False, "error": "days must be an integer"}), 400

    only_deal_id = (request.args.get("deal_id") or "").strip()
    only_pipeline = (request.args.get("pipeline") or "").strip()

    try:
        client = HubSpotClient()
        pipeline_map = hs_opps.resolve_pipeline_stage_map(client)
        property_maps = _resolve_account_property_maps(client)
        opp_property_map = hs_opps.resolve_opportunity_property_map(client)
        labels_by_name = {
            (prop.get("name") or ""): (prop.get("label") or "")
            for prop in client.get_properties("deals")
        }

        model_property = property_maps.get("deals", {}).get("contract")
        role_property = opp_property_map.get("role_to_hire")
        setup_property = opp_property_map.get("setup_fee")
        final_property = opp_property_map.get("final_fee")

        # 1) De donde sale cada columna del hub. Si algo dice resolved=false, ese
        #    campo va a entrar vacio y hay que mirar el nombre en HubSpot.
        resolution = {
            "opp_position_name": {
                "hubspot_property": role_property,
                "hubspot_label": labels_by_name.get(role_property or ""),
                "resolved": bool(role_property),
            },
            "opp_model": {
                "hubspot_property": model_property,
                "hubspot_label": labels_by_name.get(model_property or ""),
                "resolved": bool(model_property),
            },
            "hubspot_setup_fee": {
                "hubspot_property": setup_property,
                "hubspot_label": labels_by_name.get(setup_property or ""),
                "resolved": bool(setup_property),
            },
            "hubspot_final_fee": {
                "hubspot_property": final_property,
                "hubspot_label": labels_by_name.get(final_property or ""),
                "resolved": bool(final_property),
            },
            "opp_sales_lead": {
                "hubspot_property": "(el pipeline del deal)",
                "hubspot_label": None,
                "resolved": True,
            },
            "opp_type": {
                "hubspot_property": "(fijo)",
                "hubspot_label": None,
                "resolved": True,
            },
        }
        stages_resolution = {}
        for entry in pipeline_map["by_pipeline_id"].values():
            stages_resolution[entry["key"]] = {
                "pipeline_label": entry["label"],
                "sales_lead": entry["sales_lead"],
                "stages": {
                    stage_key: {
                        "id": stage_id,
                        "label": entry["stage_labels"].get(stage_id),
                        "date_property": entry["date_property_by_key"].get(stage_key),
                    }
                    for stage_key, stage_id in entry["stage_id_by_key"].items()
                },
                "unresolved": entry["unresolved"],
            }

        # 2) Traer deals reales.
        extra = [p for p in (role_property, model_property, setup_property, final_property) if p]
        extra.extend(pipeline_map["date_properties"])
        if only_deal_id:
            deals = [client.get_deal_with_associations(only_deal_id, extra_properties=extra)]
        else:
            since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
            deals = []
            for pipeline_key, pipeline_id in pipeline_map["pipeline_id_by_key"].items():
                if only_pipeline and pipeline_key != only_pipeline:
                    continue
                deals.extend(client.search_deals(
                    [
                        {"propertyName": "pipeline", "operator": "EQ", "value": pipeline_id},
                        {"propertyName": "hs_lastmodifieddate", "operator": "GTE", "value": str(since_ms)},
                    ],
                    extra_properties=extra,
                ))

        rows = []
        health = {}

        def _track(field, value):
            bucket = health.setdefault(field, {"con_valor": 0, "vacio": 0})
            bucket["con_valor" if value not in (None, "") else "vacio"] += 1

        for deal in deals:
            props = deal.get("properties") or {}
            pipeline_id = str(props.get("pipeline") or "")
            dealstage_id = str(props.get("dealstage") or "")
            entry = hs_opps.pipeline_entry(pipeline_map, pipeline_id)
            stage_key = hs_opps.deal_stage_key(pipeline_map, pipeline_id, dealstage_id)

            if entry is None:
                rows.append({
                    "deal_id": str(deal.get("id") or ""),
                    "dealname": props.get("dealname"),
                    "aviso": "pipeline fuera de los dos que sincronizamos; el sync lo ignora",
                })
                continue

            stage_dates = hs_opps.stage_dates_from_deal(
                pipeline_map, pipeline_id, props, _parse_hubspot_date
            )
            role = str(props.get(role_property or "") or "").strip()
            model = _first_mapped_value(property_maps, "contract", deal=deal) or None
            setup_fee = hs_opps.parse_money(props.get(setup_property or ""))
            final_fee = hs_opps.parse_money(props.get(final_property or ""))
            target_stage = (
                hs_opps.STAGE_KEY_TO_HUB_STAGE.get(stage_key)
                or hs_opps.initial_stage_for_new_opportunity(stage_key, stage_dates)
            ) if stage_key else None

            fields = [
                {
                    "hub_column": "opp_position_name",
                    "hubspot_property": role_property,
                    "valor_en_hubspot": props.get(role_property or ""),
                    "entraria_como": role or None,
                },
                {
                    "hub_column": "opp_model",
                    "hubspot_property": model_property,
                    "valor_en_hubspot": props.get(model_property or ""),
                    "entraria_como": model,
                },
                {
                    "hub_column": "opp_sales_lead",
                    "hubspot_property": "(pipeline)",
                    "valor_en_hubspot": entry["label"],
                    "entraria_como": entry["sales_lead"],
                },
                {
                    "hub_column": "opp_type",
                    "hubspot_property": "(fijo)",
                    "valor_en_hubspot": None,
                    "entraria_como": "New",
                },
                {
                    "hub_column": "opp_stage",
                    "hubspot_property": "dealstage",
                    "valor_en_hubspot": entry["stage_labels"].get(dealstage_id),
                    "entraria_como": target_stage,
                    "nota": (
                        "Closed Won NO mueve el stage de una opp que ya existe (en el hub "
                        "'Close Win' significa que hubo contratacion). Este es el stage con "
                        "el que se crearia si todavia no existe."
                        if stage_key == "closed_won"
                        else "solo si el hub no esta ya mas adelante"
                    ),
                },
            ]
            for stage_key_date, column in (
                ("deep_dive", "deep_dive_date"),
                ("nda_sent", "nda_sent_date"),
                ("nda_signed", "nda_signature_or_start_date"),
            ):
                prop = entry["date_property_by_key"].get(stage_key_date)
                value = stage_dates.get(column)
                fields.append({
                    "hub_column": column,
                    "hubspot_property": prop,
                    "valor_en_hubspot": props.get(prop or ""),
                    "entraria_como": value.isoformat() if value else None,
                })
            fields.append({
                "hub_column": "hubspot_setup_fee",
                "hubspot_property": setup_property,
                "valor_en_hubspot": props.get(setup_property or ""),
                "entraria_como": str(setup_fee) if setup_fee is not None else None,
                "nota": "solo se escribe en Closed Won",
            })
            fields.append({
                "hub_column": "hubspot_final_fee",
                "hubspot_property": final_property,
                "valor_en_hubspot": props.get(final_property or ""),
                "entraria_como": str(final_fee) if final_fee is not None else None,
                "nota": "solo se escribe en Closed Won",
            })

            for field in fields:
                _track(field["hub_column"], field["entraria_como"])

            avisos = []
            if not stage_key:
                avisos.append(
                    "el stage '%s' no matchea ninguno de los que seguimos: el sync lo ignora"
                    % (entry["stage_labels"].get(dealstage_id) or dealstage_id)
                )
            elif stage_key == "intro_call":
                avisos.append("todavia en Intro Call: la opp se crea recien en Deep Dive")
            elif not role:
                avisos.append(
                    "sin Role to hire: si la opp todavia no existe en el hub, el sync NO la "
                    "crea (ese campo es opp_position_name y la llave para adoptar la manual)"
                )
            if stage_key and stage_key != "intro_call" and not model:
                avisos.append("sin Model: la opp se crearia con opp_model vacio")

            rows.append({
                "deal_id": str(deal.get("id") or ""),
                "dealname": props.get("dealname"),
                "pipeline": entry["label"],
                "pipeline_key": entry["key"],
                "stage_en_hubspot": entry["stage_labels"].get(dealstage_id),
                "stage_key": stage_key,
                "fields": fields,
                "avisos": avisos,
            })

            if len(rows) >= limit:
                break

        return jsonify({
            "success": True,
            "de_donde_sale_cada_campo": resolution,
            "stages": stages_resolution,
            "warnings": pipeline_map["warnings"],
            "deals_mirados": len(rows),
            "resumen_por_campo": health,
            "deals": rows,
        })
    except HubSpotError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502
    except Exception as exc:  # noqa: BLE001
        logging.exception("HubSpot opportunity preview failed")
        return jsonify({"success": False, "error": str(exc)}), 500
