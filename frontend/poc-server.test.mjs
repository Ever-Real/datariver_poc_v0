/* global Buffer, fetch, structuredClone */
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import process from 'node:process'
import { after, before, test } from 'node:test'
import { URL } from 'node:url'

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

test('defaults the native Node listener to loopback and preserves an explicit container override', async () => {
  const { resolvePocServerHost } = await import('./poc-server.mjs?listener-host-contract-test')
  assert.equal(resolvePocServerHost({}), '127.0.0.1')
  assert.equal(resolvePocServerHost({ POC_SERVER_HOST: ' 0.0.0.0 ' }), '0.0.0.0')
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

test('fails closed when the server active subject is not configured', async () => {
  const response = await fetch(new URL('/api/v1/change-history/access', origin))
  assert.equal(response.status, 503)
  assert.equal((await response.json()).code, 'ACCESS_NOT_CONFIGURED')
})

test('makes access state server-authoritative with bootstrap, role, spoof, CAS, and core fences', async () => {
  const previousSubject = process.env.POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID
  delete process.env.POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID
  const { createPocStateStore } = await import('./poc-state-store.mjs?access-authority-contract')
  const { createPocServer } = await import('./poc-server.mjs?access-authority-contract')
  const stateStore = createPocStateStore()
  const originalChangeRecords = [{ id: 'change-request-preserved', state: 'IN_REVIEW', current_round_number: 2, version: 9 }]
  await stateStore.write('core', { sequence: 42, changeRecords: originalChangeRecords })

  const servers = []
  const listen = async (activeSubjectId, selectedStore = stateStore) => {
    const authorityServer = createPocServer({ stateStore: selectedStore, activeSubjectId })
    await new Promise((resolvePromise) => authorityServer.listen(0, '127.0.0.1', resolvePromise))
    servers.push(authorityServer)
    const address = authorityServer.address()
    assert.equal(typeof address, 'object')
    return `http://127.0.0.1:${address.port}`
  }
  const request = (authorityOrigin, options = {}) => fetch(
    new URL('/api/v1/change-history/access', authorityOrigin),
    options,
  )
  const document = {
    schema_version: 1,
    active_subject_id: 'configured-admin',
    users: [
      {
        subject_id: 'configured-admin', role: 'admin', active: true,
        username: 'configured.admin', display_name: 'Configured Admin', email: 'admin@poc.invalid',
        first_name: 'Configured', last_name: 'Admin', department_id: null, job_function: 'admin',
      },
      { subject_id: 'steward-subject', role: 'data_steward', active: true },
      { subject_id: 'developer-subject', role: 'developer', active: true },
      { subject_id: 'viewer-subject', role: 'viewer', active: true },
      { subject_id: 'inactive-subject', role: 'admin', active: false },
    ],
    systems: [{
      system_id: 'business-system', code: 'BUSINESS', name: 'Business System', description: '', active: true,
    }],
    system_schema_scopes: [{
      scope_id: 'business-schema', system_id: 'business-system', platform: ' Postgres ',
      database_name: 'business_db', schema_name: 'public', active: true,
    }],
    system_assignments: [{
      system_id: 'business-system', subject_id: 'steward-subject', responsibility: 'DATA_STEWARD',
      priority: 1, active: true,
    }],
  }

  try {
    const adminOrigin = await listen('configured-admin')
    const put = (authorityOrigin, body, ifMatch = '"0"', headers = {}) => request(authorityOrigin, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'If-Match': ifMatch, ...headers },
      body: JSON.stringify(body),
    })

    const selfAppointedViewer = await put(adminOrigin, {
      ...document,
      users: document.users.map((user) => user.subject_id === 'configured-admin'
        ? { ...user, role: 'viewer' }
        : user),
    })
    assert.equal(selfAppointedViewer.status, 403)
    assert.equal((await stateStore.readChangeHistoryAccess()).access.value, null)

    const bootstrap = await put(adminOrigin, { ...document, active_subject_id: 'steward-subject' })
    assert.equal(bootstrap.status, 200)
    assert.equal(bootstrap.headers.get('etag'), '"1"')
    const bootstrapped = await bootstrap.json()
    assert.equal(bootstrapped.version, 1)
    assert.equal(bootstrapped.active_subject_id, 'steward-subject')
    assert.equal(bootstrapped.users[0].display_name, 'Configured Admin')
    assert.equal(bootstrapped.users[0].email, 'admin@poc.invalid')
    assert.equal(bootstrapped.system_schema_scopes[0].platform, 'postgres')
    assert.deepEqual((await stateStore.read('core')).value.changeRecords, originalChangeRecords)
    assert.equal((await request(adminOrigin)).status, 200, 'stored active metadata is not runtime identity authority')

    const privateRead = await fetch(new URL('/poc-api/state/change-history-access-v1', adminOrigin))
    assert.equal(privateRead.status, 404)
    const spoofed = await request(adminOrigin, { headers: { 'X-Subject-Id': 'viewer-subject' } })
    assert.equal(spoofed.status, 400)
    assert.equal((await spoofed.json()).code, 'PROTECTED_CLAIM')
    const bodySpoof = await put(adminOrigin, { ...document, actor_ref: 'browser-actor' }, '"1"')
    assert.equal(bodySpoof.status, 400)
    assert.equal((await bodySpoof.json()).code, 'PROTECTED_CLAIM')

    const stale = await put(adminOrigin, document)
    assert.equal(stale.status, 409)
    assert.equal((await stale.json()).code, 'ACCESS_VERSION_STALE')
    const noMatch = await request(adminOrigin, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(document),
    })
    assert.equal(noMatch.status, 428)

    const ambiguous = await put(adminOrigin, {
      ...document,
      systems: [...document.systems, {
        system_id: 'second-system', code: 'SECOND', name: 'Second System', description: '', active: true,
      }],
      system_schema_scopes: [...document.system_schema_scopes, {
        scope_id: 'duplicate-business-schema', system_id: 'second-system', platform: 'postgres',
        database_name: 'business_db', schema_name: 'public', active: true,
      }],
    }, '"1"')
    assert.equal(ambiguous.status, 400)
    assert.equal((await ambiguous.json()).code, 'ACCESS_DOCUMENT_INVALID')

    for (const [subjectId, role, active, status] of [
      ['steward-subject', 'data_steward', true, 403],
      ['developer-subject', 'developer', true, 403],
      ['viewer-subject', 'viewer', true, 403],
      ['inactive-subject', 'admin', false, 401],
    ]) {
      const roleStore = createPocStateStore()
      await roleStore.writeChangeHistoryAccess({
        expectedAccessVersion: 0,
        expectedCoreVersion: 0,
        accessValue: {
          schema_version: 1, active_subject_id: 'stored-admin',
          users: [{ subject_id: subjectId, role, active, provider_owner_refs: [] }],
          system_assignments: [],
        },
        coreValue: {
          adminMemberships: [], adminSystems: [], adminSystemAssignees: [], adminSystemSchemaScopes: [],
        },
      })
      const roleOrigin = await listen(subjectId, roleStore)
      assert.equal((await request(roleOrigin)).status, status, subjectId)
      assert.equal((await put(roleOrigin, {
        schema_version: 1,
        active_subject_id: subjectId,
        users: [{ subject_id: subjectId, role, active }],
        systems: [], system_schema_scopes: [], system_assignments: [],
      }, '"1"')).status, status, `${subjectId} PUT`)
    }
    const unknownOrigin = await listen('unknown-subject')
    assert.equal((await request(unknownOrigin)).status, 401)

    const genericWrite = await fetch(new URL('/poc-api/state/core', adminOrigin), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: {
        sequence: 43,
        changeRecords: [{ ...originalChangeRecords[0], state: 'TESTING' }],
        adminMemberships: [], adminSystems: [], adminSystemAssignees: [], adminSystemSchemaScopes: [],
      } }),
    })
    assert.equal(genericWrite.status, 200)
    const afterGeneric = (await stateStore.read('core')).value
    assert.equal(afterGeneric.changeRecords[0].state, 'TESTING')
    assert.equal(afterGeneric.adminSystems[0].system_id, 'business-system')
    assert.equal(afterGeneric.adminMemberships.length, document.users.length)
    assert.equal(afterGeneric.adminMemberships.find((item) => item.subject_id === 'configured-admin').display_name, 'Configured Admin')

    const crBeforeAccessUpdate = JSON.parse(JSON.stringify(afterGeneric.changeRecords))
    const updatedDocument = {
      ...document,
      users: document.users.map((user) => user.subject_id === 'configured-admin'
        ? { ...user, display_name: 'Updated Admin', job_function: 'platform_admin' }
        : user),
      system_assignments: [{ ...document.system_assignments[0], priority: 2 }],
    }
    const update = await put(adminOrigin, updatedDocument, '"1"')
    assert.equal(update.status, 200)
    assert.equal(update.headers.get('etag'), '"2"')
    assert.deepEqual((await stateStore.read('core')).value.changeRecords, crBeforeAccessUpdate)
    assert.equal((await stateStore.read('core')).value.adminMemberships
      .find((item) => item.subject_id === 'configured-admin').display_name, 'Updated Admin')
    assert.equal((await request(adminOrigin)).status, 200)

    const primitiveCore = await fetch(new URL('/poc-api/state/core', adminOrigin), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: 'browser-replacement' }),
    })
    assert.equal(primitiveCore.status, 409)
    assert.equal((await primitiveCore.json()).code, 'CORE_ACCESS_FIELDS_PROTECTED')
  } finally {
    if (previousSubject === undefined) delete process.env.POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID
    else process.env.POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID = previousSubject
    for (const authorityServer of servers) {
      authorityServer.closeAllConnections()
      await new Promise((resolvePromise, reject) => authorityServer.close((error) => (
        error ? reject(error) : resolvePromise()
      )))
    }
  }
})

