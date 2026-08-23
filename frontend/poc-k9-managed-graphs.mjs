/* global console, process */
import { randomUUID } from 'crypto'
import {
  computeSha256,
  canonicalStringify,
  validateClassification,
  validateAuthorityPin,
  isValidTableAssignmentId,
  isValidColumnAssignmentId,
  isTermUrn,
  isNodeUrn
} from './poc-knowledge-k9-contracts.mjs'

const INTERNAL_CLASSIFICATION = 'INTERNAL'

export function buildK9GlossaryScrollVariables(scrollId) {
  return {
    input: {
      types: ['GLOSSARY_TERM', 'GLOSSARY_NODE'],
      query: '*',
      count: 250,
      keepAlive: '1m',
      sortInput: { sortCriteria: [{ field: 'urn', sortOrder: 'ASCENDING' }] },
      searchFlags: { skipCache: true, skipHighlighting: true, skipAggregates: true, fulltext: true },
      scrollId,
    },
  }
}

export const K9_POLICIES = {
  METADATA_LINEAGE: {
    graph_id: '01a02d2a-f8a0-7658-b5da-890eccdccf44',
    name: 'CATALOG_MIRROR',
    status: 'ACTIVE',
    classification: 'INTERNAL',
    ontology_version_id: '01a02d2a-f8a9-74d2-b0d4-125601c37f49',
    studio_release_id: '01a02d2a-f8ad-789f-acb0-7df3ea3d0ef0',
    publication_version: 6,
    schedule: '02:00 Asia/Seoul',
    managed_intent: 'metadata-lineage',
    accepted_proposal_id: 'contract.semantic.metadata-lineage',
    tbox_hash: '9e6e5982bceb8a85572768f746c901c84e5a5dfe28dcb3fb70e5c25acf4c799b',
    contract_hash: '187bae99322f03deedc6daaf3c3d6546c798afb8b2f1423e90e21b3b2da1ace9',
    proposal_hash: '9b6a5e0e07624df4520d333b5d673fbe77f7ab84b0f352bbe3c647b262523e96',
    source_hash: '8d8cba3f1b46f997e234207f956238bf4a87e752d7566c20bb41a1e08d2a5feb',
    mapping_hash: 'f923778369eda84d0b2942d7fd1b1b837f64125fc3a2f5dd4dc72bcdc9d99bf3'
  },
  DATA_GLOSSARY: {
    graph_id: '01a02d2a-f90d-74fe-bd96-aa596276cb87',
    name: 'CURATED_KNOWLEDGE',
    status: 'ACTIVE',
    classification: 'INTERNAL',
    ontology_version_id: '01a02d2a-f90f-7ba3-8e7c-af7153e123cc',
    studio_release_id: '01a02d2a-f910-73b7-a2f0-a8f5e4698e88',
    publication_version: 6,
    schedule: '02:00 Asia/Seoul',
    managed_intent: 'data-glossary',
    accepted_proposal_id: 'contract.semantic.data-glossary',
    tbox_hash: '9e6e5982bceb8a85572768f746c901c84e5a5dfe28dcb3fb70e5c25acf4c799b',
    contract_hash: '243e22c403146ac713a2f86a0714859122836d2ca5ccd581e9998c1d2a4eac43',
    proposal_hash: '670ac1d49ab091debe23bc706cc479576af226ea55d73fa5ffd2c1a4993836d1',
    source_hash: '12cba3de9e71c2453d94c2f625839593d627ea60f6143097a49a9d3782a089d8',
    mapping_hash: 'ed3160311a3058f9e61bc8478b07175d96b6fe3c035b55fb4fe94455a6098e7f'
  }
}

function frozenAssetDefinition(value) {
  return Object.freeze({
    ...value,
    supported_intents: Object.freeze([...value.supported_intents]),
    semantic_capabilities: Object.freeze([...value.semantic_capabilities]),
    supported_entity_types: Object.freeze([...value.supported_entity_types]),
  })
}

