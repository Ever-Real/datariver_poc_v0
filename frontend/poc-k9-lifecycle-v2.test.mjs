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

test('K9 V2 reuses a durable source and all independently READY desired/active receipts', async () => {
  const pairs = readyProjectorReceipts()
  const receipts = fakeReceiptPort({
    sourceReceipt: readySourceReceipt(),
    desired: Object.fromEntries(K9_V2_PROJECTOR_IDS.map((id) => [id, pairs[id].desired])),
    active: Object.fromEntries(K9_V2_PROJECTOR_IDS.map((id) => [id, pairs[id].active])),
  })
  const captureSource = mock.fn()
  const projectors = projectorPorts(receipts)

  const result = await createK9V2LifecycleOrchestrator({
    captureSource, receipts, projectors,
  }).run()

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
