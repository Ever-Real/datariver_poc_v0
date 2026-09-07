import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import test from 'node:test'
import { runInNewContext } from 'node:vm'

const source = readFileSync(new URL('./prep39083-general-classifier-rca-probe', import.meta.url), 'utf8')
const helpers = source.slice(source.indexOf('const ROUTE_FIELDS ='), source.indexOf('function parsedRawValue('))
const { longOutputEvidence, modelEvidence } = runInNewContext(
  `${helpers}\n({ longOutputEvidence, modelEvidence })`,
  { Buffer, createHash, boundedCount: (value) => String(value) },
)

const productSource = readFileSync(new URL('../frontend/poc-server.mjs', import.meta.url), 'utf8')
const bodyStart = productSource.indexOf("const classification = await llmRequest(llm.chat, '/chat/completions', ")
  + "const classification = await llmRequest(llm.chat, '/chat/completions', ".length
const bodyEnd = productSource.indexOf(', llmProviderTimeoutMs, signal, routePerformance)', bodyStart)
const intents = productSource.match(/const chatRouteIntents = new Set\(\[([\s\S]*?)\]\)/u)[1]
const question = '데이터 계보가 무엇인지 일반적으로 설명해줘.'
const actualBody = runInNewContext(`(${productSource.slice(bodyStart, bodyEnd)})`, {
  llm: { chat: { model: 'gemma4:test' } }, question, graphAssets: [],
  routingClassifierCompletionTokenBudget: 4096,
  chatRouteIntents: runInNewContext(`new Set([${intents}])`),
})
const abHelpers = source.slice(source.indexOf('function abRequests('), source.indexOf('async function main()'))
const { abRequests, abSchemaValid, abClassification } = runInNewContext(
  `${abHelpers}\n({ abRequests, abSchemaValid, abClassification })`,
  { structuredClone, QUESTION: question, probeFailure: (stage) => new Error(stage) },
)
const validRoute = {
  mode: 'GENERAL', confidence: 1, intent: 'GENERAL_CONVERSATION', primary_concepts: [],
  secondary_concepts: [], relation_intent: null, entity_type_hints: [], selected_graph_asset: null,
}

test('A changes only schema/messages and B preserves the actual Product request byte for byte', () => {
  const original = JSON.stringify(actualBody)
  const [a, b] = abRequests(actualBody)
  assert.equal(JSON.stringify(actualBody), original)
  assert.equal(JSON.stringify(b), original)
  for (const key of Object.keys(actualBody).filter((key) => !['response_format', 'messages'].includes(key))) {
    assert.equal(JSON.stringify(a[key]), JSON.stringify(b[key]))
  }
  assert.deepEqual(Object.keys(a.response_format.json_schema.schema.properties), ['mode'])
  assert.equal(a.response_format.json_schema.strict, true)
  assert.equal(a.messages[1].content, question)
  assert.throws(() => abRequests({ ...actualBody, max_tokens: 8192 }), /AB_REQUEST_CONTRACT/u)
  assert.throws(() => abRequests({ ...actualBody, reasoning_effort: 'low' }), /AB_REQUEST_CONTRACT/u)
})

test('diagnostic schema checks reject surplus keys and out-of-bound classifier fields', () => {
  const schema = actualBody.response_format.json_schema.schema
  assert.equal(abSchemaValid(validRoute, schema), true)
  for (const change of [
    { extra: 'field' }, { confidence: 2 }, { selected_graph_asset: 'x'.repeat(101) },
    { primary_concepts: Array(9).fill('x') }, { secondary_concepts: [''] },
    { entity_type_hints: ['unknown'] }, { mode: 'AUTO' },
  ]) assert.equal(abSchemaValid({ ...validRoute, ...change }, schema), false)
})

test('A/B classifies only observed completion outcomes and leaves transport failure inconclusive', () => {
  const result = (a, b) => abClassification({ state: a }, { state: b })
  assert.equal(result('FAIL', 'FAIL'), 'PROVIDER_MODEL_STRUCTURED_OUTPUT_UNSUPPORTED_OR_BROKEN')
  assert.equal(result('PASS', 'FAIL'), 'CLASSIFIER_SCHEMA_OR_PROMPT_INTERACTION')
  assert.equal(result('PASS', 'PASS'), 'SMOKE_CONTEXT_DIFFERENCE')
  assert.equal(result('FAIL', 'PASS'), 'INCONCLUSIVE_A_FAIL_B_PASS')
  assert.equal(result('UNAVAILABLE', 'FAIL'), 'INCONCLUSIVE_PROVIDER_FAILURE')
})

