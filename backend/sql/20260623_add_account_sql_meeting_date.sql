-- R1 (dashboard audit 2026-06-23): anclar el "SQL" de las cards de Ventas por la
-- fecha REAL del meeting (meeting_date___time de HubSpot), igual que Marketing, en
-- vez de account.creation_date (que es cuándo la cuenta aterrizó en el CRM = lead).
--
-- El sync de SQL contacts (POST /hubspot/sync/mariano-sql-contacts) escribe esta
-- columna; las cards SQL→DeepDive→NDA→Win y sql_leads/kr_sql anclan en
-- COALESCE(sql_meeting_date, creation_date) para no romper cuentas aún sin backfill.
--
-- No hay migration runner: _ensure_hubspot_account_columns() también la crea con
-- IF NOT EXISTS en el próximo sync. Esta migración la deja explícita/idempotente.

ALTER TABLE account ADD COLUMN IF NOT EXISTS sql_meeting_date DATE;

COMMENT ON COLUMN account.sql_meeting_date IS
  'Fecha real del meeting (meeting_date___time HubSpot) con la que el contacto se volvió SQL. Ancla canónica del SQL en el tab Ventas. La escribe el sync de SQL contacts.';
