/* global Buffer, structuredClone */
import { canonicalStringify, computeSha256 } from './poc-knowledge-k9-contracts.mjs'

export const K9_LIFECYCLE_KEY_V2 = 'managed-k9-v2'
export const K9_SOURCE_SNAPSHOT_CONTRACT_V2 = 'DATARIVER_K9_SOURCE_SNAPSHOT_V2'
export const K9_PROJECTOR_RECEIPT_CONTRACT_V2 = 'DATARIVER_K9_PROJECTOR_RECEIPT_V2'
export const K9_PROJECTORS_V2 = Object.freeze(['SOURCE', 'LINEAGE', 'METADATA', 'SEMANTIC'])
export const K9_LIFECYCLE_STATES_V2 = Object.freeze(['PENDING', 'RUNNING', 'READY', 'FAILED'])
export const K9_LEGACY_ADOPTION_SCOPE_V2 = 'k9-lifecycle-adoption-v2'
export const K9_LEGACY_ADOPTION_CONTRACT_V2 = 'DATARIVER_K9_LEGACY_ADOPTION_V2'
export const K9_SOURCE_PAYLOAD_KINDS_V2 = Object.freeze([
  'INVENTORY', 'LINEAGE', 'METADATA', 'DANGLING_STATE',
])

const HASH = /^[0-9a-f]{64}$/
const TOKEN = /^[A-Z][A-Z0-9_]{0,79}$/

export const K9_LIFECYCLE_SCHEMA_V6 = Object.freeze([
  `
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
    )
  `,
  `
    CREATE TABLE IF NOT EXISTS poc_k9_source_payloads_v2 (
      source_snapshot_id char(64) NOT NULL
        REFERENCES poc_k9_source_snapshots_v2(source_snapshot_id),
      payload_kind varchar(32) NOT NULL,
      payload_hash char(64) NOT NULL,
      payload jsonb NOT NULL,
      recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY (source_snapshot_id, payload_kind),
      CONSTRAINT ck_poc_k9_source_payload_v2_kind CHECK (
        payload_kind IN ('INVENTORY', 'LINEAGE', 'METADATA', 'DANGLING_STATE')
      ),
      CONSTRAINT ck_poc_k9_source_payload_v2_hash CHECK (
        payload_hash ~ '^[0-9a-f]{64}$'
      ),
      CONSTRAINT ck_poc_k9_source_payload_v2_payload CHECK (
        jsonb_typeof(payload) IN ('object', 'array')
        AND octet_length(payload::text) <= 67108864
      )
    )
  `,
  `
    CREATE TABLE IF NOT EXISTS poc_k9_semantic_manifests_v2 (
      source_snapshot_id char(64) NOT NULL
        REFERENCES poc_k9_source_snapshots_v2(source_snapshot_id),
      binding_hash char(64) NOT NULL,
      desired_count integer NOT NULL,
      manifest_hash char(64) NOT NULL,
      recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY (source_snapshot_id, binding_hash),
      CONSTRAINT ck_poc_k9_semantic_manifest_v2_hashes CHECK (
        binding_hash ~ '^[0-9a-f]{64}$' AND manifest_hash ~ '^[0-9a-f]{64}$'
      ),
      CONSTRAINT ck_poc_k9_semantic_manifest_v2_bounds CHECK (
        desired_count BETWEEN 0 AND 1000000
      )
    )
  `,
  `
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
    )
  `,
  `
    CREATE TABLE IF NOT EXISTS poc_k9_semantic_batches_v2 (
      source_snapshot_id char(64) NOT NULL
        REFERENCES poc_k9_source_snapshots_v2(source_snapshot_id),
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
    )
  `,
  `
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
      CONSTRAINT ck_poc_k9_semantic_staging_v2_bounds CHECK (
        vector_dims(embedding) BETWEEN 1 AND 4096
      )
    )
  `,
  `
    CREATE INDEX IF NOT EXISTS ix_poc_k9_semantic_staging_v2_materialize
      ON poc_k9_semantic_staging_v2
      (source_snapshot_id, binding_hash, batch_number, document_id)
  `,
  `
    CREATE TABLE IF NOT EXISTS poc_k9_projector_receipts_v2 (
      receipt_id char(64) PRIMARY KEY,
      source_snapshot_id char(64) NOT NULL
        REFERENCES poc_k9_source_snapshots_v2(source_snapshot_id),
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
        AND attempt_number > 0
        AND sequence > 0
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
        AND jsonb_typeof(receipt) = 'object'
        AND octet_length(receipt::text) <= 8192
      )
    )
  `,
  `
    CREATE INDEX IF NOT EXISTS ix_poc_k9_projector_receipts_v2_latest
      ON poc_k9_projector_receipts_v2
      (source_snapshot_id, projector, attempt_number DESC, sequence DESC, receipt_id DESC)
  `,
  `
    CREATE TABLE IF NOT EXISTS poc_k9_snapshot_lifecycle_v2 (
      lifecycle_key varchar(100) PRIMARY KEY,
      desired_snapshot_id char(64) NOT NULL
        REFERENCES poc_k9_source_snapshots_v2(source_snapshot_id),
      active_snapshot_id char(64)
        REFERENCES poc_k9_source_snapshots_v2(source_snapshot_id),
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
    )
  `,
  `
    CREATE OR REPLACE FUNCTION poc_reject_k9_lifecycle_payload_mutation()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $function$
    BEGIN
      RAISE EXCEPTION 'K9 V2 source snapshots, payloads and projector receipts are immutable';
    END
    $function$
  `,
  `
    DO $block$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_poc_k9_semantic_manifests_v2_immutable'
          AND tgrelid = 'poc_k9_semantic_manifests_v2'::regclass
      ) THEN
        CREATE TRIGGER trg_poc_k9_semantic_manifests_v2_immutable
          BEFORE UPDATE OR DELETE ON poc_k9_semantic_manifests_v2
          FOR EACH ROW EXECUTE FUNCTION poc_reject_k9_lifecycle_payload_mutation();
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_poc_k9_semantic_desired_documents_v2_immutable'
          AND tgrelid = 'poc_k9_semantic_desired_documents_v2'::regclass
      ) THEN
        CREATE TRIGGER trg_poc_k9_semantic_desired_documents_v2_immutable
          BEFORE UPDATE OR DELETE ON poc_k9_semantic_desired_documents_v2
          FOR EACH ROW EXECUTE FUNCTION poc_reject_k9_lifecycle_payload_mutation();
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_poc_k9_semantic_batches_v2_immutable'
          AND tgrelid = 'poc_k9_semantic_batches_v2'::regclass
      ) THEN
        CREATE TRIGGER trg_poc_k9_semantic_batches_v2_immutable
          BEFORE UPDATE OR DELETE ON poc_k9_semantic_batches_v2
          FOR EACH ROW EXECUTE FUNCTION poc_reject_k9_lifecycle_payload_mutation();
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_poc_k9_semantic_staging_v2_immutable'
          AND tgrelid = 'poc_k9_semantic_staging_v2'::regclass
      ) THEN
        CREATE TRIGGER trg_poc_k9_semantic_staging_v2_immutable
          BEFORE UPDATE OR DELETE ON poc_k9_semantic_staging_v2
          FOR EACH ROW EXECUTE FUNCTION poc_reject_k9_lifecycle_payload_mutation();
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_poc_k9_source_payloads_v2_immutable'
          AND tgrelid = 'poc_k9_source_payloads_v2'::regclass
      ) THEN
        CREATE TRIGGER trg_poc_k9_source_payloads_v2_immutable
          BEFORE UPDATE OR DELETE ON poc_k9_source_payloads_v2
          FOR EACH ROW EXECUTE FUNCTION poc_reject_k9_lifecycle_payload_mutation();
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_poc_k9_source_snapshots_v2_immutable'
          AND tgrelid = 'poc_k9_source_snapshots_v2'::regclass
      ) THEN
        CREATE TRIGGER trg_poc_k9_source_snapshots_v2_immutable
          BEFORE UPDATE OR DELETE ON poc_k9_source_snapshots_v2
          FOR EACH ROW EXECUTE FUNCTION poc_reject_k9_lifecycle_payload_mutation();
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_poc_k9_projector_receipts_v2_immutable'
          AND tgrelid = 'poc_k9_projector_receipts_v2'::regclass
      ) THEN
        CREATE TRIGGER trg_poc_k9_projector_receipts_v2_immutable
          BEFORE UPDATE OR DELETE ON poc_k9_projector_receipts_v2
          FOR EACH ROW EXECUTE FUNCTION poc_reject_k9_lifecycle_payload_mutation();
      END IF;
    END
    $block$
  `,
])

