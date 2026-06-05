-- Track when a war actually begins (transition from war_pending → war).
-- Used to enforce the 12-tick minimum war duration before peace can be agreed.
ALTER TABLE diplomacy ADD COLUMN war_started_at TIMESTAMPTZ;

-- Timestamp until which this pair cannot re-declare war after peace.
-- Set to peace_time + 72 hours (36 ticks × 2 hours/tick) when peace is agreed.
ALTER TABLE diplomacy ADD COLUMN peace_until TIMESTAMPTZ;
