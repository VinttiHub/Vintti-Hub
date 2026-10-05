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

**Libro de hechos (cruce entre cards distintas)**: las reglas de arriba comparan cada
card con SU drawer, y por eso no vieron que Restor (baja 30-sep) era churn de septiembre
en Client churn y de octubre en el CRR (2026-10-02). `ledger.py` corre cada detalle
etiquetado mes por mes (6 meses) y lo compara contra los hechos que `canon.py` calcula
directo de las tablas base: `hecho_mes_distinto` / `hecho_faltante` / `hecho_sobrante`.
Cada detalle declara una etiqueta `"audit"` en su `DATASET` (hecho, columna del cliente,
qué filas, y qué flags de `canon.FLAGS` **excluye por criterio decidido**: replacement
vivo, buyout, alta y baja en el mismo mes…). Sumar una card al cruce = ponerle la
etiqueta; una familia nueva = una función en `canon.CANON`. Hoy cubre
`cliente_baja` (Client churn + CRR) y `contractor_baja` (churn de contractors, NRR
global/AM, motivos de baja, Churn → Replacement, inactivos de Growth); el resto de los
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
- **Los buyouts se netean, no son churn** (2026-10-05, en los dos NRR). Si una unidad se
  va dentro de la ventana por buyout (`buyout_d >= mes de la baja`, el criterio de Client
  churn y de `canon.py`), sale **de la base y del churn a la vez**: el NRR arranca como si
  no hubiera estado. El cliente pagó el buyout, y de este NRR salen las comisiones del AM —
  Eduardo Salazar (AMPL, buyout 2026-09) le restaba $5K. Va aparte en el componente
  `buyouts`, **fuera del cociente** (CTE `nrr_buyouts` en `_nrr_decomp.py`), con su
  tarjeta en los dos drawers. Consecuencia: `mrr_inicial` del mes M **ya no** es el GMRR
  del cierre de M−1, le faltan justo los `buyouts`. El CRR sigue contando el buyout como
  churn: no se cambió ahí. Las etiquetas `audit` de los 4 detalles excluyen el flag `buyout`.
- **El tile muestra la FECHA de esa base** (campo `base_fecha`, "23-ago"). Sin ella se
  lee como si fuera el GMRR de hoy y no cuadra con el tile de al lado: con corte
  22-sep, GMRR · AM da $237,4K y la base del NRR $208,1K, que es el GMRR · AM del
  23-ago. Es el mismo indicador en dos fechas — el `+14% vs 30d` del propio tile es ese
  salto — pero sin la fecha a la vista parece un error de cálculo (reportado por la
  owner el 2026-09-22).

En el NRR del AM hay un séptimo componente, **`entradas_m3`**: lo que entró al libro
porque venció el M3 del AE. Va **fuera del cociente** a propósito — es un traspaso, no
algo que hizo el AM. No es marginal: en septiembre de 2026 eran $28.8K contra una base
de $228K, así que contarlo como expansión subiría el NRR del AM de 94% a ~107%.

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
  los 16 datasets). Si cambiás el corte, cambialo en los dos archivos. **El tab Marketing NO
  se tocó**: sigue leyendo Meeting Date & Time en vivo de los contactos.

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

Hasta el 2026-09-14 las cerradas quedaban afuera de `link_candidates` y `/link-deal` las
rechazaba con 409, con el argumento de que el sync no podría moverlas igual. Era al revés:
cuando la gemela Closed Lost era la **única** opp de la cuenta, la lista volvía vacía, el
freno leía esa lista vacía como "no hay nada que consultar" y el sync **creaba en silencio**,
sin mail y sin panel. Así nacieron 9 duplicadas entre el 11 y el 14 de septiembre (Flamingo,
Dolsten, Advisant, Rodgers, Catchy, The Art of Broth, The Email Marketers, Arcady, PQ Meats).

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

Fechas: `hs_v2_date_entered_<stage>` → `deep_dive_date` / `nda_sent_date` /
`nda_signature_or_start_date`. En una opp abierta **gana la más temprana** (`LEAST`): HubSpot
rellena o adelanta la fecha del hub, **nunca la atrasa**. En una cerrada sólo rellena los NULL.
Ojo que `nda_signature_or_start_date` es ancla de ~10 datasets.

Hasta el 2026-09-23 HubSpot pisaba siempre, y eso hacía que las fechas "cambiaran solas".
`hs_v2_date_entered_*` es cuándo el AE hizo click y guarda la **última** entrada, así que:

