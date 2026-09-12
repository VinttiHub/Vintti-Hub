"""Logica pura del sync HubSpot -> opportunities del hub.

Sin psycopg2 y sin flask a proposito: aca vive lo unico que se puede leer y
probar de un vistazo (los alias de pipelines/stages y el ranking de stages), que
es justo lo que hay que tocar cuando en HubSpot renombran una etapa. La
orquestacion con la base vive en routes/hubspot_routes.py, que es donde estan
los helpers de cuenta (_find_existing_account y companiia).

Spec: doc "AUTOMATIZACIONES HUBSPOT - HUB" de la owner.
  Intro Call -> Deep Dive  ==> crear la opportunity
  Deep Dive  -> NDA Sent   ==> stage 'NDA Sent'
  NDA Sent   -> NDA Signed ==> stage 'Sourcing'
  Closed Won               ==> solo Set Up Fee y Final Fee (NO mueve el stage)
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from difflib import SequenceMatcher
from decimal import Decimal, InvalidOperation


# ---------------------------------------------------------------- normalizacion

def fold(value):
    """Baja a minusculas, saca acentos y separadores, colapsa espacios.

    _normalize_hubspot_label() de hubspot_routes.py hace casi lo mismo pero NO
    pliega acentos, y el pipeline se llama "Proceso de contratacion" CON tilde:
    sin este plegado ningun alias sin tilde matchearia nunca.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("_", " ")
    for char in ("/", "-", "–", "—", "(", ")", ":", "?", ".", ",", "#", "&"):
        text = text.replace(char, " ")
    return " ".join(text.split())


def tokens(value):
    return set(fold(value).split())


def normalize_position_name(value):
    """Llave de adopcion: 'Senior  Accountant ' == 'senior accountant'.

    Tiene que dar EXACTAMENTE lo mismo que el regexp_replace del SQL de adopcion
    (idx_opportunity_account_position_norm), o el indice no sirve y la busqueda
    encuentra cosas distintas segun quien normalice.
    """
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def position_similarity(a, b):
    """0..1, SOLO para ordenar las candidatas que ve una persona.

    No hay umbral y no decide nada: el sync nunca adopta por parecido. En la
    practica los puestos se escriben distinto en cada sistema ('Tutor' en HubSpot
    vs 'Computer Science Teacher' en el hub), y ahi ningun puntaje alcanza — por
    eso la vinculacion la confirma una persona y esto solo pone arriba lo probable.

    El criterio de subconjunto es el mismo que companies_match() de
    reference_matching.py: 'Graphic Designer' dentro de 'Part Time Graphic
    Designer' es la misma busqueda, aunque el ratio de texto sea bajo.
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    if normalize_position_name(a) == normalize_position_name(b):
        return 1.0
    if ta <= tb or tb <= ta:
        # Cuanto menos sobra, mas se parece: 0.90 para 'Accountant' dentro de
        # 'Accountant', 0.75 para uno metido en un titulo de cuatro palabras.
        sobran = abs(len(ta) - len(tb))
        return max(0.70, 0.95 - 0.05 * sobran)
    compartidos = len(ta & tb) / len(ta | tb)
    return max(compartidos, SequenceMatcher(None, fold(a), fold(b)).ratio())


def parse_money(value):
    """'$1,200.50' / '1.200,50' / '' / None -> Decimal | None. Nunca levanta."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    raw = str(value).strip()
    if not raw:
        return None
    raw = re.sub(r"[^\d,.\-]", "", raw)
    if not raw or raw in ("-", ".", ","):
        return None
    # Formato europeo: el ultimo separador es la coma decimal (1.200,50).
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        decimals = len(raw.split(",")[-1])
        raw = raw.replace(",", "." if decimals != 3 else "")
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


# ------------------------------------------------------------------ vocabulario

# Alias DELIBERADAMENTE especificos. El portal tiene ademas un "Sales Pipeline"
# viejo (id 26687510, etapas "Recruiting Deep Dive" / "NDA (Job Description Form)")
# y un "Account Manager Pipeline" que NO se sincronizan: un alias generico como
# "Sales Pipeline" los agarraba como si fueran el de Mariano.
PIPELINE_ALIASES = {
    "hiring": [
        "Proceso de contratacion",
        "Proceso de contratación",
        "Proceso De Contratación",
    ],
    "vintti_ai": [
        "Vintti AI Pipeline",
        "Pipeline Vintti AI",
    ],
}

