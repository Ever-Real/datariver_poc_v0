BEGIN;

CREATE TABLE IF NOT EXISTS poc_k9_source_snapshots_v2 (
  source_snapshot_id char(64) PRIMARY KEY,
  contract_version varchar(64) NOT NULL,
  source_fingerprint_id char(64) NOT NULL,
  catalog_generation char(64) NOT NULL,
  datahub_version varchar(200) NOT NULL,
  datahub_commit varchar(200),
  authority_pin jsonb NOT NULL,
  inventory_projection_hash char(64) NOT NULL,
  lineage_hash char(64) NOT NULL,
  metadata_hash char(64) NOT NULL,
  dangling_state_hash char(64) NOT NULL,
  snapshot jsonb NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT ck_poc_k9_source_snapshot_v2_contract CHECK (
    contract_version = 'DATARIVER_K9_SOURCE_SNAPSHOT_V2'
  ),
  CONSTRAINT ck_poc_k9_source_snapshot_v2_hashes CHECK (
    source_snapshot_id ~ '^[0-9a-f]{64}$'
    AND source_fingerprint_id ~ '^[0-9a-f]{64}$'
    AND source_fingerprint_id = source_snapshot_id
    AND catalog_generation ~ '^[0-9a-f]{64}$'
    AND inventory_projection_hash ~ '^[0-9a-f]{64}$'
    AND lineage_hash ~ '^[0-9a-f]{64}$'
    AND metadata_hash ~ '^[0-9a-f]{64}$'
    AND dangling_state_hash ~ '^[0-9a-f]{64}$'
  ),
  CONSTRAINT ck_poc_k9_source_snapshot_v2_payload CHECK (
    jsonb_typeof(snapshot) = 'object'
    AND jsonb_typeof(authority_pin) = 'object'
    AND octet_length(snapshot::text) <= 131072
    AND octet_length(authority_pin::text) <= 4096
  )
);

CREATE TABLE IF NOT EXISTS poc_k9_source_payloads_v2 (
  source_snapshot_id char(64) NOT NULL REFERENCES poc_k9_source_snapshots_v2(source_snapshot_id),
  payload_kind varchar(32) NOT NULL,
  payload_hash char(64) NOT NULL,
  payload jsonb NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (source_snapshot_id, payload_kind),
  CONSTRAINT ck_poc_k9_source_payload_v2_kind CHECK (
    payload_kind IN ('INVENTORY', 'LINEAGE', 'METADATA', 'DANGLING_STATE')
  ),
  CONSTRAINT ck_poc_k9_source_payload_v2_hash CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_poc_k9_source_payload_v2_payload CHECK (
    jsonb_typeof(payload) IN ('object', 'array') AND octet_length(payload::text) <= 67108864
  )
);

CREATE TABLE IF NOT EXISTS poc_k9_semantic_manifests_v2 (
  source_snapshot_id char(64) NOT NULL REFERENCES poc_k9_source_snapshots_v2(source_snapshot_id),
  binding_hash char(64) NOT NULL,
  desired_count integer NOT NULL,
  manifest_hash char(64) NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (source_snapshot_id, binding_hash),
  CONSTRAINT ck_poc_k9_semantic_manifest_v2_hashes CHECK (
    binding_hash ~ '^[0-9a-f]{64}$' AND manifest_hash ~ '^[0-9a-f]{64}$'
  ),
  CONSTRAINT ck_poc_k9_semantic_manifest_v2_bounds CHECK (desired_count BETWEEN 0 AND 1000000)
);

CREATE TABLE IF NOT EXISTS poc_k9_semantic_desired_documents_v2 (
  source_snapshot_id char(64) NOT NULL,
  binding_hash char(64) NOT NULL,
  document_id text NOT NULL,
  asset_urn text NOT NULL,
  source_hash char(64) NOT NULL,
  content_text text NOT NULL,
  metadata jsonb NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (source_snapshot_id, binding_hash, document_id),
  UNIQUE (source_snapshot_id, binding_hash, asset_urn),
  UNIQUE (source_snapshot_id, binding_hash, document_id, source_hash),
  FOREIGN KEY (source_snapshot_id, binding_hash)
    REFERENCES poc_k9_semantic_manifests_v2(source_snapshot_id, binding_hash),
  CONSTRAINT ck_poc_k9_semantic_desired_document_v2_hashes CHECK (
    binding_hash ~ '^[0-9a-f]{64}$' AND source_hash ~ '^[0-9a-f]{64}$'
  ),
  CONSTRAINT ck_poc_k9_semantic_desired_document_v2_bounds CHECK (
    char_length(document_id) BETWEEN 20 AND 4096
    AND char_length(asset_urn) BETWEEN 20 AND 4096
    AND char_length(content_text) BETWEEN 1 AND 200000
    AND jsonb_typeof(metadata) = 'object'
    AND octet_length(metadata::text) <= 1048576
  )
);

