/* global process */
import { test, mock } from 'node:test'
import assert from 'node:assert/strict'
import {
  buildK9GlossaryScrollVariables,
  createK9ManagedGraphs,
  K9_GRAPH_ASSET_DEFINITIONS,
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
  projection_version: 1,
  policy_version: 'POC_LIVE_PROVIDER_V1',
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

test('K9 Managed Graphs - missing policy no-publish', async () => {
  const stateStore = createBaseStateStore()
  stateStore.getK9Policy.mock.mockImplementation(async () => null) // missing policy
  const neo4j = createBaseNeo4j()
  const k9 = createK9ManagedGraphs({ stateStore, neo4j })

  const collectorFunc = mock.fn(async () => ({ authority_pin: validAuthorityPin, nodes: [], edges: [] }))
  const result = await k9.triggerLineagePublish(authCtx, collectorFunc)

  assert.equal(result.status, 'FAILURE')
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
  assert.ok(result.reason.includes('Managed policy has drifted. No publish allowed.'))
})

test('K9 Managed Graphs - bootstrap creates authority, trigger requires it', async () => {
  const stateStore = createBaseStateStore()
  const neo4j = createBaseNeo4j()
  const k9 = createK9ManagedGraphs({ stateStore, neo4j })

  await k9.bootstrapK9Policies(authCtx)
  assert.equal(stateStore.ensureK9Policies.mock.calls.length, 1)

  const policies = stateStore.ensureK9Policies.mock.calls[0].arguments[0]
  assert.equal(policies.length, 2)
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
