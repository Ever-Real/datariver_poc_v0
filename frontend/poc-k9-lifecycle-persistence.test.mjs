/* global Buffer, structuredClone */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { URL } from 'node:url'

import { computeSha256 } from './poc-knowledge-k9-contracts.mjs'
import {
  K9_LIFECYCLE_SCHEMA_V6,
  K9_SOURCE_PAYLOAD_CHUNK_BYTES_V1,
  K9_SOURCE_PAYLOAD_CHUNK_INSERT_BATCH_V1,
  K9_SOURCE_PAYLOAD_CHUNK_SCHEMA_V8,
  K9_SOURCE_PERSISTENCE_SUBSTAGES_V2,
  K9_PROJECTOR_RECEIPT_CONTRACT_V2,
  adoptExactLegacyK9LifecycleV2,
  classifyK9SourcePersistenceFailureV2,
  encodeK9SourcePayloadChunksV2,
  normalizeK9ProjectorReceiptV2,
  normalizeK9SourcePayloadsV2,
  normalizeK9SourceSnapshotV2,
} from './poc-k9-lifecycle-persistence.mjs'

function sourcePayloads(overrides = {}) {
  return {
    inventory: { projection_version: 1, source_scope: 'scope-1', source_generation: '1'.repeat(64), items: [{ urn: 'dataset-a' }] },
    lineage: { direction: 'BOTH', nodes: [{ id: 'dataset-a' }], edges: [] },
    metadata: { collections: { table_nodes: [{ id: 'dataset-a' }] }, completeness_metadata: null },
    dangling_state: { dangling_reference_hash: null, dangling_table_refs: 0 },
    ...overrides,
  }
}

function sourceSnapshot(overrides = {}, payloads = sourcePayloads()) {
  const document = {
    contract_version: 'DATARIVER_K9_SOURCE_SNAPSHOT_V2',
    catalog_generation: '1'.repeat(64),
    datahub_version: 'v1.6.0',
    datahub_commit: 'provider-commit',
    authority_pin: {
      subject_id: 'k9-system',
      workspace_id: 'workspace-1',
      classification_ceiling: 'INTERNAL',
      projection_version: 2,
      policy_version: 'POC_DATAHUB_SEMANTIC_MODEL_V2',
      classification_policy_version: 1,
      authorization_generation: 7,
      authorization_fingerprint: 'f'.repeat(64),
    },
    inventory_projection_hash: computeSha256(payloads.inventory),
    lineage_hash: computeSha256(payloads.lineage),
    metadata_hash: computeSha256(payloads.metadata),
    dangling_state_hash: computeSha256(payloads.dangling_state),
    ...overrides,
  }
  const sourceSnapshotId = computeSha256(document)
  return {
    ...document,
    source_snapshot_id: sourceSnapshotId,
    source_fingerprint_id: sourceSnapshotId,
    metadata_source_profile: { contract: 'DATARIVER_K9_METADATA_SOURCE_PROFILE_V1' },
  }
}

function projectorReceipt(overrides = {}) {
  const document = {
    contract: K9_PROJECTOR_RECEIPT_CONTRACT_V2,
    source_snapshot_id: sourceSnapshot().source_snapshot_id,
    projector: 'SOURCE',
    status: 'PENDING',
    attempt_id: '6'.repeat(64),
    attempt_number: 1,
    sequence: 1,
    previous_receipt_id: null,
    idempotency_key_hash: '7'.repeat(64),
    progress: { phase: 'CAPTURE', completed_units: 0, total_units: 10 },
    diagnostic: null,
    output_pointer: null,
    output_hash: null,
    recorded_at: '2026-08-31T00:00:01.000Z',
    ...overrides,
  }
  return { ...document, receipt_id: computeSha256(document) }
}

