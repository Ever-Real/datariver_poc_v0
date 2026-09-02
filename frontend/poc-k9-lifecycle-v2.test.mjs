import assert from 'node:assert/strict'
import { mock, test } from 'node:test'

import {
  K9_V2_PROJECTOR_IDS,
  createK9V2LifecycleOrchestrator,
  evaluateK9V2AggregateReadiness,
} from './poc-k9-lifecycle-v2.mjs'

const snapshotA = 'a'.repeat(64)
const snapshotB = 'b'.repeat(64)

function desiredReceipt(projectorId, sourceSnapshotId, status = 'READY') {
  return Object.freeze({
    projector_id: projectorId,
    desired_snapshot_id: sourceSnapshotId,
    source_snapshot_id: sourceSnapshotId,
    status,
  })
}

function activeReceipt(projectorId, sourceSnapshotId) {
  return Object.freeze({
    projector_id: projectorId,
    active_snapshot_id: sourceSnapshotId,
    source_snapshot_id: sourceSnapshotId,
  })
}

function readySourceReceipt(sourceSnapshotId = snapshotA, evidence = {}) {
  return Object.freeze({
    status: 'READY',
    source_snapshot_id: sourceSnapshotId,
    source_snapshot: Object.freeze({ source_snapshot_id: sourceSnapshotId }),
    evidence: Object.freeze(evidence),
  })
}

function fakeReceiptPort({ sourceReceipt, desired = {}, active = {} } = {}) {
  const state = { sourceReceipt, desired: { ...desired }, active: { ...active }, calls: [] }
  return {
    state,
    async readSourceCaptureReceipt() {
      state.calls.push(['read-source'])
      return state.sourceReceipt
    },
    async writeSourceCaptureReceipt(receipt) {
      state.calls.push(['write-source'])
      state.sourceReceipt = receipt
    },
    async readProjectorDesiredReceipt(projectorId) {
      state.calls.push(['read-desired', projectorId])
      return state.desired[projectorId]
    },
    async readProjectorActiveReceipt(projectorId) {
      state.calls.push(['read-active', projectorId])
      return state.active[projectorId]
    },
  }
}

function readyProjectorReceipts(sourceSnapshotId = snapshotA) {
  return Object.fromEntries(K9_V2_PROJECTOR_IDS.map((projectorId) => [
    projectorId,
    {
      desired: desiredReceipt(projectorId, sourceSnapshotId),
      active: activeReceipt(projectorId, sourceSnapshotId),
    },
  ]))
}

function projectorPorts(receipts, implementations = {}) {
  return Object.fromEntries(K9_V2_PROJECTOR_IDS.map((projectorId) => [
    projectorId,
    {
      project: implementations[projectorId] || mock.fn(async (sourceReceipt) => {
        const sourceSnapshotId = sourceReceipt.source_snapshot_id
        receipts.state.desired[projectorId] = desiredReceipt(projectorId, sourceSnapshotId)
        receipts.state.active[projectorId] = activeReceipt(projectorId, sourceSnapshotId)
        return { status: 'READY', source_snapshot_id: sourceSnapshotId }
      }),
    },
  ]))
}

test('K9 V2 RESUME reuses aggregate READY without source recapture or projector work', async () => {
  const pairs = readyProjectorReceipts()
  const receipts = fakeReceiptPort({
    sourceReceipt: readySourceReceipt(),
    desired: Object.fromEntries(K9_V2_PROJECTOR_IDS.map((id) => [id, pairs[id].desired])),
    active: Object.fromEntries(K9_V2_PROJECTOR_IDS.map((id) => [id, pairs[id].active])),
  })
  const captureSource = mock.fn(async () => readySourceReceipt())
  const projectors = projectorPorts(receipts)

  const result = await createK9V2LifecycleOrchestrator({
    captureSource, receipts, projectors,
  }).run({ sourceRunMode: 'RESUME' })

  assert.equal(result.status, 'READY')
  assert.equal(result.source.outcome, 'REUSED')
  assert.equal(result.readiness.status, 'READY')
  assert.equal(captureSource.mock.calls.length, 0)
  for (const projectorId of K9_V2_PROJECTOR_IDS) {
    assert.deepEqual(result.projectors[projectorId], { status: 'READY', outcome: 'REUSED' })
    assert.equal(projectors[projectorId].project.mock.calls.length, 0)
    assert.ok(receipts.state.calls.some(([operation, id]) => operation === 'read-desired' && id === projectorId))
    assert.ok(receipts.state.calls.some(([operation, id]) => operation === 'read-active' && id === projectorId))
  }
})

