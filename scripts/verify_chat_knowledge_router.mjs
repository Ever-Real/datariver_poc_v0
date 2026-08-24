#!/usr/bin/env node

import { readFile, writeFile } from 'node:fs/promises'
import process from 'node:process'
import { performance } from 'node:perf_hooks'

const TABLE_A = 'cost_ledger_lithography'
const TABLE_B = 'vw_cost_ledger_lithography'
const COLUMN_A = 'business_key'

const cases = [
  ['G01', 'GENERAL', '반도체 제조에서 포토리소그래피는 어떤 역할을 해?'],
  ['G02', 'GENERAL', 'wafer와 die의 차이를 설명해줘.'],
  ['G03', 'GENERAL', '반도체에서 CMP 공정이 뭐야?'],
  ['G04', 'GENERAL', 'fabless, foundry, IDM의 차이가 뭐야?'],
  ['G05', 'GENERAL', '반도체 수율이란 무엇이고 일반적으로 어떻게 계산해?'],
  ['G06', 'GENERAL', '2nm 공정이라는 표현은 정확히 무엇을 의미해?'],
  ['G07', 'GENERAL', '데이터 엔지니어링에서 lineage라는 말의 의미를 설명해줘.'],
  ['G08', 'GENERAL', '데이터 계보가 왜 필요한지 설명해줘.'],
  ['G09', 'GENERAL', '지식그래프와 벡터 검색의 차이는 뭐야?'],
  ['G10', 'GENERAL', 'RAG와 Knowledge Graph 기반 검색은 어떤 차이가 있어?'],
  ['G11', 'GENERAL', 'MCP가 무엇인지 간단히 설명해줘.'],
  ['G12', 'GENERAL', 'SQL JOIN과 UNION의 차이를 알려줘.'],
  ['G13', 'GENERAL', 'Python의 list와 tuple은 어떻게 달라?'],
  ['G14', 'GENERAL', 'semiconductor를 한국어로 번역하면 뭐야?'],
  ['G15', 'GENERAL', '웨이퍼를 영어로 뭐라고 해?'],
  ['G16', 'GENERAL', 'etching 공정에 대해 설명해줘.'],
  ['G17', 'GENERAL', '데이터베이스에서 primary key가 필요한 이유가 뭐야?'],
  ['G18', 'GENERAL', '테이블을 변경했을 때 다른 시스템에 영향이 갈 수 있다는 것이 일반적으로 무슨 의미야?'],
  ['G19', 'GENERAL', '계보 그래프라는 개념 자체를 설명해줘.'],
  ['G20', 'GENERAL', '벡터 임베딩이 의미적으로 비슷한 문장을 찾는 원리를 설명해줘.'],
  ['V01', 'VECTOR', '웨이퍼 관련 테이블을 찾아줘.'],
  ['V02', 'VECTOR', 'wafer와 의미가 비슷한 데이터를 담고 있는 테이블을 보여줘.'],
  ['V03', 'VECTOR', '반도체 관련 dataset을 검색해줘.'],
  ['V04', 'VECTOR', 'semiconductor와 관련된 설명이 있는 테이블을 찾아줘.'],
  ['V05', 'VECTOR', '수율과 관련된 테이블이나 컬럼을 찾아줘.'],
  ['V06', 'VECTOR', 'yield 데이터를 저장하는 것으로 보이는 컬럼을 찾아줘.'],
  ['V07', 'VECTOR', 'wafer id와 의미가 비슷한 컬럼을 찾아줘.'],
  ['V08', 'VECTOR', 'lot number를 저장하는 컬럼이 있는 테이블을 찾아줘.'],
  ['V09', 'VECTOR', 'etching과 관련된 metadata를 가진 테이블을 보여줘.'],
  ['V10', 'VECTOR', 'photolithography와 관련된 tag나 glossary term이 붙은 asset을 찾아줘.'],
  ['V11', 'VECTOR', 'CMP 공정과 관련된 데이터셋을 찾아줘.'],
  ['V12', 'VECTOR', 'defect map을 설명하는 테이블이나 컬럼을 찾아줘.'],
  ['V13', 'VECTOR', 'fab 또는 fabrication과 의미적으로 연관된 asset을 보여줘.'],
  ['V14', 'VECTOR', '공정 장비와 관련된 metadata가 있는 테이블을 찾아줘.'],
  ['V15', 'VECTOR', 'die 정보를 가지고 있는 데이터셋을 찾아줘.'],
  ['V16', 'VECTOR', `${TABLE_A}의 description, tag, term 정보를 알려줘.`],
  ['V17', 'VECTOR', `${COLUMN_A}라는 컬럼이 들어 있는 테이블들을 찾아줘.`],
  ['V18', 'VECTOR', 'Default Lineage Graph라는 Knowledge Asset의 metadata를 보여줘.'],
  ['V19', 'VECTOR', 'Knowledge Graph Asset 중 데이터 계보 용도로 등록된 Asset을 찾아줘.'],
  ['V20', 'VECTOR', 'wafer와 yield 두 개념에 모두 관련된 테이블을 찾아줘.'],
  ['R01', 'GRAPH', `${TABLE_A}를 변경하면 영향을 받는 downstream 테이블을 알려줘.`],
  ['R02', 'GRAPH', `${TABLE_B}의 upstream source 테이블을 찾아줘.`],
  ['R03', 'GRAPH', `${TABLE_A}에서 ${TABLE_B}까지 어떤 테이블을 거쳐 데이터가 전달돼?`],
  ['R04', 'GRAPH', `${TABLE_A}에 직접 의존하는 테이블은 무엇이야?`],
  ['R05', 'GRAPH', `${TABLE_B}가 어떤 원천 테이블에서 만들어졌는지 알려줘.`],
  ['R06', 'GRAPH', `${TABLE_A}를 삭제하면 영향을 받을 수 있는 테이블들을 찾아줘.`],
  ['R07', 'GRAPH', `${TABLE_A}의 schema를 변경하면 downstream 영향 범위를 보여줘.`],
  ['R08', 'GRAPH', `${TABLE_B}의 upstream을 2단계까지 보여줘.`],
  ['R09', 'GRAPH', `${TABLE_A}와 ${TABLE_B} 사이에 lineage 경로가 존재해?`],
  ['R10', 'GRAPH', `${TABLE_A}와 ${TABLE_B}가 공통으로 영향을 주는 downstream 테이블이 있어?`],
  ['R11', 'GRAPH', `${TABLE_A}와 ${TABLE_B}가 공유하는 upstream source가 있는지 찾아줘.`],
  ['R12', 'GRAPH', `${TABLE_A} 이후 가장 먼저 데이터를 받는 테이블들을 알려줘.`],
  ['R13', 'GRAPH', `${TABLE_A}.${COLUMN_A}를 변경하면 어떤 downstream table에 영향이 갈 수 있어?`],
  ['R14', 'GRAPH', `${TABLE_B}의 데이터가 어디에서 시작해서 여기까지 오는지 계보를 설명해줘.`],
  ['R15', 'GRAPH', `${TABLE_A}와 ${TABLE_B} 데이터를 함께 사용하는 downstream table이 있어?`],
  ['R16', 'GRAPH', '웨이퍼 정보를 가지고 있는 원천 테이블에서 최종 결과 테이블까지 데이터가 어떻게 흐르는지 찾아줘.'],
  ['R17', 'GRAPH', 'wafer id를 변경하면 어떤 데이터셋까지 영향이 갈 가능성이 있어?'],
  ['R18', 'GRAPH', 'lot history 데이터는 어디에서 들어와서 어디에서 사용되는지 찾아줘.'],
  ['R19', 'GRAPH', '수율 데이터를 만드는 데 사용되는 upstream 데이터셋들을 찾아줘.'],
  ['R20', 'GRAPH', 'defect 관련 데이터가 어떤 테이블들을 거쳐 최종 분석 데이터로 전달되는지 보여줘.'],
]

