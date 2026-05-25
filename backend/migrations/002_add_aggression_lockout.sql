-- Add post-vacation aggression lockout timestamp to players.
-- Run once against the live database after deploying this code change.
--
--   docker compose exec db psql -U postgres -d spationsim -f /migrations/002_add_aggression_lockout.sql

ALTER TABLE players ADD COLUMN IF NOT EXISTS aggression_lockout_until TIMESTAMPTZ;
