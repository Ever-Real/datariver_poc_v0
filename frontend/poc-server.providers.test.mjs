/* global Buffer, URL, fetch, process, structuredClone */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { createServer } from 'node:http'
import { after, before, test } from 'node:test'
import {
  changeHistoryAccessCoreProjection,
  normalizeChangeHistoryAccessDocument,
  privateChangeHistoryAccess,
} from './poc-access-document.mjs'
import { approvedDefaultFeatureSecurityPolicy } from './poc-feature-security-policy.mjs'
import { applyTableSystemMappingCommand } from './poc-table-system-mappings.mjs'
import { K9_POLICIES } from './poc-k9-managed-graphs.mjs'

const managedLineageGraphId = K9_POLICIES.METADATA_LINEAGE.graph_id
const providerSourceUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.RAW.source_events,PROD)'
const providerWaferUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.QUALITY.wafer_events,PROD)'
const providerViewUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.QUALITY.view_f09ab31,PROD)'
const managedK9Nodes = [
  { id: `TABLE:${providerSourceUrn}`, type: 'class.table', classification: 'INTERNAL', properties: { external_urn: providerSourceUrn, name: 'source_events' } },
  { id: `TABLE:${providerWaferUrn}`, type: 'class.table', classification: 'INTERNAL', properties: { external_urn: providerWaferUrn, name: 'wafer_events' } },
  { id: `TABLE:${providerViewUrn}`, type: 'class.table', classification: 'INTERNAL', properties: { external_urn: providerViewUrn, name: 'wafer_quality_view' } },
]
const managedK9Edges = [
  { source: `TABLE:${providerWaferUrn}`, target: `TABLE:${providerSourceUrn}`, type: 'rel.dataset_depends_on', properties: {} },
  { source: `TABLE:${providerViewUrn}`, target: `TABLE:${providerWaferUrn}`, type: 'rel.dataset_depends_on', properties: {} },
]
const managedK9Row = {
  graph_id: managedLineageGraphId,
  name: 'Metadata Lineage',
  status: 'ACTIVE',
  classification: 'INTERNAL',
  ontology_version_id: 'provider-ontology-v1',
  studio_release_id: 'provider-studio-release-v1',
  publication_version: 1,
  schedule: '0 2 * * *',
  managed_intent: 'CATALOG_MIRROR',
  policy_hash: 'provider-policy-hash',
  active_input_snapshot_hash: 'provider-input-hash',
  active_release_pointer: 'provider-managed-release-v1',
  active_release_hash: 'provider-release-hash',
  active_completed_at: '2026-08-24T00:00:00.000Z',
  latest_completed_at: '2026-08-24T00:00:00.000Z',
  latest_result: 'RUN',
  created_at: '2026-08-24T00:00:00.000Z',
  updated_at: '2026-08-24T00:00:00.000Z',
  active_manifest: { node_count: managedK9Nodes.length, edge_count: managedK9Edges.length },
  active_canonical_release: {
    manifest: {
      graph_id: managedLineageGraphId,
      policy_hash: 'provider-policy-hash',
      input_snapshot_hash: 'provider-input-hash',
      node_count: managedK9Nodes.length,
      edge_count: managedK9Edges.length,
    },
    nodes: managedK9Nodes,
    edges: managedK9Edges,
  },
}

const requests = []
const objects = new Map()
let forcedClassifierResponse
let hideExactFromTextSearch
let omitKnowledgeColumnUrn
let forceKnowledgeNonTable
let forceABoxNeo4jFailure
let providerServer
let pocServer
let pocOrigin
let providerStateStore
const knowledgeNeo4jNodes = new Map()
const knowledgeNeo4jEdges = new Map()

async function readBody(request) {
  const chunks = []
  for await (const chunk of request) chunks.push(chunk)
  return Buffer.concat(chunks)
}

function sendJson(response, value, status = 200, headers = {}) {
  const body = JSON.stringify(value)
  response.writeHead(status, { 'Content-Type': 'application/json', ...headers })
  response.end(body)
}

function canonicalTestJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalTestJson).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalTestJson(value[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function canonicalTestHash(value) {
  return createHash('sha256').update(canonicalTestJson(value)).digest('hex')
}

function providerHandler(request, response) {
  void (async () => {
    const body = await readBody(request)
    const url = new URL(request.url || '/', 'http://provider.test')
    requests.push({ method: request.method, path: url.pathname, headers: request.headers, body: body.toString('utf8') })
    if (url.pathname === '/' || url.pathname === '/config' || url.pathname.endsWith('/models') || url.pathname === '/minio/health/live') return sendJson(response, { ok: true })
    if (url.pathname === '/airflow/api/v2/monitor/health') return sendJson(response, { detail: 'Airflow 2.x has no API v2' }, 404)
    if (url.pathname === '/airflow/api/v1/dags' && request.method === 'GET') return sendJson(response, { dags: [] })
    if (/^\/airflow\/api\/v1\/dags\/[^/]+\/dagRuns$/.test(url.pathname)) return sendJson(response, { state: 'queued' }, 201)
    if (url.pathname.endsWith('/embeddings')) {
      const payload = JSON.parse(body.toString('utf8'))
      const inputs = Array.isArray(payload.input) ? payload.input : [payload.input]
      return sendJson(response, { data: inputs.map((value, index) => {
        const normalized = String(value || '').toLocaleLowerCase()
        const embedding = normalized.includes('wafer')
          ? [1, 0]
          : normalized.includes('inspection') ? [0, 1] : [0.5, 0.5]
        return { index, embedding }
      }) })
    }
    if (url.pathname.endsWith('/rerank')) return sendJson(response, { results: [{ index: 0, relevance_score: 0.9 }] })
    if (url.pathname.endsWith('/chat/completions')) {
      const payload = JSON.parse(body.toString('utf8'))
      const systemPrompt = payload.messages?.[0]?.content || ''
      if (systemPrompt.includes('Rewrite the current Data Catalog question')) {
        return sendJson(response, { choices: [{ message: { content: JSON.stringify({
          standalone_question: 'wafer_events 테이블의 컬럼을 알려줘',
        }) } }] })
      }
      if (systemPrompt.includes('Compact the bounded conversation')) {
        return sendJson(response, { choices: [{ message: { content: JSON.stringify({
          summary: '사용자는 wafer_events 메타데이터를 확인했고 후속 컬럼 조회를 원합니다.',
        }) } }] })
      }
      if (systemPrompt.includes('Plan one untrusted Data Catalog question')) {
        const plannerInput = payload.messages?.[1]?.content || ''
        const question = plannerInput.split('\n\nQuestion:\n').at(-1) || ''
        const graph = /lineage|upstream|downstream|impact|연결 관계/i.test(question)
        const exact = /wafer_events/i.test(question)
        const inventory = /몇 개|나열/i.test(question)
        const general = /나의 이름/i.test(question)
        const graphAvailable = plannerInput.includes(managedLineageGraphId)
        const decision = general
          ? {
              mode: 'GENERAL', confidence: 0.99, intent: 'GENERAL_CONVERSATION',
              entity_resolution_required: false, graph_traversal_required: false,
              semantic_retrieval_required: false, fallback_mode: null,
              primary_concepts: [], secondary_concepts: [], relation_intent: null,
              entity_type_hints: [], selected_graph_asset: null, retrieval_method: 'NONE',
            }
          : graph && graphAvailable
          ? {
              mode: 'GRAPH', confidence: 0.98, intent: 'LINEAGE',
              entity_resolution_required: true, graph_traversal_required: true,
              semantic_retrieval_required: false, fallback_mode: 'VECTOR',
              primary_concepts: exact ? ['wafer_events'] : ['lineage'], secondary_concepts: [],
              relation_intent: /upstream/i.test(question) ? 'UPSTREAM' : /downstream|impact/i.test(question) ? 'DOWNSTREAM' : 'DEPENDENCY',
              entity_type_hints: ['TABLE'], selected_graph_asset: managedLineageGraphId,
              retrieval_method: 'SEMANTIC_ENTITY_RESOLUTION_GRAPH',
            }
          : inventory
            ? {
                mode: 'VECTOR', confidence: 0.99, intent: 'CATALOG_INVENTORY',
                entity_resolution_required: false, graph_traversal_required: false,
                semantic_retrieval_required: false, fallback_mode: null,
                primary_concepts: ['table inventory'], secondary_concepts: [], relation_intent: null,
                entity_type_hints: ['TABLE'], selected_graph_asset: null, retrieval_method: 'LEXICAL',
              }
            : exact
            ? {
                mode: 'VECTOR', confidence: 0.99, intent: 'EXACT_METADATA',
                entity_resolution_required: true, graph_traversal_required: false,
                semantic_retrieval_required: false, fallback_mode: 'GENERAL',
                primary_concepts: ['wafer_events'], secondary_concepts: [], relation_intent: null,
                entity_type_hints: ['TABLE'], selected_graph_asset: null, retrieval_method: 'LEXICAL',
              }
            : {
                mode: 'VECTOR', confidence: 0.92, intent: 'SEMANTIC_DISCOVERY',
                entity_resolution_required: false, graph_traversal_required: false,
                semantic_retrieval_required: true, fallback_mode: 'GENERAL',
                primary_concepts: ['metadata'], secondary_concepts: [], relation_intent: null,
                entity_type_hints: ['TABLE'], selected_graph_asset: null, retrieval_method: 'SEMANTIC',
              }
        return sendJson(response, { choices: [{ message: { content: forcedClassifierResponse ?? JSON.stringify(decision) } }] })
      }
      return sendJson(response, { choices: [{ message: { content: 'Live provider answer [1]' } }] })
    }
    if (url.pathname === '/api/graphql') {
      const payload = JSON.parse(body.toString('utf8'))
      if (payload.query.includes('DataRiverPocCurrentTables')) {
        return sendJson(response, { data: { entities: payload.variables.urns.map((urn) => ({
          urn,
          type: 'DATASET',
          subTypes: { typeNames: ['Table'] },
          properties: { customProperties: [] },
          schemaMetadata: { name: 'wafer_events' },
          globalTags: { tags: [{ tag: { urn: 'urn:li:tag:credential', name: 'credential' } }] },
        })) } })
      }
      if (payload.query.includes('DataRiverPocCatalog')) {
        if (hideExactFromTextSearch && payload.variables.input.query !== '*') {
          return sendJson(response, { data: { scrollAcrossEntities: {
            count: 0, total: 0, nextScrollId: null, searchResults: [],
          } } })
        }
        if (payload.variables.input.query === 'cursor-test') {
          const secondPage = payload.variables.input.scrollId === 'provider-page-2'
          const entity = secondPage ? {
            urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.QUALITY.inspection_results,PROD)',
            type: 'DATASET', name: 'inspection_results',
            platform: { urn: 'urn:li:dataPlatform:postgres', name: 'postgres' },
            properties: { name: 'inspection_results', description: 'Second provider page' },
            editableProperties: { description: null },
            browsePathV2: { path: [{ name: 'MANUFACTURING' }, { name: 'QUALITY' }, { name: 'inspection_results' }] },
            domain: null, ownership: { owners: [] }, globalTags: { tags: [] }, glossaryTerms: { terms: [] },
            schemaMetadata: { fields: [{ fieldPath: 'inspection_id' }] },
          } : {
            urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.QUALITY.wafer_events,PROD)',
            type: 'DATASET', name: 'wafer_events',
            platform: { urn: 'urn:li:dataPlatform:postgres', name: 'postgres' },
            properties: { name: 'wafer_events', description: 'First provider page' },
            editableProperties: { description: null },
            browsePathV2: { path: [{ name: 'MANUFACTURING' }, { name: 'QUALITY' }, { name: 'wafer_events' }] },
            domain: null, ownership: { owners: [] }, globalTags: { tags: [] }, glossaryTerms: { terms: [] },
            schemaMetadata: { fields: [{ fieldPath: 'wafer_id' }] },
          }
          return sendJson(response, { data: { scrollAcrossEntities: {
            count: 1,
            total: 2,
            nextScrollId: secondPage ? null : 'provider-page-2',
            searchResults: [{ entity }],
          } } })
        }
        return sendJson(response, { data: { scrollAcrossEntities: {
          count: 2,
          total: 2,
          searchResults: [
            { entity: {
              urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.QUALITY.wafer_events,PROD)',
              type: 'DATASET',
              name: 'wafer_events',
              platform: { urn: 'urn:li:dataPlatform:postgres', name: 'postgres' },
              properties: { name: 'wafer_events', description: 'Live DataHub wafer evidence' },
              editableProperties: { description: null },
              browsePathV2: { path: [{ name: 'MANUFACTURING' }, { name: 'QUALITY' }, { name: 'wafer_events' }] },
              domain: { domain: { urn: 'urn:li:domain:manufacturing' } },
              ownership: { owners: [{ owner: { urn: 'urn:li:corpuser:yield' } }] },
              globalTags: { tags: [{ tag: { name: 'gold' } }, { tag: { name: 'credential' } }] },
              glossaryTerms: { terms: [{ term: { urn: 'urn:li:glossaryTerm:wafer', name: 'Wafer' } }] },
              schemaMetadata: { fields: [{ fieldPath: 'wafer_id' }] },
            } },
            { entity: {
              urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.QUALITY.inspection_results,PROD)',
              type: 'DATASET',
              name: 'inspection_results',
              platform: { urn: 'urn:li:dataPlatform:postgres', name: 'postgres' },
              properties: { name: 'inspection_results', description: 'Live DataHub inspection evidence' },
              editableProperties: { description: null },
              browsePathV2: { path: [{ name: 'MANUFACTURING' }, { name: 'QUALITY' }, { name: 'inspection_results' }] },
              domain: null,
              ownership: { owners: [] },
              globalTags: { tags: [] },
              glossaryTerms: { terms: [] },
              schemaMetadata: { fields: [{ fieldPath: 'inspection_id' }] },
            } },
          ],
        } } })
      }
      if (payload.query.includes('DataRiverPocAsset')) {
        return sendJson(response, { data: { entity: {
          urn: payload.variables.urn,
          type: 'DATASET',
          name: 'wafer_events',
          subTypes: { typeNames: [forceKnowledgeNonTable ? 'View' : 'Table'] },
          platform: { urn: 'urn:li:dataPlatform:postgres', name: 'postgres' },
          properties: {
            name: 'wafer_events', description: 'Live DataHub wafer evidence', created: null,
            customProperties: [
              { key: 'size_in_bytes', value: '16,384' },
              { key: 'created_at', value: '2024-01-02T03:04:05Z' },
            ],
          },
          editableProperties: { description: null },
          browsePathV2: { path: [
            { name: 'urn:li:container:database', entity: { urn: 'urn:li:container:database', type: 'CONTAINER', properties: { name: 'urn:li:container:database', qualifiedName: 'MANUFACTURING' }, subTypes: { typeNames: ['Database'] } } },
            { name: 'urn:li:container:schema', entity: { urn: 'urn:li:container:schema', type: 'CONTAINER', properties: { name: 'urn:li:container:schema', qualifiedName: 'MANUFACTURING.QUALITY' }, subTypes: { typeNames: ['Schema'] } } },
          ] },
          domain: null,
          ownership: { owners: [] },
          globalTags: { tags: [{ tag: { name: 'credential' } }] },
          glossaryTerms: { terms: [] },
          schemaMetadata: { fields: [
            {
              fieldPath: 'wafer_id', nativeDataType: 'VARCHAR', description: 'Base wafer ID',
              globalTags: { tags: [{ tag: { urn: 'urn:li:tag:identifier', name: 'identifier' } }] },
              glossaryTerms: { terms: [{ term: { urn: 'urn:li:glossaryTerm:waferId', name: 'Wafer ID' } }] },
              schemaFieldEntity: {
                urn: omitKnowledgeColumnUrn
                  ? null
                  : `urn:li:schemaField:(${payload.variables.urn},wafer_id)`,
                type: omitKnowledgeColumnUrn ? null : 'SCHEMA_FIELD',
                globalTags: { tags: [{ tag: { urn: 'urn:li:tag:primary-key', name: 'primary-key' } }] },
                glossaryTerms: { terms: [] },
              },
            },
            {
              fieldPath: 'observed_at', nativeDataType: 'TIMESTAMP', description: 'Observed timestamp',
              schemaFieldEntity: {
                urn: `urn:li:schemaField:(${payload.variables.urn},observed_at)`,
                type: 'SCHEMA_FIELD', globalTags: { tags: [] }, glossaryTerms: { terms: [] },
              },
            },
          ] },
          editableSchemaMetadata: { editableSchemaFieldInfo: [{
            fieldPath: 'wafer_id', description: 'Curated wafer identifier',
            globalTags: { tags: [{ tag: { urn: 'urn:li:tag:curated', name: 'curated' } }] },
            glossaryTerms: { terms: [{ term: { urn: 'urn:li:glossaryTerm:identifier', name: 'Identifier' } }] },
          }] },
          latestFullTableProfile: [{
            rowCount: 999_999, columnCount: 2, sizeInBytes: 999_999, timestampMillis: 1_720_000_000_000,
            partitionSpec: { type: 'QUERY', partition: 'SAMPLE (sample rows 1000)' },
          }, {
            rowCount: 4400, columnCount: 2, sizeInBytes: null, timestampMillis: 1_710_000_000_000,
            partitionSpec: null,
          }, {
            rowCount: 4200, columnCount: 2, sizeInBytes: 8192, timestampMillis: 1_700_000_000_000,
            partitionSpec: { type: 'FULL_TABLE', partition: 'FULL_TABLE_SNAPSHOT' },
          }],
          assertions: {
            start: 0, count: 1, total: 1,
            assertions: [{
              urn: 'urn:li:assertion:quality-provider-test',
              info: { type: 'FRESHNESS', source: { type: 'GREAT_EXPECTATIONS' } },
              runEvents: {
                total: 1, failed: 0, succeeded: 1,
                runEvents: [{
                  timestampMillis: 1_725_000_000_000,
                  status: 'COMPLETE',
                  result: { type: 'SUCCESS' },
                }],
              },
            }],
          },
        } } })
      }
      if (payload.query.includes('DataRiverPocGlossaryAssignments')) {
        const entity = {
              urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.QUALITY.wafer_events,PROD)',
              type: 'DATASET', name: 'wafer_events',
              platform: { urn: 'urn:li:dataPlatform:postgres', name: 'postgres' },
              properties: { name: 'wafer_events' },
              browsePathV2: { path: [{ name: 'MANUFACTURING' }, { name: 'QUALITY' }, { name: 'wafer_events' }] },
              glossaryTerms: { terms: [{ term: { urn: 'urn:li:glossaryTerm:wafer' } }] },
              schemaMetadata: { fields: [{
                fieldPath: 'wafer_id',
                glossaryTerms: { terms: [{ term: { urn: 'urn:li:glossaryTerm:wafer' } }] },
                schemaFieldEntity: {
                  glossaryTerms: { terms: [{ term: { urn: 'urn:li:glossaryTerm:identifier' } }] },
                },
              }] },
              editableSchemaMetadata: { editableSchemaFieldInfo: [{
                fieldPath: 'wafer_id',
                glossaryTerms: { terms: [{ term: { urn: 'urn:li:glossaryTerm:identifier' } }] },
              }] },
            }
        return sendJson(response, { data: { entity: {
          urn: payload.variables.urn,
          type: 'GLOSSARY_TERM',
          relationships: {
            start: payload.variables.input.start,
            count: 1,
            total: 1,
            relationships: [{ entity }],
          },
        } } })
      }
      if (payload.query.includes('DataRiverPocGlossary')) {
        return sendJson(response, { data: { scrollAcrossEntities: {
          count: 2,
          total: 2,
          nextScrollId: null,
          searchResults: [
            { entity: {
              urn: 'urn:li:glossaryTerm:wafer', type: 'GLOSSARY_TERM', hierarchicalName: 'manufacturing.wafer',
              properties: { name: 'Wafer', description: 'A thin semiconductor substrate.' },
              tableAssignments: { total: 1 },
              columnAssignments: { total: 1 },
              parentNodes: { nodes: [
                { urn: 'urn:li:glossaryNode:manufacturing', type: 'GLOSSARY_NODE', properties: { name: 'Manufacturing', description: 'Manufacturing vocabulary' } },
                { urn: 'urn:li:glossaryNode:semiconductor', type: 'GLOSSARY_NODE', properties: { name: 'Semiconductor', description: 'Enterprise semiconductor vocabulary' } },
              ] },
            } },
            { entity: {
              urn: 'urn:li:glossaryTerm:identifier', type: 'GLOSSARY_TERM', hierarchicalName: 'shared.identifier',
              properties: { name: 'Identifier', description: 'A value used to identify a record.' },
              tableAssignments: { total: 0 },
              columnAssignments: { total: 1 },
              parentNodes: { nodes: [] },
            } },
          ],
        } } })
      }
      const relationships = payload.variables?.input?.direction === 'UPSTREAM'
        ? [{ entity: {
            urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.RAW.source_events,PROD)',
            type: 'DATASET', name: 'source_events',
            platform: { urn: 'urn:li:dataPlatform:postgres', name: 'postgres' },
            properties: { name: 'source_events', description: 'Raw source events' },
            editableProperties: { description: null },
            browsePathV2: { path: [{ name: 'MANUFACTURING' }, { name: 'RAW' }] },
            domain: null, ownership: { owners: [] }, globalTags: { tags: [] }, glossaryTerms: { terms: [] },
          } }]
        : [
            { entity: {
              urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.QUALITY.view_f09ab31,PROD)',
              type: 'DATASET', name: 'wafer_quality_view',
              platform: { urn: 'urn:li:dataPlatform:postgres', name: 'postgres' },
              properties: { name: 'wafer_quality_view', description: 'Published wafer quality view' },
              editableProperties: { description: null },
              browsePathV2: { path: [{ name: 'MANUFACTURING' }, { name: 'QUALITY' }] },
              domain: null, ownership: { owners: [] }, globalTags: { tags: [] }, glossaryTerms: { terms: [] },
            } },
            { entity: { urn: 'urn:li:dataJob:(urn:li:dataFlow:view_f09ab31,view_f09ab31)', type: 'DATA_JOB' } },
          ]
      return sendJson(response, { data: { dataset: { lineage: { total: relationships.length, relationships } } } })
    }
    if (url.pathname === '/db/neo4j/tx/commit') {
      const payload = JSON.parse(body.toString('utf8'))
      const query = payload.statements?.[0]?.statement || ''
      const parameters = payload.statements?.[0]?.parameters || {}
      if (query.includes('MATCH (node:K9Node)')) {
        const nodeIds = new Set(parameters.nodeIds || [])
        return sendJson(response, { errors: [], results: [{ data: managedK9Nodes
          .filter((node) => nodeIds.has(node.id))
          .map((node) => ({ row: [node.id, node.type, node.classification, JSON.stringify(node.properties)] })) }] })
      }
      if (query.includes('[relation:K9Edge]')) {
        const nodeIds = new Set(parameters.nodeIds || [])
        return sendJson(response, { errors: [], results: [{ data: managedK9Edges
          .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
          .map((edge) => ({ row: [edge.source, edge.target, edge.type, JSON.stringify(edge.properties)] })) }] })
      }
      if (query.includes('KNOWLEDGE_CHAT_NODES_V1')) {
        const expected = parameters.nodeEvidence || []
        const maximum = Number(parameters.maximumNodes || 200)
        const nodes = [...knowledgeNeo4jNodes.values()]
          .filter((node) => node.graph_id === parameters.graphId
            && node.studio_release_id === parameters.releaseId
            && expected.some((item) => item.source_urn === node.provenance?.source_urn
              && item.source_row_key === node.provenance?.source_row_key
              && item.source_hash === node.provenance?.source_hash
              && item.target_stable_element_id === node.stable_element_id))
          .sort((left, right) => left.id.localeCompare(right.id))
          .slice(0, maximum)
        return sendJson(response, { errors: [], results: [{ data: nodes.map((node) => ({ row: [
          node.id, node.type, node.identity, node.properties_json, node.stable_element_id,
          node.provenance.source_urn, node.provenance.source_row_key, node.provenance.source_hash,
          node.provenance.source_type, node.provenance.tbox_version,
        ] })) }] })
      }
      if (query.includes('KNOWLEDGE_CHAT_RELATIONS_V1')) {
        const expected = parameters.relationEvidence || []
        const nodeIds = new Set(parameters.nodeIds || [])
        const relations = [...knowledgeNeo4jEdges.values()]
          .filter((relation) => relation.graph_id === parameters.graphId
            && relation.studio_release_id === parameters.releaseId
            && nodeIds.has(relation.source_node_id)
            && nodeIds.has(relation.target_node_id)
            && expected.some((item) => item.source_urn === relation.provenance?.source_urn
              && item.source_row_key === relation.provenance?.source_row_key
              && item.source_hash === relation.provenance?.source_hash
              && item.relation_stable_element_id === relation.stable_element_id
              && item.source_node_id === relation.source_node_id
              && item.target_node_id === relation.target_node_id))
          .sort((left, right) => left.id.localeCompare(right.id))
        return sendJson(response, { errors: [], results: [{ data: relations.map((relation) => ({ row: [
          relation.id, relation.source_node_id, relation.target_node_id, relation.type,
          relation.properties_json, relation.provenance.source_urn,
          relation.provenance.source_row_key, relation.provenance.source_hash,
          relation.provenance.source_type, relation.provenance.tbox_version,
        ] })) }] })
      }
      if (query.includes('UNWIND $entities AS entity') || query.includes('UNWIND $nodes AS entity')) {
        if (forceABoxNeo4jFailure && query.includes('KnowledgeABoxEntity')) {
          return sendJson(response, { errors: [{ code: 'Neo.ClientError.Test', message: 'bounded test failure' }], results: [] })
        }
        const entities = parameters.entities || parameters.nodes || []
        for (const entity of entities) knowledgeNeo4jNodes.set(entity.id, {
          ...structuredClone(entity),
          ...(query.includes('KnowledgeABoxEntity') ? {
            graph_id: parameters.graphId,
            studio_release_id: parameters.releaseId,
            source_urn: entity.provenance?.source_urn,
            target_stable_element_id: entity.stable_element_id,
          } : {}),
        })
        return sendJson(response, { errors: [], results: [{ data: [{ row: [entities.length] }] }] })
      }
      if (query.includes('UNWIND $relations AS relationInput') && query.includes('KNOWLEDGE_RELATION')) {
        for (const relation of parameters.relations || []) {
          knowledgeNeo4jEdges.set(`abox\u0000${relation.id}`, {
            ...structuredClone(relation),
            graph_id: parameters.graphId,
            studio_release_id: parameters.releaseId,
          })
        }
        return sendJson(response, { errors: [], results: [{ data: [{ row: [(parameters.relations || []).length] }] }] })
      }
      if (query.includes('UNWIND $relations AS relationInput')) {
        for (const relation of parameters.relations || []) {
          knowledgeNeo4jEdges.set(
            `${parameters.studioReleaseId}\u0000${relation.source_id}\u0000${relation.target_id}`,
            structuredClone(relation),
          )
        }
        return sendJson(response, { errors: [], results: [{ data: [{ row: [(parameters.relations || []).length] }] }] })
      }
      if (query.includes('WITH node.id AS identity, count(node) AS copies')) {
        const nodes = [...knowledgeNeo4jNodes.values()].filter((node) => (
          query.includes('KnowledgeABoxEntity')
            ? node.graph_id === parameters.graphId
              && node.studio_release_id === parameters.releaseId
              && node.source_urn === parameters.sourceUrn
              && (Array.isArray(parameters.targetStableElementIds)
                ? parameters.targetStableElementIds.includes(node.target_stable_element_id)
                : node.target_stable_element_id === parameters.targetStableElementId)
            : node.knowledge_graph_id === parameters.graphId
              && node.knowledge_release_id === parameters.studioReleaseId
        ))
        return sendJson(response, { errors: [], results: [{ data: [{ row: [nodes.length, 0] }] }] })
      }
      if (query.includes('sum(exactCopies)')) {
        const relations = (parameters.relations || []).filter((expected) => {
          const relation = knowledgeNeo4jEdges.get(`abox\u0000${expected.id}`)
          return relation
            && relation.graph_id === parameters.graphId
            && relation.studio_release_id === parameters.releaseId
            && relation.source_node_id === expected.source_node_id
            && relation.target_node_id === expected.target_node_id
        })
        return sendJson(response, { errors: [], results: [{ data: [{ row: [relations.length, 0, relations.length] }] }] })
      }
      if (query.includes('RETURN count(relation)')) {
        const prefix = `${parameters.studioReleaseId}\u0000`
        const count = [...knowledgeNeo4jEdges.keys()].filter((identity) => identity.startsWith(prefix)).length
        return sendJson(response, { errors: [], results: [{ data: [{ row: [count] }] }] })
      }
      return sendJson(response, { errors: [], results: [{ data: [
        { row: ['wafer', 'Wafer', 'CLASS', 'HAS_INSPECTION', 'inspection', 'Inspection', 'CLASS'] },
      ] }] })
    }
    if (url.pathname.startsWith('/datariver-')) {
      assert.match(request.headers.authorization || '', /^AWS4-HMAC-SHA256 /)
      if (request.method === 'PUT') {
        objects.set(url.pathname, body)
        response.writeHead(200, { ETag: '"mock-etag"' })
        return response.end()
      }
      if (request.method === 'GET' && objects.has(url.pathname)) {
        response.writeHead(200, { 'Content-Type': 'application/octet-stream' })
        return response.end(objects.get(url.pathname))
      }
    }
    sendJson(response, { detail: 'not found' }, 404)
  })().catch((error) => sendJson(response, { detail: error.message }, 500))
}

