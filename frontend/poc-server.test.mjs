/* global Buffer, Response, fetch, setTimeout, structuredClone */
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { EventEmitter } from 'node:events'
import process from 'node:process'
import { after, before, test } from 'node:test'
import { URL, URLSearchParams } from 'node:url'

let server
let origin

function testAuthenticator(subjectId) {
  return {
    async authenticate() { return { subjectId, tokenHash: 'f'.repeat(64) } },
    assertOrigin() {},
    clearCookie() { return 'datariver_poc_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0' },
    async logout() {},
    setCookie(token) { return `datariver_poc_session=${token}; HttpOnly; SameSite=Strict; Path=/` },
  }
}

before(async () => {
  Object.assign(process.env, {
    POC_ENV_FILE: 'poc-server.test.env.missing',
    POC_DATABASE_URL: '',
    POC_POSTGRES_HOST: '',
    POC_REDIS_URL: '',
  })
  const { createPocStateStore } = await import('./poc-state-store.mjs?fallback-contract-test')
  const { createPocServer } = await import('./poc-server.mjs?fallback-contract-test')
  const stateStore = createPocStateStore()
  await stateStore.write('change-history-access-v1', {
    schema_version: 1,
    active_subject_id: 'test-subject',
    users: [{ subject_id: 'test-subject', role: 'admin', active: true, provider_owner_refs: [] }],
    system_assignments: [],
  })
  server = createPocServer({ stateStore, authenticator: testAuthenticator('test-subject') })
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  assert.equal(typeof address, 'object')
  origin = `http://127.0.0.1:${address.port}`
})

after(async () => {
  server.closeAllConnections()
  await new Promise((resolvePromise, reject) => server.close((error) => error ? reject(error) : resolvePromise()))
})

test('binds graph and semantic projections to one deterministic DataHub source snapshot', async () => {
  const {
    buildDatahubKnowledgeSourceFingerprint,
    buildDatahubKnowledgeSourceSnapshot,
  } = await import('./poc-server.mjs?kg2-source-snapshot-contract')
  const generation = '1'.repeat(64)
  const bindingHash = '2'.repeat(64)
  const input = {
    inventoryProjection: { source_generation: generation, observed_at: '2026-08-24T00:00:00.000Z' },
    datahubIdentity: { version: 'v1.6.0', commit: 'source-commit' },
    lineageSource: { nodes: [{ id: 'table-a' }], edges: [], completeness_metadata: {} },
    metadataSource: {
      table_nodes: [{ id: 'table-a' }], column_nodes: [], table_column_edges: [],
      terms: [], parent_nodes: [], term_parent_edges: [], node_parent_edges: [],
      glossary_relationships: [], table_assignments: [], column_assignments: [],
      tags: [], domains: [], containers: [], platform_instances: [],
      table_tag_assignments: [], column_tag_assignments: [], table_domain_assignments: [],
      table_container_assignments: [], table_platform_instance_assignments: [],
      completeness_metadata: {},
    },
    semanticIndex: { bindingHash, generation },
  }
  const first = buildDatahubKnowledgeSourceSnapshot(input)
  const firstFingerprint = buildDatahubKnowledgeSourceFingerprint(input)
  const observedLater = buildDatahubKnowledgeSourceSnapshot({
    ...input,
    inventoryProjection: { ...input.inventoryProjection, observed_at: '2026-08-24T01:00:00.000Z' },
  })
  assert.equal(first.source_snapshot_id, observedLater.source_snapshot_id)
  assert.equal(first.source_fingerprint_id, firstFingerprint.source_fingerprint_id)
  assert.notEqual(first.observed_at, observedLater.observed_at)
  assert.equal(first.semantic_index_generation, generation)
  assert.equal(first.semantic_index_binding_hash, bindingHash)
  assert.notEqual(buildDatahubKnowledgeSourceSnapshot({
    ...input,
    metadataSource: { ...input.metadataSource, tags: [{ urn: 'urn:li:tag:new' }] },
  }).source_snapshot_id, first.source_snapshot_id)
  assert.notEqual(buildDatahubKnowledgeSourceFingerprint({
    ...input,
    inventoryProjection: { ...input.inventoryProjection, source_generation: '4'.repeat(64) },
  }).source_fingerprint_id, firstFingerprint.source_fingerprint_id)
  assert.notEqual(buildDatahubKnowledgeSourceFingerprint({
    ...input,
    lineageSource: { ...input.lineageSource, edges: [{ source_asset_id: 'a', target_asset_id: 'b' }] },
  }).source_fingerprint_id, firstFingerprint.source_fingerprint_id)
  assert.notEqual(buildDatahubKnowledgeSourceFingerprint({
    ...input,
    metadataSource: { ...input.metadataSource, tags: [{ urn: 'urn:li:tag:generic' }] },
  }).source_fingerprint_id, firstFingerprint.source_fingerprint_id)
  assert.throws(() => buildDatahubKnowledgeSourceSnapshot({
    ...input,
    semanticIndex: { bindingHash, generation: '3'.repeat(64) },
  }), /semantic index is not bound/)
})

test('fingerprints a stable large generic source without fixed cardinality assumptions', async () => {
  const { buildDatahubKnowledgeSourceFingerprint } = await import('./poc-server.mjs?large-source-fingerprint-contract')
  const nodes = Array.from({ length: 1_001 }, (_value, index) => ({ id: `urn:synthetic:${index}` }))
  const edges = Array.from({ length: 1_951 }, (_value, index) => ({
    source_asset_id: nodes[index % nodes.length].id,
    target_asset_id: nodes[(index + 1) % nodes.length].id,
  }))
  const input = {
    inventoryProjection: { source_generation: '5'.repeat(64) },
    datahubIdentity: { version: 'v1.6.0', commit: null },
    lineageSource: { nodes, edges, completeness_metadata: { stable: true } },
    metadataSource: {
      table_nodes: nodes, column_nodes: [], table_column_edges: [], terms: [], parent_nodes: [],
      term_parent_edges: [], node_parent_edges: [], glossary_relationships: [],
      table_assignments: [], column_assignments: [], tags: [], domains: [], containers: [],
      platform_instances: [], table_tag_assignments: [], column_tag_assignments: [],
      table_domain_assignments: [], table_container_assignments: [],
      table_platform_instance_assignments: [], completeness_metadata: { stable: true },
    },
  }
  const first = buildDatahubKnowledgeSourceFingerprint(input)
  const second = buildDatahubKnowledgeSourceFingerprint(structuredClone(input))
  assert.match(first.source_fingerprint_id, /^[0-9a-f]{64}$/)
  assert.equal(first.source_fingerprint_id, second.source_fingerprint_id)
})

test('managed K9 failure status preserves LKG and never exposes an unbound semantic index as READY', async () => {
  const { managedK9AssetSummary } = await import('./poc-server.mjs?k9-failure-summary-contract')
  const base = {
    graph_id: '01a02d2a-f8a0-7658-b5da-890eccdccf44',
    name: 'CATALOG_MIRROR',
    classification: 'INTERNAL',
    studio_release_id: '01a02d2a-f8ad-789f-acb0-7df3ea3d0ef0',
    publication_version: 6,
    schedule: '02:00 Asia/Seoul',
    managed_intent: 'metadata-lineage',
    latest_result: 'FAILURE',
    latest_error_message: 'K9_SEMANTIC_INDEX_FAILED: Shared managed refresh failed at a classified stage.',
    latest_completed_at: '2026-08-28T00:00:00.000Z',
    created_at: '2026-08-27T00:00:00.000Z',
    updated_at: '2026-08-28T00:00:00.000Z',
  }
  const semanticIndex = {
    ready: true,
    contract: 'POC_DATAHUB_SEMANTIC_DOCUMENT_V3',
    bindingHash: 'b'.repeat(64),
    generation: 'g'.repeat(64),
  }

  const withoutLkg = managedK9AssetSummary(base, semanticIndex, null)
  assert.equal(withoutLkg.status, 'FAILED')
  assert.equal(withoutLkg.last_error_code, 'K9_SEMANTIC_INDEX_FAILED')
  assert.equal(withoutLkg.semantic_index_status, 'PENDING')
  assert.equal(withoutLkg.active_release_id, null)

  const withLkg = managedK9AssetSummary({
    ...base,
    active_release_pointer: 'k9_stage_existing_lkg',
    active_manifest: {
      source_snapshot: { catalog_generation: semanticIndex.generation },
      node_count: 2,
      edge_count: 1,
    },
  }, semanticIndex, null)
  assert.equal(withLkg.status, 'READY_WITH_REFRESH_FAILURE')
  assert.equal(withLkg.last_error_code, 'K9_SEMANTIC_INDEX_FAILED')
  assert.equal(withLkg.semantic_index_status, 'READY')
  assert.equal(withLkg.active_release_id, 'k9_stage_existing_lkg')
})

test('managed K9 resume reports an active descendant attempt instead of a retained terminal failure', async () => {
  const { managedK9AssetSummary } = await import('./poc-server.mjs?k9-active-retry-summary-contract')
  const summary = managedK9AssetSummary({
    graph_id: '01a02d2a-f8a0-7658-b5da-890eccdccf44',
    name: 'CATALOG_MIRROR',
    classification: 'INTERNAL',
    studio_release_id: '01a02d2a-f8ad-789f-acb0-7df3ea3d0ef0',
    publication_version: 6,
    schedule: '02:00 Asia/Seoul',
    managed_intent: 'metadata-lineage',
    latest_result: 'FAILURE',
    latest_error_message: 'K9_DATAHUB_SOURCE_FAILED: failure_stage=METADATA_COLLECTION; failure_detail_code=METADATA_IDENTITY_CONFLICT.',
    latest_completed_at: '2026-08-28T00:00:00.000Z',
    created_at: '2026-08-27T00:00:00.000Z',
    updated_at: '2026-08-28T00:00:00.000Z',
  }, { ready: false }, null, false, {
    status: 'RUNNING',
    scheduled_for: '2026-08-27T17:00:00.000Z',
    trigger: 'scheduled',
  })

  assert.equal(summary.status, 'PENDING')
  assert.equal(summary.last_result, 'RUNNING')
  assert.equal(summary.last_error_code, null)
  assert.deepEqual(summary.refresh_attempt, {
    status: 'RUNNING',
    scheduled_for: '2026-08-27T17:00:00.000Z',
    trigger: 'scheduled',
  })
  assert.equal(summary.semantic_index_status, 'PENDING')
})

test('managed K9 scheduler read model separates configured boundaries from durable receipts', async () => {
  const { managedK9SchedulerReadModel } = await import('./poc-server.mjs?k9-scheduler-read-model-contract')
  const config = {
    requested: true, enabled: true, refreshMode: 'DAILY', schedule: '02:15 Asia/Seoul',
    timeZone: 'Asia/Seoul', scheduleHour: 2, scheduleMinute: 15,
  }
  const readModel = managedK9SchedulerReadModel(config, { version: 4, value: {
    last_successful_schedule: '2026-08-28T17:15:00.000Z',
    last_attempt: {
      status: 'FAILURE', reason: 'K9_METADATA_REFRESH_FAILED',
      scheduled_for: '2026-08-29T17:15:00.000Z', completed_at: '2026-08-29T17:16:00.000Z',
      trigger: 'scheduled', internal_detail: 'must not escape',
    },
  } }, null, new Date('2026-08-29T18:00:00.000Z'))
  assert.deepEqual(readModel, {
    scheduler_status: 'SCHEDULED', scheduler_requested: true, scheduler_timer_enabled: true,
    schedule: '02:15 Asia/Seoul', schedule_timezone: 'Asia/Seoul',
    next_scheduled_run: '2026-08-30T17:15:00.000Z',
    last_successful_schedule: '2026-08-28T17:15:00.000Z',
    scheduler_last_attempt: {
      status: 'FAILURE', reason: 'K9_METADATA_REFRESH_FAILED',
      scheduled_for: '2026-08-29T17:15:00.000Z', completed_at: '2026-08-29T17:16:00.000Z',
      trigger: 'scheduled',
    },
  })
  assert.equal(JSON.stringify(readModel).includes('internal_detail'), false)
})

test('managed K9 scheduler status distinguishes active, on-demand, disabled, and unavailable states', async () => {
  const { managedK9SchedulerReadModel } = await import('./poc-server.mjs?k9-scheduler-state-contract')
  const base = {
    refreshMode: 'MANUAL', schedule: 'MANUAL', timeZone: 'Asia/Seoul', scheduleHour: 2, scheduleMinute: 0,
  }
  assert.equal(managedK9SchedulerReadModel({ ...base, requested: true, enabled: false }).scheduler_status, 'ON_DEMAND')
  assert.equal(managedK9SchedulerReadModel({ ...base, requested: false, enabled: false }).scheduler_status, 'DISABLED')
  assert.equal(managedK9SchedulerReadModel({ ...base, requested: true, enabled: false }, null, {
    status: 'RUNNING', scheduled_for: '2026-08-29T00:00:00.000Z', trigger: 'manual',
  }).scheduler_status, 'RUNNING')
  assert.equal(managedK9SchedulerReadModel(null).scheduler_status, 'UNAVAILABLE')
})

test('DataHub glossary scroll reconciliation rejects unstable or truncated provider pages', async () => {
  const { reconcileDatahubGlossaryScrollPage } = await import('./poc-server.mjs?glossary-scroll-reconciliation')
  const first = reconcileDatahubGlossaryScrollPage({
    count: 1,
    total: 2,
    nextScrollId: 'page-2',
    searchResults: [{ entity: { urn: 'urn:li:glossaryTerm:first' } }],
  })
  assert.deepEqual(first, { total: 2, fetched: 1, cursor: 'page-2', complete: false })
  assert.deepEqual(reconcileDatahubGlossaryScrollPage({
    count: 1,
    total: 2,
    nextScrollId: null,
    searchResults: [{ entity: { urn: 'urn:li:glossaryTerm:second' } }],
  }, first), { total: 2, fetched: 2, cursor: null, complete: true })

  assert.throws(() => reconcileDatahubGlossaryScrollPage({
    count: 1, total: 3, nextScrollId: 'page-3', searchResults: [{}],
  }, first), /metadata changed/)
  assert.throws(() => reconcileDatahubGlossaryScrollPage({
    count: 1, total: 2, nextScrollId: null, searchResults: [{}],
  }), /did not make progress/)
  assert.throws(() => reconcileDatahubGlossaryScrollPage({
    count: 2, total: 2, nextScrollId: null, searchResults: [{}],
  }), /metadata changed/)
  assert.throws(() => reconcileDatahubGlossaryScrollPage({
    count: 1, total: 1, nextScrollId: 'unexpected', searchResults: [{}],
  }), /continued after/)
})

test('managed K9 source failure exposes only bounded durable source diagnostics', async () => {
  const { managedK9AssetSummary } = await import('./poc-server.mjs?k9-source-diagnostic-summary')
  const summary = managedK9AssetSummary({
    graph_id: '01a02d2a-f8a0-7658-b5da-890eccdccf44',
    name: 'CATALOG_MIRROR',
    classification: 'INTERNAL',
    studio_release_id: '01a02d2a-f8ad-789f-acb0-7df3ea3d0ef0',
    publication_version: 6,
    schedule: '02:00 Asia/Seoul',
    managed_intent: 'metadata-lineage',
    latest_result: 'FAILURE',
    latest_error_message: 'K9_DATAHUB_SOURCE_FAILED: failure_stage=METADATA_COLLECTION; failure_detail_code=DUPLICATE_TERM_IDENTITY.',
    latest_manifest: { failure_diagnostic: { metadata_source_profile: {
      contract: 'DATARIVER_K9_METADATA_SOURCE_PROFILE_V1',
      source_generation: 'a'.repeat(64),
      inventory: { total_dataset_count: 2, table_count: 2, non_empty: true },
      identity_resolution: {
        exact_duplicate_observation_count: 1,
        failure: {
          locus: 'DUPLICATE_TERM_IDENTITY',
          classification: 'EXACT_DUPLICATE',
          identity_hash: 'b'.repeat(64),
          shape_hash: 'c'.repeat(64),
          page_number: 1,
          ordinal: 1,
        },
      },
    } } },
    latest_completed_at: '2026-08-28T00:00:00.000Z',
    created_at: '2026-08-27T00:00:00.000Z',
    updated_at: '2026-08-28T00:00:00.000Z',
  }, { ready: false }, null, true)

  assert.equal(summary.last_error_code, 'K9_DATAHUB_SOURCE_FAILED')
  assert.equal(summary.failure_stage, 'METADATA_COLLECTION')
  assert.equal(summary.failure_detail_code, 'DUPLICATE_TERM_IDENTITY')
  assert.equal(summary.metadata_source_profile.identity_resolution.failure.classification, 'EXACT_DUPLICATE')
  assert.equal(summary.metadata_source_profile.identity_resolution.failure.identity_hash, 'b'.repeat(64))
  assert.equal(JSON.stringify(summary).includes('urn:li:'), false)
})

test('public DataHub asset projection strips bounded internal K9 tag provenance', async () => {
  const { publicDatahubAsset } = await import('./poc-server.mjs?k9-tag-provenance-boundary')
  const asset = publicDatahubAsset({
    id: 'bounded-test-asset',
    tag_references: [{
      urn: 'urn:li:tag:datariver_classification_internal',
      name: 'CLASSIFICATION:INTERNAL',
      description: 'Internal',
      _k9_name_source: 'PROPERTIES',
    }],
  })

  assert.deepEqual(asset.tag_references, [{
    urn: 'urn:li:tag:datariver_classification_internal',
    name: 'CLASSIFICATION:INTERNAL',
    description: 'Internal',
  }])
  assert.equal(JSON.stringify(asset).includes('_k9_name_source'), false)
  assert.equal(JSON.stringify(asset).includes('PROPERTIES'), false)
})

test('normalizes only controlled DataHub manual-metadata read-back fields', async () => {
  const { manualMetadataAspectComparableDocument } = await import('./poc-server.mjs?manual-metadata-readback-contract')
  const auditStamp = { actor: 'urn:li:corpuser:datahub', time: 1 }

  assert.deepEqual(
    manualMetadataAspectComparableDocument('domains', {}, { observed: true, absent: true }),
    { domains: [] },
  )
  assert.deepEqual(
    manualMetadataAspectComparableDocument('domains', { domains: [] }, { observed: true }),
    { domains: [] },
  )
  assert.deepEqual(
    manualMetadataAspectComparableDocument('glossaryTerms', {}, { observed: true, absent: true }),
    { terms: [] },
  )
  assert.deepEqual(
    manualMetadataAspectComparableDocument('glossaryTerms', { terms: [], auditStamp }, { observed: true }),
    { terms: [] },
  )
  const controlledTerms = { terms: [{ urn: 'urn:li:glossaryTerm:controlled' }] }
  assert.deepEqual(
    manualMetadataAspectComparableDocument('glossaryTerms', {
      ...controlledTerms,
      auditStamp: { ...auditStamp, time: 2 },
    }, { observed: true }),
    manualMetadataAspectComparableDocument('glossaryTerms', controlledTerms),
  )

  for (const [aspectName, document, options] of [
    ['domains', {}, { observed: true }],
    ['domains', { domains: [], unexpected: true }, { observed: true }],
    ['glossaryTerms', { terms: [] }, { observed: true }],
    ['glossaryTerms', { terms: 'invalid', auditStamp }, { observed: true }],
    ['glossaryTerms', { terms: [], auditStamp, unexpected: true }, { observed: true }],
    ['glossaryTerms', { terms: [], auditStamp: { actor: 'invalid', time: 1 } }, { observed: true }],
  ]) {
    assert.throws(
      () => manualMetadataAspectComparableDocument(aspectName, document, options),
      { statusCode: 502, detailCode: 'DATAHUB_READBACK_MALFORMED' },
    )
  }

  const otherAspect = { description: 'controlled', auditStamp }
  assert.deepEqual(
    manualMetadataAspectComparableDocument('datasetProperties', otherAspect, { observed: true }),
    otherAspect,
  )
  assert.notStrictEqual(
    manualMetadataAspectComparableDocument('datasetProperties', otherAspect, { observed: true }),
    otherAspect,
  )
  assert.notDeepEqual(
    manualMetadataAspectComparableDocument('datasetProperties', otherAspect, { observed: true }),
    manualMetadataAspectComparableDocument('datasetProperties', {
      ...otherAspect,
      auditStamp: { ...auditStamp, time: 2 },
    }, { observed: true }),
  )
})

test('omits missing database metadata instead of inventing a hierarchy branch', async () => {
  const { catalogDatabaseBranchLabel } = await import('./poc-server.mjs?catalog-database-label-contract')

  assert.equal(catalogDatabaseBranchLabel('FINANCE', 'oracle'), 'FINANCE')
  assert.equal(catalogDatabaseBranchLabel('', 'postgres'), '')
  assert.equal(catalogDatabaseBranchLabel('', ''), '')
})

test('accepts only bounded DataHub lineage direction and depth', async () => {
  const { datahubLineageProjectionOptions } = await import('./poc-server.mjs?lineage-projection-contract')

  assert.deepEqual(
    datahubLineageProjectionOptions(new URLSearchParams('direction=downstream&depth=2')),
    { direction: 'DOWNSTREAM', depth: 2 },
  )
  assert.deepEqual(datahubLineageProjectionOptions(new URLSearchParams()), { direction: 'BOTH', depth: 1 })
  assert.throws(
    () => datahubLineageProjectionOptions(new URLSearchParams('direction=SIDEWAYS&depth=2')),
    { statusCode: 400, code: 'LINEAGE_DIRECTION_INVALID' },
  )
  assert.throws(
    () => datahubLineageProjectionOptions(new URLSearchParams('direction=UPSTREAM&depth=3')),
    { statusCode: 400, code: 'LINEAGE_DEPTH_INVALID' },
  )
})

