BEGIN;

CREATE TABLE IF NOT EXISTS applicants (
    applicant_id   BIGSERIAL PRIMARY KEY,
    first_name     TEXT NOT NULL,
    last_name      TEXT NOT NULL,
    email          TEXT NOT NULL,
    phone          TEXT NOT NULL,
    location       TEXT NOT NULL,
    role_position  TEXT NOT NULL,
    area           TEXT NOT NULL,
    linkedin_url   TEXT NOT NULL,
    english_level  TEXT NOT NULL,
    referral_source TEXT NOT NULL,
    cv_s3_key      TEXT,
    cv_file_name   TEXT,
    cv_content_type TEXT,
    cv_size_bytes  INTEGER,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_applicants_email ON applicants (LOWER(email));

COMMIT;
