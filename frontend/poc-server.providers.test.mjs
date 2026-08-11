/* global Buffer, URL, fetch, process */
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { after, before, test } from 'node:test'

const requests = []
const objects = new Map()
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
    if (url.pathname === '/' || url.pathname === '/config' || url.pathname === '/models' || url.pathname === '/minio/health/live') return sendJson(response, { ok: true })
    if (url.pathname === '/api/v2/monitor/health') return sendJson(response, { metadatabase: { status: 'healthy' } })
    if (/^\/api\/v2\/dags\/[^/]+\/dagRuns$/.test(url.pathname)) return sendJson(response, { state: 'queued' }, 201)
    if (url.pathname === '/embeddings') return sendJson(response, { data: [{ embedding: [0.1, 0.2] }] })
    if (url.pathname === '/rerank') return sendJson(response, { results: [{ index: 0, relevance_score: 0.9 }] })
    if (url.pathname === '/chat/completions') return sendJson(response, { choices: [{ message: { content: 'Live provider answer' } }] })
    if (url.pathname === '/api/graphql') {
      const payload = JSON.parse(body.toString('utf8'))
      if (payload.query.includes('DataRiverPocCatalog')) {
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
          properties: { name: 'wafer_events', description: 'Live DataHub wafer evidence' },
          editableProperties: { description: null },
          browsePathV2: { path: [{ name: 'MANUFACTURING' }, { name: 'QUALITY' }, { name: 'wafer_events' }] },
          domain: null,
          ownership: { owners: [] },
          globalTags: { tags: [] },
          glossaryTerms: { terms: [] },
          schemaMetadata: { fields: [{ fieldPath: 'wafer_id', nativeDataType: 'VARCHAR', description: 'Wafer ID' }] },
        } } })
      }
      return sendJson(response, { data: { dataset: { lineage: { total: 0, relationships: [] } } } })
    }
    if (url.pathname === '/db/neo4j/tx/commit') {
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
    DATAHUB_GMS_URL: providerOrigin,
    DATAHUB_GMS_TOKEN: 'datahub-test-token',
    AIRFLOW_URL: providerOrigin,
    AIRFLOW_USERNAME: 'airflow-test',
    AIRFLOW_PASSWORD: 'airflow-test-password',
    MINIO_URL: providerOrigin,
    MINIO_ACCESS_KEY: 'minio-test-access',
    MINIO_SECRET_KEY: 'minio-test-secret',
    LLM_CHAT_URL: providerOrigin,
    LLM_CHAT_MODEL: 'chat-model',
    LLM_CHAT_TOKEN: 'chat-test-token',
    LLM_EMBEDDING_URL: providerOrigin,
    LLM_EMBEDDING_MODEL: 'embedding-model',
    LLM_EMBEDDING_TOKEN: 'embedding-test-token',
    LLM_RERANKER_URL: providerOrigin,
    LLM_RERANKER_MODEL: 'reranker-model',
    LLM_RERANKER_TOKEN: 'reranker-test-token',
    NEO4J_HTTP_URL: providerOrigin,
    NEO4J_USERNAME: 'neo4j',
    NEO4J_PASSWORD: 'neo4j-test-password',
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
})

test('maps fixed DataHub catalog, detail and lineage contracts', async () => {
  const catalog = await (await fetch(`${pocOrigin}/poc-api/datahub/catalog?q=wafer&limit=5`)).json()
  assert.equal(catalog.items[0].name, 'wafer_events')
  assert.equal(catalog.items[0].database_name, 'MANUFACTURING')
  const urn = encodeURIComponent(catalog.items[0].external_urn)
  const detail = await (await fetch(`${pocOrigin}/poc-api/datahub/asset?urn=${urn}`)).json()
  assert.equal(detail.schema_fields[0].field_path, 'wafer_id')
  const lineage = await (await fetch(`${pocOrigin}/poc-api/datahub/lineage?urn=${urn}`)).json()
  assert.equal(lineage.center_asset_id, catalog.items[0].external_urn)
})

test('runs the fixed embedding, reranking and Chat pipeline', async () => {
  const response = await fetch(`${pocOrigin}/poc-api/llm/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'wafer evidence' }),
  })
  assert.equal(response.status, 200)
  assert.equal((await response.json()).answer, 'Live provider answer')
  for (const path of ['/embeddings', '/rerank', '/chat/completions']) {
    assert.ok(requests.some((request) => request.path === path))
  }
})

test('triggers only the fixed Airflow DAG and proxies a bounded MinIO upload', async () => {
  const dag = await fetch(`${pocOrigin}/poc-api/airflow/dags/datariver_quality_dispatch/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conf: { poc_run_id: 'run-1' } }),
  })
  assert.equal(dag.status, 202)
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
