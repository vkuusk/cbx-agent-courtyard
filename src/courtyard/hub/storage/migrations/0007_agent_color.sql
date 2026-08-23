-- Agent colour (WebUI identity). One of eight palette names; the WebUI maps a name to a
-- theme-appropriate tint. Chosen at registration, or assigned by the hub (least used).
-- Existing agents get one round-robin so the board is coloured from day one.

ALTER TABLE agents ADD COLUMN color text;

UPDATE agents a
SET color = p.name
FROM (
    SELECT id,
           (ARRAY['red', 'orange', 'yellow', 'green', 'teal', 'blue', 'purple', 'pink'])
               [(row_number() OVER (ORDER BY created_at) - 1) % 8 + 1] AS name
    FROM agents
    WHERE type <> 'human'
) p
WHERE a.id = p.id;
