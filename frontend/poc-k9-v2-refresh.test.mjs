import assert from 'node:assert/strict'
import { mock, test } from 'node:test'

import { createPocK9V2RefreshTask } from './poc-k9-v2-refresh.mjs'

const snapshotId = 'a'.repeat(64)

function source() {
  return Object.freeze({
    status: 'READY',
    source_snapshot_id: snapshotId,
    source_snapshot: Object.freeze({ source_snapshot_id: snapshotId }),
  })
}

function desired(projectorId, status = 'READY') {
  return { projector_id: projectorId, desired_snapshot_id: snapshotId, source_snapshot_id: snapshotId, status }
}

function active(projectorId) {
  return { projector_id: projectorId, active_snapshot_id: snapshotId, source_snapshot_id: snapshotId, status: 'READY' }
}

function fixture({ failSemanticOnce = false, promotionFailure = false } = {}) {
  const state = { source: null, desired: {}, active: {}, promoted: 0 }
  let semanticAttempts = 0
  const receipts = {
    state,
    async readSourceCaptureReceipt() { return state.source },
    async writeSourceCaptureReceipt(value) { state.source = value },
    async readProjectorDesiredReceipt(id) { return state.desired[id] },
    async readProjectorActiveReceipt(id) { return state.active[id] },
    async promoteAggregate(id) {
      assert.equal(id, snapshotId)
      if (promotionFailure) throw new Error('private database detail')
      state.promoted += 1
    },
  }
  const projectors = Object.fromEntries(['LINEAGE', 'METADATA', 'SEMANTIC'].map((id) => [id, {
    async project(receipt) {
      assert.equal(receipt.source_snapshot_id, snapshotId)
      if (id === 'SEMANTIC') {
        semanticAttempts += 1
        if (failSemanticOnce && semanticAttempts === 1) {
          state.desired[id] = desired(id, 'FAILED')
          throw Object.assign(new Error('raw provider token'), {
            diagnostic: { code: 'K9_SEMANTIC_PROVIDER_TIMEOUT', stage: 'PROVIDER', retryable: true },
          })
        }
      }
      state.desired[id] = desired(id)
      state.active[id] = active(id)
      return { status: 'READY', source_snapshot_id: snapshotId }
    },
  }]))
  return {
    state,
    semanticAttempts: () => semanticAttempts,
    trigger: createPocK9V2RefreshTask({
      captureSource: mock.fn(async () => source()),
      receipts,
      projectors,
    }),
  }
}

test('V2 scheduler trigger promotes aggregate only after a Semantic-only retry reaches exact READY', async () => {
  const value = fixture({ failSemanticOnce: true })
  const first = await value.trigger()
  assert.equal(first.status, 'FAILURE')
  assert.equal(first.failureCode, 'K9_SEMANTIC_PROVIDER_TIMEOUT')
  assert.equal(first.failureStage, 'PROVIDER')
  assert.equal(value.state.promoted, 0)
  assert.equal(JSON.stringify(first).includes('raw provider'), false)

  const retry = await value.trigger()
  assert.equal(retry.status, 'SUCCESS')
  assert.equal(retry.source_snapshot_id, snapshotId)
  assert.equal(value.state.promoted, 1)
  assert.equal(value.semanticAttempts(), 2)
})

test('aggregate pointer failure remains fail-closed after every projector is READY', async () => {
  const value = fixture({ promotionFailure: true })
  const result = await value.trigger()
  assert.deepEqual({
    status: result.status,
    code: result.failureCode,
    stage: result.failureStage,
    promoted: value.state.promoted,
  }, {
    status: 'FAILURE',
    code: 'K9_V2_AGGREGATE_PROMOTION_FAILED',
    stage: 'AGGREGATE_READINESS',
    promoted: 0,
  })
  assert.equal(JSON.stringify(result).includes('private database'), false)
})
