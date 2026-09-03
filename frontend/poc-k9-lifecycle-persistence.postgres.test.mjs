/* global Buffer */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import process from 'node:process'
import test from 'node:test'
import { URL } from 'node:url'
import pg from 'pg'

import { canonicalStringify, computeSha256 } from './poc-knowledge-k9-contracts.mjs'
import {
  createK9V2DurableProjector,
  createK9V2LifecycleReceiptPort,
} from './poc-k9-lifecycle-runtime.mjs'
import { createK9V2SemanticLifecycleProjector } from './poc-k9-semantic-runtime.mjs'
import { createPocK9V2RefreshTask } from './poc-k9-v2-refresh.mjs'
import { createPocK9SourceCaptureTask } from './poc-k9-scheduler.mjs'
import { createK9LifecyclePersistenceV2 } from './poc-k9-lifecycle-persistence.mjs'
import { pocPostgresTestSkipReason, withDisposablePocPostgres } from './poc-postgres-test-fixture.mjs'
import { createPocStateStore } from './poc-state-store.mjs'

const { Pool } = pg
const migrationNames = [
  '001-poc-state.sql',
  '002-poc-knowledge-ingestion.sql',
  '003-poc-k9-managed-graphs.sql',
  '004-poc-local-security-events.sql',
  '005-poc-mcp-read-receipts.sql',
  '006-poc-local-credential-provision-audit.sql',
  '007-poc-chat-discovery.sql',
]

async function withIntegrityRequired(action) {
  const previous = process.env.POC_POSTGRES_SCHEMA_INTEGRITY_REQUIRED
  process.env.POC_POSTGRES_SCHEMA_INTEGRITY_REQUIRED = 'true'
  try {
    return await action()
  } finally {
    if (previous === undefined) delete process.env.POC_POSTGRES_SCHEMA_INTEGRITY_REQUIRED
    else process.env.POC_POSTGRES_SCHEMA_INTEGRITY_REQUIRED = previous
  }
}

function sourceEnvelope(generation = '1', identityVariant = 'provider-commit') {
  const sourceGeneration = generation.repeat(64)
  const source_payloads = {
    inventory: { projection_version: 1, source_scope: 'scope-1', source_generation: sourceGeneration, items: [{ urn: 'dataset-a' }] },
    lineage: { direction: 'BOTH', depth: 1, truncated: false, nodes: [{ id: 'dataset-a' }], column_nodes: [], edges: [], completeness_metadata: null },
    metadata: { collections: { table_nodes: [{ id: 'dataset-a' }] }, completeness_metadata: null, raw_assignment_reference_hash: null },
    dangling_state: { dangling_reference_hash: null, dangling_table_refs: 0 },
  }
  const identity = {
    contract_version: 'DATARIVER_K9_SOURCE_SNAPSHOT_V2',
    catalog_generation: sourceGeneration,
    datahub_version: 'v1.6.0',
    datahub_commit: identityVariant,
    authority_pin: {
      subject_id: 'k9-system', workspace_id: 'workspace-1', classification_ceiling: 'INTERNAL',
      projection_version: 2, policy_version: 'POC_DATAHUB_SEMANTIC_MODEL_V2',
      classification_policy_version: 1, authorization_generation: 7,
      authorization_fingerprint: 'f'.repeat(64),
    },
    inventory_projection_hash: computeSha256(source_payloads.inventory),
    lineage_hash: computeSha256(source_payloads.lineage),
    metadata_hash: computeSha256(source_payloads.metadata),
    dangling_state_hash: computeSha256(source_payloads.dangling_state),
  }
  const sourceSnapshotId = computeSha256(identity)
  return {
    snapshot: {
      ...identity,
      source_snapshot_id: sourceSnapshotId,
      source_fingerprint_id: sourceSnapshotId,
      metadata_source_profile: { contract: 'DATARIVER_K9_METADATA_SOURCE_PROFILE_V1' },
    },
    source_payloads,
  }
}

function prepScaleLargeSourceEnvelope() {
  const base = sourceEnvelope('8', 'provider-prep-scale')
  const tableCount = 1_908
  const columnsPerTable = 50
  const source_payloads = {
    ...base.source_payloads,
    metadata: {
      collections: {
        table_nodes: Array.from({ length: tableCount }, (_value, table) => ({
          id: `dataset-${String(table).padStart(5, '0')}`,
        })),
        column_nodes: Array.from({ length: tableCount * columnsPerTable }, (_value, ordinal) => ({
          id: `column-${String(ordinal).padStart(7, '0')}`,
          parent_id: `dataset-${String(Math.floor(ordinal / columnsPerTable)).padStart(5, '0')}`,
          description: `normalized-${String(ordinal).padStart(7, '0')}-${'x'.repeat(620)}`,
        })),
      },
      completeness_metadata: { source_scope: 'K9', table_count: tableCount },
      raw_assignment_reference_hash: null,
    },
  }
  const identity = {
    contract_version: base.snapshot.contract_version,
    catalog_generation: base.snapshot.catalog_generation,
    datahub_version: base.snapshot.datahub_version,
    datahub_commit: base.snapshot.datahub_commit,
    authority_pin: base.snapshot.authority_pin,
    inventory_projection_hash: computeSha256(source_payloads.inventory),
    lineage_hash: computeSha256(source_payloads.lineage),
    metadata_hash: computeSha256(source_payloads.metadata),
    dangling_state_hash: computeSha256(source_payloads.dangling_state),
  }
  const sourceSnapshotId = computeSha256(identity)
  return {
    snapshot: {
      ...identity,
      source_snapshot_id: sourceSnapshotId,
      source_fingerprint_id: sourceSnapshotId,
      metadata_source_profile: { contract: 'DATARIVER_K9_METADATA_SOURCE_PROFILE_V1' },
    },
    source_payloads,
  }
}

function receipt({ snapshotId, projector, status, attemptNumber, sequence, previous = null }) {
  const attemptId = computeSha256({ projector, attemptNumber })
  const document = {
    contract: 'DATARIVER_K9_PROJECTOR_RECEIPT_V2',
    source_snapshot_id: snapshotId,
    projector,
    status,
    attempt_id: attemptId,
    attempt_number: attemptNumber,
    sequence,
    previous_receipt_id: previous?.receipt_id ?? null,
    idempotency_key_hash: computeSha256({ projector, attemptNumber, sequence }),
    progress: { phase: `${projector}_PROJECT`, completed_units: status === 'PENDING' ? 0 : status === 'RUNNING' ? 5 : 10, total_units: 10 },
    diagnostic: status === 'FAILED'
      ? { code: `${projector}_FAILED`, stage: projector, detail_hash: computeSha256({ projector, failed: true }) }
      : null,
    output_pointer: status === 'READY' ? `k9://${projector.toLowerCase()}/${snapshotId}` : null,
    output_hash: status === 'READY' ? computeSha256({ projector, snapshotId }) : null,
    recorded_at: `2026-08-31T00:${String(attemptNumber).padStart(2, '0')}:${String(sequence).padStart(2, '0')}.000Z`,
  }
  return { ...document, receipt_id: computeSha256(document) }
}

