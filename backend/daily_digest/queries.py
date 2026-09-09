"""Las tres reglas del digest, como SQL.

Gotchas del repo replicados a proposito. No "limpiar" ninguno:

  * R17 / rollback: `hire_opportunity` junta filas fantasma del formulario
    publico de reference checks (candidatos nunca contratados), y ADEMAS
    `_unmark_signed_hire_active` (accounts_routes.py) NO borra la fila cuando una
    opp vuelve para atras desde Signed: la deja con `carga_active` y `start_date`
    en NULL. Las dos trampas quedan tapadas por el mismo predicado del CTE
    `hires`. Es una feliz coincidencia, pero es la razon por la que ese WHERE no
    se puede simplificar.
  * `hire_opportunity.start_date` / `end_date` son `character varying`, no
    `date`: castear siempre con `NULLIF(x::text, '')::date`. Las fechas de
    `opportunity` (opp_close_date, deep_dive_date, nda_sent_date) SI son `date`.
  * `TRIM(o.opp_stage)`: la data tiene espacios.
  * `TRIM(LOWER(o.opp_model))`: el form escribe 'staffing' en un select y
    'Staffing' en otro. En la base hoy esta todo en minuscula, pero eso es
    suerte, no un invariante.
  * El primer <option> de un select es truthy, asi que el placeholder se guarda
    como si fuera un valor: hay 2 opps abiertas con opp_sales_lead =
    'select sales lead'. Por eso `_no_vacio()` filtra PLACEHOLDERS.
  * Un signo de porcentaje literal en el SQL (hasta dentro de un comentario)
    rompe psycopg2 con "argument formats can't be mixed". No escribir ninguno.
    Eso descarta el LIKE con comodines que seria la forma obvia de detectar una
    JD vacia; por eso la regla 2 filtra grueso en SQL y decide en Python.

Las tres devuelven el MISMO sobre de columnas, para que `service` las pueda
normalizar sin casos especiales:

    rule, owner_email, owner_name, owner_active, opportunity_id, candidate_id,
    client_name, position, candidate_name, anchor_date, missing[]

`owner_active` viene como columna en vez de como filtro del WHERE a proposito:
si el JOIN a `users` fuera INNER, una opp cuyo duenio ya no trabaja aca no
generaria fila y NADIE se enteraria, en silencio y para siempre. Asi esas filas
llegan igual y `render` las junta en una linea aparte para la owner.
"""
from __future__ import annotations

from . import people

# --------------------------------------------------------------------------- #
# Fragmentos compartidos
# --------------------------------------------------------------------------- #

def _no_vacio(expr: str) -> str:
    """SQL: `expr` tiene contenido real (ni NULL, ni vacio, ni placeholder)."""
    lista = ", ".join(f"'{p}'" for p in people.PLACEHOLDERS)
    return (f"(NULLIF(TRIM(COALESCE({expr}, '')), '') IS NOT NULL"
            f" AND LOWER(TRIM(COALESCE({expr}, ''))) NOT IN ({lista}))")


# El duenio se resuelve contra `users` SIEMPRE por LEFT JOIN. Ver el docstring.
_OWNER_JOIN = """
    LEFT JOIN users u
           ON LOWER(TRIM(u.email_vintti)) = owner.email
    LEFT JOIN admin_user_access aua ON aua.user_id = u.user_id
"""

_OWNER_COLS = """
    owner.email AS owner_email,
    COALESCE(NULLIF(TRIM(u.nickname), ''),
             NULLIF(TRIM(u.user_name), ''),
             owner.email) AS owner_name,
    (u.user_id IS NOT NULL AND COALESCE(aua.is_active, TRUE)) AS owner_active
"""

