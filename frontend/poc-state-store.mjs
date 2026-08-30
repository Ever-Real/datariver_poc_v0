/* global AbortController, clearInterval, setInterval, structuredClone */
import { createHash, randomUUID } from 'node:crypto'
import process from 'node:process'
import { TextEncoder } from 'node:util'
import { URL } from 'node:url'
import pg from 'pg'
import { createClient } from 'redis'

import {
  isMclRuntimeClassification,
  sanitizeMclRecordShape,
} from './poc-mcl-runtime-failure.mjs'
import {
  K9_METADATA_FAILURE_DETAILS,
  sanitizeK9MetadataSourceProfile,
} from './poc-k9-metadata-collection.mjs'
import {
  POC_POSTGRES_SCHEMA_INTEGRITY_FLAG,
  convergePocPostgresOwnedSchema,
} from './poc-postgres-schema-integrity.mjs'

const { Pool } = pg

const CHANGE_HISTORY_ACCESS_SCOPE = 'change-history-access-v1'
const CHANGE_HISTORY_ACCESS_SCOPES = [CHANGE_HISTORY_ACCESS_SCOPE, 'core']
const CHANGE_HISTORY_CAPTURE_STATUS_SCOPE = 'change-history-capture-status-v1'
const CHANGE_HISTORY_RUNTIME_STATUS_SCOPE = 'change-history-runtime-status-v1'
const MCP_READ_RECEIPT_SCOPE_PREFIX = 'mcp-read-receipt-v1:'
const CHANGE_HISTORY_CAPTURE_STATES = new Set([
  'CONTIGUOUS_CAPTURE_RECORDED',
  'CAPTURE_CATCHING_UP',
  'CAPTURE_CAUGHT_UP',
  'HISTORY_GAP_BLOCKED',
])
const K9_REFRESH_FAILURE_CODES = new Set([
  'K9_DATAHUB_SOURCE_FAILED',
  'K9_FAILURE_STATE_PERSISTENCE_FAILED',
  'K9_LINEAGE_REFRESH_FAILED',
  'K9_METADATA_REFRESH_FAILED',
  'K9_NEO4J_PROJECTION_FAILED',
  'K9_POLICY_PIN_DRIFT_FAILED',
  'K9_PROMOTION_FAILED',
  'K9_REFRESH_FAILED',
  'K9_SEMANTIC_INDEX_FAILED',
  'K9_SOURCE_SNAPSHOT_FAILED',
  'K9_SOURCE_DRIFT_RETRY_EXHAUSTED',
  'K9_SYSTEM_SUBJECT_FAILED',
])
const K9_SOURCE_FAILURE_STAGES = new Set([
  'INVENTORY',
  'INVENTORY_PROJECTION',
  'LINEAGE_COLLECTION',
  'METADATA_COLLECTION',
  'RUNTIME_IDENTITY',
])
const K9_SOURCE_FAILURE_DETAILS = new Set([
  'CONNECTIVITY',
  'TIMEOUT',
  'HTTP_4XX',
  'HTTP_5XX',
  'GRAPHQL',
  'CONTRACT',
  'EMPTY_SOURCE',
  'INTERNAL_TRANSFORM',
  ...K9_METADATA_FAILURE_DETAILS,
])
const PROTECTED_CORE_ACCESS_FIELDS = [
  'adminMemberships',
  'adminSystems',
  'adminSystemAssignees',
  'adminSystemSchemaScopes',
]

const CHANGE_HISTORY_SCHEMA = [
  `
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
    )
  `,
  `
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
      CONSTRAINT ck_poc_change_history_ledger_category_v3 CHECK (
        (category = 'TECHNICAL_SCHEMA' AND source_aspect = 'schemaMetadata')
        OR (category = 'DOCUMENTATION' AND source_aspect IN ('datasetProperties', 'editableSchemaMetadata'))
        OR (category = 'TAG' AND source_aspect IN ('globalTags', 'schemaMetadata', 'editableSchemaMetadata'))
        OR (category = 'GLOSSARY_TERM' AND source_aspect IN ('glossaryTerms', 'schemaMetadata', 'editableSchemaMetadata'))
        OR (category = 'DOMAIN' AND source_aspect = 'domains')
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
    )
  `,
  `
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
      IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_poc_change_history_ledger_category_v2'
          AND conrelid = 'poc_change_history_ledger_events'::regclass
      ) THEN
        ALTER TABLE poc_change_history_ledger_events
          DROP CONSTRAINT ck_poc_change_history_ledger_category_v2;
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_poc_change_history_ledger_category_v3'
          AND conrelid = 'poc_change_history_ledger_events'::regclass
      ) THEN
        ALTER TABLE poc_change_history_ledger_events
          ADD CONSTRAINT ck_poc_change_history_ledger_category_v3 CHECK (
            (category = 'TECHNICAL_SCHEMA' AND source_aspect = 'schemaMetadata')
            OR (category = 'DOCUMENTATION' AND source_aspect IN ('datasetProperties', 'editableSchemaMetadata'))
            OR (category = 'TAG' AND source_aspect IN ('globalTags', 'schemaMetadata', 'editableSchemaMetadata'))
            OR (category = 'GLOSSARY_TERM' AND source_aspect IN ('glossaryTerms', 'schemaMetadata', 'editableSchemaMetadata'))
            OR (category = 'DOMAIN' AND source_aspect = 'domains')
            OR (category = 'OWNERSHIP' AND source_aspect = 'ownership')
            OR (category = 'LIFECYCLE' AND source_aspect IN ('status', 'entity'))
          );
      END IF;
    END
    $block$
  `,
  `
    CREATE UNIQUE INDEX IF NOT EXISTS uq_poc_change_history_source_position_ordinal
      ON poc_change_history_ledger_events (
        source_identity_hash, topic_contract, source_partition, source_offset, deterministic_ordinal
      )
  `,
  `
    CREATE INDEX IF NOT EXISTS ix_poc_change_history_ledger_asset
      ON poc_change_history_ledger_events (asset_urn, source_occurred_at DESC, event_identity DESC)
  `,
  `
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
    )
  `,
  `
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
    )
  `,
  `
    CREATE INDEX IF NOT EXISTS ix_poc_change_history_cr_link_current
      ON poc_change_history_cr_link_events (ledger_event_identity, link_version DESC)
  `,
  `
    CREATE OR REPLACE FUNCTION poc_reject_change_history_mutation()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $function$
    BEGIN
      RAISE EXCEPTION 'POC change-history evidence is append-only';
    END
    $function$
  `,
  `
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
    $block$
  `,
]

const LOCAL_AUTH_SCHEMA = [
  `
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
        CHECK (username_normalized ~ '^[a-z0-9][a-z0-9._@+\\-]{0,63}$'),
      CONSTRAINT ck_poc_local_credential_password_hash
        CHECK (char_length(password_hash) BETWEEN 32 AND 512
          AND password_hash LIKE '$argon2id$v=19$%'),
      CONSTRAINT ck_poc_local_credential_attempts
        CHECK (failed_attempts BETWEEN 0 AND 1000),
      CONSTRAINT ck_poc_local_credential_version CHECK (version > 0)
    )
  `,
  `
    CREATE TABLE IF NOT EXISTS poc_local_sessions (
      token_hash char(64) PRIMARY KEY,
      subject_id text NOT NULL REFERENCES poc_local_credentials(subject_id),
      created_at timestamptz NOT NULL,
      expires_at timestamptz NOT NULL,
      revoked_at timestamptz,
      CONSTRAINT ck_poc_local_session_hash CHECK (token_hash ~ '^[0-9a-f]{64}$'),
      CONSTRAINT ck_poc_local_session_lifetime CHECK (expires_at > created_at),
      CONSTRAINT ck_poc_local_session_revocation CHECK (revoked_at IS NULL OR revoked_at >= created_at)
    )
  `,
  `
    CREATE INDEX IF NOT EXISTS ix_poc_local_sessions_subject
      ON poc_local_sessions (subject_id)
  `,
  `
    CREATE INDEX IF NOT EXISTS ix_poc_local_sessions_expiry
      ON poc_local_sessions (expires_at) WHERE revoked_at IS NULL
  `,
]

const LOCAL_SECURITY_EVENT_SCHEMA = [
  `
    CREATE TABLE IF NOT EXISTS poc_local_security_events (
      event_id uuid PRIMARY KEY,
      event_type text NOT NULL,
      subject_id text NOT NULL,
      actor_subject_id text NOT NULL,
      actor_kind text NOT NULL,
      occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      resulting_credential_version bigint NOT NULL,
      revoked_session_count bigint NOT NULL,
      CONSTRAINT uq_poc_local_security_event_subject_version
        UNIQUE (event_type, subject_id, resulting_credential_version),
      CONSTRAINT ck_poc_local_security_event_type
        CHECK (event_type = 'SELF_PASSWORD_CHANGED_V1'),
      CONSTRAINT ck_poc_local_security_event_actor
        CHECK (actor_kind = 'SELF' AND actor_subject_id = subject_id),
      CONSTRAINT ck_poc_local_security_event_subject
        CHECK (char_length(subject_id) BETWEEN 1 AND 255),
      CONSTRAINT ck_poc_local_security_event_version
        CHECK (resulting_credential_version > 0),
      CONSTRAINT ck_poc_local_security_event_session_count
        CHECK (revoked_session_count >= 0)
    )
  `,
  `
    CREATE OR REPLACE FUNCTION poc_reject_local_security_event_mutation()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $function$
    BEGIN
      RAISE EXCEPTION 'POC local security events are append-only';
    END
    $function$
  `,
  `
    DO $block$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_poc_local_security_events_append_only'
          AND tgrelid = 'poc_local_security_events'::regclass
      ) THEN
        CREATE TRIGGER trg_poc_local_security_events_append_only
          BEFORE UPDATE OR DELETE ON poc_local_security_events
          FOR EACH ROW EXECUTE FUNCTION poc_reject_local_security_event_mutation();
      END IF;
    END
    $block$
  `,
  `
    CREATE OR REPLACE FUNCTION poc_reject_schema_receipt_mutation()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $function$
    BEGIN
      IF OLD.scope LIKE 'product-owned-schema-contract-v%'
        OR (TG_OP = 'UPDATE' AND NEW.scope LIKE 'product-owned-schema-contract-v%') THEN
        RAISE EXCEPTION 'POC Product schema receipts are immutable';
      END IF;
      IF TG_OP = 'DELETE' THEN
        RETURN OLD;
      END IF;
      RETURN NEW;
    END
    $function$
  `,
  `
    DO $block$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_poc_state_schema_receipts_immutable'
          AND tgrelid = 'poc_state'::regclass
      ) THEN
        CREATE TRIGGER trg_poc_state_schema_receipts_immutable
          BEFORE UPDATE OR DELETE ON poc_state
          FOR EACH ROW EXECUTE FUNCTION poc_reject_schema_receipt_mutation();
      END IF;
    END
    $block$
  `,
]

const LOCAL_SECURITY_EVENT_AUDIT_SCHEMA = [
  `
    DO $block$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'poc_local_security_events'::regclass
          AND conname = 'ck_poc_local_security_event_type_v4'
      ) THEN
        ALTER TABLE poc_local_security_events
          DROP CONSTRAINT ck_poc_local_security_event_type,
          ADD CONSTRAINT ck_poc_local_security_event_type_v4 CHECK (
            event_type IN ('SELF_PASSWORD_CHANGED_V1', 'LOCAL_CREDENTIAL_PROVISIONED_V1')
          );
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'poc_local_security_events'::regclass
          AND conname = 'ck_poc_local_security_event_actor_v4'
      ) THEN
        ALTER TABLE poc_local_security_events
          DROP CONSTRAINT ck_poc_local_security_event_actor,
          ADD CONSTRAINT ck_poc_local_security_event_actor_v4 CHECK (
            char_length(actor_subject_id) BETWEEN 1 AND 255
            AND ((event_type = 'SELF_PASSWORD_CHANGED_V1'
                AND actor_kind = 'SELF' AND actor_subject_id = subject_id)
              OR (event_type = 'LOCAL_CREDENTIAL_PROVISIONED_V1'
                AND actor_kind = 'LOCAL_ADMIN'))
          );
      END IF;
    END
    $block$
  `,
]

const MCP_READ_RECEIPT_SCHEMA = [
  `
    CREATE OR REPLACE FUNCTION poc_reject_schema_receipt_mutation()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $function$
    BEGIN
      IF OLD.scope LIKE 'product-owned-schema-contract-v%'
        OR OLD.scope LIKE 'mcp-read-receipt-v1:%'
        OR (TG_OP = 'UPDATE' AND (
          NEW.scope LIKE 'product-owned-schema-contract-v%'
          OR NEW.scope LIKE 'mcp-read-receipt-v1:%'
        )) THEN
        RAISE EXCEPTION 'POC Product schema and MCP read receipts are immutable';
      END IF;
      IF TG_OP = 'DELETE' THEN
        RETURN OLD;
      END IF;
      RETURN NEW;
    END
    $function$
  `,
]

const CHAT_HISTORY_SCHEMA = [
  `
    CREATE TABLE IF NOT EXISTS poc_chat_sessions (
      session_id text PRIMARY KEY,
      owner_subject_id text NOT NULL,
      title text NOT NULL,
      is_favorite boolean NOT NULL DEFAULT false,
      archived boolean NOT NULL DEFAULT false,
      version bigint NOT NULL DEFAULT 1,
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      UNIQUE (session_id, owner_subject_id),
      CONSTRAINT ck_poc_chat_session_id CHECK (char_length(session_id) BETWEEN 1 AND 200),
      CONSTRAINT ck_poc_chat_session_owner CHECK (char_length(owner_subject_id) BETWEEN 1 AND 255),
      CONSTRAINT ck_poc_chat_session_title CHECK (char_length(title) BETWEEN 1 AND 240),
      CONSTRAINT ck_poc_chat_session_version CHECK (version > 0)
    )
  `,
  `
    CREATE INDEX IF NOT EXISTS ix_poc_chat_sessions_owner_updated
      ON poc_chat_sessions (owner_subject_id, updated_at DESC, session_id DESC)
      WHERE NOT archived
  `,
  `
    CREATE TABLE IF NOT EXISTS poc_chat_messages (
      message_id text PRIMARY KEY,
      session_id text NOT NULL,
      owner_subject_id text NOT NULL,
      ordinal bigint NOT NULL,
      role text NOT NULL,
      content text NOT NULL,
      evidence_json jsonb,
      discovery_json jsonb,
      route_json jsonb,
      workflow_json jsonb NOT NULL DEFAULT '[]'::jsonb,
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      UNIQUE (session_id, ordinal),
      FOREIGN KEY (session_id, owner_subject_id)
        REFERENCES poc_chat_sessions(session_id, owner_subject_id),
      CONSTRAINT ck_poc_chat_message_id CHECK (char_length(message_id) BETWEEN 1 AND 200),
      CONSTRAINT ck_poc_chat_message_owner CHECK (char_length(owner_subject_id) BETWEEN 1 AND 255),
      CONSTRAINT ck_poc_chat_message_ordinal CHECK (ordinal > 0),
      CONSTRAINT ck_poc_chat_message_role CHECK (role IN ('user', 'assistant')),
      CONSTRAINT ck_poc_chat_message_content CHECK (char_length(content) BETWEEN 1 AND 200000),
      CONSTRAINT ck_poc_chat_message_evidence CHECK (
        evidence_json IS NULL OR (jsonb_typeof(evidence_json) = 'array' AND octet_length(evidence_json::text) <= 1048576)
      ),
      CONSTRAINT ck_poc_chat_message_discovery CHECK (
        discovery_json IS NULL OR (jsonb_typeof(discovery_json) = 'object' AND octet_length(discovery_json::text) <= 1048576)
      ),
      CONSTRAINT ck_poc_chat_message_route CHECK (
        route_json IS NULL OR (jsonb_typeof(route_json) = 'object' AND octet_length(route_json::text) <= 262144)
      ),
      CONSTRAINT ck_poc_chat_message_workflow CHECK (
        jsonb_typeof(workflow_json) = 'array' AND octet_length(workflow_json::text) <= 262144
      )
    )
  `,
  `
    CREATE INDEX IF NOT EXISTS ix_poc_chat_messages_owner_session
      ON poc_chat_messages (owner_subject_id, session_id, ordinal)
  `,
]

const CHAT_DISCOVERY_SCHEMA_V5 = [
  `
    ALTER TABLE poc_chat_messages
      ADD COLUMN discovery_json jsonb,
      ADD CONSTRAINT ck_poc_chat_message_discovery CHECK (
        discovery_json IS NULL OR (jsonb_typeof(discovery_json) = 'object' AND octet_length(discovery_json::text) <= 1048576)
      )
  `,
]

const USER_TABLE_GRANT_SCHEMA = [
  `
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
    )
  `,
  `
    CREATE INDEX IF NOT EXISTS ix_poc_user_table_grants_active_table
      ON poc_user_table_grants (table_urn, subject_id) WHERE active
  `,
]

// K5 is intentionally a small, POC-owned durable bridge. It stores only non-secret
// execution/receipt metadata and a bounded disposable source-row fixture. It is not a
// replacement for the canonical ADR-0094 Python plane or a general job framework.
const KNOWLEDGE_INGESTION_SCHEMA = [
  `
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
    )
  `,
  `
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
    )
  `,
  `
    CREATE INDEX IF NOT EXISTS ix_poc_knowledge_source_rows_asset
      ON poc_knowledge_source_rows (manifest_ref, asset_urn, source_version, row_key)
  `,
]

const K9_MANAGED_GRAPH_SCHEMA = [
  `
    CREATE TABLE IF NOT EXISTS poc_k9_managed_graph_policies (
        graph_id char(36) PRIMARY KEY,
        name varchar(255) NOT NULL,
        status varchar(50) NOT NULL,
        classification varchar(50) NOT NULL,
        ontology_version_id char(36) NOT NULL,
        studio_release_id char(36) NOT NULL,
        publication_version integer NOT NULL,
        schedule varchar(100) NOT NULL,
        managed_intent varchar(100) NOT NULL,
        accepted_proposal_id varchar(255) NOT NULL,
        subject_id varchar(255) NOT NULL,
        workspace_id varchar(255) NOT NULL,
        policy_hash char(64) NOT NULL,
        tbox_hash char(64) NOT NULL,
        contract_hash char(64) NOT NULL,
        proposal_hash char(64) NOT NULL,
        source_hash char(64) NOT NULL,
        mapping_hash char(64) NOT NULL,
        active_release_pointer varchar(255),
        active_release_hash char(64),
        created_at timestamp with time zone NOT NULL,
        updated_at timestamp with time zone NOT NULL,
        CONSTRAINT chk_k9_graph_id CHECK (graph_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
        CONSTRAINT chk_k9_ontology_id CHECK (ontology_version_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
        CONSTRAINT chk_k9_studio_id CHECK (studio_release_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
        CONSTRAINT chk_k9_policy_hash CHECK (policy_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT chk_k9_tbox_hash CHECK (tbox_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT chk_k9_contract_hash CHECK (contract_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT chk_k9_proposal_hash CHECK (proposal_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT chk_k9_source_hash CHECK (source_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT chk_k9_mapping_hash CHECK (mapping_hash ~ '^[0-9a-f]{64}$')
    )
  `,
  `
    CREATE TABLE IF NOT EXISTS poc_k9_refresh_runs (
        run_id char(36) PRIMARY KEY,
        graph_id char(36) NOT NULL,
        status varchar(50) NOT NULL,
        input_snapshot_hash char(64),
        policy_hash char(64) NOT NULL,
        manifest jsonb,
        canonical_release jsonb,
        started_at timestamp with time zone NOT NULL,
        completed_at timestamp with time zone,
        active_release_pointer varchar(255),
        error_message text,
        CONSTRAINT chk_k9_run_id CHECK (run_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
        CONSTRAINT chk_k9_r_policy_hash CHECK (policy_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT chk_k9_r_snapshot_hash CHECK (input_snapshot_hash IS NULL OR input_snapshot_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT chk_k9_r_status_hash CHECK (
            (status IN ('RUN', 'NO_OP') AND input_snapshot_hash IS NOT NULL AND manifest IS NOT NULL AND canonical_release IS NOT NULL) OR
            (status NOT IN ('RUN', 'NO_OP'))
        )
    )
  `,
  `
    CREATE INDEX IF NOT EXISTS idx_poc_k9_refresh_runs_graph ON poc_k9_refresh_runs(graph_id, started_at DESC)
  `,
  `
    CREATE UNIQUE INDEX IF NOT EXISTS idx_poc_k9_preparing_run ON poc_k9_refresh_runs(graph_id) WHERE status = 'PREPARING'
  `
]

