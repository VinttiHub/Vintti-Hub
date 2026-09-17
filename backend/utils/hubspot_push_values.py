"""De donde salen los numeros que el hub le manda a HubSpot al cerrar un deal.

Este modulo es la parte delicada del sync inverso: replica en el backend lo que
hoy calcula el navegador en `docs/assets/js/candidate-details.js`. Si se separa de
esa semantica, HubSpot y el hub muestran numeros distintos para el mismo hire.

Las tres reglas que hay que respetar, todas documentadas en CLAUDE.md:310-335:

1. `revenue` es POLISEMICA segun `opp_model`: en Staffing es `salary + fee`
   (mensual) y en Recruiting es el fee one-shot. Por eso el "Final Fee" que espera
   HubSpot sale de `fee` si es Staffing y de `revenue` si es Recruiting, que es
   exactamente el `isRecruiting ? employee_revenue : employee_fee` de
   candidate-details.js:524-526.
2. El salary/fee EFECTIVO no es `hire_opportunity.*` a secas: editar esos campos
   pasa por `salary_updates`, y el MRR prefiere esa tabla. La precedencia de abajo
   es la MISMA que `backend/dashboards/datasets/_mrr_staffing.py:79-95`.
3. `salary_updates` se llavea por candidato, NO por opp: la columna
   `opportunity_id` existe pero nunca se llena.

Nada de aca escribe. Solo lee.
"""

import re

from utils.hubspot_opportunities import fold


# ---------------------------------------------------------------- normalizadores
#
# Los 3 campos de abajo son SELECT en HubSpot: si se les manda un valor que no esta
# en la lista de opciones, HubSpot lo rechaza (o peor, la propiedad queda con un
# valor invisible en la UI). El hub los guarda como texto libre, asi que hay que
# traducirlos. Cuando no se puede, se OMITE y se explica por que: adivinar es peor
# que dejarlo vacio.

# HubSpot: ['Yes', 'No'] · hub: 'yes' / 'no' en minuscula (122 'no', 72 'yes').
_COMPUTER = {"yes": "Yes", "si": "Yes", "true": "Yes", "no": "No", "false": "No"}

# HubSpot: ['Transparent', 'Close'] · hub: los mismos dos, ya coinciden.
_PRICE_TYPE = {"transparent": "Transparent", "close": "Close"}

# HubSpot: ['LATAM', 'US', 'Canada'] · hub: `candidates.country`, texto libre con
# ~25 valores distintos. Se listan explicitamente los que se pueden afirmar; lo que
# no matchea (Spain, Jamaica, Trinidad y Tobago...) se omite y sale en el reporte,
# que es como se descubre que falta agregar uno.
_LATAM = {
    "argentina", "mexico", "colombia", "brazil", "brasil", "peru", "costa rica",
    "chile", "guatemala", "honduras", "el salvador", "venezuela", "ecuador",
    "nicaragua", "uruguay", "panama", "paraguay", "bolivia", "cuba", "belize",
    "republica dominicana", "dominican republic", "puerto rico",
}
_CANADA = {"canada"}


def _norm_select(valor, tabla):
    return tabla.get(fold(valor)) if valor not in (None, "") else None


def _norm_location(country):
    """country libre -> LATAM / US / Canada. None si no se puede afirmar."""
    f = fold(country)
    if not f:
        return None
    if f in _CANADA:
        return "Canada"
    # 'USA NY', 'USA CA', 'United States', 'EEUU'...
    if f.startswith("usa") or f in ("us", "united states", "eeuu", "estados unidos"):
        return "US"
    if f in _LATAM:
        return "LATAM"
    return None


# Las 5 opciones de la propiedad `mkt_collab` de HubSpot, tal cual estan definidas.
MKT_COLLAB_OPCIONES = ("Testimonial Video", "Case Study", "Webinar", "Event", "No Collab")
_MKT_POR_FOLD = {fold(o): o for o in MKT_COLLAB_OPCIONES}