test('accepts the active subject from the dedicated server environment only', async () => {
  const previousSubject = process.env.POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID
  process.env.POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID = 'environment-admin'
  const { createPocStateStore } = await import('./poc-state-store.mjs?access-environment-contract')
  const { createPocServer } = await import('./poc-server.mjs?access-environment-contract')
  const stateStore = createPocStateStore()
  const environmentServer = createPocServer({ stateStore })
  delete process.env.POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID
  await new Promise((resolvePromise) => environmentServer.listen(0, '127.0.0.1', resolvePromise))
  const address = environmentServer.address()
  assert.equal(typeof address, 'object')
  try {
    const response = await fetch(`http://127.0.0.1:${address.port}/api/v1/change-history/access`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'If-Match': '"0"' },
      body: JSON.stringify({
        schema_version: 1,
        active_subject_id: 'environment-admin',
        users: [{ subject_id: 'environment-admin', role: 'admin', active: true }],
        systems: [],
        system_schema_scopes: [],
        system_assignments: [],
      }),
    })
    assert.equal(response.status, 200)
  } finally {
    if (previousSubject === undefined) delete process.env.POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID
    else process.env.POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID = previousSubject
    environmentServer.closeAllConnections()
    await new Promise((resolvePromise, reject) => environmentServer.close((error) => (
      error ? reject(error) : resolvePromise()
    )))
  }
})

