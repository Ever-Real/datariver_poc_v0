/* global process */
import { test, mock } from 'node:test'
import assert from 'node:assert/strict'
import {
  buildK9GlossaryScrollVariables,
  createK9ManagedGraphs,
  K9_GRAPH_ASSET_DEFINITIONS,
  K9_POLICIES,
  projectionDiffMetrics,
} from './poc-k9-managed-graphs.mjs'

const authCtx = {
  principal: { subjectId: 'test-k9-id' },
  workspaceId: 'test-workspace'
}
process.env.POC_K9_SYSTEM_SUBJECT_ID = 'test-k9-id'
process.env.POC_K9_WORKSPACE_ID = 'test-workspace'

const validAuthorityPin = {
  subject_id: 'test-k9-id',
  workspace_id: 'test-workspace',
  classification_ceiling: 'INTERNAL',
  projection_version: 2,
  policy_version: 'POC_DATAHUB_SEMANTIC_MODEL_V2',
  classification_policy_version: 1,
  authorization_generation: 1
}

function createBaseStateStore() {
  return {
    ensureK9Policies: mock.fn(async () => true),
    getK9Policy: mock.fn(async () => null),
    createK9PreparingRun: mock.fn(async () => true),
    getLastK9Run: mock.fn(async () => null),
    finalizeK9RunFailure: mock.fn(async () => true),
    executeK9Transaction: mock.fn(async () => true),
    getK9OrphanRuns: mock.fn(async () => []),
    getK9PreparingRuns: mock.fn(async () => []),
    finalizeK9RunNoOp: mock.fn(async () => true),
    recordK9ManagedRefreshFailure: mock.fn(async () => true),
    verifyK9StudioAuthority: mock.fn(async () => true)
  }
}

function createBaseNeo4j() {
  return {
    run: mock.fn(async () => [])
  }
}

test('K9 Glossary scroll variables use the live provider sort contract', () => {
  const variables = buildK9GlossaryScrollVariables('scroll-1')

  assert.deepEqual(variables.input.sortInput, {
    sortCriteria: [{ field: 'urn', sortOrder: 'ASCENDING' }]
  })
  assert.equal(Object.hasOwn(variables.input.sortInput, 'sortCriterion'), false)
})

test('K9 exact canonical graph identities expose domain-independent capability metadata', () => {
  const entries = Object.entries(K9_GRAPH_ASSET_DEFINITIONS)
  assert.deepEqual(entries.map(([id]) => id).sort(), [
    '01a02d2a-f8a0-7658-b5da-890eccdccf44',
    '01a02d2a-f90d-74fe-bd96-aa596276cb87',
  ])
  assert.equal(entries.find(([, item]) => item.graph_type === 'LINEAGE')[1].display_name, 'Default Lineage Graph')
  assert.equal(entries.find(([, item]) => item.graph_type === 'METADATA_MASTER')[1].display_name, 'Metadata Master Graph')
  assert.doesNotMatch(JSON.stringify(entries), /wafer|semiconductor|반도체|yield|\bCMP\b|etching|photolithography/iu)
})

test('KG2 projection reconciliation reports added, removed and changed canonical entities', () => {
  const previous = {
    source_snapshot: { source_snapshot_id: 'a'.repeat(64) },
    nodes: [
      { id: 'kept', type: 'class.table', properties: { name: 'before' } },
      { id: 'removed', type: 'class.table', properties: {} },
    ],
    edges: [
      { source: 'kept', target: 'removed', type: 'rel.old', properties: {} },
      { source: 'kept', target: 'removed', type: 'rel.changed', properties: { confidence: 1 } },
    ],
  }
  assert.deepEqual(projectionDiffMetrics(previous, [
    { id: 'kept', type: 'class.table', properties: { name: 'after' } },
    { id: 'added', type: 'class.tag', properties: {} },
  ], [
    { source: 'kept', target: 'added', type: 'rel.new', properties: {} },
    { source: 'kept', target: 'removed', type: 'rel.changed', properties: { confidence: 0.9 } },
  ]), {
    baseline_available: true,
    nodes: { added: 1, removed: 1, changed: 1 },
    edges: { added: 1, removed: 1, changed: 1 },
    stale_entity_count: 1,
    previous_source_snapshot_id: 'a'.repeat(64),
  })
})

