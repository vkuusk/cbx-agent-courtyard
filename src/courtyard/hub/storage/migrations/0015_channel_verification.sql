-- Items 33/34 (D29/D30): the session-channel facts the hub could not see before.
-- channel_flag: what the adapter found on its parent claude process's command line
-- (a session launched without the channels flag ACKs pushes while Claude Code drops
-- every event). verify_*: the delivery-verification check state — a nonce goes out
-- as a channel push, the model acks it with the courtyard_ack tool, or the sweep
-- times it out.
ALTER TABLE channels ADD COLUMN channel_flag TEXT NOT NULL DEFAULT 'unknown'
    CHECK (channel_flag IN ('present', 'absent', 'unknown'));
ALTER TABLE channels ADD COLUMN verify_token TEXT;
ALTER TABLE channels ADD COLUMN verify_sent_at TIMESTAMPTZ;
ALTER TABLE channels ADD COLUMN verified_at TIMESTAMPTZ;
ALTER TABLE channels ADD COLUMN verify_failed_at TIMESTAMPTZ;
