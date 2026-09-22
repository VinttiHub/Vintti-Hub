"""La descomposicion del NRR, escrita UNA sola vez.

Hasta ahora la card (`nrr_30d_summary` / `nrr_history`) y el drawer
(`nrr_30d_detail` / `nrr_month_detail`) implementaban la metrica por separado, y se
fueron separando: el detalle reimplementaba `hires_full` sin dedup ni `salary_updates`,
clasificaba el recorte con otro vocabulario y filtraba los upsells por sales lead
mientras la card filtraba por cohorte de cuentas. El total del drawer no podia dar el
numero de la card. Aca la metrica se define una vez y los cuatro datasets (por ocho,
contando los del AM) la consumen: la suma del detalle da la card por construccion.

Entrada: tres CTE ya presentes en el WITH, todos con el grano
(candidate_id, account_id, opportunity_id, salary, fee[, am_owned]) que producen
`_mrr_staffing.unit_snapshot()` y `_am_mrr_staffing.am_unit_snapshot()`:

  - `ini` : snapshot al INICIO de la ventana. Es la cohorte y la base del NRR.
  - `fin` : snapshot al CIERRE de la ventana. Sirve para el churn y para el cambio
            de precio de las unidades que sobrevivieron.
  - `ups` : upsells — hires con `opp_close_date` DENTRO de la ventana, valuados al
            cierre. Poblacion: `upsell_population()`.

Salida: el CTE `nrr_rows(componente, candidate_id, account_id, opportunity_id, monto)`.

    NRR = (mrr_inicial + upsells + expansion_precio
           - contraccion - downgrades_recorte - churn_no_recorte) / mrr_inicial

`entradas_m3` queda FUERA del cociente a proposito (decision de la owner): lo que entra
al libro del AM porque vencio el M3 del AE no es expansion del AM, es un traspaso.
"""
from __future__ import annotations


# Un unico criterio de "se fue por recorte del cliente". Antes la card decia
# `layoff|downsizing` y el drawer `recorte`: dos vocabularios sobre el mismo campo de
# texto libre. Esto es el superset de los dos, o sea que no pierde ninguna fila
# respecto de ninguna de las dos versiones anteriores.
RECORTE_RE = "(layoff|downsizing|recorte)"


def upsell_population(win_ini: str, win_fin: str, col: str = "opp_close_d") -> str:
    """Poblacion del snapshot de upsells, para pasar como `where_extra`.

    Se cuentan por `opp_close_date` dentro de la ventana y NO se les exige estar
    activos al cierre (decision de la owner): un hire vendido en la ventana cuenta
    aunque arranque el mes que viene.

    `col` es como se llama esa fecha en el CTE base: `opp_close_d` en `hires_full`
    (NRR global) y `close_d` en `hires` (NRR del AM).
    """
    return (
        f"h.{col} IS NOT NULL"
        f" AND h.{col} > {win_ini} AND h.{col} <= {win_fin}"
    )


def base_label_sql(dexpr: str) -> str:
    """La fecha de la base, en texto corto y en castellano ("23-ago").

    El tile muestra el NRR junto a su base, y esa base es el MRR de hace 30 dias, no el
    de hoy: sin la fecha a la vista se lee como si fuera el GMRR actual y no cuadra con
    el tile de al lado (la owner lo reporto el 2026-09-22 con 237.4K vs 208.1K).
    """
    meses = ("ARRAY['ene','feb','mar','abr','may','jun','jul',"
             "'ago','sep','oct','nov','dic']")
    return (f"TO_CHAR({dexpr}, 'DD') || '-' || "
            f"({meses})[EXTRACT(MONTH FROM {dexpr})::int]")


def _val(alias: str) -> str:
    return f"CASE WHEN %(metric)s = 'Fee' THEN {alias}.fee ELSE ({alias}.salary + {alias}.fee) END"