function argument(name, fallback = null) {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : fallback
}

function percentile(values, fraction) {
  if (!values.length) return null
  const sorted = [...values].sort((left, right) => left - right)
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * fraction) - 1))]
}

function metrics(results) {
  const labels = ['GENERAL', 'VECTOR', 'GRAPH']
  const matrix = Object.fromEntries(labels.map((expected) => [expected,
    Object.fromEntries(labels.map((actual) => [actual, results.filter((row) => (
      row.expected_route === expected && row.actual_route === actual
    )).length])),
  ]))
  const precision_recall = Object.fromEntries(labels.map((label) => {
    const truePositive = matrix[label][label]
    const predicted = results.filter((row) => row.actual_route === label).length
    const expected = results.filter((row) => row.expected_route === label).length
    return [label, {
      precision: predicted ? truePositive / predicted : 0,
      recall: expected ? truePositive / expected : 0,
    }]
  }))
  const totals = results.map((row) => row.total_latency_ms).filter(Number.isFinite)
  return {
    route_correct: results.filter((row) => row.route_pass).length,
    route_total: results.length,
    precision_recall,
    confusion_matrix: matrix,
    latency_ms: { p50: percentile(totals, 0.5), p95: percentile(totals, 0.95) },
  }
}

const origin = argument('--origin', 'http://127.0.0.1:39083')
const username = argument('--username')
const passwordFile = argument('--password-file')
const output = argument('--output')
const onlyIds = new Set((argument('--ids', '') || '').split(',').filter(Boolean))
if (!username || !passwordFile || !output) {
  throw new Error('Required: --username, --password-file, and --output')
}
const password = (await readFile(passwordFile, 'utf8')).trim()
const login = await fetch(`${origin}/auth/login`, {
  method: 'POST',
  headers: { Origin: origin, 'Content-Type': 'application/json' },
  body: JSON.stringify({ username, password }),
})
if (!login.ok) throw new Error(`Evaluation login failed with HTTP ${login.status}`)
const cookie = login.headers.get('set-cookie')?.split(';', 1)[0]
if (!cookie) throw new Error('Evaluation login did not return an opaque session cookie')