export const K9_GRAPH_ASSET_DEFINITIONS = Object.freeze({
  [K9_POLICIES.METADATA_LINEAGE.graph_id]: frozenAssetDefinition({
    display_name: 'Default Lineage Graph',
    description: 'DataHub dataset dependency graph for authorized provenance, path, upstream, downstream, and impact traversal.',
    graph_type: 'LINEAGE',
    source: 'DataHub',
    is_default: true,
    supported_intents: [
      'UPSTREAM', 'DOWNSTREAM', 'DEPENDENCY', 'IMPACT', 'PATH',
      'PROVENANCE', 'DATA_FLOW', 'COMMON_UPSTREAM', 'COMMON_DOWNSTREAM',
    ],
    semantic_capabilities: [
      'DIRECTED_DEPENDENCY_GRAPH',
      'BOUNDED_MULTI_HOP_TRAVERSAL',
      'SEMANTIC_ENTITY_RESOLUTION',
    ],
    supported_entity_types: ['DATASET', 'TABLE', 'VIEW', 'COLUMN'],
  }),
  [K9_POLICIES.DATA_GLOSSARY.graph_id]: frozenAssetDefinition({
    display_name: 'Metadata Master Graph',
    description: 'DataHub semantic metadata graph for tables, columns, descriptions, tags, glossary terms, domains, and business concepts.',
    graph_type: 'METADATA_MASTER',
    source: 'DataHub',
    is_default: true,
    supported_intents: ['SEMANTIC_DISCOVERY', 'ENTITY_RESOLUTION', 'METADATA_EXPLANATION'],
    semantic_capabilities: [
      'SEMANTIC_METADATA',
      'GLOSSARY_CONCEPT_BINDING',
      'VECTOR_RETRIEVAL_ENRICHMENT',
    ],
    supported_entity_types: [
      'DATASET', 'TABLE', 'VIEW', 'COLUMN', 'TAG', 'GLOSSARY_TERM', 'DOMAIN', 'KNOWLEDGE_ASSET',
    ],
  }),
})

export function k9GraphAssetDefinition(graphId) {
  return K9_GRAPH_ASSET_DEFINITIONS[graphId] || null
}

function computePolicyHash(p) {
  return computeSha256({
    graph_id: p.graph_id,
    name: p.name,
    status: p.status,
    classification: p.classification,
    ontology_version_id: p.ontology_version_id,
    studio_release_id: p.studio_release_id,
    publication_version: p.publication_version,
    schedule: p.schedule,
    managed_intent: p.managed_intent,
    accepted_proposal_id: p.accepted_proposal_id,
    subject_id: p.subject_id,
    workspace_id: p.workspace_id,
    tbox_hash: p.tbox_hash,
    contract_hash: p.contract_hash,
    proposal_hash: p.proposal_hash,
    source_hash: p.source_hash,
    mapping_hash: p.mapping_hash
  })
}

