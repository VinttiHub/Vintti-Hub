"""Edicion de campos de Account Details -> HubSpot.

Cuando alguien de ACCOUNT_EDITORS edita un campo con el lapiz de
docs/account-details.html, el PATCH /accounts/<id>?push_hubspot=1 guarda en el hub
y despues llama a push_account_fields() para escribir el mismo valor en HubSpot.

Por que hace falta: el sync HubSpot -> hub (`_insert_or_update_account` /
`_link_existing_account_to_hubspot`) hace "HubSpot gana cuando tiene valor", y corre
cada 30 min a traves del sync de opps. Si el valor nuevo no llega a HubSpot, el
proximo sync lo pisa con el viejo.

Reglas:
- Se escribe en el MISMO objeto del que lee el sync: `_first_mapped_value` mira
  contact -> company -> deal y toma el primero con valor. Escribir en otro objeto
  dejaria al sync leyendo el viejo. Se elige el primero de ese orden que tenga la
  propiedad en su schema Y del que la cuenta tenga id.
- Los desplegables de HubSpot piden el VALUE interno, no el label que guarda el
  hub. Se traduce invirtiendo las options; un valor que no matchea ninguna opcion
  NO se manda (sale en `rechazados` con las opciones validas).
- NUNCA levanta: el valor ya se guardo en el hub y la persona lo vio cambiar.
"""

import json
import logging
import re

from db import get_connection
from utils.hubspot import HubSpotClient, HubSpotError

# columna de `account` -> clave de HUBSPOT_ACCOUNT_FIELD_ALIASES (hubspot_routes.py)
ACCOUNT_COLUMN_TO_HUBSPOT_FIELD = {
    "client_name": "client_name",
    "size": "size",
    "state": "state",
    "name": "contact_name",
    "surname": "contact_surname",
    "mail": "mail",
    "industry": "industry",
    "where_come_from": "where_come_from",
    "lead_source_detail": "lead_source_detail",
    "conversion_channel": "conversion_channel",
    "credit_loop": "credit_loop",
    "referal_source": "referal_source",
    "outsource": "outsource",
    "position": "position",
    "type": "type",
    "linkedin": "linkedin",
    "website": "website",
}

# Existen solo en el hub: se guardan, pero no viajan.
HUB_ONLY_COLUMNS = {"timezone"}

OBJECT_ORDER = ("contacts", "companies", "deals")


def _normalizers():
    # Import tardio: hubspot_routes importa medio backend y este modulo lo usa
    # accounts_routes; amarrarlo en el import arriesga un ciclo.
    from routes.hubspot_routes import (
        _normalize_credit_loop_value,
        _normalize_lead_source,
        _normalize_outsource_value,
    )
    return {
        "where_come_from": _normalize_lead_source,
        "outsource": _normalize_outsource_value,
        "credit_loop": _normalize_credit_loop_value,
    }


def _norm_key(column, value):
    """Clave de comparacion: la misma normalizacion que aplica el sync al leer."""
    fn = _normalizers().get(column)
    raw = str(value or "").strip()
    if fn:
        raw = str(fn(raw) or "").strip()
    return raw.lower()


def _property_maps(client):
    from routes.hubspot_routes import _resolve_account_property_maps
    return _resolve_account_property_maps(client)


def _options_for(maps, object_type, hs_field):
    return maps.get("_option_labels", {}).get(object_type, {}).get(hs_field) or {}


def select_options(client=None):
    """Opciones de cada columna que en HubSpot es un desplegable.

    Devuelve {columna: [label, ...]} con los labels YA normalizados como los guarda
    el hub (ej. "LinkedIn" -> "Social Media" en Lead Source), sin repetidos. Sale del
    primer objeto (contact -> company -> deal) que tenga la propiedad con opciones,
    el mismo orden en que se escribe.
    """
    client = client or HubSpotClient()
    maps = _property_maps(client)
    fns = _normalizers()
    out = {}
    for column, hs_field in ACCOUNT_COLUMN_TO_HUBSPOT_FIELD.items():
        for object_type in OBJECT_ORDER:
            if not maps.get(object_type, {}).get(hs_field):
                continue
            options = _options_for(maps, object_type, hs_field)
            if options:
                labels, seen = [], set()
                for label in options.values():
                    shown = fns[column](label) if column in fns else label
                    shown = str(shown or "").strip()
                    if shown and shown.lower() not in seen:
                        seen.add(shown.lower())
                        labels.append(shown)
                out[column] = labels
            break
    return out


def _to_hubspot_value(column, value, options):
    """Label del hub -> value interno de HubSpot. None si no matchea ninguna."""
    text = str(value or "").strip()
    if not text:
        return ""  # vaciar la propiedad
    target = _norm_key(column, text)
    for opt_value, opt_label in options.items():
        if str(opt_value).strip().lower() == text.lower():
            return opt_value
        if str(opt_label).strip().lower() == text.lower():
            return opt_value
    for opt_value, opt_label in options.items():
        if _norm_key(column, opt_label) == target:
            return opt_value
    return None


def _load_account_ids(account_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT hubspot_contact_id, hubspot_company_id, hubspot_deal_id, mail
                FROM account WHERE account_id = %s
                """,
                (account_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    contact_id, company_id, deal_id, mail = row
    return {
        "contacts": (contact_id or "").strip() or None,
        "companies": (company_id or "").strip() or None,
        "deals": (deal_id or "").strip() or None,
        "mail": (mail or "").strip(),
    }


def _find_contact_by_email(client, account_id, email):
    """Cuentas viejas no tienen hubspot_contact_id: se busca por email exacto.

    Solo se adopta si hay UN contacto con ese email, y el id se guarda con COALESCE
    (nunca pisa uno existente), como el backfill por email de origin.
    """
    if not email or "@" not in email:
        return None
    results = client.search_contacts(
        [{"propertyName": "email", "operator": "EQ", "value": email.lower()}]
    )
    if len(results) != 1:
        return None
    contact_id = str(results[0].get("id") or "").strip() or None
    if contact_id:
        conn = get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE account
                        SET hubspot_contact_id = COALESCE(NULLIF(hubspot_contact_id, ''), %s)
                        WHERE account_id = %s
                        """,
                        (contact_id, account_id),
                    )
        finally:
            conn.close()
    return contact_id


