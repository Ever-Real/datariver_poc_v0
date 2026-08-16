/* global Buffer, URL, clearTimeout, fetch, performance, process, setTimeout, structuredClone */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { createServer } from 'node:http'
import { test } from 'node:test'

function entity(name, description) {
  return {
    urn: `urn:li:dataset:(urn:li:dataPlatform:postgres,MANUFACTURING.QUALITY.${name},PROD)`,
    type: 'DATASET',
    name,
    subTypes: { typeNames: ['Table'] },
    platform: { urn: 'urn:li:dataPlatform:postgres', name: 'postgres' },
    properties: { name, description, created: 1_704_164_645_000, customProperties: [] },
    editableProperties: { description: null },
    browsePathV2: { path: [{ name: 'MANUFACTURING' }, { name: 'QUALITY' }, { name }] },
    domain: null,
    ownership: { owners: [] },
    tags: { tags: [] },
    glossaryTerms: { terms: [] },
    schemaMetadata: { fields: [{ fieldPath: `${name}_id`, type: 'STRING' }] },
    editableSchemaMetadata: { editableSchemaFieldInfo: [] },
    latestFullTableProfile: [],
  }
}

async function listen(server) {
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  assert.equal(typeof address, 'object')
  return `http://127.0.0.1:${address.port}`
}

async function close(server) {
  server.closeAllConnections()
  await new Promise((resolvePromise, reject) => server.close((error) => (
    error ? reject(error) : resolvePromise()
  )))
}

function authenticatedPocServer(module, options) {
  const stateStore = options.stateStore
  stateStore.readChangeHistoryAccess ??= async () => ({
    access: {
      version: 1,
      value: {
        schema_version: 1,
        active_subject_id: 'catalog-performance-subject',
        users: [{
          subject_id: 'catalog-performance-subject', role: 'admin', active: true, provider_owner_refs: [],
        }],
        system_assignments: [],
      },
    },
    core: { version: 0, value: null },
  })
  return module.createPocServer({
    ...options,
    authenticator: {
      async authenticate() {
        return { subjectId: 'catalog-performance-subject', tokenHash: 'f'.repeat(64) }
      },
      assertOrigin() {},
    },
  })
}

async function waitFor(predicate, message) {
  const deadline = Date.now() + 2_000
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error(message)
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 10))
  }
}

function configureProviderEnvironment(providerOrigin, { embedding = false, chat = false } = {}) {
  Object.assign(process.env, {
    POC_ENV_FILE: 'poc-catalog-performance.test.env.missing',
    POC_DATABASE_URL: '',
    POC_POSTGRES_HOST: '',
    POC_REDIS_URL: '',
    POC_SERVER_HOST: '127.0.0.1',
    POC_SERVER_PORT: '0',
    POC_PUBLIC_ORIGIN: 'http://127.0.0.1:39080',
    POC_CHANGE_HISTORY_SCHEDULER_ENABLED: 'false',
    DATAHUB_GMS_URL: providerOrigin,
    DATAHUB_GMS_TOKEN: 'performance-test-token',
    LLM_EMBEDDING_URL: embedding ? `${providerOrigin}/embeddings` : '',
    LLM_EMBEDDING_MODEL: embedding ? 'performance-embedding-model' : '',
    LLM_EMBEDDING_TOKEN: embedding ? 'performance-embedding-token' : '',
    LLM_CHAT_URL: chat ? `${providerOrigin}/chat/completions` : '',
    LLM_CHAT_MODEL: chat ? 'performance-chat-model' : '',
    LLM_CHAT_TOKEN: chat ? 'performance-chat-token' : '',
    LLM_RERANKER_URL: '',
    LLM_RERANKER_MODEL: '',
    LLM_RERANKER_TOKEN: '',
  })
}

