import logging
import os
from datetime import datetime, timezone

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
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_account_hubspot_deal_id
        ON account (hubspot_deal_id)
        WHERE hubspot_deal_id IS NOT NULL AND hubspot_deal_id <> ''
        """
    )


def _normalize_bool(value):
    raw = str(value or "").strip().lower()
    if raw in ("yes", "true", "1"):
        return True
    if raw in ("no", "false", "0"):
        return False
    return None


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
        stage_ids = request.args.get("stage_ids") or os.environ.get("HUBSPOT_CLOSED_DEAL_STAGE_IDS", "closedwon")
        stage_ids = [part.strip() for part in stage_ids.split(",") if part.strip()]
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
        SET hubspot_deal_id = COALESCE(NULLIF(hubspot_deal_id, ''), NULLIF(%s, '')),
            hubspot_company_id = COALESCE(NULLIF(hubspot_company_id, ''), NULLIF(%s, '')),
            hubspot_contact_id = COALESCE(NULLIF(hubspot_contact_id, ''), NULLIF(%s, '')),
            hubspot_synced_at = %s
        WHERE account_id = %s
        """,
        (
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
        "dealname": deal_props.get("dealname"),
        "dealstage": deal_props.get("dealstage"),
        "pipeline": deal_props.get("pipeline"),
        "closedate": deal_props.get("closedate"),
        "lead_life_property": lead_life_property,
        "lead_life": deal_props.get(lead_life_property) if lead_life_property else None,
        "existing_account": existing,
    }


