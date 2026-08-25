-- The operator's declared model for the agent's runtime (feedback item 1, WP-A):
-- written into the agent's .claude/settings.local.json by install and shown as
-- --model in the suggested launch command. Null = the runtime's own default.
ALTER TABLE agents ADD COLUMN model text;
