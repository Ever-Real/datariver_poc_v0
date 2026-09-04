/* global structuredClone */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { computeSha256 } from './poc-knowledge-k9-contracts.mjs'
import {
  buildK9ProjectorReceiptV2,
  createK9V2DurableProjector,
  createK9V2LifecycleReceiptPort,
  publicK9V2LifecycleStatus,
} from './poc-k9-lifecycle-runtime.mjs'

const snapshotId = 'a'.repeat(64)

function clock() {
  let tick = 0
  return () => new Date(Date.UTC(2026, 7, 31, 0, 0, tick++)).toISOString()
}

function fakeLifecycle() {
  const state = {
    desired_snapshot_id: null,
    active_snapshot_id: null,
    status: null,
    version: 0,
    desired_snapshot: null,
    desired_source_payloads: null,
    desired_projector_receipts: [],
    active_ready_projector_receipts: [],
  }
  return {
    state,
    async readLifecycle() {
      return state.desired_snapshot_id ? structuredClone(state) : null
    },
    async setDesiredSnapshot(value) {
      state.desired_snapshot_id = value.snapshot.source_snapshot_id
      state.desired_snapshot = structuredClone(value.snapshot)
      state.desired_source_payloads = {
        INVENTORY: structuredClone(value.source_payloads.inventory),
        LINEAGE: structuredClone(value.source_payloads.lineage),
        METADATA: structuredClone(value.source_payloads.metadata),
        DANGLING_STATE: structuredClone(value.source_payloads.dangling_state),
      }
      state.status = 'PENDING'
      state.version += 1
      return { sourceSnapshotId: state.desired_snapshot_id, version: state.version }
    },
    async appendProjectorReceipt(receipt) {
      const index = state.desired_projector_receipts.findIndex((item) => item.projector === receipt.projector)
      if (index >= 0) state.desired_projector_receipts[index] = structuredClone(receipt)
      else state.desired_projector_receipts.push(structuredClone(receipt))
      state.status = receipt.status === 'FAILED' ? 'FAILED' : 'RUNNING'
      state.version += 1
      return { created: true, receipt }
    },
    async promoteActiveSnapshot({ sourceSnapshotId, expectedVersion }) {
      assert.equal(sourceSnapshotId, state.desired_snapshot_id)
      assert.equal(expectedVersion, state.version)
      assert.equal(state.desired_projector_receipts.length, 4)
      assert.ok(state.desired_projector_receipts.every((item) => item.status === 'READY'))
      state.active_snapshot_id = sourceSnapshotId
      state.status = 'READY'
      state.active_ready_projector_receipts = structuredClone(state.desired_projector_receipts)
      state.version += 1
      return { promoted: true, version: state.version }
    },
  }
}

function sourceReceipt() {
  return {
    status: 'READY',
    source_snapshot_id: snapshotId,
    source_snapshot: { source_snapshot_id: snapshotId },
    source_payloads: { inventory: {}, lineage: {}, metadata: {}, dangling_state: {} },
  }
}

function readyReceipt(projectorId, previous, now) {
  let head = previous
  if (!head || head.status === 'FAILED') head = buildK9ProjectorReceiptV2({
    sourceSnapshotId: snapshotId, projectorId, status: 'PENDING', previous: head, recordedAt: now(),
  })
  if (head.status === 'PENDING') head = buildK9ProjectorReceiptV2({
    sourceSnapshotId: snapshotId,
    projectorId,
    status: 'RUNNING',
    previous: head,
    progress: { phase: 'PROJECTION', completed_units: 0, total_units: 1 },
    recordedAt: now(),
  })
  return buildK9ProjectorReceiptV2({
    sourceSnapshotId: snapshotId,
    projectorId,
    status: 'READY',
    previous: head,
    progress: { phase: 'READY', completed_units: 1, total_units: 1 },
    outputPointer: `k9://${projectorId.toLowerCase()}/${snapshotId}`,
    outputHash: computeSha256({ projectorId, snapshotId }),
    recordedAt: now(),
  })
}

