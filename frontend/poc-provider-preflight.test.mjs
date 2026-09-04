/* global Buffer, setTimeout */
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import test from 'node:test'

import {
  collectProviderPreflight,
  providerPreflightFailure,
  runProviderPreflight,
} from './poc-provider-preflight.mjs'

const mclDiscovery = async () => ({
  receipt: {
    contract: 'DATARIVER_MCL_DISCOVERY_V1',
    source_identity_hash: 'a'.repeat(64),
    schema_contract_hash: 'b'.repeat(64),
    registry_kind: 'DATAHUB_GMS_INTERNAL',
  },
})

async function fixture({
  chatStatus = 200,
  chatDelayMs = 0,
  embeddingStatus = 200,
  embeddingPayload = { data: [{ index: 0, embedding: [0.1] }] },
  environment = {},
} = {}) {
  const server = createServer(async (request, response) => {
    const json = (status, body) => {
      response.writeHead(status, { 'Content-Type': 'application/json' })
      response.end(JSON.stringify(body))
    }
    if (request.url === '/api/graphql') {
      const chunks = []
      for await (const chunk of request) chunks.push(chunk)
      const query = JSON.parse(Buffer.concat(chunks).toString('utf8')).query
      json(200, { data: { search: { start: 0, count: query.includes('ASSERTION') ? 0 : 1, total: query.includes('ASSERTION') ? 0 : 1 } } })
    } else if (request.url === '/chat/completions') setTimeout(
      () => json(chatStatus, chatStatus === 200 ? { choices: [{}] } : { error: 'denied' }), chatDelayMs,
    )
    else if (request.url === '/embeddings') json(
      embeddingStatus,
      embeddingStatus === 200 ? embeddingPayload : { error: 'denied' },
    )
    else if (request.url === '/rerank') json(200, { results: [{ index: 0, score: 1 }] })
    else if (request.url === '/auth/token') json(200, { access_token: 'opaque-test-airflow-token' })
    else if (request.url === '/api/v2/dags/datariver_quality_dispatch') json(200, { dag_id: 'datariver_quality_dispatch' })
    else if (request.url === '/minio/health/ready') json(200, { status: 'ok' })
    else json(404, { error: 'not found' })
  })
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  assert(address && typeof address === 'object')
  const base = `http://127.0.0.1:${address.port}`
  const values = {
    POC_PUBLIC_ORIGIN: 'http://10.20.30.40:39083',
    POC_BIND_HOST: '0.0.0.0', POC_STATE_BIND_HOST: '127.0.0.1',
    DATAHUB_GMS_URL: base, DATAHUB_GMS_TOKEN: 'test-datahub-token',
    LLM_CHAT_URL: base, LLM_CHAT_MODEL: 'test-chat', LLM_CHAT_TOKEN: 'test-chat-token',
    LLM_EMBEDDING_URL: base, LLM_EMBEDDING_MODEL: 'test-embedding', LLM_EMBEDDING_TOKEN: 'test-embedding-token',
    LLM_RERANKER_URL: base, LLM_RERANKER_MODEL: 'test-reranker', LLM_RERANKER_TOKEN: 'test-reranker-token',
    ...environment,
  }
  if (values.AIRFLOW_URL === 'USE_FIXTURE') values.AIRFLOW_URL = base
  if (values.MINIO_URL === 'USE_FIXTURE') values.MINIO_URL = base
  return {
    run: () => runProviderPreflight({ environment: values, discoverMcl: mclDiscovery }),
    close: () => new Promise((resolvePromise) => server.close(resolvePromise)),
  }
}

test('preflight proves intranet, DataHub Assertion read, built-in K9 and MCL without target counts', async () => {
  const subject = await fixture()
  try {
    const result = await subject.run()
    assert.equal(result.status, 'PASS')
    assert.equal(result.web_intranet, 'READY')
    assert.equal(result.k9_built_in, 'READY')
    assert.equal(result.mcl_change_history, 'READY')
    assert.equal(result.gx_quality_read, 'READY')
    assert.equal(result.gx_assertion_count, 0)
    assert.equal(result.gx_quality_execution, 'DEFERRED')
  } finally { await subject.close() }
})

test('preflight classifies Chat authentication independently', async () => {
  const subject = await fixture({ chatStatus: 401 })
  try {
    await assert.rejects(subject.run(), (error) => (
      error.stage === 'CHAT' && error.classification === 'PREP_PREFLIGHT_CHAT_AUTH_FAILED'
    ))
  } finally { await subject.close() }
})

test('preflight keeps provider HTTP rejection distinct from connectivity', async () => {
  const subject = await fixture({ chatStatus: 502 })
  try {
    await assert.rejects(subject.run(), { classification: 'PREP_PREFLIGHT_CHAT_HTTP_FAILED' })
  } finally { await subject.close() }
})

