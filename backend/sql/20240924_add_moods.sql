CREATE TABLE IF NOT EXISTS moods (
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    clicked_at TIMESTAMP NOT NULL DEFAULT NOW(),
    mood TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS moods_user_day_idx
    ON moods (user_id, (clicked_at::date));
