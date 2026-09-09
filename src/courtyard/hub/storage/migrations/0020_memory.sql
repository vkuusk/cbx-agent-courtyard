-- Hub memory (design hub-memory.md, slice 1): the case file. One record per closed
-- thread, assembled from facts the hub already holds (no summarization): who talked,
-- the opening ask, the resolution, every verdict with its comment, and the ordered
-- messages as a document. `kind` already admits `note` for slice 2.
--
-- No foreign keys to threads or lines on purpose: those rows go when a line's history
-- is archived (D20, D34), and memory outlives them by design (it is derived from the
-- archive, not from the live tables).

CREATE TABLE memory (
    id              uuid PRIMARY KEY,
    kind            text NOT NULL CHECK (kind IN ('case', 'note')),
    thread_id       uuid,
    line_id         uuid,
    -- the participants as they were at the time: [{id, name, sme_domain}]
    participants    jsonb NOT NULL,
    participant_ids uuid[] NOT NULL,
    opened_by       uuid,
    opened_by_name  text,
    opened_at       timestamptz,
    closed_at       timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    message_count   integer NOT NULL DEFAULT 0,
    approved        integer NOT NULL DEFAULT 0,
    returned        integer NOT NULL DEFAULT 0,
    dropped         integer NOT NULL DEFAULT 0,
    -- the trimmed view's text, and what the search index is built from
    ask             text NOT NULL,
    resolution      text NOT NULL,
    verdict_text    text NOT NULL DEFAULT '',
    names_text      text NOT NULL DEFAULT '',
    domains_text    text NOT NULL DEFAULT '',
    -- the full case file: {messages: [...], closed_by: name}
    document        jsonb NOT NULL,
    superseded_by   uuid REFERENCES memory (id),
    -- Domain-aware ranking: the ask and the participants' declared domains weigh the
    -- most, so a question about terraform finds the threads terraform took part in first.
    search          tsvector GENERATED ALWAYS AS (
                        setweight(to_tsvector('english', ask), 'A') ||
                        setweight(to_tsvector('english', domains_text), 'A') ||
                        setweight(to_tsvector('english', resolution), 'B') ||
                        setweight(to_tsvector('english', names_text), 'B') ||
                        setweight(to_tsvector('english', verdict_text), 'C')
                    ) STORED
);

CREATE INDEX memory_search ON memory USING GIN (search);
CREATE INDEX memory_participant_ids ON memory USING GIN (participant_ids);
CREATE INDEX memory_created_at ON memory (created_at DESC);
