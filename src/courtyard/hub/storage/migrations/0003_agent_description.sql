-- Operator-curated agent description (discovery: the operator declares what each agent is
-- for; the hub makes it visible to every agent; the agent decides whom to ask).
-- See docs/design/use-cases-explained.md.

ALTER TABLE agents ADD COLUMN description text;