test('source receipt port durably resumes immutable capture and promotes only four exact READY receipts', async () => {
  const lifecycle = fakeLifecycle()
  const now = clock()
  const port = createK9V2LifecycleReceiptPort({ lifecycle, clock: now })
  await port.writeSourceCaptureReceipt(sourceReceipt())

  const source = await port.readSourceCaptureReceipt()
  assert.equal(source.status, 'READY')
  assert.equal(source.source_snapshot_id, snapshotId)
  assert.deepEqual(source.source_payloads, { inventory: {}, lineage: {}, metadata: {}, dangling_state: {} })
  assert.deepEqual(lifecycle.state.desired_projector_receipts.map((item) => (
    [item.projector, item.status, item.sequence]
  )), [['SOURCE', 'READY', 3]])

  for (const projectorId of ['LINEAGE', 'METADATA', 'SEMANTIC']) {
    lifecycle.state.desired_projector_receipts.push(readyReceipt(projectorId, null, now))
  }
  await port.promoteAggregate(snapshotId)
  assert.equal(lifecycle.state.active_snapshot_id, snapshotId)
  assert.equal(lifecycle.state.status, 'READY')
})

test('verified unheaded source evidence outranks an older lifecycle head for zero-provider resume', async () => {
  const lifecycle = fakeLifecycle()
  await lifecycle.setDesiredSnapshot({
    snapshot: { source_snapshot_id: 'b'.repeat(64) },
    source_payloads: { inventory: { old: true }, lineage: {}, metadata: {}, dangling_state: {} },
  })
  lifecycle.readStagedSourceEvidence = async () => ({ ...sourceReceipt(), status: 'PENDING' })
  const port = createK9V2LifecycleReceiptPort({ lifecycle })
  const staged = await port.readSourceCaptureReceipt()
  assert.equal(staged.status, 'PENDING')
  assert.equal(staged.source_snapshot_id, snapshotId)
  assert.deepEqual(staged.source_payloads.inventory, {})
})

test('source receipt port rejects unowned persistence codes at its direct boundary', async () => {
  const lifecycle = fakeLifecycle()
  lifecycle.setDesiredSnapshot = async () => {
    throw Object.assign(new Error('private token and urn:li:dataset:private'), {
      code: 'PRIVATE_SECRET_CODE', constraint: 'private_secret_constraint',
    })
  }
  const port = createK9V2LifecycleReceiptPort({ lifecycle })
  await assert.rejects(port.writeSourceCaptureReceipt(sourceReceipt()), (error) => {
    assert.deepEqual(error.diagnostic, {
      code: 'K9_V2_SOURCE_RECEIPT_PERSISTENCE_FAILED',
      stage: 'SOURCE_RECEIPT',
      failure_detail_code: 'K9_SOURCE_PERSISTENCE_UNKNOWN',
      persistence_substage: 'LIFECYCLE_HEAD_WRITE',
      payload_kind: 'NONE',
      payload_bytes: 0,
      configured_limit_bytes: 0,
      sqlstate_class: 'NONE',
      constraint_name: 'NONE',
      retryable: true,
    })
    assert.equal(JSON.stringify(error.diagnostic).includes('PRIVATE'), false)
    assert.equal(JSON.stringify(error.diagnostic).includes('urn:li:'), false)
    return true
  })
})