- El 11-sep se pusieron al día varios deals de una vez en HubSpot y la NDA Signed de la 782
  pasó del 26-ago al 11-sep. Del mismo lote, 730, 761, 788, 795 y 800 tienen 11-sep y la fecha
  real es desconocida: la tiene que confirmar la recruiter.
- El 17-sep, deshacer un push de prueba volvió 8 deals a NDA Signed, y la 780 quedó "firmada" un
  día antes del cierre. Las otras 5 Close Win las restaura
  `backend/scripts/restore_nda_dates_20260917.py`.

Una carga tardía, un retroceso o una prueba en HubSpot siempre producen fechas más nuevas: con
`LEAST` ya no pueden atrasar nada.

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
- **"Todas las opps atadas ya tienen foto" era falso.** La regla de arriba se deployó
  horas después de crear la columna, y el sync es incremental: sólo mira un deal cuando
  alguien lo toca en HubSpot. 808 y 825 quedaron en NULL, el 24-sep se movieron de stage y
  el sync les pisó el Recruiting de la recruiter con Staffing. Parecía que "cambiar de
  stage en HubSpot pasa la opp a Staffing": el stage no era la causa, sólo hizo que el sync
  mirara el deal. El historial de HubSpot (`propertiesWithHistory=model`) muestra que en
  esos deals el Model **siempre** fue Staffing, cargado por el AE en el popup del Deep
  Dive. `backend/scripts/backfill_hubspot_model_seen.py` (dry-run por defecto) saca la
  foto de las que quedaron en NULL sin tocar `opp_model`.
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
  cambiaría la marca de CVs ya enviados: eso lo decide una persona.
- Se aplica en las dos ramas de `_process_hubspot_deal` (opp nueva y opp existente), porque las
  9 opps del pipeline de AI son anteriores al cambio y nunca pasan por la rama de creación de
  cuenta. Ojo que en la rama de opp existente va **después** de `changed = False`, o el reset se
  come la marca.

El fallback del frontend (`workspace.js: matchRecord`, "si no sé si es AI, mirá si el sales lead
es mia@vintti.com") sigue siendo **código muerto**: la columna es `NOT NULL DEFAULT FALSE` y la
query hace `COALESCE(a.vintti_ai, FALSE)`, así que nunca llega un `null` y el fallback no corre
jamás. Se dejó así a propósito: ahora la marca la pone el sync, que es una sola fuente de verdad.

### La URL de App Runner hardcodeada rompe TODA prueba local

`docs/assets/js/main.js` define `API_BASE` con detección de localhost (línea ~875),
pero hasta el 2026-09-17 tenía **23 fetch con la URL de App Runner escrita a mano**,
incluidos los dos que más importan: `patchOpportunityStage()` y `patchOppFields()`.
Lo mismo en `candidate-details.js` con `API_CANDIDATES`.

El síntoma es cruel: la página corre en `localhost`, el backend local está levantado
y **el request se va a producción igual**. Todo "funciona" —el stage cambia, el campo
se guarda— pero lo atendió el código viejo de App Runner. Costó una tarde entera de
debugging del sync inverso: el botón "Enviar a HubSpot" andaba (usa
`candidatesApiBase()`) y el cambio de stage no (iba a prod), y parecía un problema de
proceso local sin reiniciar.

Ya están todos pasados a `${API_BASE}` / `candidatesApiBase()`. **Si agregás un fetch
nuevo, usá la constante.** La única excepción a propósito es `SEND_EMAIL_ENDPOINT`:
manda mails reales y no conviene que una prueba local los dispare por otra ruta.

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
`1437034145` y `1436968304`) y hasta el 2026-09-16 no estaba en `STAGE_ALIASES`, así que un deal
parado ahí caía en `unmapped_stage` y el sync entrante lo salteaba entero. No molestaba porque
no lo usaba nadie. Ahora está mapeado; `"signed"` va **después** de `"nda_signed"` en
`STAGE_RESOLUTION_ORDER` porque en la pasada por tokens `{signed} ⊆ {nda, signed}` y el alias
suelto se comería "NDA Signed". Tampoco tiene `hs_v2_date_entered_*` (404 verificado), igual que
las dos etapas "NDA Sent".