function lifecycleError(code, message) {
  return Object.assign(new Error(message), { code })
}

function isObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function exactKeys(value, expected) {
  if (!isObject(value)) return false
  const actual = Object.keys(value).sort()
  const wanted = [...expected].sort()
  return actual.length === wanted.length && actual.every((key, index) => key === wanted[index])
}

function allowlistedKeys(value, allowed, required = []) {
  return isObject(value)
    && required.every((key) => Object.hasOwn(value, key))
    && Object.keys(value).every((key) => allowed.includes(key))
}

function boundedString(value, name, maximum, nullable = false) {
  if (nullable && value === null) return null
  if (typeof value !== 'string' || value.length < 1 || value.length > maximum) {
    throw lifecycleError('K9_LIFECYCLE_CONTRACT_INVALID', `${name} is invalid.`)
  }
  return value
}

function hash(value, name) {
  const normalized = boundedString(value, name, 64)
  if (!HASH.test(normalized)) throw lifecycleError('K9_LIFECYCLE_CONTRACT_INVALID', `${name} is invalid.`)
  return normalized
}

function timestamp(value, name, nullable = false) {
  if (nullable && value === null) return null
  if (value instanceof Date && Number.isFinite(value.getTime())) return value.toISOString()
  const normalized = boundedString(value, name, 40)
  const parsed = Date.parse(normalized)
  if (!Number.isFinite(parsed)) throw lifecycleError('K9_LIFECYCLE_CONTRACT_INVALID', `${name} is invalid.`)
  return new Date(parsed).toISOString()
}

function jsonSize(value) {
  return Buffer.byteLength(canonicalStringify(value), 'utf8')
}

export function normalizeK9SourceSnapshotV2(value) {
  const keys = [
    'authority_pin', 'catalog_generation', 'contract_version', 'dangling_state_hash',
    'datahub_commit', 'datahub_version', 'inventory_projection_hash', 'lineage_hash',
    'metadata_hash', 'metadata_source_profile', 'source_fingerprint_id', 'source_snapshot_id',
  ]
  if (!exactKeys(value, keys) || value.contract_version !== K9_SOURCE_SNAPSHOT_CONTRACT_V2) {
    throw lifecycleError('K9_SOURCE_SNAPSHOT_INVALID', 'The K9 source snapshot V2 shape is invalid.')
  }
  const normalized = {
    contract_version: K9_SOURCE_SNAPSHOT_CONTRACT_V2,
    catalog_generation: hash(value.catalog_generation, 'catalog_generation'),
    datahub_version: boundedString(value.datahub_version, 'datahub_version', 200),
    datahub_commit: value.datahub_commit === null ? null : boundedString(value.datahub_commit, 'datahub_commit', 200),
    authority_pin: structuredClone(value.authority_pin),
    inventory_projection_hash: hash(value.inventory_projection_hash, 'inventory_projection_hash'),
    lineage_hash: hash(value.lineage_hash, 'lineage_hash'),
    metadata_hash: hash(value.metadata_hash, 'metadata_hash'),
    dangling_state_hash: hash(value.dangling_state_hash, 'dangling_state_hash'),
    source_snapshot_id: hash(value.source_snapshot_id, 'source_snapshot_id'),
    source_fingerprint_id: hash(value.source_fingerprint_id, 'source_fingerprint_id'),
    metadata_source_profile: value.metadata_source_profile === null
      ? null
      : structuredClone(value.metadata_source_profile),
  }
  const authorityKeys = [
    'authorization_fingerprint', 'authorization_generation', 'classification_ceiling', 'classification_policy_version',
    'policy_version', 'projection_version', 'subject_id', 'workspace_id',
  ]
  if (!exactKeys(normalized.authority_pin, authorityKeys)
    || !['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'].includes(normalized.authority_pin.classification_ceiling)
    || !Number.isSafeInteger(normalized.authority_pin.projection_version) || normalized.authority_pin.projection_version < 1
    || !Number.isSafeInteger(normalized.authority_pin.classification_policy_version)
    || normalized.authority_pin.classification_policy_version < 1
    || !Number.isSafeInteger(normalized.authority_pin.authorization_generation)
    || normalized.authority_pin.authorization_generation < 1
    || typeof normalized.authority_pin.authorization_fingerprint !== 'string'
    || !HASH.test(normalized.authority_pin.authorization_fingerprint)
    || typeof normalized.authority_pin.subject_id !== 'string'
    || normalized.authority_pin.subject_id.length < 1 || normalized.authority_pin.subject_id.length > 255
    || typeof normalized.authority_pin.workspace_id !== 'string'
    || normalized.authority_pin.workspace_id.length < 1 || normalized.authority_pin.workspace_id.length > 255
    || typeof normalized.authority_pin.policy_version !== 'string'
    || normalized.authority_pin.policy_version.length < 1 || normalized.authority_pin.policy_version.length > 200
    || normalized.source_fingerprint_id !== normalized.source_snapshot_id
    || (normalized.metadata_source_profile !== null && !isObject(normalized.metadata_source_profile))
    || jsonSize(normalized.metadata_source_profile) > 65_536) {
    throw lifecycleError('K9_SOURCE_SNAPSHOT_INVALID', 'The K9 source snapshot V2 binding is invalid.')
  }
  const document = { ...normalized }
  delete document.source_snapshot_id
  delete document.source_fingerprint_id
  delete document.metadata_source_profile
  if (computeSha256(document) !== normalized.source_snapshot_id || jsonSize(normalized) > 131_072) {
    throw lifecycleError('K9_SOURCE_SNAPSHOT_HASH_MISMATCH', 'The K9 source snapshot V2 identity does not match its canonical document.')
  }
  return Object.freeze(normalized)
}

export function normalizeK9SourcePayloadsV2(value, snapshotValue) {
  const snapshot = normalizeK9SourceSnapshotV2(snapshotValue)
  if (!exactKeys(value, ['dangling_state', 'inventory', 'lineage', 'metadata'])) {
    throw lifecycleError('K9_SOURCE_PAYLOADS_INVALID', 'The K9 source payload set is incomplete.')
  }
  const payloads = {
    INVENTORY: structuredClone(value.inventory),
    LINEAGE: structuredClone(value.lineage),
    METADATA: structuredClone(value.metadata),
    DANGLING_STATE: structuredClone(value.dangling_state),
  }
  const expected = {
    INVENTORY: snapshot.inventory_projection_hash,
    LINEAGE: snapshot.lineage_hash,
    METADATA: snapshot.metadata_hash,
    DANGLING_STATE: snapshot.dangling_state_hash,
  }
  const inventory = payloads.INVENTORY
  if (!exactKeys(inventory, ['items', 'projection_version', 'source_generation', 'source_scope'])
    || (!Number.isSafeInteger(inventory.projection_version) && inventory.projection_version !== null)
    || (inventory.source_scope !== null && typeof inventory.source_scope !== 'string')
    || inventory.source_generation !== snapshot.catalog_generation
    || !Array.isArray(inventory.items)
    || inventory.items.some((item, index, items) => !isObject(item)
      || (index > 0 && canonicalStringify(items[index - 1]).localeCompare(canonicalStringify(item)) > 0))) {
    throw lifecycleError(
      'K9_INVENTORY_PAYLOAD_NOT_NORMALIZED',
      'The INVENTORY payload is not the normalized Catalog source bound by the snapshot.',
    )
  }
  const prohibitedSourceKey = (candidate) => {
    if (Array.isArray(candidate)) return candidate.some(prohibitedSourceKey)
    if (!isObject(candidate)) return false
    return Object.entries(candidate).some(([key, item]) => (
      key.toLowerCase().endsWith('_at')
      || key.toLowerCase().endsWith('_timestamp')
      || ['matches', 'refresh_diagnostics', 'refresh_state', 'inventory_refresh', 'latency',
        'latency_ms', 'elapsed_ms', 'duration_ms', 'retry_attempt', 'retry_count',
        'ready', 'readiness', 'created', 'createdon', 'updatedon'].includes(key.toLowerCase())
      || /(?:password|secret|token|credential|cookie|authorization|api[_-]?key)/i.test(key)
      || prohibitedSourceKey(item)
    ))
  }
  if (prohibitedSourceKey(inventory)) {
    throw lifecycleError('K9_INVENTORY_PAYLOAD_NOT_NORMALIZED', 'The INVENTORY payload retains operational or secret source fields.')
  }
  for (const kind of K9_SOURCE_PAYLOAD_KINDS_V2) {
    if ((!isObject(payloads[kind]) && !Array.isArray(payloads[kind]))
      || jsonSize(payloads[kind]) > 67_108_864
      || computeSha256(payloads[kind]) !== expected[kind]) {
      throw lifecycleError(
        'K9_SOURCE_PAYLOAD_HASH_MISMATCH',
        `The ${kind} payload does not match the canonical K9 source snapshot.`,
      )
    }
  }
  return Object.freeze(payloads)
}