test('an accepted snapshot captures a changed successor and projects every successor receipt', async () => {
  const pairs = readyProjectorReceipts(snapshotA)
  const receipts = fakeReceiptPort({
    sourceReceipt: readySourceReceipt(snapshotA),
    desired: Object.fromEntries(K9_V2_PROJECTOR_IDS.map((id) => [id, pairs[id].desired])),
    active: Object.fromEntries(K9_V2_PROJECTOR_IDS.map((id) => [id, pairs[id].active])),
  })
  const captureSource = mock.fn(async () => readySourceReceipt(snapshotB))
  const projectors = projectorPorts(receipts)

  const result = await createK9V2LifecycleOrchestrator({
    captureSource, receipts, projectors,
  }).run()

  assert.equal(result.status, 'READY')
  assert.equal(result.source_snapshot_id, snapshotB)
  assert.equal(result.source.outcome, 'CAPTURED')
  assert.equal(captureSource.mock.calls.length, 1)
  for (const projectorId of K9_V2_PROJECTOR_IDS) {
    assert.equal(result.projectors[projectorId].outcome, 'PROJECTED')
    assert.equal(projectors[projectorId].project.mock.calls.length, 1)
  }
})

test('Actual-PREP-shaped Semantic retry reuses capture, direct resolution, and both graph projections', async () => {
  const evidence = Object.freeze({
    glossary_term_count: 1_570,
    direct_resolution_count: 1_486,
    dangling_assignment_reference_count: 75_431,
    direct_resolution_batch_count: 6,
  })
  const receipts = fakeReceiptPort()
  let directResolutionInvocations = 0
  let directResolutionBatches = 0
  const captureSource = mock.fn(async () => {
    directResolutionInvocations += 1
    for (let batch = 0; batch < evidence.direct_resolution_batch_count; batch += 1) {
      directResolutionBatches += 1
    }
    return readySourceReceipt(snapshotA, evidence)
  })
  const graphCalls = { LINEAGE: 0, METADATA: 0 }
  let semanticAttempts = 0
  const implementations = {
    LINEAGE: mock.fn(async (sourceReceipt) => {
      graphCalls.LINEAGE += 1
      receipts.state.desired.LINEAGE = desiredReceipt('LINEAGE', sourceReceipt.source_snapshot_id)
      receipts.state.active.LINEAGE = activeReceipt('LINEAGE', sourceReceipt.source_snapshot_id)
      return { status: 'READY', source_snapshot_id: sourceReceipt.source_snapshot_id }
    }),
    METADATA: mock.fn(async (sourceReceipt) => {
      graphCalls.METADATA += 1
      receipts.state.desired.METADATA = desiredReceipt('METADATA', sourceReceipt.source_snapshot_id)
      receipts.state.active.METADATA = activeReceipt('METADATA', sourceReceipt.source_snapshot_id)
      return { status: 'READY', source_snapshot_id: sourceReceipt.source_snapshot_id }
    }),
    SEMANTIC: mock.fn(async (sourceReceipt) => {
      semanticAttempts += 1
      if (semanticAttempts === 1) {
        receipts.state.desired.SEMANTIC = desiredReceipt('SEMANTIC', sourceReceipt.source_snapshot_id, 'FAILED')
        throw Object.assign(new Error('urn:li:dataset:private token=must-not-escape'), {
          diagnostic: {
            code: 'K9_SEMANTIC_PROVIDER_CONNECTIVITY_FAILED',
            stage: 'PROVIDER',
            retryable: true,
            raw_urn: 'urn:li:dataset:private',
            secret: 'must-not-escape',
          },
        })
      }
      receipts.state.desired.SEMANTIC = desiredReceipt('SEMANTIC', sourceReceipt.source_snapshot_id)
      receipts.state.active.SEMANTIC = activeReceipt('SEMANTIC', sourceReceipt.source_snapshot_id)
      return { status: 'READY', source_snapshot_id: sourceReceipt.source_snapshot_id }
    }),
  }
  const projectors = projectorPorts(receipts, implementations)
  const orchestrator = createK9V2LifecycleOrchestrator({ captureSource, receipts, projectors })

  const first = await orchestrator.run()
  assert.equal(first.status, 'FAILED')
  assert.equal(first.failed_projector, 'SEMANTIC')
  assert.deepEqual(first.diagnostic, {
    code: 'K9_SEMANTIC_PROVIDER_CONNECTIVITY_FAILED', stage: 'PROVIDER', retryable: true,
  })
  assert.equal(JSON.stringify(first).includes('urn:li:'), false)
  assert.equal(JSON.stringify(first).includes('must-not-escape'), false)

  const retry = await orchestrator.run()
  assert.equal(retry.status, 'READY')
  assert.equal(retry.source_snapshot_id, snapshotA)
  assert.equal(retry.source.outcome, 'REUSED')
  assert.equal(retry.projectors.LINEAGE.outcome, 'REUSED')
  assert.equal(retry.projectors.METADATA.outcome, 'REUSED')
  assert.equal(retry.projectors.SEMANTIC.outcome, 'PROJECTED')
  assert.equal(retry.readiness.status, 'READY')
  assert.equal(retry.readiness.source_snapshot_id, snapshotA)

  assert.equal(captureSource.mock.calls.length, 1)
  assert.equal(directResolutionInvocations, 1)
  assert.equal(directResolutionBatches, 6)
  assert.equal(receipts.state.sourceReceipt.evidence.glossary_term_count, 1_570)
  assert.equal(receipts.state.sourceReceipt.evidence.direct_resolution_count, 1_486)
  assert.equal(receipts.state.sourceReceipt.evidence.dangling_assignment_reference_count, 75_431)
  assert.equal(receipts.state.sourceReceipt.evidence.direct_resolution_batch_count, 6)
  assert.deepEqual(graphCalls, { LINEAGE: 1, METADATA: 1 })
  assert.equal(semanticAttempts, 2)
})

