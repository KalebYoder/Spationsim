-- Create chat and mail tables.
-- These are auto-created by SQLAlchemy create_all on first startup;
-- run this only if the app has already been deployed without these tables.
--
--   docker compose exec db psql -U postgres -d spationsim -f /migrations/003_messaging.sql

CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    channel VARCHAR(64) NOT NULL,
    sender_nation_id INTEGER NOT NULL REFERENCES nations(id),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_chat_channel_id ON chat_messages (channel, id);

CREATE TABLE IF NOT EXISTS mail_messages (
    id SERIAL PRIMARY KEY,
    sender_nation_id INTEGER NOT NULL REFERENCES nations(id),
    recipient_nation_id INTEGER NOT NULL REFERENCES nations(id),
    subject VARCHAR(256) NOT NULL,
    body TEXT NOT NULL,
    read BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_by_sender BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_by_recipient BOOLEAN NOT NULL DEFAULT FALSE,
    sent_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_mail_recipient_read ON mail_messages (recipient_nation_id, read);
CREATE INDEX IF NOT EXISTS ix_mail_sender_sent_at ON mail_messages (sender_nation_id, sent_at);
