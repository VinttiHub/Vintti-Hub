import logging
import os
from datetime import date, datetime, timezone

from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor

from db import get_connection
from utils.hubspot import (
    DEFAULT_MARIANO_EMAIL,
    HubSpotClient,
    HubSpotError,
    association_ids,
    build_account_payload,
    comma_env,
    hubspot_datetime_to_ms,
)


bp = Blueprint("hubspot", __name__)

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


def _require_sync_secret():
    expected = os.environ.get("HUBSPOT_SYNC_SECRET")
    if not expected:
        return None
    received = request.headers.get("X-HubSpot-Sync-Secret") or request.args.get("secret")
    if received != expected:
        return jsonify({"error": "Unauthorized"}), 401
    return None


def _ensure_hubspot_account_columns(cursor):
    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS hubspot_deal_id TEXT")
    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS hubspot_company_id TEXT")
    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS hubspot_contact_id TEXT")
    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS hubspot_synced_at TIMESTAMPTZ")
    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS vintti_ai BOOLEAN NOT NULL DEFAULT FALSE")
    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS lead_source_detail TEXT")
    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS conversion_channel TEXT")
    cursor.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS credit_loop TEXT")
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_account_hubspot_deal_id
        ON account (hubspot_deal_id)
        WHERE hubspot_deal_id IS NOT NULL AND hubspot_deal_id <> ''
        """
    )


def _ensure_opportunity_stage_date_columns(cursor):
    cursor.execute("ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS deep_dive_date DATE")
    cursor.execute("ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS nda_sent_date DATE")


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


def _resolve_account_property_maps(client):
    contacts, contact_options = _resolve_property_map_for_object(client, "contacts")
    companies, company_options = _resolve_property_map_for_object(client, "companies")
    deals, deal_options = _resolve_property_map_for_object(client, "deals")
    return {
        "contacts": contacts,
        "companies": companies,
        "deals": deals,
        "_option_labels": {
            "contacts": contact_options,
            "companies": company_options,
            "deals": deal_options,
        },
    }


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
            payload.get("size"),
            payload.get("timezone"),
            payload.get("state"),
            payload.get("website"),
            payload.get("linkedin"),
            payload.get("about"),
            payload.get("mail"),
            _normalize_lead_source(payload.get("where_come_from")),
            payload.get("lead_source_detail"),
            payload.get("conversion_channel"),
            payload.get("referal_source"),
            payload.get("industry"),
            _normalize_outsource_value(payload.get("outsource")),
            payload.get("pain_points"),
            payload.get("contract"),
            payload.get("position"),
            payload.get("type"),
            payload.get("contact_name"),
            payload.get("contact_surname"),
            payload.get("account_manager"),
            _normalize_credit_loop_value(payload.get("credit_loop")),
            _normalize_boolean_value(payload.get("vintti_ai")),
            payload.get("hubspot_deal_id"),
            payload.get("hubspot_company_id"),
            payload.get("hubspot_contact_id"),
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
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    _ensure_hubspot_account_columns(cursor)
                    for contact_summary in contacts:
                        contact_id = str(contact_summary.get("id") or "")
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
                                action = "created"

                            contact_props = contact.get("properties") or {}
                            synced.append({
                                "contact_id": contact_id,
                                "deal_id": payload.get("hubspot_deal_id"),
                                "account_id": account_id,
                                "action": action,
                                "client_name": payload.get("name"),
                                "contact_email": contact_props.get("email"),
                                "meeting_datetime": contact_props.get(meeting_datetime_property),
                                "lead_life": contact_props.get(lead_life_property),
                            })
                        except Exception as exc:
                            logging.exception("HubSpot contact sync failed for contact %s", contact_id)
                            errors.append({"contact_id": contact_id, "error": str(exc)})
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
        "hubspot_deal_id": payload.get("hubspot_deal_id"),
        "hubspot_company_id": payload.get("hubspot_company_id"),
        "hubspot_contact_id": payload.get("hubspot_contact_id"),
        "credit_loop": _normalize_credit_loop_value(payload.get("credit_loop")),
        "vintti_ai": _normalize_boolean_value(payload.get("vintti_ai")),
        "hubspot_synced_at": now,
    }

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
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    _ensure_hubspot_account_columns(cursor)
                    for deal_summary in deals:
                        deal_id = str(deal_summary.get("id") or "")
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
                            synced.append({
                                "deal_id": deal_id,
                                "account_id": result["account_id"],
                                "action": result["action"],
                                "client_name": payload.get("name"),
                            })
                        except Exception as exc:
                            logging.exception("HubSpot deal sync failed for deal %s", deal_id)
                            errors.append({"deal_id": deal_id, "error": str(exc)})
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
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    _ensure_opportunity_stage_date_columns(cursor)
                    _ensure_hubspot_account_columns(cursor)

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

                            updated.append({
                                "opportunity_id": row.get("opportunity_id"),
                                "deal_id": deal_id,
                                "nda_sent_date": nda_sent_date.isoformat(),
                            })
                        except Exception as exc:  # noqa: BLE001
                            logging.exception(
                                "HubSpot NDA sent date backfill failed for deal %s",
                                deal_id,
                            )
                            errors.append({
                                "opportunity_id": row.get("opportunity_id"),
                                "deal_id": deal_id,
                                "error": str(exc),
                            })
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
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    _ensure_opportunity_stage_date_columns(cursor)
                    _ensure_hubspot_account_columns(cursor)

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

                            updated.append({
                                "opportunity_id": row.get("opportunity_id"),
                                "deal_id": deal_id,
                                "deep_dive_date": deep_dive_date.isoformat(),
                            })
                        except Exception as exc:  # noqa: BLE001
                            logging.exception(
                                "HubSpot Deep Dive date backfill failed for deal %s",
                                deal_id,
                            )
                            errors.append({
                                "opportunity_id": row.get("opportunity_id"),
                                "deal_id": deal_id,
                                "error": str(exc),
                            })
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