test('TEST-shaped graph-only retry reuses Source and Semantic then READY rerun is zero-work', async () => {
  const receipts = fakeReceiptPort({
    sourceReceipt: readySourceReceipt(snapshotA, {
      direct_resolution_count: 1_486,
      dangling_assignment_reference_count: 75_431,
    }),
    desired: {
      LINEAGE: desiredReceipt('LINEAGE', snapshotA, 'FAILED'),
      METADATA: desiredReceipt('METADATA', snapshotA, 'FAILED'),
      SEMANTIC: desiredReceipt('SEMANTIC', snapshotA),
    },
    active: {
      LINEAGE: activeReceipt('LINEAGE', snapshotB),
      METADATA: activeReceipt('METADATA', snapshotB),
      SEMANTIC: activeReceipt('SEMANTIC', snapshotA),
    },
  })
  const captureSource = mock.fn()
  const calls = { LINEAGE: 0, METADATA: 0, SEMANTIC: 0 }
  const implementations = Object.fromEntries(K9_V2_PROJECTOR_IDS.map((projectorId) => [
    projectorId,
    mock.fn(async (sourceReceipt) => {
      calls[projectorId] += 1
      receipts.state.desired[projectorId] = desiredReceipt(projectorId, sourceReceipt.source_snapshot_id)
      receipts.state.active[projectorId] = activeReceipt(projectorId, sourceReceipt.source_snapshot_id)
      return { status: 'READY', source_snapshot_id: sourceReceipt.source_snapshot_id }
    }),
  ]))
  const projectors = projectorPorts(receipts, implementations)
  const orchestrator = createK9V2LifecycleOrchestrator({ captureSource, receipts, projectors })

  const resumed = await orchestrator.run({ sourceRunMode: 'RESUME' })
  assert.equal(resumed.status, 'READY')
  assert.equal(resumed.source.outcome, 'REUSED')
  assert.equal(resumed.projectors.LINEAGE.outcome, 'PROJECTED')
  assert.equal(resumed.projectors.METADATA.outcome, 'PROJECTED')
  assert.equal(resumed.projectors.SEMANTIC.outcome, 'REUSED')
  assert.equal(captureSource.mock.calls.length, 0)
  assert.deepEqual(calls, { LINEAGE: 1, METADATA: 1, SEMANTIC: 0 })

  const rerun = await orchestrator.run({ sourceRunMode: 'RESUME' })
  assert.equal(rerun.status, 'READY')
  assert.equal(rerun.source.outcome, 'REUSED')
  assert.deepEqual(Object.fromEntries(K9_V2_PROJECTOR_IDS.map((projectorId) => [
    projectorId, rerun.projectors[projectorId].outcome,
  ])), { LINEAGE: 'REUSED', METADATA: 'REUSED', SEMANTIC: 'REUSED' })
  assert.equal(captureSource.mock.calls.length, 0)
  assert.deepEqual(calls, { LINEAGE: 1, METADATA: 1, SEMANTIC: 0 })
})