test('durable projector records bounded failure, retries only itself, and exposes READY as active before aggregate promotion', async () => {
  const lifecycle = fakeLifecycle()
  const now = clock()
  const receiptPort = createK9V2LifecycleReceiptPort({ lifecycle, clock: now })
  await receiptPort.writeSourceCaptureReceipt(sourceReceipt())
  let attempts = 0
  const projector = createK9V2DurableProjector({
    projectorId: 'SEMANTIC',
    lifecycle,
    clock: now,
    progress(value) {
      const completed = value?.completed ?? (value?.stage === 'READY' ? 10 : 0)
      return { phase: value?.stage || 'SEMANTIC_INDEX', completed_units: completed, total_units: 10 }
    },
    output: () => ({
      output_pointer: `k9-semantic-v2://${snapshotId}`,
      output_hash: computeSha256({ semantic: snapshotId }),
    }),
    async materialize(_source, { onProgress }) {
      attempts += 1
      await onProgress({ stage: 'PROVIDER_REQUEST', completed: 5 })
      if (attempts === 1) {
        throw Object.assign(new Error('token=must-not-survive urn:li:dataset:private'), {
          diagnostic: {
            code: 'K9_SEMANTIC_PROVIDER_TIMEOUT',
            stage: 'PROVIDER_REQUEST',
            retryable: true,
            provider_failure_class: 'TIMEOUT',
            secret: 'must-not-survive',
          },
        })
      }
      await onProgress({ stage: 'MATERIALIZATION', completed: 10 })
      return { generation: snapshotId }
    },
  })

  await assert.rejects(projector.project(sourceReceipt()), {
    diagnostic: { code: 'K9_SEMANTIC_PROVIDER_TIMEOUT', stage: 'PROVIDER_REQUEST', retryable: true },
  })
  let failed = lifecycle.state.desired_projector_receipts.find((item) => item.projector === 'SEMANTIC')
  assert.equal(failed.status, 'FAILED')
  assert.deepEqual(failed.diagnostic, {
    code: 'K9_SEMANTIC_PROVIDER_TIMEOUT',
    stage: 'PROVIDER_REQUEST',
    detail_hash: null,
    provider_failure_class: 'TIMEOUT',
  })
  assert.equal(JSON.stringify(failed).includes('must-not-survive'), false)
  assert.equal(JSON.stringify(failed).includes('urn:li:'), false)

  const result = await projector.project(sourceReceipt())
  assert.equal(result.status, 'READY')
  assert.equal(attempts, 2)
  const desired = await receiptPort.readProjectorDesiredReceipt('SEMANTIC')
  const active = await receiptPort.readProjectorActiveReceipt('SEMANTIC')
  assert.equal(desired.status, 'READY')
  assert.equal(desired.receipt.attempt_number, 2)
  assert.equal(active.active_snapshot_id, snapshotId)
  failed = lifecycle.state.desired_projector_receipts.find((item) => item.projector === 'SEMANTIC')
  assert.equal(failed.status, 'READY')
})

test('durable projector resumes a stranded RUNNING receipt without creating a new attempt', async () => {
  const lifecycle = fakeLifecycle()
  const now = clock()
  const receiptPort = createK9V2LifecycleReceiptPort({ lifecycle, clock: now })
  await receiptPort.writeSourceCaptureReceipt(sourceReceipt())
  let metadata = buildK9ProjectorReceiptV2({
    sourceSnapshotId: snapshotId, projectorId: 'METADATA', status: 'PENDING', recordedAt: now(),
  })
  metadata = buildK9ProjectorReceiptV2({
    sourceSnapshotId: snapshotId,
    projectorId: 'METADATA',
    status: 'RUNNING',
    previous: metadata,
    progress: { phase: 'GRAPH_MAPPING', completed_units: 0, total_units: 122_241 },
    recordedAt: now(),
  })
  lifecycle.state.desired_projector_receipts.push(metadata)
  let invocations = 0
  const projector = createK9V2DurableProjector({
    projectorId: 'METADATA', lifecycle, clock: now,
    progress: (value) => ({
      phase: value?.stage || 'GRAPH_MAPPING',
      completed_units: value?.stage === 'READY' ? 122_241 : 0,
      total_units: 122_241,
    }),
    output: () => ({
      output_pointer: `k9-metadata-v2://${snapshotId}`,
      output_hash: computeSha256({ metadata: snapshotId }),
    }),
    async materialize() {
      invocations += 1
      return { generation: snapshotId }
    },
  })

  const result = await projector.project(sourceReceipt())
  const ready = lifecycle.state.desired_projector_receipts.find(
    (item) => item.projector === 'METADATA',
  )
  assert.equal(result.status, 'READY')
  assert.equal(invocations, 1)
  assert.equal(ready.status, 'READY')
  assert.equal(ready.attempt_number, metadata.attempt_number)
  assert.equal(ready.attempt_id, metadata.attempt_id)
})

