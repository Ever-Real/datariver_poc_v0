import assert from 'node:assert/strict'
import { chmod, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { spawn } from 'node:child_process'
import test from 'node:test'

const script = resolve(import.meta.dirname, 'smoke_prep39083.mjs')
const canonicalIntranetOrigin = 'http://17.20.30.40:39083'

async function requestJson(request) {
  const chunks = []
  for await (const chunk of request) chunks.push(chunk)
  return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}

async function fixture(k9Mode, {
  chatStatus = 200,
  chatFailureCode = null,
  catalogFailure = null,
  readinessTimeoutMs = '5000',
  managedItems = null,
  changeHistory = null,
  canonicalOrigin = canonicalIntranetOrigin,
  requestOrigin = canonicalIntranetOrigin,
  password = 'non-secret-test-password',
} = {}) {
  const directory = await mkdtemp(join(tmpdir(), 'prep39083-smoke-'))
  const passwordFile = join(directory, 'password')
  const output = join(directory, 'smoke.json')
  const failureOutput = join(directory, 'smoke-failure.json')
  await writeFile(passwordFile, `${password}\n`)
  await chmod(passwordFile, 0o600)
  let managedRequests = 0
  const observed = {
    healthHosts: [], loginOrigins: [], logoutOrigins: [], chatOrigins: [],
  }
  const server = createServer(async (request, response) => {
    const json = (status, body, headers = {}) => {
      response.writeHead(status, { 'Content-Type': 'application/json', ...headers })
      response.end(JSON.stringify(body))
    }
    if (request.url === '/healthz') {
      observed.healthHosts.push(request.headers.host)
      response.writeHead(200, { 'Content-Type': 'text/plain' })
      response.end('ok')
    } else if (request.url === '/auth/login') {
      observed.loginOrigins.push(request.headers.origin)
      const body = await requestJson(request)
      if (request.headers.origin !== canonicalOrigin) {
        json(403, { code: 'ORIGIN_FORBIDDEN' })
      } else if (body.username !== 'admin' || body.password !== 'non-secret-test-password') {
        json(401, { code: 'AUTHENTICATION_FAILED' })
      } else {
        json(200, { status: 'PASS' }, { 'Set-Cookie': 'session=opaque; HttpOnly' })
      }
    } else if (request.url === '/auth/logout') {
      observed.logoutOrigins.push(request.headers.origin)
      if (request.headers.origin !== canonicalOrigin) json(403, { code: 'ORIGIN_FORBIDDEN' })
      else json(200, { status: 'PASS' })
    } else if (request.url === '/poc-api/datahub/tree?parent_kind=ROOT&refresh=true&limit=1'
      || request.url === '/poc-api/datahub/catalog?limit=1') {
      if (catalogFailure) json(catalogFailure.status, catalogFailure.body)
      else json(200, { items: [], meta: { refresh_state: 'CURRENT_OR_REFRESHING' } })
    } else if (request.url === '/poc-api/knowledge/managed-assets') {
      managedRequests += 1
      json(200, { items: managedItems || [
        { graph_type: 'LINEAGE', is_default: true, status: 'READY', refresh_mode: 'DAILY', semantic_index_status: 'READY' },
        { graph_type: 'METADATA_MASTER', status: 'READY', refresh_mode: 'DAILY', semantic_index_status: 'READY' },
      ] })
    } else if (request.url?.startsWith('/api/v1/change-history/summary?')) {
      json(200, changeHistory || { capture_state: 'CAPTURE_PENDING', sync_status: 'CAPTURE_PENDING' })
    } else if (request.url === '/poc-api/llm/chat') {
      observed.chatOrigins.push(request.headers.origin)
      if (request.headers.origin !== canonicalOrigin) {
        json(403, { code: 'ORIGIN_FORBIDDEN' })
      } else {
        json(chatStatus, chatStatus === 200
          ? { route: { selected_mode: 'GENERAL' }, evidence: [] }
          : { code: chatFailureCode, error: 'provider failed with sensitive body' })
      }
    } else {
      json(404, { error: 'not found' })
    }
  })
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  assert(address && typeof address === 'object')
  const transportOrigin = `http://127.0.0.1:${address.port}`
  const smokeRequestOrigin = requestOrigin === 'TRANSPORT' ? transportOrigin : requestOrigin
  const completed = await new Promise((resolvePromise) => {
    const child = spawn(process.execPath, [
      script,
      '--origin', transportOrigin,
      '--request-origin', smokeRequestOrigin,
      '--username', 'admin',
      '--password-file', passwordFile,
      '--k9-mode', k9Mode,
      '--readiness-timeout-ms', readinessTimeoutMs,
      '--output', output,
      '--failure-output', failureOutput,
    ], { stdio: ['ignore', 'pipe', 'pipe'] })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', (chunk) => { stdout += chunk })
    child.stderr.on('data', (chunk) => { stderr += chunk })
    child.on('close', (code) => resolvePromise({ code, stdout, stderr }))
  })
  server.close()
  const report = await readFile(output, 'utf8').then(JSON.parse).catch(() => null)
  const failure = await readFile(failureOutput, 'utf8').then(JSON.parse).catch(() => null)
  await rm(directory, { recursive: true, force: true })
  return { completed, report, failure, managedRequests, observed, transportOrigin }
}

test('PREP smoke separates loopback transport from the canonical intranet request Origin', async () => {
  const result = await fixture('deferred')
  assert.equal(result.completed.code, 0, result.completed.stderr)
  assert.equal(result.report.origin, result.transportOrigin)
  assert.equal(result.report.request_origin, canonicalIntranetOrigin)
  assert.deepEqual(result.observed.loginOrigins, [canonicalIntranetOrigin])
  assert.deepEqual(result.observed.chatOrigins, [canonicalIntranetOrigin])
  assert.deepEqual(result.observed.logoutOrigins, [canonicalIntranetOrigin])
  assert.ok(result.observed.healthHosts.every((host) => host?.startsWith('127.0.0.1:')))
  assert.match(result.completed.stdout, /\[SMOKE 6\/6\].*PASS/u)
})

test('PREP smoke classifies canonical Origin rejection separately from authentication', async () => {
  const result = await fixture('deferred', { requestOrigin: 'TRANSPORT' })
  assert.equal(result.completed.code, 2)
  assert.equal(result.failure.stage, 'ADMIN_LOGIN')
  assert.equal(result.failure.classification, 'PREP_SMOKE_ADMIN_ORIGIN_FAILED')
  assert.equal(result.failure.status_class, '4xx')
})

test('PREP smoke retains ADMIN_AUTH only for wrong credentials at the canonical Origin', async () => {
  const result = await fixture('deferred', { password: 'wrong-test-password' })
  assert.equal(result.completed.code, 2)
  assert.equal(result.failure.stage, 'ADMIN_LOGIN')
  assert.equal(result.failure.classification, 'PREP_SMOKE_ADMIN_AUTH_FAILED')
  assert.equal(result.failure.status_class, '4xx')
  assert.deepEqual(result.observed.loginOrigins, [canonicalIntranetOrigin])
})

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

test('PREP smoke fails fast at classified K9 refresh boundaries', async () => {
  const result = await fixture('required', {
    managedItems: [
      {
        graph_type: 'LINEAGE', is_default: true, status: 'PENDING', refresh_mode: 'DAILY',
        semantic_index_status: 'PENDING', last_error_code: 'K9_NEO4J_PROJECTION_FAILED',
      },
      { graph_type: 'METADATA_MASTER', status: 'PENDING', refresh_mode: 'DAILY', semantic_index_status: 'PENDING' },
    ],
  })
  assert.equal(result.completed.code, 2)
  assert.equal(result.failure.stage, 'K9_INITIAL_REFRESH')
  assert.equal(result.failure.classification, 'PREP_SMOKE_K9_NEO4J_PROJECTION_FAILED')
  assert.equal(result.failure.diagnostic.product_error_code, 'K9_NEO4J_PROJECTION_FAILED')
  assert.ok(result.failure.elapsed_ms < 5_000)
})

test('PREP smoke preserves bounded K9 source diagnostics without provider detail', async () => {
  const result = await fixture('required', {
    managedItems: [
      {
        graph_type: 'LINEAGE', is_default: true, status: 'FAILED', refresh_mode: 'DAILY',
        semantic_index_status: 'PENDING', last_error_code: 'K9_DATAHUB_SOURCE_FAILED',
        failure_stage: 'METADATA_COLLECTION', failure_detail_code: 'TAG_IDENTITY_CONFLICT',
      },
      {
        graph_type: 'METADATA_MASTER', status: 'FAILED', refresh_mode: 'DAILY',
        semantic_index_status: 'PENDING', last_error_code: 'K9_DATAHUB_SOURCE_FAILED',
        failure_stage: 'METADATA_COLLECTION', failure_detail_code: 'TAG_IDENTITY_CONFLICT',
      },
    ],
  })
  assert.equal(result.completed.code, 2)
  assert.equal(result.failure.classification, 'PREP_SMOKE_K9_DATAHUB_SOURCE_FAILED')
  assert.deepEqual(result.failure.diagnostic, {
    terminal: true,
    product_error_code: 'K9_DATAHUB_SOURCE_FAILED',
    failure_stage: 'METADATA_COLLECTION',
    failure_detail_code: 'TAG_IDENTITY_CONFLICT',
  })
})

test('PREP smoke distinguishes MCL runtime discovery, capture, and retention failures', async (context) => {
  const cases = [
    ['DISCOVERY_FAILED', 'PREP_MCL_DISCOVERY_KAFKA_CLUSTER_FAILED', 'DISCOVERY_KAFKA_CLUSTER', 'CLUSTER_ID_UNAVAILABLE', 'PREP_SMOKE_MCL_RUNTIME_DISCOVERY_FAILED'],
    ['CAPTURE_FAILED', 'PREP_MCL_CAPTURE_DURABLE_APPEND_FAILED', 'DURABLE_APPEND', 'LEDGER_WRITE_REJECTED', 'PREP_SMOKE_MCL_RUNTIME_CAPTURE_FAILED'],
    ['CAPTURE_FAILED', 'PREP_MCL_CAPTURE_HISTORY_GAP_BLOCKED', 'RETENTION_CHECK', 'CHECKPOINT_BEHIND_LOW_WATERMARK', 'PREP_SMOKE_MCL_HISTORY_GAP_BLOCKED'],
  ]
  for (const [captureState, productCode, failureStage, failureDetailCode, expected] of cases) {
    await context.test(expected, async () => {
      const result = await fixture('deferred', {
        changeHistory: {
          capture_state: captureState,
          sync_status: captureState,
          capture_failure_classification: productCode,
          capture_failure_stage: failureStage,
          capture_failure_detail_code: failureDetailCode,
        },
      })
      assert.equal(result.completed.code, 2)
      assert.equal(result.failure.stage, 'MCL_INITIAL_CAPTURE')
      assert.equal(result.failure.classification, expected)
      assert.deepEqual(result.failure.diagnostic, {
        terminal: true,
        product_classification: productCode,
        failure_stage: failureStage,
        failure_detail_code: failureDetailCode,
      })
      assert.ok(result.failure.elapsed_ms < 5_000)
    })
  }
})

test('PREP smoke persists sanitized stage classification and emits progress', async () => {
  const result = await fixture('deferred', { chatStatus: 502 })
  assert.equal(result.completed.code, 2)
  assert.equal(result.failure.stage, 'GENERAL_PROVIDER')
  assert.equal(result.failure.classification, 'PREP_SMOKE_GENERAL_PROVIDER_FAILED')
  assert.equal(result.failure.status_class, '5xx')
  assert.equal(typeof result.failure.elapsed_ms, 'number')
  assert.match(result.completed.stdout, /\[SMOKE 1\/6\].*PASS/u)
  assert.equal(result.completed.stderr.includes('sensitive body'), false)
})

test('PREP smoke preserves bounded Product GENERAL provider failure classifications', async (context) => {
  const mappings = {
    POC_LLM_PROVIDER_AUTH_FAILED: 'PREP_SMOKE_GENERAL_PROVIDER_AUTH_FAILED',
    POC_LLM_PROVIDER_CONNECTIVITY_FAILED: 'PREP_SMOKE_GENERAL_PROVIDER_CONNECTIVITY_FAILED',
    POC_LLM_PROVIDER_CONTRACT_FAILED: 'PREP_SMOKE_GENERAL_PROVIDER_CONTRACT_FAILED',
    POC_LLM_PROVIDER_HTTP_FAILED: 'PREP_SMOKE_GENERAL_PROVIDER_HTTP_FAILED',
    POC_LLM_PROVIDER_TIMEOUT: 'PREP_SMOKE_GENERAL_PROVIDER_TIMEOUT_FAILED',
  }
  for (const [productCode, expected] of Object.entries(mappings)) {
    await context.test(productCode, async () => {
      const result = await fixture('deferred', { chatStatus: 502, chatFailureCode: productCode })
      assert.equal(result.completed.code, 2)
      assert.equal(result.failure.stage, 'GENERAL_PROVIDER')
      assert.equal(result.failure.classification, expected)
      assert.equal(result.failure.status_class, '5xx')
    })
  }
  await context.test('unrecognized Product code retains the legacy bounded fallback', async () => {
    const result = await fixture('deferred', {
      chatStatus: 502,
      chatFailureCode: 'POC_LLM_PROVIDER_UNTRUSTED',
    })
    assert.equal(result.failure.classification, 'PREP_SMOKE_GENERAL_PROVIDER_FAILED')
  })
})

test('PREP smoke fails fast with the exact terminal inventory phase instead of connectivity', async () => {
  const result = await fixture('deferred', {
    readinessTimeoutMs: '5000',
    catalogFailure: {
      status: 502,
      body: {
        code: 'PREP_DATAHUB_INVENTORY_NORMALIZATION_FAILED',
        detail: 'sanitized inventory failure',
        diagnostic: {
          phase: 'ENTITY_NORMALIZATION',
          page_number: 4,
          processed_count: 700,
          expected_total: 703,
          normalized_count: 698,
          skipped_noncurrent_count: 1,
          duplicate_count: 1,
          elapsed_ms: 432,
          error_class: 'PREP_DATAHUB_INVENTORY_NORMALIZATION_FAILED',
          terminal: true,
        },
      },
    },
  })
  assert.equal(result.completed.code, 2)
  assert.equal(result.failure.stage, 'DATAHUB')
  assert.equal(result.failure.classification, 'PREP_DATAHUB_INVENTORY_NORMALIZATION_FAILED')
  assert.equal(result.failure.diagnostic.phase, 'ENTITY_NORMALIZATION')
  assert.equal(result.failure.diagnostic.terminal, true)
  assert.ok(result.failure.elapsed_ms < 5_000)
  assert.equal(result.completed.stderr.includes('sanitized inventory failure'), false)
})

test('PREP smoke retains transient DataHub retry classification without hiding it as success', async () => {
  const result = await fixture('deferred', {
    readinessTimeoutMs: '1000',
    catalogFailure: {
      status: 502,
      body: {
        code: 'PREP_DATAHUB_INVENTORY_PAGE_FAILED',
        detail: 'transient inventory page failure',
        diagnostic: {
          phase: 'PAGE_FETCH',
          page_number: 3,
          processed_count: 500,
          expected_total: 700,
          normalized_count: 499,
          skipped_noncurrent_count: 1,
          duplicate_count: 0,
          elapsed_ms: 200,
          error_class: 'PREP_DATAHUB_INVENTORY_PAGE_FAILED',
          terminal: false,
        },
      },
    },
  })
  assert.equal(result.completed.code, 2)
  assert.equal(result.failure.classification, 'PREP_DATAHUB_INVENTORY_PAGE_FAILED')
  assert.equal(result.failure.diagnostic.terminal, false)
  assert.match(result.completed.stdout, /inventory page 3; 500\/700 processed/u)
})

test('PREP smoke propagates only the bounded Product inventory failure classifications', async (context) => {
  const classifications = [
    'PREP_DATAHUB_INVENTORY_QUERY_FAILED',
    'PREP_DATAHUB_INVENTORY_PAGE_FAILED',
    'PREP_DATAHUB_INVENTORY_GRAPHQL_FAILED',
    'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
    'PREP_DATAHUB_INVENTORY_NORMALIZATION_FAILED',
    'PREP_DATAHUB_INVENTORY_PROMOTION_FAILED',
  ]
  for (const classification of classifications) {
    await context.test(classification, async () => {
      const result = await fixture('deferred', {
        readinessTimeoutMs: '1000',
        catalogFailure: {
          status: 502,
          body: {
            code: classification,
            diagnostic: {
              phase: classification.endsWith('NORMALIZATION_FAILED')
                ? 'ENTITY_NORMALIZATION' : 'ENTITY_EXTRACTION',
              terminal: !classification.endsWith('QUERY_FAILED') && !classification.endsWith('PAGE_FAILED'),
            },
          },
        },
      })
      assert.equal(result.completed.code, 2)
      assert.equal(result.failure.classification, classification)
    })
  }

  await context.test('rejects an unrecognized inventory-shaped classification', async () => {
    const result = await fixture('deferred', {
      readinessTimeoutMs: '1000',
      catalogFailure: {
        status: 502,
        body: {
          code: 'PREP_DATAHUB_INVENTORY_UNTRUSTED_FAILED',
          diagnostic: { phase: 'ENTITY_EXTRACTION', terminal: true },
        },
      },
    })
    assert.equal(result.completed.code, 2)
    assert.equal(result.failure.classification, 'PREP_SMOKE_DATAHUB_CONNECTIVITY_FAILED')
  })
})
