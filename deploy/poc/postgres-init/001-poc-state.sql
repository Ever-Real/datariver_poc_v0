CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS poc_state (
  scope text PRIMARY KEY,
  value jsonb NOT NULL,
  version bigint NOT NULL DEFAULT 1,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS poc_catalog_embedding (
  binding_hash char(64) NOT NULL,
  asset_urn text NOT NULL,
  source_hash char(64) NOT NULL,
  source_generation char(64) NOT NULL,
  content_text text NOT NULL,
  metadata jsonb NOT NULL,
  embedding vector NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (binding_hash, asset_urn),
  CONSTRAINT ck_poc_catalog_embedding_dimension
    CHECK (vector_dims(embedding) BETWEEN 1 AND 4096)
);
