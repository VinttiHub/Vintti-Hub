# Vintti HUB React SPA

This folder contains the new Vite + React single-page application that will gradually replace the `docs/` static site. The goal is to reuse the existing HTML/CSS while modernising behaviour and data fetching in a componentised architecture.

## Getting started

```bash
cd frontend
npm install
npm run dev   # starts Vite dev server on http://localhost:5173
npm run build # production bundle used for deployment
```

> **Note:** The `.npmrc` forces HTTP to unblock installs on this machine (internal certificate issue). Remove it once TLS MITM is fixed.

## Project layout

```
frontend/
├── public/               # Static assets served as-is (CSS, sounds, icons, images)
├── src/
│   ├── components/       # Shared UI pieces (e.g. PasswordResetModal)
│   ├── constants/        # API base URL, avatar maps, etc.
│   ├── pages/            # Route-level screens (Login + migration placeholders)
│   ├── services/         # API wrappers (auth + current user helper)
│   ├── utils/            # Pure helpers such as avatar resolution
│   └── main.jsx          # React entry point + router wiring
└── vite.config.js        # Default Vite config (can add proxies/env later)
```

Key routing is defined in `src/App.jsx`. Today it serves the migrated login experience plus placeholder routes for Opportunities, CRM, Candidates, and Dashboard so we can land future JSX without touching URL structures.

## Migration game plan

1. **Reuse markup, keep styling stable**  
   - Copy the relevant HTML section from `docs/*.html` into a new component under `src/pages/` or `/components/`.  
   - Keep IDs/classes so `assets/css/style.css` continues to style everything without edits.

2. **Lift the existing vanilla JS logic**  
   - Translate the imperative scripts inside `docs/assets/js/*.js` into hooks/effects inside the new component.  
   - Extract shared helpers into `src/services` or `src/utils` to avoid duplicating fetch logic (example: `getCurrentUserId`).

3. **Wire the route**  
   - Add a new `<Route>` entry in `src/App.jsx` pointing to the component.  
   - Until the React version is ready, keep rendering `MigrationPlaceholder` so links don’t break.

4. **Verify against prod APIs**  
   - Always call the same `https://7m6mw95m8y.us-east-2.awsapprunner.com` endpoints and match payloads 1:1.  
   - Use the DevTools network tab or the existing JS file as a reference for request shapes.

5. **Decommission legacy page**  
   - Once a flow lives in React, flag the twin HTML/JS file under `docs/` as deprecated so we can remove it at the end of the rollout.

### Suggested order

1. Login + welcome (done)  
2. Opportunities board & creation modal (largest daily usage)  
3. Candidate search/detail (ties directly to opportunities)  
4. CRM dashboards and profile/account views  
5. Remaining utility pages (password reset, resume viewer, etc.)

Following this order keeps the highest-impact flows inside the SPA first, while still serving the static pages for everything else until their React counterparts are merged.