async function applyPocPostgresV1Schema(client) {
  await client.query(`
    CREATE TABLE IF NOT EXISTS poc_state (
      scope text PRIMARY KEY,
      value jsonb NOT NULL,
      version bigint NOT NULL DEFAULT 1,
      updated_at timestamptz NOT NULL DEFAULT now()
    )
  `)
  await client.query(`
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
    )
  `)
  for (const statement of CHANGE_HISTORY_SCHEMA) await client.query(statement)
  for (const statement of LOCAL_AUTH_SCHEMA) await client.query(statement)
  for (const statement of CHAT_HISTORY_SCHEMA) await client.query(statement)
  for (const statement of USER_TABLE_GRANT_SCHEMA) await client.query(statement)
  for (const statement of KNOWLEDGE_INGESTION_SCHEMA) await client.query(statement)
  for (const statement of K9_MANAGED_GRAPH_SCHEMA) await client.query(statement)
}

async function applyPocPostgresSchema(client) {
  await applyPocPostgresV1Schema(client)
  for (const statement of LOCAL_SECURITY_EVENT_SCHEMA) await client.query(statement)
  for (const statement of MCP_READ_RECEIPT_SCHEMA) await client.query(statement)
  for (const statement of LOCAL_SECURITY_EVENT_AUDIT_SCHEMA) await client.query(statement)
}

async function initializePocPostgresSchema(pool, integrityRequired) {
  if (!integrityRequired) {
    await applyPocPostgresSchema(pool)
    return
  }
  const client = await pool.connect()
  try {
    await convergePocPostgresOwnedSchema(client, {
      applyFreshSchema: applyPocPostgresSchema,
      applyKnownOlderSchema: applyPocPostgresV1Schema,
      applyV2Schema: async (migrationClient) => {
        for (const statement of LOCAL_SECURITY_EVENT_SCHEMA) await migrationClient.query(statement)
      },
      applyV3Schema: async (migrationClient) => {
        for (const statement of MCP_READ_RECEIPT_SCHEMA) await migrationClient.query(statement)
      },
      applyV4Schema: async (migrationClient) => {
        for (const statement of LOCAL_SECURITY_EVENT_AUDIT_SCHEMA) await migrationClient.query(statement)
      },
      applyV5Schema: async (migrationClient) => {
        for (const statement of CHAT_DISCOVERY_SCHEMA_V5) await migrationClient.query(statement)
      },
    })
  } finally {
    client.release()
  }
}


