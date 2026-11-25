# Prospecting: workflows

> El resto del módulo: `prospecting.md`.

- **Workflows al nivel de HubSpot, armados desde la página** (pestaña *Workflows*). Son filas
  de `prospect_workflows` con un **disparador** (condiciones / evento "se crea" o "cambia una
  propiedad" / horario / manual), un **grafo de pasos** (acciones, esperas, ramas si-no / Y-O /
  % al azar, "ir a" = un `next` que apunta a un paso existente), **desinscripción**, **meta** y
  **días hábiles / franja horaria** (hora AR). `rules.py` valida y traduce las condiciones a SQL
  **sólo con la lista blanca** `FIELDS` / `OPERATORS` de `constants.py`, y además las evalúa en
  Python para ramas y pruebas: **las dos tienen que dar lo mismo** (hay test de paridad; si tocás
  un operador, tocá los dos). Editan **pgonzales, manuela, mia y bahia** (`WORKFLOW_EDITORS`).
- **Los operadores (filtros avanzados + condiciones de workflows) son los del doc de la owner**
  («Hubspot - Hub : NUEVO CRM», 2026-10-28): nombre literal y misma función, en el orden del
  doc (los del tipo → históricos → «Es conocido / Se actualizó…»). Los del hub que el doc no
  tiene (`is_on`, `between` de números, `within_last_days`, `in_next_days`, `is_true/is_false`)
  quedan **al final** con su nombre viejo. «Actualizado en los últimos» de la sección 5 es el
  mismo `changed_in_last_days`: se muestra sólo el nombre de la sección 6. Los «… todos de»
  sólo en `multi`. Las reglas guardadas con la forma vieja (`has_any`, `has_none`, `is_today`,
  `contains` con un texto suelto) las traduce `rules.normalize_rule()` al validar, compilar,
  evaluar y leer: no hay script. «Es» de fechas usa `PERIODS` + `rules.period_bounds()`, uno
  solo para SQL y Python.
- **Motor con estado** (`engine.py`): cada empresa inscripta es una fila de
  `prospect_wf_enrollments` con su paso actual y `wake_at`; el log de cada paso va a
  `prospect_wf_step_log` (pestaña Historial). El disparador por condiciones inscribe sólo en la
  **transición no cumple → cumple** (`prospect_wf_match_state`), que es como reinscribe HubSpot.
  `tick()` corre al instante (PATCH de una empresa y webhook de Clay, acotado a esa empresa), en
  el cron horario `.github/workflows/prospecting-workflows.yml` (**prendido desde el 2026-11-03**) y en
  "Avanzar el reloj" del Test panel (hora simulada, sólo dummies). Tope de 50 pasos por corrida
  contra loops de "ir a". **`tick()` da varias pasadas** (disparadores → acciones, hasta 6 si es
  acotado y 2 en el cron global, corta cuando una pasada no inscribe a nadie): un workflow escribe
  el campo que hace cumplir a otro (23 pone Origin → 27 MQL Source). Con una sola pasada, el
  encadenado esperaba a la próxima edición del registro o al cron (PRUEBA 2 HUB, 2026-11-06).
- **Fin de la fase de prueba (2026-11-03)**: `AUTOMATION_REAL_DATA = True` + cron prendido. Con
  `False` todo lo automático sólo tocaba dummies, y por eso las empresas reales de Clay no
  disparaban el workflow 2: había que inscribirlas a mano. Además, al crear una empresa Clay
  registra **cada campo con valor** como cambio desde vacío (como hacen los contactos y HubSpot):
  sin eso «actualizado hoy» / «cambia una propiedad» nunca veían a una empresa recién llegada.
  Y SIEMPRE, sobre una dummy,
  mail / To-Do van a `TEST_EMAIL` y Slack a `TEST_SLACK_CHANNEL` con `[TEST]`, y el webhook se
  registra sin mandarse: una dummy nunca le escribe a una persona real.
