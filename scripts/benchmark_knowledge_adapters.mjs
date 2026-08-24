#!/usr/bin/env node

import { readFile, writeFile } from 'node:fs/promises'
import process from 'node:process'
import { performance } from 'node:perf_hooks'

function argument(name, fallback = null) {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : fallback
}

function percentile(values, fraction) {
  if (!values.length) return null
  const sorted = [...values].sort((left, right) => left - right)
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * fraction) - 1))]
}

function latency(values) {
  return {
    samples: values.length,
    p50_ms: percentile(values, 0.5),
    p95_ms: percentile(values, 0.95),
  }
}

const origin = argument('--origin', 'http://127.0.0.1:39083')
const username = argument('--username')
const passwordFile = argument('--password-file')
const mcpTokenFile = argument('--mcp-token-file')
const output = argument('--output')
const iterations = Number(argument('--iterations', '20'))
if (!username || !passwordFile || !mcpTokenFile || !output
  || !Number.isSafeInteger(iterations) || iterations < 5 || iterations > 100) {
  throw new Error('Required: --username, --password-file, --mcp-token-file, --output, and 5-100 --iterations')
}

const password = (await readFile(passwordFile, 'utf8')).trim()
const mcpToken = (await readFile(mcpTokenFile, 'utf8')).trim()
const login = await fetch(`${origin}/auth/login`, {
  method: 'POST',
  headers: { Origin: origin, 'Content-Type': 'application/json' },
  body: JSON.stringify({ username, password }),
})
if (!login.ok) throw new Error(`Benchmark login failed with HTTP ${login.status}`)
const cookie = login.headers.get('set-cookie')?.split(';', 1)[0]
if (!cookie) throw new Error('Benchmark login did not return an opaque session cookie')

let rpcId = 0
const nativeCall = async () => {
  const started = performance.now()
  const response = await fetch(`${origin}/poc-api/knowledge/managed-assets`, {
    headers: { Cookie: cookie },
    signal: AbortSignal.timeout(30_000),
  })
  const body = await response.json()
  return {
    elapsed: Math.max(0, Math.round(performance.now() - started)),
    status: response.status,
    ids: (body.items || []).map((item) => item.id).sort(),
  }
}

const mcpCall = async (token = mcpToken) => {
  const started = performance.now()
  const response = await fetch(`${origin}/api/v1/mcp`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0',
      method: 'tools/call',
      params: { name: 'knowledge_graph_assets', arguments: {} },
      id: ++rpcId,
    }),
    signal: AbortSignal.timeout(30_000),
  })
  const body = await response.json()
  return {
    elapsed: Math.max(0, Math.round(performance.now() - started)),
    status: response.status,
    ids: (body.result?.structuredContent?.items || []).map((item) => item.id).sort(),
  }
}

const nativeSamples = []
const mcpSamples = []
const nativeErrors = []
const mcpErrors = []
let nativeIds = []
let mcpIds = []
try {
  await nativeCall()
  await mcpCall()
  for (let index = 0; index < iterations; index += 1) {
    const first = index % 2 ? mcpCall : nativeCall
    const second = index % 2 ? nativeCall : mcpCall
    for (const [kind, call] of [[index % 2 ? 'MCP' : 'NATIVE', first], [index % 2 ? 'NATIVE' : 'MCP', second]]) {
      try {
        const result = await call()
        if (result.status !== 200) throw new Error(`HTTP ${result.status}`)
        if (kind === 'NATIVE') {
          nativeSamples.push(result.elapsed)
          nativeIds = result.ids
        } else {
          mcpSamples.push(result.elapsed)
          mcpIds = result.ids
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        if (kind === 'NATIVE') nativeErrors.push(message)
        else mcpErrors.push(message)
      }
    }
  }
} finally {
  await fetch(`${origin}/auth/logout`, {
    method: 'POST',
    headers: { Cookie: cookie, Origin: origin, 'Content-Type': 'application/json' },
    body: '{}',
  }).catch(() => undefined)
}

const unauthorized = await mcpCall('invalid-benchmark-token')
const sameStructuredAssets = JSON.stringify(nativeIds) === JSON.stringify(mcpIds) && nativeIds.length > 0
const report = {
  schema_version: 1,
  generated_at: new Date().toISOString(),
  comparison: 'Native managed Asset read model vs MCP adapter over the same Core Knowledge Service',
  native: { ...latency(nativeSamples), error_rate: nativeErrors.length / iterations },
  mcp: { ...latency(mcpSamples), error_rate: mcpErrors.length / iterations },
  structured_result_consistency: sameStructuredAssets,
  authorized_asset_count: mcpIds.length,
  invalid_token_http_status: unauthorized.status,
  auth_propagation_pass: unauthorized.status === 401 && mcpIds.length > 0,
  final_architecture_decision: 'INTERNAL_NATIVE_EXTERNAL_MCP_SHARED_CORE',
  decision_reason: 'Internal Chat keeps the direct in-process adapter; external agents use the authenticated MCP protocol adapter. Both resolve the same Core Knowledge Service and authorization-filtered registry.',
}
await writeFile(output, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 })
process.stdout.write(`${JSON.stringify(report)}\n`)
if (nativeErrors.length || mcpErrors.length || !sameStructuredAssets || !report.auth_propagation_pass) process.exitCode = 1