export function createPocStateStore({ databasePool } = {}) {
  const databaseUrl = process.env.POC_DATABASE_URL?.trim()
  const databaseHost = process.env.POC_POSTGRES_HOST?.trim()
  assertIsolatedTestDatabaseTarget({ databasePool, databaseUrl, databaseHost })
  const databaseConfigured = Boolean(databasePool || databaseUrl || databaseHost)
  const schemaIntegritySetting = process.env[POC_POSTGRES_SCHEMA_INTEGRITY_FLAG]?.trim().toLowerCase()
  if (schemaIntegritySetting && !['true', 'false'].includes(schemaIntegritySetting)) {
    throw Object.assign(new Error('PostgreSQL schema integrity setting must be true or false.'), {
      code: 'POC_POSTGRES_SCHEMA_INTEGRITY_CONFIG_INVALID',
    })
  }
  const schemaIntegrityRequired = schemaIntegritySetting === 'true'
  const redisUrl = process.env.POC_REDIS_URL?.trim()
  const memory = new Map()
  const memoryCatalogEmbeddings = new Map()
  const memoryCatalogEmbeddingGenerationLocks = new Map()
  const memoryCredentialsBySubject = new Map()
  const memoryCredentialSubjectByUsername = new Map()
  const memorySessions = new Map()
  const memoryLocalSecurityEvents = []
  const memoryUserTableGrants = new Map()
  const memoryChatSessions = new Map()
  const memoryChatMessages = new Map()
  let pool = databasePool
  let redis
  let startingDatabase
  let startingRedis

  async function startDatabase() {
    if (!databaseConfigured) return
    if (startingDatabase) return startingDatabase
    startingDatabase = (async () => {
      if (!pool) {
        pool = new Pool(databaseUrl ? {
          connectionString: databaseUrl, max: 4, idleTimeoutMillis: 30_000,
        } : {
          host: databaseHost,
          port: Number(process.env.POC_POSTGRES_PORT || 5432),
          database: process.env.POC_POSTGRES_DB?.trim() || 'datariver_poc',
          user: process.env.POC_POSTGRES_USER?.trim() || 'datariver_poc',
          password: process.env.POC_POSTGRES_PASSWORD || undefined,
          max: 4,
          idleTimeoutMillis: 30_000,
        })
      }
      pool.on?.('error', () => undefined)
      await initializePocPostgresSchema(pool, schemaIntegrityRequired)
    })()
    try {
      await startingDatabase
    } catch (error) {
      startingDatabase = undefined
      if (!databasePool) {
        await Promise.allSettled([pool?.end()])
        pool = undefined
      }
      throw error
    }
  }

  async function startRedis() {
    if (!redisUrl || redis) return
    if (startingRedis) return startingRedis
    startingRedis = (async () => {
      const client = createClient({
        url: redisUrl,
        socket: { reconnectStrategy: false },
      })
      client.on('error', () => undefined)
      try {
        await client.connect()
        redis = client
      } catch {
        if (client.isOpen) client.destroy()
      }
    })()
    try {
      await startingRedis
    } finally {
      startingRedis = undefined
    }
  }

  async function read(scope) {
    await startDatabase()
    if (pool) {
      const result = await pool.query('SELECT value, version FROM poc_state WHERE scope = $1', [scope])
      if (result.rows[0]) return { value: result.rows[0].value, version: Number(result.rows[0].version) }
    }
    return memory.has(scope) ? memory.get(scope) : { value: null, version: 0 }
  }

  async function readFeatureSecurityPolicy() {
    return read('feature-security-policy-v1')
  }

  async function write(scope, value) {
    await startDatabase()
    if (String(scope).startsWith(MCP_READ_RECEIPT_SCOPE_PREFIX)) {
      throw Object.assign(new Error('MCP read receipts are append-only.'), { code: 'MCP_READ_RECEIPT_IMMUTABLE' })
    }
    if (scope === 'core') return writeCoreWithAccessFence(value)
    if (pool) {
      const result = await pool.query(`
        INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
        ON CONFLICT (scope) DO UPDATE
          SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
        RETURNING version
      `, [scope, JSON.stringify(value)])
      return Number(result.rows[0].version)
    }
    const version = (memory.get(scope)?.version ?? 0) + 1
    memory.set(scope, { value, version })
    return version
  }

  async function writeIfVersion(scope, value, expectedVersion) {
    requireNonnegativeInteger(expectedVersion, 'expectedVersion')
    await startDatabase()
    if (String(scope).startsWith(MCP_READ_RECEIPT_SCOPE_PREFIX)) {
      throw Object.assign(new Error('MCP read receipts are append-only.'), { code: 'MCP_READ_RECEIPT_IMMUTABLE' })
    }
    if (scope === 'core') return writeCoreWithAccessFence(value, expectedVersion)
    if (pool) {
      const client = await pool.connect()
      try {
        await client.query('BEGIN')
        await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1, 0))', [scope])
        const selected = await client.query('SELECT version FROM poc_state WHERE scope = $1 FOR UPDATE', [scope])
        if (Number(selected.rows[0]?.version ?? 0) !== expectedVersion) throw stateVersionConflict()
        const result = selected.rows.length
          ? await client.query(`
              UPDATE poc_state
              SET value = $2::jsonb, version = version + 1, updated_at = now()
              WHERE scope = $1
              RETURNING version
            `, [scope, JSON.stringify(value)])
          : await client.query(`
              INSERT INTO poc_state (scope, value, version)
              VALUES ($1, $2::jsonb, 1)
              RETURNING version
            `, [scope, JSON.stringify(value)])
        await client.query('COMMIT')
        return Number(result.rows[0].version)
      } catch (error) {
        await client.query('ROLLBACK')
        throw error
      } finally {
        client.release()
      }
    }
    const current = memory.get(scope) ?? { value: null, version: 0 }
    if (current.version !== expectedVersion) throw stateVersionConflict()
    const version = current.version + 1
    memory.set(scope, { value, version })
    return version
  }

  async function readMcpReadReceipt(receiptIdValue) {
    const receiptId = requireSha256(receiptIdValue, 'receiptId')
    const record = await read(`${MCP_READ_RECEIPT_SCOPE_PREFIX}${receiptId}`)
    return record.value === null ? null : normalizeMcpReadReceipt(record.value)
  }

  async function appendMcpReadReceipt(receiptValue) {
    const receipt = normalizeMcpReadReceipt(receiptValue)
    const scope = `${MCP_READ_RECEIPT_SCOPE_PREFIX}${receipt.receipt_id}`
    await startDatabase()
    if (pool) {
      const inserted = await pool.query(`
        INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
        ON CONFLICT (scope) DO NOTHING
        RETURNING value
      `, [scope, JSON.stringify(receipt)])
      if (inserted.rows[0]) return { created: true, receipt: normalizeMcpReadReceipt(inserted.rows[0].value) }
      const existing = await pool.query('SELECT value FROM poc_state WHERE scope = $1', [scope])
      const stored = existing.rows[0]?.value ? normalizeMcpReadReceipt(existing.rows[0].value) : null
      if (!stored || stableJson(stored) !== stableJson(receipt)) {
        throw Object.assign(new Error('The MCP read receipt identity conflicts with prior evidence.'), {
          code: 'MCP_READ_RECEIPT_CONFLICT',
        })
      }
      return { created: false, receipt: stored }
    }
    const current = memory.get(scope)
    if (current) {
      const stored = normalizeMcpReadReceipt(current.value)
      if (stableJson(stored) !== stableJson(receipt)) {
        throw Object.assign(new Error('The MCP read receipt identity conflicts with prior evidence.'), {
          code: 'MCP_READ_RECEIPT_CONFLICT',
        })
      }
      return { created: false, receipt: stored }
    }
    memory.set(scope, { value: receipt, version: 1 })
    return { created: true, receipt }
  }

  async function writeCoreWithAccessFence(value, expectedVersion) {
    if (pool) {
      const client = await pool.connect()
      try {
        await client.query('BEGIN')
        await client.query(
          'SELECT pg_advisory_xact_lock(hashtextextended($1, 0))',
          [CHANGE_HISTORY_ACCESS_SCOPE],
        )
        const locked = await client.query(`
          SELECT scope, value, version FROM poc_state
          WHERE scope IN ($1, $2)
          ORDER BY scope
          FOR UPDATE
        `, CHANGE_HISTORY_ACCESS_SCOPES)
        const accessRow = locked.rows.find((row) => row.scope === CHANGE_HISTORY_ACCESS_SCOPE)
        const coreRow = locked.rows.find((row) => row.scope === 'core')
        if (expectedVersion !== undefined && Number(coreRow?.version ?? 0) !== expectedVersion) {
          throw stateVersionConflict()
        }
        const fencedValue = preserveProtectedCoreAccessFields(value, coreRow?.value, Boolean(accessRow))
        const result = await client.query(`
          INSERT INTO poc_state (scope, value) VALUES ('core', $1::jsonb)
          ON CONFLICT (scope) DO UPDATE
            SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
          RETURNING version
        `, [JSON.stringify(fencedValue)])
        await client.query('COMMIT')
        return Number(result.rows[0].version)
      } catch (error) {
        await client.query('ROLLBACK')
        throw error
      } finally {
        client.release()
      }
    }
    const accessExists = memory.has(CHANGE_HISTORY_ACCESS_SCOPE)
    const currentRecord = memory.get('core') ?? { value: null, version: 0 }
    if (expectedVersion !== undefined && currentRecord.version !== expectedVersion) throw stateVersionConflict()
    const currentCore = currentRecord.value
    const fencedValue = preserveProtectedCoreAccessFields(value, currentCore, accessExists)
    const version = (memory.get('core')?.version ?? 0) + 1
    memory.set('core', { value: fencedValue, version })
    return version
  }

  async function readChangeHistoryAccess() {
    await startDatabase()
    if (pool) {
      const result = await pool.query(`
        SELECT scope, value, version FROM poc_state
        WHERE scope IN ($1, $2)
      `, CHANGE_HISTORY_ACCESS_SCOPES)
      return changeHistoryAccessSnapshot(result.rows)
    }
    return {
      access: memory.get(CHANGE_HISTORY_ACCESS_SCOPE) ?? { value: null, version: 0 },
      core: memory.get('core') ?? { value: null, version: 0 },
    }
  }

  async function writeChangeHistoryAccess({
    expectedAccessVersion,
    expectedCoreVersion,
    accessValue,
    coreValue,
  }) {
    requireNonnegativeInteger(expectedAccessVersion, 'expectedAccessVersion')
    requireNonnegativeInteger(expectedCoreVersion, 'expectedCoreVersion')
    await startDatabase()
    if (pool) {
      const client = await pool.connect()
      try {
        await client.query('BEGIN')
        await client.query(
          'SELECT pg_advisory_xact_lock(hashtextextended($1, 0))',
          [CHANGE_HISTORY_ACCESS_SCOPE],
        )
        const locked = await client.query(`
          SELECT scope, value, version FROM poc_state
          WHERE scope IN ($1, $2)
          ORDER BY scope
          FOR UPDATE
        `, CHANGE_HISTORY_ACCESS_SCOPES)
        const current = changeHistoryAccessSnapshot(locked.rows)
        assertAccessVersions(current, expectedAccessVersion, expectedCoreVersion)
        const accessWrite = await client.query(`
          INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
          ON CONFLICT (scope) DO UPDATE
            SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
          RETURNING version
        `, [CHANGE_HISTORY_ACCESS_SCOPE, JSON.stringify(accessValue)])
        const coreWrite = await client.query(`
          INSERT INTO poc_state (scope, value) VALUES ('core', $1::jsonb)
          ON CONFLICT (scope) DO UPDATE
            SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
          RETURNING version
        `, [JSON.stringify(coreValue)])
        await client.query('COMMIT')
        return {
          accessVersion: Number(accessWrite.rows[0].version),
          coreVersion: Number(coreWrite.rows[0].version),
        }
      } catch (error) {
        await client.query('ROLLBACK')
        throw error
      } finally {
        client.release()
      }
    }
    const current = {
      access: memory.get(CHANGE_HISTORY_ACCESS_SCOPE) ?? { value: null, version: 0 },
      core: memory.get('core') ?? { value: null, version: 0 },
    }
    assertAccessVersions(current, expectedAccessVersion, expectedCoreVersion)
    const accessVersion = current.access.version + 1
    const coreVersion = current.core.version + 1
    memory.set(CHANGE_HISTORY_ACCESS_SCOPE, { value: accessValue, version: accessVersion })
    memory.set('core', { value: coreValue, version: coreVersion })
    return { accessVersion, coreVersion }
  }

  async function readLocalCredential(usernameNormalized) {
    requireNormalizedUsername(usernameNormalized)
    await startDatabase()
    if (pool) {
      const result = await pool.query(`
        SELECT subject_id, username_normalized, password_hash, login_enabled,
          must_change_password, failed_attempts, locked_until, version
        FROM poc_local_credentials
        WHERE username_normalized = $1
      `, [usernameNormalized])
      return result.rows[0] ? localCredentialRecord(result.rows[0]) : null
    }
    const subjectId = memoryCredentialSubjectByUsername.get(usernameNormalized)
    const credential = subjectId ? memoryCredentialsBySubject.get(subjectId) : undefined
    return credential ? structuredClone(credential) : null
  }

  async function readLocalCredentialForSubject(subjectId) {
    requireBoundedString(subjectId, 'subjectId', 255)
    await startDatabase()
    if (pool) {
      const result = await pool.query(`
        SELECT subject_id, username_normalized, password_hash, login_enabled,
          must_change_password, failed_attempts, locked_until, version
        FROM poc_local_credentials
        WHERE subject_id = $1
      `, [subjectId])
      return result.rows[0] ? localCredentialRecord(result.rows[0]) : null
    }
    const credential = memoryCredentialsBySubject.get(subjectId)
    return credential ? structuredClone(credential) : null
  }

  async function provisionLocalCredential({
    expectedAccessVersion,
    expectedCoreVersion,
    credential,
    accessValue,
    coreValue,
    actorSubjectId,
  }) {
    requireNonnegativeInteger(expectedAccessVersion, 'expectedAccessVersion')
    requireNonnegativeInteger(expectedCoreVersion, 'expectedCoreVersion')
    const normalized = normalizeLocalCredential(credential)
    if (actorSubjectId !== undefined) requireBoundedString(actorSubjectId, 'actorSubjectId', 255)
    const writesAccess = accessValue !== undefined || coreValue !== undefined
    if (writesAccess && (accessValue === undefined || coreValue === undefined)) {
      throw new Error('accessValue and coreValue must be supplied together.')
    }
    await startDatabase()
    if (pool) {
      const client = await pool.connect()
      try {
        await client.query('BEGIN')
        await client.query(
          'SELECT pg_advisory_xact_lock(hashtextextended($1, 0))',
          [CHANGE_HISTORY_ACCESS_SCOPE],
        )
        const locked = await client.query(`
          SELECT scope, value, version FROM poc_state
          WHERE scope IN ($1, $2)
          ORDER BY scope
          FOR UPDATE
        `, CHANGE_HISTORY_ACCESS_SCOPES)
        const current = changeHistoryAccessSnapshot(locked.rows)
        assertAccessVersions(current, expectedAccessVersion, expectedCoreVersion)
        const inserted = await client.query(`
          INSERT INTO poc_local_credentials (
            subject_id, username_normalized, password_hash, login_enabled, must_change_password
          ) VALUES ($1, $2, $3, $4, $5)
          ON CONFLICT DO NOTHING
          RETURNING version
        `, [
          normalized.subjectId,
          normalized.usernameNormalized,
          normalized.passwordHash,
          normalized.loginEnabled,
          normalized.mustChangePassword,
        ])
        if (inserted.rows.length !== 1) throw credentialConflict()
        if (actorSubjectId !== undefined) {
          const event = await client.query(`
            INSERT INTO poc_local_security_events (
              event_id, event_type, subject_id, actor_subject_id, actor_kind,
              resulting_credential_version, revoked_session_count
            ) VALUES ($1, 'LOCAL_CREDENTIAL_PROVISIONED_V1', $2, $3, 'LOCAL_ADMIN', $4, 0)
            RETURNING event_id, occurred_at
          `, [randomUUID(), normalized.subjectId, actorSubjectId, Number(inserted.rows[0].version)])
          if (event.rows.length !== 1) {
            throw new Error('The local credential provisioning security receipt was not inserted.')
          }
        }
        let accessVersion = current.access.version
        let coreVersion = current.core.version
        if (writesAccess) {
          const accessWrite = await client.query(`
            INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
            ON CONFLICT (scope) DO UPDATE
              SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
            RETURNING version
          `, [CHANGE_HISTORY_ACCESS_SCOPE, JSON.stringify(accessValue)])
          const coreWrite = await client.query(`
            INSERT INTO poc_state (scope, value) VALUES ('core', $1::jsonb)
            ON CONFLICT (scope) DO UPDATE
              SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
            RETURNING version
          `, [JSON.stringify(coreValue)])
          accessVersion = Number(accessWrite.rows[0].version)
          coreVersion = Number(coreWrite.rows[0].version)
        }
        await client.query('COMMIT')
        return { credentialVersion: Number(inserted.rows[0].version), accessVersion, coreVersion }
      } catch (error) {
        await client.query('ROLLBACK')
        throw error
      } finally {
        client.release()
      }
    }
    const current = {
      access: memory.get(CHANGE_HISTORY_ACCESS_SCOPE) ?? { value: null, version: 0 },
      core: memory.get('core') ?? { value: null, version: 0 },
    }
    assertAccessVersions(current, expectedAccessVersion, expectedCoreVersion)
    if (memoryCredentialsBySubject.has(normalized.subjectId)
      || memoryCredentialSubjectByUsername.has(normalized.usernameNormalized)) throw credentialConflict()
    const record = {
      ...normalized,
      failedAttempts: 0,
      lockedUntil: null,
      version: 1,
    }
    memoryCredentialsBySubject.set(normalized.subjectId, record)
    memoryCredentialSubjectByUsername.set(normalized.usernameNormalized, normalized.subjectId)
    if (actorSubjectId !== undefined) {
      memoryLocalSecurityEvents.push(Object.freeze({
        eventId: randomUUID(),
        eventType: 'LOCAL_CREDENTIAL_PROVISIONED_V1',
        subjectId: normalized.subjectId,
        actorSubjectId,
        actorKind: 'LOCAL_ADMIN',
        occurredAt: new Date().toISOString(),
        resultingCredentialVersion: 1,
        revokedSessionCount: 0,
      }))
    }
    let accessVersion = current.access.version
    let coreVersion = current.core.version
    if (writesAccess) {
      accessVersion += 1
      coreVersion += 1
      memory.set(CHANGE_HISTORY_ACCESS_SCOPE, { value: accessValue, version: accessVersion })
      memory.set('core', { value: coreValue, version: coreVersion })
    }
    return { credentialVersion: 1, accessVersion, coreVersion }
  }

  async function insertLocalCredential({ expectedAccessVersion, expectedCoreVersion, ...credential }) {
    return provisionLocalCredential({ expectedAccessVersion, expectedCoreVersion, credential })
  }

  async function recordLocalLoginFailure({
    subjectId,
    expectedVersion,
    failedAttempts,
    lockedUntil,
  }) {
    requireBoundedString(subjectId, 'subjectId', 255)
    requirePositiveInteger(expectedVersion, 'expectedVersion')
    requireNonnegativeInteger(failedAttempts, 'failedAttempts')
    if (failedAttempts > 1000) throw new Error('failedAttempts exceeds its bound.')
    if (lockedUntil !== null) requireTimestamp(lockedUntil, 'lockedUntil')
    await startDatabase()
    if (pool) {
      const result = await pool.query(`
        UPDATE poc_local_credentials
        SET failed_attempts = $3, locked_until = $4, version = version + 1, updated_at = clock_timestamp()
        WHERE subject_id = $1 AND version = $2
        RETURNING version
      `, [subjectId, expectedVersion, failedAttempts, lockedUntil])
      return result.rows.length === 1
    }
    const current = memoryCredentialsBySubject.get(subjectId)
    if (!current || current.version !== expectedVersion) return false
    current.failedAttempts = failedAttempts
    current.lockedUntil = lockedUntil
    current.version += 1
    return true
  }

  async function recordLocalLoginSuccess({ subjectId, expectedVersion }) {
    requireBoundedString(subjectId, 'subjectId', 255)
    requirePositiveInteger(expectedVersion, 'expectedVersion')
    await startDatabase()
    if (pool) {
      const result = await pool.query(`
        UPDATE poc_local_credentials
        SET failed_attempts = 0, locked_until = NULL, version = version + 1, updated_at = clock_timestamp()
        WHERE subject_id = $1 AND version = $2
        RETURNING version
      `, [subjectId, expectedVersion])
      return result.rows.length === 1
    }
    const current = memoryCredentialsBySubject.get(subjectId)
    if (!current || current.version !== expectedVersion) return false
    current.failedAttempts = 0
    current.lockedUntil = null
    current.version += 1
    return true
  }

  async function createLocalSession({ tokenHash, subjectId, createdAt, expiresAt }) {
    requireSha256(tokenHash, 'tokenHash')
    requireBoundedString(subjectId, 'subjectId', 255)
    requireTimestamp(createdAt, 'createdAt')
    requireTimestamp(expiresAt, 'expiresAt')
    if (Date.parse(expiresAt) <= Date.parse(createdAt)) throw new Error('Session expiry must follow creation.')
    await startDatabase()
    if (pool) {
      await pool.query(`
        INSERT INTO poc_local_sessions (token_hash, subject_id, created_at, expires_at)
        VALUES ($1, $2, $3, $4)
      `, [tokenHash, subjectId, createdAt, expiresAt])
      return
    }
    if (!memoryCredentialsBySubject.has(subjectId)) throw new Error('Session subject has no credential.')
    if (memorySessions.has(tokenHash)) throw new Error('Session token hash already exists.')
    memorySessions.set(tokenHash, { tokenHash, subjectId, createdAt, expiresAt, revokedAt: null })
  }

  async function readLocalSession(tokenHash) {
    requireSha256(tokenHash, 'tokenHash')
    await startDatabase()
    if (pool) {
      const result = await pool.query(`
        SELECT session.token_hash, session.subject_id, session.created_at,
          session.expires_at, session.revoked_at, credential.must_change_password
        FROM poc_local_sessions AS session
        JOIN poc_local_credentials AS credential ON credential.subject_id = session.subject_id
        WHERE session.token_hash = $1
      `, [tokenHash])
      return result.rows[0] ? localSessionRecord(result.rows[0]) : null
    }
    const session = memorySessions.get(tokenHash)
    if (!session) return null
    return {
      ...structuredClone(session),
      mustChangePassword: memoryCredentialsBySubject.get(session.subjectId)?.mustChangePassword === true,
    }
  }

  async function revokeLocalSession({ tokenHash, revokedAt }) {
    requireSha256(tokenHash, 'tokenHash')
    requireTimestamp(revokedAt, 'revokedAt')
    await startDatabase()
    if (pool) {
      const result = await pool.query(`
        UPDATE poc_local_sessions
        SET revoked_at = COALESCE(revoked_at, $2)
        WHERE token_hash = $1
        RETURNING token_hash
      `, [tokenHash, revokedAt])
      return result.rows.length === 1
    }
    const session = memorySessions.get(tokenHash)
    if (!session) return false
    session.revokedAt ??= revokedAt
    return true
  }

  async function disableLocalCredential({ usernameNormalized, expectedVersion, disabledAt }) {
    requireNormalizedUsername(usernameNormalized)
    requirePositiveInteger(expectedVersion, 'expectedVersion')
    requireTimestamp(disabledAt, 'disabledAt')
    await startDatabase()
    if (pool) {
      const client = await pool.connect()
      try {
        await client.query('BEGIN')
        const selected = await client.query(`
          SELECT subject_id, version, login_enabled
          FROM poc_local_credentials
          WHERE username_normalized = $1
          FOR UPDATE
        `, [usernameNormalized])
        const current = selected.rows[0]
        if (!current) {
          await client.query('ROLLBACK')
          return null
        }
        if (Number(current.version) !== expectedVersion) throw credentialVersionConflict()
        const updated = await client.query(`
          UPDATE poc_local_credentials
          SET login_enabled = false, version = version + 1, updated_at = $3
          WHERE subject_id = $1 AND version = $2
          RETURNING subject_id, version, login_enabled
        `, [current.subject_id, expectedVersion, disabledAt])
        if (updated.rows.length !== 1) throw credentialVersionConflict()
        const revoked = await client.query(`
          UPDATE poc_local_sessions
          SET revoked_at = COALESCE(revoked_at, $2)
          WHERE subject_id = $1 AND revoked_at IS NULL
          RETURNING token_hash
        `, [current.subject_id, disabledAt])
        await client.query('COMMIT')
        return {
          subjectId: current.subject_id,
          credentialVersion: Number(updated.rows[0].version),
          loginEnabled: false,
          revokedSessionCount: revoked.rows.length,
        }
      } catch (error) {
        await client.query('ROLLBACK')
        throw error
      } finally {
        client.release()
      }
    }
    const subjectId = memoryCredentialSubjectByUsername.get(usernameNormalized)
    const current = subjectId ? memoryCredentialsBySubject.get(subjectId) : undefined
    if (!current) return null
    if (current.version !== expectedVersion) throw credentialVersionConflict()
    current.loginEnabled = false
    current.version += 1
    let revokedSessionCount = 0
    for (const session of memorySessions.values()) {
      if (session.subjectId === subjectId && !session.revokedAt) {
        session.revokedAt = disabledAt
        revokedSessionCount += 1
      }
    }
    return {
      subjectId,
      credentialVersion: current.version,
      loginEnabled: false,
      revokedSessionCount,
    }
  }

  async function listLocalCredentialAdministration() {
    await startDatabase()
    if (pool) {
      const result = await pool.query(`
        SELECT credential.subject_id, credential.username_normalized,
          credential.login_enabled, credential.must_change_password,
          credential.failed_attempts, credential.locked_until, credential.version,
          count(session.token_hash) FILTER (
            WHERE session.revoked_at IS NULL AND session.expires_at > clock_timestamp()
          ) AS active_session_count
        FROM poc_local_credentials AS credential
        LEFT JOIN poc_local_sessions AS session ON session.subject_id = credential.subject_id
        GROUP BY credential.subject_id, credential.username_normalized,
          credential.login_enabled, credential.must_change_password,
          credential.failed_attempts, credential.locked_until, credential.version
        ORDER BY credential.username_normalized
      `)
      return result.rows.map((row) => ({
        subjectId: row.subject_id,
        usernameNormalized: row.username_normalized,
        loginEnabled: row.login_enabled,
        mustChangePassword: row.must_change_password,
        failedAttempts: Number(row.failed_attempts),
        lockedUntil: timestampValue(row.locked_until),
        version: Number(row.version),
        activeSessionCount: Number(row.active_session_count),
      }))
    }
    return [...memoryCredentialsBySubject.values()].map((credential) => ({
      subjectId: credential.subjectId,
      usernameNormalized: credential.usernameNormalized,
      loginEnabled: credential.loginEnabled,
      mustChangePassword: credential.mustChangePassword,
      failedAttempts: credential.failedAttempts,
      lockedUntil: credential.lockedUntil,
      version: credential.version,
      activeSessionCount: [...memorySessions.values()].filter((session) => (
        session.subjectId === credential.subjectId && !session.revokedAt && Date.parse(session.expiresAt) > Date.now()
      )).length,
    })).sort((left, right) => left.usernameNormalized.localeCompare(right.usernameNormalized))
  }

  async function inspectPrepDeploymentFootprint() {
    await startDatabase()
    if (!pool) throw new Error('PREP deployment footprint inspection requires PostgreSQL.')
    const tables = [
      'poc_state',
      'poc_catalog_embedding',
      'poc_change_history_sources',
      'poc_change_history_ledger_events',
      'poc_change_history_checkpoints',
      'poc_change_history_cr_link_events',
      'poc_local_credentials',
      'poc_local_sessions',
      'poc_local_security_events',
      'poc_user_table_grants',
      'poc_knowledge_ingestion_jobs',
      'poc_knowledge_source_rows',
      'poc_k9_managed_graph_policies',
      'poc_k9_refresh_runs',
    ]
    const countsQuery = tables.map((table) => (
      `SELECT '${table}' AS table_name, count(*)::bigint AS row_count FROM ${table}`
    )).join(' UNION ALL ')
    const [counts, scopes, activeSessions, k9Runs] = await Promise.all([
      pool.query(countsQuery),
      pool.query('SELECT scope FROM poc_state ORDER BY scope'),
      pool.query(`
        SELECT count(*)::bigint AS row_count
        FROM poc_local_sessions
        WHERE revoked_at IS NULL AND expires_at > clock_timestamp()
      `),
      pool.query(`
        SELECT run_id, graph_id, status, policy_hash, active_release_pointer
        FROM poc_k9_refresh_runs
        ORDER BY started_at, run_id
      `),
    ])
    return {
      table_counts: Object.fromEntries(counts.rows.map((row) => [row.table_name, Number(row.row_count)])),
      state_scopes: scopes.rows.map((row) => row.scope),
      active_session_count: Number(activeSessions.rows[0]?.row_count || 0),
      k9_runs: k9Runs.rows,
    }
  }

  async function changeOwnLocalPassword({
    subjectId,
    expectedVersion,
    passwordHash,
  }) {
    requireBoundedString(subjectId, 'subjectId', 255)
    requirePositiveInteger(expectedVersion, 'expectedVersion')
    if (typeof passwordHash !== 'string' || passwordHash.length > 512
      || !passwordHash.startsWith('$argon2id$v=19$')) {
      throw new Error('passwordHash must be a bounded Argon2id encoded hash.')
    }
    await startDatabase()
    if (pool) {
      const client = await pool.connect()
      try {
        await client.query('BEGIN')
        const selected = await client.query(`
          SELECT subject_id, version
          FROM poc_local_credentials
          WHERE subject_id = $1
          FOR UPDATE
        `, [subjectId])
        if (Number(selected.rows[0]?.version ?? 0) !== expectedVersion) {
          throw credentialVersionConflict()
        }
        const updated = await client.query(`
          UPDATE poc_local_credentials
          SET password_hash = $3,
            must_change_password = false,
            failed_attempts = 0,
            locked_until = NULL,
            version = version + 1,
            updated_at = clock_timestamp()
          WHERE subject_id = $1 AND version = $2 AND login_enabled
          RETURNING version
        `, [subjectId, expectedVersion, passwordHash])
        if (updated.rows.length !== 1) throw credentialVersionConflict()
        const credentialVersion = Number(updated.rows[0].version)
        const revoked = await client.query(`
          UPDATE poc_local_sessions
          SET revoked_at = COALESCE(revoked_at, clock_timestamp())
          WHERE subject_id = $1 AND revoked_at IS NULL
          RETURNING token_hash
        `, [subjectId])
        const event = await client.query(`
          INSERT INTO poc_local_security_events (
            event_id, event_type, subject_id, actor_subject_id, actor_kind,
            resulting_credential_version, revoked_session_count
          ) VALUES ($1, 'SELF_PASSWORD_CHANGED_V1', $2, $2, 'SELF', $3, $4)
          RETURNING event_id, occurred_at
        `, [randomUUID(), subjectId, credentialVersion, revoked.rows.length])
        if (event.rows.length !== 1) {
          throw new Error('The local password security receipt was not inserted.')
        }
        await client.query('COMMIT')
        return {
          credentialVersion,
          revokedSessionCount: revoked.rows.length,
        }
      } catch (error) {
        await client.query('ROLLBACK')
        throw error
      } finally {
        client.release()
      }
    }
    const current = memoryCredentialsBySubject.get(subjectId)
    if (!current || current.version !== expectedVersion || !current.loginEnabled) {
      throw credentialVersionConflict()
    }
    const credentialVersion = current.version + 1
    if (memoryLocalSecurityEvents.some((event) => (
      event.eventType === 'SELF_PASSWORD_CHANGED_V1'
      && event.subjectId === subjectId
      && event.resultingCredentialVersion === credentialVersion
    ))) {
      throw new Error('The local password security receipt already exists.')
    }
    current.passwordHash = passwordHash
    current.mustChangePassword = false
    current.failedAttempts = 0
    current.lockedUntil = null
    current.version = credentialVersion
    let revokedSessionCount = 0
    const occurredAt = new Date().toISOString()
    for (const session of memorySessions.values()) {
      if (session.subjectId === subjectId && !session.revokedAt) {
        session.revokedAt = occurredAt
        revokedSessionCount += 1
      }
    }
    memoryLocalSecurityEvents.push(Object.freeze({
      eventId: randomUUID(),
      eventType: 'SELF_PASSWORD_CHANGED_V1',
      subjectId,
      actorSubjectId: subjectId,
      actorKind: 'SELF',
      occurredAt,
      resultingCredentialVersion: credentialVersion,
      revokedSessionCount,
    }))
    return { credentialVersion, revokedSessionCount }
  }

  async function administerLocalCredential({
    subjectId,
    expectedVersion,
    usernameNormalized,
    passwordHash,
    loginEnabled,
    mustChangePassword,
    changedAt,
  }) {
    requireBoundedString(subjectId, 'subjectId', 255)
    requireNonnegativeInteger(expectedVersion, 'expectedVersion')
    requireNormalizedUsername(usernameNormalized)
    requireTimestamp(changedAt, 'changedAt')
    if (typeof loginEnabled !== 'boolean' || typeof mustChangePassword !== 'boolean') {
      throw new Error('credential login flags must be boolean.')
    }
    if (passwordHash !== null && (typeof passwordHash !== 'string' || passwordHash.length > 512
      || !passwordHash.startsWith('$argon2id$v=19$'))) {
      throw new Error('passwordHash must be null or a bounded Argon2id encoded hash.')
    }
    await startDatabase()
    if (pool) {
      const client = await pool.connect()
      try {
        await client.query('BEGIN')
        const selected = await client.query(`
          SELECT subject_id, version FROM poc_local_credentials WHERE subject_id = $1 FOR UPDATE
        `, [subjectId])
        const current = selected.rows[0]
        if (Number(current?.version ?? 0) !== expectedVersion) throw credentialVersionConflict()
        let updated
        if (current) {
          updated = await client.query(`
            UPDATE poc_local_credentials
            SET username_normalized = $3,
              password_hash = COALESCE($4, password_hash),
              login_enabled = $5,
              must_change_password = $6,
              failed_attempts = CASE WHEN $4 IS NULL THEN failed_attempts ELSE 0 END,
              locked_until = CASE WHEN $4 IS NULL THEN locked_until ELSE NULL END,
              version = version + 1,
              updated_at = $7
            WHERE subject_id = $1 AND version = $2
            RETURNING version
          `, [subjectId, expectedVersion, usernameNormalized, passwordHash, loginEnabled, mustChangePassword, changedAt])
        } else {
          if (passwordHash === null) throw new Error('A password hash is required for a new local credential.')
          updated = await client.query(`
            INSERT INTO poc_local_credentials (
              subject_id, username_normalized, password_hash, login_enabled, must_change_password, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING version
          `, [subjectId, usernameNormalized, passwordHash, loginEnabled, mustChangePassword, changedAt])
        }
        const shouldRevoke = passwordHash !== null || !loginEnabled
        const revoked = shouldRevoke ? await client.query(`
          UPDATE poc_local_sessions
          SET revoked_at = COALESCE(revoked_at, $2)
          WHERE subject_id = $1 AND revoked_at IS NULL
          RETURNING token_hash
        `, [subjectId, changedAt]) : { rows: [] }
        await client.query('COMMIT')
        return {
          credentialVersion: Number(updated.rows[0].version),
          revokedSessionCount: revoked.rows.length,
        }
      } catch (error) {
        await client.query('ROLLBACK')
        if (error?.code === '23505') throw credentialConflict()
        throw error
      } finally {
        client.release()
      }
    }
    const current = memoryCredentialsBySubject.get(subjectId)
    if ((current?.version ?? 0) !== expectedVersion) throw credentialVersionConflict()
    if (!current && passwordHash === null) throw new Error('A password hash is required for a new local credential.')
    const otherSubject = memoryCredentialSubjectByUsername.get(usernameNormalized)
    if (otherSubject && otherSubject !== subjectId) throw credentialConflict()
    if (current && current.usernameNormalized !== usernameNormalized) {
      memoryCredentialSubjectByUsername.delete(current.usernameNormalized)
    }
    const next = current ?? {
      subjectId, failedAttempts: 0, lockedUntil: null, version: 0,
    }
    next.usernameNormalized = usernameNormalized
    next.passwordHash = passwordHash ?? next.passwordHash
    next.loginEnabled = loginEnabled
    next.mustChangePassword = mustChangePassword
    if (passwordHash !== null) {
      next.failedAttempts = 0
      next.lockedUntil = null
    }
    next.version += 1
    memoryCredentialsBySubject.set(subjectId, next)
    memoryCredentialSubjectByUsername.set(usernameNormalized, subjectId)
    let revokedSessionCount = 0
    if (passwordHash !== null || !loginEnabled) {
      for (const session of memorySessions.values()) {
        if (session.subjectId === subjectId && !session.revokedAt) {
          session.revokedAt = changedAt
          revokedSessionCount += 1
        }
      }
    }
    return { credentialVersion: next.version, revokedSessionCount }
  }

  async function revokeLocalSessionsForSubject({ subjectId, revokedAt }) {
    requireBoundedString(subjectId, 'subjectId', 255)
    requireTimestamp(revokedAt, 'revokedAt')
    await startDatabase()
    if (pool) {
      const result = await pool.query(`
        UPDATE poc_local_sessions
        SET revoked_at = COALESCE(revoked_at, $2)
        WHERE subject_id = $1 AND revoked_at IS NULL
        RETURNING token_hash
      `, [subjectId, revokedAt])
      return result.rows.length
    }
    let changed = 0
    for (const session of memorySessions.values()) {
      if (session.subjectId === subjectId && !session.revokedAt) {
        session.revokedAt = revokedAt
        changed += 1
      }
    }
    return changed
  }

  async function listUserTableGrants(subjectId, { includeInactive = false } = {}) {
    requireBoundedString(subjectId, 'subjectId', 255)
    await startDatabase()
    if (pool) {
      const result = await pool.query(`
        SELECT subject_id, table_urn, active, version, created_at, created_by, updated_at, updated_by
        FROM poc_user_table_grants
        WHERE subject_id = $1 AND ($2::boolean OR active)
        ORDER BY table_urn
      `, [subjectId, includeInactive])
      return result.rows.map(userTableGrantRecord)
    }
    return [...memoryUserTableGrants.values()]
      .filter((row) => row.subjectId === subjectId && (includeInactive || row.active))
      .sort((left, right) => left.tableUrn.localeCompare(right.tableUrn))
      .map((row) => structuredClone(row))
  }

  async function applyUserTableGrantCommand({ subjectId, tableUrns, action, actorSubjectId, changedAt }) {
    requireBoundedString(subjectId, 'subjectId', 255)
    requireBoundedString(actorSubjectId, 'actorSubjectId', 255)
    requireTimestamp(changedAt, 'changedAt')
    if (!['GRANT', 'REMOVE'].includes(action)) throw new Error('action must be GRANT or REMOVE.')
    if (!Array.isArray(tableUrns) || tableUrns.length < 1 || tableUrns.length > 2_000
      || new Set(tableUrns).size !== tableUrns.length) {
      throw new Error('tableUrns must contain 1-2000 unique current Table identities.')
    }
    for (const tableUrn of tableUrns) requireDatasetUrn(tableUrn)
    await startDatabase()
    if (pool) {
      const result = action === 'GRANT'
        ? await pool.query(`
            INSERT INTO poc_user_table_grants (
              subject_id, table_urn, active, created_at, created_by, updated_at, updated_by
            )
            SELECT $1, table_urn, true, $4, $3, $4, $3
            FROM unnest($2::text[]) AS table_urn
            ON CONFLICT (subject_id, table_urn) DO UPDATE
              SET active = true,
                version = poc_user_table_grants.version + 1,
                updated_at = EXCLUDED.updated_at,
                updated_by = EXCLUDED.updated_by
              WHERE NOT poc_user_table_grants.active
            RETURNING table_urn
          `, [subjectId, tableUrns, actorSubjectId, changedAt])
        : await pool.query(`
            UPDATE poc_user_table_grants
            SET active = false, version = version + 1, updated_at = $4, updated_by = $3
            WHERE subject_id = $1 AND table_urn = ANY($2::text[]) AND active
            RETURNING table_urn
          `, [subjectId, tableUrns, actorSubjectId, changedAt])
      return result.rows.length
    }
    let changed = 0
    for (const tableUrn of tableUrns) {
      const key = `${subjectId}\u0000${tableUrn}`
      const existing = memoryUserTableGrants.get(key)
      if (action === 'GRANT' && !existing?.active) {
        if (existing) {
          existing.active = true
          existing.version += 1
          existing.updatedAt = changedAt
          existing.updatedBy = actorSubjectId
        } else {
          memoryUserTableGrants.set(key, {
            subjectId, tableUrn, active: true, version: 1,
            createdAt: changedAt, createdBy: actorSubjectId,
            updatedAt: changedAt, updatedBy: actorSubjectId,
          })
        }
        changed += 1
      } else if (action === 'REMOVE' && existing?.active) {
        existing.active = false
        existing.version += 1
        existing.updatedAt = changedAt
        existing.updatedBy = actorSubjectId
        changed += 1
      }
    }
    return changed
  }

  async function cacheGet(key) {
    await startRedis()
    if (!redis) return undefined
    const value = await redis.get(`datariver:poc:cache:${key}`)
    return value ? JSON.parse(value) : undefined
  }

  async function cacheSet(key, value, ttlSeconds) {
    await startRedis()
    if (!redis) return
    await redis.set(`datariver:poc:cache:${key}`, JSON.stringify(value), { EX: ttlSeconds })
  }

  async function cacheDelete(key) {
    await startRedis()
    if (!redis) return
    await redis.del(`datariver:poc:cache:${key}`)
  }

  async function catalogEmbeddingHashes(bindingHash) {
    await startDatabase()
    const sourceGeneration = await catalogEmbeddingActiveGeneration(bindingHash)
    if (!sourceGeneration) return new Map()
    if (pool) {
      const result = await pool.query(
        `SELECT asset_urn, source_hash FROM poc_catalog_embedding
         WHERE binding_hash = $1 AND source_generation = $2`,
        [bindingHash, sourceGeneration],
      )
      return new Map(result.rows.map((row) => [row.asset_urn, row.source_hash]))
    }
    return new Map([...memoryCatalogEmbeddings.values()]
      .filter((record) => record.bindingHash === bindingHash && record.sourceGeneration === sourceGeneration)
      .map((record) => [record.assetUrn, record.sourceHash]))
  }

  async function catalogEmbeddingProfileCoverage(bindingHash, projectionScope) {
    await startDatabase()
    const sourceGeneration = await catalogEmbeddingActiveGeneration(bindingHash)
    if (!sourceGeneration) return []
    if (pool) {
      const result = await pool.query(`
        SELECT
          COALESCE(NULLIF(embedding.metadata->>'platform', ''), 'unknown') AS platform,
          count(*)::int AS asset_count,
          count(*) FILTER (WHERE (embedding.metadata->'quality') ? 'rowCount')::int AS row_count_available,
          count(*) FILTER (WHERE (embedding.metadata->'quality') ? 'sizeInBytes')::int AS size_bytes_available,
          count(*) FILTER (WHERE NULLIF(embedding.metadata->>'created_at', '') IS NOT NULL)::int AS created_at_available,
          count(*) FILTER (
            WHERE COALESCE((embedding.metadata->>'schema_fields_total')::int, 0) > 0
          )::int AS schema_available,
          max(embedding.updated_at) AS observed_at
        FROM poc_catalog_embedding AS embedding
        JOIN poc_state AS current_projection ON current_projection.scope = $3
        JOIN poc_state AS active_generation ON active_generation.scope = $4
        WHERE embedding.binding_hash = $1
          AND embedding.source_generation = $2
          AND current_projection.value->>'source_generation' = $2
          AND active_generation.value->>'source_generation' = $2
        GROUP BY COALESCE(NULLIF(embedding.metadata->>'platform', ''), 'unknown')
        ORDER BY platform
      `, [
        bindingHash,
        sourceGeneration,
        projectionScope,
        catalogEmbeddingActiveScope(bindingHash),
      ])
      return result.rows.map((row) => ({
        platform: row.platform,
        asset_count: Number(row.asset_count),
        row_count_available: Number(row.row_count_available),
        size_bytes_available: Number(row.size_bytes_available),
        created_at_available: Number(row.created_at_available),
        schema_available: Number(row.schema_available),
        observed_at: row.observed_at instanceof Date ? row.observed_at.toISOString() : row.observed_at,
      }))
    }
    if (memory.get(projectionScope)?.value?.source_generation !== sourceGeneration) return []
    const grouped = new Map()
    for (const record of memoryCatalogEmbeddings.values()) {
      if (record.bindingHash !== bindingHash || record.sourceGeneration !== sourceGeneration) continue
      const metadata = record.metadata && typeof record.metadata === 'object' ? record.metadata : {}
      const platform = typeof metadata.platform === 'string' && metadata.platform ? metadata.platform : 'unknown'
      const current = grouped.get(platform) || {
        platform, asset_count: 0, row_count_available: 0, size_bytes_available: 0,
        created_at_available: 0, schema_available: 0, observed_at: new Date().toISOString(),
      }
      current.asset_count += 1
      if (Number.isInteger(metadata.quality?.rowCount)) current.row_count_available += 1
      if (Number.isInteger(metadata.quality?.sizeInBytes)) current.size_bytes_available += 1
      if (metadata.created_at) current.created_at_available += 1
      if (Number.isInteger(metadata.schema_fields_total) && metadata.schema_fields_total > 0) current.schema_available += 1
      grouped.set(platform, current)
    }
    return [...grouped.values()].sort((left, right) => left.platform.localeCompare(right.platform))
  }

  function catalogEmbeddingActiveScope(bindingHash) {
    return `catalog-embedding-active-v1:${bindingHash}`
  }

  async function catalogEmbeddingActiveGeneration(bindingHash) {
    await startDatabase()
    if (pool) {
      const result = await pool.query('SELECT value FROM poc_state WHERE scope = $1', [
        catalogEmbeddingActiveScope(bindingHash),
      ])
      const value = result.rows[0]?.value
      return value?.projection_version === 1
        && value.binding_hash === bindingHash
        && typeof value.source_generation === 'string'
        ? value.source_generation
        : undefined
    }
    const value = memory.get(catalogEmbeddingActiveScope(bindingHash))?.value
    return value?.projection_version === 1
      && value.binding_hash === bindingHash
      && typeof value.source_generation === 'string'
      ? value.source_generation
      : undefined
  }

  async function replaceCatalogEmbeddingGeneration(
    bindingHash,
    projectionScope,
    sourceGeneration,
    records,
    assetUrns,
  ) {
    for (const record of records) vectorLiteral(record.embedding)
    await startDatabase()
    const activeValue = {
      projection_version: 1,
      binding_hash: bindingHash,
      source_generation: sourceGeneration,
    }
    if (pool) {
      const client = await pool.connect()
      try {
        await client.query('BEGIN')
        const projection = await client.query(
          'SELECT value FROM poc_state WHERE scope = $1 FOR UPDATE',
          [projectionScope],
        )
        if (projection.rows[0]?.value?.source_generation !== sourceGeneration) {
          throw new Error('The Catalog projection changed while its Embedding generation was being built.')
        }
        for (const record of records) {
          await client.query(`
            INSERT INTO poc_catalog_embedding (
              binding_hash, asset_urn, source_hash, source_generation,
              content_text, metadata, embedding
            ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::vector)
            ON CONFLICT (binding_hash, asset_urn) DO UPDATE SET
              source_hash = EXCLUDED.source_hash,
              source_generation = EXCLUDED.source_generation,
              content_text = EXCLUDED.content_text,
              metadata = EXCLUDED.metadata,
              embedding = EXCLUDED.embedding,
              updated_at = now()
          `, [
            record.bindingHash,
            record.assetUrn,
            record.sourceHash,
            record.sourceGeneration,
            record.contentText,
            JSON.stringify(record.metadata),
            vectorLiteral(record.embedding),
          ])
        }
        await client.query(`
          UPDATE poc_catalog_embedding
          SET source_generation = $2, updated_at = now()
          WHERE binding_hash = $1 AND asset_urn = ANY($3::text[])
        `, [bindingHash, sourceGeneration, assetUrns])
        await client.query(
          'DELETE FROM poc_catalog_embedding WHERE binding_hash = $1 AND source_generation <> $2',
          [bindingHash, sourceGeneration],
        )
        await client.query(`
          INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
          ON CONFLICT (scope) DO UPDATE
            SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
        `, [catalogEmbeddingActiveScope(bindingHash), JSON.stringify(activeValue)])
        await client.query('COMMIT')
      } catch (error) {
        await client.query('ROLLBACK')
        throw error
      } finally {
        client.release()
      }
      return
    }
    if (memory.get(projectionScope)?.value?.source_generation !== sourceGeneration) {
      throw new Error('The Catalog projection changed while its Embedding generation was being built.')
    }
    const replacement = new Map(memoryCatalogEmbeddings)
    for (const record of records) {
      replacement.set(`${record.bindingHash}:${record.assetUrn}`, structuredClone(record))
    }
    const retained = new Set(assetUrns)
    for (const [key, record] of replacement) {
      if (record.bindingHash !== bindingHash) continue
      if (retained.has(record.assetUrn)) {
        record.sourceGeneration = sourceGeneration
      } else {
        replacement.delete(key)
      }
    }
    memoryCatalogEmbeddings.clear()
    for (const [key, record] of replacement) memoryCatalogEmbeddings.set(key, record)
    const activeScope = catalogEmbeddingActiveScope(bindingHash)
    memory.set(activeScope, {
      value: activeValue,
      version: (memory.get(activeScope)?.version ?? 0) + 1,
    })
  }

  async function pruneInactiveCatalogEmbeddingBindings(activeBindingHash) {
    const bindingHash = requireSha256(activeBindingHash, 'activeBindingHash')
    await startDatabase()
    const activeScope = catalogEmbeddingActiveScope(bindingHash)
    if (pool) {
      const client = await pool.connect()
      try {
        await client.query('BEGIN')
        const active = await client.query(
          'SELECT value FROM poc_state WHERE scope = $1 FOR UPDATE',
          [activeScope],
        )
        const value = active.rows[0]?.value
        if (value?.projection_version !== 1 || value.binding_hash !== bindingHash
          || typeof value.source_generation !== 'string') {
          throw new Error('Inactive Catalog Embedding bindings cannot be pruned before the requested binding is active.')
        }
        const rows = await client.query(
          'DELETE FROM poc_catalog_embedding WHERE binding_hash <> $1',
          [bindingHash],
        )
        const pointers = await client.query(`
          DELETE FROM poc_state
          WHERE scope LIKE 'catalog-embedding-active-v1:%'
            AND scope <> $1
        `, [activeScope])
        await client.query('COMMIT')
        return { embedding_rows: rows.rowCount || 0, active_pointers: pointers.rowCount || 0 }
      } catch (error) {
        await client.query('ROLLBACK')
        throw error
      } finally {
        client.release()
      }
    }
    const active = memory.get(activeScope)?.value
    if (active?.projection_version !== 1 || active.binding_hash !== bindingHash
      || typeof active.source_generation !== 'string') {
      throw new Error('Inactive Catalog Embedding bindings cannot be pruned before the requested binding is active.')
    }
    let embeddingRows = 0
    for (const [key, record] of memoryCatalogEmbeddings) {
      if (record.bindingHash === bindingHash) continue
      memoryCatalogEmbeddings.delete(key)
      embeddingRows += 1
    }
    let activePointers = 0
    for (const scope of memory.keys()) {
      if (!scope.startsWith('catalog-embedding-active-v1:') || scope === activeScope) continue
      memory.delete(scope)
      activePointers += 1
    }
    return { embedding_rows: embeddingRows, active_pointers: activePointers }
  }

  async function withCatalogEmbeddingGenerationLock(bindingHashValue, sourceGenerationValue, task) {
    const bindingHash = requireSha256(bindingHashValue, 'bindingHash')
    const sourceGeneration = requireSha256(sourceGenerationValue, 'sourceGeneration')
    if (typeof task !== 'function') throw new Error('The Catalog Embedding generation task is invalid.')
    await startDatabase()
    const lockName = `datariver:poc:catalog-embedding-generation:v1:${bindingHash}:${sourceGeneration}`
    if (pool) {
      const client = await pool.connect()
      let locked = false
      let heartbeat
      let heartbeatPromise = Promise.resolve()
      let ownershipError
      const ownershipAbortController = new AbortController()
      const loseOwnership = (error) => {
        if (ownershipError) return
        ownershipError = new Error('Catalog Embedding generation ownership was lost.', { cause: error })
        ownershipAbortController.abort(ownershipError)
      }
      const onClientError = (error) => loseOwnership(error)
      client.on?.('error', onClientError)
      try {
        await client.query('SELECT pg_advisory_lock(hashtextextended($1, 0))', [lockName])
        locked = true
        heartbeat = setInterval(() => {
          if (ownershipError) return
          heartbeatPromise = heartbeatPromise
            .then(() => client.query('SELECT 1'))
            .catch(loseOwnership)
        }, 15_000)
        heartbeat.unref?.()
        const result = await task(ownershipAbortController.signal)
        ownershipAbortController.signal.throwIfAborted()
        return result
      } finally {
        if (heartbeat) clearInterval(heartbeat)
        await heartbeatPromise.catch(() => undefined)
        if (locked && !ownershipError) {
          try {
            await client.query('SELECT pg_advisory_unlock(hashtextextended($1, 0))', [lockName])
          } catch (error) {
            loseOwnership(error)
          }
        }
        client.removeListener?.('error', onClientError)
        client.release(ownershipError)
      }
    }
    let releaseLock
    const currentLock = new Promise((resolvePromise) => { releaseLock = resolvePromise })
    const priorLock = memoryCatalogEmbeddingGenerationLocks.get(lockName) || Promise.resolve()
    const tail = priorLock.then(() => currentLock)
    memoryCatalogEmbeddingGenerationLocks.set(lockName, tail)
    await priorLock
    try {
      return await task(new AbortController().signal)
    } finally {
      releaseLock()
      if (memoryCatalogEmbeddingGenerationLocks.get(lockName) === tail) {
        memoryCatalogEmbeddingGenerationLocks.delete(lockName)
      }
    }
  }

  async function searchCatalogEmbeddings(bindingHash, projectionScope, sourceGeneration, embedding, limit, allowedUrnsScope) {
    if (allowedUrnsScope !== 'ADMIN_UNRESTRICTED' && (!allowedUrnsScope || allowedUrnsScope.size === 0)) return []
    await startDatabase()
    const boundedLimit = Math.max(1, Math.min(Number(limit) || 1, 20))
    if (pool) {
      const vector = vectorLiteral(embedding)
      const isRestricted = allowedUrnsScope !== 'ADMIN_UNRESTRICTED'
      const urnList = isRestricted ? [...allowedUrnsScope] : []
      const result = await pool.query(`
        SELECT catalog_embedding.asset_urn, catalog_embedding.content_text, catalog_embedding.metadata,
          1 - (catalog_embedding.embedding <=> $5::vector) AS similarity
        FROM poc_catalog_embedding AS catalog_embedding
        JOIN poc_state AS current_projection ON current_projection.scope = $3
        JOIN poc_state AS active_generation ON active_generation.scope = $4
        WHERE catalog_embedding.binding_hash = $1
          AND catalog_embedding.source_generation = $2
          AND current_projection.value->>'source_generation' = $2
          AND active_generation.value->>'source_generation' = $2
          AND vector_dims(catalog_embedding.embedding) = vector_dims($5::vector)
          ${isRestricted ? 'AND catalog_embedding.asset_urn = ANY($7::text[])' : ''}
        ORDER BY catalog_embedding.embedding <=> $5::vector, catalog_embedding.asset_urn
        LIMIT $6
      `, isRestricted ? [
        bindingHash, sourceGeneration, projectionScope, catalogEmbeddingActiveScope(bindingHash), vector, boundedLimit, urnList
      ] : [
        bindingHash, sourceGeneration, projectionScope, catalogEmbeddingActiveScope(bindingHash), vector, boundedLimit
      ])
      return result.rows.map((row) => ({
        assetUrn: row.asset_urn,
        contentText: row.content_text,
        metadata: row.metadata,
        similarity: Number(row.similarity),
      }))
    }
    if (memory.get(projectionScope)?.value?.source_generation !== sourceGeneration
      || await catalogEmbeddingActiveGeneration(bindingHash) !== sourceGeneration) return []
    return [...memoryCatalogEmbeddings.values()]
      .filter((record) => record.bindingHash === bindingHash
        && record.sourceGeneration === sourceGeneration
        && record.embedding.length === embedding.length
        && (allowedUrnsScope === 'ADMIN_UNRESTRICTED' || allowedUrnsScope.has(record.assetUrn)))
      .map((record) => ({
        assetUrn: record.assetUrn,
        contentText: record.contentText,
        metadata: structuredClone(record.metadata),
        similarity: cosineSimilarity(record.embedding, embedding),
      }))
      .sort((left, right) => right.similarity - left.similarity || left.assetUrn.localeCompare(right.assetUrn))
      .slice(0, boundedLimit)
  }
  async function readChangeHistoryCheckpoint(query) {
    if (!query || typeof query !== 'object') {
      throw new Error('The POC change-history checkpoint query is invalid.')
    }
    const sourceIdentityHash = requireSha256(query.sourceIdentityHash, 'sourceIdentityHash')
    const topicContract = requireBoundedString(query.topicContract, 'topicContract', 255)
    const partition = requireNonnegativeInteger(query.partition, 'partition')
    await startDatabase()
    if (!pool) throw new Error('PostgreSQL is required for durable POC change history.')
    const result = await pool.query(`
      SELECT next_offset
      FROM poc_change_history_checkpoints
      WHERE source_identity_hash = $1 AND topic_contract = $2 AND source_partition = $3
    `, [sourceIdentityHash, topicContract, partition])
    if (!result.rows[0]) return null
    const nextOffset = Number(result.rows[0].next_offset)
    if (!Number.isSafeInteger(nextOffset) || nextOffset < 0) {
      throw new Error('The stored POC change-history checkpoint is invalid.')
    }
    return nextOffset
  }

  async function readChangeHistoryProjection({ catalogScope } = {}) {
    const normalizedCatalogScope = requireBoundedString(catalogScope, 'catalogScope', 255)
    await startDatabase()
    if (!pool) {
      throw Object.assign(new Error('PostgreSQL is required for durable POC change history.'), {
        code: 'CHANGE_HISTORY_STORE_REQUIRED',
        statusCode: 503,
      })
    }
    const client = await pool.connect()
    try {
      await client.query('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
      const stateResult = await client.query(`
        SELECT scope, value, version FROM poc_state
        WHERE scope IN ($1, $2, $3, $4, $5)
      `, [
        ...CHANGE_HISTORY_ACCESS_SCOPES,
        normalizedCatalogScope,
        CHANGE_HISTORY_CAPTURE_STATUS_SCOPE,
        CHANGE_HISTORY_RUNTIME_STATUS_SCOPE,
      ])
      const eventResult = await client.query(`
        SELECT event_identity, event_hash, normalized_change_transaction_id,
          source_identity_hash, topic_contract, source_partition, source_offset,
          asset_urn, normalized_entity_key, category, source_aspect, operation,
          before_data, after_data, actor_ref, source_occurred_at, detected_at, captured_at
        FROM poc_change_history_ledger_events
        ORDER BY COALESCE(source_occurred_at, detected_at) DESC, event_identity DESC
      `)
      const linkResult = await client.query(`
        SELECT link_event_identity, event_hash, ledger_event_identity, link_version,
          link_kind, action, change_request_id, change_request_round, prior_link_hash,
          reason, policy_hash, basis_hash, actor_ref, occurred_at, captured_at
        FROM poc_change_history_cr_link_events
        ORDER BY ledger_event_identity, link_version
      `)
      const sourceResult = await client.query(`
        SELECT source_identity_hash, provider_name, provider_version,
          schema_contract_hash, created_at
        FROM poc_change_history_sources
        ORDER BY source_identity_hash
      `)
      const checkpointResult = await client.query(`
        SELECT source_identity_hash, topic_contract, source_partition,
          first_exact_offset, next_offset, last_contiguous_event_identity,
          last_source_occurred_at, last_captured_at, version
        FROM poc_change_history_checkpoints
        ORDER BY source_identity_hash, topic_contract, source_partition
      `)
      await client.query('COMMIT')
      const catalog = stateResult.rows.find((row) => row.scope === normalizedCatalogScope)
      const captureStatus = stateResult.rows.find((row) => row.scope === CHANGE_HISTORY_CAPTURE_STATUS_SCOPE)
      const runtimeStatus = stateResult.rows.find((row) => row.scope === CHANGE_HISTORY_RUNTIME_STATUS_SCOPE)
      return {
        ...changeHistoryAccessSnapshot(stateResult.rows),
        catalog: catalog ? { value: catalog.value, version: Number(catalog.version) } : { value: null, version: 0 },
        captureStatus: captureStatus
          ? { value: captureStatus.value, version: Number(captureStatus.version) }
          : { value: null, version: 0 },
        runtimeStatus: runtimeStatus
          ? { value: runtimeStatus.value, version: Number(runtimeStatus.version) }
          : { value: null, version: 0 },
        events: eventResult.rows,
        links: linkResult.rows,
        sources: sourceResult.rows,
        checkpoints: checkpointResult.rows,
      }
    } catch (error) {
      await client.query('ROLLBACK')
      throw error
    } finally {
      client.release()
    }
  }

  async function writeChangeHistoryCaptureStatus(command) {
    if (!command || typeof command !== 'object' || !CHANGE_HISTORY_CAPTURE_STATES.has(command.state)) {
      throw new Error('The POC change-history capture status is invalid.')
    }
    const batchProcessedRecords = requireNonnegativeInteger(
      command.batchProcessedRecords,
      'batchProcessedRecords',
    )
    const sourceIdentityHash = command.state === 'HISTORY_GAP_BLOCKED'
      ? (command.sourceIdentityHash == null ? null : requireSha256(command.sourceIdentityHash, 'sourceIdentityHash'))
      : requireSha256(command.sourceIdentityHash, 'sourceIdentityHash')
    return write(CHANGE_HISTORY_CAPTURE_STATUS_SCOPE, {
      contract: 'DATARIVER_CHANGE_HISTORY_CAPTURE_STATUS_V1',
      state: command.state,
      batch_processed_records: batchProcessedRecords,
      caught_up: command.state === 'CAPTURE_CAUGHT_UP',
      source_identity_hash: sourceIdentityHash,
      observed_at: explicitSchedulerTimestamp(command.observedAt, 'observedAt'),
    })
  }

  async function writeChangeHistoryRuntimeStatus(command) {
    if (!command || typeof command !== 'object'
      || !['READY', 'DISCOVERY_FAILED', 'CAPTURE_FAILED'].includes(command.state)) {
      throw new Error('The POC change-history runtime status is invalid.')
    }
    const classification = command.state === 'READY'
      ? null
      : requireBoundedString(command.classification, 'classification', 160)
    if (classification && !isMclRuntimeClassification(classification)) {
      throw new Error('The POC change-history runtime classification is invalid.')
    }
    const failureStage = command.state === 'READY'
      ? null
      : requireBoundedString(command.failureStage, 'failureStage', 80)
    const failureDetailCode = command.state === 'READY'
      ? null
      : requireBoundedString(command.failureDetailCode, 'failureDetailCode', 80)
    if (failureStage && !/^[A-Z][A-Z0-9_]{0,79}$/.test(failureStage)) {
      throw new Error('The POC change-history runtime failure stage is invalid.')
    }
    if (failureDetailCode && !/^[A-Z][A-Z0-9_]{0,79}$/.test(failureDetailCode)) {
      throw new Error('The POC change-history runtime failure detail code is invalid.')
    }
    const recordShape = command.state === 'READY' || command.recordShape === undefined
      ? null
      : sanitizeMclRecordShape(command.recordShape)
    if (command.recordShape !== undefined && !recordShape) {
      throw new Error('The POC change-history rejected-record shape is invalid.')
    }
    if (recordShape && failureStage !== 'RECORD_NORMALIZATION') {
      throw new Error('The POC change-history rejected-record shape is outside its failure stage.')
    }
    if (recordShape && recordShape.rejection_locus !== failureDetailCode) {
      throw new Error('The POC change-history rejected-record shape conflicts with its failure detail.')
    }
    return write(CHANGE_HISTORY_RUNTIME_STATUS_SCOPE, {
      contract: 'DATARIVER_CHANGE_HISTORY_RUNTIME_STATUS_V1',
      state: command.state,
      classification,
      failure_stage: failureStage,
      failure_detail_code: failureDetailCode,
      ...(recordShape ? { record_shape: recordShape } : {}),
      observed_at: explicitSchedulerTimestamp(command.observedAt, 'observedAt'),
    })
  }

  async function initializeChangeHistoryCaptureBoundaries(command) {
    const normalized = normalizeChangeHistoryBoundaries(command)
    await startDatabase()
    if (!pool) throw new Error('PostgreSQL is required for durable POC change history.')
    const client = await pool.connect()
    try {
      await client.query('BEGIN')
      await client.query(`
        INSERT INTO poc_change_history_sources (
          source_identity_hash, provider_name, provider_version, schema_contract_hash
        ) VALUES ($1, $2, $3, $4)
        ON CONFLICT DO NOTHING
      `, [
        normalized.sourceIdentityHash,
        normalized.providerName,
        normalized.providerVersion,
        normalized.schemaContractHash,
      ])
      const sourceResult = await client.query(`
        SELECT provider_name, provider_version, schema_contract_hash
        FROM poc_change_history_sources
        WHERE source_identity_hash = $1
        FOR UPDATE
      `, [normalized.sourceIdentityHash])
      const source = sourceResult.rows[0]
      if (!source
        || source.provider_name !== normalized.providerName
        || source.provider_version !== normalized.providerVersion
        || source.schema_contract_hash !== normalized.schemaContractHash) {
        throw new Error('The POC change-history source identity conflicts with stored evidence.')
      }
      const storedResult = await client.query(`
        SELECT source_partition, next_offset
        FROM poc_change_history_checkpoints
        WHERE source_identity_hash = $1 AND topic_contract = $2
        ORDER BY source_partition
        FOR UPDATE
      `, [normalized.sourceIdentityHash, normalized.topicContract])
      let checkpoints
      if (storedResult.rows.length === 0) {
        for (const { partition, boundary } of normalized.partitions) {
          await client.query(`
            INSERT INTO poc_change_history_checkpoints (
              source_identity_hash, topic_contract, source_partition,
              first_exact_offset, next_offset
            ) VALUES ($1, $2, $3, $4, $4)
          `, [
            normalized.sourceIdentityHash,
            normalized.topicContract,
            partition,
            boundary,
          ])
        }
        checkpoints = normalized.partitions.map(({ partition, boundary }) => ({
          partition,
          nextOffset: boundary,
        }))
      } else {
        const requestedPartitions = normalized.partitions.map(({ partition }) => partition)
        const storedPartitions = storedResult.rows.map((row) => Number(row.source_partition))
        if (storedPartitions.length !== requestedPartitions.length
          || storedPartitions.some((partition, index) => partition !== requestedPartitions[index])) {
          throw new Error('The MCL partition topology changed after its durable capture boundary was fixed.')
        }
        checkpoints = storedResult.rows.map((row) => {
          const nextOffset = Number(row.next_offset)
          if (!Number.isSafeInteger(nextOffset) || nextOffset < 0) {
            throw new Error('The stored POC change-history checkpoint is invalid.')
          }
          return { partition: Number(row.source_partition), nextOffset }
        })
      }
      await client.query('COMMIT')
      return checkpoints
    } catch (error) {
      await client.query('ROLLBACK')
      throw error
    } finally {
      client.release()
    }
  }

  async function appendChangeHistoryCapture(capture) {
    const normalized = normalizeChangeHistoryCapture(capture)
    await startDatabase()
    if (!pool) throw new Error('PostgreSQL is required for durable POC change history.')
    const client = await pool.connect()
    try {
      await client.query('BEGIN')
      const insertedSource = await client.query(`
        INSERT INTO poc_change_history_sources (
          source_identity_hash, provider_name, provider_version, schema_contract_hash
        ) VALUES ($1, $2, $3, $4)
        ON CONFLICT DO NOTHING
        RETURNING source_identity_hash
      `, [
        normalized.sourceIdentityHash,
        normalized.providerName,
        normalized.providerVersion,
        normalized.schemaContractHash,
      ])
      if (!insertedSource.rows[0]) {
        const source = await client.query(`
          SELECT provider_name, provider_version, schema_contract_hash
          FROM poc_change_history_sources
          WHERE source_identity_hash = $1
        `, [normalized.sourceIdentityHash])
        const existing = source.rows[0]
        if (!existing
          || existing.provider_name !== normalized.providerName
          || existing.provider_version !== normalized.providerVersion
          || existing.schema_contract_hash !== normalized.schemaContractHash) {
          throw new Error('The POC change-history source identity conflicts with stored evidence.')
        }
      }
      await client.query(`
        INSERT INTO poc_change_history_checkpoints (
          source_identity_hash, topic_contract, source_partition,
          first_exact_offset, next_offset
        ) VALUES ($1, $2, $3, $4, $4)
        ON CONFLICT DO NOTHING
      `, [
        normalized.sourceIdentityHash,
        normalized.topicContract,
        normalized.partition,
        normalized.offset,
      ])
      const checkpointResult = await client.query(`
        SELECT next_offset
        FROM poc_change_history_checkpoints
        WHERE source_identity_hash = $1 AND topic_contract = $2 AND source_partition = $3
        FOR UPDATE
      `, [normalized.sourceIdentityHash, normalized.topicContract, normalized.partition])
      const checkpointOffset = Number(checkpointResult.rows[0]?.next_offset)
      const replayed = checkpointOffset === normalized.offset + 1
      if (checkpointOffset !== normalized.offset && !replayed) {
        throw new Error('The POC change-history capture is stale or has an offset gap.')
      }

      for (const event of normalized.events) {
        const inserted = await client.query(`
          INSERT INTO poc_change_history_ledger_events (
            event_identity, event_hash, source_identity_hash, source_event_identity,
            normalized_change_transaction_id, deterministic_ordinal, topic_contract,
            source_partition, source_offset, asset_urn, normalized_entity_key,
            category, source_aspect, operation, before_data, after_data,
            before_hash, after_hash, actor_ref, source_occurred_at, detected_at
          ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
            $12, $13, $14, $15::jsonb, $16::jsonb, $17, $18, $19, $20, $21
          )
          ON CONFLICT DO NOTHING
          RETURNING event_identity
        `, [
          event.eventIdentity,
          event.eventHash,
          normalized.sourceIdentityHash,
          normalized.sourceEventIdentity,
          normalized.transactionIdentity,
          event.ordinal,
          normalized.topicContract,
          normalized.partition,
          normalized.offset,
          event.assetUrn,
          event.entityKey,
          event.category,
          event.sourceAspect,
          event.operation,
          event.beforeData === null ? null : JSON.stringify(event.beforeData),
          event.afterData === null ? null : JSON.stringify(event.afterData),
          event.beforeHash,
          event.afterHash,
          event.actorRef,
          event.sourceOccurredAt,
          event.detectedAt,
        ])
        if (!inserted.rows[0]) {
          const existingResult = await client.query(`
            SELECT event_hash
            FROM poc_change_history_ledger_events
            WHERE source_identity_hash = $1
              AND source_event_identity = $2
              AND deterministic_ordinal = $3
          `, [normalized.sourceIdentityHash, normalized.sourceEventIdentity, event.ordinal])
          if (existingResult.rows[0]?.event_hash !== event.eventHash) {
            throw new Error('The POC change-history replay conflicts with stored ledger evidence.')
          }
        }
      }

      if (!replayed) {
        const lastEvent = normalized.events.at(-1)
        const advanced = await client.query(`
          UPDATE poc_change_history_checkpoints
          SET next_offset = $4,
              last_contiguous_event_identity = COALESCE($5, last_contiguous_event_identity),
              last_source_occurred_at = COALESCE($6, last_source_occurred_at),
              last_captured_at = clock_timestamp(),
              version = version + 1
          WHERE source_identity_hash = $1 AND topic_contract = $2
            AND source_partition = $3 AND next_offset = $7
          RETURNING next_offset
        `, [
          normalized.sourceIdentityHash,
          normalized.topicContract,
          normalized.partition,
          normalized.offset + 1,
          lastEvent?.eventIdentity ?? null,
          lastEvent?.sourceOccurredAt ?? null,
          normalized.offset,
        ])
        if (!advanced.rows[0]) throw new Error('The POC change-history checkpoint advance lost its fence.')
      }
      await client.query('COMMIT')
      return {
        sourceEventIdentity: normalized.sourceEventIdentity,
        eventIdentities: normalized.events.map((event) => event.eventIdentity),
        nextOffset: normalized.offset + 1,
        replayed,
      }
    } catch (error) {
      await client.query('ROLLBACK')
      throw error
    } finally {
      client.release()
    }
  }

  async function appendChangeHistoryCrLink(command) {
    const normalized = normalizeChangeHistoryCrLink(command)
    await startDatabase()
    if (!pool) throw new Error('PostgreSQL is required for durable POC change history.')
    const client = await pool.connect()
    try {
      await client.query('BEGIN')
      if (command.expectedAccessVersion !== undefined || command.expectedCoreVersion !== undefined) {
        await client.query(
          'SELECT pg_advisory_xact_lock(hashtextextended($1, 0))',
          [CHANGE_HISTORY_ACCESS_SCOPE],
        )
        const normalizedCatalogScope = requireBoundedString(command.expectedCatalogScope, 'expectedCatalogScope', 255)
        const locked = await client.query(`
          SELECT scope, value, version FROM poc_state
          WHERE scope IN ($1, $2, $3)
          ORDER BY scope
          FOR UPDATE
        `, [...CHANGE_HISTORY_ACCESS_SCOPES, normalizedCatalogScope])
        const snapshot = changeHistoryAccessSnapshot(locked.rows)
        assertAccessVersions(
          snapshot,
          requireNonnegativeInteger(command.expectedAccessVersion, 'expectedAccessVersion'),
          requireNonnegativeInteger(command.expectedCoreVersion, 'expectedCoreVersion'),
        )
        if (sha256(stableJson(snapshot.core.value)) !== requireSha256(command.expectedCoreHash, 'expectedCoreHash')) {
          throw Object.assign(new Error('The change-request aggregate changed; read it and retry.'), {
            code: 'CR_BINDING_DRIFT',
            statusCode: 409,
          })
        }
        const catalog = locked.rows.find((row) => row.scope === normalizedCatalogScope)
        if (Number(catalog?.version ?? 0) !== requireNonnegativeInteger(command.expectedCatalogVersion, 'expectedCatalogVersion')
          || sha256(stableJson(catalog?.value ?? null)) !== requireSha256(command.expectedCatalogHash, 'expectedCatalogHash')) {
          throw Object.assign(new Error('The current catalog projection changed; read it and retry.'), {
            code: 'SYSTEM_MAPPING_UNRESOLVED',
            statusCode: 409,
          })
        }
      }
      const ledgerResult = await client.query(`
        SELECT event_identity FROM poc_change_history_ledger_events
        WHERE event_identity = $1
        FOR UPDATE
      `, [normalized.ledgerEventIdentity])
      if (!ledgerResult.rows[0]) {
        throw Object.assign(new Error('The change-history event was not found.'), {
          code: 'CHANGE_HISTORY_EVENT_NOT_FOUND',
          statusCode: 404,
        })
      }
      await client.query(
        'SELECT pg_advisory_xact_lock(hashtextextended($1, 0))',
        [`change-history-cr-link:${normalized.requestKeyHash}`],
      )
      const replayResult = await client.query(`
        SELECT link_event_identity, event_hash, request_hash, link_version
        FROM poc_change_history_cr_link_events
        WHERE request_key_hash = $1
        FOR UPDATE
      `, [normalized.requestKeyHash])
      const replay = replayResult.rows[0]
      if (replay) {
        if (replay.request_hash !== normalized.requestHash) {
          throw Object.assign(new Error('The POC CR link idempotency key conflicts with another request.'), {
            code: 'IDEMPOTENCY_CONFLICT',
            statusCode: 409,
          })
        }
        await client.query('COMMIT')
        return {
          linkEventIdentity: replay.link_event_identity,
          eventHash: replay.event_hash,
          linkVersion: Number(replay.link_version),
          replayed: true,
        }
      }
      const previousResult = await client.query(`
        SELECT event_hash, link_version
        FROM poc_change_history_cr_link_events
        WHERE ledger_event_identity = $1
        ORDER BY link_version DESC
        LIMIT 1
        FOR UPDATE
      `, [normalized.ledgerEventIdentity])
      const previous = previousResult.rows[0]
      const previousHash = previous?.event_hash ?? null
      if (previousHash !== normalized.priorLinkHash) {
        throw Object.assign(new Error('The POC CR link command has a stale prior-link hash.'), {
          code: 'LINK_VERSION_STALE',
          statusCode: 409,
        })
      }
      const linkVersion = Number(previous?.link_version ?? 0) + 1
      await client.query(`
        INSERT INTO poc_change_history_cr_link_events (
          link_event_identity, event_hash, request_key_hash, request_hash,
          ledger_event_identity, link_version, link_kind, action,
          change_request_id, change_request_round, prior_link_hash,
          reason, policy_hash, basis_hash, actor_ref, occurred_at
        ) VALUES (
          $1, $2, $3, $4, $5, $6, $7, $8,
          $9, $10, $11, $12, $13, $14, $15, $16
        )
      `, [
        normalized.linkEventIdentity,
        normalized.eventHash,
        normalized.requestKeyHash,
        normalized.requestHash,
        normalized.ledgerEventIdentity,
        linkVersion,
        normalized.linkKind,
        normalized.action,
        normalized.changeRequestId,
        normalized.changeRequestRound,
        normalized.priorLinkHash,
        normalized.reason,
        normalized.policyHash,
        normalized.basisHash,
        normalized.actorRef,
        normalized.occurredAt,
      ])
      await client.query('COMMIT')
      return {
        linkEventIdentity: normalized.linkEventIdentity,
        eventHash: normalized.eventHash,
        linkVersion,
        replayed: false,
      }
    } catch (error) {
      await client.query('ROLLBACK')
      throw error
    } finally {
      client.release()
    }
  }

  async function readChangeHistoryCrLinkReplay(command) {
    const requestKeyHash = sha256(requireBoundedString(command.idempotencyKey, 'idempotencyKey', 200))
    const requestHash = changeHistoryCrLinkRequestHash({
      ledgerEventIdentity: requireSha256(command.ledgerEventIdentity, 'ledgerEventIdentity'),
      linkKind: requireOneOf(command.linkKind, 'linkKind', ['PRIMARY', 'CANDIDATE']),
      action: requireOneOf(command.action, 'action', ['SET_PRIMARY', 'CLEAR_PRIMARY', 'ADD_CANDIDATE', 'REMOVE_CANDIDATE']),
      changeRequestId: requireBoundedString(command.changeRequestId, 'changeRequestId', 200),
      changeRequestRound: requirePositiveInteger(command.changeRequestRound, 'changeRequestRound'),
      reason: requireBoundedString(command.reason, 'reason', 2000),
    })
    await startDatabase()
    if (!pool) throw Object.assign(new Error('PostgreSQL is required for durable POC change history.'), {
      code: 'CHANGE_HISTORY_STORE_REQUIRED', statusCode: 503,
    })
    const result = await pool.query(`
      SELECT link_event_identity, event_hash, request_hash, link_version
      FROM poc_change_history_cr_link_events
      WHERE request_key_hash = $1
    `, [requestKeyHash])
    const replay = result.rows[0]
    if (!replay) return null
    if (replay.request_hash !== requestHash) {
      throw Object.assign(new Error('The POC CR link idempotency key conflicts with another request.'), {
        code: 'IDEMPOTENCY_CONFLICT', statusCode: 409,
      })
    }
    return {
      linkEventIdentity: replay.link_event_identity,
      eventHash: replay.event_hash,
      linkVersion: Number(replay.link_version),
      replayed: true,
    }
  }

  async function runChangeHistoryScheduler(command, task) {
    if (!command || typeof command !== 'object' || typeof task !== 'function') {
      throw new Error('The POC change-history scheduler command is invalid.')
    }
    const lockName = requireBoundedString(command.lockName, 'lockName', 255)
    const scheduledFor = explicitSchedulerTimestamp(command.scheduledFor)
    const trigger = requireOneOf(command.trigger, 'trigger', ['scheduled', 'manual', 'startup'])
    await startDatabase()
    if (!pool) throw new Error('PostgreSQL is required for the POC change-history scheduler.')
    const client = await pool.connect()
    let locked = false
    try {
      const lock = await client.query(
        'SELECT pg_try_advisory_lock(hashtextextended($1, 0)) AS acquired',
        [lockName],
      )
      locked = lock.rows[0]?.acquired === true
      if (!locked) return { status: 'locked', scheduledFor }
      const scope = `change-history-scheduler-v1:${lockName}`
      const current = await client.query('SELECT value FROM poc_state WHERE scope = $1', [scope])
      const lastSuccessfulSchedule = current.rows.length === 0
        ? null
        : explicitSchedulerTimestamp(
          current.rows[0]?.value?.last_successful_schedule,
          'stored last_successful_schedule',
        )
      const replayingSuccessfulBoundary = lastSuccessfulSchedule === scheduledFor
      if (replayingSuccessfulBoundary && trigger !== 'startup') {
        return { status: 'already_completed', scheduledFor }
      }
      if (lastSuccessfulSchedule !== null
        && Date.parse(lastSuccessfulSchedule) > Date.parse(scheduledFor)) {
        return { status: 'stale', scheduledFor }
      }
      const result = await task()
      if (result?.schedulerComplete === false) {
        return { status: 'incomplete', scheduledFor, result }
      }
      const completedAt = new Date().toISOString()
      if (replayingSuccessfulBoundary) {
        return { status: 'succeeded', scheduledFor, completedAt, result, replayedSchedule: true }
      }
      const receipt = {
        version: 1,
        last_successful_schedule: scheduledFor,
        completed_at: completedAt,
        trigger,
      }
      const receiptWrite = await client.query(`
        INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
        ON CONFLICT (scope) DO UPDATE
          SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
          WHERE poc_state.value ->> 'last_successful_schedule' = $3
            AND (poc_state.value ->> 'last_successful_schedule')::timestamptz < $4::timestamptz
        RETURNING poc_state.value ->> 'last_successful_schedule' AS last_successful_schedule
      `, [scope, JSON.stringify(receipt), lastSuccessfulSchedule, scheduledFor])
      if (receiptWrite.rows.length !== 1
        || receiptWrite.rows[0]?.last_successful_schedule !== scheduledFor) {
        throw new Error('The POC change-history scheduler receipt was not advanced.')
      }
      return { status: 'succeeded', scheduledFor, completedAt, result }
    } finally {
      if (locked) {
        await client.query('SELECT pg_advisory_unlock(hashtextextended($1, 0))', [lockName])
      }
      client.release()
    }
  }

  async function close() {
    await Promise.allSettled([
      redis?.isOpen ? redis.quit() : undefined,
      pool && !databasePool ? pool.end() : undefined,
    ])
    redis = undefined
    if (!databasePool) pool = undefined
  }

  async function requireKnowledgeDatabase() {
    await startDatabase()
    if (!pool) throw Object.assign(new Error('PostgreSQL is required for durable Knowledge ingestion.'), {
      code: 'KNOWLEDGE_INGESTION_STORE_REQUIRED', statusCode: 503,
    })
    return pool
  }

  async function readKnowledgeSourceRows(manifestRef, assetUrn, sourceVersion) {
    const db = await requireKnowledgeDatabase()
    const result = await db.query(`
      SELECT row_key, row_data, source_hash
      FROM poc_knowledge_source_rows
      WHERE manifest_ref = $1 AND asset_urn = $2 AND source_version = $3
      ORDER BY row_key
      LIMIT 1000
    `, [manifestRef, assetUrn, sourceVersion])
    return result.rows.map((row) => ({
      row_key: row.row_key, row_data: row.row_data, source_hash: row.source_hash,
    }))
  }

  async function readKnowledgeIngestionJobByIdempotency(draftId, releaseId, idempotencyKey) {
    const db = await requireKnowledgeDatabase()
    const result = await db.query(`
      SELECT * FROM poc_knowledge_ingestion_jobs
      WHERE draft_id = $1 AND release_id = $2 AND idempotency_key = $3
    `, [draftId, releaseId, idempotencyKey])
    return result.rows[0] ?? null
  }

  async function readKnowledgeIngestionJob(jobId) {
    const db = await requireKnowledgeDatabase()
    const result = await db.query(`
      SELECT * FROM poc_knowledge_ingestion_jobs WHERE job_id = $1
    `, [jobId])
    return result.rows[0] ?? null
  }

  async function listKnowledgeIngestionJobs(draftId) {
    const db = await requireKnowledgeDatabase()
    const result = await db.query(`
      SELECT * FROM poc_knowledge_ingestion_jobs
      WHERE draft_id = $1 AND state <> 'READY'
      ORDER BY created_at DESC LIMIT 100
    `, [draftId])
    return result.rows
  }

  async function insertKnowledgeIngestionJob(job) {
    const db = await requireKnowledgeDatabase()
    const result = await db.query(`
      INSERT INTO poc_knowledge_ingestion_jobs (
        job_id, draft_id, graph_id, release_id, requested_by, source_asset_urn,
        source_version, tbox_version, idempotency_key, request_hash, state, preview, result
      ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13::jsonb)
      RETURNING *
    `, [
      job.job_id, job.draft_id, job.graph_id, job.release_id, job.requested_by,
      job.source_asset_urn, job.source_version, job.tbox_version, job.idempotency_key,
      job.request_hash, job.state, JSON.stringify(job.preview), JSON.stringify(job.result),
    ])
    return result.rows[0]
  }

  async function updateKnowledgeIngestionJob(jobId, expectedVersion, state, resultValue) {
    const db = await requireKnowledgeDatabase()
    const result = await db.query(`
      UPDATE poc_knowledge_ingestion_jobs
      SET state = $3, result = $4::jsonb, version = version + 1, updated_at = clock_timestamp()
      WHERE job_id = $1 AND version = $2
      RETURNING *
    `, [jobId, expectedVersion, state, JSON.stringify(resultValue)])
    if (!result.rows[0]) throw Object.assign(new Error('Knowledge ingestion job version changed.'), {
      code: 'KNOWLEDGE_INGESTION_STALE', statusCode: 409,
    })
    return result.rows[0]
  }

  async function getK9Policy(graphId) {
    await startDatabase()
    if (!pool) throw new Error('K9 policies require PostgreSQL')
    const { rows } = await pool.query('SELECT * FROM poc_k9_managed_graph_policies WHERE graph_id = $1', [graphId])
    return rows[0]
  }

  async function listK9ManagedGraphAssets() {
    await startDatabase()
    if (!pool) throw new Error('K9 managed graph Assets require PostgreSQL')
    const { rows } = await pool.query(`
      SELECT
        policy.*,
        latest.run_id AS latest_run_id,
        latest.status AS latest_result,
        latest.started_at AS latest_started_at,
        latest.completed_at AS latest_completed_at,
        latest.error_message AS latest_error_message,
        latest.manifest AS latest_manifest,
        active.run_id AS active_run_id,
        active.started_at AS active_started_at,
        active.completed_at AS active_completed_at,
        active.input_snapshot_hash AS active_input_snapshot_hash,
        active.manifest AS active_manifest,
        active.canonical_release AS active_canonical_release
      FROM poc_k9_managed_graph_policies AS policy
      LEFT JOIN LATERAL (
        SELECT run_id, status, started_at, completed_at, error_message, manifest
        FROM poc_k9_refresh_runs
        WHERE graph_id = policy.graph_id
        ORDER BY started_at DESC, run_id DESC
        LIMIT 1
      ) AS latest ON TRUE
      LEFT JOIN LATERAL (
        SELECT run_id, started_at, completed_at, input_snapshot_hash, manifest, canonical_release
        FROM poc_k9_refresh_runs
        WHERE graph_id = policy.graph_id
          AND active_release_pointer = policy.active_release_pointer
          AND status IN ('RUN', 'NO_OP')
          AND canonical_release IS NOT NULL
        ORDER BY started_at DESC, run_id DESC
        LIMIT 1
      ) AS active ON policy.active_release_pointer IS NOT NULL
      ORDER BY policy.managed_intent, policy.graph_id
    `)
    return rows
  }

  async function getK9ManagedGraphAsset(graphId) {
    const rows = await listK9ManagedGraphAssets()
    return rows.find((row) => row.graph_id === graphId) || null
  }

  async function readK9SchedulerReceipt(lockName) {
    const name = requireBoundedString(lockName, 'lockName', 255)
    return read('k9-scheduler-v1:' + name)
  }

  async function ensureK9Policies(policies) {
    await startDatabase()
    if (!pool) throw new Error('K9 policies require PostgreSQL')

    const client = await pool.connect()
    try {
      await client.query('BEGIN')
      for (const p of policies) {
        const { rows } = await client.query('SELECT * FROM poc_k9_managed_graph_policies WHERE graph_id = $1', [p.graph_id])
        if (rows.length === 0) {
          await client.query(`
            INSERT INTO poc_k9_managed_graph_policies
            (graph_id, name, status, classification, ontology_version_id, studio_release_id, publication_version, schedule, managed_intent, accepted_proposal_id, subject_id, workspace_id, policy_hash, tbox_hash, contract_hash, proposal_hash, source_hash, mapping_hash, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, clock_timestamp(), clock_timestamp())
          `, [
            p.graph_id, p.name, p.status || 'ACTIVE', p.classification, p.ontology_version_id, p.studio_release_id, p.publication_version, p.schedule, p.managed_intent, p.accepted_proposal_id, p.subject_id, p.workspace_id, p.policy_hash, p.tbox_hash, p.contract_hash, p.proposal_hash, p.source_hash, p.mapping_hash
          ])
        } else {
          const row = rows[0]
          if (row.name !== p.name || row.status !== p.status || row.classification !== p.classification ||
              row.policy_hash !== p.policy_hash || row.tbox_hash !== p.tbox_hash || row.contract_hash !== p.contract_hash ||
              row.proposal_hash !== p.proposal_hash || row.source_hash !== p.source_hash ||
              row.mapping_hash !== p.mapping_hash || row.ontology_version_id !== p.ontology_version_id ||
              row.studio_release_id !== p.studio_release_id || row.publication_version !== p.publication_version ||
              row.schedule !== p.schedule || row.managed_intent !== p.managed_intent ||
              row.accepted_proposal_id !== p.accepted_proposal_id ||
              row.subject_id !== p.subject_id || row.workspace_id !== p.workspace_id) {
            throw new Error('K9 policy drift detected against canonical PG state')
          }
        }
      }
      await client.query('COMMIT')
    } catch (e) {
      await client.query('ROLLBACK')
      throw e
    } finally {
      client.release()
    }
  }

  async function getK9PreparingRuns() {
    await startDatabase()
    if (!pool) throw new Error('K9 runs require PostgreSQL')
    const { rows } = await pool.query(`SELECT * FROM poc_k9_refresh_runs WHERE status = 'PREPARING'`)
    return rows
  }

  async function getK9OrphanRuns(graphId, activePointer) {
    await startDatabase()
    if (!pool) throw new Error('K9 runs require PostgreSQL')
    const { rows } = await pool.query(
      `SELECT run_id, active_release_pointer FROM poc_k9_refresh_runs WHERE graph_id = $1 AND active_release_pointer IS NOT NULL AND active_release_pointer != $2`,
      [graphId, activePointer]
    )
    return rows
  }

  async function createK9PreparingRun(run) {
    await startDatabase()
    if (!pool) throw new Error('K9 runs require PostgreSQL')
    try {
      await pool.query(`
        INSERT INTO poc_k9_refresh_runs
        (run_id, graph_id, status, input_snapshot_hash, policy_hash, started_at)
        VALUES ($1, $2, 'PREPARING', $3, $4, clock_timestamp())
      `, [run.run_id, run.graph_id, run.input_snapshot_hash || null, run.policy_hash])
      return true
    } catch (e) {
      if (e.code === '23505' && e.constraint === 'idx_poc_k9_preparing_run') {
        throw new Error('Concurrent K9 refresh run for this graph is already in progress', { cause: e })
      }
      throw e
    }
  }

  async function getLastK9Run(graphId) {
    await startDatabase()
    if (!pool) throw new Error('K9 runs require PostgreSQL')
    const { rows } = await pool.query(`SELECT * FROM poc_k9_refresh_runs WHERE graph_id = $1 AND status = 'RUN' ORDER BY started_at DESC LIMIT 1`, [graphId])
    return rows.length ? rows[0] : null
  }

  async function finalizeK9RunNoOp(runId, activePointer) {
    await startDatabase()
    if (!pool) throw new Error('K9 runs require PostgreSQL')
    const updateResult = await pool.query(`
      UPDATE poc_k9_refresh_runs current
      SET status = 'NO_OP',
          completed_at = clock_timestamp(),
          active_release_pointer = $2,
          input_snapshot_hash = prev.input_snapshot_hash,
          manifest = prev.manifest,
          canonical_release = prev.canonical_release
      FROM poc_k9_refresh_runs prev
      WHERE current.run_id = $1
        AND current.status = 'PREPARING'
        AND prev.graph_id = current.graph_id
        AND prev.active_release_pointer = $2
        AND prev.status = 'RUN'
    `, [runId, activePointer])

    if (updateResult.rowCount !== 1) {
      throw new Error('NO_OP requires exactly one updated PREPARING row and one prior active RUN')
    }
  }

  async function finalizeK9RunFailure(runId, errorMessage) {
    await startDatabase()
    if (!pool) throw new Error('K9 runs require PostgreSQL')
    const updateResult = await pool.query(`
      UPDATE poc_k9_refresh_runs r
      SET status = 'FAILURE',
          completed_at = clock_timestamp(),
          error_message = $2,
          active_release_pointer = (
            SELECT active_release_pointer FROM poc_k9_managed_graph_policies WHERE graph_id = r.graph_id
          )
      WHERE run_id = $1 AND status = 'PREPARING'
    `, [runId, errorMessage])
    if (updateResult.rowCount !== 1) {
      throw new Error('Run failure finalization failed: run was not in PREPARING state')
    }
  }

  async function recordK9ManagedRefreshFailure(graphIdsValue, failureCodeValue, sourceDiagnosticValue = null) {
    if (!Array.isArray(graphIdsValue) || graphIdsValue.length < 1 || graphIdsValue.length > 2) {
      throw new Error('K9 managed refresh failure graphIds must contain one or two canonical graph IDs.')
    }
    const graphIds = graphIdsValue.map((value) => requireBoundedString(value, 'graphId', 36))
    if (new Set(graphIds).size !== graphIds.length
      || graphIds.some((value) => !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value))) {
      throw new Error('K9 managed refresh failure graphIds are invalid.')
    }
    const failureCode = requireBoundedString(failureCodeValue, 'failureCode', 96)
    if (!K9_REFRESH_FAILURE_CODES.has(failureCode)) {
      throw new Error('K9 managed refresh failureCode is invalid.')
    }
    const sourceDiagnostic = failureCode === 'K9_DATAHUB_SOURCE_FAILED'
      && K9_SOURCE_FAILURE_STAGES.has(sourceDiagnosticValue?.failureStage)
      && K9_SOURCE_FAILURE_DETAILS.has(sourceDiagnosticValue?.failureDetailCode)
      ? {
          failureStage: sourceDiagnosticValue.failureStage,
          failureDetailCode: sourceDiagnosticValue.failureDetailCode,
          ...(sourceDiagnosticValue.failureStage === 'METADATA_COLLECTION'
            && sanitizeK9MetadataSourceProfile(sourceDiagnosticValue.metadataProfile)
            ? { metadataProfile: sanitizeK9MetadataSourceProfile(sourceDiagnosticValue.metadataProfile) }
            : {}),
        }
      : null
    if (failureCode === 'K9_DATAHUB_SOURCE_FAILED' && !sourceDiagnostic) {
      throw new Error('K9 DataHub source failures require a bounded diagnostic.')
    }
    if (failureCode !== 'K9_DATAHUB_SOURCE_FAILED' && sourceDiagnosticValue != null) {
      throw new Error('K9 source diagnostics are valid only for DataHub source failures.')
    }
    const errorMessage = sourceDiagnostic
      ? `${failureCode}: failure_stage=${sourceDiagnostic.failureStage}; failure_detail_code=${sourceDiagnostic.failureDetailCode}.`
      : `${failureCode}: Shared managed refresh failed at a classified stage.`
    const failureManifest = sourceDiagnostic?.metadataProfile
      ? { failure_diagnostic: { metadata_source_profile: sourceDiagnostic.metadataProfile } }
      : null
    await startDatabase()
    if (!pool) throw new Error('K9 managed refresh failures require PostgreSQL')
    const client = await pool.connect()
    try {
      await client.query('BEGIN')
      for (const graphId of graphIds) {
        const inserted = await client.query(`
          INSERT INTO poc_k9_refresh_runs (
            run_id, graph_id, status, input_snapshot_hash, policy_hash,
            started_at, completed_at, active_release_pointer, error_message, manifest
          )
          SELECT $1, policy.graph_id, 'FAILURE', NULL, policy.policy_hash,
            clock_timestamp(), clock_timestamp(), policy.active_release_pointer, $3, $4::jsonb
          FROM poc_k9_managed_graph_policies AS policy
          WHERE policy.graph_id = $2
          RETURNING graph_id
        `, [randomUUID(), graphId, errorMessage, failureManifest ? JSON.stringify(failureManifest) : null])
        if (inserted.rows.length !== 1 || inserted.rows[0].graph_id !== graphId) {
          throw new Error('K9 managed refresh failure policy was not found.')
        }
      }
      await client.query('COMMIT')
    } catch (error) {
      await client.query('ROLLBACK').catch(() => undefined)
      throw error
    } finally {
      client.release()
    }
  }

  async function executeK9Transaction(graphId, runId, manifest, canonicalRelease, activePointer, manifestHash, inputSnapshotHash, policyHash) {
    await startDatabase()
    if (!pool) throw new Error('K9 runs require PostgreSQL')
    const client = await pool.connect()
    try {
      await client.query('BEGIN')

      const { rows: policyRows } = await client.query('SELECT policy_hash FROM poc_k9_managed_graph_policies WHERE graph_id = $1 FOR UPDATE', [graphId])
      if (policyRows.length === 0 || policyRows[0].policy_hash !== policyHash) {
        throw new Error('Policy not found or hash mismatch')
      }

      const { rows: runRows } = await client.query('SELECT status, graph_id, policy_hash FROM poc_k9_refresh_runs WHERE run_id = $1 FOR UPDATE', [runId])
      if (runRows.length === 0 || runRows[0].status !== 'PREPARING' || runRows[0].graph_id !== graphId || runRows[0].policy_hash !== policyHash) {
        throw new Error('Run not found, not in PREPARING status, or hash/graph mismatch')
      }

      const updateRun = await client.query(`
        UPDATE poc_k9_refresh_runs
        SET status = 'RUN', completed_at = clock_timestamp(), active_release_pointer = $2, manifest = $3::jsonb, canonical_release = $4::jsonb, input_snapshot_hash = $5
        WHERE run_id = $1 AND status = 'PREPARING'
      `, [runId, activePointer, JSON.stringify(manifest), JSON.stringify(canonicalRelease), inputSnapshotHash])

      if (updateRun.rowCount !== 1) {
        throw new Error('Run update failed')
      }

      const updatePolicy = await client.query(`
        UPDATE poc_k9_managed_graph_policies
        SET active_release_pointer = $2, active_release_hash = $3, updated_at = clock_timestamp()
        WHERE graph_id = $1 AND policy_hash = $4
      `, [graphId, activePointer, manifestHash, policyHash])

      if (updatePolicy.rowCount !== 1) {
        throw new Error('Policy update failed')
      }

      await client.query('COMMIT')
    } catch (e) {
      await client.query('ROLLBACK')
      throw e
    } finally {
      client.release()
    }
  }

  async function runK9Scheduler(command, task) {
    if (!command || typeof command !== 'object' || typeof task !== 'function') {
      throw new Error('The POC K9 scheduler command is invalid.')
    }
    const lockName = requireBoundedString(command.lockName, 'lockName', 255)
    const scheduledFor = explicitSchedulerTimestamp(command.scheduledFor)
    const trigger = requireOneOf(command.trigger || 'scheduled', 'trigger', ['scheduled', 'manual'])
    await startDatabase()
    if (!pool) throw new Error('PostgreSQL is required for the POC K9 scheduler.')
    const client = await pool.connect()
    let locked = false
    try {
      const lock = await client.query('SELECT pg_try_advisory_lock(hashtextextended($1, 0)) AS acquired', [lockName])
      locked = lock.rows[0]?.acquired === true
      if (!locked) return { status: 'locked', scheduledFor }
      const scope = 'k9-scheduler-v1:' + lockName
      const current = await client.query('SELECT value FROM poc_state WHERE scope = $1', [scope])
      const storedSuccessfulSchedule = current.rows[0]?.value?.last_successful_schedule
      const lastSuccessfulSchedule = storedSuccessfulSchedule == null
        ? null
        : explicitSchedulerTimestamp(storedSuccessfulSchedule, 'stored last_successful_schedule')
      if (lastSuccessfulSchedule === scheduledFor) return { status: 'already_completed', scheduledFor }
      if (lastSuccessfulSchedule !== null && Date.parse(lastSuccessfulSchedule) > Date.parse(scheduledFor)) return { status: 'stale', scheduledFor }
      const result = await task()
      const completedAt = new Date().toISOString()

      if (result && result.status === 'FAILURE') {
        const failureCode = typeof result.failureCode === 'string'
          && K9_REFRESH_FAILURE_CODES.has(result.failureCode)
          ? result.failureCode
          : 'K9_REFRESH_FAILED'
        const sourceDiagnostic = failureCode === 'K9_DATAHUB_SOURCE_FAILED'
          && K9_SOURCE_FAILURE_STAGES.has(result.failureStage)
          && K9_SOURCE_FAILURE_DETAILS.has(result.failureDetailCode)
          ? {
              failure_stage: result.failureStage,
              failure_detail_code: result.failureDetailCode,
              ...(result.failureStage === 'METADATA_COLLECTION'
                && sanitizeK9MetadataSourceProfile(result.metadataProfile)
                ? { metadata_source_profile: sanitizeK9MetadataSourceProfile(result.metadataProfile) }
                : {}),
            }
          : null
        const failureReceipt = {
          ...(current.rows[0]?.value || {}),
          version: 1,
          last_successful_schedule: lastSuccessfulSchedule,
          last_attempt: {
            status: 'FAILURE',
            reason: failureCode,
            ...(sourceDiagnostic || {}),
            scheduled_for: scheduledFor,
            completed_at: completedAt,
            trigger,
          },
        }
        const failureWrite = await client.query(`
          INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
          ON CONFLICT (scope) DO UPDATE
            SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
            WHERE (poc_state.value ->> 'last_successful_schedule' = $3 OR ($3 IS NULL AND poc_state.value ->> 'last_successful_schedule' IS NULL))
          RETURNING poc_state.value ->> 'last_successful_schedule' AS last_successful_schedule
        `, [scope, JSON.stringify(failureReceipt), lastSuccessfulSchedule])
        if (failureWrite.rows.length !== 1 || failureWrite.rows[0]?.last_successful_schedule !== lastSuccessfulSchedule) {
          throw new Error('The POC K9 scheduler failure receipt was not persisted.')
        }
        return { status: 'failed', scheduledFor, completedAt, result }
      }

      const receipt = {
        version: 1,
        last_successful_schedule: scheduledFor,
        completed_at: completedAt,
        trigger,
        last_attempt: {
          status: 'SUCCESS',
          ...(sanitizeK9MetadataSourceProfile(result?.metadataProfile)
            ? { metadata_source_profile: sanitizeK9MetadataSourceProfile(result.metadataProfile) }
            : {}),
          scheduled_for: scheduledFor,
          completed_at: completedAt,
          trigger,
        },
      }

      const receiptWrite = await client.query(`
        INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
        ON CONFLICT (scope) DO UPDATE
          SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
          WHERE (poc_state.value ->> 'last_successful_schedule' = $3 OR ($3 IS NULL AND poc_state.value ->> 'last_successful_schedule' IS NULL))
            AND (poc_state.value ->> 'last_successful_schedule' IS NULL OR (poc_state.value ->> 'last_successful_schedule')::timestamptz < $4::timestamptz)
        RETURNING poc_state.value ->> 'last_successful_schedule' AS last_successful_schedule
      `, [scope, JSON.stringify(receipt), lastSuccessfulSchedule, scheduledFor])

      if (receiptWrite.rows.length !== 1 || receiptWrite.rows[0]?.last_successful_schedule !== scheduledFor) {
        throw new Error('The POC K9 scheduler receipt was not advanced.')
      }

      return { status: 'succeeded', scheduledFor, completedAt, result }
    } finally {
      if (locked) {
        await client.query('SELECT pg_advisory_unlock(hashtextextended($1, 0))', [lockName])
      }
      client.release()
    }
  }

  async function listChatSessions(subjectIdValue, limitValue = 50) {
    const subjectId = requireBoundedString(subjectIdValue, 'subjectId', 255)
    const limit = Number(limitValue)
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new Error('Chat session limit must be between 1 and 100.')
    await startDatabase()
    if (pool) {
      const result = await pool.query(`
        SELECT s.session_id AS id, s.title, s.is_favorite, s.version,
          s.created_at, s.updated_at, count(m.message_id)::integer AS message_count
        FROM poc_chat_sessions s
        LEFT JOIN poc_chat_messages m
          ON m.session_id = s.session_id AND m.owner_subject_id = s.owner_subject_id
        WHERE s.owner_subject_id = $1 AND NOT s.archived
        GROUP BY s.session_id
        ORDER BY s.updated_at DESC, s.session_id DESC
        LIMIT $2
      `, [subjectId, limit])
      return result.rows.map(chatSessionRecord)
    }
    return [...memoryChatSessions.values()]
      .filter((session) => session.owner_subject_id === subjectId && !session.archived)
      .sort((left, right) => right.updated_at.localeCompare(left.updated_at) || right.session_id.localeCompare(left.session_id))
      .slice(0, limit)
      .map((session) => chatSessionRecord({
        ...session,
        id: session.session_id,
        message_count: (memoryChatMessages.get(session.session_id) ?? []).length,
      }))
  }

  async function listChatMessages(subjectIdValue, sessionIdValue, limitValue = 200) {
    const subjectId = requireBoundedString(subjectIdValue, 'subjectId', 255)
    const sessionId = requireBoundedString(sessionIdValue, 'sessionId', 200)
    const limit = Number(limitValue)
    if (!Number.isInteger(limit) || limit < 1 || limit > 500) throw new Error('Chat message limit must be between 1 and 500.')
    await startDatabase()
    if (pool) {
      const session = await pool.query(`
        SELECT 1 FROM poc_chat_sessions
        WHERE session_id = $1 AND owner_subject_id = $2 AND NOT archived
      `, [sessionId, subjectId])
      if (!session.rows.length) throw chatHistoryNotFound()
      const result = await pool.query(`
        SELECT message_id AS id, session_id, role, content, evidence_json, discovery_json,
          route_json AS route, workflow_json AS workflow, created_at
        FROM poc_chat_messages
        WHERE session_id = $1 AND owner_subject_id = $2
        ORDER BY ordinal ASC
        LIMIT $3
      `, [sessionId, subjectId, limit])
      return result.rows.map(chatMessageRecord)
    }
    const session = memoryChatSessions.get(sessionId)
    if (!session || session.owner_subject_id !== subjectId || session.archived) throw chatHistoryNotFound()
    return (memoryChatMessages.get(sessionId) ?? []).slice(0, limit).map(chatMessageRecord)
  }

  async function appendChatTurn(commandValue) {
    const command = normalizeChatTurn(commandValue)
    await startDatabase()
    if (pool) {
      const client = await pool.connect()
      try {
        await client.query('BEGIN')
        await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1, 0))', [`poc-chat:${command.sessionId}`])
        const selected = await client.query(`
          SELECT owner_subject_id, archived
          FROM poc_chat_sessions WHERE session_id = $1 FOR UPDATE
        `, [command.sessionId])
        const existing = selected.rows[0]
        if (existing && (existing.owner_subject_id !== command.subjectId || existing.archived)) throw chatHistoryNotFound()
        if (!existing) {
          await client.query(`
            INSERT INTO poc_chat_sessions (session_id, owner_subject_id, title)
            VALUES ($1, $2, $3)
          `, [command.sessionId, command.subjectId, command.title])
        }
        const ordinal = await client.query(`
          SELECT COALESCE(max(ordinal), 0)::bigint AS maximum
          FROM poc_chat_messages WHERE session_id = $1
        `, [command.sessionId])
        const firstOrdinal = Number(ordinal.rows[0]?.maximum ?? 0) + 1
        await client.query(`
          INSERT INTO poc_chat_messages (
            message_id, session_id, owner_subject_id, ordinal, role, content,
            evidence_json, discovery_json, route_json, workflow_json, created_at
          ) VALUES
            ($1, $2, $3, $4, 'user', $5, NULL, NULL, NULL, '[]'::jsonb, $6),
            ($7, $2, $3, $8, 'assistant', $9, $10::jsonb, $11::jsonb, $12::jsonb, $13::jsonb, $14)
        `, [
          command.requestMessageId, command.sessionId, command.subjectId, firstOrdinal,
          command.question, command.createdAt, command.responseMessageId, firstOrdinal + 1,
          command.answer, JSON.stringify(command.evidence), JSON.stringify(command.discovery),
          JSON.stringify(command.route), JSON.stringify(command.workflow), command.createdAt,
        ])
        if (existing) {
          await client.query(`
            UPDATE poc_chat_sessions
            SET updated_at = $2, version = version + 1
            WHERE session_id = $1
          `, [command.sessionId, command.createdAt])
        } else {
          await client.query('UPDATE poc_chat_sessions SET updated_at = $2 WHERE session_id = $1', [command.sessionId, command.createdAt])
        }
        await client.query('COMMIT')
      } catch (error) {
        await client.query('ROLLBACK').catch(() => undefined)
        throw error
      } finally {
        client.release()
      }
    } else {
      const existing = memoryChatSessions.get(command.sessionId)
      if (existing && (existing.owner_subject_id !== command.subjectId || existing.archived)) throw chatHistoryNotFound()
      const messages = memoryChatMessages.get(command.sessionId) ?? []
      messages.push(
        chatMessageRecord({ id: command.requestMessageId, session_id: command.sessionId, role: 'user', content: command.question, evidence_json: null, discovery_json: null, route: null, workflow: [], created_at: command.createdAt }),
        chatMessageRecord({ id: command.responseMessageId, session_id: command.sessionId, role: 'assistant', content: command.answer, evidence_json: command.evidence, discovery_json: command.discovery, route: command.route, workflow: command.workflow, created_at: command.createdAt }),
      )
      memoryChatMessages.set(command.sessionId, messages)
      memoryChatSessions.set(command.sessionId, existing ? {
        ...existing, updated_at: command.createdAt, version: existing.version + 1,
      } : {
        session_id: command.sessionId, owner_subject_id: command.subjectId, title: command.title,
        is_favorite: false, archived: false, version: 1,
        created_at: command.createdAt, updated_at: command.createdAt,
      })
    }
    return {
      sessionId: command.sessionId,
      requestMessageId: command.requestMessageId,
      responseMessageId: command.responseMessageId,
    }
  }

  async function setChatSessionFavorite(subjectIdValue, sessionIdValue, isFavoriteValue, expectedVersionValue) {
    const subjectId = requireBoundedString(subjectIdValue, 'subjectId', 255)
    const sessionId = requireBoundedString(sessionIdValue, 'sessionId', 200)
    if (typeof isFavoriteValue !== 'boolean') throw new Error('isFavorite must be boolean.')
    const expectedVersion = requirePositiveInteger(expectedVersionValue, 'expectedVersion')
    await startDatabase()
    if (pool) {
      const result = await pool.query(`
        UPDATE poc_chat_sessions
        SET is_favorite = $3, version = version + 1, updated_at = clock_timestamp()
        WHERE session_id = $1 AND owner_subject_id = $2 AND NOT archived AND version = $4
        RETURNING session_id AS id, title, is_favorite, version, created_at, updated_at,
          (SELECT count(*)::integer FROM poc_chat_messages WHERE session_id = $1) AS message_count
      `, [sessionId, subjectId, isFavoriteValue, expectedVersion])
      if (result.rows[0]) return chatSessionRecord(result.rows[0])
      const current = await pool.query(`
        SELECT version FROM poc_chat_sessions
        WHERE session_id = $1 AND owner_subject_id = $2 AND NOT archived
      `, [sessionId, subjectId])
      if (!current.rows.length) throw chatHistoryNotFound()
      throw chatHistoryVersionConflict()
    }
    const current = memoryChatSessions.get(sessionId)
    if (!current || current.owner_subject_id !== subjectId || current.archived) throw chatHistoryNotFound()
    if (current.version !== expectedVersion) throw chatHistoryVersionConflict()
    const updated = { ...current, is_favorite: isFavoriteValue, version: current.version + 1, updated_at: new Date().toISOString() }
    memoryChatSessions.set(sessionId, updated)
    return chatSessionRecord({ ...updated, id: sessionId, message_count: (memoryChatMessages.get(sessionId) ?? []).length })
  }

  async function archiveChatSession(subjectIdValue, sessionIdValue, expectedVersionValue) {
    const subjectId = requireBoundedString(subjectIdValue, 'subjectId', 255)
    const sessionId = requireBoundedString(sessionIdValue, 'sessionId', 200)
    const expectedVersion = requirePositiveInteger(expectedVersionValue, 'expectedVersion')
    await startDatabase()
    if (pool) {
      const result = await pool.query(`
        UPDATE poc_chat_sessions
        SET archived = true, version = version + 1, updated_at = clock_timestamp()
        WHERE session_id = $1 AND owner_subject_id = $2 AND NOT archived AND version = $3
        RETURNING session_id
      `, [sessionId, subjectId, expectedVersion])
      if (result.rows.length) return
      const current = await pool.query(`
        SELECT version FROM poc_chat_sessions
        WHERE session_id = $1 AND owner_subject_id = $2 AND NOT archived
      `, [sessionId, subjectId])
      if (!current.rows.length) throw chatHistoryNotFound()
      throw chatHistoryVersionConflict()
    }
    const current = memoryChatSessions.get(sessionId)
    if (!current || current.owner_subject_id !== subjectId || current.archived) throw chatHistoryNotFound()
    if (current.version !== expectedVersion) throw chatHistoryVersionConflict()
    memoryChatSessions.set(sessionId, { ...current, archived: true, version: current.version + 1, updated_at: new Date().toISOString() })
  }

  return {
    read,
    readFeatureSecurityPolicy,
    write,
    writeIfVersion,
    readMcpReadReceipt,
    appendMcpReadReceipt,
    cacheGet,
    cacheSet,
    cacheDelete,
    catalogEmbeddingHashes,
    catalogEmbeddingProfileCoverage,
    catalogEmbeddingActiveGeneration,
    replaceCatalogEmbeddingGeneration,
    pruneInactiveCatalogEmbeddingBindings,
    withCatalogEmbeddingGenerationLock,
    searchCatalogEmbeddings,
    readChangeHistoryCheckpoint,
    readChangeHistoryProjection,
    writeChangeHistoryCaptureStatus,
    writeChangeHistoryRuntimeStatus,
    readChangeHistoryAccess,
    writeChangeHistoryAccess,
    readLocalCredential,
    readLocalCredentialForSubject,
    insertLocalCredential,
    provisionLocalCredential,
    recordLocalLoginFailure,
    recordLocalLoginSuccess,
    createLocalSession,
    readLocalSession,
    revokeLocalSession,
    disableLocalCredential,
    listLocalCredentialAdministration,
    inspectPrepDeploymentFootprint,
    changeOwnLocalPassword,
    administerLocalCredential,
    revokeLocalSessionsForSubject,
    listUserTableGrants,
    applyUserTableGrantCommand,
    initializeChangeHistoryCaptureBoundaries,
    appendChangeHistoryCapture,
    appendChangeHistoryCrLink,
    readChangeHistoryCrLinkReplay,
    runChangeHistoryScheduler,
    readKnowledgeSourceRows,
    readKnowledgeIngestionJob,
    readKnowledgeIngestionJobByIdempotency,
    listKnowledgeIngestionJobs,
    insertKnowledgeIngestionJob,
    updateKnowledgeIngestionJob,
    getK9Policy,
    listK9ManagedGraphAssets,
    getK9ManagedGraphAsset,
    readK9SchedulerReceipt,
    ensureK9Policies,
    getK9PreparingRuns,
    getK9OrphanRuns,
    createK9PreparingRun,
    getLastK9Run,
    finalizeK9RunNoOp,
    finalizeK9RunFailure,
    recordK9ManagedRefreshFailure,
    executeK9Transaction,
    runK9Scheduler,
    listChatSessions,
    listChatMessages,
    appendChatTurn,
    setChatSessionFavorite,
    archiveChatSession,
    close,
    configured: { postgres: databaseConfigured, redis: Boolean(redisUrl) },
  }
}