- **Workflows de empresa o de contacto** (`prospect_workflows.object`, fijo al crear).
  `objects.py` le dice a rules/engine qué tabla y cómo leer cada campo (columna o
  `props->>'key'` con cast). Un campo `company.<key>` en un workflow de contacto es la
  **empresa asociada**: se puede poner en condiciones y **editar** (el «Editar la empresa
  asociada» de HubSpot). `contact.<key>` en uno de empresa = «tiene algún contacto que…». La
  paridad SQL↔Python se prueba en los dos objetos y en las cruzadas. La memoria «ya cumplía»
  pasó a `prospect_wf_match (workflow_id, record_id)`.
- Los workflows de la primera versión (`conditions` + `actions`) los convierte
  `workflows.normalize()` al leerlos. `prospect_workflow_enrollments` quedó sin uso.
- **Pruebas**: botón *Test panel* (sólo admin) siembra empresas `is_dummy`, que los BDRs no
  ven, y corre los workflows en dry run o aplicados. `backend/scripts/clay_webhook_simulator.py`
  manda payloads con la forma de Clay.
- Las listas cerradas (status, Not ICP reasons, sizes) viven sólo en `constants.py`.
- **Slack en workflows (2026-11-05)**: `send_slack` acepta `mention_field` (una propiedad `user` /
  `owner`, también `company.<key>`) → `<@ID>` al principio vía `daily_digest.people.slack_id()`,
  puesta **después** de `slack.esc()`; sin ID, el nombre en negrita; sobre un dummy nunca menciona.
  En cualquier texto, `{campo:<clave>}` de una propiedad de persona sale con el **nombre**, no el
  email (`_token_text`). Para el workflow «propiedades incompletas» volvieron al contacto
  `website` («URL del sitio web», también la guarda la llegada de Calendly) y `headcount`
  (opciones de HubSpot), con el mismo `name` que HubSpot para que el sync las traiga.
  **Un Slack que no llega NO corta ni deshace el workflow** (2026-11-24): antes levantaba, el
  `ROLLBACK TO SAVEPOINT` del tick deshacía lo ya hecho en esa corrida (el Lead Life) y la
  inscripción quedaba `failed`. Ahora el paso queda en el historial con `ok=False` y el motivo
  (`engine.slack_error_text()`) y sigue. `channel_not_found` = canal privado sin la app:
  `/invite @VinttiHub` dentro del canal. El canal acepta el id, `#id` o el link
  (`rules.slack_channel_id()`), y el botón **Probar canal** (`POST /prospecting/slack/test-channel`,
  sólo `WORKFLOW_EDITORS`) postea una prueba.
- **Condiciones sobre negocios asociados (2026-11-05)**: en un workflow de contacto o de
  empresa (y en los filtros avanzados), `deal.<key>` = «tiene algún negocio asociado que…»
  (contacto: `prospect_deal_contacts`; empresa: `prospect_deals.company_id`). **Sólo
  condiciones**: no hay acciones ni `{campo:deal.x}`, ni ramas por valor, ni operadores de
  historial. `objects.OBJECTS["deal"]` es destino de cruce, no objeto de workflow
  (`WORKFLOW_OBJECTS`). Campos sintéticos: `stage` = `"<pipeline_key>:<stage_key>"` («Closed
  Win (Proceso De Contratación)») y `pipeline`. Las opciones salen de la base
  (`workflows.deal_condition_options()` → `Ctx.deal_options` y `workflow_schema.deal_fields`);
  en Python, `engine.deals_of()` arma las mismas columnas que la expresión SQL.