before(async () => {
  providerServer = createServer(providerHandler)
  await new Promise((resolvePromise) => providerServer.listen(0, '127.0.0.1', resolvePromise))
  const providerAddress = providerServer.address()
  assert.equal(typeof providerAddress, 'object')
  const providerOrigin = `http://127.0.0.1:${providerAddress.port}`
  Object.assign(process.env, {
    POC_ENV_FILE: 'poc-server.providers.test.env.missing',
    POC_REDIS_URL: '',
    POC_DATABASE_URL: '',
    POC_POSTGRES_HOST: '',
    DATAHUB_GMS_URL: providerOrigin,
    DATAHUB_GMS_TOKEN: 'datahub-test-token',
    AIRFLOW_URL: `${providerOrigin}/airflow`,
    AIRFLOW_USERNAME: 'airflow-test',
    AIRFLOW_PASSWORD: 'airflow-test-password',
    MINIO_URL: providerOrigin,
    MINIO_ACCESS_KEY: 'minio-test-access',
    MINIO_SECRET_KEY: 'minio-test-secret',
    LLM_CHAT_URL: `${providerOrigin}/llm/chat/v1/chat/completions`,
    LLM_CHAT_MODEL: 'chat-model',
    LLM_CHAT_TOKEN: 'chat-test-token',
    LLM_EMBEDDING_URL: `${providerOrigin}/llm/embedding/v1/embeddings`,
    LLM_EMBEDDING_MODEL: 'embedding-model',
    LLM_EMBEDDING_TOKEN: 'embedding-test-token',
    LLM_RERANKER_URL: `${providerOrigin}/llm/reranker/v1/rerank`,
    LLM_RERANKER_MODEL: 'reranker-model',
    LLM_RERANKER_TOKEN: 'reranker-test-token',
    NEO4J_HTTP_URL: providerOrigin,
    NEO4J_USERNAME: 'neo4j',
    NEO4J_PASSWORD: 'neo4j-test-password',
    UI_GRAFANA_URL: `${providerOrigin}/dashboards/datariver`,
    GRAFANA_EMBED_BASE_URL: providerOrigin,
    GRAFANA_EMBED_ENABLED: 'true',
    GRAFANA_EMBED_EVIDENCE_REFERENCE: 'prep-poc-grafana-config-v1',
    MONITORING_DASHBOARDS_JSON: JSON.stringify([
      { id: 'platform', label: 'Platform', url: `${providerOrigin}/dashboards/datariver`, height_px: 900 },
      { id: 'airflow', label: 'Airflow', url: `${providerOrigin}/dashboards/airflow`, height_px: 720 },
    ]),
    POC_KNOWLEDGE_SOURCE_MANIFEST: JSON.stringify({
      'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.QUALITY.wafer_events,PROD)': {
        manifest_ref: 'k5-provider-test-v1',
        source_version: 'provider-source-v1',
        secret_ref: 'secret:provider-source',
      },
    }),
  })
  const { createPocStateStore } = await import('./poc-state-store.mjs?provider-contract-test')
  const module = await import('./poc-server.mjs?provider-contract-test')
  providerStateStore = createPocStateStore()
  providerStateStore.listK9ManagedGraphAssets = async () => [managedK9Row]
  providerStateStore.getK9ManagedGraphAsset = async (graphId) => (
    graphId === managedLineageGraphId ? managedK9Row : null
  )
  await providerStateStore.write('change-history-access-v1', {
    schema_version: 1,
    active_subject_id: 'provider-test-subject',
    users: [{ subject_id: 'provider-test-subject', role: 'admin', active: true, provider_owner_refs: [] }],
    system_assignments: [],
  })
  pocServer = module.createPocServer({
    stateStore: providerStateStore,
    authenticator: {
      async authenticate() { return { subjectId: 'provider-test-subject', tokenHash: 'f'.repeat(64) } },
      assertOrigin() {},
    },
  })
  await new Promise((resolvePromise) => pocServer.listen(0, '127.0.0.1', resolvePromise))
  const pocAddress = pocServer.address()
  assert.equal(typeof pocAddress, 'object')
  pocOrigin = `http://127.0.0.1:${pocAddress.port}`
})

after(async () => {
  pocServer.closeAllConnections()
  providerServer.closeAllConnections()
  await Promise.all([
    new Promise((resolvePromise, reject) => pocServer.close((error) => error ? reject(error) : resolvePromise())),
    new Promise((resolvePromise, reject) => providerServer.close((error) => error ? reject(error) : resolvePromise())),
  ])
  await providerStateStore.close()
})

test('publishes only enabled flags while all provider probes pass', async () => {
  const runtime = await (await fetch(`${pocOrigin}/poc-runtime-config.js`)).text()
  assert.match(runtime, /"datahub":true/)
  assert.doesNotMatch(runtime, /test-token|test-password|test-secret/)
  const capability = await (await fetch(`${pocOrigin}/poc-api/capabilities`)).json()
  assert.ok(capability.items.every((item) => item.state === 'available'))
  assert.equal(capability.grafana_embed.state, 'AVAILABLE')
  assert.equal(capability.items.find((item) => item.name === 'Airflow').detail_code, 'AIRFLOW_API_V1')
  assert.deepEqual(
    capability.monitoring_configuration.items.map((item) => [item.id, item.embed_state, item.embed_url]),
    [
      ['platform', 'AVAILABLE', `${new URL(capability.grafana_embed.url).origin}/dashboards/datariver`],
      ['airflow', 'AVAILABLE', `${new URL(capability.grafana_embed.url).origin}/dashboards/airflow`],
    ],
  )
  assert.ok(requests.some((request) => request.method === 'POST' && request.path.endsWith('/rerank')))
})

test('maps fixed DataHub catalog, detail and lineage contracts', async () => {
  const catalog = await (await fetch(`${pocOrigin}/poc-api/datahub/catalog?q=wafer%20evidence&limit=5`)).json()
  assert.equal(catalog.items[0].name, 'wafer_events')
  assert.equal(catalog.items[0].database_name, 'MANUFACTURING')
  assert.equal(catalog.match_mode, 'ALL')
  assert.deepEqual(catalog.items[0].matches.map((match) => match.field), ['NAME', 'DESCRIPTION', 'COLUMN', 'TERM'])
  assert.deepEqual(catalog.items[0].matches.find((match) => match.field === 'NAME').matched_terms, ['wafer'])
  assert.deepEqual(catalog.items[0].matches.find((match) => match.field === 'DESCRIPTION').matched_terms, ['wafer', 'evidence'])
  const missingTerm = await (await fetch(`${pocOrigin}/poc-api/datahub/catalog?q=wafer%20missing&limit=5`)).json()
  assert.equal(missingTerm.items.length, 0)
  const columnMatch = await (await fetch(`${pocOrigin}/poc-api/datahub/catalog?q=inspection_id&search_fields=COLUMN&limit=5`)).json()
  assert.equal(columnMatch.items[0].name, 'inspection_results')
  assert.deepEqual(columnMatch.items[0].matches.map((match) => match.field), ['COLUMN'])
  const tagMatch = await (await fetch(`${pocOrigin}/poc-api/datahub/catalog?q=gold&search_fields=TAG&limit=5`)).json()
  assert.equal(tagMatch.items[0].name, 'wafer_events')
  assert.deepEqual(tagMatch.items[0].matches.map((match) => match.field), ['TAG'])
  const wrongField = await (await fetch(`${pocOrigin}/poc-api/datahub/catalog?q=gold&search_fields=TABLE&limit=5`)).json()
  assert.equal(wrongField.items.length, 0)
  const urn = encodeURIComponent(catalog.items[0].external_urn)
  const detail = await (await fetch(`${pocOrigin}/poc-api/datahub/asset?urn=${urn}`)).json()
  assert.equal(detail.database_name, 'MANUFACTURING')
  assert.equal(detail.schema_name, 'QUALITY')
  assert.equal(detail.dataset_kind, 'TABLE')
  assert.equal(detail.schema_fields[0].fieldPath, 'wafer_id')
  assert.equal(detail.schema_fields[0].description, 'Curated wafer identifier')
  assert.equal(detail.schema_fields[0].globalTags.tags[0].tag.name, 'identifier')
  assert.deepEqual(detail.schema_fields[0].globalTags.tags.map((item) => item.tag.name), ['identifier', 'primary-key', 'curated'])
  assert.equal(detail.schema_fields[0].glossaryTerms.terms[0].term.name, 'Wafer ID')
  assert.deepEqual(detail.schema_fields[0].glossaryTerms.terms.map((item) => item.term.name), ['Wafer ID', 'Identifier'])
  assert.equal(detail.quality.rowCount, 4400)
  assert.equal(detail.quality.rowCountSource, 'DATASET_PROFILE_FULL_TABLE')
  assert.equal(detail.quality.sizeInBytes, 16384)
  assert.equal(detail.quality.sizeInBytesSource, 'DATASET_PROPERTIES_ALLOWLIST')
  assert.equal(detail.quality.assertionTotal, 1)
  assert.equal(detail.quality.assertionReturned, 1)
  assert.equal(detail.quality.assertionTruncated, false)
  assert.deepEqual(detail.quality.assertionSourceTypes, ['GREAT_EXPECTATIONS'])
  assert.equal(detail.quality.latestAssertionStatus, 'COMPLETE')
  assert.equal(detail.quality.latestAssertionResult, 'SUCCESS')
  assert.equal(detail.quality.latestAssertionObservedAt, '2024-08-30T06:40:00.000Z')
  assert.equal(detail.created_at, '2024-01-02T03:04:05.000Z')
  const detailQuery = [...requests].reverse().find((request) => (
    request.path === '/api/graphql' && request.body.includes('DataRiverPocAsset')
  ))
  assert.match(detailQuery.body, /datasetProfiles\(limit: 10\)/)
  assert.match(detailQuery.body, /assertions\(start: 0, count: 100\)/)
  const secondFieldPage = await (await fetch(`${pocOrigin}/poc-api/datahub/asset?urn=${urn}&field_offset=1&field_limit=1`)).json()
  assert.equal(secondFieldPage.schema_fields[0].fieldPath, 'observed_at')
  assert.equal(secondFieldPage.schema_fields_offset, 1)
  assert.equal(secondFieldPage.schema_fields_has_more, false)
  const lineage = await (await fetch(`${pocOrigin}/poc-api/datahub/lineage?urn=${urn}`)).json()
  assert.equal(lineage.center_asset_id, catalog.items[0].external_urn)
  assert.deepEqual(lineage.nodes.map((item) => item.name).sort(), [
    'source_events', 'wafer_events', 'wafer_quality_view',
  ])
  assert.equal(lineage.nodes.some((item) => item.name.includes('view_f09ab31')), false)
  const lineageRequests = requests
    .filter((request) => request.path === '/api/graphql' && request.body.includes('DataRiverPocLineage'))
    .map((request) => JSON.parse(request.body))
  assert.equal(lineageRequests.length, 2)
  assert.ok(lineageRequests.every((request) => request.variables.input.separateSiblings === false))
  assert.ok(lineageRequests.every((request) => request.variables.input.includeGhostEntities === false))
})

test('keeps opaque cursors server-side and aggregates the complete DataHub inventory', async () => {
  const first = await (await fetch(`${pocOrigin}/poc-api/datahub/catalog?q=evidence&limit=1`)).json()
  assert.equal(first.items[0].name, 'inspection_results')
  assert.ok(first.page.next_cursor)
  assert.notEqual(first.page.next_cursor, 'provider-page-2')
  const second = await (await fetch(`${pocOrigin}/poc-api/datahub/catalog?q=evidence&limit=1&cursor=${encodeURIComponent(first.page.next_cursor)}`)).json()
  assert.equal(second.items[0].name, 'wafer_events')
  assert.equal(second.page.next_cursor, null)
  const located = await (await fetch(
    `${pocOrigin}/poc-api/datahub/catalog/locate?asset_id=${encodeURIComponent(second.items[0].id)}&q=*&search_fields=SCHEMA%2CTABLE%2CCOLUMN%2CTAG%2CTERM%2CDESCRIPTION&limit=1`,
  )).json()
  assert.equal(located.asset_id, second.items[0].id)
  assert.equal(located.page_index, 1)
  assert.equal(located.cursors.length, 2)
  assert.ok(located.cursors[1])
  const inventoryRequest = requests.find((request) => (
    request.path === '/api/graphql' && request.body.includes('DataRiverPocCatalogEmbeddingInventory')
  ))
  assert.ok(inventoryRequest, 'the fixed DataHub inventory query must be observed')
  assert.deepEqual(JSON.parse(inventoryRequest.body).variables.input.sortInput, {
    sortCriteria: [{ field: 'urn', sortOrder: 'ASCENDING' }],
  })

  const root = await (await fetch(`${pocOrigin}/poc-api/datahub/tree?parent_kind=ROOT&limit=100`)).json()
  assert.deepEqual(root.items.map((item) => item.label), ['postgres'])
  assert.equal(root.items[0].asset_count, 2)
  const refreshedRoot = await (await fetch(`${pocOrigin}/poc-api/datahub/tree?parent_kind=ROOT&limit=100&refresh=true`)).json()
  assert.deepEqual(refreshedRoot.items.map((item) => item.label), ['postgres'])
  const dashboard = await (await fetch(`${pocOrigin}/poc-api/datahub/dashboard`)).json()
  assert.equal(dashboard.catalog_asset_count, 2)
  const coverage = await (await fetch(`${pocOrigin}/poc-api/datahub/profile-coverage`)).json()
  assert.ok(['DATAHUB_GMS_VECTOR_PROJECTION', 'PROCESS_MEMORY_CURRENT_PROJECTION'].includes(coverage.source))
  assert.equal(coverage.asset_count, 2)
  assert.equal(coverage.schema_available, 2)
  const systems = await (await fetch(`${pocOrigin}/poc-api/datahub/systems`)).json()
  assert.deepEqual(systems.items.map((item) => item.id), ['postgres'])
  const glossary = await (await fetch(`${pocOrigin}/poc-api/datahub/glossary?q=wafer`)).json()
  assert.equal(glossary.items.length, 1)
  assert.equal(glossary.items[0].name, 'Wafer')
  assert.equal(glossary.items[0].description, 'A thin semiconductor substrate.')
  assert.deepEqual(glossary.items[0].parent_terms.map((item) => item.name), ['Semiconductor', 'Manufacturing'])
  assert.equal(glossary.items[0].asset_count, 2)
  assert.equal(glossary.items[0].table_asset_count, 1)
  assert.equal(glossary.items[0].column_asset_count, 1)
  assert.deepEqual(glossary.items[0].assets, [])
  const termUrn = encodeURIComponent(glossary.items[0].urn)
  const tableAssignments = await (await fetch(`${pocOrigin}/poc-api/datahub/glossary/assignments?urn=${termUrn}&target_type=TABLE&limit=25`)).json()
  assert.equal(tableAssignments.total, 1)
  assert.equal(tableAssignments.items[0].target_type, 'TABLE')
  assert.equal(tableAssignments.items[0].table_name, 'wafer_events')
  const columnAssignments = await (await fetch(`${pocOrigin}/poc-api/datahub/glossary/assignments?urn=${termUrn}&target_type=COLUMN&limit=25`)).json()
  assert.equal(columnAssignments.total, 1)
  assert.equal(columnAssignments.items[0].target_type, 'COLUMN')
  assert.equal(columnAssignments.items[0].field_path, 'wafer_id')
  const technicalGlossary = await (await fetch(`${pocOrigin}/poc-api/datahub/glossary?q=manufacturing_wafer`)).json()
  assert.equal(technicalGlossary.items[0].name, 'Wafer')
})