const MCP_READ_RECEIPT_TOOLS = new Set([
  'UNKNOWN',
  'metadata_search',
  'knowledge_graph_assets',
  'knowledge_lineage_traversal',
  'knowledge_release_snapshot',
  'knowledge_release_graphrag',
])

function normalizeMcpReadReceipt(value) {
  if (!isPlainObject(value)) throw new Error('The MCP read receipt must be an object.')
  if (value.contract !== 'DATARIVER_MCP_READ_RECEIPT_V1') {
    throw new Error('The MCP read receipt contract is invalid.')
  }
  const keys = [
    'contract', 'receipt_id', 'service_subject_hash', 'actor_subject_hash', 'workspace_hash',
    'idempotency_key_hash', 'request_hash', 'authorization_hash', 'response_hash', 'tool_name',
    'outcome', 'reason_code', 'occurred_at',
  ]
  const observed = Object.keys(value).sort()
  if (observed.length !== keys.length || keys.sort().some((key, index) => key !== observed[index])) {
    throw new Error('The MCP read receipt shape is invalid.')
  }
  const toolName = requireBoundedString(value.tool_name, 'receipt.tool_name', 80)
  if (!MCP_READ_RECEIPT_TOOLS.has(toolName)) throw new Error('The MCP read receipt tool is invalid.')
  const outcome = requireOneOf(value.outcome, 'receipt.outcome', ['SUCCEEDED', 'DENIED', 'FAILED'])
  const reasonCode = value.reason_code == null
    ? null
    : requireBoundedString(value.reason_code, 'receipt.reason_code', 80)
  if ((reasonCode !== null && !/^[A-Z][A-Z0-9_]*$/.test(reasonCode))
    || (outcome === 'SUCCEEDED' && reasonCode !== null)
    || (outcome !== 'SUCCEEDED' && reasonCode === null)) {
    throw new Error('The MCP read receipt reason is invalid.')
  }
  return Object.freeze({
    contract: value.contract,
    receipt_id: requireSha256(value.receipt_id, 'receipt.receipt_id'),
    service_subject_hash: requireSha256(value.service_subject_hash, 'receipt.service_subject_hash'),
    actor_subject_hash: requireSha256(value.actor_subject_hash, 'receipt.actor_subject_hash'),
    workspace_hash: requireSha256(value.workspace_hash, 'receipt.workspace_hash'),
    idempotency_key_hash: requireSha256(value.idempotency_key_hash, 'receipt.idempotency_key_hash'),
    request_hash: requireSha256(value.request_hash, 'receipt.request_hash'),
    authorization_hash: requireSha256(value.authorization_hash, 'receipt.authorization_hash'),
    response_hash: requireSha256(value.response_hash, 'receipt.response_hash'),
    tool_name: toolName,
    outcome,
    reason_code: reasonCode,
    occurred_at: requireTimestamp(value.occurred_at, 'receipt.occurred_at'),
  })
}

