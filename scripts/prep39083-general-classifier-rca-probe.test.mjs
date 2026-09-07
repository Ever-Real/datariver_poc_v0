import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { chmodSync, existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
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
    DIAGNOSTIC_SHA: 'd'.repeat(40),
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
    productSource, process: { env: { DATARIVER_CLASSIFIER_PROBE_MODE: 'AB' }, argv: ['node', '-', 'AB', 'd'.repeat(40)] },
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

test('identity fence refuses missing mode, dirty script, stale HEAD and stale origin before Docker', () => {
  const root = mkdtempSync(join(tmpdir(), 'rca-identity-test-'))
  try {
    const checkout = join(root, 'diagnostic')
    const remote = join(root, 'remote.git')
    const bin = join(root, 'bin')
    mkdirSync(checkout)
    mkdirSync(bin)
    const dockerCalls = join(root, 'docker-calls')
    writeFileSync(join(bin, 'docker'), '#!/bin/sh\nprintf called >> "$RCA_TEST_DOCKER_CALLS"\nexit 1\n')
    chmodSync(join(bin, 'docker'), 0o700)
    const env = { ...process.env, PATH: `${bin}:${process.env.PATH}`, RCA_TEST_DOCKER_CALLS: dockerCalls }
    const git = (...args) => {
      const result = spawnSync('git', ['-c', 'user.name=RCA Test', '-c', 'user.email=rca@example.test', ...args], {
        cwd: checkout, encoding: 'utf8', env,
      })
      assert.equal(result.status, 0, result.stderr)
      return result.stdout.trim()
    }
    git('init', '--bare', remote)
    git('init', '-b', 'dev')
    mkdirSync(join(checkout, 'scripts'))
    const script = join(checkout, 'scripts', 'prep39083-general-classifier-rca-probe')
    writeFileSync(script, source)
    chmodSync(script, 0o700)
    git('add', 'scripts')
    git('commit', '-m', 'Diagnostic fixture')
    git('remote', 'add', 'origin', remote)
    git('push', '-u', 'origin', 'dev')
    const originalHead = git('rev-parse', 'HEAD')
    const run = (...args) => spawnSync('bash', [script, ...args], { encoding: 'utf8', env })
    assert.match(run().stdout, /stage=ARGUMENTS/u)
    assert.equal(existsSync(dockerCalls), false)
    writeFileSync(script, `${source}\n# uncommitted alteration\n`)
    assert.match(run('--ab').stdout, /status=STALE_DIAGNOSTIC.*stage=STALE_SCRIPT/u)
    assert.equal(existsSync(dockerCalls), false)
    writeFileSync(script, source)
    assert.match(run('--ab').stdout, /mode=AB\|stage=WEB_IDENTITY/u)
    assert.equal(readFileSync(dockerCalls, 'utf8'), 'called')
    rmSync(dockerCalls)
    git('commit', '--allow-empty', '-m', 'Unpublished fixture head')
    assert.match(run('--ab').stdout, /status=STALE_DIAGNOSTIC.*stage=STALE_CHECKOUT/u)
    assert.equal(existsSync(dockerCalls), false)
    git('push', 'origin', 'dev')
    git('update-ref', 'refs/remotes/origin/dev', originalHead)
    assert.match(run('--ab').stdout, /status=STALE_DIAGNOSTIC.*stage=STALE_CHECKOUT/u)
    assert.equal(existsSync(dockerCalls), false)

    const review = readFileSync(new URL('../docs/reviews/2026-09-07_PREP_CLASSIFIER_GRAPH_PARTIAL_RCA.md', import.meta.url), 'utf8')
    const launcher = review.split('<!-- PREP39083_RCA_AB_LAUNCHER -->\n```bash\n')[1].split('\n```')[0]
      .replace('/tmp/datariver-rca.XXXXXX', join(root, 'fresh-diagnostic.XXXXXX'))
    git('switch', '--detach', originalHead)
    writeFileSync(script, `${source}\n# caller checkout must stay unchanged\n`)
    const launch = () => spawnSync('bash', ['-c', launcher], { cwd: checkout, encoding: 'utf8', env })
    assert.match(launch().stdout, /mode=AB\|stage=WEB_IDENTITY/u)
    assert.equal(git('rev-parse', 'HEAD'), originalHead)
    assert.equal(readFileSync(script, 'utf8'), `${source}\n# caller checkout must stay unchanged\n`)
    assert.equal(readFileSync(dockerCalls, 'utf8'), 'called')
    rmSync(dockerCalls)

    // A pre-guard remote script is rejected by the launcher without executing that script.
    git('switch', 'dev')
    writeFileSync(script, '#!/bin/sh\ndocker stale-script-must-not-run\n')
    git('add', 'scripts')
    git('commit', '-m', 'Pre-guard diagnostic fixture')
    git('push', 'origin', 'HEAD:dev')
    assert.equal(launch().stdout, 'RCA|status=STALE_DIAGNOSTIC\n')
    assert.equal(existsSync(dockerCalls), false)
  } finally { rmSync(root, { recursive: true, force: true }) }
})

test('missing or mismatched Bash-to-Node mode fails before persistence or provider work', async () => {
  const main = source.slice(source.indexOf('async function main()'), source.indexOf('\ntry {\n  await main()'))
  for (const mode of [undefined, 'DEFAULT', 'AB']) {
    let reads = 0
    await assert.rejects(runInNewContext(`${main}\nmain()`, {
      PROBE_MODE: mode, DIAGNOSTIC_SHA: 'd'.repeat(40), process: { env: {} },
      probeFailure: (stage) => new Error(stage), readPersistedEvidence: async () => { reads += 1 },
    }), /MODE_IDENTITY_HANDSHAKE/u)
    assert.equal(reads, 0)
  }
  const probeProcess = { env: { DATARIVER_CLASSIFIER_PROBE_MODE: 'AB' } }
  let abRuns = 0
  await runInNewContext(`let serverModule;\n${main}\nmain()`, {
    PROBE_MODE: 'AB', DIAGNOSTIC_SHA: 'd'.repeat(40), process: probeProcess,
    readPersistedEvidence: async () => ({ managedGraphRows: [], activeGenerations: new Map() }),
    readFile: async () => '', SERVER_PATH: 'server', STATE_STORE_PATH: 'store',
    DISCOVERY_SQL_NULL_NEEDLE: 'sql-null', DISCOVERY_SQL_NEEDLE: 'sql', DISCOVERY_JSON_NULL_NEEDLE: 'json-null',
    prepareTemporaryServer: async () => {
      // Importing Product code cannot redirect AB into the old three-call path.
      probeProcess.env.DATARIVER_CLASSIFIER_PROBE_MODE = 'DEFAULT'
      return { createPocServer: () => {} }
    },
    runClassifierAB: async () => { abRuns += 1 },
    auditManagedGraphs: async () => assert.fail('AB must not enter graph/default-three-call path'),
  })
  assert.equal(abRuns, 1)
})

test('stdout is one compact A/B line; detailed evidence is private and default-mode output is rejected', () => {
  const root = mkdtempSync(join(tmpdir(), 'rca-summary-test-'))
  try {
    const detail = join(root, 'diagnostic.log')
    const head = 'd'.repeat(40)
    const summary = source.split("<<'SUMMARY'\n")[1].split('\nSUMMARY\n')[0]
    const fields = [
      'GENERAL_RCA_EVIDENCE', 'mode=AB', `diag=${head}`, 'completion_calls=2',
      'ab=CLASSIFIER_SCHEMA_OR_PROMPT_INTERACTION',
      'provider={"software":"OLLAMA_API","version":"0.12.6","model":"private-model-alias"}',
      'request_model={"family":"GEMMA"}',
      'A={"state":"PASS","finish":"STOP","output":{"prefix_redacted":"hidden-excerpt"}}',
      'B={"state":"FAIL","finish":"LENGTH","usage":"hidden-usage"}',
    ]
    const run = (line) => {
      writeFileSync(detail, `${line}\n`)
      return spawnSync('python3', ['-', detail, head, head, head, 'b'.repeat(40), 'b'.repeat(40), 'AB', root], {
        input: summary, encoding: 'utf8',
      })
    }
    const result = run(fields.join('|'))
    assert.equal(result.status, 0, result.stderr)
    assert.equal(result.stdout.trim().split('\n').length, 1)
    assert.match(result.stdout, /^RCA_AB\|diag=dddddddd\|mode=AB\|completion_calls=2\|A=PASS\|B=FAIL/u)
    assert.match(result.stdout, /model=GEMMA\|A_finish=STOP\|B_finish=LENGTH/u)
    assert.ok(result.stdout.length < 450)
    for (const hidden of ['private-model-alias', 'hidden-excerpt', 'hidden-usage', 'b'.repeat(40)]) {
      assert.equal(result.stdout.includes(hidden), false)
    }
    assert.equal(statSync(detail).mode & 0o777, 0o600)
    const saved = JSON.parse(readFileSync(detail, 'utf8'))
    assert.equal(saved.diag, head)
    assert.equal(saved.script_blob, 'b'.repeat(40))
    assert.match(saved.evidence, /hidden-excerpt/u)
    const wrongMode = run('GENERAL_RCA_EVIDENCE|run1=PASS|run2=PASS|run3=PASS')
    assert.equal(wrongMode.status, 2)
    assert.match(wrongMode.stdout, /stage=OUTPUT_MODE_IDENTITY/u)
    assert.equal(wrongMode.stdout.includes('run1='), false)
  } finally { rmSync(root, { recursive: true, force: true }) }
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