test('A/B sends exactly two completions and two bounded metadata GETs without retries', async () => {
  const sent = []
  const metadataPaths = []
  const output = []
  const context = {
    Buffer, URL, AbortSignal, structuredClone, createHash, QUESTION: question,
    OUTPUT_PREFIX: 'GENERAL_RCA_EVIDENCE', SAFE_PROVIDER_CODES: new Set(['POC_LLM_PROVIDER_TIMEOUT']),
    process: { stdout: { write: (value) => output.push(value) } },
    probeFailure: (stage) => new Error(stage), boundedCount: String,
    boundedToken: (value, fallback) => typeof value === 'string' ? value.toUpperCase() : fallback,
    requestShape: () => 'fixture', classifierUsage: () => 'fixture',
    parsedRawValue: (raw) => { try { return { state: 'PARSED', value: JSON.parse(raw) } } catch { return { state: 'INVALID_JSON' } } },
  }
  context.serverModule = {
    chatRoute: async () => {
      Object.assign(context.__DATARIVER_GENERAL_CLASSIFIER_RCA, {
        body: structuredClone(actualBody), providerCalls: 1, requests: [{}],
        provider: { url: 'http://provider.test/v1', token: 'secret-fixture' },
        endpoint: '/chat/completions', timeoutMs: 120_000,
      })
      throw new Error('Capture only')
    },
    graphPlannerAssets: async () => [],
    parseChatRouteDecision: JSON.parse,
    providerTransport: {
      fetch: async (url, options) => {
        metadataPaths.push(url.pathname)
        assert.equal(options.redirect, 'error')
        return new Response(JSON.stringify(url.pathname === '/api/version'
          ? { version: '0.12.6' }
          : { models: [{ name: actualBody.model, digest: 'a'.repeat(64) }] }))
      },
    },
    llmRequest: async (_provider, _endpoint, body) => {
      sent.push(body)
      if (sent.length === 2) throw Object.assign(new Error('secret error detail'), { code: 'POC_LLM_PROVIDER_TIMEOUT' })
      return { choices: [{ finish_reason: 'stop', message: { content: '{"mode":"GENERAL"}' } }] }
    },
  }
  await runInNewContext(`${helpers}\n${abHelpers}\nrunClassifierAB()`, context)
  assert.equal(sent.length, 2)
  assert.equal(JSON.stringify(sent[1]), JSON.stringify(actualBody))
  assert.deepEqual(metadataPaths, ['/api/version', '/api/tags'])
  assert.equal(output.length, 1)
  assert.match(output[0], /ab=INCONCLUSIVE_PROVIDER_FAILURE/u)
  assert.match(output[0], /"software":"OLLAMA_API"/u)
  assert.equal(output[0].includes('secret'), false)
})

test('temporary source capture runs before provider transport and preserves valid module syntax', async () => {
  const constants = source.slice(source.indexOf("const OUTPUT_PREFIX = 'GENERAL_RCA_EVIDENCE'"), source.indexOf('const { Pool } = pg'))
  const preparation = source.slice(source.indexOf('async function prepareTemporaryServer('), source.indexOf('function boundedToken('))
    .replace('return import(`file://${join(temporaryDirectory, SERVER_FILE)}?rca=${Date.now()}`)', 'return instrumented')
  const instrumented = await runInNewContext(`let temporaryDirectory;\n${constants}\n${preparation}\nprepareTemporaryServer(productSource)`, {
    productSource, process: { env: { DATARIVER_CLASSIFIER_PROBE_MODE: 'AB' } },
    countOccurrences: (value, needle) => value.split(needle).length - 1,
    mkdtemp: async () => '/tmp/fixture', tmpdir: () => '/tmp', join: (...parts) => parts.join('/'),
    readdir: async () => [], writeFile: async () => {}, probeFailure: (stage) => new Error(stage),
  })
  const check = spawnSync(process.execPath, ['--input-type=module', '--check'], { input: instrumented, encoding: 'utf8' })
  assert.equal(check.status, 0, check.stderr)
  const requestFunction = instrumented.slice(instrumented.indexOf('async function llmRequest('), instrumented.indexOf('function boundedLlmStageError('))
  let networkCalls = 0
  const capture = { captureRequest: true, captureOnly: true, requests: [] }
  const context = {
    __DATARIVER_GENERAL_CLASSIFIER_RCA: capture, structuredClone, performance,
    providerFetch: async () => { networkCalls += 1 }, body: actualBody,
    llmProviderTimeoutMs: 120_000,
  }
  await assert.rejects(runInNewContext(`${requestFunction}\nllmRequest({ model: 'gemma4:test' }, '/chat/completions', body)`, context), /capture only/u)
  assert.equal(networkCalls, 0)
  assert.equal(capture.requests.length, 1)
  assert.equal(JSON.stringify(capture.body), JSON.stringify(actualBody))
})

