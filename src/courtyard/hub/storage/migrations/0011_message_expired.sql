-- D24: end shift closes the books — an unfinished message (in flight awaiting a reply,
-- or held at the gate) is closed as 'expired': kept in history, its obligation gone.
ALTER TABLE messages DROP CONSTRAINT messages_status_check;
ALTER TABLE messages ADD CONSTRAINT messages_status_check
    CHECK (status IN ('pending_gate', 'queued', 'delivered', 'rejected', 'returned', 'expired'));