test('runs the fixed embedding, reranking and Chat pipeline', async () => {
  const response = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'wafer metadata evidence', mode: 'AUTO' }),
  })
  assert.equal(response.status, 200, await response.clone().text())
  const payload = await response.json()
  assert.equal(payload.answer, 'Live provider answer [1]')
  assert.equal(payload.route.selected_mode, 'VECTOR')
  assert.equal(payload.evidence[0].evidence_type, 'CATALOG_METADATA')
  assert.equal(payload.evidence[0].retrieval_method, 'PGVECTOR_COSINE')
  for (const path of ['/embeddings', '/rerank', '/chat/completions']) {
    assert.ok(requests.some((request) => request.path.endsWith(path)))
  }
  const catalogBatch = requests.find((request) => request.path.endsWith('/embeddings')
    && Array.isArray(JSON.parse(request.body).input)
    && JSON.parse(request.body).input.length === 2)
  assert.ok(catalogBatch, 'the complete two-asset DataHub inventory must be embedded')
  assert.ok(JSON.parse(catalogBatch.body).input.every((document) => document.includes('Columns (')))
  const classifierRequest = [...requests].reverse().find((request) => {
    if (!request.path.endsWith('/chat/completions')) return false
    return JSON.parse(request.body).messages?.[0]?.content?.includes('Plan one untrusted Data Catalog question')
  })
  const classifierPayload = JSON.parse(classifierRequest.body)
  assert.equal(classifierPayload.response_format.type, 'json_schema')
  assert.equal(classifierPayload.reasoning_effort, 'none')
  assert.deepEqual(classifierPayload.reasoning, { effort: 'none' })
  assert.equal(classifierPayload.max_tokens, 640)
})

test('counts the complete DataHub table inventory and returns the requested list cardinality', async () => {
  const completionsBefore = requests.filter((request) => request.path.endsWith('/chat/completions')).length
  const response = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'DataHub에 테이블이 몇 개 있고 10개를 나열해줘', mode: 'AUTO' }),
  })
  assert.equal(response.status, 200)
  const payload = await response.json()
  assert.equal(payload.route.selected_mode, 'VECTOR')
  assert.equal(payload.route.intent, 'CATALOG_INVENTORY')
  assert.equal(payload.evidence[0].dataset_kind, 'CATALOG')
  assert.equal(payload.evidence[0].inventory_total, 2)
  assert.deepEqual(payload.evidence.slice(1).map((item) => item.name), ['inspection_results', 'wafer_events'])
  assert.match(payload.answer, /테이블 2개/)
  assert.match(payload.answer, /inspection_results/)
  assert.match(payload.answer, /wafer_events/)
  assert.equal(requests.filter((request) => request.path.endsWith('/chat/completions')).length, completionsBefore + 1)
})

test('streams approved answer deltas before the persisted final provider result', async () => {
  const response = await fetch(`${pocOrigin}/poc-api/llm/chat/stream`, {
    method: 'POST',
    headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'wafer_events 테이블의 컬럼을 알려줘', mode: 'AUTO' }),
  })
  assert.equal(response.status, 200)
  assert.match(response.headers.get('content-type') || '', /^text\/event-stream/)
  const stream = await response.text()
  const frames = stream.trim().split(/\n\n+/)
  assert.match(frames[0], /^event: workflow\ndata: /)
  assert.match(frames[0], /"stage":"AUTHORIZATION","status":"IN_PROGRESS"/)
  const answerDelta = stream.indexOf('event: answer_delta')
  const persistence = stream.indexOf('"stage":"PERSISTENCE","status":"IN_PROGRESS"')
  const result = stream.indexOf('event: result')
  assert.ok(stream.indexOf('"stage":"ROUTING","status":"IN_PROGRESS"') < answerDelta)
  assert.ok(answerDelta < persistence)
  assert.ok(persistence < result)
  assert.match(stream, /event: answer_delta\ndata: \{"delta":"/)
  assert.match(frames.at(-1) || '', /^event: result\ndata: /)
  assert.match(frames.at(-1) || '', /"persistence":"PERSISTED"/)
  const resultPayload = JSON.parse((frames.at(-1) || '').split('\ndata: ')[1])
  const sessionsResponse = await fetch(`${pocOrigin}/poc-api/chat/sessions`)
  assert.equal(sessionsResponse.status, 200)
  const sessions = await sessionsResponse.json()
  assert.equal(sessions.some((session) => session.id === resultPayload.session_id && session.message_count === 2), true)
  const messagesResponse = await fetch(`${pocOrigin}/poc-api/chat/sessions/${resultPayload.session_id}/messages`)
  assert.equal(messagesResponse.status, 200)
  const messages = await messagesResponse.json()
  assert.deepEqual(messages.map((message) => message.role), ['user', 'assistant'])
  assert.equal(messages[1].content, resultPayload.answer)
})

test('uses bounded conversation memory to resolve a same-session follow-up without treating it as evidence', async () => {
  const memory = {
    summary: '사용자는 wafer_events 테이블을 확인했습니다.',
    compacted_turn_count: 5,
    recent_turns: [{
      question: '이 테이블의 목적은?',
      answer: 'wafer_events는 웨이퍼 이벤트를 기록합니다.',
    }],
  }
  const response = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: '그 테이블의 컬럼도 알려줘', mode: 'AUTO', memory }),
  })
  assert.equal(response.status, 200)
  const payload = await response.json()
  assert.equal(payload.evidence[0].name, 'wafer_events')
  const contextualizer = [...requests].reverse().find((request) => {
    if (!request.path.endsWith('/chat/completions')) return false
    return JSON.parse(request.body).messages?.[0]?.content?.includes('Rewrite the current Data Catalog question')
  })
  assert.ok(contextualizer)
  const composer = [...requests].reverse().find((request) => {
    if (!request.path.endsWith('/chat/completions')) return false
    return JSON.parse(request.body).messages?.[0]?.content?.includes('Bounded conversation memory is non-authoritative')
  })
  assert.match(JSON.parse(composer.body).messages[1].content, /사용자는 wafer_events 테이블을 확인했습니다/)
  assert.equal(payload.evidence.some((item) => item.evidence_type === 'CHAT_MEMORY'), false)
})

test('compacts exactly five bounded Chat turns and rejects oversized question or memory input', async () => {
  const recentTurns = Array.from({ length: 5 }, (_, index) => ({
    question: `${index + 1}번째 wafer_events 질문`,
    answer: `${index + 1}번째 DataHub 근거 답변`,
  }))
  const compact = await fetch(`${pocOrigin}/poc-api/llm/chat/compact`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ memory: { summary: '', compacted_turn_count: 0, recent_turns: recentTurns } }),
  })
  assert.equal(compact.status, 200)
  assert.deepEqual(await compact.json(), {
    summary: '사용자는 wafer_events 메타데이터를 확인했고 후속 컬럼 조회를 원합니다.',
    compacted_turn_count: 5,
  })

  const oversizedQuestion = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'x'.repeat(12_001), mode: 'AUTO' }),
  })
  assert.equal(oversizedQuestion.status, 400)
  assert.match((await oversizedQuestion.json()).detail, /at most 12000 characters/)

  const oversizedMemory = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question: 'wafer_events', mode: 'AUTO',
      memory: { summary: '', compacted_turn_count: 0, recent_turns: [...recentTurns, recentTurns[0]] },
    }),
  })
  assert.equal(oversizedMemory.status, 400)
  assert.match((await oversizedMemory.json()).detail, /at most five recent turns/)
})

test('routes a high-confidence Korean discovery question to the full vector inventory without classifier drift', async () => {
  const classifiersBefore = requests.filter((request) => request.path.endsWith('/chat/completions')
    && JSON.parse(request.body).messages?.[0]?.content?.includes('Plan one untrusted Data Catalog question')).length
  const response = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: '설비 투자와 관련된 테이블을 추천해줘', mode: 'AUTO' }),
  })
  assert.equal(response.status, 200)
  const payload = await response.json()
  assert.equal(payload.route.selected_mode, 'VECTOR')
  assert.equal(payload.route.intent, 'SEMANTIC_DISCOVERY')
  assert.ok(payload.evidence.length > 0)
  assert.ok(payload.evidence.every((item) => item.retrieval_method === 'PGVECTOR_COSINE'))
  const classifiersAfter = requests.filter((request) => request.path.endsWith('/chat/completions')
    && JSON.parse(request.body).messages?.[0]?.content?.includes('Plan one untrusted Data Catalog question')).length
  assert.equal(classifiersAfter, classifiersBefore + 1)
})

test('retrieves Knowledge Graph Asset metadata from the authorized managed registry instead of DataHub tables', async () => {
  forcedClassifierResponse = JSON.stringify({
    mode: 'VECTOR', confidence: 0.99, intent: 'SEMANTIC_DISCOVERY',
    entity_resolution_required: false, graph_traversal_required: false,
    semantic_retrieval_required: true, fallback_mode: null,
    primary_concepts: ['Default Lineage Graph'], secondary_concepts: [], relation_intent: null,
    entity_type_hints: ['KNOWLEDGE_ASSET'], selected_graph_asset: null, retrieval_method: 'SEMANTIC',
  })
  try {
    const response = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: 'Show the Default Lineage Graph Asset metadata', mode: 'AUTO' }),
    })
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.route.selected_mode, 'VECTOR')
    assert.equal(payload.route.entity_type_hints[0], 'KNOWLEDGE_ASSET')
    assert.equal(payload.evidence.length, 1)
    assert.equal(payload.evidence[0].id, managedLineageGraphId)
    assert.equal(payload.evidence[0].name, 'Default Lineage Graph')
    assert.equal(payload.evidence[0].evidence_type, 'KNOWLEDGE_GRAPH_ASSET_METADATA')
    assert.equal(payload.evidence[0].retrieval_method, 'K9_REGISTRY_EXACT')
    assert.match(payload.evidence[0].description, /Source: DataHub/)
    assert.match(payload.evidence[0].description, /Semantic \/ Vector Index:/)

    forcedClassifierResponse = JSON.stringify({
      mode: 'VECTOR', confidence: 0.99, intent: 'SEMANTIC_DISCOVERY',
      entity_resolution_required: false, graph_traversal_required: false,
      semantic_retrieval_required: true, fallback_mode: null,
      primary_concepts: ['Knowledge Graph Asset', 'data lineage'], secondary_concepts: [], relation_intent: null,
      entity_type_hints: ['KNOWLEDGE_ASSET'], selected_graph_asset: null, retrieval_method: 'SEMANTIC',
    })
    const discoveryResponse = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: 'Find the registered graph Asset for data lineage', mode: 'AUTO' }),
    })
    assert.equal(discoveryResponse.status, 200)
    const discovery = await discoveryResponse.json()
    assert.equal(discovery.evidence.length, 1)
    assert.equal(discovery.evidence[0].id, managedLineageGraphId)
    assert.equal(discovery.evidence[0].retrieval_method, 'K9_REGISTRY_SEMANTIC_METADATA')
  } finally {
    forcedClassifierResponse = undefined
  }
})

test('resolves an exact table name and composes detailed DataHub metadata evidence', async () => {
  const classifiersBefore = requests.filter((request) => request.path.endsWith('/chat/completions')
    && JSON.parse(request.body).messages?.[0]?.content?.includes('Plan one untrusted Data Catalog question')).length
  const response = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'wafer_events 테이블의 목적, 컬럼, 태그와 용어를 설명해줘', mode: 'AUTO' }),
  })
  assert.equal(response.status, 200)
  const payload = await response.json()
  assert.equal(payload.route.selected_mode, 'VECTOR')
  assert.equal(payload.route.intent, 'EXACT_METADATA')
  assert.equal(payload.route.semantic_retrieval_required, false)
  assert.equal(payload.evidence.length, 1)
  assert.equal(payload.evidence[0].name, 'wafer_events')
  assert.equal(payload.evidence[0].retrieval_method, 'CATALOG_EXACT')
  assert.match(payload.evidence[0].description, /wafer_id \(VARCHAR\)/)
  assert.match(payload.evidence[0].description, /Curated wafer identifier/)
  assert.match(payload.evidence[0].description, /Wafer ID/)
  assert.equal(payload.evidence[0].dataset_kind, 'TABLE')
  const composer = [...requests].reverse().find((request) => {
    if (!request.path.endsWith('/chat/completions')) return false
    return !JSON.parse(request.body).messages?.[0]?.content?.includes('Plan one untrusted Data Catalog question')
  })
  assert.equal(JSON.parse(composer.body).max_tokens, 896)
  assert.doesNotMatch(JSON.parse(composer.body).messages[0].content, /concisely/i)
  const classifiersAfter = requests.filter((request) => request.path.endsWith('/chat/completions')
    && JSON.parse(request.body).messages?.[0]?.content?.includes('Plan one untrusted Data Catalog question')).length
  assert.equal(classifiersAfter, classifiersBefore + 1)
})

test('routes an exact Korean relationship question through one semantic planner and the managed graph', async () => {
  const classifiersBefore = requests.filter((request) => request.path.endsWith('/chat/completions')
    && JSON.parse(request.body).messages?.[0]?.content?.includes('Plan one untrusted Data Catalog question')).length
  const completionsBefore = requests.filter((request) => request.path.endsWith('/chat/completions')).length
  const response = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'wafer_events 연결 관계를 알려줘', mode: 'AUTO' }),
  })
  assert.equal(response.status, 200)
  const payload = await response.json()
  assert.equal(payload.route.selected_mode, 'GRAPH')
  assert.equal(payload.route.intent, 'LINEAGE')
  assert.equal(payload.route.selected_graph_asset, managedLineageGraphId)
  assert.equal(payload.route.knowledge_scope.selection_source, 'MANAGED_ASSET_CAPABILITY')
  assert.ok(payload.evidence.some((item) => item.evidence_type === 'KNOWLEDGE_ASSET_NODE'))
  assert.ok(payload.evidence.some((item) => item.evidence_type === 'KNOWLEDGE_ASSET_RELATION'))
  assert.ok(payload.evidence.some((item) => item.name === 'source_events'))
  const classifiersAfter = requests.filter((request) => request.path.endsWith('/chat/completions')
    && JSON.parse(request.body).messages?.[0]?.content?.includes('Plan one untrusted Data Catalog question')).length
  assert.equal(classifiersAfter, classifiersBefore + 1)
  assert.equal(requests.filter((request) => request.path.endsWith('/chat/completions')).length, completionsBefore + 2)
})

test('resolves an exact graph asset from the cached provider inventory when DataHub text ranking omits it', async () => {
  hideExactFromTextSearch = true
  try {
    const response = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: 'wafer_events 테이블의 upstream과 downstream을 알려줘', mode: 'AUTO' }),
    })
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.route.selected_graph_asset, managedLineageGraphId)
    assert.equal(payload.route.resolved_entities[0].method, 'CATALOG_EXACT')
    assert.ok(payload.evidence.some((item) => item.evidence_type === 'KNOWLEDGE_ASSET_RELATION'))
    assert.doesNotMatch(payload.answer, /가장 가까운 후보/)
  } finally {
    hideExactFromTextSearch = false
  }
})