- **Acción «Crear registro (negocio)» (`create_deal`, 2026-11-05)**: contactos y empresas.
  `pipeline_key` + `stage_key` (validados contra `Ctx.deal_options["stage"]`), `owner_email`,
  `name` con tokens y `values` opcionales del catálogo de negocios. **Un negocio nuevo del pipeline
  Vintti AI sin propietario queda a nombre de mia** (`create_deal()`, 2026-11-25; nunca pisa uno elegido;
  el insert del sync de HubSpot no pasa por ahí). `engine._create_deal()` →
  `deals.create_deal(check_required=False)` asociado al contacto y a su empresa; un registro dummy
  crea un negocio dummy. **No pasa por `deal_to_hub`** (eso corre al mover de etapa) y **crea uno
  nuevo en cada ejecución** aunque ya haya otro abierto (decisión de la owner, como HubSpot). Para
  el workflow «reunión agendada → negocio» volvieron al contacto `vintti_ai` (bool) y
  `date_of_meeting_scheduled` (date), con el `name` de HubSpot. El workflow #13 del Hub
  («Meeting Scheduled --> Deal created») y el de HubSpot conviven: **el sync de negocios adopta en
  vez de duplicar** (2026-11-24, `hubspot_deals.find_adoptable()`): antes de crear un negocio de
  HubSpot busca uno del Hub sin `hubspot_deal_id`, mismo pipeline, abierto, creado a ≤14 días y con
  un contacto en común (si no, misma empresa), y le pega el id. Sin foto, sólo rellena vacíos y la
  etapa sólo avanza (o pasa a Closed Lost si no hay oportunidad). Hueco: si el de HubSpot llega
  ANTES que el workflow del Hub, quedan dos. Del 6 al 24-nov se habían duplicado 19 (Fuse, Vishram,
  FinCo…): los fusiona `scripts/merge_duplicate_deals.py` (en seco por defecto; queda el que tiene
  opp, si no el más avanzado, si no el de HubSpot; se lleva id, fecha más vieja, vacíos, contactos e
  historial). Re-correrlo sirve también para el hueco.
- **El motor escribe en lote (2026-10-29)**: `engine.BatchCursor` difiere los INSERT/UPDATE/DELETE
  sin RETURNING (y los SAVEPOINT) y los manda pegados a la próxima consulta que necesita
  respuesta, en el mismo orden; RELEASE / ROLLBACK TO mandan todo, así un error cae en el
  savepoint de SU registro. Lo usan `enroll_now()`, `advance()` y la edición masiva. Además:
  `enroll_many()` inscribe N registros en 3 consultas, `enabled_workflows()` lee los activos una
  vez por corrida, `emit_event()` no lee el registro si no hay workflows por evento, y `tick()`
  acepta una lista de empresas (`_company_match()`). Inscribir 25 empresas pasó de 34 s a 9 s
  desde el backend local (cada viaje a la RDS son ~70 ms). Verificado con foto antes/después:
  la base queda idéntica. **Si agregás una escritura cuyo resultado leés (rowcount, fetch),
  ponele RETURNING o leé `rowcount` del BatchCursor (vacía antes)**; un `fetch` no vacía lo
  pendiente a propósito.
- **Carpetas de workflows (2026-11-03)**, anidadas como en HubSpot: tabla `prospect_wf_folders`
  (`parent_id` NULL = raíz) + `prospect_workflows.folder_id`, autocreadas en `ensure_schema()`.
  Lógica en `backend/prospecting/folders.py`; rutas `POST/PATCH/DELETE /prospecting/workflow-folders`
  y `POST /prospecting/workflows/move` (sólo `WORKFLOW_EDITORS`); `GET /workflows` trae `folders`.
  **Borrar una carpeta nunca borra workflows**: su contenido sube a la carpeta de arriba (si una
  subcarpeta choca de nombre, se le agrega el de la borrada). Una carpeta no se puede mover dentro
  de sí misma ni de una descendiente. El workflow nuevo nace en la carpeta abierta (`folder_id` en
  el POST); el PUT del editor **no** toca `folder_id`, así Guardar nunca lo saca de su carpeta. El
  buscador de la lista busca en todas las carpetas y muestra la ruta. **Arrastrar y soltar** (`bindDrag()`): un
  workflow (o todos los tildados, si es uno de ellos) o una carpeta se suelta sobre una carpeta
  o sobre un tramo de la ruta de arriba («Workflows» = sin carpeta); va por las mismas rutas que
  «Mover a…» (`doMoveWorkflows()` / `doMoveFolder()`) y `canDrop()` rechaza la carpeta actual y
  las descendientes.