test('serves authoritative change-history reads, reverse lookup, weekly aggregation, and zero-effect link commands', async () => {
  const { createPocServer } = await import('./poc-server.mjs?change-history-api-contract')
  const eventId = '1'.repeat(64)
  const transactionId = '2'.repeat(64)
  const assetUrn = 'urn:li:dataset:(urn:li:dataPlatform:postgres,business_db.public.orders,PROD)'
  const changeRequest = {
    id: 'poc-change-request-1', state: 'IN_REVIEW', current_round_id: 'round-1',
    current_round_number: 1, version: 7,
    rounds: [{ id: 'round-1', selected_system_id: 'business-system' }],
    items: [{ routing_system_id: 'business-system' }], approvals: [], transitions: [],
  }
  const projection = {
    access: { version: 3, value: {
      schema_version: 1, active_subject_id: 'admin-subject',
      policy: { version: 1, priority_order: 'ASCENDING', fallback: ['DATA_STEWARD', 'DEVELOPER', 'DATAHUB_OWNER', 'UNASSIGNED'] },
      users: [
        { subject_id: 'admin-subject', role: 'admin', active: true, provider_owner_refs: [] },
        { subject_id: 'steward-subject', role: 'data_steward', active: true, provider_owner_refs: [] },
      ],
      system_assignments: [{ system_id: 'business-system', subject_id: 'steward-subject', responsibility: 'DATA_STEWARD', priority: 1, active: true }],
    } },
    core: { version: 5, value: {
      changeRecords: [changeRequest],
      adminSystems: [{ system_id: 'business-system', code: 'BUSINESS', name: 'Business', description: '', active: true, version: 1 }],
      adminSystemSchemaScopes: [['business-system', [{ scope_id: 'scope-1', system_id: 'business-system', platform: 'postgres', database_name: 'business_db', schema_name: 'public', active: true, version: 1 }]]],
    } },
    catalog: { version: 2, value: {
      projection_version: 1, source_scope: 'disabled', source_generation: 'a'.repeat(64), observed_at: '2026-08-14T00:00:00.000Z',
      items: [{ id: assetUrn, name: 'orders', platform: 'postgres', database_name: 'business_db', schema_name: 'public' }],
    } },
    events: [{
      event_identity: eventId, event_hash: '3'.repeat(64), normalized_change_transaction_id: transactionId,
      source_identity_hash: '9'.repeat(64), topic_contract: 'MetadataChangeLog_Versioned_v1', source_partition: 0, source_offset: 10,
      asset_urn: assetUrn, normalized_entity_key: 'business_db.public.orders', category: 'TECHNICAL_SCHEMA',
      source_aspect: 'schemaMetadata', operation: 'UPDATE', before_data: { nullable: true }, after_data: { nullable: false },
      actor_ref: null, source_occurred_at: '2026-08-11T01:00:00.000Z', detected_at: '2026-08-11T01:00:01.000Z', captured_at: '2026-08-11T01:00:02.000Z',
    }],
    links: [],
    sources: [{ source_identity_hash: '9'.repeat(64), provider_name: 'DataHub', provider_version: 'contract-test', schema_contract_hash: '8'.repeat(64), created_at: '2026-08-11T00:00:00.000Z' }],
    checkpoints: [{ source_identity_hash: '9'.repeat(64), topic_contract: 'MetadataChangeLog_Versioned_v1', source_partition: 0, first_exact_offset: 10, next_offset: 11, last_captured_at: '2026-08-11T01:00:02.000Z', version: 2 }],
  }
  let appendCommand
  const replayCommands = new Map()
  const stateStore = {
    configured: { postgres: true, redis: false },
    async readChangeHistoryProjection({ catalogScope }) {
      assert.equal(catalogScope, 'catalog-inventory-v1:disabled')
      return structuredClone(projection)
    },
    async readChangeHistoryCrLinkReplay(command) {
      const stored = replayCommands.get(command.idempotencyKey)
      if (!stored) return null
      if (stored.reason !== command.reason || stored.action !== command.action) {
        throw Object.assign(new Error('idempotency conflict'), { code: 'IDEMPOTENCY_CONFLICT', statusCode: 409 })
      }
      return { ...stored.result, replayed: true }
    },
    async appendChangeHistoryCrLink(command) {
      appendCommand = command
      assert.deepEqual(projection.core.value.changeRecords, [changeRequest])
      const linkVersion = projection.links.length + 1
      const result = {
        linkEventIdentity: String(3 + linkVersion).repeat(64),
        eventHash: String(4 + linkVersion).repeat(64),
        linkVersion,
        replayed: false,
      }
      projection.links.push({
        link_event_identity: result.linkEventIdentity, event_hash: result.eventHash,
        ledger_event_identity: eventId, link_version: linkVersion, link_kind: command.linkKind, action: command.action,
        change_request_id: command.changeRequestId, change_request_round: command.changeRequestRound, prior_link_hash: command.priorLinkHash,
        reason: command.reason, policy_hash: command.policyHash, basis_hash: command.basisHash,
        actor_ref: command.actorRef, occurred_at: command.occurredAt, captured_at: command.occurredAt,
      })
      replayCommands.set(command.idempotencyKey, { ...command, result })
      return result
    },
  }
  const server = createPocServer({ stateStore, activeSubjectId: 'admin-subject' })
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  assert.equal(typeof address, 'object')
  const base = `http://127.0.0.1:${address.port}`
  try {
    const list = await fetch(`${base}/api/v1/change-history/events`)
    assert.equal(list.status, 200)
    const listed = await list.json()
    assert.equal(listed.total, 1)
    assert.deepEqual(listed.items[0], {
      ...listed.items[0],
      change_type: 'SCHEMA_CHANGE',
      precision: 'EXACT_MCL',
      current_stage: 'UNLINKED',
      allowed_link_actions: ['SET_PRIMARY', 'CLEAR_PRIMARY', 'ADD_CANDIDATE', 'REMOVE_CANDIDATE'],
      locator: { platform: 'postgres', database_name: 'business_db', schema_name: 'public', asset_name: 'orders' },
    })
    assert.equal(listed.items[0].system.system_id, 'business-system')
    const filtered = await (await fetch(`${base}/api/v1/change-history/events?week_start=2026-08-10&change_type=SCHEMA_CHANGE&category=TECHNICAL_SCHEMA&precision=EXACT_MCL&operation=UPDATE&platform=postgres&database_name=business_db&schema_name=public&system_id=business-system&assignee_subject_id=steward-subject&link_state=UNLINKED&stage=UNLINKED`)).json()
    assert.equal(filtered.total, 1)
    assert.equal((await fetch(`${base}/api/v1/change-history/events?precision=GUESSED`)).status, 400)
    assert.equal((await fetch(`${base}/api/v1/change-history/events?stage=UNKNOWN`)).status, 400)
    const detail = await fetch(`${base}/api/v1/change-history/events/${eventId}`)
    assert.equal(detail.headers.get('etag'), '"0"')
    assert.equal((await detail.json()).assignee.subject_id, 'steward-subject')
    const before = JSON.stringify(projection.core.value.changeRecords)
    const linked = await fetch(`${base}/api/v1/change-history/events/${eventId}/cr-link-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'link-1', 'If-Match': '"0"' },
      body: JSON.stringify({ action: 'SET_PRIMARY', change_request_id: changeRequest.id, change_request_round: 1, reason: 'reviewed link' }),
    })
    assert.equal(linked.status, 201)
    assert.equal(linked.headers.get('etag'), `"${'5'.repeat(64)}"`)
    assert.equal(appendCommand.actorRef, 'admin-subject')
    assert.equal(JSON.stringify(projection.core.value.changeRecords), before)
    const linkHistory = await fetch(`${base}/api/v1/change-history/events/${eventId}/cr-links`)
    assert.equal(linkHistory.headers.get('etag'), `"${'5'.repeat(64)}"`)
    assert.equal((await linkHistory.json()).items[0].link_version, 1)
    const replay = await fetch(`${base}/api/v1/change-history/events/${eventId}/cr-link-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'link-1', 'If-Match': '"0"' },
      body: JSON.stringify({ action: 'SET_PRIMARY', change_request_id: changeRequest.id, change_request_round: 1, reason: 'reviewed link' }),
    })
    assert.equal(replay.status, 200)
    assert.equal((await replay.json()).replayed, true)
    const conflict = await fetch(`${base}/api/v1/change-history/events/${eventId}/cr-link-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'link-1', 'If-Match': `"${'5'.repeat(64)}"` },
      body: JSON.stringify({ action: 'SET_PRIMARY', change_request_id: changeRequest.id, change_request_round: 1, reason: 'different' }),
    })
    assert.equal(conflict.status, 409)
    const reverse = await fetch(`${base}/api/v1/change-requests/${changeRequest.id}/change-history`)
    assert.equal((await reverse.json()).items.length, 1)
    const addCandidate = await fetch(`${base}/api/v1/change-history/events/${eventId}/cr-link-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'link-2', 'If-Match': `"${'5'.repeat(64)}"` },
      body: JSON.stringify({ action: 'ADD_CANDIDATE', change_request_id: changeRequest.id, change_request_round: 1, reason: 'candidate' }),
    })
    assert.equal(addCandidate.status, 201)
    const removeCandidate = await fetch(`${base}/api/v1/change-history/events/${eventId}/cr-link-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'link-3', 'If-Match': `"${'6'.repeat(64)}"` },
      body: JSON.stringify({ action: 'REMOVE_CANDIDATE', change_request_id: changeRequest.id, change_request_round: 1, reason: 'remove candidate' }),
    })
    assert.equal(removeCandidate.status, 201)
    const clearPrimary = await fetch(`${base}/api/v1/change-history/events/${eventId}/cr-link-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'link-4', 'If-Match': `"${'7'.repeat(64)}"` },
      body: JSON.stringify({ action: 'CLEAR_PRIMARY', change_request_id: changeRequest.id, change_request_round: 1, reason: 'clear primary' }),
    })
    assert.equal(clearPrimary.status, 201)
    assert.equal(JSON.stringify(projection.core.value.changeRecords), before)

    projection.events.push(
      {
        ...projection.events[0], event_identity: 'a'.repeat(64), event_hash: 'b'.repeat(64),
        normalized_entity_key: 'business_db.public.orders.description', category: 'DOCUMENTATION',
        source_aspect: 'datasetProperties',
      },
      {
        ...projection.events[0], event_identity: 'b'.repeat(64), event_hash: 'c'.repeat(64),
        normalized_entity_key: 'business_db.public.orders.description-duplicate', category: 'DOCUMENTATION',
        source_aspect: 'datasetProperties',
      },
    )
    for (const [index, event] of projection.events.entries()) {
      projection.links.push({
        ledger_event_identity: event.event_identity,
        link_event_identity: ['d', 'e', 'f'][index].repeat(64),
        event_hash: ['a', 'b', 'c'][index].repeat(64),
        link_version: 10,
        link_kind: 'PRIMARY',
        action: 'SET_PRIMARY',
        change_request_id: changeRequest.id,
        change_request_round: 1,
      })
    }

    const pagedEventIds = []
    let cursor = null
    do {
      const cursorQuery = cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''
      const page = await (await fetch(`${base}/api/v1/change-history/events?limit=1${cursorQuery}`)).json()
      assert.equal(page.total, 3)
      assert.equal(page.limit, 1)
      assert.equal(page.items.length, 1)
      pagedEventIds.push(page.items[0].event_id)
      assert.notEqual(page.next_cursor, cursor)
      cursor = page.next_cursor
    } while (cursor)
    assert.equal(new Set(pagedEventIds).size, 3)

    const lifecycleEventId = 'c'.repeat(64)
    projection.events.push({
      ...projection.events[0], event_identity: lifecycleEventId, event_hash: 'd'.repeat(64),
      normalized_change_transaction_id: 'e'.repeat(64), normalized_entity_key: 'asset:lifecycle:removed',
      category: 'LIFECYCLE', source_aspect: 'status', operation: 'DELETE',
      before_data: { removed: false }, after_data: { removed: true },
    })
    const lifecycleList = await (await fetch(`${base}/api/v1/change-history/events?category=LIFECYCLE`)).json()
    assert.equal(lifecycleList.total, 1)
    assert.deepEqual(lifecycleList.items[0], {
      ...lifecycleList.items[0], category: 'LIFECYCLE', change_type: 'METADATA_CHANGE',
      source_aspect: 'status', operation: 'DELETE', entity_key: 'asset:lifecycle:removed',
    })
    const lifecycleDetail = await (await fetch(`${base}/api/v1/change-history/events/${lifecycleEventId}`)).json()
    assert.deepEqual(lifecycleDetail.before, { removed: false })
    assert.deepEqual(lifecycleDetail.after, { removed: true })

    const weekly = await fetch(`${base}/api/v1/change-history/weekly?week_start=2026-08-10`)
    assert.equal(weekly.status, 200)
    const summary = await weekly.json()
    assert.equal(summary.week_start, '2026-08-10')
    assert.equal(summary.week_end_exclusive, '2026-08-17')
    assert.equal(summary.total_count, 2)
    assert.equal(summary.received_count, 1)
    assert.equal(summary.total_count, summary.unlinked_count + summary.received_count + summary.recheck_count
      + summary.testing_count + summary.final_review_count + summary.completed_count)
    const sourceSummary = await (await fetch(`${base}/api/v1/change-history/summary?week_start=2026-08-10`)).json()
    assert.equal(sourceSummary.schema_change_count, 1)
    assert.equal(sourceSummary.metadata_change_count, 2)
    assert.equal(sourceSummary.event_count, 4)
    assert.equal(sourceSummary.precision_counts.EXACT_MCL, 2)
    assert.equal(sourceSummary.category_counts.TECHNICAL_SCHEMA, 1)
    assert.equal(sourceSummary.category_counts.DOCUMENTATION, 1)
    assert.equal(sourceSummary.category_counts.LIFECYCLE, 1)
    assert.equal(sourceSummary.operation_counts.UPDATE, 1)
    assert.equal(sourceSummary.operation_counts.DELETE, 1)
    assert.equal(sourceSummary.sync_status, 'CONTIGUOUS_CAPTURE_RECORDED')
    assert.equal(sourceSummary.source_generation, 'a'.repeat(64))
    assert.equal(sourceSummary.ledger_guarantee_from, '2026-08-11T01:00:02.000Z')

    projection.core.value.changeRecords[0].current_round_number = 2
    const resubmittedSummary = await (await fetch(`${base}/api/v1/change-history/weekly?week_start=2026-08-10`)).json()
    assert.equal(resubmittedSummary.recheck_count, 1)
    assert.equal(resubmittedSummary.received_count, 0)
    projection.core.value.changeRecords[0].state = 'CANCELLED'
    const cancelledSummary = await (await fetch(`${base}/api/v1/change-history/weekly?week_start=2026-08-10`)).json()
    assert.equal(cancelledSummary.unlinked_count, 2)
    assert.equal(cancelledSummary.recheck_count, 0)
    projection.core.value.changeRecords[0].state = 'IN_REVIEW'
    projection.core.value.changeRecords[0].current_round_number = 1

    const invalidTuesday = await fetch(`${base}/api/v1/change-history/weekly?week_start=2026-08-11`)
    assert.equal(invalidTuesday.status, 400)
    assert.equal((await invalidTuesday.json()).code, 'WEEK_START_INVALID')
    projection.core.value.changeRecords[0].state = 'REJECTED'
    const rejectedSummary = await (await fetch(`${base}/api/v1/change-history/weekly?week_start=2026-08-10`)).json()
    assert.equal(rejectedSummary.unlinked_count, 2)
    assert.equal(rejectedSummary.received_count, 0)
    const spoofed = await fetch(`${base}/api/v1/change-history/events`, { headers: { 'X-Subject-Id': 'steward-subject' } })
    assert.equal(spoofed.status, 400)
  } finally {
    server.closeAllConnections()
    await new Promise((resolvePromise, reject) => server.close((error) => error ? reject(error) : resolvePromise()))
  }
})