function normalizeChatTurn(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Chat turn must be an object.')
  const subjectId = requireBoundedString(value.subjectId, 'turn.subjectId', 255)
  const sessionId = requireBoundedString(value.sessionId, 'turn.sessionId', 200)
  const requestMessageId = requireBoundedString(value.requestMessageId, 'turn.requestMessageId', 200)
  const responseMessageId = requireBoundedString(value.responseMessageId, 'turn.responseMessageId', 200)
  const question = requireBoundedString(value.question, 'turn.question', 12_000)
  const answer = requireBoundedString(value.answer, 'turn.answer', 200_000)
  const title = requireBoundedString(value.title, 'turn.title', 240)
  const createdAt = explicitSchedulerTimestamp(value.createdAt, 'turn.createdAt')
  return {
    subjectId,
    sessionId,
    requestMessageId,
    responseMessageId,
    question,
    answer,
    title,
    evidence: boundedChatJson(value.evidence, 'turn.evidence', 'array', 1_048_576),
    discovery: value.discovery == null
      ? null
      : boundedChatJson(value.discovery, 'turn.discovery', 'object', 1_048_576),
    route: boundedChatJson(value.route, 'turn.route', 'object', 262_144),
    workflow: boundedChatJson(value.workflow, 'turn.workflow', 'array', 262_144),
    createdAt,
  }
}

