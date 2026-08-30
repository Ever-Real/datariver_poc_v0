/* global Buffer, URL, URLSearchParams, fetch, process, structuredClone, setTimeout */
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { test } from 'node:test'

const providerPageSize = 250

async function listen(server) {
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  assert(address && typeof address === 'object')
  return `http://127.0.0.1:${address.port}`
}

async function close(server) {
  server.closeAllConnections()
  await new Promise((resolvePromise, reject) => server.close((error) => (
    error ? reject(error) : resolvePromise()
  )))
}

function dataset(index, { sparse = false, missingHierarchy = false, view = false } = {}) {
  const suffix = String(index).padStart(5, '0')
  const qualifiedName = missingHierarchy ? `asset_${suffix}` : `warehouse.analytics.asset_${suffix}`
  const urn = `urn:li:dataset:(urn:li:dataPlatform:postgres,${qualifiedName},PROD)`
  const optional = sparse ? null : {
    globalTags: { tags: [{ tag: {
      urn: `urn:li:tag:inventory-${index % 7}`,
      name: `inventory-${index % 7}`,
      properties: { name: `inventory-${index % 7}`, description: 'bounded test tag' },
    } }] },
    glossaryTerms: { terms: [{ term: {
      urn: `urn:li:glossaryTerm:inventory-${index % 5}`,
      name: `inventory-${index % 5}`,
      properties: { name: `inventory-${index % 5}`, description: 'bounded test term' },
    } }] },
    domain: { domain: {
      urn: `urn:li:domain:inventory-${index % 3}`,
      properties: { name: `Inventory ${index % 3}`, description: 'bounded test domain' },
    } },
    ownership: { owners: [{ owner: { urn: `urn:li:corpuser:test-owner-${index % 4}` }, type: 'TECHNICAL_OWNER' }] },
  }
  return {
    urn,
    type: 'DATASET',
    name: `asset_${suffix}`,
    subTypes: { typeNames: [view ? 'View' : 'Table'] },
    platform: { urn: 'urn:li:dataPlatform:postgres', name: 'postgres' },
    properties: {
      name: `asset_${suffix}`,
      qualifiedName,
      description: sparse ? null : `Inventory description ${index}`,
      created: index % 2 ? null : 1_704_164_645_000,
      customProperties: sparse ? null : [{ key: 'inventory.test', value: String(index) }],
    },
    editableProperties: sparse ? null : { description: null },
    container: sparse ? null : {
      urn: 'urn:li:container:warehouse-analytics',
      properties: { name: 'analytics', qualifiedName: 'warehouse.analytics', customProperties: [] },
      subTypes: { typeNames: ['Schema'] },
    },
    dataPlatformInstance: sparse ? null : {
      urn: 'urn:li:dataPlatformInstance:(urn:li:dataPlatform:postgres,prod)',
      instanceId: 'prod',
      properties: { name: 'prod', description: '', customProperties: [] },
    },
    browsePathV2: missingHierarchy || sparse ? null : { path: [
      { name: 'warehouse', entity: { type: 'CONTAINER', properties: { name: 'warehouse' }, subTypes: { typeNames: ['Database'] } } },
      { name: 'analytics', entity: { type: 'CONTAINER', properties: { name: 'analytics' }, subTypes: { typeNames: ['Schema'] } } },
    ] },
    structuredProperties: sparse ? null : { properties: [] },
    ownership: optional?.ownership ?? null,
    globalTags: optional?.globalTags ?? null,
    glossaryTerms: optional?.glossaryTerms ?? null,
    domain: optional?.domain ?? null,
    schemaMetadata: { fields: index % 11 === 0 ? [] : [{
      fieldPath: `column_${index % 13}`,
      label: null,
      type: index % 2 ? 'STRING' : 'NUMBER',
      nativeDataType: index % 2 ? 'varchar' : 'numeric',
      description: sparse ? null : 'bounded schema field',
      nullable: index % 3 !== 0,
      globalTags: null,
      glossaryTerms: null,
      schemaFieldEntity: null,
    }] },
    editableSchemaMetadata: sparse ? null : { editableSchemaFieldInfo: [] },
    latestFullTableProfile: sparse ? null : [],
    fineGrainedLineages: sparse ? null : [],
  }
}

