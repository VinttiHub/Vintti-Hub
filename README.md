# Vintti-hub
Repositorio inicializado.

## Google Calendar (OAuth)

Para habilitar la integración en `docs/calendar.html`, configurar:

- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI` (ej: `https://<tu-backend>/google-calendar/callback`)
- `GOOGLE_CALENDAR_SCOPES` (opcional, default: `https://www.googleapis.com/auth/calendar`)

Además, ejecutar la migración SQL `backend/sql/20241112_add_google_calendar_tokens.sql`.
