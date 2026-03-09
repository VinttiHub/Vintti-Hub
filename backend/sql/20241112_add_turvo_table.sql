BEGIN;

CREATE TABLE IF NOT EXISTS turvo (
    turvo_id INTEGER PRIMARY KEY,
    opportunity_id INTEGER NOT NULL,
    meeting_name TEXT NOT NULL,
    hr_lead TEXT NOT NULL,
    meeting_date TIMESTAMPTZ NOT NULL,
    candidates INTEGER NOT NULL DEFAULT 0,
    last_refresh_date TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS turvo_unique_meeting
    ON turvo (opportunity_id, meeting_name, hr_lead, meeting_date);

CREATE INDEX IF NOT EXISTS turvo_opportunity_meeting_date
    ON turvo (opportunity_id, meeting_date DESC);

COMMIT;