CREATE TABLE IF NOT EXISTS poc_k9_semantic_batches_v2 (
  source_snapshot_id char(64) NOT NULL REFERENCES poc_k9_source_snapshots_v2(source_snapshot_id),
  binding_hash char(64) NOT NULL,
  batch_number integer NOT NULL,
  batch_total integer NOT NULL,
  document_count integer NOT NULL,
  batch_hash char(64) NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (source_snapshot_id, binding_hash, batch_number),
  CONSTRAINT ck_poc_k9_semantic_batch_v2_hashes CHECK (
    binding_hash ~ '^[0-9a-f]{64}$' AND batch_hash ~ '^[0-9a-f]{64}$'
  ),
  CONSTRAINT ck_poc_k9_semantic_batch_v2_bounds CHECK (
    batch_number BETWEEN 1 AND 1000000
    AND batch_total BETWEEN 1 AND 1000000
    AND batch_number <= batch_total
    AND document_count BETWEEN 0 AND 1000000
  )
);

CREATE TABLE IF NOT EXISTS poc_k9_semantic_staging_v2 (
  source_snapshot_id char(64) NOT NULL,
  binding_hash char(64) NOT NULL,
  document_id text NOT NULL,
  batch_number integer NOT NULL,
  source_hash char(64) NOT NULL,
  embedding vector NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (source_snapshot_id, binding_hash, document_id),
  FOREIGN KEY (source_snapshot_id, binding_hash, batch_number)
    REFERENCES poc_k9_semantic_batches_v2(source_snapshot_id, binding_hash, batch_number),
  FOREIGN KEY (source_snapshot_id, binding_hash, document_id, source_hash)
    REFERENCES poc_k9_semantic_desired_documents_v2(source_snapshot_id, binding_hash, document_id, source_hash),
  CONSTRAINT ck_poc_k9_semantic_staging_v2_hashes CHECK (
    binding_hash ~ '^[0-9a-f]{64}$' AND source_hash ~ '^[0-9a-f]{64}$'
  ),
  CONSTRAINT ck_poc_k9_semantic_staging_v2_bounds CHECK (vector_dims(embedding) BETWEEN 1 AND 4096)
);

CREATE INDEX IF NOT EXISTS ix_poc_k9_semantic_staging_v2_materialize
  ON poc_k9_semantic_staging_v2 (source_snapshot_id, binding_hash, batch_number, document_id);