test('accepts only the exact source-only snapshot V2 hash and authority binding', () => {
  const snapshot = sourceSnapshot()
  assert.deepEqual(normalizeK9SourceSnapshotV2(snapshot), snapshot)
  assert.throws(
    () => normalizeK9SourceSnapshotV2({ ...snapshot, metadata_hash: '9'.repeat(64) }),
    { code: 'K9_SOURCE_SNAPSHOT_HASH_MISMATCH' },
  )
  assert.throws(
    () => normalizeK9SourceSnapshotV2({
      ...snapshot,
      authority_pin: { ...snapshot.authority_pin, workspace_id: '' },
    }),
    { code: 'K9_SOURCE_SNAPSHOT_INVALID' },
  )
  assert.throws(
    () => normalizeK9SourceSnapshotV2({ ...snapshot, unknown: true }),
    { code: 'K9_SOURCE_SNAPSHOT_INVALID' },
  )
})

test('requires all immutable normalized source payloads and verifies their canonical hashes', () => {
  const payloads = sourcePayloads()
  const snapshot = sourceSnapshot({}, payloads)
  assert.deepEqual(normalizeK9SourcePayloadsV2(payloads, snapshot), {
    INVENTORY: payloads.inventory,
    LINEAGE: payloads.lineage,
    METADATA: payloads.metadata,
    DANGLING_STATE: payloads.dangling_state,
  })
  assert.throws(
    () => normalizeK9SourcePayloadsV2({ ...payloads, lineage: { nodes: [] } }, snapshot),
    { code: 'K9_SOURCE_PAYLOAD_HASH_MISMATCH' },
  )
  const incomplete = { ...payloads }
  delete incomplete.metadata
  assert.throws(() => normalizeK9SourcePayloadsV2(incomplete, snapshot), {
    code: 'K9_SOURCE_PAYLOADS_INVALID',
  })
  const noisy = structuredClone(payloads)
  noisy.inventory.items[0].observed_at = '2026-08-31T00:00:00.000Z'
  const noisySnapshot = sourceSnapshot({}, noisy)
  assert.throws(() => normalizeK9SourcePayloadsV2(noisy, noisySnapshot), {
    code: 'K9_INVENTORY_PAYLOAD_NOT_NORMALIZED',
  })
})

test('accepts bounded receipt states and rejects payload-shaped diagnostics or identity drift', () => {
  const pending = projectorReceipt()
  assert.deepEqual(normalizeK9ProjectorReceiptV2(pending), pending)
  const failedDocument = {
    ...pending,
    receipt_id: undefined,
    status: 'FAILED',
    progress: { phase: 'SOURCE_READ', completed_units: 4, total_units: 10 },
    diagnostic: { code: 'SOURCE_CONTRACT_FAILED', stage: 'SOURCE', detail_hash: '8'.repeat(64) },
  }
  delete failedDocument.receipt_id
  const failed = { ...failedDocument, receipt_id: computeSha256(failedDocument) }
  assert.deepEqual(normalizeK9ProjectorReceiptV2(failed), failed)
  assert.throws(() => normalizeK9ProjectorReceiptV2({
    ...failed,
    diagnostic: { ...failed.diagnostic, raw_payload: { secret: true } },
  }), { code: 'K9_PROJECTOR_RECEIPT_INVALID' })
  assert.throws(() => normalizeK9ProjectorReceiptV2({
    ...pending,
    progress: { phase: 'CAPTURE', completed_units: 11, total_units: 10 },
  }), { code: 'K9_PROJECTOR_RECEIPT_INVALID' })
  for (const field of ['asset_urn', 'content_text', 'embedding', 'provider_token']) {
    assert.throws(() => normalizeK9ProjectorReceiptV2({
      ...pending,
      progress: { ...pending.progress, [field]: field === 'embedding' ? [0.1] : 'raw' },
    }), { code: 'K9_PROJECTOR_RECEIPT_INVALID' })
  }
  const boundedSemantic = projectorReceipt({
    progress: {
      phase: 'SEMANTIC_BATCH', documents_processed: 10, documents_changed: 4,
      documents_materialized: 4, batch_size: 10, batch_total: 2, batch_number: 1,
      batch_requested_count: 10, batch_response_count: 10, batch_elapsed_ms: 45,
      provider_failure_class: null, vector_dimensions: 1536,
      lock_acquired: true, pointer_advanced: false,
    },
  })
  assert.deepEqual(normalizeK9ProjectorReceiptV2(boundedSemantic), boundedSemantic)
  const boundedGraphDocument = {
    ...pending,
    receipt_id: undefined,
    status: 'FAILED',
    diagnostic: {
      code: 'K9_GRAPH_PROJECTION_FAILED', stage: 'GRAPH_WRITE',
      failure_detail_code: 'NODE_BATCH_WRITE_FAILED', projector_id: 'LINEAGE',
      detail_hash: '9'.repeat(64), provider_failure_class: null,
      neo4j_http_class: 'HTTP_2XX', neo4j_error_class: 'CLIENT',
      batch_number: 1, batch_total: 2, batch_requested_nodes: 500,
      batch_requested_edges: 0, batch_written_nodes: 0, batch_written_edges: 0,
      query_family: 'NODE_BATCH_WRITE', transaction_phase: 'STAGING',
      expected_snapshot_id_present: true, active_snapshot_id_present: true,
      promotion_attempted: false, promotion_completed: false,
    },
    output_pointer: null,
    output_hash: null,
  }
  delete boundedGraphDocument.receipt_id
  const boundedGraph = {
    ...boundedGraphDocument,
    receipt_id: computeSha256(boundedGraphDocument),
  }
  assert.deepEqual(normalizeK9ProjectorReceiptV2(boundedGraph), boundedGraph)
  assert.throws(() => normalizeK9ProjectorReceiptV2({
    ...boundedGraph,
    diagnostic: { ...boundedGraph.diagnostic, raw_cypher: 'MATCH (n) RETURN n' },
  }), { code: 'K9_PROJECTOR_RECEIPT_INVALID' })
})

