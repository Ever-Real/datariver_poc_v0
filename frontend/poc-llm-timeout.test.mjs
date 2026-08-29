/* global Buffer, fetch, process, setTimeout */
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { after, before, test } from 'node:test'

import {
  defaultLlmProviderTimeoutMs,
  maximumLlmProviderTimeoutMs,
  minimumLlmProviderTimeoutMs,
  parseLlmProviderTimeoutMs,
} from './poc-llm-timeout.mjs'

let answerDelayMs = 0
let answerInvalidContract = false
let answerStatus = 200
let providerServer
let productServer
let productOrigin

function sendJson(response, status, value) {
  response.writeHead(status, { 'Content-Type': 'application/json' })
  response.end(JSON.stringify(value))
}

const generalDecision = {
  mode: 'GENERAL', confidence: 0.99, intent: 'GENERAL_CONVERSATION',
  entity_resolution_required: false, graph_traversal_required: false,
  semantic_retrieval_required: false, fallback_mode: null,
  primary_concepts: [], secondary_concepts: [], relation_intent: null,
  entity_type_hints: [], selected_graph_asset: null, retrieval_method: 'NONE',
}

before(async () => {
  providerServer = createServer(async (request, response) => {
    const chunks = []
    for await (const chunk of request) chunks.push(chunk)
    const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    const system = payload.messages?.[0]?.content || ''
    if (system.includes('Plan one untrusted Data Catalog question')) {
      return sendJson(response, 200, { choices: [{ message: { content: JSON.stringify(generalDecision) } }] })
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, answerDelayMs))
    if (response.destroyed) return
    sendJson(response, answerStatus, answerStatus === 200
      ? answerInvalidContract ? { choices: [] } : { choices: [{ message: { content: 'bounded GENERAL answer' } }] }
      : { error: 'private provider failure body' })
  })
  await new Promise((resolvePromise) => providerServer.listen(0, '127.0.0.1', resolvePromise))
  const address = providerServer.address()
  assert(address && typeof address === 'object')
  const providerOrigin = `http://127.0.0.1:${address.port}`
  Object.assign(process.env, {
    POC_ENV_FILE: 'poc-llm-timeout.test.env.missing',
    POC_DATABASE_URL: '',
    POC_POSTGRES_HOST: '',
    POC_REDIS_URL: '',
    POC_LLM_TIMEOUT_MS: '1000',
    LLM_CHAT_URL: providerOrigin,
    LLM_CHAT_MODEL: 'timeout-contract-model',
    LLM_CHAT_TOKEN: 'timeout-contract-token',
  })
  const { createPocStateStore } = await import('./poc-state-store.mjs?llm-timeout-contract')
  const { createPocServer } = await import('./poc-server.mjs?llm-timeout-contract')
  const stateStore = createPocStateStore()
  await stateStore.write('change-history-access-v1', {
    schema_version: 1,
    active_subject_id: 'timeout-subject',
    users: [{ subject_id: 'timeout-subject', role: 'admin', active: true, provider_owner_refs: [] }],
    system_assignments: [],
  })
  productServer = createPocServer({
    stateStore,
    authenticator: {
      async authenticate() { return { subjectId: 'timeout-subject', tokenHash: 'f'.repeat(64) } },
      assertOrigin() {},
    },
  })
  await new Promise((resolvePromise) => productServer.listen(0, '127.0.0.1', resolvePromise))
  const productAddress = productServer.address()
  assert(productAddress && typeof productAddress === 'object')
  productOrigin = `http://127.0.0.1:${productAddress.port}`
})

after(async () => {
  productServer.closeAllConnections()
  providerServer.closeAllConnections()
  await Promise.all([
    new Promise((resolvePromise, reject) => productServer.close((error) => error ? reject(error) : resolvePromise())),
    new Promise((resolvePromise, reject) => providerServer.close((error) => error ? reject(error) : resolvePromise())),
  ])
})

async function chat(mode = 'AUTO') {
  return fetch(`${productOrigin}/poc-api/llm/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: '일반적인 데이터 거버넌스를 설명해줘.', mode }),
  })
}

test('canonical timeout accepts a generated latency beyond the former short bound', () => {
  const generatedRemoteInferenceLatencyMs = 15_000 + 137
  assert.equal(parseLlmProviderTimeoutMs(undefined), defaultLlmProviderTimeoutMs)
  assert.ok(generatedRemoteInferenceLatencyMs < defaultLlmProviderTimeoutMs)
  assert.equal(parseLlmProviderTimeoutMs(String(minimumLlmProviderTimeoutMs)), minimumLlmProviderTimeoutMs)
  assert.equal(parseLlmProviderTimeoutMs(String(maximumLlmProviderTimeoutMs)), maximumLlmProviderTimeoutMs)
  assert.throws(() => parseLlmProviderTimeoutMs('999'))
  assert.throws(() => parseLlmProviderTimeoutMs('300001'))
})

test('AUTO classifier and GENERAL composition succeed without retrieval evidence', async () => {
  answerDelayMs = 60
  answerInvalidContract = false
  answerStatus = 200
  const started = Date.now()
  const response = await chat('AUTO')
  assert.equal(response.status, 200, await response.clone().text())
  const payload = await response.json()
  assert.equal(payload.route.selected_mode, 'GENERAL')
  assert.deepEqual(payload.evidence, [])
  assert.ok(payload.performance.composition_ms >= payload.performance.provider_response_wait_ms)
  assert.ok(payload.performance.provider_response_wait_ms >= 40)
  assert.equal(Number.isInteger(payload.performance.prompt_assembly_ms), true)
  assert.equal(Number.isInteger(payload.performance.provider_request_serialization_ms), true)
  assert.equal(Number.isInteger(payload.performance.provider_response_body_ms), true)
  assert.ok(Date.now() - started < 1_000)
})

test('GENERAL generation exceeding the configured bound is a typed timeout', async () => {
  answerDelayMs = 1_200
  answerInvalidContract = false
  answerStatus = 200
  const response = await chat('GENERAL')
  assert.equal(response.status, 504)
  const payload = await response.json()
  assert.equal(payload.code, 'POC_LLM_PROVIDER_TIMEOUT')
  assert.equal(JSON.stringify(payload).includes('timeout-contract-token'), false)
})

test('provider HTTP rejection remains distinct from timeout', async () => {
  answerDelayMs = 0
  answerInvalidContract = false
  answerStatus = 503
  const response = await chat('GENERAL')
  assert.equal(response.status, 502)
  const payload = await response.json()
  assert.equal(payload.code, 'POC_LLM_PROVIDER_HTTP_FAILED')
  assert.equal(JSON.stringify(payload).includes('private provider failure body'), false)
})

test('provider authentication and answer contract failures remain distinct', async () => {
  answerDelayMs = 0
  answerInvalidContract = false
  answerStatus = 401
  const authentication = await chat('GENERAL')
  assert.equal(authentication.status, 502)
  assert.equal((await authentication.json()).code, 'POC_LLM_PROVIDER_AUTH_FAILED')

  answerStatus = 200
  answerInvalidContract = true
  const contract = await chat('GENERAL')
  assert.equal(contract.status, 502)
  assert.equal((await contract.json()).code, 'POC_LLM_PROVIDER_CONTRACT_FAILED')
})
