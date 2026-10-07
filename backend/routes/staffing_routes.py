"""Staffing — la sección que reemplaza el Google Sheet "Candidate Success VINTTI".

Tres vistas, las tres con la MISMA fuente de verdad que el resto del Hub
(`hire_opportunity` + `opportunity` + `account` + `candidates`):

  * `/staffing/database` — una fila por (candidato, cuenta) de Staffing.
  * `/staffing/churn`    — las bajas reales (excluye buyouts), con filtro de año.
  * `/staffing/bonuses`  — `bonus_requests` con los dos estados de pago del Sheet.

Lo que el Sheet tenía y la base no (Platform, Performance, Comments, y el override
de Renuncia/Despido) vive en la tabla lateral `staffing_extra`, tipada por el par
(candidate_id, account_id). NO se agregan columnas a `hire_opportunity`: esa tabla
también junta filas basura del formulario público de referencias (ver el comentario
R17 en dashboards/datasets/acpa_history.py) y es el corazón de todas las métricas.

Grano: (candidato, cuenta). Un candidato puede tener varias filas en
`hire_opportunity` para la misma cuenta (los aumentos históricos crearon filas
nuevas), así que se colapsan igual que hace `cohort_by_contractor`: la opp
"primaria" es la de `start_d` más reciente y es la que manda para salary/fee.

Ojo con dos trampas ya conocidas del repo:
  * un `%` literal en el SQL (incluso en un comentario) rompe psycopg2.
  * desempaquetar un RealDictCursor devuelve las CLAVES, no los valores.
"""
from __future__ import annotations

import csv
import io
from datetime import date

from flask import Blueprint, Response, jsonify, request
from psycopg2.extras import Json, RealDictCursor

from db import get_connection

bp = Blueprint("staffing", __name__, url_prefix="/staffing")


# --------------------------------------------------------------------------- #
# Permisos — el allow-list del sidebar es sólo cosmético, el gate real es este.
# Misma lista que `equipmentsLink` en docs/assets/js/sidebar.js.
# --------------------------------------------------------------------------- #
STAFFING_ALLOWED = {
    "pgonzales@vintti.com",
    "jazmin@vintti.com",
    "agustin@vintti.com",
    "lara@vintti.com",
    "pilar@vintti.com",  # AM, agregada 2026-10-07 (pedido de la owner)
}


def _current_email() -> str:
    return (request.headers.get("X-User-Email") or "").strip().lower()


def _forbidden():
    return jsonify({"error": "You do not have access to the Staffing section."}), 403


# --------------------------------------------------------------------------- #
# Schema (lazy, sin migration runner — igual que offboarding_routes / credit_loop)
# --------------------------------------------------------------------------- #
_SCHEMA_READY = False


