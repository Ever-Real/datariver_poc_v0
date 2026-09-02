import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { test } from 'node:test'

import {
  createK9LineageTrace,
  sanitizeK9LineageSourceProfile,
} from './poc-k9-lineage-collection.mjs'

const assetUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,fixture.lineage.table,PROD)'

function observationIdentity(value) {
  return createHash('sha256').update(JSON.stringify(value)).digest('hex')
}

function page({ start = 0, count = 100, total = 0, filtered = 0, relationships = [] } = {}) {
  return { start, count, total, filtered, relationships }
}

function failureDetail(action) {
  let captured
  assert.throws(action, (error) => {
    captured = error
    assert.equal(typeof error.message, 'string')
    assert.equal(error.message.includes(assetUrn), false)
    assert.ok(error.k9SourceFailureDetailCode)
    const profile = sanitizeK9LineageSourceProfile(error.k9LineageSourceProfile)
    assert.ok(profile)
    assert.equal(JSON.stringify(profile).includes(assetUrn), false)
    return true
  })
  return captured.k9SourceFailureDetailCode
}

test('accepts Actual-PREP filtered lineage accounting without weakening completeness', () => {
  const trace = createK9LineageTrace({ assetIdentity: assetUrn, direction: 'UPSTREAM' })
  const response = page({
    total: 4,
    filtered: 1,
    relationships: [{ id: 1 }, { id: 2 }, { id: 3 }],
  })

  const observed = trace.observePage(response)
  assert.equal(observed.done, true)
  assert.deepEqual(trace.complete(), {
    returned: 3,
    filtered: 1,
    total: 4,
    pages: 1,
    profile: trace.complete().profile,
  })
  assert.equal(trace.complete().profile.returned_relationship_count, 3)
  assert.equal(trace.complete().profile.filtered_relationship_count, 1)
  assert.equal(trace.complete().profile.failure, null)
})

test('accepts a fully filtered page and advances by the fixed request count', () => {
  const trace = createK9LineageTrace({ assetIdentity: assetUrn, direction: 'DOWNSTREAM' })
  const observed = trace.observePage(page({ total: 4, filtered: 4 }))

  assert.equal(observed.done, true)
  assert.deepEqual(trace.complete(), {
    returned: 0,
    filtered: 4,
    total: 4,
    pages: 1,
    profile: trace.complete().profile,
  })
})

test('accepts filtered relationships across multiple fixed-offset pages', () => {
  const trace = createK9LineageTrace({ assetIdentity: assetUrn, direction: 'UPSTREAM' })
  const first = trace.observePage(page({
    total: 150,
    filtered: 1,
    relationships: Array.from({ length: 99 }, (_, index) => ({ id: index })),
  }))
  assert.equal(first.done, false)
  assert.equal(trace.nextStart, 100)
  const second = trace.observePage(page({
    start: 100,
    total: 150,
    filtered: 1,
    relationships: Array.from({ length: 49 }, (_, index) => ({ id: index + 100 })),
  }))

  assert.equal(second.done, true)
  assert.deepEqual(trace.complete(), {
    returned: 148,
    filtered: 2,
    total: 150,
    pages: 2,
    profile: trace.complete().profile,
  })
})

test('preserves the unfiltered lineage page contract', () => {
  const trace = createK9LineageTrace({ assetIdentity: assetUrn, direction: 'UPSTREAM' })
  trace.observePage(page({ total: 3, relationships: [{ id: 1 }, { id: 2 }, { id: 3 }] }))
  const result = trace.complete()
  assert.equal(result.returned, 3)
  assert.equal(result.filtered, 0)
  assert.equal(result.total, 3)
})

test('fails typed when total drifts between pages', () => {
  const trace = createK9LineageTrace({ assetIdentity: assetUrn, direction: 'UPSTREAM' })
  trace.observePage(page({
    total: 150,
    relationships: Array.from({ length: 100 }, (_, index) => ({ id: index })),
  }))
  assert.equal(failureDetail(() => trace.observePage(page({
    start: 100, total: 151, relationships: [{ id: 100 }],
  }))), 'LINEAGE_TOTAL_DRIFT')
})

test('fails typed on an unexplained empty page', () => {
  const trace = createK9LineageTrace({ assetIdentity: assetUrn, direction: 'UPSTREAM' })
  assert.equal(
    failureDetail(() => trace.observePage(page({ total: 4 }))),
    'LINEAGE_PAGE_GAP',
  )
})