test('semantic route plans preserve GENERAL/VECTOR/GRAPH boundaries and graph Asset capability selection', async () => {
  const { parseChatRouteDecision } = await import('./poc-server.mjs?semantic-route-contract')
  const asset = {
    asset_id: 'lineage-graph-id',
    name: 'Default Lineage Graph',
    supported_intents: ['UPSTREAM', 'DOWNSTREAM'],
    semantic_capabilities: ['BOUNDED_MULTI_HOP_TRAVERSAL'],
  }
  const base = {
    confidence: 0.98,
    entity_resolution_required: false,
    graph_traversal_required: false,
    semantic_retrieval_required: false,
    fallback_mode: null,
    primary_concepts: ['data lineage'],
    secondary_concepts: [],
    relation_intent: null,
    entity_type_hints: [],
    selected_graph_asset: null,
    retrieval_method: 'NONE',
  }
  assert.equal(parseChatRouteDecision(JSON.stringify({
    ...base,
    mode: 'GENERAL',
    intent: 'GENERAL_CONVERSATION',
  }), [asset]).mode, 'GENERAL')
  assert.deepEqual(parseChatRouteDecision(JSON.stringify({
    ...base,
    mode: 'GENERAL',
    intent: 'EXACT_METADATA',
    semantic_retrieval_required: true,
    fallback_mode: 'VECTOR',
    relation_intent: 'DATA_FLOW',
    entity_type_hints: ['TABLE'],
    retrieval_method: 'SEMANTIC_ENTITY_RESOLUTION_GRAPH',
  }), [asset],), {
    ...base,
    mode: 'GENERAL',
    intent: 'GENERAL_CONVERSATION',
    fallback_mode: null,
    relation_intent: null,
    entity_type_hints: [],
    retrieval_method: 'NONE',
  })
  assert.equal(parseChatRouteDecision(JSON.stringify({
    ...base,
    mode: 'VECTOR',
    intent: 'SEMANTIC_DISCOVERY',
    semantic_retrieval_required: true,
    entity_type_hints: ['KNOWLEDGE_ASSET'],
    retrieval_method: 'SEMANTIC',
  }), [asset]).mode, 'VECTOR')
  assert.deepEqual(parseChatRouteDecision(JSON.stringify({
    ...base,
    mode: 'VECTOR',
    intent: 'SEMANTIC_DISCOVERY',
    semantic_retrieval_required: true,
    primary_concepts: ['Knowledge Graph Asset', 'data lineage'],
    entity_type_hints: ['DATASET', 'TABLE'],
    retrieval_method: 'SEMANTIC',
  }), [asset]).entity_type_hints, ['KNOWLEDGE_ASSET'])
  assert.deepEqual(parseChatRouteDecision(JSON.stringify({
    ...base,
    mode: 'VECTOR',
    intent: 'SEMANTIC_DISCOVERY',
    semantic_retrieval_required: true,
    primary_concepts: ['business concept'],
    entity_type_hints: ['KNOWLEDGE_ASSET', 'GLOSSARY_TERM'],
    retrieval_method: 'SEMANTIC',
  }), [asset]).entity_type_hints, ['GLOSSARY_TERM'])
  assert.deepEqual(parseChatRouteDecision(JSON.stringify({
    ...base,
    mode: 'VECTOR',
    intent: 'GENERAL_CONVERSATION',
    semantic_retrieval_required: true,
    fallback_mode: 'VECTOR',
    primary_concepts: ['Knowledge Graph Asset'],
    entity_type_hints: ['KNOWLEDGE_ASSET'],
    selected_graph_asset: asset.name,
    retrieval_method: 'SEMANTIC_ENTITY_RESOLUTION_GRAPH',
  }), [asset]), {
    ...base,
    mode: 'VECTOR',
    intent: 'SEMANTIC_DISCOVERY',
    semantic_retrieval_required: true,
    primary_concepts: ['Knowledge Graph Asset'],
    entity_type_hints: ['KNOWLEDGE_ASSET'],
    retrieval_method: 'SEMANTIC',
  })
  assert.equal(parseChatRouteDecision(JSON.stringify({
    ...base,
    mode: 'GRAPH',
    intent: 'IMPACT_ANALYSIS',
    entity_resolution_required: true,
    graph_traversal_required: true,
    semantic_retrieval_required: true,
    fallback_mode: 'VECTOR',
    relation_intent: 'IMPACT',
    entity_type_hints: ['TABLE'],
    selected_graph_asset: asset.asset_id,
    retrieval_method: 'SEMANTIC_ENTITY_RESOLUTION_GRAPH',
  }), [asset]).selected_graph_asset, asset.asset_id)
  assert.equal(parseChatRouteDecision(JSON.stringify({
    ...base,
    mode: 'GRAPH',
    intent: 'LINEAGE',
    graph_traversal_required: true,
    relation_intent: 'UPSTREAM',
    selected_graph_asset: asset.name,
    retrieval_method: 'GRAPH_TRAVERSAL',
  }), [asset]).selected_graph_asset, asset.asset_id)
  const assetMetadataPlan = parseChatRouteDecision(JSON.stringify({
    ...base,
    mode: 'GRAPH',
    intent: 'LINEAGE',
    entity_resolution_required: true,
    graph_traversal_required: true,
    relation_intent: 'PATH',
    primary_concepts: ['Knowledge Graph Asset', 'data lineage'],
    entity_type_hints: ['DATASET', 'TABLE'],
    selected_graph_asset: asset.asset_id,
    retrieval_method: 'SEMANTIC_ENTITY_RESOLUTION_GRAPH',
  }), [asset])
  assert.equal(assetMetadataPlan.mode, 'VECTOR')
  assert.deepEqual(assetMetadataPlan.entity_type_hints, ['KNOWLEDGE_ASSET'])
  assert.equal(assetMetadataPlan.relation_intent, null)
  assert.equal(parseChatRouteDecision(JSON.stringify({
    ...base,
    mode: 'GRAPH',
    intent: 'LINEAGE',
    entity_resolution_required: true,
    graph_traversal_required: true,
    relation_intent: 'DOWNSTREAM',
    primary_concepts: ['Knowledge Graph Asset', 'cost_ledger_lithography'],
    entity_type_hints: ['TABLE'],
    selected_graph_asset: asset.asset_id,
    retrieval_method: 'SEMANTIC_ENTITY_RESOLUTION_GRAPH',
  }), [asset]).mode, 'GRAPH')
  assert.throws(() => parseChatRouteDecision(JSON.stringify({
    ...base,
    mode: 'GRAPH',
    intent: 'LINEAGE',
    graph_traversal_required: true,
    relation_intent: 'UPSTREAM',
    retrieval_method: 'GRAPH_TRAVERSAL',
  }), [asset]), /inconsistent route/)
})

test('managed graph entity resolution prefers nodes connected in the requested traversal direction', async () => {
  const { managedGraphNodeSupportsDirection } = await import('./poc-server.mjs?managed-graph-resolution-contract')
  const release = { edges: [
    { source: 'dependent', target: 'upstream' },
    { source: 'view', target: 'dependent' },
  ] }
  assert.equal(managedGraphNodeSupportsDirection(release, 'isolated', 'BOTH'), false)
  assert.equal(managedGraphNodeSupportsDirection(release, 'dependent', 'OUT'), true)
  assert.equal(managedGraphNodeSupportsDirection(release, 'dependent', 'IN'), true)
  assert.equal(managedGraphNodeSupportsDirection(release, 'upstream', 'OUT'), false)
  assert.equal(managedGraphNodeSupportsDirection(release, 'upstream', 'IN'), true)
})

test('managed graph entity resolution confirms authorized candidates through Metadata Master semantic hubs', async () => {
  const { metadataMasterCandidateContext } = await import('./poc-server.mjs?metadata-master-resolution-contract')
  const tableA = 'urn:li:dataset:(urn:li:dataPlatform:oracle,scope.table_a,DEV)'
  const tableB = 'urn:li:dataset:(urn:li:dataPlatform:oracle,scope.table_b,DEV)'
  const tableAId = `TABLE:${tableA}`
  const release = {
    nodes: [
      { id: tableAId, type: 'class.table', properties: { name: 'table_a', external_urn: tableA } },
      { id: 'urn:li:glossaryTerm:shared', type: 'class.business_term', properties: { name: 'Shared term' } },
    ],
    edges: [{
      source: tableAId,
      target: 'urn:li:glossaryTerm:shared',
      type: 'rel.table_has_glossary_term',
      properties: {
        source_aspect: 'glossaryTerms', explicit_or_inferred: 'EXPLICIT', confidence: 1,
      },
    }],
  }
  const matches = metadataMasterCandidateContext(release, [
    { id: tableA, external_urn: tableA, name: 'table_a' },
    { id: tableB, external_urn: tableB, name: 'table_b' },
  ])
  assert.equal(matches.length, 1)
  assert.equal(matches[0].tableId, tableAId)
  assert.deepEqual(matches[0].semanticContext, [{
    id: 'urn:li:glossaryTerm:shared',
    entity_type: 'class.business_term',
    name: 'Shared term',
    relation_type: 'rel.table_has_glossary_term',
    source_aspect: 'glossaryTerms',
    explicit_or_inferred: 'EXPLICIT',
    confidence: 1,
  }])
})

test('managed graph snapshots retain request-time Table authorization boundaries', async () => {
  const { authorizeManagedK9Release } = await import('./poc-server.mjs?managed-graph-authorization-contract')
  const tableA = 'urn:li:dataset:(urn:li:dataPlatform:oracle,scope.table_a,DEV)'
  const tableB = 'urn:li:dataset:(urn:li:dataPlatform:oracle,scope.table_b,DEV)'
  const release = {
    manifest: { graph_id: 'g1' },
    nodes: [
      { id: 'table-a', classification: 'CONFIDENTIAL', properties: { external_urn: tableA } },
      { id: 'column-a', classification: 'CONFIDENTIAL', properties: { dataset_urn: tableA } },
      { id: 'table-b', classification: 'CONFIDENTIAL', properties: { external_urn: tableB } },
      { id: 'term-shared', classification: 'CONFIDENTIAL', properties: { name: 'Shared term' } },
    ],
    edges: [
      { source: 'table-a', target: 'column-a', type: 'CONTAINS' },
      { source: 'table-a', target: 'term-shared', type: 'HAS_TERM' },
      { source: 'table-b', target: 'term-shared', type: 'HAS_TERM' },
    ],
  }
  const principal = {
    role: 'data_steward',
    maxSecurityGrade: 'credential',
    activeTableGrantUrns: new Set([tableA]),
    allowedFeatureSecurityCells: new Set(['knowledge\u0000data_steward\u0000credential']),
  }
  const authorized = authorizeManagedK9Release(principal, release)
  assert.deepEqual(authorized.nodes.map((node) => node.id), ['table-a', 'column-a', 'term-shared'])
  assert.deepEqual(authorized.edges.map((edge) => `${edge.source}->${edge.target}`), [
    'table-a->column-a',
    'table-a->term-shared',
  ])
  const servicePrincipal = {
    ...principal,
    allowedFeatureSecurityCells: new Set(),
  }
  const serviceAuthorized = authorizeManagedK9Release(servicePrincipal, release, { knowledgeAdapter: 'MCP' })
  assert.deepEqual(serviceAuthorized.nodes.map((node) => node.id), ['table-a', 'column-a', 'term-shared'])
  assert.deepEqual(serviceAuthorized.edges.map((edge) => `${edge.source}->${edge.target}`), [
    'table-a->column-a',
    'table-a->term-shared',
  ])
  const insufficientClearance = authorizeManagedK9Release({
    ...servicePrincipal,
    maxSecurityGrade: 'normal',
  }, release, { knowledgeAdapter: 'MCP' })
  assert.deepEqual(insufficientClearance.nodes, [])
  assert.deepEqual(insufficientClearance.edges, [])
  assert.equal(authorizeManagedK9Release({ role: 'admin' }, release), release)
})

test('managed visualization resolves and bounds only the authorization-filtered canonical projection', async () => {
  const {
    authorizeManagedK9Release,
    knowledgeVisualizationRoot,
    selectManagedKnowledgeVisualization,
  } = await import('./poc-server.mjs?managed-cytoscape-visualization-contract')
  const tableA = 'urn:li:dataset:(urn:li:dataPlatform:oracle,scope.allowed_table,DEV)'
  const tableB = 'urn:li:dataset:(urn:li:dataPlatform:oracle,scope.hidden_table,DEV)'
  const canonical = {
    nodes: [
      { id: 'table-a', type: 'class.table', classification: 'CONFIDENTIAL', properties: { external_urn: tableA, name: 'Allowed Table' } },
      { id: 'column-a', type: 'class.column', classification: 'CONFIDENTIAL', properties: { dataset_urn: tableA, name: 'allowed_id' } },
      { id: 'table-b', type: 'class.table', classification: 'CONFIDENTIAL', properties: { external_urn: tableB, name: 'Hidden Table' } },
      { id: 'term-shared', type: 'class.glossary_term', classification: 'CONFIDENTIAL', properties: { name: 'Shared term' } },
    ],
    edges: [
      { source: 'table-a', target: 'column-a', type: 'rel.contains' },
      { source: 'table-a', target: 'term-shared', type: 'rel.has_term' },
      { source: 'table-b', target: 'term-shared', type: 'rel.has_term' },
    ],
  }
  const authorized = authorizeManagedK9Release({
    role: 'data_steward',
    maxSecurityGrade: 'credential',
    activeTableGrantUrns: new Set([tableA]),
    allowedFeatureSecurityCells: new Set(['knowledge\u0000data_steward\u0000credential']),
  }, canonical)

  assert.deepEqual(authorized.nodes.map((node) => node.id), ['table-a', 'column-a', 'term-shared'])
  const root = knowledgeVisualizationRoot(authorized.nodes, authorized.edges, { focusQuery: 'Allowed Table' })
  assert.equal(root.id, 'table-a')
  assert.equal(knowledgeVisualizationRoot(authorized.nodes, authorized.edges, { focusQuery: 'Hidden Table' }), null)

  const selected = selectManagedKnowledgeVisualization(authorized, {
    rootNodeId: root.id,
    maximumNodes: 2,
    maximumEdges: 1,
    maximumHops: 1,
  })
  assert.deepEqual(selected.nodes.map((node) => node.id), ['table-a', 'column-a'])
  assert.deepEqual(selected.edges.map((edge) => `${edge.source}->${edge.target}`), ['table-a->column-a'])
  assert.equal(selected.truncated, true)
  assert.equal(JSON.stringify(selected).includes('table-b'), false)
  assert.equal(JSON.stringify(selected).includes('Hidden Table'), false)

  const upstream = selectManagedKnowledgeVisualization(authorized, {
    rootNodeId: 'table-a', maximumNodes: 3, maximumEdges: 2, maximumHops: 2,
    direction: 'UPSTREAM',
  })
  assert.deepEqual(upstream.nodes.map((node) => node.id), ['table-a', 'column-a', 'term-shared'])
  const downstream = selectManagedKnowledgeVisualization(authorized, {
    rootNodeId: 'column-a', maximumNodes: 3, maximumEdges: 2, maximumHops: 2,
    direction: 'DOWNSTREAM',
  })
  assert.deepEqual(downstream.nodes.map((node) => node.id), ['table-a', 'column-a'])
  assert.equal(JSON.stringify(downstream).includes('table-b'), false)
})

test('serves the POC at the root with the runtime boundary', async () => {
  const response = await fetch(origin)
  assert.equal(response.status, 200)
  assert.match(response.headers.get('content-security-policy'), /connect-src 'self'/)
  assert.match(response.headers.get('content-security-policy'), /script-src 'self' 'wasm-unsafe-eval'/)
  assert.doesNotMatch(response.headers.get('content-security-policy'), /script-src[^;]*\s'unsafe-eval'(?:\s|;|$)/)
  const body = await response.text()
  assert.match(body, /poc-runtime-config\.js/)
  assert.match(body, /src="\.\/assets\/poc-/)
})

test('does not expose provider credentials through runtime configuration', async () => {
  const response = await fetch(new URL('/poc-runtime-config.js', origin))
  assert.equal(response.status, 200)
  const body = await response.text()
  assert.doesNotMatch(body, /token|password|secret/i)
  assert.match(body, /__DATARIVER_POC_RUNTIME__/)
})

test('allows Compose-only Neo4j credentials when npm mode has no Neo4j URL', () => {
  const result = spawnSync(process.execPath, [
    '--input-type=module',
    '--eval',
    "await import('./poc-server.mjs?npm-config-test')",
  ], {
    cwd: new URL('.', import.meta.url),
    encoding: 'utf8',
    env: {
      ...process.env,
      NEO4J_HTTP_URL: '',
      NEO4J_USERNAME: 'neo4j',
      NEO4J_PASSWORD: 'local-test-password',
    },
  })
  assert.equal(result.status, 0, result.stderr)
})

test('DataHub GMS URL without token is rejected when POC_DATAHUB_ALLOW_NO_TOKEN is not set', () => {
  // Default is fail-closed: a URL without a token must throw at startup.
  const result = spawnSync(process.execPath, [
    '--input-type=module',
    '--eval',
    "await import('./poc-server.mjs?datahub-no-token-fail-closed')",
  ], {
    cwd: new URL('.', import.meta.url),
    encoding: 'utf8',
    env: {
      ...process.env,
      DATAHUB_GMS_URL: 'http://127.0.0.1:18080',
      DATAHUB_GMS_TOKEN: '',
      POC_DATAHUB_ALLOW_NO_TOKEN: 'false',
    },
  })
  assert.notEqual(result.status, 0, 'expected startup to fail without a token')
  assert.match(result.stderr, /DATAHUB_GMS_TOKEN/)
})

test('DataHub GMS URL without token is accepted when POC_DATAHUB_ALLOW_NO_TOKEN=true', () => {
  // DEV-local explicit opt-in for an auth-disabled local GMS.
  const result = spawnSync(process.execPath, [
    '--input-type=module',
    '--eval',
    "await import('./poc-server.mjs?datahub-no-token-permitted')",
  ], {
    cwd: new URL('.', import.meta.url),
    encoding: 'utf8',
    env: {
      ...process.env,
      DATAHUB_GMS_URL: 'http://127.0.0.1:18080',
      DATAHUB_GMS_TOKEN: '',
      POC_DATAHUB_ALLOW_NO_TOKEN: 'true',
    },
  })
  assert.equal(result.status, 0, result.stderr)
})



test('defaults the native Node listener to loopback and preserves an explicit container override', async () => {
  const { resolvePocServerHost } = await import('./poc-server.mjs?listener-host-contract-test')
  assert.equal(resolvePocServerHost({}), '127.0.0.1')
  assert.equal(resolvePocServerHost({ POC_SERVER_HOST: ' 0.0.0.0 ' }), '0.0.0.0')
})

test('reports a safe provider capability inventory', async () => {
  const response = await fetch(new URL('/poc-api/capabilities', origin))
  assert.equal(response.status, 200)
  const body = await response.json()
  assert.ok(Array.isArray(body.items))
  assert.equal(body.items.length, 7)
  assert.ok(body.items.every((item) => ['available', 'disabled', 'unavailable'].includes(item.state)))
})

test('persists only fixed allowlisted POC state scopes in the server fallback store', async () => {
  const empty = await fetch(new URL('/poc-api/state/core', origin))
  assert.equal(empty.status, 200)
  assert.equal((await empty.json()).value, null)
  const stored = await fetch(new URL('/poc-api/state/core', origin), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'If-Match': '"0"' },
    body: JSON.stringify({ value: { sequence: 901, changeRecords: [] } }),
  })
  assert.equal(stored.status, 200)
  assert.equal((await stored.json()).version, 1)
  assert.equal(stored.headers.get('etag'), '"1"')
  const stale = await fetch(new URL('/poc-api/state/core', origin), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'If-Match': '"0"' },
    body: JSON.stringify({ value: { sequence: 902, changeRecords: [] } }),
  })
  assert.equal(stale.status, 409)
  assert.equal((await stale.json()).code, 'STATE_VERSION_STALE')
  const reread = await (await fetch(new URL('/poc-api/state/core', origin))).json()
  assert.deepEqual(reread.value, { sequence: 901, changeRecords: [] })
  assert.equal((await fetch(new URL('/poc-api/state/arbitrary', origin))).status, 404)
})

test('bounds an unavailable Redis startup and retries after a cold-start PostgreSQL failure', () => {
  const result = spawnSync(process.execPath, [
    '--input-type=module',
    '--eval',
    String.raw`
      import assert from 'node:assert/strict'
      import { createHash } from 'node:crypto'
      import { createServer as createTcpServer } from 'node:net'

      function parseCommand(buffer) {
        if (!buffer.length) return undefined
        assert.equal(buffer[0], 42)
        let offset = 1
        const readLine = () => {
          const end = buffer.indexOf('\r\n', offset)
          if (end < 0) return undefined
          const line = buffer.subarray(offset, end).toString('utf8')
          offset = end + 2
          return line
        }
        const countLine = readLine()
        if (countLine === undefined) return undefined
        const count = Number(countLine)
        const args = []
        for (let index = 0; index < count; index += 1) {
          if (offset >= buffer.length) return undefined
          assert.equal(buffer[offset], 36)
          offset += 1
          const lengthLine = readLine()
          if (lengthLine === undefined) return undefined
          const length = Number(lengthLine)
          if (buffer.length < offset + length + 2) return undefined
          args.push(buffer.subarray(offset, offset + length).toString('utf8'))
          offset += length
          assert.equal(buffer.subarray(offset, offset + 2).toString('utf8'), '\r\n')
          offset += 2
        }
        return { args, bytes: offset }
      }

      const providerUrl = 'http://127.0.0.1:1'
      const sourceScope = createHash('sha256').update(providerUrl).digest('hex').slice(0, 16)
      const observedAt = new Date().toISOString()
      const projection = {
        projection_version: 1,
        source_scope: sourceScope,
        source_generation: 'f'.repeat(64),
        observed_at: observedAt,
        items: [{
          id: 'urn:li:dataset:(urn:li:dataPlatform:postgres,DB.SCHEMA.redis_last_good,PROD)',
          external_urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,DB.SCHEMA.redis_last_good,PROD)',
          asset_type: 'DATASET',
          dataset_kind: 'TABLE',
          name: 'redis_last_good',
          description: 'bounded Redis fallback',
          platform: 'postgres',
          database_name: 'DB',
          schema_name: 'SCHEMA',
          owner: 'Unassigned',
          domain: 'Unassigned',
          tags: [],
          terms: [],
          term_references: [],
          created_at: null,
          classification: 'INTERNAL',
          lifecycle: 'ACTIVE',
          observed_at: observedAt,
          matches: [],
        }],
      }
      const encodedProjection = JSON.stringify(projection)
      let redisConnections = 0
      let redisGets = 0
      const redisSockets = new Set()
      const redisServer = createTcpServer((socket) => {
        redisConnections += 1
        redisSockets.add(socket)
        socket.on('close', () => redisSockets.delete(socket))
        let buffered = Buffer.alloc(0)
        socket.on('data', (chunk) => {
          buffered = Buffer.concat([buffered, chunk])
          for (;;) {
            const command = parseCommand(buffered)
            if (!command) break
            buffered = buffered.subarray(command.bytes)
            const name = command.args[0]?.toUpperCase()
            if (name === 'HELLO') {
              socket.write('%1\r\n+proto\r\n:3\r\n')
            } else if (name === 'GET') {
              redisGets += 1
              socket.write('$' + Buffer.byteLength(encodedProjection) + '\r\n'
                + encodedProjection + '\r\n')
            } else {
              socket.write('+OK\r\n')
            }
          }
        })
      })

      try {
        await new Promise((resolvePromise) => redisServer.listen(0, '127.0.0.1', resolvePromise))
        const redisAddress = redisServer.address()
        assert.equal(typeof redisAddress, 'object')
        await new Promise((resolvePromise, reject) => redisServer.close((error) => (
          error ? reject(error) : resolvePromise()
        )))
        Object.assign(process.env, {
          POC_ENV_FILE: 'poc-state-store.adapter.test.env.missing',
          POC_DATABASE_URL: '',
          POC_POSTGRES_HOST: '',
          POC_REDIS_URL: 'redis://127.0.0.1:' + redisAddress.port,
          DATAHUB_GMS_URL: providerUrl,
          DATAHUB_GMS_TOKEN: '',
          POC_DATAHUB_ALLOW_NO_TOKEN: 'true',
        })
        let postgresQueries = 0
        const databasePool = {
          async query() {
            postgresQueries += 1
            throw new Error('bounded PostgreSQL startup failure')
          },
          async end() {},
        }
        const { createPocStateStore } = await import('./poc-state-store.mjs?pg-failure-redis-fallback')
        const { createPocServer } = await import('./poc-server.mjs?actual-adapter-redis-fallback')
        const stateStore = createPocStateStore({ databasePool })
        stateStore.readChangeHistoryAccess = async () => ({
          access: { version: 1, value: {
            schema_version: 1, active_subject_id: 'adapter-test-subject',
            users: [{ subject_id: 'adapter-test-subject', role: 'admin', active: true, provider_owner_refs: [] }],
            system_assignments: [],
          } },
          core: { version: 0, value: null },
        })
        stateStore.listUserTableGrants = async () => []
        stateStore.readFeatureSecurityPolicy = async () => ({ value: null, version: 0 })
        const pocServer = createPocServer({
          stateStore,
          authenticator: {
            async authenticate() { return { subjectId: 'adapter-test-subject', tokenHash: 'f'.repeat(64) } },
            assertOrigin() {},
          },
        })
        await new Promise((resolvePromise) => pocServer.listen(0, '127.0.0.1', resolvePromise))
        const address = pocServer.address()
        assert.equal(typeof address, 'object')
        const startedAt = performance.now()
        const unavailableResponse = await fetch(
          'http://127.0.0.1:' + address.port + '/poc-api/datahub/catalog?limit=20',
          { signal: AbortSignal.timeout(1500) },
        )
        const unavailableMilliseconds = performance.now() - startedAt
        assert.equal(unavailableResponse.status, 503)
        assert.ok(unavailableMilliseconds < 1500)

        await new Promise((resolvePromise) => redisServer.listen(redisAddress.port, '127.0.0.1', resolvePromise))
        const recoveredResponse = await fetch(
          'http://127.0.0.1:' + address.port + '/poc-api/datahub/catalog?limit=20',
        )
        const payload = await recoveredResponse.json()
        assert.equal(recoveredResponse.status, 200)
        assert.deepEqual(payload.items.map((item) => item.name), ['redis_last_good'])
        assert.equal(postgresQueries, 2)
        assert.equal(redisConnections, 1)
        assert.equal(redisGets, 1)
        pocServer.closeAllConnections()
        await new Promise((resolvePromise, reject) => pocServer.close((error) => (
          error ? reject(error) : resolvePromise()
        )))
        for (const socket of redisSockets) socket.destroy()
        await new Promise((resolvePromise, reject) => redisServer.close((error) => (
          error ? reject(error) : resolvePromise()
        )))
        process.stdout.write(JSON.stringify({
          unavailableStatus: unavailableResponse.status,
          unavailableMilliseconds,
          postgresQueries,
          redisConnections,
          redisGets,
        }))
      } catch (error) {
        console.error(error)
        process.exit(1)
      }
    `,
  ], {
    cwd: new URL('.', import.meta.url),
    encoding: 'utf8',
    timeout: 10_000,
    env: { ...process.env },
  })
  assert.equal(result.status, 0, result.stderr || result.stdout)
  const observation = JSON.parse(result.stdout)
  assert.deepEqual(observation, {
    unavailableStatus: 503,
    unavailableMilliseconds: observation.unavailableMilliseconds,
    postgresQueries: 2,
    redisConnections: 1,
    redisGets: 1,
  })
  assert.ok(observation.unavailableMilliseconds < 1500)
})