function reconciliationStateStore() {
  let persisted
  let writes = 0
  let historyWrites = 0
  const activeGenerations = new Map()
  const embeddingRows = new Map()
  return {
    stateStore: {
      configured: { postgres: true, redis: true },
      async read() { return { value: persisted ? structuredClone(persisted) : null, version: writes } },
      async write(_scope, value) {
        persisted = structuredClone(value)
        writes += 1
        return writes
      },
      async cacheGet() { return undefined },
      async cacheSet() {},
      async cacheDelete() {},
      async catalogEmbeddingActiveGeneration(bindingHash) { return activeGenerations.get(bindingHash) },
      async catalogEmbeddingHashes(bindingHash) {
        return new Map([...embeddingRows.values()]
          .filter((row) => row.bindingHash === bindingHash)
          .map((row) => [row.assetUrn, row.sourceHash]))
      },
      async replaceCatalogEmbeddingGeneration(bindingHash, sourceScope, sourceGeneration, replacements, assetUrns) {
        for (const [key, row] of embeddingRows) {
          if (row.bindingHash === bindingHash && row.sourceScope === sourceScope) embeddingRows.delete(key)
        }
        for (const row of replacements) {
          if (assetUrns.includes(row.assetUrn)) {
            embeddingRows.set(`${bindingHash}:${row.assetUrn}`, { ...structuredClone(row), sourceScope })
          }
        }
        activeGenerations.set(bindingHash, sourceGeneration)
      },
      async searchCatalogEmbeddings(bindingHash, sourceScope, sourceGeneration, _queryVector, limit) {
        return [...embeddingRows.values()]
          .filter((row) => row.bindingHash === bindingHash
            && row.sourceScope === sourceScope && row.sourceGeneration === sourceGeneration)
          .sort((left, right) => left.assetUrn.localeCompare(right.assetUrn))
          .slice(0, limit)
          .map((row) => ({ ...structuredClone(row), similarity: 1 }))
      },
      async appendChangeHistory() { historyWrites += 1 },
    },
    markStale() {
      persisted.observed_at = new Date(Date.now() - 16 * 60 * 1_000).toISOString()
    },
    observation() {
      return { persisted: structuredClone(persisted), writes, historyWrites }
    },
  }
}

function lifecycleStateStore(initialProjection) {
  let persisted = initialProjection ? structuredClone(initialProjection) : undefined
  let closed = false
  let closeCalls = 0
  let postCloseUses = 0
  let writes = 0
  let embeddingReplacements = 0
  const guard = () => {
    if (closed) postCloseUses += 1
  }
  return {
    stateStore: {
      configured: { postgres: true, redis: true },
      async read() {
        guard()
        return { value: persisted ? structuredClone(persisted) : null, version: writes }
      },
      async write(_scope, value) {
        guard()
        persisted = structuredClone(value)
        writes += 1
        return writes
      },
      async cacheGet() { guard(); return undefined },
      async cacheSet() { guard() },
      async cacheDelete() { guard() },
      async catalogEmbeddingActiveGeneration() { guard(); return undefined },
      async catalogEmbeddingHashes() { guard(); return new Map() },
      async replaceCatalogEmbeddingGeneration() {
        guard()
        embeddingReplacements += 1
      },
      async readLocalCredential() { guard(); return null },
      async recordLocalLoginFailure() { guard(); return false },
      async recordLocalLoginSuccess() { guard(); return false },
      async createLocalSession() { guard() },
      async readLocalSession() { guard(); return null },
      async revokeLocalSession() { guard(); return false },
      async runChangeHistoryScheduler(_options, task) {
        guard()
        return task()
      },
      async close() {
        closeCalls += 1
        closed = true
      },
    },
    observation() {
      return {
        persisted: persisted ? structuredClone(persisted) : undefined,
        closed,
        closeCalls,
        postCloseUses,
        writes,
        embeddingReplacements,
      }
    },
  }
}