test('K9 Managed Graphs - missing policy no-publish', async () => {
  const stateStore = createBaseStateStore()
  stateStore.getK9Policy.mock.mockImplementation(async () => null) // missing policy
  const neo4j = createBaseNeo4j()
  const k9 = createK9ManagedGraphs({ stateStore, neo4j })

  const collectorFunc = mock.fn(async () => ({ authority_pin: validAuthorityPin, nodes: [], edges: [] }))
  const result = await k9.triggerLineagePublish(authCtx, collectorFunc)

  assert.equal(result.status, 'FAILURE')
  assert.equal(result.failureCode, 'K9_POLICY_PIN_DRIFT_FAILED')
  assert.ok(result.reason.includes('Managed policy is missing. No publish allowed.'))
})

test('K9 Managed Graphs - drift no-publish', async () => {
  const stateStore = createBaseStateStore()
  stateStore.getK9Policy.mock.mockImplementation(async () => ({ policy_hash: 'drifted-hash' }))
  const neo4j = createBaseNeo4j()
  const k9 = createK9ManagedGraphs({ stateStore, neo4j })

  const collectorFunc = mock.fn(async () => ({ authority_pin: validAuthorityPin, nodes: [], edges: [] }))
  const result = await k9.triggerLineagePublish(authCtx, collectorFunc)

  assert.equal(result.status, 'FAILURE')
  assert.equal(result.failureCode, 'K9_POLICY_PIN_DRIFT_FAILED')
  assert.ok(result.reason.includes('Managed policy has drifted. No publish allowed.'))
})

test('K9 Managed Graphs records one typed terminal failure for each requested canonical policy', async () => {
  const stateStore = createBaseStateStore()
  const k9 = createK9ManagedGraphs({ stateStore, neo4j: createBaseNeo4j() })

  await k9.recordRefreshFailure('K9_SEMANTIC_INDEX_FAILED', ['metadata-lineage', 'data-glossary'])

  const [graphIds, failureCode] = stateStore.recordK9ManagedRefreshFailure.mock.calls[0].arguments
  assert.deepEqual(graphIds, [
    K9_POLICIES.METADATA_LINEAGE.graph_id,
    K9_POLICIES.DATA_GLOSSARY.graph_id,
  ])
  assert.equal(failureCode, 'K9_SEMANTIC_INDEX_FAILED')
})

test('K9 Managed Graphs - bootstrap creates authority, trigger requires it', async () => {
  const stateStore = createBaseStateStore()
  const neo4j = createBaseNeo4j()
  const k9 = createK9ManagedGraphs({ stateStore, neo4j })

  await k9.bootstrapK9Policies(authCtx)
  assert.equal(stateStore.ensureK9Policies.mock.calls.length, 1)

  const policies = stateStore.ensureK9Policies.mock.calls[0].arguments[0]
  assert.equal(policies.length, 2)
  assert.ok(policies.every((policy) => policy.studio_release_no === 1))
  assert.ok(policies.every((policy) => policy.publication_version === 6))
  assert.ok(policies[0].policy_hash)

  stateStore.getK9Policy.mock.mockImplementation(async () => policies.find(p => p.managed_intent === 'metadata-lineage'))

  const collectorFunc = mock.fn(async () => ({ authority_pin: validAuthorityPin, nodes: [], edges: [] }))
  const result = await k9.triggerLineagePublish(authCtx, collectorFunc)
  assert.ok(result.reason.includes('Neo4j verification failed'))
})

