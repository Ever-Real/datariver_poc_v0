/* global structuredClone */
import assert from 'node:assert/strict'
import { mock, test } from 'node:test'

import {
  K9GraphProjectorError,
  createK9GraphProjector,
  createK9GraphProjectors,
  createK9LineageProjector,
  createK9MetadataProjector,
  k9GraphProjectorReceiptState,
} from './poc-k9-graph-projector.mjs'
import {
  K9_PROJECTOR_RECEIPT_CONTRACT_V2,
  normalizeK9ProjectorReceiptV2,
} from './poc-k9-lifecycle-persistence.mjs'
import { computeSha256 } from './poc-knowledge-k9-contracts.mjs'

const oldSnapshotId = 'f'.repeat(64)
const tableA = 'TABLE:urn:li:dataset:(urn:li:dataPlatform:test,A,PROD)'
const tableB = 'TABLE:urn:li:dataset:(urn:li:dataPlatform:test,B,PROD)'

function sourceEnvelope() {
  const source_payloads = {
    inventory: {
      projection_version: 2,
      source_scope: 'K9',
      source_generation: '1'.repeat(64),
      items: [{ urn: tableA.slice('TABLE:'.length) }],
    },
    lineage: {
      direction: 'BOTH',
      depth: 1,
      truncated: false,
      nodes: [
        { id: tableA, classification: 'INTERNAL', properties: { name: 'A' } },
        { id: tableB, classification: 'INTERNAL', properties: { name: 'B' } },
      ],
      column_nodes: [],
      edges: [{ source_asset_id: tableA, target_asset_id: tableB }],
      completeness_metadata: { complete: true },
    },
    metadata: {
      collections: {
        table_nodes: [{ id: tableA, classification: 'INTERNAL', properties: { name: 'A' } }],
        column_nodes: [],
        table_column_edges: [],
        terms: [],
        parent_nodes: [],
        term_parent_edges: [],
        node_parent_edges: [],
        glossary_relationships: [],
        table_assignments: [],
        column_assignments: [],
        tags: [],
        domains: [],
        containers: [],
        platform_instances: [],
        table_tag_assignments: [],
        column_tag_assignments: [],
        table_domain_assignments: [],
        table_container_assignments: [],
        table_platform_instance_assignments: [],
      },
      completeness_metadata: { complete: true },
      raw_assignment_reference_hash: null,
    },
    dangling_state: { dangling_reference_hash: null, dangling_table_refs: 0 },
  }
  const identity = {
    contract_version: 'DATARIVER_K9_SOURCE_SNAPSHOT_V2',
    catalog_generation: source_payloads.inventory.source_generation,
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
      metadata_source_profile: null,
    },
    source_payloads,
  }
}

function receipt({
  snapshotId,
  projector,
  status,
  attemptNumber = 1,
  sequence = 3,
  previousReceiptId = null,
  attemptId = computeSha256({ projector, attemptNumber }),
  pointer = `k9://${projector.toLowerCase()}/${snapshotId}`,
}) {
  const document = {
    contract: K9_PROJECTOR_RECEIPT_CONTRACT_V2,
    source_snapshot_id: snapshotId,
    projector,
    status,
    attempt_id: attemptId,
    attempt_number: attemptNumber,
    sequence,
    previous_receipt_id: previousReceiptId,
    idempotency_key_hash: computeSha256({ projector, attemptNumber, sequence, status }),
    progress: {
      phase: `${projector}_${status}`,
      completed_units: status === 'READY' ? 1 : 0,
      total_units: 1,
      pointer_advanced: status === 'READY',
    },
    diagnostic: status === 'FAILED'
      ? { code: 'K9_GRAPH_PROJECTION_FAILED', stage: 'GRAPH_PROJECTION', detail_hash: 'd'.repeat(64) }
      : null,
    output_pointer: status === 'READY' ? pointer : null,
    output_hash: status === 'READY' ? computeSha256({ pointer }) : null,
    recorded_at: '2026-08-31T00:00:00.000Z',
  }
  return normalizeK9ProjectorReceiptV2({ ...document, receipt_id: computeSha256(document) })
}

