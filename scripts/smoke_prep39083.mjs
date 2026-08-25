#!/usr/bin/env node

import { lstat, readFile, writeFile } from 'node:fs/promises'
import process from 'node:process'

function argument(name, fallback = null) {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : fallback
}

async function privateSecret(path) {
  const metadata = await lstat(path)
  if (!metadata.isFile() || metadata.isSymbolicLink() || (metadata.mode & 0o077) !== 0 || metadata.size > 1026) {
    throw new Error('Password file must be a regular non-symlink file, mode 0600 or stricter, at most 1026 bytes.')
  }
  const value = (await readFile(path, 'utf8')).trim()
  if (!value) throw new Error('Password file is empty.')
  return value
}

async function responseJson(url, init = {}) {
  const response = await fetch(url, { ...init, signal: AbortSignal.timeout(300_000) })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(`${new URL(url).pathname} returned HTTP ${response.status}`)
  return { response, body }
}

function boundedMilliseconds(value, fallback, minimum, maximum, name) {
  const raw = value === null ? String(fallback) : String(value)
  if (!/^\d+$/.test(raw)) throw new Error(`${name} must be an integer.`)
  const parsed = Number(raw)
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${name} must be between ${minimum} and ${maximum}.`)
  }
  return parsed
}

async function retryReadiness(operation, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  let lastError
  do {
    try {
      return await operation()
    } catch (error) {
      lastError = error
      if (Date.now() >= deadline) break
      await new Promise((resolvePromise) => setTimeout(resolvePromise, 15_000))
    }
  } while (Date.now() < deadline)
  throw lastError
}

const origin = argument('--origin', 'http://127.0.0.1:39083')
const username = argument('--username')
const passwordFile = argument('--password-file')
const output = argument('--output')
const readinessTimeoutMs = boundedMilliseconds(
  argument('--readiness-timeout-ms'), 1_200_000, 1_000, 3_600_000, '--readiness-timeout-ms',
)
if (!username || !passwordFile || !output) {
  throw new Error('Required: --username, --password-file, and --output')
}
const parsedOrigin = new URL(origin)
if (!['http:', 'https:'].includes(parsedOrigin.protocol) || parsedOrigin.pathname !== '/') {
  throw new Error('--origin must be one HTTP(S) origin without a path.')
}

const health = await fetch(`${origin}/healthz`, { signal: AbortSignal.timeout(10_000) })
if (!health.ok || (await health.text()).trim() !== 'ok') throw new Error('healthz did not return canonical ok.')
const password = await privateSecret(passwordFile)
const login = await responseJson(`${origin}/auth/login`, {
  method: 'POST',
  headers: { Origin: origin, 'Content-Type': 'application/json' },
  body: JSON.stringify({ username, password }),
})
const cookie = login.response.headers.get('set-cookie')?.split(';', 1)[0]
if (!cookie) throw new Error('Login did not return an opaque session cookie.')

const report = {
  contract: 'DATARIVER_PREP39083_SMOKE_V1',
  generated_at: new Date().toISOString(),
  origin,
  health: 'PASS',
  login: 'PASS',
  datahub: 'FAIL',
  managed_assets: 'FAIL',
  default_lineage: 'FAIL',
  metadata_master: 'FAIL',
  semantic_index: 'FAIL',
  llm_general: 'FAIL',
}
try {
  await retryReadiness(async () => {
    const catalog = await responseJson(`${origin}/poc-api/datahub/catalog?limit=1`, {
      headers: { Cookie: cookie },
    })
    if (!catalog.body || typeof catalog.body !== 'object') throw new Error('DataHub Catalog response is invalid.')
    report.datahub = 'PASS'

    const managed = await responseJson(`${origin}/poc-api/knowledge/managed-assets`, {
      headers: { Cookie: cookie },
    })
    const items = Array.isArray(managed.body?.items) ? managed.body.items : []
    const lineage = items.find((item) => item.graph_type === 'LINEAGE' && item.is_default)
    const metadata = items.find((item) => item.graph_type === 'METADATA_MASTER')
    if (!lineage || !metadata) throw new Error('Both canonical managed graph Assets are required.')
    if (!String(lineage.status).startsWith('READY') || !String(metadata.status).startsWith('READY')) {
      throw new Error('Managed graph Assets are not READY.')
    }
    if (lineage.refresh_mode !== 'DAILY' || metadata.refresh_mode !== 'DAILY') {
      throw new Error('Managed graph refresh mode is not DAILY.')
    }
    if (lineage.semantic_index_status !== 'READY' || metadata.semantic_index_status !== 'READY') {
      throw new Error('The shared semantic index is not READY.')
    }
    report.managed_assets = 'PASS'
    report.default_lineage = 'PASS'
    report.metadata_master = 'PASS'
    report.semantic_index = 'PASS'
  }, readinessTimeoutMs)

  const chat = await responseJson(`${origin}/poc-api/llm/chat`, {
    method: 'POST',
    headers: { Cookie: cookie, Origin: origin, 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: '데이터 계보가 무엇인지 일반적으로 설명해줘.', mode: 'AUTO' }),
  })
  if (chat.body?.route?.selected_mode !== 'GENERAL' || (chat.body?.evidence || []).length !== 0) {
    throw new Error('Representative GENERAL route did not skip internal retrieval.')
  }
  report.llm_general = 'PASS'
} finally {
  await fetch(`${origin}/auth/logout`, {
    method: 'POST',
    headers: { Cookie: cookie, Origin: origin, 'Content-Type': 'application/json' },
    body: '{}',
  }).catch(() => undefined)
}

await writeFile(output, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600, flag: 'wx' })
process.stdout.write(`${JSON.stringify(report)}\n`)