test('K9 Managed Graphs - mapper deduplication and deterministic sorting', async () => {
  const k9 = createK9ManagedGraphs({ stateStore: createBaseStateStore(), neo4j: createBaseNeo4j() })

  const lineageDataSafe = {
    nodes: [
      { id: 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,B,PROD)', classification: 'INTERNAL', external_urn: 'x' },
      { id: 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,A,PROD)', classification: 'INTERNAL', external_urn: 'x' },
      { id: 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,A,PROD)', classification: 'INTERNAL', external_urn: 'x' }
    ],
    edges: [
      { source_asset_id: 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,B,PROD)', target_asset_id: 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,C,PROD)' },
      { source_asset_id: 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,A,PROD)', target_asset_id: 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,B,PROD)' },
      { source_asset_id: 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,A,PROD)', target_asset_id: 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,B,PROD)' }
    ]
  }
  const resultSafe = k9.mapLineage(lineageDataSafe)
  assert.equal(resultSafe.nodes.length, 2)
  assert.equal(resultSafe.edges.length, 2)
  assert.equal(resultSafe.nodes[0].id, 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,A,PROD)')
  assert.equal(resultSafe.edges[0].source, 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,B,PROD)')

  const lineageDataConflict = {
    nodes: [
      { id: 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,A,PROD)', classification: 'INTERNAL' },
      { id: 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,A,PROD)', classification: 'EXTERNAL' }
    ],
    edges: []
  }
  assert.throws(() => k9.mapLineage(lineageDataConflict), /Conflicting duplicate node/)

  const glossaryDataSafe = {
    table_nodes: [{
      id: 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,A,PROD)',
      classification: 'INTERNAL',
      properties: { name: 'A', tags: ['tag-a'] },
    }],
    column_nodes: [{
      id: 'COLUMN:urn:li:dataset:(urn:li:dataPlatform:hive,A,PROD):id',
      classification: 'INTERNAL',
      properties: { name: 'id', parent_table_id: 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,A,PROD)' },
    }],
    table_column_edges: [{
      table_id: 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,A,PROD)',
      column_id: 'COLUMN:urn:li:dataset:(urn:li:dataPlatform:hive,A,PROD):id',
    }],
    terms: [
      { urn: 'urn:li:glossaryTerm:2', name: 't2' },
      { urn: 'urn:li:glossaryTerm:1', name: 't1' },
      { urn: 'urn:li:glossaryTerm:1', name: 't1' }
    ],
    parent_nodes: [], table_assignments: [], column_assignments: [], term_parent_edges: [], node_parent_edges: []
  }
  const glossaryResult = k9.mapGlossary(glossaryDataSafe)
  assert.equal(glossaryResult.nodes.length, 4)
  assert.equal(glossaryResult.edges[0].type, 'rel.table_contains_column')
})

test('KG2 Metadata Master uses typed hubs, explicit provenance and evidence-derived aliases and units', () => {
  const k9 = createK9ManagedGraphs({ stateStore: createBaseStateStore(), neo4j: createBaseNeo4j() })
  const sourceSnapshot = {
    source_snapshot_id: '1'.repeat(64),
    observed_at: '2026-08-24T00:00:00.000Z',
  }
  const tableA = 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,A,PROD)'
  const tableB = 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,B,PROD)'
  const columnA = `${tableA.replace('TABLE:', 'COLUMN:')}:metric`
  const term = 'urn:li:glossaryTerm:shared'
  const group = 'urn:li:glossaryNode:root'
  const tag = 'urn:li:tag:shared'
  const propertiesA = {
    external_urn: tableA.slice('TABLE:'.length),
    name: 'A',
    custom_properties: [
      { key: 'aliases', value: 'Primary A; Alternate A' },
      { key: 'unit_of_measure', value: 'explicit-unit' },
    ],
  }
  const result = k9.mapGlossary({
    source_snapshot: sourceSnapshot,
    table_nodes: [
      { id: tableA, classification: 'INTERNAL', properties: propertiesA },
      { id: tableB, classification: 'INTERNAL', properties: { external_urn: tableB.slice('TABLE:'.length), name: 'B' } },
    ],
    column_nodes: [{
      id: columnA,
      classification: 'INTERNAL',
      properties: {
        external_urn: columnA,
        dataset_urn: tableA.slice('TABLE:'.length),
        name: 'metric',
        description: 'Measured value (unit: inferred-unit)',
      },
    }],
    table_column_edges: [{ table_id: tableA, column_id: columnA }],
    terms: [{ urn: term, name: 'Shared term', description: 'Canonical meaning' }],
    parent_nodes: [{ urn: group, name: 'Root' }],
    tags: [{ urn: tag, name: 'Shared tag' }],
    glossary_relationships: [{
      source_urn: term,
      target_urn: group,
      source_type: 'GLOSSARY_TERM',
      target_type: 'GLOSSARY_NODE',
      relationship_type: 'IsPartOf',
    }],
    table_assignments: [
      { id: tableA, term_urn: term, classification: 'INTERNAL', properties: propertiesA },
      { id: tableB, term_urn: term, classification: 'INTERNAL', properties: { external_urn: tableB.slice('TABLE:'.length), name: 'B' } },
    ],
    column_assignments: [],
    table_tag_assignments: [
      { source_id: tableA, target_id: tag },
      { source_id: tableB, target_id: tag },
    ],
  })

  assert.equal(result.edges.filter((edge) => edge.type === 'rel.table_has_glossary_term').length, 2)
  assert.equal(result.edges.filter((edge) => edge.type === 'rel.table_has_tag').length, 2)
  assert.equal(result.edges.filter((edge) => edge.type === 'rel.glossary_in_term_group').length, 1)
  assert.equal(result.edges.some((edge) => /same_(?:tag|term)|pairwise|similar_to/i.test(edge.type)), false)
  assert.equal(result.edges.filter((edge) => edge.type === 'rel.has_explicit_unit').length, 1)
  assert.equal(result.edges.filter((edge) => edge.type === 'rel.has_inferred_unit_candidate').length, 1)
  assert.ok(result.edges.every((edge) => edge.properties.source === 'DataHub'
    && edge.properties.source_aspect
    && ['EXPLICIT', 'INFERRED'].includes(edge.properties.explicit_or_inferred)
    && edge.properties.projection_version === 2
    && edge.properties.source_snapshot_id === sourceSnapshot.source_snapshot_id))
  const mappedTableA = result.nodes.find((node) => node.id === tableA)
  assert.deepEqual(mappedTableA.properties.aliases, ['a', 'alternate a', 'primary a'])
  assert.ok(mappedTableA.properties.alias_evidence.some((item) => item.explicit && item.source_aspect === 'customProperties'))
})

