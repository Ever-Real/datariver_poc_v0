/* global Buffer, URL, fetch, process */
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { after, before, test } from 'node:test'

let server
let origin

before(async () => {
  Object.assign(process.env, {
    POC_ENV_FILE: 'poc-server.test.env.missing',
    POC_DATABASE_URL: '',
    POC_POSTGRES_HOST: '',
    POC_REDIS_URL: '',
  })
  const { createPocServer } = await import('./poc-server.mjs?fallback-contract-test')
  server = createPocServer()
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  assert.equal(typeof address, 'object')
  origin = `http://127.0.0.1:${address.port}`
})

after(async () => {
  server.closeAllConnections()
  await new Promise((resolvePromise, reject) => server.close((error) => error ? reject(error) : resolvePromise()))
})

test('serves the POC at the root with the runtime boundary', async () => {
  const response = await fetch(origin)
  assert.equal(response.status, 200)
  assert.match(response.headers.get('content-security-policy'), /connect-src 'self'/)
  assert.match(response.headers.get('content-security-policy'), /script-src 'self' 'wasm-unsafe-eval'/)
  assert.doesNotMatch(response.headers.get('content-security-policy'), /script-src[^;]*\s'unsafe-eval'(?:\s|;|$)/)
  const body = await response.text()
  assert.match(body, /poc-runtime-config\.js/)
  assert.match(body, /src="\.\/assets\/poc-/)
})

test('does not expose provider credentials through runtime configuration', async () => {
  const response = await fetch(new URL('/poc-runtime-config.js', origin))
  assert.equal(response.status, 200)
  const body = await response.text()
  assert.doesNotMatch(body, /token|password|secret/i)
  assert.match(body, /__DATARIVER_POC_RUNTIME__/)
})

test('allows Compose-only Neo4j credentials when npm mode has no Neo4j URL', () => {
  const result = spawnSync(process.execPath, [
    '--input-type=module',
    '--eval',
    "await import('./poc-server.mjs?npm-config-test')",
  ], {
    cwd: new URL('.', import.meta.url),
    encoding: 'utf8',
    env: {
      ...process.env,
      NEO4J_HTTP_URL: '',
      NEO4J_USERNAME: 'neo4j',
      NEO4J_PASSWORD: 'local-test-password',
    },
  })
  assert.equal(result.status, 0, result.stderr)
})

test('reports a safe provider capability inventory', async () => {
  const response = await fetch(new URL('/poc-api/capabilities', origin))
  assert.equal(response.status, 200)
  const body = await response.json()
  assert.ok(Array.isArray(body.items))
  assert.equal(body.items.length, 7)
  assert.ok(body.items.every((item) => ['available', 'disabled', 'unavailable'].includes(item.state)))
})

test('persists only fixed allowlisted POC state scopes in the server fallback store', async () => {
  const empty = await fetch(new URL('/poc-api/state/core', origin))
  assert.equal(empty.status, 200)
  assert.equal((await empty.json()).value, null)
  const stored = await fetch(new URL('/poc-api/state/core', origin), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value: { sequence: 901, changeRecords: [] } }),
  })
  assert.equal(stored.status, 200)
  assert.equal((await stored.json()).version, 1)
  const reread = await (await fetch(new URL('/poc-api/state/core', origin))).json()
  assert.deepEqual(reread.value, { sequence: 901, changeRecords: [] })
  assert.equal((await fetch(new URL('/poc-api/state/arbitrary', origin))).status, 404)
})

