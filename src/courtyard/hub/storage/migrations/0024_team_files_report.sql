-- Charter projection writes the agents' files (design team-charter.md section 6, D33):
-- an agent the load registers gets its courtyard files in its workdir at once. What the
-- last load wrote, per agent, is kept beside the load report for the Teams view; the
-- load report stays the list of problems.
ALTER TABLE teams ADD COLUMN files_report jsonb NOT NULL DEFAULT '[]'::jsonb;
