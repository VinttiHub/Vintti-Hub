# HubSpot ↔ Hub (oportunidades, push, cuentas, corte)

## Sync HubSpot → Opportunities

`POST /hubspot/sync/opportunities` (en `backend/routes/hubspot_routes.py`) refleja en el hub
el movimiento de los deals de los dos pipelines de HubSpot. Lo dispara
`.github/workflows/hubspot-opportunity-sync.yml` cada 30 min y el botón **Sync HubSpot**
de `docs/opportunities.html`.

| HubSpot | Hub |
|---|---|
| Intro Call → **SQL** | crea o vincula **sólo la cuenta** del CRM y sella `account.sql_date`. No crea la opp (desde 2026-10-05) |
| SQL → **Deep Dive** | crea la opportunity (`Role to hire` → `opp_position_name`, `Model` → `opp_model`, `opp_type='New'`) |
| Deep Dive → **NDA Sent** | `opp_stage = 'NDA Sent'` + los 7 campos de negocio (abajo) |
| NDA Sent → **NDA Signed** | `opp_stage = 'Sourcing'` |
| **Closed Win** | sólo las 5 columnas espejo (abajo). **No mueve el stage** |

El sales lead lo decide el pipeline, no el owner del deal: *Proceso de contratación* →
`mariano@vintti.com`, *Vintti AI Pipeline* → `mia@vintti.com` (`PIPELINE_SALES_LEAD` en
`backend/utils/hubspot_opportunities.py`).

**La invariante que sostiene todo**: una opportunity con `hubspot_deal_id` NULL fue creada a
mano desde el modal y el sync **no la toca nunca**. Todos los UPDATE llevan
`AND NULLIF(hubspot_deal_id,'') IS NOT NULL`.

Tres cosas que no son obvias:

- **No retrocede.** `decide_stage_transition()` compara `HUB_STAGE_RANK`: si el hub ya está en
  Interviewing y HubSpot todavía en NDA Signed, no toca el stage (pero sí las fechas).
  `Closed Lost` y `Stop` están blindados aparte — reabrirlos revertiría
  `stage_before_closed_lost` y sacaría la cuenta de "Inactive Client".
- **No hardcodea stage ids.** `resolve_pipeline_stage_map()` los resuelve por label contra
  `GET /crm/v3/pipelines/deals` (los dos pipelines tienen ids DISTINTOS para el mismo label).
  Si un label no matchea, el stage entra en `unresolved` y **se ignora**: nunca adivina.
  Mirar `GET /hubspot/debug/deal-pipelines` antes de correr nada.
- **Adopta en vez de duplicar.** Si ya hay una opp abierta de esa cuenta con el mismo
  `opp_position_name` normalizado y sin deal atado, le pega el `hubspot_deal_id`.

### El stage SQL crea la cuenta, y su fecha es el ancla del SQL desde el 2026-10-05

HubSpot sumó el 2026-10-05 un stage **SQL** entre Intro Call y Deep Dive, en los dos
pipelines (ids `1451281949` Vintti AI y `1451281950` Proceso de contratación). Los datos
que antes se pedían al pasar a Deep Dive (Role to hire, Model, grabación de la intro call)
ahora se piden ahí, pero ninguno tiene dónde caer hasta que exista la opp: como nunca
estuvieron gateados por stage, entran solos cuando la opp se crea en Deep Dive.

- **SQL → `account_only`.** `_process_hubspot_deal` llama a `_resolve_account_for_deal()`,
  el mismo bloque que usa la creación de opp, **sin exigir Role to hire** y sin adopción ni
  freno de candidatas. En Deep Dive la cuenta ya existe y `_find_existing_account` la encuentra
  primero por `account.hubspot_deal_id`, que se escribió en SQL.
- **`account.sql_date`** sale de "SQL Date (Deal)" (`sql_date_deal`) o, si está vacía, de
  `hs_v2_date_entered_<stage SQL>`. Se sella **una sola vez** (`WHERE sql_date IS NULL`)
  porque la de entrada guarda la ÚLTIMA entrada, y **nunca con una fecha anterior al
  2026-10-05** (`SQL_DATE_CUTOVER` en `utils/hubspot_opportunities.py`). También se sella en
  la rama de opp existente, para un deal que saltó SQL → Deep Dive entre dos corridas.
- **Las 16 cards de SQL del tab Sales anclan en `_sql_anchor.py`**: `sql_meeting_date` si es
  anterior al corte (historia congelada), si no `sql_date`, si no `sql_meeting_date`. Pedido
  de la owner: que no cambie ningún número de antes del corte (verificado: 0 diferencias en
  los 16 datasets). Si cambiás el corte, cambialo en los dos archivos (y en `_mkt_sql_anchor.py`).
- **El tab Marketing usa la misma regla desde el 2026-10-26**, sobre los contactos de HubSpot:
  `_mkt_sql_anchor.py` (`sql_date_of()`) en los 7 datasets `mkt_*` que cuentan SQL. Meeting
  Date & Time anterior al corte → esa; si no, la SQL Date mínima de sus deals; si no, Meeting.
  Desde el corte, un contacto cuyo deal pasó por el stage SQL **cuenta como SQL aunque esté en
  Closed Lost** (decisión de la owner, igual que Sales). Verificado: 0 diferencias antes del
  corte. Alimenta también el OKR O3·KR4 "SQL Marketing" (`mkt_business_metrics`).

### Vincular a mano: la adopción automática casi nunca alcanza

El puesto tiene que coincidir **letra por letra**, y entre los dos sistemas casi nunca
coincide: "Tutor" vs "Computer Science Teacher", "Graphic Designer" vs "Part Time Graphic
Designer", "Pep Talk" vs "Finance Manager" (casos reales del 2026-09-11). Encima
`_adopt_existing_opportunity()` excluye `close win`, y la mitad de las opps que la recruiter
ya había cargado están cerradas. Sin ayuda, el sync crea una duplicada por cada una.

La salida **no** es emparejar por parecido: un rol repetido de la misma cuenta (Criterium-Dudka
tiene dos "Admin Assistant / Bookkeeper") puede ser un deal genuinamente nuevo, y tragarlo
dentro de la opp vieja borra una contratación del funnel. Es **sugerencia + un click**, igual
que los montos de Closed Win:

- En `dry_run`, cada item que diría "se crearía" (y los `ambiguous_position_match`) trae
  `link_candidates`: **todas** las opps de esa cuenta sin deal atado, sin filtro de stage —
  Close Win, Closed Lost y Stop incluidas. Ordenadas por `mismo_deep_dive` y después por
  `hs_opps.position_similarity()`. **Ni la fecha ni el puntaje deciden nada** — no hay umbral
  en ningún lado, sólo ordenan para que la correcta quede arriba y no se caiga del `limit=8`.
- El botón **Simular** de `docs/opportunities.html` pinta el reporte con un `<select>` por fila;
  **Vincular** pega `POST /hubspot/opportunities/<id>/link-deal`, que escribe **sólo** las tres
  columnas `hubspot_*`. El stage y las fechas las sigue decidiendo el sync siguiente vía
  `decide_stage_transition()` — moverlas desde acá saltearía `_unmark_signed_hire_active`.
  `POST .../unlink-deal` deshace un click equivocado.

#### Vincular una opp cerrada la deja cerrada (y es el caso que más se usa)

_Historia (cómo se llegó a esto): ver `.claude/docs/historical-decisions.md` → «Las 9 opps duplicadas (11–14 sep 2026)»._

Atarla no la revive: `decide_stage_transition()` devuelve `hub_stage_is_terminal` y el sync no
le toca el stage. Y es justo lo que se quiere, porque el patrón real es que **el hub tiene
razón y HubSpot quedó atrasado** — Flamingo se cerró en el hub el 16-jun y el deal sigue
parado en NDA Signed de mayo. Atar el deal es lo único que frena al cron de crear una
duplicada por día.

Una sola salvedad: en una opp cerrada las fechas **no se pisan**, sólo se rellenan los NULL.
La fecha de HubSpot ahí es la vieja, y `nda_signature_or_start_date` es ancla de ~10 datasets.

La señal que decide en la práctica es la **fecha de Deep Dive**: en las 9 duplicadas coincidía
día por día o a menos de 5 días, incluso donde el texto no se parecía en nada ("Tax Specialist"
vs "Part Time Senior Tax Professional", parecido 0.34). Se muestra en el `<select>` y ordena,
pero no decide. La limpieza de esas 9 quedó en
`backend/scripts/dedupe_hubspot_opportunities.py` (pares hardcodeados, dry-run por defecto):
**borrar la duplicada sin atarle el deal a la vieja no sirve, el cron la recrea a los 30 min.**

### El cron no crea si hay candidata: lo frena y espera

Un botón "Simular" no alcanzaba: el cron corre **cada 30 minutos** y creaba igual, así que
sólo te salvaba si simulabas en la ventana justa. Por eso el freno está **en el sync**, no en
la UI: si el deal fuera a crear una opp y la cuenta tiene alguna candidata, **no crea** —
devuelve `waiting_for_decision` con las candidatas y no toca nada. Aplica igual en dry run,
porque el reporte tiene que decir lo que va a pasar de verdad.

Las dos salidas, las dos desde el panel:

- **Vincular** con una candidata → `POST /hubspot/opportunities/<id>/link-deal`.
- **"Es nueva, creala"** → `POST /hubspot/deals/<deal_id>/mark-new`, que guarda la decisión en
  `hubspot_deal_decisions` (se autocrea, no hay migración a mano) y deja que el próximo sync la
  cree. `DELETE` sobre la misma ruta deshace la marca. **Sin esta segunda salida el deal queda
  frenado para siempre.**

Sólo se guarda la decisión "es nueva": la contraria ya queda registrada sola en
`opportunity.hubspot_deal_id`.

Cuánto frena en la práctica: de las 6 opps que el cron creó el 2026-09-11, sólo 2 habrían
esperado (las dos que efectivamente había que revisar). Las cuentas nuevas no tienen
candidatas y se crean solas como siempre.

**La cola de frenados es una tabla, no el reporte de la última corrida.** El sync es
incremental: un deal frenado hoy se cae de la ventana apenas pasan 24 h sin que lo toquen en
HubSpot, y desaparecería de todos los reportes siguientes — frenado y olvidado, exactamente
lo que le pasó a Nsync. Por eso cada freno se guarda en `hubspot_deals_waiting` (se autocrea)
y se borra solo cuando el deal se resuelve por cualquier vía: vinculado, marcado como nuevo o
adoptado por el propio sync.

Cómo se entera una persona, porque el cron corre en GitHub Actions y no lo mira nadie:

- **Al abrir `docs/opportunities.html`**, `mostrarDealsFrenados()` pega a
  `GET /hubspot/deals/waiting` (lee la tabla, no toca HubSpot) y pinta el panel con los
  desplegables si hay algo. No corre ningún sync.
- **La columna `candidates` dice QUÉ deals están frenados, no qué opps mostrar.** El
  endpoint recalcula las candidatas en vivo con `_link_candidates()` y descarta el JSON
  guardado, porque esa foto sólo se refresca mientras el deal siga entrando en la ventana
  de 24 h: un deal que nadie toca en HubSpot se cae de la ventana y la foto queda clavada.
  Así el panel llegó a ofrecer #763 como "Interviewing" cuando en el hub ya estaba en
  Closed Lost hacía dos días, y a Heavys le faltaba la única candidata que servía (#656
  Senior Accountant, misma fecha de Deep Dive que el deal). `deal_deep_dive_date` está en
  la tabla justamente para poder marcar "misma fecha" sin volver a pegarle a HubSpot.
  Si el recálculo vuelve vacío el panel igual dibuja **"Es nueva, creala"**: sin botón, ese
  deal quedaría frenado para siempre.
- **Un mail por deal frenado, una sola vez.** Sólo por los que tienen `notified_at IS NULL`,
  reclamados con un `UPDATE ... RETURNING` para que dos corridas solapadas no lo dupliquen. Sin
  frenos nuevos no sale ningún mail: avisar por los que siguen esperando serían 48 mails
  iguales por día. Destinatarios hardcodeados en `RECIPIENTS` de `utils/hubspot_waiting_alert.py`
  (`pgonzales@` + `mariano@`), mismo criterio que el auditor.
