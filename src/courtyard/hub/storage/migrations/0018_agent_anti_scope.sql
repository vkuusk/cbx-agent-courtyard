-- Anti-scope (design team-charter.md, D33): what NOT to ask this agent. Capabilities
-- tell peers whom to ask; the anti-scope tells them whom not to ask -- misrouting is a
-- real failure class. Charter-fed (anti-scope.md), also editable on the agent forms.
ALTER TABLE agents ADD COLUMN anti_scope text;