test('serves PostgreSQL last-good Catalog state without a synchronous provider scan', async () => {
  let providerRequests = 0
  let failSecondPage = false
  let terminalPageIncomplete = false
  let providerAssets = [
    entity('inspection_results', 'Inspection evidence'),
    entity('wafer_events', 'Wafer evidence'),
  ]
  const provider = createServer(async (request, response) => {
    const chunks = []
    for await (const chunk of request) chunks.push(chunk)
    const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    providerRequests += 1
    const secondPage = body.variables?.input?.scrollId === 'page-2'
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 25))
    if (secondPage && failSecondPage) {
      response.writeHead(502, { 'Content-Type': 'application/json' })
      return response.end(JSON.stringify({ error: 'bounded provider failure' }))
    }
    const pageAssets = secondPage ? providerAssets.slice(1) : providerAssets.slice(0, 1)
    const payload = { data: { scrollAcrossEntities: {
      count: pageAssets.length,
      total: providerAssets.length,
      nextScrollId: !terminalPageIncomplete && !secondPage && providerAssets.length > 1 ? 'page-2' : null,
      searchResults: pageAssets.map((item) => ({ entity: item })),
    } } }
    response.writeHead(200, { 'Content-Type': 'application/json' })
    return response.end(JSON.stringify(payload))
  })
  const providerOrigin = await listen(provider)

  let persisted
  let writes = 0
  const stateStore = {
    configured: { postgres: true, redis: true },
    async read() { return { value: persisted ? structuredClone(persisted) : null, version: writes } },
    async write(_scope, value) {
      persisted = structuredClone(value)
      writes += 1
      return writes
    },
    async cacheGet() { throw new Error('Redis unavailable') },
    async cacheSet() { throw new Error('Redis unavailable') },
    async cacheDelete() {},
  }

  Object.assign(process.env, {
    POC_ENV_FILE: 'poc-catalog-performance.test.env.missing',
    POC_DATABASE_URL: '',
    POC_POSTGRES_HOST: '',
    POC_REDIS_URL: '',
    DATAHUB_GMS_URL: providerOrigin,
    DATAHUB_GMS_TOKEN: 'performance-test-token',
  })

  const coldModule = await import('./poc-server.mjs?catalog-performance-cold')
  const coldServer = authenticatedPocServer(coldModule, { stateStore })
  const coldOrigin = await listen(coldServer)
  const coldStartedAt = performance.now()
  const coldResponse = await fetch(`${coldOrigin}/poc-api/datahub/catalog?q=evidence&limit=20`)
  const coldMilliseconds = performance.now() - coldStartedAt
  assert.equal(coldResponse.status, 503)
  assert.ok(coldMilliseconds < 100, `cold request blocked for ${coldMilliseconds}ms`)
  await waitFor(() => writes === 1, 'background Catalog refresh did not complete')
  assert.equal(providerRequests, 2)
  await close(coldServer)

  providerRequests = 0
  const warmModule = await import('./poc-server.mjs?catalog-performance-warm')
  const warmServer = authenticatedPocServer(warmModule, { stateStore })
  const warmOrigin = await listen(warmServer)
  const warmStartedAt = performance.now()
  const warmResponse = await fetch(`${warmOrigin}/poc-api/datahub/catalog?q=evidence&limit=20`)
  const warmText = await warmResponse.text()
  const warmMilliseconds = performance.now() - warmStartedAt
  const parseStartedAt = performance.now()
  const warmPayload = JSON.parse(warmText)
  const parseMilliseconds = performance.now() - parseStartedAt
  assert.equal(warmResponse.status, 200)
  assert.deepEqual(warmPayload.items.map((item) => item.name), ['inspection_results', 'wafer_events'])
  assert.equal(warmPayload.meta.projection_source, 'POSTGRES_CURRENT_PROJECTION')
  assert.equal(providerRequests, 0)
  await close(warmServer)

  persisted.observed_at = new Date(Date.now() - 16 * 60 * 1_000).toISOString()
  failSecondPage = true
  providerRequests = 0
  const failedModule = await import('./poc-server.mjs?catalog-performance-failed-refresh')
  const failedServer = authenticatedPocServer(failedModule, { stateStore })
  const failedOrigin = await listen(failedServer)
  const failedResponse = await fetch(`${failedOrigin}/poc-api/datahub/catalog?q=evidence&limit=20`)
  assert.equal(failedResponse.status, 200)
  assert.equal((await failedResponse.json()).items.length, 2)
  await waitFor(() => providerRequests === 2, 'partial provider failure was not observed')
  await new Promise((resolvePromise) => setTimeout(resolvePromise, 50))
  assert.equal(writes, 1, 'a partial refresh must not replace the last-good projection')
  const lastGood = await (await fetch(`${failedOrigin}/poc-api/datahub/catalog?q=evidence&limit=20`)).json()
  assert.equal(lastGood.meta.refresh_state, 'DEGRADED_LAST_GOOD')
  await close(failedServer)

  failSecondPage = false
  providerAssets = [providerAssets[1]]
  providerRequests = 0
  const refreshModule = await import('./poc-server.mjs?catalog-performance-generation-refresh')
  const refreshServer = authenticatedPocServer(refreshModule, { stateStore })
  const refreshOrigin = await listen(refreshServer)
  assert.equal((await (await fetch(`${refreshOrigin}/poc-api/datahub/catalog?q=evidence&limit=20`)).json()).items.length, 2)
  await waitFor(() => writes === 2, 'replacement Catalog generation did not commit')
  assert.equal(providerRequests, 1)
  await close(refreshServer)

  providerRequests = 0
  const replacementModule = await import('./poc-server.mjs?catalog-performance-replacement')
  const replacementServer = authenticatedPocServer(replacementModule, { stateStore })
  const replacementOrigin = await listen(replacementServer)
  const replacement = await (await fetch(`${replacementOrigin}/poc-api/datahub/catalog?q=wafer&limit=20`)).json()
  assert.deepEqual(replacement.items.map((item) => item.name), ['wafer_events'])
  assert.equal(providerRequests, 0)
  await close(replacementServer)

  const currentItem = structuredClone(persisted.items[0])
  persisted.observed_at = new Date(Date.now() - 16 * 60 * 1_000).toISOString()
  providerAssets = [
    entity('terminal_first', 'First of an incomplete terminal page'),
    entity('terminal_missing', 'Missing from the terminal page'),
  ]
  terminalPageIncomplete = true
  providerRequests = 0
  const incompleteModule = await import('./poc-server.mjs?catalog-performance-incomplete-terminal')
  const incompleteServer = authenticatedPocServer(incompleteModule, { stateStore })
  const incompleteOrigin = await listen(incompleteServer)
  assert.equal((await fetch(`${incompleteOrigin}/poc-api/datahub/catalog?limit=20`)).status, 200)
  await waitFor(() => providerRequests === 1, 'incomplete terminal provider page was not observed')
  await new Promise((resolvePromise) => setTimeout(resolvePromise, 50))
  assert.equal(writes, 2, 'an incomplete terminal page must not replace the last-good projection')
  assert.deepEqual(persisted.items.map((item) => item.name), ['wafer_events'])
  await close(incompleteServer)

  terminalPageIncomplete = false
  providerAssets = []
  providerRequests = 0
  const zeroModule = await import('./poc-server.mjs?catalog-performance-valid-zero-refresh')
  const zeroServer = authenticatedPocServer(zeroModule, { stateStore })
  const zeroOrigin = await listen(zeroServer)
  assert.equal((await fetch(`${zeroOrigin}/poc-api/datahub/catalog?limit=20`)).status, 200)
  await waitFor(() => writes === 3, 'valid empty inventory did not commit')
  assert.equal(providerRequests, 1)
  await close(zeroServer)

  providerRequests = 0
  const zeroStoredModule = await import('./poc-server.mjs?catalog-performance-valid-zero-stored')
  const zeroStoredServer = authenticatedPocServer(zeroStoredModule, { stateStore })
  const zeroStoredOrigin = await listen(zeroStoredServer)
  const zeroStored = await (await fetch(`${zeroStoredOrigin}/poc-api/datahub/catalog?limit=20`)).json()
  assert.deepEqual(zeroStored.items, [])
  assert.equal(providerRequests, 0)
  await close(zeroStoredServer)

  const redisProjection = structuredClone(persisted)
  redisProjection.source_generation = 'redis-stale-generation'
  redisProjection.items = [{ ...currentItem, name: 'redis_old' }]
  redisProjection.observed_at = new Date().toISOString()
  const postgresProjection = structuredClone(redisProjection)
  postgresProjection.source_generation = 'postgres-current-generation'
  postgresProjection.items = [{ ...currentItem, name: 'postgres_new' }]
  let postgresReads = 0
  let redisReads = 0
  const splitSuccessStore = {
    configured: { postgres: true, redis: true },
    async read() {
      postgresReads += 1
      return { value: structuredClone(postgresProjection), version: 2 }
    },
    async write() { throw new Error('a fresh valid projection must not refresh synchronously') },
    async cacheGet() {
      redisReads += 1
      return structuredClone(redisProjection)
    },
    async cacheSet() {},
    async cacheDelete() {},
  }
  const splitModule = await import('./poc-server.mjs?catalog-performance-postgres-authoritative')
  const splitServer = authenticatedPocServer(splitModule, { stateStore: splitSuccessStore })
  const splitOrigin = await listen(splitServer)
  const splitPayload = await (await fetch(`${splitOrigin}/poc-api/datahub/catalog?limit=20`)).json()
  assert.deepEqual(splitPayload.items.map((item) => item.name), ['postgres_new'])
  assert.equal(postgresReads, 1)
  assert.equal(redisReads, 0, 'valid Redis must not mask the authoritative PostgreSQL projection')
  await close(splitServer)

  let brokenRedisReads = 0
  const readablePostgresStore = {
    configured: { postgres: true, redis: true },
    async read() { return { value: structuredClone(postgresProjection), version: 2 } },
    async write() { throw new Error('a fresh valid projection must not refresh synchronously') },
    async cacheGet() {
      brokenRedisReads += 1
      throw new Error('Redis unavailable')
    },
    async cacheSet() {},
    async cacheDelete() {},
  }
  const readablePostgresModule = await import('./poc-server.mjs?catalog-performance-readable-pg-broken-redis')
  const readablePostgresServer = authenticatedPocServer(readablePostgresModule, { stateStore: readablePostgresStore })
  const readablePostgresOrigin = await listen(readablePostgresServer)
  const readablePostgresPayload = await (
    await fetch(`${readablePostgresOrigin}/poc-api/datahub/catalog?limit=20`)
  ).json()
  assert.deepEqual(readablePostgresPayload.items.map((item) => item.name), ['postgres_new'])
  assert.equal(brokenRedisReads, 0, 'a broken Redis adapter must not hide readable PostgreSQL')
  await close(readablePostgresServer)

  const failureResponse = async (suffix, failingStore) => {
    const failureModule = await import(`./poc-server.mjs?catalog-performance-${suffix}`)
    const failureServer = authenticatedPocServer(failureModule, { stateStore: failingStore })
    const failureOrigin = await listen(failureServer)
    const response = await fetch(`${failureOrigin}/poc-api/datahub/catalog?limit=20`)
    assert.equal(response.status, 503)
    await close(failureServer)
  }
  let invalidPostgresRedisReads = 0
  await failureResponse('invalid-pg-not-masked-by-redis', {
    configured: { postgres: true, redis: true },
    async read() { return { value: { projection_version: 1, items: [] }, version: 1 } },
    async write() { throw new Error('bounded refresh write failure') },
    async cacheGet() {
      invalidPostgresRedisReads += 1
      return structuredClone(redisProjection)
    },
    async cacheSet() {},
    async cacheDelete() {},
  })
  assert.equal(invalidPostgresRedisReads, 0, 'invalid authoritative data must fail safe without Redis masking')

  await failureResponse('invalid-redis-fallback', {
    configured: { postgres: true, redis: true },
    async read() { throw new Error('PostgreSQL unavailable') },
    async write() { throw new Error('bounded refresh write failure') },
    async cacheGet() { return { projection_version: 1, items: [] } },
    async cacheSet() {},
    async cacheDelete() {},
  })

  await failureResponse('both-state-providers-unavailable', {
    configured: { postgres: true, redis: true },
    async read() { throw new Error('PostgreSQL unavailable') },
    async write() { throw new Error('bounded refresh write failure') },
    async cacheGet() { throw new Error('Redis unavailable') },
    async cacheSet() {},
    async cacheDelete() {},
  })
  await close(provider)

  process.stdout.write(`${JSON.stringify({
    cold_status: coldResponse.status,
    cold_ms: Number(coldMilliseconds.toFixed(3)),
    cold_provider_pages: 2,
    warm_status: warmResponse.status,
    warm_ms: Number(warmMilliseconds.toFixed(3)),
    warm_provider_pages: 0,
    warm_payload_bytes: Buffer.byteLength(warmText),
    warm_parse_ms: Number(parseMilliseconds.toFixed(3)),
    partial_failure_preserved_items: 2,
    terminal_incomplete_preserved_items: 1,
    valid_zero_items: 0,
    split_success_source: 'POSTGRES_CURRENT_PROJECTION',
    failure_status: 503,
    replacement_items: 1,
  })}\n`)
})