- **Sábado y domingo no se avisa** (`alerta_en_pausa()`, hora Argentina vía `today_ar()`). El
  cron corre igual los 7 días, pero un freno sólo se resuelve desde Opportunities: el mail del
  sábado a la madrugada sólo logra que el lunes ya nadie lo lea. **No se pierde: se posterga.**
  El corte va sobre el *claim*, no sobre el envío — reclamar la fila sin mandar el mail
  perdería el aviso para siempre, que es el olvido silencioso que esta tabla existe para
  evitar. Como `notified_at` sigue en NULL, la primera corrida del lunes manda **un solo mail**
  con todo el fin de semana junto (el cuerpo ya es una tabla de N deals). Hora Argentina y no
  UTC: un freno del sábado 21:00 ARG es domingo 00:00 UTC.
- Un `::warning::` en el log del cron, para datar cuándo apareció cada uno.

Para probar el panel sin correr nada: `docs/opportunities.html?hs_deals=<id>,<id>` hace que el
botón **Simular** mire sólo esos deals, salteando la ventana incremental. Lo lee únicamente el
dry run.

Campos que HubSpot pide al pasar a NDA Sent, todos **sólo si la columna del hub está
en NULL** — nunca pisan lo que cargó la recruiter, porque budget y salario se
renegocian dentro del hub:

| HubSpot | Hub | Datasets afectados |
|---|---|---|
| Min/Max Client Budget | `min_budget` / `max_budget` | ninguno |
| Min/Max Candidate Salary | `min_salary` / `max_salary` | ninguno |
| Candidate's Years of Experience | `years_experience` | ninguno |
| Expected Fee | `expected_fee` | Active Pipeline / Pipeline Outbound AE |
| **Expected Revenue** | `expected_revenue` | Active Pipeline / Pipeline CR − Churn / Open opps by industry / Pipeline Outbound AE |
| **Expected Set Up Fee** | `fee` (el "Set Up Fee" de Opportunity Detail) | ninguno |

`opportunity.fee` NO es el fee del MRR: ese sale de `hire_opportunity.fee`, y ningún
dataset lee `o.fee` (cuidado al grepear: `o\.fee` también matchea `ho.fee`).
Ojo que `expected_set_up_fee` y `set_up_fee` son propiedades DISTINTAS de HubSpot
(esperada en NDA Sent vs final en Closed Win) y van a columnas distintas.

#### Los 2 links de grabación

HubSpot los pide en otras dos transiciones, y son **texto libre**, no números:

| HubSpot | Se pide al pasar a | Hub (input de Opportunity Detail) | Datasets |
|---|---|---|---|
| `intro_call_recording` ("Intro Call Recording") | Intro Call → **SQL** (antes del 2026-10-05, → Deep Dive) | `first_meeting_recording` ("First Meeting Recording") | ninguno |
| `deep_dive_recording` ("Deep Dive Recording") | Deep Dive → **NDA Sent** | `deepdive_recording` ("Deep Dive Recording") | ninguno |

Las columnas ya existían en `opportunity` (`varchar` sin límite) — no hubo migración.
Tres cosas que no son obvias:

- **No se gatean por stage.** El cron corre cada 30 min, así que un deal puede saltar
  Deep Dive → NDA Sent entre dos corridas, y el AE puede cargar el link tarde. Atarlos a
  `stage_key` los perdería en silencio, así que entran en cualquier stage donde HubSpot
  los tenga cargados.
- **"Vacío" acá incluye el string vacío**, no sólo NULL: el `blur` del input de
  Opportunity Detail guarda `''` cuando lo dejás en blanco, y había 276 opps con
  `first_meeting_recording = ''`. Por eso van por `_apply_recording_fields()` y no por
  `_apply_business_fields()` (que decide con `is None` y se las habría comido todas), y
  el SQL usa `COALESCE(NULLIF(col,''), %s)`.
- **Se truncan a 120 caracteres en el reporte.** Son campos de texto libre y alguien llegó
  a pegar un transcript de 29 KB en vez de un link; entero reventaría el JSON de
  `/sync/opportunities/last` y el mail.

#### El sello `hubspot_pushed_at` se crea aparte, a propósito

`_ensure_hubspot_opportunity_columns()` se **cortocircuita** si las columnas que ya conocía
están presentes (`_hubspot_opportunity_schema_is_ready`), para no tomar un ACCESS EXCLUSIVE
sobre `opportunity` antes de un loop de minutos. Consecuencia que costó una hora el 2026-09-16:
una columna **nueva** agregada dentro de esa función **no se crea nunca** en un entorno donde el
chequeo ya da True — o sea, en producción. El push escribía bien en HubSpot y después reventaba
con `UndefinedColumn` al sellar, y como el disparo automático nunca levanta, el error se veía
sólo en el campo `hubspot_push` de la respuesta.

Por eso `hubspot_pushed_at` la crea `_ensure_push_columns()`, con su propio flag de proceso y su
propia consulta al catálogo. Cualquier columna nueva que haga falta para el push va ahí, no en
la otra.

### Retrocesos en HubSpot: se detectan, no se actúan

`hs_v2_date_entered_<stage>` guarda la **última** entrada a esa etapa y **no se borra al
salir** (verificado 2026-09-11). Si hay fecha de entrada a una etapa posterior a donde
está parado el deal, es que retrocedió: eso lo detecta
`detect_hubspot_regression()` y sale en el reporte como `hubspot_retrocedio`, en el array
`retrocesos`, en el alert del botón y como `::warning::` del cron.

**El sync no toca ni el stage ni las fechas.** HubSpot no distingue un error de carga
(movieron el deal de más y lo vuelven atrás) de un retroceso real (la reunión se hizo y el
cliente se enfrió): en el primer caso querrías borrar la fecha, en el segundo borrarla
perdería un evento que sí ocurrió y sacaría la opp de las cards del funnel de ese mes.
Decide una persona. Y retroceder el stage por SQL saltearía
`_unmark_signed_hire_active`, dejando una opp atrasada con el hire todavía activo.

