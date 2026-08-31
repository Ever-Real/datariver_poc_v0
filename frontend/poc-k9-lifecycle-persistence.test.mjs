/* global structuredClone */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { URL } from 'node:url'

import { computeSha256 } from './poc-knowledge-k9-contracts.mjs'
import {
  K9_LIFECYCLE_SCHEMA_V6,
  K9_PROJECTOR_RECEIPT_CONTRACT_V2,
  adoptExactLegacyK9LifecycleV2,
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