function inventoryStore() {
  let persisted
  let writes = 0
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
      async readChangeHistoryAccess() {
        return {
          access: { version: 1, value: {
            schema_version: 1,
            active_subject_id: 'inventory-scale-subject',
            users: [{
              subject_id: 'inventory-scale-subject', role: 'admin', active: true,
              provider_owner_refs: [], max_security_grade: 'restricted',
            }],
            system_assignments: [],
          } },
          core: { version: 0, value: null },
        }
      },
    },
    observation() { return { persisted: structuredClone(persisted), writes } },
  }
}

async function waitForCatalog(origin) {
  const deadline = Date.now() + 10_000
  let response
  while (Date.now() < deadline) {
    response = await fetch(`${origin}/poc-api/datahub/catalog?limit=1`)
    if (response.status === 200) return { response, body: await response.json() }
    const body = await response.json()
    if (body.diagnostic?.terminal) throw new Error(`${body.code}: ${body.detail}`)
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 10))
  }
  throw new Error(`Catalog did not become ready; last status ${response?.status}`)
}

async function exactInventoryScenario(rawEntities, suffix) {
  let providerRequests = 0
  const providerPages = []
  const stableProviderEntities = [...rawEntities].sort((left, right) => (
    String(left?.urn || '').localeCompare(String(right?.urn || ''))
  ))
  const provider = createServer(async (request, response) => {
    const chunks = []
    for await (const chunk of request) chunks.push(chunk)
    const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    assert.match(body.query, /DataRiverPocCatalogEmbeddingInventory/u)
    assert.match(body.query, /exists\s+status \{ removed \}/u)
    assert.equal(body.variables.input.count, providerPageSize)
    assert.deepEqual(body.variables.input.sortInput, {
      sortCriteria: [{ field: 'urn', sortOrder: 'ASCENDING' }],
    })
    const offset = body.variables.input.scrollId ? Number(body.variables.input.scrollId) : 0
    const count = body.variables.input.count
    const items = stableProviderEntities.slice(offset, offset + count)
    const nextOffset = offset + items.length
    const exactBoundaryConfirmation = stableProviderEntities.length > 0
      && nextOffset === stableProviderEntities.length && items.length === count
    const nextScrollId = nextOffset < stableProviderEntities.length || exactBoundaryConfirmation
      ? String(nextOffset)
      : null
    providerRequests += 1
    providerPages.push({ metadataCount: count, envelopeCount: items.length, nextScrollId })
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify({ data: { scrollAcrossEntities: {
      // DataHub ScrollResults.count is provider page-size metadata, not the
      // number of materialized SearchResult envelopes on a partial page.
      count,
      total: stableProviderEntities.length,
      nextScrollId,
      searchResults: items.map((entity) => ({ entity })),
    } } }))
  })
  const providerOrigin = await listen(provider)
  Object.assign(process.env, {
    POC_ENV_FILE: 'poc-datahub-inventory-scale.test.env.missing',
    POC_DATABASE_URL: '',
    POC_POSTGRES_HOST: '',
    POC_REDIS_URL: '',
    DATAHUB_GMS_URL: providerOrigin,
    DATAHUB_GMS_TOKEN: 'inventory-scale-test-token',
    LLM_CHAT_URL: '',
    LLM_CHAT_MODEL: '',
    LLM_CHAT_TOKEN: '',
    LLM_EMBEDDING_URL: '',
    LLM_EMBEDDING_MODEL: '',
    LLM_EMBEDDING_TOKEN: '',
    LLM_RERANKER_URL: '',
    LLM_RERANKER_MODEL: '',
    LLM_RERANKER_TOKEN: '',
  })
  const store = inventoryStore()
  const module = await import(`./poc-server.mjs?inventory-scale-${suffix}`)
  const server = module.createPocServer({
    stateStore: store.stateStore,
    authenticator: {
      async authenticate() { return { subjectId: 'inventory-scale-subject', tokenHash: 'f'.repeat(64) } },
      assertOrigin() {},
    },
  })
  const origin = await listen(server)
  return {
    origin,
    providerRequests: () => providerRequests,
    providerPages: () => structuredClone(providerPages),
    store,
    close: async () => {
      await close(server)
      await close(provider)
    },
  }
}