test('reconciles deleted and reactivated Catalog URNs across Search, Tree, Chat exact, and vector', async () => {
  const removed = entity('inspection_results', 'Inspection evidence')
  const retained = entity('wafer_events', 'Wafer evidence')
  let providerAssets = [removed, retained]
  const provider = createServer(async (request, response) => {
    const chunks = []
    for await (const chunk of request) chunks.push(chunk)
    const url = new URL(request.url || '/', 'http://provider.test')
    const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    if (url.pathname === '/embeddings') {
      const inputs = Array.isArray(body.input) ? body.input : [body.input]
      response.writeHead(200, { 'Content-Type': 'application/json' })
      return response.end(JSON.stringify({ data: inputs.map((_input, index) => ({ index, embedding: [1, 0] })) }))
    }
    if (url.pathname === '/chat/completions') {
      const schemaName = body.response_format?.json_schema?.name
      const content = schemaName === 'datariver_chat_route'
        ? JSON.stringify({
            mode: 'VECTOR', confidence: 1, intent: 'EXACT_METADATA',
            entity_resolution_required: true, graph_traversal_required: false,
            semantic_retrieval_required: false, fallback_mode: 'GENERAL',
          })
        : 'current projection evidence [1]'
      response.writeHead(200, { 'Content-Type': 'application/json' })
      return response.end(JSON.stringify({ choices: [{ message: { content } }] }))
    }
    if (url.pathname !== '/api/graphql') {
      response.writeHead(404)
      return response.end()
    }
    if (body.variables?.urn) {
      const dataset = providerAssets.find((item) => item.urn === body.variables.urn) || null
      response.writeHead(200, { 'Content-Type': 'application/json' })
      return response.end(JSON.stringify({ data: { entity: dataset } }))
    }
    const secondPage = body.variables?.input?.scrollId === 'page-2'
    const pageAssets = secondPage ? providerAssets.slice(1) : providerAssets.slice(0, 1)
    response.writeHead(200, { 'Content-Type': 'application/json' })
    return response.end(JSON.stringify({ data: { scrollAcrossEntities: {
      count: pageAssets.length,
      total: providerAssets.length,
      nextScrollId: !secondPage && providerAssets.length > 1 ? 'page-2' : null,
      searchResults: pageAssets.map((item) => ({ entity: item })),
    } } }))
  })
  const providerOrigin = await listen(provider)
  configureProviderEnvironment(providerOrigin, { embedding: true, chat: true })
  const store = reconciliationStateStore()

  const generationA = await import('./poc-server.mjs?catalog-generation-a')
  const serverA = authenticatedPocServer(generationA, { stateStore: store.stateStore })
  const originA = await listen(serverA)
  assert.equal((await fetch(`${originA}/poc-api/datahub/catalog?limit=20`)).status, 503)
  await waitFor(() => store.observation().writes === 1, 'generation A did not commit')
  await close(serverA)

  store.markStale()
  providerAssets = [retained]
  const generationB = await import('./poc-server.mjs?catalog-generation-b')
  const serverB = authenticatedPocServer(generationB, { stateStore: store.stateStore })
  const originB = await listen(serverB)
  assert.equal((await (await fetch(`${originB}/poc-api/datahub/catalog?limit=20`)).json()).total, 2)
  await waitFor(() => store.observation().writes === 2, 'generation B did not replace the projection')
  const searchB = await (await fetch(`${originB}/poc-api/datahub/catalog?q=inspection_results&limit=20`)).json()
  assert.deepEqual(searchB.items, [])
  const treeB = await (await fetch(`${originB}/poc-api/datahub/tree?parent_kind=SCHEMA&platform=postgres&database=MANUFACTURING&schema=QUALITY`)).json()
  assert.equal(treeB.items.some((item) => item.asset.id === removed.urn), false)
  const chatExactB = await (await fetch(`${originB}/poc-api/llm/chat`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'inspection_results table metadata', mode: 'AUTO' }),
  })).json()
  assert.equal(chatExactB.evidence.some((item) => item.id === removed.urn), false)
  const chatVectorB = await (await fetch(`${originB}/poc-api/llm/chat`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'find related table assets', mode: 'AUTO' }),
  })).json()
  assert.equal(chatVectorB.evidence.some((item) => item.id === removed.urn), false)
  assert.ok(chatVectorB.evidence.every((item) => item.retrieval_method === 'PGVECTOR_COSINE'))
  await close(serverB)

  store.markStale()
  providerAssets = [removed, retained]
  const generationC = await import('./poc-server.mjs?catalog-generation-c')
  const serverC = authenticatedPocServer(generationC, { stateStore: store.stateStore })
  const originC = await listen(serverC)
  assert.equal((await (await fetch(`${originC}/poc-api/datahub/catalog?limit=20`)).json()).total, 1)
  await waitFor(() => store.observation().writes === 3, 'generation C did not reactivate the same URN')
  const searchC = await (await fetch(`${originC}/poc-api/datahub/catalog?q=inspection_results&limit=20`)).json()
  assert.deepEqual(searchC.items.map((item) => item.id), [removed.urn])
  const treeC = await (await fetch(`${originC}/poc-api/datahub/tree?parent_kind=SCHEMA&platform=postgres&database=MANUFACTURING&schema=QUALITY`)).json()
  assert.equal(treeC.items.some((item) => item.asset.id === removed.urn), true)
  const chatExactCResponse = await fetch(`${originC}/poc-api/llm/chat`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'inspection_results table metadata', mode: 'AUTO' }),
  })
  const chatExactC = await chatExactCResponse.json()
  assert.equal(chatExactC.evidence.some((item) => item.id === removed.urn && item.retrieval_method === 'CATALOG_EXACT'), true)
  const chatVectorC = await (await fetch(`${originC}/poc-api/llm/chat`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'find related table assets', mode: 'AUTO' }),
  })).json()
  assert.equal(chatVectorC.evidence.some((item) => item.id === removed.urn && item.retrieval_method === 'PGVECTOR_COSINE'), true)
  assert.equal(store.observation().historyWrites, 0, 'current inventory reconciliation must not write the history ledger')
  assert.deepEqual(store.observation().persisted.items.map((item) => item.id).sort(), [removed.urn, retained.urn].sort())
  await close(serverC)
  await close(provider)
})

