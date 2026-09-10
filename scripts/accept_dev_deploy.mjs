#!/usr/bin/env node
/* global AbortSignal, URL, URLSearchParams, fetch, setTimeout */

import { lstat, readFile, writeFile } from 'node:fs/promises'
import process from 'node:process'
import { requestBudget, retryAllowed, withReadinessDeadline } from './readiness.mjs'

function option(name, fallback = null) {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : fallback
}

function fail(code, options = {}) {
  throw Object.assign(new Error(code), options)
}

function safeCode(value) {
  return typeof value === 'string' && /^[A-Z][A-Z0-9_]{0,95}$/.test(value) ? value : null
}

function safeRca(value) {
  if (!value) return null
  return Object.fromEntries(['state', 'stage', 'code', 'detail'].map((key) => [key, safeCode(value[key])]))
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
  let response
  try {
    response = await fetch(url, { ...init, signal: AbortSignal.timeout(requestBudget()) })
  } catch (error) {
    fail(error?.name === 'TimeoutError' ? 'REQUEST_TIMEOUT' : 'REQUEST_CONNECTIVITY_FAILED', {
      retryable: !init.method || ['GET', 'HEAD'].includes(init.method),
    })
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) fail(`HTTP_${response.status}`, {
    status: response.status,
    providerCode: safeCode(body?.code),
    retryable: [408, 429, 502, 503, 504].includes(response.status),
  })
  return { response, body }
}

const origin = option('--origin', 'http://127.0.0.1:8080')
const requestOrigin = option('--request-origin')
const username = option('--username')
const passwordFile = option('--password-file')
const output = option('--output')
const phase = option('--phase', 'all')
if (!['all', 'readiness', 'features'].includes(phase)) fail('PHASE_INVALID')

if (!requestOrigin || !username || !passwordFile || !output) fail('INPUT_INVALID')
for (const value of [origin, requestOrigin]) {
  const parsed = new URL(value)
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) fail('ORIGIN_INVALID')
}

const result = {
  contract: 'DATARIVER_DEV_DEPLOY_ACCEPTANCE_V1',
  phase,
  started_at: new Date().toISOString(),
  accepted_at: null,
  auto_chat: 'NOT_RUN',
  graph_chat: 'NOT_RUN',
  knowledge_graph_preview: 'NOT_RUN',
  mcl_current: 'NOT_RUN',
  mcl_history: 'NOT_RUN',
  k9_semantic: 'NOT_RUN',
  auto_graph: 'NOT_RUN',
  auto_search: 'NOT_RUN',
  vector_chat: 'NOT_RUN',
  k9_rca: null,
  mcl_rca: null,
}

async function retryReady(operation, timeoutMs = 1_200_000) {
  const deadline = Date.now() + timeoutMs
  let lastError
  do {
    try {
      return await withReadinessDeadline(deadline, operation)
    } catch (error) {
      if (lastError && error?.retryable && Date.now() >= deadline) break
      lastError = error
      if (!retryAllowed(error)) throw error
      if (Date.now() >= deadline) break
      await new Promise((resolve) => setTimeout(resolve, Math.min(15_000, Math.max(0, deadline - Date.now()))))
    }
  } while (Date.now() < deadline)
  throw lastError
}

