-- Stored agent tokens (design D19). A personal-use app on a trusted machine (D3): the
-- operator must be able to open an agent's launch config again and to rotate its token,
-- so the plaintext is kept beside the hash (the hash stays the lookup key for
-- authentication). Registrations made before this migration have no stored token until
-- they are rotated.

ALTER TABLE agents ADD COLUMN token text;