test('atomically fences in-memory Catalog embeddings to the active current generation', async () => {
  const { createPocStateStore } = await import('./poc-state-store.mjs?memory-generation-contract')
  const store = createPocStateStore()
  const bindingHash = 'b'.repeat(64)
  const firstGeneration = '1'.repeat(64)
  const secondGeneration = '2'.repeat(64)
  const projectionScope = 'catalog-inventory-v1:test'
  const record = (assetUrn, sourceGeneration, embedding) => ({
    bindingHash,
    assetUrn,
    sourceHash: assetUrn === 'asset-a' ? 'a'.repeat(64) : 'c'.repeat(64),
    sourceGeneration,
    contentText: assetUrn,
    metadata: { id: assetUrn },
    embedding,
  })

  await store.write(projectionScope, { source_generation: firstGeneration })
  await store.replaceCatalogEmbeddingGeneration(bindingHash, projectionScope, firstGeneration, [
    record('asset-a', firstGeneration, [1, 0]),
    record('asset-b', firstGeneration, [0, 1]),
  ], ['asset-a', 'asset-b'])
  assert.equal(await store.catalogEmbeddingActiveGeneration(bindingHash), firstGeneration)
  assert.deepEqual(
    (await store.searchCatalogEmbeddings(bindingHash, projectionScope, firstGeneration, [1, 0], 5, 'ADMIN_UNRESTRICTED'))
      .map((item) => item.assetUrn),
    ['asset-a', 'asset-b'],
  )

  await store.write(projectionScope, { source_generation: secondGeneration })
  await assert.rejects(
    store.replaceCatalogEmbeddingGeneration(bindingHash, projectionScope, secondGeneration, [
      record('asset-a', secondGeneration, [1, 0]),
      record('asset-b', secondGeneration, [Number.NaN, 1]),
    ], ['asset-a', 'asset-b']),
    /invalid or outside the supported dimension bound/,
  )
  assert.equal(await store.catalogEmbeddingActiveGeneration(bindingHash), firstGeneration)
  assert.deepEqual(await store.searchCatalogEmbeddings(
    bindingHash, projectionScope, secondGeneration, [1, 0], 5, 'ADMIN_UNRESTRICTED'
  ), [])

  await store.replaceCatalogEmbeddingGeneration(bindingHash, projectionScope, secondGeneration, [
    record('asset-b', secondGeneration, [0, 1]),
  ], ['asset-b'])
  assert.equal(await store.catalogEmbeddingActiveGeneration(bindingHash), secondGeneration)
  assert.deepEqual(
    (await store.searchCatalogEmbeddings(bindingHash, projectionScope, secondGeneration, [0, 1], 5, 'ADMIN_UNRESTRICTED'))
      .map((item) => item.assetUrn),
    ['asset-b'],
  )
  assert.deepEqual(await store.searchCatalogEmbeddings(
    bindingHash, projectionScope, firstGeneration, [1, 0], 5, 'ADMIN_UNRESTRICTED'
  ), [])

  const inactiveBindingHash = 'c'.repeat(64)
  const inactiveRecord = {
    ...record('asset-old-binding', secondGeneration, [1, 0]),
    bindingHash: inactiveBindingHash,
    sourceHash: 'd'.repeat(64),
  }
  await store.replaceCatalogEmbeddingGeneration(
    inactiveBindingHash,
    projectionScope,
    secondGeneration,
    [inactiveRecord],
    ['asset-old-binding'],
  )
  assert.equal(await store.catalogEmbeddingActiveGeneration(inactiveBindingHash), secondGeneration)
  assert.deepEqual(await store.pruneInactiveCatalogEmbeddingBindings(bindingHash), {
    embedding_rows: 1,
    active_pointers: 1,
  })
  assert.equal(await store.catalogEmbeddingActiveGeneration(inactiveBindingHash), undefined)
  assert.equal(await store.catalogEmbeddingActiveGeneration(bindingHash), secondGeneration)
  await assert.rejects(
    store.pruneInactiveCatalogEmbeddingBindings('f'.repeat(64)),
    /cannot be pruned before the requested binding is active/,
  )
})

test('serializes same-generation Catalog Embedding producers before materialization', async () => {
  const { createPocStateStore } = await import('./poc-state-store.mjs?memory-generation-owner-contract')
  const store = createPocStateStore()
  const bindingHash = '7'.repeat(64)
  const sourceGeneration = '8'.repeat(64)
  let active = 0
  let maximumActive = 0
  const order = []
  const producer = (name, delay) => store.withCatalogEmbeddingGenerationLock(
    bindingHash,
    sourceGeneration,
    async () => {
      active += 1
      maximumActive = Math.max(maximumActive, active)
      order.push(`${name}:start`)
      await new Promise((resolvePromise) => setTimeout(resolvePromise, delay))
      order.push(`${name}:end`)
      active -= 1
      return name
    },
  )
  assert.deepEqual(await Promise.all([producer('first', 15), producer('second', 0)]), ['first', 'second'])
  assert.equal(maximumActive, 1)
  assert.deepEqual(order, ['first:start', 'first:end', 'second:start', 'second:end'])
})

test('aborts a Catalog Embedding producer when its PostgreSQL ownership session is lost', async () => {
  const { createPocStateStore } = await import('./poc-state-store.mjs?postgres-generation-owner-loss')
  const client = new EventEmitter()
  client.query = async () => ({ rows: [] })
  client.release = () => undefined
  const databasePool = {
    async query() { return { rows: [] } },
    async connect() { return client },
    async end() {},
  }
  const store = createPocStateStore({ databasePool })
  const task = store.withCatalogEmbeddingGenerationLock(
    '7'.repeat(64),
    '8'.repeat(64),
    async (ownershipSignal) => {
      client.emit('error', new Error('connection lost'))
      await new Promise((resolvePromise) => setTimeout(resolvePromise, 0))
      ownershipSignal.throwIfAborted()
    },
  )
  await assert.rejects(task, /Catalog Embedding generation ownership was lost/)
})

test('handles an idle PostgreSQL pool connection loss without terminating the Product process', async () => {
  const { createPocStateStore } = await import('./poc-state-store.mjs?postgres-idle-pool-loss')
  const databasePool = new EventEmitter()
  databasePool.query = async () => ({ rows: [] })
  databasePool.end = async () => undefined
  const store = createPocStateStore({ databasePool })
  await store.catalogEmbeddingHashes('7'.repeat(64))
  assert.doesNotThrow(() => databasePool.emit('error', new Error('idle connection lost')))
  await store.close()
})

test('commits the PostgreSQL Embedding generation and active pointer in one fenced transaction', async () => {
  const { createPocStateStore } = await import('./poc-state-store.mjs?postgres-generation-contract')
  const statements = []
  const bindingHash = 'd'.repeat(64)
  const sourceGeneration = '3'.repeat(64)
  const projectionScope = 'catalog-inventory-v1:postgres-test'
  const client = {
    async query(sql, parameters = []) {
      const normalized = String(sql).replace(/\s+/g, ' ').trim()
      statements.push({ sql: normalized, parameters })
      if (normalized.includes('SELECT value FROM poc_state') && normalized.includes('FOR UPDATE')) {
        return { rows: [{ value: { source_generation: sourceGeneration } }] }
      }
      return { rows: [] }
    },
    release() {},
  }
  const databasePool = {
    async query(sql, parameters = []) {
      const normalized = String(sql).replace(/\s+/g, ' ').trim()
      statements.push({ sql: normalized, parameters })
      if (normalized.includes('FROM poc_catalog_embedding')) {
        return { rows: [{
          asset_urn: 'asset-current', content_text: 'current', metadata: { id: 'asset-current' }, similarity: 1,
        }] }
      }
      return { rows: [] }
    },
    async connect() { return client },
    async end() {},
  }
  const store = createPocStateStore({ databasePool })
  await store.replaceCatalogEmbeddingGeneration(bindingHash, projectionScope, sourceGeneration, [{
    bindingHash,
    assetUrn: 'asset-current',
    sourceHash: 'e'.repeat(64),
    sourceGeneration,
    contentText: 'current',
    metadata: { id: 'asset-current' },
    embedding: [1, 0],
  }], ['asset-current'])
  const transactionSql = statements.map((entry) => entry.sql)
  assert.ok(transactionSql.includes('BEGIN'))
  assert.ok(transactionSql.some((sql) => sql.includes('SELECT value FROM poc_state') && sql.includes('FOR UPDATE')))
  assert.ok(transactionSql.some((sql) => sql.startsWith('DELETE FROM poc_catalog_embedding')
    && sql.includes('source_generation <> $2')))
  assert.ok(transactionSql.some((sql) => sql.startsWith('INSERT INTO poc_state (scope, value)')))
  assert.ok(transactionSql.indexOf('COMMIT') > transactionSql.findIndex((sql) => sql.startsWith('INSERT INTO poc_state')))

  const ranked = await store.searchCatalogEmbeddings(
    bindingHash, projectionScope, sourceGeneration, [1, 0], 5, 'ADMIN_UNRESTRICTED'
  )
  assert.deepEqual(ranked.map((item) => item.assetUrn), ['asset-current'])
  const search = statements.findLast((entry) => entry.sql.includes('ORDER BY catalog_embedding.embedding <=>'))
  assert.match(search.sql, /source_generation = \$2/)
  assert.deepEqual(search.parameters, [
    bindingHash,
    sourceGeneration,
    projectionScope,
    `catalog-embedding-active-v1:${bindingHash}`,
    '[1,0]',
    5,
  ])

  const searchesBeforeEmptyScope = statements.filter((entry) => entry.sql.includes('FROM poc_catalog_embedding')).length
  assert.deepEqual(await store.searchCatalogEmbeddings(
    bindingHash, projectionScope, sourceGeneration, [1, 0], 5, new Set(),
  ), [])
  assert.equal(
    statements.filter((entry) => entry.sql.includes('FROM poc_catalog_embedding')).length,
    searchesBeforeEmptyScope,
  )

  await store.searchCatalogEmbeddings(
    bindingHash, projectionScope, sourceGeneration, [1, 0], 5, new Set(['asset-current']),
  )
  const restrictedSearch = statements.findLast((entry) => entry.sql.includes('FROM poc_catalog_embedding'))
  assert.ok(restrictedSearch.sql.indexOf('asset_urn = ANY($7::text[])') < restrictedSearch.sql.indexOf('ORDER BY'))
  assert.deepEqual(restrictedSearch.parameters, [
    bindingHash,
    sourceGeneration,
    projectionScope,
    `catalog-embedding-active-v1:${bindingHash}`,
    '[1,0]',
    5,
    ['asset-current'],
  ])

  assert.equal(await store.withCatalogEmbeddingGenerationLock(
    bindingHash,
    sourceGeneration,
    async () => 'owned',
  ), 'owned')
  assert.ok(statements.some((entry) => entry.sql.startsWith('SELECT pg_advisory_lock(hashtextextended($1, 0))')))
  assert.ok(statements.some((entry) => entry.sql.startsWith('SELECT pg_advisory_unlock(hashtextextended($1, 0))')))
})

test('rejects arbitrary gateway paths and non-allowlisted DAGs', async () => {
  const missing = await fetch(new URL('/poc-api/arbitrary-proxy', origin))
  assert.equal(missing.status, 404)
  const dags = await fetch(new URL('/poc-api/airflow/dags', origin))
  assert.equal(dags.status, 503)
  assert.equal((await dags.json()).code, 'AIRFLOW_NOT_CONFIGURED')
  const dag = await fetch(new URL('/poc-api/airflow/dags/arbitrary/runs', origin), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: Buffer.from('{}'),
  })
  assert.equal(dag.status, 400)
  const minio = await fetch(new URL('/poc-api/minio/uploads/upload-1/parts/1', origin), {
    method: 'PUT',
    body: Buffer.from('sample'),
  })
  assert.equal(minio.status, 503)
})

test('normalizes only reviewed Airflow DAG status documents and preserves missing DAGs', async () => {
  const {
    collectAllowedAirflowDagStatuses,
    normalizeAirflowDagStatus,
  } = await import('./poc-airflow-control.mjs?airflow-read-only-status-contract')
  const observed = await collectAllowedAirflowDagStatuses('v2', async (dagId) => {
    if (dagId === 'datariver_catalog_probe') return new Response(null, { status: 404 })
    return new Response(JSON.stringify({
      dag_id: dagId,
      is_paused: dagId === 'datariver_manual_metadata_apply',
      next_dagrun_logical_date: '2026-08-30T02:00:00+09:00',
      next_dagrun_run_after: '2026-08-30T02:01:00+09:00',
      last_parsed_time: '2026-08-29T12:00:00Z',
      provider_only_field: 'ignored',
    }), { status: 200 })
  }, async (dagId) => new Response(JSON.stringify({
    dag_runs: [{ dag_id: dagId, dag_run_id: `scheduled__${dagId}`, state: 'success' }],
  }), { status: 200 }))
  assert.equal(observed.api_mode, 'V2')
  assert.equal(observed.execution_scope, 'WORKSPACE_WIDE')
  assert.deepEqual(observed.items.map((item) => item.dag_id), [
    'datariver_bulk_registration_prepare',
    'datariver_catalog_probe',
    'datariver_catalog_sync',
    'datariver_manual_metadata_apply',
    'datariver_quality_dispatch',
  ])
  assert.deepEqual(observed.items.find((item) => item.dag_id === 'datariver_catalog_probe'), {
    system_id: 'AIRFLOW', dag_id: 'datariver_catalog_probe', execution_scope: 'WORKSPACE_WIDE',
    state: 'MISSING', paused: null,
    next_logical_date: null, next_run_at: null, last_parsed_at: null, latest_run: null,
  })
  assert.equal(
    observed.items.find((item) => item.dag_id === 'datariver_manual_metadata_apply').paused,
    true,
  )
  assert.equal(observed.items[0].next_logical_date, '2026-08-29T17:00:00.000Z')
  assert.equal(observed.items[0].next_run_at, '2026-08-29T17:01:00.000Z')
  assert.equal(observed.items[0].last_parsed_at, '2026-08-29T12:00:00.000Z')
  assert.throws(
    () => normalizeAirflowDagStatus(
      { dag_id: 'unexpected', is_paused: false },
      'datariver_catalog_sync', 'v2',
    ),
    { code: 'AIRFLOW_DAG_CONTRACT_INVALID' },
  )
  assert.throws(
    () => normalizeAirflowDagStatus(
      { dag_id: 'datariver_catalog_sync', is_paused: false, next_dagrun_run_after: 1 },
      'datariver_catalog_sync', 'v2',
    ),
    { code: 'AIRFLOW_DAG_CONTRACT_INVALID' },
  )
})

test('fails closed when local authentication is not explicitly constructed', async () => {
  const { createPocServer } = await import('./poc-server.mjs?missing-authentication-contract')
  const closedServer = createPocServer()
  await new Promise((resolvePromise) => closedServer.listen(0, '127.0.0.1', resolvePromise))
  const address = closedServer.address()
  assert.equal(typeof address, 'object')
  try {
    const response = await fetch(`http://127.0.0.1:${address.port}/api/v1/change-history/access`)
    assert.equal(response.status, 503)
    assert.equal((await response.json()).code, 'AUTHENTICATION_NOT_CONFIGURED')
  } finally {
    closedServer.closeAllConnections()
    await new Promise((resolvePromise, reject) => closedServer.close((error) => error ? reject(error) : resolvePromise()))
  }
})

