#!/usr/bin/env node

import { chmod, lstat, readFile, rename, unlink, writeFile } from 'node:fs/promises'
import process from 'node:process'

import { prepGeneralSmokeClassification } from '../frontend/poc-llm-timeout.mjs'

const processStarted = Date.now()
const inventoryFailureClassifications = new Set([
  'PREP_DATAHUB_INVENTORY_QUERY_FAILED',
  'PREP_DATAHUB_INVENTORY_PAGE_FAILED',
  'PREP_DATAHUB_INVENTORY_GRAPHQL_FAILED',
  'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
  'PREP_DATAHUB_INVENTORY_NORMALIZATION_FAILED',
  'PREP_DATAHUB_INVENTORY_PROMOTION_FAILED',
])

function argument(name, fallback = null) {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : fallback
}

function smokeFailure(stage, classification, message, status = null, diagnostic = null) {
  return Object.assign(new Error(message), {
    stage,
    classification,
    status,
    diagnostic,
    terminal: diagnostic?.terminal === true,
  })
}

function adminLoginClassification(body, status) {
  if (body?.code === 'ORIGIN_FORBIDDEN' && status === 403) {
    return 'PREP_SMOKE_ADMIN_ORIGIN_FAILED'
  }
  if (body?.code === 'AUTHENTICATION_FAILED' && status === 401) {
    return 'PREP_SMOKE_ADMIN_AUTH_FAILED'
  }
  return 'PREP_SMOKE_ADMIN_LOGIN_FAILED'
}

async function privateSecret(path) {
  const metadata = await lstat(path)
  if (!metadata.isFile() || metadata.isSymbolicLink() || (metadata.mode & 0o077) !== 0 || metadata.size > 1026) {
    throw smokeFailure(
      'INPUT',
      'PREP_SMOKE_INPUT_INVALID',
      'Password file must be a regular non-symlink file, mode 0600 or stricter, at most 1026 bytes.',
    )
  }
  const value = (await readFile(path, 'utf8')).trim()
  if (!value) throw smokeFailure('INPUT', 'PREP_SMOKE_INPUT_INVALID', 'Password file is empty.')
  return value
}

async function responseJson(url, init, stage, classification) {
  let response
  try {
    response = await fetch(url, { ...init, signal: AbortSignal.timeout(300_000) })
  } catch (error) {
    const requestClassification = stage === 'GENERAL_PROVIDER' && error?.name === 'TimeoutError'
      ? 'PREP_SMOKE_GENERAL_PROVIDER_TIMEOUT_FAILED'
      : classification
    throw smokeFailure(stage, requestClassification, `${stage} request failed.`)
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const inventoryClassification = stage === 'DATAHUB'
      && typeof body?.code === 'string'
      && inventoryFailureClassifications.has(body.code)
      ? body.code
      : classification
    const generalClassification = stage === 'GENERAL_PROVIDER'
      ? prepGeneralSmokeClassification(body?.code)
      : undefined
    const adminClassification = stage === 'ADMIN_LOGIN'
      ? adminLoginClassification(body, response.status)
      : undefined
    const failureClassification = adminClassification || generalClassification || inventoryClassification
    throw smokeFailure(
      stage,
      failureClassification,
      `${stage} request was rejected.`,
      response.status,
      failureClassification === body?.code ? body?.diagnostic : null,
    )
  }
  return { response, body }
}

function boundedMilliseconds(value, fallback, minimum, maximum, name) {
  const raw = value === null ? String(fallback) : String(value)
  if (!/^\d+$/.test(raw)) throw smokeFailure('INPUT', 'PREP_SMOKE_INPUT_INVALID', `${name} must be an integer.`)
  const parsed = Number(raw)
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw smokeFailure('INPUT', 'PREP_SMOKE_INPUT_INVALID', `${name} must be between ${minimum} and ${maximum}.`)
  }
  return parsed
}

function progress(step, message) {
  process.stdout.write(`[SMOKE ${step}] ${message}\n`)
}

async function retryReadiness(operation, timeoutMs, label) {
  const started = Date.now()
  const deadline = started + timeoutMs
  let lastError
  do {
    try {
      return await operation()
    } catch (error) {
      lastError = error
      if (error?.terminal) throw error
      if (Date.now() >= deadline) break
      const diagnostic = error?.diagnostic
      if (diagnostic && Number.isSafeInteger(diagnostic.page_number) && diagnostic.page_number > 0) {
        const pageProgress = `inventory page ${diagnostic.page_number}`
        const countProgress = Number.isSafeInteger(diagnostic.expected_total)
          ? `; ${diagnostic.processed_count}/${diagnostic.expected_total} processed`
          : ''
        progress(label, `${pageProgress}${countProgress}`)
      } else {
        progress(label, `still pending (elapsed ${Math.round((Date.now() - started) / 1000)}s)`)
      }
      const remaining = deadline - Date.now()
      if (remaining > 0) {
        await new Promise((resolvePromise) => setTimeout(resolvePromise, Math.min(15_000, remaining)))
      }
    }
  } while (Date.now() < deadline)
  throw lastError
}

