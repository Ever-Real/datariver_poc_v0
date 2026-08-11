/* global Buffer, URL, fetch, process */
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { after, before, test } from 'node:test'
import { createPocServer } from './poc-server.mjs'

let server
let origin

before(async () => {
  server = createPocServer()
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  assert.equal(typeof address, 'object')
  origin = `http://127.0.0.1:${address.port}`
})

after(async () => {
  await new Promise((resolvePromise, reject) => server.close((error) => error ? reject(error) : resolvePromise()))
})

test('serves the POC at the root with the runtime boundary', async () => {
  const response = await fetch(origin)
  assert.equal(response.status, 200)
  assert.match(response.headers.get('content-security-policy'), /connect-src 'self'/)
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
