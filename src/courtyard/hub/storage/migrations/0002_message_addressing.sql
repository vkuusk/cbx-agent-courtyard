-- Message addressing (step 1). The design schema lacked an explicit recipient: for
-- kind=message it is derivable (the other party), but operator notes are targeted and
-- system notices address the original sender — so store it. Hub-generated system
-- messages have no sender; a NULL recipient marks a log-only entry (nothing to deliver).

ALTER TABLE messages ALTER COLUMN sender DROP NOT NULL;

ALTER TABLE messages ADD COLUMN recipient uuid REFERENCES agents (id);

ALTER TABLE messages ADD CONSTRAINT messages_sender_required
    CHECK (sender IS NOT NULL OR kind = 'system');

CREATE INDEX messages_inbox_idx ON messages (recipient, status);