test('routes lineage questions through the capability-selected managed graph only', async () => {
  const genericNeo4jReadsBefore = requests.filter((request) => (
    request.path === '/db/neo4j/tx/commit'
    && request.body.includes('MATCH (source)-[relation]->(target)')
  )).length
  const response = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'Show upstream lineage impact', mode: 'AUTO' }),
  })
  assert.equal(response.status, 200)
  const payload = await response.json()
  assert.equal(payload.route.selected_mode, 'GRAPH')
  assert.equal(payload.route.reason, 'GRAPH_ASSET_CAPABILITY')
  assert.equal(payload.route.selected_graph_asset, managedLineageGraphId)
  assert.ok(payload.evidence.some((item) => item.evidence_type === 'KNOWLEDGE_ASSET_NODE'))
  assert.ok(payload.evidence.some((item) => item.evidence_type === 'KNOWLEDGE_ASSET_RELATION'))
  assert.ok(payload.workflow.some((item) => item.detail_code === 'AUTHORIZED_KNOWLEDGE_ASSET_EVIDENCE_BOUND'))
  assert.equal(requests.filter((request) => (
    request.path === '/db/neo4j/tx/commit'
    && request.body.includes('MATCH (source)-[relation]->(target)')
  )).length, genericNeo4jReadsBefore)
})

test('bypasses the classifier for explicit Chat routes and fails malformed AUTO routes closed', async () => {
  const before = requests.filter((request) => request.path.endsWith('/chat/completions')).length
  const explicit = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'Explain governance in general', mode: 'GENERAL' }),
  })
  assert.equal(explicit.status, 200)
  const explicitPayload = await explicit.json()
  assert.equal(explicitPayload.route.selected_mode, 'GENERAL')
  assert.ok(explicitPayload.workflow.some((item) => (
    item.stage === 'RETRIEVAL'
    && item.status === 'SKIPPED'
    && item.detail_code === 'RETRIEVAL_NOT_EXECUTED'
  )))
  assert.ok(explicitPayload.workflow.some((item) => item.detail_code === 'NO_INTERNAL_CITATIONS_GENERAL_ANSWER'))
  const generalCompletion = requests.filter((request) => request.path.endsWith('/chat/completions')).at(-1)
  const generalCompletionPayload = JSON.parse(generalCompletion.body)
  assert.match(generalCompletionPayload.messages[0].content, /GENERAL route: answer useful general-knowledge/)
  assert.doesNotMatch(generalCompletionPayload.messages[1].content, /Live POC evidence|no matching live evidence/)
  assert.equal(requests.filter((request) => request.path.endsWith('/chat/completions')).length, before + 1)

  forcedClassifierResponse = 'VECTOR because metadata'
  const malformed = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'Please classify this request', mode: 'AUTO' }),
  })
  forcedClassifierResponse = undefined
  assert.equal(malformed.status, 503)
  assert.match((await malformed.json()).detail, /bounded classifier failed/)
})

test('routes general Korean conversation without probing DataHub as arbitrary asset identifiers', async () => {
  const graphqlBefore = requests.filter((request) => request.path === '/api/graphql').length
  forcedClassifierResponse = JSON.stringify({
    mode: 'GENERAL', confidence: 0.99, intent: 'GENERAL_CONVERSATION',
    entity_resolution_required: false, graph_traversal_required: false,
    semantic_retrieval_required: false, fallback_mode: null,
    primary_concepts: [], secondary_concepts: [], relation_intent: null,
    entity_type_hints: [], selected_graph_asset: null, retrieval_method: 'NONE',
  })
  const response = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: '나의 이름은 뭐지?', mode: 'AUTO' }),
  })
  forcedClassifierResponse = undefined
  assert.equal(response.status, 200)
  assert.equal((await response.json()).route.selected_mode, 'GENERAL')
  assert.equal(requests.filter((request) => request.path === '/api/graphql').length, graphqlBefore)
})

test('triggers only the fixed Airflow DAG and proxies a bounded MinIO upload', async () => {
  const dag = await fetch(`${pocOrigin}/poc-api/airflow/dags/datariver_quality_dispatch/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conf: { poc_run_id: 'run-1' } }),
  })
  assert.equal(dag.status, 202)
  assert.ok(requests.some((request) => request.path.includes('/airflow/api/v1/dags/datariver_quality_dispatch/dagRuns')))
  const part = await fetch(`${pocOrigin}/poc-api/minio/uploads/upload-1/parts/1`, {
    method: 'PUT',
    headers: { 'Content-Type': 'text/plain' },
    body: 'sample-object',
  })
  assert.equal(part.status, 200)
  const complete = await fetch(`${pocOrigin}/poc-api/minio/uploads/upload-1/complete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ part_count: 1, display_name: 'sample.txt', content_type: 'text/plain' }),
  })
  assert.equal(complete.status, 200)
  assert.equal((await complete.json()).size_bytes, 13)
  const download = await fetch(`${pocOrigin}/poc-api/minio/accepted/upload-1/sample.txt`)
  assert.equal(download.status, 200)
  assert.equal(await download.text(), 'sample-object')
  const invalid = await fetch(`${pocOrigin}/poc-api/minio/uploads/upload-1/complete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ part_count: 'not-a-number' }),
  })
  assert.equal(invalid.status, 400)
})

test('binds one READY metadata candidate to one server-authored CR with current authority and replay fencing', async () => {
  const waferUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.QUALITY.wafer_events,PROD)'
  const subjectId = 'bulk-registration-steward'
  const outsiderId = 'bulk-registration-outsider'
  const adminId = 'bulk-registration-admin'
  const serviceToken = 'bulk-registration-service-token-1234567890'
  const { createPocStateStore } = await import('./poc-state-store.mjs?bulk-candidate-cr-test')
  const { createPocServer } = await import('./poc-server.mjs?bulk-candidate-cr-test')
  const stateStore = createPocStateStore()
  const document = normalizeChangeHistoryAccessDocument({
    schema_version: 1,
    active_subject_id: subjectId,
    users: [
      { subject_id: subjectId, role: 'data_steward', active: true, max_security_grade: 'restricted', provider_owner_refs: [] },
      { subject_id: outsiderId, role: 'data_steward', active: true, max_security_grade: 'restricted', provider_owner_refs: [] },
      { subject_id: adminId, role: 'admin', active: true, max_security_grade: 'restricted', provider_owner_refs: [] },
    ],
    systems: [{ system_id: 'quality-system', code: 'QUALITY', name: 'Quality', active: true }],
    system_schema_scopes: [{
      scope_id: 'quality-schema', system_id: 'quality-system', platform: 'postgres',
      database_name: 'MANUFACTURING', schema_name: 'QUALITY', active: true,
    }],
    system_assignments: [
      { system_id: 'quality-system', subject_id: subjectId, responsibility: 'DATA_STEWARD', priority: 1, active: true },
      { system_id: 'quality-system', subject_id: outsiderId, responsibility: 'DATA_STEWARD', priority: 1, active: true },
    ],
  })
  const accessSnapshot = await stateStore.readChangeHistoryAccess()
  await stateStore.writeChangeHistoryAccess({
    expectedAccessVersion: accessSnapshot.access.version,
    expectedCoreVersion: accessSnapshot.core.version,
    accessValue: privateChangeHistoryAccess(document),
    coreValue: changeHistoryAccessCoreProjection(accessSnapshot.core.value, document, 1),
  })
  const policy = approvedDefaultFeatureSecurityPolicy()
  policy.cells.find((cell) => (
    cell.feature === 'registration' && cell.role === 'data_steward' && cell.grade === 'credential'
  )).allow = true
  await stateStore.write('feature-security-policy-v1', policy)
  const mapping = applyTableSystemMappingCommand(null, {
    action: 'ASSIGN', table_ids: [waferUrn], system_ids: ['quality-system'],
    reason: 'Bind the disposable bulk Registration test Table.',
  }, 'bulk-registration-test-admin', '2026-08-18T00:00:00.000Z')
  await stateStore.write('table-system-mappings-v1', mapping.document)
  for (const userId of [subjectId, outsiderId]) {
    await stateStore.applyUserTableGrantCommand({
      subjectId: userId, tableUrns: [waferUrn], action: 'GRANT',
      actorSubjectId: 'bulk-registration-test-admin', changedAt: '2026-08-18T00:00:00.000Z',
    })
  }

  const servers = []
  const originFor = async (actorId) => {
    const server = createPocServer({
      stateStore,
      airflowServiceToken: serviceToken,
      authenticator: {
        async authenticate() { return { subjectId: actorId, tokenHash: 'd'.repeat(64) } },
        assertOrigin() {},
      },
    })
    await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
    servers.push(server)
    return `http://127.0.0.1:${server.address().port}`
  }
  const ownerOrigin = await originFor(subjectId)
  const outsiderOrigin = await originFor(outsiderId)
  const adminOrigin = await originFor(adminId)
  const uploadId = 'bulk-candidate-cr-test'
  const csv = Buffer.from([
    'record_kind,asset_id,platform,database_name,schema_name,table_name,field_path,operation,value_text,controlled_ref',
    `TABLE_DESCRIPTION,"${waferUrn}",postgres,MANUFACTURING,QUALITY,wafer_events,,SET,Governed bulk description,`,
    '',
  ].join('\n'))
  const postCandidate = (origin, preparationId, candidateId, headers, body = {
    title: 'Governed bulk metadata change', reason: 'Create one governed CR from one READY candidate.',
  }) => fetch(`${origin}/poc-api/bulk/uploads/${uploadId}/preparations/${preparationId}/metadata-candidates/${candidateId}/change-request`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(body),
  })
  const providerWritesBefore = requests.filter((request) => request.method !== 'GET'
    && request.path.startsWith('/aspects')).length

  try {
    const part = await fetch(`${ownerOrigin}/poc-api/minio/uploads/${uploadId}/parts/1`, {
      method: 'PUT', headers: { 'Content-Type': 'text/csv' }, body: csv,
    })
    assert.equal(part.status, 200, await part.clone().text())
    const complete = await fetch(`${ownerOrigin}/poc-api/minio/uploads/${uploadId}/complete`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ part_count: 1, display_name: 'metadata.csv', content_type: 'text/csv', target_bucket: 'filefolder' }),
    })
    assert.equal(complete.status, 200, await complete.clone().text())
    const stored = await complete.json()
    const queued = await fetch(`${ownerOrigin}/poc-api/bulk/preparations`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        upload_id: uploadId, content_profile: 'CATALOG_METADATA_ROWS_CSV_V1',
        source_sha256: stored.sha256, object_bucket: stored.bucket, object_key: stored.key,
      }),
    })
    assert.equal(queued.status, 202, await queued.clone().text())
    const preparation = await queued.json()
    const executed = await fetch(`${ownerOrigin}/api/v1/registration/bulk-preparations/execute`, {
      method: 'POST', headers: { Authorization: `Bearer ${serviceToken}` },
    })
    assert.equal(executed.status, 200, await executed.clone().text())
    assert.equal((await executed.json()).state, 'READY')

    const candidatesResponse = await fetch(`${ownerOrigin}/poc-api/bulk/uploads/${uploadId}/preparations/${preparation.id}/metadata-candidates`)
    assert.equal(candidatesResponse.status, 200, await candidatesResponse.clone().text())
    const candidates = await candidatesResponse.json()
    assert.equal(candidates.items.length, 1)
    const candidateId = candidates.items[0].id
    const previewResponse = await fetch(`${ownerOrigin}/poc-api/bulk/uploads/${uploadId}/preparations/${preparation.id}/metadata-candidates/${candidateId}/preview`)
    assert.equal(previewResponse.status, 200, await previewResponse.clone().text())
    const preview = await previewResponse.json()

    assert.equal((await postCandidate(ownerOrigin, preparation.id, candidateId, {
      'Idempotency-Key': 'bulk-candidate-command-1',
    })).status, 428)
    assert.equal((await postCandidate(ownerOrigin, preparation.id, candidateId, {
      'Idempotency-Key': 'bulk-candidate-command-1', 'If-Match': 'not-an-etag',
    })).status, 400)
    assert.equal((await postCandidate(ownerOrigin, preparation.id, candidateId, {
      'Idempotency-Key': 'bulk-candidate-command-1', 'If-Match': `"${'0'.repeat(64)}"`,
    })).status, 412)
    assert.equal((await postCandidate(outsiderOrigin, preparation.id, candidateId, {
      'Idempotency-Key': 'bulk-candidate-command-1', 'If-Match': preview.preview_etag,
    })).status, 404)

    await stateStore.applyUserTableGrantCommand({
      subjectId, tableUrns: [waferUrn], action: 'REMOVE', actorSubjectId: adminId,
      changedAt: '2026-08-18T00:01:00.000Z',
    })
    assert.equal((await postCandidate(ownerOrigin, preparation.id, candidateId, {
      'Idempotency-Key': 'bulk-candidate-command-1', 'If-Match': preview.preview_etag,
    })).status, 404)
    await stateStore.applyUserTableGrantCommand({
      subjectId, tableUrns: [waferUrn], action: 'GRANT', actorSubjectId: adminId,
      changedAt: '2026-08-18T00:02:00.000Z',
    })

    const removedMapping = applyTableSystemMappingCommand(mapping.document, {
      action: 'REMOVE', table_ids: [waferUrn], system_ids: ['quality-system'],
      reason: 'Exercise immediate Registration mapping revocation.',
    }, adminId, '2026-08-18T00:03:00.000Z')
    await stateStore.write('table-system-mappings-v1', removedMapping.document)
    assert.equal((await postCandidate(ownerOrigin, preparation.id, candidateId, {
      'Idempotency-Key': 'bulk-candidate-command-1', 'If-Match': preview.preview_etag,
    })).status, 404)
    const adminWithoutMapping = await postCandidate(adminOrigin, preparation.id, candidateId, {
      'Idempotency-Key': 'bulk-candidate-command-1', 'If-Match': preview.preview_etag,
    })
    assert.equal(adminWithoutMapping.status, 403)
    assert.equal((await adminWithoutMapping.json()).code, 'MAPPING_INTEGRITY_VIOLATION')
    const restoredMapping = applyTableSystemMappingCommand(removedMapping.document, {
      action: 'ASSIGN', table_ids: [waferUrn], system_ids: ['quality-system'],
      reason: 'Restore the Registration test mapping after revocation.',
    }, adminId, '2026-08-18T00:04:00.000Z')
    await stateStore.write('table-system-mappings-v1', restoredMapping.document)

    const createdResponse = await postCandidate(ownerOrigin, preparation.id, candidateId, {
      'Idempotency-Key': 'bulk-candidate-command-1', 'If-Match': preview.preview_etag,
    })
    assert.equal(createdResponse.status, 201, await createdResponse.clone().text())
    const created = await createdResponse.json()
    assert.equal(created.request_type, 'BULK_CATALOG_METADATA')
    const replayResponse = await postCandidate(ownerOrigin, preparation.id, candidateId, {
      'Idempotency-Key': 'bulk-candidate-command-1', 'If-Match': preview.preview_etag,
    })
    assert.equal(replayResponse.status, 200, await replayResponse.clone().text())
    assert.equal((await replayResponse.json()).id, created.id)
    assert.equal((await postCandidate(ownerOrigin, preparation.id, candidateId, {
      'Idempotency-Key': 'bulk-candidate-command-1', 'If-Match': preview.preview_etag,
    }, { title: 'Changed command', reason: 'The same key must not authorize a changed command.' })).status, 409)
    assert.equal((await postCandidate(ownerOrigin, preparation.id, candidateId, {
      'Idempotency-Key': 'bulk-candidate-command-2', 'If-Match': preview.preview_etag,
    })).status, 409)

    const persisted = await stateStore.read('core')
    assert.equal(persisted.value.changeRecords.filter((record) => record.id === created.id).length, 1)
    assert.equal(persisted.value.bulkRegistrationCandidateBindings.length, 1)
    const publicCore = await (await fetch(`${adminOrigin}/poc-api/state/core`)).json()
    assert.equal(Object.hasOwn(publicCore.value, 'bulkRegistrationCandidateBindings'), false)
    assert.equal(requests.filter((request) => request.method !== 'GET'
      && request.path.startsWith('/aspects')).length, providerWritesBefore)
  } finally {
    await Promise.all(servers.map(async (server) => {
      server.closeAllConnections()
      await new Promise((resolvePromise, reject) => server.close((error) => error ? reject(error) : resolvePromise()))
    }))
    await stateStore.close()
  }
})