def decomp_cte(
    ini: str,
    fin: str,
    ups: str,
    hires: str,
    win_ini: str,
    win_fin: str,
    owned: bool = False,
    key: str = "",
    reason_join: str = "",
) -> str:
    """Emite `nrr_cohorte`, `nrr_ups` y `nrr_rows`.

    `hires` es el CTE base (`hires_full` en el NRR global, `hires` en el del AM); se usa
    para recuperar el `inactive_reason` de la baja. `owned=True` restringe todo a lo que
    ya es del AM y habilita `entradas_m3`.

    `key` particiona todo por una columna extra (la serie mensual pasa `"mes"`), y en ese
    caso `reason_join` trae el CTE de meses al LATERAL de la baja para poder acotar
    `end_d` a la ventana de cada mes.
    """
    vi, vf, vu = _val("i"), _val("f"), _val("u")
    # `am_owned` solo se enciende (el reloj de 3 meses avanza, nunca retrocede), asi que
    # si la unidad es del AM al inicio tambien lo es al cierre: alcanza con filtrar `i`.
    owned_ini = " AND i.am_owned" if owned else ""
    owned_ups = " AND u.am_owned" if owned else ""

    # Particion opcional: sin `key` es una sola ventana; con `key` es una por mes.
    k_i = f"i.{key}, " if key else ""
    k_u = f"u.{key}, " if key else ""
    k_f = f"f.{key}, " if key else ""
    k_col = f"{key}, " if key else ""
    j_fi = f" AND f.{key} = i.{key}" if key else ""
    j_ui = f" AND u.{key} = i.{key}" if key else ""
    coh_k = f"i.{key}, " if key else ""
    coh_j = f"c.{key} = u.{key} AND " if key else ""

    entradas_m3 = ""
    if owned:
        entradas_m3 = f"""
          UNION ALL
          -- 6. Entradas por vencimiento del M3 del AE: la unidad ya estaba activa al
          -- inicio pero todavia era del AE, y durante la ventana cumplio los 3 meses.
          -- Suma al MRR del AM pero NO es expansion: va aparte, fuera del cociente.
          SELECT
            'entradas_m3'::text, {k_f}f.candidate_id, f.account_id, f.opportunity_id,
            {vf}::numeric, NULL::numeric, NULL::numeric
          FROM {fin} f
          JOIN {ini} i
            ON i.candidate_id = f.candidate_id AND i.account_id = f.account_id{j_fi}
          WHERE f.am_owned AND NOT i.am_owned"""

    return f"""
        nrr_cohorte AS (
          -- Las cuentas que YA eran clientes al inicio. Un hire en una cuenta nueva es
          -- new business, no expansion, y queda fuera del NRR.
          SELECT DISTINCT {coh_k}i.account_id
          FROM {ini} i
          WHERE i.account_id IS NOT NULL{owned_ini}
        ),
        nrr_ups AS (
          SELECT u.*
          FROM {ups} u
          WHERE EXISTS (
            SELECT 1 FROM nrr_cohorte c
            WHERE {coh_j}c.account_id = u.account_id
          ){owned_ups}
        ),
        nrr_rows AS (
          -- 1. Base: el MRR de la cohorte al inicio de la ventana.
          SELECT
            'mrr_inicial'::text AS componente,
            {k_i}i.candidate_id, i.account_id, i.opportunity_id,
            {vi}::numeric       AS monto,
            NULL::numeric       AS monto_ini,
            NULL::numeric       AS monto_fin
          FROM {ini} i
          WHERE TRUE{owned_ini}

          UNION ALL
          -- 2. Upsells: vacantes cerradas en la ventana sobre cuentas de la cohorte.
          SELECT
            'upsells'::text, {k_u}u.candidate_id, u.account_id, u.opportunity_id,
            {vu}::numeric, NULL::numeric, NULL::numeric
          FROM nrr_ups u

          UNION ALL
          -- 3. Expansion de precio: le subieron salary/fee a alguien que ya estaba.
          -- Se excluyen las unidades ya contadas como upsell: una opp puede tener
          -- `opp_close_date` dentro de la ventana con el hire activo desde antes (close
          -- date cargado tarde, o pisado por el sync de HubSpot) y se contaria dos veces.
          SELECT
            'expansion_precio'::text, {k_i}i.candidate_id, i.account_id, i.opportunity_id,
            ({vf} - {vi})::numeric, {vi}::numeric, {vf}::numeric
          FROM {ini} i
          JOIN {fin} f
            ON f.candidate_id = i.candidate_id AND f.account_id = i.account_id{j_fi}
          WHERE {vf} > {vi}
            AND NOT EXISTS (
              SELECT 1 FROM nrr_ups u
              WHERE u.candidate_id = i.candidate_id
                AND u.account_id = i.account_id{j_ui}
            ){owned_ini}

          UNION ALL
          -- 4. Contraccion: el espejo de la anterior, cuando el precio baja.
          SELECT
            'contraccion'::text, {k_i}i.candidate_id, i.account_id, i.opportunity_id,
            ({vi} - {vf})::numeric, {vi}::numeric, {vf}::numeric
          FROM {ini} i
          JOIN {fin} f
            ON f.candidate_id = i.candidate_id AND f.account_id = i.account_id{j_fi}
          WHERE {vi} > {vf}
            AND NOT EXISTS (
              SELECT 1 FROM nrr_ups u
              WHERE u.candidate_id = i.candidate_id
                AND u.account_id = i.account_id{j_ui}
            ){owned_ini}

          UNION ALL
          -- 5. Se fueron: estaban al inicio y ya no al cierre, valuados a su MRR del
          -- inicio. El split por `inactive_reason` no cambia el NRR (los dos se restan
          -- igual): existe para poder ver cuales vienen de un recorte del cliente.
          SELECT
            CASE WHEN COALESCE(r.reason, '') ~* '{RECORTE_RE}'
                 THEN 'downgrades_recorte' ELSE 'churn_no_recorte' END,
            {k_i}i.candidate_id, i.account_id, i.opportunity_id,
            {vi}::numeric, NULL::numeric, NULL::numeric
          FROM {ini} i
          LEFT JOIN LATERAL (
            SELECT h.inactive_reason AS reason
            FROM {hires} h{reason_join}
            WHERE h.candidate_id = i.candidate_id
              AND h.account_id = i.account_id
              AND h.end_d IS NOT NULL
              AND h.end_d > {win_ini} AND h.end_d <= {win_fin}
            ORDER BY h.end_d DESC LIMIT 1
          ) r ON TRUE
          WHERE NOT EXISTS (
            SELECT 1 FROM {fin} f
            WHERE f.candidate_id = i.candidate_id
              AND f.account_id = i.account_id{j_fi}
          ){owned_ini}{entradas_m3}
        )
    """


