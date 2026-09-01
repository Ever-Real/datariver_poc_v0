BEGIN;

CREATE TABLE IF NOT EXISTS poc_change_history_gap_receipts (
  receipt_id char(64) PRIMARY KEY,
  source_identity_hash char(64) NOT NULL REFERENCES poc_change_history_sources(source_identity_hash),
  topic_contract text NOT NULL,
  source_partition integer NOT NULL,
  previous_next_offset bigint NOT NULL,
  observed_low_watermark bigint NOT NULL,
  observed_high_watermark bigint NOT NULL,
  missing_interval_start bigint NOT NULL,
  missing_interval_end bigint NOT NULL,
  reason text NOT NULL,
  prior_exact_segment_identity char(64) NOT NULL,
  new_segment_start bigint NOT NULL,
  observed_at timestamptz NOT NULL,
  receipt_version integer NOT NULL,
  UNIQUE (
    source_identity_hash, topic_contract, source_partition,
    previous_next_offset, observed_low_watermark
  ),
  CONSTRAINT ck_poc_change_history_gap_receipt_hashes CHECK (
    receipt_id ~ '^[0-9a-f]{64}$'
    AND prior_exact_segment_identity ~ '^[0-9a-f]{64}$'
  ),
  CONSTRAINT ck_poc_change_history_gap_receipt_position CHECK (
    source_partition >= 0
    AND previous_next_offset >= 0
    AND observed_low_watermark > previous_next_offset
    AND observed_high_watermark >= observed_low_watermark
    AND missing_interval_start = previous_next_offset
    AND missing_interval_end = observed_low_watermark
    AND new_segment_start = observed_low_watermark
  ),
  CONSTRAINT ck_poc_change_history_gap_receipt_contract CHECK (
    reason = 'RETENTION_EXPIRED'
    AND receipt_version = 1
    AND char_length(topic_contract) BETWEEN 1 AND 255
  )
);

CREATE INDEX IF NOT EXISTS ix_poc_change_history_gap_receipt_source
  ON poc_change_history_gap_receipts (
    source_identity_hash, topic_contract, source_partition, observed_at, receipt_id
  );

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgname = 'trg_poc_change_history_gap_receipt_append_only'
      AND tgrelid = 'poc_change_history_gap_receipts'::regclass
  ) THEN
    CREATE TRIGGER trg_poc_change_history_gap_receipt_append_only
      BEFORE UPDATE OR DELETE ON poc_change_history_gap_receipts
      FOR EACH ROW EXECUTE FUNCTION poc_reject_change_history_mutation();
  END IF;
END
$block$;

INSERT INTO poc_state (scope, value)
VALUES (
  'product-owned-schema-contract-v7',
  '{"contract":"DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V7","revision":7,"fingerprint":"1481be3bb0ff1f92aaad70e41a8b7e534c685c207dc8f5918be750b73887861f"}'::jsonb
);

COMMIT;