test('reads a fixed Neo4j graph contract without accepting Cypher from the browser', async () => {
  const graph = await (await fetch(`${pocOrigin}/poc-api/neo4j/graph`)).json()
  assert.equal(graph.nodes.length, 2)
  assert.equal(graph.edges[0].edge_type, 'HAS_INSPECTION')
  const arbitrary = await fetch(`${pocOrigin}/poc-api/neo4j/query`, { method: 'POST', body: '{}' })
  assert.equal(arbitrary.status, 404)
})

test('serves a Knowledge-scoped canonical Table catalog with exact Column identity', async () => {
  const tableUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.QUALITY.wafer_events,PROD)'
  const columnUrn = `urn:li:schemaField:(${tableUrn},wafer_id)`
  forceKnowledgeNonTable = false
  omitKnowledgeColumnUrn = false
  try {
    const searchResponse = await fetch(`${pocOrigin}/poc-api/knowledge/catalog?q=wafer&limit=10`)
    assert.equal(searchResponse.status, 200, await searchResponse.clone().text())
    const search = await searchResponse.json()
    assert.equal(search.items.length, 1)
    assert.equal(search.items[0].id, tableUrn)
    assert.equal(search.items[0].asset_type, 'TABLE')
    assert.equal(search.items[0].classification, 'credential')

    const detailResponse = await fetch(
      `${pocOrigin}/poc-api/knowledge/catalog/asset?urn=${encodeURIComponent(tableUrn)}`,
    )
    assert.equal(detailResponse.status, 200, await detailResponse.clone().text())
    const detail = await detailResponse.json()
    assert.equal(detail.dataset.id, tableUrn)
    assert.equal(detail.dataset.field_metadata[0].field_urn, columnUrn)
    assert.match(detail.dataset.selection_fingerprint, /^[a-f0-9]{64}$/)

    omitKnowledgeColumnUrn = true
    const unresolvedColumnResponse = await fetch(
      `${pocOrigin}/poc-api/knowledge/catalog/asset?urn=${encodeURIComponent(tableUrn)}`,
    )
    assert.equal(unresolvedColumnResponse.status, 200)
    assert.equal((await unresolvedColumnResponse.json()).dataset.field_metadata[0].field_urn, null)
    omitKnowledgeColumnUrn = false

    forceKnowledgeNonTable = true
    const nonTableResponse = await fetch(
      `${pocOrigin}/poc-api/knowledge/catalog/asset?urn=${encodeURIComponent(tableUrn)}`,
    )
    assert.equal(nonTableResponse.status, 404)
    assert.equal((await nonTableResponse.json()).code, 'KNOWLEDGE_CATALOG_TABLE_NOT_FOUND')
  } finally {
    forceKnowledgeNonTable = false
    omitKnowledgeColumnUrn = false
  }
})