test('metadata reads stop at the byte bound and redact a model identifier containing a credential', async () => {
  const deadlines = []
  let calls = 0
  const result = await runInNewContext(`${abHelpers}\nreadProviderMetadata(provider, model)`, {
    Buffer, URL, createHash,
    AbortSignal: { timeout: (value) => { deadlines.push(value); return AbortSignal.timeout(value) } },
    provider: { url: 'http://provider.test/v1', token: 'secret-token' }, model: 'gemma4:secret-token',
    probeFailure: (stage) => new Error(stage),
    serverModule: { providerTransport: { fetch: async () => {
      calls += 1
      return new Response(calls === 1 ? '{"version":"0.12.6"}' : ' '.repeat(131_073))
    } } },
  })
  assert.equal(calls, 2)
  assert.deepEqual(deadlines, [10_000, 10_000])
  assert.equal(result.model, 'REDACTED')
  assert.equal(result.software, 'UNKNOWN')
  assert.equal(result.model_artifact_digest, 'UNKNOWN')
  assert.equal(JSON.stringify(result).includes('secret-token'), false)
})

test('bounds and redacts excerpts and never exposes raw SyntaxError text', () => {
  const value = '```json\n{"mode":"GENERAL","primary_concepts":["person@example.test sk-secret-fixture-value 010-1234-5678 홍길동|'
    + 'private'.repeat(80)
  const evidence = longOutputEvidence(value)
  const output = JSON.stringify(evidence)
  for (const secret of ['person', 'example.test', 'sk-secret', '010-1234', '홍길동', 'private', '|']) {
    assert.equal(output.includes(secret), false)
  }
  assert.ok([...evidence.prefix_redacted].length <= 160)
  assert.ok([...evidence.suffix_redacted].length <= 160)
  assert.equal(evidence.bytes, Buffer.byteLength(value))
  assert.equal(evidence.chars, [...value].length)
  assert.equal(evidence.code_fence, true)
  assert.equal(evidence.parse, 'UNEXPECTED_TOKEN')
})

test('distinguishes numeric, string, whitespace and repeated-object growth', () => {
  const number = longOutputEvidence('{"mode":"GENERAL","confidence":0.' + '9'.repeat(6000))
  assert.equal(number.last_field_candidate, 'confidence')
  assert.equal(number.longest_number_run, 6002)
  assert.equal(number.repeated_pattern, true)
  assert.equal(number.parse, 'EXPECTED_DELIMITER')
  const string = longOutputEvidence('{"primary_concepts":["' + 'abc'.repeat(500))
  assert.equal(string.last_field_candidate, 'primary_concepts')
  assert.ok(string.longest_string_token > 100)
  assert.equal(string.repeated_pattern, true)
  assert.equal(string.parse, 'UNTERMINATED_STRING')
  assert.match(string.parse_position, /^\d+$/u)
  assert.equal(longOutputEvidence('{"mode":' + ' '.repeat(500)).longest_whitespace_run, 500)
  const objects = longOutputEvidence('{"mode":"GENERAL"}\n'.repeat(10))
  assert.equal(objects.adjacent_objects, 9)
  assert.equal(objects.repeated_route_keys, 9)
  assert.equal(objects.parse, 'TRAILING_CONTENT')
})

test('classifies visible reasoning markers without printing natural language', () => {
  const evidence = longOutputEvidence('<think>We need to identify the route.</think>')
  assert.equal(evidence.reasoning_marker, true)
  assert.equal(evidence.opening, 'OTHER')
  assert.equal(evidence.prefix_redacted.includes('identify'), false)
})

test('handles valid, missing and oversized content without treating diagnostics as routing', () => {
  assert.equal(longOutputEvidence('{"mode":"GENERAL"}').parse, 'VALID')
  assert.equal(longOutputEvidence(undefined).state, 'NON_STRING')
  assert.equal(longOutputEvidence(' ').first, 'EMPTY')
  assert.equal(longOutputEvidence(' '.repeat(100_001)).analysis, 'TRUNCATED_100K')
  // Private deployment aliases are identified by a digest, never emitted verbatim.
  assert.equal(modelEvidence('private-deployment-alias').family, 'OTHER')
  assert.match(modelEvidence('qwen3:8b').sha256, /^[a-f0-9]{64}$/u)
  assert.equal(modelEvidence('qwen3:8b').family, 'QWEN')
})
