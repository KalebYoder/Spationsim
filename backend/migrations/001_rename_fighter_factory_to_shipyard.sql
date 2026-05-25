-- Rename fighter_factory → shipyard in existing infrastructure rows.
-- Run once against the live database after deploying this code change.
--
--   docker compose exec db psql -U postgres -d spationsim -f /migrations/001_rename_fighter_factory_to_shipyard.sql

UPDATE infrastructure SET type = 'shipyard' WHERE type = 'fighter_factory';
