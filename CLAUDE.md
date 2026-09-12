# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository shape

Three deployables live side-by-side, and understanding which one you're touching is the single most important thing:

- **`backend/`** — Flask API (Python). Deployed on AWS App Runner at `https://7m6mw95m8y.us-east-2.awsapprunner.com`. Both the legacy `docs/` site and the new React SPA call this same origin.
- **`frontend/`** — Vite + React 19 SPA. The eventual replacement for `docs/`. Entry at `src/main.jsx` → `src/App.jsx`.
- **`docs/`** — Legacy static HTML/CSS/vanilla-JS site served via GitHub Pages at `vinttihub.vintti.com` (see root `CNAME`). Being migrated page-by-page into the React app; both coexist in production today.

The React SPA deliberately reuses `docs/assets/css/style.css` and keeps the same element IDs/classes so styling is shared during migration. `src/hooks/usePageStylesheet.js` dynamically injects a `<link>` per page for this purpose. When porting a page, preserve IDs/classes and translate the paired `docs/assets/js/<page>.js` into hooks/effects — see `frontend/README.md` for the full migration recipe.

## Common commands

### Frontend (from `frontend/`)
```bash
npm install
npm run dev      # Vite dev server on http://localhost:5173
npm run build    # Production bundle
npm run lint     # ESLint (flat config, eslint.config.js)
npm run preview
```
Note: `frontend/.npmrc` forces HTTP to bypass a local TLS MITM issue — remove once fixed.

### Backend (from `backend/`)
```bash
pip install -r requirements.txt   # loose deps; root requirements.txt has full pins
python app.py                     # runs on $PORT or 8080
```
No test suite is wired up in either frontend or backend.

### Database migrations
SQL migrations live in `backend/sql/` as dated files (e.g. `20241112_add_google_calendar_tokens.sql`). There is no migration runner — run them manually against the RDS instance when merging a PR that depends on one.

## Backend architecture

Entry point is `backend/app.py::create_app()`. It:
1. Loads `backend/.env` via `python-dotenv`.
2. Calls `utils.services.init_services()` to initialize the OpenAI, Affinda, and boto3/S3 clients from env vars. **Anything that touches these clients must run after `init_services()`** — don't import-time-bind them at module top level.
3. Registers two styles of route modules, both of which you'll see mixed together:
   - **Newer split** — `backend/routes/*.py`, each exposing a `bp = Blueprint(...)` registered with `app.register_blueprint(...)`.
   - **Older monolithic files at `backend/`** (e.g. `ai_routes.py`, `recruiter_metrics_routes.py`, `reminders_routes.py`, `profile_routes.py`, `reset_password.py`, `send_email_endpoint.py`, `interviewing_routes.py`, `ai_candidate_search_routes.py`, `admin_routes.py`, `coresignal_routes.py`, `hunter.py`). Several expose `register_*(app)` functions instead of blueprints — call them from `create_app()`.
   When adding a route, match the style of the module you're extending rather than refactoring across the split.

### Database access
`backend/db.py::get_connection()` returns a raw `psycopg2` connection to the shared RDS Postgres instance. **Credentials are hardcoded in that file** — do not move them without coordinating, and do not print/commit them in error messages or logs. Every route opens its own connection and is responsible for closing it; there is no pool or ORM. Login (`routes/auth_routes.py`) joins `users` against `admin_user_access` to gate inactive accounts.

### External integrations
Third-party clients and helpers are grouped under `backend/utils/` and `backend/routes/`:
- HubSpot CRM sync (`utils/hubspot.py`, `routes/hubspot_routes.py`) — recent work; see recent commits for the sync flow.
- Google Calendar OAuth (`utils/google_calendar.py`, `routes/google_calendar_routes.py`). Requires env vars `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, optional `GOOGLE_CALENDAR_SCOPES`, and the `20241112_add_google_calendar_tokens.sql` migration applied.
- Turvo (`routes/turvo_routes.py`), Coresignal (`coresignal_routes.py`), Hunter.io (`hunter.py`), Affinda resume parsing, OpenAI (for AI routes + candidate scoring in `utils/applicant_matching.py` and `utils/credit_loop.py`), SendGrid email (`send_email_endpoint.py`), S3 for uploads (`utils/storage_utils.py`), Google Sheets (`utils/sheets_utils.py`).

### CORS
`create_app()` configures `flask-cors` to allow only `https://vinttihub.vintti.com`, and the `after_request` hook additionally allows `http://localhost:5500` / `127.0.0.1:5500` (the static-site dev setup for `docs/`). **Vite's default `localhost:5173` is not allowed** — when running the React SPA against the deployed backend locally, either add an origin here, use a proxy in `vite.config.js`, or change the Vite port to 5500. Don't silently widen CORS in commits.

## Frontend architecture

