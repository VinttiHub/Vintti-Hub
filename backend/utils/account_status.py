"""Estado de cuenta del CRM: Active Client / Inactive Client / Lead in Process / …

ÚNICA implementación en el backend. Espeja `deriveStatusFrom()` de
docs/assets/js/crm.js, que sigue siendo la especificación de referencia: si
cambia una, hay que cambiar la otra (y viceversa).

Lo consumen:
  - routes/metrics_routes.py    → POST /accounts/status/summary (lo que pinta el CRM)
  - routes/candidates_routes.py → mail de aviso cuando una cuenta cae a 'Inactive Client'

Sutilezas que NO son obvias y que hay que respetar al tocar esto:
  - Un hire con buyout mantiene la cuenta en 'Active Client' aunque no tenga
    ningún activo.
  - Una opp en pipeline (sourcing/interviewing/negotiating/deep dive/NDA/signed)
    gana sobre 'Inactive Client': la cuenta pasa a 'Lead in Process'.
  - "Tiene candidatos" se define por `opportunity.candidato_contratado`, NO por
    la existencia de filas en hire_opportunity: hay filas fantasma creadas sólo
    para guardar reference checks que harían ver 'Inactive Client' cuentas que
    en realidad son 'Lead Lost'.
"""
from __future__ import annotations

ACTIVE_CLIENT = 'Active Client'
INACTIVE_CLIENT = 'Inactive Client'
LEAD_IN_PROCESS = 'Lead in Process'
LEAD = 'Lead'
LEAD_LOST = 'Lead Lost'

# Orden de las columnas del SELECT de abajo. Se usa para normalizar la fila,
# porque las rutas que llaman acá usan cursores distintos (tupla vs RealDict).
_FLAG_KEYS = (
    'account_id',
    'has_candidates',
    'any_active',
    'has_buyout',
    'has_opps',
    'has_pipeline',
    'all_lost',
    'contract_staffing',
    'contract_recruiting',
)

_FLAGS_SQL = """
    WITH opps AS (
      SELECT
        account_id,
        COUNT(*)                    AS total_opps,
        COUNT(*) FILTER (WHERE lower(opp_stage) LIKE '%%lost%%') AS lost_opps,
        BOOL_OR(
          lower(opp_stage) LIKE '%%sourc%%'
          OR lower(opp_stage) LIKE '%%interview%%'
          OR lower(opp_stage) LIKE '%%negotiat%%'
          OR lower(opp_stage) LIKE '%%deep%%'
          OR lower(opp_stage) LIKE '%%nda%%'
          OR lower(opp_stage) LIKE '%%signed%%'
        ) AS has_pipeline
      FROM opportunity
      WHERE account_id = ANY(%s)
      GROUP BY account_id
    ),
    -- "Tiene candidatos" se define por opportunity.candidato_contratado, igual
    -- que GET /accounts/<id>/opportunities/candidates, que es de donde el CRM
    -- sacaba el dato al recalcular en el navegador.
    --
    -- Antes esto arrancaba en `JOIN hire_opportunity`, y así contaba hires
    -- fantasma: filas de hire_opportunity que existen sólo para guardar las
    -- reference checks de un candidato (sin start_date ni status) en opps que
    -- después se perdieron. Esas cuentas salían "Inactive Client" cuando en
    -- realidad son "Lead Lost".
    hires AS (
      SELECT
        o.account_id,
        COUNT(*) > 0 AS has_candidates,
        -- Espeja isActiveHire() de crm.js sobre el status derivado:
        -- 'inactive' si hay end_date, 'active' si la opp está en Close Win.
        BOOL_OR(
          h.end_date IS NULL
          AND TRIM(COALESCE(o.opp_stage, '')) = 'Close Win'
        ) AS any_active,
        BOOL_OR(
          (
            h.buyout_dolar IS NOT NULL
            AND NULLIF(TRIM(CAST(h.buyout_dolar AS TEXT)), '') IS NOT NULL
          )
          OR (
            h.buyout_daterange IS NOT NULL
            AND NULLIF(TRIM(CAST(h.buyout_daterange AS TEXT)), '') IS NOT NULL
          )
        ) AS has_buyout,
        -- Tipo de contrato: espeja deriveContractTypeFromCandidates() de
        -- crm.js. Ojo: ahí el buyout SÓLO cuenta para hires activos (está
        -- después del early-return de isActiveHire), a diferencia de has_buyout
        -- de arriba, que mira todas las filas.
        BOOL_OR(
          (h.end_date IS NULL AND TRIM(COALESCE(o.opp_stage, '')) = 'Close Win')
          AND lower(COALESCE(o.opp_model, '')) LIKE '%%staff%%'
        ) AS contract_staffing,
        BOOL_OR(
          (h.end_date IS NULL AND TRIM(COALESCE(o.opp_stage, '')) = 'Close Win')
          AND (
            lower(COALESCE(o.opp_model, '')) LIKE '%%recruit%%'
            OR (
              h.buyout_dolar IS NOT NULL
              AND NULLIF(TRIM(CAST(h.buyout_dolar AS TEXT)), '') IS NOT NULL
            )
            OR (
              h.buyout_daterange IS NOT NULL
              AND NULLIF(TRIM(CAST(h.buyout_daterange AS TEXT)), '') IS NOT NULL
            )
          )
        ) AS contract_recruiting
      FROM opportunity o
      JOIN candidates c ON c.candidate_id = o.candidato_contratado
      LEFT JOIN hire_opportunity h
             ON h.opportunity_id = o.opportunity_id
            AND h.candidate_id   = c.candidate_id
      WHERE o.account_id = ANY(%s)
      GROUP BY o.account_id
    )
    SELECT
      a.account_id,
      COALESCE(hi.has_candidates, FALSE) AS has_candidates,
      COALESCE(hi.any_active, FALSE)     AS any_active,
      COALESCE(hi.has_buyout, FALSE)     AS has_buyout,
      COALESCE(op.total_opps, 0) > 0     AS has_opps,
      COALESCE(op.has_pipeline, FALSE)   AS has_pipeline,
      (COALESCE(op.total_opps,0) > 0 AND COALESCE(op.lost_opps,0) = COALESCE(op.total_opps,0)) AS all_lost,
      COALESCE(hi.contract_staffing, FALSE)   AS contract_staffing,
      COALESCE(hi.contract_recruiting, FALSE) AS contract_recruiting
    FROM account a
    LEFT JOIN opps  op ON op.account_id = a.account_id
    LEFT JOIN hires hi ON hi.account_id = a.account_id
    WHERE a.account_id = ANY(%s)
    ORDER BY a.account_id
"""


