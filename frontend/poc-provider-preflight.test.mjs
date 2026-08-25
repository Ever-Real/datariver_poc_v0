import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { resolve } from 'node:path'
import process from 'node:process'
import { spawn } from 'node:child_process'
import test from 'node:test'

const script = resolve(import.meta.dirname, 'poc-provider-preflight.mjs')

async function fixture({ chatStatus = 200, environment = {} } = {}) {
  const server = createServer((request, response) => {
    const json = (status, body) => {
      response.writeHead(status, { 'Content-Type': 'application/json' })
      response.end(JSON.stringify(body))
    }
    if (request.url === '/api/graphql') json(200, { data: { search: { start: 0, count: 1, total: 1 } } })
    else if (request.url === '/chat/completions') json(chatStatus, chatStatus === 200 ? { choices: [{}] } : { error: 'denied' })
    else if (request.url === '/embeddings') json(200, { data: [{ embedding: [0.1] }] })
    else if (request.url === '/rerank') json(200, { results: [{ index: 0, score: 1 }] })
    else json(404, { error: 'not found' })
  })
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  assert(address && typeof address === 'object')
  const base = `http://127.0.0.1:${address.port}`
  const completed = await new Promise((resolvePromise) => {
    const child = spawn(process.execPath, [script], {
      env: {
        PATH: process.env.PATH,
        DATAHUB_GMS_URL: base,
        DATAHUB_GMS_TOKEN: 'test-datahub-token',
        LLM_CHAT_URL: base,
        LLM_CHAT_MODEL: 'test-chat',
        LLM_CHAT_TOKEN: 'test-chat-token',
        LLM_EMBEDDING_URL: base,
        LLM_EMBEDDING_MODEL: 'test-embedding',
        LLM_EMBEDDING_TOKEN: 'test-embedding-token',
        LLM_RERANKER_URL: base,
        LLM_RERANKER_MODEL: 'test-reranker',
        LLM_RERANKER_TOKEN: 'test-reranker-token',
        POC_K9_STUDIO_DATABASE_URL: '',
        ...environment,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', (chunk) => { stdout += chunk })
    child.stderr.on('data', (chunk) => { stderr += chunk })
    child.on('close', (code) => resolvePromise({ code, stdout, stderr }))
  })
  await new Promise((resolvePromise) => server.close(resolvePromise))
  return completed
}

test('provider preflight uses each configured exact endpoint and leaves K9 deferred', async () => {
  const completed = await fixture()
  assert.equal(completed.code, 0, completed.stderr)
  const result = JSON.parse(completed.stdout.trim())
  assert.equal(result.status, 'PASS')
  assert.equal(result.datahub, 'PASS')
  assert.equal(result.chat, 'PASS')
  assert.equal(result.embedding, 'PASS')
  assert.equal(result.reranker, 'PASS')
  assert.equal(result.k9_studio, 'DEFERRED')
})

test('provider preflight classifies authentication without exposing response bodies', async () => {
  const completed = await fixture({ chatStatus: 401 })
  assert.equal(completed.code, 2)
  const failure = JSON.parse(completed.stderr.trim())
  assert.equal(failure.stage, 'CHAT')
  assert.equal(failure.classification, 'PREP_PREFLIGHT_CHAT_AUTH_FAILED')
  assert.equal(failure.status_class, '4xx')
  assert.equal(completed.stderr.includes('test-chat-token'), false)
  assert.equal(completed.stderr.includes('denied'), false)
})

test('provider preflight classifies invalid runtime routing before any provider request', async () => {
  const completed = await fixture({ environment: { POC_RUNTIME_HTTP_PROXY: 'not-a-url' } })
  assert.equal(completed.code, 2)
  const failure = JSON.parse(completed.stderr.trim())
  assert.equal(failure.stage, 'RUNTIME_NETWORK')
  assert.equal(failure.classification, 'PREP_PREFLIGHT_RUNTIME_NETWORK_CONFIG_FAILED')
})
