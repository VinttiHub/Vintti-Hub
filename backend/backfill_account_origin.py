"""Backfill ÚNICO de account.where_come_from (origin) + conversion_channel desde HubSpot.

PROBLEMA: las cuentas VIEJAS (creadas antes del sync) no tienen origin ni
conversion_channel → aparecen como "(Sin origen)" en el tab Marketing. El sync
normal (`/hubspot/sync/mariano-sql-contacts`) SOLO cubre lead_life='SQL (AE)' +
owner Mariano, así que nunca las toca.

QUÉ HACE (sin modificar el sync normal):
  1. Trae todos los contactos de HubSpot (reusa HubSpotClient + la misma lógica de
     lectura de propiedades que el sync: _resolve_account_property_maps,
     _first_mapped_value, _normalize_lead_source).
  2. Los indexa por EMAIL (match exacto y seguro: account.mail = contact.email).
  3. Para cada cuenta a la que le falte origin Y/O conversion_channel, busca su
     contacto por email y rellena SOLO los campos vacíos (COALESCE → no pisa nada).
  4. De paso setea hubspot_contact_id si está vacío (causa raíz: a estas cuentas
     les falta el id; así el sync normal a futuro las puede incluir).
     → desactivable con --no-link.

SEGURIDAD: dry-run por defecto (no escribe). Solo escribe con --apply.
Match SOLO por email (no por nombre) para no arriesgar cruces equivocados; las
cuentas sin mail o cuyo email no esté en HubSpot quedan sin rellenar (se reportan).

USO (desde backend/, con RDS_PASSWORD y HUBSPOT_PRIVATE_APP_TOKEN en backend/.env):
    python backfill_account_origin.py            # DRY-RUN: reporta, no escribe
    python backfill_account_origin.py --apply     # aplica los cambios
    python backfill_account_origin.py --apply --no-link   # no toca hubspot_contact_id
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from db import get_connection
from utils.hubspot import HubSpotClient
from routes.hubspot_routes import (
    _resolve_account_property_maps,
    _first_mapped_value,
    _normalize_lead_source,
)

APPLY = "--apply" in sys.argv
LINK_CID = "--no-link" not in sys.argv


def main() -> None:
    client = HubSpotClient()
    pm = _resolve_account_property_maps(client)
    origin_prop = (pm.get("contacts") or {}).get("where_come_from")
    channel_prop = (pm.get("contacts") or {}).get("conversion_channel")
    extra = [p for p in (origin_prop, channel_prop, "email") if p]

    # Catch-all: todos los contactos que tienen email.
    contacts = client.search_contacts(
        [{"propertyName": "email", "operator": "HAS_PROPERTY"}],
        extra_properties=extra,
    )
    by_email: dict[str, dict] = {}
    for c in contacts:
        props = c.get("properties") or {}
        email = str(props.get("email") or "").strip().lower()
        if not email:
            continue
        origin = _normalize_lead_source(_first_mapped_value(pm, "where_come_from", contact=c)) or ""
        channel = (_first_mapped_value(pm, "conversion_channel", contact=c) or "").strip()
        by_email[email] = {"origin": origin, "channel": channel, "cid": str(c.get("id") or "")}
    print(f"HubSpot: {len(contacts)} contactos, {len(by_email)} con email.")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT account_id, client_name, LOWER(TRIM(mail)),
               where_come_from, conversion_channel, hubspot_contact_id
        FROM account
        WHERE (where_come_from IS NULL OR TRIM(where_come_from) = ''
               OR conversion_channel IS NULL OR TRIM(conversion_channel) = '')
          AND mail IS NOT NULL AND TRIM(mail) <> ''
        """
    )
    rows = cur.fetchall()

    updates = []  # (acc_id, name, wcf, new_wcf, cc, new_cc, hcid, new_cid)
    matched = 0
    for acc_id, name, mail, wcf, cc, hcid in rows:
        m = by_email.get(mail)
        if not m:
            continue
        matched += 1
        new_wcf = m["origin"] if (not (wcf or "").strip()) and m["origin"] else ""
        new_cc = m["channel"] if (not (cc or "").strip()) and m["channel"] else ""
        new_cid = m["cid"] if (LINK_CID and not (hcid or "").strip()) and m["cid"] else ""
        if not (new_wcf or new_cc or new_cid):
            continue
        updates.append((acc_id, name, wcf, new_wcf, cc, new_cc, hcid, new_cid))

    print(f"Cuentas candidatas (sin origin/channel, con mail): {len(rows)}")
    print(f"  matcheadas por email en HubSpot:  {matched}")
    print(f"  con algo para rellenar:           {len(updates)}")
    print(f"  sin match por email (quedan así): {len(rows) - matched}")
    print("\nMuestra (primeras 20):")
    for acc_id, name, wcf, nwcf, cc, ncc, hcid, ncid in updates[:20]:
        print(
            f"  [{acc_id}] {str(name)[:22]:22s} "
            f"origin {wcf!r}->{nwcf or '(=)'}  "
            f"channel {cc!r}->{ncc or '(=)'}  "
            f"cid:{'set' if ncid else '-'}"
        )

    if not APPLY:
        print("\nDRY-RUN: no se escribió nada. Corré con --apply para aplicar.")
        cur.close()
        conn.close()
        return

    n = 0
    for acc_id, name, wcf, nwcf, cc, ncc, hcid, ncid in updates:
        cur.execute(
            """
            UPDATE account SET
              where_come_from    = COALESCE(NULLIF(%(wcf)s, ''), where_come_from),
              conversion_channel = COALESCE(NULLIF(%(cc)s, ''),  conversion_channel),
              hubspot_contact_id = COALESCE(NULLIF(%(cid)s, ''), hubspot_contact_id)
            WHERE account_id = %(id)s
            """,
            {"wcf": nwcf, "cc": ncc, "cid": ncid, "id": acc_id},
        )
        n += cur.rowcount
    conn.commit()
    print(f"\nAPLICADO: {n} cuentas actualizadas.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
