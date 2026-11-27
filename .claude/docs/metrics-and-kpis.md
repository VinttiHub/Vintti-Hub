# Métricas y KPIs (dashboard)

> El ancla del SQL en Sales/Marketing (`_sql_anchor.py`, `_mkt_sql_anchor.py`) está en
> `hubspot.md`, sección «El stage SQL crea la cuenta».

## Dashboard metrics audit

`backend/dashboards/audit/` recalcula cada número que muestra `docs/dashboard.html` y
verifica invariantes que antes sólo se detectaban a ojo. Corre los lunes vía
`.github/workflows/weekly-dashboard-audit.yml` → `POST /dashboards/audit/run` (202 +
hilo; la corrida tarda ~6 min y gunicorn corta a los 300s) → mail con los hallazgos.

```bash
cd backend
python -m dashboards.audit                      # en seco: no escribe ni manda mail
python -m dashboards.audit --tab sales          # una pestaña
python -m dashboards.audit --local-html         # usar docs/ del repo en vez de prod
```

Cómo funciona: `topology.py` parsea el HTML (los 1219 nodos `data-chart` declaran
chart, columna, `data-reduce` y overrides), `reduce.py` es un **port 1:1** de
`reduce()` de `control-dashboard.js:873` — si tocás uno, tocá el otro o el auditor
valida contra una semántica que ya no existe. `runner.py` deduplica a ~316 queries y
las corre **secuencialmente sobre una conexión** (RDS tiene `max_connections=81` y
prod ya usa ~60 en pico).

**Libro de hechos (cruce entre cards distintas)**: las reglas de arriba comparan cada
card con SU drawer, y por eso no vieron que Restor (baja 30-sep) era churn de septiembre
en Client churn y de octubre en el CRR (2026-10-02). `ledger.py` corre cada detalle
etiquetado mes por mes (6 meses) y lo compara contra los hechos que `canon.py` calcula
directo de las tablas base: `hecho_mes_distinto` / `hecho_faltante` / `hecho_sobrante`.
Cada detalle declara una etiqueta `"audit"` en su `DATASET` (hecho, columna del cliente,
qué filas, y qué flags de `canon.FLAGS` **excluye por criterio decidido**: replacement
vivo, buyout, alta y baja en el mismo mes…). Sumar una card al cruce = ponerle la
etiqueta; una familia nueva = una función en `canon.CANON`. Hoy cubre
`cliente_baja` (Client churn + CRR), `contractor_baja` (churn de contractors, motivos de
baja, Churn → Replacement, inactivos de Growth) y `contractor_baja_end` (NRR global/AM, que
fecha la baja por `end_date`); el resto de los
detalles sale como "sin etiqueta". Los hallazgos se agrupan: uno por card y regla, con
los casos adentro.
`python -m dashboards.audit --ledger-only` corre sólo esto en segundos.

Para el triage: `GET /dashboards/audit/last` devuelve cada hallazgo con
`source_file` (el módulo del dataset) y `html_line`, así se va directo al archivo.
Un hallazgo aceptado se silencia con `POST /dashboards/audit/waivers`; se sigue
guardando, sólo no aparece en el mail.

Los destinatarios están **hardcodeados** en `RECIPIENTS`, en `service.py`: hoy
`pgonzales@vintti.com` (owner) y `lara@vintti.com` (AM, agregada 2026-09-04). Sin env
var de por medio, para que una variable mal seteada no pueda redirigir el reporte ni
sumar destinatarios por error. Para tocar la lista hay que editar esa línea, y sólo a
pedido de la owner.

Requiere la migración `backend/sql/20260902_dashboard_audit.sql` corrida a mano y la env
`DASHBOARD_AUDIT_TOKEN` (ya seteada en App Runner y como secret del repo).

## NRR: una sola definición para las 8 cards

El NRR del tab Account Management existe en dos versiones —**global** (todo Staffing) y
**del AM** (sobre `_am_mrr_staffing`, sin los 3 meses posteriores al Close Win de un AE)—
y cada una tiene card de 30d, serie mensual y sus dos drawers. Los ocho leen la misma
descomposición:

```
NRR = (mrr_inicial + upsells + expansion_precio
       − contraccion − downgrades_recorte − churn_no_recorte) / mrr_inicial
```

**Sobre qué se valúa (2026-10-26, pedido de la owner por las métricas del AM):**
- **NRR · AM = MRR** (sólo `fee`). Los 4 `am_nrr_*.py` fijan `METRIC = "Fee"` y **no**
  leen `filters["metric"]`: el filtro Metric del tab Growth viaja en el state global de
  `fetchChart` y si no se fijara le cambiaría la base al AM sin que nadie lo note.