function fakePersistence(envelope, { desiredReceipts = [], activeReceipts = [] } = {}) {
  const lifecycle = {
    desired_snapshot_id: envelope.snapshot.source_snapshot_id,
    active_snapshot_id: activeReceipts[0]?.source_snapshot_id || null,
    desired_snapshot: envelope.snapshot,
    active_snapshot: null,
    desired_projector_receipts: [...desiredReceipts],
    active_ready_projector_receipts: [...activeReceipts],
    desired_source_payloads: {
      INVENTORY: envelope.source_payloads.inventory,
      LINEAGE: envelope.source_payloads.lineage,
      METADATA: envelope.source_payloads.metadata,
      DANGLING_STATE: envelope.source_payloads.dangling_state,
    },
    active_source_payloads: null,
  }
  const appended = []
  return {
    appended,
    lifecycle,
    async readLifecycle() { return structuredClone(lifecycle) },
    async appendProjectorReceipt(value) {
      const normalized = normalizeK9ProjectorReceiptV2(value)
      appended.push(normalized)
      lifecycle.desired_projector_receipts = [
        ...lifecycle.desired_projector_receipts.filter((item) => item.projector !== normalized.projector),
        normalized,
      ]
      return { created: true, receipt: normalized }
    },
  }
}

function sourceReceipt(envelope) {
  return {
    status: 'READY',
    source_snapshot_id: envelope.snapshot.source_snapshot_id,
    source_snapshot: envelope.snapshot,
  }
}

function projector(projectorId, persistence, managedGraphs) {
  return createK9GraphProjector({
    projectorId,
    persistence,
    managedGraphs,
    resolveAuthContext: async () => ({ principal: { subjectId: 'k9-system' }, workspaceId: 'workspace-1' }),
    clock: () => new Date('2026-08-31T00:00:00.000Z'),
    createAttemptId: ({ attemptNumber }) => String(attemptNumber).repeat(64),
  })
}

test('LINEAGE and METADATA consume only persisted normalized payload X and append bounded receipts', async () => {
  const envelope = sourceEnvelope()
  for (const projectorId of ['LINEAGE', 'METADATA']) {
    const persistence = fakePersistence(envelope)
    const managedGraphs = {
      publishPersistedProjection: mock.fn(async (authContext, input) => {
        assert.equal(authContext.principal.subjectId, 'k9-system')
        assert.equal(input.projector_id, projectorId)
        assert.equal(input.source_snapshot.source_snapshot_id, envelope.snapshot.source_snapshot_id)
        assert.deepEqual(input.source_payload, envelope.source_payloads[projectorId.toLowerCase()])
        assert.equal(Object.hasOwn(input, 'semantic'), false)
        return {
          status: 'RUN',
          sourceSnapshotId: envelope.snapshot.source_snapshot_id,
          outputPointer: `k9-stage-${projectorId.toLowerCase()}`,
          manifestHash: computeSha256({ projectorId, ready: true }),
        }
      }),
    }
    const result = await projector(projectorId, persistence, managedGraphs).project(sourceReceipt(envelope))
    assert.deepEqual(persistence.appended.map((item) => item.status), ['PENDING', 'RUNNING', 'READY'])
    assert.deepEqual(persistence.appended.map((item) => item.sequence), [1, 2, 3])
    assert.ok(persistence.appended.every((item) => JSON.stringify(item).length < 8192))
    assert.equal(result.status, 'READY')
    assert.equal(result.desired_snapshot_id, envelope.snapshot.source_snapshot_id)
    assert.equal(result.active_snapshot_id, envelope.snapshot.source_snapshot_id)
  }
})