test('declares additive V6 tables with immutable payload triggers and no payload GC', () => {
  const schema = K9_LIFECYCLE_SCHEMA_V6.join('\n')
  for (const table of [
    'poc_k9_source_snapshots_v2',
    'poc_k9_source_payloads_v2',
    'poc_k9_semantic_manifests_v2',
    'poc_k9_semantic_desired_documents_v2',
    'poc_k9_semantic_batches_v2',
    'poc_k9_semantic_staging_v2',
    'poc_k9_projector_receipts_v2',
    'poc_k9_snapshot_lifecycle_v2',
  ]) assert.match(schema, new RegExp(`CREATE TABLE IF NOT EXISTS ${table}`))
  assert.match(schema, /BEFORE UPDATE OR DELETE ON poc_k9_source_snapshots_v2/)
  assert.match(schema, /BEFORE UPDATE OR DELETE ON poc_k9_source_payloads_v2/)
  assert.match(schema, /BEFORE UPDATE OR DELETE ON poc_k9_semantic_staging_v2/)
  assert.match(schema, /BEFORE UPDATE OR DELETE ON poc_k9_projector_receipts_v2/)
  assert.doesNotMatch(schema, /DROP TABLE|TRUNCATE TABLE|DELETE FROM poc_k9_/)
  assert.doesNotMatch(schema, /semantic_index_(?:binding_hash|generation|contract)|observed_at/)
  for (const field of [
    'authority_pin', 'inventory_projection_hash', 'lineage_hash', 'metadata_hash',
    'dangling_state_hash', 'catalog_generation', 'datahub_version', 'datahub_commit',
  ]) assert.match(schema, new RegExp(field))
  assert.match(schema, /status IN \('PENDING', 'RUNNING', 'READY', 'FAILED'\)/)
  assert.match(schema, /status <> 'READY'[\s\S]*active_snapshot_id IS NOT NULL[\s\S]*active_snapshot_id = desired_snapshot_id/)
  assert.match(schema, /desired_snapshot_id/)
  assert.match(schema, /active_snapshot_id/)
  assert.match(schema, /attempt_number DESC, sequence DESC/)
})