# El sales lead lo decide el PIPELINE, no el owner del deal (regla de la owner).
PIPELINE_SALES_LEAD = {
    "hiring": "mariano@vintti.com",
    "vintti_ai": "mia@vintti.com",
}

STAGE_ALIASES = {
    "intro_call": ["Intro Call", "Intro", "Llamada inicial", "Primera llamada"],
    "deep_dive": ["Deep Dive", "Deepdive"],
    "nda_sent": ["NDA Sent", "NDA enviado", "Envio NDA", "NDA Enviada"],
    "nda_signed": ["NDA Signed", "NDA firmado", "NDA Firmada", "Firma NDA"],
    "closed_won": ["Closed Won", "Cerrado ganado", "Ganado", "Won", "Close Win"],
}

# Orden de resolucion: los mas especificos primero, para que "NDA Signed" no se
# lo coma el alias "NDA Sent" via matching por tokens.
STAGE_RESOLUTION_ORDER = ("nda_signed", "nda_sent", "deep_dive", "intro_call", "closed_won")

OPPORTUNITY_FIELD_ALIASES = {
    "role_to_hire": [
        "role_to_hire", "Role to hire", "Role to Hire", "Role To Hire",
        "Role To Hire (Deal)", "Rol a contratar", "Puesto a contratar",
    ],
    # Los 5 campos que HubSpot pide al llegar a Closed Win. Todos van a columnas
    # espejo de `opportunity`: los montos reales del negocio viven en
    # hire_opportunity y los aplica una persona desde la solapa Hire.
    "setup_fee": [
        "set_up_fee", "setup_fee", "Set Up Fee", "Setup Fee", "Set-up Fee",
    ],
    "final_fee": [
        "final_fee", "Final Fee", "Fee final", "Fee Final",
    ],
    "final_salary": [
        "candidates_final_salary", "Candidate's Final Salary",
        "Candidates Final Salary", "Final Salary",
    ],
    "role_hired": [
        "role_hired_deal", "Role Hired", "Role hired", "Rol contratado",
    ],
    "mkt_collab": [
        "mkt_collab", "MKT Collab", "Marketing Collab",
    ],
    # Los que HubSpot pide al pasar a NDA Sent. Ojo: "expected_set_up_fee" es OTRA
    # propiedad que "set_up_fee" (esperado vs final), no se pisan entre si.
    "min_budget": ["min_client_budget", "Min Client Budget"],
    "max_budget": ["max_client_budget", "Max Client Budget"],
    "min_salary": ["min_candidate_salary", "Min Candidate Salary"],
    "max_salary": ["max_candidate_salary", "Max Candidate Salary"],
    "years_experience": [
        "candidates_years_of_experience", "Candidate's Years of Experience",
        "Years of Experience",
    ],
    "expected_fee": ["expected_fee", "Expected Fee"],
    "expected_setup_fee": ["expected_set_up_fee", "Expected Set Up Fee"],
}

# Campos de negocio que HubSpot carga en NDA Sent -> columna del hub.
# Ninguna de estas columnas la lee un dataset del dashboard, salvo expected_fee
# (Active Pipeline / Pipeline Outbound AE). `fee` es la que el hub muestra como
# "Set Up Fee"; el fee del MRR es otro, sale de hire_opportunity.
BUSINESS_FIELD_TO_COLUMN = {
    "min_budget": "min_budget",
    "max_budget": "max_budget",
    "min_salary": "min_salary",
    "max_salary": "max_salary",
    "years_experience": "years_experience",
    "expected_fee": "expected_fee",
    "expected_setup_fee": "fee",
}

OPPORTUNITY_FIELD_ENV_OVERRIDES = {
    "role_to_hire": "HUBSPOT_OPP_ROLE_PROPERTY",
    "setup_fee": "HUBSPOT_OPP_SETUP_FEE_PROPERTY",
    "final_fee": "HUBSPOT_OPP_FINAL_FEE_PROPERTY",
}


# ------------------------------------------------------- maquina de stages (hub)