async function classifiedFailureScenario(suffix, providerHandler, stateStoreOverride) {
  let requests = 0
  const provider = createServer(async (request, response) => {
    const chunks = []
    for await (const chunk of request) chunks.push(chunk)
    const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    requests += 1
    await providerHandler({ body, requestNumber: requests, response })
  })
  const providerOrigin = await listen(provider)
  Object.assign(process.env, {
    POC_ENV_FILE: 'poc-datahub-inventory-scale.test.env.missing',
    POC_DATABASE_URL: '',
    POC_POSTGRES_HOST: '',
    POC_REDIS_URL: '',
    DATAHUB_GMS_URL: providerOrigin,
    DATAHUB_GMS_TOKEN: 'inventory-scale-test-token',
    LLM_CHAT_URL: '', LLM_CHAT_MODEL: '', LLM_CHAT_TOKEN: '',
    LLM_EMBEDDING_URL: '', LLM_EMBEDDING_MODEL: '', LLM_EMBEDDING_TOKEN: '',
    LLM_RERANKER_URL: '', LLM_RERANKER_MODEL: '', LLM_RERANKER_TOKEN: '',
  })
  const store = inventoryStore()
  const module = await import(`./poc-server.mjs?inventory-failure-${suffix}`)
  const server = module.createPocServer({
    stateStore: stateStoreOverride || store.stateStore,
    authenticator: {
      async authenticate() { return { subjectId: 'inventory-scale-subject', tokenHash: 'f'.repeat(64) } },
      assertOrigin() {},
    },
  })
  const origin = await listen(server)
  return {
    origin,
    requests: () => requests,
    close: async () => {
      await close(server)
      await close(provider)
    },
  }
}

async function terminalCatalogFailure(scenario) {
  assert.equal((await fetch(`${scenario.origin}/poc-api/datahub/catalog?limit=1`)).status, 503)
  const deadline = Date.now() + 2_000
  let response
  let body
  while (Date.now() < deadline) {
    response = await fetch(`${scenario.origin}/poc-api/datahub/catalog?limit=1`)
    body = await response.json()
    if (body.diagnostic?.terminal) return { response, body }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 10))
  }
  throw new Error(`Terminal inventory diagnostic did not surface: ${response?.status} ${body?.code}`)
}

test('keeps inventory pagination count-independent at dynamic provider boundaries', async () => {
  const counts = [
    0,
    1,
    providerPageSize - 1,
    providerPageSize,
    providerPageSize + 1,
    providerPageSize * 2 + 3,
  ]
  for (const count of counts) {
    const scenario = await exactInventoryScenario(
      Array.from({ length: count }, (_value, index) => dataset(index)),
      `dynamic-${count}`,
    )
    try {
      const { body } = await waitForCatalog(scenario.origin)
      assert.equal(body.total, count)
      assert.equal(scenario.store.observation().persisted.items.length, count)
      assert.equal(body.meta.inventory_refresh.processed_count, count)
      assert.equal(body.meta.inventory_refresh.expected_total, count)
      assert.equal(body.meta.inventory_refresh.normalized_count, count)
      assert.equal(body.meta.inventory_refresh.skipped_noncurrent_count, 0)
      assert.equal(body.meta.inventory_refresh.duplicate_count, 0)
      assert.equal(body.meta.inventory_refresh.unresolved_search_result_count, 0)
      assert.equal(body.meta.inventory_refresh.raw_search_result_count, count)
      assert.ok(scenario.providerRequests() >= 1)
    } finally {
      await scenario.close()
    }
  }
})

