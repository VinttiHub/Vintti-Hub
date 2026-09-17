"""Chequea que un token de HubSpot sirva para TODO lo que el repo le pide.

Existe para hacer seguro el cambio de token: si se rota la app privada y al token
nuevo le falta uno de los scopes, no se rompe en el momento — se rompe despues, de
noche, en el cron del sync o en un grafico del dashboard de Marketing. Esto lo
detecta antes, ejercitando cada llamada real que hace `utils/hubspot.py`.

    cd backend
    python scripts/check_hubspot_token.py                  # el token de .env
    python scripts/check_hubspot_token.py --token pat-xxx  # uno nuevo, sin tocar nada

NO escribe nada en HubSpot, ni siquiera al probar el permiso de escritura: el PATCH
va contra un deal INEXISTENTE, asi que HubSpot contesta 403 si falta el permiso y
404 si lo tiene. Las dos respuestas dejan el CRM igual que antes.

Sirve para cualquier tipo de credencial (app privada o clave de servicio): lo que
decide es si las llamadas reales andan, no como se llame la credencial.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from utils.hubspot import HubSpotClient  # noqa: E402


# Lo que el repo necesita de verdad. Los 4 de lectura son los que ya tiene el token
# de hoy; deals.write es el que suma el sync inverso (hub -> HubSpot).
SCOPES_REQUERIDOS = [
    ("crm.objects.contacts.read", "sync de cuentas, contactos de los deals"),
    ("crm.objects.companies.read", "sync de cuentas"),
    ("crm.objects.deals.read", "sync de opportunities, dashboard de Marketing"),
    ("crm.objects.owners.read", "resolver el owner de un deal por email"),
    ("crm.objects.deals.write", "sync INVERSO: mover el stage y escribir los montos"),
]


def _token_info(token):
    """Los scopes declarados. Devuelve None si la credencial no los expone.

    Este endpoint es de apps privadas; una clave de servicio puede no contestarlo.
    No es motivo para abortar: los scopes declarados son informativos, lo que manda
    son las llamadas reales de mas abajo.
    """
    try:
        resp = requests.post(
            "https://api.hubapi.com/oauth/v2/private-apps/get/access-token-info",
            json={"tokenKey": token}, timeout=20,
        )
        if not resp.ok:
            return None
        return resp.json()
    except Exception:  # noqa: BLE001
        return None


def _puede_escribir_deals(token):
    """(bool, detalle). Prueba el PATCH sin tocar ningun deal real.

    Se pega a un deal que NO existe: HubSpot resuelve el permiso ANTES de buscar el
    objeto, asi que 403 = sin permiso y 404 = con permiso. Verificado contra el
    token de solo lectura, que da 403 MISSING_SCOPES.
    """
    try:
        resp = requests.patch(
            "https://api.hubapi.com/crm/v3/objects/deals/1",
            headers={"Authorization": "Bearer %s" % token, "Content-Type": "application/json"},
            json={"properties": {"dealname": "permission probe"}}, timeout=20,
        )
    except Exception as exc:  # noqa: BLE001
        return False, "no se pudo probar: %s" % exc
    if resp.status_code == 404:
        return True, "404 sobre un deal inexistente = el permiso esta"
    if resp.status_code == 403:
        return False, "403 MISSING_SCOPES = falta crm.objects.deals.write"
    return False, "respuesta inesperada %s: %s" % (resp.status_code, resp.text[:120])


def _pruebas_de_lectura(client):
    """Una entrada por cada llamada distinta que hace utils/hubspot.py."""
    def owners():
        return "%s owners" % len(
            client._request("GET", "/crm/v3/owners/", params={"limit": 10, "archived": "false"}).get("results", [])
        )

    def props(obj):
        return lambda: "%s propiedades" % len(client.get_properties(obj))

    def pipelines():
        pipes = client.get_deal_pipelines()
        return "%s pipelines" % len(pipes)

    # Se pega al endpoint crudo y NO a client.search_*: esos helpers paginan hasta
    # el final (todos los contactos del CRM), que para un diagnostico es carisimo y
    # ademas gasta rate limit. Lo que se esta probando es el permiso, no la
    # paginacion, y con una pagina de 1 alcanza.
    def buscar(objeto, prop):
        def _fn():
            payload = client._request(
                "POST", "/crm/v3/objects/%s/search" % objeto,
                json={"limit": 1, "filterGroups": [{"filters": [
                    {"propertyName": prop, "operator": "HAS_PROPERTY"}]}]},
            )
            return "%s en total" % payload.get("total", "?")
        return _fn

    def un_deal():
        payload = client._request(
            "POST", "/crm/v3/objects/deals/search",
            json={"limit": 1, "filterGroups": [{"filters": [
                {"propertyName": "dealname", "operator": "HAS_PROPERTY"}]}]},
        )
        results = payload.get("results") or []
        if not results:
            return "sin deals para probar"
        d = client.get_deal_with_associations(str(results[0]["id"]))
        return "deal %s ok (con asociaciones)" % d.get("id")

    return [
        ("GET  /crm/v3/owners/", owners),
        ("GET  /crm/v3/properties/deals", props("deals")),
        ("GET  /crm/v3/properties/contacts", props("contacts")),
        ("GET  /crm/v3/properties/companies", props("companies")),
        ("GET  /crm/v3/pipelines/deals", pipelines),
        ("POST /crm/v3/objects/deals/search", buscar("deals", "dealname")),
        ("POST /crm/v3/objects/contacts/search", buscar("contacts", "createdate")),
        ("GET  /crm/v3/objects/deals/{id}", un_deal),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token", help="token a probar (por defecto el de backend/.env)")
    args = parser.parse_args()

    if not args.token:
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
        except ImportError:
            pass
    token = args.token or os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")
    if not token:
        print("Falta el token: pasalo con --token o poné HUBSPOT_PRIVATE_APP_TOKEN en backend/.env")
        return 2

    info = _token_info(token)
    if info:
        scopes = set(info.get("scopes") or [])
        print("Portal %s · app %s · %s scopes" % (info.get("hubId"), info.get("appId"), len(scopes)))
        print()
        print("SCOPES DECLARADOS")
        for scope, para_que in SCOPES_REQUERIDOS:
            print("  %s  %-32s  %s" % ("OK  " if scope in scopes else "FALTA", scope, para_que))
        extra = sorted(scopes - {s for s, _ in SCOPES_REQUERIDOS} - {"oauth"})
        if extra:
            print("  (de más, no molestan: %s)" % ", ".join(extra))
    else:
        print("La credencial no expone la lista de scopes (normal en claves de servicio).")
        print("Se decide sólo por las llamadas reales de abajo, que es lo que importa.")
    print()

    print("LLAMADAS REALES (solo lectura)")
    client = HubSpotClient(token=token)
    fallaron = []
    for nombre, fn in _pruebas_de_lectura(client):
        try:
            print("  OK    %-38s  %s" % (nombre, fn()))
        except Exception as exc:  # noqa: BLE001
            fallaron.append(nombre)
            print("  FALLA %-38s  %s" % (nombre, str(exc)[:110]))
    print()

    puede_escribir, detalle = _puede_escribir_deals(token)
    print("ESCRITURA (sin tocar ningún deal real)")
    print("  %s  PATCH /crm/v3/objects/deals/{id}   %s" % (
        "OK   " if puede_escribir else "FALLA", detalle))
    print()

    if fallaron or not puede_escribir:
        print("RESULTADO: NO sirve todavía.")
        if fallaron:
            print("  Llamadas de lectura que fallan: %s" % ", ".join(fallaron))
        if not puede_escribir:
            print("  Falta el permiso de escritura de deals: el sync inverso daría 403.")
        return 1
    print("RESULTADO: este token sirve para todo lo que el repo le pide.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
