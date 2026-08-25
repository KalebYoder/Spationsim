-- Migration 019: conquest_lockout_until on territories
-- Stores the timestamp until which no new facilities may be built on a
-- freshly conquered territory (12-tick / 24-hour lockout).
ALTER TABLE territories
    ADD COLUMN IF NOT EXISTS conquest_lockout_until TIMESTAMPTZ;