Como HubSpot actualiza `entered` en cada re-entrada y el UPDATE del sync deja ganar al
valor de HubSpot, si el deal vuelve a avanzar la fecha nueva pisa sola a la vieja.

### Closed Win: los montos van al hire, y los aplica una persona

HubSpot pide 5 campos al cerrar el deal. Los cinco van a **columnas espejo** de
`opportunity` (`hubspot_setup_fee`, `hubspot_final_fee`, `hubspot_final_salary`,
`hubspot_role_hired`, `hubspot_mkt_collab`) y **ninguna las lee un dataset**.

El sync **no escribe `hire_opportunity` ni `salary_updates`**, aunque ahí es donde viven
esos montos de verdad. Siete razones, todas verificadas:

1. `revenue` es polisémica: Staffing = `salary + fee`, Recruiting = fee one-shot. Y se
   calcula **sólo en el navegador** (`candidate-details.js:441`).
2. Por eso Final Fee va a `fee` si es Staffing y a `revenue` si es Recruiting.
3. Editar Salary/Fee nunca escribe el hire directo: pasa por `salary_updates`, que el MRR
   prefiere sobre `ho.*` (`_mrr_staffing.py:79-95`). Escribir sólo `ho.fee` deja dos
   números distintos para el mismo hire según la card.
4. El Credit Loop pisa `fee`/`revenue` (`utils/credit_loop.py:880-902`).
5. Esos montos liquidan el mail mensual de comisiones AE.
6. `hire_opportunity` tiene filas fantasma del formulario público de referencias.
7. Una opp tiene N hires y los datasets hacen `SUM(ho.fee)`.

Y sobre todo: **HubSpot no tiene identidad de candidato** — `role_hired_deal` es texto
libre. La asociación persona↔plata sólo existe en `opportunity.candidato_contratado`, que
escribe la recruiter al pasar a Signed.

Por eso el flujo es **sugerencia + un click**: `GET /candidates/<id>/hire_opportunity`
(que ya resuelve la opp por `candidato_contratado`) devuelve las columnas espejo, la
solapa Hire las muestra en un panel, y **Aplicar** escribe los valores en los inputs de
siempre y dispara `createSalaryUpdateFromInputs()` / `updateHireField()` — el único camino
que resuelve el branch por modelo, el revenue derivado y el dedupe de `salary_updates`.
`POST /opportunities/<id>/hubspot-hire-applied` sella que ya se aplicó.

### Fechas de stage: las de negocio mandan (desde 2026-10-08)

HubSpot exige al pasar de stage una propiedad de fecha (tipo `date`) que tipea una persona.
Reemplazan a `hs_v2_date_entered_*`, que es cuándo se hizo click:

| HubSpot | Dirección | Hub |
|---|---|---|
| `nda_sent_date_deal` | HubSpot → hub | `nda_sent_date` |
| `nda_signed_date_deal` | HubSpot → hub | `nda_signature_or_start_date` (arranque de Sourcing) |
| `candidate_signed_date_deal` | hub → HubSpot (push) | `opportunity.signed_date` |
| `closed_win_date_deal` | hub → HubSpot (push, sólo al cerrar) | `opp_close_date` |
| `closed_lost_date_deal` | hub → HubSpot (push de Closed Lost) | `opp_close_date` |

- **Entrante** (`_apply_stage_dates()` en `hubspot_routes.py`, alias en
  `BUSINESS_DATE_FIELD_TO_COLUMN`): precedencia **negocio > entrada al stage > inferida**. La de
  negocio pisa el hub **sólo cuando cambia en HubSpot** (foto en `opportunity.hubspot_dates_seen`
  JSONB, mismo patrón que `hubspot_model_seen`; la primera vez cuenta como cambio). Si la
  recruiter la corrige en el hub después, gana el hub y sale `fecha_distinta` en el reporte. En
  una opp cerrada sólo rellena NULL. Un deal sin la propiedad (los anteriores) sigue la regla de
  abajo. `deep_dive_date` no tiene propiedad de negocio. `unlink-deal` borra la foto.
- **La SQL Date queda AFUERA de esta regla** (decisión de la owner, 2026-10-08): `account.sql_date`
  se escribe una sola vez y nunca se pisa, aunque Mariano la corrija en HubSpot. No proponer
  alinearla: la cuenta tiene N deals y «pisa cuando cambia» movería el SQL histórico con cada recompra.
- **`signed_date`** no la pide ningún popup: la sella `update_opportunity_stage` (y el sync si
  mueve a Signed) con `today_ar()` al pasar a Signed. Las opps firmadas antes no la tienen y el
  push lo dice en `omitidos`. Columnas autocreadas en `_ensure_dates_seen_columns()` /
  `_ensure_push_columns()` / `_ensure_opportunity_stage_date_columns()`, aparte por el
  cortocircuito de `_ensure_hubspot_opportunity_columns()`.
- Las 3 que empuja el hub **se pisan siempre** (`PUSH_OVERWRITE`). Al deployar, la huella de las
  opps atadas cambia y el cron las re-empuja una vez: completa `closed_win_date_deal` en las
  Close Win (alguien ya había cargado muchas a mano en HubSpot). Las Closed Lost viejas no se
  re-empujan solas.

Sin fecha de negocio: `hs_v2_date_entered_<stage>` → `deep_dive_date` / `nda_sent_date` /
`nda_signature_or_start_date`. En una opp abierta **gana la más temprana** (`LEAST`): HubSpot
rellena o adelanta la fecha del hub, **nunca la atrasa**. En una cerrada sólo rellena los NULL.
Ojo que `nda_signature_or_start_date` es ancla de ~10 datasets.

_Historia (por qué LEAST): ver `.claude/docs/historical-decisions.md` → «Fechas que «cambiaban solas» (hasta 2026-09-23)»._

Una carga tardía, un retroceso o una prueba en HubSpot siempre producen fechas más nuevas: con
`LEAST` ya no pueden atrasar nada.

