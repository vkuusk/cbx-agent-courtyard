-- D22 (§5.8): under manual discovery the operator can unlink two agents — the line is
-- removed and its history archived with its own reason.
ALTER TABLE lines_archive DROP CONSTRAINT lines_archive_reason_check;
ALTER TABLE lines_archive ADD CONSTRAINT lines_archive_reason_check
    CHECK (reason IN ('agent_removed', 'operator', 'unlinked'));
