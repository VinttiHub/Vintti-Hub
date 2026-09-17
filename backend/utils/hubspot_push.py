"""Sync inverso: que le escribe el hub a HubSpot al final del funnel.

Imagen especular de `hubspot_opportunities.py`. Todo lo de aca es logica pura (ni
HTTP ni SQL) para poder probarlo sin tocar nada ni gastar rate limit.

Por que existe: los 3 montos que HubSpot pide al cerrar un deal estan en **0 de 33**
deals de Closed Win (medido 2026-09-16). Nadie los carga de ese lado porque la plata
vive en el hub. Los dos campos de texto, en cambio, si los escribe una persona en
HubSpot (`role_hired_deal` 26/33, `mkt_collab` 25/33) — de ahi la politica de pisado
asimetrica de abajo.
"""

import hashlib

from utils.hubspot_opportunities import (
    OPPORTUNITY_FIELD_ALIASES,
    HUBSPOT_STAGE_RANK,
    pipeline_entry,
)


# Stage del hub -> stage key de HubSpot. Solo el final del funnel: el resto lo
# sigue decidiendo HubSpot y lo lee el sync entrante.
HUB_STAGE_TO_STAGE_KEY = {
    "signed": "signed",
    "close win": "closed_won",
}

# Campo logico -> de donde sale el valor en el dict de hire_values_for_opportunity.
# Son los mismos campos logicos que usa el sync entrante (CLOSED_WIN_FIELD_TO_COLUMN),
# para que los nombres internos de HubSpot los resuelva el mismo property_map.
PUSH_FIELDS = (
    # Los 4 de Closed Win
    "final_salary", "final_fee", "setup_fee", "role_hired",
    # Los 7 que HubSpot pide ademas al pasar a Signed. Salen de la solapa Hire y de
    # la ficha del candidato.
    "price_type", "computer", "candidate_start_date", "candidate_end_date",
    "candidate_address", "candidate_dni", "candidate_location",
    # Solo viajan al cerrar. Ver PUSH_SOLO_AL_CERRAR.
    "close_date", "mkt_collab",
)

# `closedate` es la unica propiedad con doble sentido segun el stage: en un deal
# ABIERTO es la fecha de cierre ESPERADA, que maneja ventas a mano (CM Products
# tenia 2026-09-08 puesta desde la UI). Pisarla al empujar a Signed le borraria el
# forecast al AE. Recien cuando el deal cierra la fecha real del hub es la que vale.
#
# Ademas HubSpot la estampa SOLA con la fecha de HOY al entrar a una etapa cerrada,
# asi que si el push no la manda, el deal queda cerrado con la fecha del dia en que
# corrio el sync en vez de cuando se cerro de verdad.
# `mkt_collab` tambien: HubSpot lo exige recien en Closed Win, y antes de eso la
# recruiter no lo cargo todavia.
PUSH_SOLO_AL_CERRAR = {"close_date", "mkt_collab"}

# Todo lo que el hub pisa. Medido contra los 33 deals de Closed Win: estos 10
# campos estan cargados en **0** de 33, o sea que nadie los completa del lado de
# HubSpot. El unico que si escribe una persona es role_hired_deal (26/33), y por eso
# es el unico que queda afuera: sale de `opp_position_name` y puede estar redactado
# distinto de lo que tipeo el AE.
PUSH_OVERWRITE = set(PUSH_FIELDS) - {"role_hired"}

# Selects de HubSpot: mandar un valor fuera de la lista lo rechaza o lo deja
# invisible en la UI. La traduccion vive en hubspot_push_values.py.
PUSH_SELECTS = {"price_type", "computer", "candidate_location"}

# Ya no queda nada en esta lista: `mkt_collab` salio de aca el 2026-09-17, cuando el
# hub gano su propia columna y el popup de Close Win empezo a pedirlo.
PUSH_NEVER = set()

# Sólo estos 3 se serializan como número; el resto va como texto.
_MONEY = {"final_salary", "final_fee", "setup_fee"}