**HubSpot no tiene propiedad de fecha para las dos etapas "NDA Sent"** (ids
`1429477933` y `1429487919`, agregadas después que el resto): no existe el
`hs_v2_date_entered_*` correspondiente. Para esas, el sync estampa la fecha en que
detecta el cambio — misma semántica que el `CURRENT_DATE` del hub al mover el stage a
mano — y lo marca como `fechas_inferidas` en el reporte para no hacerlo pasar por dato
de HubSpot. Sólo aplica a la etapa donde el deal está parado: si saltó de Deep Dive a
NDA Signed no se inventa un `nda_sent_date`. Desde el 2026-10-08 no corre si el deal trae `nda_sent_date_deal`.

Efectos que el sync SÍ dispara: `create_stage_todos` y, sólo al crear, el mail interno de
Credit Loop (`HUBSPOT_OPP_SYNC_SEND_EMAILS=false` lo apaga). Los que **nunca** dispara:
`_mark_signed_hire_active`/`_unmark_signed_hire_active` (el `elif` de `update_opportunity_stage`
borra `hire_opportunity.carga_active`), `create_credit_for_close_win` y el mail de cliente
inactivo.

Marca de agua incremental en la tabla `hubspot_sync_state` (no en `app_cache`, que vence y se
borra solo). Sólo avanza si la corrida no tuvo errores ni se cortó por `limit`.
`GET /hubspot/sync/opportunities/last` devuelve el último reporte.

Para verificar ANTES de sincronizar, dos GET que se abren en el navegador y no escriben nada:
`GET /hubspot/debug/deal-pipelines` (qué stage ids resolvió) y
`GET /hubspot/preview/opportunities?limit=10` (de qué propiedad de HubSpot sale cada columna del
hub, con valores reales, más un `resumen_por_campo` que dice cuántos deals tienen cada campo
vacío). El `dry_run` dice *qué va a pasar*; el preview dice *de dónde sale cada dato*.

```bash
curl -X POST .../hubspot/sync/opportunities -d '{"dry_run": true, "limit": 20}'
curl -X POST .../hubspot/sync/opportunities -d '{"deal_ids": ["123"]}'
```

El esquema (columnas `hubspot_*` en `opportunity`, los 2 índices y la tabla
`hubspot_sync_state`) ya está aplicado en RDS — se corrió a mano el 2026-09-11 y no hay
archivo de migración versionado. En un entorno nuevo lo crea igual
`_ensure_hubspot_opportunity_columns()` en la primera corrida del sync.
Env opcionales: `HUBSPOT_OPP_PIPELINE_IDS`, `HUBSPOT_OPP_STAGE_IDS`, `HUBSPOT_OPP_ROLE_PROPERTY`,
`HUBSPOT_OPP_SETUP_FEE_PROPERTY`, `HUBSPOT_OPP_FINAL_FEE_PROPERTY`,
`HUBSPOT_OPP_SYNC_BOOTSTRAP` (default: 24 h atrás — un bootstrap ancho crearía una opp por cada
deal histórico), `HUBSPOT_OPP_SYNC_OVERLAP_MINUTES` (10), `HUBSPOT_OPP_SYNC_SEND_EMAILS` (true).

### El Model sigue a HubSpot sólo cuando HubSpot cambia

`opp_model` sale del `model` del deal ("Model (Deal)"). Hasta el 2026-09-23 se copiaba
**sólo al crear**, así que si el AE lo corregía en HubSpot después el hub no se enteraba.
Tampoco se puede copiar en cada corrida: en Summit Chase (808) y founderfirst (825)
HubSpot dice Staffing desde el Deep Dive y la recruiter lo corrigió a Recruiting en el hub.
Pisarlo desharía esa corrección cada 30 minutos.

Por eso `opportunity.hubspot_model_seen` guarda el **último valor visto en HubSpot**, y
`_apply_model_from_hubspot()` copia al hub **sólo cuando ese valor cambia**:

- Primera vez que se ve un deal (seen NULL = la opp **se acaba de atar**, adoptada por el
  sync o con Vincular): **gana HubSpot** si la opp está abierta; si está cerrada sólo
  `modelo_distinto_cerrada`. Una opp creada a mano desde el modal arranca en Staffing por
  default y ese valor no es una decisión: PGAM #838 (2026-09-23) quedó Staffing con el
  deal en Recruiting. **Excepción: si una persona ya cambió el Model en el hub**
  (`opportunity.opp_model_edited_at`, lo sella `PATCH /opportunities/<id>/fields` vía
  `utils/opp_model_edits.py`), la primera vez sólo toma la foto y reporta
  `modelo_distinto_manual`. `unlink-deal` borra la foto para que un deal nuevo vuelva a
  contar como "primera vez".
- **Opps atadas sin foto**: si alguna quedó con `hubspot_model_seen` NULL,
  `backend/scripts/backfill_hubspot_model_seen.py` (dry-run por defecto) saca la foto sin tocar
  `opp_model`.
_Historia (el caso): ver `.claude/docs/historical-decisions.md` → «808 y 825 pasadas a Staffing (2026-09-24)»._

- HubSpot igual a lo visto: gana el hub, aunque difieran. El desfase sale como
  `modelo_distinto` en el reporte y como `::warning::` del cron: casi siempre es HubSpot
  mal cargado y se arregla del lado de HubSpot (el hub no le manda el Model). Lo que ve
  una persona es el panel **"Model distinto entre el hub y HubSpot"** de
  `docs/opportunities.html` (`mostrarModelosDistintos()`, misma allow-list que los deals
  frenados), que lee `GET /hubspot/opportunities/model-mismatches`: compara **todas** las
  opps abiertas atadas en lote contra HubSpot, no sólo la ventana de 24 h del sync, y
  cachea 10 min en `app_cache` (`?refresh=1` lo saltea).
- HubSpot cambió y la opp está abierta: `modelo_actualizado` en el reporte.
- HubSpot cambió y la opp está cerrada: sólo `modelo_distinto_cerrada`, sin tocarla. El modelo
  decide si el revenue cuenta como Staffing o Recruiting.

