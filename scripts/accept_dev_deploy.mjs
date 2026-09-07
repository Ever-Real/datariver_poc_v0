#!/usr/bin/env node
/* global AbortSignal, URL, fetch */

import { lstat, readFile, writeFile } from 'node:fs/promises'
import process from 'node:process'

function option(name, fallback = null) {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : fallback
}

function fail(code) {
  throw new Error(code)
}

async function privateSecret(path) {
  const metadata = await lstat(path)
  if (!metadata.isFile() || metadata.isSymbolicLink() || (metadata.mode & 0o077) !== 0) {
    fail('ADMIN_PASSWORD_FILE_INSECURE')
  }
  const value = (await readFile(path, 'utf8')).trim()
  if (!value) fail('ADMIN_PASSWORD_EMPTY')
  return value
}

async function jsonRequest(url, init = {}) {
  const response = await fetch(url, { ...init, signal: AbortSignal.timeout(300_000) })
  const body = await response.json().catch(() => null)
  if (!response.ok) fail(`HTTP_${response.status}`)
  return { response, body }
}

const origin = option('--origin', 'http://127.0.0.1:8080')
const requestOrigin = option('--request-origin')
const username = option('--username')
const passwordFile = option('--password-file')
const output = option('--output')

if (!requestOrigin || !username || !passwordFile || !output) fail('INPUT_INVALID')
for (const value of [origin, requestOrigin]) {
  const parsed = new URL(value)
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) fail('ORIGIN_INVALID')
}

const result = {
  contract: 'DATARIVER_DEV_DEPLOY_ACCEPTANCE_V1',
  accepted_at: new Date().toISOString(),
  auto_chat: 'FAIL',
  graph_chat: 'FAIL',
  knowledge_graph_preview: 'FAIL',
  mcl_current: 'FAIL',
  mcl_history: 'UNKNOWN',
  k9_semantic: 'FAIL',
  k9_rca: null,
  mcl_rca: null,
}

async function retryReady(operation, timeoutMs = 1_200_000) {
  const deadline = Date.now() + timeoutMs
  let lastError
  do {
    try {
      return await operation()
    } catch (error) {
      lastError = error
      if (Date.now() >= deadline) break
      await new Promise((resolve) => setTimeout(resolve, 15_000))
    }
  } while (Date.now() < deadline)
  throw lastError
}

