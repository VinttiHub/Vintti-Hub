BEGIN;

ALTER TABLE candidates
    ADD COLUMN IF NOT EXISTS tests_documents_s3 JSONB DEFAULT '[]'::jsonb;

UPDATE candidates
SET tests_documents_s3 = '[]'::jsonb
WHERE tests_documents_s3 IS NULL;

COMMIT;
