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
  const projectorAttempts = { LINEAGE: 0, METADATA: 0, SEMANTIC: 0 }
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
      projectorAttempts[id] += 1
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
  const captureSource = mock.fn(async () => source())
  return {
    state,
    semanticAttempts: () => semanticAttempts,
    projectorAttempts,
    captureSource,
    trigger: createPocK9V2RefreshTask({
      captureSource,
      receipts,
      projectors,
    }),
  }
}

test('V2 RESUME reuses an aggregate READY snapshot without source or projector work', async () => {
  const value = fixture()

  assert.equal((await value.trigger()).status, 'SUCCESS')
  assert.equal((await value.trigger({ lifecycleMode: 'RESUME' })).status, 'SUCCESS')

  assert.equal(value.captureSource.mock.calls.length, 1)
  assert.deepEqual(value.projectorAttempts, { LINEAGE: 1, METADATA: 1, SEMANTIC: 1 })
  assert.equal(value.state.promoted, 2)
})

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

test('V2 trigger exposes the exact bounded source diagnostic before snapshot persistence', async () => {
  const value = fixture()
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
  value.trigger = createPocK9V2RefreshTask({
    captureSource: mock.fn(async () => {
      throw Object.assign(new Error('private DataHub response'), {
        k9FailureCode: 'K9_DATAHUB_SOURCE_FAILED',
        k9SourceDiagnostic: {
          failureStage: 'LINEAGE_COLLECTION',
          failureDetailCode: 'LINEAGE_COMPLETENESS_MISMATCH',
          lineageProfile,
        },
      })
    }),
    receipts: {
      ...value.state,
      async readSourceCaptureReceipt() { return null },
      async writeSourceCaptureReceipt() { throw new Error('must not persist') },
      async readProjectorDesiredReceipt() { return null },
      async readProjectorActiveReceipt() { return null },
      async promoteAggregate() { throw new Error('must not promote') },
    },
    projectors: Object.fromEntries(['LINEAGE', 'METADATA', 'SEMANTIC'].map((id) => [id, {
      async project() { throw new Error('must not project') },
    }])),
  })

  const result = await value.trigger()

  assert.deepEqual({
    status: result.status,
    failureCode: result.failureCode,
    failureStage: result.failureStage,
    failureDetailCode: result.failureDetailCode,
    lineageProfile: result.lineageProfile,
  }, {
    status: 'FAILURE',
    failureCode: 'K9_DATAHUB_SOURCE_FAILED',
    failureStage: 'LINEAGE_COLLECTION',
    failureDetailCode: 'LINEAGE_COMPLETENESS_MISMATCH',
    lineageProfile: {
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
  assert.equal(JSON.stringify(result).includes('private DataHub'), false)
})