export function createK9ManagedGraphs({ stateStore, neo4j, schedule, classificationCeiling, log = console }) {
  if (!stateStore || typeof stateStore.executeK9Transaction !== 'function' || typeof stateStore.getK9Policy !== 'function') {
    throw new Error('K9 managed graphs requires a PostgreSQL stateStore interface with K9 capabilities')
  }
  if (!neo4j || typeof neo4j.run !== 'function') {
    throw new Error('K9 managed graphs requires a Neo4j driver interface')
  }
  const configuredSchedule = typeof schedule === 'string' && schedule.trim() ? schedule.trim() : null
  if (classificationCeiling !== undefined) validateClassification(classificationCeiling, classificationCeiling)
  const configuredClassification = classificationCeiling || null

  function configuredPolicy(base) {
    return Object.assign(
      {},
      base,
      configuredSchedule ? { schedule: configuredSchedule } : {},
      configuredClassification ? { classification: configuredClassification } : {},
    )
  }

  async function resolveK9SystemSubject(context) {
    const principal = context && context.principal
    if (!principal) throw new Error('Unauthorized: missing principal')
    const k9Id = process.env.POC_K9_SYSTEM_SUBJECT_ID ? process.env.POC_K9_SYSTEM_SUBJECT_ID.trim() : null
    const workspaceId = process.env.POC_K9_WORKSPACE_ID ? process.env.POC_K9_WORKSPACE_ID.trim() : null

    if (!k9Id || !workspaceId) {
      throw new Error('K9 System Subject configuration is missing')
    }

    if (principal.subjectId !== k9Id) {
      throw new Error('Unauthorized: principal does not match K9 System Subject ID')
    }
    if (context.workspaceId !== workspaceId) {
      throw new Error('Unauthorized: mismatched K9 workspace')
    }
    return { subject_id: k9Id, workspace_id: workspaceId }
  }

  async function bootstrapK9Policies(authCtx) {
    const resolved = await resolveK9SystemSubject(authCtx)
    const k9Policies = []
    for (const base of Object.values(K9_POLICIES)) {
      const p = Object.assign({}, configuredPolicy(base), {
        subject_id: resolved.subject_id,
        workspace_id: resolved.workspace_id
      })
      k9Policies.push(p)
    }
    k9Policies[0].policy_hash = computePolicyHash(k9Policies[0])
    k9Policies[1].policy_hash = computePolicyHash(k9Policies[1])

    await stateStore.verifyK9StudioAuthority(authCtx, k9Policies[0])
    await stateStore.verifyK9StudioAuthority(authCtx, k9Policies[1])

    await stateStore.ensureK9Policies(k9Policies)
  }

  async function cleanupOrphanStaging(graphId, activePointer) {
    const orphanRuns = await stateStore.getK9OrphanRuns(graphId, activePointer || 'NONE')
    for (const row of orphanRuns) {
      if (row.active_release_pointer) {
        await neo4j.run(
          'MATCH (n) WHERE n.namespace = $namespace DETACH DELETE n',
          { namespace: row.active_release_pointer }
        ).catch(() => {})
      }
    }
  }

  async function performRestartRecovery() {
    if (log && log.info) log.info('K9: Performing restart recovery for PREPARING runs')
    const preparingRuns = await stateStore.getK9PreparingRuns()

    for (const run of preparingRuns) {
      const stagingNamespace = 'k9_stage_' + run.run_id.replace(/-/g, '')
      let recoveryErrorMessage = 'Aborted during restart recovery'
      try {
        const verifyResult = await neo4j.run(
          'MATCH (n:K9Release) WHERE n.namespace = $ns RETURN n.input_snapshot_hash AS hash, n.policy_hash AS policy',
          { ns: stagingNamespace }
        )

        const record = verifyResult[0]
        if (record && record[0] === run.input_snapshot_hash && record[1] === run.policy_hash) {
          recoveryErrorMessage = 'Cleaned during restart recovery after matching Neo4j staging'
        }
      } catch (error) {
        if (log && log.warn) log.warn('Failed to read back staging during recovery for run ' + run.run_id, error)
      }

      await neo4j.run(
        'MATCH (n) WHERE n.namespace = $namespace DETACH DELETE n',
        { namespace: stagingNamespace }
      ).catch(() => {})

      await stateStore.finalizeK9RunFailure(run.run_id, recoveryErrorMessage)
      if (log && log.info) log.info('K9: Cleaned and marked run ' + run.run_id + ' as FAILURE during recovery')
    }
  }

  async function collectAndPublish(authCtx, policyBase, collectorFunc, mapperFunc) {
    const resolved = await resolveK9SystemSubject(authCtx)
    const expectedPolicy = Object.assign({}, configuredPolicy(policyBase), {
      subject_id: resolved.subject_id,
      workspace_id: resolved.workspace_id
    })
    expectedPolicy.policy_hash = computePolicyHash(expectedPolicy)

    await stateStore.verifyK9StudioAuthority(authCtx, expectedPolicy)

    const runId = randomUUID()
    await stateStore.createK9PreparingRun({
      run_id: runId,
      graph_id: expectedPolicy.graph_id,
      input_snapshot_hash: null,
      policy_hash: expectedPolicy.policy_hash
    })
    const stagingNamespace = 'k9_stage_' + runId.replace(/-/g, '')

    const existingPolicy = await stateStore.getK9Policy(expectedPolicy.graph_id)
    if (!existingPolicy) {
      await stateStore.finalizeK9RunFailure(runId, 'Managed policy is missing. No publish allowed.')
      return { runId, status: 'FAILURE', reason: 'Managed policy is missing. No publish allowed.', policy: expectedPolicy.name }
    }
    if (existingPolicy.policy_hash !== expectedPolicy.policy_hash) {
      await stateStore.finalizeK9RunFailure(runId, 'Managed policy has drifted. No publish allowed.')
      return { runId, status: 'FAILURE', reason: 'Managed policy has drifted. No publish allowed.', policy: expectedPolicy.name }
    }

    let failureReason = null
    let manifestHash, canonicalRelease, inputSnapshotHash

    try {
      const sourceData = await collectorFunc(authCtx)
      const pin = sourceData.authority_pin
      validateAuthorityPin(pin)
      if (pin.subject_id !== resolved.subject_id) throw new Error('Authority pin subject_id mismatch')
      if (pin.workspace_id !== resolved.workspace_id) throw new Error('Authority pin workspace_id mismatch')
      if (pin.classification_ceiling !== expectedPolicy.classification) throw new Error('Authority pin classification ceiling mismatch')

      const mappedData = mapperFunc(sourceData, expectedPolicy)

      mappedData.nodes.sort(function(a, b) { return a.id.localeCompare(b.id) })
      mappedData.edges.sort(function(a, b) {
        var cmp = a.source.localeCompare(b.source)
        if (cmp !== 0) return cmp
        cmp = a.target.localeCompare(b.target)
        if (cmp !== 0) return cmp
        return a.type.localeCompare(b.type)
      })

      const nodeMap = new Map()
      for (const n of mappedData.nodes) {
        if (!n.classification) throw new Error('Missing classification for node ' + n.id)
        validateClassification(n.classification, expectedPolicy.classification)
        if (nodeMap.has(n.id)) {
          const existing = nodeMap.get(n.id)
          if (existing.type !== n.type || existing.classification !== n.classification || canonicalStringify(existing.properties) !== canonicalStringify(n.properties)) {
            throw new Error('Duplicate canonical node ID with conflicting properties: ' + n.id)
          }
        } else {
          nodeMap.set(n.id, n)
        }
      }
      mappedData.nodes = Array.from(nodeMap.values())
      mappedData.nodes.sort(function(a, b) { return a.id.localeCompare(b.id) })

      for (const e of mappedData.edges) {
        if (!nodeMap.has(e.source)) throw new Error('Dangling edge source: ' + e.source)
        if (!nodeMap.has(e.target)) throw new Error('Dangling edge target: ' + e.target)
      }

      inputSnapshotHash = computeSha256({ nodes: mappedData.nodes, edges: mappedData.edges })

      const lastRun = await stateStore.getLastK9Run(expectedPolicy.graph_id)
      if (lastRun && lastRun.input_snapshot_hash === inputSnapshotHash && lastRun.policy_hash === expectedPolicy.policy_hash) {
        await stateStore.finalizeK9RunNoOp(runId, lastRun.active_release_pointer)
        return { runId: runId, status: 'NO_OP', inputSnapshotHash: inputSnapshotHash, policy: expectedPolicy.name }
      }

      await neo4j.run(
        'MATCH (n) WHERE n.namespace = $namespace DETACH DELETE n',
        { namespace: stagingNamespace }
      )

      for (const node of mappedData.nodes) {
        await neo4j.run(
          'CREATE (n:K9Node { namespace: $ns, id: $id, type: $type, classification: $classification, properties: $props })',
          { ns: stagingNamespace, id: node.id, type: node.type, classification: node.classification, props: canonicalStringify(node.properties || {}) }
        )
      }

      for (const edge of mappedData.edges) {
        await neo4j.run(
          'MATCH (source:K9Node { namespace: $ns, id: $sourceId }), (target:K9Node { namespace: $ns, id: $targetId }) ' +
          'CREATE (source)-[r:K9Edge { type: $type, properties: $props }]->(target)',
          { ns: stagingNamespace, sourceId: edge.source, targetId: edge.target, type: edge.type, props: canonicalStringify(edge.properties || {}) }
        )
      }

      const verifyNodes = await neo4j.run(
        'MATCH (n:K9Node) WHERE n.namespace = $ns AND NOT n:K9Release RETURN n.id AS id, n.type AS type, n.classification AS classification, n.properties AS properties ORDER BY id ASC',
        { ns: stagingNamespace }
      )

      const verifyEdges = await neo4j.run(
        'MATCH (source:K9Node { namespace: $ns })-[r:K9Edge]->(target:K9Node { namespace: $ns }) RETURN source.id AS source, target.id AS target, r.type AS type, r.properties AS properties ORDER BY source ASC, target ASC, r.type ASC',
        { ns: stagingNamespace }
      )

      const readBackNodes = verifyNodes.map(function(r) { return { id: r[0], type: r[1], classification: r[2], properties: JSON.parse(r[3]) } })
      const readBackEdges = verifyEdges.map(function(r) { return { source: r[0], target: r[1], type: r[2], properties: JSON.parse(r[3]) } })

      if (computeSha256(readBackNodes) !== computeSha256(mappedData.nodes) ||
          computeSha256(readBackEdges) !== computeSha256(mappedData.edges)) {
        throw new Error('Neo4j verification failed: read-back did not match staging expectations')
      }

      await neo4j.run(
        'CREATE (n:K9Node:K9Release { namespace: $ns, input_snapshot_hash: $hash, policy_hash: $policy, node_count: $ncount, edge_count: $ecount })',
        { ns: stagingNamespace, hash: inputSnapshotHash, policy: expectedPolicy.policy_hash, ncount: mappedData.nodes.length, ecount: mappedData.edges.length }
      )

      const verifyRelease = await neo4j.run(
        'MATCH (n:K9Release) WHERE n.namespace = $ns RETURN n.input_snapshot_hash AS hash, n.policy_hash AS policy',
        { ns: stagingNamespace }
      )
      if (verifyRelease.length !== 1 || verifyRelease[0][0] !== inputSnapshotHash || verifyRelease[0][1] !== expectedPolicy.policy_hash) {
        throw new Error('Neo4j verification failed: release node hash mismatch')
      }

      const manifestPayload = {
        graph_id: expectedPolicy.graph_id,
        policy_hash: expectedPolicy.policy_hash,
        input_snapshot_hash: inputSnapshotHash,
        node_count: mappedData.nodes.length,
        edge_count: mappedData.edges.length
      }
      manifestHash = computeSha256(manifestPayload)
      canonicalRelease = {
        manifest: manifestPayload,
        nodes: mappedData.nodes,
        edges: mappedData.edges
      }

    } catch (e) {
      failureReason = e.message
    }

    if (failureReason) {
      await stateStore.finalizeK9RunFailure(runId, failureReason)
      await neo4j.run(
        'MATCH (n) WHERE n.namespace = $namespace DETACH DELETE n',
        { namespace: stagingNamespace }
      ).catch(function() {})

      return { runId: runId, status: 'FAILURE', reason: failureReason, policy: expectedPolicy.name }
    }

    try {
      await stateStore.executeK9Transaction(expectedPolicy.graph_id, runId, canonicalRelease.manifest, canonicalRelease, stagingNamespace, manifestHash, inputSnapshotHash, expectedPolicy.policy_hash)
    } catch (e) {
      await neo4j.run(
        'MATCH (n) WHERE n.namespace = $namespace DETACH DELETE n',
        { namespace: stagingNamespace }
      ).catch(function() {})
      await stateStore.finalizeK9RunFailure(runId, 'Canonical finalization failed: ' + e.message)
      return { runId: runId, status: 'FAILURE', reason: 'Canonical PG commit failed: ' + e.message, policy: expectedPolicy.name }
    }

    await cleanupOrphanStaging(expectedPolicy.graph_id, stagingNamespace).catch(function(e) {
      if (log && log.warn) log.warn('Failed to cleanup orphan staging data', e)
    })

    return { runId: runId, status: 'RUN', manifestHash: manifestHash, inputSnapshotHash: inputSnapshotHash, stagingNamespace: stagingNamespace, policy: expectedPolicy.name }
  }

  function mapLineage(sourceData) {
    const nodeMap = new Map()
    const edgeMap = new Map()

    function addNode(n) {
      if (nodeMap.has(n.id)) {
        const existing = nodeMap.get(n.id)
        if (existing.type !== n.type || existing.classification !== n.classification || JSON.stringify(existing.properties) !== JSON.stringify(n.properties)) {
          throw new Error('Conflicting duplicate node: ' + n.id)
        }
      } else {
        nodeMap.set(n.id, n)
      }
    }

    function addEdge(e) {
      const key = `${e.source}->${e.target}->${e.type}`
      if (edgeMap.has(key)) {
        const existing = edgeMap.get(key)
        if (JSON.stringify(existing.properties) !== JSON.stringify(e.properties)) {
          throw new Error('Conflicting duplicate edge: ' + key)
        }
      } else {
        edgeMap.set(key, e)
      }
    }

    for (const node of (sourceData.nodes || [])) {
      if (!isValidTableAssignmentId(node.id)) throw new Error('Invalid node id: ' + node.id)
      if (!node.classification) throw new Error('Missing classification for lineage node')
      const props = {}
      for (const key of [
        'external_urn', 'name', 'qualified_name', 'platform', 'database_name',
        'schema_name', 'description', 'domain',
      ]) {
        if (node[key] !== undefined && node[key] !== null && node[key] !== '') props[key] = node[key]
      }
      if (Array.isArray(node.tags) && node.tags.length) props.tags = [...new Set(node.tags)].sort()
      if (Array.isArray(node.terms) && node.terms.length) props.terms = [...new Set(node.terms)].sort()
      addNode({ id: node.id, type: 'class.dataset', classification: node.classification, properties: props })
    }
    for (const edge of (sourceData.edges || [])) {
      if (!isValidTableAssignmentId(edge.source_asset_id) || !isValidTableAssignmentId(edge.target_asset_id)) throw new Error('Invalid edge asset id')
      addEdge({ source: edge.target_asset_id, target: edge.source_asset_id, type: 'rel.dataset_depends_on', properties: {} })
    }

    const nodes = Array.from(nodeMap.values()).sort((a,b) => a.id.localeCompare(b.id))
    const edges = Array.from(edgeMap.values()).sort((a,b) => a.source.localeCompare(b.source) || a.target.localeCompare(b.target) || a.type.localeCompare(b.type))
    return { nodes, edges }
  }

  function hasGlossaryCycle(edgesMap, startNode) {
    const visited = new Set()
    const recStack = new Set()
    function checkCycle(node) {
      if (!visited.has(node)) {
        visited.add(node)
        recStack.add(node)
        const neighbors = edgesMap.get(node) || []
        for (const n of neighbors) {
          if (!visited.has(n) && checkCycle(n)) return true
          if (recStack.has(n)) return true
        }
      }
      recStack.delete(node)
      return false
    }
    return checkCycle(startNode)
  }

  function mapGlossary(sourceData) {
    const nodeMap = new Map()
    const edgeMap = new Map()
    const hierarchyAdj = new Map()

    function addNode(n) {
      if (nodeMap.has(n.id)) {
        const existing = nodeMap.get(n.id)
        if (existing.type !== n.type || existing.classification !== n.classification || JSON.stringify(existing.properties) !== JSON.stringify(n.properties)) {
          throw new Error('Conflicting duplicate node: ' + n.id)
        }
      } else {
        nodeMap.set(n.id, n)
      }
    }

    function addEdge(e) {
      const key = `${e.source}->${e.target}->${e.type}`
      if (edgeMap.has(key)) {
        const existing = edgeMap.get(key)
        if (JSON.stringify(existing.properties) !== JSON.stringify(e.properties)) {
          throw new Error('Conflicting duplicate edge: ' + key)
        }
      } else {
        edgeMap.set(key, e)
      }
    }

    for (const table of (sourceData.table_nodes || [])) {
      if (!isValidTableAssignmentId(table.id)) throw new Error('Invalid table id: ' + table.id)
      if (!table.classification) throw new Error('Missing classification for table')
      addNode({ id: table.id, type: 'class.table', classification: table.classification, properties: table.properties || {} })
    }
    for (const column of (sourceData.column_nodes || [])) {
      if (!isValidColumnAssignmentId(column.id)) throw new Error('Invalid column id: ' + column.id)
      if (!column.classification) throw new Error('Missing classification for column')
      addNode({ id: column.id, type: 'class.column', classification: column.classification, properties: column.properties || {} })
    }
    for (const containment of (sourceData.table_column_edges || [])) {
      if (!isValidTableAssignmentId(containment.table_id) || !isValidColumnAssignmentId(containment.column_id)) {
        throw new Error('Invalid table-column containment identity')
      }
      addEdge({ source: containment.table_id, target: containment.column_id, type: 'rel.table_contains_column', properties: {} })
    }

    for (const term of (sourceData.terms || [])) {
      if (!isTermUrn(term.urn)) throw new Error('Invalid term urn: ' + term.urn)
      const props = {}
      if (term.name !== undefined) props.name = term.name
      if (term.description !== undefined) props.description = term.description
      addNode({ id: term.urn, type: 'class.business_term', classification: INTERNAL_CLASSIFICATION, properties: props })
    }
    for (const parent of (sourceData.parent_nodes || [])) {
      if (!isNodeUrn(parent.urn)) throw new Error('Invalid node urn: ' + parent.urn)
      const props = {}
      if (parent.name !== undefined) props.name = parent.name
      if (parent.description !== undefined) props.description = parent.description
      addNode({ id: parent.urn, type: 'class.glossary_node', classification: INTERNAL_CLASSIFICATION, properties: props })
    }
    for (const ta of (sourceData.table_assignments || [])) {
      if (!isValidTableAssignmentId(ta.id)) throw new Error('Invalid table id: ' + ta.id)
      if (!isTermUrn(ta.term_urn)) throw new Error('Invalid term id: ' + ta.term_urn)
      if (!ta.classification) throw new Error('Missing classification for table assignment')
      addNode({ id: ta.id, type: 'class.table', classification: ta.classification, properties: ta.properties || {} })
      addEdge({ source: ta.id, target: ta.term_urn, type: 'rel.table_mapped_to_term', properties: {} })
    }
    for (const ca of (sourceData.column_assignments || [])) {
      if (!isValidColumnAssignmentId(ca.id)) throw new Error('Invalid column id: ' + ca.id)
      if (!isTermUrn(ca.term_urn)) throw new Error('Invalid term id: ' + ca.term_urn)
      if (!ca.classification) throw new Error('Missing classification for column assignment')
      addNode({ id: ca.id, type: 'class.column', classification: ca.classification, properties: ca.properties || {} })
      addEdge({ source: ca.id, target: ca.term_urn, type: 'rel.column_mapped_to_term', properties: {} })
    }
    for (const te of (sourceData.term_parent_edges || [])) {
      if (!isTermUrn(te.term_urn)) throw new Error('Invalid term id: ' + te.term_urn)
      if (!isNodeUrn(te.parent_urn)) throw new Error('Invalid node id: ' + te.parent_urn)
      addEdge({ source: te.term_urn, target: te.parent_urn, type: 'rel.term_has_parent', properties: {} })
      if (!hierarchyAdj.has(te.term_urn)) hierarchyAdj.set(te.term_urn, [])
      hierarchyAdj.get(te.term_urn).push(te.parent_urn)
    }
    for (const ne of (sourceData.node_parent_edges || [])) {
      if (!isNodeUrn(ne.child_urn)) throw new Error('Invalid child node id: ' + ne.child_urn)
      if (!isNodeUrn(ne.parent_urn)) throw new Error('Invalid parent node id: ' + ne.parent_urn)
      addEdge({ source: ne.child_urn, target: ne.parent_urn, type: 'rel.node_has_parent', properties: {} })
      if (!hierarchyAdj.has(ne.child_urn)) hierarchyAdj.set(ne.child_urn, [])
      hierarchyAdj.get(ne.child_urn).push(ne.parent_urn)
    }

    const nodes = Array.from(nodeMap.values()).sort((a,b) => a.id.localeCompare(b.id))
    const edges = Array.from(edgeMap.values()).sort((a,b) => a.source.localeCompare(b.source) || a.target.localeCompare(b.target) || a.type.localeCompare(b.type))

    for (const n of nodes) {
      if (hasGlossaryCycle(hierarchyAdj, n.id)) {
        throw new Error('Cycle detected in glossary hierarchy starting from: ' + n.id)
      }
    }

    return { nodes, edges }
  }

  async function triggerLineagePublish(authCtx, collectLineageInventorySeam) {
    return collectAndPublish(authCtx, K9_POLICIES.METADATA_LINEAGE, collectLineageInventorySeam, mapLineage)
  }

  async function triggerGlossaryPublish(authCtx, collectGlossaryInventorySeam) {
    return collectAndPublish(authCtx, K9_POLICIES.DATA_GLOSSARY, collectGlossaryInventorySeam, mapGlossary)
  }

  return {
    bootstrapK9Policies: bootstrapK9Policies,
    triggerLineagePublish: triggerLineagePublish,
    triggerGlossaryPublish: triggerGlossaryPublish,
    performRestartRecovery: performRestartRecovery,
    mapLineage: mapLineage,
    mapGlossary: mapGlossary
  }
}