function semanticDesiredDocument(ordinal, sourceVariant = 'stable') {
  return {
    document_id: `urn:li:dataset:(urn:li:dataPlatform:postgres,k9.table_${ordinal},PROD)`,
    source_hash: computeSha256({ ordinal, sourceVariant }),
    content_text: `normalized semantic document ${ordinal}`,
    metadata: { ordinal, normalized: true },
  }
}

function changedVector(document, ordinal) {
  return {
    document_id: document.document_id,
    source_hash: document.source_hash,
    embedding: [ordinal / 10, ordinal / 20],
  }
}

function prepShapedSourceReceipt(documentCount = 2_003) {
  const sourceGeneration = '6'.repeat(64)
  const source_payloads = {
    inventory: {
      projection_version: 1,
      source_scope: 'authorized-current-tables',
      source_generation: sourceGeneration,
      items: Array.from({ length: documentCount }, (_value, index) => ({
        id: `urn:li:dataset:(urn:li:dataPlatform:postgres,prep.table_${String(index).padStart(5, '0')},PROD)`,
        name: `table_${String(index).padStart(5, '0')}`,
      })),
    },
    lineage: { nodes: [], edges: [], completeness_metadata: { source_scope: 'K9' } },
    metadata: {
      collections: {},
      completeness_metadata: { source_scope: 'K9' },
      source_profile: {
        contract: 'DATARIVER_K9_METADATA_SOURCE_PROFILE_V1',
        glossary_entities_fetched: 1_570,
        direct_resolution: {
          total_unique_terms: 1_486,
          dangling_unique_terms: 1_486,
          batch_total: 6,
        },
        assignments: { dangling_assignment_references: 75_431 },
      },
    },
    dangling_state: {
      dangling_unique_terms: 1_486,
      dangling_assignment_references: 75_431,
    },
  }
  const identity = {
    contract_version: 'DATARIVER_K9_SOURCE_SNAPSHOT_V2',
    catalog_generation: sourceGeneration,
    datahub_version: 'v1.6.0rc1',
    datahub_commit: 'provider-compatible-fixture',
    authority_pin: {
      subject_id: 'k9-system', workspace_id: 'workspace-1', classification_ceiling: 'INTERNAL',
      projection_version: 2, policy_version: 'POC_DATAHUB_SEMANTIC_MODEL_V2',
      classification_policy_version: 1, authorization_generation: 7,
      authorization_fingerprint: 'f'.repeat(64),
    },
    inventory_projection_hash: computeSha256(source_payloads.inventory),
    lineage_hash: computeSha256(source_payloads.lineage),
    metadata_hash: computeSha256(source_payloads.metadata),
    dangling_state_hash: computeSha256(source_payloads.dangling_state),
  }
  const sourceSnapshotId = computeSha256(identity)
  return Object.freeze({
    status: 'READY',
    source_snapshot_id: sourceSnapshotId,
    source_snapshot: Object.freeze({
      ...identity,
      source_snapshot_id: sourceSnapshotId,
      source_fingerprint_id: sourceSnapshotId,
      metadata_source_profile: source_payloads.metadata.source_profile,
    }),
    source_payloads: Object.freeze(source_payloads),
  })
}

async function appendAttempt(store, snapshotId, projector, attemptNumber, terminalStatus, previousAttempt = null) {
  const pending = receipt({ snapshotId, projector, status: 'PENDING', attemptNumber, sequence: 1, previous: previousAttempt })
  const running = receipt({ snapshotId, projector, status: 'RUNNING', attemptNumber, sequence: 2, previous: pending })
  const terminal = receipt({ snapshotId, projector, status: terminalStatus, attemptNumber, sequence: 3, previous: running })
  await store.appendK9ProjectorReceiptV2(pending)
  await store.appendK9ProjectorReceiptV2(running)
  await store.appendK9ProjectorReceiptV2(terminal)
  return terminal
}

test('fresh V8 persists replayable source payloads, retries FAILED attempts, and separates desired from active receipts', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('k9_v2_lifecycle', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 3 })
  await pool.query('CREATE EXTENSION IF NOT EXISTS vector')
  await withIntegrityRequired(async () => {
    const store = createPocStateStore({ databasePool: pool })
    try {
      const first = sourceEnvelope('1')
      const created = await store.setK9DesiredSourceSnapshotV2(first)
      assert.equal(created.created, true)
      assert.equal(created.payloadsCreated, true)
      await assert.rejects(pool.query(`
        UPDATE poc_k9_snapshot_lifecycle_v2
        SET status = 'READY', active_snapshot_id = NULL
        WHERE lifecycle_key = 'managed-k9-v2'
      `), /ck_poc_k9_snapshot_lifecycle_v2_state/)
      assert.deepEqual(await store.setK9DesiredSourceSnapshotV2(first), {
        ...created, created: false, payloadsCreated: false,
      })

      const failed = await appendAttempt(store, first.snapshot.source_snapshot_id, 'SOURCE', 1, 'FAILED')
      const skippedAttempt = receipt({
        snapshotId: first.snapshot.source_snapshot_id,
        projector: 'SOURCE', status: 'PENDING', attemptNumber: 3, sequence: 1, previous: failed,
      })
      await assert.rejects(store.appendK9ProjectorReceiptV2(skippedAttempt), {
        code: 'K9_PROJECTOR_TRANSITION_INVALID',
      })

      await appendAttempt(store, first.snapshot.source_snapshot_id, 'LINEAGE', 1, 'READY')
      assert.equal((await store.readK9SnapshotLifecycleV2()).status, 'FAILED')
      await appendAttempt(store, first.snapshot.source_snapshot_id, 'SOURCE', 2, 'READY', failed)
      await appendAttempt(store, first.snapshot.source_snapshot_id, 'METADATA', 1, 'READY')
      await appendAttempt(store, first.snapshot.source_snapshot_id, 'SEMANTIC', 1, 'READY')

      const ready = await store.readK9SnapshotLifecycleV2()
      assert.equal(ready.desired_projector_receipts.length, 4)
      assert.equal(ready.desired_projector_receipts.find((item) => item.projector === 'SOURCE').attempt_number, 2)
      assert.deepEqual(ready.active_ready_projector_receipts, [])
      assert.deepEqual(ready.desired_source_payloads.INVENTORY, first.source_payloads.inventory)
      await store.promoteK9ActiveSourceSnapshotV2({
        sourceSnapshotId: first.snapshot.source_snapshot_id,
        expectedVersion: Number(ready.version),
      })

      const second = sourceEnvelope('2')
      await store.setK9DesiredSourceSnapshotV2(second)
      const split = await store.readK9SnapshotLifecycleV2()
      assert.equal(split.desired_snapshot_id, second.snapshot.source_snapshot_id)
      assert.equal(split.active_snapshot_id, first.snapshot.source_snapshot_id)
      assert.deepEqual(split.desired_projector_receipts, [])
      assert.equal(split.active_ready_projector_receipts.length, 4)
      assert.deepEqual(split.desired_source_payloads.INVENTORY, second.source_payloads.inventory)
      assert.deepEqual(split.active_source_payloads.INVENTORY, first.source_payloads.inventory)

      await assert.rejects(pool.query(
        'DELETE FROM poc_k9_source_payloads_v2 WHERE source_snapshot_id = $1',
        [first.snapshot.source_snapshot_id],
      ))
      assert.equal((await pool.query(
        'SELECT count(*)::integer AS count FROM poc_k9_source_payloads_v2',
      )).rows[0].count, 8)
    } finally {
      await store.close()
    }
  })
  await pool.end()
}))

