-- Add construction queue support to infrastructure.
-- status: 'active' | 'under_construction' | 'demolishing'
-- completes_at: tick timestamp when status transitions to complete
--
--   docker compose exec db psql -U spationsim -d spationsim -f /migrations/005_facility_construction.sql

ALTER TABLE infrastructure ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'active';
ALTER TABLE infrastructure ADD COLUMN IF NOT EXISTS completes_at TIMESTAMPTZ;

-- Index so the tick can cheaply find due constructions/demolitions
CREATE INDEX IF NOT EXISTS ix_infrastructure_status_completes_at
    ON infrastructure(status, completes_at)
    WHERE status IN ('under_construction', 'demolishing');