- Routing is centralized in `src/App.jsx`. Unmatched routes redirect to `/` (login). `src/pages/redirects/*` provides bridges from SPA paths to the legacy `docs/` pages that haven't been migrated yet.
- API base URL is a single constant: `src/constants/api.js` → `API_BASE_URL`. All `src/services/*.js` modules hit that origin. Keep request/response shapes 1:1 with the legacy JS so the React and static versions can coexist.
- Auth state lives in `localStorage` (`user_email`, `user_id`, `user_id_owner_email`) — see `src/services/authService.js` and `userService.js`. There is no token; the app is behind a simple email/password check that returns a success flag.
- `src/components/` holds shared UI, `src/pages/<area>/` holds route-level screens, `src/services/` holds fetch wrappers, `src/utils/` holds pure helpers (formatting, avatars, resume PDF generation via `pdf-lib`).

## Things that surprise people

- The two `requirements.txt` files are not redundant: root is a fully pinned list (used where reproducible installs matter), `backend/requirements.txt` is a loose list suitable for local dev. Update both when adding a backend dep.
- `backend/.env` is gitignored and must exist for `init_services()` to populate clients. Missing env vars silently leave clients as `None` rather than raising — expect `AttributeError` on first use if you forgot to set one.
- The repo root also contains `icons/` and `docs/assets/` which are static assets served by GitHub Pages, not part of any build step.

- Don´t work on the frontend file, everything that is related to React, Do not touch the files

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

## Sync HubSpot → Opportunities

`POST /hubspot/sync/opportunities` (en `backend/routes/hubspot_routes.py`) refleja en el hub
el movimiento de los deals de los dos pipelines de HubSpot. Lo dispara
`.github/workflows/hubspot-opportunity-sync.yml` cada 30 min y el botón **Sync HubSpot**
de `docs/opportunities.html`.

| HubSpot | Hub |
|---|---|
| Intro Call → **Deep Dive** | crea la opportunity (`Role to hire` → `opp_position_name`, `Model` → `opp_model`, `opp_type='New'`) |
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
  `link_candidates`: las opps de esa cuenta sin deal atado, con Close Win adentro y Closed
  Lost/Stop afuera, ordenadas por `hs_opps.position_similarity()`. **Ese puntaje sólo ordena,
  no decide nada** — no hay umbral en ningún lado.
- El botón **Simular** de `docs/opportunities.html` pinta el reporte con un `<select>` por fila;
  **Vincular** pega `POST /hubspot/opportunities/<id>/link-deal`, que escribe **sólo** las tres
  columnas `hubspot_*`. El stage y las fechas las sigue decidiendo el sync siguiente vía
  `decide_stage_transition()` — moverlas desde acá saltearía `_unmark_signed_hire_active`.
  `POST .../unlink-deal` deshace un click equivocado.

### El cron no crea si hay candidata: la freca y espera

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
- **Un mail por deal frenado, una sola vez.** Sólo por los que tienen `notified_at IS NULL`,
  reclamados con un `UPDATE ... RETURNING` para que dos corridas solapadas no lo dupliquen. Sin
  frenos nuevos no sale ningún mail: avisar por los que siguen esperando serían 48 mails
  iguales por día. Destinatarios hardcodeados en `RECIPIENTS` de `utils/hubspot_waiting_alert.py`
  (`pgonzales@` + `mariano@`), mismo criterio que el auditor.
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
| **Expected Set Up Fee** | `fee` (el "Set Up Fee" de Opportunity Detail) | ninguno |

`opportunity.fee` NO es el fee del MRR: ese sale de `hire_opportunity.fee`, y ningún
dataset lee `o.fee` (cuidado al grepear: `o\.fee` también matchea `ho.fee`).
Ojo que `expected_set_up_fee` y `set_up_fee` son propiedades DISTINTAS de HubSpot
(esperada en NDA Sent vs final en Closed Win) y van a columnas distintas.

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

Fechas: `hs_v2_date_entered_<stage>` → `deep_dive_date` / `nda_sent_date` /
`nda_signature_or_start_date`. HubSpot **pisa** el `CURRENT_DATE` que estampó el hub, pero nunca
borra (`COALESCE`). Ojo que `nda_signature_or_start_date` es ancla de ~10 datasets.

**HubSpot no tiene propiedad de fecha para las dos etapas "NDA Sent"** (ids
`1429477933` y `1429487919`, agregadas después que el resto): no existe el
`hs_v2_date_entered_*` correspondiente. Para esas, el sync estampa la fecha en que
detecta el cambio — misma semántica que el `CURRENT_DATE` del hub al mover el stage a
mano — y lo marca como `fechas_inferidas` en el reporte para no hacerlo pasar por dato
de HubSpot. Sólo aplica a la etapa donde el deal está parado: si saltó de Deep Dive a
NDA Signed no se inventa un `nda_sent_date`.

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