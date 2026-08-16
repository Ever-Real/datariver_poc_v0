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

CREATE TABLE IF NOT EXISTS poc_change_history_sources (
  source_identity_hash char(64) PRIMARY KEY,
  provider_name text NOT NULL,
  provider_version text NOT NULL,
  schema_contract_hash char(64) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT ck_poc_change_history_source_identity
    CHECK (source_identity_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_poc_change_history_source_schema
    CHECK (schema_contract_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_poc_change_history_source_provider
    CHECK (char_length(provider_name) BETWEEN 1 AND 100
      AND char_length(provider_version) BETWEEN 1 AND 100)
);

CREATE TABLE IF NOT EXISTS poc_change_history_ledger_events (
  event_identity char(64) PRIMARY KEY,
  event_hash char(64) NOT NULL,
  source_identity_hash char(64) NOT NULL REFERENCES poc_change_history_sources(source_identity_hash),
  source_event_identity char(64) NOT NULL,
  normalized_change_transaction_id char(64) NOT NULL,
  deterministic_ordinal integer NOT NULL,
  topic_contract text NOT NULL,
  source_partition integer NOT NULL,
  source_offset bigint NOT NULL,
  asset_urn text NOT NULL,
  normalized_entity_key text NOT NULL,
  category text NOT NULL,
  source_aspect text NOT NULL,
  operation text NOT NULL,
  before_data jsonb,
  after_data jsonb,
  before_hash char(64),
  after_hash char(64),
  actor_ref text,
  source_occurred_at timestamptz,
  detected_at timestamptz NOT NULL,
  captured_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (source_identity_hash, source_event_identity, deterministic_ordinal),
  CONSTRAINT ck_poc_change_history_ledger_hashes CHECK (
    event_identity ~ '^[0-9a-f]{64}$'
    AND event_hash ~ '^[0-9a-f]{64}$'
    AND source_event_identity ~ '^[0-9a-f]{64}$'
    AND normalized_change_transaction_id ~ '^[0-9a-f]{64}$'
    AND (before_hash IS NULL OR before_hash ~ '^[0-9a-f]{64}$')
    AND (after_hash IS NULL OR after_hash ~ '^[0-9a-f]{64}$')
  ),
  CONSTRAINT ck_poc_change_history_ledger_position
    CHECK (source_partition >= 0 AND source_offset >= 0 AND deterministic_ordinal >= 0),
  CONSTRAINT ck_poc_change_history_ledger_category_v2 CHECK (
    (category = 'TECHNICAL_SCHEMA' AND source_aspect = 'schemaMetadata')
    OR (category = 'DOCUMENTATION' AND source_aspect IN ('datasetProperties', 'editableSchemaMetadata'))
    OR (category = 'TAG' AND source_aspect IN ('globalTags', 'schemaMetadata', 'editableSchemaMetadata'))
    OR (category = 'GLOSSARY_TERM' AND source_aspect IN ('glossaryTerms', 'schemaMetadata', 'editableSchemaMetadata'))
    OR (category = 'OWNERSHIP' AND source_aspect = 'ownership')
    OR (category = 'LIFECYCLE' AND source_aspect IN ('status', 'entity'))
  ),
  CONSTRAINT ck_poc_change_history_ledger_operation
    CHECK (operation IN ('CREATE', 'UPDATE', 'UPSERT', 'DELETE', 'ADD', 'REMOVE')),
  CONSTRAINT ck_poc_change_history_ledger_bounds CHECK (
    char_length(topic_contract) BETWEEN 1 AND 255
    AND char_length(asset_urn) BETWEEN 1 AND 4096
    AND char_length(normalized_entity_key) BETWEEN 1 AND 1000
    AND (actor_ref IS NULL OR char_length(actor_ref) BETWEEN 1 AND 1000)
    AND (before_data IS NULL OR (jsonb_typeof(before_data) = 'object'
      AND octet_length(before_data::text) <= 16384
      AND NOT jsonb_path_exists(before_data, '$.** ? (@.type() == "object").keyvalue() ? (@.key == "raw" || @.key == "payload" || @.key == "aspect" || @.key == "schemaMetadata" || @.key == "previousAspectValue")')))
    AND (after_data IS NULL OR (jsonb_typeof(after_data) = 'object'
      AND octet_length(after_data::text) <= 16384
      AND NOT jsonb_path_exists(after_data, '$.** ? (@.type() == "object").keyvalue() ? (@.key == "raw" || @.key == "payload" || @.key == "aspect" || @.key == "schemaMetadata" || @.key == "previousAspectValue")')))
  )
);

DO $block$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_poc_change_history_ledger_category'
      AND conrelid = 'poc_change_history_ledger_events'::regclass
  ) THEN
    ALTER TABLE poc_change_history_ledger_events
      DROP CONSTRAINT ck_poc_change_history_ledger_category;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_poc_change_history_ledger_category_v2'
      AND conrelid = 'poc_change_history_ledger_events'::regclass
  ) THEN
    ALTER TABLE poc_change_history_ledger_events
      ADD CONSTRAINT ck_poc_change_history_ledger_category_v2 CHECK (
        (category = 'TECHNICAL_SCHEMA' AND source_aspect = 'schemaMetadata')
        OR (category = 'DOCUMENTATION' AND source_aspect IN ('datasetProperties', 'editableSchemaMetadata'))
        OR (category = 'TAG' AND source_aspect IN ('globalTags', 'schemaMetadata', 'editableSchemaMetadata'))
        OR (category = 'GLOSSARY_TERM' AND source_aspect IN ('glossaryTerms', 'schemaMetadata', 'editableSchemaMetadata'))
        OR (category = 'OWNERSHIP' AND source_aspect = 'ownership')
        OR (category = 'LIFECYCLE' AND source_aspect IN ('status', 'entity'))
      );
  END IF;
