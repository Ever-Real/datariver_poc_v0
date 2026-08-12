import assert from 'node:assert/strict'
import test from 'node:test'
import { chatRouterBenchmark } from './chat-router-benchmark.mjs'

test('keeps a balanced credential-free Chat routing benchmark contract', () => {
  assert.equal(chatRouterBenchmark.length, 72)
  const categories = new Map()
  const ids = new Set()
  for (const item of chatRouterBenchmark) {
    assert.ok(item.query.length >= 4)
    assert.ok(['GENERAL', 'VECTOR', 'GRAPH'].includes(item.expected_primary_mode))
    assert.equal(typeof item.entity_resolution_required, 'boolean')
    assert.ok(item.acceptable_fallback === null || ['GENERAL', 'VECTOR', 'GRAPH'].includes(item.acceptable_fallback))
    assert.doesNotMatch(item.query, /urn:li:|localhost|https?:\/\/|token|password|secret/i)
    assert.equal(ids.has(item.id), false)
    ids.add(item.id)
    categories.set(item.category, (categories.get(item.category) || 0) + 1)
  }
  assert.equal(categories.size, 9)
  assert.ok([...categories.values()].every((count) => count === 8))
  for (const pair of ['upstream-meaning-vs-asset', 'exact-description-vs-impact', 'column-similarity-vs-lineage']) {
    assert.equal(chatRouterBenchmark.filter((item) => item.negative_pair === pair).length, 2)
  }
})