function normalizeProgress(value) {
  if (value === null) return null
  const integerFields = [
    'completed_units', 'total_units', 'documents_processed', 'documents_changed',
    'documents_materialized', 'batch_size', 'batch_total', 'batch_number',
    'batch_requested_count', 'batch_response_count', 'batch_elapsed_ms', 'vector_dimensions',
  ]
  const allowed = ['phase', ...integerFields, 'provider_failure_class', 'lock_acquired', 'pointer_advanced']
  if (!allowlistedKeys(value, allowed, ['phase'])
    || typeof value.phase !== 'string' || !TOKEN.test(value.phase)
    || integerFields.some((field) => Object.hasOwn(value, field)
      && (!Number.isSafeInteger(value[field]) || value[field] < 0 || value[field] > 1_000_000_000))
    || (Object.hasOwn(value, 'completed_units') && Object.hasOwn(value, 'total_units')
      && value.completed_units > value.total_units)
    || (Object.hasOwn(value, 'batch_number') && Object.hasOwn(value, 'batch_total')
      && (value.batch_number < 1 || value.batch_number > value.batch_total))
    || (Object.hasOwn(value, 'vector_dimensions')
      && (value.vector_dimensions < 1 || value.vector_dimensions > 4096))
    || (Object.hasOwn(value, 'provider_failure_class')
      && value.provider_failure_class !== null
      && (typeof value.provider_failure_class !== 'string' || !TOKEN.test(value.provider_failure_class)))
    || ['lock_acquired', 'pointer_advanced'].some((field) => Object.hasOwn(value, field)
      && typeof value[field] !== 'boolean')) {
    throw lifecycleError('K9_PROJECTOR_RECEIPT_INVALID', 'The K9 projector progress is invalid.')
  }
  return Object.freeze({ ...value })
}

function normalizeDiagnostic(value) {
  if (value === null) return null
  if (!allowlistedKeys(value, ['code', 'detail_hash', 'provider_failure_class', 'stage'], ['code', 'detail_hash', 'stage'])
    || typeof value.code !== 'string' || !TOKEN.test(value.code)
    || typeof value.stage !== 'string' || !TOKEN.test(value.stage)
    || (Object.hasOwn(value, 'provider_failure_class')
      && value.provider_failure_class !== null
      && (typeof value.provider_failure_class !== 'string' || !TOKEN.test(value.provider_failure_class)))) {
    throw lifecycleError('K9_PROJECTOR_RECEIPT_INVALID', 'The K9 projector diagnostic is invalid.')
  }
  return Object.freeze({
    code: value.code,
    stage: value.stage,
    detail_hash: value.detail_hash === null ? null : hash(value.detail_hash, 'diagnostic.detail_hash'),
    ...(Object.hasOwn(value, 'provider_failure_class')
      ? { provider_failure_class: value.provider_failure_class } : {}),
  })
}

export function normalizeK9ProjectorReceiptV2(value) {
  const keys = [
    'attempt_id', 'attempt_number', 'contract', 'diagnostic', 'idempotency_key_hash', 'output_hash',
    'output_pointer', 'previous_receipt_id', 'progress', 'projector', 'receipt_id',
    'recorded_at', 'sequence', 'source_snapshot_id', 'status',
  ]
  if (!exactKeys(value, keys) || value.contract !== K9_PROJECTOR_RECEIPT_CONTRACT_V2
    || !K9_PROJECTORS_V2.includes(value.projector) || !K9_LIFECYCLE_STATES_V2.includes(value.status)
    || !Number.isSafeInteger(value.attempt_number) || value.attempt_number < 1
    || !Number.isSafeInteger(value.sequence) || value.sequence < 1) {
    throw lifecycleError('K9_PROJECTOR_RECEIPT_INVALID', 'The K9 projector receipt shape is invalid.')
  }
  const normalized = {
    contract: K9_PROJECTOR_RECEIPT_CONTRACT_V2,
    receipt_id: hash(value.receipt_id, 'receipt_id'),
    source_snapshot_id: hash(value.source_snapshot_id, 'source_snapshot_id'),
    projector: value.projector,
    status: value.status,
    attempt_id: hash(value.attempt_id, 'attempt_id'),
    attempt_number: value.attempt_number,
    sequence: value.sequence,
    previous_receipt_id: value.previous_receipt_id === null ? null : hash(value.previous_receipt_id, 'previous_receipt_id'),
    idempotency_key_hash: hash(value.idempotency_key_hash, 'idempotency_key_hash'),
    progress: normalizeProgress(value.progress),
    diagnostic: normalizeDiagnostic(value.diagnostic),
    output_pointer: value.output_pointer === null ? null : boundedString(value.output_pointer, 'output_pointer', 255),
    output_hash: value.output_hash === null ? null : hash(value.output_hash, 'output_hash'),
    recorded_at: timestamp(value.recorded_at, 'recorded_at'),
  }
  const terminalValid = normalized.status === 'READY'
    ? normalized.output_pointer !== null && normalized.output_hash !== null && normalized.diagnostic === null
    : normalized.status === 'FAILED'
      ? normalized.output_pointer === null && normalized.output_hash === null && normalized.diagnostic !== null
      : normalized.output_pointer === null && normalized.output_hash === null && normalized.diagnostic === null
  const document = { ...normalized }
  delete document.receipt_id
  if (!terminalValid || computeSha256(document) !== normalized.receipt_id || jsonSize(normalized) > 8192) {
    throw lifecycleError('K9_PROJECTOR_RECEIPT_INVALID', 'The K9 projector receipt identity or state is invalid.')
  }
  return Object.freeze(normalized)
}

function vectorLiteral(value) {
  if (!Array.isArray(value) || value.length < 1 || value.length > 4096
    || value.some((item) => typeof item !== 'number' || !Number.isFinite(item))) {
    throw lifecycleError('K9_SEMANTIC_DOCUMENT_INVALID', 'The staged semantic vector is invalid.')
  }
  return `[${value.join(',')}]`
}

function normalizeSemanticDesiredDocumentV2(value) {
  const keys = ['content_text', 'document_id', 'metadata', 'source_hash']
  if (!exactKeys(value, keys) || !isObject(value.metadata)
    || jsonSize(value.metadata) > 1_048_576) {
    throw lifecycleError('K9_SEMANTIC_DOCUMENT_INVALID', 'The desired semantic document shape is invalid.')
  }
  const normalized = {
    document_id: boundedString(value.document_id, 'document_id', 4096),
    asset_urn: boundedString(value.document_id, 'document_id', 4096),
    source_hash: hash(value.source_hash, 'source_hash'),
    content_text: boundedString(value.content_text, 'content_text', 200_000),
    metadata: structuredClone(value.metadata),
  }
  if (normalized.asset_urn.length < 20) {
    throw lifecycleError('K9_SEMANTIC_DOCUMENT_INVALID', 'The staged semantic asset identity is invalid.')
  }
  return Object.freeze(normalized)
}

function normalizeSemanticManifestV2(value, snapshot) {
  if (!exactKeys(value, ['binding_hash', 'documents', 'source_snapshot_id'])
    || value.source_snapshot_id !== snapshot.source_snapshot_id
    || !Array.isArray(value.documents) || value.documents.length > 1_000_000) {
    throw lifecycleError('K9_SEMANTIC_MANIFEST_INVALID', 'The desired semantic manifest shape is invalid.')
  }
  const documents = value.documents.map(normalizeSemanticDesiredDocumentV2)
  if (new Set(documents.map((item) => item.document_id)).size !== documents.length
    || new Set(documents.map((item) => item.asset_urn)).size !== documents.length) {
    throw lifecycleError('K9_SEMANTIC_MANIFEST_INVALID', 'The desired semantic manifest contains duplicate documents.')
  }
  const normalized = {
    source_snapshot_id: snapshot.source_snapshot_id,
    binding_hash: hash(value.binding_hash, 'binding_hash'),
    documents: [...documents].sort((left, right) => left.document_id.localeCompare(right.document_id)),
  }
  return Object.freeze({ ...normalized, manifest_hash: computeSha256(normalized) })
}

function normalizeChangedVectorV2(value) {
  if (!exactKeys(value, ['document_id', 'embedding', 'source_hash']) || !Array.isArray(value.embedding)) {
    throw lifecycleError('K9_SEMANTIC_DOCUMENT_INVALID', 'The changed semantic vector shape is invalid.')
  }
  const normalized = {
    document_id: boundedString(value.document_id, 'document_id', 4096),
    source_hash: hash(value.source_hash, 'source_hash'),
    embedding: [...value.embedding],
  }
  vectorLiteral(normalized.embedding)
  return Object.freeze(normalized)
}