test('projects release-pinned DataHub Table and Column identities idempotently and fails closed', async () => {
  const tableUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.QUALITY.wafer_events,PROD)'
  const columnUrn = `urn:li:schemaField:(${tableUrn},wafer_id)`
  const draftId = 'knowledge-k1-disposable-draft'
  const graphId = 'knowledge-k1-disposable-graph'
  const releaseId = 'knowledge-k1-disposable-release'
  const stableElementId = 'knowledge-k1-wafer-class'
  const coreSnapshot = await providerStateStore.read('core')
  const accessSnapshot = await providerStateStore.read('change-history-access-v1')
  const policySnapshot = await providerStateStore.read('feature-security-policy-v1')
  knowledgeNeo4jNodes.clear()
  knowledgeNeo4jEdges.clear()
  omitKnowledgeColumnUrn = false
  forceKnowledgeNonTable = false
  await providerStateStore.write('core', {
    ...(coreSnapshot.value || {}),
    knowledgeDrafts: [{
      id: draftId,
      state: 'PUBLISHED',
      materialized_graph_id: graphId,
      published_studio_release_id: releaseId,
    }],
    knowledgeReleases: [{ id: releaseId, graph_id: graphId, state: 'ACTIVE' }],
    knowledgeDraftBlocks: [[draftId, [{
      id: 'knowledge-k1-tbox-block',
      elements: [{ stable_element_id: stableElementId, kind: 'CLASS' }],
    }]]],
    knowledgeDraftBindings: [[draftId, [{
      id: 'knowledge-k1-binding',
      source_asset_id: tableUrn,
      target_stable_element_id: stableElementId,
      rules: [{ source_field_path: 'wafer_id', target_stable_element_id: stableElementId }],
      tbox_version: 1,
      version: 1,
    }]]],
  })
  const createProjection = () => fetch(`${pocOrigin}/poc-api/knowledge/projections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ draft_id: draftId }),
  })
  try {
    const firstResponse = await createProjection()
    assert.equal(firstResponse.status, 201, await firstResponse.clone().text())
    const first = await firstResponse.json()
    assert.equal(first.contract_version, 'KNOWLEDGE_PROJECTION_RECEIPT_V1')
    assert.equal(first.studio_release_id, releaseId)
    assert.equal(first.node_count, 2)
    assert.equal(first.edge_count, 1)
    assert.equal(first.duplicate_count, 0)
    assert.deepEqual(first.provenance.map((item) => item.external_urn).sort(), [columnUrn, tableUrn].sort())
    assert.ok(first.provenance.every((item) => item.source_type === 'DATAHUB_SYNC'))

    const reloadResponse = await fetch(
      `${pocOrigin}/poc-api/knowledge/projections?draft_id=${encodeURIComponent(draftId)}`,
    )
    assert.equal(reloadResponse.status, 200, await reloadResponse.clone().text())
    const reload = await reloadResponse.json()
    assert.equal(reload.items.length, 1)
    assert.equal(reload.items[0].result_evidence_hash, first.result_evidence_hash)

    const secondResponse = await createProjection()
    assert.equal(secondResponse.status, 201, await secondResponse.clone().text())
    const second = await secondResponse.json()
    assert.equal(second.id, first.id)
    assert.equal(second.result_evidence_hash, first.result_evidence_hash)
    assert.equal(second.duplicate_count, 0)
    assert.deepEqual(
      second.provenance.map((item) => item.knowledge_entity_id).sort(),
      first.provenance.map((item) => item.knowledge_entity_id).sort(),
    )
    assert.equal(knowledgeNeo4jNodes.size, 2)
    assert.equal(knowledgeNeo4jEdges.size, 1)

    const writesBeforeMissingColumn = requests.filter((item) => (
      item.path === '/db/neo4j/tx/commit' && item.body.includes('UNWIND $entities AS entity')
    )).length
    omitKnowledgeColumnUrn = true
    const missingColumnResponse = await createProjection()
    assert.equal(missingColumnResponse.status, 409)
    assert.equal((await missingColumnResponse.json()).code, 'KNOWLEDGE_COLUMN_IDENTITY_UNRESOLVED')
    assert.equal(requests.filter((item) => (
      item.path === '/db/neo4j/tx/commit' && item.body.includes('UNWIND $entities AS entity')
    )).length, writesBeforeMissingColumn)
    omitKnowledgeColumnUrn = false

    forceKnowledgeNonTable = true
    const nonTableResponse = await createProjection()
    assert.equal(nonTableResponse.status, 409)
    assert.equal((await nonTableResponse.json()).code, 'KNOWLEDGE_CURRENT_TABLE_REQUIRED')
    forceKnowledgeNonTable = false

    const allowedPolicy = approvedDefaultFeatureSecurityPolicy()
    allowedPolicy.cells.find((cell) => (
      cell.feature === 'knowledge' && cell.role === 'manager' && cell.grade === 'credential'
    )).allow = true
    await providerStateStore.write('feature-security-policy-v1', allowedPolicy)
    await providerStateStore.write('change-history-access-v1', {
      schema_version: 1,
      active_subject_id: 'provider-test-subject',
      users: [{
        subject_id: 'provider-test-subject',
        role: 'manager',
        active: true,
        max_security_grade: 'restricted',
        provider_owner_refs: [],
      }],
      system_assignments: [],
    })
    const hiddenCatalogResponse = await fetch(`${pocOrigin}/poc-api/knowledge/catalog?q=wafer&limit=10`)
    assert.equal(hiddenCatalogResponse.status, 200)
    assert.equal((await hiddenCatalogResponse.json()).items.length, 0)
    const hiddenDetailResponse = await fetch(
      `${pocOrigin}/poc-api/knowledge/catalog/asset?urn=${encodeURIComponent(tableUrn)}`,
    )
    assert.equal(hiddenDetailResponse.status, 404)
    const writesBeforeDenied = requests.filter((item) => (
      item.path === '/db/neo4j/tx/commit' && item.body.includes('UNWIND $entities AS entity')
    )).length
    const deniedResponse = await createProjection()
    assert.equal(deniedResponse.status, 403)
    assert.equal((await deniedResponse.json()).code, 'KNOWLEDGE_TABLE_FORBIDDEN')
    assert.equal(requests.filter((item) => (
      item.path === '/db/neo4j/tx/commit' && item.body.includes('UNWIND $entities AS entity')
    )).length, writesBeforeDenied)
  } finally {
    omitKnowledgeColumnUrn = false
    forceKnowledgeNonTable = false
    knowledgeNeo4jNodes.clear()
    knowledgeNeo4jEdges.clear()
    await providerStateStore.write('core', coreSnapshot.value || {})
    await providerStateStore.write('change-history-access-v1', accessSnapshot.value)
    await providerStateStore.write(
      'feature-security-policy-v1',
      policySnapshot.value || approvedDefaultFeatureSecurityPolicy(),
    )
  }
})

test('fences durable K5 projection and serves its bounded authorized K6 relation evidence', async () => {
  const tableUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.QUALITY.wafer_events,PROD)'
  const draftId = 'knowledge-k5-durable-draft'
  const graphId = 'knowledge-k5-durable-graph'
  const releaseId = 'knowledge-k5-durable-release'
  const targetId = 'knowledge-k5-wafer-class'
  const assetTargetId = 'knowledge-k5-asset-class'
  const relationTargetId = 'knowledge-k5-owns-relation'
  const subjectId = 'provider-test-subject'
  const coreSnapshot = await providerStateStore.read('core')
  const accessSnapshot = await providerStateStore.read('change-history-access-v1')
  const policySnapshot = await providerStateStore.read('feature-security-policy-v1')
  const originalMethods = Object.fromEntries([
    'readKnowledgeSourceRows', 'readKnowledgeIngestionJob', 'readKnowledgeIngestionJobByIdempotency',
    'listKnowledgeIngestionJobs', 'insertKnowledgeIngestionJob', 'updateKnowledgeIngestionJob',
  ].map((name) => [name, providerStateStore[name]]))
  let sourceRows = [{ row_key: 'wafer-1', row_data: { wafer_id: 'W-001' } }, { row_key: 'wafer-2', row_data: { wafer_id: 'W-002' } }]
    .map((row) => ({ ...row, source_hash: canonicalTestHash(row.row_data) }))
  const jobs = new Map()
  providerStateStore.readKnowledgeSourceRows = async () => structuredClone(sourceRows)
  providerStateStore.readKnowledgeIngestionJob = async (jobId) => structuredClone(jobs.get(jobId) ?? null)
  providerStateStore.readKnowledgeIngestionJobByIdempotency = async (requestedDraftId, requestedReleaseId, key) => (
    structuredClone([...jobs.values()].find((row) => row.draft_id === requestedDraftId
      && row.release_id === requestedReleaseId && row.idempotency_key === key) ?? null)
  )
  providerStateStore.listKnowledgeIngestionJobs = async (requestedDraftId) => structuredClone(
    [...jobs.values()].filter((row) => row.draft_id === requestedDraftId && row.state !== 'READY'),
  )
  providerStateStore.insertKnowledgeIngestionJob = async (job) => {
    const now = new Date().toISOString()
    const row = { ...structuredClone(job), version: 1, created_at: now, updated_at: now }
    jobs.set(row.job_id, row)
    return structuredClone(row)
  }
  providerStateStore.updateKnowledgeIngestionJob = async (jobId, expectedVersion, state, result) => {
    const current = jobs.get(jobId)
    assert.equal(current?.version, expectedVersion)
    const row = { ...current, state, result: structuredClone(result), version: expectedVersion + 1, updated_at: new Date().toISOString() }
    jobs.set(jobId, row)
    return structuredClone(row)
  }
  await providerStateStore.write('core', {
    ...(coreSnapshot.value || {}),
    knowledgeDrafts: [{
      id: draftId, version: 7, state: 'PUBLISHED', materialized_graph_id: graphId,
      published_studio_release_id: releaseId, name: 'K6 bounded relation asset',
      endpoint_alias: 'k6-bounded-relation', classification: 'credential',
      domain_id: 'domain-quality', domain_source_version: '1',
      author_id: 'knowledge-author', published_by: 'knowledge-reviewer',
      created_at: '2026-08-20T00:00:00.000Z', updated_at: '2026-08-20T00:00:00.000Z',
      published_at: '2026-08-20T00:00:00.000Z',
    }],
    knowledgeReleases: [{
      id: releaseId, graph_id: graphId, state: 'ACTIVE', release_no: 1,
      ontology_version_id: 'knowledge-k5-ontology-v3', contract_hash: 'c'.repeat(64),
      published_by: 'knowledge-reviewer', published_at: '2026-08-20T00:00:00.000Z',
    }],
    knowledgeDeliveryPolicies: [{
      id: 'knowledge-k7-policy', graph_id: graphId, api_enabled: false, chat_enabled: true,
      priority: 700, match_any_terms: ['bounded relation'], match_all_terms: ['관계'], excluded_terms: [],
      version: 1, created_by: 'knowledge-reviewer', updated_by: 'knowledge-reviewer',
      created_at: '2026-08-20T00:00:00.000Z', updated_at: '2026-08-20T00:00:00.000Z',
    }],
    knowledgeDraftBlocks: [[draftId, [{
      id: 'knowledge-k5-tbox-block',
      elements: [
        { stable_element_id: targetId, kind: 'CLASS', canonical_name: 'Wafer' },
        { stable_element_id: assetTargetId, kind: 'CLASS', canonical_name: 'Asset' },
        {
          stable_element_id: relationTargetId, kind: 'RELATION', canonical_name: 'OWNS',
          source_stable_element_id: targetId, target_stable_element_id: assetTargetId,
        },
      ],
    }]]],
    knowledgeDraftBindings: [[draftId, [
      {
        id: 'knowledge-k5-binding', source_asset_id: tableUrn,
        target_stable_element_id: targetId, tbox_version: 3, version: 2,
        rules: [{ method: 'SUBJECT_ID', source_field_path: 'wafer_id', target_stable_element_id: targetId }],
      },
      {
        id: 'knowledge-k5-asset-binding', source_asset_id: tableUrn,
        target_stable_element_id: assetTargetId, tbox_version: 3, version: 4,
        rules: [{ method: 'SUBJECT_ID', source_field_path: 'observed_at', target_stable_element_id: assetTargetId }],
      },
    ]]],
  })
  knowledgeNeo4jNodes.clear()
  knowledgeNeo4jEdges.clear()
  forceABoxNeo4jFailure = false
  const previewRequest = () => fetch(`${pocOrigin}/poc-api/knowledge/studio/drafts/${draftId}/abox/previews`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'If-Match': '"7"' },
    body: JSON.stringify({ target_stable_element_id: targetId, sample_limit: 5 }),
  })
  const confirmRequest = (previewJobId, idempotencyKey) => fetch(
    `${pocOrigin}/poc-api/knowledge/studio/drafts/${draftId}/abox/ingestions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'If-Match': '"7"', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ preview_job_id: previewJobId, target_stable_element_id: targetId }),
    },
  )
  const relationPreviewRequest = () => fetch(`${pocOrigin}/poc-api/knowledge/studio/drafts/${draftId}/abox/previews`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'If-Match': '"7"' },
    body: JSON.stringify({ relation_stable_element_id: relationTargetId, sample_limit: 5 }),
  })
  const relationConfirmRequest = (previewJobId, idempotencyKey) => fetch(
    `${pocOrigin}/poc-api/knowledge/studio/drafts/${draftId}/abox/ingestions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'If-Match': '"7"', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ preview_job_id: previewJobId, relation_stable_element_id: relationTargetId }),
    },
  )
  try {
    const previewResponse = await previewRequest()
    assert.equal(previewResponse.status, 200, await previewResponse.clone().text())
    const preview = await previewResponse.json()
    assert.equal(preview.pinned_tbox_version, 3)
    assert.equal(preview.node_count, 2)
    assert.equal(preview.relation_count, 0)
    assert.equal(preview.provenance.length, 2)
    assert.equal(knowledgeNeo4jNodes.size, 0)

    const missingReceipt = await confirmRequest('', 'k5-missing-preview')
    assert.equal(missingReceipt.status, 409)
    assert.equal(knowledgeNeo4jNodes.size, 0)

    const firstResponse = await confirmRequest(preview.job_id, 'k5-confirm-v1')
    assert.equal(firstResponse.status, 201, await firstResponse.clone().text())
    const first = await firstResponse.json()
    assert.equal(first.state, 'SUCCESS')
    assert.equal(first.current_stage, 'DRAFT_CHANGESET_READY')
    assert.equal(first.node_count, 2)
    assert.equal(first.duplicate_count, 0)
    assert.equal(first.pinned_tbox_version, 3)

    const replayResponse = await confirmRequest(preview.job_id, 'k5-confirm-v1')
    assert.equal(replayResponse.status, 200, await replayResponse.clone().text())
    const replay = await replayResponse.json()
    assert.equal(replay.id, first.id)
    assert.equal(replay.result_evidence_hash, first.result_evidence_hash)
    assert.equal(replay.duplicate_count, 0)

    knowledgeNeo4jNodes.clear()
    knowledgeNeo4jEdges.clear()
    sourceRows = [{ row_key: 'relation-1', row_data: { wafer_id: 'W-REL-001', observed_at: '2026-08-20T00:00:00Z' } }]
      .map((row) => ({ ...row, source_hash: canonicalTestHash(row.row_data) }))
    const relationPreviewResponse = await relationPreviewRequest()
    assert.equal(relationPreviewResponse.status, 200, await relationPreviewResponse.clone().text())
    const relationPreview = await relationPreviewResponse.json()
    assert.equal(relationPreview.plan_mode, 'RELATION')
    assert.equal(relationPreview.target_stable_element_id, null)
    assert.equal(relationPreview.relation_stable_element_id, relationTargetId)
    assert.equal(relationPreview.node_count, 2)
    assert.equal(relationPreview.relation_count, 1)
    assert.equal(relationPreview.graph.nodes.length, 2)
    assert.equal(relationPreview.graph.edges.length, 1)
    assert.equal(relationPreview.graph.edges[0].source_node_id, relationPreview.graph.nodes.find((node) => node.stable_element_id === targetId).id)
    assert.equal(relationPreview.graph.edges[0].target_node_id, relationPreview.graph.nodes.find((node) => node.stable_element_id === assetTargetId).id)
    assert.equal(relationPreview.provenance.filter((item) => item.entity_kind === 'RELATION').length, 1)
    assert.equal(knowledgeNeo4jNodes.size, 0)
    assert.equal(knowledgeNeo4jEdges.size, 0)

    const relationResponse = await relationConfirmRequest(relationPreview.job_id, 'k5-relation-confirm-v1')
    assert.equal(relationResponse.status, 201, await relationResponse.clone().text())
    const relationResult = await relationResponse.json()
    assert.equal(relationResult.node_count, 2)
    assert.equal(relationResult.edge_count, 1)
    assert.equal(relationResult.duplicate_count, 0)
    assert.equal(relationResult.provenance.filter((item) => item.entity_kind === 'RELATION').length, 1)
    assert.equal(knowledgeNeo4jNodes.size, 2)
    assert.equal(knowledgeNeo4jEdges.size, 1)

    const relationReplayResponse = await relationConfirmRequest(relationPreview.job_id, 'k5-relation-confirm-v1')
    assert.equal(relationReplayResponse.status, 200, await relationReplayResponse.clone().text())
    const relationReplay = await relationReplayResponse.json()
    assert.equal(relationReplay.id, relationResult.id)
    assert.equal(relationReplay.result_evidence_hash, relationResult.result_evidence_hash)
    assert.equal(relationReplay.edge_count, 1)
    assert.equal(knowledgeNeo4jEdges.size, 1)
    for (const [jobId, job] of jobs) {
      if (job.state === 'PROJECTED' && jobId !== relationResult.id) jobs.delete(jobId)
    }

    const knowledgePolicy = approvedDefaultFeatureSecurityPolicy()
    knowledgePolicy.cells.find((cell) => (
      cell.feature === 'knowledge' && cell.role === 'manager' && cell.grade === 'credential'
    )).allow = true
    await providerStateStore.write('feature-security-policy-v1', knowledgePolicy)
    await providerStateStore.write('change-history-access-v1', {
      schema_version: 1,
      active_subject_id: subjectId,
      users: [{
        subject_id: subjectId, role: 'manager', active: true,
        max_security_grade: 'restricted', provider_owner_refs: [],
      }],
      system_assignments: [],
    })
    await providerStateStore.applyUserTableGrantCommand({
      subjectId, tableUrns: [tableUrn], action: 'GRANT', actorSubjectId: subjectId,
      changedAt: '2026-08-20T01:00:00.000Z',
    })
    const graphsResponse = await fetch(`${pocOrigin}/poc-api/knowledge/graphs`)
    assert.equal(graphsResponse.status, 200, await graphsResponse.clone().text())
    const graphs = await graphsResponse.json()
    assert.deepEqual(new Set(graphs.map((item) => item.id)), new Set([graphId, managedLineageGraphId]))
    assert.equal(graphs.find((item) => item.id === graphId).active_release_id, releaseId)
    const releasesResponse = await fetch(`${pocOrigin}/poc-api/knowledge/graphs/${graphId}/releases`)
    assert.equal(releasesResponse.status, 200, await releasesResponse.clone().text())
    assert.deepEqual((await releasesResponse.json()).map((item) => item.id), [releaseId])
    const snapshotResponse = await fetch(`${pocOrigin}/poc-api/knowledge/graphs/${graphId}/releases/${releaseId}/snapshot`)
    assert.equal(snapshotResponse.status, 200, await snapshotResponse.clone().text())
    const snapshot = await snapshotResponse.json()
    assert.equal(snapshot.nodes.length, 2)
    assert.equal(snapshot.edges.length, 1)
    assert.equal(snapshot.edges[0].source_id, relationPreview.graph.edges[0].source_node_id)
    assert.equal(snapshot.edges[0].target_id, relationPreview.graph.edges[0].target_node_id)
    const visualizationResponse = await fetch(
      `${pocOrigin}/poc-api/knowledge/graphs/${graphId}/releases/${releaseId}/snapshot?maximum_nodes=1&maximum_edges=0&maximum_hops=0&root_node_id=${encodeURIComponent(snapshot.nodes[0].id)}`,
    )
    assert.equal(visualizationResponse.status, 200, await visualizationResponse.clone().text())
    const visualization = await visualizationResponse.json()
    assert.equal(visualization.nodes.length, 1)
    assert.equal(visualization.edges.length, 0)
    assert.equal(visualization.bounds.root_node_id, snapshot.nodes[0].id)
    assert.equal(visualization.bounds.node_limit, 1)
    assert.equal(visualization.bounds.edge_limit, 0)
    assert.equal(visualization.bounds.total_authorized_nodes, 2)
    assert.equal(visualization.bounds.total_authorized_edges, 1)
    assert.equal(visualization.bounds.truncated, true)
    const graphRagResponse = await fetch(`${pocOrigin}/poc-api/knowledge/graphs/${graphId}/releases/${releaseId}/graphrag`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: '두 지식 엔터티의 관계를 설명해줘',
        start_node_id: snapshot.edges[0].source_id, direction: 'OUT', edge_types: [],
        maximum_hops: 1, maximum_nodes: 8,
      }),
    })
    assert.equal(graphRagResponse.status, 200, await graphRagResponse.clone().text())
    const graphRag = await graphRagResponse.json()
    assert.equal(graphRag.answer, 'Live provider answer [1]')
    assert.equal(graphRag.nodes.length, 2)
    assert.equal(graphRag.edges.length, 1)
    assert.equal(graphRag.citations.length, 3)
    assert.equal(graphRag.model_audit.prompt_version, 'knowledge-graphrag-v1')
    assert.ok(graphRag.citations.every((item) => item.source_locator.includes(tableUrn)))
    const mainChatResponse = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: 'bounded relation 지식 관계의 lineage를 설명해줘', mode: 'GRAPH' }),
    })
    assert.equal(mainChatResponse.status, 200, await mainChatResponse.clone().text())
    const mainChat = await mainChatResponse.json()
    assert.equal(mainChat.answer, 'Live provider answer [1]')
    assert.equal(mainChat.route.reason, 'KNOWLEDGE_ASSET_POLICY')
    assert.equal(mainChat.route.intent, 'EXPLICIT_SELECTION')
    assert.equal(mainChat.route.knowledge_scope.graph_id, graphId)
    assert.equal(mainChat.route.knowledge_scope.release_id, releaseId)
    assert.equal(mainChat.route.knowledge_scope.policy_id, 'knowledge-k7-policy')
    assert.equal(mainChat.evidence.filter((item) => item.evidence_type === 'KNOWLEDGE_ASSET_NODE').length, 2)
    assert.equal(mainChat.evidence.filter((item) => item.evidence_type === 'KNOWLEDGE_ASSET_RELATION').length, 1)
    assert.equal(mainChat.evidence.flatMap((item) => item.graph_nodes || []).length, 2)
    assert.equal(mainChat.evidence.flatMap((item) => item.graph_edges || []).length, 1)
    assert.deepEqual(
      mainChat.evidence.flatMap((item) => item.graph_edges || []).map((edge) => [edge.source, edge.target]),
      [[snapshot.edges[0].source_id, snapshot.edges[0].target_id]],
    )
    assert.ok(mainChat.evidence.every((item) => item.source_locator.includes(tableUrn)))
    assert.equal(
      mainChat.workflow.find((step) => step.stage === 'CITATION_VALIDATION')?.detail_code,
      'AUTHORIZED_KNOWLEDGE_ASSET_EVIDENCE_BOUND',
    )
    const unsafeRequest = await fetch(`${pocOrigin}/poc-api/knowledge/graphs/${graphId}/releases/${releaseId}/graphrag`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: '관계를 알려줘', cypher: 'MATCH (n) RETURN n' }),
    })
    assert.equal(unsafeRequest.status, 400)
    await providerStateStore.write('feature-security-policy-v1', approvedDefaultFeatureSecurityPolicy())
    const policyHidden = await fetch(`${pocOrigin}/poc-api/knowledge/graphs`)
    assert.equal(policyHidden.status, 200)
    assert.deepEqual((await policyHidden.json()).map((item) => item.id), [managedLineageGraphId])
    await providerStateStore.write('feature-security-policy-v1', knowledgePolicy)
    await providerStateStore.write('change-history-access-v1', {
      schema_version: 1,
      active_subject_id: subjectId,
      users: [{
        subject_id: subjectId, role: 'manager', active: true,
        max_security_grade: 'normal', provider_owner_refs: [],
      }],
      system_assignments: [],
    })
    const gradeHidden = await fetch(`${pocOrigin}/poc-api/knowledge/graphs/${graphId}/releases/${releaseId}/snapshot`)
    assert.equal(gradeHidden.status, 404)
    await providerStateStore.write('change-history-access-v1', {
      schema_version: 1,
      active_subject_id: subjectId,
      users: [{
        subject_id: subjectId, role: 'manager', active: true,
        max_security_grade: 'restricted', provider_owner_refs: [],
      }],
      system_assignments: [],
    })
    await providerStateStore.applyUserTableGrantCommand({
      subjectId, tableUrns: [tableUrn], action: 'REMOVE', actorSubjectId: subjectId,
      changedAt: '2026-08-20T01:01:00.000Z',
    })
    const hiddenGraphs = await fetch(`${pocOrigin}/poc-api/knowledge/graphs`)
    assert.equal(hiddenGraphs.status, 200)
    assert.deepEqual((await hiddenGraphs.json()).map((item) => item.id), [managedLineageGraphId])
    const hiddenSnapshot = await fetch(`${pocOrigin}/poc-api/knowledge/graphs/${graphId}/releases/${releaseId}/snapshot`)
    assert.equal(hiddenSnapshot.status, 404)
    const hiddenMainChatResponse = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: 'bounded relation 지식 관계의 lineage를 설명해줘', mode: 'GRAPH' }),
    })
    assert.equal(hiddenMainChatResponse.status, 200, await hiddenMainChatResponse.clone().text())
    const hiddenMainChat = await hiddenMainChatResponse.json()
    assert.equal(hiddenMainChat.route.knowledge_scope, undefined)
    assert.notEqual(hiddenMainChat.route.reason, 'KNOWLEDGE_ASSET_POLICY')
    assert.equal(hiddenMainChat.evidence.some((item) => String(item.evidence_type).startsWith('KNOWLEDGE_ASSET_')), false)
    await providerStateStore.write('change-history-access-v1', accessSnapshot.value)
    await providerStateStore.write('feature-security-policy-v1', policySnapshot.value || approvedDefaultFeatureSecurityPolicy())

    knowledgeNeo4jNodes.clear()
    knowledgeNeo4jEdges.clear()

    const stalePreviewResponse = await previewRequest()
    const stalePreview = await stalePreviewResponse.json()
    sourceRows = [{ row_key: 'wafer-3', row_data: { wafer_id: 'W-003' } }]
      .map((row) => ({ ...row, source_hash: canonicalTestHash(row.row_data) }))
    const staleConfirmation = await confirmRequest(stalePreview.job_id, 'k5-confirm-stale')
    assert.equal(staleConfirmation.status, 409)
    assert.equal((await staleConfirmation.json()).code, 'PREVIEW_STALE')

    sourceRows = [{ row_key: 'wafer-bad', row_data: { wafer_id: 'W-BAD' }, source_hash: '0'.repeat(64) }]
    const badHash = await previewRequest()
    assert.equal(badHash.status, 409)
    assert.equal((await badHash.json()).code, 'SOURCE_HASH_MISMATCH')

    sourceRows = [{ row_key: 'wafer-failure', row_data: { wafer_id: 'W-FAIL' } }]
      .map((row) => ({ ...row, source_hash: canonicalTestHash(row.row_data) }))
    const failurePreview = await (await previewRequest()).json()
    forceABoxNeo4jFailure = true
    const failedProjection = await confirmRequest(failurePreview.job_id, 'k5-confirm-failure')
    assert.equal(failedProjection.status, 502)
    forceABoxNeo4jFailure = false
    const authorizedList = await fetch(`${pocOrigin}/poc-api/knowledge/studio/drafts/${draftId}/abox/ingestions`)
    assert.equal(authorizedList.status, 200)
    const items = (await authorizedList.json()).items
    assert.equal(items.filter((item) => item.state === 'FAILED').length, 1)
    assert.equal(items.some((item) => item.error_code === 'KNOWLEDGE_ABOX_PROJECTION_FAILED'), true)
    assert.equal(items.some((item) => item.state === 'READY'), false)

    const allowedPolicy = approvedDefaultFeatureSecurityPolicy()
    allowedPolicy.cells.find((cell) => (
      cell.feature === 'knowledge' && cell.role === 'manager' && cell.grade === 'credential'
    )).allow = true
    await providerStateStore.write('feature-security-policy-v1', allowedPolicy)
    await providerStateStore.write('change-history-access-v1', {
      schema_version: 1,
      active_subject_id: subjectId,
      users: [{ subject_id: subjectId, role: 'manager', active: true, max_security_grade: 'restricted', provider_owner_refs: [] }],
      system_assignments: [],
    })
    const deniedList = await fetch(`${pocOrigin}/poc-api/knowledge/studio/drafts/${draftId}/abox/ingestions`)
    assert.equal(deniedList.status, 403)
    assert.equal((await deniedList.json()).code, 'KNOWLEDGE_TABLE_FORBIDDEN')
    const edgesBeforeDenied = knowledgeNeo4jEdges.size
    const deniedRelationPreview = await relationPreviewRequest()
    assert.equal(deniedRelationPreview.status, 403)
    assert.equal((await deniedRelationPreview.json()).code, 'KNOWLEDGE_TABLE_FORBIDDEN')
    assert.equal(knowledgeNeo4jEdges.size, edgesBeforeDenied)
  } finally {
    forceABoxNeo4jFailure = false
    knowledgeNeo4jNodes.clear()
    knowledgeNeo4jEdges.clear()
    await providerStateStore.applyUserTableGrantCommand({
      subjectId, tableUrns: [tableUrn], action: 'REMOVE', actorSubjectId: subjectId,
      changedAt: '2026-08-20T01:02:00.000Z',
    })
    Object.assign(providerStateStore, originalMethods)
    await providerStateStore.write('core', coreSnapshot.value || {})
    await providerStateStore.write('change-history-access-v1', accessSnapshot.value)
    await providerStateStore.write('feature-security-policy-v1', policySnapshot.value || approvedDefaultFeatureSecurityPolicy())
  }
})

test('enforces request-time Table scope before counts, vector Chat and graph evidence for a non-admin', async () => {
  const waferUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.QUALITY.wafer_events,PROD)'
  const inspectionUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.QUALITY.inspection_results,PROD)'
  const subjectId = 'table-scope-developer'
  const { createPocStateStore } = await import('./poc-state-store.mjs?provider-table-scope-test')
  const { createPocServer } = await import('./poc-server.mjs?provider-table-scope-test')
  const stateStore = createPocStateStore()
  const accessDocument = (maxSecurityGrade) => ({
    schema_version: 1,
    active_subject_id: subjectId,
    users: [{
      subject_id: subjectId,
      role: 'developer',
      active: true,
      max_security_grade: maxSecurityGrade,
      provider_owner_refs: [],
    }],
    systems: [{ system_id: 'quality-system', code: 'QUALITY', name: 'Quality', active: true }],
    system_schema_scopes: [{
      scope_id: 'quality-schema', system_id: 'quality-system', platform: 'postgres',
      database_name: 'MANUFACTURING', schema_name: 'QUALITY', active: true,
    }],
    system_assignments: [{
      system_id: 'quality-system', subject_id: subjectId, responsibility: 'DEVELOPER', priority: 1, active: true,
    }],
  })
  const allowedPolicy = approvedDefaultFeatureSecurityPolicy()
  const credentialFeatures = new Set(['catalog', 'chat', 'monitoring', 'governance'])
  for (const cell of allowedPolicy.cells) {
    if (cell.role === 'developer' && cell.grade === 'credential' && credentialFeatures.has(cell.feature)) {
      cell.allow = true
    }
  }
  const writeAccess = async (maximumGrade) => {
    const document = normalizeChangeHistoryAccessDocument(accessDocument(maximumGrade))
    const snapshot = await stateStore.readChangeHistoryAccess()
    await stateStore.writeChangeHistoryAccess({
      expectedAccessVersion: snapshot.access.version,
      expectedCoreVersion: snapshot.core.version,
      accessValue: privateChangeHistoryAccess(document),
      coreValue: changeHistoryAccessCoreProjection(snapshot.core.value, document, snapshot.access.version + 1),
    })
  }

  await writeAccess('credential')
  await stateStore.write('feature-security-policy-v1', allowedPolicy)
  await stateStore.applyUserTableGrantCommand({
    subjectId,
    tableUrns: [waferUrn],
    action: 'GRANT',
    actorSubjectId: 'test-admin',
    changedAt: '2026-08-17T03:00:00.000Z',
  })
  const server = createPocServer({
    stateStore,
    authenticator: {
      async authenticate() { return { subjectId, tokenHash: 'e'.repeat(64) } },
      assertOrigin() {},
    },
  })
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  assert.equal(typeof address, 'object')
  const origin = `http://127.0.0.1:${address.port}`
  const getJson = async (path) => {
    const response = await fetch(`${origin}${path}`)
    assert.equal(response.status, 200, await response.clone().text())
    return response.json()
  }

  try {
    const catalog = await getJson('/poc-api/datahub/catalog?limit=20')
    assert.equal(catalog.total, 1)
    assert.deepEqual(catalog.items.map((item) => item.id), [waferUrn])
    const exactAllowed = await getJson(`/poc-api/datahub/catalog?limit=20&urn=${encodeURIComponent(waferUrn)}`)
    assert.deepEqual(exactAllowed.items.map((item) => item.id), [waferUrn])
    const exactHidden = await getJson(`/poc-api/datahub/catalog?limit=20&urn=${encodeURIComponent(inspectionUrn)}`)
    assert.equal(exactHidden.total, 0)
    assert.deepEqual(exactHidden.items, [])
    const facets = await getJson('/poc-api/datahub/facets')
    assert.deepEqual(facets.platforms, [{ value: 'postgres', count: 1 }])
    const tree = await getJson('/poc-api/datahub/tree?parent_kind=ROOT')
    assert.equal(tree.items[0].asset_count, 1)
    const dashboard = await getJson('/poc-api/datahub/dashboard')
    assert.equal(dashboard.catalog_asset_count, 1)
    const coverage = await getJson('/poc-api/datahub/profile-coverage')
    assert.equal(coverage.asset_count, 0)
    const vectorStatus = await getJson('/poc-api/datahub/vector-index')
    assert.equal(vectorStatus.indexed, null)
    assert.equal(vectorStatus.refreshed, null)
    assert.equal(vectorStatus.generation, null)

    const hiddenDetail = await fetch(`${origin}/poc-api/datahub/asset?urn=${encodeURIComponent(inspectionUrn)}`)
    assert.equal(hiddenDetail.status, 404)
    const graph = await getJson('/poc-api/neo4j/graph')
    assert.deepEqual(graph, { nodes: [], edges: [] })

    const unauthorizedAuto = await fetch(`${origin}/poc-api/llm/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: 'inspection_results 테이블의 목적과 컬럼을 설명해줘', mode: 'AUTO' }),
    })
    assert.equal(unauthorizedAuto.status, 200, await unauthorizedAuto.clone().text())
    const unauthorizedAutoPayload = await unauthorizedAuto.json()
    assert.ok(unauthorizedAutoPayload.evidence.every((item) => item.id !== inspectionUrn && item.name !== 'inspection_results'))
    assert.doesNotMatch(JSON.stringify(unauthorizedAutoPayload), /MANUFACTURING\.QUALITY\.inspection_results/)

    const deniedPolicy = structuredClone(allowedPolicy)
    deniedPolicy.cells.find((cell) => (
      cell.feature === 'catalog' && cell.role === 'developer' && cell.grade === 'credential'
    )).allow = false
    await stateStore.write('feature-security-policy-v1', deniedPolicy)
    assert.equal((await getJson('/poc-api/datahub/catalog?limit=20')).total, 0)
    await stateStore.write('feature-security-policy-v1', allowedPolicy)
    assert.equal((await getJson('/poc-api/datahub/catalog?limit=20')).total, 1)

    await writeAccess('normal')
    assert.equal((await getJson('/poc-api/datahub/catalog?limit=20')).total, 0)
    await writeAccess('credential')
    assert.equal((await getJson('/poc-api/datahub/catalog?limit=20')).total, 1)

    await stateStore.applyUserTableGrantCommand({
      subjectId,
      tableUrns: [waferUrn],
      action: 'REMOVE',
      actorSubjectId: 'test-admin',
      changedAt: '2026-08-17T03:01:00.000Z',
    })
    assert.equal((await getJson('/poc-api/datahub/catalog?limit=20')).total, 0)
    const requestsBeforeEmptyChat = requests.length
    const emptyChat = await fetch(`${origin}/poc-api/llm/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: '비슷한 inspection_results 테이블을 찾아줘', mode: 'AUTO' }),
    })
    assert.equal(emptyChat.status, 200, await emptyChat.clone().text())
    assert.deepEqual((await emptyChat.json()).evidence, [])
    assert.equal(requests.slice(requestsBeforeEmptyChat).some((request) => {
      if (!request.path.endsWith('/embeddings')) return false
      return JSON.parse(request.body).input === '비슷한 inspection_results 테이블을 찾아줘'
    }), false)
  } finally {
    server.closeAllConnections()
    await new Promise((resolvePromise, reject) => server.close((error) => (
      error ? reject(error) : resolvePromise()
    )))
    await stateStore.close()
  }
})

