# Prospecting (CRM de los BDRs)

> Workflows y motor: `prospecting-workflows.md`. Corte de HubSpot: `hubspot.md`.

## Prospecting: el CRM de los BDRs (Clay → Hub, sin HubSpot)

`docs/prospecting.html` reemplaza a HubSpot para la prospección: Clay manda cada empresa
al Hub, los BDRs la trabajan ahí y los workflows que corría HubSpot viven en el backend.
Es un módulo **aparte** del CRM de clientes (`account`): otras empresas, otro volumen.
Código en `backend/prospecting/` (`constants.py`, `store.py`, `workflows.py`) +
`backend/routes/prospecting_routes.py`. Tablas autocreadas: `prospect_companies`,
`prospect_company_events` (historial por campo), `prospect_workflow_runs`.

**Quién puede qué** (resumen; el detalle y las fechas están en los bullets de abajo, todo en `constants.py`):

| Lista | Quiénes | Para qué |
|---|---|---|
| rol `BDR` (activo) | los BDRs | entrar; editar empresas/contactos; owner sólo en Recycled |
| `ADMIN_EMAILS` | pgonzales, lara | todo |
| `EXTRA_ACCESS_EMAILS` | mariano, justo, ana, agustin | entrar + Negocios, Workflows (lectura), Eliminar |
| `WORKFLOW_EDITORS` | pgonzales, manuela, mia, bahia, lara | editar workflows, Configuración, Test panel |
| `OWNER_MANAGERS` (= `PROPERTY_EDITORS`) | pgonzales, bahia, justo, ana, manuela, lara, mia | cambiar Prospecting Owner siempre; editar Propiedades |

- **Acceso**: `users.role` que contenga `BDR` (activo) **+ pgonzales y lara siempre**
  (`ADMIN_EMAILS`; lara desde el 2026-11-25 con el mismo acceso que la owner: también está en
  `WORKFLOW_EDITORS` y `OWNER_MANAGERS`) **+ `EXTRA_ACCESS_EMAILS`** (mariano, 2026-11-06: maneja los negocios; justo, ana y
  agustin (Morrone), 2026-11-09; no son owners ni ven Configuración). **Negocios y Workflows
  no son para los BDRs** (2026-11-09): sólo admin + `WORKFLOW_EDITORS` + `EXTRA_ACCESS_EMAILS`
  (`_is_staff()` en `prospecting_routes.py`, `_gate(cur, staff=True)` en las rutas `/deals*` y
  de lectura de workflows; `/me` → `can_see_deals` / `can_see_workflows`). La ficha de empresa
  y de contacto les llega con `deals` e `enrollments` vacíos. Paneles los siguen viendo. El sidebar no tiene Set hardcodeado: pregunta a `GET /prospecting/me`.
  La UI limitada de `crm.js` (abril, luca, felipe, felicitas) deja pasar el link por texto.
- **Prospecting Owner (2026-11-24, reemplaza la regla del líder del 2026-11-13)**:
  `OWNER_MANAGERS` (`constants.py`: pgonzales, bahia, justo, ana, manuela, lara, mia — mia desde el
  2026-11-25, encargada de los negocios de Vintti AI) lo cambian siempre,
  en cualquier status; cualquier otra persona con acceso (los BDRs) **sólo si la empresa está en
  Recycled** (status actual, antes del cambio). Ya no usa `users.lider`. Una regla:
  `store.can_change_owner()`, aplicada en el PATCH (403 `owner_locked`), la edición masiva (va a
  `failed`) y el alta manual (un BDR la crea sin owner). `/me` → `can_manage_owner`; el front
  muestra el owner con candado. **Lo automático no está alcanzado**: Clay, workflows, sync e
  importación de HubSpot escriben el owner igual.
- **Clay**: columna "HTTP API" → `POST /prospecting/clay/webhook` con `X-Clay-Token`
  (= env `CLAY_WEBHOOK_TOKEN`, propia). Acepta snake_case o los nombres de la planilla de
  HubSpot (`_ALIASES` en `store.py`). Match por `clay_record_id`, si no por dominio.
  **Un re-envío nunca pisa lo que trabaja el BDR** (status, owner, start date, Not ICP,
  semana): esos sólo se rellenan si están vacíos.
  **`"recycle": true` (2026-11-25)**: para las tablas «Recycle» de Clay (empresas que ya existen y se
  reasignan). Sólo actualiza —si no matchea, error «mandala como nueva», no crea— y **pisa owner y
  semana** (`RECYCLE_OVERWRITE_FIELDS` en `store.py`); `lead_source` ya se pisa siempre. El resto de
  BDR_FIELDS sigue con «sólo vacíos». Los cambios disparan workflows como cualquier update de Clay.
  **`"is_dummy": true` en el body la crea como prueba** (2026-10-15): así se prueba la columna
  de Clay directo contra App Runner —Clay no llega a `localhost` sin túnel, y la owner no quiere
  túnel— sin que los BDRs vean nada; se borra con "Borrar dummies". El match por dominio es
  **dentro del mismo `is_dummy`**, y como `clay_record_id` es único en toda la tabla, la misma
  fila de Clay mandada del otro lado se rechaza con un mensaje en vez de convertirse. El
  simulador (`scripts/clay_webhook_simulator.py`) manda dummies por defecto (`--real` lo apaga).
  Ojo: el backend local de la owner escribe en la RDS de producción.
  **Body de Clay = el mapeo que iba a HubSpot** (2026-11-03): además de los básicos manda
  `lead_source`, `open_jobs` (columna `Totaljobsfound`), `tier`, `remote_jobs` (checkbox
  "Remote Jobs" → se guarda `Yes`/`No`, el "Remote?" de HubSpot) y `prospecting_owner_id`
  (columna `Value` del round robin). `tier` y `remote_jobs` son columnas autocreadas y CLAY_FIELDS.
- **El owner llega como ID del Hub** (2026-10-28): igual que con HubSpot, Clay reparte las
  empresas con un **round robin** de IDs, que ahora son `users.user_id` del BDR, mandados
  en `prospecting_owner_id`. `resolve_owner()` (`store.py`) los convierte en el email del
  BDR; también acepta un email, pero **sólo si es de un BDR**. Si no coincide con nadie, la
  empresa entra sin owner y la celda de Clay muestra `owner_warning`. Antes se guardaba
  cualquier texto ("abril acosta") y la empresa no le aparecía a nadie. Los IDs se ven en
  el botón **BDR IDs (Clay)** de `prospecting.html` (sólo admin). Hay **un solo owner**:
  "Prospecting Owner Apollo" salió de `FIELDS` y de la UI. La columna queda en la tabla,
  sin uso. Los workflows guardados que la nombraban los limpia
  `scripts/drop_owner_apollo_from_workflows.py`.

