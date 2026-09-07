import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'

const source = readFileSync(new URL('./prep39083-general-classifier-rca-probe', import.meta.url), 'utf8')
const helpers = source.slice(source.indexOf('const ROUTE_FIELDS ='), source.indexOf('function parsedRawValue('))
const { longOutputEvidence, modelEvidence } = runInNewContext(
  `${helpers}\n({ longOutputEvidence, modelEvidence })`,
  { Buffer, createHash, boundedCount: (value) => String(value) },
)

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