test('fails typed on malformed page fields without exposing identity', () => {
  const trace = createK9LineageTrace({ assetIdentity: assetUrn, direction: 'UPSTREAM' })
  assert.equal(failureDetail(() => trace.observePage({
    start: 0, count: 100, total: 1, relationships: [],
  })), 'LINEAGE_RESPONSE_MALFORMED')
})

test('fails typed on a malformed returned relationship without exposing identity', () => {
  const trace = createK9LineageTrace({ assetIdentity: assetUrn, direction: 'UPSTREAM' })
  trace.observePage(page({ total: 1, relationships: [{ entity: null }] }))
  assert.equal(
    failureDetail(() => trace.rejectMalformedRelationship()),
    'LINEAGE_RESPONSE_MALFORMED',
  )
})

test('deduplicates exact same-page observations and merges distinct observations per edge', () => {
  const trace = createK9LineageTrace({ assetIdentity: assetUrn, direction: 'UPSTREAM' })
  trace.observePage(page({ total: 3, relationships: [{}, {}, {}] }))
  const exact = observationIdentity({ edge: 'a', type: 'TRANSFORMED', updated: 1 })
  const distinct = observationIdentity({ edge: 'a', type: 'COPY', updated: 2 })

  assert.equal(trace.observeRelationship({ observationIdentity: exact, edgeIdentity: 'a->b' }), 'NEW_EDGE')
  assert.equal(trace.observeRelationship({ observationIdentity: exact, edgeIdentity: 'a->b' }), 'EXACT_DUPLICATE')
  assert.equal(trace.observeRelationship({ observationIdentity: distinct, edgeIdentity: 'a->b' }), 'DISTINCT_OBSERVATION')
  assert.equal(trace.complete().profile.exact_duplicate_observation_count, 1)
  assert.equal(trace.complete().profile.distinct_same_edge_observation_count, 1)
})

test('keeps provider filtering, source-scope exclusions, and projectable observations separate', () => {
  const trace = createK9LineageTrace({ assetIdentity: assetUrn, direction: 'UPSTREAM' })
  trace.observePage(page({ total: 4, filtered: 1, relationships: [{}, {}, {}] }))
  trace.recordProjectableTableEdge()
  trace.recordProjectableColumnEdge()
  trace.recordOutsideSourceScope()

  const profile = trace.complete().profile
  assert.equal(profile.filtered_relationship_count, 1)
  assert.equal(profile.projectable_table_edge_observation_count, 1)
  assert.equal(profile.projectable_column_edge_observation_count, 1)
  assert.equal(profile.outside_source_scope_relationship_count, 1)
})

test('fails typed when an exact observation reappears at a later provider offset', () => {
  const trace = createK9LineageTrace({ assetIdentity: assetUrn, direction: 'UPSTREAM' })
  const identity = observationIdentity({ edge: 'a', type: 'TRANSFORMED' })
  trace.observePage(page({
    total: 101,
    relationships: Array.from({ length: 100 }, (_, index) => ({ id: index })),
  }))
  assert.equal(trace.observeRelationship({ observationIdentity: identity, edgeIdentity: 'a->b' }), 'NEW_EDGE')
  trace.observePage(page({ start: 100, total: 101, relationships: [{ id: 0 }] }))
  assert.equal(failureDetail(() => trace.observeRelationship({
    observationIdentity: identity, edgeIdentity: 'a->b',
  })), 'LINEAGE_DUPLICATE_REPLAY')
})

test('fails typed when final returned plus filtered accounting is incomplete', () => {
  const trace = createK9LineageTrace({ assetIdentity: assetUrn, direction: 'UPSTREAM' })
  trace.observePage(page({
    total: 101,
    relationships: Array.from({ length: 99 }, (_, index) => ({ id: index })),
  }))
  trace.observePage(page({ start: 100, total: 101, relationships: [{ id: 100 }] }))
  assert.equal(failureDetail(() => trace.complete()), 'LINEAGE_COMPLETENESS_MISMATCH')
})

test('supports an Actual-PREP-shaped 1,892 Dataset inventory without identity leakage', () => {
  const identities = Array.from({ length: 1_892 }, (_, index) => (
    `urn:li:dataset:(urn:li:dataPlatform:postgres,fixture.table_${index},PROD)`
  ))
  for (let index = 0; index < identities.length; index += 1) {
    const trace = createK9LineageTrace({
      assetIdentity: identities[index],
      direction: 'UPSTREAM',
      totalAssetCount: identities.length,
      processedAssetCount: index,
    })
    trace.observePage(page())
    const result = trace.complete()
    assert.equal(result.profile.total_asset_count, 1_892)
    assert.equal(result.profile.processed_asset_count, index)
  }
})