test('V7 monolithic source evidence remains readable after additive V8 migration and rejects mixed chunk evidence', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('k9_v8_legacy_payload_read', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 3 })
  await pool.query('CREATE EXTENSION IF NOT EXISTS vector')
  for (const migrationName of [...migrationNames, '008-poc-k9-lifecycle-v2.sql', '009-poc-change-history-retention-gap.sql']) {
    await pool.query(readFileSync(new URL(
      `../deploy/poc/postgres-init/${migrationName}`, import.meta.url,
    ), 'utf8'))
  }
  const source = sourceEnvelope('7', 'provider-v7-monolith')
  await pool.query(`
    INSERT INTO poc_k9_source_snapshots_v2 (
      source_snapshot_id, contract_version, source_fingerprint_id, catalog_generation,
      datahub_version, datahub_commit, authority_pin, inventory_projection_hash,
      lineage_hash, metadata_hash, dangling_state_hash, snapshot
    ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11,$12::jsonb)
  `, [
    source.snapshot.source_snapshot_id,
    source.snapshot.contract_version,
    source.snapshot.source_fingerprint_id,
    source.snapshot.catalog_generation,
    source.snapshot.datahub_version,
    source.snapshot.datahub_commit,
    JSON.stringify(source.snapshot.authority_pin),
    source.snapshot.inventory_projection_hash,
    source.snapshot.lineage_hash,
    source.snapshot.metadata_hash,
    source.snapshot.dangling_state_hash,
    JSON.stringify(source.snapshot),
  ])
  for (const [kind, payload, payloadHash] of [
    ['INVENTORY', source.source_payloads.inventory, source.snapshot.inventory_projection_hash],
    ['LINEAGE', source.source_payloads.lineage, source.snapshot.lineage_hash],
    ['METADATA', source.source_payloads.metadata, source.snapshot.metadata_hash],
    ['DANGLING_STATE', source.source_payloads.dangling_state, source.snapshot.dangling_state_hash],
  ]) {
    await pool.query(`
      INSERT INTO poc_k9_source_payloads_v2 (
        source_snapshot_id, payload_kind, payload_hash, payload
      ) VALUES ($1, $2, $3, $4::jsonb)
    `, [source.snapshot.source_snapshot_id, kind, payloadHash, JSON.stringify(payload)])
  }
  await pool.query(`
    INSERT INTO poc_k9_snapshot_lifecycle_v2 (
      lifecycle_key, desired_snapshot_id, status
    ) VALUES ('managed-k9-v2', $1, 'PENDING')
  `, [source.snapshot.source_snapshot_id])
  await pool.query(readFileSync(new URL(
    '../deploy/poc/postgres-init/010-poc-k9-source-payload-chunks.sql', import.meta.url,
  ), 'utf8'))

  await withIntegrityRequired(async () => {
    const store = createPocStateStore({ databasePool: pool })
    try {
      const lifecycle = await store.readK9SnapshotLifecycleV2()
      assert.equal(lifecycle.desired_snapshot_id, source.snapshot.source_snapshot_id)
      assert.deepEqual(lifecycle.desired_source_payloads.INVENTORY, source.source_payloads.inventory)
      assert.deepEqual(lifecycle.desired_source_payloads.METADATA, source.source_payloads.metadata)
      assert.equal((await pool.query(
        'SELECT count(*)::integer AS count FROM poc_k9_source_payload_chunks_v2',
      )).rows[0].count, 0)

      await pool.query(`
        INSERT INTO poc_k9_source_payload_chunks_v2 (
          source_snapshot_id, payload_kind, chunk_number, chunk_count,
          payload_hash, chunk_hash, byte_count, payload_chunk
        ) VALUES ($1, 'INVENTORY', 1, 1, $2, $3, 1, decode('78', 'hex'))
      `, [
        source.snapshot.source_snapshot_id,
        source.snapshot.inventory_projection_hash,
        '0'.repeat(64),
      ])
      await assert.rejects(store.readK9SnapshotLifecycleV2(), {
        code: 'K9_SOURCE_PAYLOAD_READBACK_MISMATCH',
      })
    } finally {
      await store.close()
    }
  })
  await pool.end()
}))