def _normalize_contact_preview_row(contact, deal, payload, existing, lead_life_property):
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
        "hubspot_contact_id": payload.get("hubspot_contact_id"),
        "hubspot_company_id": payload.get("hubspot_company_id"),
        "hubspot_deal_id": payload.get("hubspot_deal_id"),
        "client_name": client_name,
        "hubspot_company_name": hubspot_company_name,
        "crm_account_id": existing.get("account_id") if existing else None,
        "crm_client_name": existing.get("client_name") if existing else None,
        "contact_email": contact_props.get("email"),
        "contact_name": contact_name,
        "dealname": deal_props.get("dealname"),
        "dealstage": deal_props.get("dealstage"),
        "pipeline": deal_props.get("pipeline"),
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
        owner_id = client.get_owner_id_by_email(owner_email)
        contacts = client.search_contacts(
            [
                {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(owner_id)},
                {"propertyName": lead_life_property, "operator": "EQ", "value": lead_life_value},
            ],
            extra_properties=[lead_life_property],
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
                            extra_properties=[lead_life_property],
                            associations=["companies", "deals"],
                        )
                        company_ids = association_ids(contact, "companies")
                        deal_ids = association_ids(contact, "deals")
                        company = client.get_company(company_ids[0]) if company_ids else None
                        deal = client.get_deal_with_associations(deal_ids[0]) if deal_ids else {}
                        payload = build_account_payload(
                            deal,
                            company=company,
                            contact=contact,
                            owner_email=owner_email,
                        )
                        existing = _preview_existing_account(cursor, payload)
                        rows.append(_normalize_contact_preview_row(
                            contact,
                            deal,
                            payload,
                            existing,
                            lead_life_property,
                        ))
        finally:
            conn.close()

        return jsonify({
            "success": True,
            "owner_email": owner_email,
            "owner_id": owner_id,
            "lead_life_property": lead_life_property,
            "lead_life_value": lead_life_value,
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
        owner_id = client.get_owner_id_by_email(owner_email)
        contacts = client.search_contacts(
            [
                {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(owner_id)},
                {"propertyName": lead_life_property, "operator": "EQ", "value": lead_life_value},
            ],
            extra_properties=[lead_life_property],
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
                                extra_properties=[lead_life_property],
                                associations=["companies", "deals"],
                            )
                            company_ids = association_ids(contact, "companies")
                            deal_ids = association_ids(contact, "deals")
                            company = client.get_company(company_ids[0]) if company_ids else None
                            deal = client.get_deal_with_associations(deal_ids[0]) if deal_ids else {}
                            payload = build_account_payload(
                                deal,
                                company=company,
                                contact=contact,
                                owner_email=owner_email,
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
            "lead_life_property": lead_life_property,
            "lead_life_value": lead_life_value,
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
        stage_ids = request.args.get("stage_ids") or os.environ.get("HUBSPOT_CLOSED_DEAL_STAGE_IDS", "closedwon")
        stage_ids = [part.strip() for part in stage_ids.split(",") if part.strip()]
        pipeline_id = request.args.get("pipeline_id") or os.environ.get("HUBSPOT_PIPELINE_ID")

        client = HubSpotClient()
        owner_id = client.get_owner_id_by_email(owner_email)
        deals = client.search_closed_deals(
            owner_id,
            stage_ids=stage_ids,
            pipeline_id=pipeline_id,
        )

        rows = []
        conn = get_connection()
        try:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    _ensure_hubspot_account_columns(cursor)
                    for deal_summary in deals:
                        deal_id = str(deal_summary.get("id") or "")
                        deal = client.get_deal_with_associations(deal_id)
                        company_ids = association_ids(deal, "companies")
                        contact_ids = association_ids(deal, "contacts")
                        company = client.get_company(company_ids[0]) if company_ids else None
                        contact = client.get_contact(contact_ids[0]) if contact_ids else None
                        payload = build_account_payload(
                            deal,
                            company=company,
                            contact=contact,
                            owner_email=owner_email,
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
        owner_id = client.get_owner_id_by_email(owner_email)
        filters = [
            {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(owner_id)},
            {"propertyName": lead_life_property, "operator": "EQ", "value": lead_life_value},
        ]
        if pipeline_id:
            filters.append({"propertyName": "pipeline", "operator": "EQ", "value": str(pipeline_id)})
        deals = client.search_deals(filters, extra_properties=[lead_life_property])

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
                            extra_properties=[lead_life_property],
                        )
                        company_ids = association_ids(deal, "companies")
                        contact_ids = association_ids(deal, "contacts")
                        company = client.get_company(company_ids[0]) if company_ids else None
                        contact = client.get_contact(contact_ids[0]) if contact_ids else None
                        payload = build_account_payload(
                            deal,
                            company=company,
                            contact=contact,
                            owner_email=owner_email,
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
        "where_come_from": payload.get("where_come_from") or "HubSpot",
        "referal_source": payload.get("referal_source"),
        "industry": payload.get("industry"),
        "outsource": _normalize_bool(payload.get("outsource")),
        "pain_points": payload.get("pain_points"),
        "position": payload.get("position"),
        "type": payload.get("type") or "NA",
        "name": payload.get("contact_name"),
        "surname": payload.get("contact_surname"),
        "account_manager": payload.get("account_manager") or DEFAULT_MARIANO_EMAIL,
        "hubspot_deal_id": payload.get("hubspot_deal_id"),
        "hubspot_company_id": payload.get("hubspot_company_id"),
        "hubspot_contact_id": payload.get("hubspot_contact_id"),
        "hubspot_synced_at": now,
    }

    if existing:
        account_id = existing["account_id"] if isinstance(existing, dict) else existing[0]
        cursor.execute(
            """
            UPDATE account
            SET size = COALESCE(%(size)s, size),
                timezone = COALESCE(NULLIF(%(timezone)s, ''), timezone),
                state = COALESCE(NULLIF(%(state)s, ''), state),
                website = COALESCE(NULLIF(%(website)s, ''), website),
                linkedin = COALESCE(NULLIF(%(linkedin)s, ''), linkedin),
                comments = COALESCE(NULLIF(%(comments)s, ''), comments),
                mail = COALESCE(NULLIF(%(mail)s, ''), mail),
                where_come_from = COALESCE(NULLIF(%(where_come_from)s, ''), where_come_from),
                referal_source = COALESCE(NULLIF(%(referal_source)s, ''), referal_source),
                industry = COALESCE(NULLIF(%(industry)s, ''), industry),
                outsource = COALESCE(%(outsource)s, outsource),
                pain_points = COALESCE(NULLIF(%(pain_points)s, ''), pain_points),
                position = COALESCE(NULLIF(%(position)s, ''), position),
                type = COALESCE(NULLIF(%(type)s, ''), type),
                name = COALESCE(NULLIF(%(name)s, ''), name),
                surname = COALESCE(NULLIF(%(surname)s, ''), surname),
                account_manager = COALESCE(NULLIF(%(account_manager)s, ''), account_manager),
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
            where_come_from, referal_source,
            industry, outsource, pain_points, position, type,
            name, surname, account_manager,
            hubspot_deal_id, hubspot_company_id, hubspot_contact_id, hubspot_synced_at
        ) VALUES (
            %(client_name)s, %(size)s, %(timezone)s, %(state)s,
            %(website)s, %(linkedin)s, %(comments)s, %(mail)s,
            %(where_come_from)s, %(referal_source)s,
            %(industry)s, %(outsource)s, %(pain_points)s, %(position)s, %(type)s,
            %(name)s, %(surname)s, %(account_manager)s,
            %(hubspot_deal_id)s, %(hubspot_company_id)s, %(hubspot_contact_id)s, %(hubspot_synced_at)s
        )
        RETURNING account_id
        """,
        values,
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
        stage_ids = body.get("stage_ids") or comma_env("HUBSPOT_CLOSED_DEAL_STAGE_IDS", "closedwon")
        if isinstance(stage_ids, str):
            stage_ids = [part.strip() for part in stage_ids.split(",") if part.strip()]
        pipeline_id = body.get("pipeline_id") or os.environ.get("HUBSPOT_PIPELINE_ID")
        modified_after_ms = hubspot_datetime_to_ms(
            body.get("modified_after") or os.environ.get("HUBSPOT_SYNC_MODIFIED_AFTER")
        )

        client = HubSpotClient()
        owner_id = client.get_owner_id_by_email(owner_email)
        deals = client.search_closed_deals(
            owner_id,
            stage_ids=stage_ids,
            pipeline_id=pipeline_id,
            modified_after_ms=modified_after_ms,
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
                            deal = client.get_deal_with_associations(deal_id)
                            company_ids = association_ids(deal, "companies")
                            contact_ids = association_ids(deal, "contacts")
                            company = client.get_company(company_ids[0]) if company_ids else None
                            contact = client.get_contact(contact_ids[0]) if contact_ids else None
                            payload = build_account_payload(
                                deal,
                                company=company,
                                contact=contact,
                                owner_email=owner_email,
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
