-- Hub memory, slice 3 (design hub-memory.md section 7): vectors behind the same door.
-- pgvector rides with the compose postgres (image pgvector/pgvector:pg18). The column
-- has no fixed dimension: the encoder decides it, and `embedding_model` says which
-- encoder produced each vector, so a model change means a re-embed, not a new column.
-- Vector search always filters on the current model, so dimensions never mix.
-- No ANN index until the table reaches tens of thousands of rows; a scan is fast below.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE memory ADD COLUMN embedding vector;
ALTER TABLE memory ADD COLUMN embedding_model text;
ALTER TABLE memory ADD COLUMN embedded_at timestamptz;

CREATE INDEX memory_embedding_model ON memory (embedding_model);