test('confirms exact-boundary DataHub inventories once and fails unsafe pagination closed', async () => {
  const boundaryAssets = Array.from({ length: 250 }, (_value, index) => (
    entity(`boundary_${String(index).padStart(3, '0')}`, `Boundary asset ${index}`)
  ))
  let scenario
  const provider = createServer(async (request, response) => {
    const chunks = []
    for await (const chunk of request) chunks.push(chunk)
    JSON.parse(Buffer.concat(chunks).toString('utf8'))
    const page = scenario.pages[scenario.requests]
    scenario.requests += 1
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 20))
    if (!page) {
      response.writeHead(500, { 'Content-Type': 'application/json' })
      return response.end(JSON.stringify({ error: 'unexpected provider page' }))
    }
    if (page.status) {
      response.writeHead(page.status, { 'Content-Type': 'application/json' })
      return response.end(JSON.stringify({ error: 'bounded provider failure' }))
    }
    response.writeHead(200, { 'Content-Type': 'application/json' })
    return response.end(JSON.stringify({ data: { scrollAcrossEntities: {
      count: page.items.length,
      total: page.total,
      nextScrollId: page.next,
      searchResults: page.items.map((item) => ({ entity: item })),
    } } }))
  })
  const providerOrigin = await listen(provider)
  configureProviderEnvironment(providerOrigin)

  const makeStore = () => {
    let persisted
    let writes = 0
    let cacheWrites = 0
    return {
      stateStore: {
        configured: { postgres: true, redis: true },
        async read() { return { value: persisted ? structuredClone(persisted) : null, version: writes } },
        async write(_scope, value) {
          persisted = structuredClone(value)
          writes += 1
          return writes
        },
        async cacheGet() { return undefined },
        async cacheSet() { cacheWrites += 1 },
        async cacheDelete() {},
      },
      observation: () => ({ persisted, writes, cacheWrites }),
    }
  }

  scenario = {
    requests: 0,
    pages: [
      { items: boundaryAssets, total: 250, next: 'terminal-confirmation' },
      { items: [], total: 250, next: null },
    ],
  }
  const exactStore = makeStore()
  const exactModule = await import('./poc-server.mjs?catalog-exact-boundary-confirmation')
  const exactServer = authenticatedPocServer(exactModule, { stateStore: exactStore.stateStore })
  const exactOrigin = await listen(exactServer)
  const coldResponses = await Promise.all(Array.from({ length: 6 }, () => (
    fetch(`${exactOrigin}/poc-api/datahub/catalog?limit=20`)
  )))
  assert.deepEqual(coldResponses.map((response) => response.status), Array(6).fill(503))
  await waitFor(() => exactStore.observation().writes === 1, 'exact-boundary projection did not commit')
  assert.equal(scenario.requests, 2)
  assert.equal(exactStore.observation().cacheWrites, 1)
  const exactResponse = await fetch(`${exactOrigin}/poc-api/datahub/catalog?limit=20`)
  assert.equal(exactResponse.status, 200)
  assert.equal((await exactResponse.json()).items.length, 20)
  assert.equal(exactStore.observation().persisted.items.length, 250)
  await close(exactServer)

  const unsafeCases = [
    {
      name: 'terminal-continuation',
      pages: [
        { items: boundaryAssets, total: 250, next: 'terminal-a' },
        { items: [], total: 250, next: 'terminal-b' },
      ],
    },
    {
      name: 'terminal-new-asset',
      pages: [
        { items: boundaryAssets, total: 250, next: 'terminal-a' },
        { items: [entity('overflow_asset', 'Unsafe overflow')], total: 250, next: null },
      ],
    },
    {
      name: 'terminal-duplicate-asset',
      pages: [
        { items: boundaryAssets, total: 250, next: 'terminal-a' },
        { items: [boundaryAssets[0]], total: 250, next: null },
      ],
    },
    {
      name: 'cursor-cycle',
      pages: [
        { items: [boundaryAssets[0]], total: 3, next: 'cycle-a' },
        { items: [boundaryAssets[1]], total: 3, next: 'cycle-b' },
        { items: [boundaryAssets[1]], total: 3, next: 'cycle-a' },
      ],
    },
  ]
  for (const unsafe of unsafeCases) {
    scenario = { requests: 0, pages: unsafe.pages }
    const unsafeStore = makeStore()
    const unsafeModule = await import(`./poc-server.mjs?catalog-${unsafe.name}`)
    authenticatedPocServer(unsafeModule, { stateStore: unsafeStore.stateStore })
    await assert.rejects(
      unsafeModule.startDatahubInventoryRefresh(),
      (error) => error?.statusCode === 502,
    )
    assert.equal(scenario.requests, unsafe.pages.length)
    assert.equal(unsafeStore.observation().writes, 0, `${unsafe.name} must not commit`)
  }

  scenario = { requests: 0, pages: [{ status: 502, items: [], total: 0, next: null }] }
  const retryStore = makeStore()
  const retryModule = await import('./poc-server.mjs?catalog-cold-retry-suppression')
  const retryServer = authenticatedPocServer(retryModule, { stateStore: retryStore.stateStore })
  const retryOrigin = await listen(retryServer)
  assert.equal((await fetch(`${retryOrigin}/poc-api/datahub/catalog?limit=20`)).status, 503)
  await waitFor(() => scenario.requests === 1, 'initial failed Catalog refresh was not attempted')
  await new Promise((resolvePromise) => setTimeout(resolvePromise, 50))
  const retryResponses = await Promise.all(Array.from({ length: 4 }, () => (
    fetch(`${retryOrigin}/poc-api/datahub/catalog?limit=20`)
  )))
  assert.deepEqual(retryResponses.map((response) => response.status), Array(4).fill(503))
  assert.equal(scenario.requests, 1, 'cold polling must respect the failed-refresh retry boundary')
  assert.equal(retryStore.observation().writes, 0)
  await close(retryServer)
  await close(provider)
})

