/* global AbortSignal, Buffer, process */
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { loadPocLocalAuthConfig } from './poc-local-auth.mjs'
import { discoverPocMclSource } from './poc-mcl-discovery.mjs'
import { createProviderTransport, joinProviderUrl, llmEndpoint } from './poc-provider-transport.mjs'
import { parseLlmProviderTimeoutMs } from './poc-llm-timeout.mjs'

const providerTimeoutMs = 60_000

function required(environment, name) {
  const value = environment[name]?.trim()
  if (!value) throw classified(name, 'CONFIG', `${name} is not configured.`)
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

async function response(providerTransport, stage, url, options, timeoutMs = providerTimeoutMs) {
  let result
  try {
    result = await providerTransport.fetch(url, {
      ...options, redirect: 'error', signal: AbortSignal.timeout(timeoutMs),
    })
  } catch (error) {
    throw classified(stage, error?.name === 'TimeoutError' ? 'TIMEOUT' : 'CONNECTIVITY', `${stage} request failed.`)
  }
  if (!result.ok) throw classified(stage, statusKind(result.status), `${stage} request was rejected.`, result.status)
  return result
}

async function graphql(providerTransport, environment, stage, query) {
  const result = await response(providerTransport, stage, joinProviderUrl(required(environment, 'DATAHUB_GMS_URL'), '/api/graphql'), {
    method: 'POST',
    headers: { Authorization: `Bearer ${required(environment, 'DATAHUB_GMS_TOKEN')}`, 'Content-Type': 'application/json' },
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
  const assertions = await graphql(providerTransport, environment, 'QUALITY_READ',
    'query DataRiverQualityReadPreflight { search(input: { type: ASSERTION, query: "*", start: 0, count: 1 }) { start count total } }')
  if (!assertions.search || !Number.isSafeInteger(assertions.search.total) || assertions.search.total < 0) {
    throw classified('QUALITY_READ', 'CONTRACT', 'DataHub Assertion bounded read returned an invalid contract.')
  }
  return { assertion_count: assertions.search.total }
}

function llmStage(environment, prefix) {
  return {
    url: required(environment, `${prefix}_URL`),
    model: required(environment, `${prefix}_MODEL`),
    token: required(environment, `${prefix}_TOKEN`),
  }
}

async function llmPost(providerTransport, name, provider, endpoint, body, timeoutMs = providerTimeoutMs) {
  const result = await response(providerTransport, name, llmEndpoint(provider, endpoint), {
    method: 'POST',
    headers: { Authorization: `Bearer ${provider.token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }, timeoutMs)
  return result.json().catch(() => null)
}

async function llmPreflights(providerTransport, environment) {
  const chat = llmStage(environment, 'LLM_CHAT')
  const chatBody = await llmPost(providerTransport, 'CHAT', chat, '/chat/completions', {
    model: chat.model, messages: [{ role: 'user', content: 'Reply with OK.' }], max_tokens: 1, temperature: 0,
  }, parseLlmProviderTimeoutMs(environment.POC_LLM_TIMEOUT_MS))
  if (!Array.isArray(chatBody?.choices)) throw classified('CHAT', 'CONTRACT', 'Chat returned no choices.')
  const embedding = llmStage(environment, 'LLM_EMBEDDING')
  const embeddingBody = await llmPost(providerTransport, 'EMBEDDING', embedding, '/embeddings', {
    model: embedding.model, input: ['DataRiver PREP provider preflight'],
  })
  if (!Array.isArray(embeddingBody?.data)) throw classified('EMBEDDING', 'CONTRACT', 'Embedding returned no vectors.')
  const reranker = llmStage(environment, 'LLM_RERANKER')
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
    try {
      return await providerTransport.fetch(joinProviderUrl(url, path), {
        ...options, redirect: 'error', signal: AbortSignal.timeout(providerTimeoutMs),
      })
    } catch {
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
  await response(providerTransport, 'MINIO', joinProviderUrl(url, '/minio/health/ready'), {})
  return 'READY'
}

function intranetPreflight(environment) {
  let auth
  try {
    auth = loadPocLocalAuthConfig(environment)
  } catch {
    throw classified('WEB_INTRANET', 'ORIGIN', 'The intranet public origin is invalid.')
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
} = {}) {
  const started = Date.now()
  let transport
  try {
    transport = providerTransport ?? createProviderTransport(environment)
  } catch {
    throw classified('RUNTIME_NETWORK', 'CONFIG', 'Runtime provider network configuration is invalid.')
  }
  const ownsTransport = !providerTransport
  try {
    const publicOrigin = intranetPreflight(environment)
    const datahub = await datahubPreflight(transport, environment)
    await llmPreflights(transport, environment)
    const mcl = await discoverMcl({ environment, providerTransport: transport })
    const airflow = await airflowPreflight(transport, environment)
    const minio = await minioPreflight(transport, environment)
    return {
      contract: 'DATARIVER_PREP39083_PROVIDER_PREFLIGHT_V2', status: 'PASS',
      web_intranet: 'READY', public_origin: publicOrigin,
      datahub: 'READY', chat: 'READY', embedding: 'READY', reranker: 'READY',
      k9_built_in: 'READY', mcl_change_history: 'READY', mcl_discovery: mcl.receipt,
      gx_quality_read: 'READY', gx_assertion_count: datahub.assertion_count,
      gx_quality_execution: airflow === 'READY' ? 'READY' : 'DEFERRED',
      airflow, minio, elapsed_ms: Date.now() - started,
    }
  } finally {
    if (ownsTransport) await transport.close()
  }
}

async function main() {
  try {
    process.stdout.write(`${JSON.stringify(await runProviderPreflight())}\n`)
  } catch (error) {
    const classification = error?.code?.startsWith('PREP_MCL_DISCOVERY_')
      ? error.code : error?.classification || 'PREP_PREFLIGHT_UNKNOWN_FAILED'
    process.stderr.write(`${JSON.stringify({
      contract: 'DATARIVER_PREP39083_PROVIDER_PREFLIGHT_V2', status: 'FAILED',
      stage: error?.code?.startsWith('PREP_MCL_DISCOVERY_') ? 'MCL_DISCOVERY' : error?.stage || 'UNKNOWN',
      classification,
      status_class: Number.isInteger(error?.status) ? `${Math.floor(error.status / 100)}xx` : null,
    })}\n`)
    process.exitCode = 2
  }
}

if (resolve(process.argv[1] || '') === resolve(fileURLToPath(import.meta.url))) await main()