function normalizeSemanticBatchV2(value, snapshot) {
  if (!exactKeys(value, ['batch_number', 'batch_total', 'binding_hash', 'documents', 'source_snapshot_id'])
    || value.source_snapshot_id !== snapshot.source_snapshot_id
    || !Number.isSafeInteger(value.batch_number) || value.batch_number < 1 || value.batch_number > 1_000_000
    || !Number.isSafeInteger(value.batch_total) || value.batch_total < value.batch_number || value.batch_total > 1_000_000
    || !Array.isArray(value.documents) || value.documents.length > 1_000_000) {
    throw lifecycleError('K9_SEMANTIC_BATCH_INVALID', 'The semantic staging batch shape is invalid.')
  }
  const documents = value.documents.map(normalizeChangedVectorV2)
  if (new Set(documents.map((item) => item.document_id)).size !== documents.length) {
    throw lifecycleError('K9_SEMANTIC_BATCH_INVALID', 'The semantic staging batch contains duplicate documents.')
  }
  const normalized = {
    source_snapshot_id: snapshot.source_snapshot_id,
    binding_hash: hash(value.binding_hash, 'binding_hash'),
    batch_number: value.batch_number,
    batch_total: value.batch_total,
    documents,
  }
  return Object.freeze({ ...normalized, batch_hash: computeSha256(normalized) })
}

export async function applyK9LifecycleSchemaV6(client) {
  for (const statement of K9_LIFECYCLE_SCHEMA_V6) await client.query(statement)
}

function snapshotInsertValues(snapshot) {
  return [
    snapshot.source_snapshot_id, snapshot.contract_version, snapshot.source_fingerprint_id,
    snapshot.catalog_generation, snapshot.datahub_version, snapshot.datahub_commit,
    JSON.stringify(snapshot.authority_pin), snapshot.inventory_projection_hash,
    snapshot.lineage_hash, snapshot.metadata_hash, snapshot.dangling_state_hash,
    JSON.stringify(snapshot),
  ]
}

async function insertSnapshot(client, snapshot) {
  const inserted = await client.query(`
    INSERT INTO poc_k9_source_snapshots_v2 (
      source_snapshot_id, contract_version, source_fingerprint_id, catalog_generation,
      datahub_version, datahub_commit, authority_pin, inventory_projection_hash,
      lineage_hash, metadata_hash, dangling_state_hash, snapshot
    ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11,$12::jsonb)
    ON CONFLICT (source_snapshot_id) DO NOTHING
    RETURNING source_snapshot_id
  `, snapshotInsertValues(snapshot))
  if (inserted.rows.length === 1) return true
  const existing = await client.query(
    'SELECT snapshot FROM poc_k9_source_snapshots_v2 WHERE source_snapshot_id = $1',
    [snapshot.source_snapshot_id],
  )
  if (existing.rows.length !== 1
    || canonicalStringify(existing.rows[0].snapshot) !== canonicalStringify(snapshot)) {
    throw lifecycleError('K9_SOURCE_SNAPSHOT_CONFLICT', 'The K9 source snapshot identity conflicts with persisted evidence.')
  }
  return false
}

async function insertSourcePayloads(client, snapshot, payloads) {
  const hashes = {
    INVENTORY: snapshot.inventory_projection_hash,
    LINEAGE: snapshot.lineage_hash,
    METADATA: snapshot.metadata_hash,
    DANGLING_STATE: snapshot.dangling_state_hash,
  }
  let created = false
  for (const kind of K9_SOURCE_PAYLOAD_KINDS_V2) {
    const inserted = await client.query(`
      INSERT INTO poc_k9_source_payloads_v2 (
        source_snapshot_id, payload_kind, payload_hash, payload
      ) VALUES ($1, $2, $3, $4::jsonb)
      ON CONFLICT (source_snapshot_id, payload_kind) DO NOTHING
      RETURNING payload_kind
    `, [snapshot.source_snapshot_id, kind, hashes[kind], JSON.stringify(payloads[kind])])
    if (inserted.rows.length === 1) {
      created = true
      continue
    }
    const existing = await client.query(`
      SELECT payload_hash, payload FROM poc_k9_source_payloads_v2
      WHERE source_snapshot_id = $1 AND payload_kind = $2
    `, [snapshot.source_snapshot_id, kind])
    if (existing.rows.length !== 1 || existing.rows[0].payload_hash !== hashes[kind]
      || canonicalStringify(existing.rows[0].payload) !== canonicalStringify(payloads[kind])) {
      throw lifecycleError('K9_SOURCE_PAYLOAD_CONFLICT', 'Persisted K9 source payload evidence conflicts with its identity.')
    }
  }
  return created
}

function receiptInsertValues(receipt) {
  return [
    receipt.receipt_id, receipt.source_snapshot_id, receipt.projector, receipt.status,
    receipt.attempt_id, receipt.attempt_number, receipt.sequence, receipt.previous_receipt_id,
    receipt.idempotency_key_hash, receipt.progress ? JSON.stringify(receipt.progress) : null,
    receipt.diagnostic ? JSON.stringify(receipt.diagnostic) : null,
    receipt.output_pointer, receipt.output_hash, receipt.recorded_at, JSON.stringify(receipt),
  ]
}

async function insertReceipt(client, receipt) {
  const inserted = await client.query(`
    INSERT INTO poc_k9_projector_receipts_v2 (
      receipt_id, source_snapshot_id, projector, status, attempt_id, attempt_number, sequence,
      previous_receipt_id, idempotency_key_hash, progress, diagnostic,
      output_pointer, output_hash, recorded_at, receipt
    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb,$12,$13,$14,$15::jsonb)
    ON CONFLICT (projector, idempotency_key_hash) DO NOTHING
    RETURNING receipt_id
  `, receiptInsertValues(receipt))
  if (inserted.rows.length === 1) return true
  const existing = await client.query(`
    SELECT receipt FROM poc_k9_projector_receipts_v2
    WHERE projector = $1 AND idempotency_key_hash = $2
  `, [receipt.projector, receipt.idempotency_key_hash])
  if (existing.rows.length !== 1
    || canonicalStringify(existing.rows[0].receipt) !== canonicalStringify(receipt)) {
    throw lifecycleError('K9_PROJECTOR_RECEIPT_CONFLICT', 'The K9 projector idempotency key conflicts with persisted evidence.')
  }
  return false
}

export async function adoptExactLegacyK9LifecycleV2(client) {
  const persisted = await client.query(
    'SELECT value, version FROM poc_state WHERE scope = $1',
    [K9_LEGACY_ADOPTION_SCOPE_V2],
  )
  if (persisted.rows.length > 0) {
    const value = persisted.rows[0]?.value
    if (persisted.rows.length !== 1 || Number(persisted.rows[0]?.version) !== 1
      || value?.contract !== K9_LEGACY_ADOPTION_CONTRACT_V2
      || !['NO_LEGACY_STATE', 'NEW_SNAPSHOT_REQUIRED'].includes(value?.state)
      || !['NOT_PRESENT', 'PRESERVED'].includes(value?.legacy_lkg_state)) {
      throw lifecycleError('K9_LIFECYCLE_ADOPTION_CONFLICT', 'The durable K9 legacy adoption receipt is invalid.')
    }
    return Object.freeze({ state: value.state })
  }
  const existing = await client.query('SELECT count(*)::integer AS count FROM poc_k9_snapshot_lifecycle_v2')
  if (existing.rows[0]?.count !== 0) {
    throw lifecycleError('K9_LIFECYCLE_ADOPTION_CONFLICT', 'K9 V2 lifecycle state already exists during historical adoption.')
  }
  const legacy = await client.query(`
    SELECT
      (SELECT count(*)::integer FROM poc_k9_managed_graph_policies) AS policy_count,
      (SELECT count(*)::integer FROM poc_k9_refresh_runs) AS run_count,
      (SELECT count(*)::integer FROM poc_state
        WHERE scope LIKE 'catalog-embedding-active-v1:%') AS semantic_pointer_count
  `)
  const evidence = legacy.rows[0]
  if (!evidence || !Number.isInteger(evidence.policy_count)
    || !Number.isInteger(evidence.run_count) || !Number.isInteger(evidence.semantic_pointer_count)) {
    throw lifecycleError('K9_LIFECYCLE_ADOPTION_INSPECTION_INVALID', 'The legacy K9 lifecycle inspection was malformed.')
  }
  const noLegacyState = evidence.policy_count === 0
    && evidence.run_count === 0
    && evidence.semantic_pointer_count === 0
  // ADR-0130 manifests omit authority_pin, inventory_projection_hash and
  // dangling_state_hash. Even matching graph/LKG and semantic pointers cannot
  // prove the canonical DATARIVER_K9_SOURCE_SNAPSHOT_V2 identity. Preserve all
  // legacy payloads and pointers verbatim; the next collector cycle must create
  // the first V2 snapshot and receipts.
  const adoption = Object.freeze({
    contract: K9_LEGACY_ADOPTION_CONTRACT_V2,
    state: noLegacyState ? 'NO_LEGACY_STATE' : 'NEW_SNAPSHOT_REQUIRED',
    legacy_lkg_state: noLegacyState ? 'NOT_PRESENT' : 'PRESERVED',
    policy_count: evidence.policy_count,
    run_count: evidence.run_count,
    semantic_pointer_count: evidence.semantic_pointer_count,
  })
  const inserted = await client.query(`
    INSERT INTO poc_state (scope, value, version)
    VALUES ($1, $2::jsonb, 1)
    ON CONFLICT (scope) DO NOTHING
    RETURNING value, version
  `, [K9_LEGACY_ADOPTION_SCOPE_V2, JSON.stringify(adoption)])
  if (inserted.rows.length !== 1 || Number(inserted.rows[0]?.version) !== 1
    || canonicalStringify(inserted.rows[0]?.value) !== canonicalStringify(adoption)) {
    throw lifecycleError('K9_LIFECYCLE_ADOPTION_CONFLICT', 'The durable K9 legacy adoption receipt could not be recorded exactly once.')
  }
  return Object.freeze({ state: adoption.state })
}