La columna la crea `_ensure_model_seen_column()`, **aparte** de
`_ensure_hubspot_opportunity_columns()`, por el mismo cortocircuito de `hubspot_pushed_at`.
El hub **no** le manda el Model a HubSpot: el sync inverso sigue siendo sólo stage + montos.

### La marca Vintti AI la decide el pipeline, no un checkbox

`account.vintti_ai` sale ahora del **pipeline del deal**: si viene de *Vintti AI Pipeline*
(`898243926`), el sync prende la marca. Antes dependía de una propiedad `vintti_ai` que en
HubSpot vive en el **CONTACTO** y que casi nadie tilda — 3 cuentas de 344 —, así que las opps
de Mia aparecían sin la insignia en Opportunities. El pipeline es el mismo dato del que ya
sale `opp_sales_lead = mia@vintti.com`, o sea que era información que el sync ya tenía.

Tres cosas para tener en cuenta:

- **No es sólo la insignia de la tabla**: esa columna decide **qué logo sale en el CV que ve el
  cliente** (`resume-readonly.js`, vía `candidates_routes.py:1206-1250`). Cambiarla es visible
  para afuera.
- **Sólo prende, nunca apaga.** Si un deal se mueve fuera del pipeline de AI, apagar la marca
  cambiaría la marca de CVs ya enviados: eso lo decide una persona. Desde el 2026-10-15 vale
  también para `_link_existing_account_to_hubspot()` / `_insert_or_update_account()` (los usan
  este sync y el botón **Sync HubSpot** del CRM): `vintti_ai = vintti_ai OR %s`, y
  `account_manager` sólo se rellena si está vacío — antes el payload (dueño del deal) le
  devolvía a Mariano una cuenta ganada y reasignada a la AM. El botón del CRM queda manual: las
  SQL desde el corte entran por este cron y anclan en `sql_date`.
- Se aplica en las dos ramas de `_process_hubspot_deal` (opp nueva y opp existente), porque las
  9 opps del pipeline de AI son anteriores al cambio y nunca pasan por la rama de creación de
  cuenta. Ojo que en la rama de opp existente va **después** de `changed = False`, o el reset se
  come la marca.

