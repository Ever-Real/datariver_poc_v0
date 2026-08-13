/* global Buffer, fetch, performance, process, setTimeout, structuredClone */
import assert from 'node:assert/strict'
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

async function waitFor(predicate, message) {
  const deadline = Date.now() + 2_000
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error(message)
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 10))
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
  const coldServer = coldModule.createPocServer({ stateStore })
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
  const warmServer = warmModule.createPocServer({ stateStore })
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
  const failedServer = failedModule.createPocServer({ stateStore })
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
  const refreshServer = refreshModule.createPocServer({ stateStore })
  const refreshOrigin = await listen(refreshServer)
  assert.equal((await (await fetch(`${refreshOrigin}/poc-api/datahub/catalog?q=evidence&limit=20`)).json()).items.length, 2)
  await waitFor(() => writes === 2, 'replacement Catalog generation did not commit')
  assert.equal(providerRequests, 1)
  await close(refreshServer)

  providerRequests = 0
  const replacementModule = await import('./poc-server.mjs?catalog-performance-replacement')
  const replacementServer = replacementModule.createPocServer({ stateStore })
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
  const incompleteServer = incompleteModule.createPocServer({ stateStore })
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
  const zeroServer = zeroModule.createPocServer({ stateStore })
  const zeroOrigin = await listen(zeroServer)
  assert.equal((await fetch(`${zeroOrigin}/poc-api/datahub/catalog?limit=20`)).status, 200)
  await waitFor(() => writes === 3, 'valid empty inventory did not commit')
  assert.equal(providerRequests, 1)
  await close(zeroServer)

  providerRequests = 0
  const zeroStoredModule = await import('./poc-server.mjs?catalog-performance-valid-zero-stored')
  const zeroStoredServer = zeroStoredModule.createPocServer({ stateStore })
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
  const splitServer = splitModule.createPocServer({ stateStore: splitSuccessStore })
  const splitOrigin = await listen(splitServer)
  const splitPayload = await (await fetch(`${splitOrigin}/poc-api/datahub/catalog?limit=20`)).json()
  assert.deepEqual(splitPayload.items.map((item) => item.name), ['postgres_new'])
  assert.equal(postgresReads, 1)
  assert.equal(redisReads, 0, 'valid Redis must not mask the authoritative PostgreSQL projection')
  await close(splitServer)
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
    replacement_items: 1,
  })}\n`)
})
