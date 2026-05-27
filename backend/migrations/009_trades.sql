CREATE TABLE trades (
    id               SERIAL PRIMARY KEY,
    from_nation_id   INTEGER REFERENCES nations(id) NOT NULL,
    to_nation_id     INTEGER REFERENCES nations(id) NOT NULL,
    offer_minerals   NUMERIC(12,2) DEFAULT 0 NOT NULL,
    offer_fuel       NUMERIC(12,2) DEFAULT 0 NOT NULL,
    offer_currency   NUMERIC(12,2) DEFAULT 0 NOT NULL,
    request_minerals NUMERIC(12,2) DEFAULT 0 NOT NULL,
    request_fuel     NUMERIC(12,2) DEFAULT 0 NOT NULL,
    request_currency NUMERIC(12,2) DEFAULT 0 NOT NULL,
    status           VARCHAR(16) DEFAULT 'pending' NOT NULL,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    resolved_at      TIMESTAMPTZ
);
CREATE INDEX ix_trades_from   ON trades(from_nation_id);
CREATE INDEX ix_trades_to     ON trades(to_nation_id);
CREATE INDEX ix_trades_status ON trades(status);