const selectedCases = onlyIds.size ? cases.filter(([id]) => onlyIds.has(id)) : cases
const results = []
try {
  for (const [testId, expectedRoute, question] of selectedCases) {
    const started = performance.now()
    let status = 0
    let body
    let failureReason = null
    try {
      const response = await fetch(`${origin}/poc-api/llm/chat`, {
        method: 'POST',
        headers: { Cookie: cookie, Origin: origin, 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, mode: 'AUTO' }),
        signal: AbortSignal.timeout(300_000),
      })
      status = response.status
      body = await response.json()
      if (!response.ok) failureReason = body.detail || body.title || `HTTP ${status}`
    } catch (error) {
      failureReason = error instanceof Error ? error.message : String(error)
    }
    const elapsed = Math.max(0, Math.round(performance.now() - started))
    const route = body?.route || {}
    const evidence = Array.isArray(body?.evidence) ? body.evidence : []
    const actualRoute = route.selected_mode || 'ERROR'
    const routePass = actualRoute === expectedRoute
    const retrievalRequired = expectedRoute !== 'GENERAL'
    const retrievalPass = retrievalRequired ? evidence.length > 0 : evidence.length === 0
    const answerGrounded = typeof body?.answer === 'string' && body.answer.trim().length > 0
      && (expectedRoute === 'GENERAL' ? evidence.length === 0 : evidence.length > 0)
    const row = {
      test_id: testId,
      question,
      expected_route: expectedRoute,
      actual_route: actualRoute,
      route_confidence: route.confidence ?? null,
      primary_concepts: route.primary_concepts || [],
      secondary_concepts: route.secondary_concepts || [],
      relation_intent: route.relation_intent ?? null,
      resolved_entity: evidence.map((item) => item.external_urn || item.id || item.name).filter(Boolean),
      selected_graph_asset: route.selected_graph_asset ?? null,
      retrieval_method: route.retrieval_method || null,
      runtime_result: status === 200 ? 'HTTP_200' : `HTTP_${status || 'ERROR'}`,
      routing_latency_ms: route.latency_ms?.routing ?? null,
      retrieval_latency_ms: route.latency_ms?.retrieval ?? null,
      total_latency_ms: route.latency_ms?.total ?? elapsed,
      route_pass: routePass,
      entity_resolution_pass: expectedRoute === 'GENERAL' ? true : evidence.length > 0,
      retrieval_pass: retrievalPass,
      answer_grounded_pass: answerGrounded,
      authorization_pass: status === 200,
      llm_call_count: route.llm_call_count ?? null,
      pass: routePass && status === 200,
      failure_reason: failureReason,
    }
    results.push(row)
    process.stderr.write(`${testId} ${actualRoute} ${row.pass ? 'PASS' : 'FAIL'} ${row.total_latency_ms}ms\n`)
  }
} finally {
  await fetch(`${origin}/auth/logout`, {
    method: 'POST',
    headers: { Cookie: cookie, Origin: origin, 'Content-Type': 'application/json' },
    body: '{}',
  }).catch(() => undefined)
}

const report = {
  schema_version: 1,
  generated_at: new Date().toISOString(),
  placeholders: { table_a: TABLE_A, table_b: TABLE_B, column_a: COLUMN_A },
  production_path: '/poc-api/llm/chat AUTO',
  cases: results,
  metrics: metrics(results),
}
await writeFile(output, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 })
process.stdout.write(`${JSON.stringify(report.metrics)}\n`)
if (report.metrics.route_correct !== report.metrics.route_total) process.exitCode = 1