### Contactos y llegadas

- **Contactos (2026-10-07)**: `prospect_contacts`, N por empresa, los carga el BDR desde la ficha
  (`docs/prospecting-company.html?id=`, layout tipo HubSpot) o la pestaña *Contacts*. Las ~90
  propiedades salen de **`backend/prospecting/contact_fields.py`** (única definición). Sólo las
  que se filtran seguido son columna propia; el resto vive en **`props` JSONB**, así sumar una no
  requiere ALTER. Su historial va a `prospect_company_events` con `contact_id`, y por eso aparece
  también en la actividad de la empresa. **Country/Continent** (`country_continent`, enum,
  2026-11-03) es la de HubSpot, para el workflow «freelance/independent en LatAm → Lead Life
  DQL»: no es el «Pais» de la empresa, que Clay manda con el nombre del país.
- **Contactos desde Calendly vía Zapier (2026-10-28)**: Zapier **empuja**, no se consulta. El
  Zap *Calendly · Invitee Created* → *Webhooks by Zapier · POST* pega a
  `POST /prospecting/zapier/calendly` con `X-Zapier-Token` (= env `ZAPIER_WEBHOOK_TOKEN`, propia).
  Todo en `backend/prospecting/inbound.py`; cada llegada queda en `prospect_inbound_contacts`
  (autocreada). Email ya existente → se actualiza: **sólo Meeting Date & Time se pisa**, las UTM
  y el resto sólo se rellenan si están vacíos (el primer canal no se pierde). Dominio (website
  del form, si no el del mail; nunca `FREE_EMAIL_DOMAINS`) de **una sola** empresa → contacto
  creado ahí. *(Lo que sigue sobre la bandeja quedó superado: desde el 2026-11-04 el contacto se crea sin empresa, ver «Contactos SIN empresa».)* Si no → bandeja **"Unassigned from Calendly"** de la pestaña Contacts, con
  **Link** / **Discard**; y cuando Clay carga después una empresa con ese dominio, el webhook de
  Clay los asocia solo (`attach_pending_for_company`). Es una bandeja aparte y no
  `company_id` NULL porque de esa columna cuelgan el historial, el motor y los JOINs. Una
  pregunta del form se mapea en Zapier con la clave exacta de `contact_fields.py`; un valor
  inválido no frena la llegada, vuelve en `warnings`. `"is_dummy": true` = prueba, como Clay.
  Son **dos Zaps** al mismo endpoint: el de reservas (*Invitee Created or Rescheduled*) y el del
  formulario sin reserva (*Routing Form Submission* → Delay), que manda `origin_detail =
  "Abandoned Calendar"` (`ABANDONED_ORIGIN_DETAIL`). Esa llegada **nunca trae reunión**: se tira
  la fecha que venga (era la hora del form y, como la reunión se pisa siempre, borraba la real), y
  si el mail ya tiene reunión no se marca. Agendar después no borra la marca (fill-if-empty).
- **Desplegables con buscador (2026-11-05)**: `docs/assets/js/prospecting-select-search.js`
  (en `prospecting.html` y `prospecting-company.html`) reemplaza la lista nativa de todo
  `<select>` simple con 8+ opciones por un panel que filtra al tipear (sin acentos, por palabras,
  también por el `<optgroup>`). Elige poniendo el valor y disparando `change` con bubbles: los
  listeners de siempre no cambian. `data-nosearch` lo excluye.
- **Qualified / SQL exigen contacto**: si la empresa queda en esos status sin un contacto con
  `REQUIRED_ON_QUALIFIED` completos, `contact_incomplete = TRUE`. El PATCH responde
  `needs_contact` y la página abre «Completá el contacto». Se recalcula en cada cambio de
  contacto o de status (`recompute_contact_incomplete`).

### Importación y sync desde HubSpot

- **Importación masiva desde HubSpot (2026-11-03)**: `backend/scripts/import_hubspot_companies.py`
  (dry-run por defecto, `--apply`, `--limit`, `--resume`) trae las ~165 k empresas por la API,
  en lotes de 500, `lead_source='HubSpot'`, `created_at` = createdate. Cruza por
  `hubspot_company_id` (índice parcial en `ensure_schema()`) y adopta por dominio sólo filas de
  Clay sin id; en lo existente **sólo rellena vacíos**. **No pasa por `upsert_from_clay`** (un
  evento por campo = horas) ni dispara workflows: en cada lote anota en `prospect_wf_match` las
  que ya cumplen un workflow por condiciones, así el cron no las inscribe en masa. Los workflows
  por horario no tienen memoria: el resumen avisa cuántas importadas cumplirían.
  **El owner sale de «Prospecting Owner (HubSpot)»** (el PO HubSpot = el PO del Hub), nunca de
  `hubspot_owner_id`, y se cruza con un BDR activo por email **o por nombre** (`OwnerResolver`):
  el mail del owner en HubSpot no siempre es el `email_vintti`. La primera corrida no lo hacía y
  dejó sin owner empresas de BDRs activas (Valeria Arias, Semana 30). `--audit` lo diagnostica y
  `--repair-owners` lo corrige sin pisar un owner que puso una persona o un workflow.
- **Sync HubSpot → Hub de empresas (2026-11-04)**, mientras los BDRs sigan usando HubSpot. Sólo
  en esa dirección (el Hub no escribe empresas en HubSpot). Cron cada 30 min
  `.github/workflows/prospecting-hubspot-sync.yml` → `POST /prospecting/hubspot/sync`
  (X-Audit-Token; `?dry=1`; `GET /prospecting/hubspot/sync/last`). Código en
  `backend/prospecting/hubspot_companies.py`, que también tiene el mapeo que usa la importación
  (una sola definición). Incremental por `hs_lastmodifieddate` (marca en `hubspot_sync_state`,
  clave `prospect_companies`, 10 min de solape, se congela si hubo errores), hasta 2000 empresas
  o ~200 s por corrida. **HubSpot gana sólo cuando su valor cambió** respecto de la foto
  `prospect_companies.hubspot_seen` (patrón de `hubspot_model_seen`): lo editado en el Hub no se
  pisa cada 30 min. Sin foto (las importadas) la base es el `raw_payload` de la importación; el
  owner, el valor actual del Hub si nadie lo tocó después. Un valor de HubSpot que no se puede
  traducir (status fuera de la lista, PO que no es BDR activo) no se aplica ni vacía nada.
  Empresa nueva en HubSpot → se crea (o adopta la de Clay del mismo dominio). **Los cambios son
  cambios reales** (decisión de la owner): historial `source='hubspot_sync'`, `emit_event()` y
  `tick()`, así que disparan workflows. `python scripts/import_hubspot_companies.py --sync
  [--apply]` corre lo mismo sin tope, para ponerse al día.