test('PREP-shaped metadata above legacy 64 MiB persists as verified chunks and resumes after head failure without recapture', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('k9_v8_large_source_resume', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 3 })
  await pool.query('CREATE EXTENSION IF NOT EXISTS vector')
  await withIntegrityRequired(async () => {
    const store = createPocStateStore({ databasePool: pool })
    try {
      assert.equal(await store.readK9SnapshotLifecycleV2(), null)
      const source = prepScaleLargeSourceEnvelope()
      const metadataBytes = Buffer.byteLength(canonicalStringify(source.source_payloads.metadata), 'utf8')
      assert.ok(metadataBytes > 67_108_864)
      await pool.query(`
        CREATE FUNCTION poc_test_reject_k9_source_consume() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.status = 'CONSUMED' THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              CONSTRAINT = 'ck_poc_k9_source_staging_v2_state',
              MESSAGE = 'synthetic private consume failure';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_poc_test_reject_k9_source_consume
          BEFORE UPDATE ON poc_k9_source_staging_v2
          FOR EACH ROW EXECUTE FUNCTION poc_test_reject_k9_source_consume();
      `)
      await assert.rejects(store.setK9DesiredSourceSnapshotV2(source), (error) => {
        assert.equal(error.diagnostic.code, 'K9_V2_SOURCE_RECEIPT_PERSISTENCE_FAILED')
        assert.equal(error.diagnostic.persistence_substage, 'LIFECYCLE_HEAD_WRITE')
        assert.equal(error.diagnostic.sqlstate_class, 'CHECK_CONSTRAINT')
        assert.equal(error.diagnostic.constraint_name, 'CK_POC_K9_SOURCE_STAGING_V2_STATE')
        assert.equal(JSON.stringify(error.diagnostic).includes('synthetic private'), false)
        return true
      })
      assert.equal((await pool.query(
        'SELECT count(*)::integer AS count FROM poc_k9_snapshot_lifecycle_v2',
      )).rows[0].count, 0)
      assert.equal((await pool.query(
        "SELECT status FROM poc_k9_source_staging_v2 WHERE lifecycle_key = 'managed-k9-v2'",
      )).rows[0].status, 'VERIFIED')
      const metadataRow = (await pool.query(`
        SELECT payload FROM poc_k9_source_payloads_v2
        WHERE source_snapshot_id = $1 AND payload_kind = 'METADATA'
      `, [source.snapshot.source_snapshot_id])).rows[0]
      assert.equal(metadataRow.payload.contract, 'DATARIVER_K9_SOURCE_PAYLOAD_MANIFEST_V1')
      assert.equal(metadataRow.payload.total_bytes, metadataBytes)
      assert.ok(metadataRow.payload.chunk_count > 64)
      assert.equal((await pool.query(`
        SELECT count(*)::integer AS count FROM poc_k9_source_payload_chunks_v2
        WHERE source_snapshot_id = $1 AND payload_kind = 'METADATA'
      `, [source.snapshot.source_snapshot_id])).rows[0].count, metadataRow.payload.chunk_count)

      const staged = await store.readK9StagedSourceEvidenceV2()
      assert.equal(staged.status, 'PENDING')
      assert.equal(staged.source_snapshot_id, source.snapshot.source_snapshot_id)
      assert.equal(computeSha256(staged.source_payloads.metadata), source.snapshot.metadata_hash)

      const providerCalls = { inventory: 0, lineage: 0, metadata: 0, runtime: 0 }
      const resumeCapture = createPocK9SourceCaptureTask({
        resolveAuthContext: async () => ({}),
        currentInventory: async () => { providerCalls.inventory += 1; return [] },
        inventoryProjection: async () => ({}),
        collectLineage: async () => { providerCalls.lineage += 1; return {} },
        collectMetadata: async () => { providerCalls.metadata += 1; return {} },
        runtimeIdentity: async () => { providerCalls.runtime += 1; return {} },
        buildSourceCapture: () => { throw new Error('must not rebuild source') },
      })
      const resumedSource = await resumeCapture({ currentReceipt: staged })
      assert.equal(resumedSource.status, 'READY')
      assert.deepEqual(providerCalls, { inventory: 0, lineage: 0, metadata: 0, runtime: 0 })

      await pool.query(`
        DROP TRIGGER trg_poc_test_reject_k9_source_consume ON poc_k9_source_staging_v2;
        DROP FUNCTION poc_test_reject_k9_source_consume();
      `)
      const replay = await store.setK9DesiredSourceSnapshotV2({
        snapshot: resumedSource.source_snapshot,
        source_payloads: resumedSource.source_payloads,
      })
      assert.equal(replay.created, false)
      assert.equal(replay.payloadsCreated, false)
      assert.equal((await pool.query(
        "SELECT status FROM poc_k9_source_staging_v2 WHERE lifecycle_key = 'managed-k9-v2'",
      )).rows[0].status, 'CONSUMED')
      const lifecycle = await store.readK9SnapshotLifecycleV2()
      assert.equal(lifecycle.desired_snapshot_id, source.snapshot.source_snapshot_id)
      assert.equal(computeSha256(lifecycle.desired_source_payloads.METADATA), source.snapshot.metadata_hash)
    } finally {
      await store.close()
    }
  })
  await pool.end()
}))

test('phase-one persistence failures release the PostgreSQL client exactly once and retain commit-uncertain evidence', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('k9_v8_phase_one_release', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 3 })
  await pool.query('CREATE EXTENSION IF NOT EXISTS vector')
  await withIntegrityRequired(async () => {
    const store = createPocStateStore({ databasePool: pool })
    try {
      await store.readK9SnapshotLifecycleV2()
      const source = sourceEnvelope('9', 'provider-phase-one-release')

      async function persistenceWithFault(fault) {
        let releaseCount = 0
        const persistence = createK9LifecyclePersistenceV2({
          requireDatabase: async () => ({
            async connect() {
              const client = await pool.connect()
              const query = client.query.bind(client)
              const release = client.release.bind(client)
              let released = false
              return {
                async query(statement, values) {
                  const sql = typeof statement === 'string' ? statement : statement?.text || ''
                  return fault({ query, sql, statement, values })
                },
                release() {
                  assert.equal(released, false)
                  released = true
                  releaseCount += 1
                  release()
                },
              }
            },
          }),
        })
        return { persistence, releaseCount: () => releaseCount }
      }

      const insertFailure = await persistenceWithFault(async ({ query, sql, statement, values }) => {
        if (/INSERT INTO poc_k9_source_snapshots_v2/u.test(sql)) {
          throw Object.assign(new Error('private synthetic insert failure'), {
            code: '23514', constraint: 'ck_poc_k9_source_snapshot_v2_payload',
          })
        }
        return query(statement, values)
      })
      await assert.rejects(insertFailure.persistence.setDesiredSnapshot(source), (error) => {
        assert.equal(error.diagnostic.persistence_substage, 'SNAPSHOT_INSERT')
        assert.equal(error.diagnostic.sqlstate_class, 'SNAPSHOT_CONSTRAINT')
        return true
      })
      assert.equal(insertFailure.releaseCount(), 1)

      let firstCommit = true
      const uncertainCommit = await persistenceWithFault(async ({ query, sql, statement, values }) => {
        if (sql === 'COMMIT' && firstCommit) {
          firstCommit = false
          await query(statement, values)
          throw Object.assign(new Error('private synthetic lost commit acknowledgement'), { code: '08006' })
        }
        return query(statement, values)
      })
      await assert.rejects(uncertainCommit.persistence.setDesiredSnapshot(source), (error) => {
        assert.equal(error.diagnostic.persistence_substage, 'TRANSACTION_COMMIT')
        assert.equal(error.diagnostic.sqlstate_class, 'CONNECTION')
        assert.equal(JSON.stringify(error.diagnostic).includes('private synthetic'), false)
        return true
      })
      assert.equal(uncertainCommit.releaseCount(), 1)
      assert.equal((await pool.query(
        "SELECT status FROM poc_k9_source_staging_v2 WHERE lifecycle_key = 'managed-k9-v2'",
      )).rows[0].status, 'VERIFIED')
      assert.equal((await pool.query(
        'SELECT count(*)::integer AS count FROM poc_k9_snapshot_lifecycle_v2',
      )).rows[0].count, 0)
    } finally {
      await store.close()
    }
  })
  await pool.end()
}))

