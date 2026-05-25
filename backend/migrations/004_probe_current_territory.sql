-- Add current position tracking to probes for step-by-step tick movement.
--   docker compose exec db psql -U spationsim -d spationsim -f /migrations/004_probe_current_territory.sql

ALTER TABLE probes ADD COLUMN IF NOT EXISTS current_territory INTEGER REFERENCES territories(id);