let cookie
let check = 'ADMIN_LOGIN'
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
  if (phase !== 'features') {
  check = 'K9'
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
      result.k9_rca = safeRca({
        stage: semantic?.diagnostic?.stage || 'AGGREGATE_READINESS',
        code: semantic?.diagnostic?.code || lifecycle?.aggregate?.reason || 'K9_NOT_READY',
        detail: semantic?.diagnostic?.failure_detail_code || null,
      })
      fail('K9_SEMANTIC_NOT_READY', { terminal: !lifecycle || [lifecycle?.source, lifecycle?.aggregate, ...Object.values(lifecycle?.projectors || {})].some((item) => item?.status === 'FAILED') })
    }
  })
  result.k9_semantic = 'READY'
  result.k9_rca = null

  check = 'MCL'
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
      result.mcl_rca = safeRca({
        state: body?.capture_state || 'UNKNOWN',
        stage: body?.capture_failure_stage || null,
        code: body?.capture_failure_classification || 'MCL_CURRENT_NOT_READY',
        detail: body?.capture_failure_detail_code || null,
      })
      fail('MCL_CURRENT_NOT_READY', { terminal: !['CAPTURING', 'CAPTURE_IN_PROGRESS', 'CAPTURE_PENDING', 'CAPTURE_CATCHING_UP', 'CONTIGUOUS_CAPTURE_RECORDED', 'CAPTURE_CAUGHT_UP'].includes(body?.capture_state) || (body?.capture_state === 'CAPTURE_CAUGHT_UP' && !acceptedHistory) })
    }
    result.mcl_history = body.history_completeness
  })
  result.mcl_current = 'READY'
  result.mcl_rca = null
  }

  if (phase !== 'readiness') {
  if (phase === 'features') {
    check = 'CANONICAL_SMOKE_EVIDENCE'
    const smoke = JSON.parse(await readFile(option('--canonical-smoke'), 'utf8'))
    if (smoke.smoke_product_sha !== option('--source-sha') || smoke.request_origin !== requestOrigin
      || smoke.origin !== origin || smoke.llm_general !== 'PASS'
      || smoke.mcl_current_capture !== 'READY' || smoke.semantic_index !== 'PASS'
      || Date.now() - Date.parse(smoke.generated_at) > 1_800_000) fail('CANONICAL_SMOKE_EVIDENCE_INVALID')
    result.auto_chat = 'PASS'
    result.mcl_current = 'READY'
    result.mcl_history = smoke.mcl_history_completeness
    result.k9_semantic = 'READY'
    result.general_evidence = 'SAME_DEPLOY_CANONICAL_SMOKE'
    managedAssets = await jsonRequest(`${origin}/poc-api/knowledge/managed-assets`, { headers: { Cookie: cookie } })
  } else {
  check = 'AUTO_GENERAL_CHAT'
  const auto = await jsonRequest(`${origin}/poc-api/llm/chat`, {
    method: 'POST', headers,
    body: JSON.stringify({ question: '데이터 계보가 무엇인지 일반적으로 설명해줘.', mode: 'AUTO' }),
  })
  if (auto.body?.route?.selected_mode !== 'GENERAL'
    || typeof auto.body?.answer !== 'string' || !auto.body.answer.trim()) fail('AUTO_CHAT_CONTRACT')
  result.auto_chat = 'PASS'
  }

  // Bounded positive target selection, across pages; do not assert on an accidental first25.
  check = 'CATALOG_LINEAGE'
  let table
  let cursor
  let lineageReads = 0
  let targetLineage
  const seenCursors = new Set()
  for (let page = 0; page < 10 && !table; page += 1) {
    const query = new URLSearchParams({ asset_type: 'DATASET', limit: '100' })
    if (cursor) query.set('cursor', cursor)
    const catalog = await jsonRequest(`${origin}/poc-api/datahub/catalog?${query}`, { headers: { Cookie: cookie } })
    const candidates = (Array.isArray(catalog.body?.items) ? catalog.body.items : [])
      .filter((item) => item?.dataset_kind === 'TABLE' && typeof item?.id === 'string'
        && typeof item?.name === 'string' && item.name.trim())
    for (const candidate of candidates) {
      if (lineageReads >= 20) break
      lineageReads += 1
      const lineage = await jsonRequest(`${origin}/poc-api/datahub/lineage?${new URLSearchParams({ urn: candidate.id, direction: 'DOWNSTREAM', depth: '1' })}`, { headers: { Cookie: cookie } })
      if (lineage.body?.center_asset_id !== candidate.id || !Array.isArray(lineage.body?.edges)) fail('LINEAGE_READBACK_CONTRACT')
      if (lineage.body.edges.length) { table = candidate; targetLineage = lineage.body; break }
    }
    if (lineageReads >= 20 && !table) break
    cursor = catalog.body?.page?.next_cursor
    if (!cursor) break
    if (seenCursors.has(cursor)) fail('CATALOG_CURSOR_STALLED')
    seenCursors.add(cursor)
  }
  if (!table) fail('NO_TEST_DATA_GRAPH_RELATION')
  result.target_selection = { catalog_page_limit: 10, lineage_reads: lineageReads, read_only: true }
  for (const [name, mode, expected, question] of [
    ['graph_chat', 'GRAPH', 'GRAPH', `${table.name} 테이블을 변경하면 어떤 테이블이 영향을 받지?`],
    ['auto_graph', 'AUTO', 'GRAPH', `${table.name} 테이블의 downstream 변경 영향과 데이터 계보를 분석해줘.`],
    ['vector_chat', 'VECTOR', 'VECTOR', `${table.name} 테이블의 설명과 메타데이터를 검색해줘.`],
    ['auto_search', 'AUTO', 'VECTOR', `${table.name} 테이블의 설명과 메타데이터를 검색해줘.`],
  ]) {
    check = name.toUpperCase()
    const chat = await jsonRequest(`${origin}/poc-api/llm/chat`, {
      method: 'POST', headers, body: JSON.stringify({ question, mode }),
    })
    const evidence = Array.isArray(chat.body?.evidence) ? chat.body.evidence : []
    if (chat.body?.route?.selected_mode !== expected || typeof chat.body?.answer !== 'string'
      || !chat.body.answer.trim() || evidence.length === 0) fail(`${name.toUpperCase()}_CONTRACT`)
    // Require evidence tied to the authorized table identity, not just an HTTP200 answer.
    if (!evidence.some((item) => [item.id, item.external_urn, item.source_locator,
      ...(item.graph_nodes || []).flatMap((node) => [node.id, node.source_locator])].includes(table.id))) {
      fail(`${name.toUpperCase()}_READBACK_MISSING`)
    }
    if (expected === 'GRAPH') {
      const related = new Set(targetLineage.edges.flatMap((edge) => [edge.source_asset_id, edge.target_asset_id]))
      related.delete(table.id)
      const locators = evidence.flatMap((item) => [item.id, item.source_locator, item.external_urn,
        ...(item.relationships || []).map((relation) => relation.urn),
        ...(item.graph_nodes || []).flatMap((node) => [node.id, node.source_locator])])
      if (!locators.some((id) => related.has(id))) fail(`${name.toUpperCase()}_RELATION_READBACK_MISSING`)
    }
    result[name] = 'PASS'
  }

  check = 'KNOWLEDGE_GRAPH_PREVIEW'
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
  }
  check = 'RECEIPT_WRITE'
  result.accepted_at = new Date().toISOString()
  await writeFile(output, `${JSON.stringify(result, null, 2)}\n`, { mode: 0o600 })
  process.stdout.write(`${JSON.stringify(result)}\n`)
} catch (error) {
  const code = safeCode(error?.message) || 'FOCUSED_ACCEPTANCE_FAILED'
  const failedKey = {
    K9: 'k9_semantic', MCL: 'mcl_current', AUTO_GENERAL_CHAT: 'auto_chat',
    GRAPH_CHAT: 'graph_chat', AUTO_GRAPH: 'auto_graph', VECTOR_CHAT: 'vector_chat',
    AUTO_SEARCH: 'auto_search', KNOWLEDGE_GRAPH_PREVIEW: 'knowledge_graph_preview',
  }[check]
  if (failedKey && ![401, 403].includes(error?.status)) result[failedKey] = 'FAIL'
  const diagnostic = check === 'K9' ? safeRca(result.k9_rca)
    : check === 'MCL' ? safeRca(result.mcl_rca) : null
  const failure = {
    contract: 'DATARIVER_DEV_DEPLOY_ACCEPTANCE_FAILURE_V1',
    status: 'FAILED', phase, stage: check, code,
    http_status: Number.isInteger(error?.status) ? error.status : null,
    provider_code: safeCode(error?.providerCode),
    diagnostic,
    failed_at: new Date().toISOString(),
  }
  result.accepted_at = null
  result.failure_code = code
  result.failure = failure
  await writeFile(output, `${JSON.stringify(result, null, 2)}\n`, { mode: 0o600 }).catch(() => undefined)
  process.stderr.write(`${JSON.stringify(failure)}\n`)
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