function boundedChatJson(value, field, kind, maximumBytes) {
  if ((kind === 'array' && !Array.isArray(value))
    || (kind === 'object' && (!value || typeof value !== 'object' || Array.isArray(value)))) {
    throw new Error(`${field} must be a JSON ${kind}.`)
  }
  const encoded = JSON.stringify(value)
  if (new TextEncoder().encode(encoded).byteLength > maximumBytes) throw new Error(`${field} exceeds its byte bound.`)
  return JSON.parse(encoded)
}

function chatSessionRecord(row) {
  return {
    id: row.id ?? row.session_id,
    title: row.title,
    is_favorite: row.is_favorite,
    version: Number(row.version),
    created_at: timestampValue(row.created_at),
    updated_at: timestampValue(row.updated_at),
    message_count: Number(row.message_count ?? 0),
  }
}

function chatMessageRecord(row) {
  return {
    id: row.id ?? row.message_id,
    session_id: row.session_id,
    role: row.role,
    content: row.content,
    evidence_json: row.evidence_json ?? null,
    discovery_json: row.discovery_json ?? null,
    created_at: timestampValue(row.created_at),
    route: row.route ?? row.route_json ?? null,
    workflow: row.workflow ?? row.workflow_json ?? [],
  }
}

function chatHistoryNotFound() {
  return Object.assign(new Error('The Chat session was not found.'), {
    code: 'CHAT_SESSION_NOT_FOUND',
    statusCode: 404,
  })
}