test('bounds an unavailable Redis startup and retries after a cold-start PostgreSQL failure', () => {
  const result = spawnSync(process.execPath, [
    '--input-type=module',
    '--eval',
    String.raw`
      import assert from 'node:assert/strict'
      import { createHash } from 'node:crypto'
      import { createServer as createTcpServer } from 'node:net'

      function parseCommand(buffer) {
        if (!buffer.length) return undefined
        assert.equal(buffer[0], 42)
        let offset = 1
        const readLine = () => {
          const end = buffer.indexOf('\r\n', offset)
          if (end < 0) return undefined
          const line = buffer.subarray(offset, end).toString('utf8')
          offset = end + 2
          return line
        }
        const countLine = readLine()
        if (countLine === undefined) return undefined
        const count = Number(countLine)
        const args = []
        for (let index = 0; index < count; index += 1) {
          if (offset >= buffer.length) return undefined
          assert.equal(buffer[offset], 36)
          offset += 1
          const lengthLine = readLine()
          if (lengthLine === undefined) return undefined
          const length = Number(lengthLine)
          if (buffer.length < offset + length + 2) return undefined
          args.push(buffer.subarray(offset, offset + length).toString('utf8'))
          offset += length
          assert.equal(buffer.subarray(offset, offset + 2).toString('utf8'), '\r\n')
          offset += 2
        }
        return { args, bytes: offset }
      }

      const providerUrl = 'http://127.0.0.1:1'
      const sourceScope = createHash('sha256').update(providerUrl).digest('hex').slice(0, 16)
      const observedAt = new Date().toISOString()
      const projection = {
        projection_version: 1,
        source_scope: sourceScope,
        source_generation: 'f'.repeat(64),
        observed_at: observedAt,
        items: [{
          id: 'urn:li:dataset:(urn:li:dataPlatform:postgres,DB.SCHEMA.redis_last_good,PROD)',
          external_urn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,DB.SCHEMA.redis_last_good,PROD)',
          asset_type: 'DATASET',
          dataset_kind: 'TABLE',
          name: 'redis_last_good',
          description: 'bounded Redis fallback',
          platform: 'postgres',
          database_name: 'DB',
          schema_name: 'SCHEMA',
          owner: 'Unassigned',
          domain: 'Unassigned',
          tags: [],
          terms: [],
          term_references: [],
          created_at: null,
          classification: 'INTERNAL',
          lifecycle: 'ACTIVE',
          observed_at: observedAt,
          matches: [],
        }],
      }
      const encodedProjection = JSON.stringify(projection)
      let redisConnections = 0
      let redisGets = 0
      const redisSockets = new Set()
      const redisServer = createTcpServer((socket) => {
        redisConnections += 1
        redisSockets.add(socket)
        socket.on('close', () => redisSockets.delete(socket))
        let buffered = Buffer.alloc(0)
        socket.on('data', (chunk) => {
          buffered = Buffer.concat([buffered, chunk])
          for (;;) {
            const command = parseCommand(buffered)
            if (!command) break
            buffered = buffered.subarray(command.bytes)
            const name = command.args[0]?.toUpperCase()
            if (name === 'HELLO') {
              socket.write('%1\r\n+proto\r\n:3\r\n')
            } else if (name === 'GET') {
              redisGets += 1
              socket.write('$' + Buffer.byteLength(encodedProjection) + '\r\n'
                + encodedProjection + '\r\n')
            } else {
              socket.write('+OK\r\n')
            }
          }
        })
      })

      try {
        await new Promise((resolvePromise) => redisServer.listen(0, '127.0.0.1', resolvePromise))
        const redisAddress = redisServer.address()
        assert.equal(typeof redisAddress, 'object')
        await new Promise((resolvePromise, reject) => redisServer.close((error) => (
          error ? reject(error) : resolvePromise()
        )))
        Object.assign(process.env, {
          POC_ENV_FILE: 'poc-state-store.adapter.test.env.missing',
          POC_DATABASE_URL: '',
          POC_POSTGRES_HOST: '',
          POC_REDIS_URL: 'redis://127.0.0.1:' + redisAddress.port,
          DATAHUB_GMS_URL: providerUrl,
          DATAHUB_GMS_TOKEN: '',
        })
        let postgresQueries = 0
        const databasePool = {
          async query() {
            postgresQueries += 1
            throw new Error('bounded PostgreSQL startup failure')
          },
          async end() {},
        }
        const { createPocStateStore } = await import('./poc-state-store.mjs?pg-failure-redis-fallback')
        const { createPocServer } = await import('./poc-server.mjs?actual-adapter-redis-fallback')
        const stateStore = createPocStateStore({ databasePool })
        const pocServer = createPocServer({ stateStore })
        await new Promise((resolvePromise) => pocServer.listen(0, '127.0.0.1', resolvePromise))
        const address = pocServer.address()
        assert.equal(typeof address, 'object')
        const startedAt = performance.now()
        const unavailableResponse = await fetch(
          'http://127.0.0.1:' + address.port + '/poc-api/datahub/catalog?limit=20',
          { signal: AbortSignal.timeout(1500) },
        )
        const unavailableMilliseconds = performance.now() - startedAt
        assert.equal(unavailableResponse.status, 503)
        assert.ok(unavailableMilliseconds < 1500)

        await new Promise((resolvePromise) => redisServer.listen(redisAddress.port, '127.0.0.1', resolvePromise))
        const recoveredResponse = await fetch(
          'http://127.0.0.1:' + address.port + '/poc-api/datahub/catalog?limit=20',
        )
        const payload = await recoveredResponse.json()
        assert.equal(recoveredResponse.status, 200)
        assert.deepEqual(payload.items.map((item) => item.name), ['redis_last_good'])
        assert.equal(postgresQueries, 2)
        assert.equal(redisConnections, 1)
        assert.equal(redisGets, 1)
        pocServer.closeAllConnections()
        await new Promise((resolvePromise, reject) => pocServer.close((error) => (
          error ? reject(error) : resolvePromise()
        )))
        for (const socket of redisSockets) socket.destroy()
        await new Promise((resolvePromise, reject) => redisServer.close((error) => (
          error ? reject(error) : resolvePromise()
        )))
        process.stdout.write(JSON.stringify({
          unavailableStatus: unavailableResponse.status,
          unavailableMilliseconds,
          postgresQueries,
          redisConnections,
          redisGets,
        }))
      } catch (error) {
        console.error(error)
        process.exit(1)
      }
    `,
  ], {
    cwd: new URL('.', import.meta.url),
    encoding: 'utf8',
    timeout: 10_000,
    env: { ...process.env },
  })
  assert.equal(result.status, 0, result.stderr || result.stdout)
  const observation = JSON.parse(result.stdout)
  assert.deepEqual(observation, {
    unavailableStatus: 503,
    unavailableMilliseconds: observation.unavailableMilliseconds,
    postgresQueries: 2,
    redisConnections: 1,
    redisGets: 1,
  })
  assert.ok(observation.unavailableMilliseconds < 1500)
})

