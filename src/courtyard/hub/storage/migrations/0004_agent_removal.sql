-- Liveness vs removal (step 2). agents.status becomes purely a liveness state
-- (invited/connected/stale/gone — gone is re-attachable, e.g. after a crash or clean
-- detach). Removal from the courtyard is a separate, permanent fact: removed_at.

ALTER TABLE agents ADD COLUMN removed_at timestamptz;

-- Agents removed under the step-1 semantics (status='gone' meant removed).
UPDATE agents SET removed_at = now() WHERE status = 'gone';