# Deploy, comandos y crons

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

## Producción

- Backend: AWS App Runner (`https://7m6mw95m8y.us-east-2.awsapprunner.com`), **Python 3.8**:
  `zoneinfo` u otra sintaxis 3.9+ tumba el boot y prod queda en la versión vieja (síntoma: 404
  en una ruta nueva).
- `docs/`: GitHub Pages en `vinttihub.vintti.com` (`CNAME` en la raíz).
- Env vars en `backend/.env` (gitignored) **y** en App Runner. Las específicas de cada módulo
  están en su doc (HubSpot, Apriora, Clay, Zapier, Google OAuth…).
- Los crons de GitHub Actions llegan con varias horas de atraso: la hora del cron no es la de
  llegada. Por eso los recordatorios corren cada hora y deciden con su propia tabla.

## Crons (`.github/workflows/`)

| Workflow | Cuándo (UTC) | Qué hace |
|---|---|---|
| `weekly-dashboard-audit.yml` | lunes 11:00 | `POST /dashboards/audit/run` |
| `hubspot-opportunity-sync.yml` | cada 30 min | `POST /hubspot/sync/opportunities` + push |
| `prospecting-hubspot-sync.yml` | cada 30 min | sync de empresas, contactos y negocios |
| `prospecting-workflows.yml` | :15 cada hora | `tick()` del motor de workflows |
| `sheet-applicants-import.yml` | cada 15 min | `POST /sheets/candidates/import` |
| `second-interview-references.yml` | cada hora | `POST /reminders/second_interview_refs/due` |
| `profile-completion-reminder.yml` | cada hora | `POST /reminders/profile_completion/due` |
| `stale-opps-slack.yml` | cada hora | `POST /reminders/stale_opps_slack/due` |
| `weekly-sales-scores-slack.yml` | cada hora los lunes (+ martes 0-2 UTC) | `POST /reminders/weekly_sales_scores/due` |
| `birthday-weekly-report.yml` | lunes | `POST /reminders/birthdays/weekly` |
| `daily-reminders.yml` | diario 12:00 | `/reminders/due` |
| `daily-digest.yml` | lun-vie 08:00 | digest de pendientes a Slack |
| `daily-turvo-sync.yml` | diario 10:00 | sync de Turvo |
| `monthly-ae-commissions.yml` | día 1, 11:00 | mail de comisiones AE |

Los crons propios autentican con `X-Audit-Token` (= `DASHBOARD_AUDIT_TOKEN`) y aceptan `?dry=1`.
