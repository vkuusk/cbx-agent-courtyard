-- Hub memory, slice 2 (design hub-memory.md sections 4, 5, 8): notes. A note is a memory
-- record with an author, a body and a scope, no thread: an agent deposits a lesson on
-- purpose, or the operator writes standing guidance. Scope is one line unless the author
-- says team-wide. An agent's note passes the gate like a message: `pending` until the
-- operator approves, returns or drops it; only `accepted` notes are memory.

ALTER TABLE memory ADD COLUMN body        text NOT NULL DEFAULT '';
ALTER TABLE memory ADD COLUMN scope       text NOT NULL DEFAULT 'line'
    CHECK (scope IN ('line', 'team'));
ALTER TABLE memory ADD COLUMN status      text NOT NULL DEFAULT 'accepted'
    CHECK (status IN ('pending', 'accepted', 'returned', 'dropped'));
ALTER TABLE memory ADD COLUMN author      uuid;
ALTER TABLE memory ADD COLUMN author_name text;
ALTER TABLE memory ADD COLUMN gate_note   text;
ALTER TABLE memory ADD COLUMN decided_at  timestamptz;

-- The search index gains the note's body at the ask's weight (a generated column cannot
-- be altered in place; it is rebuilt).
DROP INDEX memory_search;
ALTER TABLE memory DROP COLUMN search;
ALTER TABLE memory ADD COLUMN search tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', ask), 'A') ||
    setweight(to_tsvector('english', body), 'A') ||
    setweight(to_tsvector('english', domains_text), 'A') ||
    setweight(to_tsvector('english', resolution), 'B') ||
    setweight(to_tsvector('english', names_text), 'B') ||
    setweight(to_tsvector('english', verdict_text), 'C')
) STORED;
CREATE INDEX memory_search ON memory USING GIN (search);
CREATE INDEX memory_pending ON memory (created_at) WHERE status = 'pending';
