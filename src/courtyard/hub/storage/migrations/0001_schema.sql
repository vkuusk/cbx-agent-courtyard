-- Courtyard v1 core schema (design doc §9.3).

CREATE TABLE agents (
    id           uuid PRIMARY KEY,
    name         text NOT NULL UNIQUE,
    type         text NOT NULL CHECK (type IN ('claude-code', 'pi', 'puppet', 'human')),
    workdir      text,
    token_hash   text NOT NULL,
    status       text NOT NULL DEFAULT 'invited'
                 CHECK (status IN ('invited', 'connected', 'stale', 'gone')),
    launch       jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz
);

-- One line per unordered pair; the pair is stored in normalized order (agent_a < agent_b).
CREATE TABLE lines (
    id            uuid PRIMARY KEY,
    agent_a       uuid NOT NULL REFERENCES agents (id),
    agent_b       uuid NOT NULL REFERENCES agents (id),
    mode          text NOT NULL DEFAULT 'supervised' CHECK (mode IN ('supervised', 'auto_pass')),
    state         text NOT NULL DEFAULT 'idle'
                  CHECK (state IN ('idle', 'pending_gate', 'awaiting_reply')),
    awaiting_from uuid REFERENCES agents (id),
    in_flight_msg uuid,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CHECK (agent_a < agent_b),
    UNIQUE (agent_a, agent_b)
);

CREATE TABLE messages (
    id              uuid PRIMARY KEY,
    line_id         uuid NOT NULL REFERENCES lines (id),
    seq             bigint NOT NULL,
    sender          uuid NOT NULL REFERENCES agents (id),
    kind            text NOT NULL CHECK (kind IN ('message', 'operator_note', 'system')),
    body            text NOT NULL,
    reply_to        uuid REFERENCES messages (id),
    status          text NOT NULL
                    CHECK (status IN ('pending_gate', 'queued', 'delivered', 'rejected', 'returned')),
    gate_verdict    text CHECK (gate_verdict IN ('approve', 'return', 'reject')),
    gate_note       text,
    gate_decided_by uuid REFERENCES agents (id),
    gate_decided_at timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    delivered_at    timestamptz,
    UNIQUE (line_id, seq)
);

ALTER TABLE lines
    ADD CONSTRAINT lines_in_flight_msg_fkey FOREIGN KEY (in_flight_msg) REFERENCES messages (id);

-- Live channel registrations: exactly one active channel per agent (design doc §6.2, §6.4).
CREATE TABLE channels (
    agent_id       uuid PRIMARY KEY REFERENCES agents (id) ON DELETE CASCADE,
    endpoint       text NOT NULL,
    channel_token  text NOT NULL,
    registered_at  timestamptz NOT NULL DEFAULT now(),
    last_heartbeat timestamptz NOT NULL DEFAULT now()
);