- **Contactos de HubSpot (2026-11-04)**: importación `backend/scripts/import_hubspot_contacts.py`
  (dry-run por defecto; correr DESPUÉS de las empresas) + sync cada 30 min (segundo paso del mismo
  cron → `POST /prospecting/hubspot/sync-contacts`, marca `prospect_contacts`), lógica en
  `backend/prospecting/hubspot_contacts.py`. Mapeo contra `contact_fields.py` por nombre o label
  (el catálogo salió de la planilla de HubSpot); el *value* interno de un desplegable se traduce al
  label, `a;b` → lista, owners por `OwnerResolver`; un valor que no valida se omite (queda en
  `raw_payload`), nunca frena el contacto. **Empresa**: asociación de HubSpot (Primary primero) →
  `hubspot_company_id`; si no, dominio del mail de una sola empresa; si no, *(superado: hoy queda sin empresa, ver «Contactos SIN empresa»)* **la bandeja
  «Unassigned contacts»** (`prospect_inbound_contacts`, `source='hubspot'`, único por
  `hubspot_contact_id`), que ahora tiene filtro por origen y búsqueda; `inbound.link()` usa el
  `source` de la fila y le pega al contacto su id y foto de HubSpot. Al crear una empresa, el sync
  de empresas llama a `attach_pending_for_company()`. Mismas reglas que empresas: foto
  `prospect_contacts.hubspot_seen`, los cambios disparan workflows, la importación blinda los
  workflows de contacto por condiciones. Un contacto que en HubSpot cambia de empresa **no se
  mueve** (sale en el reporte).
- **Sync de contactos/empresas trabado (arreglado 2026-11-24)**: el 17-nov HubSpot modificó ~58.600
  empresas a la vez; el sync volvía 10 min atrás (`OVERLAP`) en cada corrida, releía las mismas 2.000 y la
  marca no pasaba nunca. Ahora una corrida que quedó `partial`/`running` sigue desde la marca exacta
  (`hubspot_companies._start_from()`, también contactos). Y un contacto cuyo mail ya es de otro contacto del
  Hub (atado a otro id de HubSpot: fusionado o recreado allá) se saltea con aviso en vez de ser error: con
  errores la marca se congela. Además se sumaron a `contact_fields.py` las opciones de HubSpot que faltaban
  (Lead Life «PQL (BDRs)», «MQL (Event)», «MQL (MKT) - LM», eventos, Model…) y Marketing contact status se
  traduce a la etiqueta. Lo perdido antes lo completa `scripts/backfill_contacts_from_raw.py` (en seco por
  defecto; re-mapea `raw_payload`, sólo rellena vacíos, blinda workflows). Para ponerse al día con empresas:
  `python scripts/import_hubspot_companies.py --sync --catch-up --apply`: aplica los datos pero **no dispara
  workflows**, blinda como la importación (`hubspot_companies.shield()`). Sin `--catch-up`, cada cambio de hace
  días inscribía en workflows y la corrida iba a ~3.000 empresas/hora. Se corta con Ctrl+C y sigue desde la marca.
- **Contactos SIN empresa, como en HubSpot (2026-11-04, decisión de la owner)**:
  `prospect_contacts.company_id`, `prospect_company_events.company_id` y
  `prospect_wf_enrollments.company_id` son nullable (`ensure_schema()`). Un contacto sin empresa
  está en la tabla (filtro **Company: No company**), se edita, tiene historial y corre workflows
  de contacto. Se crea desde cero con **New contact** de la pestaña Contacts
  (`POST /prospecting/contacts`, `company_id` opcional) y la empresa se elige, cambia o quita en
  su ficha (`PATCH /prospecting/contacts/<id>/company` → `store.set_contact_company()`, que
  también mueve sus inscripciones abiertas). **Sin empresa, el buscador va en el campo «Company name»** del panel (2026-11-25):
  la propiedad de texto no asocia nada y además se veía vacía al reabrir (en `get_contact()` `company_name`
  es la empresa del Hub por el JOIN y pisa la de `props`). Con empresa, el bloque «Empresa» va arriba y
  Company name queda de sólo lectura. Se le asocia sola cuando llega una empresa con su
  dominio (única) — `store.attach_contacts_for_company()` en el webhook de Clay y el sync de
  empresas — o cuando HubSpot le asocia una que ya está en el Hub. **Motor**: un contacto sin
  empresa se alcanza por `tick(contact_ids=[…])` (`_scope_sql` / `_enr_scope_sql`); **nunca
  pasar `company_id=None` esperando "ese contacto"**: sin alcance, `tick()` es la corrida global
  (por eso `_run_instant()` y la edición masiva separan los ids). `advance()` /
  `_close_by_conditions()` van con LEFT JOIN y dummy = `COALESCE(ct.is_dummy, c.is_dummy)`.
  Acciones sobre la empresa (editar/copiar `company.*`, inscribir la empresa, IA a un campo de
  la empresa) no hacen nada y lo dicen en el log; condiciones `company.*` = falsas.
  **Fin de la bandeja «Unassigned contacts»**: HubSpot y Calendly crean el contacto sin empresa;
  lo que quedaba pendiente lo pasa `backend/scripts/migrate_inbound_to_contacts.py` (dry-run por
  defecto). `prospect_inbound_contacts` queda como registro de llegadas de Calendly.

### Negocios (deals)