# `closedate` es tipo **datetime** en HubSpot, no `date` como candidates_start_date.
# Mandarle "2026-09-10" lo guarda como 2026-09-10T00:00:00Z, y la UI lo renderiza en
# la zona del portal (US/Eastern, UTC-4): medianoche UTC se ve como el DIA ANTERIOR
# a las 20:00. Por eso se manda el mediodia UTC, que cae en el mismo dia calendario
# en cualquier huso entre UTC-11 y UTC+11.
_DATETIME_DATES = {"close_date"}


def values_fingerprint(hire_values):
    """Huella de lo que el hub quiere que HubSpot tenga. Se calcula SOLO con SQL.

    Sirve para que la pasada del cron no le pegue a HubSpot al pedo: el conjunto de
    opps en Signed/Close Win crece para siempre (una opp cerrada se queda cerrada),
    asi que re-leer cada deal cada 30 minutos seria cada vez mas caro y casi
    siempre para no cambiar nada. Si la huella coincide con la guardada, se saltea
    sin una sola llamada HTTP.

    Incluye el stage porque mover la opp de Signed a Close Win no cambia ningun
    monto pero si tiene que empujar.
    """
    valores = hire_values.get("valores") or {}
    partes = ["stage=%s" % str(hire_values.get("opp_stage") or "").strip().lower()]
    partes.extend("%s=%s" % (k, valores[k]) for k in sorted(valores))
    return hashlib.sha1("|".join(partes).encode("utf-8")).hexdigest()


def hub_stage_to_stage_key(opp_stage):
    return HUB_STAGE_TO_STAGE_KEY.get(str(opp_stage or "").strip().lower())


def decide_push_stage(current_stage_key, target_stage_key):
    """(mover_a_o_None, motivo). Espejo de decide_stage_transition(), hacia afuera.

    Las dos negativas importantes:

    - `current_stage_key` en None significa que el deal esta en un stage que NO
      mapeamos: Closed Lost o DQL. Mover un deal desde ahi lo estaria RESUCITANDO
      en el pipeline de ventas. Igual que el sync entrante con
      `unknown_hub_stage`: si no lo entendemos, no lo tocamos.
    - Nunca retrocede. Si HubSpot ya esta en Closed Win y el hub recien pasa a
      Signed, el stage no se toca (los montos si se mandan igual: son
      independientes del movimiento).
    """
    if not target_stage_key:
        return None, "el stage del hub no mapea a ninguno de HubSpot"
    if not current_stage_key:
        return None, "el deal esta en un stage que no seguimos (Closed Lost / DQL): no se toca"
    if current_stage_key == target_stage_key:
        return None, "HubSpot ya esta en ese stage"
    actual = HUBSPOT_STAGE_RANK.get(current_stage_key)
    destino = HUBSPOT_STAGE_RANK.get(target_stage_key)
    if actual is None:
        return None, "stage actual de HubSpot sin rank conocido"
    if destino is None:
        return None, "stage destino sin rank conocido"
    if destino <= actual:
        return None, "HubSpot ya esta igual o mas adelante"
    return target_stage_key, "avanza"


def _as_hubspot_number(valor):
    """HubSpot acepta el numero como string. Las 3 columnas del hub son integer."""
    try:
        return str(int(valor))
    except (TypeError, ValueError):
        return None


