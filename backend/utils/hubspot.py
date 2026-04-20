import os
from datetime import datetime, timezone

import requests


HUBSPOT_API_BASE = "https://api.hubapi.com"
DEFAULT_MARIANO_EMAIL = "mariano@vintti.com"


class HubSpotError(RuntimeError):
    pass


class HubSpotClient:
    def __init__(self, token=None):
        self.token = token or os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")
        if not self.token:
            raise HubSpotError("Missing HUBSPOT_PRIVATE_APP_TOKEN")

    def _request(self, method, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })
        response = requests.request(
            method,
            f"{HUBSPOT_API_BASE}{path}",
            headers=headers,
            timeout=30,
            **kwargs,
        )
        if not response.ok:
            raise HubSpotError(f"HubSpot {method} {path} failed: {response.status_code} {response.text}")
        if response.status_code == 204:
            return {}
        return response.json()

    def get_owner_id_by_email(self, email):
        target = (email or DEFAULT_MARIANO_EMAIL).strip().lower()
        payload = self._request("GET", "/crm/v3/owners/", params={"email": target, "archived": "false"})
        for owner in payload.get("results", []):
            if (owner.get("email") or "").strip().lower() == target:
                return str(owner.get("id"))

        payload = self._request("GET", "/crm/v3/owners/", params={"limit": 500, "archived": "false"})
        for owner in payload.get("results", []):
            if (owner.get("email") or "").strip().lower() == target:
                return str(owner.get("id"))
        raise HubSpotError(f"No HubSpot owner found for {target}")

    def get_properties(self, object_type):
        payload = self._request("GET", f"/crm/v3/properties/{object_type}")
        return payload.get("results", [])

    def search_closed_deals(self, owner_id, stage_ids=None, pipeline_id=None, modified_after_ms=None):
        filters = [
            {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(owner_id)},
        ]
        if stage_ids is None:
            stage_ids = ["closedwon"]
        stages = [stage.strip() for stage in stage_ids if stage and stage.strip()]
        if len(stages) == 1:
            filters.append({"propertyName": "dealstage", "operator": "EQ", "value": stages[0]})
        elif len(stages) > 1:
            filters.append({"propertyName": "dealstage", "operator": "IN", "values": stages})
        if pipeline_id:
            filters.append({"propertyName": "pipeline", "operator": "EQ", "value": str(pipeline_id)})
        if modified_after_ms:
            filters.append({
                "propertyName": "hs_lastmodifieddate",
                "operator": "GTE",
                "value": str(modified_after_ms),
            })
        return self.search_deals(filters)

    def search_deals(self, filters, extra_properties=None):
        properties = [
            "dealname",
            "dealstage",
            "pipeline",
            "hubspot_owner_id",
            "closedate",
            "createdate",
            "hs_lastmodifieddate",
            "amount",
        ]
        for prop in extra_properties or []:
            if prop and prop not in properties:
                properties.append(prop)
        results = []
        after = None
        while True:
            body = {
                "filterGroups": [{"filters": filters}],
                "properties": properties,
                "limit": 100,
                "sorts": [{"propertyName": "hs_lastmodifieddate", "direction": "DESCENDING"}],
            }
            if after:
                body["after"] = after
            payload = self._request("POST", "/crm/v3/objects/deals/search", json=body)
            results.extend(payload.get("results", []))
            after = payload.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        return results

    def search_contacts(self, filters, extra_properties=None):
        properties = [
            "firstname",
            "lastname",
            "email",
            "jobtitle",
            "hubspot_owner_id",
            "createdate",
            "lastmodifieddate",
        ]
        for prop in extra_properties or []:
            if prop and prop not in properties:
                properties.append(prop)
        results = []
        after = None
        while True:
            body = {
                "filterGroups": [{"filters": filters}],
                "properties": properties,
                "limit": 100,
                "sorts": [{"propertyName": "lastmodifieddate", "direction": "DESCENDING"}],
            }
            if after:
                body["after"] = after
            payload = self._request("POST", "/crm/v3/objects/contacts/search", json=body)
            results.extend(payload.get("results", []))
            after = payload.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        return results

    def get_deal_with_associations(self, deal_id, extra_properties=None):
        properties = [
            "dealname",
            "dealstage",
            "pipeline",
            "hubspot_owner_id",
            "closedate",
            "createdate",
            "hs_lastmodifieddate",
            "amount",
        ]
        for prop in extra_properties or []:
            if prop and prop not in properties:
                properties.append(prop)
        return self._request(
            "GET",
            f"/crm/v3/objects/deals/{deal_id}",
            params={
                "properties": ",".join(properties),
                "associations": "companies,contacts",
                "archived": "false",
            },
        )

    def get_company(self, company_id, extra_properties=None):
        properties = [
            "name",
            "domain",
            "website",
            "industry",
            "state",
            "city",
            "country",
            "numberofemployees",
            "description",
        ]
        for prop in extra_properties or []:
            if prop and prop not in properties:
                properties.append(prop)
        return self._request(
            "GET",
            f"/crm/v3/objects/companies/{company_id}",
            params={
                "properties": ",".join(properties),
                "archived": "false",
            },
        )

    def get_contact(self, contact_id, extra_properties=None, associations=None):
        properties = [
            "firstname",
            "lastname",
            "email",
            "jobtitle",
            "state",
            "city",
            "country",
            "hubspot_owner_id",
            "createdate",
            "lastmodifieddate",
        ]
        for prop in extra_properties or []:
            if prop and prop not in properties:
                properties.append(prop)
        params = {
            "properties": ",".join(properties),
            "archived": "false",
        }
        if associations:
            params["associations"] = ",".join(associations)
        return self._request(
            "GET",
            f"/crm/v3/objects/contacts/{contact_id}",
            params=params,
        )


