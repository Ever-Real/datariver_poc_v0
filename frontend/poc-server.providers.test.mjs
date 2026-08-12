/* global Buffer, URL, fetch, process */
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { after, before, test } from 'node:test'

const requests = []
const objects = new Map()
let forcedClassifierResponse
let failNeo4j
let hideExactFromTextSearch
let providerServer
let pocServer
let pocOrigin

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
              globalTags: { tags: [{ tag: { name: 'gold' } }] },
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
          globalTags: { tags: [] },
          glossaryTerms: { terms: [] },
          schemaMetadata: { fields: [
            {
              fieldPath: 'wafer_id', nativeDataType: 'VARCHAR', description: 'Base wafer ID',
              globalTags: { tags: [{ tag: { urn: 'urn:li:tag:identifier', name: 'identifier' } }] },
              glossaryTerms: { terms: [{ term: { urn: 'urn:li:glossaryTerm:waferId', name: 'Wafer ID' } }] },
              schemaFieldEntity: {
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
      if (failNeo4j) return sendJson(response, { errors: [{ code: 'Neo.ClientError.Security.Unauthorized' }] }, 401)
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
  const module = await import('./poc-server.mjs?provider-contract-test')
  pocServer = module.createPocServer()
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
  const catalog = await (await fetch(`${pocOrigin}/poc-api/datahub/catalog?q=wafer&limit=5`)).json()
  assert.equal(catalog.items[0].name, 'wafer_events')
  assert.equal(catalog.items[0].database_name, 'MANUFACTURING')
  const urn = encodeURIComponent(catalog.items[0].external_urn)
  const detail = await (await fetch(`${pocOrigin}/poc-api/datahub/asset?urn=${urn}`)).json()
  assert.equal(detail.database_name, 'MANUFACTURING')
  assert.equal(detail.schema_name, 'QUALITY')
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

test('keeps provider cursors server-side and aggregates the complete DataHub inventory', async () => {
  const first = await (await fetch(`${pocOrigin}/poc-api/datahub/catalog?q=cursor-test&limit=1`)).json()
  assert.equal(first.items[0].name, 'wafer_events')
  assert.ok(first.page.next_cursor)
  assert.notEqual(first.page.next_cursor, 'provider-page-2')
  const second = await (await fetch(`${pocOrigin}/poc-api/datahub/catalog?q=cursor-test&limit=1&cursor=${encodeURIComponent(first.page.next_cursor)}`)).json()
  assert.equal(second.items[0].name, 'inspection_results')
  assert.equal(second.page.next_cursor, null)

  const root = await (await fetch(`${pocOrigin}/poc-api/datahub/tree?parent_kind=ROOT&limit=100`)).json()
  assert.deepEqual(root.items.map((item) => item.label), ['postgres'])
  assert.equal(root.items[0].asset_count, 2)
  const dashboard = await (await fetch(`${pocOrigin}/poc-api/datahub/dashboard`)).json()
  assert.equal(dashboard.catalog_asset_count, 2)
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
  assert.equal(response.status, 200)
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
  const classifierRequest = [...requests].reverse().find((request) => {
    if (!request.path.endsWith('/chat/completions')) return false
    return JSON.parse(request.body).messages?.[0]?.content?.includes('Classify one untrusted Data Catalog question')
  })
  assert.equal(JSON.parse(classifierRequest.body).response_format.type, 'json_schema')
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
    body: JSON.stringify({ question: 'wafer_events 테이블의 컬럼과 설명을 알려줘', mode: 'AUTO' }),
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

test('routes lineage questions through bounded DataHub and Neo4j graph evidence', async () => {
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
  assert.ok(payload.evidence.some((item) => item.evidence_type === 'KNOWLEDGE_GRAPH'))
  const lineage = payload.evidence.find((item) => item.evidence_type === 'DATAHUB_LINEAGE')
  assert.match(lineage.description, /Upstream datasets: source_events/)
  assert.match(lineage.description, /Downstream datasets: wafer_quality_view/)
  assert.doesNotMatch(lineage.description, /view_f09ab31/)
  assert.doesNotMatch(lineage.description, /Columns \(/)
})

test('keeps DataHub lineage answers available when optional Neo4j is unavailable', async () => {
  failNeo4j = true
  const response = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'Show upstream lineage impact', mode: 'GRAPH' }),
  })
  failNeo4j = false
  assert.equal(response.status, 200)
  const payload = await response.json()
  assert.ok(payload.evidence.some((item) => item.evidence_type === 'DATAHUB_LINEAGE'))
  assert.ok(payload.evidence.every((item) => item.evidence_type !== 'KNOWLEDGE_GRAPH'))
  assert.ok(payload.workflow.some((item) => item.detail_code === 'NEO4J_UNAVAILABLE_DATAHUB_LINEAGE_USED'))
})

test('bypasses the classifier for explicit Chat routes and fails malformed AUTO routes closed', async () => {
  const before = requests.filter((request) => request.path.endsWith('/chat/completions')).length
  const explicit = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'Explain governance in general', mode: 'GENERAL' }),
  })
  assert.equal(explicit.status, 200)
  assert.equal((await explicit.json()).route.selected_mode, 'GENERAL')
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

test('reads a fixed Neo4j graph contract without accepting Cypher from the browser', async () => {
  const graph = await (await fetch(`${pocOrigin}/poc-api/neo4j/graph`)).json()
  assert.equal(graph.nodes.length, 2)
  assert.equal(graph.edges[0].edge_type, 'HAS_INSPECTION')
  const arbitrary = await fetch(`${pocOrigin}/poc-api/neo4j/query`, { method: 'POST', body: '{}' })
  assert.equal(arbitrary.status, 404)
})