# Rank del stage LOCAL (opp_stage). Sirve para una sola cosa: no dejar que el
# sync retroceda una opp que en el hub ya avanzo mas que HubSpot.
HUB_STAGE_RANK = {
    "deep dive": 10,
    "nda sent": 20,
    "sourcing": 30,
    "interviewing": 40,
    "negotiating": 50,
    "signed": 60,
    "close win": 70,
}

# Si alguien mato la opp en el hub, el cron no la resucita: reabrirla revertiria
# stage_before_closed_lost y sacaria a la cuenta de 'Inactive Client'.
HUB_TERMINAL_STAGES = {"closed lost", "stop"}

STAGE_KEY_TO_HUB_STAGE = {
    "intro_call": None,   # todavia no es opportunity
    "deep_dive": "Deep Dive",
    "nda_sent": "NDA Sent",
    "nda_signed": "Sourcing",
    # Closed Won NO mueve el stage: en el hub 'Close Win' dispara creditos,
    # marca el hire activo y entra a revenue. Solo trae los fees.
    "closed_won": None,
}

# Stages de HubSpot a partir de los cuales la opportunity debe existir en el hub.
STAGE_KEYS_THAT_CREATE = ("deep_dive", "nda_sent", "nda_signed", "closed_won")

# Los unicos stage keys cuya fecha de entrada tiene columna en `opportunity`.
STAGE_KEYS_WITH_HUB_DATE = ("deep_dive", "nda_sent", "nda_signed")

# Que columna del hub guarda la fecha de entrada de cada stage.
STAGE_KEY_TO_DATE_COLUMN = {
    "deep_dive": "deep_dive_date",
    "nda_sent": "nda_sent_date",
    "nda_signed": "nda_signature_or_start_date",
}


def hub_stage_rank(stage):
    return HUB_STAGE_RANK.get(str(stage or "").strip().lower())


def decide_stage_transition(current_hub_stage, target_hub_stage):
    """(nuevo_stage_o_None, reason)."""
    if not target_hub_stage:
        return None, "no_target_stage"
    current = str(current_hub_stage or "").strip().lower()
    if current in HUB_TERMINAL_STAGES:
        return None, "hub_stage_is_terminal"
    if not current:
        # opp sin stage cargado: escribirlo es una mejora, no un retroceso.
        return target_hub_stage, "advanced"
    current_rank = hub_stage_rank(current)
    if current_rank is None:
        # opp_stage es TEXT libre; si dice algo que no conocemos no adivinamos.
        return None, "unknown_hub_stage"
    target_rank = hub_stage_rank(target_hub_stage)
    if target_rank is None:
        return None, "unknown_target_stage"
    if target_rank <= current_rank:
        return None, "hub_ahead_or_equal"
    return target_hub_stage, "advanced"


def initial_stage_for_new_opportunity(stage_key, stage_dates):
    """Stage con el que se CREA una opp que el hub nunca vio.

    Para closed_won no hay target (no movemos a Close Win), asi que se deduce el
    ultimo hito conocido por fecha. Nunca devuelve 'Close Win'.
    """
    direct = STAGE_KEY_TO_HUB_STAGE.get(stage_key)
    if direct:
        return direct
    if stage_key != "closed_won":
        return None
    if stage_dates.get("nda_signature_or_start_date"):
        return "Sourcing"
    if stage_dates.get("nda_sent_date"):
        return "NDA Sent"
    return "Deep Dive"


# ------------------------------------------ resolucion de pipelines y stages

_PIPELINE_MAP_CACHE = {"data": None, "ts": 0.0}
_PIPELINE_MAP_TTL = 600

_OPP_PROPERTY_MAP_CACHE = {"data": None, "ts": 0.0}
_OPP_PROPERTY_MAP_TTL = 600


def _parse_pipeline_id_overrides():
    """'hiring:123,vintti_ai:456' -> {'123': 'hiring', '456': 'vintti_ai'}."""
    raw = (os.environ.get("HUBSPOT_OPP_PIPELINE_IDS") or "").strip()
    mapping = {}
    if not raw:
        return mapping
    for chunk in raw.split(","):
        if ":" not in chunk:
            continue
        key, pipeline_id = chunk.split(":", 1)
        key = key.strip()
        pipeline_id = pipeline_id.strip()
        if key in PIPELINE_ALIASES and pipeline_id:
            mapping[pipeline_id] = key
    return mapping


