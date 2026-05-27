-- Add war_starts_at to diplomacy to support the 2-tick war declaration window.
-- When war is declared, status is set to 'war_pending' and war_starts_at is set
-- to NOW() + 4 hours. The tick promotes the row to 'war' once war_starts_at passes.
ALTER TABLE diplomacy ADD COLUMN IF NOT EXISTS war_starts_at TIMESTAMPTZ;