test('atomically fences in-memory Catalog embeddings to the active current generation', async () => {
  const { createPocStateStore } = await import('./poc-state-store.mjs?memory-generation-contract')
  const store = createPocStateStore()
  const bindingHash = 'b'.repeat(64)
  const firstGeneration = '1'.repeat(64)
  const secondGeneration = '2'.repeat(64)
  const projectionScope = 'catalog-inventory-v1:test'
  const record = (assetUrn, sourceGeneration, embedding) => ({
    bindingHash,
    assetUrn,
    sourceHash: assetUrn === 'asset-a' ? 'a'.repeat(64) : 'c'.repeat(64),
    sourceGeneration,
    contentText: assetUrn,
    metadata: { id: assetUrn },
    embedding,
  })

  await store.write(projectionScope, { source_generation: firstGeneration })
  await store.replaceCatalogEmbeddingGeneration(bindingHash, projectionScope, firstGeneration, [
    record('asset-a', firstGeneration, [1, 0]),
    record('asset-b', firstGeneration, [0, 1]),
  ], ['asset-a', 'asset-b'])
  assert.equal(await store.catalogEmbeddingActiveGeneration(bindingHash), firstGeneration)
  assert.deepEqual(
    (await store.searchCatalogEmbeddings(bindingHash, projectionScope, firstGeneration, [1, 0], 5))
      .map((item) => item.assetUrn),
    ['asset-a', 'asset-b'],
  )

  await store.write(projectionScope, { source_generation: secondGeneration })
  await assert.rejects(
    store.replaceCatalogEmbeddingGeneration(bindingHash, projectionScope, secondGeneration, [
      record('asset-a', secondGeneration, [1, 0]),
      record('asset-b', secondGeneration, [Number.NaN, 1]),
    ], ['asset-a', 'asset-b']),
    /invalid or outside the supported dimension bound/,
  )
  assert.equal(await store.catalogEmbeddingActiveGeneration(bindingHash), firstGeneration)
  assert.deepEqual(await store.searchCatalogEmbeddings(
    bindingHash, projectionScope, secondGeneration, [1, 0], 5,
  ), [])

  await store.replaceCatalogEmbeddingGeneration(bindingHash, projectionScope, secondGeneration, [
    record('asset-b', secondGeneration, [0, 1]),
  ], ['asset-b'])
  assert.equal(await store.catalogEmbeddingActiveGeneration(bindingHash), secondGeneration)
  assert.deepEqual(
    (await store.searchCatalogEmbeddings(bindingHash, projectionScope, secondGeneration, [0, 1], 5))
      .map((item) => item.assetUrn),
    ['asset-b'],
  )
  assert.deepEqual(await store.searchCatalogEmbeddings(
    bindingHash, projectionScope, firstGeneration, [1, 0], 5,
  ), [])
})

