BEGIN;

-- K5 fixed-function durable bridge only. This is not a generic job/queue schema.
CREATE TABLE IF NOT EXISTS poc_knowledge_ingestion_jobs (
  job_id text PRIMARY KEY,
  draft_id text NOT NULL,
  graph_id text NOT NULL,
  release_id text NOT NULL,
  requested_by text NOT NULL,
  source_asset_urn text NOT NULL,
  source_version text NOT NULL,
  tbox_version integer NOT NULL,
  idempotency_key text NOT NULL,
  request_hash char(64) NOT NULL,
  state text NOT NULL,
  preview jsonb NOT NULL,
  result jsonb,
  version integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (draft_id, release_id, idempotency_key),
  CONSTRAINT ck_poc_knowledge_ingestion_job_hash CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_poc_knowledge_ingestion_job_state CHECK (
    state IN ('PREPARING', 'READY', 'CONFIRMED', 'DRAFT_CHANGESET_READY', 'PROJECTED', 'FAILED')
  ),
  CONSTRAINT ck_poc_knowledge_ingestion_job_versions CHECK (tbox_version > 0 AND version > 0),
  CONSTRAINT ck_poc_knowledge_ingestion_job_bounds CHECK (
    char_length(draft_id) BETWEEN 1 AND 255
    AND char_length(graph_id) BETWEEN 1 AND 255
    AND char_length(release_id) BETWEEN 1 AND 255
    AND char_length(requested_by) BETWEEN 1 AND 255
    AND char_length(source_asset_urn) BETWEEN 20 AND 4096
    AND char_length(source_version) BETWEEN 1 AND 255
    AND char_length(idempotency_key) BETWEEN 1 AND 200
  )
);

CREATE TABLE IF NOT EXISTS poc_knowledge_source_rows (
  manifest_ref text NOT NULL,
  asset_urn text NOT NULL,
  source_version text NOT NULL,
  row_key text NOT NULL,
  row_data jsonb NOT NULL,
  source_hash char(64) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (manifest_ref, row_key),
  CONSTRAINT ck_poc_knowledge_source_row_hash CHECK (source_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_poc_knowledge_source_row_bounds CHECK (
    char_length(manifest_ref) BETWEEN 1 AND 255
    AND char_length(asset_urn) BETWEEN 20 AND 4096
    AND char_length(source_version) BETWEEN 1 AND 255
    AND char_length(row_key) BETWEEN 1 AND 255
    AND jsonb_typeof(row_data) = 'object'
  )
);

CREATE INDEX IF NOT EXISTS ix_poc_knowledge_source_rows_asset
  ON poc_knowledge_source_rows (manifest_ref, asset_urn, source_version, row_key);

COMMIT;
