ALTER TABLE trades
    ADD COLUMN from_accepted_at  TIMESTAMPTZ,
    ADD COLUMN from_confirmed_at TIMESTAMPTZ,
    ADD COLUMN to_accepted_at    TIMESTAMPTZ,
    ADD COLUMN to_confirmed_at   TIMESTAMPTZ;