test('concurrent exact source persistence is idempotent and creates one consumed evidence state', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('k9_v8_concurrent_exact_source', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 4 })
  await pool.query('CREATE EXTENSION IF NOT EXISTS vector')
  await withIntegrityRequired(async () => {
    const store = createPocStateStore({ databasePool: pool })
    try {
      await store.readK9SnapshotLifecycleV2()
      const source = sourceEnvelope('0', 'provider-concurrent-exact')
      const results = await Promise.all([
        store.setK9DesiredSourceSnapshotV2(source),
        store.setK9DesiredSourceSnapshotV2(source),
      ])
      assert.equal(results.length, 2)
      assert.equal(results.every((result) => (
        result.sourceSnapshotId === source.snapshot.source_snapshot_id
      )), true)
      const lifecycle = await store.readK9SnapshotLifecycleV2()
      assert.equal(lifecycle.desired_snapshot_id, source.snapshot.source_snapshot_id)
      assert.equal((await pool.query(
        'SELECT count(*)::integer AS count FROM poc_k9_source_snapshots_v2',
      )).rows[0].count, 1)
      assert.equal((await pool.query(
        'SELECT count(*)::integer AS count FROM poc_k9_source_payloads_v2',
      )).rows[0].count, 4)
      const staged = (await pool.query(
        "SELECT status, version FROM poc_k9_source_staging_v2 WHERE lifecycle_key = 'managed-k9-v2'",
      )).rows[0]
      assert.deepEqual({ status: staged.status, version: Number(staged.version) }, {
        status: 'CONSUMED', version: 2,
      })
    } finally {
      await store.close()
    }
  })
  await pool.end()
}))

test('legacy same-boundary success bootstraps V2, resumes its failure, then reuses the boundary', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('k9_v2_legacy_boundary_bootstrap', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 3 })
  await pool.query('CREATE EXTENSION IF NOT EXISTS vector')
  await withIntegrityRequired(async () => {
    const store = createPocStateStore({ databasePool: pool })
    const scheduledFor = '2026-08-30T17:00:00.000Z'
    const schedulerScope = 'k9-scheduler-v1:datariver:poc:k9-scheduler:v1'
    try {
      assert.equal(await store.readK9SnapshotLifecycleV2(), null)
      await pool.query(`
        INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)
      `, [schedulerScope, JSON.stringify({
        version: 1,
        last_successful_schedule: scheduledFor,
        last_successful_reconciliation_generation: null,
        completed_at: '2026-08-30T17:01:00.000Z',
        trigger: 'scheduled',
        last_attempt: {
          status: 'SUCCESS',
          scheduled_for: scheduledFor,
          completed_at: '2026-08-30T17:01:00.000Z',
          trigger: 'scheduled',
        },
      })])
      let invocations = 0
      const command = {
        lockName: 'datariver:poc:k9-scheduler:v1',
        scheduledFor,
        trigger: 'scheduled',
        bootstrapLifecycleV2: true,
      }
      const first = await store.runK9Scheduler(command, async () => {
        invocations += 1
        await store.setK9DesiredSourceSnapshotV2(sourceEnvelope('3'))
        return { status: 'FAILURE', failureCode: 'K9_SEMANTIC_INDEX_FAILED' }
      })
      assert.equal(first.status, 'failed')
      assert.equal(invocations, 1)
      assert.notEqual(await store.readK9SnapshotLifecycleV2(), null)

      const resumed = await store.runK9Scheduler({
        lockName: command.lockName,
        scheduledFor,
        trigger: 'scheduled',
      }, async () => {
        invocations += 1
        return { status: 'SUCCESS' }
      })
      assert.equal(resumed.status, 'succeeded')
      assert.equal(invocations, 2)

      const replay = await store.runK9Scheduler({
        lockName: command.lockName,
        scheduledFor,
        trigger: 'scheduled',
      }, async () => {
        invocations += 1
        return { status: 'SUCCESS' }
      })
      assert.equal(replay.status, 'already_completed')
      assert.equal(invocations, 2)
    } finally {
      await store.close()
    }
  })
  await pool.end()
}))

