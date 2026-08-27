-- D26: at startup the hub flips stored connected/stale agents to 'unknown' — a liveness
-- claim from a previous hub life is not repeated until a heartbeat (or the grace) proves it.
ALTER TABLE agents DROP CONSTRAINT agents_status_check;
ALTER TABLE agents ADD CONSTRAINT agents_status_check
    CHECK (status IN ('invited', 'connected', 'stale', 'gone', 'unknown'));
