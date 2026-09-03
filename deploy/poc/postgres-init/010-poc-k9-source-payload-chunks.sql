-- Additive K9 V2 source payload chunk persistence. Existing snapshots, monolithic
-- payload rows, lifecycle heads, projector receipts and LKG pointers are preserved.

BEGIN;

CREATE TABLE IF NOT EXISTS poc_k9_source_payload_chunks_v2 (
  source_snapshot_id char(64) NOT NULL,
  payload_kind varchar(32) NOT NULL,
  chunk_number integer NOT NULL,
  chunk_count integer NOT NULL,
  payload_hash char(64) NOT NULL,
  chunk_hash char(64) NOT NULL,
  byte_count integer NOT NULL,
  payload_chunk bytea NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (source_snapshot_id, payload_kind, chunk_number),
  FOREIGN KEY (source_snapshot_id, payload_kind)
    REFERENCES poc_k9_source_payloads_v2(source_snapshot_id, payload_kind),
  CONSTRAINT ck_poc_k9_source_payload_chunk_v2_kind CHECK (
    payload_kind IN ('INVENTORY', 'LINEAGE', 'METADATA', 'DANGLING_STATE')
  ),
  CONSTRAINT ck_poc_k9_source_payload_chunk_v2_hashes CHECK (
    payload_hash ~ '^[0-9a-f]{64}$' AND chunk_hash ~ '^[0-9a-f]{64}$'
  ),
  CONSTRAINT ck_poc_k9_source_payload_chunk_v2_bounds CHECK (
    chunk_number BETWEEN 1 AND 1024
    AND chunk_count BETWEEN 1 AND 1024
    AND chunk_number <= chunk_count
    AND byte_count BETWEEN 1 AND 1048576
    AND octet_length(payload_chunk) = byte_count
  )
);

CREATE INDEX IF NOT EXISTS ix_poc_k9_source_payload_chunks_v2_read
  ON poc_k9_source_payload_chunks_v2
  (source_snapshot_id, payload_kind, chunk_number, chunk_hash);

CREATE TABLE IF NOT EXISTS poc_k9_source_staging_v2 (
  lifecycle_key varchar(100) PRIMARY KEY,
  source_snapshot_id char(64) NOT NULL
    REFERENCES poc_k9_source_snapshots_v2(source_snapshot_id),
  evidence_hash char(64) NOT NULL,
  status varchar(16) NOT NULL,
  version bigint NOT NULL DEFAULT 1,
  verified_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  consumed_at timestamptz,
  CONSTRAINT ck_poc_k9_source_staging_v2_hash CHECK (
    evidence_hash ~ '^[0-9a-f]{64}$'
  ),
  CONSTRAINT ck_poc_k9_source_staging_v2_state CHECK (
    status IN ('VERIFIED', 'CONSUMED')
    AND version > 0
    AND ((status = 'VERIFIED' AND consumed_at IS NULL)
      OR (status = 'CONSUMED' AND consumed_at IS NOT NULL))
  )
);

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgname = 'trg_poc_k9_source_payload_chunks_v2_immutable'
      AND tgrelid = 'poc_k9_source_payload_chunks_v2'::regclass
  ) THEN
    CREATE TRIGGER trg_poc_k9_source_payload_chunks_v2_immutable
      BEFORE UPDATE OR DELETE ON poc_k9_source_payload_chunks_v2
      FOR EACH ROW EXECUTE FUNCTION poc_reject_k9_lifecycle_payload_mutation();
  END IF;
END
$block$;

INSERT INTO poc_state (scope, value, version)
VALUES (
  'product-owned-schema-contract-v8',
  '{"contract":"DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V8","revision":8,"fingerprint":"f5c1ef9ae3dee38422834d736df718793c5324fc0d7f553cbcc617739ffe6560"}'::jsonb,
  1
);

COMMIT;