- **Fecha de entrada a cada etapa (2026-11-06)**: `prospect_deals.stage_dates` JSONB
  `{"<pipeline>:<etapa>": ts}`, la **última** entrada (como `hs_v2_date_entered_*`). La sellan
  `create_deal`, `move_stage` y `reflect()` (`deals.STAMP_STAGE`); el sync / la importación de
  HubSpot la pisan con la fecha real de HubSpot **después** del move (`_merge_stage_dates`).
  Candidate Signed no tiene esa propiedad en HubSpot. En condiciones: `deal.entered_<pipeline>_<etapa>`
  («Date entered "NDA Sent (Proceso De Contratación)"», tipo datetime; `objects.entered_key()`, la
  misma clave en `engine.deals_of()`). Backfill ya aplicado: `scripts/backfill_deal_stage_dates.py`
  (historial del Hub → etapa actual → HubSpot).
- **Propiedades sincronizadas contacto ↔ negocio ↔ empresa (2026-11-06)**: reemplaza las dos
  subcarpetas de workflows de HubSpot que copiaban propiedades entre objetos. **No son workflows**
  (no editan negocios): una tabla `LINKS` en `backend/prospecting/prop_sync.py` + `propagate()`,
  enganchado al final de `store.update_contact`, `store.update_company` y `deals.update_deal` (cubre
  UI, edición masiva, workflows, popup y syncs). Políticas del doc de la owner: `contact` (contacto →
  sus negocios **abiertos**, pisa: Origin, LinkedIn del contacto), `deal` (negocio → todos sus
  contactos, pisa: MQL/SQL Lost Reason, Model, Role Hired), `common` (el último cambio gana entre
  contacto y negocios abiertos; la **empresa sólo rellena vacíos**, nunca se pisa lo de Clay). Un
  negocio cerrado no recibe cambios del contacto, pero lo suyo sí viaja. Anti-loop: lo que escribe
  lleva `source = "sync:<obj>:<id>"` y eso no se re-propaga; dispara `emit_event` (las condiciones lo
  ven en el próximo tick). Un valor que no entra en el destino (otra lista) se saltea. Negocio nuevo
  o contacto recién asociado → `pull_into_deal()` rellena los vacíos del negocio. **Se llena solo
  sin HubSpot** (`deals.after_stage()`, en create/move/reflect): Lead Life (Deal) por etapa
  (`LEAD_LIFE_BY_STAGE`), First Deep Dive Date (Deal) al entrar a Deep Dive, y en el contacto First /
  Last Deep Dive Date = la primera y la última de sus negocios; Credit Loop / Credits Won / Expiring
  al Close Win desde `account_credit_loop` (`deals._credit_values`). Closed Lost antes de SQL pide
  **MQL (AE) Lost Reason** en vez de SQL (`deals.lost_before_sql()` → `form_for(before_sql=)`).
  Propiedades nuevas: negocio `mql_lost_reason`, `lead_life_deal`, `first_deep_dive_date`,
  `follow_up_date`, `credit_loop`, `credits_won`, `credits_expiring_date`; contacto `credit_loop`,
  `sql_lost_reason`, `role_hired` (mismo `name` que HubSpot). Datos existentes:
  `scripts/backfill_prop_sync.py` (en seco reporta diferencias; `--apply` completa sólo las nuevas
  vacías, primero desde HubSpot). Lead Life del contacto NO está en el mapa (lo manejan workflows).
- **Negocios (deals, 2026-11-04)**: el pipeline de ventas de HubSpot (*Proceso De Contratación*
  y *Vintti AI Pipeline*) como tablero por etapa en la sección Negocios (`prospecting-deals.js`):
  arrastrar = cambiar de etapa, tabla, filtros, export, panel del negocio, tarjeta en la ficha de
  la empresa y lista en el panel del contacto. Tablas en `backend/prospecting/deals.py`
  (`prospect_deal_stages` sembrada de HubSpot con labels/orden/% — sin HubSpot, de
  `deal_fields.DEFAULT_STAGES` —, `prospect_deals`, `prospect_deal_contacts`, y
  `prospect_company_events.deal_id`); catálogo en `deal_fields.py`. **Cambiar de etapa abre
  «Propiedades dependientes», igual que HubSpot** (pedido de la owner): `STAGE_FORMS` = (campo,
  obligatorio) por etapa, en el orden de HubSpot; el popup muestra todos (`GET
  /deals/<id>/stage-form`, `POST /deals/stage-form` para uno nuevo), **prellenados** de la empresa /
  contacto (`PREFILL`), y lo cargado **rellena los vacíos** de la empresa y el contacto
  (`deals.fill_related`, con historial y workflows). Sólo los obligatorios frenan (409
  `needs_fields`). SQL y NDA Sent salieron de las capturas de la owner (2026-11-04); NDA Signed y Closed
  Lost, de lo que el sync de oportunidades ya sabía que HubSpot exige. **Candidate Signed, Closed
  Won y Closed Lost de un negocio CON oportunidad se mueven sólo desde Opportunities**
  (`OPPORTUNITY_OWNED_STAGES`; el server responde 400): ahí nacen el hire, el MKT Collab y el motivo,
  que el hub le empuja a HubSpot. `deals.copy_closing_values()` copia al negocio esos mismos valores
  con la misma regla del push (`hire_values_for_opportunity`; se pisa todo menos Role Hired; MKT
  Collab / Closed Win Date / fecha de cierre sólo al ganar; Closed Lost: motivo, detalle y fecha).
  Corre en `reflect(values=True)`: el cron y al abrir un negocio, no en cada carga del tablero. Role to hire + Model se
  exigen además desde Deep Dive si faltan (sin eso no hay oportunidad). Las opciones de los
  desplegables salen de las propiedades de deal de HubSpot (`prospect_deal_field_options`, se
  siembra con las etapas); sin opciones, el campo va como texto. La propiedad «Company Name» del
  negocio es `company_name_deal`: `company_name` en las lecturas es la empresa asociada del Hub. **Los filtros de historial de EMPRESA excluyen `deal_id`**
  (`objects.history_filter`, `engine` y `property_history`): si no, el owner de un negocio contaría
  como owner de la empresa en un workflow. **Workflows de negocios todavía no**: el catálogo va en
  `options.deals`, aparte de `objects`, para que el editor de workflows no lo ofrezca.
  **Puente al hub** (`deal_to_hub.py`, la regla del sync de HubSpot): **SQL** crea o vincula la
  cuenta (`_find_existing_account` y compañía de `hubspot_routes.py`) y sella `account.sql_date`
  una vez; **Deep Dive o más** crea la oportunidad (`_insert_opportunity_from_deal`, sales lead del
  pipeline, Role to hire → puesto, to-dos, mail de Credit Loop, Slack de Sourcing después del
  commit) con el mismo **freno**: si la cuenta tiene opps sin negocio atado, queda «esperando
  decisión» y la ficha ofrece **Vincular** / **Es nueva, creala**. Etapas siguientes empujan la opp
  sólo hacia adelante (NDA Sent, NDA Signed → Sourcing); Signed / Close Win / Closed Lost los mueve
  la recruiter en Opportunities y `deals.reflect()` (al abrir el tablero y en el cron) lo trae al
  negocio, sin retroceder. Las opps que crea nacen con `hubspot_deal_id` NULL: el sync de HubSpot
  no las toca. Un negocio dummy no crea nada. **Negocio importado de HubSpot (desde 2026-11-25)**:
  movido por una persona en el Hub, también crea cuenta y opp (Delancy CPA pasó a SQL / Deep Dive en
  el Hub con HubSpot en Intro Call y no se creaba nada). Nacen **con el `hubspot_deal_id`** del
  negocio, así `/hubspot/sync/opportunities` las encuentra por ese id cuando HubSpot se pone al día
  (no duplica, no retrocede); si el sync la creó primero, `_opp_by_hubspot_deal()` la ata. Lo que
  viene sólo de HubSpot (sync de negocios) no llama a `deal_to_hub.run()`: ahí crea el sync de opps. **El día del corte**:
  ver la checklist completa en `hubspot.md` → «Corte de HubSpot: el «interruptor»». **HubSpot → Hub**: importación
  `backend/scripts/import_hubspot_deals.py` (dry-run por defecto, después de empresas y contactos) +
  tercer paso del cron (`POST /prospecting/hubspot/sync-deals`, marca `prospect_deals`), lógica en
  `hubspot_deals.py`: sólo los 2 pipelines, etapa por `hubspot_stage_id`, empresa/contactos por
  asociación, foto `hubspot_seen` (clave `__stage` para la etapa); con oportunidad, HubSpot no hace
  retroceder la etapa. De paso se arregló el mail de Credit Loop del sync de oportunidades
  (`payload` sin definir → NameError tragado, no salía nunca).

