-- Hub memory, slice 4 (design hub-memory.md section 8): retention. A case file goes
-- with the archive it was distilled from; the archive's transcript names the threads,
-- so deletion is by thread id. A deleted case file that had superseded another leaves
-- that record in place, unsuperseded (the reference used to block the delete).

ALTER TABLE memory DROP CONSTRAINT memory_superseded_by_fkey;
ALTER TABLE memory ADD CONSTRAINT memory_superseded_by_fkey
    FOREIGN KEY (superseded_by) REFERENCES memory (id) ON DELETE SET NULL;

CREATE INDEX memory_thread ON memory (thread_id);
