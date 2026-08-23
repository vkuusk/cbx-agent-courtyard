-- Archived line histories (design §5.7, D20). One row = one immutable document: the
-- line's identity at the time, why and when it was archived, and the whole transcript
-- as JSON (every message as the board showed it). Kept apart from the live tables so it
-- can be dumped, exported and pruned on its own.

CREATE TABLE lines_archive (
    id             uuid PRIMARY KEY,
    line_id        uuid NOT NULL,             -- the line it came from (may be gone by now)
    agent_a        uuid NOT NULL,
    agent_b        uuid NOT NULL,
    agent_a_name   text NOT NULL,
    agent_b_name   text NOT NULL,
    mode           text NOT NULL,
    reason         text NOT NULL CHECK (reason IN ('agent_removed', 'operator')),
    archived_at    timestamptz NOT NULL DEFAULT now(),
    first_at       timestamptz,
    last_at        timestamptz,
    message_count  integer NOT NULL,
    transcript     jsonb NOT NULL
);

CREATE INDEX lines_archive_archived_at_idx ON lines_archive (archived_at DESC);