### Tabla, vistas y paneles

- **Edición masiva (2026-10-29)**: tildar empresas (tabla) o contactos (pestaña Contacts) →
  **Editar** → una propiedad y un valor para todos. `POST /prospecting/companies/bulk` y
  `/contacts/bulk` con `ids` o con `filters` (los mismos params del GET: «Seleccionar las N que
  coinciden con los filtros» manda los filtros, no los ids). Filtran con `_company_where()` /
  `_contact_where()` de `store.py`, los mismos de las listas: no armar otro WHERE. Cada registro
  va por `update_company()` / `update_contact()` (historial por campo, igual que de a uno) dentro
  de un **SAVEPOINT**: un valor inválido salta ese registro sin abortar el lote. Workflows: un
  `emit_event()` por registro y un `tick()` por empresa. Lo usa cualquiera con acceso (como la
  edición de a uno); inscribir en workflow sigue siendo de `WORKFLOW_EDITORS`. Empresas: sólo
  `EDITABLE_FIELDS`; contactos: todo el catálogo menos `email` (único). Tope `BULK_MAX` = 1000.
- **Eliminar (2026-11-06)**: Acciones → «Eliminar» (tildados o todos los del filtro), desde el
  2026-11-09 todos menos los BDRs (`_gate(cur, staff=True)` = admin + `WORKFLOW_EDITORS` +
  `EXTRA_ACCESS_EMAILS`, `can_delete` de `/me`; también el `DELETE /contacts/<id>` del panel).
  «Registros eliminados» sigue en Configuración. `POST /prospecting/companies/delete` y `/contacts/delete`, mismos `ids` / `filters` que la
  edición masiva. **Borrar una empresa NO borra sus contactos** (como HubSpot): las FK de `company_id`
  son ON DELETE CASCADE, así que `store.delete_companies()` primero los deja sin empresa y suelta su
  historial e inscripciones (`company_id = NULL`). Un contacto borrado cierra sus inscripciones
  abiertas (`contact_id` no tiene FK). Todo queda en `prospect_deleted_records`, que además es la
  **lista de bloqueo**: `upsert_from_clay` (clay_record_id o dominio) y los syncs de HubSpot
  (`hubspot_id`) no lo recrean. Calendly sí (un lead que vuelve a agendar es nuevo). Configuración →
  «Registros eliminados» → «Permitir que vuelva» lo saca de la lista.
- **Alta manual de empresas (2026-11-06)**: botón «Nueva empresa» (sección Empresas) y «Crear
  empresa "…"» al final del buscador de empresa del panel del contacto (queda asociada al guardar).
  Un solo modal, `ProspectingContacts.newCompanyModal()`. `POST /prospecting/companies` →
  `store.create_company()`: cualquiera con acceso, `lead_source = 'Manual'`, owner sólo BDR activo,
  **dominio repetido → 409 con la existente** («Usar esta»). La lista de borrados no la frena (lo
  decide una persona). Cada campo con valor queda como cambio desde vacío y pasa por
  `_run_instant()`, así el owner dispara el workflow 2 igual que con Clay.
- **Exportar a CSV (2026-10-29)**: Acciones → «Exportar a CSV», con las columnas que se elijan
  (arranca con las de la tabla). `POST /prospecting/companies/export` y `/contacts/export`, mismos
  `ids` / `filters` que la edición masiva (`_bulk_target_ids()`), tope `EXPORT_MAX` = 20000. El
  catálogo de columnas lo da `store.export_fields()` (también en `/options` → `export_fields`);
  en contactos la empresa del Hub sale como `hub_company`, porque `company_name` ya es una
  propiedad del contacto. CSV con BOM (acentos en Excel), fechas con hora en hora Argentina.
- **Editar en la celda (2026-10-30)**: en Contactos todas las propiedades se editan con un click
  en la tabla (menos Name, que abre el panel, y Company, que es el link); en Empresas además de
  Owner/Status/Not ICP, Start Date, Semana y Lead Source. Lo de Clay sigue de lectura (decisión de
  la owner). Un solo `inlineEdit()` en `prospecting.js`, con los controles de
  `ProspectingContacts.fieldControl()`; guarda por los PATCH de siempre (historial y workflows).