- **NRR global en las dos versiones**: GMRR (salary + fee) y MRR. Mismas chart keys
  (`am_kpi_nrr_30d`, `am_line_nrr`, los dos detalles), la versión la elige
  `data-override-metric="Revenue"` / `"Fee"` en cada elemento (`_val()` de
  `_nrr_decomp.py`: `'Fee'` → fee, cualquier otro → salary + fee). El tile es un split
  GMRR | MRR, hay una card mensual por versión y dos drawers (`am-nrr` = GMRR,
  `am-nrr-mrr` = MRR). **Todo elemento del NRR global tiene que llevar el override**, o
  cae en GMRR por default y además sigue al filtro de Growth.
- `refetchMonthDetails()` pasa `data-override-metric`: sin eso las dos cards mensuales
  mostraban el mismo detalle.

**Está escrita una sola vez, en `backend/dashboards/datasets/_nrr_decomp.py`**
(`decomp_cte()` → el CTE `nrr_rows`, una fila por unidad). Los summary lo agregan con
`SUM(...) FILTER`, los detalles lo listan tal cual: por eso la suma del drawer da el
número de la card **por construcción**. Antes la card y el drawer implementaban la
métrica por separado y se separaron — el detalle no dedupeaba ni leía `salary_updates`,
clasificaba el recorte con otro vocabulario y filtraba los upsells por sales lead
mientras la card filtraba por cohorte de cuentas. Si tocás la fórmula, tocás ese archivo
y listo; no la repliques en un dataset.

Cinco cosas que no son obvias:

- **El upsell NO exige que el hire esté vivo al cierre de la ventana**: se cuenta por
  `opp_close_date` dentro de la ventana, aunque el contractor arranque el mes que viene.
  Es decisión de la owner (2026-09-22). Consecuencia asumida: la identidad
  `MRR(fin) = mrr_inicial + componentes` **no cierra** contra `mrr_history`, así que esa
  reconciliación no sirve como test. Lo que sí tiene que cerrar es card == drawer, y
  card de un mes == punto de ese mes en el chart. `mrr_inicial` del mes M ya **no** es
  el GMRR de Management del cierre de M−1: le faltan las bajas de ese último día (ver
  abajo).
- **Por eso los upsells se valúan con un snapshot sin filtro de actividad**: el
  `where_extra` de `unit_snapshot()` / `am_unit_snapshot()`. Con la cláusula de actividad
  un upsell que todavía no arrancó se valuaría en cero.
  Pero **sí exige `start_d IS NOT NULL`** (gate de contratado, R17): ese `where_extra`
  reemplaza la población por defecto, y en el motor del AM (`hires`) el gate vivía ahí.
  Sin él, el NRR del AM contaba como upsell las filas de referencias de candidatos que
  nunca fueron contratados (2026-11-27: 2–7 por mes, casi todas a $0; jul y ago 2026
  tenían $1.400 y $700 fantasma). Vive en `upsell_population()`.
- **Expansión y contracción excluyen lo ya contado como upsell** (`NOT EXISTS` contra
  `nrr_ups`): una opp puede tener `opp_close_date` dentro de la ventana con el hire
  activo desde antes —close date cargado tarde, o pisado por el sync de HubSpot— y se
  contaría dos veces.
- **En la UI, `expansion_precio` y `contraccion` se llaman "salary updates"** (pedido de
  la owner, 2026-09-22: "expansión/contracción" no se entendía, y en el hub esa acción es
  literalmente editar Salary/Fee en la solapa Hire → una fila en `salary_updates`). Las
  **cards muestran el NETO** en un solo chip, vía el campo calculado `salary_updates`
  (= `expansion_precio − contraccion`, con `data-fmt="delta-currency-k"` que ya pone el
  signo); el desglose ↑/↓ queda para el drawer. Los nombres de columna no cambiaron.
  Ojo que **no** es lo mismo que `downgrades_recorte`: eso es gente que **se fue**, esto
  es la misma gente cobrando distinto.
- **El detalle trae `monto_ini` / `monto_fin`** (cuánto valía y cuánto vale) además del
  `monto`, para que los salary updates se lean "de $1.700 a $800" y no sólo la
  diferencia. Van NULL en los componentes donde no aplica. También trae `close_date` y
  `entra_el`: sin esas fechas, upsells y `entradas_m3` parecen fuera de período, porque
  los dos se rigen por el Close Win y no por el start del contractor.
- **Cada tarjeta del drawer despliega su propio desglose**: es un `.expander` cuyo panel
  lleva la misma `dtable` del detalle filtrada con `data-where-field="componente"` +
  `data-where-value="<componente>"`. No hace falta JS nuevo (`bindExpanders()` engancha
  cualquier `[data-expand-toggle]` y `renderBinding()` ya aplica ese filtro), ni un fetch
  por tarjeta: `hydrate` agrupa por chart y reparte las mismas filas a los seis paneles.