async function withHeartbeat(promise, label, intervalMs = 30_000) {
  const started = Date.now()
  const timer = setInterval(() => {
    progress(label, `still pending (elapsed ${Math.round((Date.now() - started) / 1000)}s)`)
  }, intervalMs)
  timer.unref()
  try {
    return await promise
  } finally {
    clearInterval(timer)
  }
}

async function atomicJson(path, value) {
  const temporary = `${path}.tmp-${process.pid}`
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600, flag: 'wx' })
    await rename(temporary, path)
    await chmod(path, 0o600)
  } finally {
    await removeIfPresent(temporary)
  }
}

async function removeIfPresent(path) {
  if (!path) return
  await unlink(path).catch((error) => {
    if (error?.code !== 'ENOENT') throw error
  })
}

const transportOrigin = argument('--origin', 'http://127.0.0.1:39083')
const requestOrigin = argument('--request-origin')
const username = argument('--username')
const passwordFile = argument('--password-file')
const output = argument('--output')
const failureOutput = argument('--failure-output')
const k9Mode = String(argument('--k9-mode', 'required')).trim().toUpperCase()
const readinessTimeoutMs = boundedMilliseconds(
  argument('--readiness-timeout-ms'), 1_200_000, 1_000, 3_600_000, '--readiness-timeout-ms',
)

