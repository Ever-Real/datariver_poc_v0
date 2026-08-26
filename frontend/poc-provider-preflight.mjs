/* global AbortSignal */
import { readFile } from 'node:fs/promises'
import process from 'node:process'

import pg from 'pg'

import {
  createProviderTransport,
  joinProviderUrl,
  llmEndpoint,
} from './poc-provider-transport.mjs'
import { parseLlmProviderTimeoutMs } from './poc-llm-timeout.mjs'

const { Pool } = pg
const providerTimeoutMs = 60_000
const llmProviderTimeoutMs = parseLlmProviderTimeoutMs(process.env.POC_LLM_TIMEOUT_MS)

function required(name) {
  const value = process.env[name]?.trim()
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
      ...options,
      redirect: 'error',
      signal: AbortSignal.timeout(timeoutMs),
    })
  } catch (error) {
    throw classified(
      stage,
      error?.name === 'TimeoutError' ? 'TIMEOUT' : 'CONNECTIVITY',
      `${stage} request failed.`,
    )
  }
  if (!result.ok) throw classified(stage, statusKind(result.status), `${stage} request was rejected.`, result.status)
  return result
}

async function datahubPreflight(providerTransport) {
  const url = required('DATAHUB_GMS_URL')
  const token = required('DATAHUB_GMS_TOKEN')
  const result = await response(providerTransport, 'DATAHUB', joinProviderUrl(url, '/api/graphql'), {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: 'query DataRiverPrepPreflight { search(input: { type: DATASET, query: "*", start: 0, count: 1 }) { start count total } }',
    }),
  })
  const body = await result.json().catch(() => null)
  if (!body?.data?.search || body.errors?.length) {
    throw classified('DATAHUB', 'CONTRACT', 'DataHub bounded read returned an invalid contract.')
  }
}

function stage(prefix) {
  return {
    url: required(`${prefix}_URL`),
    model: required(`${prefix}_MODEL`),
    token: required(`${prefix}_TOKEN`),
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

async function providerPreflights(providerTransport) {
  const chat = stage('LLM_CHAT')
  const chatBody = await llmPost(providerTransport, 'CHAT', chat, '/chat/completions', {
    model: chat.model,
    messages: [{ role: 'user', content: 'Reply with OK.' }],
    max_tokens: 1,
    temperature: 0,
  }, llmProviderTimeoutMs)
  if (!Array.isArray(chatBody?.choices)) throw classified('CHAT', 'CONTRACT', 'Chat returned no choices.')

  const embedding = stage('LLM_EMBEDDING')
  const embeddingBody = await llmPost(providerTransport, 'EMBEDDING', embedding, '/embeddings', {
    model: embedding.model,
    input: ['DataRiver PREP provider preflight'],
  })
  if (!Array.isArray(embeddingBody?.data)) throw classified('EMBEDDING', 'CONTRACT', 'Embedding returned no vectors.')

  const reranker = stage('LLM_RERANKER')
  const rerankerBody = await llmPost(providerTransport, 'RERANKER', reranker, '/rerank', {
    model: reranker.model,
    query: 'DataRiver PREP provider preflight',
    documents: ['DataRiver PREP provider preflight'],
    top_n: 1,
  })
  if (!Array.isArray(rerankerBody?.results || rerankerBody?.data)) {
    throw classified('RERANKER', 'CONTRACT', 'Reranker returned no ordered results.')
  }
}

async function studioPreflight() {
  const connectionString = process.env.POC_K9_STUDIO_DATABASE_URL?.trim()
  if (!connectionString) return 'DEFERRED'
  const caPath = process.env.POC_RUNTIME_CA_CERT_FILE?.trim()
  const ssl = caPath ? { ca: await readFile(caPath, 'utf8'), rejectUnauthorized: true } : undefined
  const pool = new Pool({ connectionString, max: 1, connectionTimeoutMillis: 30_000, query_timeout: 30_000, ssl })
  try {
    const client = await pool.connect()
    try {
      await client.query('BEGIN READ ONLY')
      await client.query('SELECT 1')
      await client.query('ROLLBACK')
    } finally {
      client.release()
    }
  } catch (error) {
    throw classified('K9_STUDIO', error?.code === '28P01' ? 'AUTH' : 'CONNECTIVITY', 'K9 Studio read-only preflight failed.')
  } finally {
    await pool.end()
  }
  return 'PASS'
}

async function main() {
  const started = Date.now()
  let providerTransport
  try {
    providerTransport = createProviderTransport(process.env)
  } catch {
    throw classified('RUNTIME_NETWORK', 'CONFIG', 'Runtime provider network configuration is invalid.')
  }
  try {
    await datahubPreflight(providerTransport)
    await providerPreflights(providerTransport)
    const k9Studio = await studioPreflight()
    process.stdout.write(`${JSON.stringify({
      contract: 'DATARIVER_PREP39083_PROVIDER_PREFLIGHT_V1',
      status: 'PASS',
      datahub: 'PASS',
      chat: 'PASS',
      embedding: 'PASS',
      reranker: 'PASS',
      k9_studio: k9Studio,
      elapsed_ms: Date.now() - started,
    })}\n`)
  } finally {
    await providerTransport.close()
  }
}

main().catch((error) => {
  process.stderr.write(`${JSON.stringify({
    contract: 'DATARIVER_PREP39083_PROVIDER_PREFLIGHT_V1',
    status: 'FAILED',
    stage: error?.stage || 'UNKNOWN',
    classification: error?.classification || 'PREP_PREFLIGHT_UNKNOWN_FAILED',
    status_class: Number.isInteger(error?.status) ? `${Math.floor(error.status / 100)}xx` : null,
  })}\n`)
  process.exitCode = 2
})