test('provides a canonical authorized NOT_STARTED apply-report projection without mutating server state', async () => {
  const { createPocStateStore } = await import('./poc-state-store.mjs')
  const { createPocServer } = await import('./poc-server.mjs')
  const {
    normalizeChangeHistoryAccessDocument,
    privateChangeHistoryAccess,
    changeHistoryAccessCoreProjection,
  } = await import('./poc-access-document.mjs')
  const stateStore = createPocStateStore()

  const document = normalizeChangeHistoryAccessDocument({
    schema_version: 1,
    active_subject_id: 'admin',
    policy: {
      version: 1,
      priority_order: 'ASCENDING',
      fallback: ['DATA_STEWARD', 'DEVELOPER', 'DATAHUB_OWNER', 'UNASSIGNED'],
    },
    users: [{
      subject_id: 'admin', role: 'admin', active: true, provider_owner_refs: [],
      username: 'admin', display_name: 'Admin', email: 'admin@test.invalid',
      first_name: 'Admin', last_name: 'Admin', department_id: null, job_function: 'admin',
      max_security_grade: 'restricted',
    }],
    systems: [],
    system_schema_scopes: [],
    system_assignments: [],
  })
  const snapshot = await stateStore.readChangeHistoryAccess()
  await stateStore.writeChangeHistoryAccess({
    expectedAccessVersion: snapshot.access.version,
    expectedCoreVersion: snapshot.core.version,
    accessValue: privateChangeHistoryAccess(document),
    coreValue: changeHistoryAccessCoreProjection(snapshot.core.value, document, snapshot.access.version + 1),
  })

  const currentCore = await stateStore.read('core')
  await stateStore.write('core', {
    ...currentCore.value,
    changeRecords: [{ id: 'test-cr-1', state: 'TESTING', items: [] }],
  })

  const server = createPocServer({
    stateStore,
    authenticator: {
      async authenticate() { return { subjectId: 'admin', tokenHash: 'e'.repeat(64) } },
      assertOrigin() {},
    },
  })
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const origin = `http://127.0.0.1:${server.address().port}`

  try {
    const missing = await fetch(`${origin}/poc-api/change-requests/unknown/apply-report`)
    assert.equal(missing.status, 404)

    const method = await fetch(`${origin}/poc-api/change-requests/test-cr-1/apply-report`, { method: 'POST' })
    assert.equal(method.status, 404)

    const beforeSuccess = await stateStore.read('core')
    const success = await fetch(`${origin}/poc-api/change-requests/test-cr-1/apply-report`)
    assert.equal(success.status, 200)
    assert.equal(success.headers.get('cache-control'), 'private, no-store')

    const payload = await success.json()
    assert.deepEqual(payload, {
      change_request_id: 'test-cr-1',
      job_id: null,
      state: 'NOT_STARTED',
      attempt_count: 0,
      last_error_code: null,
      expected_hash: null,
      observed_hash: null,
      reconciled: false,
      created_at: null,
      updated_at: null,
      items: [],
      attempts: [],
    })
    assert.deepEqual(await stateStore.read('core'), beforeSuccess)
  } finally {
    server.closeAllConnections()
    await new Promise((resolvePromise, reject) => server.close((error) => (
      error ? reject(error) : resolvePromise()
    )))
    await stateStore.close()
  }
})
