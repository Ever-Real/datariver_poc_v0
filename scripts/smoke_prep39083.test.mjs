import assert from 'node:assert/strict'
import { chmod, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { spawn } from 'node:child_process'
import test from 'node:test'

const script = resolve(import.meta.dirname, 'smoke_prep39083.mjs')

async function fixture(k9Mode) {
  const directory = await mkdtemp(join(tmpdir(), 'prep39083-smoke-'))
  const passwordFile = join(directory, 'password')
  const output = join(directory, 'smoke.json')
  await writeFile(passwordFile, 'non-secret-test-password\n')
  await chmod(passwordFile, 0o600)
  let managedRequests = 0
  const server = createServer((request, response) => {
    const json = (status, body, headers = {}) => {
      response.writeHead(status, { 'Content-Type': 'application/json', ...headers })
      response.end(JSON.stringify(body))
    }
    if (request.url === '/healthz') {
      response.writeHead(200, { 'Content-Type': 'text/plain' })
      response.end('ok')
    } else if (request.url === '/auth/login') {
      json(200, { status: 'PASS' }, { 'Set-Cookie': 'session=opaque; HttpOnly' })
    } else if (request.url === '/auth/logout') {
      json(200, { status: 'PASS' })
    } else if (request.url === '/poc-api/datahub/catalog?limit=1') {
      json(200, { items: [] })
    } else if (request.url === '/poc-api/knowledge/managed-assets') {
      managedRequests += 1
      json(200, { items: [
        { graph_type: 'LINEAGE', is_default: true, status: 'READY', refresh_mode: 'DAILY', semantic_index_status: 'READY' },
        { graph_type: 'METADATA_MASTER', status: 'READY', refresh_mode: 'DAILY', semantic_index_status: 'READY' },
      ] })
    } else if (request.url === '/poc-api/llm/chat') {
      json(200, { route: { selected_mode: 'GENERAL' }, evidence: [] })
    } else {
      json(404, { error: 'not found' })
    }
  })
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  assert(address && typeof address === 'object')
  const completed = await new Promise((resolvePromise) => {
    const child = spawn(process.execPath, [
      script,
      '--origin', `http://127.0.0.1:${address.port}`,
      '--username', 'admin',
      '--password-file', passwordFile,
      '--k9-mode', k9Mode,
      '--readiness-timeout-ms', '5000',
      '--output', output,
    ], { stdio: ['ignore', 'pipe', 'pipe'] })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', (chunk) => { stdout += chunk })
    child.stderr.on('data', (chunk) => { stderr += chunk })
    child.on('close', (code) => resolvePromise({ code, stdout, stderr }))
  })
  server.close()
  const report = JSON.parse(await readFile(output, 'utf8'))
  await rm(directory, { recursive: true, force: true })
  return { completed, report, managedRequests }
}

test('PREP smoke accepts K9 deferred without requesting managed graph assets', async () => {
  const result = await fixture('deferred')
  assert.equal(result.completed.code, 0, result.completed.stderr)
  assert.equal(result.managedRequests, 0)
  assert.equal(result.report.k9_mode, 'DEFERRED')
  assert.equal(result.report.managed_assets, 'DEFERRED')
  assert.equal(result.report.datahub, 'PASS')
  assert.equal(result.report.llm_general, 'PASS')
})

test('PREP smoke retains strict managed graph gates when K9 is configured', async () => {
  const result = await fixture('required')
  assert.equal(result.completed.code, 0, result.completed.stderr)
  assert.equal(result.managedRequests, 1)
  assert.equal(result.report.k9_mode, 'REQUIRED')
  assert.equal(result.report.managed_assets, 'PASS')
  assert.equal(result.report.semantic_index, 'PASS')
})