# Los hires REALES, con las fechas ya casteadas. Ver la nota R17 del docstring.
_HIRES_CTE = """
    hires AS (
      SELECT
        ho.opportunity_id,
        ho.candidate_id,
        COALESCE(ho.salary, 0)   AS salary,
        COALESCE(ho.fee, 0)      AS fee,
        COALESCE(ho.revenue, 0)  AS revenue,
        ho.status,
        ho.carga_inactive,
        NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '') AS start_raw,
        CASE WHEN ho.carga_active IS NOT NULL THEN ho.carga_active
             ELSE NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '')::date END AS start_d,
        CASE WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive
             WHEN NULLIF(TRIM(CAST(ho.end_date AS TEXT)), '') IS NULL THEN NULL
             ELSE NULLIF(TRIM(CAST(ho.end_date AS TEXT)), '')::date END AS end_d
      FROM hire_opportunity ho
      WHERE ho.carga_active IS NOT NULL
         OR NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '') IS NOT NULL
    )
"""


def _stage_list(stages) -> str:
    return ", ".join(f"'{s}'" for s in stages)


# --------------------------------------------------------------------------- #
# Regla 1 - pricing del hire sin cargar
# --------------------------------------------------------------------------- #
def pricing() -> tuple[str, dict]:
    """Hires firmados a los que les falta el numero.

    Duenio: `account.account_manager`. Al ganar la cuenta se reasigna al AM
    post-venta (ver `dashboards/datasets/_sales_scope.py`), y esta regla vive
    entera del lado post-venta, asi que el AM es quien tiene el dato hoy.

    Que falta depende del modelo, verificado contra `adaptHireFieldsByModel`
    (`docs/assets/js/candidate-details.js`), que ESCONDE fee/setup_fee en
    Recruiting y habilita `revenue` solo ahi:
        Staffing    -> salary y fee efectivo
        Recruiting  -> revenue
        + start_date en los dos

    `price_type` NO se reclama aunque este en el form: esta vacio en 317 de 406
    hires. Un campo que nadie llena no es un pendiente, es un campo muerto.

    La trampa de `salary_updates` corta para los dos lados. Si `ho.fee` es 0 pero
    hay un update con el fee real, no falta nada. Y el bug conocido de doble
    guardado (el blur de cada campo crea una fila) deja updates con fee 0 que, si
    se tomara "el mas reciente" a secas, PISARIAN un ho.fee bueno e inventarian
    un pendiente. Por eso se toma el ultimo update con fee distinto de cero.
    Esto DIFIERE a proposito de `routes/staffing_routes.py`: alla la pregunta es
    "que numero muestro", aca es "?alguien cargo algo?". Ante la duda se
    sobre-suprime, nunca se sobre-avisa.
    """
    sql = f"""
    WITH {_HIRES_CTE},
    base AS (
      SELECT
        o.opportunity_id,
        h.candidate_id,
        LOWER(TRIM(COALESCE(a.account_manager, ''))) AS owner_email_raw,
        NULLIF(TRIM(a.client_name), '')        AS client_name,
        NULLIF(TRIM(o.opp_position_name), '')  AS position,
        NULLIF(TRIM(c.name), '')               AS candidate_name,
        h.start_d                              AS anchor_date,
        (TRIM(LOWER(COALESCE(o.opp_model, ''))) = 'recruiting') AS es_recruiting,
        h.salary,
        h.revenue,
        h.start_raw,
        COALESCE(NULLIF(su.fee, 0), h.fee, 0) AS eff_fee
      FROM hires h
      JOIN opportunity o ON o.opportunity_id = h.opportunity_id
      LEFT JOIN account a ON a.account_id = o.account_id
      LEFT JOIN candidates c ON c.candidate_id = h.candidate_id
      LEFT JOIN LATERAL (
        SELECT s.fee
          FROM salary_updates s
         WHERE s.candidate_id = h.candidate_id
           AND COALESCE(s.fee, 0) <> 0
         ORDER BY s.date DESC NULLS LAST, s.update_id DESC
         LIMIT 1
      ) su ON TRUE
      WHERE TRIM(o.opp_stage) IN ({_stage_list(people.STAGES_CON_HIRE)})
        AND COALESCE(a.vintti_internal, FALSE) = FALSE
        AND h.carga_inactive IS NULL
        AND (h.end_d IS NULL OR h.end_d >= CURRENT_DATE)
        AND LOWER(TRIM(COALESCE(h.status, ''))) <> 'inactive'
        AND h.start_d IS NOT NULL
        AND h.start_d <= CURRENT_DATE - %(gracia)s::int
        AND h.start_d >= CURRENT_DATE - %(backlog)s::int
    ),
    flagged AS (
      SELECT b.*, ARRAY_REMOVE(ARRAY[
          CASE WHEN NOT b.es_recruiting AND b.salary  = 0 THEN 'Salary'  END,
          CASE WHEN NOT b.es_recruiting AND b.eff_fee = 0 THEN 'Fee'     END,
          CASE WHEN     b.es_recruiting AND b.revenue = 0 THEN 'Revenue' END,
          CASE WHEN b.start_raw IS NULL                   THEN 'Start date' END
      ], NULL) AS missing
      FROM base b
    ),
    owner AS (
      SELECT f.*, f.owner_email_raw AS email FROM flagged f
       WHERE COALESCE(ARRAY_LENGTH(f.missing, 1), 0) > 0
    )
    SELECT
      'pricing'::text AS rule,
      {_OWNER_COLS},
      owner.opportunity_id, owner.candidate_id, owner.client_name,
      owner.position, owner.candidate_name, owner.anchor_date, owner.missing
    FROM owner
    {_OWNER_JOIN}
    ORDER BY owner.anchor_date
    """
    return sql, {"gracia": people.GRACIA_DIAS["pricing"],
                 "backlog": people.BACKLOG_DIAS}