test('commits the PostgreSQL Embedding generation and active pointer in one fenced transaction', async () => {
  const { createPocStateStore } = await import('./poc-state-store.mjs?postgres-generation-contract')
  const statements = []
  const bindingHash = 'd'.repeat(64)
  const sourceGeneration = '3'.repeat(64)
  const projectionScope = 'catalog-inventory-v1:postgres-test'
  const client = {
    async query(sql, parameters = []) {
      const normalized = String(sql).replace(/\s+/g, ' ').trim()
      statements.push({ sql: normalized, parameters })
      if (normalized.includes('SELECT value FROM poc_state') && normalized.includes('FOR UPDATE')) {
        return { rows: [{ value: { source_generation: sourceGeneration } }] }
      }
      return { rows: [] }
    },
    release() {},
  }
  const databasePool = {
    async query(sql, parameters = []) {
      const normalized = String(sql).replace(/\s+/g, ' ').trim()
      statements.push({ sql: normalized, parameters })
      if (normalized.includes('FROM poc_catalog_embedding')) {
        return { rows: [{
          asset_urn: 'asset-current', content_text: 'current', metadata: { id: 'asset-current' }, similarity: 1,
        }] }
      }
      return { rows: [] }
    },
    async connect() { return client },
    async end() {},
  }
  const store = createPocStateStore({ databasePool })
  await store.replaceCatalogEmbeddingGeneration(bindingHash, projectionScope, sourceGeneration, [{
    bindingHash,
    assetUrn: 'asset-current',
    sourceHash: 'e'.repeat(64),
    sourceGeneration,
    contentText: 'current',
    metadata: { id: 'asset-current' },
    embedding: [1, 0],
  }], ['asset-current'])
  const transactionSql = statements.map((entry) => entry.sql)
  assert.ok(transactionSql.includes('BEGIN'))
  assert.ok(transactionSql.some((sql) => sql.includes('SELECT value FROM poc_state') && sql.includes('FOR UPDATE')))
  assert.ok(transactionSql.some((sql) => sql.startsWith('DELETE FROM poc_catalog_embedding')
    && sql.includes('source_generation <> $2')))
  assert.ok(transactionSql.some((sql) => sql.startsWith('INSERT INTO poc_state (scope, value)')))
  assert.ok(transactionSql.indexOf('COMMIT') > transactionSql.findIndex((sql) => sql.startsWith('INSERT INTO poc_state')))

  const ranked = await store.searchCatalogEmbeddings(
    bindingHash, projectionScope, sourceGeneration, [1, 0], 5,
  )
  assert.deepEqual(ranked.map((item) => item.assetUrn), ['asset-current'])
  const search = statements.findLast((entry) => entry.sql.includes('ORDER BY catalog_embedding.embedding <=>'))
  assert.match(search.sql, /source_generation = \$2/)
  assert.deepEqual(search.parameters, [
    bindingHash,
    sourceGeneration,
    projectionScope,
    `catalog-embedding-active-v1:${bindingHash}`,
    '[1,0]',
    5,
  ])
})

test('rejects arbitrary gateway paths and non-allowlisted DAGs', async () => {
  const missing = await fetch(new URL('/poc-api/arbitrary-proxy', origin))
  assert.equal(missing.status, 404)
  const dag = await fetch(new URL('/poc-api/airflow/dags/arbitrary/runs', origin), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: Buffer.from('{}'),
  })
  assert.equal(dag.status, 400)
  const minio = await fetch(new URL('/poc-api/minio/uploads/upload-1/parts/1', origin), {
    method: 'PUT',
    body: Buffer.from('sample'),
  })
  assert.equal(minio.status, 503)
})
