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