test('makes access state server-authoritative with bootstrap, role, spoof, CAS, and core fences', async () => {
  const { createPocStateStore } = await import('./poc-state-store.mjs?access-authority-contract')
  const { createPocServer } = await import('./poc-server.mjs?access-authority-contract')
  const stateStore = createPocStateStore()
  const originalChangeRecords = [{ id: 'change-request-preserved', state: 'IN_REVIEW', current_round_number: 2, version: 9 }]
  await stateStore.write('core', { sequence: 42, changeRecords: originalChangeRecords })

  const servers = []
  const listen = async (activeSubjectId, selectedStore = stateStore) => {
    const authorityServer = createPocServer({
      stateStore: selectedStore,
      authenticator: testAuthenticator(activeSubjectId),
    })
    await new Promise((resolvePromise) => authorityServer.listen(0, '127.0.0.1', resolvePromise))
    servers.push(authorityServer)
    const address = authorityServer.address()
    assert.equal(typeof address, 'object')
    return `http://127.0.0.1:${address.port}`
  }
  const request = (authorityOrigin, options = {}) => fetch(
    new URL('/api/v1/change-history/access', authorityOrigin),
    options,
  )
  const document = {
    schema_version: 1,
    active_subject_id: 'configured-admin',
    users: [
      {
        subject_id: 'configured-admin', role: 'admin', active: true,
        username: 'configured.admin', display_name: 'Configured Admin', email: 'admin@poc.invalid',
        first_name: 'Configured', last_name: 'Admin', department_id: null, job_function: 'admin',
      },
      { subject_id: 'steward-subject', role: 'data_steward', active: true },
      { subject_id: 'developer-subject', role: 'developer', active: true },
      { subject_id: 'viewer-subject', role: 'viewer', active: true },
      { subject_id: 'inactive-subject', role: 'admin', active: false },
    ],
    systems: [{
      system_id: 'business-system', code: 'BUSINESS', name: 'Business System', description: '', active: true,
    }],
    system_schema_scopes: [{
      scope_id: 'business-schema', system_id: 'business-system', platform: ' Postgres ',
      database_name: 'business_db', schema_name: 'public', active: true,
    }],
    system_assignments: [{
      system_id: 'business-system', subject_id: 'steward-subject', responsibility: 'DATA_STEWARD',
      priority: 1, active: true,
    }],
  }
  await stateStore.write('change-history-access-v1', {
    schema_version: 1,
    active_subject_id: 'configured-admin',
    users: [{
      subject_id: 'configured-admin', role: 'admin', active: true, provider_owner_refs: [],
    }],
    system_assignments: [],
  })

  try {
    const adminOrigin = await listen('configured-admin')
    const put = (authorityOrigin, body, ifMatch = '"1"', headers = {}) => request(authorityOrigin, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'If-Match': ifMatch, ...headers },
      body: JSON.stringify(body),
    })

    const selfAppointedViewer = await put(adminOrigin, {
      ...document,
      users: document.users.map((user) => user.subject_id === 'configured-admin'
        ? { ...user, role: 'viewer' }
        : user),
    })
    assert.equal(selfAppointedViewer.status, 403)
    assert.equal(
      (await stateStore.readChangeHistoryAccess()).access.value.users[0].role,
      'admin',
    )

    const bootstrap = await put(adminOrigin, { ...document, active_subject_id: 'steward-subject' })
    assert.equal(bootstrap.status, 200)
    assert.equal(bootstrap.headers.get('etag'), '"2"')
    const bootstrapped = await bootstrap.json()
    assert.equal(bootstrapped.version, 2)
    assert.equal(bootstrapped.active_subject_id, 'steward-subject')
    assert.equal(bootstrapped.users[0].display_name, 'Configured Admin')
    assert.equal(bootstrapped.users[0].email, 'admin@poc.invalid')
    assert.equal(bootstrapped.system_schema_scopes[0].platform, 'postgres')
    assert.deepEqual((await stateStore.read('core')).value.changeRecords, originalChangeRecords)
    assert.equal((await request(adminOrigin)).status, 200, 'stored active metadata is not runtime identity authority')

    const privateRead = await fetch(new URL('/poc-api/state/change-history-access-v1', adminOrigin))
    assert.equal(privateRead.status, 404)
    const spoofed = await request(adminOrigin, { headers: { 'X-Subject-Id': 'viewer-subject' } })
    assert.equal(spoofed.status, 400)
    assert.equal((await spoofed.json()).code, 'PROTECTED_CLAIM')
    const bodySpoof = await put(adminOrigin, { ...document, actor_ref: 'browser-actor' }, '"2"')
    assert.equal(bodySpoof.status, 400)
    assert.equal((await bodySpoof.json()).code, 'PROTECTED_CLAIM')

    const stale = await put(adminOrigin, document)
    assert.equal(stale.status, 409)
    assert.equal((await stale.json()).code, 'ACCESS_VERSION_STALE')
    const noMatch = await request(adminOrigin, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(document),
    })
    assert.equal(noMatch.status, 428)

    const ambiguous = await put(adminOrigin, {
      ...document,
      systems: [...document.systems, {
        system_id: 'second-system', code: 'SECOND', name: 'Second System', description: '', active: true,
      }],
      system_schema_scopes: [...document.system_schema_scopes, {
        scope_id: 'duplicate-business-schema', system_id: 'second-system', platform: 'postgres',
        database_name: 'business_db', schema_name: 'public', active: true,
      }],
    }, '"2"')
    assert.equal(ambiguous.status, 400)
    assert.equal((await ambiguous.json()).code, 'ACCESS_DOCUMENT_INVALID')

    for (const [subjectId, role, active, status] of [
      ['steward-subject', 'data_steward', true, 403],
      ['developer-subject', 'developer', true, 403],
      ['viewer-subject', 'viewer', true, 403],
      ['inactive-subject', 'admin', false, 403],
    ]) {
      const roleStore = createPocStateStore()
      await roleStore.writeChangeHistoryAccess({
        expectedAccessVersion: 0,
        expectedCoreVersion: 0,
        accessValue: {
          schema_version: 1, active_subject_id: 'stored-admin',
          users: [{ subject_id: subjectId, role, active, provider_owner_refs: [] }],
          system_assignments: [],
        },
        coreValue: {
          adminMemberships: [], adminSystems: [], adminSystemAssignees: [], adminSystemSchemaScopes: [],
        },
      })
      const roleOrigin = await listen(subjectId, roleStore)
      assert.equal((await request(roleOrigin)).status, status, subjectId)
      assert.equal((await put(roleOrigin, {
        schema_version: 1,
        active_subject_id: subjectId,
        users: [{ subject_id: subjectId, role, active }],
        systems: [], system_schema_scopes: [], system_assignments: [],
      }, '"1"')).status, status, `${subjectId} PUT`)
    }
    const unknownOrigin = await listen('unknown-subject')
    assert.equal((await request(unknownOrigin)).status, 403)

    const genericWrite = await fetch(new URL('/poc-api/state/core', adminOrigin), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'If-Match': '"2"' },
      body: JSON.stringify({ value: {
        sequence: 43,
        changeRecords: [{ ...originalChangeRecords[0], state: 'TESTING' }],
        adminMemberships: [], adminSystems: [], adminSystemAssignees: [], adminSystemSchemaScopes: [],
      } }),
    })
    assert.equal(genericWrite.status, 200)
    const afterGeneric = (await stateStore.read('core')).value
    assert.equal(afterGeneric.changeRecords[0].state, 'TESTING')
    assert.equal(afterGeneric.adminSystems[0].system_id, 'business-system')
    assert.equal(afterGeneric.adminMemberships.length, document.users.length)
    assert.equal(afterGeneric.adminMemberships.find((item) => item.subject_id === 'configured-admin').display_name, 'Configured Admin')

    const crBeforeAccessUpdate = JSON.parse(JSON.stringify(afterGeneric.changeRecords))
    const updatedDocument = {
      ...document,
      users: document.users.map((user) => user.subject_id === 'configured-admin'
        ? { ...user, display_name: 'Updated Admin', job_function: 'platform_admin' }
        : user),
      system_assignments: [{ ...document.system_assignments[0], priority: 2 }],
    }
    const update = await put(adminOrigin, updatedDocument, '"2"')
    assert.equal(update.status, 200)
    assert.equal(update.headers.get('etag'), '"3"')
    assert.deepEqual((await stateStore.read('core')).value.changeRecords, crBeforeAccessUpdate)
    assert.equal((await stateStore.read('core')).value.adminMemberships
      .find((item) => item.subject_id === 'configured-admin').display_name, 'Updated Admin')
    assert.equal((await request(adminOrigin)).status, 200)

    const primitiveCore = await fetch(new URL('/poc-api/state/core', adminOrigin), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'If-Match': '"4"' },
      body: JSON.stringify({ value: 'browser-replacement' }),
    })
    assert.equal(primitiveCore.status, 409)
    assert.equal((await primitiveCore.json()).code, 'CORE_STATE_INVALID')
  } finally {
    for (const authorityServer of servers) {
      authorityServer.closeAllConnections()
      await new Promise((resolvePromise, reject) => authorityServer.close((error) => (
        error ? reject(error) : resolvePromise()
      )))
    }
  }
})

test('does not use a process-global active subject as request authority', async () => {
  const previousSubject = process.env.POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID
  process.env.POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID = 'spoofed-environment-admin'
  const { createPocStateStore } = await import('./poc-state-store.mjs?access-environment-contract')
  const { createPocServer } = await import('./poc-server.mjs?access-environment-contract')
  const stateStore = createPocStateStore()
  await stateStore.writeChangeHistoryAccess({
    expectedAccessVersion: 0,
    expectedCoreVersion: 0,
    accessValue: {
      schema_version: 1,
      active_subject_id: 'stored-metadata-only',
      users: [{ subject_id: 'request-session-admin', role: 'admin', active: true, provider_owner_refs: [] }],
      system_assignments: [],
    },
    coreValue: {
      adminMemberships: [], adminSystems: [], adminSystemAssignees: [], adminSystemSchemaScopes: [],
    },
  })
  const environmentServer = createPocServer({
    stateStore,
    authenticator: testAuthenticator('request-session-admin'),
  })
  delete process.env.POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID
  await new Promise((resolvePromise) => environmentServer.listen(0, '127.0.0.1', resolvePromise))
  const address = environmentServer.address()
  assert.equal(typeof address, 'object')
  try {
    const response = await fetch(`http://127.0.0.1:${address.port}/api/v1/change-history/access`)
    assert.equal(response.status, 200)
  } finally {
    if (previousSubject === undefined) delete process.env.POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID
    else process.env.POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID = previousSubject
    environmentServer.closeAllConnections()
    await new Promise((resolvePromise, reject) => environmentServer.close((error) => (
      error ? reject(error) : resolvePromise()
    )))
  }
})

test('serves authoritative change-history reads, reverse lookup, weekly aggregation, and zero-effect link commands', async () => {
  const { createPocServer } = await import('./poc-server.mjs?change-history-api-contract')
  const eventId = '1'.repeat(64)
  const transactionId = '2'.repeat(64)
  const assetUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,business_db.public.orders,PROD)'
  const targetItem = { routing_system_id: 'business-system', target_system_id: 'business-system', target_asset_id: assetUrn,
    target_ref: assetUrn, aspect_name: 'schemaMetadata', operation: 'UPDATE' }
  const changeRequest = {
    id: 'poc-change-request-1', number: 'CR-2026-0001', request_type: 'CHANGE_INTAKE',
    title: 'Orders schema change', state: 'IN_REVIEW', current_round_id: 'round-1',
    current_round_number: 1, version: 7,
    requester_id: 'historical-requester', requester_department_id: null,
    created_at: '2026-08-12T00:30:00.000Z', requested_due_date: '2026-08-20',
    priority: 'HIGH', urgency: 'NORMAL', classification: 'INTERNAL',
    rounds: [{ id: 'round-1', selected_system_id: 'business-system' }],
    items: [targetItem, { ...targetItem }], approvals: [], transitions: [],
  }
  const mappingDocument = { schema_version: 2, bindings: [{
    table_identity: assetUrn, system_id: 'business-system', active: true, version: 1,
    created_at: '2026-08-10T00:00:00.000Z', created_by: 'admin-subject',
    updated_at: '2026-08-10T00:00:00.000Z', updated_by: 'admin-subject', reason: 'contract fixture',
  }], asset_snapshots: [{
    table_identity: assetUrn, dataset_kind: 'TABLE', platform: 'postgres',
    database_name: 'business_db', schema_name: 'public', asset_name: 'orders',
    security_grade: 'normal', observed_at: '2026-08-10T00:00:00.000Z',
  }] }
  const projection = {
    access: { version: 3, value: {
      schema_version: 1, active_subject_id: 'admin-subject',
      policy: { version: 1, priority_order: 'ASCENDING', fallback: ['DATA_STEWARD', 'DEVELOPER', 'DATAHUB_OWNER', 'UNASSIGNED'] },
      users: [
        { subject_id: 'admin-subject', display_name: 'Request Admin', role: 'admin', active: true, provider_owner_refs: [] },
        { subject_id: 'historical-requester', display_name: 'Historical Requester', role: 'viewer', active: false, provider_owner_refs: [] },
        { subject_id: 'steward-subject', display_name: 'Primary Steward', role: 'data_steward', active: true, provider_owner_refs: [] },
      ],
      system_assignments: [
        { system_id: 'business-system', subject_id: 'steward-subject', responsibility: 'DATA_STEWARD', priority: 1, active: true },
        { system_id: 'business-system', subject_id: 'steward-subject', responsibility: 'DEVELOPER', priority: 1, active: true },
      ],
    } },
    core: { version: 5, value: {
      changeRecords: [changeRequest],
      adminSystems: [{ system_id: 'business-system', code: 'BUSINESS', name: 'Business', description: '', active: true, version: 1 }],
      adminSystemSchemaScopes: [['business-system', [{ scope_id: 'scope-1', system_id: 'business-system', platform: 'postgres', database_name: 'business_db', schema_name: 'public', active: true, version: 1 }]]],
    } },
    catalog: { version: 2, value: {
      projection_version: 1, source_scope: 'disabled', source_generation: 'a'.repeat(64), observed_at: '2026-08-14T00:00:00.000Z',
      items: [{ id: assetUrn, name: 'orders', dataset_kind: 'TABLE', security_grade: 'normal', platform: 'postgres', database_name: 'business_db', schema_name: 'public' }],
    } },
    events: [{
      event_identity: eventId, event_hash: '3'.repeat(64), normalized_change_transaction_id: transactionId,
      source_identity_hash: '9'.repeat(64), topic_contract: 'MetadataChangeLog_Versioned_v1', source_partition: 0, source_offset: 10,
      asset_urn: assetUrn, normalized_entity_key: 'business_db.public.orders', category: 'TECHNICAL_SCHEMA',
      source_aspect: 'schemaMetadata', operation: 'UPDATE', before_data: { nullable: true }, after_data: { nullable: false },
      actor_ref: null, source_occurred_at: '2026-08-11T01:00:00.000Z', detected_at: '2026-08-11T01:00:01.000Z', captured_at: '2026-08-11T01:00:02.000Z',
    }],
    links: [],
    sources: [{ source_identity_hash: '9'.repeat(64), provider_name: 'DataHub', provider_version: 'contract-test', schema_contract_hash: '8'.repeat(64), created_at: '2026-08-11T00:00:00.000Z' }],
    checkpoints: [{ source_identity_hash: '9'.repeat(64), topic_contract: 'MetadataChangeLog_Versioned_v1', source_partition: 0, first_exact_offset: 10, next_offset: 11, last_captured_at: '2026-08-11T01:00:02.000Z', version: 2 }],
  }
  let appendCommand
  const replayCommands = new Map()
  const stateStore = {
    configured: { postgres: true, redis: false },
    async readChangeHistoryAccess() {
      return { access: structuredClone(projection.access), core: structuredClone(projection.core) }
    },
    async readChangeHistoryProjection({ catalogScope }) {
      assert.equal(catalogScope, 'catalog-inventory-v1:disabled')
      return structuredClone(projection)
    },
    async read(scope) {
      assert.equal(scope, 'table-system-mappings-v1')
      return { value: structuredClone(mappingDocument), version: 1 }
    },
    async readChangeHistoryCrLinkReplay(command) {
      const stored = replayCommands.get(command.idempotencyKey)
      if (!stored) return null
      if (stored.reason !== command.reason || stored.action !== command.action) {
        throw Object.assign(new Error('idempotency conflict'), { code: 'IDEMPOTENCY_CONFLICT', statusCode: 409 })
      }
      return { ...stored.result, replayed: true }
    },
    async appendChangeHistoryCrLink(command) {
      appendCommand = command
      assert.deepEqual(projection.core.value.changeRecords, [changeRequest])
      const linkVersion = projection.links.length + 1
      const result = {
        linkEventIdentity: String(3 + linkVersion).repeat(64),
        eventHash: String(4 + linkVersion).repeat(64),
        linkVersion,
        replayed: false,
      }
      projection.links.push({
        link_event_identity: result.linkEventIdentity, event_hash: result.eventHash,
        ledger_event_identity: eventId, link_version: linkVersion, link_kind: command.linkKind, action: command.action,
        change_request_id: command.changeRequestId, change_request_round: command.changeRequestRound, prior_link_hash: command.priorLinkHash,
        reason: command.reason, policy_hash: command.policyHash, basis_hash: command.basisHash,
        actor_ref: command.actorRef, occurred_at: command.occurredAt, captured_at: command.occurredAt,
      })
      replayCommands.set(command.idempotencyKey, { ...command, result })
      return result
    },
  }
  const server = createPocServer({
    stateStore,
    authenticator: testAuthenticator('admin-subject'),
  })
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  assert.equal(typeof address, 'object')
  const base = `http://127.0.0.1:${address.port}`
  try {
    const list = await fetch(`${base}/api/v1/change-history/events`)
    assert.equal(list.status, 200)
    const listed = await list.json()
    assert.equal(listed.total, 1)
    assert.equal(listed.empty_state_reason, null)
    assert.equal(listed.empty_state_detail, null)
    assert.deepEqual(listed.items[0], {
      ...listed.items[0],
      change_type: 'SCHEMA_CHANGE',
      precision: 'EXACT_MCL',
      current_stage: 'UNLINKED',
      allowed_link_actions: ['SET_PRIMARY', 'CLEAR_PRIMARY', 'ADD_CANDIDATE', 'REMOVE_CANDIDATE'],
      locator: { platform: 'postgres', database_name: 'business_db', schema_name: 'public', asset_name: 'orders' },
    })
    assert.equal(listed.items[0].system.system_id, 'business-system')
    const currentCatalogItems = projection.catalog.value.items
    projection.catalog.value.items = []
    const historicalAfterDeletion = await (await fetch(`${base}/api/v1/change-history/events`)).json()
    assert.equal(historicalAfterDeletion.total, 1, 'a mapped historical event survives current DataHub deletion')
    assert.equal(historicalAfterDeletion.items[0].locator.asset_name, 'orders')
    projection.catalog.value.items = currentCatalogItems
    const emptyRange = await (await fetch(`${base}/api/v1/change-history/events?date_from=2026-01-01&date_to=2026-01-02`)).json()
    assert.equal(emptyRange.total, 0)
    assert.equal(emptyRange.empty_state_reason, 'FILTER_DATE_RANGE_EMPTY')
    assert.equal(emptyRange.empty_state_detail, null)
    const rangeSummaryResponse = await fetch(`${base}/api/v1/change-requests/summaries?limit=25&date_from=2026-08-11&date_to=2026-08-12`)
    assert.equal(rangeSummaryResponse.status, 200)
    const rangeSummary = await rangeSummaryResponse.json()
    assert.equal(rangeSummary.items.length, 1)
    assert.equal(rangeSummary.items[0].target_schema_name, 'public')
    assert.equal(rangeSummary.items[0].item_count, 2)
    assert.equal(rangeSummary.items[0].requester_name, 'Historical Requester')
    assert.deepEqual(rangeSummary.items[0].assignee_names, ['Primary Steward'])
    const authorizedCrDetail = await fetch(`${base}/api/v1/change-requests/${changeRequest.id}`)
    assert.equal(authorizedCrDetail.status, 200)
    assert.deepEqual(await authorizedCrDetail.json(), changeRequest)
    assert.deepEqual({
      event_count: rangeSummary.overview[0].event_count,
      unprogressed_event_count: rangeSummary.overview[0].unprogressed_event_count,
      total_count: rangeSummary.overview[0].total_count,
      received_count: rangeSummary.overview[0].received_count,
    }, { event_count: 1, unprogressed_event_count: 1, total_count: 1, received_count: 1 })
    changeRequest.items.push({ ...targetItem, target_asset_id: 'urn:li:dataset:(urn:li:dataPlatform:postgres,business_db.public.missing,PROD)' })
    const missingCurrentTarget = await (await fetch(`${base}/api/v1/change-requests/summaries?limit=25&date_from=2026-08-11&date_to=2026-08-12`)).json()
    assert.equal(missingCurrentTarget.items.length, 0, 'one absent current target hides the entire multi-item CR')
    assert.equal(missingCurrentTarget.overview[0].total_count, 0)
    const missingCurrentTargetDetail = await fetch(`${base}/api/v1/change-requests/${changeRequest.id}`)
    assert.equal(missingCurrentTargetDetail.status, 404, 'one unauthorized target existence-hides the entire multi-item CR')
    changeRequest.items.pop()
    changeRequest.items[1].routing_system_id = 'stale-system'
    const mismatchedBinding = await (await fetch(`${base}/api/v1/change-requests/summaries?limit=25&date_from=2026-08-11&date_to=2026-08-12`)).json()
    assert.equal(mismatchedBinding.items.length, 0)
    assert.equal(mismatchedBinding.overview[0].total_count, 0)
    changeRequest.items[1].routing_system_id = 'business-system'
    mappingDocument.bindings[0].active = false
    const inactiveBinding = await (await fetch(`${base}/api/v1/change-requests/summaries?limit=25&date_from=2026-08-11&date_to=2026-08-12`)).json()
    assert.deepEqual(inactiveBinding.items, [])
    assert.deepEqual(inactiveBinding.overview, [])
    mappingDocument.bindings[0].active = true
    projection.core.value.adminSystems[0].active = false
    projection.core.value.adminSystemSchemaScopes[0][1][0].active = false
    projection.access.value.system_assignments.forEach((assignment) => { assignment.active = false })
    const inactiveSystem = await (await fetch(`${base}/api/v1/change-requests/summaries?limit=25&date_from=2026-08-11&date_to=2026-08-12`)).json()
    assert.deepEqual(inactiveSystem.items, [])
    assert.deepEqual(inactiveSystem.overview, [])
    projection.core.value.adminSystems[0].active = true
    projection.core.value.adminSystemSchemaScopes[0][1][0].active = true
    projection.access.value.system_assignments.forEach((assignment) => { assignment.active = true })
    changeRequest.rounds[0].revision_kind = 'EDITED'
    const resubmittedRange = await (await fetch(`${base}/api/v1/change-requests/summaries?limit=25&date_from=2026-08-11&date_to=2026-08-12`)).json()
    assert.equal(resubmittedRange.overview[0].received_count, 0)
    assert.equal(resubmittedRange.overview[0].recheck_count, 1)
    delete changeRequest.rounds[0].revision_kind
    const outsideRange = await (await fetch(`${base}/api/v1/change-requests/summaries?limit=25&date_from=2026-08-13&date_to=2026-08-13`)).json()
    assert.equal(outsideRange.items.length, 0)
    assert.equal(outsideRange.overview[0].event_count, 0)
    assert.equal(outsideRange.overview[0].total_count, 0)
    const filtered = await (await fetch(`${base}/api/v1/change-history/events?week_start=2026-08-10&change_type=SCHEMA_CHANGE&category=TECHNICAL_SCHEMA&precision=EXACT_MCL&operation=UPDATE&platform=postgres&database_name=business_db&schema_name=public&system_id=business-system&assignee_subject_id=steward-subject&link_state=UNLINKED&stage=UNLINKED`)).json()
    assert.equal(filtered.total, 1)
    const ranged = await (await fetch(`${base}/api/v1/change-history/events?date_from=2026-08-11&date_to=2026-08-11&platform=postgres&database_name=business_db&schema_name=public&system_id=business-system`)).json()
    assert.equal(ranged.total, 1)
    assert.equal((await fetch(`${base}/api/v1/change-history/events?date_from=2026-08-12&date_to=2026-08-11`)).status, 400)
    assert.equal((await fetch(`${base}/api/v1/change-history/events?precision=GUESSED`)).status, 400)
    assert.equal((await fetch(`${base}/api/v1/change-history/events?stage=UNKNOWN`)).status, 400)
    const detail = await fetch(`${base}/api/v1/change-history/events/${eventId}`)
    assert.equal(detail.headers.get('etag'), '"0"')
    assert.equal((await detail.json()).assignee.subject_id, 'steward-subject')
    const before = JSON.stringify(projection.core.value.changeRecords)
    const linked = await fetch(`${base}/api/v1/change-history/events/${eventId}/cr-link-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'link-1', 'If-Match': '"0"' },
      body: JSON.stringify({ action: 'SET_PRIMARY', change_request_id: changeRequest.id, change_request_round: 1, reason: 'reviewed link' }),
    })
    assert.equal(linked.status, 201)
    assert.equal(linked.headers.get('etag'), `"${'5'.repeat(64)}"`)
    assert.equal(appendCommand.actorRef, 'admin-subject')
    assert.equal(JSON.stringify(projection.core.value.changeRecords), before)
    const linkHistory = await fetch(`${base}/api/v1/change-history/events/${eventId}/cr-links`)
    assert.equal(linkHistory.headers.get('etag'), `"${'5'.repeat(64)}"`)
    assert.equal((await linkHistory.json()).items[0].link_version, 1)
    const replay = await fetch(`${base}/api/v1/change-history/events/${eventId}/cr-link-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'link-1', 'If-Match': '"0"' },
      body: JSON.stringify({ action: 'SET_PRIMARY', change_request_id: changeRequest.id, change_request_round: 1, reason: 'reviewed link' }),
    })
    assert.equal(replay.status, 200)
    assert.equal((await replay.json()).replayed, true)
    const conflict = await fetch(`${base}/api/v1/change-history/events/${eventId}/cr-link-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'link-1', 'If-Match': `"${'5'.repeat(64)}"` },
      body: JSON.stringify({ action: 'SET_PRIMARY', change_request_id: changeRequest.id, change_request_round: 1, reason: 'different' }),
    })
    assert.equal(conflict.status, 409)
    const reverse = await fetch(`${base}/api/v1/change-requests/${changeRequest.id}/change-history`)
    assert.equal((await reverse.json()).items.length, 1)
    const addCandidate = await fetch(`${base}/api/v1/change-history/events/${eventId}/cr-link-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'link-2', 'If-Match': `"${'5'.repeat(64)}"` },
      body: JSON.stringify({ action: 'ADD_CANDIDATE', change_request_id: changeRequest.id, change_request_round: 1, reason: 'candidate' }),
    })
    assert.equal(addCandidate.status, 201)
    const removeCandidate = await fetch(`${base}/api/v1/change-history/events/${eventId}/cr-link-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'link-3', 'If-Match': `"${'6'.repeat(64)}"` },
      body: JSON.stringify({ action: 'REMOVE_CANDIDATE', change_request_id: changeRequest.id, change_request_round: 1, reason: 'remove candidate' }),
    })
    assert.equal(removeCandidate.status, 201)
    const clearPrimary = await fetch(`${base}/api/v1/change-history/events/${eventId}/cr-link-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'link-4', 'If-Match': `"${'7'.repeat(64)}"` },
      body: JSON.stringify({ action: 'CLEAR_PRIMARY', change_request_id: changeRequest.id, change_request_round: 1, reason: 'clear primary' }),
    })
    assert.equal(clearPrimary.status, 201)
    assert.equal(JSON.stringify(projection.core.value.changeRecords), before)

    projection.events.push(
      {
        ...projection.events[0], event_identity: 'a'.repeat(64), event_hash: 'b'.repeat(64),
        normalized_entity_key: 'business_db.public.orders.description', category: 'DOCUMENTATION',
        source_aspect: 'datasetProperties',
      },
      {
        ...projection.events[0], event_identity: 'b'.repeat(64), event_hash: 'c'.repeat(64),
        normalized_entity_key: 'business_db.public.orders.description-duplicate', category: 'DOCUMENTATION',
        source_aspect: 'datasetProperties',
      },
    )
    for (const [index, event] of projection.events.entries()) {
      projection.links.push({
        ledger_event_identity: event.event_identity,
        link_event_identity: ['d', 'e', 'f'][index].repeat(64),
        event_hash: ['a', 'b', 'c'][index].repeat(64),
        link_version: 10,
        link_kind: 'PRIMARY',
        action: 'SET_PRIMARY',
        change_request_id: changeRequest.id,
        change_request_round: 1,
      })
    }

    const pagedEventIds = []
    let cursor = null
    do {
      const cursorQuery = cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''
      const page = await (await fetch(`${base}/api/v1/change-history/events?limit=1${cursorQuery}`)).json()
      assert.equal(page.total, 3)
      assert.equal(page.limit, 1)
      assert.equal(page.items.length, 1)
      pagedEventIds.push(page.items[0].event_id)
      assert.notEqual(page.next_cursor, cursor)
      cursor = page.next_cursor
    } while (cursor)
    assert.equal(new Set(pagedEventIds).size, 3)

    const lifecycleEventId = 'c'.repeat(64)
    projection.events.push({
      ...projection.events[0], event_identity: lifecycleEventId, event_hash: 'd'.repeat(64),
      normalized_change_transaction_id: 'e'.repeat(64), normalized_entity_key: 'asset:lifecycle:removed',
      category: 'LIFECYCLE', source_aspect: 'status', operation: 'DELETE',
      before_data: { removed: false }, after_data: { removed: true },
    })
    const lifecycleList = await (await fetch(`${base}/api/v1/change-history/events?category=LIFECYCLE`)).json()
    assert.equal(lifecycleList.total, 1)
    assert.deepEqual(lifecycleList.items[0], {
      ...lifecycleList.items[0], category: 'LIFECYCLE', change_type: 'METADATA_CHANGE',
      source_aspect: 'status', operation: 'DELETE', entity_key: 'asset:lifecycle:removed',
    })
    const lifecycleDetail = await (await fetch(`${base}/api/v1/change-history/events/${lifecycleEventId}`)).json()
    assert.deepEqual(lifecycleDetail.before, { removed: false })
    assert.deepEqual(lifecycleDetail.after, { removed: true })

    const weekly = await fetch(`${base}/api/v1/change-history/weekly?week_start=2026-08-10`)
    assert.equal(weekly.status, 200)
    const summary = await weekly.json()
    assert.equal(summary.week_start, '2026-08-10')
    assert.equal(summary.week_end_exclusive, '2026-08-17')
    assert.equal(summary.total_count, 2)
    assert.equal(summary.received_count, 1)
    assert.equal(summary.total_count, summary.unlinked_count + summary.received_count + summary.recheck_count
      + summary.testing_count + summary.final_review_count + summary.completed_count)
    const sourceSummary = await (await fetch(`${base}/api/v1/change-history/summary?week_start=2026-08-10`)).json()
    assert.equal(sourceSummary.schema_change_count, 1)
    assert.equal(sourceSummary.metadata_change_count, 2)
    assert.equal(sourceSummary.event_count, 4)
    assert.equal(sourceSummary.precision_counts.EXACT_MCL, 2)
    assert.equal(sourceSummary.category_counts.TECHNICAL_SCHEMA, 1)
    assert.equal(sourceSummary.category_counts.DOCUMENTATION, 1)
    assert.equal(sourceSummary.category_counts.LIFECYCLE, 1)
    assert.equal(sourceSummary.operation_counts.UPDATE, 1)
    assert.equal(sourceSummary.operation_counts.DELETE, 1)
    assert.equal(sourceSummary.sync_status, 'CONTIGUOUS_CAPTURE_RECORDED')
    assert.equal(sourceSummary.source_generation, 'a'.repeat(64))
    assert.equal(sourceSummary.ledger_guarantee_from, '2026-08-11T01:00:02.000Z')

    projection.core.value.changeRecords[0].current_round_number = 2
    const staleRoundSummary = await (await fetch(`${base}/api/v1/change-history/weekly?week_start=2026-08-10`)).json()
    const staleRoundDetail = await (await fetch(`${base}/api/v1/change-history/events/${eventId}`)).json()
    assert.equal(staleRoundSummary.unlinked_count, 2)
    assert.equal(staleRoundSummary.recheck_count, 0)
    assert.equal(staleRoundDetail.current_stage, 'UNLINKED')
    assert.equal(staleRoundDetail.current_primary, null)
    projection.core.value.changeRecords[0].current_round_number = 1
    projection.core.value.changeRecords[0].rounds[0].revision_kind = 'EDITED'
    const editedEventSummary = await (await fetch(`${base}/api/v1/change-history/weekly?week_start=2026-08-10`)).json()
    const editedEventDetail = await (await fetch(`${base}/api/v1/change-history/events/${eventId}`)).json()
    const editedCrSummary = await (await fetch(`${base}/api/v1/change-requests/summaries?date_from=2026-08-11&date_to=2026-08-12`)).json()
    assert.equal(editedEventSummary.recheck_count, 1)
    assert.equal(editedEventSummary.received_count, 0)
    assert.equal(editedEventDetail.current_stage, 'RECHECK')
    assert.equal(editedCrSummary.overview[0].recheck_count, 1)
    delete projection.core.value.changeRecords[0].rounds[0].revision_kind
    projection.core.value.changeRecords[0].transitions = [
      { round_id: 'round-1', from_state: 'CHANGES_REQUESTED', to_state: 'REGISTERED' },
      { round_id: 'round-1', from_state: 'REGISTERED', to_state: 'IN_REVIEW' },
    ]
    const transitionEventSummary = await (await fetch(`${base}/api/v1/change-history/weekly?week_start=2026-08-10`)).json()
    const transitionEventDetail = await (await fetch(`${base}/api/v1/change-history/events/${eventId}`)).json()
    const transitionCrSummary = await (await fetch(`${base}/api/v1/change-requests/summaries?date_from=2026-08-11&date_to=2026-08-12`)).json()
    assert.equal(transitionEventSummary.recheck_count, 1)
    assert.equal(transitionEventDetail.current_stage, 'RECHECK')
    assert.equal(transitionCrSummary.overview[0].recheck_count, 1)
    projection.core.value.changeRecords[0].transitions = []
    projection.core.value.changeRecords[0].state = 'CANCELLED'
    const cancelledSummary = await (await fetch(`${base}/api/v1/change-history/weekly?week_start=2026-08-10`)).json()
    assert.equal(cancelledSummary.unlinked_count, 2)
    assert.equal(cancelledSummary.recheck_count, 0)
    projection.core.value.changeRecords[0].state = 'IN_REVIEW'

    const invalidTuesday = await fetch(`${base}/api/v1/change-history/weekly?week_start=2026-08-11`)
    assert.equal(invalidTuesday.status, 400)
    assert.equal((await invalidTuesday.json()).code, 'WEEK_START_INVALID')
    projection.core.value.changeRecords[0].state = 'REJECTED'
    const rejectedSummary = await (await fetch(`${base}/api/v1/change-history/weekly?week_start=2026-08-10`)).json()
    assert.equal(rejectedSummary.unlinked_count, 2)
    assert.equal(rejectedSummary.received_count, 0)
    const spoofed = await fetch(`${base}/api/v1/change-history/events`, { headers: { 'X-Subject-Id': 'steward-subject' } })
    assert.equal(spoofed.status, 400)
  } finally {
    server.closeAllConnections()
    await new Promise((resolvePromise, reject) => server.close((error) => error ? reject(error) : resolvePromise()))
  }
})