test('aggregate readiness fails closed when any desired or active receipt has a mixed snapshot ID', () => {
  const projectorReceipts = readyProjectorReceipts(snapshotA)
  projectorReceipts.METADATA = {
    desired: desiredReceipt('METADATA', snapshotA),
    active: activeReceipt('METADATA', snapshotB),
  }

  const readiness = evaluateK9V2AggregateReadiness({
    sourceReceipt: readySourceReceipt(snapshotA),
    projectorReceipts,
    expectedSourceSnapshotId: snapshotA,
  })

  assert.equal(readiness.status, 'NOT_READY')
  assert.equal(readiness.reason, 'K9_V2_MIXED_SOURCE_SNAPSHOT_IDS')
  assert.equal(readiness.projectors.LINEAGE.ready, true)
  assert.equal(readiness.projectors.METADATA.ready, false)
  assert.equal(readiness.projectors.SEMANTIC.ready, true)
})

test('a FAILED desired snapshot may preserve a stale active LKG without becoming a mixed-ID contradiction', () => {
  const projectorReceipts = readyProjectorReceipts(snapshotA)
  projectorReceipts.SEMANTIC = {
    desired: desiredReceipt('SEMANTIC', snapshotA, 'FAILED'),
    active: activeReceipt('SEMANTIC', snapshotB),
  }

  const readiness = evaluateK9V2AggregateReadiness({
    sourceReceipt: readySourceReceipt(snapshotA),
    projectorReceipts,
    expectedSourceSnapshotId: snapshotA,
  })

  assert.equal(readiness.status, 'NOT_READY')
  assert.equal(readiness.reason, 'K9_V2_AGGREGATE_NOT_READY')
  assert.equal(readiness.projectors.SEMANTIC.active, 'VALID')
  assert.equal(readiness.projectors.SEMANTIC.ready, false)
})

test('a projector result cannot declare READY without matching durable desired and active receipts', async () => {
  const pairs = readyProjectorReceipts(snapshotA)
  const receipts = fakeReceiptPort({
    sourceReceipt: readySourceReceipt(snapshotA),
    desired: { LINEAGE: pairs.LINEAGE.desired, METADATA: pairs.METADATA.desired },
    active: { LINEAGE: pairs.LINEAGE.active, METADATA: pairs.METADATA.active },
  })
  const projectors = projectorPorts(receipts, {
    SEMANTIC: mock.fn(async () => ({ status: 'READY', source_snapshot_id: snapshotA })),
  })

  const result = await createK9V2LifecycleOrchestrator({
    captureSource: mock.fn(), receipts, projectors,
  }).run()

  assert.equal(result.status, 'FAILED')
  assert.equal(result.failed_projector, 'SEMANTIC')
  assert.deepEqual(result.diagnostic, {
    code: 'K9_V2_PROJECTOR_RECEIPT_NOT_READY', stage: 'PROJECTOR_RECEIPT', retryable: true,
  })
  assert.equal(result.readiness.status, 'NOT_READY')
})

test('invalid READY source receipts fail closed without silently recollecting source data', async () => {
  const receipts = fakeReceiptPort({
    sourceReceipt: { status: 'READY', source_snapshot_id: snapshotA, source_snapshot: { source_snapshot_id: snapshotB } },
  })
  const captureSource = mock.fn()
  const projectors = projectorPorts(receipts)

  const result = await createK9V2LifecycleOrchestrator({
    captureSource, receipts, projectors,
  }).run()

  assert.equal(result.status, 'FAILED')
  assert.deepEqual(result.diagnostic, {
    code: 'K9_V2_SOURCE_RECEIPT_INVALID', stage: 'SOURCE_RECEIPT', retryable: false,
  })
  assert.equal(captureSource.mock.calls.length, 0)
  for (const projectorId of K9_V2_PROJECTOR_IDS) {
    assert.equal(projectors[projectorId].project.mock.calls.length, 0)
  }
})

