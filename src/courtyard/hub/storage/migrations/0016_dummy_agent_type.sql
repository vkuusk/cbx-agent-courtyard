-- Item 38: the test-twin agent type renames puppet -> dummy. To a devops audience
-- "Puppet agent" reads as the config-management product's daemon, which is exactly
-- the confusion the first cold readers hit. Stored rows follow; the old value is
-- retired from the constraint. History docs keep the old word as record.
ALTER TABLE agents DROP CONSTRAINT agents_type_check;
UPDATE agents SET type = 'dummy' WHERE type = 'puppet';
ALTER TABLE agents ADD CONSTRAINT agents_type_check
    CHECK (type IN ('claude-code', 'pi', 'dummy', 'human'));