async function main() {
  const started = processStarted
  if (!requestOrigin || !username || !passwordFile || !output) {
    throw smokeFailure(
      'INPUT',
      'PREP_SMOKE_INPUT_INVALID',
      'Required: --request-origin, --username, --password-file, and --output',
    )
  }
  if (!['REQUIRED', 'DEFERRED'].includes(k9Mode)) {
    throw smokeFailure('INPUT', 'PREP_SMOKE_INPUT_INVALID', '--k9-mode must be required or deferred.')
  }
  for (const [name, value] of [['--origin', transportOrigin], ['--request-origin', requestOrigin]]) {
    let parsed
    try {
      parsed = new URL(value)
    } catch {
      throw smokeFailure('INPUT', 'PREP_SMOKE_INPUT_INVALID', `${name} must be one exact HTTP(S) origin.`)
    }
    if (!['http:', 'https:'].includes(parsed.protocol)
      || parsed.username || parsed.password || parsed.pathname !== '/'
      || parsed.search || parsed.hash || parsed.origin !== value) {
      throw smokeFailure('INPUT', 'PREP_SMOKE_INPUT_INVALID', `${name} must be one exact HTTP(S) origin.`)
    }
  }

  let health
  try {
    health = await fetch(`${transportOrigin}/healthz`, { signal: AbortSignal.timeout(10_000) })
  } catch {
    throw smokeFailure('HEALTH', 'PREP_SMOKE_WEB_HEALTH_FAILED', 'Host web health request failed.')
  }
  if (!health.ok || (await health.text()).trim() !== 'ok') {
    throw smokeFailure('HEALTH', 'PREP_SMOKE_WEB_HEALTH_FAILED', 'Host web health is not canonical ok.', health.status)
  }
  progress('1/6', 'Host and Product health PASS')

  const password = await privateSecret(passwordFile)
  const login = await responseJson(`${transportOrigin}/auth/login`, {
    method: 'POST',
    headers: { Origin: requestOrigin, 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  }, 'ADMIN_LOGIN', 'PREP_SMOKE_ADMIN_AUTH_FAILED')
  const cookie = login.response.headers.get('set-cookie')?.split(';', 1)[0]
  if (!cookie) {
    throw smokeFailure(
      'ADMIN_LOGIN',
      'PREP_SMOKE_ADMIN_LOGIN_CONTRACT_FAILED',
      'Login returned no opaque session.',
    )
  }
  progress('2/6', 'Administrator login PASS')

  const report = {
    contract: 'DATARIVER_PREP39083_SMOKE_V1',
    generated_at: new Date().toISOString(),
    origin: transportOrigin,
    request_origin: requestOrigin,
    health: 'PASS',
    login: 'PASS',
    k9_mode: k9Mode,
    datahub: 'FAIL',
    managed_assets: k9Mode === 'REQUIRED' ? 'FAIL' : 'DEFERRED',
    default_lineage: k9Mode === 'REQUIRED' ? 'FAIL' : 'DEFERRED',
    metadata_master: k9Mode === 'REQUIRED' ? 'FAIL' : 'DEFERRED',
    semantic_index: k9Mode === 'REQUIRED' ? 'FAIL' : 'DEFERRED',
    mcl_change_history: 'FAIL',
    llm_general: 'FAIL',
  }
  try {
    await retryReadiness(async () => {
      const currentInventory = await withHeartbeat(responseJson(
        `${transportOrigin}/poc-api/datahub/tree?parent_kind=ROOT&refresh=true&limit=1`,
        { headers: { Cookie: cookie } },
        'DATAHUB',
        'PREP_SMOKE_DATAHUB_CONNECTIVITY_FAILED',
      ), '3/6 DataHub current inventory')
      if (!currentInventory.body || typeof currentInventory.body !== 'object') {
        throw smokeFailure('DATAHUB', 'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED', 'Current DataHub inventory response is invalid.', null, {
          phase: 'RESPONSE_BUILD', terminal: true,
        })
      }
      const catalog = await responseJson(`${transportOrigin}/poc-api/datahub/catalog?limit=1`, {
        headers: { Cookie: cookie },
      }, 'DATAHUB', 'PREP_SMOKE_DATAHUB_CONNECTIVITY_FAILED')
      if (!catalog.body || typeof catalog.body !== 'object') {
        throw smokeFailure('DATAHUB', 'PREP_SMOKE_DATAHUB_CONNECTIVITY_FAILED', 'DataHub Catalog response is invalid.')
      }
      report.datahub = 'PASS'
    }, readinessTimeoutMs, '3/6 DataHub')
    progress('3/6', 'DataHub bounded read PASS')

    if (k9Mode === 'REQUIRED') {
      await retryReadiness(async () => {
        const managed = await responseJson(`${transportOrigin}/poc-api/knowledge/managed-assets`, {
          headers: { Cookie: cookie },
        }, 'K9', 'PREP_SMOKE_K9_NOT_READY')
        const items = Array.isArray(managed.body?.items) ? managed.body.items : []
        const lineage = items.find((item) => item.graph_type === 'LINEAGE' && item.is_default)
        const metadata = items.find((item) => item.graph_type === 'METADATA_MASTER')
        const refreshFailure = [lineage, metadata]
          .map((item) => item?.last_error_code)
          .find((code) => typeof code === 'string' && code.startsWith('K9_'))
        const refreshClassifications = {
          K9_DATAHUB_SOURCE_FAILED: 'PREP_SMOKE_K9_DATAHUB_SOURCE_FAILED',
          K9_POLICY_PIN_DRIFT_FAILED: 'PREP_SMOKE_K9_POLICY_PIN_DRIFT_FAILED',
          K9_NEO4J_PROJECTION_FAILED: 'PREP_SMOKE_K9_NEO4J_PROJECTION_FAILED',
          K9_PROMOTION_FAILED: 'PREP_SMOKE_K9_PROMOTION_FAILED',
          K9_SEMANTIC_INDEX_FAILED: 'PREP_SMOKE_SEMANTIC_INDEX_NOT_READY',
        }
        if (refreshFailure) {
          throw smokeFailure(
            'K9_INITIAL_REFRESH',
            refreshClassifications[refreshFailure] || 'PREP_SMOKE_K9_REFRESH_FAILED',
            'The initial managed-graph refresh failed at a classified stage.',
            null,
            { terminal: true, product_error_code: refreshFailure },
          )
        }
        if (!lineage || !metadata || !String(lineage.status).startsWith('READY')
          || !String(metadata.status).startsWith('READY')
          || lineage.refresh_mode !== 'DAILY' || metadata.refresh_mode !== 'DAILY') {
          throw smokeFailure('K9', 'PREP_SMOKE_K9_NOT_READY', 'Canonical managed graphs are not DAILY and READY.')
        }
        if (lineage.semantic_index_status !== 'READY' || metadata.semantic_index_status !== 'READY') {
          throw smokeFailure('K9', 'PREP_SMOKE_SEMANTIC_INDEX_NOT_READY', 'The shared semantic index is not READY.')
        }
        report.managed_assets = 'PASS'
        report.default_lineage = 'PASS'
        report.metadata_master = 'PASS'
        report.semantic_index = 'PASS'
      }, readinessTimeoutMs, '4/6 K9')
      progress('4/6', 'Managed graphs and semantic index PASS')
    } else {
      progress('4/6', 'K9 DEFERRED')
    }

    const week = new Date()
    const day = (week.getUTCDay() + 6) % 7
    week.setUTCDate(week.getUTCDate() - day)
    const weekStart = week.toISOString().slice(0, 10)
    await retryReadiness(async () => {
      const changeHistory = await responseJson(
        `${transportOrigin}/api/v1/change-history/summary?week_start=${weekStart}`,
        { headers: { Cookie: cookie } },
        'MCL_CHANGE_HISTORY',
        'PREP_SMOKE_MCL_SOURCE_FAILED',
      )
      if (changeHistory.body?.capture_state === 'DISCOVERY_FAILED') {
        throw smokeFailure(
          'MCL_INITIAL_CAPTURE',
          'PREP_SMOKE_MCL_RUNTIME_DISCOVERY_FAILED',
          'MCL runtime discovery failed after read-only provider preflight.',
          null,
          { terminal: true },
        )
      }
      if (changeHistory.body?.capture_state === 'CAPTURE_FAILED') {
        const historyGap = changeHistory.body?.capture_failure_classification
          === 'PREP_MCL_CAPTURE_HISTORY_GAP_BLOCKED'
        throw smokeFailure(
          'MCL_INITIAL_CAPTURE',
          historyGap
            ? 'PREP_SMOKE_MCL_HISTORY_GAP_BLOCKED'
            : 'PREP_SMOKE_MCL_RUNTIME_CAPTURE_FAILED',
          'MCL runtime capture failed after read-only provider preflight.',
          null,
          { terminal: true },
        )
      }
      if (![
        'CAPTURE_PENDING',
        'CONTIGUOUS_CAPTURE_RECORDED',
        'CAPTURE_CATCHING_UP',
        'CAPTURE_CAUGHT_UP',
      ].includes(changeHistory.body?.capture_state)) {
        throw smokeFailure('MCL_CHANGE_HISTORY', 'PREP_SMOKE_MCL_SOURCE_FAILED', 'MCL source/checkpoint contract is not ready.')
      }
      report.mcl_change_history = 'PASS'
    }, readinessTimeoutMs, '5/6 MCL')
    progress('5/6', 'MCL source and durable checkpoint contract PASS')

    const chat = await withHeartbeat(responseJson(`${transportOrigin}/poc-api/llm/chat`, {
      method: 'POST',
      headers: { Cookie: cookie, Origin: requestOrigin, 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: '데이터 계보가 무엇인지 일반적으로 설명해줘.', mode: 'AUTO' }),
    }, 'GENERAL_PROVIDER', 'PREP_SMOKE_GENERAL_PROVIDER_FAILED'), '6/6 GENERAL provider')
    if (chat.body?.route?.selected_mode !== 'GENERAL' || (chat.body?.evidence || []).length !== 0) {
      throw smokeFailure('GENERAL_ROUTE', 'PREP_SMOKE_GENERAL_ROUTE_FAILED', 'Representative GENERAL route used internal retrieval or selected another route.')
    }
    report.llm_general = 'PASS'
    progress('6/6', 'GENERAL provider and route PASS')
  } finally {
    await fetch(`${transportOrigin}/auth/logout`, {
      method: 'POST',
      headers: { Cookie: cookie, Origin: requestOrigin, 'Content-Type': 'application/json' },
      body: '{}',
      signal: AbortSignal.timeout(10_000),
    }).catch(() => undefined)
  }

  await atomicJson(output, report)
  await removeIfPresent(failureOutput)
  process.stdout.write(`${JSON.stringify(report)}\n`)
  process.stdout.write(`[SMOKE PASS] completed in ${Math.round((Date.now() - started) / 1000)}s\n`)
}

main().catch(async (error) => {
  const failure = {
    contract: 'DATARIVER_PREP39083_SMOKE_FAILURE_V1',
    stage: error?.stage || 'UNKNOWN',
    classification: error?.classification || 'PREP_SMOKE_UNKNOWN_FAILED',
    status_class: Number.isInteger(error?.status) ? `${Math.floor(error.status / 100)}xx` : null,
    elapsed_ms: Date.now() - processStarted,
    k9_mode: k9Mode,
    failed_at: new Date().toISOString(),
    ...(error?.diagnostic ? { diagnostic: error.diagnostic } : {}),
  }
  if (failureOutput) await atomicJson(failureOutput, failure).catch(() => undefined)
  process.stderr.write(`${JSON.stringify(failure)}\n`)
  process.exitCode = 2
})