test('projects bounded Table and Column presentation without list-detail fanout', async () => {
  const { changeHistoryPresentation } = await import('./poc-server.mjs?change-history-presentation-contract')
  const event = (overrides) => ({
    normalized_entity_key: 'dataset-properties', category: 'DOCUMENTATION', source_aspect: 'datasetProperties',
    operation: 'UPDATE', before_data: null, after_data: null, ...overrides,
  })
  const present = (overrides) => changeHistoryPresentation({ event: event(overrides) })

  assert.deepEqual(present({
    normalized_entity_key: 'asset:lifecycle', category: 'LIFECYCLE', source_aspect: 'entity', operation: 'CREATE',
  }), {
    target_kind: 'TABLE', field_name: null, presentation_change_type: 'TABLE_CREATE',
    change_summary: 'CREATE · LIFECYCLE', change_detail: [],
  })
  assert.equal(present({
    normalized_entity_key: 'asset:lifecycle:removed', category: 'LIFECYCLE', source_aspect: 'status', operation: 'DELETE',
    before_data: { removed: false }, after_data: { removed: true },
  }).presentation_change_type, 'TABLE_DELETE')
  assert.deepEqual(present({
    before_data: { description: 'old', custom_properties: {} },
    after_data: { description: 'new', custom_properties: {} },
  }), {
    target_kind: 'TABLE', field_name: null, presentation_change_type: 'TABLE_CHANGE',
    change_summary: 'UPDATE · DOCUMENTATION',
    change_detail: [{ field: 'DESCRIPTION', before: 'old', after: 'new' }],
  })
  assert.deepEqual(present({
    normalized_entity_key: 'field:amount', category: 'TECHNICAL_SCHEMA', source_aspect: 'schemaMetadata', operation: 'CREATE',
    after_data: { field_path: 'amount', native_data_type: 'integer', logical_type: 'NumberType', nullable: true },
  }).presentation_change_type, 'COLUMN_CREATE')
  assert.equal(present({
    normalized_entity_key: 'field:amount', category: 'TECHNICAL_SCHEMA', source_aspect: 'schemaMetadata', operation: 'DELETE',
    before_data: { field_path: 'amount', native_data_type: 'integer', logical_type: 'NumberType', nullable: true },
  }).presentation_change_type, 'COLUMN_DELETE')
  assert.deepEqual(present({
    normalized_entity_key: 'field:amount', category: 'TECHNICAL_SCHEMA', source_aspect: 'schemaMetadata', operation: 'UPDATE',
    before_data: { field_path: 'amount', native_data_type: 'integer', logical_type: 'NumberType', nullable: true, description: 'old' },
    after_data: { field_path: 'amount', native_data_type: 'bigint', logical_type: 'NumberType', nullable: false, description: 'new' },
  }).change_detail.map(({ field }) => field), ['TYPE', 'NULLABLE', 'DESCRIPTION'])

  const semanticCases = [
    ['TAG', 'globalTags', { tag_urn: 'urn:li:tag:old' }, { tag_urn: 'urn:li:tag:new' }, 'TAG'],
    ['GLOSSARY_TERM', 'glossaryTerms', { term_urn: 'urn:li:glossaryTerm:old' }, { term_urn: 'urn:li:glossaryTerm:new' }, 'GLOSSARY_TERM'],
    ['DOMAIN', 'domains', { domain_urn: 'urn:li:domain:old' }, { domain_urn: 'urn:li:domain:new' }, 'DOMAIN'],
    ['OWNERSHIP', 'ownership', { owner_urn: 'urn:li:corpuser:old', ownership_type: 'TECHNICAL_OWNER' }, { owner_urn: 'urn:li:corpuser:new', ownership_type: 'DATAOWNER' }, 'OWNER'],
  ]
  for (const [category, sourceAspect, beforeData, afterData, expectedField] of semanticCases) {
    const projection = present({
      category, source_aspect: sourceAspect, operation: 'UPDATE', before_data: beforeData, after_data: afterData,
    })
    assert.equal(projection.presentation_change_type, 'TABLE_CHANGE')
    assert.equal(projection.change_detail[0].field, expectedField)
  }
  const columnDescription = present({
    normalized_entity_key: 'field:amount', category: 'DOCUMENTATION', source_aspect: 'editableSchemaMetadata', operation: 'UPDATE',
    before_data: { field_path: 'amount', description: 'old' }, after_data: { field_path: 'amount', description: 'new' },
  })
  assert.equal(columnDescription.presentation_change_type, 'COLUMN_CHANGE')
  assert.deepEqual(columnDescription.change_detail, [{ field: 'DESCRIPTION', before: 'old', after: 'new' }])
})

test('prunes assigned-role rows, keeps viewer read-only, and fails closed on stale or unmapped mutations', async () => {
  const { createPocServer } = await import('./poc-server.mjs?change-history-role-contract')
  const { approvedDefaultFeatureSecurityPolicy } = await import('./poc-feature-security-policy.mjs')
  const opposingPolicy = (catalogAllowed, changeAllowed) => {
    const document = approvedDefaultFeatureSecurityPolicy()
    for (const cell of document.cells) {
      if (cell.role !== 'viewer' || cell.grade !== 'normal') continue
      if (cell.feature === 'catalog') cell.allow = catalogAllowed
      if (cell.feature === 'change') cell.allow = changeAllowed
    }
    return document
  }
  const eventId = '6'.repeat(64)
  const assetUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.public.one,PROD)'
  const event = {
    event_identity: eventId, event_hash: '7'.repeat(64), normalized_change_transaction_id: '8'.repeat(64),
    asset_urn: assetUrn, normalized_entity_key: 'one', category: 'TAG', source_aspect: 'globalTags', operation: 'ADD',
    before_data: {}, after_data: {}, source_occurred_at: '2026-08-11T01:00:00.000Z', detected_at: '2026-08-11T01:00:01.000Z', captured_at: '2026-08-11T01:00:02.000Z',
  }
  const baseProjection = {
    access: { version: 1, value: {
      schema_version: 1, active_subject_id: 'stored-admin',
      policy: { version: 1, priority_order: 'ASCENDING', fallback: ['DATA_STEWARD', 'DEVELOPER', 'DATAHUB_OWNER', 'UNASSIGNED'] },
      users: [{ subject_id: 'role-subject', role: 'viewer', active: true, max_security_grade: 'normal', provider_owner_refs: [] }], system_assignments: [],
    } },
    core: { version: 1, value: {
      changeRecords: [{ id: 'cr-1', current_round_id: 'r1', current_round_number: 1, state: 'REGISTERED', rounds: [{ id: 'r1', selected_system_id: 'system-1' }], items: [{ target_asset_id: assetUrn, target_system_id: 'system-1', routing_system_id: 'system-1' }] }],
      adminSystems: [{ system_id: 'system-1', code: 'ONE', name: 'One', active: true, version: 1 }],
      adminSystemSchemaScopes: [['system-1', [{ scope_id: 's1', system_id: 'system-1', platform: 'postgres', database_name: 'db', schema_name: 'public', active: true, version: 1 }]]],
    } },
    catalog: { version: 1, value: { projection_version: 1, source_scope: 'disabled', source_generation: '9'.repeat(64), observed_at: '2026-08-14T00:00:00.000Z', items: [{ id: event.asset_urn, dataset_kind: 'TABLE', security_grade: 'normal', platform: 'postgres', database_name: 'db', schema_name: 'public' }] } },
    tableGrants: [],
    featurePolicy: approvedDefaultFeatureSecurityPolicy(),
    mapping: { schema_version: 1, bindings: [{
      table_identity: assetUrn, system_id: 'system-1', active: true, version: 1,
      created_at: '2026-08-10T00:00:00.000Z', created_by: 'admin',
      updated_at: '2026-08-10T00:00:00.000Z', updated_by: 'admin', reason: 'contract fixture',
    }] },
    events: [event], links: [],
  }
  const run = async (projection, action) => {
    let appendCalls = 0
    const stateStore = {
      configured: { postgres: true, redis: false },
      async readChangeHistoryAccess() {
        return { access: structuredClone(projection.access), core: structuredClone(projection.core) }
      },
      async readChangeHistoryProjection() { return structuredClone(projection) },
      async read(scope) {
        assert.equal(scope, 'table-system-mappings-v1')
        return { value: structuredClone(projection.mapping), version: 1 }
      },
      async listUserTableGrants() { return structuredClone(projection.tableGrants ?? []) },
      async readFeatureSecurityPolicy() { return { value: structuredClone(projection.featurePolicy), version: 1 } },
      async appendChangeHistoryCrLink() { appendCalls += 1; return { linkEventIdentity: 'a'.repeat(64), eventHash: 'b'.repeat(64), linkVersion: 1, replayed: false } },
    }
    const roleServer = createPocServer({
      stateStore,
      authenticator: testAuthenticator('role-subject'),
    })
    await new Promise((resolvePromise) => roleServer.listen(0, '127.0.0.1', resolvePromise))
    const address = roleServer.address()
    try { return { result: await action(`http://127.0.0.1:${address.port}`), appendCalls } } finally {
      roleServer.closeAllConnections()
      await new Promise((resolvePromise, reject) => roleServer.close((error) => error ? reject(error) : resolvePromise()))
    }
  }
  const viewerRead = await run(baseProjection, (origin) => fetch(`${origin}/api/v1/change-history/events`))
  const viewerReadBody = await viewerRead.result.json()
  assert.equal(viewerReadBody.total, 0)
  assert.deepEqual(viewerReadBody.items, [])
  assert.equal(viewerReadBody.empty_state_reason, 'EVENTS_EXIST_BUT_NOT_AUTHORIZED')
  assert.equal(viewerReadBody.empty_state_detail, 'AUTHORIZATION_SCOPE')
  const noExactMapping = structuredClone(baseProjection)
  noExactMapping.mapping.bindings = []
  const noExactMappingBody = await (await run(
    noExactMapping,
    (origin) => fetch(`${origin}/api/v1/change-history/events`),
  )).result.json()
  assert.equal(noExactMappingBody.total, 0)
  assert.equal(noExactMappingBody.empty_state_reason, 'EVENTS_EXIST_BUT_NOT_AUTHORIZED')
  assert.equal(noExactMappingBody.empty_state_detail, 'NO_EXACT_MAPPING')
  const deniedDetail = await run(baseProjection, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}`))
  assert.equal(deniedDetail.result.status, 404)
  const viewerSummary = await run(baseProjection, (origin) => fetch(`${origin}/api/v1/change-requests/summaries?limit=25`))
  const viewerSummaryBody = await viewerSummary.result.json()
  assert.equal(viewerSummaryBody.items.length, 0, 'global or responsible-System read never substitutes for current Table authority')
  assert.deepEqual(viewerSummaryBody.overview, [], 'denied targets leak neither existence nor counts')
  const grantedViewer = structuredClone(baseProjection)
  grantedViewer.tableGrants = [{ tableUrn: assetUrn, active: true }]
  grantedViewer.core.value.adminSystemSchemaScopes = []
  const grantedViewerRead = await run(grantedViewer, (origin) => fetch(`${origin}/api/v1/change-history/events`))
  const grantedViewerReadBody = await grantedViewerRead.result.json()
  assert.equal(grantedViewerReadBody.total, 1, 'exact Table authority is sufficient without a legacy schema scope')
  assert.equal(grantedViewerReadBody.items[0].system.system_id, 'system-1')
  assert.deepEqual(grantedViewerReadBody.items[0].allowed_link_actions, [])
  const grantedDrawerRead = await run(grantedViewer, (origin) => fetch(`${origin}/api/v1/change-history/events?date_from=2026-08-11&date_to=2026-08-11&platform=postgres&database_name=db&schema_name=public&system_id=system-1&system_resolution=RESOLVED`))
  assert.equal((await grantedDrawerRead.result.json()).total, 1)
  const grantedViewerSummary = await run(grantedViewer, (origin) => fetch(`${origin}/api/v1/change-requests/summaries?limit=25`))
  const grantedViewerSummaryBody = await grantedViewerSummary.result.json()
  assert.equal(grantedViewerSummaryBody.items.length, 1)
  assert.equal(grantedViewerSummaryBody.overview[0].event_count, 1)
  const grantedDetail = await run(grantedViewer, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}`))
  assert.equal(grantedDetail.result.status, 200)
  const grantedLinks = await run(grantedViewer, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}/cr-links`))
  assert.equal(grantedLinks.result.status, 200)
  const catalogOnly = structuredClone(grantedViewer)
  catalogOnly.featurePolicy = opposingPolicy(true, false)
  const catalogOnlyList = await run(catalogOnly, (origin) => fetch(`${origin}/api/v1/change-history/events`))
  const catalogOnlyDrawer = await run(catalogOnly, (origin) => fetch(`${origin}/api/v1/change-history/events?date_from=2026-08-11&date_to=2026-08-11&platform=postgres&database_name=db&schema_name=public&system_id=system-1&system_resolution=RESOLVED`))
  const catalogOnlyWeekly = await run(catalogOnly, (origin) => fetch(`${origin}/api/v1/change-history/weekly?week_start=2026-08-10`))
  const catalogOnlyDetail = await run(catalogOnly, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}`))
  const catalogOnlyLinks = await run(catalogOnly, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}/cr-links`))
  const catalogOnlySummary = await run(catalogOnly, (origin) => fetch(`${origin}/api/v1/change-requests/summaries?limit=25`))
  const catalogOnlyCrDetail = await run(catalogOnly, (origin) => fetch(`${origin}/api/v1/change-requests/cr-1`))
  assert.equal((await catalogOnlyList.result.json()).total, 0)
  assert.equal((await catalogOnlyDrawer.result.json()).total, 0)
  assert.equal((await catalogOnlyWeekly.result.json()).total_count, 0)
  assert.equal(catalogOnlyDetail.result.status, 404)
  assert.equal(catalogOnlyLinks.result.status, 404)
  assert.equal(catalogOnlyCrDetail.result.status, 404)
  assert.deepEqual((await catalogOnlySummary.result.json()), {
    items: [], overview: [], overview_truncated: false, page: { next_cursor: null, limit: 25 },
  })
  const changeOnly = structuredClone(grantedViewer)
  changeOnly.featurePolicy = opposingPolicy(false, true)
  const changeOnlyList = await run(changeOnly, (origin) => fetch(`${origin}/api/v1/change-history/events`))
  const changeOnlyDrawer = await run(changeOnly, (origin) => fetch(`${origin}/api/v1/change-history/events?date_from=2026-08-11&date_to=2026-08-11&platform=postgres&database_name=db&schema_name=public&system_id=system-1&system_resolution=RESOLVED`))
  const changeOnlyWeekly = await run(changeOnly, (origin) => fetch(`${origin}/api/v1/change-history/weekly?week_start=2026-08-10`))
  const changeOnlyDetail = await run(changeOnly, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}`))
  const changeOnlyLinks = await run(changeOnly, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}/cr-links`))
  const changeOnlySummary = await run(changeOnly, (origin) => fetch(`${origin}/api/v1/change-requests/summaries?limit=25`))
  const changeOnlyCrDetail = await run(changeOnly, (origin) => fetch(`${origin}/api/v1/change-requests/cr-1`))
  assert.equal((await changeOnlyList.result.json()).total, 1)
  assert.equal((await changeOnlyDrawer.result.json()).total, 1)
  assert.equal((await changeOnlyWeekly.result.json()).total_count, 1)
  assert.equal(changeOnlyDetail.result.status, 200)
  assert.equal(changeOnlyLinks.result.status, 200)
  assert.equal(changeOnlyCrDetail.result.status, 200)
  assert.equal((await changeOnlyCrDetail.result.json()).id, 'cr-1')
  const changeOnlySummaryBody = await changeOnlySummary.result.json()
  assert.equal(changeOnlySummaryBody.items.length, 1)
  assert.equal(changeOnlySummaryBody.overview[0].event_count, 1)
  const viewerWrite = await run(baseProjection, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}/cr-link-events`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'k', 'If-Match': '"0"' },
    body: JSON.stringify({ action: 'SET_PRIMARY', change_request_id: 'cr-1', change_request_round: 1, reason: 'no' }),
  }))
  assert.equal(viewerWrite.result.status, 403)
  assert.equal(viewerWrite.appendCalls, 0)
  const steward = structuredClone(baseProjection)
  steward.access.value.users[0].role = 'data_steward'
  const hidden = await run(steward, (origin) => fetch(`${origin}/api/v1/change-history/events`))
  assert.equal((await hidden.result.json()).items.length, 0)
  const hiddenSummary = await run(steward, (origin) => fetch(`${origin}/api/v1/change-requests/summaries?limit=25`))
  assert.equal((await hiddenSummary.result.json()).items.length, 0)
  steward.access.value.system_assignments = [{ system_id: 'system-1', subject_id: 'role-subject', responsibility: 'DATA_STEWARD', priority: 1, active: true }]
  const visible = await run(steward, (origin) => fetch(`${origin}/api/v1/change-history/events`))
  assert.equal((await visible.result.json()).total, 0, 'legacy System responsibility cannot grant event visibility')
  const responsibleSystemOnlyDetail = await run(steward, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}`))
  assert.equal(responsibleSystemOnlyDetail.result.status, 404)
  const responsibleSystemOnlyLinks = await run(steward, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}/cr-links`))
  assert.equal(responsibleSystemOnlyLinks.result.status, 404)
  const responsibleSystemOnlySummary = await run(steward, (origin) => fetch(`${origin}/api/v1/change-requests/summaries?limit=25`))
  const responsibleSystemOnlyBody = await responsibleSystemOnlySummary.result.json()
  assert.equal(responsibleSystemOnlyBody.items.length, 0)
  assert.deepEqual(responsibleSystemOnlyBody.overview, [])
  steward.tableGrants = [{ tableUrn: assetUrn, active: true }]
  steward.core.value.adminSystemSchemaScopes = []
  const tableAuthorized = await run(steward, (origin) => fetch(`${origin}/api/v1/change-history/events`))
  const tableAuthorizedItems = (await tableAuthorized.result.json()).items
  assert.equal(tableAuthorizedItems.length, 1)
  assert.deepEqual(tableAuthorizedItems[0].allowed_link_actions, ['SET_PRIMARY', 'CLEAR_PRIMARY', 'ADD_CANDIDATE', 'REMOVE_CANDIDATE'])
  const visibleSummary = await run(steward, (origin) => fetch(`${origin}/api/v1/change-requests/summaries?limit=25`))
  assert.equal((await visibleSummary.result.json()).items.length, 1)
  const mutate = (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}/cr-link-events`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'assigned-key', 'If-Match': '"0"' },
    body: JSON.stringify({ action: 'SET_PRIMARY', change_request_id: 'cr-1', change_request_round: 1, reason: 'assigned' }),
  })
  const stewardMutation = await run(steward, mutate)
  assert.equal(stewardMutation.result.status, 201)
  assert.equal(stewardMutation.appendCalls, 1)
  const developer = structuredClone(steward)
  developer.access.value.users[0].role = 'developer'
  const unassignedDeveloperItems = (await (await run(developer, (origin) => fetch(`${origin}/api/v1/change-history/events`))).result.json()).items
  assert.equal(unassignedDeveloperItems.length, 1)
  assert.deepEqual(unassignedDeveloperItems[0].allowed_link_actions, [])
  developer.access.value.system_assignments[0].responsibility = 'DEVELOPER'
  assert.equal((await (await run(developer, (origin) => fetch(`${origin}/api/v1/change-history/events`))).result.json()).items.length, 1)
  const developerMutation = await run(developer, mutate)
  assert.equal(developerMutation.result.status, 201)
  assert.equal(developerMutation.appendCalls, 1)
  const unmapped = structuredClone(steward)
  unmapped.catalog.value.items = []
  const rejected = await run(unmapped, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}/cr-link-events`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'k', 'If-Match': '"0"' },
    body: JSON.stringify({ action: 'SET_PRIMARY', change_request_id: 'cr-1', change_request_round: 1, reason: 'no' }),
  }))
  assert.equal(rejected.result.status, 404, 'assigned roles cannot observe or mutate unmapped rows')
  assert.equal(rejected.appendCalls, 0)
  const adminUnmapped = structuredClone(unmapped)
  adminUnmapped.access.value.users[0].role = 'admin'
  const adminRejected = await run(adminUnmapped, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}/cr-link-events`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'k', 'If-Match': '"0"' },
    body: JSON.stringify({ action: 'SET_PRIMARY', change_request_id: 'cr-1', change_request_round: 1, reason: 'no' }),
  }))
  assert.equal(adminRejected.result.status, 404)
  const stale = structuredClone(steward)
  stale.links = [{ ledger_event_identity: eventId, event_hash: 'c'.repeat(64), link_version: 1, link_event_identity: 'd'.repeat(64), link_kind: 'CANDIDATE', action: 'ADD_CANDIDATE', change_request_id: 'cr-1', change_request_round: 1, occurred_at: '2026-08-11T02:00:00.000Z' }]
  const staleResponse = await run(stale, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}/cr-link-events`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'k', 'If-Match': '"0"' },
    body: JSON.stringify({ action: 'SET_PRIMARY', change_request_id: 'cr-1', change_request_round: 1, reason: 'no' }),
  }))
  assert.equal(staleResponse.result.status, 409)
  assert.equal(staleResponse.appendCalls, 0)
})