# Los componentes que entran al cociente, con su signo.
_POSITIVOS = ("mrr_inicial", "upsells", "expansion_precio")
_NEGATIVOS = ("contraccion", "downgrades_recorte", "churn_no_recorte")


def summary_columns(group: str = "", owned: bool = False) -> str:
    """Las columnas de un dataset de resumen, agregando `nrr_rows`.

    `group` es un prefijo de columnas extra (p.ej. "mes,") para la serie mensual.
    """
    cols = [group] if group else []
    for c in _POSITIVOS + _NEGATIVOS:
        cols.append(
            f"COALESCE(SUM(monto) FILTER (WHERE componente = '{c}'), 0)::float AS {c}"
        )
    # Neto de los cambios de precio, para las cards: en el tile es un solo chip
    # ("salary updates") y el desglose suba/baja queda para el drawer.
    cols.append(
        "(COALESCE(SUM(monto) FILTER (WHERE componente = 'expansion_precio'), 0)"
        " - COALESCE(SUM(monto) FILTER (WHERE componente = 'contraccion'), 0)"
        ")::float AS salary_updates"
    )
    if owned:
        cols.append(
            "COALESCE(SUM(monto) FILTER (WHERE componente = 'entradas_m3'), 0)::float"
            " AS entradas_m3"
        )
    num = " + ".join(
        f"COALESCE(SUM(monto) FILTER (WHERE componente = '{c}'), 0)" for c in _POSITIVOS
    )
    den = "NULLIF(SUM(monto) FILTER (WHERE componente = 'mrr_inicial'), 0)"
    sub = " + ".join(
        f"COALESCE(SUM(monto) FILTER (WHERE componente = '{c}'), 0)" for c in _NEGATIVOS
    )
    cols.append(
        f"ROUND(100.0 * (({num}) - ({sub})) / {den}, 2)::float AS nrr_pct"
    )
    return ",\n          ".join(cols)


MEASURES = [
    {"key": "mrr_inicial", "label": "MRR", "type": "currency"},
    {"key": "upsells", "label": "Upsells", "type": "currency"},
    {"key": "salary_updates", "label": "Salary updates (neto)", "type": "currency"},
    {"key": "expansion_precio", "label": "Subió el precio", "type": "currency"},
    {"key": "contraccion", "label": "Bajó el precio", "type": "currency"},
    {"key": "downgrades_recorte", "label": "Downgrades", "type": "currency"},
    {"key": "churn_no_recorte", "label": "Churn", "type": "currency"},
    {"key": "nrr_pct", "label": "NRR %", "type": "percent"},
]

MEASURES_AM = MEASURES[:-1] + [
    {"key": "entradas_m3", "label": "Entró del AE", "type": "currency"},
    MEASURES[-1],
]
