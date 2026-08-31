import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import process from 'node:process'

import { createK9ManagedGraphs } from './poc-k9-managed-graphs.mjs'
import { computeSha256 } from './poc-knowledge-k9-contracts.mjs'

const neo4jUrl = process.env.POC_TEST_NEO4J_HTTP_URL?.replace(/\/+$/u, '') || null
const neo4jUsername = process.env.POC_TEST_NEO4J_USERNAME || null
const neo4jPassword = process.env.POC_TEST_NEO4J_PASSWORD || null
const realNeo4jTest = neo4jUrl ? test : test.skip

function authorizationHeader() {
  return neo4jUsername && neo4jPassword
    ? { Authorization: `Basic ${Buffer.from(`${neo4jUsername}:${neo4jPassword}`).toString('base64')}` }
    : {}
}

function realNeo4jAdapter() {
  return {
    async run(statement, parameters = {}) {
      const response = await globalThis.fetch(`${neo4jUrl}/db/neo4j/tx/commit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authorizationHeader() },
        body: JSON.stringify({ statements: [{ statement, parameters, resultDataContents: ['row'] }] }),
      })
      assert.equal(response.status, 200)
      const payload = await response.json()
      assert.deepEqual(payload.errors, [])
      return (payload.results?.[0]?.data || []).map((item) => item.row)
    },
  }
}

function stateStoreFixture() {
  let policies = []
  const runs = []
  return {
    runs,
    async ensureK9Policies(value) { policies = globalThis.structuredClone(value) },
    async getK9Policy(graphId) { return policies.find((item) => item.graph_id === graphId) || null },
    async createK9PreparingRun(value) { runs.push({ ...value, status: 'PREPARING' }) },
    async getLastK9Run() { return null },
    async finalizeK9RunFailure(runId, reason) {
      const run = runs.find((item) => item.run_id === runId)
      Object.assign(run, { status: 'FAILURE', reason })
    },
    async executeK9Transaction(graphId, runId, manifest, canonicalRelease, pointer) {
      const run = runs.find((item) => item.run_id === runId)
      Object.assign(run, { graph_id: graphId, status: 'RUN', manifest, canonicalRelease, pointer })
    },
    async getK9OrphanRuns() { return [] },
    async getK9PreparingRuns() { return [] },
    async finalizeK9RunNoOp() {},
    async recordK9ManagedRefreshFailure() {},
    async verifyK9StudioAuthority() { return true },
  }
}

realNeo4jTest('persisted V2 Lineage and Metadata projections pass the exact Neo4j 2026 HTTP transaction path', async () => {
  process.env.POC_K9_SYSTEM_SUBJECT_ID = 'real-neo4j-k9-system'
  process.env.POC_K9_WORKSPACE_ID = 'real-neo4j-workspace'
  const authContext = {
    principal: { subjectId: process.env.POC_K9_SYSTEM_SUBJECT_ID },
    workspaceId: process.env.POC_K9_WORKSPACE_ID,
  }
  const stateStore = stateStoreFixture()
  const neo4j = realNeo4jAdapter()
  const managedGraphs = createK9ManagedGraphs({
    stateStore, neo4j, classificationCeiling: 'INTERNAL',
  })
  await managedGraphs.bootstrapK9Policies(authContext)
  const first = 'TABLE:urn:li:dataset:(urn:li:dataPlatform:test,graph_probe_a,PROD)'
  const second = 'TABLE:urn:li:dataset:(urn:li:dataPlatform:test,graph_probe_b,PROD)'
  const sourcePayload = {
    direction: 'BOTH',
    depth: 1,
    truncated: false,
    nodes: [
      { id: first, classification: 'INTERNAL', properties: { name: 'A' } },
      { id: second, classification: 'INTERNAL', properties: { name: 'B' } },
    ],
    column_nodes: [],
    edges: [{ source_asset_id: first, target_asset_id: second }],
    completeness_metadata: { complete: true },
  }
  const metadataPayload = {
    collections: {
      table_nodes: [], column_nodes: [], table_column_edges: [], terms: [], parent_nodes: [],
      term_parent_edges: [], node_parent_edges: [], glossary_relationships: [],
      table_assignments: [], column_assignments: [], tags: [], domains: [], containers: [],
      platform_instances: [], table_tag_assignments: [], column_tag_assignments: [],
      table_domain_assignments: [], table_container_assignments: [],
      table_platform_instance_assignments: [],
    },
    completeness_metadata: { complete: true },
    raw_assignment_reference_hash: null,
  }
  const sourceSnapshot = {
    source_snapshot_id: '3'.repeat(64),
    lineage_hash: computeSha256(sourcePayload),
    metadata_hash: computeSha256(metadataPayload),
    authority_pin: {
      subject_id: process.env.POC_K9_SYSTEM_SUBJECT_ID,
      workspace_id: process.env.POC_K9_WORKSPACE_ID,
      classification_ceiling: 'INTERNAL',
      projection_version: 2,
      policy_version: 'POC_DATAHUB_SEMANTIC_MODEL_V2',
      classification_policy_version: 1,
      authorization_generation: 1,
      authorization_fingerprint: 'f'.repeat(64),
    },
  }
  const pointers = []
  try {
    const lineageResult = await managedGraphs.publishPersistedProjection(authContext, {
      projector_id: 'LINEAGE', source_snapshot: sourceSnapshot, source_payload: sourcePayload,
    })
    const metadataResult = await managedGraphs.publishPersistedProjection(authContext, {
      projector_id: 'METADATA', source_snapshot: sourceSnapshot, source_payload: metadataPayload,
    })
    assert.equal(lineageResult.status, 'RUN')
    assert.equal(metadataResult.status, 'RUN')
    assert.equal(lineageResult.sourceSnapshotId, sourceSnapshot.source_snapshot_id)
    assert.equal(metadataResult.sourceSnapshotId, sourceSnapshot.source_snapshot_id)
    pointers.push(lineageResult.outputPointer, metadataResult.outputPointer)
    const rows = await neo4j.run(
      'MATCH (n:K9Release) WHERE n.namespace = $ns RETURN n.source_snapshot_id AS snapshot',
      { ns: lineageResult.outputPointer },
    )
    assert.deepEqual(rows, [[sourceSnapshot.source_snapshot_id]])
    const metadataRows = await neo4j.run(
      'MATCH (n:K9Release) WHERE n.namespace = $ns RETURN n.source_snapshot_id AS snapshot',
      { ns: metadataResult.outputPointer },
    )
    assert.deepEqual(metadataRows, [[sourceSnapshot.source_snapshot_id]])
    assert.equal(stateStore.runs.length, 2)
    assert.equal(stateStore.runs.at(-1).status, 'RUN')
  } finally {
    for (const pointer of pointers) {
      await neo4j.run('MATCH (n) WHERE n.namespace = $namespace DETACH DELETE n', {
        namespace: pointer,
      })
    }
  }
})