- **Orden por columna (2026-10-30)**: click en el título → menú con las formas según el tipo
  (A→Z, menor→mayor, más recientes, **orden de la lista** para Size/Status/Lead Life, owner por
  **nombre**, Sí/No primero). Un solo `store.order_sql(obj, sort)` para empresas y contactos;
  `sort` = `<campo>:<asc|desc|list_asc|list_desc>` (`views.SORT_MODES`), vacíos siempre al final.
  El texto se ordena con `COLLATE "es-x-icu"`: la intercalación de la base (en_US) ignora los
  espacios y ponía «Agustina» antes que «Agustin Penna». Las vistas de contactos guardan `sort`.
- **Historial por propiedad (2026-10-29)**: el reloj junto a la etiqueta de cada campo (ficha de
  la empresa, vista rápida, panel del contacto) abre quién la cambió, cuándo y de qué a qué
  (`GET /prospecting/<companies|contacts>/<id>/history?field=` → `store.property_history()`,
  sobre el mismo `prospect_company_events` de la actividad, sin su tope de 300). Clay no registra
  campo por campo al crear una empresa: el «valor al crearse» es el `old_value` del cambio más
  viejo o el actual. Front compartido en `prospecting-history.js` (botón `data-hist`).
  La edición masiva escribe sus eventos con `source = "bulk:<n registros>"` (y el `actor` de
  siempre): historiales y actividad la muestran con la etiqueta «Edición masiva · n».
- **«Por segmento» + vistas de contactos (2026-10-29)**: Acciones → «Por segmento» crea una vista
  nueva sólo con lo seleccionado (`POST /prospecting/views/segment`), con las columnas que se
  elijan. Es **fija**: `config.segment_ids` guarda los ids de ese momento, también con «todas las
  del filtro». La tabla la pide con `segment=<view id>` y `_company_filters()` /
  `_contact_filters()` lo traducen a `ids` vía `views.segment_ids_of()` (sólo vistas propias o
  compartidas; si no, vacío). Los demás filtros y la edición/export funcionan dentro del segmento.
  Guardar la vista sin `segment_ids` no lo borra (`views.update()` lo conserva). Las vistas tienen
  `object` (`company` | `contact`): las de contacto van en la tira de la pestaña Contacts (columnas
  elegibles y filtros búsqueda / Lead Life / Owner guardados con la barra «Unsaved changes»; el
  orden de esa tira va en `prospect_view_prefs.contact_tabs`, `PUT /views/tabs` con
  `object: "contact"`). Las columnas también se mueven arrastrando el encabezado de la tabla
  (`bindHeaderDrag()`, empresas y contactos); en «Todos los contactos» quedan en el navegador y no entran en las pestañas de empresas. En `/contacts`,
  `company_name` sigue siendo la empresa del Hub (la leen workflows y fichas); la propiedad del
  contacto viaja como `contact_company_name` y la del Hub también como `hub_company`.
- **Vistas de contactos al nivel de Empresas (2026-11-06)**: la tira de Contactos tiene `+` (crear
  desde la vista actual o en blanco, compartida o no), botón **Columns** y **Advanced filters**. La
  vista guarda búsqueda / Lead Life / Owner / **Company** (`any`/`none`; faltaba en
  `CONTACT_FILTER_KEYS` y se perdía al guardar) + filtros avanzados + columnas + orden. Los avanzados
  son condiciones de workflow de CONTACTO (`conditionsPanel(..., "contact")`, validadas en
  `_contact_filters()` y `views._clean_contact_config()`); `_contact_where()` los mete como
  `ct.id IN (SELECT … FROM prospect_contacts WHERE <compile_conditions(…, "contact")>)` porque el
  compilador escribe sin alias. Verificado: mismo resultado que `engine.matching_ids()`.
