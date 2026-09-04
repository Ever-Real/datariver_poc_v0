/* global Buffer */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  K9_SEMANTIC_INPUT_SEGMENTATION_CONTRACT_V1,
  K9_SEMANTIC_MAX_SEGMENT_BYTES_V1,
  K9SemanticInputContractError,
  k9SemanticInputPlan,
  k9SemanticMaterializationHash,
  poolK9SemanticVectors,
  segmentK9SemanticInput,
} from './poc-k9-semantic-input.mjs'

test('segments deterministically on UTF-8-safe boundaries without changing content', () => {
  const content = `${'α'.repeat(2_600)}\n\n${'🚀'.repeat(1_500)} ${'z'.repeat(5_000)}`
  const first = segmentK9SemanticInput(content)
  const second = segmentK9SemanticInput(content)
  assert.deepEqual(first, second)
  assert.equal(first.join(''), content)
  assert.ok(first.length > 1)
  assert.ok(first.every((segment) => Buffer.byteLength(segment, 'utf8') <= 8_192))
  assert.ok(first.every((segment) => !segment.includes('\uFFFD')))
})

test('keeps the exact one-segment provider input and deterministic boundary contract', () => {
  const atBoundary = 'a'.repeat(K9_SEMANTIC_MAX_SEGMENT_BYTES_V1)
  const one = k9SemanticInputPlan(atBoundary)
  assert.equal(one.contract, K9_SEMANTIC_INPUT_SEGMENTATION_CONTRACT_V1)
  assert.deepEqual(one.segments, [atBoundary])
  assert.equal(one.legacy_compatible, true)

  const paragraph = `${'a'.repeat(5_000)}\n\n${'b'.repeat(5_000)}`
  const first = k9SemanticInputPlan(paragraph)
  const second = k9SemanticInputPlan(paragraph)
  assert.equal(first.segments[0], `${'a'.repeat(5_000)}\n\n`)
  assert.equal(first.segments.join(''), paragraph)
  assert.deepEqual(first, second)
  assert.equal(first.legacy_compatible, false)
})

test('materialization identity is stable and changes with the output binding', () => {
  const first = k9SemanticMaterializationHash('a'.repeat(64))
  assert.equal(first, k9SemanticMaterializationHash('a'.repeat(64)))
  assert.notEqual(first, k9SemanticMaterializationHash('b'.repeat(64)))
  assert.match(first, /^[0-9a-f]{64}$/u)
})

test('single vector remains exact and multi-segment pooling is byte-weighted and L2 normalized', () => {
  const single = [3, 4]
  assert.deepEqual(poolK9SemanticVectors(['short'], [single]), single)

  const pooled = poolK9SemanticVectors(['a', 'bbb'], [[1, 0], [0, 1]])
  assert.ok(Math.abs(pooled[0] - (1 / Math.sqrt(10))) < 1e-12)
  assert.ok(Math.abs(pooled[1] - (3 / Math.sqrt(10))) < 1e-12)
  assert.ok(Math.abs(Math.hypot(...pooled) - 1) < 1e-12)
})

test('pooling fails closed on dimension, finite-value, and zero-norm violations', () => {
  for (const [segments, vectors, kind] of [
    [['a', 'b'], [[1], [1, 2]], 'DIMENSION'],
    [['a', 'b'], [[1], [Number.NaN]], 'FINITE'],
    [['a', 'b'], [[1], [-1]], 'FINITE'],
  ]) {
    assert.throws(
      () => poolK9SemanticVectors(segments, vectors),
      (error) => error instanceof K9SemanticInputContractError && error.kind === kind,
    )
  }
})
