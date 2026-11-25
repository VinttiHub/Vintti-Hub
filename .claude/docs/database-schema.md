# Base de datos

### Database access
`backend/db.py::get_connection()` returns a raw `psycopg2` connection to the shared RDS Postgres instance. Credentials come from env vars (`RDS_PASSWORD`, required, no fallback; `RDS_HOST` / `RDS_PORT` / `RDS_DB` / `RDS_USER` with defaults), set in `backend/.env` locally and in App Runner in prod. The old hardcoded password was rotated on 2026-06-25 and only survives, dead, in git history. Never put the password back in code (the repo is public) and never print it in error messages or logs. Every route opens its own connection and is responsible for closing it; there is no pool or ORM. Login (`routes/auth_routes.py`) joins `users` against `admin_user_access` to gate inactive accounts.

### Database migrations
SQL migrations live in `backend/sql/` as dated files (e.g. `20241112_add_google_calendar_tokens.sql`). There is no migration runner — run them manually against the RDS instance when merging a PR that depends on one.

## Convenciones de esquema (recopiladas de los otros docs)

- **Sin migración a mano en lo nuevo**: casi todas las tablas recientes se autocrean con
  `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` en el primer uso (`ensure_schema()`,
  `_ensure_*`). Las migraciones de `backend/sql/` son las viejas y se corren a mano.
- **Columna nueva del sync de HubSpot → un `_ensure_*` propio**, nunca dentro de
  `_ensure_hubspot_opportunity_columns()` (se cortocircuita en prod). Ver `hubspot.md`.
- **Vacío incluye `''`**: el blur de `docs/` guarda string vacío, no NULL. Un «sólo si está
  vacío» va con `COALESCE(NULLIF(col,''), %s)`, no con `is None` ni `COALESCE(col, %s)`.
- **`opportunity.fee` ≠ fee del MRR**: el del MRR es `hire_opportunity.fee`, con
  `salary_updates` por encima (precedencia en `_mrr_staffing.py:79-95`). Ojo al grepear: `o\.fee`
  también matchea `ho.fee`. `salary_updates.opportunity_id` está siempre en NULL.
- **Columnas espejo `hubspot_*` de `opportunity`**: ningún dataset las lee.
- **Fotos `*_seen`** (`hubspot_model_seen`, `hubspot_dates_seen`, `hubspot_seen` de prospecting):
  guardan el último valor visto en HubSpot, para pisar el hub sólo cuando HubSpot cambia.
- **`nda_signature_or_start_date` es ancla de ~10 datasets**: no se pisa ni se borra a la ligera.
- **Prospecting**: `props` JSONB para propiedades que no son columna (contactos, empresas,
  negocios); tablas `prospect_*` autocreadas. Ver `prospecting.md`.
- **RDS `max_connections=81`**: procesos largos usan una sola conexión secuencial.