def _ensure_schema(cur) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS staffing_extra (
            staffing_extra_id BIGSERIAL PRIMARY KEY,
            candidate_id      BIGINT,
            account_id        BIGINT,
            candidate_name    TEXT,
            client_name       TEXT,
            platform          TEXT,
            performance       TEXT,
            provider          TEXT,
            notes             TEXT,
            exit_type         TEXT,
            churn_m3_override BOOLEAN,
            source            TEXT NOT NULL DEFAULT 'hub',
            updated_by        TEXT,
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_staffing_extra_pair
          ON staffing_extra (candidate_id, account_id)
          WHERE candidate_id IS NOT NULL
        """
    )
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_staffing_extra_orphan
          ON staffing_extra (LOWER(candidate_name), LOWER(COALESCE(client_name, '')))
          WHERE candidate_id IS NULL
        """
    )
    # Los dos estados de pago del Sheet: cobrado al cliente vs. pagado al candidato.
    # `bonus_requests.status` sigue siendo el del workflow de aprobación.
    # `provider` se agregó después de la primera versión de la tabla.
    cur.execute("ALTER TABLE staffing_extra ADD COLUMN IF NOT EXISTS provider TEXT")
    # Check "Payments" de la tabla: marca fija por par, se destilda a mano.
    cur.execute(
        "ALTER TABLE staffing_extra ADD COLUMN IF NOT EXISTS payment BOOLEAN NOT NULL DEFAULT FALSE"
    )
    cur.execute("ALTER TABLE bonus_requests ADD COLUMN IF NOT EXISTS invoice_status TEXT")
    cur.execute("ALTER TABLE bonus_requests ADD COLUMN IF NOT EXISTS candidate_status TEXT")

    # Columnas y opciones que se crean desde la página (ver "Columnas y opciones
    # editables" más abajo). Los valores de las columnas custom van en `custom`.
    cur.execute(
        "ALTER TABLE staffing_extra ADD COLUMN IF NOT EXISTS custom JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    cur.execute(
        "ALTER TABLE bonus_requests ADD COLUMN IF NOT EXISTS custom JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS staffing_columns (
            column_id   BIGSERIAL PRIMARY KEY,
            tab         TEXT NOT NULL,
            label       TEXT NOT NULL,
            type        TEXT NOT NULL,
            position    INTEGER NOT NULL DEFAULT 0,
            archived_at TIMESTAMPTZ,
            created_by  TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS staffing_options (
            option_id   BIGSERIAL PRIMARY KEY,
            tab         TEXT NOT NULL,
            col_key     TEXT NOT NULL,
            value       TEXT NOT NULL,
            color       TEXT NOT NULL DEFAULT 'gray',
            position    INTEGER NOT NULL DEFAULT 0,
            locked      BOOLEAN NOT NULL DEFAULT FALSE,
            archived_at TIMESTAMPTZ,
            updated_by  TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_staffing_options_value
          ON staffing_options (tab, col_key, LOWER(value))
          WHERE archived_at IS NULL
        """
    )
    _seed_options(cur)
    _SCHEMA_READY = True


# --------------------------------------------------------------------------- #
# Columnas y opciones editables desde la página
#
# Hasta el 2026-10-05 cada desplegable estaba escrito a mano en staffing.js y
# agregar "Payoneer" era un cambio de código. Ahora los catálogos viven en
# `staffing_options` y las columnas nuevas en `staffing_columns`; sus valores, en
# el JSONB `custom` de `staffing_extra` (Database y Churn, mismo par) o de
# `bonus_requests` (Bonuses). La clave de una columna custom es `c_<column_id>`:
# estable aunque se renombre, y única entre pestañas.
# --------------------------------------------------------------------------- #
TABS = ("database", "churn", "bonos")
COLUMN_TYPES = {"select", "text", "number", "date", "checkbox"}
# Paleta cerrada: cada clave es una clase `stf-badge--c-<color>` en staffing.css.
OPTION_COLORS = (
    "gray", "red", "orange", "yellow", "green", "teal",
    "cyan", "blue", "lilac", "purple", "magenta",
)

# Las columnas de lista que ya existían, y dónde guardan su valor. Renombrar una
# opción actualiza esa columna en las filas que la tenían.
BUILTIN_SELECTS = {
    ("database", "platform"): ("staffing_extra", "platform"),
    ("database", "performance"): ("staffing_extra", "performance"),
    ("database", "provider"): ("staffing_extra", "provider"),
    ("churn", "exit_type"): ("staffing_extra", "exit_type"),
    ("bonos", "invoice_status"): ("bonus_requests", "invoice_status"),
    ("bonos", "candidate_status"): ("bonus_requests", "candidate_status"),
}

# Lo que estaba hardcodeado en el JS, con sus colores. Se siembra una sola vez por
# columna. `locked` = la página tiene lógica atada a ese texto (los KPIs de Churn
# cuentan "Terminated"/"Resigned", que además se derivan del motivo de baja, y los
# de Bonuses cuentan "Paid"): se les puede cambiar el color, no el nombre.
SEED_OPTIONS = {
    ("database", "platform"): [
        ("Bank Account", "orange"), ("Deel", "lilac"), ("Ontop", "cyan"), ("Payoneer", "magenta"),
    ],
    ("database", "performance"): [
        ("Not performing", "red"), ("Performing", "green"), ("Under review", "yellow"),
        ("Feedback", "orange"), ("Salary review", "blue"), ("Computer repair", "purple"),
        ("Computer pedido", "magenta"), ("Onboarding", "teal"),
    ],
    ("database", "provider"): [("Quipteams", "blue"), ("Onbordea", "teal")],
    ("churn", "exit_type"): [("Resigned", "cyan", True), ("Terminated", "red", True)],
    ("bonos", "invoice_status"): [("Paid", "green", True), ("Sent, not paid", "yellow")],
    ("bonos", "candidate_status"): [("Paid", "green", True), ("Not Paid", "yellow")],
}


def _seed_options(cur) -> None:
    for (tab, key), options in SEED_OPTIONS.items():
        cur.execute(
            "SELECT 1 FROM staffing_options WHERE tab = %s AND col_key = %s LIMIT 1", (tab, key)
        )
        if cur.fetchone():
            continue
        for position, opt in enumerate(options, 1):
            cur.execute(
                """
                INSERT INTO staffing_options (tab, col_key, value, color, position, locked)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (tab, key, opt[0], opt[1], position, len(opt) > 2 and opt[2]),
            )


class _BadValue(ValueError):
    """Valor inválido para una columna custom: se devuelve como 400."""


def _custom_columns(cur, tabs) -> dict:
    """{c_<id>: type} de las columnas custom activas de esas pestañas."""
    cur.execute(
        "SELECT column_id, type FROM staffing_columns WHERE tab = ANY(%s) AND archived_at IS NULL",
        (list(tabs),),
    )
    return {f"c_{r['column_id']}": r["type"] for r in cur.fetchall()}


def _coerce_custom(kind: str, raw):
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if kind == "number":
        try:
            return float(str(raw).replace(",", "").replace("$", "").strip())
        except ValueError:
            raise _BadValue(f"'{raw}' is not a number.")
    if kind == "checkbox":
        return _tri_bool(raw)
    if kind == "date":
        txt = str(raw).strip()[:10]
        try:
            date.fromisoformat(txt)
        except ValueError:
            raise _BadValue(f"'{raw}' is not a date (YYYY-MM-DD).")
        return txt
    txt = _clean(raw)
    return txt[:2000] if txt else None


def _custom_patch(cur, raw, tabs):
    """Valida `custom` del request -> (claves a escribir, claves a borrar).

    Las claves tienen que ser columnas activas de esas pestañas. Vacío = borrar la
    clave (no guardar un "" que después aparece como valor en el filtro).
    """
    if not isinstance(raw, dict):
        raise _BadValue("custom must be an object.")
    known = _custom_columns(cur, tabs)
    to_set, to_del = {}, []
    for key, value in raw.items():
        if key not in known:
            raise _BadValue(f"Unknown column: {key}")
        coerced = _coerce_custom(known[key], value)
        if coerced is None:
            to_del.append(key)
        else:
            to_set[key] = coerced
    return to_set, to_del


# Mezcla en vez de pisar: editar una celda no borra las demás columnas custom.
CUSTOM_MERGE_SQL = (
    "custom = (COALESCE(custom, '{}'::jsonb) - %(custom_del)s::text[]) || %(custom_set)s::jsonb"
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
# Gente que figura como `opportunity.opp_hr_lead` en búsquedas viejas pero que hoy
# no cumple ese rol. Decisión de la owner (2026-09-01): no mostrarlas en la columna
# Recruiter de esta página; esos contractors quedan sin recruiter asignado.
#
# NO se toca `opportunity.opp_hr_lead`: el dato histórico queda intacto y esto se
# revierte sacando el mail de esta lista. Mismo criterio que la exclusión de
# ex-recruiters en los datasets de recruiter power.
FORMER_RECRUITERS = {
    "bahia@vintti.com",            # Sales Lead — llevó búsquedas hasta 2025-12
    "jazmin@vintti.com",           # HR Lead — llevó búsquedas hasta 2025-10
    "agustina.barbero@vintti.com", # ya no está en `users`
    "pilar.fernandez@vintti.com",  # ya no está en `users` — OJO: no confundir con
                                   # pilar@vintti.com (Pilar Flores Levalle), que
                                   # sí es recruiter activa y lleva 71 contractors
}

TRUEY = {"si", "sí", "yes", "y", "true", "t", "1"}
FALSEY = {"no", "n", "false", "f", "0"}

# Cómo se deriva Renuncia vs Despido a partir del motivo cargado en el hire.
# El Sheet lo llevaba a mano; acá es un default que se puede pisar por fila.
#
# `hire_opportunity.inactive_reason` guarda las etiquetas EN INGLÉS (son las del
# formulario de la oportunidad); el Sheet las escribía en español. Se mapean las
# dos formas para que las filas que ya están en la base deriven solas y las que
# vengan del import también.
EXIT_BY_REASON = {
    # Como lo guarda la base (inglés)
    "poor candidate performance": "Terminated",
    "company layoffs / downsizing": "Terminated",
    "accepted a better offer": "Resigned",
    "candidate resigned": "Resigned",
    # Como venía del Sheet (español), por si alguien reimporta
    "mala performance": "Terminated",
    "recorte": "Terminated",
    "recibe mejor oferta": "Resigned",
    "candidato decide irse": "Resigned",
}

# La página está en inglés; los valores viejos importados del Sheet vienen en
# español. Se normalizan al leer para no depender de una migración.
EXIT_TYPE_ALIASES = {"despido": "Terminated", "renuncia": "Resigned"}


def _tri_bool(raw):
    """'Si'/'No'/vacío -> True/False/None. Tolera booleanos ya tipados."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    txt = str(raw).strip().lower()
    if txt in TRUEY:
        return True
    if txt in FALSEY:
        return False
    return None


def _derive_exit_type(reason: str | None) -> str | None:
    return EXIT_BY_REASON.get((reason or "").strip().lower())


def _clean(value):
    if value is None:
        return None
    txt = str(value).strip()
    return txt or None


# --------------------------------------------------------------------------- #
# SQL compartido: los hires de Staffing con salary/fee efectivos.
#
# `salary_updates` no tiene opportunity_id, así que los aumentos sólo aplican a la
# opp primaria del par (candidato, cuenta) — mismo criterio que
# cohort_by_contractor / _mrr_staffing, para no contar dos veces un aumento cuando
# hay varias opps paralelas en la misma cuenta.
#
# El salario efectivo se resuelve a la fecha de corte del hire: hoy si sigue
# activo, su end_d si ya se fue (así un inactivo muestra el último sueldo que
# cobró, no el de hoy).
# --------------------------------------------------------------------------- #
HIRES_CTE = """
    hires AS (
      SELECT
        ho.hire_opp_id,
        ho.opportunity_id,
        ho.candidate_id,
        ho.account_id,
        -- Hay DOS pares de fechas a propósito:
        --
        --   start_d / end_d      fechas REALES (primer y último día de trabajo).
        --                        Son las que se muestran en la tabla y las que
        --                        mostraba el Sheet. `carga_active` es la fecha en
        --                        que la opp pasó a "Signed" — la firma, no el primer
        --                        día — así que acá es sólo el fallback.
        --
        --   start_dash / end_dash  el orden canónico de las métricas
        --                        (COALESCE(carga_active, start_date)), que es lo que
        --                        usa active_headcount_30d_total.py. Sirven SÓLO para
        --                        decidir quién está activo, para dar exactamente el
        --                        mismo número que el KPI "Candidatos activos".
        COALESCE(
          CASE WHEN CAST(ho.start_date AS TEXT) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
               THEN LEFT(TRIM(CAST(ho.start_date AS TEXT)), 10)::date END,
          ho.carga_active::date
        ) AS start_d,
        COALESCE(
          CASE WHEN CAST(ho.end_date AS TEXT) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
               THEN LEFT(TRIM(CAST(ho.end_date AS TEXT)), 10)::date END,
          ho.carga_inactive::date
        ) AS end_d,
        COALESCE(
          ho.carga_active::date,
          CASE WHEN CAST(ho.start_date AS TEXT) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
               THEN LEFT(TRIM(CAST(ho.start_date AS TEXT)), 10)::date END
        ) AS start_dash,
        COALESCE(
          ho.carga_inactive::date,
          CASE WHEN CAST(ho.end_date AS TEXT) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
               THEN LEFT(TRIM(CAST(ho.end_date AS TEXT)), 10)::date END
        ) AS end_dash,
        -- churn_d: el día en que se marcó la baja en la base (`carga_inactive`),
        -- no el último día trabajado (ése es end_d).
        ho.carga_inactive::date AS churn_d,
        LOWER(TRIM(COALESCE(CAST(ho.status AS TEXT), ''))) AS hire_status,
        CASE
          WHEN NULLIF(TRIM(ho.buyout_daterange), '') IS NOT NULL
            THEN TO_DATE(TRIM(ho.buyout_daterange) || '-01', 'YYYY-MM-DD')
          ELSE NULL
        END AS buyout_d,
        COALESCE(ho.salary, 0)::numeric AS hire_salary,
        COALESCE(ho.fee, 0)::numeric    AS hire_fee,
        LOWER(TRIM(COALESCE(CAST(ho.computer AS TEXT), '')))          AS computer,
        NULLIF(TRIM(CAST(ho.inactive_reason AS TEXT)), '')            AS inactive_reason,
        NULLIF(TRIM(CAST(ho.inactive_comments AS TEXT)), '')          AS inactive_comments,
        NULLIF(TRIM(CAST(ho.inactive_vinttierror AS TEXT)), '')       AS inactive_vinttierror
      FROM hire_opportunity ho
      JOIN opportunity o     ON o.opportunity_id = ho.opportunity_id
      LEFT JOIN account a    ON a.account_id     = ho.account_id
      WHERE o.opp_model = 'Staffing'
        AND COALESCE(a.vintti_internal, FALSE) = FALSE
        AND ho.candidate_id IS NOT NULL
        AND ho.account_id IS NOT NULL
        -- R17: descartar las filas que crea el formulario público de referencias
        -- para candidatos que sólo compitieron (nacen sin carga_active ni start_date).
        AND (
          ho.carga_active IS NOT NULL
          OR NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '') IS NOT NULL
        )
    ),
    -- Rango de vida del par (candidato, cuenta) y su fecha de corte: hoy si sigue
    -- activo, su end_d si ya se fue. Nunca antes del start (un onboarding que
    -- todavía no arrancó se corta en su propia fecha de inicio, no en hoy).
    pair_bounds AS (
      SELECT
        h.candidate_id,
        h.account_id,
        MIN(h.start_d) AS start_d,
        CASE WHEN BOOL_OR(h.end_d IS NULL) THEN NULL ELSE MAX(h.end_d) END AS end_d,
        -- Misma puerta que end_d: si al par le queda un hire abierto no hay baja
        -- que mostrar, aunque una fila vieja tenga carga_inactive de un paso anterior.
        CASE WHEN BOOL_OR(h.end_d IS NULL) THEN NULL ELSE MAX(h.churn_d) END AS churn_d,
        MAX(h.buyout_d) AS buyout_d,
        -- Vigencia = la misma regla que el GMRR del dashboard
        -- (gmrr_contractors_detail / staffing_window_summary) y que
        -- active_headcount_history: sólo fechas, cortando a hoy.
        --
        -- El KPI `active_headcount_30d_total` agrega además `status = 'active'` y por
        -- eso da 1 menos. Acá se sigue a la mayoría (las dos cards de plata + el
        -- historial) para que GMRR y MRR reconcilien al centavo; el único caso donde
        -- difiere es alguien cuyo último día es HOY y ya tiene status='inactive'
        -- (Gerardo Sztrancman el 2026-08-31), y se resuelve solo al día siguiente,
        -- cuando end_d < hoy lo saca también del GMRR.
        --
        -- BOOL_OR: al candidato le alcanza con un hire vigente, igual que el
        -- COUNT(DISTINCT candidate_id) del dashboard.
        BOOL_OR(
          h.start_dash IS NOT NULL
          AND h.start_dash <= CURRENT_DATE
          AND COALESCE(h.end_dash, DATE '9999-12-31') >= CURRENT_DATE
        ) AS vigente
      FROM hires h
      GROUP BY h.candidate_id, h.account_id
    ),
    cut AS (
      SELECT pb.*,
        -- cut_d: hasta dónde mirar para saber qué opps siguen en pie. Se estira
        -- hasta start_d para no perder a los que todavía no arrancaron.
        GREATEST(COALESCE(pb.end_d, CURRENT_DATE), pb.start_d) AS cut_d,
        -- snap_d: la fecha a la que se resuelve salary/fee contra `salary_updates`.
        -- Para los vigentes es HOY, igual que el snapshot del dashboard
        -- (_mrr_staffing.unit_snapshot corta en win_fin = hoy). No usar cut_d acá:
        -- para un onboarding cut_d cae en su fecha de inicio futura y agarraría
        -- updates que el dashboard todavía no aplica, dando otro número.
        CASE
          WHEN COALESCE(pb.vigente, FALSE) THEN CURRENT_DATE
          ELSE GREATEST(COALESCE(pb.end_d, CURRENT_DATE), pb.start_d)
        END AS snap_d
      FROM pair_bounds pb
    ),
    -- Sólo las opps vigentes a esa fecha de corte. Los aumentos históricos dejaron
    -- filas viejas ya cerradas en hire_opportunity; si no se filtran, el sueldo se
    -- cuenta dos veces. Mismo criterio que `opps_in_month` en cohort_by_contractor.
    live AS (
      SELECT h.*, cu.cut_d, cu.snap_d
      FROM hires h
      JOIN cut cu ON cu.candidate_id = h.candidate_id AND cu.account_id = h.account_id
      WHERE h.start_d <= cu.cut_d
        AND (h.end_d IS NULL OR h.end_d >= cu.cut_d)
    ),
    ranked AS (
      SELECT l.*,
        ROW_NUMBER() OVER (
          PARTITION BY l.candidate_id, l.account_id
          ORDER BY l.start_d DESC NULLS LAST, l.opportunity_id DESC
        ) AS rn_primary
      FROM live l
    ),
    eff AS (
      SELECT r.*,
        CASE WHEN r.rn_primary = 1
          THEN COALESCE(su_recent.salary::numeric, su_first.salary::numeric, r.hire_salary)
          ELSE r.hire_salary END AS salary,
        CASE WHEN r.rn_primary = 1
          THEN COALESCE(su_recent.fee::numeric, su_first.fee::numeric, r.hire_fee)
          ELSE r.hire_fee END AS fee
      FROM ranked r
      LEFT JOIN LATERAL (
        SELECT s.salary, s.fee FROM salary_updates s
        WHERE s.candidate_id = r.candidate_id
          AND s.date IS NOT NULL
          AND s.date::date <= r.snap_d
        ORDER BY s.date::date DESC, s.update_id DESC
        LIMIT 1
      ) su_recent ON TRUE
      LEFT JOIN LATERAL (
        SELECT s.salary, s.fee FROM salary_updates s
        WHERE s.candidate_id = r.candidate_id AND s.date IS NOT NULL
        ORDER BY s.date::date ASC, s.update_id ASC
        LIMIT 1
      ) su_first ON TRUE
    ),
    -- Un renglón por par. Salary/fee suman todas las opps vigentes (un candidato
    -- puede tener dos posiciones en paralelo en la misma cuenta); el resto de los
    -- campos los aporta la opp primaria = la de start_d más reciente.
    pairs AS (
      SELECT
        cu.candidate_id,
        cu.account_id,
        cu.start_d,
        cu.end_d,
        cu.churn_d,
        cu.buyout_d,
        cu.vigente,
        MAX(e.hire_opp_id)    FILTER (WHERE e.rn_primary = 1) AS hire_opp_id,
        MAX(e.opportunity_id) FILTER (WHERE e.rn_primary = 1) AS opportunity_id,
        COALESCE(SUM(e.salary), 0) AS salary,
        COALESCE(SUM(e.fee), 0)    AS fee,
        MAX(e.computer)                 FILTER (WHERE e.rn_primary = 1) AS computer,
        MAX(e.inactive_reason)          FILTER (WHERE e.rn_primary = 1) AS inactive_reason,
        MAX(e.inactive_comments)        FILTER (WHERE e.rn_primary = 1) AS inactive_comments,
        MAX(e.inactive_vinttierror)     FILTER (WHERE e.rn_primary = 1) AS inactive_vinttierror
      FROM cut cu
      LEFT JOIN eff e ON e.candidate_id = cu.candidate_id AND e.account_id = cu.account_id
      GROUP BY cu.candidate_id, cu.account_id, cu.start_d, cu.end_d, cu.churn_d,
               cu.buyout_d, cu.vigente
    )
"""

# Enriquecimiento común: candidato, cuenta, recruiter, proveedor de equipo y extras.
PAIRS_SELECT = """
    SELECT
      p.candidate_id::text                                   AS candidate_id,
      p.account_id::text                                     AS account_id,
      p.hire_opp_id::text                                    AS hire_opp_id,
      p.opportunity_id::text                                 AS opportunity_id,
      TRIM(COALESCE(c.name, ''))                             AS candidate_name,
      NULLIF(TRIM(COALESCE(c.email, '')), '')                AS mail,
      NULLIF(TRIM(COALESCE(c.country, '')), '')              AS country,
      COALESCE(a.client_name, '')                            AS client_name,
      NULLIF(TRIM(COALESCE(o.opp_position_name, '')), '')    AS position_name,
      COALESCE(NULLIF(TRIM(COALESCE(u.user_name, '')), ''),
               NULLIF(TRIM(COALESCE(o.opp_hr_lead, '')), '')) AS recruiter,
      LOWER(NULLIF(TRIM(COALESCE(o.opp_hr_lead, '')), ''))    AS hr_lead_email,
      p.start_d::text                                        AS start_date,
      p.end_d::text                                          AS end_date,
      p.churn_d::text                                        AS churn_date,
      p.buyout_d::text                                       AS buyout_month,
      COALESCE(p.salary, 0)::numeric(12,2)                   AS salary,
      COALESCE(p.fee, 0)::bigint                             AS fee,
      (COALESCE(p.salary, 0) + COALESCE(p.fee, 0))::numeric(12,2) AS client_payment,
      p.computer                                             AS computer,
      COALESCE(NULLIF(TRIM(COALESCE(eq.proveedor, '')), ''),
               se.provider)                                  AS provider,
      -- Si el equipo trae proveedor, ése gana y editar el de acá no se vería.
      (NULLIF(TRIM(COALESCE(eq.proveedor, '')), '') IS NOT NULL) AS provider_locked,
      COALESCE(se.custom, '{}'::jsonb)                       AS custom,
      p.inactive_reason                                      AS inactive_reason,
      p.inactive_comments                                    AS inactive_comments,
      p.inactive_vinttierror                                 AS inactive_vinttierror,
      se.platform                                            AS platform,
      COALESCE(se.payment, FALSE)                            AS payment,
      se.performance                                         AS performance,
      se.notes                                               AS notes,
      se.exit_type                                           AS exit_type_override,
      se.churn_m3_override                                   AS churn_m3_override,
      CASE
        WHEN NOT COALESCE(p.vigente, FALSE)  THEN 'Inactive'
        WHEN p.start_d >= CURRENT_DATE       THEN 'Onboarding'
        ELSE 'Active'
      END                                                    AS status,
      (p.buyout_d IS NOT NULL AND p.end_d IS NOT NULL
        AND p.buyout_d >= DATE_TRUNC('month', p.end_d))      AS is_buyout,
      (p.end_d IS NOT NULL AND p.start_d IS NOT NULL
        AND p.end_d < (p.start_d + INTERVAL '3 months'))     AS churn_m3_calc
    FROM pairs p
    LEFT JOIN candidates c  ON c.candidate_id  = p.candidate_id
    LEFT JOIN account a     ON a.account_id    = p.account_id
    LEFT JOIN opportunity o ON o.opportunity_id = p.opportunity_id
    LEFT JOIN users u       ON LOWER(u.email_vintti) = LOWER(NULLIF(TRIM(COALESCE(o.opp_hr_lead, '')), ''))
    LEFT JOIN staffing_extra se
           ON se.candidate_id = p.candidate_id AND se.account_id = p.account_id
    LEFT JOIN LATERAL (
      SELECT e.proveedor
      FROM equipments e
      WHERE e.candidate_id = p.candidate_id
      ORDER BY (e.account_id = p.account_id) DESC, e.equipment_id DESC
      LIMIT 1
    ) eq ON TRUE
"""

ORPHANS_SQL = """
    SELECT
      NULL::text            AS candidate_id,
      NULL::text            AS account_id,
      NULL::text            AS hire_opp_id,
      NULL::text            AS opportunity_id,
      se.candidate_name     AS candidate_name,
      NULL::text            AS mail,
      NULL::text            AS country,
      COALESCE(se.client_name, '') AS client_name,
      NULL::text            AS position_name,
      NULL::text            AS recruiter,
      NULL::text            AS hr_lead_email,
      NULL::text            AS start_date,
      NULL::text            AS end_date,
      NULL::text            AS churn_date,
      NULL::text            AS buyout_month,
      0::numeric(12,2)      AS salary,
      0::bigint             AS fee,
      0::numeric(12,2)      AS client_payment,
      NULL::text            AS computer,
      se.provider           AS provider,
      FALSE                 AS provider_locked,
      COALESCE(se.custom, '{}'::jsonb) AS custom,
      NULL::text            AS inactive_reason,
      NULL::text            AS inactive_comments,
      NULL::text            AS inactive_vinttierror,
      se.platform           AS platform,
      COALESCE(se.payment, FALSE) AS payment,
      se.performance        AS performance,
      se.notes              AS notes,
      se.exit_type          AS exit_type_override,
      se.churn_m3_override  AS churn_m3_override,
      NULL::text            AS status,
      FALSE                 AS is_buyout,
      FALSE                 AS churn_m3_calc
    FROM staffing_extra se
    WHERE se.candidate_id IS NULL
"""


def _shape_row(raw: dict) -> dict:
    """Normaliza una fila cruda a la forma que consume el front."""
    row = dict(raw)
    row["orphan"] = row.get("candidate_id") is None
    if (row.pop("hr_lead_email", None) or "") in FORMER_RECRUITERS:
        row["recruiter"] = None
    row["equipment"] = {"yes": "Yes", "no": "No"}.get((row.pop("computer", None) or ""), None)
    row["vintti_fault"] = _tri_bool(row.pop("inactive_vinttierror", None))
    reason = row.get("inactive_reason")
    override = row.pop("exit_type_override", None)
    if override:
        override = EXIT_TYPE_ALIASES.get(override.strip().lower(), override)
    row["exit_type"] = override or _derive_exit_type(reason)
    # `churn_m3` es el valor que se muestra; `churn_m3_override` se manda aparte para
    # que el drawer pueda distinguir "lo calculó el sistema" de "alguien lo pisó".
    override = row.get("churn_m3_override")
    row["churn_m3"] = override if override is not None else bool(row.pop("churn_m3_calc", False))
    row.pop("churn_m3_calc", None)
    if row["orphan"] and not row.get("status"):
        row["status"] = "Inactive"
    return row


def _fetch_pairs(cur, include_orphans: bool) -> list[dict]:
    sql = f"WITH {HIRES_CTE} {PAIRS_SELECT}"
    if include_orphans:
        sql = f"{sql} UNION ALL {ORPHANS_SQL}"
    cur.execute(sql)
    return [_shape_row(r) for r in cur.fetchall()]


# --------------------------------------------------------------------------- #
# Staffing Database
# --------------------------------------------------------------------------- #
@bp.route("/database", methods=["GET", "OPTIONS"])
def staffing_database():
    if request.method == "OPTIONS":
        return ("", 204)
    if _current_email() not in STAFFING_ALLOWED:
        return _forbidden()

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_schema(cur)
        conn.commit()
        rows = _fetch_pairs(cur, include_orphans=True)
        cur.close()
        rows.sort(key=lambda r: (r.get("candidate_name") or "").lower())
        return jsonify(rows)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        if conn is not None:
            conn.close()


@bp.route("/database.csv", methods=["GET"])
def staffing_database_csv():
    if _current_email() not in STAFFING_ALLOWED:
        return _forbidden()

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_schema(cur)
        conn.commit()
        rows = _fetch_pairs(cur, include_orphans=True)
        cur.execute(
            """
            SELECT column_id, label, type FROM staffing_columns
             WHERE tab = 'database' AND archived_at IS NULL
             ORDER BY position, column_id
            """
        )
        custom_cols = cur.fetchall()
        cur.close()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        if conn is not None:
            conn.close()

    rows.sort(key=lambda r: (r.get("candidate_name") or "").lower())
    for row in rows:
        custom = row.get("custom") or {}
        for c in custom_cols:
            value = custom.get(f"c_{c['column_id']}")
            if c["type"] == "checkbox" and value is not None:
                value = "Yes" if value else "No"
            row[f"c_{c['column_id']}"] = value
    cols = [
        ("candidate_name", "Candidate"), ("status", "Status"), ("mail", "Mail"),
        ("performance", "Performance"), ("client_name", "Client"), ("country", "Country"),
        ("start_date", "Starting Date"), ("end_date", "End date"), ("churn_date", "Churn date"),
        ("platform", "Platform"), ("payment", "Payments"),
        ("salary", "Salary"), ("equipment", "Equipment"), ("provider", "Provider"),
        ("recruiter", "Recruiter"), ("notes", "Comments"),
    ] + [(f"c_{c['column_id']}", c["label"]) for c in custom_cols]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in cols])
    for row in rows:
        row["payment"] = "Yes" if row.get("payment") else "No"
        writer.writerow([row.get(key) if row.get(key) is not None else "" for key, _ in cols])

    stamp = date.today().isoformat()
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="staffing-database-{stamp}.csv"'},
    )


# --------------------------------------------------------------------------- #
# Churn — bajas reales (excluye buyouts), con filtro de año
# --------------------------------------------------------------------------- #
@bp.route("/churn", methods=["GET", "OPTIONS"])
def staffing_churn():
    if request.method == "OPTIONS":
        return ("", 204)
    if _current_email() not in STAFFING_ALLOWED:
        return _forbidden()

    year = (request.args.get("year") or "all").strip().lower()

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_schema(cur)
        conn.commit()
        rows = _fetch_pairs(cur, include_orphans=False)
        cur.close()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        if conn is not None:
            conn.close()

    bajas = [
        r for r in rows
        if r.get("end_date") and not r.get("is_buyout") and r["end_date"] <= date.today().isoformat()
    ]
    if year not in ("all", ""):
        bajas = [r for r in bajas if (r.get("end_date") or "")[:4] == year]
    bajas.sort(key=lambda r: r.get("end_date") or "", reverse=True)

    years = sorted({(r.get("end_date") or "")[:4] for r in rows
                    if r.get("end_date") and not r.get("is_buyout")}, reverse=True)
    return jsonify({"rows": bajas, "years": [y for y in years if y]})


# --------------------------------------------------------------------------- #
# Edición de los campos que sólo existían en el Sheet
# --------------------------------------------------------------------------- #
EDITABLE = {"platform", "performance", "provider", "notes", "exit_type", "churn_m3_override", "payment"}


@bp.route("/extra", methods=["PATCH", "OPTIONS"])
def patch_staffing_extra():
    """Upsert de los campos manuales para un par (candidate_id, account_id)."""
    if request.method == "OPTIONS":
        return ("", 204)
    email = _current_email()
    if email not in STAFFING_ALLOWED:
        return _forbidden()

    data = request.get_json(silent=True) or {}
    candidate_id = data.get("candidate_id")
    account_id = data.get("account_id")
    if not candidate_id or not account_id:
        return jsonify({"error": "candidate_id and account_id are required"}), 400

    fields = {k: v for k, v in data.items() if k in EDITABLE}
    if not fields and "custom" not in data:
        return jsonify({"error": "Nothing to update"}), 400

    if "churn_m3_override" in fields:
        fields["churn_m3_override"] = _tri_bool(fields["churn_m3_override"])
    if "payment" in fields:
        # La columna es NOT NULL: vacío o basura cuenta como destildado.
        fields["payment"] = bool(_tri_bool(fields["payment"]))
    for key in ("platform", "performance", "provider", "notes", "exit_type"):
        if key in fields:
            fields[key] = _clean(fields[key])

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_schema(cur)
        conn.commit()

        assignments = [f"{k} = %({k})s" for k in fields]
        insert_cols = list(fields)
        insert_vals = [f"%({k})s" for k in fields]
        params = dict(fields, candidate_id=candidate_id, account_id=account_id, email=email)
        if "custom" in data:
            # Database y Churn comparten la fila de staffing_extra del par.
            to_set, to_del = _custom_patch(cur, data["custom"], ("database", "churn"))
            params.update(custom_set=Json(to_set), custom_del=to_del)
            assignments.append(CUSTOM_MERGE_SQL)
            insert_cols.append("custom")
            insert_vals.append("%(custom_set)s::jsonb")

        cur.execute(
            f"""
            UPDATE staffing_extra
               SET {", ".join(assignments)}, updated_by = %(email)s, updated_at = NOW()
             WHERE candidate_id = %(candidate_id)s AND account_id = %(account_id)s
            RETURNING staffing_extra_id
            """,
            params,
        )
        if cur.fetchone() is None:
            cur.execute(
                f"""
                INSERT INTO staffing_extra (candidate_id, account_id, {", ".join(insert_cols)}, updated_by)
                VALUES (%(candidate_id)s, %(account_id)s, {", ".join(insert_vals)}, %(email)s)
                """,
                params,
            )
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    except _BadValue as exc:
        if conn is not None:
            conn.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        return jsonify({"error": str(exc)}), 500
    finally:
        if conn is not None:
            conn.close()


@bp.route("/extra/payment", methods=["PATCH", "OPTIONS"])
def patch_staffing_payment_bulk():
    """Tilda o destilda "Payments" en muchos pares de una vez (Check all / Uncheck all).

    El front manda sólo las filas visibles, así que respeta el buscador y los filtros.
    Un solo INSERT ... ON CONFLICT contra `uq_staffing_extra_pair`: los pares que
    todavía no tienen fila en `staffing_extra` se crean en el mismo statement.
    """
    if request.method == "OPTIONS":
        return ("", 204)
    email = _current_email()
    if email not in STAFFING_ALLOWED:
        return _forbidden()

    data = request.get_json(silent=True) or {}
    pairs = data.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        return jsonify({"error": "pairs is required"}), 400
    try:
        cand_ids = [int(p["candidate_id"]) for p in pairs]
        acct_ids = [int(p["account_id"]) for p in pairs]
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Every pair needs candidate_id and account_id"}), 400
    payment = bool(_tri_bool(data.get("payment")))

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_schema(cur)
        conn.commit()
        cur.execute(
            """
            INSERT INTO staffing_extra (candidate_id, account_id, payment, updated_by)
            SELECT DISTINCT t.candidate_id, t.account_id, %(payment)s, %(email)s
              FROM unnest(%(cands)s::bigint[], %(accts)s::bigint[]) AS t(candidate_id, account_id)
            ON CONFLICT (candidate_id, account_id) WHERE candidate_id IS NOT NULL
            DO UPDATE SET payment = EXCLUDED.payment,
                          updated_by = EXCLUDED.updated_by,
                          updated_at = NOW()
            """,
            {"payment": payment, "email": email, "cands": cand_ids, "accts": acct_ids},
        )
        updated = cur.rowcount
        conn.commit()
        cur.close()
        return jsonify({"ok": True, "updated": updated})
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        return jsonify({"error": str(exc)}), 500
    finally:
        if conn is not None:
            conn.close()


# --------------------------------------------------------------------------- #
# Bonos
# --------------------------------------------------------------------------- #
BONUS_SELECT = """
    SELECT
      br.bonus_request_id::text                                       AS bonus_id,
      br.account_id::text                                             AS account_id,
      COALESCE(a.client_name, '')                                     AS client_name,
      br.candidate_id::text                                           AS candidate_id,
      COALESCE(NULLIF(TRIM(COALESCE(c.name, '')), ''),
               NULLIF(TRIM(COALESCE(br.employee_name_manual, '')), ''),
               '')                                                    AS candidate_name,
      COALESCE(br.amount, 0)::numeric                                 AS amount,
      COALESCE(NULLIF(TRIM(COALESCE(br.currency, '')), ''), 'USD')    AS currency,
      COALESCE(br.payout_date::text, br.created_at::date::text)       AS payout_date,
      NULLIF(TRIM(CAST(br.reason AS TEXT)), '')                       AS reason,
      NULLIF(TRIM(CAST(br.bonus_type AS TEXT)), '')                   AS bonus_type,
      NULLIF(TRIM(CAST(br.notes AS TEXT)), '')                        AS notes,
      br.status                                                       AS status,
      br.invoice_status                                               AS invoice_status,
      br.candidate_status                                             AS candidate_status,
      COALESCE(br.custom, '{}'::jsonb)                                AS custom
    FROM bonus_requests br
    LEFT JOIN account a    ON a.account_id    = br.account_id
    LEFT JOIN candidates c ON c.candidate_id  = br.candidate_id
"""


@bp.route("/bonuses", methods=["GET", "POST", "OPTIONS"])
def staffing_bonuses():
    if request.method == "OPTIONS":
        return ("", 204)
    email = _current_email()
    if email not in STAFFING_ALLOWED:
        return _forbidden()

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_schema(cur)
        conn.commit()

        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            # payout_date es NOT NULL en bonus_requests: sin esto el INSERT
            # revienta con un 500 en vez de decir qué falta.
            if not _clean(data.get("payout_date")):
                cur.close()
                return jsonify({"error": "The bonus date is required."}), 400
            if not data.get("account_id"):
                cur.close()
                return jsonify({"error": "The bonus must be linked to an account."}), 400
            custom_set = {}
            if data.get("custom"):
                custom_set, _ = _custom_patch(cur, data["custom"], ("bonos",))
            cur.execute(
                """
                INSERT INTO bonus_requests (
                    account_id, candidate_id, employee_name_manual, currency, amount,
                    payout_date, reason, notes, status,
                    invoice_status, candidate_status, custom, created_at, updated_at
                ) VALUES (
                    %(account_id)s, %(candidate_id)s, %(employee_name_manual)s,
                    %(currency)s, %(amount)s, %(payout_date)s, %(reason)s,
                    %(notes)s, %(status)s, %(invoice_status)s, %(candidate_status)s,
                    %(custom)s::jsonb, NOW(), NOW()
                )
                RETURNING bonus_request_id
                """,
                {
                    "account_id": data.get("account_id") or None,
                    "candidate_id": data.get("candidate_id") or None,
                    "employee_name_manual": _clean(data.get("candidate_name")),
                    "currency": _clean(data.get("currency")) or "USD",
                    "amount": data.get("amount") or 0,
                    "payout_date": _clean(data.get("payout_date")),
                    "reason": _clean(data.get("reason")),
                    "notes": _clean(data.get("notes")),
                    "status": _clean(data.get("status")) or "approved",
                    "invoice_status": _clean(data.get("invoice_status")),
                    "candidate_status": _clean(data.get("candidate_status")),
                    "custom": Json(custom_set),
                },
            )
            new_id = cur.fetchone()["bonus_request_id"]
            conn.commit()
            cur.close()
            return jsonify({"ok": True, "bonus_id": str(new_id)}), 201

        year = (request.args.get("year") or "all").strip().lower()
        cur.execute(BONUS_SELECT + " ORDER BY payout_date DESC NULLS LAST, br.bonus_request_id DESC")
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        for row in rows:
            row["amount"] = float(row["amount"] or 0)
        years = sorted({(r.get("payout_date") or "")[:4] for r in rows if r.get("payout_date")}, reverse=True)
        if year not in ("all", ""):
            rows = [r for r in rows if (r.get("payout_date") or "")[:4] == year]
        return jsonify({"rows": rows, "years": [y for y in years if y]})
    except _BadValue as exc:
        if conn is not None:
            conn.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        return jsonify({"error": str(exc)}), 500
    finally:
        if conn is not None:
            conn.close()


BONUS_EDITABLE = {
    "amount", "payout_date", "reason", "notes",
    "status", "invoice_status", "candidate_status",
}


@bp.route("/bonuses/<int:bonus_id>", methods=["PATCH", "OPTIONS"])
def patch_bonus(bonus_id: int):
    if request.method == "OPTIONS":
        return ("", 204)
    if _current_email() not in STAFFING_ALLOWED:
        return _forbidden()

    data = request.get_json(silent=True) or {}
    fields = {k: v for k, v in data.items() if k in BONUS_EDITABLE}
    if not fields and "custom" not in data:
        return jsonify({"error": "Nothing to update"}), 400
    for key in ("payout_date", "reason", "notes", "status", "invoice_status", "candidate_status"):
        if key in fields:
            fields[key] = _clean(fields[key])

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_schema(cur)
        conn.commit()
        assignments = [f"{k} = %({k})s" for k in fields]
        params = dict(fields, bonus_id=bonus_id)
        if "custom" in data:
            to_set, to_del = _custom_patch(cur, data["custom"], ("bonos",))
            params.update(custom_set=Json(to_set), custom_del=to_del)
            assignments.append(CUSTOM_MERGE_SQL)
        cur.execute(
            f"UPDATE bonus_requests SET {', '.join(assignments)}, updated_at = NOW() "
            "WHERE bonus_request_id = %(bonus_id)s",
            params,
        )
        updated = cur.rowcount
        conn.commit()
        cur.close()
        if not updated:
            return jsonify({"error": "Bonus not found"}), 404
        return jsonify({"ok": True})
    except _BadValue as exc:
        if conn is not None:
            conn.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        return jsonify({"error": str(exc)}), 500
    finally:
        if conn is not None:
            conn.close()


# --------------------------------------------------------------------------- #
# Columnas y opciones: endpoints
# --------------------------------------------------------------------------- #
class _Conflict(ValueError):
    """Choque con otra opción/columna: se devuelve como 409."""


def _with_schema(fn):
    """Corre `fn(cur, email)` en una transacción, con el mismo gate que el resto.

    `fn` devuelve (payload, status). _BadValue -> 400, _Conflict -> 409, y
    cualquier error deshace todo: renombrar una opción y actualizar las filas que
    la tenían tiene que pasar junto o no pasar.
    """
    if request.method == "OPTIONS":
        return ("", 204)
    email = _current_email()
    if email not in STAFFING_ALLOWED:
        return _forbidden()
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_schema(cur)
        conn.commit()
        payload, status = fn(cur, email)
        conn.commit()
        cur.close()
        return jsonify(payload), status
    except _BadValue as exc:
        if conn is not None:
            conn.rollback()
        return jsonify({"error": str(exc)}), 400
    except _Conflict as exc:
        if conn is not None:
            conn.rollback()
        return jsonify({"error": str(exc)}), 409
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        return jsonify({"error": str(exc)}), 500
    finally:
        if conn is not None:
            conn.close()


def _column_out(r) -> dict:
    return {
        "id": r["column_id"], "key": f"c_{r['column_id']}", "tab": r["tab"],
        "label": r["label"], "type": r["type"], "position": r["position"],
        "archived": r["archived_at"] is not None,
    }


def _option_out(r) -> dict:
    return {
        "id": r["option_id"], "tab": r["tab"], "col_key": r["col_key"], "value": r["value"],
        "color": r["color"], "position": r["position"], "locked": r["locked"],
    }


def _clean_label(raw, what="name") -> str:
    txt = _clean(raw)
    if not txt:
        raise _BadValue(f"The {what} cannot be empty.")
    return txt[:80]


def _clean_color(raw) -> str:
    color = (_clean(raw) or "gray").lower()
    if color not in OPTION_COLORS:
        raise _BadValue(f"Unknown color: {color}")
    return color


def _check_select_column(cur, tab, col_key) -> None:
    """Sólo se le cargan opciones a una columna de lista: built-in o custom."""
    if tab not in TABS:
        raise _BadValue("Unknown tab.")
    if (tab, col_key) in BUILTIN_SELECTS:
        return
    if col_key.startswith("c_") and col_key[2:].isdigit():
        cur.execute(
            "SELECT 1 FROM staffing_columns WHERE column_id = %s AND tab = %s AND type = 'select'",
            (int(col_key[2:]), tab),
        )
        if cur.fetchone():
            return
    raise _BadValue("That column does not take a list of options.")


def _insert_option(cur, tab, col_key, value, color, email) -> dict:
    """Agrega una opción. Si había una oculta con el mismo texto, la revive."""
    cur.execute(
        """
        SELECT * FROM staffing_options
         WHERE tab = %s AND col_key = %s AND LOWER(value) = LOWER(%s)
         ORDER BY archived_at IS NULL DESC, option_id DESC
         LIMIT 1
        """,
        (tab, col_key, value),
    )
    found = cur.fetchone()
    if found and found["archived_at"] is None:
        raise _Conflict(f"'{found['value']}' is already an option.")
    cur.execute(
        "SELECT COALESCE(MAX(position), 0) + 1 AS pos FROM staffing_options "
        "WHERE tab = %s AND col_key = %s AND archived_at IS NULL",
        (tab, col_key),
    )
    pos = cur.fetchone()["pos"]
    if found:
        cur.execute(
            """
            UPDATE staffing_options
               SET archived_at = NULL, color = %s, position = %s, updated_by = %s
             WHERE option_id = %s RETURNING *
            """,
            (color, pos, email, found["option_id"]),
        )
    else:
        cur.execute(
            """
            INSERT INTO staffing_options (tab, col_key, value, color, position, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING *
            """,
            (tab, col_key, value, color, pos, email),
        )
    return _option_out(cur.fetchone())


def _custom_table(tab: str) -> str:
    """Dónde viven los valores custom de esa pestaña (constante, nunca del request)."""
    return "bonus_requests" if tab == "bonos" else "staffing_extra"


def _hard_delete(flag) -> bool:
    return str(flag or "").strip().lower() in ("1", "true", "yes")


def _clear_option_rows(cur, tab, col_key, value) -> int:
    """Vacía el valor en las filas que tenían esa opción (para eliminarla de verdad)."""
    params = {"value": value, "key": col_key}
    if (tab, col_key) in BUILTIN_SELECTS:
        table, column = BUILTIN_SELECTS[(tab, col_key)]
        cur.execute(
            f"UPDATE {table} SET {column} = NULL "
            f"WHERE LOWER(TRIM({column})) = LOWER(TRIM(%(value)s))",
            params,
        )
    else:
        cur.execute(
            f"""
            UPDATE {_custom_table(tab)} SET custom = custom - %(key)s
             WHERE LOWER(TRIM(custom->>%(key)s)) = LOWER(TRIM(%(value)s))
            """,
            params,
        )
    return cur.rowcount


def _rename_option_rows(cur, tab, col_key, old, new) -> int:
    """Lleva el renombre a las filas que tenían el valor viejo.

    Tabla y columna salen de BUILTIN_SELECTS (constantes), nunca del request.
    """
    params = {"old": old, "new": new, "key": col_key}
    if (tab, col_key) in BUILTIN_SELECTS:
        table, column = BUILTIN_SELECTS[(tab, col_key)]
        cur.execute(
            f"UPDATE {table} SET {column} = %(new)s "
            f"WHERE LOWER(TRIM({column})) = LOWER(TRIM(%(old)s))",
            params,
        )
    else:
        table = "bonus_requests" if tab == "bonos" else "staffing_extra"
        cur.execute(
            f"""
            UPDATE {table}
               SET custom = jsonb_set(custom, ARRAY[%(key)s], to_jsonb(%(new)s::text))
             WHERE LOWER(TRIM(custom->>%(key)s)) = LOWER(TRIM(%(old)s))
            """,
            params,
        )
    return cur.rowcount


@bp.route("/schema", methods=["GET", "OPTIONS"])
def staffing_schema():
    """Columnas custom (también las ocultas, para poder restaurarlas) + catálogos."""
    def run(cur, _email):
        cur.execute("SELECT * FROM staffing_columns ORDER BY tab, position, column_id")
        columns = [_column_out(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT * FROM staffing_options WHERE archived_at IS NULL ORDER BY position, option_id"
        )
        options: dict = {}
        for r in cur.fetchall():
            options.setdefault(f"{r['tab']}.{r['col_key']}", []).append(_option_out(r))
        return {"columns": columns, "options": options, "colors": list(OPTION_COLORS)}, 200
    return _with_schema(run)


@bp.route("/columns", methods=["POST", "OPTIONS"])
def create_staffing_column():
    def run(cur, email):
        data = request.get_json(silent=True) or {}
        tab = _clean(data.get("tab"))
        if tab not in TABS:
            raise _BadValue("Unknown tab.")
        kind = _clean(data.get("type"))
        if kind not in COLUMN_TYPES:
            raise _BadValue("Unknown column type.")
        label = _clean_label(data.get("label"), "column name")
        cur.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 AS pos FROM staffing_columns WHERE tab = %s",
            (tab,),
        )
        pos = cur.fetchone()["pos"]
        cur.execute(
            """
            INSERT INTO staffing_columns (tab, label, type, position, created_by)
            VALUES (%s, %s, %s, %s, %s) RETURNING *
            """,
            (tab, label, kind, pos, email),
        )
        column = _column_out(cur.fetchone())
        options = []
        if kind == "select":
            seen = set()
            for opt in data.get("options") or []:
                value = _clean(opt.get("value") if isinstance(opt, dict) else opt)
                if not value or value.lower() in seen:
                    continue
                seen.add(value.lower())
                color = _clean_color(opt.get("color") if isinstance(opt, dict) else None)
                options.append(_insert_option(cur, tab, column["key"], value[:80], color, email))
        return {"column": column, "options": options}, 201
    return _with_schema(run)


@bp.route("/columns/<int:column_id>", methods=["PATCH", "DELETE", "OPTIONS"])
def edit_staffing_column(column_id: int):
    """PATCH: label / position / archived. DELETE: la oculta (los valores quedan).

    DELETE ?hard=1 la elimina de verdad: la columna, su catálogo y el valor en cada
    fila, todo en la misma transacción. No tiene vuelta atrás; el front lo confirma.
    """
    def run(cur, _email):
        data = request.get_json(silent=True) or {}
        sets, params = [], {"id": column_id}
        if request.method == "DELETE" and _hard_delete(request.args.get("hard")):
            cur.execute("SELECT * FROM staffing_columns WHERE column_id = %s", (column_id,))
            col = cur.fetchone()
            if not col:
                return {"error": "Column not found"}, 404
            key = f"c_{column_id}"
            cur.execute(
                f"UPDATE {_custom_table(col['tab'])} SET custom = custom - %(key)s "
                "WHERE custom->>%(key)s IS NOT NULL",
                {"key": key},
            )
            cleared = cur.rowcount
            cur.execute("DELETE FROM staffing_options WHERE tab = %s AND col_key = %s", (col["tab"], key))
            cur.execute("DELETE FROM staffing_columns WHERE column_id = %s", (column_id,))
            return {"deleted": True, "cleared_rows": cleared}, 200
        if request.method == "DELETE":
            sets.append("archived_at = COALESCE(archived_at, NOW())")
        else:
            if "label" in data:
                sets.append("label = %(label)s")
                params["label"] = _clean_label(data["label"], "column name")
            if "position" in data:
                sets.append("position = %(position)s")
                params["position"] = int(data["position"])
            if "archived" in data:
                sets.append("archived_at = CASE WHEN %(archived)s THEN COALESCE(archived_at, NOW()) END")
                params["archived"] = bool(data["archived"])
        if not sets:
            raise _BadValue("Nothing to update.")
        cur.execute(
            f"UPDATE staffing_columns SET {', '.join(sets)} WHERE column_id = %(id)s RETURNING *",
            params,
        )
        row = cur.fetchone()
        if not row:
            return {"error": "Column not found"}, 404
        return {"column": _column_out(row)}, 200
    return _with_schema(run)


@bp.route("/options", methods=["POST", "OPTIONS"])
def create_staffing_option():
    def run(cur, email):
        data = request.get_json(silent=True) or {}
        tab = _clean(data.get("tab"))
        col_key = _clean(data.get("col_key")) or ""
        _check_select_column(cur, tab, col_key)
        value = _clean_label(data.get("value"), "option")
        option = _insert_option(cur, tab, col_key, value, _clean_color(data.get("color")), email)
        return {"option": option}, 201
    return _with_schema(run)


@bp.route("/options/<int:option_id>", methods=["PATCH", "DELETE", "OPTIONS"])
def edit_staffing_option(option_id: int):
    """PATCH: value (renombra también las filas) / color / position. DELETE: la oculta.

    Ocultar no toca las filas: el valor sigue ahí y el filtro lo muestra como un
    valor fuera del catálogo, igual que cualquier texto viejo del Sheet.
    DELETE ?hard=1 la elimina y deja vacías las filas que la tenían.
    """
    def run(cur, email):
        data = request.get_json(silent=True) or {}
        cur.execute("SELECT * FROM staffing_options WHERE option_id = %s", (option_id,))
        current = cur.fetchone()
        if not current or current["archived_at"] is not None:
            return {"error": "Option not found"}, 404

        if request.method == "DELETE" and _hard_delete(request.args.get("hard")):
            if current["locked"]:
                raise _BadValue(f"'{current['value']}' is used by the page's totals and cannot be deleted.")
            cleared = _clear_option_rows(cur, current["tab"], current["col_key"], current["value"])
            cur.execute("DELETE FROM staffing_options WHERE option_id = %s", (option_id,))
            return {"deleted": True, "cleared_rows": cleared}, 200

        renamed_rows = 0
        sets, params = ["updated_by = %(email)s"], {"id": option_id, "email": email}
        if request.method == "DELETE":
            if current["locked"]:
                raise _BadValue(f"'{current['value']}' is used by the page's totals and cannot be hidden.")
            sets.append("archived_at = NOW()")
        else:
            if "value" in data:
                value = _clean_label(data["value"], "option")
                if value != current["value"]:
                    if current["locked"]:
                        raise _BadValue(
                            f"'{current['value']}' is used by the page's totals and cannot be renamed."
                        )
                    cur.execute(
                        """
                        SELECT 1 FROM staffing_options
                         WHERE tab = %s AND col_key = %s AND LOWER(value) = LOWER(%s)
                           AND archived_at IS NULL AND option_id <> %s
                        """,
                        (current["tab"], current["col_key"], value, option_id),
                    )
                    if cur.fetchone():
                        raise _Conflict(f"'{value}' is already an option.")
                    sets.append("value = %(value)s")
                    params["value"] = value
                    renamed_rows = _rename_option_rows(
                        cur, current["tab"], current["col_key"], current["value"], value
                    )
            if "color" in data:
                sets.append("color = %(color)s")
                params["color"] = _clean_color(data["color"])
            if "position" in data:
                sets.append("position = %(position)s")
                params["position"] = int(data["position"])
        cur.execute(
            f"UPDATE staffing_options SET {', '.join(sets)} WHERE option_id = %(id)s RETURNING *",
            params,
        )
        return {"option": _option_out(cur.fetchone()), "renamed_rows": renamed_rows}, 200
    return _with_schema(run)
