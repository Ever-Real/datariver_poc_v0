/* global console, process, structuredClone */
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
const NEO4J_WRITE_BATCH_SIZE = 500
export const KG2_MODEL_VERSION = 2
const KG2_PROJECTION_VERSION = 2

function hasForbiddenControlCharacters(value) {
  return [...String(value)].some((character) => {
    const codePoint = character.codePointAt(0)
    return codePoint <= 0x1f || codePoint === 0x7f
  })
}

function canonicalDatahubUrn(value, entityType) {
  return typeof value === 'string'
    && value.startsWith(`urn:li:${entityType}:`)
    && value.length <= 4096
    && !hasForbiddenControlCharacters(value)
    && !/\s/u.test(value)
}

function sourceTimestamp(value) {
  if (typeof value === 'number' && Number.isFinite(value) && value >= 0) {
    const date = new Date(value < 10_000_000_000 ? value * 1_000 : value)
    return Number.isFinite(date.getTime()) ? date.toISOString() : null
  }
  if (typeof value === 'string' && value.trim()) {
    const date = new Date(value.trim())
    return Number.isFinite(date.getTime()) ? date.toISOString() : null
  }
  return null
}

function relationEvidence(sourceData, sourceAspect, sourceEntityUrn, overrides = {}) {
  const snapshot = sourceData?.source_snapshot
  return {
    source: 'DataHub',
    source_aspect: sourceAspect,
    explicit_or_inferred: 'EXPLICIT',
    confidence: 1,
    observed_at: null,
    source_entity_urn: sourceEntityUrn,
    projection_version: KG2_PROJECTION_VERSION,
    source_snapshot_id: snapshot?.source_snapshot_id || null,
    ...overrides,
  }
}

function normalizedAlias(value) {
  return typeof value === 'string'
    ? value.normalize('NFKC').trim().toLocaleLowerCase().replace(/[._-]+/gu, ' ').replace(/\s+/gu, ' ')
    : ''
}

function aliasMetadataKey(value) {
  const key = normalizedAlias(value).replaceAll(' ', '_')
  return ['alias', 'aliases', 'synonym', 'synonyms', 'alternative_label', 'alternative_labels'].includes(key)
    || key.endsWith('_alias')
    || key.endsWith('_aliases')
}

function explicitAliasValues(value) {
  if (typeof value !== 'string') return []
  return value.split(/[,;|\n]/u)
    .map((item) => item.normalize('NFKC').trim())
    .filter((item) => item && item.length <= 255 && !hasForbiddenControlCharacters(item))
}

function semanticNodeProperties(properties, sourceData, sourceAspects) {
  const value = properties && typeof properties === 'object' && !Array.isArray(properties)
    ? structuredClone(properties)
    : {}
  const aliasEvidence = new Map()
  const addAlias = (alias, evidence) => {
    const normalized = normalizedAlias(alias)
    if (!normalized) return
    const current = aliasEvidence.get(normalized)
    if (!current || evidence.explicit || evidence.confidence > current.confidence) {
      aliasEvidence.set(normalized, { value: alias, normalized_value: normalized, ...evidence })
    }
  }
  for (const alias of [value.name, value.business_name, value.qualified_name]) {
    addAlias(alias, { explicit: false, confidence: 1, source_aspect: 'NORMALIZED_NAME' })
  }
  for (const item of value.custom_properties || []) {
    if (!aliasMetadataKey(item?.key)) continue
    for (const alias of explicitAliasValues(item.value)) {
      addAlias(alias, { explicit: true, confidence: 1, source_aspect: 'customProperties' })
    }
  }
  for (const item of value.structured_properties || []) {
    if (!aliasMetadataKey(item?.qualified_name) && !aliasMetadataKey(item?.display_name)) continue
    for (const candidate of item.values || []) {
      for (const alias of explicitAliasValues(String(candidate))) {
        addAlias(alias, { explicit: true, confidence: 1, source_aspect: 'structuredProperties' })
      }
    }
  }
  const aliases = [...aliasEvidence.keys()].sort()
  if (aliases.length) value.aliases = aliases
  if (aliasEvidence.size) {
    value.alias_evidence = [...aliasEvidence.values()]
      .sort((left, right) => left.normalized_value.localeCompare(right.normalized_value))
  }
  value.source = 'DataHub'
  value.source_aspects = [...new Set(sourceAspects)].sort()
  value.projection_version = KG2_PROJECTION_VERSION
  value.source_snapshot_id = sourceData?.source_snapshot?.source_snapshot_id || null
  return value
}