test('aborts a partial startup inventory refresh before closing the state store', async () => {
  let providerRequests = 0
  let abortedRequests = 0
  const provider = createServer(async (request, response) => {
    const chunks = []
    for await (const chunk of request) chunks.push(chunk)
    JSON.parse(Buffer.concat(chunks).toString('utf8'))
    providerRequests += 1
    if (providerRequests === 1) {
      response.writeHead(200, { 'Content-Type': 'application/json' })
      return response.end(JSON.stringify({ data: { scrollAcrossEntities: {
        count: 1,
        total: 2,
        nextScrollId: 'partial-page-2',
        searchResults: [{ entity: entity('partial_new', 'Uncommitted partial asset') }],
      } } }))
    }
    response.on('close', () => { abortedRequests += 1 })
  })
  const providerOrigin = await listen(provider)
  configureProviderEnvironment(providerOrigin)
  const sourceScope = createHash('sha256').update(providerOrigin).digest('hex').slice(0, 16)
  const lastGood = {
    projection_version: 1,
    source_scope: sourceScope,
    source_generation: 'last-good-generation',
    observed_at: new Date(Date.now() - 16 * 60 * 1_000).toISOString(),
    items: [{ id: 'urn:li:dataset:last-good' }],
  }
  const store = lifecycleStateStore(lastGood)
  const module = await import('./poc-server.mjs?catalog-shutdown-partial-refresh')
  const server = await module.startPocServer({ stateStore: store.stateStore })
  await waitFor(() => providerRequests === 2, 'startup refresh did not reach the hanging second page')

  const startedAt = performance.now()
  const firstStop = server.stopPoc()
  const secondStop = server.stopPoc()
  assert.strictEqual(firstStop, secondStop)
  let timeout
  try {
    await Promise.race([
      firstStop,
      new Promise((_resolve, reject) => {
        timeout = setTimeout(() => reject(new Error('shutdown exceeded 10 seconds')), 10_000)
      }),
    ])
  } finally {
    clearTimeout(timeout)
  }
  assert.ok(performance.now() - startedAt < 10_000)
  const observation = store.observation()
  assert.equal(observation.writes, 0)
  assert.deepEqual(observation.persisted, lastGood)
  assert.equal(observation.closeCalls, 1)
  assert.equal(observation.postCloseUses, 0)
  assert.equal(observation.closed, true)
  assert.equal(server.listening, false)
  await waitFor(() => abortedRequests === 1, 'hanging provider request was not aborted')
  assert.equal(abortedRequests, 1)
  await close(provider)
})

