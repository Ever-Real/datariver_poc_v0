import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import process from 'node:process'
import test from 'node:test'
import { URL } from 'node:url'
import pg from 'pg'

import { computeSha256 } from './poc-knowledge-k9-contracts.mjs'
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

async function appendAttempt(store, snapshotId, projector, attemptNumber, terminalStatus, previousAttempt = null) {
  const pending = receipt({ snapshotId, projector, status: 'PENDING', attemptNumber, sequence: 1, previous: previousAttempt })
  const running = receipt({ snapshotId, projector, status: 'RUNNING', attemptNumber, sequence: 2, previous: pending })
  const terminal = receipt({ snapshotId, projector, status: terminalStatus, attemptNumber, sequence: 3, previous: running })
  await store.appendK9ProjectorReceiptV2(pending)
  await store.appendK9ProjectorReceiptV2(running)
  await store.appendK9ProjectorReceiptV2(terminal)
  return terminal
}

test('fresh V6 persists replayable source payloads, retries FAILED attempts, and separates desired from active receipts', {
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