test('accepts a cursor-driven partial terminal page whose provider count metadata exceeds its envelopes', async () => {
  const generatedCount = providerPageSize * 2 + 7
  const scenario = await exactInventoryScenario(
    Array.from({ length: generatedCount }, (_value, index) => dataset(index)),
    'partial-terminal-page',
  )
  try {
    const { body } = await waitForCatalog(scenario.origin)
    const terminal = scenario.providerPages().at(-1)
    assert.equal(terminal.metadataCount, providerPageSize)
    assert.equal(terminal.envelopeCount, generatedCount % providerPageSize)
    assert.equal(terminal.nextScrollId, null)
    assert.equal(body.meta.inventory_refresh.raw_search_result_count, generatedCount)
    assert.equal(body.meta.inventory_refresh.expected_total, generatedCount)
  } finally {
    await scenario.close()
  }
})

test('caps ordinary catalog pages at 100 while the schema tree advances in 200-item pages', async () => {
  const scenario = await exactInventoryScenario(
    Array.from({ length: 450 }, (_value, index) => dataset(index)),
    'tree-page-size',
  )
  try {
    await waitForCatalog(scenario.origin)

    const catalogResponse = await fetch(`${scenario.origin}/poc-api/datahub/catalog?limit=200`)
    const catalog = await catalogResponse.json()
    assert.equal(catalogResponse.status, 200, JSON.stringify(catalog))
    assert.equal(catalog.page.limit, 100)
    assert.equal(catalog.items.length, 100)
    assert.ok(catalog.page.next_cursor)

    const treeUrl = new URL('/poc-api/datahub/tree', scenario.origin)
    treeUrl.search = new URLSearchParams({
      parent_kind: 'SCHEMA',
      platform: 'postgres',
      database: 'warehouse',
      schema: 'analytics',
      limit: '200',
    }).toString()
    const firstResponse = await fetch(treeUrl)
    const first = await firstResponse.json()
    assert.equal(firstResponse.status, 200, JSON.stringify(first))
    assert.equal(first.page.limit, 200)
    assert.equal(first.items.length, 200)
    assert.ok(first.page.next_cursor)

    treeUrl.searchParams.set('cursor', first.page.next_cursor)
    const secondResponse = await fetch(treeUrl)
    const second = await secondResponse.json()
    assert.equal(secondResponse.status, 200, JSON.stringify(second))
    assert.equal(second.page.limit, 200)
    assert.equal(second.items.length, 200)
    assert.ok(second.page.next_cursor)
    assert.notEqual(second.page.next_cursor, first.page.next_cursor)
    assert.equal(new Set([...first.items, ...second.items].map((item) => item.id)).size, 400)

    const wrongScope = await fetch(
      `${scenario.origin}/poc-api/datahub/catalog?limit=200&cursor=${encodeURIComponent(first.page.next_cursor)}`,
    )
    assert.equal(wrongScope.status, 400)
  } finally {
    await scenario.close()
  }
})