let cookie
try {
  const password = await privateSecret(passwordFile)
  const login = await jsonRequest(`${origin}/auth/login`, {
    method: 'POST',
    headers: { Origin: requestOrigin, 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  cookie = login.response.headers.get('set-cookie')?.split(';', 1)[0]
  if (!cookie) fail('LOGIN_COOKIE_MISSING')
  const headers = { Cookie: cookie, Origin: requestOrigin, 'Content-Type': 'application/json' }

  let managedAssets
  await retryReady(async () => {
    managedAssets = await jsonRequest(`${origin}/poc-api/knowledge/managed-assets`, {
      headers: { Cookie: cookie },
    })
    const lifecycle = managedAssets.body?.k9_lifecycle
    const sourceId = lifecycle?.source?.desired_snapshot_id
    const projectors = ['LINEAGE', 'METADATA', 'SEMANTIC']
    if (lifecycle?.contract !== 'DATARIVER_K9_LIFECYCLE_STATUS_V2'
      || lifecycle?.aggregate?.status !== 'READY' || lifecycle?.source?.status !== 'READY'
      || typeof sourceId !== 'string' || !/^[0-9a-f]{64}$/.test(sourceId)
      || lifecycle.source.active_snapshot_id !== sourceId
      || projectors.some((name) => lifecycle?.projectors?.[name]?.status !== 'READY'
        || lifecycle.projectors[name].desired_snapshot_id !== sourceId
        || lifecycle.projectors[name].active_snapshot_id !== sourceId)) {
      const semantic = lifecycle?.projectors?.SEMANTIC
      result.k9_rca = {
        stage: semantic?.diagnostic?.stage || 'AGGREGATE_READINESS',
        code: semantic?.diagnostic?.code || lifecycle?.aggregate?.reason || 'K9_NOT_READY',
        detail: semantic?.diagnostic?.failure_detail_code || null,
      }
      fail('K9_SEMANTIC_NOT_READY')
    }
  })
  result.k9_semantic = 'READY'

  const week = new Date()
  week.setUTCDate(week.getUTCDate() - ((week.getUTCDay() + 6) % 7))
  const weekStart = week.toISOString().slice(0, 10)
  await retryReady(async () => {
    const summary = await jsonRequest(`${origin}/api/v1/change-history/summary?week_start=${weekStart}`, {
      headers: { Cookie: cookie },
    })
    const body = summary.body
    const acceptedHistory = body?.history_completeness === 'EXACT'
      || (body?.history_completeness === 'DEGRADED_GAP'
        && body?.history_gap_reason === 'RETENTION_EXPIRED')
    if (body?.capture_state !== 'CAPTURE_CAUGHT_UP' || !acceptedHistory) {
      result.mcl_rca = {
        state: body?.capture_state || 'UNKNOWN',
        stage: body?.capture_failure_stage || null,
        code: body?.capture_failure_classification || 'MCL_CURRENT_NOT_READY',
        detail: body?.capture_failure_detail_code || null,
      }
      fail('MCL_CURRENT_NOT_READY')
    }
    result.mcl_history = body.history_completeness
  })
  result.mcl_current = 'READY'

  const auto = await jsonRequest(`${origin}/poc-api/llm/chat`, {
    method: 'POST', headers,
    body: JSON.stringify({ question: '데이터 계보가 무엇인지 일반적으로 설명해줘.', mode: 'AUTO' }),
  })
  if (auto.body?.route?.selected_mode !== 'GENERAL'
    || typeof auto.body?.answer !== 'string' || !auto.body.answer.trim()) fail('AUTO_CHAT_CONTRACT')
  result.auto_chat = 'PASS'

  const catalog = await jsonRequest(`${origin}/poc-api/datahub/catalog?asset_type=DATASET&limit=25`, {
    headers: { Cookie: cookie },
  })
  const table = (Array.isArray(catalog.body?.items) ? catalog.body.items : [])
    .find((item) => item?.dataset_kind === 'TABLE' && typeof item?.name === 'string' && item.name.trim())
  if (!table) fail('GRAPH_CHAT_TABLE_NOT_FOUND')
  const graph = await jsonRequest(`${origin}/poc-api/llm/chat`, {
    method: 'POST', headers,
    body: JSON.stringify({ question: `${table.name} 테이블을 변경하면 어떤 테이블이 영향을 받지?`, mode: 'GRAPH' }),
  })
  if (graph.body?.route?.selected_mode !== 'GRAPH'
    || typeof graph.body?.answer !== 'string' || !graph.body.answer.trim()) fail('GRAPH_CHAT_CONTRACT')
  result.graph_chat = 'PASS'

  const candidate = (Array.isArray(managedAssets.body?.items) ? managedAssets.body.items : [])
    .find((item) => ['READY', 'ACTIVE'].includes(item?.status) && typeof item?.active_release_id === 'string'
      && item.active_release_id && item?.projection_state === 'READY')
  if (!candidate) fail('KNOWLEDGE_GRAPH_NOT_PUBLISHED')
  const encodedGraph = encodeURIComponent(candidate.id)
  const encodedRelease = encodeURIComponent(candidate.active_release_id)
  const versions = await jsonRequest(`${origin}/poc-api/knowledge/managed-assets/${encodedGraph}/versions`, {
    headers: { Cookie: cookie },
  })
  if (!(Array.isArray(versions.body?.items)
    && versions.body.items.some((item) => item?.is_current === true && item?.status === 'READY'))) {
    fail('KNOWLEDGE_GRAPH_VERSION_NOT_PUBLISHED')
  }
  const snapshot = await jsonRequest(
    `${origin}/poc-api/knowledge/graphs/${encodedGraph}/releases/${encodedRelease}/snapshot?maximum_nodes=200`,
    { headers: { Cookie: cookie } },
  )
  if (snapshot.body?.release?.id !== candidate.active_release_id
    || !Array.isArray(snapshot.body?.nodes) || !Array.isArray(snapshot.body?.edges)) {
    fail('KNOWLEDGE_GRAPH_PREVIEW_CONTRACT')
  }
  result.knowledge_graph_preview = 'PASS'
  await writeFile(output, `${JSON.stringify(result, null, 2)}\n`, { mode: 0o600 })
  process.stdout.write(`${JSON.stringify(result)}\n`)
} catch (error) {
  const code = /^[A-Z][A-Z0-9_]{0,95}$/.test(error?.message || '')
    ? error.message : 'FOCUSED_ACCEPTANCE_FAILED'
  result.failure_code = code
  await writeFile(output, `${JSON.stringify(result, null, 2)}\n`, { mode: 0o600 }).catch(() => undefined)
  process.stderr.write(`${JSON.stringify({ status: 'FAILED', code })}\n`)
  process.exitCode = 2
} finally {
  if (cookie) {
    await fetch(`${origin}/auth/logout`, {
      method: 'POST',
      headers: { Cookie: cookie, Origin: requestOrigin, 'Content-Type': 'application/json' },
      body: '{}', signal: AbortSignal.timeout(10_000),
    }).catch(() => undefined)
  }
}
