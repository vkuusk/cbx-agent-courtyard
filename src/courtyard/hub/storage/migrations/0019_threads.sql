-- Threads (design threads.md, D34): one bounded exchange about one ask.
-- Serial v1: at most one open thread per line; the sender declares boundaries,
-- the hub never infers them. Messages older than this migration stay
-- thread-less (no backfill).

CREATE TABLE threads (
    id        uuid PRIMARY KEY,
    line_id   uuid NOT NULL REFERENCES lines (id),
    state     text NOT NULL DEFAULT 'open'
              CHECK (state IN ('open', 'closed', 'expired', 'locked')),
    opened_by uuid NOT NULL REFERENCES agents (id),
    opened_at timestamptz NOT NULL DEFAULT now(),
    ended_at  timestamptz
);

-- The serial invariant, held by the database itself.
CREATE UNIQUE INDEX threads_one_open_per_line ON threads (line_id) WHERE state = 'open';

ALTER TABLE messages ADD COLUMN thread_id uuid REFERENCES threads (id);
CREATE INDEX messages_thread_id ON messages (thread_id);

ALTER TABLE lines ADD COLUMN open_thread uuid REFERENCES threads (id);