- **Paneles (métricas de BDRs, 2026-11-06)**: sección «Paneles» del menú, los reportes de HubSpot
  que la owner pasa de a uno. `GET /prospecting/panels/<key>?from=&to=` (cualquiera con acceso) →
  `backend/prospecting/panels.py` (`PANELS`) devuelve **filas a nivel registro**, y
  `docs/assets/js/prospecting-panels.js` agrupa por período (mes / semana / trimestre) y persona:
  barra, celda del ranking y detalle salen de las mismas filas. En vivo, sin caché. **SQLs by BDR** =
  contactos distintos por SQL Date del negocio asociado × Scheduled By, con los 5 filtros del reporte
  de HubSpot: Scheduled By conocido y fuera de `EXCLUDED_SCHEDULERS` (bahia, agustin, mariano,
  valentinacadirola), email fuera de `@vintti.com` («Internal Team»), Meeting Date & Time conocido
  (HubSpot pedía > 2026-01-01; acá el corte lo da Desde/Hasta) y negocio con SQL Date. Cuadra exacto
  con HubSpot (ene–nov 2026: 6/8/12/12/19/14/14/6/9/16/2). **No hay datos antes de dic-2025**: «SQL
  Date» arranca el 25-11-2025. Cada BDR tiene un color fijo en el ranking (`PALETTE`, por email).
  **SQLs by BDR · VinttiKids** = el mismo panel con `team="vinttikids"`: además Scheduled By ∈
  `panels.TEAMS["vinttikids"]` (abril, victoria, valeria, catalina, joel, bartolome, marcos). Un
  equipo nuevo = una entrada en `TEAMS` + una en `PANELS` y en el `PANELS` del front. Ídem
  **NextGen** (`TEAMS["nextgen"]`). **El color de cada persona es el mismo en todos los paneles**:
  sale de `people_order` (quienes tienen algún SQL, por fecha de su primer SQL; 24 colores en `PALETTE`), no de las filas
  del panel; alguien nuevo va al final y no corre a nadie.
  **Se ven de a uno** (2026-11-06): barra ‹ selector › arriba (`PANELS` del front con `title` +
  `group`; el grupo es un `<optgroup>` y se lee arriba del nombre). Los 3 de SQLs van en el grupo
  «SQLs - Monthly YTD». Cada panel se arma la primera vez que se muestra y después sólo se oculta
  (conserva sus filtros); el último visto queda en `localStorage` (`pp_current_v1`). ← / → también
  cambian de panel.
  **Intro Calls** (grupo «Intro Calls - Monthly YTD», 2026-11-07): `panels.intro_calls()` + equipos,
  contactos por **Date of Meeting Scheduled** × Scheduled By, sin negocios: Scheduled By conocido y
  fuera de `EXCLUDED_SCHEDULERS`, fuera de Internal Team, Meeting Date & Time conocido, Date of
  Meeting Scheduled conocido. Ene–oct 2026 = 17/26/28/35/45/26/30/26/36/54, igual que HubSpot (el
  contacto 4230 tenía la fecha vieja: en HubSpot cambió y la importación no la aplicó; corregido a mano
  el 2026-11-07). En
  el front es el mismo panel (`CountByBdr`) con `METRICS.sql` / `METRICS.intro`; las filas traen
  `date` (la dimensión). `people_order` une SQLs e intro calls (sin los excluidos): 28 personas, 32
  colores en `PALETTE`.
  **Lead Quality** (subtítulo «Reasons why intro call were not SQL», 2026-11-07): `panels.lead_quality()`
  = contactos con **MQL (AE) Lost Reason** por mes de Meeting Date & Time (UTC); Scheduled By conocido y
  fuera de `LQ_EXCLUDED_SCHEDULERS` (bahia, agustin, mariano: **Valentina sí cuenta**, va al final de
  `people_order` para no correr colores). «Lead Life alguna vez Closed Lost» no se aplica: todos los
  que tienen motivo lo cumplen. **Cuenta el motivo del Hub, incluido el copiado del negocio por
  `prop_sync`** (decisión de la owner): da 175 contra 162 de HubSpot, cuyos contactos no tienen el
  motivo que sí tiene su negocio (`deal_lost_reason`). El panel general desglosa por motivo
  (`groupKey: "reason"`, colores fijos `REASON_PALETTE` en el orden de `MQL_LOST_REASONS`), también por
  equipo (= «Lead Quality - VinttiKids/NextGen» de HubSpot, todos los motivos); «Lead
  Quality x BDR» (+ VinttiKids / NextGen) desglosa por persona con un desplegable de motivo que
  arranca en Timing. Dos paneles leen el mismo endpoint: el DOM y las preferencias van por `uid`.
  **Inicio y fin de cada BDR (2026-11-13)**: tabla `prospect_bdr_tenure` (email, inicio, fin,
  `end_reason` = `left` | `role_change`), autocreada y **sembrada con la tabla «Status of Contract» de
  la owner** (`panels.SEED_TENURE`, `ON CONFLICT DO NOTHING`: lo corregido nunca se pisa). Motivo
  sembrado: `role_change` si sigue activa en el Hub (Ana y Justo → BDM, Manuela → SOA). Cada panel la
  devuelve en `tenure`; en el mapa de calor por persona (no en Lead Quality por motivo) el período de
  inicio lleva una línea a la izquierda, el de fin a la derecha, lo de afuera va rayado en gris (con su
  número igual) y el nombre lleva «hasta ago ’26» / «→ BDM». Se edita en «Altas y bajas» (staff,
  `PUT /prospecting/panels/tenure`). No usa `users.ingreso_vintti_date`: no coincide con la realidad.
  **Sólo cuadra porque las propiedades tipo `user` aceptan gente que ya no está**: el sync de
  contactos resolvía Scheduled By contra usuarios ACTIVOS y descartaba a los ex-BDRs (93 contactos).
  Ahora, si no matchea a nadie del Hub, guarda el email del owner de HubSpot (activos y archivados) y
  su nombre en `prospect_people`. Contact Owner y Follow Up Task Owner aceptan **cualquier persona activa
  del Hub** (tipo `user` desde el 2026-11-24; antes `owner` = sólo BDRs y se perdían ~5.000 owners de Justo,
  Bahía, Mariano…), pero sin ese respaldo de ex-empleados (`hubspot_contacts.ACTIVE_ONLY`). Backfill ya
  aplicado: `scripts/backfill_scheduled_by.py` (blinda los workflows por condiciones).
  **Not ICP Reason** (grupo «Rendimiento de Islas», 2026-11-10): `panels.not_icp_reason()` = TODAS
  las empresas con motivo (sin fecha, como HubSpot), por motivo × Prospecting Owner; sin owner =
  «Sin owner» (gris). En el front es otro componente, `ByCategory` (barras apiladas por owner + mapa
  de calor owner × motivo, drawer de empresas con `kind: "company"`). **Not ICP Reason <> BDR** = las
  mismas filas con `pivot: true`: una barra por owner (A→Z, «Sin owner» al final) y tramos por motivo.
  **Not ICP Reason <> Semana** = `dim: "week"`: una barra por «Semana» de la empresa (`week_label`,
  normalizada a «Semana N»; vacía = «Sin semana» al final), tramos por motivo, mapa de calor semana ×
  motivo en el color de cada motivo. El filtro de BDRs sigue siendo por owner. Cuadra con HubSpot
  semana por semana (38–46: 479/657/1114/1284/849/794/648/539/401).
  **Not ICP Reason - Lead Source** = `seg: "source"`: barras por motivo, tramos y mapa de calor por
  Lead Source. `lead_source = 'HubSpot'` es el relleno de la importación cuando HubSpot no tenía valor:
  se muestra como «Sin valor», igual que el reporte.
  **(Estado al 2026-11-13) Hasta deployar la lista de 6 motivos, el sync de prod sigue descartando los 4 nuevos**: después del
  deploy, volver a correr `scripts/backfill_not_icp_reason.py --apply` (es idempotente; el 2026-11-13
  ya recuperó 82 más). Los owners que no agendaron
  nada se suman al FINAL de `people_order`. Cuadra exacto con HubSpot (2054/1858/1474/738/384/299)
  **sólo desde que `NOT_ICP_REASONS` tiene los 6 motivos de HubSpot** («Otro», no «Other»): con 3,
  la importación y el sync descartaban el resto y 4676 empresas quedaron sin motivo. Las recuperó
  `scripts/backfill_not_icp_reason.py` (ya aplicado; trae de HubSpot en vivo, sólo rellena vacíos,
  actualiza `hubspot_seen` y blinda el workflow 7 «Not ICP conocido → DQL»: 275 de esas no estaban en
  DQL y así siguen, igual que en HubSpot).