- **Lienzo con zoom y movimiento libre (2026-11-03)**: el viewport `.pr-wf-canvas` no
  scrollea; `.pr-wf-flow` va con `transform: translate(panX, panY) scale(zoom)` (`applyView()`
  en `prospecting-workflows.js`). Rueda / dos dedos = mover, Ctrl/⌘ + rueda o pinch = zoom en el
  puntero, arrastrar el fondo (mouse o dedo) = mover, barra − / % / + / Ajustar, Ctrl/⌘ + / − / 0.
  **No volver a CSS `zoom`**: con el tamaño mínimo de letra del navegador las tarjetas se
  angostaban y el texto quedaba grande (captura de la owner a 25 %). Pan y zoom sobreviven a los
  redibujos (variables del módulo); el zoom se recuerda por navegador (`pr_wf_zoom`).
- **Duplicar / copiar pasos (2026-11-04)**: cada tarjeta del lienzo tiene una casilla; con
  pasos tildados aparece una barra con **Duplicar** (pega debajo del último tildado),
  **Copiar** y **Copiar a otro workflow…** (abre el destino, del mismo objeto, o uno nuevo).
  El portapapeles va en `localStorage` (`pr_wf_clip`) y se pega con la tarjeta «Pegar» del
  panel de cualquier «+». Todo front (`buildClip()` / `pasteClip()` en
  `prospecting-workflows.js`); el backend valida al Guardar como siempre. Una ramificación
  se copia con todo lo que tiene adentro (`ancestry()`, mismo recorrido que `chain()`) y
  cierra la copia, así que sólo se pega en un «+» final. Los ids se regeneran al pegar; un
  «ir a» hacia afuera de lo copiado sólo se conserva en el mismo workflow. Copia de
  contactos no se pega en uno de empresas.
- «Crear con IA» (prompt → workflow) quedó afuera por decisión de la owner (2026-11-03).
- **Panel «Elegir una acción» (2026-11-03)**, el de HubSpot: el «+» del lienzo ya no abre un
  desplegable, abre un panel en la columna derecha (`pickerPanel()` en
  `prospecting-workflows.js`; en <1100px es un drawer) con buscador, 4 tarjetas (Retraso,
  Ramificación, Ir a workflow = `enroll_workflow`, Ir a acción = «ir a», sólo en el «+» final) y
  las categorías de `ACTION_GROUPS` (`constants.py`). Categoría, descripción y app de cada acción
  salen de `ACTIONS` (`group` / `desc` / `app`; `hidden` = no se ofrece suelta, p. ej.
  `set_today`). Retraso y Ramificación abren una 2ª pantalla con `title` + `example` de
  `DELAYS` / `BRANCHES`. Cuatro acciones nuevas, todas validadas en `rules.check_action()` y
  corridas en `engine.run_action()`: **`format_phone`** (sólo contactos, E.164 con
  `phonenumbers` — dep nueva en los dos requirements; inválido = no toca el valor),
  **`create_contact`** (sólo empresas, vía `store.create_contact()` + evento `created`),
  **`sheets_append`** (Google Sheets por la service account de `utils/sheets_utils.py`; el
  Sheet hay que compartirlo con ella como editor; sobre dummies no escribe) y **`ask_ai`**
  (gpt-4o-mini; guarda en una propiedad de texto o como nota `__note__`; en dry run no llama a
  OpenAI). Los textos admiten además `{campo:<clave>}` (y `{campo:company.<clave>}` desde un
  contacto) en `render_tokens()`.
