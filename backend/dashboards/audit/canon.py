"""Hechos canonicos: lo que paso de verdad, calculado directo de las tablas base.

El libro (`ledger.py`) compara cada detalle del dashboard contra esto. Sin una
fuente propia, dos datasets que se equivocan igual se darian la razon entre si;
con ella, cada uno se mide contra los hechos y no contra el vecino.

Cada hecho lleva FLAGS: circunstancias que hacen que un dataset, por un criterio
que la owner ya decidio, no lo cuente. El dataset declara en su etiqueta `audit`
cuales excluye. Un flag nunca decide nada solo: sirve para que una diferencia
explicada no salga como hallazgo.

Los hechos usan el nombre del cliente como clave porque es lo unico que traen
todos los detalles (la mayoria no tiene `account_id`).
"""
from __future__ import annotations

from datetime import date


def norm(name) -> str:
    return " ".join(str(name or "").split()).lower()


def month_key(d) -> str:
    if isinstance(d, str):
        return d[:7]
    return f"{d.year:04d}-{d.month:02d}"


# Misma poblacion y mismas fechas que los datasets de clientes (CRR, Client churn):
# Staffing, cuentas no internas, carga_active/carga_inactive mandan sobre start/end.
_HIRES = """
    hires AS (
      SELECT
        ho.account_id,
        ho.candidate_id,
        CASE WHEN NULLIF(TRIM(ho.buyout_daterange::text), '') IS NOT NULL
             THEN TO_DATE(TRIM(ho.buyout_daterange::text) || '-01', 'YYYY-MM-DD') END AS buyout_d,
        CASE WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
             ELSE NULLIF(ho.start_date::text, '')::date END AS start_d,
        CASE WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
             WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
             ELSE ho.end_date::date END AS end_d
      FROM hire_opportunity ho
      JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
      LEFT JOIN account a ON a.account_id = ho.account_id
      WHERE ho.account_id IS NOT NULL
        AND o.opp_model = 'Staffing'
        AND COALESCE(a.vintti_internal, FALSE) = FALSE
        AND (ho.carga_active IS NOT NULL OR NULLIF(ho.start_date::text, '') IS NOT NULL)
    )
"""

# Baja de cliente = el dia en que la cuenta se queda sin ningun hire activo: un
# end_d tal que ningun hire cubre end_d + 1. Es la definicion del evento, sin
# ningun criterio de conteo encima; los criterios van como flags.
_CLIENT_BAJAS_SQL = f"""
    WITH {_HIRES},
    bajas AS (
      SELECT DISTINCT h.account_id, h.end_d AS fecha
      FROM hires h
      WHERE h.end_d IS NOT NULL
        AND h.end_d BETWEEN %(ini)s AND %(fin)s
        AND NOT EXISTS (
          SELECT 1 FROM hires h2
          WHERE h2.account_id = h.account_id
            AND h2.start_d <= h.end_d + 1
            AND (h2.end_d IS NULL OR h2.end_d >= h.end_d + 1)
        )
    )
    SELECT
      a.client_name,
      b.fecha,
      -- Un contractor que se fue ese dia tiene un Replacement vivo: Client churn
      -- no lo cuenta (decision de la owner, 2026-09-23).
      EXISTS (
        SELECT 1
        FROM hires h
        JOIN opportunity ro
          ON ro.account_id = h.account_id
         AND ro.opp_type = 'Replacement'
         AND NULLIF(ro.replacement_of::text, '') = h.candidate_id::text
         AND COALESCE(ro.opp_stage, '') NOT IN ('Closed Lost', 'Stop')
        WHERE h.account_id = b.account_id AND h.end_d = b.fecha
      ) AS replacement_vivo,
      -- No estaba activa el dia anterior al mes: arranco y se fue dentro del mismo
      -- mes. El CRR no la puede contar como perdida porque nunca estuvo en su base.
      NOT EXISTS (
        SELECT 1 FROM hires h
        WHERE h.account_id = b.account_id
          AND h.start_d <= (DATE_TRUNC('month', b.fecha)::date - 1)
          AND (h.end_d IS NULL OR h.end_d >= DATE_TRUNC('month', b.fecha)::date)
      ) AS nuevo_en_mes,
      -- Volvio a tener a alguien activo al cierre del mismo mes: el CRR la ve
      -- retenida, Client churn igual registra la baja (es un evento).
      EXISTS (
        SELECT 1 FROM hires h
        WHERE h.account_id = b.account_id
          AND h.start_d > b.fecha
          AND h.start_d <= (DATE_TRUNC('month', b.fecha) + INTERVAL '1 month - 1 day')::date
          AND (h.end_d IS NULL
               OR h.end_d > (DATE_TRUNC('month', b.fecha) + INTERVAL '1 month - 1 day')::date)
      ) AS volvio_en_mes,
      -- Buyout: el cliente se quedo con el contractor. Mismo criterio que Client
      -- churn (buyout de ese mes o posterior). El CRR lo cuenta como churn
      -- (decision de la owner, 2026-09-23); la card de Client churn sólo el real.
      COALESCE((SELECT MAX(h.buyout_d) FROM hires h WHERE h.account_id = b.account_id)
               >= DATE_TRUNC('month', b.fecha)::date, FALSE) AS buyout
    FROM bajas b
    JOIN account a ON a.account_id = b.account_id
"""