El loop entre las dos direcciones está acotado: cuando el hub empuja Closed Win, el sync
entrante lo lee como `closed_won` y `STAGE_KEY_TO_HUB_STAGE["closed_won"] = None`, así que **no
mueve el stage del hub**. Sí vuelve a copiar los 5 espejos con los valores que acabamos de
mandar — circular, pero inofensivo: ningún dataset lee esas columnas.

## Apriora: las 6 preguntas obligatorias de screening

El botón **Create Job in Apriora** de `docs/opportunity-detail.html` (pestaña Job Description)
crea la entrevista vía `POST /opportunities/<id>/alex/create_position`. Toda entrevista creada
desde el Hub lleva 6 preguntas fijas de screening + el criterio de inglés C1. La definición
única está en **`backend/utils/alex.py::APRIORA_SCREENING_QUESTIONS`**: de ahí salen el template
de Apriora, el fallback por `additionalQuestions` y la verificación posterior. Tocar una lista y
no la otra es el error a evitar.

**`additionalQuestions` es una sugerencia, no un mandato.** La doc de Apriora lo dice literal
("optional free-text questions to *append* to the generated interview") y se comprobó contra las
31 positions que creó el Hub: las reescribe (la opp 799 preguntó "Are you *currently*
participating in other *hiring* processes?"), las intercala aunque se mande
`intelligentlyOrderQuestions=false` (la opp 800 las tiene en las posiciones 1, 2, 3, 6, 7 y 9), y
**a veces dropea una**: la opp 792 quedó sin la de la computadora propia en sus 10 entrevistas.
Es a nivel del guion generado, no algo que Alex saltee por tiempo — todos los candidatos de una
position reciben exactamente las mismas preguntas.

Por eso el camino bueno es un **interview guide template** (`POST /templates`), donde las
preguntas son parte del guion y no sugerencias:

```bash
cd backend
python scripts/create_apriora_template.py            # dry-run: imprime el payload
python scripts/create_apriora_template.py --apply    # lo crea
```

El id que devuelve va a la env **`APRIORA_TEMPLATE_ID`** (`backend/.env` **y** App Runner).
Sin esa env el Hub sigue por el camino viejo, así que un deploy sin setearla no rompe nada —
pero tampoco arregla nada.

Tres cosas que no son obvias:

- **`/templates` sólo tiene GET y POST.** No hay PATCH ni DELETE, y el `name` es único por
  company. Cambiar una pregunta = template nuevo con otro nombre + repuntar la env. Lo mismo
  vale para las positions: `createJob` rechaza `externalJobId` duplicado y no existe update, así
  que una entrevista mal generada sólo se arregla **borrándola a mano en la UI de Apriora** y
  volviéndola a crear desde el botón.
- **Con template no se manda `additionalQuestions`** (se harían dos veces) ni se llama a
  `append_grading_criteria()` sobre la JD: el C1 pasa a ser un `criteria` de verdad, con
  `priority`, en vez de un bloque de texto pegado al final de la job description.
- **`questionLimit` no se setea.** La doc dice que `0` "adds none beyond the template questions":
  pondría en cero las preguntas del rol que Apriora genera desde la JD, que son el grueso de la
  entrevista.

### Verificar que efectivamente las hizo

`GET /opportunities/<id>/alex/question_check` cruza las 6 contra lo que se preguntó de verdad y
lo pinta un badge en la pestaña **Pipeline** (`#apriora-question-check`, lo llena `pipeline.js`).
Dos caminos de match, porque hay dos generaciones de positions:

- **Por tag**, exacto, para las creadas con el template: los nombres de los tags los fijamos
  nosotros. **Un tag sin valor no cuenta**: Apriora lo crea igual y lo deja en `null` cuando la
  pregunta no llegó a hacerse (la opp 776 tiene `US Citizenship = null` y en sus 14 preguntas no
  hay ninguna de ciudadanía).
- **Por texto** (regex sobre `questionSummary`) para las anteriores, calibrado contra las 31
  positions reales. Sin template Apriora **se inventa el nombre del tag en cada entrevista** — la
  misma pregunta salía como "Planned Absences", "Planned Time Off" y "Planned Vacations" — así
  que ahí el tag no sirve de clave.

Sólo se puede responder cuando hay **al menos una entrevista completada**: `questionSummary` no
existe antes, y no hay ningún endpoint que devuelva el guion de una position. Como el guion es
idéntico para todos los candidatos, con el primero alcanza — y conviene, porque arreglarlo
implica rehacer la position. La respuesta se cachea en `app_cache` (1 h con entrevistas hechas,
2 min sin ellas): `list_reports` no está cacheado y el de la opp 792 son 200 KB.

### El fallo del createJob ya no es mudo

`create_position` devuelve **202 antes de que arranque el hilo** que hace el `createJob` (Apriora
tarda ~1-2 min). Hasta el 2026-09-16 la excepción moría en un `logging.warning` y
`apriora-notifier.js` se rendía a los 8 minutos **sin decir nada**, con la lista de pendientes en
`localStorage` (o sea que además moría al cerrar la pestaña). Resultado: la entrevista nunca
creada parecía estar generándose para siempre. Así fue como la opp 790 terminó cargada a mano en
la UI de Apriora sin que nadie supiera que el botón había fallado.

Ahora cada intento queda en **`apriora_job_creations`** (`pending` → `ok` | `error`, se autocrea
con `CREATE TABLE IF NOT EXISTS`, sin migración a mano), `GET /opportunities/<id>/alex/create_status`
la expone, y el notificador muestra el error real de Apriora en vez de callarse.

Contexto que conviene tener a mano: de las **348 positions** que hay en Apriora sólo **31** tienen
`externalJobId`, o sea salieron del Hub. Las otras 317 se crearon a mano en la UI y promedian
**2 de 6** preguntas obligatorias. El template las arregla sólo si la recruiter lo elige al crear
la job, o si se lo pone como default de la company — y eso se hace en Apriora, no acá.

## JD Review: el CV Review, pero para la Job Description

La JD (`opportunity.hr_job_description`) la escribe gpt-4o desde los transcripts de Grain de la
Intro Call y la Deep Dive (`POST /ai/generate_jd`) y nadie la contrastaba con lo que se habló.
Circuito: la recruiter aprieta **Send JD to review** en la pestaña Job Description de
`docs/opportunity-detail.html` (lógica en `jd-review-opp.js`, aparte de opportunity-detail.js) →
`POST /opportunities/<id>/jd_reviews` congela la JD → un hilo trae los transcripts de los links
guardados en la opp (`first_meeting_recording` / `deepdive_recording`), los congela en
`transcript_snapshot` y scorea → mail al sales lead (o al HR lead) + `OVERSIGHT_EMAILS` → el sales
lead decide en `docs/jd-review.html`.

- Backend: `routes/jd_review_routes.py`, `jd_review_store.py` (tablas `jd_reviews` +
  `jd_review_checklist`, se autocrean como las de cv_reviews), `utils/jd_review_ai.py`.
- **Quién revisa se importa de `cv_review_routes`** (`_require_reviewer`, `OVERSIGHT_EMAILS`): una
  sola lista. En el front, `jd-review.js` y el link del sidebar usan la misma allow-list que CV Review.
- **No hay "rejected"**: una JD no se descarta, se corrige. Aprobar o pedir cambios, con checklist
  obligatorio (ítems de `CHECKLIST_ITEMS` o "clean") y comentario obligatorio al pedir cambios.
- **El juez son dos llamadas separadas a propósito**: primero se extraen los hechos de los
  transcripts SIN ver la JD (para que no se acomode a lo que la JD ya dice), después se juzga cada
  hecho contra la JD (covered / partial / contradicted / missing) + lo que la JD dice y nadie dijo
  (`unsupported`, hard/soft).
- **El número lo calcula `compute_score()`, no el modelo**: core pesa 2, nice 1; partial = medio;
  −5 por contradicción y −5 por requisito inventado "hard" (tope 20 cada uno). El relleno "soft" se
  muestra pero no resta. Subir `ANALYSIS_VERSION` saca los análisis viejos del promedio.
- **La lista de puntos se guarda y se reusa** (tabla `jd_review_facts`, clave = vacante + huella
  de los transcripts + `EXTRACT_VERSION`). Re-extraer en cada corrida agrupaba distinto las tareas
  y el score saltaba ±10 con la misma JD (opp 844: 68 y 80); reusándola, tres corridas dieron 78,
  78, 78. Las rondas siguientes y **Retry the analysis** reusan la lista (Retry sólo aparece si el
  análisis falló o no se pudo leer alguna grabación: sin error daría lo mismo); cambia sola si cambian los links/transcripts,
  y **Rebuild the list of points** (`POST .../analyze {"rebuild": true}`) la rehace a mano.
  **Rebuild re-scorea TODAS las rondas no canceladas de la vacante** contra la lista nueva
  (incluso las ya decididas, y con eso el score del primer envío que usa la métrica): si sólo se
  re-scoreara la actual, la ronda 1 y la 2 quedarían medidas con varas distintas. La lista queda
  firmada (`rebuilt_by` / `rebuilt_at` en `jd_review_facts`) y el drawer lo muestra en ámbar. Lo
  pueden usar los sales leads, no sólo la supervisión (decisión de la owner, 2026-09-25). Si tocás
  el prompt del extractor, subí `EXTRACT_VERSION` o se siguen usando las listas viejas.
- **El salario nunca se exige con monto** (decisión de la owner, 2026-09-25, v2): en la JD no va
  cuánto se gana, así que un punto de salario cuenta como *covered* si la JD menciona la paga de
  cualquier forma ("competitive salary", bonos). Se fuerza en código (`is_salary` + `_SALARY_RE`),
  no sólo en el prompt, porque el juez igual lo marcaba *partial*.
- **El estado de cada punto lo deriva el código, no el juez** (v5, 2026-09-25): el EXTRACTOR parte
  cada punto en partes atómicas ("full-time contractor" = full-time + contractor; una lista = un
  ítem por parte), el juez sólo marca cada parte `explicit` / `implied` / `no`, y
  `derive_status()` decide: todas → covered, algunas → partial, ninguna → missing. Con criterio
  libre (v3) y con el juez partiendo (v4) el mismo caso de la opp 844 salía missing una corrida sí
  y otra no, aunque la JD dijera "9 to 5" (que implica full-time).
- **La cuenta del score la arma `compute_score()`** (`points` / `max_points` / `penalty` por punto,
  `breakdown` / `earned` / `possible` en el resumen) y la página sólo la muestra: no hay una
  segunda copia de la fórmula en el JS.
- Sin links de Grain la ronda se crea igual con `ai_error='no_transcripts'` y el mail lo dice. Si
  el campo del link tiene un transcript pegado (pasó), se usa como texto.
- El popup del AI Assistant ahora precarga los links guardados, y si la opp no los tenía guarda
  los que se usaron para generar (sólo si el campo está vacío).
- **Editar la JD re-califica los CV Reviews `pending` de esa vacante** (2026-09-29, pregunta
  sobre la opp 799). `PATCH /opportunities/<id>/fields` con algún campo del bloque del juez
  llama, después del commit, a `cv_review_routes.rescore_pending_for_opportunity()`: un hilo
  que re-scorea el snapshot enviado sólo si `_jd_hash` difiere de la JD actual (el blur guarda
  aunque no cambie nada). Los decididos **no** se tocan: el score de la 1ª ronda es la métrica
  de la recruiter. Esos siguen con el aviso ámbar + Re-run manual. El bloque lo arma sólo
  `_current_jd_block()`; si se arma distinto en otro lado, la huella deja de ser comparable.
- Métricas: `GET /jd_reviews/metrics` (sección "Per recruiter" de jd-review.html y pestaña **JD
  quality** de Recruiter Power, las dos con la tarjeta de `jd-review-cards.js`). Una vacante cuenta
  una vez, en el período de su primer envío.

## Second Interview: recordatorio de referencias cada 24 h

La 6ª columna del Pipeline de `docs/opportunity-detail.html` es **Second Interview**
(`opportunity_candidates.stage_pipeline = 'Segunda entrevista'`, última en `stageOrder` de
`pipeline.js`). Al entrar ahí, `PATCH /opportunities/<id>/candidates/<cid>/stage` llama
`start_second_interview_refs_reminder()` (**después del commit y nunca levanta**) y sale un
mail a `agostina@vintti.com` + `opp_hr_lead` para que pidan y carguen las referencias.
Toda la lógica vive en `backend/utils/second_interview_refs.py`.

- **Se repite cada 24 h hasta que la recruiter marca "References filled"** en la Overview de
  `candidate-details.html` (`candidates.references_filled`, por candidato). También se corta
  si el candidato sale de la columna (`left_stage`). Si vuelve a entrar, la fila se reabre.
- **`references_filled` NO es `check_hr_lead`.** Ese ("All set: resignation letter &
  references") corta el recordatorio de Signed, que pide además la carta de renuncia.
  Reusarlo lo apagaba de antemano (decisión de la owner, 2026-09-29).
- **Cron propio y horario**: `.github/workflows/second-interview-references.yml` →
  `POST /reminders/second_interview_refs/due` con `X-Audit-Token` (= `DASHBOARD_AUDIT_TOKEN`).
  Las 24 h las mide `second_interview_refs_reminders.last_sent_at`, no el cron. No va dentro
  de `/reminders/due` porque ese sólo corre en la ventana 05:00-07:59 de Guatemala y el cron de
  GitHub llega ~4 h tarde: casi nunca manda nada (así está roto hoy el recordatorio de Signed).
- **Sábado y domingo (hora Argentina) no manda**: se posterga al lunes (`alerta_en_pausa()`).
  El primer mail sí sale al instante aunque sea fin de semana, porque lo disparó una persona.
- Un primer envío fallido (`last_sent_at` NULL) se reintenta en la próxima corrida.
- Esquema autocreado (columna + tabla), sin migración a mano. `?dry=1` lista los vencidos.
- Modo prueba: `TEST_ONLY_RECIPIENT` en el módulo (hoy `None` = producción). Con un email ahí,
  todo va sólo a esa dirección con `[TEST]` en el asunto y un aviso de a quién habría ido.

## Perfil incompleto: recordatorio diario hasta completarlo

Cada persona activa (`COALESCE(admin_user_access.is_active, TRUE)`) a la que le falte
**Address, Emergency Contact, Date of Birth o Vintti Start Date** en `docs/profile.html`
recibe un mail en su `email_vintti` cada 24 h, sin CC. Todo en
`backend/utils/profile_completion_reminder.py` (`REQUIRED_FIELDS` es la única lista).

- **El corte es por construcción**: el runner mira `users` en cada corrida; quien guarda los
  4 campos desde su perfil deja de salir solo. `profile_completion_reminders` sólo lleva
  `last_sent_at` (las 24 h) y sella `completed_at` como registro.
- **Vacío incluye `''`**: `profile.js` guarda Emergency Contact en blanco como `''` (los 13
  que faltaban al 2026-09-29 eran todos `''`, ninguno NULL).
- Cron horario `.github/workflows/profile-completion-reminder.yml` →
  `POST /reminders/profile_completion/due` con `X-Audit-Token`; `?dry=1` lista a quién le toca.
  Sábado y domingo (hora Argentina) no manda.
- Modo prueba: `TEST_ONLY_RECIPIENT` en el módulo (hoy `None` = producción, desde el
  2026-09-29). Con un email ahí, todo va sólo a esa dirección con `[TEST]` en el asunto.

## Cumpleaños → calendario "Birthdays/ Team Personal Stuff"

Al guardar **Date of Birth** en `docs/profile.html`, `update_user` (`profile_routes.py`)
dispara, **después del commit y en un hilo**, `sync_birthday_event_async()`: el hub crea el
evento anual (día completo, `transparent`, invita a `team@vintti.com`, título
`Cumple <nombre> :)` para todos: el hub no guarda género) o lo mueve si cambió la fecha. Todo en `backend/utils/birthday_calendar.py`.

- **Escribe con el Google de Jazmín** (`CALENDAR_OWNER_EMAIL`, token de
  `google_calendar_tokens`), no con una cuenta de servicio. Sin su token no se crea nada: el
  panel muestra **Connect Google Calendar** y el mail semanal lo avisa. El calendario se busca
  por nombre en su `calendarList`.
- **Nunca duplica un manual.** Antes de crear busca eventos de cumpleaños (`_BIRTHDAY_RE`) del
  mismo día del año: si el título tiene un prefijo del nombre ("Agos" ⊂ "Agostina") lo
  **adopta** sin tocarlo (`source='adopted'`); si hay uno ese día con otro nombre, o uno con su
  nombre en otro día, queda **review** y no se crea. Un adoptado con fecha distinta tampoco se
  mueve solo: es de Jazmín.
- **Google devuelve cada cumple manual dos veces**: con `singleEvents=False` vienen la serie y
  sus excepciones (una ocurrencia a la que alguien respondió) con `recurringEventId`. Se
  descartan, y dos series iguales el mismo día cuentan como una. Sin eso todos los manuales
  caían en review ("Cumple Agos <3, Cumple Agos <3").
- **Nombres repetidos**: un evento con su nombre en otro día sólo frena si ese día no cumple
  nadie del hub (activo o no); "Cumple Vale" del 18-ago es de otra Valentina. Y un evento del
  MISMO día que nombra a otra persona que cumple ese día es suyo ("Cumple Mia" no frena a
  Benjamin, los dos el 7-mar). Si el nombre/nickname se repite entre activos, el título lleva
  apellido: "Cumple Valentina Cadirola :)" (`_display_name`). Lo que quede en
  review se destraba con **Create anyway** (`POST /birthdays/sync/<id> {"force": true}`).
- **Una baja borra el cumple** (pedido de la owner, 2026-09-30): `_deactivate_endpoint` de
  `admin_routes.py` llama `remove_birthday_event_async()` después del commit. Borra la serie
  entera, **también si era un evento manual**, con `sendUpdates="none"`: desaparece de los
  calendarios de todos sin mandar un "Canceled event" que anuncie la baja. Nunca borra un
  evento registrado a nombre de alguien activo ni uno que nombre a una persona activa que
  cumple ese día. Las bajas anteriores salen en el panel ("No longer at Vintti, still in the
  calendar") con **Remove** y en el mail semanal. No hay ruta de reactivación: si alguien
  vuelve, su cumple se recrea con Create desde el panel.
- Mapeo persona → evento en `birthday_calendar_events` (autocreada). Si borran el evento en
  Google, la fila se suelta sola en el próximo sync.
- Detección: pestaña **Birthdays** de profile.html (sólo `PANEL_EMAILS` = jazmin + pgonzales,
  igual a `BIRTHDAY_PANEL_EMAILS` de profile.js) con los próximos 30 días y quién no tiene
  fecha, + mail semanal a Jazmín (`.github/workflows/birthday-weekly-report.yml` →
  `POST /reminders/birthdays/weekly`, X-Audit-Token; `birthday_report_log` = 1 por semana).
- `POST /birthdays/backfill` es **dry-run por defecto**; el botón "Preview full sync" lo muestra
  y "Create missing events" lo aplica. Arranque: Jazmín conecta → preview → aplicar.

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
## Slack: opps de Mariano paradas +20 días en Deep Dive / NDA Sent

`backend/utils/stale_opps_slack.py`: un mensaje por día hábil (desde las 09:00 ART) que
menciona a Mariano con las opps suyas (`opp_sales_lead`) que llevan 20 días o más en la
etapa actual — `deep_dive_date` si está en Deep Dive, `nda_sent_date` si está en NDA Sent —
para que las cierre o las mueva. Sin vencidas no se postea nada.

- Cron horario `.github/workflows/stale-opps-slack.yml` →
  `POST /reminders/stale_opps_slack/due` con `X-Audit-Token`; `?dry=1` lista sin postear.
  Un solo mensaje por día lo garantiza `stale_opps_slack_log` (autocreada), reclamada antes
  de postear; si Slack falla se suelta y la próxima corrida reintenta.
- Canal **Sales & Opps** (`SLACK_CHANNEL_ID = "C07GZ8RQWF3"`, hardcodeado, definitivo desde
  el 2026-09-30; antes era el de prueba `C0C0UQ7SYBW`). El bot tiene que estar invitado.

## Stop ya no borra la start date (NDA)

Hasta el 2026-10-01, mover una opp a **Stop** en `docs/opportunities.html` hacía
`patchOppFields(id, { nda_signature_or_start_date: null })` (`dispatchStageChange()` en
`main.js`). Al reactivarla se pedía una fecha nueva y la original se perdía sin dejar rastro, y
esa columna es ancla de ~10 datasets. Se notó cuando **NDA → Close Win** de Operations pasó a
excluir las opps sin start date (`data-override-requiere-nda`, filtro `requiere_nda` de los 4
`nda_close_win_*.py`) y se cayeron 582, 623, 624 y 712. Ahora Stop deja la fecha y volver a
Sourcing abre el popup de nueva ronda (`POST /sourcing`).

Las 11 opps afectadas se restauraron con `backend/scripts/restore_nda_dates_stop_20261001.py`.
El valor tipeado no se guardaba en ningún lado: se usó el día (hora ARG) del primer
`saveSourcingDate` en `tracks`, que puede diferir unos días del real. `tracks` arranca en
feb-2026, así que si aparece una opp más vieja sin fecha no hay de dónde sacarla.

## Prospecting: el CRM de los BDRs (Clay → Hub, sin HubSpot)

`docs/prospecting.html` reemplaza a HubSpot para la prospección: Clay manda cada empresa
al Hub, los BDRs la trabajan ahí y los workflows que corría HubSpot viven en el backend.
Es un módulo **aparte** del CRM de clientes (`account`): otras empresas, otro volumen.
Código en `backend/prospecting/` (`constants.py`, `store.py`, `workflows.py`) +
`backend/routes/prospecting_routes.py`. Tablas autocreadas: `prospect_companies`,
`prospect_company_events` (historial por campo), `prospect_workflow_runs`.

- **Acceso**: `users.role` que contenga `BDR` (activo) **+ pgonzales siempre**
  (`ADMIN_EMAILS`). El sidebar no tiene Set hardcodeado: pregunta a `GET /prospecting/me`.
  La UI limitada de `crm.js` (abril, luca, felipe, felicitas) deja pasar el link por texto.
- **Clay**: columna "HTTP API" → `POST /prospecting/clay/webhook` con `X-Clay-Token`
  (= env `CLAY_WEBHOOK_TOKEN`, propia). Acepta snake_case o los nombres de la planilla de
  HubSpot (`_ALIASES` en `store.py`). Match por `clay_record_id`, si no por dominio.
  **Un re-envío nunca pisa lo que trabaja el BDR** (status, owner, start date, Not ICP,
  semana): esos sólo se rellenan si están vacíos.
- **Workflows**: una entrada por workflow en `WORKFLOWS` (`workflows.py`). Hoy sólo
  `recycle_60d` (In Progress con start date de hace más de 60 días → borra owner, owner
  Apollo y start date, status Recycled). `as_of` simula la fecha. Cron
  `.github/workflows/prospecting-workflows.yml` con el **schedule comentado** hasta validar.
- **Pruebas**: botón *Test panel* (sólo admin) siembra empresas `is_dummy`, que los BDRs no
  ven, y corre los workflows en dry run o aplicados. `backend/scripts/clay_webhook_simulator.py`
  manda payloads con la forma de Clay.
- Las listas cerradas (status, Not ICP reasons, sizes) viven sólo en `constants.py`.

## Staffing: columnas y opciones desde la vista

En `docs/staffing.html` (las 3 pestañas) las 4 personas de `STAFFING_ALLOWED` crean
columnas (lista, texto, número, fecha, Sí/No) y editan las opciones de cualquier
desplegable sin tocar código; los valores se cargan en la celda, tipo Excel. Desde el
2026-10-05 los catálogos ya **no** están en `staffing.js` (quedan sólo como fallback si
`GET /staffing/schema` falla). Todo en `backend/routes/staffing_routes.py`:

- `staffing_options` (catálogo, también el de Platform/Performance/Provider/Exit
  type/Invoice/Paid) y `staffing_columns` (columnas nuevas), autocreadas + seed único
  desde `SEED_OPTIONS`. Sin migración a mano.
- Los valores de las columnas nuevas van en el JSONB `custom` de `staffing_extra`
  (Database y Churn comparten el par) o de `bonus_requests`. Clave = `c_<column_id>`,
  estable aunque se renombre. El PATCH **mezcla** (`custom || ...`), no pisa.
- **Renombrar una opción actualiza las filas** que la tenían, en la misma transacción
  (`BUILTIN_SELECTS` dice dónde vive cada built-in). Ocultar no toca las filas: el valor
  queda y se ve en gris. Ocultar una columna conserva sus valores; se restaura desde
  "Add column".
- **Eliminar** (`DELETE ...?hard=1`, con confirm en el front) sí borra: una opción deja
  vacías las filas que la tenían; una columna se lleva su catálogo y su valor en cada
  fila. Sin vuelta atrás. Las opciones `locked` y las columnas de fábrica no se eliminan.
- `locked`: "Resigned"/"Terminated" y "Paid" sólo se pueden recolorear — los KPIs
  cuentan ese texto y Exit type además se deriva del motivo de baja.
- Colores: paleta cerrada `OPTION_COLORS` ↔ clases `stf-badge--c-<color>` en
  `staffing.css`. Si sumás un color, van los dos.
- Provider no se edita en la celda cuando el equipo trae proveedor
  (`provider_locked`): `equipments.proveedor` gana y el cambio no se vería.