test('creates a CR for a viewer through exact current Table, grant, grade, policy, and mapping checks', async () => {
  const { createPocStateStore } = await import('./poc-state-store.mjs?cr-create-contract-test')
  const { createPocServer } = await import('./poc-server.mjs?cr-create-contract-test')
  const { applyTableSystemMappingCommand } = await import('./poc-table-system-mappings.mjs')
  const {
    changeHistoryAccessCoreProjection,
    normalizeChangeHistoryAccessDocument,
    privateChangeHistoryAccess,
  } = await import('./poc-access-document.mjs')
  const stateStore = createPocStateStore()
  const tableUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.a.valid_table,PROD)'
  const unavailableUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.a.unavailable_table,PROD)'
  const changedAt = '2026-08-17T00:00:00.000Z'
  const accessDocument = normalizeChangeHistoryAccessDocument({
    schema_version: 1,
    active_subject_id: 'viewer-subject',
    users: [{
      subject_id: 'viewer-subject', role: 'viewer', active: true,
      max_security_grade: 'normal', provider_owner_refs: [],
    }],
    systems: [{ system_id: 'system-a', code: 'A', name: 'System A', active: true }],
    system_schema_scopes: [],
    system_assignments: [],
  })
  await stateStore.writeChangeHistoryAccess({
    expectedAccessVersion: 0,
    expectedCoreVersion: 0,
    accessValue: privateChangeHistoryAccess(accessDocument),
    coreValue: changeHistoryAccessCoreProjection(null, accessDocument, 1),
  })
  const mappingResult = applyTableSystemMappingCommand(null, {
    action: 'ASSIGN', table_ids: [tableUrn], system_ids: ['system-a'],
    reason: 'CR server contract test mapping',
  }, 'admin-subject', changedAt)
  await stateStore.write('table-system-mappings-v1', mappingResult.document)
  await stateStore.applyUserTableGrantCommand({
    subjectId: 'viewer-subject', tableUrns: [tableUrn], action: 'GRANT',
    actorSubjectId: 'admin-subject', changedAt,
  })
  const currentDatahubTables = async (urns) => {
    if (urns.includes(unavailableUrn)) throw new Error('provider unavailable')
    return urns.includes(tableUrn)
      ? [{ id: tableUrn, dataset_kind: 'TABLE', security_grade: 'normal' }]
      : []
  }
  const testServer = createPocServer({
    stateStore,
    authenticator: testAuthenticator('viewer-subject'),
    currentDatahubTables,
  })
  await new Promise((resolvePromise) => testServer.listen(0, '127.0.0.1', resolvePromise))
  const address = testServer.address()
  const testOrigin = `http://127.0.0.1:${address.port}`
  const request = (body, version = 1) => fetch(`${testOrigin}/poc-api/change-requests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'If-Match': `"${version}"` },
    body: JSON.stringify(body),
  })
  const validBody = {
    table_urn: tableUrn,
    responsible_system_id: 'system-a',
    title: 'Bounded table change',
    description: 'The viewer is allowed to register this accessible Table change.',
    change_document: { requested: { description: 'updated' } },
  }
  try {
    const invalid = await request({ ...validBody, table_urn: `${tableUrn}-missing` })
    const invalidBody = await invalid.json()
    assert.equal(invalid.status, 400, JSON.stringify(invalidBody))
    assert.equal(invalidBody.code, 'CR_TABLE_INVALID')

    const unavailable = await request({ ...validBody, table_urn: unavailableUrn })
    assert.equal(unavailable.status, 503)
    assert.equal((await unavailable.json()).code, 'PROVIDER_UNAVAILABLE')

    const spoofed = await request({ ...validBody, role: 'admin' })
    assert.equal(spoofed.status, 400)
    assert.equal((await spoofed.json()).code, 'PROTECTED_CLAIM')

    const created = await request(validBody)
    assert.equal(created.status, 201)
    assert.equal(created.headers.get('etag'), '"2"')
    const createdBody = await created.json()
    const record = createdBody.change_request
    assert.equal(record.requester_id, 'viewer-subject')
    assert.equal(record.rounds[0].selected_system_id, 'system-a')
    assert.equal(record.items.length, 1)
    assert.equal(record.items[0].target_asset_id, tableUrn)
    assert.equal(record.items[0].routing_system_id, 'system-a')
    assert.equal(record.items[0].operation, 'UPSERT')
    assert.deepEqual(record.items[0].after_document, validBody.change_document)
    assert.deepEqual(record.approval_lanes, [])
    assert.equal(record.items[0].target_binding_hash.length, 64)
    assert.equal(record.rounds[0].evidence_hash.length, 64)

    const stale = await request(validBody)
    assert.equal(stale.status, 409)
    assert.equal((await stale.json()).code, 'STATE_VERSION_STALE')
    const persisted = await stateStore.read('core')
    assert.equal(persisted.version, 2)
    assert.equal(persisted.value.changeRecords.length, 1)
  } finally {
    testServer.closeAllConnections()
    await new Promise((resolvePromise, reject) => testServer.close((error) => error ? reject(error) : resolvePromise()))
  }
})

test('enforces responsible-System actors and atomically completes three independent final lanes', async () => {
  const { createPocStateStore } = await import('./poc-state-store.mjs?cr-lanes-contract-test')
  const { createPocServer } = await import('./poc-server.mjs?cr-lanes-contract-test')
  const {
    changeHistoryAccessCoreProjection,
    normalizeChangeHistoryAccessDocument,
    privateChangeHistoryAccess,
  } = await import('./poc-access-document.mjs')
  const stateStore = createPocStateStore()
  const users = [
    ['developer-one', 'developer'],
    ['developer-two', 'developer'],
    ['developer-wrong', 'developer'],
    ['steward-one', 'data_steward'],
    ['manager-one', 'manager'],
    ['admin-one', 'admin'],
  ].map(([subject_id, role]) => ({
    subject_id, role, active: true, max_security_grade: 'restricted', provider_owner_refs: [],
  }))
  const accessDocument = normalizeChangeHistoryAccessDocument({
    schema_version: 1,
    active_subject_id: 'admin-one',
    users,
    systems: [
      { system_id: 'system-a', code: 'A', name: 'System A', active: true },
      { system_id: 'system-b', code: 'B', name: 'System B', active: true },
    ],
    system_schema_scopes: [],
    system_assignments: [
      { subject_id: 'developer-one', system_id: 'system-a', responsibility: 'DEVELOPER', priority: 1, active: true },
      { subject_id: 'developer-two', system_id: 'system-a', responsibility: 'DEVELOPER', priority: 2, active: true },
      { subject_id: 'developer-wrong', system_id: 'system-b', responsibility: 'DEVELOPER', priority: 1, active: true },
      { subject_id: 'steward-one', system_id: 'system-a', responsibility: 'DATA_STEWARD', priority: 1, active: true },
      { subject_id: 'manager-one', system_id: 'system-a', responsibility: 'MANAGER', priority: 1, active: true },
    ],
  })
  await stateStore.writeChangeHistoryAccess({
    expectedAccessVersion: 0,
    expectedCoreVersion: 0,
    accessValue: privateChangeHistoryAccess(accessDocument),
    coreValue: changeHistoryAccessCoreProjection(null, accessDocument, 1),
  })
  const cr = {
    id: 'cr-three-lanes', number: 'CR-THREE', request_type: 'CHANGE_INTAKE',
    title: 'Three lanes', description: 'Three lane integration contract', state: 'FINAL_REVIEW',
    requester_id: 'viewer-one', requester_department_id: null,
    current_round_id: 'round-one', current_round_number: 1, revision_allowed: false,
    created_at: '2026-08-17T00:00:00.000Z', requested_due_date: null,
    priority: null, urgency: null, classification: 'normal', version: 1,
    items: [{ target_system_id: 'system-a', routing_system_id: 'system-a' }],
    approvals: [], approval_lanes: [], transitions: [], test_runs: [],
    rounds: [{ id: 'round-one', selected_system_id: 'system-a' }],
  }
  await stateStore.write('core', { sequence: 1, changeRecords: [cr], changeAttachments: [] })

  const actors = new Map()
  const originFor = async (subjectId) => {
    const actorServer = createPocServer({ stateStore, authenticator: testAuthenticator(subjectId) })
    await new Promise((resolvePromise) => actorServer.listen(0, '127.0.0.1', resolvePromise))
    const address = actorServer.address()
    actors.set(subjectId, actorServer)
    return `http://127.0.0.1:${address.port}`
  }
  const command = async (origin, version, body) => fetch(`${origin}/poc-api/change-requests/${cr.id}/commands`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'If-Match': `"${version}"` },
    body: JSON.stringify(body),
  })
  try {
    const [developerTwo, wrongDeveloper, steward, manager, admin] = await Promise.all([
      originFor('developer-two'), originFor('developer-wrong'), originFor('steward-one'),
      originFor('manager-one'), originFor('admin-one'),
    ])
    const wrong = await command(wrongDeveloper, 2, { command: 'final-lane', decision: 'APPROVED', reason: 'Wrong System must fail.' })
    const wrongBody = await wrong.json()
    assert.equal(wrong.status, 403, JSON.stringify(wrongBody))
    assert.equal(wrongBody.code, 'CR_SYSTEM_FORBIDDEN')
    const adminDenied = await command(admin, 2, { command: 'final-lane', decision: 'APPROVED', reason: 'Admin is not a workflow lane.' })
    assert.equal(adminDenied.status, 403)
    assert.equal((await adminDenied.json()).code, 'CR_ADMIN_LANE_DENIED')

    const developerApproval = await command(developerTwo, 2, { command: 'final-lane', decision: 'APPROVED', reason: 'Priority two is still authorized.' })
    assert.equal(developerApproval.status, 200)
    assert.equal((await developerApproval.json()).change_request.state, 'FINAL_REVIEW')
    const stewardApproval = await command(steward, 3, { command: 'final-lane', decision: 'APPROVED', reason: 'Steward lane approved.' })
    assert.equal(stewardApproval.status, 200)
    assert.equal((await stewardApproval.json()).change_request.state, 'FINAL_REVIEW')

    const concurrent = await Promise.all([
      command(manager, 4, { command: 'final-lane', decision: 'APPROVED', reason: 'Manager lane concurrent request one.' }),
      command(manager, 4, { command: 'final-lane', decision: 'APPROVED', reason: 'Manager lane concurrent request two.' }),
    ])
    assert.equal(concurrent.filter((response) => response.status === 200).length, 1)
    assert.equal(concurrent.filter((response) => response.status === 409).length, 1)
    const persisted = await stateStore.read('core')
    const finalCr = persisted.value.changeRecords[0]
    assert.equal(finalCr.state, 'COMPLETED')
    assert.deepEqual(finalCr.approval_lanes.filter((lane) => lane.stage === 'FINAL')
      .map((lane) => lane.lane_kind).sort(), ['DATA_STEWARD', 'DEVELOPER', 'MANAGER'])
    assert.equal(finalCr.transitions.filter((transition) => transition.to_state === 'COMPLETED').length, 1)
    assert.equal(persisted.version, 5)
  } finally {
    await Promise.all([...actors.values()].map(async (actorServer) => {
      actorServer.closeAllConnections()
      await new Promise((resolvePromise, reject) => actorServer.close((error) => error ? reject(error) : resolvePromise()))
    }))
  }
})

// ---------------------------------------------------------------------------
// Focused MCL configured-source summary tests
// ---------------------------------------------------------------------------

function makeChangeHistoryProjection({ sourceHashes, configuredCheckpointHash }) {
  // Use the exact known-valid catalog/access/core shapes from the existing passing test
  // (same URN format, same admin policy shape, same catalog fields) to pass validDatahubInventory.
  const assetUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,business_db.public.orders,PROD)'
  const sources = sourceHashes.map((h, i) => ({
    source_identity_hash: h, provider_name: 'DataHub',
    provider_version: `v${i}`, schema_contract_hash: '8'.repeat(64),
    created_at: `2026-0${i + 1}-01T00:00:00.000Z`,
  }))
  const events = sourceHashes.map((h, i) => ({
    event_identity: String(i).repeat(64), event_hash: String(i + 1).repeat(64),
    normalized_change_transaction_id: String(i + 2).repeat(64),
    source_identity_hash: h, topic_contract: 'MetadataChangeLog_Versioned_v1',
    source_partition: 0, source_offset: 10,
    asset_urn: assetUrn, normalized_entity_key: 'business_db.public.orders',
    category: 'TECHNICAL_SCHEMA', source_aspect: 'schemaMetadata',
    operation: 'UPDATE', before_data: { nullable: true }, after_data: { nullable: false },
    actor_ref: null,
    source_occurred_at: `2026-0${i + 1}-11T01:00:00.000Z`,
    detected_at: `2026-0${i + 1}-11T01:00:01.000Z`,
    captured_at: `2026-0${i + 1}-11T01:00:02.000Z`,
  }))
  // Only supply a checkpoint for the configuredCheckpointHash source (so it can resolve).
  const checkpoints = configuredCheckpointHash ? [{
    source_identity_hash: configuredCheckpointHash,
    topic_contract: 'MetadataChangeLog_Versioned_v1',
    source_partition: 0, first_exact_offset: 10, next_offset: 11,
    last_captured_at: '2026-01-11T01:00:02.000Z', version: 1,
  }] : []
  return {
    access: { version: 1, value: {
      schema_version: 1, active_subject_id: 'admin-sub',
      policy: { version: 1, priority_order: 'ASCENDING', fallback: ['DATA_STEWARD', 'DEVELOPER', 'DATAHUB_OWNER', 'UNASSIGNED'] },
      users: [{ subject_id: 'admin-sub', role: 'admin', active: true, provider_owner_refs: [] }],
      system_assignments: [],
    } },
    core: { version: 1, value: {
      changeRecords: [],
      adminSystems: [{ system_id: 'biz-system', code: 'BIZ', name: 'Biz', description: '', active: true, version: 1 }],
      adminSystemSchemaScopes: [['biz-system', [{ scope_id: 'scope-1', system_id: 'biz-system', platform: 'postgres', database_name: 'business_db', schema_name: 'public', active: true, version: 1 }]]],
    } },
    catalog: { version: 2, value: {
      projection_version: 1, source_scope: 'disabled',
      source_generation: 'a'.repeat(64), observed_at: '2026-08-14T00:00:00.000Z',
      items: [{ id: assetUrn, name: 'orders', dataset_kind: 'TABLE', security_grade: 'normal', platform: 'postgres', database_name: 'business_db', schema_name: 'public' }],
    } },
    mapping: { schema_version: 1, bindings: [{
      table_identity: assetUrn, system_id: 'biz-system', active: true, version: 1,
      created_at: '2026-01-01T00:00:00.000Z', created_by: 'admin-sub',
      updated_at: '2026-01-01T00:00:00.000Z', updated_by: 'admin-sub', reason: 'source fixture',
    }] },
    events,
    links: [],
    sources,
    checkpoints,
  }
}