def comma_env(name, default):
    raw = os.environ.get(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


def association_ids(record, association_name):
    associations = record.get("associations") or {}
    assoc = associations.get(association_name) or {}
    return [str(item.get("id")) for item in assoc.get("results", []) if item.get("id")]


def employee_size_bucket(value):
    try:
        count = int(str(value or "").replace(",", "").strip())
    except ValueError:
        return ""
    if count <= 10:
        return "1-10"
    if count <= 50:
        return "11-50"
    if count <= 200:
        return "51-200"
    if count <= 500:
        return "201-500"
    return "+500"


def normalize_website(company_props):
    website = (company_props.get("website") or company_props.get("domain") or "").strip()
    return website


def normalize_account_name_from_deal(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    for separator in (" - ", " – ", " — "):
        if separator in raw:
            before = raw.split(separator, 1)[0].strip()
            if before:
                return before
    return raw


def build_account_payload(deal, company=None, contact=None, owner_email=DEFAULT_MARIANO_EMAIL):
    deal = deal or {}
    deal_props = deal.get("properties") or {}
    company_props = (company or {}).get("properties") or {}
    contact_props = (contact or {}).get("properties") or {}
    contact_name = " ".join(
        part for part in [
            contact_props.get("firstname") or "",
            contact_props.get("lastname") or "",
        ]
        if part
    ).strip()

    deal_company_name = normalize_account_name_from_deal(deal_props.get("dealname"))
    company_name = (
        company_props.get("name")
        or deal_company_name
        or contact_props.get("email")
        or contact_name
        or f"HubSpot deal {deal.get('id')}"
    )
    closedate = deal_props.get("closedate") or ""
    amount = deal_props.get("amount") or ""
    description = company_props.get("description") or ""
    notes = [
        "Imported from HubSpot.",
        f"Deal: {deal_props.get('dealname') or deal.get('id')}",
    ]
    if closedate:
        notes.append(f"Close date: {closedate}")
    if amount:
        notes.append(f"Amount: {amount}")
    if description:
        notes.append(description)

    return {
        "name": company_name,
        "size": employee_size_bucket(company_props.get("numberofemployees")),
        "timezone": "",
        "state": company_props.get("state") or contact_props.get("state") or "",
        "website": normalize_website(company_props),
        "linkedin": "",
        "about": "\n".join(notes),
        "mail": contact_props.get("email") or "",
        "where_come_from": "HubSpot",
        "referal_source": None,
        "industry": company_props.get("industry") or "",
        "outsource": None,
        "pain_points": "",
        "position": contact_props.get("jobtitle") or "",
        "type": "NA",
        "contact_name": contact_props.get("firstname") or "",
        "contact_surname": contact_props.get("lastname") or "",
        "account_manager": owner_email,
        "hubspot_deal_id": str(deal.get("id") or ""),
        "hubspot_company_id": str((company or {}).get("id") or ""),
        "hubspot_contact_id": str((contact or {}).get("id") or ""),
        "_hubspot_company_name": company_props.get("name") or "",
    }


def hubspot_datetime_to_ms(value):
    if not value:
        return None
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None