def _parse_stage_id_overrides():
    """JSON {'hiring': {'deep_dive': '123', ...}, ...}."""
    raw = (os.environ.get("HUBSPOT_OPP_STAGE_IDS") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    clean = {}
    for pipeline_key, stages in parsed.items():
        if pipeline_key not in PIPELINE_ALIASES or not isinstance(stages, dict):
            continue
        clean[pipeline_key] = {
            str(k): str(v).strip()
            for k, v in stages.items()
            if k in STAGE_ALIASES and str(v or "").strip()
        }
    return clean


def _match_pipeline_key(label, with_kind=False):
    """(key, 'exact'|'tokens') o None. El tipo de match importa: si dos pipelines
    reclaman la misma key, gana el exacto en vez de "el primero que vino"."""
    label_tokens = tokens(label)
    folded = fold(label)
    for key, aliases in PIPELINE_ALIASES.items():
        for alias in aliases:
            if fold(alias) == folded:
                return (key, "exact") if with_kind else key
    best = None
    for key, aliases in PIPELINE_ALIASES.items():
        for alias in aliases:
            alias_tokens = tokens(alias)
            if alias_tokens and alias_tokens <= label_tokens:
                score = (len(label_tokens) - len(alias_tokens), -len(alias_tokens))
                if best is None or score < best[0]:
                    best = (score, key)
    if not best:
        return None
    return (best[1], "tokens") if with_kind else best[1]


def _match_stages(stages):
    """[{id,label,metadata}] -> ({stage_key: stage_id}, [keys sin resolver])."""
    by_key = {}
    claimed = set()

    # 1) exacta
    for stage_key in STAGE_RESOLUTION_ORDER:
        aliases = {fold(a) for a in STAGE_ALIASES[stage_key]}
        for stage in stages:
            stage_id = str(stage.get("id") or "")
            if not stage_id or stage_id in claimed:
                continue
            if fold(stage.get("label")) in aliases:
                by_key[stage_key] = stage_id
                claimed.add(stage_id)
                break

    # 2) por tokens: gana el label con menos palabras de sobra ("3. Deep Dive",
    #    "NDA Signed [ok]"). Nunca se pisa un stage ya reclamado por la exacta.
    for stage_key in STAGE_RESOLUTION_ORDER:
        if stage_key in by_key:
            continue
        alias_token_sets = [tokens(a) for a in STAGE_ALIASES[stage_key]]
        best = None
        for stage in stages:
            stage_id = str(stage.get("id") or "")
            if not stage_id or stage_id in claimed:
                continue
            label_tokens = tokens(stage.get("label"))
            for alias_tokens in alias_token_sets:
                if alias_tokens and alias_tokens <= label_tokens:
                    score = (len(label_tokens) - len(alias_tokens), -len(alias_tokens))
                    if best is None or score < best[0]:
                        best = (score, stage_id)
                    break
        if best:
            by_key[stage_key] = best[1]
            claimed.add(best[1])

    # 3) closed_won tiene marca propia en HubSpot; es el unico que se puede
    #    deducir sin mirar el label.
    if "closed_won" not in by_key:
        for stage in stages:
            stage_id = str(stage.get("id") or "")
            metadata = stage.get("metadata") or {}
            is_closed = str(metadata.get("isClosed", "")).strip().lower() == "true"
            probability = str(metadata.get("probability", "")).strip()
            if stage_id and stage_id not in claimed and is_closed and probability in ("1", "1.0"):
                by_key["closed_won"] = stage_id
                claimed.add(stage_id)
                break

    unresolved = [k for k in STAGE_RESOLUTION_ORDER if k not in by_key]
    return by_key, unresolved


def stage_date_property(stage_id):
    return "hs_v2_date_entered_%s" % stage_id


def resolve_pipeline_stage_map(client, force_refresh=False):
    """Mapa de los 2 pipelines de Vintti con sus stage ids resueltos por label.

    Se resuelve SIEMPRE contra la API y recien despues se aplican los overrides
    de env: al reves, un typo en la env dejaria al sync ciego.
    """
    now = time.time()
    if (
        not force_refresh
        and _PIPELINE_MAP_CACHE["data"] is not None
        and now - _PIPELINE_MAP_CACHE["ts"] < _PIPELINE_MAP_TTL
    ):
        return _PIPELINE_MAP_CACHE["data"]

    pipelines = client.get_deal_pipelines()
    pipeline_id_overrides = _parse_pipeline_id_overrides()
    stage_id_overrides = _parse_stage_id_overrides()

    by_pipeline_id = {}
    pipeline_id_by_key = {}
    match_kind_by_key = {}
    warnings = []
    date_properties = []

    for pipeline in pipelines:
        pipeline_id = str(pipeline.get("id") or "")
        if not pipeline_id:
            continue
        label = pipeline.get("label") or ""
        if pipeline_id in pipeline_id_overrides:
            key, match_kind = pipeline_id_overrides[pipeline_id], "env"
        else:
            matched = _match_pipeline_key(label, with_kind=True)
            key, match_kind = matched if matched else (None, None)
        if not key:
            continue
        if key in pipeline_id_by_key:
            previous = pipeline_id_by_key[key]
            previous_kind = match_kind_by_key.get(key)
            rank = {"env": 0, "exact": 1, "tokens": 2}
            if rank[match_kind] >= rank.get(previous_kind, 2):
                warnings.append(
                    "el pipeline '%s' (%s) tambien matchea '%s'; se ignora y se usa %s"
                    % (label, pipeline_id, key, previous)
                )
                continue
            warnings.append(
                "el pipeline %s matcheaba '%s' por %s; lo reemplaza '%s' (%s), que es match %s"
                % (previous, key, previous_kind, label, pipeline_id, match_kind)
            )
            by_pipeline_id.pop(previous, None)

        stages = pipeline.get("stages") or []
        stage_id_by_key, unresolved = _match_stages(stages)
        for stage_key, stage_id in (stage_id_overrides.get(key) or {}).items():
            stage_id_by_key[stage_key] = stage_id
            if stage_key in unresolved:
                unresolved.remove(stage_key)

        date_property_by_key = {
            stage_key: stage_date_property(stage_id)
            for stage_key, stage_id in stage_id_by_key.items()
        }
        # Las 5, no solo las 3 que tienen columna: detect_hubspot_regression() compara
        # contra intro_call y closed_won para saber si el deal retrocedio.
        date_properties.extend(date_property_by_key.values())

        pipeline_id_by_key[key] = pipeline_id
        match_kind_by_key[key] = match_kind
        by_pipeline_id[pipeline_id] = {
            "key": key,
            "id": pipeline_id,
            "label": label,
            "sales_lead": PIPELINE_SALES_LEAD.get(key),
            "stage_id_by_key": stage_id_by_key,
            "stage_key_by_id": {v: k for k, v in stage_id_by_key.items()},
            "date_property_by_key": date_property_by_key,
            "stage_labels": {str(s.get("id")): s.get("label") for s in stages},
            "unresolved": unresolved,
        }

    for pipeline_id, key in pipeline_id_overrides.items():
        if pipeline_id not in by_pipeline_id:
            warnings.append(
                "HUBSPOT_OPP_PIPELINE_IDS apunta a %s (%s) pero la API no lo devolvio"
                % (pipeline_id, key)
            )

    for key in PIPELINE_ALIASES:
        if key not in pipeline_id_by_key:
            warnings.append("no se pudo resolver el pipeline '%s' en HubSpot" % key)

    resolved = {
        "by_pipeline_id": by_pipeline_id,
        "pipeline_id_by_key": pipeline_id_by_key,
        "date_properties": sorted(set(date_properties)),
        "warnings": warnings,
    }
    _PIPELINE_MAP_CACHE["data"] = resolved
    _PIPELINE_MAP_CACHE["ts"] = now
    return resolved


def pipeline_entry(pipeline_map, pipeline_id):
    return (pipeline_map.get("by_pipeline_id") or {}).get(str(pipeline_id or ""))


def deal_stage_key(pipeline_map, pipeline_id, dealstage_id):
    entry = pipeline_entry(pipeline_map, pipeline_id)
    if not entry:
        return None
    return entry["stage_key_by_id"].get(str(dealstage_id or ""))


def stage_dates_from_deal(pipeline_map, pipeline_id, deal_props, parse_date):
    """Fechas de entrada a stage del deal, ya mapeadas a columnas del hub.

    Siempre del pipeline del deal: las constantes viejas
    HUBSPOT_DEEP_DIVE_DATE_PROPERTY / HUBSPOT_NDA_SENT_DATE_PROPERTY son de UN
    pipeline y para el de Vintti AI leen una propiedad que no existe.
    """
    result = {
        "deep_dive_date": None,
        "nda_sent_date": None,
        "nda_signature_or_start_date": None,
    }
    entry = pipeline_entry(pipeline_map, pipeline_id)
    if not entry:
        return result
    props = deal_props or {}
    mapping = (
        ("deep_dive", "deep_dive_date"),
        ("nda_sent", "nda_sent_date"),
        ("nda_signed", "nda_signature_or_start_date"),
    )
    for stage_key, column in mapping:
        prop = entry["date_property_by_key"].get(stage_key)
        if not prop:
            continue
        result[column] = parse_date(props.get(prop))
    return result


# Orden de las etapas DE HUBSPOT. Distinto de HUB_STAGE_RANK, que ordena las del
# hub (que tiene Interviewing y Negotiating, etapas que HubSpot no conoce).
HUBSPOT_STAGE_RANK = {
    "intro_call": 0,
    "deep_dive": 10,
    "nda_sent": 20,
    "nda_signed": 30,
    "closed_won": 40,
}


def detect_hubspot_regression(pipeline_map, pipeline_id, deal_props, stage_key, parse_date):
    """¿HubSpot movio el deal HACIA ATRAS? -> dict con el detalle, o None.

    HubSpot deja `hs_v2_date_entered_<stage>` con la ULTIMA vez que entro a cada
    etapa y no la borra al salir (verificado 2026-09-11). Asi que si hay fecha de
    entrada a una etapa POSTERIOR a donde esta parado ahora, es que retrocedio.

    No se actua sobre esto a proposito: HubSpot no distingue un error de carga
    (movieron el deal de mas y lo vuelven atras) de un retroceso real (la reunion
    se hizo y el cliente se enfrio). En el primero querrias borrar la fecha; en el
    segundo, borrarla perderia un evento que si ocurrio. Se reporta y decide una
    persona. Ver CLAUDE.md.
    """
    entry = pipeline_entry(pipeline_map, pipeline_id)
    if not entry or stage_key not in HUBSPOT_STAGE_RANK:
        return None
    actual = HUBSPOT_STAGE_RANK[stage_key]
    alcanzado, fecha = None, None
    for otra_key, prop in entry["date_property_by_key"].items():
        rank = HUBSPOT_STAGE_RANK.get(otra_key)
        if rank is None or rank <= actual:
            continue
        entrada = parse_date((deal_props or {}).get(prop))
        if entrada and (alcanzado is None or rank > HUBSPOT_STAGE_RANK[alcanzado]):
            alcanzado, fecha = otra_key, entrada
    if not alcanzado:
        return None
    return {
        "ahora_en": stage_key,
        "habia_llegado_a": alcanzado,
        "fecha_de_esa_entrada": fecha.isoformat(),
    }


def fill_missing_entry_date(stage_dates, stage_key, today):
    """Fecha de entrada al stage donde el deal esta AHORA, cuando HubSpot no la tiene.

    HubSpot crea una propiedad hs_v2_date_entered_<stageId> por etapa, pero para
    las dos etapas "NDA Sent" (ids 1429477933 y 1429487919, agregadas despues que
    el resto) esa propiedad NO existe: el deal entra al stage y no hay fecha que
    leer. Sin esto la columna quedaria NULL y las cards que anclan ahi no verian
    la opp — peor que el comportamiento manual del hub, que estampa CURRENT_DATE
    cuando alguien mueve el stage a mano.

    Solo aplica al stage DONDE ESTA el deal, nunca a etapas por las que pudo haber
    pasado: si salto de Deep Dive a NDA Signed no se inventa un nda_sent_date.
    Tampoco pisa un valor que HubSpot si tenga.

    Devuelve el nombre de la columna completada, o None.
    """
    column = STAGE_KEY_TO_DATE_COLUMN.get(stage_key)
    if not column or stage_dates.get(column):
        return None
    stage_dates[column] = today
    return column


def resolve_opportunity_property_map(client, force_refresh=False):
    """Nombres internos de Role to hire / Set Up Fee / Final Fee en deals."""
    now = time.time()
    if (
        not force_refresh
        and _OPP_PROPERTY_MAP_CACHE["data"] is not None
        and now - _OPP_PROPERTY_MAP_CACHE["ts"] < _OPP_PROPERTY_MAP_TTL
    ):
        return _OPP_PROPERTY_MAP_CACHE["data"]

    properties = client.get_properties("deals")
    by_name = {}
    by_label = {}
    for prop in properties:
        name = str(prop.get("name") or "")
        if not name:
            continue
        by_name[fold(name)] = name
        label = prop.get("label")
        if label:
            by_label.setdefault(fold(label), name)

    resolved = {}
    unresolved = []
    for field, aliases in OPPORTUNITY_FIELD_ALIASES.items():
        env_var = OPPORTUNITY_FIELD_ENV_OVERRIDES.get(field)
        override = (os.environ.get(env_var) or "").strip() if env_var else ""
        if override:
            resolved[field] = override
            continue
        found = None
        for alias in aliases:
            folded = fold(alias)
            found = by_name.get(folded) or by_label.get(folded)
            if found:
                break
        if found:
            resolved[field] = found
        else:
            unresolved.append(field)
    resolved["_unresolved"] = unresolved

    _OPP_PROPERTY_MAP_CACHE["data"] = resolved
    _OPP_PROPERTY_MAP_CACHE["ts"] = now
    return resolved


def parse_int(value):
    """A entero, que es el tipo de las 7 columnas destino. Nunca levanta.

    HubSpot manda numeros como texto ("2500", "2500.00"), asi que se pasa por
    parse_money primero y recien despues se trunca.
    """
    amount = parse_money(value)
    if amount is None:
        return None
    try:
        return int(amount)
    except (ValueError, OverflowError):
        return None


def normalize_multi_select(value):
    """'a;b' -> 'a; b'. HubSpot manda los checkbox multiples separados por ';'.

    Guardarlo crudo hace que la pantalla muestre "Case Study;Webinar" pegado, y
    que cualquier comparacion futura dependa del orden en que HubSpot los serializa.
    """
    if value in (None, ""):
        return None
    partes = [p.strip() for p in str(value).split(";")]
    partes = [p for p in partes if p]
    return "; ".join(partes) if partes else None


# Los 5 campos de Closed Win -> columna espejo de `opportunity`.
CLOSED_WIN_FIELD_TO_COLUMN = {
    "setup_fee": "hubspot_setup_fee",
    "final_fee": "hubspot_final_fee",
    "final_salary": "hubspot_final_salary",
    "role_hired": "hubspot_role_hired",
    "mkt_collab": "hubspot_mkt_collab",
}

_CLOSED_WIN_MONEY = ("setup_fee", "final_fee", "final_salary")


def closed_win_fields_from_deal(deal_props, property_map):
    """{columna espejo: valor} con lo que HubSpot tenga al cerrar el deal."""
    values = {}
    props = deal_props or {}
    for field, column in CLOSED_WIN_FIELD_TO_COLUMN.items():
        prop = property_map.get(field)
        if not prop:
            continue
        raw = props.get(prop)
        if field in _CLOSED_WIN_MONEY:
            parsed = parse_money(raw)
        elif field == "mkt_collab":
            parsed = normalize_multi_select(raw)
        else:
            parsed = str(raw).strip() if raw not in (None, "") else None
        if parsed is not None:
            values[column] = parsed
    return values


def business_fields_from_deal(deal_props, property_map):
    """{columna del hub: entero} con lo que HubSpot tenga cargado. Omite los vacios."""
    values = {}
    for field, column in BUSINESS_FIELD_TO_COLUMN.items():
        prop = property_map.get(field)
        if not prop:
            continue
        parsed = parse_int((deal_props or {}).get(prop))
        if parsed is not None:
            values[column] = parsed
    return values


def reset_caches():
    """Para tests y para el ?refresh=1 del endpoint de debug."""
    _PIPELINE_MAP_CACHE.update({"data": None, "ts": 0.0})
    _OPP_PROPERTY_MAP_CACHE.update({"data": None, "ts": 0.0})