test('canonical 008 migration carries the runtime V6 identities and immutable receipt', () => {
  const migration = readFileSync(new URL(
    '../deploy/poc/postgres-init/008-poc-k9-lifecycle-v2.sql', import.meta.url,
  ), 'utf8')
  for (const table of [
    'poc_k9_source_snapshots_v2', 'poc_k9_source_payloads_v2',
    'poc_k9_semantic_manifests_v2', 'poc_k9_semantic_desired_documents_v2',
    'poc_k9_semantic_batches_v2', 'poc_k9_semantic_staging_v2',
    'poc_k9_projector_receipts_v2', 'poc_k9_snapshot_lifecycle_v2',
  ]) assert.match(migration, new RegExp(`CREATE TABLE IF NOT EXISTS ${table}`))
  assert.match(migration, /product-owned-schema-contract-v6/)
  assert.match(migration, /912b81ebb39e2a725dece61e22a52064e7f133c5206caa65e0ce6f17782c2dcc/)
  assert.doesNotMatch(migration, /DROP TABLE|TRUNCATE TABLE|DELETE FROM poc_k9_/)
})

test('declares one additive V8 chunk path with immutable evidence and a non-promotable staging pointer', () => {
  const schema = K9_SOURCE_PAYLOAD_CHUNK_SCHEMA_V8.join('\n')
  assert.match(schema, /CREATE TABLE IF NOT EXISTS poc_k9_source_payload_chunks_v2/)
  assert.match(schema, /CREATE TABLE IF NOT EXISTS poc_k9_source_staging_v2/)
  assert.match(schema, /FOREIGN KEY \(source_snapshot_id, payload_kind\)/)
  assert.match(schema, /octet_length\(payload_chunk\) = byte_count/)
  assert.match(schema, /BEFORE UPDATE OR DELETE ON poc_k9_source_payload_chunks_v2/)
  assert.doesNotMatch(schema, /DROP TABLE|TRUNCATE TABLE|DELETE FROM poc_k9_/)
  const migration = readFileSync(new URL(
    '../deploy/poc/postgres-init/010-poc-k9-source-payload-chunks.sql', import.meta.url,
  ), 'utf8')
  assert.match(migration, /DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V8/)
  assert.match(migration, /f5c1ef9ae3dee38422834d736df718793c5324fc0d7f553cbcc617739ffe6560/)
  assert.match(migration, /BEGIN;[\s\S]*COMMIT;/)
  assert.doesNotMatch(migration, /DROP TABLE|TRUNCATE TABLE|DELETE FROM poc_k9_/)
})

test('canonical source payload chunking is deterministic across and above the legacy 64 MiB boundary', () => {
  const legacyLimit = 67_108_864
  for (const targetBytes of [legacyLimit - 1, legacyLimit, legacyLimit + 1]) {
    const payload = { blob: 'x'.repeat(targetBytes - Buffer.byteLength('{"blob":""}', 'utf8')) }
    const payloadHash = computeSha256(payload)
    const first = encodeK9SourcePayloadChunksV2('METADATA', payload, payloadHash)
    const second = encodeK9SourcePayloadChunksV2('METADATA', payload, payloadHash)
    assert.equal(first.payload_bytes, targetBytes)
    assert.equal(first.manifest.payload_hash, payloadHash)
    assert.equal(first.manifest.chunk_count, Math.ceil(targetBytes / K9_SOURCE_PAYLOAD_CHUNK_BYTES_V1))
    assert.deepEqual(first.manifest, second.manifest)
    assert.deepEqual(first.chunks.map((item) => item.chunk_hash), second.chunks.map((item) => item.chunk_hash))
    assert.ok(K9_SOURCE_PAYLOAD_CHUNK_INSERT_BATCH_V1 * K9_SOURCE_PAYLOAD_CHUNK_BYTES_V1 <= 16_777_216)
  }
})