function chatHistoryVersionConflict() {
  return Object.assign(new Error('The Chat session version changed; read it and retry.'), {
    code: 'CHAT_SESSION_VERSION_STALE',
    statusCode: 409,
  })
}

function credentialConflict() {
  return Object.assign(new Error('The local credential subject or username already exists.'), {
    code: 'CREDENTIAL_EXISTS',
    statusCode: 409,
  })
}

function credentialVersionConflict() {
  return Object.assign(new Error('The local credential version changed; read it and retry.'), {
    code: 'CREDENTIAL_VERSION_STALE',
    statusCode: 409,
  })
}

function stateVersionConflict() {
  return Object.assign(new Error('The POC state version changed; read it and retry.'), {
    code: 'STATE_VERSION_STALE',
    statusCode: 409,
  })
}

function requireNormalizedUsername(value) {
  if (typeof value !== 'string' || !/^[a-z0-9][a-z0-9._@+-]{0,63}$/.test(value)) {
    throw new Error('usernameNormalized is outside its normalized contract.')
  }
  return value
}

function normalizeLocalCredential(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('credential must be an object.')
  }
  const subjectId = requireBoundedString(value.subjectId, 'credential.subjectId', 255)
  const usernameNormalized = requireNormalizedUsername(value.usernameNormalized)
  const passwordHash = value.passwordHash
  if (typeof passwordHash !== 'string' || passwordHash.length > 512
    || !passwordHash.startsWith('$argon2id$v=19$')) {
    throw new Error('credential.passwordHash must be a bounded Argon2id encoded hash.')
  }
  if (typeof value.loginEnabled !== 'boolean' || typeof value.mustChangePassword !== 'boolean') {
    throw new Error('credential login flags must be boolean.')
  }
  return {
    subjectId,
    usernameNormalized,
    passwordHash,
    loginEnabled: value.loginEnabled,
    mustChangePassword: value.mustChangePassword,
  }
}

