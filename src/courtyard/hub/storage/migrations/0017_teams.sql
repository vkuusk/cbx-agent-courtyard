-- Team charter registry (design team-charter.md, D33): the hub is pointed at charter
-- directories; the files stay the source of truth, these rows cache what the hub last
-- loaded so the WebUI can display it (and show how stale it is). At most one team is
-- current; no team registered = the hub behaves exactly as before (charter is opt-in).
CREATE TABLE teams (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    charter_dir text NOT NULL UNIQUE,
    name text,
    is_current boolean NOT NULL DEFAULT false,
    loaded jsonb,
    load_report jsonb NOT NULL DEFAULT '[]'::jsonb,
    loaded_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX teams_one_current ON teams ((true)) WHERE is_current;