test('embedding preflight proves the POST endpoint and exact bounded vector contract', async () => {
  const rejected = await fixture({ embeddingStatus: 400 })
  try {
    await assert.rejects(rejected.run(), {
      classification: 'PREP_PREFLIGHT_EMBEDDING_HTTP_FAILED',
    })
  } finally { await rejected.close() }

  for (const embeddingPayload of [
    { data: [] },
    { data: [{ index: 0, embedding: [] }] },
    { data: [{ index: 0, embedding: [null] }] },
    { data: [{ index: 1, embedding: [0.1] }] },
  ]) {
    const malformed = await fixture({ embeddingPayload })
    try {
      await assert.rejects(malformed.run(), {
        classification: 'PREP_PREFLIGHT_EMBEDDING_CONTRACT_FAILED',
      })
    } finally { await malformed.close() }
  }
})

test('preflight uses the shared bounded Chat timeout classification', async () => {
  const subject = await fixture({ chatDelayMs: 1_200, environment: { POC_LLM_TIMEOUT_MS: '1000' } })
  try {
    await assert.rejects(subject.run(), { classification: 'PREP_PREFLIGHT_CHAT_TIMEOUT_FAILED' })
  } finally { await subject.close() }
})

test('preflight distinguishes unapproved HTTP origin, malformed origin, and invalid CIDR', async () => {
  const subject = await fixture({ environment: { POC_PUBLIC_ORIGIN: 'http://203.0.113.10:39083' } })
  try {
    await assert.rejects(subject.run(), {
      classification: 'PREP_PREFLIGHT_WEB_INTRANET_ORIGIN_NOT_APPROVED_FAILED',
    })
  } finally { await subject.close() }

  const malformed = await fixture({ environment: { POC_PUBLIC_ORIGIN: 'http://poc.example.test:39083' } })
  try {
    await assert.rejects(malformed.run(), {
      classification: 'PREP_PREFLIGHT_WEB_INTRANET_ORIGIN_MALFORMED_FAILED',
    })
  } finally { await malformed.close() }

  const invalidCidr = await fixture({ environment: {
    POC_PUBLIC_ORIGIN: 'http://203.0.113.10:39083',
    POC_INTRANET_HTTP_ALLOWED_CIDRS: '0.0.0.0/0',
  } })
  try {
    await assert.rejects(invalidCidr.run(), {
      classification: 'PREP_PREFLIGHT_WEB_INTRANET_CIDR_CONFIG_FAILED',
    })
  } finally { await invalidCidr.close() }
})

test('preflight accepts an operator-approved non-RFC1918 intranet range', async () => {
  const subject = await fixture({ environment: {
    POC_PUBLIC_ORIGIN: 'http://100.64.17.9:39083',
    POC_INTRANET_HTTP_ALLOWED_CIDRS: '100.64.0.0/10',
  } })
  try {
    assert.equal((await subject.run()).web_intranet, 'READY')
  } finally { await subject.close() }
})

test('preflight reuses existing Airflow quality dispatch and optional MinIO without deploying providers', async () => {
  const subject = await fixture({ environment: {
    AIRFLOW_URL: 'USE_FIXTURE', AIRFLOW_USERNAME: 'quality-user', AIRFLOW_PASSWORD: 'quality-password',
    MINIO_URL: 'USE_FIXTURE',
  } })
  try {
    const result = await subject.run()
    assert.equal(result.airflow, 'READY')
    assert.equal(result.gx_quality_execution, 'READY')
    assert.equal(result.minio, 'READY')
  } finally { await subject.close() }
})

test('every known provider preflight stage owns unexpected exceptions', async (context) => {
  const successful = {
    webIntranet: async () => 'http://10.20.30.40:39083',
    datahub: async () => undefined,
    qualityRead: async () => ({ assertion_count: 0 }),
    chat: async () => undefined,
    embedding: async () => undefined,
    reranker: async () => undefined,
    mclDiscovery: async () => mclDiscovery(),
    airflow: async () => 'DEFERRED',
    minio: async () => 'DEFERRED',
  }
  const stages = new Map([
    ['webIntranet', 'WEB_INTRANET'],
    ['datahub', 'DATAHUB'],
    ['qualityRead', 'QUALITY_READ'],
    ['chat', 'CHAT'],
    ['embedding', 'EMBEDDING'],
    ['reranker', 'RERANKER'],
    ['mclDiscovery', 'MCL_DISCOVERY'],
    ['airflow', 'AIRFLOW'],
    ['minio', 'MINIO'],
  ])
  for (const [operation, stage] of stages) {
    await context.test(stage, async () => {
      const operations = { ...successful, [operation]: async () => { throw new TypeError('injected') } }
      await assert.rejects(
        runProviderPreflight({ environment: {}, providerTransport: {}, operations }),
        (error) => error.stage === stage
          && error.classification === `PREP_PREFLIGHT_${stage}_UNEXPECTED_FAILED`,
      )
    })
  }
})