def _is_scope_error(exc):
    text = str(exc)
    return " 403 " in text or "MISSING_SCOPES" in text


def _is_validation_error(exc):
    """HubSpot rechazo el VALOR (400 VALIDATION_ERROR): email invalido, email que ya
    tiene otro contacto, opcion inexistente... Distinto de un error de red/permiso:
    aca el valor nunca va a entrar, asi que el hub tiene que volver al anterior."""
    text = str(exc)
    return " 400 " in text and "VALIDATION_ERROR" in text


def _hubspot_message(exc):
    """El mensaje legible de HubSpot, sin el JSON alrededor."""
    text = str(exc)
    if "already has that value" in text:
        # Email (y otras unicas): HubSpot no deja dos contactos con el mismo valor.
        return "another HubSpot contact already uses this value"
    start = text.find("{")
    if start >= 0:
        try:
            body = json.loads(text[start:])
            msgs = [e.get("message") for e in body.get("errors") or [] if e.get("message")]
            if msgs:
                return "; ".join(msgs)[:300]
            msg = str(body.get("message") or "")
            match = re.search(r'\\?"message\\?":\\?"([^"\\]+)', msg)
            return (match.group(1) if match else msg)[:300]
        except ValueError:
            pass
    return text[:300]


def push_account_fields(account_id, changed):
    """Escribe en HubSpot las columnas editadas. NUNCA levanta.

    `changed` = {columna_de_account: valor_guardado_en_el_hub}.
    Devuelve {escritos: [...], omitidos: [{campo, motivo}], rechazados: [...], error}.
    Motivos de omitidos: solo_hub, sin_hubspot, sin_propiedad, sin_scope, invalido
    (HubSpot rechazo el valor: el PATCH de la cuenta lo revierte en el hub), error.
    """
    result = {"escritos": [], "omitidos": [], "rechazados": [], "error": None}
    try:
        pending = {}
        for column, value in (changed or {}).items():
            if column in HUB_ONLY_COLUMNS:
                result["omitidos"].append({"campo": column, "motivo": "solo_hub"})
            elif column in ACCOUNT_COLUMN_TO_HUBSPOT_FIELD:
                pending[column] = value
        if not pending:
            return result

        ids = _load_account_ids(account_id)
        if ids is None:
            result["error"] = "cuenta inexistente"
            return result

        client = HubSpotClient()
        if not ids["contacts"]:
            try:
                ids["contacts"] = _find_contact_by_email(client, account_id, ids["mail"])
            except Exception:  # noqa: BLE001 - la busqueda es un extra, no frena el push
                logging.exception("account %s: busqueda de contacto por email fallo", account_id)

        if not any(ids[o] for o in OBJECT_ORDER):
            for column in pending:
                result["omitidos"].append({"campo": column, "motivo": "sin_hubspot"})
            return result

        maps = _property_maps(client)
        by_object = {}  # object_type -> {prop_name: value}
        where = {}      # (object_type, prop_name) -> columna
        for column, value in pending.items():
            hs_field = ACCOUNT_COLUMN_TO_HUBSPOT_FIELD[column]
            target = None
            for object_type in OBJECT_ORDER:
                prop = maps.get(object_type, {}).get(hs_field)
                if prop and ids[object_type]:
                    target = (object_type, prop)
                    break
            if not target:
                has_prop = any(maps.get(o, {}).get(hs_field) for o in OBJECT_ORDER)
                result["omitidos"].append(
                    {"campo": column, "motivo": "sin_hubspot" if has_prop else "sin_propiedad"}
                )
                continue
            object_type, prop = target
            options = _options_for(maps, object_type, hs_field)
            hs_value = _to_hubspot_value(column, value, options) if options else (
                "" if value is None else str(value).strip()
            )
            if hs_value is None:
                result["rechazados"].append({
                    "campo": column,
                    "valor": value,
                    "opciones": sorted({str(v) for v in options.values()}),
                })
                continue
            by_object.setdefault(object_type, {})[prop] = hs_value
            where[(object_type, prop)] = column

        writers = {
            "contacts": client.update_contact,
            "companies": client.update_company,
            "deals": client.update_deal,
        }
        for object_type, props in by_object.items():
            columns = [where[(object_type, p)] for p in props]
            try:
                writers[object_type](ids[object_type], props)
                for p, v in props.items():
                    result["escritos"].append({
                        "campo": where[(object_type, p)],
                        "objeto": object_type,
                        "propiedad": p,
                        "valor": v,
                    })
            except HubSpotError as exc:
                if _is_scope_error(exc):
                    motivo = "sin_scope"
                elif _is_validation_error(exc):
                    motivo = "invalido"
                else:
                    motivo = "error"
                logging.warning("account %s: push a HubSpot %s fallo: %s", account_id, object_type, exc)
                for column in columns:
                    result["omitidos"].append(
                        {"campo": column, "motivo": motivo, "detalle": _hubspot_message(exc)}
                    )
    except Exception as exc:  # noqa: BLE001
        logging.exception("account %s: push de campos a HubSpot fallo", account_id)
        result["error"] = str(exc)[:300]
    return result