test('configured current source among two resolves operational status and preserves full event history', async () => {
  const sourceA = '9'.repeat(64)
  const sourceB = '8'.repeat(64)
  const { createPocServer } = await import('./poc-server.mjs?mcl-configured-source-among-two')
  const projection = makeChangeHistoryProjection({ sourceHashes: [sourceA, sourceB], configuredCheckpointHash: sourceA })
  const stateStore = {
    configured: { postgres: true, redis: false },
    async readChangeHistoryAccess() { return { access: structuredClone(projection.access), core: structuredClone(projection.core) } },
    async readChangeHistoryProjection() { return structuredClone(projection) },
    async read(scope) { assert.equal(scope, 'table-system-mappings-v1'); return { value: structuredClone(projection.mapping), version: 1 } },
  }
  const saved = process.env.POC_MCL_SOURCE_IDENTITY_HASH
  try {
    process.env.POC_MCL_SOURCE_IDENTITY_HASH = sourceA
    const srv = createPocServer({ stateStore, authenticator: testAuthenticator('admin-sub') })
    await new Promise((resolve) => srv.listen(0, '127.0.0.1', resolve))
    const base = `http://127.0.0.1:${srv.address().port}`
    try {
      // Summary: configured source resolves, no SOURCE_AMBIGUOUS
      const sumRes = await fetch(`${base}/api/v1/change-history/summary?week_start=2026-08-10`)
      assert.equal(sumRes.status, 200)
      const sum = await sumRes.json()
      assert.equal(sum.sync_status, 'CONTIGUOUS_CAPTURE_RECORDED',
        `expected CONTIGUOUS_CAPTURE_RECORDED, got ${sum.sync_status}`)
      assert.notEqual(sum.sync_status, 'SOURCE_AMBIGUOUS')
      // ledger_guarantee_from comes from sourceA's EXACT_MCL row only
      assert.equal(sum.ledger_guarantee_from, '2026-01-11T01:00:02.000Z')
      // Event list/count must include ALL events from both sources
      const listRes = await fetch(`${base}/api/v1/change-history/events`)
      assert.equal(listRes.status, 200)
      const list = await listRes.json()
      assert.equal(list.total, 2, `expected 2 events (both sources), got ${list.total}`)
    } finally {
      srv.closeAllConnections()
      await new Promise((resolve, reject) => srv.close((e) => e ? reject(e) : resolve()))
    }
  } finally {
    if (saved === undefined) delete process.env.POC_MCL_SOURCE_IDENTITY_HASH
    else process.env.POC_MCL_SOURCE_IDENTITY_HASH = saved
  }
})

test('change-history summary exposes only bounded durable MCL failure diagnostics', async () => {
  const sourceHash = '9'.repeat(64)
  const { createPocServer } = await import('./poc-server.mjs?mcl-runtime-failure-diagnostic')
  const projection = makeChangeHistoryProjection({
    sourceHashes: [sourceHash], configuredCheckpointHash: sourceHash,
  })
  projection.runtimeStatus = { version: 9, value: {
    contract: 'DATARIVER_CHANGE_HISTORY_RUNTIME_STATUS_V1',
    state: 'CAPTURE_FAILED',
    classification: 'PREP_MCL_CAPTURE_DURABLE_APPEND_FAILED',
    failure_stage: 'DURABLE_APPEND',
    failure_detail_code: 'LEDGER_WRITE_REJECTED',
    observed_at: '2026-08-28T01:02:03.000Z',
  } }
  const stateStore = {
    configured: { postgres: true, redis: false },
    async readChangeHistoryAccess() {
      return { access: structuredClone(projection.access), core: structuredClone(projection.core) }
    },
    async readChangeHistoryProjection() { return structuredClone(projection) },
    async read(scope) {
      assert.equal(scope, 'table-system-mappings-v1')
      return { value: structuredClone(projection.mapping), version: 1 }
    },
  }
  const saved = process.env.POC_MCL_SOURCE_IDENTITY_HASH
  try {
    process.env.POC_MCL_SOURCE_IDENTITY_HASH = sourceHash
    const srv = createPocServer({ stateStore, authenticator: testAuthenticator('admin-sub') })
    await new Promise((resolve) => srv.listen(0, '127.0.0.1', resolve))
    const base = `http://127.0.0.1:${srv.address().port}`
    try {
      const summary = await (await fetch(`${base}/api/v1/change-history/summary?week_start=2026-08-10`)).json()
      assert.equal(summary.capture_state, 'CAPTURE_FAILED')
      assert.equal(summary.capture_failure_classification, 'PREP_MCL_CAPTURE_DURABLE_APPEND_FAILED')
      assert.equal(summary.capture_failure_stage, 'DURABLE_APPEND')
      assert.equal(summary.capture_failure_detail_code, 'LEDGER_WRITE_REJECTED')
      assert.equal(summary.capture_failure_record_shape, null)

      projection.runtimeStatus.value.classification = 'PREP_MCL_CAPTURE_RECORD_CONTRACT_FAILED'
      projection.runtimeStatus.value.failure_stage = 'RECORD_NORMALIZATION'
      projection.runtimeStatus.value.failure_detail_code = 'CREATED_TIME_INVALID'
      projection.runtimeStatus.value.record_shape = {
        contract: 'DATARIVER_MCL_REJECTED_RECORD_SHAPE_V1',
        partition: 0,
        offset: 17,
        entity_type: 'dataset',
        aspect_name: 'schemaMetadata',
        change_type: 'UPSERT',
        aspect_present: true,
        previous_aspect_value_present: false,
        aspect_content_type: 'APPLICATION_JSON',
        previous_aspect_content_type: 'MISSING',
        created_type: 'OBJECT',
        created_time_type: 'NUMBER',
        created_time_representation: 'NUMBER',
        created_actor_type: 'STRING',
        current_aspect_decoded_object: true,
        previous_aspect_decoded_object: false,
        current_collection_item_count: 8,
        previous_collection_item_count: null,
        rejection_locus: 'CREATED_TIME_INVALID',
      }
      const normalization = await (await fetch(`${base}/api/v1/change-history/summary?week_start=2026-08-10`)).json()
      assert.deepEqual(normalization.capture_failure_record_shape, projection.runtimeStatus.value.record_shape)

      projection.runtimeStatus.value.record_shape.entity_type = 'urn:li:dataset:private'
      const rejectedShape = await (await fetch(`${base}/api/v1/change-history/summary?week_start=2026-08-10`)).json()
      assert.equal(rejectedShape.capture_failure_record_shape, null)
      assert.equal(JSON.stringify(rejectedShape).includes('urn:li:dataset:private'), false)

      projection.runtimeStatus.value.classification = 'PREP_MCL_CAPTURE_DURABLE_APPEND_FAILED'
      delete projection.runtimeStatus.value.failure_stage
      delete projection.runtimeStatus.value.failure_detail_code
      delete projection.runtimeStatus.value.record_shape
      const legacy = await (await fetch(`${base}/api/v1/change-history/summary?week_start=2026-08-10`)).json()
      assert.equal(legacy.capture_state, 'CAPTURE_FAILED')
      assert.equal(legacy.capture_failure_classification, 'PREP_MCL_CAPTURE_DURABLE_APPEND_FAILED')
      assert.equal(legacy.capture_failure_stage, null)
      assert.equal(legacy.capture_failure_detail_code, null)

      projection.runtimeStatus.value.failure_stage = 'secret=value'
      projection.runtimeStatus.value.failure_detail_code = 'https://private.invalid/schema'
      const sanitized = await (await fetch(`${base}/api/v1/change-history/summary?week_start=2026-08-10`)).json()
      assert.equal(sanitized.capture_failure_stage, null)
      assert.equal(sanitized.capture_failure_detail_code, null)
      assert.equal(JSON.stringify(sanitized).includes('private.invalid'), false)
    } finally {
      srv.closeAllConnections()
      await new Promise((resolve, reject) => srv.close((error) => error ? reject(error) : resolve()))
    }
  } finally {
    if (saved === undefined) delete process.env.POC_MCL_SOURCE_IDENTITY_HASH
    else process.env.POC_MCL_SOURCE_IDENTITY_HASH = saved
  }
})

test('missing or syntactically invalid configured source falls back to SOURCE_AMBIGUOUS with two stored sources', async () => {
  const sourceA = '9'.repeat(64)
  const sourceB = '8'.repeat(64)
  const { createPocServer } = await import('./poc-server.mjs?mcl-missing-configured-source')
  const projection = makeChangeHistoryProjection({ sourceHashes: [sourceA, sourceB], configuredCheckpointHash: sourceA })
  const stateStore = {
    configured: { postgres: true, redis: false },
    async readChangeHistoryAccess() { return { access: structuredClone(projection.access), core: structuredClone(projection.core) } },
    async readChangeHistoryProjection() { return structuredClone(projection) },
    async read(scope) { assert.equal(scope, 'table-system-mappings-v1'); return { value: structuredClone(projection.mapping), version: 1 } },
  }
  const saved = process.env.POC_MCL_SOURCE_IDENTITY_HASH
  try {
    // No env var set — must fall back to ambiguous
    delete process.env.POC_MCL_SOURCE_IDENTITY_HASH
    const srv = createPocServer({ stateStore, authenticator: testAuthenticator('admin-sub') })
    await new Promise((resolve) => srv.listen(0, '127.0.0.1', resolve))
    const base = `http://127.0.0.1:${srv.address().port}`
    try {
      const sum1 = await (await fetch(`${base}/api/v1/change-history/summary?week_start=2026-08-10`)).json()
      assert.equal(sum1.sync_status, 'SOURCE_AMBIGUOUS', `unset: expected SOURCE_AMBIGUOUS, got ${sum1.sync_status}`)

      // Syntactically invalid value (not 64 hex chars) — same fallback
      process.env.POC_MCL_SOURCE_IDENTITY_HASH = 'not-a-hash'
      const sum2 = await (await fetch(`${base}/api/v1/change-history/summary?week_start=2026-08-10`)).json()
      assert.equal(sum2.sync_status, 'SOURCE_AMBIGUOUS', `invalid: expected SOURCE_AMBIGUOUS, got ${sum2.sync_status}`)

      // Event count still returns both events
      const list = await (await fetch(`${base}/api/v1/change-history/events`)).json()
      assert.equal(list.total, 2)
    } finally {
      srv.closeAllConnections()
      await new Promise((resolve, reject) => srv.close((e) => e ? reject(e) : resolve()))
    }
  } finally {
    if (saved === undefined) delete process.env.POC_MCL_SOURCE_IDENTITY_HASH
    else process.env.POC_MCL_SOURCE_IDENTITY_HASH = saved
  }
})

test('configured source hash matching no stored source fails closed with SOURCE_NOT_CONFIGURED', async () => {
  const sourceA = '9'.repeat(64)
  const unknownHash = '7'.repeat(64)
  const { createPocServer } = await import('./poc-server.mjs?mcl-configured-source-not-found')
  const projection = makeChangeHistoryProjection({ sourceHashes: [sourceA], configuredCheckpointHash: sourceA })
  const stateStore = {
    configured: { postgres: true, redis: false },
    async readChangeHistoryAccess() { return { access: structuredClone(projection.access), core: structuredClone(projection.core) } },
    async readChangeHistoryProjection() { return structuredClone(projection) },
    async read(scope) { assert.equal(scope, 'table-system-mappings-v1'); return { value: structuredClone(projection.mapping), version: 1 } },
  }
  const saved = process.env.POC_MCL_SOURCE_IDENTITY_HASH
  try {
    process.env.POC_MCL_SOURCE_IDENTITY_HASH = unknownHash
    const srv = createPocServer({ stateStore, authenticator: testAuthenticator('admin-sub') })
    await new Promise((resolve) => srv.listen(0, '127.0.0.1', resolve))
    const base = `http://127.0.0.1:${srv.address().port}`
    try {
      const sum = await (await fetch(`${base}/api/v1/change-history/summary?week_start=2026-08-10`)).json()
      assert.equal(sum.sync_status, 'SOURCE_NOT_CONFIGURED', `expected SOURCE_NOT_CONFIGURED, got ${sum.sync_status}`)
      assert.equal(sum.capture_state, 'SOURCE_NOT_CONFIGURED')
      assert.equal(sum.ledger_guarantee_from, null)
      // Events are still all returned
      const list = await (await fetch(`${base}/api/v1/change-history/events`)).json()
      assert.equal(list.total, 1)
    } finally {
      srv.closeAllConnections()
      await new Promise((resolve, reject) => srv.close((e) => e ? reject(e) : resolve()))
    }
  } finally {
    if (saved === undefined) delete process.env.POC_MCL_SOURCE_IDENTITY_HASH
    else process.env.POC_MCL_SOURCE_IDENTITY_HASH = saved
  }
})

