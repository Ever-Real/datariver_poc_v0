import assert from 'node:assert/strict'
import { test } from 'node:test'

import { computeSha256 } from './poc-knowledge-k9-contracts.mjs'
import {
  buildK9ProjectorReceiptV2,
  createK9V2DurableProjector,
  createK9V2LifecycleReceiptPort,
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