test('source capture preserves bounded DataHub stage and detail without leaking provider errors', async () => {
  const receipts = fakeReceiptPort()
  const transitions = []
  const lineageProfile = {
    contract: 'DATARIVER_K9_LINEAGE_SOURCE_PROFILE_V1',
    total_asset_count: 1_892,
    processed_asset_count: 731,
    pages_fetched: 2,
    provider_relationship_total: 150,
    returned_relationship_count: 148,
    filtered_relationship_count: 1,
    failure: {
      detail_code: 'LINEAGE_COMPLETENESS_MISMATCH', direction: 'UPSTREAM',
      page_number: 2, request_start: 100, response_start: 100,
      response_count: 1, total: 150, filtered: 0, relationships: 1,
      identity_hash: 'd'.repeat(64),
    },
  }
  const captureSource = mock.fn(async () => {
    throw Object.assign(new Error('private provider response and token'), {
      k9FailureCode: 'K9_DATAHUB_SOURCE_FAILED',
      k9SourceDiagnostic: {
        failureStage: 'LINEAGE_COLLECTION',
        failureDetailCode: 'LINEAGE_COMPLETENESS_MISMATCH',
        lineageProfile,
        raw_urn: 'urn:li:glossaryTerm:must-not-survive',
      },
    })
  })
  const projectors = projectorPorts(receipts)

  const result = await createK9V2LifecycleOrchestrator({
    captureSource, receipts, projectors, onTransition: (event) => transitions.push(event),
  }).run()

  assert.equal(result.status, 'FAILED')
  assert.deepEqual(result.diagnostic, {
    code: 'K9_DATAHUB_SOURCE_FAILED',
    stage: 'LINEAGE_COLLECTION',
    failure_detail_code: 'LINEAGE_COMPLETENESS_MISMATCH',
    retryable: true,
    lineage_source_profile: {
      contract: 'DATARIVER_K9_LINEAGE_SOURCE_PROFILE_V1',
      total_asset_count: 1_892,
      processed_asset_count: 731,
      pages_fetched: 2,
      provider_relationship_total: 150,
      returned_relationship_count: 148,
      filtered_relationship_count: 1,
      projectable_table_edge_observation_count: 0,
      projectable_column_edge_observation_count: 0,
      outside_source_scope_relationship_count: 0,
      exact_duplicate_observation_count: 0,
      distinct_same_edge_observation_count: 0,
      failure: lineageProfile.failure,
    },
  })
  assert.deepEqual(transitions, [{
    stage: 'SOURCE', status: 'FAILED', diagnostic: result.diagnostic,
  }])
  assert.equal(JSON.stringify(result).includes('private provider'), false)
  assert.equal(JSON.stringify(result).includes('urn:li:'), false)
  for (const projectorId of K9_V2_PROJECTOR_IDS) {
    assert.equal(projectors[projectorId].project.mock.calls.length, 0)
  }
})

test('an interrupted durable source receipt is resumed from its immutable payload without an external recollection', async () => {
  const incomplete = Object.freeze({
    status: 'RUNNING',
    source_snapshot_id: snapshotA,
    source_snapshot: Object.freeze({ source_snapshot_id: snapshotA }),
    source_payloads: Object.freeze({ inventory: {}, lineage: {}, metadata: {}, dangling_state: {} }),
  })
  const receipts = fakeReceiptPort({ sourceReceipt: incomplete })
  let externalCollections = 0
  const captureSource = mock.fn(async ({ currentReceipt }) => {
    assert.equal(currentReceipt, incomplete)
    if (!currentReceipt?.source_snapshot || !currentReceipt?.source_payloads) externalCollections += 1
    return Object.freeze({ ...currentReceipt, status: 'READY' })
  })
  const projectors = projectorPorts(receipts)

  const result = await createK9V2LifecycleOrchestrator({
    captureSource, receipts, projectors,
  }).run()

  assert.equal(result.status, 'READY')
  assert.equal(result.source.outcome, 'CAPTURED')
  assert.equal(captureSource.mock.calls.length, 1)
  assert.equal(externalCollections, 0)
})
