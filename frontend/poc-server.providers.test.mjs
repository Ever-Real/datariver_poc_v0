/* global Buffer, URL, fetch, process, structuredClone */
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { after, before, test } from 'node:test'
import {
  changeHistoryAccessCoreProjection,
  normalizeChangeHistoryAccessDocument,
  privateChangeHistoryAccess,
} from './poc-access-document.mjs'
import { approvedDefaultFeatureSecurityPolicy } from './poc-feature-security-policy.mjs'
import { applyTableSystemMappingCommand } from './poc-table-system-mappings.mjs'

const requests = []
const objects = new Map()
let forcedClassifierResponse
let hideExactFromTextSearch
let omitKnowledgeColumnUrn
let forceKnowledgeNonTable
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
      if (systemPrompt.includes('Classify one untrusted Data Catalog question')) {
        const question = payload.messages?.[1]?.content || ''
        const graph = /lineage|upstream|impact/i.test(question)
        const exact = /wafer_events/i.test(question)
        const decision = graph
          ? {
              mode: 'GRAPH', confidence: 0.98, intent: 'LINEAGE',
              entity_resolution_required: true, graph_traversal_required: true,
              semantic_retrieval_required: false, fallback_mode: 'VECTOR',
            }
          : exact
            ? {
                mode: 'VECTOR', confidence: 0.99, intent: 'EXACT_METADATA',
                entity_resolution_required: true, graph_traversal_required: false,
                semantic_retrieval_required: false, fallback_mode: 'GENERAL',
              }
            : {
                mode: 'VECTOR', confidence: 0.92, intent: 'SEMANTIC_DISCOVERY',
                entity_resolution_required: false, graph_traversal_required: false,
                semantic_retrieval_required: true, fallback_mode: 'GENERAL',
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
            { fieldPath: 'observed_at', nativeDataType: 'TIMESTAMP', description: 'Observed timestamp' },
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
      if (query.includes('UNWIND $entities AS entity')) {
        for (const entity of parameters.entities || []) knowledgeNeo4jNodes.set(entity.id, structuredClone(entity))
        return sendJson(response, { errors: [], results: [{ data: [{ row: [(parameters.entities || []).length] }] }] })
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
          node.knowledge_graph_id === parameters.graphId
          && node.knowledge_release_id === parameters.studioReleaseId
        ))
        return sendJson(response, { errors: [], results: [{ data: [{ row: [nodes.length, 0] }] }] })
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
  })
  const { createPocStateStore } = await import('./poc-state-store.mjs?provider-contract-test')
  const module = await import('./poc-server.mjs?provider-contract-test')
  providerStateStore = createPocStateStore()
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
  assert.equal(detail.created_at, '2024-01-02T03:04:05.000Z')
  const detailQuery = [...requests].reverse().find((request) => (
    request.path === '/api/graphql' && request.body.includes('DataRiverPocAsset')
  ))
  assert.match(detailQuery.body, /datasetProfiles\(limit: 10\)/)
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
  const inventoryRequest = requests.find((request) => (
    request.path === '/api/graphql' && request.body.includes('DataRiverPocCatalogEmbeddingInventory')
  ))
  assert.ok(inventoryRequest, 'the fixed DataHub inventory query must be observed')
  assert.equal(
    Object.hasOwn(JSON.parse(inventoryRequest.body).variables.input, 'sortInput'),
    false,
    'DataHub v1.6 supplies deterministic score/URN scroll ordering when sortInput is omitted',
  )

  const root = await (await fetch(`${pocOrigin}/poc-api/datahub/tree?parent_kind=ROOT&limit=100`)).json()
  assert.deepEqual(root.items.map((item) => item.label), ['postgres'])
  assert.equal(root.items[0].asset_count, 2)
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
    return JSON.parse(request.body).messages?.[0]?.content?.includes('Classify one untrusted Data Catalog question')
  })
  const classifierPayload = JSON.parse(classifierRequest.body)
  assert.equal(classifierPayload.response_format.type, 'json_schema')
  assert.equal(classifierPayload.reasoning_effort, 'none')
  assert.deepEqual(classifierPayload.reasoning, { effort: 'none' })
  assert.equal(classifierPayload.max_tokens, 320)
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
  assert.equal(requests.filter((request) => request.path.endsWith('/chat/completions')).length, completionsBefore)
})