test('KG2 Default Lineage preserves table and column provenance without fabricating traversal', () => {
  const k9 = createK9ManagedGraphs({ stateStore: createBaseStateStore(), neo4j: createBaseNeo4j() })
  const tableA = 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,A,PROD)'
  const tableB = 'TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,B,PROD)'
  const columnA = `${tableA.replace('TABLE:', 'COLUMN:')}:id`
  const columnB = `${tableB.replace('TABLE:', 'COLUMN:')}:id`
  const result = k9.mapLineage({
    source_snapshot: { source_snapshot_id: '2'.repeat(64) },
    nodes: [
      { id: tableA, classification: 'INTERNAL', properties: { external_urn: tableA.slice('TABLE:'.length), name: 'A' } },
      { id: tableB, classification: 'INTERNAL', properties: { external_urn: tableB.slice('TABLE:'.length), name: 'B' } },
      { id: columnA, classification: 'INTERNAL', properties: { dataset_urn: tableA.slice('TABLE:'.length), name: 'id' } },
      { id: columnB, classification: 'INTERNAL', properties: { dataset_urn: tableB.slice('TABLE:'.length), name: 'id' } },
    ],
    edges: [
      {
        source_asset_id: tableA,
        target_asset_id: tableB,
        properties: { source_aspect: 'upstreamLineage', source_entity_urn: tableB.slice('TABLE:'.length), lineage_level: 'TABLE' },
      },
      {
        source_asset_id: columnA,
        target_asset_id: columnB,
        properties: { source_aspect: 'fineGrainedLineages', source_entity_urn: tableB.slice('TABLE:'.length), lineage_level: 'COLUMN', transformation_query: 'SELECT id' },
      },
    ],
  })
  assert.deepEqual(result.edges.map((edge) => edge.type), ['rel.column_depends_on', 'rel.dataset_depends_on'])
  assert.equal(result.edges.find((edge) => edge.type === 'rel.column_depends_on').properties.transformation_query, 'SELECT id')
  assert.deepEqual(result.quality_metrics.source_coverage, {
    catalog_assets: 2,
    table_lineage_edges: 1,
    column_lineage_edges: 1,
  })
})