test('known stages preserve existing bounded classifications exactly', async () => {
  const typed = Object.assign(new Error('typed'), {
    stage: 'DATAHUB', classification: 'PREP_PREFLIGHT_DATAHUB_CONTRACT_FAILED', status: 422,
  })
  await assert.rejects(
    runProviderPreflight({
      environment: {}, providerTransport: {},
      operations: { webIntranet: async () => 'origin', datahub: async () => { throw typed } },
    }),
    (error) => error === typed,
  )
})

test('malformed provider URL and Chat timeout are deterministic CONFIG failures', async () => {
  const malformed = await fixture({ environment: { DATAHUB_GMS_URL: 'not a provider URL' } })
  try {
    await assert.rejects(malformed.run(), { classification: 'PREP_PREFLIGHT_DATAHUB_CONFIG_FAILED' })
  } finally { await malformed.close() }

  const timeout = await fixture({ environment: { POC_LLM_TIMEOUT_MS: 'invalid' } })
  try {
    await assert.rejects(timeout.run(), { classification: 'PREP_PREFLIGHT_CHAT_CONFIG_FAILED' })
  } finally { await timeout.close() }
})

test('sanitized failure envelope preserves stage, classification and safe status class only', () => {
  const error = Object.assign(new Error('body with sensitive details'), {
    stage: 'DATAHUB', classification: 'PREP_PREFLIGHT_DATAHUB_AUTH_FAILED', status: 401,
    url: 'https://token@example.test/private', responseBody: { secret: 'value' },
  })
  assert.deepEqual(providerPreflightFailure(error), {
    contract: 'DATARIVER_PREP39083_PROVIDER_PREFLIGHT_V2', status: 'FAILED',
    stage: 'DATAHUB', classification: 'PREP_PREFLIGHT_DATAHUB_AUTH_FAILED', status_class: '4xx',
  })
  assert.deepEqual(providerPreflightFailure(new Error('programmer error')), {
    contract: 'DATARIVER_PREP39083_PROVIDER_PREFLIGHT_V2', status: 'FAILED',
    stage: 'INTERNAL', classification: 'PREP_PREFLIGHT_INTERNAL_UNEXPECTED_FAILED', status_class: null,
  })
})

test('MCL discovery classifications survive the provider stage and output envelope unchanged', async () => {
  const typed = Object.assign(new Error('typed'), { code: 'PREP_MCL_DISCOVERY_KAFKA_ADMIN_FAILED' })
  await assert.rejects(
    runProviderPreflight({
      environment: {}, providerTransport: {},
      operations: {
        webIntranet: async () => 'origin', datahub: async () => undefined,
        qualityRead: async () => ({ assertion_count: 0 }), chat: async () => undefined,
        embedding: async () => undefined, reranker: async () => undefined,
        mclDiscovery: async () => { throw typed },
      },
    }),
    (error) => error === typed && providerPreflightFailure(error).classification === typed.code,
  )
})

function collectAllOperations(overrides = {}) {
  return {
    webIntranet: async () => 'origin',
    datahub: async () => undefined,
    qualityRead: async () => ({ assertion_count: 0 }),
    chat: async () => undefined,
    embedding: async () => undefined,
    reranker: async () => undefined,
    mclDiscovery: async () => mclDiscovery(),
    airflow: async () => 'DEFERRED',
    minio: async () => 'DEFERRED',
    ...overrides,
  }
}

test('doctor collection reports every independent stage after typed failures', async () => {
  const calls = []
  const failed = (stage, classification) => Object.assign(new Error('sanitized'), { stage, classification })
  const operations = collectAllOperations({
    chat: async () => { calls.push('CHAT'); throw failed('CHAT', 'PREP_PREFLIGHT_CHAT_AUTH_FAILED') },
    embedding: async () => { calls.push('EMBEDDING') },
    reranker: async () => { calls.push('RERANKER') },
    airflow: async () => { calls.push('AIRFLOW'); return 'READY' },
    minio: async () => { calls.push('MINIO'); return 'DEFERRED' },
  })
  const matrix = await collectProviderPreflight({ environment: {}, providerTransport: {}, operations })
  assert.equal(matrix.status, 'FAILED')
  assert.deepEqual(matrix.stages.CHAT, {
    status: 'FAILED', classification: 'PREP_PREFLIGHT_CHAT_AUTH_FAILED',
  })
  assert.equal(matrix.stages.EMBEDDING.status, 'READY')
  assert.equal(matrix.stages.RERANKER.status, 'READY')
  assert.equal(matrix.stages.AIRFLOW.status, 'READY')
  assert.equal(matrix.stages.MINIO.status, 'DEFERRED')
  assert.deepEqual(calls, ['CHAT', 'EMBEDDING', 'RERANKER', 'AIRFLOW', 'MINIO'])
  assert.equal(JSON.stringify(matrix).includes('sanitized'), false)
})

