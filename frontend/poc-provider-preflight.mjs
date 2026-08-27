/* global AbortSignal, Buffer, URL, process */
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { loadPocLocalAuthConfig } from './poc-local-auth.mjs'
import { discoverPocMclSource } from './poc-mcl-discovery.mjs'
import { createProviderTransport, joinProviderUrl, llmEndpoint } from './poc-provider-transport.mjs'
import { parseLlmProviderTimeoutMs } from './poc-llm-timeout.mjs'

const providerTimeoutMs = 60_000

function required(environment, name, stage = name) {
  const value = environment[name]?.trim()
  if (!value) throw classified(stage, 'CONFIG', `${name} is not configured.`)
  return value
}

function classified(stage, kind, message, status) {
  return Object.assign(new Error(message), {
    stage,
    classification: `PREP_PREFLIGHT_${stage}_${kind}_FAILED`,
    status,
  })
}

function statusKind(status) {
  return [401, 403].includes(status) ? 'AUTH' : 'HTTP'
}

function providerUrl(stage, baseUrl, path) {
  try {
    const joined = joinProviderUrl(baseUrl, path)
    const parsed = new URL(joined)
    if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) throw new Error('invalid provider URL')
    return parsed.toString()
  } catch {
    throw classified(stage, 'CONFIG', `${stage} provider URL configuration is invalid.`)
  }
}

function preservesKnownClassification(error) {
  return (typeof error?.classification === 'string' && error.classification.startsWith('PREP_PREFLIGHT_'))
    || (typeof error?.code === 'string' && error.code.startsWith('PREP_MCL_DISCOVERY_'))
}

async function knownStage(stage, operation) {
  try {
    return await operation()
  } catch (error) {
    if (preservesKnownClassification(error)) throw error
    throw classified(stage, 'UNEXPECTED', `${stage} provider preflight failed unexpectedly.`)
  }
}

async function response(providerTransport, stage, url, options, timeoutMs = providerTimeoutMs) {
  let result
  try {
    result = await providerTransport.fetch(url, {
      ...options, redirect: 'error', signal: AbortSignal.timeout(timeoutMs),
    })
  } catch (error) {
    if (preservesKnownClassification(error)) throw error
    throw classified(stage, error?.name === 'TimeoutError' ? 'TIMEOUT' : 'CONNECTIVITY', `${stage} request failed.`)
  }
  if (!result.ok) throw classified(stage, statusKind(result.status), `${stage} request was rejected.`, result.status)
  return result
}