test('promotes a large generated rich inventory after explicit noncurrent filtering and canonical deduplication', async () => {
  const generatedRawCount = providerPageSize * 6 + 37
  const current = Array.from({ length: generatedRawCount - 4 }, (_value, index) => dataset(index, {
    sparse: index % 17 === 0,
    missingHierarchy: index % 31 === 0,
    view: index % 19 === 0,
  }))
  const noncurrent = [
    { ...dataset(50_000), properties: null, schemaMetadata: null },
    { ...dataset(50_001), exists: false, status: { removed: false } },
    { ...dataset(50_002), exists: true, status: { removed: true } },
  ]
  const rawEntities = [...current, ...noncurrent, structuredClone(current[17])]
  assert.equal(rawEntities.length, generatedRawCount)
  const scenario = await exactInventoryScenario(rawEntities, 'large-generated-rich-inventory')
  try {
    const { body } = await waitForCatalog(scenario.origin)
    const observation = scenario.store.observation()
    assert.ok(scenario.providerRequests() > 2)
    assert.equal(observation.writes, 1)
    assert.equal(observation.persisted.items.length, current.length)
    assert.equal(body.total, current.length)
    assert.equal(body.items.length, 1)
    assert.equal(body.meta.catalog_request.phase, 'RESPONSE_BUILD')
    assert.equal(body.meta.catalog_request.processed_count, current.length)
    assert.equal(body.meta.catalog_request.normalized_count, 1)
    assert.deepEqual(body.meta.inventory_refresh, {
      ...body.meta.inventory_refresh,
      processed_count: generatedRawCount,
      expected_total: generatedRawCount,
      normalized_count: current.length,
      skipped_noncurrent_count: noncurrent.length,
      duplicate_count: 1,
      unresolved_search_result_count: 0,
      terminal: false,
    })
    assert.deepEqual(body.meta.inventory_refresh.filtered_noncurrent_reasons, {
      DATASET_CURRENT_ASPECTS_ABSENT: 1,
      DATASET_EXISTS_FALSE: 1,
      DATASET_STATUS_REMOVED: 1,
    })
    assert.equal(
      body.meta.inventory_refresh.processed_count,
      body.meta.inventory_refresh.normalized_count
        + body.meta.inventory_refresh.skipped_noncurrent_count
        + body.meta.inventory_refresh.duplicate_count
        + body.meta.inventory_refresh.unresolved_search_result_count,
    )
    assert.ok(body.meta.inventory_refresh.elapsed_ms < 10_000)
    assert.ok(body.meta.inventory_refresh.page_fetch_ms < 10_000)
    assert.ok(body.meta.inventory_refresh.normalization_ms < 10_000)

    const platformTree = await (
      await fetch(`${scenario.origin}/poc-api/datahub/tree?parent_kind=PLATFORM&platform=postgres&limit=100`)
    ).json()
    assert.equal(platformTree.items.some((item) => !item.label), false)
    assert.equal(JSON.stringify(platformTree).includes('Database 메타데이터 없음'), false)
  } finally {
    await scenario.close()
  }
})

test('accounts from SearchResult envelopes and classifies deterministic extraction failures exactly', async () => {
  const cases = [
    { suffix: 'page-count', count: null, results: [{ entity: dataset(1) }], reason: 'PAGE_RESULT_COUNT_CONTRACT' },
    { suffix: 'envelope', count: 1, results: [null], reason: 'SEARCH_RESULT_ENVELOPE_INVALID' },
    { suffix: 'entity-absent', count: 1, results: [{ entity: null }], reason: 'SEARCH_RESULT_ENTITY_ABSENT' },
    {
      suffix: 'entity-type', count: 1,
      results: [{ entity: { urn: 'urn:li:chart:test', type: 'CHART' } }],
      reason: 'SEARCH_RESULT_ENTITY_TYPE_INVALID',
    },
    {
      suffix: 'dataset-urn', count: 1,
      results: [{ entity: { urn: 'not-a-dataset-urn', type: 'DATASET' } }],
      reason: 'SEARCH_RESULT_DATASET_URN_INVALID',
    },
  ]
  for (const value of cases) {
    const scenario = await classifiedFailureScenario(value.suffix, async ({ response }) => {
      response.writeHead(200, { 'Content-Type': 'application/json' })
      response.end(JSON.stringify({ data: { scrollAcrossEntities: {
        count: value.count, total: value.results.length, nextScrollId: null,
        searchResults: value.results,
      } } }))
    })
    try {
      const { response, body } = await terminalCatalogFailure(scenario)
      assert.equal(response.status, 502)
      assert.equal(body.code, 'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED')
      assert.equal(body.diagnostic.phase, 'ENTITY_EXTRACTION')
      assert.equal(body.diagnostic.extraction_reason, value.reason)
      assert.equal(body.diagnostic.search_result_envelope_count, value.results.length)
      assert.equal(body.diagnostic.raw_search_result_count, value.results.length)
      assert.equal(body.diagnostic.terminal, true)
      const requests = scenario.requests()
      const repeated = await fetch(`${scenario.origin}/poc-api/datahub/catalog?limit=1`)
      assert.equal((await repeated.json()).code, body.code)
      assert.equal(scenario.requests(), requests, 'terminal extraction failures must fail fast during cooldown')
    } finally {
      await scenario.close()
    }
  }

  const normalization = await classifiedFailureScenario('entity-normalization', async ({ response }) => {
    const invalidOptionalShape = dataset(1)
    invalidOptionalShape.browsePathV2 = { path: {} }
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify({ data: { scrollAcrossEntities: {
      count: 1, total: 1, nextScrollId: null,
      searchResults: [{ entity: invalidOptionalShape }],
    } } }))
  })

  try {
    const { body } = await terminalCatalogFailure(normalization)
    assert.equal(body.code, 'PREP_DATAHUB_INVENTORY_NORMALIZATION_FAILED')
    assert.equal(body.diagnostic.phase, 'ENTITY_NORMALIZATION')
  } finally {
    await normalization.close()
  }
})