# --------------------------------------------------------------------------- #
# Regla 2 - job description faltante
# --------------------------------------------------------------------------- #
def job_description() -> tuple[str, dict]:
    """Opps abiertas sin JD, a la recruiter asignada.

    Duenio: `opp_hr_lead`. Es literalmente el to-do que el Hub ya genera solo
    ("Draft the job description for the {role} at {client}",
    `utils/hr_lead_todo.py`), solo que ese to-do se puede tildar sin cargar nada.

    Si la opp no tiene recruiter asignada no genera fila: no se le puede
    reclamar una JD a nadie. Esas opps (9 hoy) las levanta la regla de datos
    base por el lado del sales lead.

    El SQL filtra GRUESO por largo y devuelve el texto; quien decide es Python
    con `html_to_plain_text`. La columna es HTML y esta llena de casos que no son
    NULL pero tampoco son una JD (`<p></p>`, `<br>`, `<p>TBD</p>`), y el
    stripper del repo ya sabe resolverlos. Reimplementarlo en SQL seria una
    segunda semantica que se despega de la primera.
    """
    sql = f"""
    WITH base AS (
      SELECT
        o.opportunity_id,
        NULL::int AS candidate_id,
        LOWER(TRIM(COALESCE(o.opp_hr_lead, ''))) AS email,
        NULLIF(TRIM(a.client_name), '')       AS client_name,
        NULLIF(TRIM(o.opp_position_name), '') AS position,
        NULL::text AS candidate_name,
        COALESCE(o.deep_dive_date, o.nda_sent_date, o.since_sourcing) AS anchor_date,
        ARRAY['Job description']::text[] AS missing,
        LEFT(COALESCE(NULLIF(TRIM(o.hr_job_description), ''),
                      NULLIF(TRIM(o.career_description), ''),
                      NULLIF(TRIM(o.career_requirements), ''), ''), 600) AS jd_raw
      FROM opportunity o
      LEFT JOIN account a ON a.account_id = o.account_id
      WHERE TRIM(o.opp_stage) IN ({_stage_list(people.STAGES_ABIERTOS)})
        AND COALESCE(a.vintti_internal, FALSE) = FALSE
        AND {_no_vacio('o.opp_hr_lead')}
        AND (COALESCE(o.deep_dive_date, o.nda_sent_date, o.since_sourcing) IS NULL
             OR COALESCE(o.deep_dive_date, o.nda_sent_date, o.since_sourcing)
                <= CURRENT_DATE - %(gracia)s::int)
        AND LENGTH(COALESCE(o.hr_job_description, '')
                   || COALESCE(o.career_description, '')
                   || COALESCE(o.career_requirements, '')) < 4000
    )
    SELECT
      'jd'::text AS rule,
      {_OWNER_COLS},
      owner.opportunity_id, owner.candidate_id, owner.client_name,
      owner.position, owner.candidate_name, owner.anchor_date, owner.missing,
      owner.jd_raw
    FROM base owner
    {_OWNER_JOIN}
    ORDER BY owner.anchor_date
    """
    return sql, {"gracia": people.GRACIA_DIAS["jd"]}