END
$block$;

CREATE TABLE IF NOT EXISTS poc_local_credentials (
  subject_id text PRIMARY KEY,
  username_normalized text NOT NULL UNIQUE,
  password_hash text NOT NULL,
  login_enabled boolean NOT NULL DEFAULT true,
  must_change_password boolean NOT NULL DEFAULT false,
  failed_attempts integer NOT NULL DEFAULT 0,
  locked_until timestamptz,
  version bigint NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT ck_poc_local_credential_subject
    CHECK (char_length(subject_id) BETWEEN 1 AND 255),
  CONSTRAINT ck_poc_local_credential_username
    CHECK (username_normalized ~ '^[a-z0-9][a-z0-9._@+\-]{0,63}$'),
  CONSTRAINT ck_poc_local_credential_password_hash
    CHECK (char_length(password_hash) BETWEEN 32 AND 512
      AND password_hash LIKE '$argon2id$v=19$%'),
  CONSTRAINT ck_poc_local_credential_attempts
    CHECK (failed_attempts BETWEEN 0 AND 1000),
  CONSTRAINT ck_poc_local_credential_version CHECK (version > 0)
);

CREATE TABLE IF NOT EXISTS poc_local_sessions (
  token_hash char(64) PRIMARY KEY,
  subject_id text NOT NULL REFERENCES poc_local_credentials(subject_id),
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  CONSTRAINT ck_poc_local_session_hash CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_poc_local_session_lifetime CHECK (expires_at > created_at),
  CONSTRAINT ck_poc_local_session_revocation CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);

CREATE INDEX IF NOT EXISTS ix_poc_local_sessions_subject
  ON poc_local_sessions (subject_id);

CREATE INDEX IF NOT EXISTS ix_poc_local_sessions_expiry
  ON poc_local_sessions (expires_at) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS poc_user_table_grants (
  subject_id text NOT NULL,
  table_urn text NOT NULL,
  active boolean NOT NULL DEFAULT true,
  version bigint NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  created_by text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_by text NOT NULL,
  PRIMARY KEY (subject_id, table_urn),
  CONSTRAINT ck_poc_user_table_grant_subject
    CHECK (char_length(subject_id) BETWEEN 1 AND 255),
  CONSTRAINT ck_poc_user_table_grant_table
    CHECK (char_length(table_urn) BETWEEN 20 AND 4096
      AND table_urn LIKE 'urn:li:dataset:(%'),
  CONSTRAINT ck_poc_user_table_grant_actor
    CHECK (char_length(created_by) BETWEEN 1 AND 255
      AND char_length(updated_by) BETWEEN 1 AND 255),
  CONSTRAINT ck_poc_user_table_grant_version CHECK (version > 0)
);

CREATE INDEX IF NOT EXISTS ix_poc_user_table_grants_active_table
  ON poc_user_table_grants (table_urn, subject_id) WHERE active;

CREATE UNIQUE INDEX IF NOT EXISTS uq_poc_change_history_source_position_ordinal
  ON poc_change_history_ledger_events (
    source_identity_hash, topic_contract, source_partition, source_offset, deterministic_ordinal
  );

CREATE INDEX IF NOT EXISTS ix_poc_change_history_ledger_asset
  ON poc_change_history_ledger_events (asset_urn, source_occurred_at DESC, event_identity DESC);