function allowedReceiptTransition(previous, receipt) {
  if (!previous) return receipt.attempt_number === 1 && receipt.sequence === 1
    && receipt.previous_receipt_id === null && receipt.status === 'PENDING'
  if (previous.status === 'FAILED') {
    return receipt.status === 'PENDING'
      && receipt.attempt_number === Number(previous.attempt_number) + 1
      && receipt.attempt_id !== previous.attempt_id
      && receipt.sequence === 1
      && receipt.previous_receipt_id === previous.receipt_id
  }
  if (receipt.attempt_number !== Number(previous.attempt_number)
    || receipt.attempt_id !== previous.attempt_id || receipt.sequence !== Number(previous.sequence) + 1
    || receipt.previous_receipt_id !== previous.receipt_id) return false
  if (previous.status === 'PENDING') return ['RUNNING', 'FAILED'].includes(receipt.status)
  if (previous.status === 'RUNNING') return ['RUNNING', 'READY', 'FAILED'].includes(receipt.status)
  return false
}

export function createK9LifecyclePersistenceV2({ requireDatabase }) {
  if (typeof requireDatabase !== 'function') throw new Error('K9 lifecycle persistence requires a database provider.')

  async function setDesiredSnapshot({ snapshot: snapshotValue, source_payloads: sourcePayloadsValue }, lifecycleKeyValue = K9_LIFECYCLE_KEY_V2) {
    const snapshot = normalizeK9SourceSnapshotV2(snapshotValue)
    const sourcePayloads = normalizeK9SourcePayloadsV2(sourcePayloadsValue, snapshot)
    const lifecycleKey = boundedString(lifecycleKeyValue, 'lifecycleKey', 100)
    const pool = await requireDatabase()
    const client = await pool.connect()
    try {
      await client.query('BEGIN')
      const created = await insertSnapshot(client, snapshot)
      const payloadsCreated = await insertSourcePayloads(client, snapshot, sourcePayloads)
      await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1, 0))', [`k9-lifecycle-v2:${lifecycleKey}`])
      const current = await client.query(
        'SELECT * FROM poc_k9_snapshot_lifecycle_v2 WHERE lifecycle_key = $1 FOR UPDATE',
        [lifecycleKey],
      )
      let version
      if (current.rows.length === 0) {
        const inserted = await client.query(`
          INSERT INTO poc_k9_snapshot_lifecycle_v2 (
            lifecycle_key, desired_snapshot_id, status
          ) VALUES ($1, $2, 'PENDING') RETURNING version
        `, [lifecycleKey, snapshot.source_snapshot_id])
        version = Number(inserted.rows[0].version)
      } else if (current.rows[0].desired_snapshot_id === snapshot.source_snapshot_id) {
        version = Number(current.rows[0].version)
      } else {
        if (['PENDING', 'RUNNING'].includes(current.rows[0].status)) {
          throw lifecycleError('K9_LIFECYCLE_IN_PROGRESS', 'A different K9 source snapshot is already in progress.')
        }
        const updated = await client.query(`
          UPDATE poc_k9_snapshot_lifecycle_v2
          SET desired_snapshot_id = $2, status = 'PENDING', version = version + 1,
            updated_at = clock_timestamp()
          WHERE lifecycle_key = $1 AND version = $3
          RETURNING version
        `, [lifecycleKey, snapshot.source_snapshot_id, current.rows[0].version])
        if (updated.rows.length !== 1) throw lifecycleError('K9_LIFECYCLE_STALE', 'The K9 lifecycle head changed.')
        version = Number(updated.rows[0].version)
      }
      await client.query('COMMIT')
      return { created, payloadsCreated, lifecycleKey, sourceSnapshotId: snapshot.source_snapshot_id, version }
    } catch (error) {
      await client.query('ROLLBACK').catch(() => undefined)
      throw error
    } finally {
      client.release()
    }
  }

  async function appendProjectorReceipt(receiptValue, lifecycleKeyValue = K9_LIFECYCLE_KEY_V2) {
    const receipt = normalizeK9ProjectorReceiptV2(receiptValue)
    const lifecycleKey = boundedString(lifecycleKeyValue, 'lifecycleKey', 100)
    const pool = await requireDatabase()
    const client = await pool.connect()
    try {
      await client.query('BEGIN')
      await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1, 0))', [
        `k9-projector-v2:${receipt.source_snapshot_id}:${receipt.projector}`,
      ])
      const replay = await client.query(`
        SELECT receipt FROM poc_k9_projector_receipts_v2
        WHERE projector = $1 AND idempotency_key_hash = $2
      `, [receipt.projector, receipt.idempotency_key_hash])
      if (replay.rows.length) {
        if (canonicalStringify(replay.rows[0].receipt) !== canonicalStringify(receipt)) {
          throw lifecycleError('K9_PROJECTOR_RECEIPT_CONFLICT', 'The K9 projector idempotency key conflicts with persisted evidence.')
        }
        await client.query('COMMIT')
        return { created: false, receipt }
      }
      const head = await client.query(
        'SELECT * FROM poc_k9_snapshot_lifecycle_v2 WHERE lifecycle_key = $1 FOR UPDATE',
        [lifecycleKey],
      )
      if (head.rows.length !== 1 || head.rows[0].desired_snapshot_id !== receipt.source_snapshot_id
        || head.rows[0].status === 'READY') {
        throw lifecycleError('K9_LIFECYCLE_HEAD_MISMATCH', 'The receipt does not target the current mutable K9 lifecycle head.')
      }
      const latest = await client.query(`
        SELECT receipt_id, attempt_id, attempt_number, sequence, status, progress
        FROM poc_k9_projector_receipts_v2
        WHERE source_snapshot_id = $1 AND projector = $2
        ORDER BY attempt_number DESC, sequence DESC, receipt_id DESC LIMIT 1
        FOR UPDATE
      `, [receipt.source_snapshot_id, receipt.projector])
      const previous = latest.rows[0]
      if (!allowedReceiptTransition(previous, receipt)) {
        throw lifecycleError('K9_PROJECTOR_TRANSITION_INVALID', 'The K9 projector receipt transition is not forward-only.')
      }
      if (previous?.attempt_id === receipt.attempt_id && previous?.progress && receipt.progress
        && (receipt.progress.completed_units < Number(previous.progress.completed_units)
          || receipt.progress.total_units !== Number(previous.progress.total_units))) {
        throw lifecycleError('K9_PROJECTOR_PROGRESS_REGRESSION', 'The K9 projector progress regressed.')
      }
      await insertReceipt(client, receipt)
      const latestStates = await client.query(`
        SELECT DISTINCT ON (projector) projector, status
        FROM poc_k9_projector_receipts_v2
        WHERE source_snapshot_id = $1
        ORDER BY projector, attempt_number DESC, sequence DESC, receipt_id DESC
      `, [receipt.source_snapshot_id])
      const states = latestStates.rows.map((row) => row.status)
      const nextStatus = states.some((status) => ['PENDING', 'RUNNING'].includes(status))
        ? 'RUNNING'
        : states.some((status) => status === 'FAILED') ? 'FAILED' : 'RUNNING'
      if (nextStatus !== head.rows[0].status) {
        await client.query(`
          UPDATE poc_k9_snapshot_lifecycle_v2
          SET status = $2, version = version + 1, updated_at = clock_timestamp()
          WHERE lifecycle_key = $1
        `, [lifecycleKey, nextStatus])
      }
      await client.query('COMMIT')
      return { created: true, receipt }
    } catch (error) {
      await client.query('ROLLBACK').catch(() => undefined)
      throw error
    } finally {
      client.release()
    }
  }

  async function promoteActiveSnapshot({
    sourceSnapshotId: sourceSnapshotIdValue,
    expectedVersion,
    lifecycleKey: lifecycleKeyValue = K9_LIFECYCLE_KEY_V2,
  }) {
    const sourceSnapshotId = hash(sourceSnapshotIdValue, 'sourceSnapshotId')
    const lifecycleKey = boundedString(lifecycleKeyValue, 'lifecycleKey', 100)
    if (!Number.isSafeInteger(expectedVersion) || expectedVersion < 1) {
      throw lifecycleError('K9_LIFECYCLE_CONTRACT_INVALID', 'expectedVersion is invalid.')
    }
    const pool = await requireDatabase()
    const client = await pool.connect()
    try {
      await client.query('BEGIN')
      const head = await client.query(
        'SELECT * FROM poc_k9_snapshot_lifecycle_v2 WHERE lifecycle_key = $1 FOR UPDATE',
        [lifecycleKey],
      )
      if (head.rows.length !== 1 || head.rows[0].desired_snapshot_id !== sourceSnapshotId
        || Number(head.rows[0].version) !== expectedVersion) {
        throw lifecycleError('K9_LIFECYCLE_STALE', 'The K9 lifecycle head cannot be promoted.')
      }
      if (head.rows[0].status === 'READY' && head.rows[0].active_snapshot_id === sourceSnapshotId) {
        await client.query('COMMIT')
        return { promoted: false, version: Number(head.rows[0].version) }
      }
      const latest = await client.query(`
        SELECT DISTINCT ON (projector) projector, status
        FROM poc_k9_projector_receipts_v2
        WHERE source_snapshot_id = $1
        ORDER BY projector, attempt_number DESC, sequence DESC, receipt_id DESC
      `, [sourceSnapshotId])
      const statuses = new Map(latest.rows.map((row) => [row.projector, row.status]))
      if (K9_PROJECTORS_V2.some((projector) => statuses.get(projector) !== 'READY')) {
        throw lifecycleError('K9_PROJECTORS_NOT_READY', 'Every K9 V2 projector must be READY before promotion.')
      }
      const updated = await client.query(`
        UPDATE poc_k9_snapshot_lifecycle_v2
        SET active_snapshot_id = desired_snapshot_id, status = 'READY',
          version = version + 1, updated_at = clock_timestamp()
        WHERE lifecycle_key = $1 AND version = $2
        RETURNING version
      `, [lifecycleKey, expectedVersion])
      if (updated.rows.length !== 1) throw lifecycleError('K9_LIFECYCLE_STALE', 'The K9 lifecycle head changed.')
      await client.query('COMMIT')
      return { promoted: true, version: Number(updated.rows[0].version) }
    } catch (error) {
      await client.query('ROLLBACK').catch(() => undefined)
      throw error
    } finally {
      client.release()
    }
  }

  async function persistSemanticDesiredManifest(manifestValue, lifecycleKeyValue = K9_LIFECYCLE_KEY_V2) {
    const lifecycleKey = boundedString(lifecycleKeyValue, 'lifecycleKey', 100)
    const sourceSnapshotId = hash(manifestValue?.source_snapshot_id, 'source_snapshot_id')
    const pool = await requireDatabase()
    const client = await pool.connect()
    try {
      await client.query('BEGIN')
      await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1, 0))', [
        `k9-semantic-manifest-v2:${sourceSnapshotId}:${manifestValue?.binding_hash}`,
      ])
      const evidence = await client.query(`
        SELECT source.snapshot
        FROM poc_k9_snapshot_lifecycle_v2 AS head
        JOIN poc_k9_source_snapshots_v2 AS source
          ON source.source_snapshot_id = head.desired_snapshot_id
        WHERE head.lifecycle_key = $1 AND head.desired_snapshot_id = $2
        FOR UPDATE OF head
      `, [lifecycleKey, sourceSnapshotId])
      if (evidence.rows.length !== 1) {
        throw lifecycleError('K9_LIFECYCLE_HEAD_MISMATCH', 'The semantic manifest does not target the desired K9 snapshot.')
      }
      const manifest = normalizeSemanticManifestV2(
        manifestValue,
        normalizeK9SourceSnapshotV2(evidence.rows[0].snapshot),
      )
      const inserted = await client.query(`
        INSERT INTO poc_k9_semantic_manifests_v2 (
          source_snapshot_id, binding_hash, desired_count, manifest_hash
        ) VALUES ($1,$2,$3,$4)
        ON CONFLICT (source_snapshot_id, binding_hash) DO NOTHING
        RETURNING manifest_hash
      `, [manifest.source_snapshot_id, manifest.binding_hash, manifest.documents.length, manifest.manifest_hash])
      if (inserted.rows.length === 0) {
        const existing = await client.query(`
          SELECT desired_count, manifest_hash FROM poc_k9_semantic_manifests_v2
          WHERE source_snapshot_id = $1 AND binding_hash = $2
        `, [manifest.source_snapshot_id, manifest.binding_hash])
        if (existing.rows.length !== 1 || Number(existing.rows[0].desired_count) !== manifest.documents.length
          || existing.rows[0].manifest_hash !== manifest.manifest_hash) {
          throw lifecycleError('K9_SEMANTIC_MANIFEST_CONFLICT', 'The semantic manifest conflicts with persisted evidence.')
        }
      }
      for (const document of manifest.documents) {
        const row = await client.query(`
          INSERT INTO poc_k9_semantic_desired_documents_v2 (
            source_snapshot_id, binding_hash, document_id, asset_urn, source_hash, content_text, metadata
          ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)
          ON CONFLICT (source_snapshot_id, binding_hash, document_id) DO NOTHING
          RETURNING document_id
        `, [manifest.source_snapshot_id, manifest.binding_hash, document.document_id,
          document.asset_urn, document.source_hash, document.content_text, JSON.stringify(document.metadata)])
        if (row.rows.length === 0) {
          const exact = await client.query(`
            SELECT document_id FROM poc_k9_semantic_desired_documents_v2
            WHERE source_snapshot_id = $1 AND binding_hash = $2 AND document_id = $3
              AND asset_urn = $4 AND source_hash = $5 AND content_text = $6 AND metadata = $7::jsonb
          `, [manifest.source_snapshot_id, manifest.binding_hash, document.document_id,
            document.asset_urn, document.source_hash, document.content_text, JSON.stringify(document.metadata)])
          if (exact.rows.length !== 1) {
            throw lifecycleError('K9_SEMANTIC_DOCUMENT_CONFLICT', 'The desired semantic document conflicts with persisted evidence.')
          }
        }
      }
      await client.query('COMMIT')
      return { created: inserted.rows.length === 1, manifest_hash: manifest.manifest_hash, desired_count: manifest.documents.length }
    } catch (error) {
      await client.query('ROLLBACK').catch(() => undefined)
      throw error
    } finally {
      client.release()
    }
  }

  async function stageSemanticBatch(batchValue, lifecycleKeyValue = K9_LIFECYCLE_KEY_V2) {
    const lifecycleKey = boundedString(lifecycleKeyValue, 'lifecycleKey', 100)
    const sourceSnapshotId = hash(batchValue?.source_snapshot_id, 'source_snapshot_id')
    const pool = await requireDatabase()
    const client = await pool.connect()
    try {
      await client.query('BEGIN')
      await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1, 0))', [
        `k9-semantic-stage-v2:${sourceSnapshotId}:${batchValue?.binding_hash}`,
      ])
      const evidence = await client.query(`
        SELECT source.snapshot
        FROM poc_k9_snapshot_lifecycle_v2 AS head
        JOIN poc_k9_source_snapshots_v2 AS source
          ON source.source_snapshot_id = head.desired_snapshot_id
        WHERE head.lifecycle_key = $1 AND head.desired_snapshot_id = $2
        FOR UPDATE OF head
      `, [lifecycleKey, sourceSnapshotId])
      if (evidence.rows.length !== 1) {
        throw lifecycleError('K9_LIFECYCLE_HEAD_MISMATCH', 'Semantic staging does not target the desired K9 snapshot.')
      }
      const snapshot = normalizeK9SourceSnapshotV2(evidence.rows[0].snapshot)
      const batch = normalizeSemanticBatchV2(batchValue, snapshot)
      const inserted = await client.query(`
        INSERT INTO poc_k9_semantic_batches_v2 (
          source_snapshot_id, binding_hash, batch_number, batch_total, document_count, batch_hash
        ) VALUES ($1,$2,$3,$4,$5,$6)
        ON CONFLICT (source_snapshot_id, binding_hash, batch_number) DO NOTHING
        RETURNING batch_number
      `, [batch.source_snapshot_id, batch.binding_hash, batch.batch_number,
        batch.batch_total, batch.documents.length, batch.batch_hash])
      if (inserted.rows.length === 0) {
        const existing = await client.query(`
          SELECT batch_total, document_count, batch_hash
          FROM poc_k9_semantic_batches_v2
          WHERE source_snapshot_id = $1 AND binding_hash = $2 AND batch_number = $3
        `, [batch.source_snapshot_id, batch.binding_hash, batch.batch_number])
        if (existing.rows.length !== 1
          || Number(existing.rows[0].batch_total) !== batch.batch_total
          || Number(existing.rows[0].document_count) !== batch.documents.length
          || existing.rows[0].batch_hash !== batch.batch_hash) {
          throw lifecycleError('K9_SEMANTIC_BATCH_CONFLICT', 'The semantic batch identity conflicts with staged evidence.')
        }
      }
      for (const document of batch.documents) {
        const row = await client.query(`
          INSERT INTO poc_k9_semantic_staging_v2 (
            source_snapshot_id, binding_hash, document_id, batch_number, source_hash, embedding
          ) VALUES ($1,$2,$3,$4,$5,$6::vector)
          ON CONFLICT (source_snapshot_id, binding_hash, document_id) DO NOTHING
          RETURNING document_id
        `, [batch.source_snapshot_id, batch.binding_hash, document.document_id,
          batch.batch_number, document.source_hash, vectorLiteral(document.embedding)])
        if (row.rows.length === 0) {
          const exact = await client.query(`
            SELECT document_id FROM poc_k9_semantic_staging_v2
            WHERE source_snapshot_id = $1 AND binding_hash = $2 AND document_id = $3
              AND batch_number = $4 AND source_hash = $5 AND embedding = $6::vector
          `, [batch.source_snapshot_id, batch.binding_hash, document.document_id,
            batch.batch_number, document.source_hash, vectorLiteral(document.embedding)])
          if (exact.rows.length !== 1) {
            throw lifecycleError('K9_SEMANTIC_DOCUMENT_CONFLICT', 'The semantic document identity conflicts with staged evidence.')
          }
        }
      }
      await client.query('COMMIT')
      return { created: inserted.rows.length === 1, batch_hash: batch.batch_hash, document_count: batch.documents.length }
    } catch (error) {
      await client.query('ROLLBACK').catch(() => undefined)
      throw error
    } finally {
      client.release()
    }
  }

  async function activateSemanticSnapshot(value, lifecycleKeyValue = K9_LIFECYCLE_KEY_V2) {
    const lifecycleKey = boundedString(lifecycleKeyValue, 'lifecycleKey', 100)
    const keys = [
      'binding_hash', 'expected_batch_count', 'expected_changed_count',
      'expected_desired_count', 'source_snapshot_id',
    ]
    if (!exactKeys(value, keys)
      || !Number.isSafeInteger(value.expected_batch_count) || value.expected_batch_count < 0
      || !Number.isSafeInteger(value.expected_changed_count) || value.expected_changed_count < 0
      || !Number.isSafeInteger(value.expected_desired_count) || value.expected_desired_count < 0
      || value.expected_changed_count > value.expected_desired_count
      || (value.expected_changed_count === 0 && value.expected_batch_count !== 0)
      || (value.expected_changed_count > 0 && value.expected_batch_count < 1)) {
      throw lifecycleError('K9_SEMANTIC_ACTIVATION_INVALID', 'The semantic activation contract is invalid.')
    }
    const sourceSnapshotId = hash(value.source_snapshot_id, 'source_snapshot_id')
    const bindingHash = hash(value.binding_hash, 'binding_hash')
    const pool = await requireDatabase()
    const client = await pool.connect()
    try {
      await client.query('BEGIN')
      await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1, 0))', [
        `k9-semantic-activate-v2:${sourceSnapshotId}:${bindingHash}`,
      ])
      const head = await client.query(`
        SELECT head.desired_snapshot_id, source.catalog_generation
        FROM poc_k9_snapshot_lifecycle_v2 AS head
        JOIN poc_k9_source_snapshots_v2 AS source
          ON source.source_snapshot_id = head.desired_snapshot_id
        WHERE head.lifecycle_key = $1
        FOR UPDATE OF head
      `, [lifecycleKey])
      if (head.rows.length !== 1 || head.rows[0].desired_snapshot_id !== sourceSnapshotId) {
        throw lifecycleError('K9_LIFECYCLE_HEAD_MISMATCH', 'Semantic activation does not target the desired K9 snapshot.')
      }
      const manifest = await client.query(`
        SELECT desired_count, manifest_hash
        FROM poc_k9_semantic_manifests_v2
        WHERE source_snapshot_id = $1 AND binding_hash = $2
      `, [sourceSnapshotId, bindingHash])
      const completeness = await client.query(`
        SELECT count(*)::integer AS batch_count,
          min(batch_number)::integer AS first_batch,
          max(batch_number)::integer AS last_batch,
          min(batch_total)::integer AS minimum_total,
          max(batch_total)::integer AS maximum_total,
          sum(document_count)::integer AS declared_documents
        FROM poc_k9_semantic_batches_v2
        WHERE source_snapshot_id = $1 AND binding_hash = $2
      `, [sourceSnapshotId, bindingHash])
      const staged = await client.query(`
        SELECT count(*)::integer AS document_count,
          count(*) FILTER (WHERE desired.document_id IS NOT NULL)::integer AS desired_match_count,
          min(vector_dims(embedding))::integer AS minimum_dimensions,
          max(vector_dims(embedding))::integer AS maximum_dimensions
        FROM poc_k9_semantic_staging_v2 AS staged
        LEFT JOIN poc_k9_semantic_desired_documents_v2 AS desired
          ON desired.source_snapshot_id = staged.source_snapshot_id
          AND desired.binding_hash = staged.binding_hash
          AND desired.document_id = staged.document_id
          AND desired.source_hash = staged.source_hash
        WHERE staged.source_snapshot_id = $1 AND staged.binding_hash = $2
      `, [sourceSnapshotId, bindingHash])
      const boundary = completeness.rows[0]
      const documentBoundary = staged.rows[0]
      const emptyBatchesValid = value.expected_batch_count === 0
        && boundary.batch_count === 0 && boundary.first_batch === null
        && boundary.last_batch === null && boundary.minimum_total === null
        && boundary.maximum_total === null && boundary.declared_documents === null
      const batchesValid = emptyBatchesValid || (
        boundary.batch_count === value.expected_batch_count && boundary.first_batch === 1
        && boundary.last_batch === value.expected_batch_count
        && boundary.minimum_total === value.expected_batch_count
        && boundary.maximum_total === value.expected_batch_count
        && boundary.declared_documents === value.expected_changed_count
      )
      if (manifest.rows.length !== 1
        || Number(manifest.rows[0].desired_count) !== value.expected_desired_count
        || !batchesValid || documentBoundary.document_count !== value.expected_changed_count
        || documentBoundary.desired_match_count !== value.expected_changed_count
        || (value.expected_changed_count > 0
          && documentBoundary.minimum_dimensions !== documentBoundary.maximum_dimensions)) {
        throw lifecycleError('K9_SEMANTIC_BATCHES_INCOMPLETE', 'Semantic staging is not complete enough to activate.')
      }
      const pointerScope = `catalog-embedding-active-v1:${bindingHash}`
      const materializationGeneration = head.rows[0].catalog_generation
      const activeValue = {
        projection_version: 1,
        binding_hash: bindingHash,
        source_generation: materializationGeneration,
        source_snapshot_id: sourceSnapshotId,
        manifest_hash: manifest.rows[0].manifest_hash,
      }
      const pointer = await client.query('SELECT value FROM poc_state WHERE scope = $1 FOR UPDATE', [pointerScope])
      const replay = pointer.rows.length === 1
        && canonicalStringify(pointer.rows[0].value) === canonicalStringify(activeValue)
      if (!replay) {
        const priorGeneration = pointer.rows[0]?.value?.binding_hash === bindingHash
          && typeof pointer.rows[0]?.value?.source_generation === 'string'
          ? pointer.rows[0].value.source_generation : null
        const resolution = await client.query(`
          SELECT count(*)::integer AS desired_count,
            count(*) FILTER (WHERE staged.document_id IS NOT NULL OR prior.asset_urn IS NOT NULL)::integer AS resolved_count,
            min(vector_dims(COALESCE(staged.embedding, prior.embedding)))::integer AS minimum_dimensions,
            max(vector_dims(COALESCE(staged.embedding, prior.embedding)))::integer AS maximum_dimensions
          FROM poc_k9_semantic_desired_documents_v2 AS desired
          LEFT JOIN poc_k9_semantic_staging_v2 AS staged
            ON staged.source_snapshot_id = desired.source_snapshot_id
            AND staged.binding_hash = desired.binding_hash
            AND staged.document_id = desired.document_id
          LEFT JOIN poc_catalog_embedding AS prior
            ON staged.document_id IS NULL AND prior.binding_hash = desired.binding_hash
            AND prior.asset_urn = desired.asset_urn AND prior.source_hash = desired.source_hash
            AND prior.source_generation = $3
          WHERE desired.source_snapshot_id = $1 AND desired.binding_hash = $2
        `, [sourceSnapshotId, bindingHash, priorGeneration])
        if (resolution.rows[0]?.desired_count !== value.expected_desired_count
          || resolution.rows[0]?.resolved_count !== value.expected_desired_count
          || (value.expected_desired_count > 0
            && (resolution.rows[0].minimum_dimensions === null
              || resolution.rows[0].minimum_dimensions !== resolution.rows[0].maximum_dimensions))) {
          throw lifecycleError('K9_SEMANTIC_VECTOR_RESOLUTION_INCOMPLETE', 'Every desired semantic document must resolve one dimension-consistent vector.')
        }
        if (priorGeneration === materializationGeneration) {
          const inactiveGeneration = computeSha256({
            source_snapshot_id: sourceSnapshotId,
            binding_hash: bindingHash,
            state: 'INACTIVE_REMOVED',
          })
          await client.query(`
            UPDATE poc_catalog_embedding AS prior
            SET source_generation = $3, updated_at = now()
            WHERE prior.binding_hash = $2 AND prior.source_generation = $4
              AND NOT EXISTS (
                SELECT 1 FROM poc_k9_semantic_desired_documents_v2 AS desired
                WHERE desired.source_snapshot_id = $1 AND desired.binding_hash = $2
                  AND desired.asset_urn = prior.asset_urn
              )
          `, [sourceSnapshotId, bindingHash, inactiveGeneration, priorGeneration])
        }
        await client.query(`
          INSERT INTO poc_catalog_embedding (
            binding_hash, asset_urn, source_hash, source_generation,
            content_text, metadata, embedding
          )
          SELECT desired.binding_hash, desired.asset_urn, desired.source_hash, $3,
            desired.content_text, desired.metadata, COALESCE(staged.embedding, prior.embedding)
          FROM poc_k9_semantic_desired_documents_v2 AS desired
          LEFT JOIN poc_k9_semantic_staging_v2 AS staged
            ON staged.source_snapshot_id = desired.source_snapshot_id
            AND staged.binding_hash = desired.binding_hash
            AND staged.document_id = desired.document_id
          LEFT JOIN poc_catalog_embedding AS prior
            ON staged.document_id IS NULL AND prior.binding_hash = desired.binding_hash
            AND prior.asset_urn = desired.asset_urn AND prior.source_hash = desired.source_hash
            AND prior.source_generation = $4
          WHERE desired.source_snapshot_id = $1 AND desired.binding_hash = $2
          ORDER BY desired.document_id
          ON CONFLICT (binding_hash, asset_urn) DO UPDATE SET
            source_hash = EXCLUDED.source_hash,
            source_generation = EXCLUDED.source_generation,
            content_text = EXCLUDED.content_text,
            metadata = EXCLUDED.metadata,
            embedding = EXCLUDED.embedding,
            updated_at = now()
          WHERE (poc_catalog_embedding.source_hash, poc_catalog_embedding.source_generation,
            poc_catalog_embedding.content_text, poc_catalog_embedding.metadata,
            poc_catalog_embedding.embedding::text)
            IS DISTINCT FROM (EXCLUDED.source_hash, EXCLUDED.source_generation,
              EXCLUDED.content_text, EXCLUDED.metadata, EXCLUDED.embedding::text)
        `, [sourceSnapshotId, bindingHash, materializationGeneration, priorGeneration])
        await client.query(`
          INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
          ON CONFLICT (scope) DO UPDATE
          SET value = EXCLUDED.value, version = poc_state.version + 1, updated_at = now()
        `, [pointerScope, JSON.stringify(activeValue)])
      }
      const materialized = await client.query(`
        SELECT count(*)::integer AS count
        FROM poc_catalog_embedding AS active
        JOIN poc_k9_semantic_desired_documents_v2 AS desired
          ON desired.source_snapshot_id = $1 AND desired.binding_hash = $2
          AND active.binding_hash = desired.binding_hash AND active.asset_urn = desired.asset_urn
          AND active.source_hash = desired.source_hash
          AND active.source_generation = $3
          AND active.content_text = desired.content_text
          AND active.metadata = desired.metadata
      `, [sourceSnapshotId, bindingHash, materializationGeneration])
      if (materialized.rows[0]?.count !== value.expected_desired_count) {
        throw lifecycleError('K9_SEMANTIC_MATERIALIZATION_INCOMPLETE', 'Semantic materialization did not match staged evidence.')
      }
      await client.query('COMMIT')
      return { activated: !replay, materialized: materialized.rows[0].count, active_pointer: activeValue }
    } catch (error) {
      await client.query('ROLLBACK').catch(() => undefined)
      throw error
    } finally {
      client.release()
    }
  }

  async function readLifecycle(lifecycleKeyValue = K9_LIFECYCLE_KEY_V2) {
    const lifecycleKey = boundedString(lifecycleKeyValue, 'lifecycleKey', 100)
    const pool = await requireDatabase()
    const result = await pool.query(`
      SELECT head.*, desired.snapshot AS desired_snapshot, active.snapshot AS active_snapshot
      FROM poc_k9_snapshot_lifecycle_v2 AS head
      JOIN poc_k9_source_snapshots_v2 AS desired
        ON desired.source_snapshot_id = head.desired_snapshot_id
      LEFT JOIN poc_k9_source_snapshots_v2 AS active
        ON active.source_snapshot_id = head.active_snapshot_id
      WHERE head.lifecycle_key = $1
    `, [lifecycleKey])
    if (!result.rows[0]) return null
    const desiredReceipts = await pool.query(`
      SELECT DISTINCT ON (projector) receipt
      FROM poc_k9_projector_receipts_v2
      WHERE source_snapshot_id = $1
      ORDER BY projector, attempt_number DESC, sequence DESC, receipt_id DESC
    `, [result.rows[0].desired_snapshot_id])
    const activeReadyReceipts = result.rows[0].active_snapshot_id === null
      ? { rows: [] }
      : await pool.query(`
        SELECT DISTINCT ON (projector) receipt
        FROM poc_k9_projector_receipts_v2
        WHERE source_snapshot_id = $1 AND status = 'READY'
        ORDER BY projector, attempt_number DESC, sequence DESC, receipt_id DESC
      `, [result.rows[0].active_snapshot_id])
    const payloadRows = await pool.query(`
      SELECT source_snapshot_id, payload_kind, payload
      FROM poc_k9_source_payloads_v2
      WHERE source_snapshot_id IN ($1, $2)
      ORDER BY source_snapshot_id, payload_kind
    `, [result.rows[0].desired_snapshot_id, result.rows[0].active_snapshot_id])
    const payloadsFor = (sourceSnapshotId) => Object.fromEntries(payloadRows.rows
      .filter((row) => row.source_snapshot_id === sourceSnapshotId)
      .map((row) => [row.payload_kind, row.payload]))
    return {
      ...result.rows[0],
      desired_projector_receipts: desiredReceipts.rows.map((row) => row.receipt),
      active_ready_projector_receipts: activeReadyReceipts.rows.map((row) => row.receipt),
      desired_source_payloads: payloadsFor(result.rows[0].desired_snapshot_id),
      active_source_payloads: result.rows[0].active_snapshot_id === null
        ? null : payloadsFor(result.rows[0].active_snapshot_id),
    }
  }

  return Object.freeze({
    setDesiredSnapshot,
    appendProjectorReceipt,
    promoteActiveSnapshot,
    persistSemanticDesiredManifest,
    stageSemanticBatch,
    activateSemanticSnapshot,
    readLifecycle,
  })
}