test('projector receipt identity is deterministic for one exact transition and rejects skipped starts', () => {
  const value = {
    sourceSnapshotId: snapshotId,
    projectorId: 'LINEAGE',
    status: 'PENDING',
    recordedAt: '2026-08-31T00:00:00.000Z',
  }
  assert.deepEqual(buildK9ProjectorReceiptV2(value), buildK9ProjectorReceiptV2(value))
  assert.throws(() => buildK9ProjectorReceiptV2({ ...value, status: 'READY' }), {
    code: 'K9_PROJECTOR_TRANSITION_INVALID',
  })
})

test('public lifecycle status exposes bounded projector failure/progress and aggregate promotion only', async () => {
  const lifecycle = fakeLifecycle()
  const now = clock()
  const port = createK9V2LifecycleReceiptPort({ lifecycle, clock: now })
  await port.writeSourceCaptureReceipt(sourceReceipt())
  for (const projectorId of ['LINEAGE', 'METADATA']) {
    lifecycle.state.desired_projector_receipts.push(readyReceipt(projectorId, null, now))
  }
  let semantic = buildK9ProjectorReceiptV2({
    sourceSnapshotId: snapshotId, projectorId: 'SEMANTIC', status: 'PENDING', recordedAt: now(),
  })
  semantic = buildK9ProjectorReceiptV2({
    sourceSnapshotId: snapshotId,
    projectorId: 'SEMANTIC',
    status: 'RUNNING',
    previous: semantic,
    progress: {
      phase: 'EMBEDDING', completed_units: 32, total_units: 2003,
      documents_processed: 32, documents_changed: 2003, documents_materialized: 32,
      batch_number: 1, batch_total: 63,
    },
    recordedAt: now(),
  })
  semantic = buildK9ProjectorReceiptV2({
    sourceSnapshotId: snapshotId,
    projectorId: 'SEMANTIC',
    status: 'FAILED',
    previous: semantic,
    progress: semantic.progress,
    diagnostic: {
      code: 'K9_SEMANTIC_PROVIDER_TIMEOUT', stage: 'PROVIDER', detail_hash: null,
      provider_failure_class: 'TIMEOUT',
    },
    recordedAt: now(),
  })
  lifecycle.state.desired_projector_receipts.push(semantic)
  const failed = publicK9V2LifecycleStatus(lifecycle.state)
  assert.equal(failed.source.status, 'READY')
  assert.deepEqual(failed.projectors.SEMANTIC, {
    desired_snapshot_id: snapshotId,
    active_snapshot_id: null,
    status: 'FAILED',
    attempt: 1,
    progress: semantic.progress,
    diagnostic: {
      code: 'K9_SEMANTIC_PROVIDER_TIMEOUT',
      stage: 'PROVIDER',
      provider_failure_class: 'TIMEOUT',
    },
  })
  assert.deepEqual(failed.aggregate, {
    status: 'FAILED', reason: 'K9_SEMANTIC_PROVIDER_TIMEOUT',
  })
  assert.equal(JSON.stringify(failed).includes('urn:li:'), false)
  assert.equal(JSON.stringify(failed).includes('token'), false)

  lifecycle.state.desired_projector_receipts = lifecycle.state.desired_projector_receipts
    .filter((item) => item.projector !== 'SEMANTIC')
  lifecycle.state.desired_projector_receipts.push(readyReceipt('SEMANTIC', semantic, now))
  const unpromoted = publicK9V2LifecycleStatus(lifecycle.state)
  assert.deepEqual(unpromoted.aggregate, {
    status: 'NOT_READY', reason: 'K9_V2_AGGREGATE_NOT_PROMOTED',
  })
  await port.promoteAggregate(snapshotId)
  const ready = publicK9V2LifecycleStatus(lifecycle.state)
  assert.deepEqual(ready.aggregate, { status: 'READY', reason: null })
  assert.equal(ready.projectors.SEMANTIC.active_snapshot_id, snapshotId)
})

test('public lifecycle status is explicit before the first V2 source capture', () => {
  const status = publicK9V2LifecycleStatus(null)
  assert.equal(status.source.status, 'NOT_STARTED')
  assert.equal(status.aggregate.status, 'NOT_READY')
  assert.equal(status.projectors.LINEAGE.status, 'NOT_STARTED')
  assert.equal(status.projectors.METADATA.status, 'NOT_STARTED')
  assert.equal(status.projectors.SEMANTIC.status, 'NOT_STARTED')
})