CREATE TABLE IF NOT EXISTS poc_change_history_checkpoints (
  source_identity_hash char(64) NOT NULL REFERENCES poc_change_history_sources(source_identity_hash),
  topic_contract text NOT NULL,
  source_partition integer NOT NULL,
  first_exact_offset bigint NOT NULL,
  next_offset bigint NOT NULL,
  last_contiguous_event_identity char(64),
  last_source_occurred_at timestamptz,
  last_captured_at timestamptz,
  version bigint NOT NULL DEFAULT 1,
  PRIMARY KEY (source_identity_hash, topic_contract, source_partition),
  CONSTRAINT ck_poc_change_history_checkpoint_position CHECK (
    source_partition >= 0 AND first_exact_offset >= 0 AND next_offset >= first_exact_offset
  ),
  CONSTRAINT ck_poc_change_history_checkpoint_event CHECK (
    last_contiguous_event_identity IS NULL
    OR last_contiguous_event_identity ~ '^[0-9a-f]{64}$'
  ),
  CONSTRAINT ck_poc_change_history_checkpoint_version CHECK (version > 0)
);

CREATE TABLE IF NOT EXISTS poc_change_history_cr_link_events (
  link_event_identity char(64) PRIMARY KEY,
  event_hash char(64) NOT NULL,
  request_key_hash char(64) NOT NULL UNIQUE,
  request_hash char(64) NOT NULL,
  ledger_event_identity char(64) NOT NULL REFERENCES poc_change_history_ledger_events(event_identity),
  link_version bigint NOT NULL,
  link_kind text NOT NULL,
  action text NOT NULL,
  change_request_id text NOT NULL,
  change_request_round integer NOT NULL,
  prior_link_hash char(64),
  reason text NOT NULL,
  policy_hash char(64) NOT NULL,
  basis_hash char(64) NOT NULL,
  actor_ref text NOT NULL,
  occurred_at timestamptz NOT NULL,
  captured_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (ledger_event_identity, link_version),
  UNIQUE (ledger_event_identity, event_hash),
  CONSTRAINT ck_poc_change_history_cr_link_hashes CHECK (
    link_event_identity ~ '^[0-9a-f]{64}$'
    AND event_hash ~ '^[0-9a-f]{64}$'
    AND request_key_hash ~ '^[0-9a-f]{64}$'
    AND request_hash ~ '^[0-9a-f]{64}$'
    AND (prior_link_hash IS NULL OR prior_link_hash ~ '^[0-9a-f]{64}$')
    AND policy_hash ~ '^[0-9a-f]{64}$'
    AND basis_hash ~ '^[0-9a-f]{64}$'
  ),
  CONSTRAINT ck_poc_change_history_cr_link_action CHECK (
    (link_kind = 'PRIMARY' AND action IN ('SET_PRIMARY', 'CLEAR_PRIMARY'))
    OR (link_kind = 'CANDIDATE' AND action IN ('ADD_CANDIDATE', 'REMOVE_CANDIDATE'))
  ),
  CONSTRAINT ck_poc_change_history_cr_link_bounds CHECK (
    link_version > 0 AND change_request_round > 0
    AND char_length(change_request_id) BETWEEN 1 AND 200
    AND char_length(reason) BETWEEN 1 AND 2000
    AND char_length(actor_ref) BETWEEN 1 AND 1000
  )
);

CREATE INDEX IF NOT EXISTS ix_poc_change_history_cr_link_current
  ON poc_change_history_cr_link_events (ledger_event_identity, link_version DESC);

CREATE OR REPLACE FUNCTION poc_reject_change_history_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
  RAISE EXCEPTION 'POC change-history evidence is append-only';
END
$function$;

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgname = 'trg_poc_change_history_ledger_append_only'
      AND tgrelid = 'poc_change_history_ledger_events'::regclass
  ) THEN
    CREATE TRIGGER trg_poc_change_history_ledger_append_only
      BEFORE UPDATE OR DELETE ON poc_change_history_ledger_events
      FOR EACH ROW EXECUTE FUNCTION poc_reject_change_history_mutation();
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgname = 'trg_poc_change_history_cr_link_append_only'
      AND tgrelid = 'poc_change_history_cr_link_events'::regclass
  ) THEN
    CREATE TRIGGER trg_poc_change_history_cr_link_append_only
      BEFORE UPDATE OR DELETE ON poc_change_history_cr_link_events
      FOR EACH ROW EXECUTE FUNCTION poc_reject_change_history_mutation();
  END IF;
END
$block$;
