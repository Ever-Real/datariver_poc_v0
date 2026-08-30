import assert from 'node:assert/strict'
import { test } from 'node:test'
import { glossaryAssignmentCountsFromInventory } from './poc-server.mjs'

const termA = 'urn:li:glossaryTerm:generic-a'
const termB = 'urn:li:glossaryTerm:generic-b'
const table = (id, tableTerms = [], fields = []) => ({
  id: `urn:li:dataset:(urn:li:dataPlatform:postgres,synthetic.${id},PROD)`,
  dataset_kind: 'TABLE',
  glossary_terms: tableTerms.map((urn) => ({ urn })),
  term_references: tableTerms.map((urn) => ({ urn })),
  schema_fields: fields.map((terms, index) => ({
    fieldPath: `field_${index}`,
    glossaryTerms: { terms: terms.map((urn) => ({ term: { urn } })) },
  })),
})

test('batch counts use canonical Term identity, dedupe observations, and return exact zero', () => {
  const result = glossaryAssignmentCountsFromInventory([termA, termB], [
    table('one', [termA, termA], [[termA, termA], [termA]]),
    table('two', [termA], [[termB]]),
    { ...table('view', [termA], [[termA]]), dataset_kind: 'VIEW' },
  ])

  assert.deepEqual(result, { items: [
    { urn: termA, table_asset_count: 2, column_asset_count: 2 },
    { urn: termB, table_asset_count: 0, column_asset_count: 1 },
  ] })
})
