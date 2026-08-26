-- Courtyard settings (design §8.1, D23): a small key-value store for hub-level
-- configuration and state that must survive restarts — team_mode, terminal_app, and the
-- shift state document. Also the future home of Admin defaults (7c), so new settings
-- need no migration.
CREATE TABLE settings (
    key text PRIMARY KEY,
    value jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