test('READY(X) is reused without source access, graph work, or Semantic readiness', async () => {
  const envelope = sourceEnvelope()
  const ready = receipt({
    snapshotId: envelope.snapshot.source_snapshot_id,
    projector: 'LINEAGE',
    status: 'READY',
  })
  const semanticFailed = receipt({
    snapshotId: envelope.snapshot.source_snapshot_id,
    projector: 'SEMANTIC',
    status: 'FAILED',
  })
  const persistence = fakePersistence(envelope, { desiredReceipts: [ready, semanticFailed] })
  const managedGraphs = { publishPersistedProjection: mock.fn() }
  const resolveAuthContext = mock.fn()
  const value = createK9GraphProjector({
    projectorId: 'LINEAGE', persistence, managedGraphs, resolveAuthContext,
  })

  const result = await value.project(sourceReceipt(envelope))

  assert.equal(result.outcome, 'REUSED')
  assert.equal(managedGraphs.publishPersistedProjection.mock.calls.length, 0)
  assert.equal(resolveAuthContext.mock.calls.length, 0)
  assert.deepEqual(persistence.appended, [])
})

test('a same-X graph-only retry appends a new attempt and preserves the prior active LKG', async () => {
  const envelope = sourceEnvelope()
  const oldReady = receipt({ snapshotId: oldSnapshotId, projector: 'METADATA', status: 'READY' })
  const persistence = fakePersistence(envelope, { activeReceipts: [oldReady] })
  const inactiveCandidates = []
  let activePointer = oldReady.output_pointer
  const managedGraphs = {
    publishPersistedProjection: mock.fn(async (authContext, input) => {
      inactiveCandidates.push(input.source_snapshot.source_snapshot_id)
      if (inactiveCandidates.length === 1) {
        return {
          status: 'FAILURE',
          failureCode: 'K9_NEO4J_PROJECTION_FAILED',
          diagnostic: {
            failure_stage: 'GRAPH_WRITE',
            failure_detail_code: 'NODE_BATCH_WRITE_FAILED',
            neo4j_http_class: 'HTTP_2XX',
            neo4j_error_class: 'CLIENT',
            batch_number: 1,
            batch_total: 2,
            batch_requested_nodes: 2,
            batch_requested_edges: 0,
            batch_written_nodes: 0,
            batch_written_edges: 0,
            query_family: 'NODE_BATCH_WRITE',
            transaction_phase: 'STAGING',
            expected_snapshot_id_present: true,
            active_snapshot_id_present: true,
            promotion_attempted: false,
            promotion_completed: false,
          },
        }
      }
      activePointer = 'k9-stage-metadata-new'
      return {
        status: 'RUN',
        sourceSnapshotId: envelope.snapshot.source_snapshot_id,
        outputPointer: activePointer,
        manifestHash: computeSha256(input.source_payload),
      }
    }),
  }
  const value = projector('METADATA', persistence, managedGraphs)

  await assert.rejects(value.project(sourceReceipt(envelope)), (error) => {
    assert.ok(error instanceof K9GraphProjectorError)
    assert.equal(error.diagnostic.code, 'K9_GRAPH_PROJECTION_FAILED')
    assert.equal(error.diagnostic.stage, 'GRAPH_WRITE')
    assert.equal(error.diagnostic.failure_detail_code, 'NODE_BATCH_WRITE_FAILED')
    assert.equal(error.diagnostic.query_family, 'NODE_BATCH_WRITE')
    return true
  })
  assert.equal(activePointer, oldReady.output_pointer)
  const failedState = k9GraphProjectorReceiptState(persistence.lifecycle, 'METADATA')
  assert.equal(failedState.desired.status, 'FAILED')
  assert.equal(failedState.desired.receipt.diagnostic.neo4j_error_class, 'CLIENT')
  assert.equal(failedState.desired.receipt.diagnostic.batch_requested_nodes, 2)
  assert.equal(failedState.active.active_snapshot_id, oldSnapshotId)

  const retried = await value.project(sourceReceipt(envelope))

  assert.equal(retried.status, 'READY')
  assert.deepEqual(persistence.appended.map((item) => item.status), [
    'PENDING', 'RUNNING', 'FAILED', 'PENDING', 'RUNNING', 'READY',
  ])
  assert.deepEqual(persistence.appended.map((item) => item.attempt_number), [1, 1, 1, 2, 2, 2])
  assert.equal(managedGraphs.publishPersistedProjection.mock.calls.length, 2)
  assert.deepEqual(inactiveCandidates, [
    envelope.snapshot.source_snapshot_id, envelope.snapshot.source_snapshot_id,
  ])
  const readyState = k9GraphProjectorReceiptState(persistence.lifecycle, 'METADATA')
  assert.equal(readyState.active.active_snapshot_id, envelope.snapshot.source_snapshot_id)
})