function timestampValue(value) {
  if (value === null || value === undefined) return null
  return value instanceof Date ? value.toISOString() : new Date(value).toISOString()
}

function localCredentialRecord(row) {
  return {
    subjectId: row.subject_id,
    usernameNormalized: row.username_normalized,
    passwordHash: row.password_hash,
    loginEnabled: row.login_enabled,
    mustChangePassword: row.must_change_password,
    failedAttempts: Number(row.failed_attempts),
    lockedUntil: timestampValue(row.locked_until),
    version: Number(row.version),
  }
}

function requireDatasetUrn(value) {
  const urn = requireBoundedString(value, 'tableUrn', 4096)
  if (!urn.startsWith('urn:li:dataset:(')) throw new Error('tableUrn must be a canonical DataHub dataset URN.')
  return urn
}

function userTableGrantRecord(row) {
  return {
    subjectId: row.subject_id,
    tableUrn: row.table_urn,
    active: row.active,
    version: Number(row.version),
    createdAt: timestampValue(row.created_at),
    createdBy: row.created_by,
    updatedAt: timestampValue(row.updated_at),
    updatedBy: row.updated_by,
  }
}

function localSessionRecord(row) {
  return {
    tokenHash: row.token_hash,
    subjectId: row.subject_id,
    createdAt: timestampValue(row.created_at),
    expiresAt: timestampValue(row.expires_at),
    revokedAt: timestampValue(row.revoked_at),
    mustChangePassword: row.must_change_password === true,
  }
}

function assertIsolatedTestDatabaseTarget({ databasePool, databaseUrl, databaseHost }) {
  if (databasePool || (!databaseUrl && !databaseHost) || !nodeUnitTestContext()) return
  const acknowledged = process.env.POC_TEST_DATABASE_ISOLATED_ACK?.trim() === 'TRUE'
  const declaredTarget = process.env.POC_TEST_DATABASE_TARGET?.trim()
  let actualTarget
  try {
    if (databaseUrl) {
      const parsed = new URL(databaseUrl)
      const database = decodeURIComponent(parsed.pathname.replace(/^\//, ''))
      actualTarget = `${parsed.hostname}:${parsed.port || '5432'}/${database}`
    } else {
      actualTarget = `${databaseHost}:${process.env.POC_POSTGRES_PORT || '5432'}/${process.env.POC_POSTGRES_DB?.trim() || 'datariver_poc'}`
    }
  } catch {
    throw testDatabaseIsolationError()
  }
  if (!acknowledged || !declaredTarget || declaredTarget !== actualTarget) {
    throw testDatabaseIsolationError()
  }
}

function nodeUnitTestContext() {
  return Boolean(process.env.NODE_TEST_CONTEXT)
    || process.env.NODE_ENV?.trim().toLowerCase() === 'test'
    || process.execArgv.includes('--test')
    || process.argv.includes('--test')
}

function testDatabaseIsolationError() {
  return Object.assign(new Error(
    'A Node test cannot use inherited PostgreSQL settings without an explicitly acknowledged isolated target.',
  ), { code: 'POC_TEST_DATABASE_ISOLATION_REQUIRED' })
}

function changeHistoryAccessSnapshot(rows) {
  const rowByScope = new Map(rows.map((row) => [row.scope, row]))
  const snapshot = (scope) => {
    const row = rowByScope.get(scope)
    return row ? { value: row.value, version: Number(row.version) } : { value: null, version: 0 }
  }
  return { access: snapshot(CHANGE_HISTORY_ACCESS_SCOPE), core: snapshot('core') }
}

function assertAccessVersions(current, expectedAccessVersion, expectedCoreVersion) {
  if (current.access.version !== expectedAccessVersion || current.core.version !== expectedCoreVersion) {
    throw Object.assign(new Error('The change-history access state changed; read it and retry.'), {
      code: 'ACCESS_VERSION_STALE',
      statusCode: 409,
    })
  }
}

function preserveProtectedCoreAccessFields(value, currentCore, accessExists) {
  if (!accessExists) return value
  if (!isPlainObject(value)) {
    throw Object.assign(new Error('Core state must remain an object after access authority exists.'), {
      code: 'CORE_ACCESS_FIELDS_PROTECTED',
      statusCode: 409,
    })
  }
  const next = { ...value }
  const current = isPlainObject(currentCore) ? currentCore : {}
  for (const field of PROTECTED_CORE_ACCESS_FIELDS) {
    if (Object.hasOwn(current, field)) next[field] = current[field]
    else delete next[field]
  }
  return next
}

function explicitSchedulerTimestamp(value, field = 'scheduledFor') {
  if (typeof value !== 'string' || !value.endsWith('Z')) {
    throw new Error(`${field} must be an explicit UTC timestamp.`)
  }
  const parsed = new Date(value)
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString() !== value) {
    throw new Error(`${field} must be an explicit UTC timestamp.`)
  }
  return value
}

function normalizeChangeHistoryBoundaries(command) {
  if (!command || typeof command !== 'object') {
    throw new Error('The POC change-history capture boundary command is invalid.')
  }
  if (!Array.isArray(command.partitions)
    || command.partitions.length < 1
    || command.partitions.length > 1000) {
    throw new Error('The POC change-history capture boundary inventory is invalid.')
  }
  const partitions = command.partitions.map((item) => ({
    partition: requireNonnegativeInteger(item?.partition, 'partition'),
    boundary: requireNonnegativeInteger(item?.boundary, 'boundary'),
  })).sort((left, right) => left.partition - right.partition)
  if (new Set(partitions.map(({ partition }) => partition)).size !== partitions.length) {
    throw new Error('The POC change-history capture boundary inventory contains a duplicate partition.')
  }
  return {
    sourceIdentityHash: requireSha256(command.sourceIdentityHash, 'sourceIdentityHash'),
    schemaContractHash: requireSha256(command.schemaContractHash, 'schemaContractHash'),
    providerName: requireBoundedString(command.providerName, 'providerName', 100),
    providerVersion: requireBoundedString(command.providerVersion, 'providerVersion', 100),
    topicContract: requireBoundedString(command.topicContract, 'topicContract', 255),
    partitions,
  }
}

function vectorLiteral(values) {
  if (!Array.isArray(values) || values.length < 1 || values.length > 4096
    || values.some((value) => typeof value !== 'number' || !Number.isFinite(value))) {
    throw new Error('The catalog embedding is invalid or outside the supported dimension bound.')
  }
  return `[${values.join(',')}]`
}

function cosineSimilarity(left, right) {
  let dot = 0
  let leftMagnitude = 0
  let rightMagnitude = 0
  for (let index = 0; index < left.length; index += 1) {
    dot += left[index] * right[index]
    leftMagnitude += left[index] ** 2
    rightMagnitude += right[index] ** 2
  }
  if (!leftMagnitude || !rightMagnitude) return 0
  return dot / (Math.sqrt(leftMagnitude) * Math.sqrt(rightMagnitude))
}

function normalizeChangeHistoryCapture(capture) {
  if (!capture || typeof capture !== 'object') throw new Error('The POC change-history capture is invalid.')
  const sourceIdentityHash = requireSha256(capture.sourceIdentityHash, 'sourceIdentityHash')
  const schemaContractHash = requireSha256(capture.schemaContractHash, 'schemaContractHash')
  const providerName = requireBoundedString(capture.providerName, 'providerName', 100)
  const providerVersion = requireBoundedString(capture.providerVersion, 'providerVersion', 100)
  const topicContract = requireBoundedString(capture.topicContract, 'topicContract', 255)
  const partition = requireNonnegativeInteger(capture.partition, 'partition')
  const offset = requireNonnegativeInteger(capture.offset, 'offset')
  if (!Array.isArray(capture.events) || capture.events.length > 1000) {
    throw new Error('The POC change-history capture must contain 0 to 1000 normalized events.')
  }
  const sourceEventIdentity = sha256(stableJson([
    sourceIdentityHash, topicContract, partition, offset,
  ]))
  const transactionIdentity = sourceEventIdentity
  const sorted = capture.events.map((event) => normalizeSemanticEvent(event))
    .sort((left, right) => {
      const leftKey = stableJson(left)
      const rightKey = stableJson(right)
      return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0
    })
  const events = sorted.map((event, ordinal) => {
    const eventIdentity = sha256(stableJson([
      sourceEventIdentity, event.category, event.entityKey, event.operation, ordinal,
    ]))
    return {
      ...event,
      ordinal,
      eventIdentity,
      eventHash: sha256(stableJson({ ...event, eventIdentity, ordinal })),
    }
  })
  return {
    sourceIdentityHash,
    schemaContractHash,
    providerName,
    providerVersion,
    topicContract,
    partition,
    offset,
    sourceEventIdentity,
    transactionIdentity,
    events,
  }
}

function normalizeSemanticEvent(event) {
  if (!event || typeof event !== 'object') throw new Error('A normalized change-history event is invalid.')
  const category = requireOneOf(event.category, 'category', [
    'TECHNICAL_SCHEMA', 'DOCUMENTATION', 'TAG', 'GLOSSARY_TERM', 'DOMAIN', 'OWNERSHIP', 'LIFECYCLE',
  ])
  const aspectByCategory = {
    TECHNICAL_SCHEMA: ['schemaMetadata'],
    DOCUMENTATION: ['datasetProperties', 'editableSchemaMetadata'],
    TAG: ['globalTags', 'schemaMetadata', 'editableSchemaMetadata'],
    GLOSSARY_TERM: ['glossaryTerms', 'schemaMetadata', 'editableSchemaMetadata'],
    DOMAIN: ['domains'],
    OWNERSHIP: ['ownership'],
    LIFECYCLE: ['status', 'entity'],
  }
  const sourceAspect = requireOneOf(event.sourceAspect, 'sourceAspect', aspectByCategory[category])
  const beforeData = normalizeBoundedDocument(event.beforeData, 'beforeData')
  const afterData = normalizeBoundedDocument(event.afterData, 'afterData')
  return {
    assetUrn: requireBoundedString(event.assetUrn, 'assetUrn', 4096),
    entityKey: requireBoundedString(event.entityKey, 'entityKey', 1000),
    category,
    sourceAspect,
    operation: requireOneOf(event.operation, 'operation', [
      'CREATE', 'UPDATE', 'UPSERT', 'DELETE', 'ADD', 'REMOVE',
    ]),
    beforeData,
    afterData,
    beforeHash: beforeData === null ? null : sha256(stableJson(beforeData)),
    afterHash: afterData === null ? null : sha256(stableJson(afterData)),
    actorRef: event.actorRef == null ? null : requireBoundedString(event.actorRef, 'actorRef', 1000),
    sourceOccurredAt: event.sourceOccurredAt == null ? null : requireTimestamp(event.sourceOccurredAt, 'sourceOccurredAt'),
    detectedAt: requireTimestamp(event.detectedAt, 'detectedAt'),
  }
}

function normalizeChangeHistoryCrLink(command) {
  if (!command || typeof command !== 'object') throw new Error('The POC CR link command is invalid.')
  const linkKind = requireOneOf(command.linkKind, 'linkKind', ['PRIMARY', 'CANDIDATE'])
  const action = requireOneOf(command.action, 'action', linkKind === 'PRIMARY'
    ? ['SET_PRIMARY', 'CLEAR_PRIMARY']
    : ['ADD_CANDIDATE', 'REMOVE_CANDIDATE'])
  const normalized = {
    ledgerEventIdentity: requireSha256(command.ledgerEventIdentity, 'ledgerEventIdentity'),
    linkKind,
    action,
    changeRequestId: requireBoundedString(command.changeRequestId, 'changeRequestId', 200),
    changeRequestRound: requirePositiveInteger(command.changeRequestRound, 'changeRequestRound'),
    priorLinkHash: command.priorLinkHash == null ? null : requireSha256(command.priorLinkHash, 'priorLinkHash'),
    reason: requireBoundedString(command.reason, 'reason', 2000),
    policyHash: requireSha256(command.policyHash, 'policyHash'),
    basisHash: requireSha256(command.basisHash, 'basisHash'),
    actorRef: requireBoundedString(command.actorRef, 'actorRef', 1000),
    occurredAt: requireTimestamp(command.occurredAt, 'occurredAt'),
  }
  const requestKeyHash = sha256(requireBoundedString(command.idempotencyKey, 'idempotencyKey', 200))
  const requestHash = changeHistoryCrLinkRequestHash(normalized)
  const eventHash = sha256(stableJson({ ...normalized, requestKeyHash, requestHash }))
  return {
    ...normalized,
    requestKeyHash,
    requestHash,
    eventHash,
    linkEventIdentity: sha256(stableJson([requestKeyHash, requestHash])),
  }
}

function changeHistoryCrLinkRequestHash(normalized) {
  return sha256(stableJson({
    ledgerEventIdentity: normalized.ledgerEventIdentity,
    linkKind: normalized.linkKind,
    action: normalized.action,
    changeRequestId: normalized.changeRequestId,
    changeRequestRound: normalized.changeRequestRound,
    reason: normalized.reason,
  }))
}

function normalizeBoundedDocument(value, field) {
  if (value == null) return null
  if (!isPlainObject(value)) throw new Error(`${field} must be a normalized JSON object or null.`)
  assertNoRawProviderKeys(value, field)
  const normalized = JSON.parse(stableJson(value))
  if (new TextEncoder().encode(JSON.stringify(normalized)).byteLength > 16_384) {
    throw new Error(`${field} exceeds the normalized 16384-byte bound.`)
  }
  return normalized
}

function assertNoRawProviderKeys(value, field) {
  if (Array.isArray(value)) {
    for (const item of value) assertNoRawProviderKeys(item, field)
    return
  }
  if (!isPlainObject(value)) return
  for (const [key, item] of Object.entries(value)) {
    if (['raw', 'payload', 'aspect', 'schemaMetadata', 'previousAspectValue'].includes(key)) {
      throw new Error(`${field} contains a forbidden raw provider-document key.`)
    }
    assertNoRawProviderKeys(item, field)
  }
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`
  if (isPlainObject(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function sha256(value) {
  return createHash('sha256').update(value).digest('hex')
}

function requireSha256(value, field) {
  if (typeof value !== 'string' || !/^[0-9a-f]{64}$/.test(value)) {
    throw new Error(`${field} must be a lowercase SHA-256 value.`)
  }
  return value
}

function requireBoundedString(value, field, maximum) {
  if (typeof value !== 'string' || value.trim() !== value || value.length < 1 || value.length > maximum) {
    throw new Error(`${field} is outside its normalized string bound.`)
  }
  return value
}

function requireOneOf(value, field, allowed) {
  if (!allowed.includes(value)) throw new Error(`${field} is outside its closed vocabulary.`)
  return value
}

function requireNonnegativeInteger(value, field) {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error(`${field} must be a non-negative integer.`)
  return value
}

function requirePositiveInteger(value, field) {
  if (!Number.isSafeInteger(value) || value < 1) throw new Error(`${field} must be a positive integer.`)
  return value
}

function requireTimestamp(value, field) {
  if (typeof value !== 'string' || !value.endsWith('Z')) throw new Error(`${field} must be an explicit UTC timestamp.`)
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) throw new Error(`${field} must be a valid UTC timestamp.`)
  return parsed.toISOString()
}