CREATE TABLE IF NOT EXISTS poc_k9_projector_receipts_v2 (
  receipt_id char(64) PRIMARY KEY,
  source_snapshot_id char(64) NOT NULL REFERENCES poc_k9_source_snapshots_v2(source_snapshot_id),
  projector varchar(16) NOT NULL,
  status varchar(16) NOT NULL,
  attempt_id char(64) NOT NULL,
  attempt_number integer NOT NULL,
  sequence integer NOT NULL,
  previous_receipt_id char(64) REFERENCES poc_k9_projector_receipts_v2(receipt_id),
  idempotency_key_hash char(64) NOT NULL,
  progress jsonb,
  diagnostic jsonb,
  output_pointer varchar(255),
  output_hash char(64),
  recorded_at timestamptz NOT NULL,
  receipt jsonb NOT NULL,
  UNIQUE (source_snapshot_id, projector, attempt_number, sequence),
  UNIQUE (source_snapshot_id, projector, attempt_id, sequence),
  UNIQUE (projector, idempotency_key_hash),
  CONSTRAINT ck_poc_k9_projector_receipt_v2_identity CHECK (
    receipt_id ~ '^[0-9a-f]{64}$'
    AND attempt_id ~ '^[0-9a-f]{64}$'
    AND idempotency_key_hash ~ '^[0-9a-f]{64}$'
    AND (previous_receipt_id IS NULL OR previous_receipt_id ~ '^[0-9a-f]{64}$')
  ),
  CONSTRAINT ck_poc_k9_projector_receipt_v2_kind CHECK (
    projector IN ('SOURCE', 'LINEAGE', 'METADATA', 'SEMANTIC')
    AND status IN ('PENDING', 'RUNNING', 'READY', 'FAILED')
    AND attempt_number > 0 AND sequence > 0
  ),
  CONSTRAINT ck_poc_k9_projector_receipt_v2_terminal CHECK (
    (status = 'READY' AND output_pointer IS NOT NULL AND output_hash IS NOT NULL AND diagnostic IS NULL)
    OR (status = 'FAILED' AND output_pointer IS NULL AND output_hash IS NULL AND diagnostic IS NOT NULL)
    OR (status IN ('PENDING', 'RUNNING') AND output_pointer IS NULL AND output_hash IS NULL AND diagnostic IS NULL)
  ),
  CONSTRAINT ck_poc_k9_projector_receipt_v2_bounds CHECK (
    (output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$')
    AND (progress IS NULL OR (jsonb_typeof(progress) = 'object' AND octet_length(progress::text) <= 2048))
    AND (diagnostic IS NULL OR (jsonb_typeof(diagnostic) = 'object' AND octet_length(diagnostic::text) <= 2048))
    AND jsonb_typeof(receipt) = 'object' AND octet_length(receipt::text) <= 8192
  )
);

CREATE INDEX IF NOT EXISTS ix_poc_k9_projector_receipts_v2_latest
  ON poc_k9_projector_receipts_v2
  (source_snapshot_id, projector, attempt_number DESC, sequence DESC, receipt_id DESC);

CREATE TABLE IF NOT EXISTS poc_k9_snapshot_lifecycle_v2 (
  lifecycle_key varchar(100) PRIMARY KEY,
  desired_snapshot_id char(64) NOT NULL REFERENCES poc_k9_source_snapshots_v2(source_snapshot_id),
  active_snapshot_id char(64) REFERENCES poc_k9_source_snapshots_v2(source_snapshot_id),
  status varchar(16) NOT NULL,
  version bigint NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT ck_poc_k9_snapshot_lifecycle_v2_state CHECK (
    status IN ('PENDING', 'RUNNING', 'READY', 'FAILED')
    AND version > 0
    AND (
      status <> 'READY'
      OR (active_snapshot_id IS NOT NULL AND active_snapshot_id = desired_snapshot_id)
    )
  )
);

CREATE OR REPLACE FUNCTION poc_reject_k9_lifecycle_payload_mutation()
RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
  RAISE EXCEPTION 'K9 V2 source snapshots, payloads and projector receipts are immutable';
END
$function$;

DO $block$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_poc_k9_semantic_manifests_v2_immutable' AND tgrelid = 'poc_k9_semantic_manifests_v2'::regclass) THEN
    CREATE TRIGGER trg_poc_k9_semantic_manifests_v2_immutable BEFORE UPDATE OR DELETE ON poc_k9_semantic_manifests_v2 FOR EACH ROW EXECUTE FUNCTION poc_reject_k9_lifecycle_payload_mutation();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_poc_k9_semantic_desired_documents_v2_immutable' AND tgrelid = 'poc_k9_semantic_desired_documents_v2'::regclass) THEN
    CREATE TRIGGER trg_poc_k9_semantic_desired_documents_v2_immutable BEFORE UPDATE OR DELETE ON poc_k9_semantic_desired_documents_v2 FOR EACH ROW EXECUTE FUNCTION poc_reject_k9_lifecycle_payload_mutation();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_poc_k9_semantic_batches_v2_immutable' AND tgrelid = 'poc_k9_semantic_batches_v2'::regclass) THEN
    CREATE TRIGGER trg_poc_k9_semantic_batches_v2_immutable BEFORE UPDATE OR DELETE ON poc_k9_semantic_batches_v2 FOR EACH ROW EXECUTE FUNCTION poc_reject_k9_lifecycle_payload_mutation();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_poc_k9_semantic_staging_v2_immutable' AND tgrelid = 'poc_k9_semantic_staging_v2'::regclass) THEN
    CREATE TRIGGER trg_poc_k9_semantic_staging_v2_immutable BEFORE UPDATE OR DELETE ON poc_k9_semantic_staging_v2 FOR EACH ROW EXECUTE FUNCTION poc_reject_k9_lifecycle_payload_mutation();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_poc_k9_source_payloads_v2_immutable' AND tgrelid = 'poc_k9_source_payloads_v2'::regclass) THEN
    CREATE TRIGGER trg_poc_k9_source_payloads_v2_immutable BEFORE UPDATE OR DELETE ON poc_k9_source_payloads_v2 FOR EACH ROW EXECUTE FUNCTION poc_reject_k9_lifecycle_payload_mutation();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_poc_k9_source_snapshots_v2_immutable' AND tgrelid = 'poc_k9_source_snapshots_v2'::regclass) THEN
    CREATE TRIGGER trg_poc_k9_source_snapshots_v2_immutable BEFORE UPDATE OR DELETE ON poc_k9_source_snapshots_v2 FOR EACH ROW EXECUTE FUNCTION poc_reject_k9_lifecycle_payload_mutation();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_poc_k9_projector_receipts_v2_immutable' AND tgrelid = 'poc_k9_projector_receipts_v2'::regclass) THEN
    CREATE TRIGGER trg_poc_k9_projector_receipts_v2_immutable BEFORE UPDATE OR DELETE ON poc_k9_projector_receipts_v2 FOR EACH ROW EXECUTE FUNCTION poc_reject_k9_lifecycle_payload_mutation();
  END IF;
END
$block$;

INSERT INTO poc_state (scope, value) VALUES (
  'product-owned-schema-contract-v6',
  '{"contract":"DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V6","revision":6,"fingerprint":"912b81ebb39e2a725dece61e22a52064e7f133c5206caa65e0ce6f17782c2dcc"}'::jsonb
);

COMMIT;