function datasetEntityType(properties) {
  const kind = String(properties?.dataset_kind || '').toUpperCase()
  if (kind === 'VIEW' || kind === 'MATERIALIZED_VIEW') return 'class.view'
  if (kind === 'TABLE') return 'class.table'
  return 'class.dataset'
}

function unitMetadataKey(value) {
  const key = normalizedAlias(value).replaceAll(' ', '_')
  const qualifiedTail = String(value || '').split(/[.:/]/u).at(-1)
  const tail = normalizedAlias(qualifiedTail).replaceAll(' ', '_')
  return ['unit', 'uom', 'unit_of_measure', 'measurement_unit'].includes(key)
    || ['unit', 'uom', 'unit_of_measure', 'measurement_unit'].includes(tail)
    || key.endsWith('_unit_of_measure')
    || key.endsWith('_measurement_unit')
}

function normalizedUnitValue(value) {
  if (typeof value !== 'string' && typeof value !== 'number') return ''
  const normalized = String(value).normalize('NFKC').trim()
  return normalized && normalized.length <= 64 && !hasForbiddenControlCharacters(normalized)
    ? normalized
    : ''
}

function unitCandidates(properties) {
  const candidates = new Map()
  const add = (value, evidence) => {
    const display = normalizedUnitValue(value)
    if (!display) return
    const key = display.toLocaleLowerCase()
    const existing = candidates.get(key)
    if (!existing || evidence.explicit || evidence.confidence > existing.confidence) {
      candidates.set(key, { value: display, normalized_value: key, ...evidence })
    }
  }
  for (const item of properties?.custom_properties || []) {
    if (unitMetadataKey(item?.key)) {
      add(item.value, { explicit: true, confidence: 1, method: 'DATAHUB_CUSTOM_PROPERTY', source_text: `${item.key}=${item.value}` })
    }
  }
  for (const item of properties?.structured_properties || []) {
    if (!unitMetadataKey(item?.qualified_name) && !unitMetadataKey(item?.display_name)) continue
    for (const value of item.values || []) {
      add(value, { explicit: true, confidence: 1, method: 'DATAHUB_STRUCTURED_PROPERTY', source_text: `${item.qualified_name}=${value}` })
    }
  }
  for (const value of [...(properties?.tags || []), ...(properties?.terms || [])]) {
    const match = String(value).match(/^(?:unit|uom|unit[ _-]of[ _-]measure)\s*[:=]\s*(\S.{0,63})$/iu)
    if (match) add(match[1], { explicit: true, confidence: 1, method: 'DATAHUB_ASSIGNED_METADATA', source_text: value })
  }
  for (const value of [properties?.name, properties?.business_name, properties?.description]) {
    if (typeof value !== 'string') continue
    const match = value.match(/(?:^|[\s;,(])(?:unit|uom|unit[ _-]of[ _-]measure)\s*[:=]\s*([\p{L}\p{N}%/._-]{1,64})/iu)
    if (match) add(match[1], { explicit: false, confidence: 0.75, method: 'GENERIC_UNIT_MARKER', source_text: match[0].trim() })
  }
  return [...candidates.values()].sort((left, right) => left.normalized_value.localeCompare(right.normalized_value))
}

function unitNodeId(value) {
  return `urn:datariver:unit:${computeSha256({ contract: 'GENERIC_UNIT_ID_V1', value })}`
}

function graphQualityMetrics(nodes, edges) {
  const entity_count_by_type = {}
  const relation_count_by_type = {}
  const degree = new Map(nodes.map((node) => [node.id, 0]))
  let explicit_edge_count = 0
  let inferred_edge_count = 0
  let pairwise_clique_count = 0
  for (const node of nodes) entity_count_by_type[node.type] = (entity_count_by_type[node.type] || 0) + 1
  for (const edge of edges) {
    relation_count_by_type[edge.type] = (relation_count_by_type[edge.type] || 0) + 1
    degree.set(edge.source, (degree.get(edge.source) || 0) + 1)
    degree.set(edge.target, (degree.get(edge.target) || 0) + 1)
    if (edge.properties?.explicit_or_inferred === 'INFERRED') inferred_edge_count += 1
    else explicit_edge_count += 1
    if (/pairwise|same_(?:tag|term)|similar_to/iu.test(edge.type)) pairwise_clique_count += 1
  }
  const degreeValues = [...degree.values()]
  const top_hubs = [...degree.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, 10)
    .map(([id, value]) => ({ id, degree: value, type: nodes.find((node) => node.id === id)?.type || null }))
  return {
    entity_count_by_type,
    relation_count_by_type,
    explicit_edge_count,
    inferred_edge_count,
    orphan_node_count: degreeValues.filter((value) => value === 0).length,
    duplicate_node_count: 0,
    duplicate_edge_count: 0,
    average_degree: degreeValues.length
      ? Number((degreeValues.reduce((sum, value) => sum + value, 0) / degreeValues.length).toFixed(4))
      : 0,
    maximum_degree: degreeValues.length ? Math.max(...degreeValues) : 0,
    top_hubs,
    pairwise_clique_count,
    semantic_candidate_count: nodes.filter((node) => node.type === 'class.semantic_concept').length,
    unit_explicit_count: edges.filter((edge) => edge.type === 'rel.has_explicit_unit').length,
    unit_inferred_count: edges.filter((edge) => edge.type === 'rel.has_inferred_unit_candidate').length,
    lineage_table_edge_count: edges.filter((edge) => edge.properties?.lineage_level === 'TABLE').length,
    lineage_column_edge_count: edges.filter((edge) => edge.properties?.lineage_level === 'COLUMN').length,
  }
}

export function projectionDiffMetrics(previousRelease, nodes, edges) {
  const previousNodes = Array.isArray(previousRelease?.nodes) ? previousRelease.nodes : []
  const previousEdges = Array.isArray(previousRelease?.edges) ? previousRelease.edges : []
  const previousNodeMap = new Map(previousNodes.map((node) => [node.id, canonicalStringify(node)]))
  const nextNodeMap = new Map(nodes.map((node) => [node.id, canonicalStringify(node)]))
  const edgeKey = (edge) => `${edge.source}\u0000${edge.target}\u0000${edge.type}`
  const previousEdgeMap = new Map(previousEdges.map((edge) => [edgeKey(edge), canonicalStringify(edge)]))
  const nextEdgeMap = new Map(edges.map((edge) => [edgeKey(edge), canonicalStringify(edge)]))
  const countChanges = (previous, next) => ({
    added: [...next.keys()].filter((key) => !previous.has(key)).length,
    removed: [...previous.keys()].filter((key) => !next.has(key)).length,
    changed: [...next.entries()].filter(([key, value]) => previous.has(key) && previous.get(key) !== value).length,
  })
  return {
    baseline_available: Boolean(previousRelease),
    nodes: countChanges(previousNodeMap, nextNodeMap),
    edges: countChanges(previousEdgeMap, nextEdgeMap),
    stale_entity_count: [...previousNodeMap.keys()].filter((key) => !nextNodeMap.has(key)).length,
    previous_source_snapshot_id: previousRelease?.source_snapshot?.source_snapshot_id || null,
  }
}

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
    studio_release_no: 1,
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
    studio_release_no: 1,
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
      'DATASET', 'TABLE', 'VIEW', 'COLUMN', 'TAG', 'GLOSSARY_TERM',
      'GLOSSARY_TERM_GROUP', 'DOMAIN', 'CONTAINER', 'DATA_PLATFORM_INSTANCE',
      'UNIT_OF_MEASURE', 'KNOWLEDGE_ASSET',
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
    studio_release_no: p.studio_release_no,
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
  let neo4jSchemaReady

  async function ensureK9Neo4jSchema() {
    if (!neo4jSchemaReady) {
      neo4jSchemaReady = (async () => {
        await neo4j.run(
          'CREATE CONSTRAINT k9_node_namespace_id IF NOT EXISTS FOR (n:K9Node) REQUIRE (n.namespace, n.id) IS UNIQUE',
          {},
        )
        await neo4j.run(
          'CREATE INDEX k9_node_namespace_type IF NOT EXISTS FOR (n:K9Node) ON (n.namespace, n.type)',
          {},
        )
      })().catch((error) => {
        neo4jSchemaReady = undefined
        throw error
      })
    }
    return neo4jSchemaReady
  }

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
        var comparison = a.source.localeCompare(b.source)
        if (comparison !== 0) return comparison
        comparison = a.target.localeCompare(b.target)
        if (comparison !== 0) return comparison
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
        const evidence = e.properties || {}
        if (evidence.source !== 'DataHub'
          || typeof evidence.source_aspect !== 'string' || !evidence.source_aspect
          || !['EXPLICIT', 'INFERRED'].includes(evidence.explicit_or_inferred)
          || typeof evidence.confidence !== 'number' || evidence.confidence < 0 || evidence.confidence > 1
          || evidence.projection_version !== KG2_PROJECTION_VERSION) {
          throw new Error('Managed relation provenance is incomplete: ' + e.type)
        }
      }

      const qualityMetrics = {
        ...graphQualityMetrics(mappedData.nodes, mappedData.edges),
        ...(mappedData.quality_metrics || {}),
      }
      const semanticContentHash = computeSha256({ nodes: mappedData.nodes, edges: mappedData.edges })
      const sourceSnapshot = sourceData.source_snapshot && typeof sourceData.source_snapshot === 'object'
        ? sourceData.source_snapshot
        : {
            source_snapshot_id: semanticContentHash,
            observed_at: null,
            contract_version: 'LEGACY_TEST_SOURCE',
          }
      if (!/^[0-9a-f]{64}$/.test(sourceSnapshot.source_snapshot_id || '')) {
        throw new Error('Managed source snapshot identity is invalid')
      }
      inputSnapshotHash = computeSha256({
        model_version: KG2_MODEL_VERSION,
        source_snapshot_id: sourceSnapshot.source_snapshot_id,
        semantic_content_hash: semanticContentHash,
      })

      const lastRun = await stateStore.getLastK9Run(expectedPolicy.graph_id)
      if (lastRun && lastRun.input_snapshot_hash === inputSnapshotHash && lastRun.policy_hash === expectedPolicy.policy_hash) {
        await stateStore.finalizeK9RunNoOp(runId, lastRun.active_release_pointer)
        return { runId: runId, status: 'NO_OP', inputSnapshotHash: inputSnapshotHash, policy: expectedPolicy.name }
      }
      qualityMetrics.reconciliation = projectionDiffMetrics(
        lastRun?.canonical_release,
        mappedData.nodes,
        mappedData.edges,
      )

      await neo4j.run(
        'MATCH (n) WHERE n.namespace = $namespace DETACH DELETE n',
        { namespace: stagingNamespace }
      )

      await ensureK9Neo4jSchema()

      for (let offset = 0; offset < mappedData.nodes.length; offset += NEO4J_WRITE_BATCH_SIZE) {
        const nodes = mappedData.nodes.slice(offset, offset + NEO4J_WRITE_BATCH_SIZE).map((node) => ({
          id: node.id,
          type: node.type,
          classification: node.classification,
          properties: canonicalStringify(node.properties || {}),
        }))
        await neo4j.run(
          'UNWIND $nodes AS node ' +
          'CREATE (n:K9Node { namespace: $ns, id: node.id, type: node.type, classification: node.classification, properties: node.properties })',
          { ns: stagingNamespace, nodes }
        )
      }

      for (let offset = 0; offset < mappedData.edges.length; offset += NEO4J_WRITE_BATCH_SIZE) {
        const edges = mappedData.edges.slice(offset, offset + NEO4J_WRITE_BATCH_SIZE).map((edge) => ({
          source: edge.source,
          target: edge.target,
          type: edge.type,
          properties: canonicalStringify(edge.properties || {}),
        }))
        await neo4j.run(
          'UNWIND $edges AS edge ' +
          'MATCH (source:K9Node { namespace: $ns, id: edge.source }), (target:K9Node { namespace: $ns, id: edge.target }) ' +
          'CREATE (source)-[r:K9Edge { type: edge.type, properties: edge.properties }]->(target)',
          { ns: stagingNamespace, edges }
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
        'CREATE (n:K9Node:K9Release { namespace: $ns, input_snapshot_hash: $hash, policy_hash: $policy, node_count: $ncount, edge_count: $ecount, model_version: $model, source_snapshot_id: $sourceSnapshot })',
        {
          ns: stagingNamespace,
          hash: inputSnapshotHash,
          policy: expectedPolicy.policy_hash,
          ncount: mappedData.nodes.length,
          ecount: mappedData.edges.length,
          model: KG2_MODEL_VERSION,
          sourceSnapshot: sourceSnapshot.source_snapshot_id,
        }
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
        model_version: KG2_MODEL_VERSION,
        source_snapshot: sourceSnapshot,
        quality_metrics: qualityMetrics,
        node_count: mappedData.nodes.length,
        edge_count: mappedData.edges.length
      }
      manifestHash = computeSha256(manifestPayload)
      canonicalRelease = {
        manifest: manifestPayload,
        model_version: KG2_MODEL_VERSION,
        source_snapshot: sourceSnapshot,
        quality_metrics: qualityMetrics,
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

    return {
      runId: runId,
      status: 'RUN',
      manifestHash: manifestHash,
      inputSnapshotHash: inputSnapshotHash,
      sourceSnapshotId: canonicalRelease?.source_snapshot?.source_snapshot_id || null,
      stagingNamespace: stagingNamespace,
      policy: expectedPolicy.name,
    }
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
      const tableNode = isValidTableAssignmentId(node.id)
      const columnNode = isValidColumnAssignmentId(node.id)
      if (!tableNode && !columnNode) throw new Error('Invalid node id: ' + node.id)
      if (!node.classification) throw new Error('Missing classification for lineage node')
      const props = node.properties && typeof node.properties === 'object'
        ? structuredClone(node.properties)
        : {}
      if (!node.properties) {
        for (const key of [
          'external_urn', 'name', 'qualified_name', 'platform', 'database_name',
          'schema_name', 'description', 'domain',
        ]) {
          if (node[key] !== undefined && node[key] !== null && node[key] !== '') props[key] = node[key]
        }
        if (Array.isArray(node.tags) && node.tags.length) props.tags = [...new Set(node.tags)].sort()
        if (Array.isArray(node.terms) && node.terms.length) props.terms = [...new Set(node.terms)].sort()
      }
      addNode({
        id: node.id,
        type: tableNode ? datasetEntityType(props) : 'class.column',
        classification: node.classification,
        properties: semanticNodeProperties(
          props,
          sourceData,
          tableNode ? ['datasetProperties', 'upstreamLineage'] : ['schemaMetadata', 'fineGrainedLineages'],
        ),
      })
    }
    for (const edge of (sourceData.edges || [])) {
      const tableEdge = isValidTableAssignmentId(edge.source_asset_id)
        && isValidTableAssignmentId(edge.target_asset_id)
      const columnEdge = isValidColumnAssignmentId(edge.source_asset_id)
        && isValidColumnAssignmentId(edge.target_asset_id)
      if (!tableEdge && !columnEdge) throw new Error('Invalid edge asset id')
      const collected = edge.properties && typeof edge.properties === 'object' ? edge.properties : {}
      addEdge({
        // K9 keeps the accepted dependency orientation: downstream depends on upstream.
        source: edge.target_asset_id,
        target: edge.source_asset_id,
        type: tableEdge ? 'rel.dataset_depends_on' : 'rel.column_depends_on',
        properties: relationEvidence(
          sourceData,
          collected.source_aspect || (tableEdge ? 'upstreamLineage' : 'fineGrainedLineages'),
          collected.source_entity_urn || null,
          {
            ...collected,
            source: 'DataHub',
            source_aspect: collected.source_aspect || (tableEdge ? 'upstreamLineage' : 'fineGrainedLineages'),
            explicit_or_inferred: 'EXPLICIT',
            confidence: 1,
            observed_at: sourceTimestamp(collected.observed_at),
            lineage_level: tableEdge ? 'TABLE' : 'COLUMN',
            projection_version: KG2_PROJECTION_VERSION,
            source_snapshot_id: sourceData.source_snapshot?.source_snapshot_id || null,
          },
        ),
      })
    }

    const nodes = Array.from(nodeMap.values()).sort((a,b) => a.id.localeCompare(b.id))
    const edges = Array.from(edgeMap.values()).sort((a,b) => a.source.localeCompare(b.source) || a.target.localeCompare(b.target) || a.type.localeCompare(b.type))
    return {
      nodes,
      edges,
      quality_metrics: {
        source_coverage: {
          catalog_assets: (sourceData.nodes || []).filter((node) => isValidTableAssignmentId(node.id)).length,
          table_lineage_edges: edges.filter((edge) => edge.type === 'rel.dataset_depends_on').length,
          column_lineage_edges: edges.filter((edge) => edge.type === 'rel.column_depends_on').length,
        },
      },
    }
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

    const addTypedRelation = (source, target, type, sourceAspect, sourceEntityUrn, overrides = {}) => {
      addEdge({
        source,
        target,
        type,
        properties: relationEvidence(sourceData, sourceAspect, sourceEntityUrn, overrides),
      })
    }

    const sourceEntityUrnForGraphId = (id) => {
      const node = nodeMap.get(id)
      const candidate = node?.properties?.dataset_urn || node?.properties?.external_urn
      return typeof candidate === 'string' && candidate.startsWith('urn:li:') ? candidate : id
    }

    for (const table of (sourceData.table_nodes || [])) {
      if (!isValidTableAssignmentId(table.id)) throw new Error('Invalid table id: ' + table.id)
      if (!table.classification) throw new Error('Missing classification for table')
      addNode({
        id: table.id,
        type: datasetEntityType(table.properties),
        classification: table.classification,
        properties: semanticNodeProperties(table.properties, sourceData, table.properties?.source_aspects || ['datasetProperties']),
      })
    }
    for (const column of (sourceData.column_nodes || [])) {
      if (!isValidColumnAssignmentId(column.id)) throw new Error('Invalid column id: ' + column.id)
      if (!column.classification) throw new Error('Missing classification for column')
      addNode({
        id: column.id,
        type: 'class.column',
        classification: column.classification,
        properties: semanticNodeProperties(column.properties, sourceData, column.properties?.source_aspects || ['schemaMetadata']),
      })
    }
    for (const containment of (sourceData.table_column_edges || [])) {
      if (!isValidTableAssignmentId(containment.table_id) || !isValidColumnAssignmentId(containment.column_id)) {
        throw new Error('Invalid table-column containment identity')
      }
      addTypedRelation(
        containment.table_id,
        containment.column_id,
        'rel.table_contains_column',
        'schemaMetadata',
        containment.table_id.slice('TABLE:'.length),
      )
    }

    for (const term of (sourceData.terms || [])) {
      if (!isTermUrn(term.urn)) throw new Error('Invalid term urn: ' + term.urn)
      const props = Object.fromEntries(Object.entries({
        name: term.name,
        description: term.description,
        term_source: term.term_source,
        source_ref: term.source_ref,
        source_url: term.source_url,
        custom_properties: term.custom_properties,
        structured_properties: term.structured_properties,
      }).filter(([, value]) => value !== undefined && value !== null && value !== ''
        && (!Array.isArray(value) || value.length)))
      addNode({
        id: term.urn,
        type: 'class.business_term',
        classification: INTERNAL_CLASSIFICATION,
        properties: semanticNodeProperties(props, sourceData, ['glossaryTermInfo', 'structuredProperties']),
      })
      if (term.domain_reference?.urn) {
        const domain = term.domain_reference
        if (!canonicalDatahubUrn(domain.urn, 'domain')) throw new Error('Invalid glossary Domain urn: ' + domain.urn)
        addNode({
          id: domain.urn,
          type: 'class.domain',
          classification: INTERNAL_CLASSIFICATION,
          properties: semanticNodeProperties(domain, sourceData, ['domains']),
        })
        addTypedRelation(term.urn, domain.urn, 'rel.glossary_term_belongs_to_domain', 'domains', term.urn)
      }
    }
    for (const parent of (sourceData.parent_nodes || [])) {
      if (!isNodeUrn(parent.urn)) throw new Error('Invalid node urn: ' + parent.urn)
      addNode({
        id: parent.urn,
        type: 'class.glossary_term_group',
        classification: INTERNAL_CLASSIFICATION,
        properties: semanticNodeProperties(parent, sourceData, ['glossaryNodeInfo', 'structuredProperties']),
      })
    }
    for (const tag of (sourceData.tags || [])) {
      if (!canonicalDatahubUrn(tag.urn, 'tag')) throw new Error('Invalid Tag urn: ' + tag.urn)
      addNode({
        id: tag.urn,
        type: 'class.tag',
        classification: INTERNAL_CLASSIFICATION,
        properties: semanticNodeProperties(tag, sourceData, ['globalTags']),
      })
    }
    for (const domain of (sourceData.domains || [])) {
      if (!canonicalDatahubUrn(domain.urn, 'domain')) throw new Error('Invalid Domain urn: ' + domain.urn)
      addNode({
        id: domain.urn,
        type: 'class.domain',
        classification: INTERNAL_CLASSIFICATION,
        properties: semanticNodeProperties(domain, sourceData, ['domains']),
      })
    }
    for (const container of (sourceData.containers || [])) {
      if (!canonicalDatahubUrn(container.urn, 'container')) throw new Error('Invalid Container urn: ' + container.urn)
      addNode({
        id: container.urn,
        type: 'class.container',
        classification: INTERNAL_CLASSIFICATION,
        properties: semanticNodeProperties(container, sourceData, ['containerProperties']),
      })
    }
    for (const instance of (sourceData.platform_instances || [])) {
      if (!canonicalDatahubUrn(instance.urn, 'dataPlatformInstance')) {
        throw new Error('Invalid Data Platform Instance urn: ' + instance.urn)
      }
      addNode({
        id: instance.urn,
        type: 'class.data_platform_instance',
        classification: INTERNAL_CLASSIFICATION,
        properties: semanticNodeProperties(instance, sourceData, ['dataPlatformInstanceProperties']),
      })
    }
    for (const ta of (sourceData.table_assignments || [])) {
      if (!isValidTableAssignmentId(ta.id)) throw new Error('Invalid table id: ' + ta.id)
      if (!isTermUrn(ta.term_urn)) throw new Error('Invalid term id: ' + ta.term_urn)
      if (!ta.classification) throw new Error('Missing classification for table assignment')
      addNode({
        id: ta.id,
        type: datasetEntityType(ta.properties),
        classification: ta.classification,
        properties: semanticNodeProperties(ta.properties, sourceData, ta.properties?.source_aspects || ['datasetProperties']),
      })
      addTypedRelation(ta.id, ta.term_urn, 'rel.table_has_glossary_term', 'glossaryTerms', ta.id.slice('TABLE:'.length))
    }
    for (const ca of (sourceData.column_assignments || [])) {
      if (!isValidColumnAssignmentId(ca.id)) throw new Error('Invalid column id: ' + ca.id)
      if (!isTermUrn(ca.term_urn)) throw new Error('Invalid term id: ' + ca.term_urn)
      if (!ca.classification) throw new Error('Missing classification for column assignment')
      addNode({
        id: ca.id,
        type: 'class.column',
        classification: ca.classification,
        properties: semanticNodeProperties(ca.properties, sourceData, ca.properties?.source_aspects || ['schemaMetadata']),
      })
      addTypedRelation(
        ca.id,
        ca.term_urn,
        'rel.column_has_glossary_term',
        'schemaMetadata.glossaryTerms',
        sourceEntityUrnForGraphId(ca.id),
      )
    }

    const addAssignmentRelations = (items, type, aspect) => {
      for (const item of items || []) {
        addTypedRelation(
          item.source_id,
          item.target_id,
          type,
          aspect,
          sourceEntityUrnForGraphId(item.source_id),
        )
      }
    }
    addAssignmentRelations(sourceData.table_tag_assignments, 'rel.table_has_tag', 'globalTags')
    addAssignmentRelations(sourceData.column_tag_assignments, 'rel.column_has_tag', 'schemaMetadata.globalTags')
    addAssignmentRelations(sourceData.table_domain_assignments, 'rel.table_belongs_to_domain', 'domains')
    addAssignmentRelations(sourceData.table_container_assignments, 'rel.table_in_container', 'container')
    addAssignmentRelations(
      sourceData.table_platform_instance_assignments,
      'rel.table_on_platform_instance',
      'dataPlatformInstance',
    )

    const directRelationships = sourceData.glossary_relationships || []
    if (directRelationships.length) {
      for (const relation of directRelationships) {
        const sourceValid = isTermUrn(relation.source_urn) || isNodeUrn(relation.source_urn)
        const targetValid = isTermUrn(relation.target_urn) || isNodeUrn(relation.target_urn)
        if (!sourceValid || !targetValid) throw new Error('Invalid explicit glossary relationship identity')
        const relationshipKey = normalizedAlias(relation.relationship_type).replaceAll(' ', '_')
        let type = 'rel.glossary_related_to'
        if (relationshipKey === 'ispartof' || relationshipKey === 'is_part_of') {
          type = 'rel.glossary_in_term_group'
        } else if (['contains', 'hasa', 'has_a'].includes(relationshipKey)) {
          type = 'rel.glossary_contains_term'
        } else if (['isa', 'is_a', 'inheritsfrom', 'inherits_from'].includes(relationshipKey)) {
          type = 'rel.glossary_inherits_from'
        }
        addTypedRelation(
          relation.source_urn,
          relation.target_urn,
          type,
          'relationships',
          relation.source_urn,
          { source_relationship_type: relation.relationship_type },
        )
        if (type !== 'rel.glossary_related_to') {
          if (!hierarchyAdj.has(relation.source_urn)) hierarchyAdj.set(relation.source_urn, [])
          hierarchyAdj.get(relation.source_urn).push(relation.target_urn)
        }
      }
    } else {
      // Legacy unit-test/source compatibility only. Runtime V2 collectors always
      // provide the explicit DataHub outgoing relationship list.
      for (const te of (sourceData.term_parent_edges || [])) {
        if (!isTermUrn(te.term_urn) || !isNodeUrn(te.parent_urn)) throw new Error('Invalid legacy glossary parent identity')
        addTypedRelation(te.term_urn, te.parent_urn, 'rel.glossary_in_term_group', 'parentNodes', te.term_urn)
        if (!hierarchyAdj.has(te.term_urn)) hierarchyAdj.set(te.term_urn, [])
        hierarchyAdj.get(te.term_urn).push(te.parent_urn)
      }
      for (const ne of (sourceData.node_parent_edges || [])) {
        if (!isNodeUrn(ne.child_urn) || !isNodeUrn(ne.parent_urn)) throw new Error('Invalid legacy glossary-node parent identity')
        addTypedRelation(ne.child_urn, ne.parent_urn, 'rel.glossary_in_term_group', 'parentNodes', ne.child_urn)
        if (!hierarchyAdj.has(ne.child_urn)) hierarchyAdj.set(ne.child_urn, [])
        hierarchyAdj.get(ne.child_urn).push(ne.parent_urn)
      }
    }

    for (const node of [...nodeMap.values()]) {
      if (!['class.dataset', 'class.table', 'class.view', 'class.column'].includes(node.type)) continue
      for (const unit of unitCandidates(node.properties)) {
        const unitId = unitNodeId(unit.normalized_value)
        addNode({
          id: unitId,
          type: 'class.unit_of_measure',
          classification: INTERNAL_CLASSIFICATION,
          properties: semanticNodeProperties({
            name: unit.value,
            normalized_value: unit.normalized_value,
          }, sourceData, [unit.method]),
        })
        addTypedRelation(
          node.id,
          unitId,
          unit.explicit ? 'rel.has_explicit_unit' : 'rel.has_inferred_unit_candidate',
          unit.method,
          node.properties.dataset_urn || node.properties.external_urn || node.id,
          {
            explicit_or_inferred: unit.explicit ? 'EXPLICIT' : 'INFERRED',
            confidence: unit.confidence,
            extraction_method: unit.method,
            source_text: unit.source_text,
          },
        )
      }
    }

    const nodes = Array.from(nodeMap.values()).sort((a,b) => a.id.localeCompare(b.id))
    const edges = Array.from(edgeMap.values()).sort((a,b) => a.source.localeCompare(b.source) || a.target.localeCompare(b.target) || a.type.localeCompare(b.type))

    for (const n of nodes) {
      if (hasGlossaryCycle(hierarchyAdj, n.id)) {
        throw new Error('Cycle detected in glossary hierarchy starting from: ' + n.id)
      }
    }

    return {
      nodes,
      edges,
      quality_metrics: {
        source_coverage: {
          table_count: (sourceData.table_nodes || []).length,
          column_count: (sourceData.column_nodes || []).length,
          glossary_term_count: (sourceData.terms || []).length,
          glossary_group_count: (sourceData.parent_nodes || []).length,
          tag_count: (sourceData.tags || []).length,
          domain_count: (sourceData.domains || []).length,
          container_count: (sourceData.containers || []).length,
          platform_instance_count: (sourceData.platform_instances || []).length,
          structured_property_assignment_count: [
            ...(sourceData.table_nodes || []),
            ...(sourceData.column_nodes || []),
          ].reduce((sum, node) => sum + (node.properties?.structured_properties?.length || 0), 0),
        },
      },
    }
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
