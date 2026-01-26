ALTER TABLE client_overview
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT timezone('America/New_York', now());

UPDATE client_overview
SET updated_at = timezone('America/New_York', now())
WHERE updated_at IS NULL;