- **Las dos cards de NRR muestran sólo el % y la base** ("sobre $267.8K al 23-ago");
  todo el desglose vive en sus drawers (`am-nrr` y `am-nrr-am`), con las mismas tarjetas
  en los dos. La owner pidió sacarles texto el 2026-09-22: con los seis componentes a la
  vista la card se leía como un párrafo.
- **La sección "GMRR & MRR · AM" es una grilla de 3×2**: los tiles de GMRR, MRR y NRR
  arriba (`s-4` cada uno) y sus tres charts abajo, cada métrica en su columna. Antes el
  NRR iba en una fila propia junto a su chart y quedaba un hueco debajo del tile, porque
  un `skpi-tile` es mucho más bajo que una `card` con chart.
- **`downgrades_recorte` vs `churn_no_recorte` NO cambia el número** (los dos se restan
  igual). Existe sólo para ver cuáles vienen de un recorte del cliente, y se decide con
  `RECORTE_RE` = `layoff|downsizing|recorte`, el superset de los dos vocabularios que
  convivían.
- **La base es el cierre del día ANTERIOR al inicio de la ventana** (`D_INI` es
  `win_ini − 1`), igual que `prev_end` en la serie mensual. Así, al elegir un mes, la
  card de 30d da exactamente el mismo número que el punto de ese mes en el chart.
- **La fecha de baja es el ÚLTIMO día del contractor, y CRR y NRR la tratan igual**
  (2026-10-02): los dos bordes piden `end_d > borde` (`exclude_end_day=True` en
  `unit_snapshot()` / `am_unit_snapshot()` y sus `_monthly`; `end_d >` en los 4
  `crr_*.py`). Antes era `>=`: una baja del 30-sep seguía "activa" ese día, quedaba
  retenida en septiembre y entraba en la base de octubre para perderse en octubre.
  Restor Medical SPA (baja 30-sep) salía como churn de septiembre en Client churn y de
  octubre en el CRR — la AM lo leyó como contarlo dos veces, y tenía razón en el mes.
  Ahora la baja cae en su propio mes, como en Client churn. El default `False` de los
  snapshots queda para GMRR/MRR: no lo cambies ahí.
- **En el NRR la fecha de baja es `end_date`, no `carga_inactive`** (2026-11-02, pedido de
  la owner). Columna `exit_d` = `COALESCE(end_date, carga_inactive)` en `hires_full` y en
  `hires` del AM; los 8 datasets piden `unit_ini`/`unit_fin` con `exit_col='exit_d'` y
  `decomp_cte()` mide las ventanas de la baja con `exit_d`. Tiene que ser en los snapshots y
  no sólo en el componente churn: churn = "en `ini` y no en `fin`", y con fechas mezcladas
  Sergio Cano (end 15-oct, inactive 2-nov) salía churn dos veces y Denise Bianchi (inactive
  30-sep, end 6-oct) ninguna. **GMRR/MRR, Churn de contractors y el canon siguen con
  `carga_inactive`**: una misma baja puede caer en meses distintos en el NRR y en Churn de
  contractors, a propósito. Por eso las etiquetas `audit` del NRR declaran el hecho
  `contractor_baja_end` (`canon.contractor_bajas(use_end_date=True)`), no `contractor_baja`.
  Efecto lateral: si la end_date deja a la cuenta sin nadie al cierre del mes y el reemplazo
  se cierra al mes siguiente (Engenious y Green House, jul/ago-2026), la cuenta no está en la
  cohorte y el reemplazo ya no cuenta como upsell.
- **Un upsell que se va dentro de la misma ventana también resta** (bloque 5b de
  `decomp_cte()`, 2026-11-02): Diana Ortiz (Bravura) entró el 5-oct y se fue el 30-oct, y
  sumaba +$500 de upsell sin restar nada porque el churn sólo mira la base. Ahora suma y
  resta el mismo monto (neto cero) y se ve en el drawer. Por eso el NRR ya no excluye
  `nuevo_en_mes` en el auditor; sí excluye `cuenta_nueva` (new business, fuera de la
  cohorte). Hueco conocido: vendido un mes y arrancado y dado de baja en otro posterior suma
  como upsell y no resta nunca (4 casos, todos de 2025 o antes).
- **Los buyouts se netean, no son churn** (2026-10-05, en los dos NRR). Si una unidad se
  va dentro de la ventana por buyout (`buyout_d >= mes de la baja`, el criterio de Client
  churn y de `canon.py`), sale **de la base y del churn a la vez**: el NRR arranca como si
  no hubiera estado. El cliente pagó el buyout, y de este NRR salen las comisiones del AM —
  Eduardo Salazar (AMPL, buyout 2026-09) le restaba $5K. Va aparte en el componente
  `buyouts`, **fuera del cociente** (CTE `nrr_buyouts` en `_nrr_decomp.py`), con su
  tarjeta en los dos drawers. Consecuencia: `mrr_inicial` del mes M **ya no** es el GMRR
  del cierre de M−1, le faltan justo los `buyouts`. El CRR sigue contando el buyout como
  churn: no se cambió ahí. Las etiquetas `audit` de los 4 detalles excluyen el flag `buyout`.