- **Menú de secciones (2026-11-03)**: el título de la página es un desplegable «Empresas ▾» con
  Empresas, Contactos, Negocios y Workflows (`SECTIONS` / `showSection()` en `prospecting.js`);
  debajo, como pestañas subrayadas, sólo las vistas de esa sección (la tira de contactos
  `#prCtTabs` vive ahí, ya no en la tarjeta).
  Cambiar de sección no descarta nada y la última queda en `localStorage`. **Configuración** (2026-11-03) junta «BDR IDs
  (Clay)» y el «Test panel», que antes eran botones del header sólo para pgonzales: la ven
  pgonzales, mia, manuela y bahia (`can_configure` de `/prospecting/me` = admin o `WORKFLOW_EDITORS`;
  `POST /dummy/seed` y `DELETE /dummy` piden lo mismo con `_gate(cur, settings=True)`).
- **Vistas guardadas por persona (2026-10-14)** — sólo tipo Tabla por decisión de la owner (un kanban u
  otro tipo sería un `type` nuevo en `config`), como las de HubSpot: el `+` de las pestañas
  crea una vista con filtros, **filtros avanzados**, columnas en el orden que se arrastren,
  orden de filas y tamaño de página. Todo en `backend/prospecting/views.py`: tablas
  `prospect_saved_views` (privada salvo `shared`; compartida = otros la agregan y la
  duplican, **sólo la dueña la edita**, lo frena el server) y `prospect_view_prefs`
  (pestañas que ve cada uno y en qué orden). Desde el 2026-11-06 hay UNA sola fija, «Companies» (`sys:all`), siempre primera: no se oculta ni se arrastra; My companies / Unassigned se arman como vistas propias. Desde el 2026-11-09 «Recycled» (`sys:recycled`, status Recycled) y «This Week» (`sys:week`: owner = quien mira + `week="__current__"`, que `_company_where()` traduce a la «Semana N» ISO de hoy en hora AR, sin importar mayúsculas) son fijas para todos, en ese orden (`SYSTEM_TABS` en `views.py` + `SYS_TABS` / `SYS_OVERRIDES` en `prospecting.js`).
  Los filtros avanzados son condiciones de workflow: el param `advanced` de
  `GET /prospecting/companies` pasa por `rules.validate_conditions()` +
  `compile_conditions()`, la misma lista blanca. En el front reusa `conditionsEditor()` de
  `prospecting-workflows.js` con la clave `"ext"` (`conditionsPanel()`), así el editor de
  workflows no cambió. Owner `__me__` = quien mira la vista. Las fijas siguen guardando
  columnas en `localStorage`.


### Propiedades editables

- **Propiedades editables desde la página (2026-11-25)**: Configuración → **Propiedades**
  (`docs/assets/js/prospecting-properties.js`) crea, edita, ordena, oculta y borra propiedades de
  empresas, contactos y negocios. Editan `PROPERTY_EDITORS` (= `OWNER_MANAGERS`: pgonzales, bahia,
  justo, ana, manuela, lara, mia); `/me` → `can_edit_properties`, y la sección Configuración se les
  muestra sólo con ese ítem si no son `can_configure`. Backend: `backend/prospecting/properties.py`
  + `/prospecting/properties*`. Tabla `prospect_properties` (autocreada): fila de una de fábrica =
  **override** (nombre, descripción, opciones, tipo texto ↔ desplegable, obligatoria, oculta, orden,
  grupo); fila `is_custom` = propiedad nueva, con su valor en `props` JSONB (para empresas se agregó
  `prospect_companies.props`; `objects.sql_expr` / `store._sort_value` la leen con `storage="props"`,
  `store.flatten_company()` la aplana en listas, ficha, export y `engine.load_company`).
  **Cómo llega al código**: `properties.refresh(cur)` reconstruye EN EL LUGAR `FIELDS`,
  `FIELDS_BY_KEY`, `EDITABLE_FIELDS` (ahora lista), `CONTACT_FIELDS*`, `DEAL_FIELDS*`, los grupos y los
  sets de `objects.OBJECTS`, desde una copia del catálogo de código + la tabla. Lo llama `_Db` en cada
  request (una consulta compara versión; sólo reconstruye si cambió, así se enteran todos los
  workers). **No copies esos catálogos a otra estructura al importar**: no se actualizaría. Los
  scripts sueltos (importaciones) no pasan por `_Db` y ven sólo el catálogo de fábrica.
  - Al pasar a desplegable un campo que ya tiene datos, la lista se precarga con los valores existentes.
  - **Obligatoria frena sólo lo manual** (decisión de la owner): `check_create` / `check_patch` en las
    rutas de alta y PATCH de empresa / contacto / negocio y en la edición masiva (no deja VACIAR una
    obligatoria; lo que ya faltaba no frena). Clay, HubSpot, Calendly, workflows y `prop_sync` no.
    No reemplaza `REQUIRED_ON_QUALIFIED` ni `STAGE_FORMS`.
  - **Desplegables**: un desplegable de empresa se valida contra su lista sólo a mano
    (`update_company(validate=True)`); Clay/HubSpot guardan lo que llegue y se ve igual. En contactos y
    negocios la lista valida siempre (como antes): si se quita una opción, el sync de HubSpot descarta
    ese valor (`avisos`). Las opciones editadas de un negocio ganan sobre las de HubSpot
    (`options_locked` en `deals.field_defs`). Renombrar / unificar opciones (`renames`) hace UPDATE de
    los registros con un evento `source='property_edit'` por registro, sin disparar workflows; los
    filtros de workflows/vistas que nombraban el valor viejo NO se reescriben (la respuesta los lista).
  - **Las de fábrica no se borran, se ocultan** (siguen en el catálogo con `hidden`, así los workflows
    que las usan siguen validando). Las que el código usa a mano (`properties._locked_keys()`: BDR_FIELDS,
    `prop_sync.LINKS`, `PREFILL`, `STAGE_FORMS`, `REQUIRED_ON_QUALIFIED`, columnas…) no se ocultan ni
    cambian de tipo; las opciones de `prospecting_status` no se editan. Una nueva se borra (archiva) sólo
    si ningún workflow ni vista guardada la nombra (`usages()`, 409). Claves nuevas: slug único entre los
    tres objetos, fijo aunque se renombre.
  - En el front: columnas de empresa por catálogo (`syncCompanyColumns()` en `prospecting.js`; las nuevas
    se editan en la celda), tarjeta **Propiedades** en la vista rápida y la ficha
    (`ProspectingContacts.companyPropsHtml/companyPropsPatch`, con Lead Source), y el alta de empresa
    pide las nuevas y las obligatorias (`extraCompanyFields()`).