test('classifies every persistence substage with only bounded payload and SQL evidence', () => {
  for (const substage of K9_SOURCE_PERSISTENCE_SUBSTAGES_V2) {
    const diagnostic = classifyK9SourcePersistenceFailureV2(
      Object.assign(new Error('raw SQL and urn:li:dataset:must-not-survive'), {
        code: '23514', constraint: 'ck_poc_k9_source_payload_chunk_v2_bounds',
        detail: 'private row', query: 'SELECT secret',
      }),
      {
        substage, payloadKind: 'METADATA', payloadBytes: 67_108_865,
        configuredLimitBytes: 1_073_741_824,
      },
    )
    assert.deepEqual(diagnostic, {
      code: 'K9_V2_SOURCE_RECEIPT_PERSISTENCE_FAILED',
      stage: 'SOURCE_RECEIPT',
      failure_detail_code: 'K9_SOURCE_PERSISTENCE_SQL_FAILED',
      persistence_substage: substage,
      payload_kind: 'METADATA',
      payload_bytes: 67_108_865,
      configured_limit_bytes: 1_073_741_824,
      sqlstate_class: 'PAYLOAD_CONSTRAINT',
      constraint_name: 'CK_POC_K9_SOURCE_PAYLOAD_CHUNK_V2_BOUNDS',
      retryable: true,
    })
    assert.equal(JSON.stringify(diagnostic).includes('urn:li:'), false)
    assert.equal(JSON.stringify(diagnostic).includes('SELECT'), false)
  }
  const unknown = classifyK9SourcePersistenceFailureV2(
    Object.assign(new Error('private'), { code: 'SECRET_TOKEN', constraint: 'private_constraint' }),
    { substage: 'PRIVATE_STAGE', payloadKind: 'PRIVATE', payloadBytes: -1 },
  )
  assert.equal(unknown.failure_detail_code, 'K9_SOURCE_PERSISTENCE_UNKNOWN')
  assert.equal(unknown.persistence_substage, 'SOURCE_RECEIPT_VALIDATE')
  assert.equal(unknown.payload_kind, 'NONE')
  assert.equal(unknown.payload_bytes, 0)
  assert.equal(unknown.constraint_name, 'NONE')
  const foreignKey = classifyK9SourcePersistenceFailureV2(
    Object.assign(new Error('private'), {
      code: '23503', constraint: 'poc_k9_source_staging_v2_source_snapshot_id_fkey',
    }),
    { substage: 'SOURCE_EVIDENCE_STAGE' },
  )
  assert.equal(foreignKey.sqlstate_class, 'FK')
  assert.equal(
    foreignKey.constraint_name,
    'POC_K9_SOURCE_STAGING_V2_SOURCE_SNAPSHOT_ID_FKEY',
  )
  const resanitized = classifyK9SourcePersistenceFailureV2({ diagnostic: {
    code: 'K9_V2_SOURCE_RECEIPT_PERSISTENCE_FAILED', stage: 'SOURCE_RECEIPT',
    failure_detail_code: 'SECRET_TOKEN', persistence_substage: 'PRIVATE_STAGE',
    payload_kind: 'PRIVATE', payload_bytes: -1, configured_limit_bytes: -1,
    sqlstate_class: 'PRIVATE', constraint_name: 'PRIVATE', raw_payload: 'must-not-survive',
  } })
  assert.equal(resanitized.failure_detail_code, 'K9_SOURCE_PERSISTENCE_UNKNOWN')
  assert.equal(resanitized.persistence_substage, 'SOURCE_RECEIPT_VALIDATE')
  assert.equal(JSON.stringify(resanitized).includes('raw_payload'), false)
})

test('preserves every legacy pointer and records an immutable new-snapshot adoption decision', async () => {
  const statements = []
  const client = {
    async query(sql, parameters = []) {
      const normalized = String(sql).replace(/\s+/g, ' ').trim()
      statements.push(normalized)
      if (normalized.startsWith('SELECT value, version FROM poc_state')) return { rows: [] }
      if (normalized.startsWith('SELECT count(*)::integer AS count')) return { rows: [{ count: 0 }] }
      if (normalized.startsWith('SELECT (SELECT count(*)::integer')) {
        return { rows: [{ policy_count: 2, run_count: 9, semantic_pointer_count: 1 }] }
      }
      if (normalized.startsWith('INSERT INTO poc_state')) {
        return { rows: [{ value: JSON.parse(parameters[1]), version: 1 }] }
      }
      throw new Error(`Unexpected SQL: ${normalized}`)
    },
  }
  assert.deepEqual(await adoptExactLegacyK9LifecycleV2(client), { state: 'NEW_SNAPSHOT_REQUIRED' })
  assert.equal(statements.filter((sql) => /^INSERT INTO poc_state/.test(sql)).length, 1)
  assert.equal(statements.some((sql) => /^(?:UPDATE|DELETE)/.test(sql)), false)
})