def build_push_payload(hire_values, deal_props, property_map, pipeline_map):
    """Que PATCH le mandariamos a este deal. Puro: no llama a HubSpot ni a la base.

    Devuelve properties (lo que se manda), omitidos (por que cada campo NO se
    manda) y el detalle del stage. `omitidos` es la mitad util del reporte: sin eso
    un campo ausente no se distingue de un campo que decidimos no pisar.
    """
    props = {}
    omitidos = {}
    deal_props = deal_props or {}

    entry = pipeline_entry(pipeline_map, hire_values.get("pipeline_id"))
    target_key = hub_stage_to_stage_key(hire_values.get("opp_stage"))
    va_a_cerrar = target_key == "closed_won"

    for campo in PUSH_FIELDS:
        if campo in PUSH_SOLO_AL_CERRAR and not va_a_cerrar:
            omitidos[campo] = (
                "solo se manda al pasar a Closed Win: en un deal abierto `closedate` es "
                "el forecast que maneja ventas, y el MKT Collab todavia no se cargo"
            )
            continue
        prop = property_map.get(campo)
        if not prop:
            omitidos[campo] = "HubSpot no tiene esa propiedad resuelta"
            continue
        valor = (hire_values.get("valores") or {}).get(campo)
        if valor is None:
            omitidos[campo] = (hire_values.get("motivos") or {}).get(campo, "el hub no tiene el dato")
            continue
        actual = deal_props.get(prop)
        tiene_algo = actual not in (None, "")
        if tiene_algo and campo not in PUSH_OVERWRITE:
            omitidos[campo] = "HubSpot ya tiene %r cargado y este campo no se pisa" % (actual,)
            continue
        if campo in _MONEY:
            serializado = _as_hubspot_number(valor)
            if serializado is None:
                omitidos[campo] = "el valor del hub (%r) no es un numero" % (valor,)
                continue
        elif campo in _DATETIME_DATES:
            serializado = "%sT12:00:00Z" % str(valor).strip()[:10]
        else:
            serializado = str(valor).strip()
            if not serializado:
                omitidos[campo] = "el valor del hub esta vacio"
                continue
        # Comparacion EXACTA tambien para el datetime: HubSpot devuelve el instante
        # tal cual se lo mandamos, asi que un 00:00:00Z guardado (que se ve un dia
        # antes) se detecta como distinto y se corrige solo. Comparar solo el dia
        # lo daria por bueno y dejaria la fecha mal para siempre.
        if str(actual or "") == serializado:
            omitidos[campo] = "HubSpot ya tiene exactamente ese valor"
            continue
        props[prop] = serializado

    for campo in PUSH_NEVER:
        omitidos[campo] = "el hub no tiene ese dato: lo carga marketing en HubSpot"

    # --- el stage ---------------------------------------------------------
    stage_id, stage_motivo = None, "sin pipeline resuelto"
    current_key = None
    if entry:
        current_key = entry["stage_key_by_id"].get(str(hire_values.get("dealstage_id") or ""))
        mover_a, stage_motivo = decide_push_stage(current_key, target_key)
        if mover_a:
            stage_id = entry["stage_id_by_key"].get(mover_a)
            if not stage_id:
                stage_motivo = "el stage '%s' no existe en el pipeline %s" % (mover_a, entry["label"])
    if stage_id:
        props["dealstage"] = stage_id

    return {
        "properties": props,
        "omitidos": omitidos,
        "stage": {
            "pipeline": entry["label"] if entry else None,
            "desde": current_key,
            "hacia": target_key,
            "stage_id": stage_id,
            "motivo": stage_motivo,
        },
    }


def properties_to_fetch(property_map):
    """Las propiedades del deal que hay que LEER antes de escribir.

    Hacen falta para dos decisiones: no pisar el texto que ya cargo una persona, y
    no mandar un PATCH con el valor que el deal ya tiene.
    """
    nombres = ["dealstage", "pipeline", "dealname"]
    for campo in PUSH_FIELDS:
        prop = property_map.get(campo)
        if prop and prop not in nombres:
            nombres.append(prop)
    # Se lee tambien el que nunca escribimos, para poder mostrarlo en el preview.
    for campo in PUSH_NEVER:
        prop = property_map.get(campo)
        if prop and prop not in nombres:
            nombres.append(prop)
    return nombres


# Sanity check de arranque: todo campo que empujamos tiene que tener alias en
# OPPORTUNITY_FIELD_ALIASES, o resolve_opportunity_property_map() no le va a
# encontrar el nombre interno y el push lo omitiria en silencio.
_desconocidos = set(PUSH_FIELDS) | PUSH_NEVER
_desconocidos -= set(OPPORTUNITY_FIELD_ALIASES)
if _desconocidos:  # pragma: no cover
    raise RuntimeError(
        "hubspot_push: %s no tienen alias en OPPORTUNITY_FIELD_ALIASES" % sorted(_desconocidos)
    )