test('K9 Managed Graphs - identical NO_OP', async () => {
  const stateStore = createBaseStateStore()
  const neo4j = createBaseNeo4j()
  const k9 = createK9ManagedGraphs({ stateStore, neo4j })

  await k9.bootstrapK9Policies(authCtx)
  const policies = stateStore.ensureK9Policies.mock.calls[0].arguments[0]
  const policy = policies.find(p => p.managed_intent === 'metadata-lineage')
  stateStore.getK9Policy.mock.mockImplementation(async () => policy)

  const staleRun = { run_id: 'stale-run-123', input_snapshot_hash: 'hash', policy_hash: 'phash' }
  stateStore.getK9PreparingRuns.mock.mockImplementation(async () => [staleRun])
  await k9.performRestartRecovery()
  assert.equal(stateStore.finalizeK9RunFailure.mock.calls.length, 1)
  assert.equal(stateStore.finalizeK9RunFailure.mock.calls[0].arguments[0], 'stale-run-123')
  const neo4jDeletes = neo4j.run.mock.calls.filter(c => c.arguments[0].includes('DETACH DELETE'))
  assert.ok(neo4jDeletes.length > 0)
  assert.equal(neo4jDeletes[0].arguments[1].namespace, 'k9_stage_stalerun123')

  let neo4jHash = null
  let neo4jPolicy = null
  neo4j.run.mock.mockImplementation(async (query, params) => {
    if (query.includes('MATCH (n:K9Release)')) {
      if (!neo4jHash) return []
      return [[neo4jHash, neo4jPolicy]]
    }
    if (query.includes('CREATE (n:K9Node:K9Release')) {
      neo4jHash = params?.hash
      neo4jPolicy = params?.policy
      return []
    }
    return []
  })

  let capturedHash = null
  stateStore.executeK9Transaction.mock.mockImplementation(async (g, r, m, c, a, mh, sh) => {
    capturedHash = sh
    return true
  })

  const collectorFunc = mock.fn(async () => ({ authority_pin: validAuthorityPin, nodes: [], edges: [] }))
  await k9.triggerLineagePublish(authCtx, collectorFunc)

  assert.ok(capturedHash)
  stateStore.getLastK9Run.mock.mockImplementation(async () => ({ input_snapshot_hash: capturedHash, policy_hash: policy.policy_hash }))

  const result = await k9.triggerLineagePublish(authCtx, collectorFunc)
  assert.equal(result.status, 'NO_OP')
  assert.equal(stateStore.finalizeK9RunNoOp.mock.calls.length, 1)
})

test('K9 Managed Graphs writes large staging projections in bounded batches', async () => {
  const stateStore = createBaseStateStore()
  const neo4j = createBaseNeo4j()
  const k9 = createK9ManagedGraphs({ stateStore, neo4j })
  await k9.bootstrapK9Policies(authCtx)
  const policy = stateStore.ensureK9Policies.mock.calls[0].arguments[0]
    .find((item) => item.managed_intent === 'metadata-lineage')
  stateStore.getK9Policy.mock.mockImplementation(async () => policy)
  const ids = Array.from({ length: 1001 }, (_, index) => (
    `TABLE:urn:li:dataset:(urn:li:dataPlatform:hive,T${String(index).padStart(4, '0')},PROD)`
  ))
  const result = await k9.triggerLineagePublish(authCtx, async () => ({
    authority_pin: validAuthorityPin,
    nodes: ids.map((id) => ({ id, classification: 'INTERNAL' })),
    edges: ids.slice(1).map((target, index) => ({ source_asset_id: ids[index], target_asset_id: target })),
  }))
  assert.equal(result.status, 'FAILURE')
  const nodeWrites = neo4j.run.mock.calls.filter((call) => call.arguments[0].includes('UNWIND $nodes AS node'))
  const edgeWrites = neo4j.run.mock.calls.filter((call) => call.arguments[0].includes('UNWIND $edges AS edge'))
  assert.deepEqual(nodeWrites.map((call) => call.arguments[1].nodes.length), [500, 500, 1])
  assert.deepEqual(edgeWrites.map((call) => call.arguments[1].edges.length), [500, 500])
})

test('K9 Managed Graphs - PREPARING->FAILURE cleanup on Neo4j mismatch', async () => {
  const stateStore = createBaseStateStore()
  const neo4j = createBaseNeo4j()
  const k9 = createK9ManagedGraphs({ stateStore, neo4j })

  await k9.bootstrapK9Policies(authCtx)
  const policies = stateStore.ensureK9Policies.mock.calls[0].arguments[0]
  const policy = policies.find(p => p.managed_intent === 'metadata-lineage')
  stateStore.getK9Policy.mock.mockImplementation(async () => policy)
  neo4j.run.mock.mockImplementation(async (query) => {
    if (query.includes('RETURN n.id AS id')) return [['unexpected-node','TABLE','INTERNAL','{}']]
    return []
  })

  const result = await k9.triggerLineagePublish(authCtx, async () => ({ authority_pin: validAuthorityPin, nodes: [], edges: [] }))

  assert.equal(result.status, 'FAILURE')
  assert.ok(result.reason.includes('Neo4j verification failed'))
  assert.equal(stateStore.finalizeK9RunFailure.mock.calls.length, 1)
  assert.equal(stateStore.executeK9Transaction.mock.calls.length, 0)

  const neo4jDeletes = neo4j.run.mock.calls.filter(c => c.arguments[0].includes('DETACH DELETE'))
  assert.ok(neo4jDeletes.length > 0)
})