test('MCP adapter bounded implementation', async () => {
  const { authorizeManagedK9Release, createPocServer } = await import('./poc-server.mjs?mcp-full')
  const mcpSubjectId = 'mcp-subject'
  const mcpWorkspaceId = '00000000-0000-4000-8000-000000000061'
  const otherWorkspaceId = '00000000-0000-4000-8000-000000000062'
  const projection = makeChangeHistoryProjection({ sourceHashes: [], configuredCheckpointHash: null })
  projection.access.value.active_subject_id = 'admin-sub'
  projection.access.value.users.push({ subject_id: mcpSubjectId, role: 'developer', active: true, provider_owner_refs: [] })
  projection.access.value.users.push({ subject_id: 'other', role: 'developer', active: true, provider_owner_refs: [] })
  const grantedTableUrn = 'urn:li:dataset:(urn:li:dataPlatform:generic,mcp.authorized_table,PROD)'
  const deniedTableUrn = 'urn:li:dataset:(urn:li:dataPlatform:generic,mcp.denied_identity_must_not_leak,PROD)'
  const deniedMarker = 'mcp-denied-identity-must-not-leak'
  const managedGraphId = '01a02d2a-f8a0-7658-b5da-890eccdccf44'
  let mcpGrants = [{ active: true, tableUrn: grantedTableUrn }]
  let writeCalled = false
  let managedAssetsFailure = null
  const mcpCredentials = new Map([
    [mcpSubjectId, { subjectId: mcpSubjectId, loginEnabled: true, lockedUntil: null }],
    ['inactive', { subjectId: 'inactive', loginEnabled: true, lockedUntil: null }],
    ['disabled-sub', { subjectId: 'disabled-sub', loginEnabled: false, lockedUntil: null }],
    ['locked-sub', { subjectId: 'locked-sub', loginEnabled: true, lockedUntil: new Date(Date.now() + 60000).toISOString() }]
  ])
  const stateStore = {
    configured: { postgres: true, redis: false },
    async readChangeHistoryAccess() { return { access: structuredClone(projection.access), core: structuredClone(projection.core) } },
    async readChangeHistoryProjection() { return structuredClone(projection) },
    async write() { writeCalled = true },
    async listUserTableGrants(subjectId) { return subjectId === mcpSubjectId ? mcpGrants : [] },
    async listK9ManagedGraphAssets() {
      if (managedAssetsFailure === 'malformed') {
        return [{ graph_id: `${deniedMarker}:${providerToken}`, classification: 'INTERNAL' }]
      }
      if (managedAssetsFailure) throw managedAssetsFailure
      return [{
        graph_id: managedGraphId,
        managed_intent: 'metadata-lineage',
        name: 'CATALOG_MIRROR',
        classification: 'INTERNAL',
        subject_id: 'k9-service-subject',
        ontology_version_id: 'managed-ontology',
        studio_release_id: 'managed-studio-release',
        active_release_pointer: 'managed-active-release',
        active_input_snapshot_hash: 'managed-input-hash',
        active_release_hash: 'managed-release-hash',
        publication_version: 1,
        latest_result: 'RUN',
        active_manifest: { node_count: 3, edge_count: 2, model_version: 2 },
      }]
    },
    async readFeatureSecurityPolicy() { return null },
    async readLocalCredential(subjectId) { return mcpCredentials.get(subjectId) || null },
  }
  const releaseFixture = (s) => ({
    id: 'r1',
    graph_id: s.graphId,
    release_no: 1,
    ontology_version_id: 'o',
    content_hash: 'hash1',
    node_count: s.authorizedRelease?.nodes.length ?? 1,
    edge_count: s.authorizedRelease?.edges.length ?? 1,
    published_by: 'p',
    published_at: '2026',
    publisher_name: null,
    publisher_email: null,
  })
  const provFixture = [{ source_ref: 'sr1', source_locator: 'sl1', source_version: 'sv1', method: 'm1', confidence: 1 }]
  const nodeFixture = [{ id: 'n1', entity_type: 't1', properties: { p: 1 }, classification: 1, provenance: provFixture }]
  const edgeFixture = [{ id: 'e1', source_id: 'n1', target_id: 'n2', edge_type: 'et1', properties: {}, classification: 1, provenance: provFixture }]
  const canonicalAuthorizationRelease = {
    manifest: { graph_id: 'authorization-filtered' },
    nodes: [
      { id: 'table-allowed', type: 'class.table', classification: 'INTERNAL', properties: { external_urn: grantedTableUrn, name: 'Allowed table', nested: { source: grantedTableUrn } } },
      { id: 'column-allowed', type: 'class.column', classification: 'INTERNAL', properties: { dataset_urn: grantedTableUrn, name: 'allowed_id' } },
      { id: deniedMarker, type: 'class.table', classification: 'INTERNAL', properties: { external_urn: deniedTableUrn, name: deniedMarker, nested: { source: deniedTableUrn } } },
      { id: 'semantic-shared', type: 'class.business_term', classification: 'INTERNAL', properties: { name: 'Shared semantic hub' } },
    ],
    edges: [
      { id: 'allowed-to-hub', source: 'table-allowed', target: 'semantic-shared', type: 'rel.table_has_glossary_term', properties: { source_entity_urn: grantedTableUrn } },
      { id: deniedMarker, source: deniedMarker, target: 'semantic-shared', type: 'rel.table_has_glossary_term', properties: { source_entity_urn: deniedTableUrn, nested: { source: deniedTableUrn } } },
    ],
  }
  const authorizedSnapshot = (scope) => {
    const provenance = (identity) => [{ source_ref: identity, source_locator: identity, source_version: 'authorized-source-version', method: 'DATAHUB_MANAGED_PROJECTION', confidence: 1 }]
    return {
      release: releaseFixture(scope),
      nodes: scope.authorizedRelease.nodes.map((node) => ({
        id: node.id,
        entity_type: node.type,
        properties: node.properties,
        classification: 1,
        provenance: provenance(node.properties.external_urn || node.id),
      })),
      edges: scope.authorizedRelease.edges.map((edge) => ({
        id: edge.id,
        source_id: edge.source,
        target_id: edge.target,
        edge_type: edge.type,
        properties: edge.properties,
        classification: 1,
        provenance: provenance(`${edge.source}->${edge.target}`),
      })),
      filtered: true,
    }
  }

  let lastScope = null
  let lastArgs = null
  const mcpKnowledgeChatScope = async (ctx, g, r) => {
    lastScope = { principal: ctx.principal, knowledgeAdapter: ctx.knowledgeAdapter, graphId: g, studioReleaseId: r }
    if (g === 'unauth') throw Object.assign(new Error('Nope'), { statusCode: 404, code: 'NOT_FOUND' })
    if (g === 'fail' || g === 'graph-provider-unavailable') throw new Error(`Provider unavailable: ${providerBody}; ${providerToken}; ${mcpToken}`)
    if (g === 'graph-provider-timeout') throw Object.assign(new Error(`Provider timeout: ${providerBody}; ${providerToken}; ${mcpToken}`), { name: 'TimeoutError' })
    if (g === 'authorization-filtered') {
      return {
        graphId: g,
        studioReleaseId: r,
        authorizedRelease: authorizeManagedK9Release(ctx.principal, canonicalAuthorizationRelease, {
          knowledgeAdapter: ctx.knowledgeAdapter,
        }),
      }
    }
    return { graphId: g, studioReleaseId: r }
  }
  const mcpKnowledgeChatSnapshot = async (s) => {
    if (s.graphId === 'authorization-filtered') return authorizedSnapshot(s)
    if (s.graphId === 'extra') return { release: releaseFixture(s), nodes: nodeFixture, edges: edgeFixture, filtered: false, extraKey: providerToken }
    if (s.graphId === 'mismatch') return { release: releaseFixture({ graphId: 'wrong' }), nodes: nodeFixture, edges: edgeFixture, filtered: false }
    return { release: releaseFixture(s), nodes: nodeFixture, edges: edgeFixture, filtered: false }
  }
  const mcpKnowledgeGraphRag = async (s, args) => {
    lastArgs = args
    if (s.graphId === 'rag-provider-unavailable') throw new Error(`GraphRAG unavailable: ${providerBody}; ${providerToken}; ${mcpToken}`)
    if (s.graphId === 'rag-provider-timeout') throw Object.assign(new Error(`GraphRAG timeout: ${providerBody}; ${providerToken}; ${mcpToken}`), { name: 'TimeoutError' })
    if (s.graphId === 'authorization-filtered') {
      const snapshot = authorizedSnapshot(s)
      const evidence = [...snapshot.nodes, ...snapshot.edges]
      return {
        release: snapshot.release,
        nodes: snapshot.nodes,
        edges: snapshot.edges,
        truncated: snapshot.filtered,
        answer: `Authorized answer for ${args.question}`,
        citations: evidence.map((item) => ({
          evidence_id: item.id,
          source_locator: item.provenance[0].source_locator,
          source_version: item.provenance[0].source_version,
          page_number: null,
        })),
        model_audit: { provider: 'p', model: 'm', prompt_version: 'pv', tool_schema_version: 'tv' },
      }
    }
    if (s.graphId === 'malformed') return { release: releaseFixture(s), nodes: nodeFixture, edges: edgeFixture, truncated: 'yes', answer: providerBody, citations: [{ evidence_id: 'e', source_locator: providerToken, source_version: 'v', page_number: null }], model_audit: { provider: 'p', model: 'm', prompt_version: 'pv', tool_schema_version: 'tv' } }
    if (s.graphId === 'mismatch') return { release: releaseFixture({ graphId: 'wrong' }), nodes: nodeFixture, edges: edgeFixture, truncated: false, answer: `ans to ${args.question}`, citations: [{ evidence_id: 'e', source_locator: 'loc', source_version: 'v', page_number: null }], model_audit: { provider: 'p', model: 'm', prompt_version: 'pv', tool_schema_version: 'tv' } }
    return { release: releaseFixture(s), nodes: nodeFixture, edges: edgeFixture, truncated: false, answer: `ans to ${args.question}`, citations: [{ evidence_id: 'e', source_locator: 'loc', source_version: 'v', page_number: null }], model_audit: { provider: 'p', model: 'm', prompt_version: 'pv', tool_schema_version: 'tv' } }
  }
  const mcpToken = 'A'.repeat(32)
  const airflowToken = 'B'.repeat(32)
  const rotatedToken = 'C'.repeat(32)
  const providerToken = 'provider-token-must-not-leak'
  const providerBody = 'provider-body-must-not-leak'
  const metadataSearchCalls = []
  const mcpMetadataSearch = async (question, route, limit, principal) => {
    metadataSearchCalls.push({ question, route, limit, principal })
    if (question === 'provider unavailable') throw new Error(`DataHub unavailable: ${providerBody}; ${providerToken}`)
    if (question === 'provider timeout') {
      throw Object.assign(new Error(`DataHub timeout: ${providerBody}`), { name: 'TimeoutError' })
    }
    if (question === 'malformed response') return { items: [] }
    return [
      {
        id: grantedTableUrn,
        external_urn: grantedTableUrn,
        name: 'Authorized synthetic table',
        dataset_kind: 'TABLE',
        provider_description: 'Authorized metadata',
        classification: 'PUBLIC',
        retrieval_method: 'DATAHUB_GMS',
        raw_provider_body: providerBody,
        provider_token: providerToken,
      },
      {
        id: deniedTableUrn,
        external_urn: deniedTableUrn,
        name: deniedMarker,
        dataset_kind: 'TABLE',
        provider_description: deniedMarker,
        classification: 'PUBLIC',
        retrieval_method: 'DATAHUB_GMS',
      },
    ].filter((item) => principal.activeTableGrantUrns.has(item.id))
  }

  const srvMissing = createPocServer({ stateStore, authenticator: testAuthenticator('admin-sub') })
  await new Promise((resolve) => srvMissing.listen(0, '127.0.0.1', resolve))
  const baseMissing = `http://127.0.0.1:${srvMissing.address().port}`
  const rMissing = await fetch(`${baseMissing}/api/v1/mcp`, { method: 'POST', body: JSON.stringify({ jsonrpc: '2.0', method: 'initialize', id: 1 }) })
  assert.equal(rMissing.status, 503)
  srvMissing.closeAllConnections()
  await new Promise((resolve) => srvMissing.close(resolve))

  const srvUnknownSub = createPocServer({ stateStore, authenticator: testAuthenticator('admin-sub'), mcpServiceToken: mcpToken, mcpSubjectId: 'unknown', mcpWorkspaceId })
  await new Promise((resolve) => srvUnknownSub.listen(0, '127.0.0.1', resolve))
  const baseUnknownSub = `http://127.0.0.1:${srvUnknownSub.address().port}`
  const rUnknownSub = await (await fetch(`${baseUnknownSub}/api/v1/mcp`, { method: 'POST', headers: { Authorization: `Bearer ${mcpToken}` }, body: JSON.stringify({ jsonrpc: '2.0', method: 'initialize', id: 1 }) })).json()
  assert.equal(rUnknownSub.status, 401)
  assert.equal(rUnknownSub.code, 'SERVICE_AUTHENTICATION_FAILED')
  assert.equal(rUnknownSub.detail, 'Valid service authentication is required.')
  srvUnknownSub.closeAllConnections()
  await new Promise((resolve) => srvUnknownSub.close(resolve))

  const srvDisabledSub = createPocServer({ stateStore, authenticator: testAuthenticator('admin-sub'), mcpServiceToken: mcpToken, mcpSubjectId: 'disabled-sub', mcpWorkspaceId })
  await new Promise((resolve) => srvDisabledSub.listen(0, '127.0.0.1', resolve))
  const baseDisabledSub = `http://127.0.0.1:${srvDisabledSub.address().port}`
  const rDisabledSub = await (await fetch(`${baseDisabledSub}/api/v1/mcp`, { method: 'POST', headers: { Authorization: `Bearer ${mcpToken}` }, body: JSON.stringify({ jsonrpc: '2.0', method: 'initialize', id: 1 }) })).json()
  assert.equal(rDisabledSub.status, 401)
  assert.equal(rDisabledSub.code, 'SERVICE_AUTHENTICATION_FAILED')
  assert.equal(rDisabledSub.detail, 'Valid service authentication is required.')
  srvDisabledSub.closeAllConnections()
  await new Promise((resolve) => srvDisabledSub.close(resolve))

  const srvLockedSub = createPocServer({ stateStore, authenticator: testAuthenticator('admin-sub'), mcpServiceToken: mcpToken, mcpSubjectId: 'locked-sub', mcpWorkspaceId })
  await new Promise((resolve) => srvLockedSub.listen(0, '127.0.0.1', resolve))
  const baseLockedSub = `http://127.0.0.1:${srvLockedSub.address().port}`
  const rLockedSub = await (await fetch(`${baseLockedSub}/api/v1/mcp`, { method: 'POST', headers: { Authorization: `Bearer ${mcpToken}` }, body: JSON.stringify({ jsonrpc: '2.0', method: 'initialize', id: 1 }) })).json()
  assert.equal(rLockedSub.status, 401)
  assert.equal(rLockedSub.code, 'SERVICE_AUTHENTICATION_FAILED')
  assert.equal(rLockedSub.detail, 'Valid service authentication is required.')
  srvLockedSub.closeAllConnections()
  await new Promise((resolve) => srvLockedSub.close(resolve))

  projection.access.value.users.push({ subject_id: 'inactive', role: 'developer', active: false, provider_owner_refs: [] })
  const srvInactiveSub = createPocServer({ stateStore, authenticator: testAuthenticator('admin-sub'), mcpServiceToken: mcpToken, mcpSubjectId: 'inactive', mcpWorkspaceId })
  await new Promise((resolve) => srvInactiveSub.listen(0, '127.0.0.1', resolve))
  const baseInactiveSub = `http://127.0.0.1:${srvInactiveSub.address().port}`
  assert.equal((await (await fetch(`${baseInactiveSub}/api/v1/mcp`, { method: 'POST', headers: { Authorization: `Bearer ${mcpToken}` }, body: JSON.stringify({ jsonrpc: '2.0', method: 'initialize', id: 1 }) })).json()).status, 403)
  srvInactiveSub.closeAllConnections()
  await new Promise((resolve) => srvInactiveSub.close(resolve))

  const srvWorkspaceMismatch = createPocServer({ stateStore, authenticator: testAuthenticator('admin-sub'), mcpServiceToken: mcpToken, mcpSubjectId, mcpWorkspaceId: otherWorkspaceId })
  await new Promise((resolve) => srvWorkspaceMismatch.listen(0, '127.0.0.1', resolve))
  const baseWorkspaceMismatch = `http://127.0.0.1:${srvWorkspaceMismatch.address().port}`
  assert.equal((await (await fetch(`${baseWorkspaceMismatch}/api/v1/mcp`, { method: 'POST', headers: { Authorization: `Bearer ${mcpToken}` }, body: JSON.stringify({ jsonrpc: '2.0', method: 'initialize', id: 1 }) })).json()).status, 403)
  srvWorkspaceMismatch.closeAllConnections()
  await new Promise((resolve) => srvWorkspaceMismatch.close(resolve))

  const srv = createPocServer({
    stateStore,
    authenticator: { ...testAuthenticator('admin-sub'), assertOrigin() { throw new Error('Not allowed') } },
    airflowServiceToken: airflowToken,
    mcpServiceToken: mcpToken,
    mcpSubjectId,
    mcpWorkspaceId,
    mcpMetadataSearch,
    mcpKnowledgeChatScope,
    mcpKnowledgeChatSnapshot,
    mcpKnowledgeGraphRag,
  })
  await new Promise((resolve) => srv.listen(0, '127.0.0.1', resolve))
  const base = `http://127.0.0.1:${srv.address().port}`
  try {
    const postJson = async (path, body, headers = {}) => {
      const res = await fetch(`${base}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(body) })
      if (res.headers.get('content-type')?.includes('application/problem+json')) {
        return { status: res.status, error: await res.json() }
      }
      return { status: res.status, body: await res.json() }
    }
    const assertNoSensitiveLeak = (value, additionalMarkers = []) => {
      const serialized = JSON.stringify(value)
      for (const marker of [deniedMarker, deniedTableUrn, providerBody, providerToken, mcpToken, ...additionalMarkers]) {
        assert.equal(serialized.includes(marker), false, `response leaked ${marker}`)
      }
    }
    const assertInternalError = (value) => {
      assert.equal(value.status, 200)
      assert.ok(value.body?.error, JSON.stringify(value))
      assert.equal(value.body.error.code, -32603)
      assert.equal(value.body.error.message, 'Internal error')
      assertNoSensitiveLeak(value)
    }
    const req0 = { jsonrpc: '2.0', method: 'initialize', id: 1 }

    assert.equal((await fetch(`${base}/api/v1/mcp`, { method: 'POST', body: JSON.stringify(req0) })).status, 401)
    const rejectedToken = 'rejected-token-must-not-leak'
    const rejectedTokenResponse = await fetch(`${base}/api/v1/mcp`, { method: 'POST', headers: { Authorization: `Bearer ${rejectedToken}` }, body: JSON.stringify(req0) })
    assert.equal(rejectedTokenResponse.status, 401)
    assertNoSensitiveLeak(await rejectedTokenResponse.json(), [rejectedToken])
    assert.equal((await fetch(`${base}/api/v1/mcp`, { method: 'POST', headers: { Authorization: `Bearer ${rotatedToken}` }, body: JSON.stringify(req0) })).status, 401)
    assert.equal((await fetch(`${base}/api/v1/mcp`, { method: 'POST', headers: { Authorization: `Bearer ${airflowToken}` }, body: JSON.stringify(req0) })).status, 401)
    assert.equal((await fetch(`${base}/api/v1/mcp`, { method: 'GET' })).status, 405)
    assert.equal((await fetch(`${base}/api/v1/mcp`, { method: 'PUT' })).status, 405)

    const h = { Authorization: `Bearer ${mcpToken}` }
    assert.equal((await fetch(`${base}/api/v1/mcp?workspace_id=${otherWorkspaceId}`, { method: 'POST', headers: h, body: JSON.stringify(req0) })).status, 403)
    assert.equal((await fetch(`${base}/api/v1/mcp?workspace=${otherWorkspaceId}`, { method: 'POST', headers: h, body: JSON.stringify(req0) })).status, 403)
    assert.equal((await fetch(`${base}/api/v1/mcp`, { method: 'POST', headers: { ...h, 'x-workspace-id': otherWorkspaceId }, body: JSON.stringify(req0) })).status, 403)
    assert.equal((await fetch(`${base}/api/v1/mcp`, { method: 'POST', headers: h, body: '{ malformed' })).status, 400)

    const id0 = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'initialize', id: 0 }, h)
    assert.equal(id0.body.id, 0)

    const list = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/list', id: 2 }, h)
    assert.deepEqual(list.body.result.tools.map((tool) => tool.name), [
      'metadata_search',
      'knowledge_graph_assets',
      'knowledge_lineage_traversal',
      'knowledge_release_snapshot',
      'knowledge_release_graphrag',
    ])
    assert.ok(list.body.result.tools.every((tool) => tool.outputSchema.additionalProperties === false))
    const relSchema0 = list.body.result.tools[3].outputSchema.properties.release
    const nodeSchema0 = list.body.result.tools[3].outputSchema.properties.nodes.items
    const edgeSchema0 = list.body.result.tools[3].outputSchema.properties.edges.items
    const provSchema0 = nodeSchema0.properties.provenance.items
    assert.equal(relSchema0.additionalProperties, false)
    assert.equal(nodeSchema0.additionalProperties, false)
    assert.equal(edgeSchema0.additionalProperties, false)
    assert.equal(provSchema0.additionalProperties, false)
    const citeSchema1 = list.body.result.tools[4].outputSchema.properties.citations.items
    const modSchema1 = list.body.result.tools[4].outputSchema.properties.model_audit
    assert.equal(citeSchema1.additionalProperties, false)
    assert.equal(modSchema1.additionalProperties, false)

    const listParams = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/list', params: {}, id: 2 }, h)
    assert.equal(listParams.body.error.code, -32602)

    const unkMethod = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'unknown', id: 7 }, h)
    assert.equal(unkMethod.body.error.code, -32601)

    const unkTool = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'unknown', arguments: {} }, id: 8 }, h)
    assert.equal(unkTool.body.error.code, -32601)

    const resources = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'resources/list', id: 9 }, h)
    assert.equal(resources.body.result.resources.length, 1)
    assert.equal(resources.body.result.resources[0].uri, `datariver://knowledge/assets/${managedGraphId}`)
    assertNoSensitiveLeak(resources)

    const resource = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'resources/read', params: { uri: resources.body.result.resources[0].uri }, id: 10 }, h)
    assert.equal(resource.body.result.contents.length, 1)
    assert.equal(JSON.parse(resource.body.result.contents[0].text).id, managedGraphId)
    assertNoSensitiveLeak(resource)

    const hiddenResource = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'resources/read', params: { uri: `datariver://knowledge/assets/${deniedMarker}` }, id: 11 }, h)
    assert.equal(hiddenResource.status, 404)
    assert.equal(hiddenResource.body.code, 'KNOWLEDGE_GRAPH_NOT_FOUND')
    assertNoSensitiveLeak(hiddenResource)

    const assets = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_graph_assets', arguments: {} }, id: 12 }, h)
    assert.equal(assets.body.result.structuredContent.items.length, 1)
    assert.equal(assets.body.result.structuredContent.items[0].id, managedGraphId)
    assertNoSensitiveLeak(assets)

    for (const [failure, request] of [
      [new Error(`Asset registry unavailable: ${providerBody}; ${providerToken}; ${mcpToken}`), { jsonrpc: '2.0', method: 'resources/list', id: 13 }],
      [Object.assign(new Error(`Asset registry timeout: ${providerBody}; ${providerToken}; ${mcpToken}`), { name: 'TimeoutError' }), { jsonrpc: '2.0', method: 'resources/read', params: { uri: resources.body.result.resources[0].uri }, id: 14 }],
      ['malformed', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_graph_assets', arguments: {} }, id: 15 }],
    ]) {
      managedAssetsFailure = failure
      assertInternalError(await postJson('/api/v1/mcp', request, h))
      managedAssetsFailure = null
    }

    const metadata = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'metadata_search', arguments: { query: 'authorized table', limit: 3 } }, id: 16 }, h)
    assert.equal(metadata.status, 200)
    assert.deepEqual(metadata.body.result.structuredContent.items, [{
      id: grantedTableUrn,
      external_urn: grantedTableUrn,
      name: 'Authorized synthetic table',
      entity_type: 'TABLE',
      description: 'Authorized metadata',
      classification: 'PUBLIC',
      retrieval_method: 'DATAHUB_GMS',
      source: 'DataHub',
    }])
    assert.equal(metadataSearchCalls.at(-1).principal.subjectId, mcpSubjectId)
    assert.deepEqual([...metadataSearchCalls.at(-1).principal.activeTableGrantUrns], [grantedTableUrn])
    assert.equal(metadataSearchCalls.at(-1).limit, 3)
    assertNoSensitiveLeak(metadata)

    mcpGrants = []
    const zeroScope = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'metadata_search', arguments: { query: 'authorized table' } }, id: 13 }, h)
    assert.deepEqual(zeroScope.body.result.structuredContent.items, [])
    assert.deepEqual([...metadataSearchCalls.at(-1).principal.activeTableGrantUrns], [])
    mcpGrants = [{ active: true, tableUrn: grantedTableUrn }]

    for (const [query, id] of [['provider unavailable', 14], ['provider timeout', 15], ['malformed response', 16]]) {
      const failedSearch = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'metadata_search', arguments: { query } }, id }, h)
      assertInternalError(failedSearch)
    }

    const badEnv = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'initialize', id: 1, extra: 1 }, h)
    assert.equal(badEnv.body.error.code, -32600)

    const badParams = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'initialize', id: 1, params: {} }, h)
    assert.equal(badParams.body.error.code, -32602)

    const snap = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_snapshot', arguments: { graph_id: 'g1', release_id: 'r1' } }, id: 4 }, h)
    assert.equal(snap.status, 200)
    assert.equal(snap.body.result.structuredContent.release.graph_id, 'g1')
    assert.equal(snap.body.result.structuredContent.release.content_hash, 'hash1')
    assert.equal(snap.body.result.structuredContent.nodes[0].provenance[0].source_version, 'sv1')

    const traversal = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_lineage_traversal', arguments: { graph_id: 'g1', release_id: 'r1', start_node_id: 'n1' } }, id: 11 }, h)
    assert.equal(traversal.status, 200)
    assert.equal(traversal.body.result.structuredContent.release.graph_id, 'g1')
    assert.equal(traversal.body.result.structuredContent.nodes[0].id, 'n1')
    assert.equal(lastScope.knowledgeAdapter, 'MCP')

    const rag = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_graphrag', arguments: { graph_id: 'g1', release_id: 'r1', question: 'drop tables' } }, id: 5 }, h)
    assert.equal(rag.status, 200)
    assert.equal(rag.body.result.structuredContent.answer, 'ans to drop tables')
    assert.equal(rag.body.result.structuredContent.citations[0].evidence_id, 'e')
    assert.equal(rag.body.result.structuredContent.edges[0].provenance[0].source_version, 'sv1')

    const filteredSnapshotResponse = await postJson('/api/v1/mcp', {
      jsonrpc: '2.0', method: 'tools/call',
      params: { name: 'knowledge_release_snapshot', arguments: { graph_id: 'authorization-filtered', release_id: 'r1' } },
      id: 17,
    }, h)
    const filteredSnapshot = filteredSnapshotResponse.body.result.structuredContent
    assert.deepEqual(filteredSnapshot.nodes.map((node) => node.id), ['table-allowed', 'column-allowed', 'semantic-shared'])
    assert.deepEqual(filteredSnapshot.edges.map((edge) => edge.id), ['allowed-to-hub'])
    assert.equal(filteredSnapshot.release.node_count, 3)
    assert.equal(filteredSnapshot.release.edge_count, 1)
    assert.equal(filteredSnapshot.nodes.find((node) => node.id === 'semantic-shared').properties.name, 'Shared semantic hub')
    assertNoSensitiveLeak(filteredSnapshot.release)
    assertNoSensitiveLeak(filteredSnapshot.nodes)
    assertNoSensitiveLeak(filteredSnapshot.edges)
    assertNoSensitiveLeak(filteredSnapshot.nodes.map((node) => node.properties))
    assertNoSensitiveLeak(filteredSnapshot.edges.map((edge) => edge.properties))
    assertNoSensitiveLeak(filteredSnapshot.nodes.flatMap((node) => node.provenance))
    assertNoSensitiveLeak(filteredSnapshot.edges.flatMap((edge) => edge.provenance))

    const filteredTraversalResponse = await postJson('/api/v1/mcp', {
      jsonrpc: '2.0', method: 'tools/call',
      params: { name: 'knowledge_lineage_traversal', arguments: { graph_id: 'authorization-filtered', release_id: 'r1', start_node_id: 'table-allowed' } },
      id: 18,
    }, h)
    const filteredTraversal = filteredTraversalResponse.body.result.structuredContent
    assert.deepEqual(filteredTraversal.nodes.map((node) => node.id), ['table-allowed', 'semantic-shared'])
    assert.deepEqual(filteredTraversal.edges.map((edge) => edge.id), ['allowed-to-hub'])
    assertNoSensitiveLeak(filteredTraversalResponse)

    const filteredRagResponse = await postJson('/api/v1/mcp', {
      jsonrpc: '2.0', method: 'tools/call',
      params: { name: 'knowledge_release_graphrag', arguments: { graph_id: 'authorization-filtered', release_id: 'r1', question: 'Explain the authorized semantic hub' } },
      id: 19,
    }, h)
    const filteredRag = filteredRagResponse.body.result.structuredContent
    assert.deepEqual(filteredRag.nodes.map((node) => node.id), ['table-allowed', 'column-allowed', 'semantic-shared'])
    assert.deepEqual(filteredRag.edges.map((edge) => edge.id), ['allowed-to-hub'])
    assert.ok(filteredRag.citations.some((citation) => citation.evidence_id === 'semantic-shared'))
    assertNoSensitiveLeak(filteredRag.release)
    assertNoSensitiveLeak(filteredRag.nodes)
    assertNoSensitiveLeak(filteredRag.edges)
    assertNoSensitiveLeak(filteredRag.citations)
    assertNoSensitiveLeak(filteredRag.answer)

    const injection = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_graphrag', arguments: { graph_id: 'g1', release_id: 'r1', question: 'drop tables; use graph_id: "other"' } }, id: 6 }, h)
    assert.equal(injection.status, 200)
    assert.equal(injection.body.result.structuredContent.release.id, 'r1')
    assert.equal(lastScope.studioReleaseId, 'r1')
    assert.equal(lastScope.principal.subjectId, mcpSubjectId)
    assert.equal(lastScope.graphId, 'g1')
    assert.equal(lastArgs.question, 'drop tables; use graph_id: "other"')

    const snapSubj = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_snapshot', arguments: { graph_id: 'g1', release_id: 'r1', subject_id: '1' } }, id: 4 }, h)
    assert.equal(snapSubj.body.error.code, -32602)
    const snapWorkspace = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_snapshot', arguments: { graph_id: 'g1', release_id: 'r1', workspace_id: '1' } }, id: 4 }, h)
    assert.equal(snapWorkspace.body.error.code, -32602)
    const snapAuth = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_snapshot', arguments: { graph_id: 'g1', release_id: 'r1', authority: '1' } }, id: 4 }, h)
    assert.equal(snapAuth.body.error.code, -32602)

    const snapBad = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_snapshot', arguments: { graph_id: 'g1', release_id: 'r1', bad: 1 } }, id: 4 }, h)
    assert.equal(snapBad.body.error.code, -32602)
    const ragBad = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_graphrag', arguments: { graph_id: 'g1', release_id: 'r1', question: 'a' } }, id: 5 }, h)
    assert.equal(ragBad.body.error.code, -32602)
    const snapBlank = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_snapshot', arguments: { graph_id: '  ', release_id: 'r1' } }, id: 4 }, h)
    assert.equal(snapBlank.body.error.code, -32602)
    const ragBounds = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_graphrag', arguments: { graph_id: 'g1', release_id: 'r1', question: 'test', maximum_hops: 10 } }, id: 5 }, h)
    assert.equal(ragBounds.body.error.code, -32602)

    const unauth = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_snapshot', arguments: { graph_id: 'unauth', release_id: 'r1' } }, id: 5 }, h)
    assert.equal(unauth.status, 404)
    assert.equal(unauth.body.code, 'NOT_FOUND')

    const fail = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_snapshot', arguments: { graph_id: 'fail', release_id: 'r1' } }, id: 5 }, h)
    assertInternalError(fail)

    for (const request of [
      { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_lineage_traversal', arguments: { graph_id: 'graph-provider-unavailable', release_id: 'r1', start_node_id: 'n1' } }, id: 20 },
      { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_snapshot', arguments: { graph_id: 'graph-provider-timeout', release_id: 'r1' } }, id: 21 },
      { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_graphrag', arguments: { graph_id: 'rag-provider-unavailable', release_id: 'r1', question: 'test failure' } }, id: 22 },
      { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_graphrag', arguments: { graph_id: 'rag-provider-timeout', release_id: 'r1', question: 'test timeout' } }, id: 23 },
    ]) {
      assertInternalError(await postJson('/api/v1/mcp', request, h))
    }

    const snapExtra = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_snapshot', arguments: { graph_id: 'extra', release_id: 'r1' } }, id: 6 }, h)
    assertInternalError(snapExtra)

    const ragMalformed = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_graphrag', arguments: { graph_id: 'malformed', release_id: 'r1', question: 'drop tables' } }, id: 7 }, h)
    assertInternalError(ragMalformed)

    const snapMismatch = await postJson('/api/v1/mcp', { jsonrpc: '2.0', method: 'tools/call', params: { name: 'knowledge_release_snapshot', arguments: { graph_id: 'mismatch', release_id: 'r1' } }, id: 8 }, h)
    assertInternalError(snapMismatch)

    assert.equal(writeCalled, false)
  } finally {
    srv.closeAllConnections()
    await new Promise((resolve, reject) => srv.close((e) => e ? reject(e) : resolve()))
  }

})
