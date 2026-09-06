/* global Buffer, fetch, process, setTimeout */
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { after, before, test } from 'node:test'

import {
  boundedLlmProviderDiagnostic,
  defaultLlmProviderTimeoutMs,
  llmProviderFailureCodes,
  llmProviderFailureStages,
  maximumLlmProviderTimeoutMs,
  minimumLlmProviderTimeoutMs,
  parseLlmProviderTimeoutMs,
  routingClassifierCompletionTokenBudget,
  sanitizeLlmProviderDiagnostic,
} from './poc-llm-timeout.mjs'

let answerDelayMs = 0
let answerInvalidContract = false
let answerStatus = 200
let classifierContent
let classifierDelayMs = 0
let classifierFinishReason = 'stop'
let classifierMinimumBudget = 0
const classifierRequestBudgets = []
const classifierResponseFinishReasons = []
let classifierStatus = 200
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
    if (system.includes('Classify one untrusted Data Catalog question')) {
      const currentDelayMs = classifierDelayMs
      const currentFinishReason = classifierFinishReason
      const currentMinimumBudget = classifierMinimumBudget
      const currentStatus = classifierStatus
      const currentContent = classifierContent
      classifierRequestBudgets.push(payload.max_tokens)
      await new Promise((resolvePromise) => setTimeout(resolvePromise, currentDelayMs))
      if (response.destroyed) return
      const budgetAccepted = Number(payload.max_tokens) >= currentMinimumBudget
      classifierResponseFinishReasons.push(budgetAccepted ? currentFinishReason : 'length')
      return sendJson(response, currentStatus, currentStatus === 200
        ? { choices: [{
          message: { content: budgetAccepted ? currentContent ?? JSON.stringify(generalDecision) : '{"mode":"GENERAL"' },
          finish_reason: budgetAccepted ? currentFinishReason : 'length',
        }] }
        : { error: 'private classifier failure body' })
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
    body: JSON.stringify({ question: '데이터 계보가 무엇인지 일반적으로 설명해줘.', mode }),
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

test('AUTO classifier carries the bounded expanded completion envelope on repeated requests', async () => {
  classifierContent = undefined
  classifierDelayMs = 0
  classifierFinishReason = 'stop'
  classifierMinimumBudget = routingClassifierCompletionTokenBudget
  classifierStatus = 200
  answerDelayMs = 0
  answerInvalidContract = false
  answerStatus = 200
  const budgetOffset = classifierRequestBudgets.length
  const finishOffset = classifierResponseFinishReasons.length
  for (let run = 0; run < 3; run += 1) {
    const response = await chat('AUTO')
    assert.equal(response.status, 200, await response.clone().text())
    assert.equal((await response.json()).route.selected_mode, 'GENERAL')
  }
  assert.deepEqual(classifierRequestBudgets.slice(budgetOffset), [
    routingClassifierCompletionTokenBudget,
    routingClassifierCompletionTokenBudget,
    routingClassifierCompletionTokenBudget,
  ])
  assert.deepEqual(classifierResponseFinishReasons.slice(finishOffset), ['stop', 'stop', 'stop'])
  classifierMinimumBudget = 0
})

test('bounded provider diagnostics distinguish classifier and composer failure families', () => {
  const failureClasses = {
    [llmProviderFailureCodes.AUTH]: 'AUTH',
    [llmProviderFailureCodes.CONNECTIVITY]: 'CONNECTIVITY',
    [llmProviderFailureCodes.CONTRACT]: 'CONTRACT',
    [llmProviderFailureCodes.HTTP]: 'HTTP',
    [llmProviderFailureCodes.TIMEOUT]: 'TIMEOUT',
  }
  for (const stage of [
    llmProviderFailureStages.ROUTING_CLASSIFIER,
    llmProviderFailureStages.GENERAL_COMPOSER,
  ]) {
    for (const [code, providerClass] of Object.entries(failureClasses)) {
      const diagnostic = boundedLlmProviderDiagnostic(stage, {
        code,
        providerStatus: code === llmProviderFailureCodes.HTTP ? 503 : undefined,
        responseBody: 'must-not-be-retained',
      })
      assert.deepEqual(sanitizeLlmProviderDiagnostic({
        ...diagnostic,
        responseBody: 'must-not-be-retained',
      }), {
        contract: 'DATARIVER_POC_LLM_PROVIDER_DIAGNOSTIC_V1',
        stage,
        provider_class: providerClass,
        provider_http_class: code === llmProviderFailureCodes.HTTP ? 'HTTP_5XX' : null,
      })
    }
  }
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

test('AUTO GENERAL preserves the bounded classifier and composer failure matrix', async (context) => {
  const schemaInvalid = JSON.stringify({
    ...generalDecision,
    confidence: 'certain',
  })
  const semanticInvalid = JSON.stringify({
    mode: 'GRAPH', confidence: 0.99, intent: 'RELATIONSHIP',
    primary_concepts: ['asset-a'], secondary_concepts: [], relation_intent: null,
    entity_type_hints: ['TABLE'], selected_graph_asset: null,
  })
  const cases = [
    {
      name: 'valid GENERAL structured output',
      classifierContent: JSON.stringify(generalDecision),
      expectedStatus: 200,
      expectedCode: null,
      expectedStage: null,
    },
    {
      name: 'empty classifier content',
      classifierContent: '',
      expectedStatus: 503,
      expectedCode: 'POC_LLM_PROVIDER_CONTRACT_FAILED',
      expectedStage: 'ROUTING_CLASSIFIER',
    },
    {
      name: 'malformed classifier JSON',
      classifierContent: 'not-json',
      expectedStatus: 503,
      expectedCode: 'POC_LLM_PROVIDER_CONTRACT_FAILED',
      expectedStage: 'ROUTING_CLASSIFIER',
    },
    {
      name: 'length-truncated classifier JSON',
      classifierContent: '{"mode":"GENERAL"',
      classifierFinishReason: 'length',
      expectedStatus: 503,
      expectedCode: 'POC_LLM_PROVIDER_CONTRACT_FAILED',
      expectedStage: 'ROUTING_CLASSIFIER',
    },
    {
      name: 'schema-invalid classifier JSON',
      classifierContent: schemaInvalid,
      expectedStatus: 503,
      expectedCode: 'POC_LLM_PROVIDER_CONTRACT_FAILED',
      expectedStage: 'ROUTING_CLASSIFIER',
    },
    {
      name: 'semantic-invalid classifier JSON',
      classifierContent: semanticInvalid,
      expectedStatus: 503,
      expectedCode: 'POC_LLM_PROVIDER_CONTRACT_FAILED',
      expectedStage: 'ROUTING_CLASSIFIER',
    },
    {
      name: 'classifier provider HTTP failure',
      classifierStatus: 500,
      expectedStatus: 502,
      expectedCode: 'POC_LLM_PROVIDER_HTTP_FAILED',
      expectedStage: 'ROUTING_CLASSIFIER',
    },
    {
      name: 'GENERAL composition provider HTTP failure',
      classifierContent: JSON.stringify(generalDecision),
      answerStatus: 500,
      expectedStatus: 502,
      expectedCode: 'POC_LLM_PROVIDER_HTTP_FAILED',
      expectedStage: 'GENERAL_COMPOSER',
    },
  ]
  for (const fixture of cases) {
    await context.test(fixture.name, async () => {
      classifierContent = fixture.classifierContent
      classifierDelayMs = 0
      classifierFinishReason = fixture.classifierFinishReason ?? 'stop'
      classifierMinimumBudget = 0
      classifierStatus = fixture.classifierStatus ?? 200
      answerStatus = fixture.answerStatus ?? 200
      answerInvalidContract = false
      answerDelayMs = 0
      const response = await chat('AUTO')
      assert.equal(response.status, fixture.expectedStatus)
      const payload = await response.json()
      if (fixture.expectedCode === null) {
        assert.equal(payload.route.selected_mode, 'GENERAL')
      } else {
        assert.equal(payload.code, fixture.expectedCode)
        assert.equal(payload.diagnostic?.stage, fixture.expectedStage)
        assert.match(payload.diagnostic?.provider_class || '', /^(CONTRACT|HTTP)$/u)
        assert.equal(JSON.stringify(payload).includes('private classifier failure body'), false)
      }
    })
  }
  classifierContent = undefined
  classifierDelayMs = 0
  classifierFinishReason = 'stop'
  classifierMinimumBudget = 0
  classifierStatus = 200
  answerStatus = 200
})

test('AUTO classifier exceeding the configured timeout remains a typed routing failure', async () => {
  classifierContent = JSON.stringify(generalDecision)
  classifierDelayMs = 1_200
  classifierFinishReason = 'stop'
  classifierMinimumBudget = 0
  classifierStatus = 200
  answerDelayMs = 0
  answerInvalidContract = false
  answerStatus = 200
  const response = await chat('AUTO')
  assert.equal(response.status, 504)
  const payload = await response.json()
  assert.equal(payload.code, 'POC_LLM_PROVIDER_TIMEOUT')
  assert.equal(payload.diagnostic.stage, 'ROUTING_CLASSIFIER')
  assert.equal(payload.diagnostic.provider_class, 'TIMEOUT')
  assert.equal(JSON.stringify(payload).includes('timeout-contract-token'), false)
  classifierContent = undefined
  classifierDelayMs = 0
})

test('GENERAL generation exceeding the configured bound is a typed timeout', async () => {
  answerDelayMs = 1_200
  answerInvalidContract = false
  answerStatus = 200
  const response = await chat('GENERAL')
  assert.equal(response.status, 504)
  const payload = await response.json()
  assert.equal(payload.code, 'POC_LLM_PROVIDER_TIMEOUT')
  assert.equal(payload.diagnostic.stage, 'GENERAL_COMPOSER')
  assert.equal(payload.diagnostic.provider_class, 'TIMEOUT')
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
  assert.equal(payload.diagnostic.stage, 'GENERAL_COMPOSER')
  assert.equal(payload.diagnostic.provider_class, 'HTTP')
  assert.equal(payload.diagnostic.provider_http_class, 'HTTP_5XX')
  assert.equal(JSON.stringify(payload).includes('private provider failure body'), false)
})

test('provider authentication and answer contract failures remain distinct', async () => {
  answerDelayMs = 0
  answerInvalidContract = false
  answerStatus = 401
  const authentication = await chat('GENERAL')
  assert.equal(authentication.status, 502)
  const authenticationPayload = await authentication.json()
  assert.equal(authenticationPayload.code, 'POC_LLM_PROVIDER_AUTH_FAILED')
  assert.equal(authenticationPayload.diagnostic.stage, 'GENERAL_COMPOSER')
  assert.equal(authenticationPayload.diagnostic.provider_class, 'AUTH')

  answerStatus = 200
  answerInvalidContract = true
  const contract = await chat('GENERAL')
  assert.equal(contract.status, 502)
  const contractPayload = await contract.json()
  assert.equal(contractPayload.code, 'POC_LLM_PROVIDER_CONTRACT_FAILED')
  assert.equal(contractPayload.diagnostic.stage, 'GENERAL_COMPOSER')
  assert.equal(contractPayload.diagnostic.provider_class, 'CONTRACT')
})