# --------------------------------------------------------------------------- #
# Regla 3 - datos base de la opp
# --------------------------------------------------------------------------- #
def base_data() -> tuple[str, dict]:
    """Opps abiertas con el encabezado a medias, al sales lead.

    Duenio: `opp_sales_lead`, con fallback al `account_manager` — porque una opp
    SIN sales lead es, ella misma, uno de los datos que faltan, y entonces no hay
    a quien reclamarsela por esa via.

    Una fila por OPORTUNIDAD con un array de etiquetas, nunca una fila por
    campo: si no, una opp recien creada escribe ocho lineas de Slack sola.

    Que campos entran lo decide `people.CAMPOS_BASE`, y ahi esta explicado por
    que `years_experience` arranca apagado.
    """
    c = people.CAMPOS_BASE
    cond, etiquetas = [], []

    def add(activo: bool, test: str, label: str):
        if not activo:
            return
        cond.append(test)
        etiquetas.append(f"CASE WHEN {test} THEN '{label}' END")

    add(c["position"], f"NOT {_no_vacio('o.opp_position_name')}", "Opportunity Name")
    add(c["model"], "TRIM(LOWER(COALESCE(o.opp_model, ''))) NOT IN "
                    "('staffing', 'recruiting', 'mix')", "Model")
    add(c["sales_lead"], f"NOT {_no_vacio('o.opp_sales_lead')}", "Sales Lead")
    add(c["type"], f"NOT {_no_vacio('o.opp_type')}", "Type")
    add(c["budget"], "COALESCE(o.min_budget, 0) = 0 OR COALESCE(o.max_budget, 0) = 0",
        "Client Budget")
    add(c["salary_range"], "COALESCE(o.min_salary, 0) = 0 OR COALESCE(o.max_salary, 0) = 0",
        "Candidate Salary Range")
    add(c["years_experience"], "COALESCE(o.years_experience, 0) = 0", "Years of Experience")

    if not cond:
        return "SELECT 1 WHERE FALSE", {}

    sql = f"""
    WITH base AS (
      SELECT
        o.opportunity_id,
        NULL::int AS candidate_id,
        COALESCE(
          CASE WHEN {_no_vacio('o.opp_sales_lead')}
               THEN LOWER(TRIM(o.opp_sales_lead)) END,
          CASE WHEN {_no_vacio('a.account_manager')}
               THEN LOWER(TRIM(a.account_manager)) END,
          ''
        ) AS email,
        NULLIF(TRIM(a.client_name), '')       AS client_name,
        NULLIF(TRIM(o.opp_position_name), '') AS position,
        NULL::text AS candidate_name,
        COALESCE(o.deep_dive_date, o.nda_sent_date, o.since_sourcing) AS anchor_date,
        ARRAY_REMOVE(ARRAY[{', '.join(etiquetas)}], NULL) AS missing
      FROM opportunity o
      LEFT JOIN account a ON a.account_id = o.account_id
      WHERE TRIM(o.opp_stage) IN ({_stage_list(people.STAGES_ABIERTOS)})
        AND COALESCE(a.vintti_internal, FALSE) = FALSE
        AND (COALESCE(o.deep_dive_date, o.nda_sent_date, o.since_sourcing) IS NULL
             OR COALESCE(o.deep_dive_date, o.nda_sent_date, o.since_sourcing)
                <= CURRENT_DATE - %(gracia)s::int)
        AND ({' OR '.join(f'({x})' for x in cond)})
    )
    SELECT
      'base'::text AS rule,
      {_OWNER_COLS},
      owner.opportunity_id, owner.candidate_id, owner.client_name,
      owner.position, owner.candidate_name, owner.anchor_date, owner.missing
    FROM base owner
    {_OWNER_JOIN}
    ORDER BY owner.anchor_date
    """
    return sql, {"gracia": people.GRACIA_DIAS["base"]}


RULES = {
    "pricing": pricing,
    "jd": job_description,
    "base": base_data,
}