async function graphql(providerTransport, environment, stage, query) {
  const result = await response(providerTransport, stage, providerUrl(
    stage,
    required(environment, 'DATAHUB_GMS_URL', stage),
    '/api/graphql',
  ), {
    method: 'POST',
    headers: { Authorization: `Bearer ${required(environment, 'DATAHUB_GMS_TOKEN', stage)}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  })
  const body = await result.json().catch(() => null)
  if (!body?.data || body.errors?.length) throw classified(stage, 'CONTRACT', `${stage} bounded read returned an invalid contract.`)
  return body.data
}

async function datahubPreflight(providerTransport, environment) {
  const catalog = await graphql(providerTransport, environment, 'DATAHUB',
    'query DataRiverPrepPreflight { search(input: { type: DATASET, query: "*", start: 0, count: 1 }) { start count total } }')
  if (!catalog.search) throw classified('DATAHUB', 'CONTRACT', 'DataHub bounded Dataset read returned an invalid contract.')
}

async function qualityReadPreflight(providerTransport, environment) {
  const assertions = await graphql(providerTransport, environment, 'QUALITY_READ',
    'query DataRiverQualityReadPreflight { search(input: { type: ASSERTION, query: "*", start: 0, count: 1 }) { start count total } }')
  if (!assertions.search || !Number.isSafeInteger(assertions.search.total) || assertions.search.total < 0) {
    throw classified('QUALITY_READ', 'CONTRACT', 'DataHub Assertion bounded read returned an invalid contract.')
  }
  return { assertion_count: assertions.search.total }
}

function llmStage(environment, prefix, stage) {
  return {
    url: required(environment, `${prefix}_URL`, stage),
    model: required(environment, `${prefix}_MODEL`, stage),
    token: required(environment, `${prefix}_TOKEN`, stage),
  }
}

async function llmPost(providerTransport, name, provider, endpoint, body, timeoutMs = providerTimeoutMs) {
  let url
  try {
    url = llmEndpoint(provider, endpoint)
    const parsed = new URL(url)
    if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) throw new Error('invalid provider URL')
    url = parsed.toString()
  } catch {
    throw classified(name, 'CONFIG', `${name} provider URL configuration is invalid.`)
  }
  const result = await response(providerTransport, name, url, {
    method: 'POST',
    headers: { Authorization: `Bearer ${provider.token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }, timeoutMs)
  return result.json().catch(() => null)
}

async function chatPreflight(providerTransport, environment) {
  const chat = llmStage(environment, 'LLM_CHAT', 'CHAT')
  let timeoutMs
  try {
    timeoutMs = parseLlmProviderTimeoutMs(environment.POC_LLM_TIMEOUT_MS)
  } catch {
    throw classified('CHAT', 'CONFIG', 'The Chat provider timeout configuration is invalid.')
  }
  const chatBody = await llmPost(providerTransport, 'CHAT', chat, '/chat/completions', {
    model: chat.model, messages: [{ role: 'user', content: 'Reply with OK.' }], max_tokens: 1, temperature: 0,
  }, timeoutMs)
  if (!Array.isArray(chatBody?.choices)) throw classified('CHAT', 'CONTRACT', 'Chat returned no choices.')
}

async function embeddingPreflight(providerTransport, environment) {
  const embedding = llmStage(environment, 'LLM_EMBEDDING', 'EMBEDDING')
  const embeddingBody = await llmPost(providerTransport, 'EMBEDDING', embedding, '/embeddings', {
    model: embedding.model, input: ['DataRiver PREP provider preflight'],
  })
  if (!Array.isArray(embeddingBody?.data)) throw classified('EMBEDDING', 'CONTRACT', 'Embedding returned no vectors.')
}

async function rerankerPreflight(providerTransport, environment) {
  const reranker = llmStage(environment, 'LLM_RERANKER', 'RERANKER')
  const rerankerBody = await llmPost(providerTransport, 'RERANKER', reranker, '/rerank', {
    model: reranker.model, query: 'DataRiver PREP provider preflight', documents: ['DataRiver PREP provider preflight'], top_n: 1,
  })
  if (!Array.isArray(rerankerBody?.results || rerankerBody?.data)) throw classified('RERANKER', 'CONTRACT', 'Reranker returned no ordered results.')
}

async function airflowPreflight(providerTransport, environment) {
  const url = environment.AIRFLOW_URL?.trim()
  const username = environment.AIRFLOW_USERNAME?.trim()
  const password = environment.AIRFLOW_PASSWORD?.trim()
  if (!url && !username && !password) return 'DEFERRED'
  if (!url || !username || !password) throw classified('AIRFLOW', 'CONFIG', 'Airflow URL and credentials must be configured together.')
  const request = async (path, options = {}) => {
    const endpoint = providerUrl('AIRFLOW', url, path)
    try {
      return await providerTransport.fetch(endpoint, {
        ...options, redirect: 'error', signal: AbortSignal.timeout(providerTimeoutMs),
      })
    } catch (error) {
      if (preservesKnownClassification(error)) throw error
      throw classified('AIRFLOW', 'CONNECTIVITY', 'Airflow quality dispatch request failed.')
    }
  }
  const tokenResponse = await request('/auth/token', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  let dag
  if (tokenResponse.ok) {
    const token = await tokenResponse.json().catch(() => null)
    if (typeof token?.access_token !== 'string' || !token.access_token.trim()) {
      throw classified('AIRFLOW', 'CONTRACT', 'Airflow v2 token response is invalid.')
    }
    dag = await request('/api/v2/dags/datariver_quality_dispatch', {
      headers: { Authorization: `Bearer ${token.access_token.trim()}` },
    })
  } else {
    const authorization = `Basic ${Buffer.from(`${username}:${password}`, 'utf8').toString('base64')}`
    dag = await request('/api/v1/dags/datariver_quality_dispatch', { headers: { Authorization: authorization } })
  }
  if (!dag.ok) throw classified('AIRFLOW', statusKind(dag.status), 'Airflow quality dispatch DAG was rejected.', dag.status)
  const body = await dag.json().catch(() => null)
  if (!body || (body.dag_id !== undefined && body.dag_id !== 'datariver_quality_dispatch')) {
    throw classified('AIRFLOW', 'CONTRACT', 'Airflow quality dispatch DAG returned an invalid contract.')
  }
  return 'READY'
}

async function minioPreflight(providerTransport, environment) {
  const url = environment.MINIO_URL?.trim()
  if (!url) return 'DEFERRED'
  await response(providerTransport, 'MINIO', providerUrl('MINIO', url, '/minio/health/ready'), {})
  return 'READY'
}

function intranetPreflight(environment) {
  let auth
  try {
    auth = loadPocLocalAuthConfig(environment)
  } catch (error) {
    if (error?.code === 'POC_INTRANET_HTTP_ALLOWED_CIDRS_INVALID') {
      throw classified('WEB_INTRANET', 'CIDR_CONFIG', 'The intranet CIDR configuration is invalid.')
    }
    if (error?.code === 'POC_PUBLIC_ORIGIN_NOT_APPROVED') {
      throw classified('WEB_INTRANET', 'ORIGIN_NOT_APPROVED', 'The HTTP origin is outside approved intranet ranges.')
    }
    if (error?.code === 'POC_PUBLIC_ORIGIN_MALFORMED') {
      throw classified('WEB_INTRANET', 'ORIGIN_MALFORMED', 'The intranet public origin is malformed.')
    }
    throw error
  }
  if (environment.POC_BIND_HOST?.trim() !== '0.0.0.0') {
    throw classified('WEB_INTRANET', 'BIND', 'PREP web must publish on the intranet bind address.')
  }
  if (environment.POC_STATE_BIND_HOST?.trim() !== '127.0.0.1') {
    throw classified('WEB_INTRANET', 'STATE_EXPOSURE', 'PREP state services must remain loopback-only.')
  }
  return auth.publicOrigin
}

export async function runProviderPreflight({
  environment = process.env,
  providerTransport,
  discoverMcl = discoverPocMclSource,
  operations = {},
} = {}) {
  const started = Date.now()
  let transport
  try {
    transport = providerTransport ?? createProviderTransport(environment)
  } catch {
    throw classified('RUNTIME_NETWORK', 'CONFIG', 'Runtime provider network configuration is invalid.')
  }
  const ownsTransport = !providerTransport
  let primaryError
  let cleanupError
  let preflightResult
  try {
    const publicOrigin = await knownStage('WEB_INTRANET', operations.webIntranet
      ?? (() => intranetPreflight(environment)))
    await knownStage('DATAHUB', operations.datahub
      ?? (() => datahubPreflight(transport, environment)))
    const datahub = await knownStage('QUALITY_READ', operations.qualityRead
      ?? (() => qualityReadPreflight(transport, environment)))
    await knownStage('CHAT', operations.chat
      ?? (() => chatPreflight(transport, environment)))
    await knownStage('EMBEDDING', operations.embedding
      ?? (() => embeddingPreflight(transport, environment)))
    await knownStage('RERANKER', operations.reranker
      ?? (() => rerankerPreflight(transport, environment)))
    const mcl = await knownStage('MCL_DISCOVERY', operations.mclDiscovery
      ?? (() => discoverMcl({ environment, providerTransport: transport })))
    const airflow = await knownStage('AIRFLOW', operations.airflow
      ?? (() => airflowPreflight(transport, environment)))
    const minio = await knownStage('MINIO', operations.minio
      ?? (() => minioPreflight(transport, environment)))
    preflightResult = {
      contract: 'DATARIVER_PREP39083_PROVIDER_PREFLIGHT_V2', status: 'PASS',
      web_intranet: 'READY', public_origin: publicOrigin,
      datahub: 'READY', chat: 'READY', embedding: 'READY', reranker: 'READY',
      k9_built_in: 'READY', mcl_change_history: 'READY', mcl_discovery: mcl.receipt,
      gx_quality_read: 'READY', gx_assertion_count: datahub.assertion_count,
      gx_quality_execution: airflow === 'READY' ? 'READY' : 'DEFERRED',
      airflow, minio, elapsed_ms: Date.now() - started,
    }
  } catch (error) {
    primaryError = error
  } finally {
    if (ownsTransport) {
      try {
        await transport.close()
      } catch {
        if (!primaryError) {
          cleanupError = classified('RUNTIME_NETWORK', 'UNEXPECTED', 'Runtime provider transport cleanup failed unexpectedly.')
        }
      }
    }
  }
  if (primaryError) throw primaryError
  if (cleanupError) throw cleanupError
  return preflightResult
}

const collectAllStageOperations = Object.freeze([
  ['WEB_INTRANET', 'webIntranet'],
  ['DATAHUB', 'datahub'],
  ['QUALITY_READ', 'qualityRead'],
  ['CHAT', 'chat'],
  ['EMBEDDING', 'embedding'],
  ['RERANKER', 'reranker'],
  ['MCL_DISCOVERY', 'mclDiscovery'],
  ['AIRFLOW', 'airflow'],
  ['MINIO', 'minio'],
])

function matrixFailure(error) {
  const failure = providerPreflightFailure(error)
  return Object.freeze({
    status: 'FAILED',
    classification: failure.classification,
    ...(failure.status_class === null ? {} : { status_class: failure.status_class }),
  })
}

function datahubDependencyUnavailable(entry) {
  if (entry?.status !== 'FAILED') return false
  return /_(AUTH|CONFIG|CONNECTIVITY|TIMEOUT)_FAILED$/.test(entry.classification)
}

function mclBlockedByDatahub(error, datahub) {
  return datahubDependencyUnavailable(datahub)
    && /^PREP_MCL_DISCOVERY_PROVIDER_(CONNECTIVITY|CONTRACT|VERSION)_FAILED$/.test(error?.code || '')
}

/**
 * Read-only diagnostic variant of the provider gate. Unlike deploy's fail-fast
 * runProviderPreflight(), doctor executes every independent stage and returns a
 * bounded, sanitized matrix. Provider bodies and discovery receipts are omitted.
 */
export async function collectProviderPreflight({
  environment = process.env,
  providerTransport,
  discoverMcl = discoverPocMclSource,
  operations = {},
} = {}) {
  let transport = providerTransport
  let transportError
  if (!transport) {
    try {
      transport = createProviderTransport(environment)
    } catch {
      transportError = classified('RUNTIME_NETWORK', 'CONFIG', 'Runtime provider network configuration is invalid.')
      transport = Object.freeze({
        async fetch() { throw new Error('Runtime provider transport is unavailable.') },
        async close() {},
      })
    }
  }
  const ownsTransport = !providerTransport && Boolean(transport)
  const entries = {}
  const operationByName = {
    webIntranet: () => intranetPreflight(environment),
    datahub: () => datahubPreflight(transport, environment),
    qualityRead: () => qualityReadPreflight(transport, environment),
    chat: () => chatPreflight(transport, environment),
    embedding: () => embeddingPreflight(transport, environment),
    reranker: () => rerankerPreflight(transport, environment),
    mclDiscovery: () => discoverMcl({ environment, providerTransport: transport }),
    airflow: () => airflowPreflight(transport, environment),
    minio: () => minioPreflight(transport, environment),
  }
  let internalFailure
  try {
    for (const [stage, name] of collectAllStageOperations) {
      if (stage === 'QUALITY_READ' && datahubDependencyUnavailable(entries.DATAHUB)) {
        entries[stage] = Object.freeze({ status: 'BLOCKED_BY_DEPENDENCY', dependency: 'DATAHUB' })
        continue
      }
      if (transportError && !['WEB_INTRANET', 'MCL_DISCOVERY'].includes(stage)) {
        entries[stage] = matrixFailure(classified(
          stage, 'RUNTIME_NETWORK_CONFIG', `${stage} runtime network configuration is invalid.`,
        ))
        continue
      }
      try {
        const result = await knownStage(stage, operations[name] ?? operationByName[name])
        entries[stage] = Object.freeze({ status: result === 'DEFERRED' ? 'DEFERRED' : 'READY' })
      } catch (error) {
        if (stage === 'MCL_DISCOVERY' && mclBlockedByDatahub(error, entries.DATAHUB)) {
          entries[stage] = Object.freeze({ status: 'BLOCKED_BY_DEPENDENCY', dependency: 'DATAHUB' })
        } else {
          entries[stage] = matrixFailure(error)
        }
      }
    }
  } finally {
    if (ownsTransport) {
      try {
        await transport.close()
      } catch {
        internalFailure = 'PREP_PREFLIGHT_RUNTIME_NETWORK_CLEANUP_UNEXPECTED_FAILED'
      }
    }
  }
  const complete = collectAllStageOperations.every(([stage]) => entries[stage])
  const failed = Object.values(entries).some((entry) => (
    entry.status === 'FAILED' || entry.status === 'BLOCKED_BY_DEPENDENCY'
  ))
  return Object.freeze({
    contract: 'DATARIVER_PREP39083_PROVIDER_PREFLIGHT_MATRIX_V1',
    status: !complete || failed || internalFailure ? 'FAILED' : 'PASS',
    stages: Object.freeze(entries),
    ...(internalFailure ? { internal_classification: internalFailure } : {}),
  })
}

export function providerPreflightFailure(error) {
  const mcl = typeof error?.code === 'string' && error.code.startsWith('PREP_MCL_DISCOVERY_')
  return Object.freeze({
    contract: 'DATARIVER_PREP39083_PROVIDER_PREFLIGHT_V2', status: 'FAILED',
    stage: mcl ? 'MCL_DISCOVERY' : error?.stage || 'INTERNAL',
    classification: mcl ? error.code : error?.classification || 'PREP_PREFLIGHT_INTERNAL_UNEXPECTED_FAILED',
    status_class: Number.isInteger(error?.status) ? `${Math.floor(error.status / 100)}xx` : null,
  })
}

async function main() {
  if (process.argv.slice(2).includes('--collect-all')) {
    try {
      const matrix = await collectProviderPreflight()
      process.stdout.write(`${JSON.stringify(matrix)}\n`)
      if (matrix.status !== 'PASS') process.exitCode = 2
    } catch (error) {
      process.stderr.write(`${JSON.stringify(providerPreflightFailure(error))}\n`)
      process.exitCode = 2
    }
    return
  }
  try {
    process.stdout.write(`${JSON.stringify(await runProviderPreflight())}\n`)
  } catch (error) {
    process.stderr.write(`${JSON.stringify(providerPreflightFailure(error))}\n`)
    process.exitCode = 2
  }
}

if (resolve(process.argv[1] || '') === resolve(fileURLToPath(import.meta.url))) await main()
