-- Item 24: the gate verdict `reject` becomes `drop` ("reject" read too close to
-- "return to sender"); the resulting message status `rejected` becomes `dropped`.
-- Constraints off first so the stored rows can cross from the old names to the new.
ALTER TABLE messages DROP CONSTRAINT messages_status_check;
ALTER TABLE messages DROP CONSTRAINT messages_gate_verdict_check;
UPDATE messages SET status = 'dropped' WHERE status = 'rejected';
UPDATE messages SET gate_verdict = 'drop' WHERE gate_verdict = 'reject';
ALTER TABLE messages ADD CONSTRAINT messages_status_check
    CHECK (status IN ('pending_gate', 'queued', 'delivered', 'dropped', 'returned', 'expired'));
ALTER TABLE messages ADD CONSTRAINT messages_gate_verdict_check
    CHECK (gate_verdict IN ('approve', 'return', 'drop'));
