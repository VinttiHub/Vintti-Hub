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
from psycopg2.extras import RealDictCursor

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
    cur.execute("ALTER TABLE bonus_requests ADD COLUMN IF NOT EXISTS invoice_status TEXT")
    cur.execute("ALTER TABLE bonus_requests ADD COLUMN IF NOT EXISTS candidate_status TEXT")
    _SCHEMA_READY = True


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
      GROUP BY cu.candidate_id, cu.account_id, cu.start_d, cu.end_d, cu.buyout_d, cu.vigente
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
      p.buyout_d::text                                       AS buyout_month,
      COALESCE(p.salary, 0)::bigint                          AS salary,
      COALESCE(p.fee, 0)::bigint                             AS fee,
      (COALESCE(p.salary, 0) + COALESCE(p.fee, 0))::bigint   AS client_payment,
      p.computer                                             AS computer,
      COALESCE(NULLIF(TRIM(COALESCE(eq.proveedor, '')), ''),
               se.provider)                                  AS provider,
      p.inactive_reason                                      AS inactive_reason,
      p.inactive_comments                                    AS inactive_comments,
      p.inactive_vinttierror                                 AS inactive_vinttierror,
      se.platform                                            AS platform,
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
      NULL::text            AS buyout_month,
      0::bigint             AS salary,
      0::bigint             AS fee,
      0::bigint             AS client_payment,
      NULL::text            AS computer,
      se.provider           AS provider,
      NULL::text            AS inactive_reason,
      NULL::text            AS inactive_comments,
      NULL::text            AS inactive_vinttierror,
      se.platform           AS platform,
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
        cur.close()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        if conn is not None:
            conn.close()

    rows.sort(key=lambda r: (r.get("candidate_name") or "").lower())
    cols = [
        ("candidate_name", "Candidate"), ("status", "Status"), ("mail", "Mail"),
        ("performance", "Performance"), ("client_name", "Client"), ("country", "Country"),
        ("start_date", "Starting Date"), ("end_date", "End date"), ("platform", "Platform"),
        ("salary", "Salary"), ("equipment", "Equipment"), ("provider", "Provider"),
        ("recruiter", "Recruiter"), ("notes", "Comments"),
    ]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in cols])
    for row in rows:
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
EDITABLE = {"platform", "performance", "provider", "notes", "exit_type", "churn_m3_override"}


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
    if not fields:
        return jsonify({"error": "Nothing to update"}), 400

    if "churn_m3_override" in fields:
        fields["churn_m3_override"] = _tri_bool(fields["churn_m3_override"])
    for key in ("platform", "performance", "provider", "notes", "exit_type"):
        if key in fields:
            fields[key] = _clean(fields[key])

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_schema(cur)
        conn.commit()

        assignments = ", ".join(f"{k} = %({k})s" for k in fields)
        params = dict(fields, candidate_id=candidate_id, account_id=account_id, email=email)
        cur.execute(
            f"""
            UPDATE staffing_extra
               SET {assignments}, updated_by = %(email)s, updated_at = NOW()
             WHERE candidate_id = %(candidate_id)s AND account_id = %(account_id)s
            RETURNING staffing_extra_id
            """,
            params,
        )
        if cur.fetchone() is None:
            cols = ", ".join(fields)
            placeholders = ", ".join(f"%({k})s" for k in fields)
            cur.execute(
                f"""
                INSERT INTO staffing_extra (candidate_id, account_id, {cols}, updated_by)
                VALUES (%(candidate_id)s, %(account_id)s, {placeholders}, %(email)s)
                """,
                params,
            )
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
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
      br.candidate_status                                             AS candidate_status
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
            cur.execute(
                """
                INSERT INTO bonus_requests (
                    account_id, candidate_id, employee_name_manual, currency, amount,
                    payout_date, reason, notes, status,
                    invoice_status, candidate_status, created_at, updated_at
                ) VALUES (
                    %(account_id)s, %(candidate_id)s, %(employee_name_manual)s,
                    %(currency)s, %(amount)s, %(payout_date)s, %(reason)s,
                    %(notes)s, %(status)s, %(invoice_status)s, %(candidate_status)s,
                    NOW(), NOW()
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
    if not fields:
        return jsonify({"error": "Nothing to update"}), 400
    for key in ("payout_date", "reason", "notes", "status", "invoice_status", "candidate_status"):
        if key in fields:
            fields[key] = _clean(fields[key])

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        _ensure_schema(cur)
        conn.commit()
        assignments = ", ".join(f"{k} = %({k})s" for k in fields)
        cur.execute(
            f"UPDATE bonus_requests SET {assignments}, updated_at = NOW() WHERE bonus_request_id = %(bonus_id)s",
            dict(fields, bonus_id=bonus_id),
        )
        updated = cur.rowcount
        conn.commit()
        cur.close()
        if not updated:
            return jsonify({"error": "Bonus not found"}), 404
        return jsonify({"ok": True})
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        return jsonify({"error": str(exc)}), 500
    finally:
        if conn is not None:
            conn.close()