def _norm_mkt_collab(valor):
    """'webinar; event' -> 'Webinar;Event'. Descarta lo que no este en la lista.

    HubSpot separa las multi-seleccion con ';' (sin espacio) y rechaza cualquier
    valor fuera de sus opciones.
    """
    if valor in (None, ""):
        return None
    elegidas = []
    for parte in str(valor).replace(",", ";").split(";"):
        opcion = _MKT_POR_FOLD.get(fold(parte))
        if opcion and opcion not in elegidas:
            elegidas.append(opcion)
    return ";".join(elegidas) or None


def _norm_date(valor):
    """HubSpot quiere YYYY-MM-DD. El hub las guarda como varchar, asi que hay de todo."""
    if valor in (None, ""):
        return None
    texto = str(valor).strip()[:10]
    return texto if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto) else None


# Precedencia del salary/fee efectivo, calcada de _mrr_staffing.py:79-95:
#   1) la ultima fila de salary_updates con fecha <= hoy
#   2) si no hay, la PRIMERA de todas (backfill de hires que arrancaron antes de
#      que existiera la primera actualizacion)
#   3) si no hay ninguna, hire_opportunity.salary / .fee
# El desempate por `update_id DESC` a igual fecha tambien viene de ahi: la UI
# puede escribir dos filas el mismo dia (ver project_salary_updates_doble_guardado).
_SQL = """
SELECT
    o.opportunity_id,
    o.opp_model,
    o.opp_stage,
    o.opp_position_name,
    o.opp_close_date,
    o.mkt_collab,
    o.account_id,
    NULLIF(o.hubspot_deal_id, '')     AS deal_id,
    NULLIF(o.hubspot_pipeline_id, '') AS pipeline_id,
    NULLIF(o.hubspot_dealstage_id, '') AS dealstage_id,
    h.candidate_id,
    c.name          AS candidate_name,
    h.salary        AS hire_salary,
    h.fee           AS hire_fee,
    h.revenue       AS hire_revenue,
    h.setup_fee     AS hire_setup_fee,
    h.price_type    AS hire_price_type,
    h.computer      AS hire_computer,
    h.start_date    AS hire_start_date,
    h.end_date      AS hire_end_date,
    c.address       AS cand_address,
    c.dni           AS cand_dni,
    c.country       AS cand_country,
    sr.salary       AS upd_salary,
    sr.fee          AS upd_fee,
    sr.update_id    AS upd_id,
    se.salary       AS first_salary,
    se.fee          AS first_fee,
    se.update_id    AS first_id
  FROM opportunity o
  -- El hire: por candidato_contratado si esta, y si no el mas reciente de la opp.
  -- Mismo criterio que utils/credit_loop.py:257-268, para no inventar una tercera
  -- regla: una opp puede tener N hires y hay filas fantasma del formulario publico
  -- de referencias.
  LEFT JOIN LATERAL (
      SELECT h2.*
        FROM hire_opportunity h2
       WHERE h2.opportunity_id = o.opportunity_id
         AND (o.candidato_contratado IS NULL OR h2.candidate_id = o.candidato_contratado)
       ORDER BY (h2.carga_active IS NOT NULL) DESC,
                h2.start_date DESC NULLS LAST,
                h2.hire_opp_id DESC
       LIMIT 1
  ) h ON TRUE
  LEFT JOIN candidates c ON c.candidate_id = h.candidate_id
  LEFT JOIN LATERAL (
      SELECT s.salary, s.fee, s.update_id
        FROM salary_updates s
       WHERE s.candidate_id = h.candidate_id
         AND s.date IS NOT NULL AND s.date::date <= CURRENT_DATE
       ORDER BY s.date::date DESC, s.update_id DESC
       LIMIT 1
  ) sr ON TRUE
  LEFT JOIN LATERAL (
      SELECT s.salary, s.fee, s.update_id
        FROM salary_updates s
       WHERE s.candidate_id = h.candidate_id AND s.date IS NOT NULL
       ORDER BY s.date::date ASC, s.update_id DESC
       LIMIT 1
  ) se ON TRUE
 WHERE o.opportunity_id = %s
"""