- **El tile muestra la FECHA de esa base** (campo `base_fecha`, "23-ago"). Desde el
  2026-11-02 rotula el **primer día de la ventana** ("01-oct"), no `D_INI` ("30-sep"): es la
  misma foto (cierre de `D_INI` sin sus bajas = quien sigue al empezar el 1-oct), pero
  "30-sep" se leía como base de septiembre. Sólo cambió el texto; `win_ini` del summary
  sigue devolviendo `D_INI`.
  Sin ella se
  lee como si fuera el MRR de hoy y no cuadra con el tile de al lado: con corte
  22-sep, GMRR · AM daba $237,4K y la base del NRR $208,1K, que era el GMRR · AM del
  23-ago (ejemplo de cuando el NRR · AM era sobre GMRR; desde el 2026-10-26 se compara
  con el tile **MRR · AM**). Es el mismo indicador en dos fechas — el `+14% vs 30d` del propio tile es ese
  salto — pero sin la fecha a la vista parece un error de cálculo (reportado por la
  owner el 2026-09-22).
- **El NRR va con 2 decimales** (`data-fmt="percent2"` en todo `nrr_pct`) y **los 3
  drawers abren con "Cómo se calcula"** (2026-11-02): base + upsells + salary updates ↑ −
  ↓ − downgrades − churn = `quedo`, y `quedo ÷ base = NRR`, en dólares exactos. `quedo`
  es el numerador que arma `summary_columns()`; con el entero, octubre se veía "100%"
  siendo 100,32% y parecía un número clavado. El del AM suma "De acá al período siguiente":
  `quedo + entradas_m3 = pasa_siguiente`, que es la base del período que sigue (sep-2026:
  $61.425 + $6.627 = $68.052 = base de octubre). Sin ese renglón, la base del mes siguiente
  parecía no cuadrar con lo que quedó. No cierra exacto sólo con un upsell sin arrancar, un
  buyout o una cuenta nueva.

En el NRR del AM hay un séptimo componente, **`entradas_m3`**: lo que entró al libro
porque venció el M3 del AE. Va **fuera del cociente** a propósito — es un traspaso, no
algo que hizo el AM. No es marginal: en septiembre de 2026 eran $28.8K contra una base
de $228K (valores en GMRR, de antes de pasar a MRR), así que contarlo como expansión
subía el NRR del AM de 94% a ~107%.

**Upsells del AM en cuentas nuevas** (decisión de la owner, 2026-11-27: «todo lo que lleva
Pilar es upsell»). En el NRR del AM, `nrr_ups` no exige que la cuenta esté en la cohorte:
alcanza `am_owned`, o sea, que la vacante no la haya vendido un AE. El NRR global sigue
excluyendo cuentas nuevas (new business). El caso que lo motivó fue Papaya Tutor
(nov-2026, $2.687 de fee). Es retroactivo: sube todos los meses de la serie en que alguien
que no es AE vendió en una cuenta nueva (jul-2026 Real Books/agustin@, ago-2026 Anderson
Law + Green House/lara@).

## Brand color palette (dashboards)

When coloring dashboard cards/charts (especially the Sales-tab funnel & KPI cards in `docs/dashboard.html` + `docs/assets/css/control-dashboard-retro.css`), use ONLY these 5 brand primaries (each has 100/80/60/40/20% shade steps toward white):

| Color | Hex (100%) | Notes |
|-------|-----------|-------|
| Blue | `#003bff` | |
| Violet | `#6c38ff` | also `--c-violet` |
| **Lime green** | `#c1ff72` | the brand "green" — NOT forest/emerald green. Light: use a dark text color (e.g. `#3a6b00` / `var(--ink)`) on top, since the lime itself is too light to read as text. |
| Cyan / celeste | `#4ba9ff` | also `--c-cyan` |
| Magenta | `#ff1fdb` | also `--c-mag` |

Rules of thumb:
- "Green" ALWAYS means lime `#c1ff72` (use it for arcs/fills/tints; keep big numbers/labels dark for legibility). Do NOT substitute `#2e9b5d`, `#33b277`, etc.
- The funnel gauge cards use one primary each: SQL→Deep Dive=violet, Deep Dive→NDA=lime, NDA→Client Win=cyan, SQL→Client Win=magenta, SQL→Close Win=blue (via `.wr-violet/.wr-lime/.wr-cyan/.wr-magenta/.wr-blue` → `--wr`).
- Monochrome shades are generated with `color-mix(in srgb, var(--wr) N%, #fff)`. 