test('aborts embedding work and prevents its timer from relaunching during shutdown', async () => {
  let embeddingRequests = 0
  let abortedEmbeddingRequests = 0
  const provider = createServer(async (request, response) => {
    const chunks = []
    for await (const chunk of request) chunks.push(chunk)
    const url = new URL(request.url || '/', 'http://provider.test')
    if (url.pathname === '/api/graphql') {
      response.writeHead(200, { 'Content-Type': 'application/json' })
      return response.end(JSON.stringify({ data: { scrollAcrossEntities: {
        count: 1,
        total: 1,
        nextScrollId: null,
        searchResults: [{ entity: entity('embedding_asset', 'Embedding lifecycle asset') }],
      } } }))
    }
    if (url.pathname === '/embeddings') {
      embeddingRequests += 1
      response.on('close', () => { abortedEmbeddingRequests += 1 })
      return
    }
    response.writeHead(404)
    response.end()
  })
  const providerOrigin = await listen(provider)
  configureProviderEnvironment(providerOrigin, { embedding: true })
  const store = lifecycleStateStore()
  const module = await import('./poc-server.mjs?catalog-shutdown-embedding-refresh')
  const server = await module.startPocServer({ stateStore: store.stateStore })
  await waitFor(
    () => store.observation().writes === 1 && embeddingRequests === 1,
    'embedding refresh did not start after the inventory commit',
  )
  await server.stopPoc()
  await new Promise((resolvePromise) => setTimeout(resolvePromise, 50))
  const observation = store.observation()
  assert.equal(embeddingRequests, 1, 'the embedding timer must not relaunch after stop')
  assert.equal(abortedEmbeddingRequests, 1)
  assert.equal(observation.embeddingReplacements, 0)
  assert.equal(observation.closeCalls, 1)
  assert.equal(observation.postCloseUses, 0)
  assert.equal(server.listening, false)
  await close(provider)
})