El fallback del frontend (`workspace.js: matchRecord`, "si no sé si es AI, mirá si el sales lead
es mia@vintti.com") sigue siendo **código muerto**: la columna es `NOT NULL DEFAULT FALSE` y la
query hace `COALESCE(a.vintti_ai, FALSE)`, así que nunca llega un `null` y el fallback no corre
jamás. Se dejó así a propósito: ahora la marca la pone el sync, que es una sola fuente de verdad.

## Sync INVERSO: el hub escribe en HubSpot (Signed y Close Win)

Todo lo de arriba va HubSpot → hub. Las **dos últimas etapas van al revés**: la recruiter mueve
la opp a Signed en el hub, carga el hire en el hub, la pasa a Close Win, y el hub le empuja a
HubSpot el stage y los montos.

Por qué se dio vuelta: de los **33 deals en Closed Win, `set_up_fee`, `final_fee` y
`candidates_final_salary` están cargados en 0** (medido 2026-09-16). Nadie los completa de ese
lado porque la plata vive en el hub. Los dos de texto sí los carga una persona en HubSpot
(`role_hired_deal` 26/33, `mkt_collab` 25/33) — de ahí que la política de pisado sea asimétrica:

| Campo | Hub → HubSpot |
|---|---|
| `candidates_final_salary`, `final_fee`, `set_up_fee` | **el hub pisa siempre** |
| `role_hired_deal` | sólo si HubSpot lo tiene vacío |
| `mkt_collab` | **nunca se manda** — el hub no tiene ese dato |

**`role_hired_deal` es el PUESTO, no la persona.** Los 26 valores cargados dicen "Accounts
Payable", "Fund Accountant", "Operations Manager": ni uno es un nombre propio. Sale de
`opp_position_name`, no de `candidates.name` (HubSpot no tiene identidad de candidato).

`GET /hubspot/push/preview` muestra deal por deal qué se escribiría, **corre con el token de
sólo lectura** y es lo que hay que mirar antes de prender nada. `GET /hubspot/push/scope` dice
si el token puede escribir. `POST /hubspot/push/opportunity/<id>` (con `dry_run`) empuja una.

Cinco cosas que no son obvias:

- **Necesita el scope `crm.objects.deals.write`**, que se agrega a mano desde la UI de HubSpot
  (app privada **36896335**, portal **23778741**) con una cuenta Super Admin. Sin él, HubSpot
  devuelve 403 y no se escribe nada. `HubSpotClient.update_deal()` es **el único write del repo**
  hacia HubSpot; todo lo demás lee.
- **Apagado por defecto** (`HUBSPOT_PUSH_ENABLED`, con **D** al final). Mover un deal a Closed
  Win puede disparar workflows y notificaciones que ve todo ventas: no es algo que deba
  encenderse al deployar. El 2026-09-18 la env en App Runner estaba como `HUBSPOT_PUSH_ENABLE`
  y costó una tarde: el botón contestaba "desactivado en este entorno" mientras la consola de
  AWS mostraba la variable en `true`. Por eso `GET /hubspot/push/scope` ahora devuelve
  **`env_sospechosa`**: si el push está apagado y hay una env con el nombre casi igual, la
  nombra. Es lo primero que hay que mirar ante un "pero si la tengo puesta".
- **El disparo va FUERA del `with conn:`** de `update_opportunity_stage`, igual que el mail de
  cliente inactivo, y **nunca levanta**. Adentro, una llamada HTTP de 30s con reintentos dejaría
  la transacción abierta y un error de HubSpot haría rollback de un stage que la persona ya
  movió. Y tiene que leer los montos **después** del commit, porque el Credit Loop pisa
  `ho.fee`/`ho.revenue` (`credit_loop.py:867-902`).
- **No retrocede ni resucita.** `decide_push_stage()` es el espejo de `decide_stage_transition()`:
  si HubSpot ya está igual o más adelante no toca el stage (los montos sí viajan igual), y si el
  deal está en Closed Lost o DQL **no lo toca en absoluto** — moverlo desde ahí lo reabriría.
- **Sólo alcanza a las opps con `hubspot_deal_id`.** Al 2026-09-18 son **15**: de 355 opps en
  Close Win con hire cargado, 14 tienen deal (más 1 en Signed). Las históricas nunca se ataron,
  así que sin vincularlas esto sirve sólo **hacia adelante** — de ahí el buscador de la solapa
  Hire, abajo.

### Vincular desde la vacante: el camino inverso al panel de deals frenados

El panel de `docs/opportunities.html` arranca del **deal** y sólo aparece mientras el sync lo
frena. Para una opp vieja que ya tiene el hire cargado el recorrido es el contrario —tengo la
vacante, me falta el deal— y hasta el 2026-09-18 no existía: el banner de la solapa Hire se
escondía entero cuando no había deal, así que desde afuera parecía que el botón **Enviar a
HubSpot** sólo salía en las opps que había creado el sync. La regla siempre fue *tiene
`hubspot_deal_id`*, que también se cumple en una opp cargada a mano que el sync **adoptó**.

Ahora el banner tiene dos estados y el de "sin deal" ofrece buscar:
`GET /hubspot/opportunities/<id>/deal-candidates?q=` (read-only) →
`POST .../link-deal`, que ya existía.

Tres cosas que no son obvias:

- **Se busca por NOMBRE, no por cuenta.** `account.hubspot_company_id` está cargado en 16 de
  345 cuentas y en **ninguna** de las que hay que arreglar, así que la asociación por company
  no sirve para este caso.
- **Dos pasadas contra `CONTAINS_TOKEN`, y las dos hacen falta** (medido contra la API):
  el texto entero encuentra `PinPoint Analytics`, pero devuelve **cero** para
  `KTB Services` → `KTBSERVICES LLC` y para `One Shore Media` → `One Core Media`. La segunda
  pasada va token por token con comodín (`KTB*`) y **junta todas**: cortar en el primer token
  que trae algo probaba `Services*` y nunca llegaba a `KTB*`.
- **El input es editable a propósito.** Cuando el deal se llama distinto que la cuenta
  (*One Core* vs *One Shore*) es la única forma de llegar a él. La red de contención es que
  `link-deal` **no valida** que el deal sea de la cuenta de la opp: por eso cada fila muestra
  el nombre del deal en grande, y nunca hay nada preseleccionado.

A diferencia del panel de Opportunities —gateado a `pgonzales` + `mariano` por
`OPP_HUBSPOT_WAITING_ALLOWED`— este camino **no tiene lista de acceso**: lo usa cualquiera que
cargue un hire, que es el punto de sacar el cuello de botella. Por eso el estado "vinculada"
muestra el deal id y tiene **Desvincular** al lado de Enviar.

**`unlink-deal` borra también `hubspot_push_hash` / `hubspot_pushed_at`, y eso no es
cosmética.** `values_fingerprint()` se calcula SOLO con stage + montos del hub y **no incluye
el deal**: sin limpiar el sello, una opp que se desata y se vuelve a atar a OTRO deal conserva
la huella vieja, el push contesta `sin_cambios` y **no escribe nunca en el deal nuevo**
mientras el hub muestra todo en orden.

Los números salen de `utils/hubspot_push_values.py`, que **replica la precedencia de
`_mrr_staffing.py:79-95`** (última fila de `salary_updates` → la primera → `hire_opportunity.*`)
y el branch por modelo de `candidate-details.js:524-526` (Staffing → `fee`; Recruiting →
`revenue`, el fee one-shot). Verificado: las 7 opps reconcilian exacto con el MRR. Si se toca
una, hay que tocar la otra.

**El stage "Signed" de HubSpot no estaba mapeado.** Existe en los dos pipelines (ids
`1437034145` y `1452559430`; desde el 2026-10-08 se llama **"Candidate Signed"** y en Proceso de Contratación el id cambió, era `1436968304`) y hasta el 2026-09-16 no estaba en `STAGE_ALIASES`, así que un deal
parado ahí caía en `unmapped_stage` y el sync entrante lo salteaba entero. No molestaba porque
no lo usaba nadie. Ahora está mapeado; `"signed"` va **después** de `"nda_signed"` en
`STAGE_RESOLUTION_ORDER` porque en la pasada por tokens `{signed} ⊆ {nda, signed}` y el alias
suelto se comería "NDA Signed". Tampoco tiene `hs_v2_date_entered_*` (404 verificado), igual que
las dos etapas "NDA Sent".

El loop entre las dos direcciones está acotado: cuando el hub empuja Closed Win, el sync
entrante lo lee como `closed_won` y `STAGE_KEY_TO_HUB_STAGE["closed_won"] = None`, así que **no
mueve el stage del hub**. Sí vuelve a copiar los 5 espejos con los valores que acabamos de
mandar — circular, pero inofensivo: ningún dataset lee esas columnas.

### Closed Lost también viaja (desde 2026-10-07)

Pasar una opp a Closed Lost en el hub cierra el deal como perdido en HubSpot, con lo que pide
el popup del hub: `opp_close_date` → `closedate`, `motive_close_lost` → **SQL (AE) Lost
Reason** (`sql_ae_lost_reason`; el de MQL no, porque en el hub la opp existe recién desde Deep
Dive), `details_close_lost` → **Lost Reason Detail (Deal)**. Va por `build_closed_lost_payload()`
y `_push_closed_lost()`, aparte del camino de Signed/CW (no hay hire ni montos).

- **Timing se manda como `Bad Timing`**: es el *value* interno del select; HubSpot rechaza el
  label. Lo mismo con la competencia (desde 2026-10-08 HubSpot tiene las dos): Internal
  Competition → value `Competitor` (el value viejo quedó con ese label), External
  Competition → `External Competition`. El detalle viaja tal cual, sin prefijo.
- Motivo y detalle **sólo si HubSpot los tiene vacíos**; `closedate` se pisa.
- Sólo mueve desde un stage abierto conocido. Deal en Closed Won o en uno que no seguimos (DQL)
  → no toca nada. Ya en Closed Lost → sólo rellena motivo/detalle.
- **`closed_lost` NO es un stage_key** (no está en `STAGE_ALIASES`): si lo fuera, el sync
  entrante dejaría de saltear esos deals como `unmapped_stage`. El id sale de
  `entry["closed_lost_stage_id"]`, por la marca `isClosed` + probabilidad 0 del stage.
- Viaja **una sola vez, al mover el stage**: el cron `_push_pass()` no lo mira. Las opps que ya
  estaban en Closed Lost antes de esto no se empujan solas (`POST /hubspot/push/opportunity/<id>`).

## Account Details: lápiz + escritura en HubSpot

En `docs/account-details.html` (Account Info) pgonzales, agustin, lara y pilar
(`ACCOUNT_EDITORS`, en `accounts_routes.py` **y** en `account-details.js`) editan cada campo
con ✎. El PATCH va con `?push_hubspot=1` + `X-User-Email` y, después del commit,
`utils/account_hubspot_push.py` escribe el valor en HubSpot. Si no llega, el sync
HubSpot → hub ("HubSpot gana si tiene valor", cada 30 min vía el de opps) lo pisa: por eso
el toast siempre dice qué pasó del lado de HubSpot.

- Se escribe en el objeto del que **lee** el sync (contact → company → deal, el primero con
  la propiedad y con id). Hoy todos los campos caen en el **contacto**. Sin
  `hubspot_contact_id` se busca el contacto por email (exacto, único) y se guarda el id.
- Los desplegables se traducen label → value interno; un valor que HubSpot no acepta no se
  manda (`rechazados`). `GET /accounts/hubspot-options` da las opciones ya normalizadas.
- Necesita el scope **`crm.objects.contacts.write`** (y `companies.write` por si algún campo
  cae en la empresa). Al 2026-10-16 el token sólo tiene `deals.write`: hasta agregarlo, se
  guarda en el hub y el toast dice `sin_scope`.
- `name`, `surname`, `industry`, `position`, `type`, `credit_loop` sólo los puede PATCHear
  un editor. Los demás campos siguen abiertos porque `opportunity-detail` los edita.
- Timezone es sólo del hub; Contract y los totales no tienen lápiz (se recalculan solos).
- **Si HubSpot rechaza el valor, el hub vuelve al anterior** (`revertidos` en la respuesta).
  Pasa con el email: HubSpot valida el formato y **no deja dos contactos con el mismo email**
  (prueba del 2026-10-16 en la cuenta 333). Guardarlo igual dejaba al hub distinto de HubSpot.

## Corte de HubSpot: el «interruptor» (pendiente, lo pide la owner cuando toque)

Mientras se use HubSpot, conviven dos caminos y cada negocio va por uno solo:
- **Negocio nacido en el Hub** (`prospect_deals.hubspot_deal_id` NULL): ya hace todo desde el Hub
  (`backend/prospecting/deal_to_hub.py`): SQL crea/vincula la cuenta + `account.sql_date`; Deep
  Dive crea la oportunidad (con el freno «esperando decisión»); NDA Sent / NDA Signed empujan la
  opp (NDA Signed → Sourcing, con el Slack de Sourcing); Signed / Close Win / Closed Lost se
  mueven en Opportunities y `deals.reflect()` trae etapa + valores al negocio.
- **Negocio importado de HubSpot** (`hubspot_deal_id` con valor): si una persona lo mueve en el
  Hub, crea cuenta y opp igual que uno nacido acá (desde 2026-11-25), pero **atadas al
  `hubspot_deal_id`**, para que el sync de opps las encuentre en vez de duplicar. Si lo mueven en
  HubSpot, las crea `POST /hubspot/sync/opportunities` y `reflect()` ata el negocio.

Cuando la owner diga **«prendé el interruptor» / «apagamos HubSpot»**, hacer TODO esto junto:
1. `deal_to_hub.HUB_IS_SOURCE = True` (desde 2026-11-25 ya no frena nada en `applies()`: los
   negocios importados ya crean desde el Hub; queda como marca del corte).
2. **Apagar los crons de HubSpot**: `prospecting-hubspot-sync.yml` (empresas, contactos,
   negocios) y `hubspot-opportunity-sync.yml` (deals → opps, y el push del hub). Si queda
   prendido el de opps, crea opps duplicadas de deals que ya no se mueven.
3. **Cron nuevo sin HubSpot** que corra `deals.reflect(cur, values=True)` cada 30 min: hoy esa
   copia (etapa + valores de Signed / Close Win / Closed Lost desde la oportunidad) corre DENTRO
   del sync de negocios de HubSpot; sin él sólo se hace al abrir el tablero (etapa) o el negocio
   (valores). Endpoint propio con `X-Audit-Token`, mismo patrón que los demás crons.
4. `HUBSPOT_PUSH_ENABLED=false` en App Runner (el push de Signed / CW / CL a HubSpot ya no tiene
   destino).
5. **Dashboards que leen HubSpot en vivo** → portarlos a las tablas del Hub (`prospect_contacts`
   para Lead Life / MQL / Meeting Date; `prospect_deals` para SQL Date y etapas):
   `_sql_hubspot.py`, `_mkt_sql_anchor.py`, `mkt_*`, `sales_funnel_*`, `sales_mql_to_sql_30d`,
   `sql_to_cw_ae_am_cierre`. Sin esto dejan de ver los datos nuevos (no fallan: se congelan).
   Es el paso más grande; conviene hacerlo ANTES de apagar.
6. Los workflows de Prospecting que dependían de cambios que llegaban de HubSpot pasan a
   dispararse sólo por cambios en el Hub (no hay que tocar nada, sólo avisarle a la owner).

Pendiente de decisión (2026-11-04): en `deals.HUB_TO_DEAL_STAGE`, una opp en **Stop** manda el
negocio a Closed Lost. Probablemente no corresponde (Stop es pausa) y explica parte de la
diferencia de Closed Lost entre el Hub (328) y HubSpot (267); la otra parte son opps Closed Lost
anteriores al 2026-10-07 que nunca se empujaron a HubSpot (ahí el Hub tiene razón). Preguntar
antes de cambiarlo.