test('classifies provider query, page, GraphQL, and snapshot promotion failures separately', async () => {
  const cases = [
    {
      suffix: 'query',
      expected: 'PREP_DATAHUB_INVENTORY_QUERY_FAILED',
      terminal: false,
      handler: async ({ response }) => {
        response.writeHead(503, { 'Content-Type': 'application/json' })
        response.end('{}')
      },
    },
    {
      suffix: 'page',
      expected: 'PREP_DATAHUB_INVENTORY_PAGE_FAILED',
      terminal: false,
      handler: async ({ requestNumber, response }) => {
        if (requestNumber === 1) {
          response.writeHead(200, { 'Content-Type': 'application/json' })
          response.end(JSON.stringify({ data: { scrollAcrossEntities: {
            count: 1, total: 2, nextScrollId: 'next-page',
            searchResults: [{ entity: dataset(1) }],
          } } }))
          return
        }
        response.writeHead(503, { 'Content-Type': 'application/json' })
        response.end('{}')
      },
    },
    {
      suffix: 'graphql',
      expected: 'PREP_DATAHUB_INVENTORY_GRAPHQL_FAILED',
      terminal: true,
      handler: async ({ response }) => {
        response.writeHead(200, { 'Content-Type': 'application/json' })
        response.end(JSON.stringify({ errors: [{ message: 'sanitized test rejection' }] }))
      },
    },
  ]
  for (const value of cases) {
    const scenario = await classifiedFailureScenario(value.suffix, value.handler)
    try {
      assert.equal((await fetch(`${scenario.origin}/poc-api/datahub/catalog?limit=1`)).status, 503)
      const deadline = Date.now() + 2_000
      let body
      while (Date.now() < deadline) {
        const response = await fetch(`${scenario.origin}/poc-api/datahub/catalog?limit=1`)
        body = await response.json()
        if (body.code === value.expected) break
        await new Promise((resolvePromise) => setTimeout(resolvePromise, 10))
      }
      assert.equal(body.code, value.expected)
      assert.equal(body.diagnostic.terminal, value.terminal)
    } finally {
      await scenario.close()
    }
  }

  const baseStore = inventoryStore()
  const promotionStore = {
    ...baseStore.stateStore,
    async write() { throw new Error('bounded snapshot write failure') },
  }
  const promotion = await classifiedFailureScenario('promotion', async ({ response }) => {
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify({ data: { scrollAcrossEntities: {
      count: 1, total: 1, nextScrollId: null,
      searchResults: [{ entity: dataset(1) }],
    } } }))
  }, promotionStore)
  try {
    const { body } = await terminalCatalogFailure(promotion)
    assert.equal(body.code, 'PREP_DATAHUB_INVENTORY_PROMOTION_FAILED')
    assert.equal(body.diagnostic.phase, 'SNAPSHOT_PERSISTENCE')
  } finally {
    await promotion.close()
  }
})
