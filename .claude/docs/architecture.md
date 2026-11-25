# Arquitectura

> Detalle de backend, frontend y acceso. Lo esencial está en `CLAUDE.md`.

## Backend architecture

Entry point is `backend/app.py::create_app()`. It:
1. Loads `backend/.env` via `python-dotenv`.
2. Calls `utils.services.init_services()` to initialize the OpenAI, Affinda, and boto3/S3 clients from env vars. **Anything that touches these clients must run after `init_services()`** — don't import-time-bind them at module top level.
3. Registers two styles of route modules, both of which you'll see mixed together:
   - **Newer split** — `backend/routes/*.py`, each exposing a `bp = Blueprint(...)` registered with `app.register_blueprint(...)`.
   - **Older monolithic files at `backend/`** (e.g. `ai_routes.py`, `recruiter_metrics_routes.py`, `reminders_routes.py`, `profile_routes.py`, `reset_password.py`, `send_email_endpoint.py`, `interviewing_routes.py`, `ai_candidate_search_routes.py`, `admin_routes.py`, `coresignal_routes.py`, `hunter.py`). Several expose `register_*(app)` functions instead of blueprints — call them from `create_app()`.
   When adding a route, match the style of the module you're extending rather than refactoring across the split.

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

### La URL de App Runner hardcodeada rompe TODA prueba local

`docs/assets/js/main.js` define `API_BASE` con detección de localhost (línea ~875),
pero hasta el 2026-09-17 tenía **23 fetch con la URL de App Runner escrita a mano**,
incluidos los dos que más importan: `patchOpportunityStage()` y `patchOppFields()`.
Lo mismo en `candidate-details.js` con `API_CANDIDATES`.

_Historia (por qué): ver `.claude/docs/historical-decisions.md` → «API_BASE hardcodeada (2026-09-17)»._

Ya están todos pasados a `${API_BASE}` / `candidatesApiBase()`. **Si agregás un fetch
nuevo, usá la constante.** La única excepción a propósito es `SEND_EMAIL_ENDPOINT`:
manda mails reales y no conviene que una prueba local los dispare por otra ruta.

## Sidebar: recruiters y BDRs entran por su rol

Dar de alta a una recruiter o un BDR = ponerle el rol en el panel de admin. **No hay que
sumar su email a ninguna lista.** `sidebar.js` pregunta a `GET /users/access`
(`routes/users_routes.py`, cacheado 10 min en `sessionStorage`) y pinta según:

- **`is_recruiter`** = fila `user_roles.role_type='recruiter'` (la misma de
  `/users/recruiters` y de los dashboards de recruiters). Prende Candidate Search y Recruiter
  Power. Las listas por email que quedan en `sidebar.js` son sólo para quien usa esas
  pestañas **sin** ser recruiter (agustin, lara, pgonzales…). Luz (2026-10-26) no veía nada
  porque eran listas copiadas en 6 archivos; las copias de `main.js` / `crm.js` /
  `candidate.js` se borraron (corrían antes de montar el sidebar: eran código muerto).
- **`is_bdr`** = `users.role` contiene "BDR". `enforceBdrUI()` deja en el sidebar sólo
  Candidates, CRM, Opportunities, Prospecting, To-Do y Calendar (`BDR_ALLOWED_LINKS`, las que
  fijó la owner el 2026-10-26), y desde cualquier otra página manda a Opportunities. Se
  permiten además los detalles (candidate-details, resume-readonly, account-details,
  opportunity-detail, prospecting-company) y profile: `BDR_ALLOWED_PAGES`, por nombre exacto. Antes vivía en `crm.js`
  con 4 emails fijos y de los 15 BDRs sólo alcanzaba a abril. No es
  `prospecting.store.has_access()`: ese incluye a los editores de workflows (mia, manuela, bahia).
- **Recruiter Power** restringe al revés que antes: ven a todas sólo `FULL_VIEW_EMAILS`
  (pgonzales, agostina, lara, agustin); cualquier otra persona ve sólo su fila.
- El link de applicants de `opportunity-detail.js` ya caía a `/users/recruiters`.

Todo es client-side, como antes: ninguno de estos endpoints tiene gate por rol.