FLAGS = {
    "replacement_vivo": "tiene un Replacement abierto para el contractor que se fue",
    "nuevo_en_mes": "arranco y se fue dentro del mismo mes",
    "volvio_en_mes": "volvio a contratar antes de que cerrara el mes",
    "buyout": "fue un buyout (el cliente se quedo con el contractor)",
    "sigue_en_cuenta": "sigue trabajando para el mismo cliente en otra vacante",
}


def client_bajas(conn, ini: date, fin: date) -> list:
    """Bajas de cliente entre `ini` y `fin`, con sus flags."""
    with conn.cursor() as cur:
        cur.execute(_CLIENT_BAJAS_SQL, {"ini": ini, "fin": fin})
        rows = cur.fetchall()
    out = []
    for name, fecha, repl, nuevo, volvio, buyout in rows:
        flags = {k for k, v in (("replacement_vivo", repl), ("nuevo_en_mes", nuevo),
                                ("volvio_en_mes", volvio), ("buyout", buyout)) if v}
        out.append({
            "fact": "cliente_baja", "entity": norm(name), "label": name,
            "month": month_key(fecha), "date": fecha.isoformat(), "flags": flags,
        })
    return out


# Baja de contractor = cada hire (candidato, cuenta) con end_d. Mismo universo que
# los datasets de churn de contractors: Staffing, cuentas no internas.
_CONTRACTOR_BAJAS_SQL = f"""
    WITH {_HIRES}
    SELECT DISTINCT
      c.name AS candidate_name,
      a.client_name,
      h.end_d,
      -- Buyout: el contractor pasa a ser del cliente.
      COALESCE(h.buyout_d >= DATE_TRUNC('month', h.end_d)::date, FALSE) AS buyout,
      -- Arranco y se fue en el mismo mes: no estaba en ninguna base de inicio.
      h.start_d >= DATE_TRUNC('month', h.end_d)::date AS nuevo_en_mes,
      -- Sigue trabajando para la misma cuenta al dia siguiente (otro hire): la
      -- unidad (candidato, cuenta) no se perdio, sólo cambio de vacante.
      EXISTS (
        SELECT 1 FROM hires h2
        WHERE h2.candidate_id = h.candidate_id AND h2.account_id = h.account_id
          AND h2.start_d <= h.end_d + 1
          AND (h2.end_d IS NULL OR h2.end_d >= h.end_d + 1)
      ) AS sigue_en_cuenta
    FROM hires h
    JOIN candidates c ON c.candidate_id = h.candidate_id
    JOIN account a ON a.account_id = h.account_id
    WHERE h.end_d BETWEEN %(ini)s AND %(fin)s
"""


def contractor_bajas(conn, ini: date, fin: date) -> list:
    """Bajas de contractor entre `ini` y `fin`. Clave: candidato @ cliente."""
    with conn.cursor() as cur:
        cur.execute(_CONTRACTOR_BAJAS_SQL, {"ini": ini, "fin": fin})
        rows = cur.fetchall()
    out = []
    for cand, client, fecha, buyout, nuevo, sigue in rows:
        flags = {k for k, v in (("buyout", buyout), ("nuevo_en_mes", nuevo),
                                ("sigue_en_cuenta", sigue)) if v}
        out.append({
            "fact": "contractor_baja", "entity": entity_key(cand, client),
            "label": f"{cand} ({client})",
            "month": month_key(fecha), "date": fecha.isoformat(), "flags": flags,
        })
    return out


def entity_key(*parts) -> str:
    return " @ ".join(norm(p) for p in parts)


# hecho -> funcion que lo calcula. Una familia nueva del libro agrega su entrada aca.
CANON = {
    "cliente_baja": client_bajas,
    "contractor_baja": contractor_bajas,
}