test('doctor collection applies only explicit DataHub dependencies and still diagnoses Kafka', async () => {
  const datahubFailure = Object.assign(new Error('unreachable'), {
    stage: 'DATAHUB', classification: 'PREP_PREFLIGHT_DATAHUB_CONNECTIVITY_FAILED',
  })
  const kafkaFailure = Object.assign(new Error('advertised broker unreachable'), {
    code: 'PREP_MCL_DISCOVERY_KAFKA_CLUSTER_FAILED',
  })
  let qualityCalls = 0
  let mclCalls = 0
  const matrix = await collectProviderPreflight({
    environment: {}, providerTransport: {},
    operations: collectAllOperations({
      datahub: async () => { throw datahubFailure },
      qualityRead: async () => { qualityCalls += 1 },
      mclDiscovery: async () => { mclCalls += 1; throw kafkaFailure },
    }),
  })
  assert.deepEqual(matrix.stages.QUALITY_READ, {
    status: 'BLOCKED_BY_DEPENDENCY', dependency: 'DATAHUB',
  })
  assert.deepEqual(matrix.stages.MCL_DISCOVERY, {
    status: 'FAILED', classification: kafkaFailure.code,
  })
  assert.equal(qualityCalls, 0)
  assert.equal(mclCalls, 1)
})

test('doctor collection marks DataHub-dependent MCL provider checks as blocked', async () => {
  const datahubFailure = Object.assign(new Error('unreachable'), {
    stage: 'DATAHUB', classification: 'PREP_PREFLIGHT_DATAHUB_CONNECTIVITY_FAILED',
  })
  const providerFailure = Object.assign(new Error('unreachable'), {
    code: 'PREP_MCL_DISCOVERY_PROVIDER_CONNECTIVITY_FAILED',
  })
  const matrix = await collectProviderPreflight({
    environment: {}, providerTransport: {},
    operations: collectAllOperations({
      datahub: async () => { throw datahubFailure },
      mclDiscovery: async () => { throw providerFailure },
    }),
  })
  assert.deepEqual(matrix.stages.MCL_DISCOVERY, {
    status: 'BLOCKED_BY_DEPENDENCY', dependency: 'DATAHUB',
  })
})

test('doctor collection continues DataHub-dependent reads after an HTTP response proves transport', async () => {
  const datahubFailure = Object.assign(new Error('rejected'), {
    stage: 'DATAHUB', classification: 'PREP_PREFLIGHT_DATAHUB_HTTP_FAILED', status: 500,
  })
  let qualityCalls = 0
  let mclCalls = 0
  const matrix = await collectProviderPreflight({
    environment: {}, providerTransport: {},
    operations: collectAllOperations({
      datahub: async () => { throw datahubFailure },
      qualityRead: async () => { qualityCalls += 1; return { assertion_count: 0 } },
      mclDiscovery: async () => { mclCalls += 1; return mclDiscovery() },
    }),
  })
  assert.equal(matrix.stages.DATAHUB.status, 'FAILED')
  assert.equal(matrix.stages.QUALITY_READ.status, 'READY')
  assert.equal(matrix.stages.MCL_DISCOVERY.status, 'READY')
  assert.equal(qualityCalls, 1)
  assert.equal(mclCalls, 1)
})

test('doctor collection still runs Kafka-owned MCL diagnostics when runtime provider transport config is invalid', async () => {
  let mclCalls = 0
  const kafkaFailure = Object.assign(new Error('cluster'), {
    code: 'PREP_MCL_DISCOVERY_KAFKA_CONNECTIVITY_FAILED',
  })
  const matrix = await collectProviderPreflight({
    environment: { POC_RUNTIME_HTTP_PROXY: 'not-a-url' },
    operations: collectAllOperations({
      mclDiscovery: async () => { mclCalls += 1; throw kafkaFailure },
    }),
  })
  assert.equal(matrix.stages.DATAHUB.status, 'FAILED')
  assert.equal(matrix.stages.DATAHUB.classification, 'PREP_PREFLIGHT_DATAHUB_RUNTIME_NETWORK_CONFIG_FAILED')
  assert.deepEqual(matrix.stages.MCL_DISCOVERY, {
    status: 'FAILED', classification: kafkaFailure.code,
  })
  assert.equal(mclCalls, 1)
})
