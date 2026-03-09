BEGIN;

CREATE TABLE IF NOT EXISTS google_calendar_tokens (
    user_id       INTEGER PRIMARY KEY,
    access_token  TEXT NOT NULL,
    refresh_token TEXT,
    token_expiry  TIMESTAMPTZ,
    scope         TEXT,
    token_type    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS google_calendar_oauth_states (
    state       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    redirect_to TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_google_calendar_oauth_states_expires_at
    ON google_calendar_oauth_states (expires_at);

COMMIT;
