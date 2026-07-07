-- Approximate geolocation for resume views, resolved from ip_address on demand
-- (lazily, when the team opens the view-detail popover) and cached back into the row.
-- Run manually against RDS.

ALTER TABLE resume_view_events ADD COLUMN IF NOT EXISTS city    TEXT;
ALTER TABLE resume_view_events ADD COLUMN IF NOT EXISTS region  TEXT;
ALTER TABLE resume_view_events ADD COLUMN IF NOT EXISTS country TEXT;
-- Marks that a geo lookup has already been attempted (so we don't retry unresolvable IPs).
ALTER TABLE resume_view_events ADD COLUMN IF NOT EXISTS geo_checked BOOLEAN NOT NULL DEFAULT FALSE;