def decide(has_candidates, any_active, has_buyout, has_opps, has_pipeline, all_lost):
    """Espeja deriveStatusFrom() de crm.js. Mismo orden de reglas, a propósito."""
    if any_active or has_buyout:
        return ACTIVE_CLIENT
    if has_pipeline:
        return LEAD_IN_PROCESS
    if has_candidates and not any_active:
        return INACTIVE_CLIENT
    if (not has_opps) and (not has_candidates):
        return LEAD
    if all_lost and not has_candidates:
        return LEAD_LOST
    if (not has_opps) and has_candidates:
        return INACTIVE_CLIENT
    return LEAD_IN_PROCESS


def decide_contract(staffing, recruiting):
    """Espeja deriveContractTypeFromCandidates() de crm.js."""
    if staffing and recruiting:
        return 'Mix'
    if staffing:
        return 'Staffing'
    if recruiting:
        return 'Recruiting'
    return None


def account_status_flags(cur, account_ids):
    """{account_id: {has_candidates, any_active, …}} para las cuentas pedidas.

    Tolera cursor de tuplas y RealDictCursor: normaliza contra _FLAG_KEYS.
    """
    ids = []
    for raw in account_ids:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue  # un id basura no puede tumbar el lote entero
    if not ids:
        return {}
    cur.execute(_FLAGS_SQL, (ids, ids, ids))
    out = {}
    for row in cur.fetchall():
        values = (
            [row[key] for key in _FLAG_KEYS]
            if isinstance(row, dict)
            else list(row)
        )
        flags = dict(zip(_FLAG_KEYS, values))
        out[flags['account_id']] = flags
    return out


def derive_account_status(cur, account_id):
    """Estado CRM de UNA cuenta, o None si la cuenta no existe."""
    flags = account_status_flags(cur, [account_id]).get(account_id)
    if not flags:
        return None
    return decide(
        flags['has_candidates'],
        flags['any_active'],
        flags['has_buyout'],
        flags['has_opps'],
        flags['has_pipeline'],
        flags['all_lost'],
    )