test('prunes assigned-role rows, keeps viewer read-only, and fails closed on stale or unmapped mutations', async () => {
  const { createPocServer } = await import('./poc-server.mjs?change-history-role-contract')
  const eventId = '6'.repeat(64)
  const event = {
    event_identity: eventId, event_hash: '7'.repeat(64), normalized_change_transaction_id: '8'.repeat(64),
    asset_urn: 'urn:asset:one', normalized_entity_key: 'one', category: 'TAG', source_aspect: 'globalTags', operation: 'ADD',
    before_data: {}, after_data: {}, source_occurred_at: '2026-08-11T01:00:00.000Z', detected_at: '2026-08-11T01:00:01.000Z', captured_at: '2026-08-11T01:00:02.000Z',
  }
  const baseProjection = {
    access: { version: 1, value: {
      schema_version: 1, active_subject_id: 'stored-admin',
      policy: { version: 1, priority_order: 'ASCENDING', fallback: ['DATA_STEWARD', 'DEVELOPER', 'DATAHUB_OWNER', 'UNASSIGNED'] },
      users: [{ subject_id: 'role-subject', role: 'viewer', active: true, provider_owner_refs: [] }], system_assignments: [],
    } },
    core: { version: 1, value: {
      changeRecords: [{ id: 'cr-1', current_round_id: 'r1', current_round_number: 1, state: 'REGISTERED', rounds: [{ id: 'r1', selected_system_id: 'system-1' }], items: [{ routing_system_id: 'system-1' }] }],
      adminSystems: [{ system_id: 'system-1', code: 'ONE', name: 'One', active: true, version: 1 }],
      adminSystemSchemaScopes: [['system-1', [{ scope_id: 's1', system_id: 'system-1', platform: 'postgres', database_name: 'db', schema_name: 'public', active: true, version: 1 }]]],
    } },
    catalog: { version: 1, value: { projection_version: 1, source_scope: 'disabled', source_generation: '9'.repeat(64), observed_at: '2026-08-14T00:00:00.000Z', items: [{ id: event.asset_urn, platform: 'postgres', database_name: 'db', schema_name: 'public' }] } },
    events: [event], links: [],
  }
  const run = async (projection, action) => {
    let appendCalls = 0
    const stateStore = {
      configured: { postgres: true, redis: false },
      async readChangeHistoryProjection() { return structuredClone(projection) },
      async appendChangeHistoryCrLink() { appendCalls += 1; return { linkEventIdentity: 'a'.repeat(64), eventHash: 'b'.repeat(64), linkVersion: 1, replayed: false } },
    }
    const roleServer = createPocServer({ stateStore, activeSubjectId: 'role-subject' })
    await new Promise((resolvePromise) => roleServer.listen(0, '127.0.0.1', resolvePromise))
    const address = roleServer.address()
    try { return { result: await action(`http://127.0.0.1:${address.port}`), appendCalls } } finally {
      roleServer.closeAllConnections()
      await new Promise((resolvePromise, reject) => roleServer.close((error) => error ? reject(error) : resolvePromise()))
    }
  }
  const viewerRead = await run(baseProjection, (origin) => fetch(`${origin}/api/v1/change-history/events`))
  const viewerItems = (await viewerRead.result.json()).items
  assert.equal(viewerItems.length, 1)
  assert.deepEqual(viewerItems[0].allowed_link_actions, [])
  const viewerWrite = await run(baseProjection, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}/cr-link-events`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'k', 'If-Match': '"0"' },
    body: JSON.stringify({ action: 'SET_PRIMARY', change_request_id: 'cr-1', change_request_round: 1, reason: 'no' }),
  }))
  assert.equal(viewerWrite.result.status, 403)
  assert.equal(viewerWrite.appendCalls, 0)
  const steward = structuredClone(baseProjection)
  steward.access.value.users[0].role = 'data_steward'
  const hidden = await run(steward, (origin) => fetch(`${origin}/api/v1/change-history/events`))
  assert.equal((await hidden.result.json()).items.length, 0)
  steward.access.value.system_assignments = [{ system_id: 'system-1', subject_id: 'role-subject', responsibility: 'DATA_STEWARD', priority: 1, active: true }]
  const visible = await run(steward, (origin) => fetch(`${origin}/api/v1/change-history/events`))
  const stewardItems = (await visible.result.json()).items
  assert.equal(stewardItems.length, 1)
  assert.deepEqual(stewardItems[0].allowed_link_actions, ['SET_PRIMARY', 'CLEAR_PRIMARY', 'ADD_CANDIDATE', 'REMOVE_CANDIDATE'])
  const mutate = (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}/cr-link-events`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'assigned-key', 'If-Match': '"0"' },
    body: JSON.stringify({ action: 'SET_PRIMARY', change_request_id: 'cr-1', change_request_round: 1, reason: 'assigned' }),
  })
  const stewardMutation = await run(steward, mutate)
  assert.equal(stewardMutation.result.status, 201)
  assert.equal(stewardMutation.appendCalls, 1)
  const developer = structuredClone(steward)
  developer.access.value.users[0].role = 'developer'
  assert.equal((await (await run(developer, (origin) => fetch(`${origin}/api/v1/change-history/events`))).result.json()).items.length, 0)
  developer.access.value.system_assignments[0].responsibility = 'DEVELOPER'
  assert.equal((await (await run(developer, (origin) => fetch(`${origin}/api/v1/change-history/events`))).result.json()).items.length, 1)
  const developerMutation = await run(developer, mutate)
  assert.equal(developerMutation.result.status, 201)
  assert.equal(developerMutation.appendCalls, 1)
  const unmapped = structuredClone(steward)
  unmapped.catalog.value.items = []
  const rejected = await run(unmapped, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}/cr-link-events`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'k', 'If-Match': '"0"' },
    body: JSON.stringify({ action: 'SET_PRIMARY', change_request_id: 'cr-1', change_request_round: 1, reason: 'no' }),
  }))
  assert.equal(rejected.result.status, 404, 'assigned roles cannot observe or mutate unmapped rows')
  assert.equal(rejected.appendCalls, 0)
  const adminUnmapped = structuredClone(unmapped)
  adminUnmapped.access.value.users[0].role = 'admin'
  const adminRejected = await run(adminUnmapped, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}/cr-link-events`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'k', 'If-Match': '"0"' },
    body: JSON.stringify({ action: 'SET_PRIMARY', change_request_id: 'cr-1', change_request_round: 1, reason: 'no' }),
  }))
  assert.equal(adminRejected.result.status, 409)
  assert.equal((await adminRejected.result.json()).code, 'SYSTEM_MAPPING_UNRESOLVED')
  const stale = structuredClone(steward)
  stale.links = [{ ledger_event_identity: eventId, event_hash: 'c'.repeat(64), link_version: 1, link_event_identity: 'd'.repeat(64), link_kind: 'CANDIDATE', action: 'ADD_CANDIDATE', change_request_id: 'cr-1', change_request_round: 1, occurred_at: '2026-08-11T02:00:00.000Z' }]
  const staleResponse = await run(stale, (origin) => fetch(`${origin}/api/v1/change-history/events/${eventId}/cr-link-events`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'k', 'If-Match': '"0"' },
    body: JSON.stringify({ action: 'SET_PRIMARY', change_request_id: 'cr-1', change_request_round: 1, reason: 'no' }),
  }))
  assert.equal(staleResponse.result.status, 409)
  assert.equal(staleResponse.appendCalls, 0)
})
