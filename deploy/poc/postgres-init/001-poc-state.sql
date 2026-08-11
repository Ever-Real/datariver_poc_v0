CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS poc_state (
  scope text PRIMARY KEY,
  value jsonb NOT NULL,
  version bigint NOT NULL DEFAULT 1,
  updated_at timestamptz NOT NULL DEFAULT now()
);