def _model_key(opp_model):
    texto = str(opp_model or "").strip().lower()
    if "staff" in texto:
        return "staffing"
    if "recruit" in texto:
        return "recruiting"
    return None


def _pick(row, campo):
    """(valor, fuente) segun la precedencia de _mrr_staffing. None si no hay dato."""
    if row.get("upd_" + campo) is not None:
        return row["upd_" + campo], "salary_updates#%s" % row.get("upd_id")
    if row.get("first_" + campo) is not None:
        return row["first_" + campo], "salary_updates#%s (la primera)" % row.get("first_id")
    if row.get("hire_" + campo) is not None:
        return row["hire_" + campo], "hire_opportunity.%s" % campo
    return None, None


def hire_values_for_opportunity(cursor, opportunity_id):
    """Los 4 valores que HubSpot pide al cerrar, mas de donde salio cada uno.

    Devuelve siempre un dict, nunca levanta por falta de datos: un hire a medio
    cargar tiene que poder reportarse ("por que falta") en vez de romper el cambio
    de stage. `motivos` es lo que explica cada hueco; sin eso un campo ausente no
    se distingue de un campo en cero.
    """
    cursor.execute(_SQL, (opportunity_id,))
    row = cursor.fetchone()
    if not row:
        return {"opportunity_id": opportunity_id, "existe": False,
                "valores": {}, "fuentes": {}, "motivos": {"_": "la opportunity no existe"}}

    row = dict(row)
    modelo = _model_key(row.get("opp_model"))
    valores, fuentes, motivos = {}, {}, {}

    def poner(campo, valor, fuente):
        if valor is None:
            return False
        valores[campo] = valor
        if fuente:
            fuentes[campo] = fuente
        return True

    if not row.get("candidate_id"):
        # Sin hire no hay plata que mandar. Pasa de verdad: una opp puede saltar a
        # Close Win sin candidato_contratado, y _unmark_signed_hire_active lo borra
        # si la opp rebota fuera de Signed.
        motivos["_hire"] = "la opp no tiene hire ni candidato contratado"
    else:
        salary, f_salary = _pick(row, "salary")
        if not poner("final_salary", salary, f_salary):
            motivos["final_salary"] = "el hire no tiene salary cargado"

        if modelo == "recruiting":
            # El fee one-shot vive en revenue. `salary_updates.fee` en Recruiting lo
            # fuerza a 0 la propia UI, asi que usarlo mandaria 0 a HubSpot.
            if not poner("final_fee", row.get("hire_revenue"), "hire_opportunity.revenue"):
                motivos["final_fee"] = "Recruiting sin revenue cargado"
            motivos["setup_fee"] = "no aplica en Recruiting"
        elif modelo == "staffing":
            fee, f_fee = _pick(row, "fee")
            if not poner("final_fee", fee, f_fee):
                motivos["final_fee"] = "el hire no tiene fee cargado"
            if not poner("setup_fee", row.get("hire_setup_fee"), "hire_opportunity.setup_fee"):
                motivos["setup_fee"] = "el hire no tiene setup fee cargado"
        else:
            # Igual que createSalaryUpdateFromInputs, que ante un modelo desconocido
            # no escribe nada: sin saber el modelo no se sabe que significa el fee.
            motivos["final_fee"] = "opp_model desconocido (%r): no se puede decidir fee vs revenue" % row.get("opp_model")
            motivos["setup_fee"] = "opp_model desconocido"

        # Los campos operativos que HubSpot pide al pasar a Signed. Todos salen del
        # hire o de la ficha del candidato, y estan 0/33 cargados en HubSpot.
        for campo, crudo, fuente, normalizador, queja in (
            ("price_type", row.get("hire_price_type"), "hire_opportunity.price_type",
             lambda v: _norm_select(v, _PRICE_TYPE),
             "price_type %r no es Transparent ni Close"),
            ("computer", row.get("hire_computer"), "hire_opportunity.computer",
             lambda v: _norm_select(v, _COMPUTER),
             "computer %r no se pudo leer como Yes/No"),
            ("candidate_start_date", row.get("hire_start_date"), "hire_opportunity.start_date",
             _norm_date, "start_date %r no esta en formato YYYY-MM-DD"),
            ("candidate_end_date", row.get("hire_end_date"), "hire_opportunity.end_date",
             _norm_date, "end_date %r no esta en formato YYYY-MM-DD"),
            ("candidate_address", row.get("cand_address"), "candidates.address",
             lambda v: (str(v).strip() or None) if v else None,
             "el candidato no tiene direccion cargada"),
            ("candidate_dni", row.get("cand_dni"), "candidates.dni",
             lambda v: (str(v).strip() or None) if v else None,
             "el candidato no tiene DNI cargado"),
            ("candidate_location", row.get("cand_country"), "candidates.country",
             _norm_location,
             "country %r no mapea a LATAM/US/Canada: agregalo a _LATAM si corresponde"),
        ):
            if not poner(campo, normalizador(crudo), fuente):
                motivos[campo] = (queja % (crudo,)) if "%r" in queja else queja

    # MKT Collab: multi-seleccion que HubSpot exige al cerrar. La carga la recruiter
    # en el popup de Close Win. HubSpot espera los valores separados por ';' y solo
    # acepta los 5 de su lista, asi que se filtra contra ella en vez de mandar texto
    # libre que la propiedad rechazaria.
    if not poner("mkt_collab", _norm_mkt_collab(row.get("mkt_collab")), "opportunity.mkt_collab"):
        motivos["mkt_collab"] = "la opp no tiene MKT Collab cargado"

    # Fecha de cierre. Va fuera del bloque del hire: es de la opp, no del hire.
    # Esta cargada en las 358 opps de Close Win del hub.
    if not poner("close_date", _norm_date(row.get("opp_close_date")), "opportunity.opp_close_date"):
        motivos["close_date"] = "la opp no tiene opp_close_date cargada"

    # OJO: "Role Hired" es el PUESTO, no la persona. Verificado contra los 26 deals
    # de Closed Win que lo tienen cargado: dicen "Accounts Payable", "Fund
    # Accountant", "Operations Manager"... ni uno solo es un nombre propio. Mandar
    # candidates.name ahi seria llenar la columna con otra cosa de la que HubSpot
    # viene guardando hace meses.
    #
    # Va FUERA del bloque del hire: el puesto es de la opp y no depende de que el
    # hire este cargado.
    if not poner("role_hired", (row.get("opp_position_name") or "").strip() or None,
                 "opportunity.opp_position_name"):
        motivos["role_hired"] = "la opp no tiene opp_position_name cargado"

    return {
        "opportunity_id": row["opportunity_id"],
        "existe": True,
        "opp_model": row.get("opp_model"),
        "opp_stage": row.get("opp_stage"),
        "opp_position_name": row.get("opp_position_name"),
        "opp_close_date": row.get("opp_close_date"),
        "deal_id": row.get("deal_id"),
        "pipeline_id": row.get("pipeline_id"),
        "dealstage_id": row.get("dealstage_id"),
        "candidate_id": row.get("candidate_id"),
        "candidate_name": row.get("candidate_name"),
        "valores": valores,
        "fuentes": fuentes,
        "motivos": motivos,
    }


def opportunities_pushables(cursor, limit=50):
    """Las opps que el push podria tocar: en Signed/Close Win y con deal atado.

    El filtro del deal no es una optimizacion: sin `hubspot_deal_id` no hay a que
    escribirle. Hoy son 6 sobre 358 Close Win, porque el resto son historicas que
    nunca se ataron a un deal.
    """
    cursor.execute(
        """
        SELECT opportunity_id
          FROM opportunity
         WHERE lower(btrim(opp_stage)) IN ('signed', 'close win')
           AND NULLIF(hubspot_deal_id, '') IS NOT NULL
         ORDER BY opportunity_id DESC
         LIMIT %s
        """,
        (limit,),
    )
    return [r["opportunity_id"] if isinstance(r, dict) else r[0] for r in cursor.fetchall()]