test('streams real Chat workflow stages before the final provider result', async () => {
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
  assert.ok(stream.indexOf('"stage":"ROUTING","status":"IN_PROGRESS"') < stream.indexOf('event: result'))
  assert.match(frames.at(-1) || '', /^event: result\ndata: /)
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
    && JSON.parse(request.body).messages?.[0]?.content?.includes('Classify one untrusted Data Catalog question')).length
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
    && JSON.parse(request.body).messages?.[0]?.content?.includes('Classify one untrusted Data Catalog question')).length
  assert.equal(classifiersAfter, classifiersBefore)
})

test('resolves an exact table name and composes detailed DataHub metadata evidence', async () => {
  const classifiersBefore = requests.filter((request) => request.path.endsWith('/chat/completions')
    && JSON.parse(request.body).messages?.[0]?.content?.includes('Classify one untrusted Data Catalog question')).length
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
    return !JSON.parse(request.body).messages?.[0]?.content?.includes('Classify one untrusted Data Catalog question')
  })
  assert.equal(JSON.parse(composer.body).max_tokens, 896)
  assert.doesNotMatch(JSON.parse(composer.body).messages[0].content, /concisely/i)
  const classifiersAfter = requests.filter((request) => request.path.endsWith('/chat/completions')
    && JSON.parse(request.body).messages?.[0]?.content?.includes('Classify one untrusted Data Catalog question')).length
  assert.equal(classifiersAfter, classifiersBefore)
})

test('routes an exact Korean relationship question deterministically before the classifier', async () => {
  const classifiersBefore = requests.filter((request) => request.path.endsWith('/chat/completions')
    && JSON.parse(request.body).messages?.[0]?.content?.includes('Classify one untrusted Data Catalog question')).length
  const completionsBefore = requests.filter((request) => request.path.endsWith('/chat/completions')).length
  const response = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'wafer_events 연결 관계를 알려줘', mode: 'AUTO' }),
  })
  assert.equal(response.status, 200)
  const payload = await response.json()
  assert.equal(payload.route.selected_mode, 'GRAPH')
  assert.equal(payload.route.intent, 'RELATIONSHIP')
  assert.ok(payload.evidence.some((item) => item.evidence_type === 'DATAHUB_LINEAGE'))
  assert.match(payload.answer, /source_events/)
  assert.match(payload.answer, /wafer_quality_view/)
  const classifiersAfter = requests.filter((request) => request.path.endsWith('/chat/completions')
    && JSON.parse(request.body).messages?.[0]?.content?.includes('Classify one untrusted Data Catalog question')).length
  assert.equal(classifiersAfter, classifiersBefore)
  assert.equal(requests.filter((request) => request.path.endsWith('/chat/completions')).length, completionsBefore)
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
    const lineage = payload.evidence.find((item) => item.evidence_type === 'DATAHUB_LINEAGE')
    assert.equal(lineage.entity_resolution_method, 'CATALOG_EXACT')
    assert.doesNotMatch(payload.answer, /가장 가까운 후보/)
  } finally {
    hideExactFromTextSearch = false
  }
})

test('routes lineage questions through DataHub lineage only without generic Neo4j evidence', async () => {
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
  assert.equal(payload.route.reason, 'GRAPH_INTENT')
  assert.ok(payload.evidence.some((item) => item.evidence_type === 'DATAHUB_LINEAGE'))
  assert.ok(payload.evidence.every((item) => item.evidence_type !== 'KNOWLEDGE_GRAPH'))
  const lineage = payload.evidence.find((item) => item.evidence_type === 'DATAHUB_LINEAGE')
  assert.match(lineage.description, /Upstream datasets: source_events/)
  assert.match(lineage.description, /Downstream datasets: wafer_quality_view/)
  assert.doesNotMatch(lineage.description, /view_f09ab31/)
  assert.doesNotMatch(lineage.description, /Columns \(/)
  assert.ok(payload.workflow.some((item) => item.detail_code === 'DATAHUB_LINEAGE_EVIDENCE_BOUND'))
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
