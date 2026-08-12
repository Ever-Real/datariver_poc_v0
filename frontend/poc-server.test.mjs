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