test('PREP-shaped V2 retry uses persisted PostgreSQL source and reruns only Semantic', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('k9_v2_prep_resume', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 4 })
  await pool.query('CREATE EXTENSION IF NOT EXISTS vector')
  await withIntegrityRequired(async () => {
    const store = createPocStateStore({ databasePool: pool })
    try {
      const source = prepShapedSourceReceipt()
      const lifecycle = Object.freeze({
        readLifecycle: (...args) => store.readK9SnapshotLifecycleV2(...args),
        setDesiredSnapshot: (...args) => store.setK9DesiredSourceSnapshotV2(...args),
        appendProjectorReceipt: (...args) => store.appendK9ProjectorReceiptV2(...args),
        promoteActiveSnapshot: (...args) => store.promoteK9ActiveSourceSnapshotV2(...args),
      })
      const receipts = createK9V2LifecycleReceiptPort({ lifecycle })
      const calls = {
        source_capture: 0,
        direct_resolution_batches: 0,
        lineage_projection: 0,
        metadata_projection: 0,
        semantic_provider: 0,
      }
      const captureSource = async () => {
        calls.source_capture += 1
        calls.direct_resolution_batches += 6
        return source
      }
      const graphProjector = (projectorId) => createK9V2DurableProjector({
        projectorId,
        lifecycle,
        progress: (value) => ({
          phase: value?.stage || `${projectorId}_PROJECTOR`,
          completed_units: value?.stage === 'READY' ? 1 : 0,
          total_units: 1,
        }),
        output: () => ({
          output_pointer: `k9://${projectorId.toLowerCase()}/${source.source_snapshot_id}`,
          output_hash: computeSha256({ projectorId, source: source.source_snapshot_id }),
        }),
        async materialize() {
          calls[`${projectorId.toLowerCase()}_projection`] += 1
          return { status: 'READY' }
        },
      })
      let failSecondProviderBatch = true
      const semantic = createK9V2SemanticLifecycleProjector({
        bindingHash: computeSha256({ binding: 'prep-scale-semantic-v2' }),
        model: 'embedding-fixture-v1',
        lifecycle,
        semanticPersistence: store.k9SemanticPersistenceV2,
        renderDocument: (item) => `normalized document ${item.name}`,
        projectMetadata: (item) => ({ id: item.id, name: item.name }),
        provider: {
          async embed({ input }) {
            calls.semantic_provider += 1
            if (failSecondProviderBatch && calls.semantic_provider === 2) {
              throw Object.assign(new Error('private provider detail'), { code: 'ECONNRESET' })
            }
            return {
              data: input.map((_item, index) => ({ index, embedding: [index + 0.1, index + 0.2] })),
            }
          },
        },
      })
      const trigger = createPocK9V2RefreshTask({
        captureSource,
        receipts,
        projectors: Object.freeze({
          LINEAGE: graphProjector('LINEAGE'),
          METADATA: graphProjector('METADATA'),
          SEMANTIC: semantic,
        }),
      })

      const first = await trigger()
      assert.equal(first.status, 'FAILURE')
      assert.equal(first.failedProjector, 'SEMANTIC')
      assert.equal(first.failureCode, 'K9_SEMANTIC_PROVIDER_CONNECTIVITY_FAILED')
      assert.equal(JSON.stringify(first).includes('private provider detail'), false)
      assert.deepEqual(calls, {
        source_capture: 1,
        direct_resolution_batches: 6,
        lineage_projection: 1,
        metadata_projection: 1,
        semantic_provider: 2,
      })
      const failedState = await store.readK9SnapshotLifecycleV2()
      assert.equal(failedState.active_snapshot_id, null)
      assert.equal(
        failedState.desired_projector_receipts.find((item) => item.projector === 'SEMANTIC').status,
        'FAILED',
      )
      assert.equal((await pool.query(
        'SELECT count(*)::integer AS count FROM poc_k9_semantic_staging_v2',
      )).rows[0].count, 32)

      failSecondProviderBatch = false
      const retry = await trigger()
      assert.equal(retry.status, 'SUCCESS')
      assert.equal(retry.source_snapshot_id, source.source_snapshot_id)
      assert.equal(retry.lifecycle.source.outcome, 'REUSED')
      assert.equal(retry.lifecycle.projectors.LINEAGE.outcome, 'REUSED')
      assert.equal(retry.lifecycle.projectors.METADATA.outcome, 'REUSED')
      assert.equal(retry.lifecycle.projectors.SEMANTIC.outcome, 'PROJECTED')
      assert.equal(calls.source_capture, 1)
      assert.equal(calls.direct_resolution_batches, 6)
      assert.equal(calls.lineage_projection, 1)
      assert.equal(calls.metadata_projection, 1)
      assert.equal(calls.semantic_provider, 64)

      const ready = await store.readK9SnapshotLifecycleV2()
      assert.equal(ready.status, 'READY')
      assert.equal(ready.desired_snapshot_id, source.source_snapshot_id)
      assert.equal(ready.active_snapshot_id, source.source_snapshot_id)
      assert.equal(
        ready.desired_projector_receipts.find((item) => item.projector === 'SEMANTIC').attempt_number,
        2,
      )
      assert.equal((await pool.query(
        'SELECT count(*)::integer AS count FROM poc_k9_semantic_batches_v2',
      )).rows[0].count, 63)
      assert.equal((await pool.query(
        'SELECT count(*)::integer AS count FROM poc_k9_semantic_staging_v2',
      )).rows[0].count, 2_003)
      assert.equal((await pool.query(
        'SELECT count(*)::integer AS count FROM poc_catalog_embedding WHERE source_generation = $1',
        [source.source_snapshot.catalog_generation],
      )).rows[0].count, 2_003)
    } finally {
      await store.close()
    }
  })
  await pool.end()
}))

test('V5 adoption preserves accepted/failed legacy runs, LKG and semantic pointer and requires a new snapshot', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('k9_v2_adoption', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 2 })
  try {
    for (const name of migrationNames) {
      await pool.query(readFileSync(new URL(`../deploy/poc/postgres-init/${name}`, import.meta.url), 'utf8'))
    }
    const graphId = '11111111-1111-1111-1111-111111111111'
    await pool.query(`
      INSERT INTO poc_k9_managed_graph_policies (
        graph_id, name, status, classification, ontology_version_id, studio_release_id,
        publication_version, schedule, managed_intent, accepted_proposal_id, subject_id,
        workspace_id, policy_hash, tbox_hash, contract_hash, proposal_hash, source_hash,
        mapping_hash, active_release_pointer, active_release_hash, created_at, updated_at
      ) VALUES (
        $1, 'Legacy graph', 'ACTIVE', 'INTERNAL', $2, $3, 1, '0 * * * *', 'REFRESH',
        'proposal-1', 'k9-system', 'workspace-1', repeat('1',64), repeat('2',64),
        repeat('3',64), repeat('4',64), repeat('5',64), repeat('6',64),
        'k9://legacy/lkg', repeat('7',64), $4, $4
      )
    `, [graphId, '22222222-2222-2222-2222-222222222222', '33333333-3333-3333-3333-333333333333', '2026-08-31T00:00:00.000Z'])
    await pool.query(`
      INSERT INTO poc_k9_refresh_runs (
        run_id, graph_id, status, input_snapshot_hash, policy_hash, manifest,
        canonical_release, started_at, completed_at, active_release_pointer, error_message
      ) VALUES
        ('44444444-4444-4444-4444-444444444444', $1, 'RUN', repeat('8',64), repeat('1',64),
          '{"result":"SUCCESS"}'::jsonb, '{"release":"legacy"}'::jsonb, $2, $2, 'k9://legacy/lkg', NULL),
        ('55555555-5555-5555-5555-555555555555', $1, 'FAILURE', repeat('9',64), repeat('1',64),
          '{"result":"FAILURE"}'::jsonb, NULL, $2, $2, NULL, 'bounded legacy failure')
    `, [graphId, '2026-08-31T00:00:00.000Z'])
    await pool.query(
      'INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)',
      ['catalog-embedding-active-v1:legacy-binding', JSON.stringify({ generation: 'a'.repeat(64) })],
    )
    const before = {
      policy: (await pool.query('SELECT * FROM poc_k9_managed_graph_policies')).rows,
      runs: (await pool.query('SELECT * FROM poc_k9_refresh_runs ORDER BY run_id')).rows,
      pointer: (await pool.query("SELECT * FROM poc_state WHERE scope LIKE 'catalog-embedding-active-v1:%'")).rows,
    }

    await withIntegrityRequired(async () => {
      const store = createPocStateStore({ databasePool: pool })
      try {
        assert.equal(await store.readK9SnapshotLifecycleV2(), null)
      } finally {
        await store.close()
      }
    })
    assert.deepEqual((await pool.query('SELECT * FROM poc_k9_managed_graph_policies')).rows, before.policy)
    assert.deepEqual((await pool.query('SELECT * FROM poc_k9_refresh_runs ORDER BY run_id')).rows, before.runs)
    assert.deepEqual((await pool.query("SELECT * FROM poc_state WHERE scope LIKE 'catalog-embedding-active-v1:%'")).rows, before.pointer)
    const adoption = (await pool.query(
      "SELECT value, version FROM poc_state WHERE scope = 'k9-lifecycle-adoption-v2'",
    )).rows[0]
    assert.equal(Number(adoption.version), 1)
    assert.deepEqual(adoption.value, {
      contract: 'DATARIVER_K9_LEGACY_ADOPTION_V2',
      state: 'NEW_SNAPSHOT_REQUIRED',
      legacy_lkg_state: 'PRESERVED',
      policy_count: 1,
      run_count: 2,
      semantic_pointer_count: 1,
    })
    for (const table of [
      'poc_k9_source_snapshots_v2', 'poc_k9_source_payloads_v2',
      'poc_k9_semantic_manifests_v2', 'poc_k9_semantic_desired_documents_v2',
      'poc_k9_semantic_batches_v2', 'poc_k9_semantic_staging_v2',
      'poc_k9_projector_receipts_v2', 'poc_k9_snapshot_lifecycle_v2',
    ]) {
      assert.equal((await pool.query(`SELECT count(*)::integer AS count FROM ${table}`)).rows[0].count, 0)
    }
  } finally {
    await pool.end()
  }
}))