test('malformed persisted payload identity fails before a receipt or graph candidate is created', async () => {
  const envelope = sourceEnvelope()
  const persistence = fakePersistence(envelope)
  persistence.lifecycle.desired_source_payloads.LINEAGE.nodes[0].properties.name = 'drifted'
  const managedGraphs = { publishPersistedProjection: mock.fn() }

  await assert.rejects(projector('LINEAGE', persistence, managedGraphs).project(sourceReceipt(envelope)), {
    diagnostic: {
      code: 'K9_GRAPH_SOURCE_CONTRACT_FAILED',
      stage: 'SOURCE_PAYLOAD',
      retryable: false,
      message: 'The persisted graph source payload does not match its immutable snapshot.',
    },
  })
  assert.deepEqual(persistence.appended, [])
  assert.equal(managedGraphs.publishPersistedProjection.mock.calls.length, 0)
})

test('resumes an interrupted RUNNING receipt through managed READY output reuse', async () => {
  const envelope = sourceEnvelope()
  const pending = receipt({
    snapshotId: envelope.snapshot.source_snapshot_id,
    projector: 'LINEAGE',
    status: 'PENDING',
    sequence: 1,
  })
  const running = receipt({
    snapshotId: envelope.snapshot.source_snapshot_id,
    projector: 'LINEAGE',
    status: 'RUNNING',
    sequence: 2,
    previousReceiptId: pending.receipt_id,
    attemptId: pending.attempt_id,
  })
  const persistence = fakePersistence(envelope, { desiredReceipts: [running] })
  const outputPointer = 'k9_stage_already_promoted'
  const managedGraphs = {
    publishPersistedProjection: mock.fn(async () => ({
      status: 'NO_OP',
      sourceSnapshotId: envelope.snapshot.source_snapshot_id,
      outputPointer,
      manifestHash: computeSha256({ outputPointer }),
    })),
  }

  const result = await projector('LINEAGE', persistence, managedGraphs).project(sourceReceipt(envelope))

  assert.equal(result.outcome, 'REUSED_OUTPUT')
  assert.deepEqual(persistence.appended.map((item) => item.status), ['RUNNING', 'READY'])
  assert.deepEqual(persistence.appended.map((item) => item.sequence), [3, 4])
  assert.ok(persistence.appended.every((item) => item.attempt_id === running.attempt_id))
})

test('constructs both graph adapters without any Semantic projector dependency', () => {
  const envelope = sourceEnvelope()
  const persistence = fakePersistence(envelope)
  const managedGraphs = { publishPersistedProjection: async () => undefined }
  const projectors = createK9GraphProjectors({
    persistence,
    managedGraphs,
    resolveAuthContext: async () => ({}),
  })
  assert.deepEqual(Object.keys(projectors), ['LINEAGE', 'METADATA'])
  assert.equal(typeof createK9LineageProjector({
    persistence, managedGraphs, resolveAuthContext: async () => ({}),
  }).project, 'function')
  assert.equal(typeof createK9MetadataProjector({
    persistence, managedGraphs, resolveAuthContext: async () => ({}),
  }).project, 'function')
})
