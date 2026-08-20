-- Domain of responsibility, for authority grading (design §7.5).
--
-- A short operator-written phrase naming what this agent OWNS ("the AWS estate and IAM").
-- Distinct from `description`, which is prose for discovery: an agent can be described
-- without being given ownership of anything, and that difference is exactly what separates
-- a `domain-owner` from a plain `agent` in the delivery envelope. Domains may overlap; the
-- receiving model resolves overlap, the hub does not arbitrate it.

ALTER TABLE agents ADD COLUMN sme_domain text;