test('semantic staging survives restart and materializes with its pointer atomically and idempotently', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('k9_v2_semantic_stage', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 3 })
  await pool.query('CREATE EXTENSION IF NOT EXISTS vector')
  await withIntegrityRequired(async () => {
    const envelope = sourceEnvelope('3')
    const bindingHash = computeSha256({ binding: 'semantic-v2' })
    const pointerScope = `catalog-embedding-active-v1:${bindingHash}`
    const oldPointer = { projection_version: 1, binding_hash: bindingHash, source_generation: '9'.repeat(64) }
    const first = createPocStateStore({ databasePool: pool })
    await first.setK9DesiredSourceSnapshotV2(envelope)
    const one = semanticDesiredDocument(1)
    const two = semanticDesiredDocument(2, 'changed')
    await pool.query(`
      INSERT INTO poc_catalog_embedding (
        binding_hash, asset_urn, source_hash, source_generation, content_text, metadata, embedding
      ) VALUES
        ($1, $2, $3, repeat('9',64), $4, $5::jsonb, '[0.1,0.05]'::vector),
        ($1, 'urn:li:dataset:(urn:li:dataPlatform:postgres,removed.table,PROD)',
          repeat('8',64), repeat('9',64), 'removed prior document', '{"prior":true}'::jsonb, '[0.9,0.9]'::vector)
    `, [bindingHash, one.document_id, one.source_hash, one.content_text, JSON.stringify(one.metadata)])
    await pool.query('INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)', [pointerScope, JSON.stringify(oldPointer)])
    const target = {
      source_snapshot_id: envelope.snapshot.source_snapshot_id,
      binding_hash: bindingHash,
      document_count: 2,
      documents: [one, two],
      staged_count: 1,
      batch_total: 1,
      vector_dimension: 2,
    }
    await assert.rejects(first.stageK9SemanticBatchV2({
      source_snapshot_id: target.source_snapshot_id,
      binding_hash: target.binding_hash,
      batch_number: 1,
      batch_total: 1,
      documents: [changedVector(two, 2)],
    }), { code: '23503' })
    assert.deepEqual((await pool.query('SELECT value FROM poc_state WHERE scope = $1', [pointerScope])).rows[0].value, oldPointer)
    assert.equal((await pool.query('SELECT count(*)::integer AS count FROM poc_k9_semantic_batches_v2')).rows[0].count, 0)
    await first.k9SemanticPersistenceV2.persistDesiredManifest(target)
    await assert.rejects(first.stageK9SemanticBatchV2({
      source_snapshot_id: target.source_snapshot_id,
      binding_hash: target.binding_hash,
      batch_number: 1,
      batch_total: 1,
      documents: [{ ...changedVector(two, 2), source_hash: 'f'.repeat(64) }],
    }), { code: '23503' })
    assert.deepEqual((await pool.query('SELECT value FROM poc_state WHERE scope = $1', [pointerScope])).rows[0].value, oldPointer)
    assert.equal((await pool.query('SELECT count(*)::integer AS count FROM poc_k9_semantic_batches_v2')).rows[0].count, 0)
    await assert.rejects(first.k9SemanticPersistenceV2.activateSnapshot(target), {
      code: 'K9_SEMANTIC_BATCHES_INCOMPLETE',
    })
    assert.deepEqual((await pool.query('SELECT value FROM poc_state WHERE scope = $1', [pointerScope])).rows[0].value, oldPointer)
    assert.equal((await pool.query('SELECT count(*)::integer AS count FROM poc_catalog_embedding WHERE binding_hash = $1', [bindingHash])).rows[0].count, 2)
    await first.k9SemanticPersistenceV2.writeEmbeddingBatch({
      ...target,
      batch_number: 1,
      records: [{ ...two, embedding: changedVector(two, 2).embedding }],
    })
    assert.deepEqual(await first.k9SemanticPersistenceV2.readStagedDocumentHashes(target), {
      hashes: [{ document_id: two.document_id, source_hash: two.source_hash }],
      vector_dimension: 2,
      batch_count: 1,
      batch_total: 1,
    })
    await first.close()

    const restarted = createPocStateStore({ databasePool: pool })
    try {
      assert.equal((await restarted.k9SemanticPersistenceV2.persistDesiredManifest(target)).created, false)
      await pool.query(`
        CREATE FUNCTION poc_test_reject_k9_pointer() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'synthetic pointer failure'; END $$;
        CREATE TRIGGER trg_poc_test_reject_k9_pointer
          BEFORE UPDATE ON poc_state FOR EACH ROW
          WHEN (NEW.scope LIKE 'catalog-embedding-active-v1:%')
          EXECUTE FUNCTION poc_test_reject_k9_pointer();
      `)
      await assert.rejects(restarted.k9SemanticPersistenceV2.activateSnapshot(target), /synthetic pointer failure/)
      assert.deepEqual((await pool.query('SELECT value FROM poc_state WHERE scope = $1', [pointerScope])).rows[0].value, oldPointer)
      assert.equal((await pool.query('SELECT count(*)::integer AS count FROM poc_catalog_embedding WHERE binding_hash = $1', [bindingHash])).rows[0].count, 2)
      await pool.query('DROP TRIGGER trg_poc_test_reject_k9_pointer ON poc_state; DROP FUNCTION poc_test_reject_k9_pointer()')

      const activated = await restarted.k9SemanticPersistenceV2.activateSnapshot(target)
      assert.equal(activated.activated, true)
      assert.equal(activated.materialized, 2)
      assert.equal(activated.active_pointer.source_generation, envelope.snapshot.catalog_generation)
      assert.equal(activated.active_pointer.source_snapshot_id, envelope.snapshot.source_snapshot_id)
      const pointerVersion = (await pool.query('SELECT version::integer, value FROM poc_state WHERE scope = $1', [pointerScope])).rows[0]
      assert.deepEqual(pointerVersion.value, activated.active_pointer)
      assert.equal((await restarted.k9SemanticPersistenceV2.activateSnapshot(target)).activated, false)
      assert.equal((await pool.query('SELECT version::integer FROM poc_state WHERE scope = $1', [pointerScope])).rows[0].version, pointerVersion.version)
      assert.equal((await pool.query('SELECT count(*)::integer AS count FROM poc_k9_semantic_staging_v2', [])).rows[0].count, 1)
      assert.equal((await pool.query('SELECT count(*)::integer AS count FROM poc_catalog_embedding WHERE binding_hash = $1', [bindingHash])).rows[0].count, 3)
      assert.deepEqual(await restarted.k9SemanticPersistenceV2.readActiveDocumentHashes({ binding_hash: bindingHash }), {
        hashes: [
          { document_id: one.document_id, source_hash: one.source_hash },
          { document_id: two.document_id, source_hash: two.source_hash },
        ],
        source_snapshot_id: envelope.snapshot.source_snapshot_id,
      })
      const sameGeneration = sourceEnvelope('3', 'next-provider-commit')
      await restarted.setK9DesiredSourceSnapshotV2(sameGeneration, 'same-catalog-generation')
      await restarted.persistK9SemanticDesiredManifestV2({
        source_snapshot_id: sameGeneration.snapshot.source_snapshot_id,
        binding_hash: bindingHash,
        documents: [one, two],
      }, 'same-catalog-generation')
      const identityOnly = await restarted.activateK9SemanticSnapshotV2({
        source_snapshot_id: sameGeneration.snapshot.source_snapshot_id,
        binding_hash: bindingHash,
        expected_desired_count: 2,
        expected_changed_count: 0,
        expected_batch_count: 0,
      }, 'same-catalog-generation')
      assert.equal(identityOnly.active_pointer.source_generation, envelope.snapshot.catalog_generation)
      assert.equal(identityOnly.active_pointer.source_snapshot_id, sameGeneration.snapshot.source_snapshot_id)
      const sameGenerationRemoval = sourceEnvelope('3', 'removal-provider-commit')
      await restarted.setK9DesiredSourceSnapshotV2(sameGenerationRemoval, 'same-generation-removal')
      await restarted.persistK9SemanticDesiredManifestV2({
        source_snapshot_id: sameGenerationRemoval.snapshot.source_snapshot_id,
        binding_hash: bindingHash,
        documents: [one],
      }, 'same-generation-removal')
      await restarted.activateK9SemanticSnapshotV2({
        source_snapshot_id: sameGenerationRemoval.snapshot.source_snapshot_id,
        binding_hash: bindingHash,
        expected_desired_count: 1,
        expected_changed_count: 0,
        expected_batch_count: 0,
      }, 'same-generation-removal')
      assert.equal((await pool.query(`
        SELECT count(*)::integer AS count FROM poc_catalog_embedding
        WHERE binding_hash = $1 AND source_generation = $2
      `, [bindingHash, envelope.snapshot.catalog_generation])).rows[0].count, 1)
      assert.equal((await pool.query(
        'SELECT count(*)::integer AS count FROM poc_catalog_embedding WHERE binding_hash = $1',
        [bindingHash],
      )).rows[0].count, 3)

      for (const scenario of [
        { name: 'zero', documents: [one], prior: [one], changed: [] },
        { name: 'full', documents: [one, two], prior: [], changed: [one, two] },
        { name: 'removal', documents: [], prior: [one], changed: [] },
      ]) {
        const scenarioBinding = computeSha256({ scenario: scenario.name })
        const scenarioPointer = `catalog-embedding-active-v1:${scenarioBinding}`
        for (const document of scenario.prior) {
          await pool.query(`
            INSERT INTO poc_catalog_embedding (
              binding_hash, asset_urn, source_hash, source_generation, content_text, metadata, embedding
            ) VALUES ($1,$2,$3,repeat('7',64),$4,$5::jsonb,'[0.1,0.05]'::vector)
          `, [scenarioBinding, document.document_id, document.source_hash, document.content_text, JSON.stringify(document.metadata)])
        }
        if (scenario.prior.length) {
          await pool.query('INSERT INTO poc_state (scope, value) VALUES ($1,$2::jsonb)', [scenarioPointer, JSON.stringify({
            projection_version: 1, binding_hash: scenarioBinding, source_generation: '7'.repeat(64),
          })])
        }
        const scenarioTarget = {
          source_snapshot_id: envelope.snapshot.source_snapshot_id,
          binding_hash: scenarioBinding,
          document_count: scenario.documents.length,
          documents: scenario.documents,
          staged_count: scenario.changed.length,
          batch_total: scenario.changed.length ? 1 : 0,
          vector_dimension: scenario.documents.length ? 2 : undefined,
        }
        await restarted.k9SemanticPersistenceV2.persistDesiredManifest(scenarioTarget)
        if (scenario.changed.length) {
          await restarted.k9SemanticPersistenceV2.writeEmbeddingBatch({
            ...scenarioTarget, batch_number: 1,
            records: scenario.changed.map((document, index) => ({
              ...document, embedding: changedVector(document, index + 1).embedding,
            })),
          })
        }
        const result = await restarted.k9SemanticPersistenceV2.activateSnapshot(scenarioTarget)
        assert.equal(result.materialized, scenario.documents.length)
        assert.equal((await pool.query(`
          SELECT count(*)::integer AS count FROM poc_catalog_embedding
          WHERE binding_hash = $1 AND source_generation = $2
        `, [scenarioBinding, envelope.snapshot.catalog_generation])).rows[0].count, scenario.documents.length)
      }
    } finally {
      await restarted.close()
    }
  })
  await pool.end()
}))
