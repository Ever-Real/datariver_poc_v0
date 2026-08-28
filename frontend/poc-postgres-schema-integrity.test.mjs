import assert from 'node:assert/strict'
import test from 'node:test'

import {
  POC_POSTGRES_OWNED_SCHEMA_QUERY,
  canonicalizePocOwnedSchemaRows,
  classifyPocPostgresOwnedSchema,
  fingerprintPocOwnedSchema,
} from './poc-postgres-schema-integrity.mjs'

function ownedSchemaRows() {
  return [
    { kind: 'TABLE', identity: 'poc_alpha', definition: 'r' },
    { kind: 'COLUMN', identity: 'poc_alpha.1.id', definition: 'bigint|true|||' },
    { kind: 'CONSTRAINT', identity: 'poc_alpha.poc_alpha_pkey', definition: 'p|false|false|true|PRIMARY KEY (id)' },
    { kind: 'INDEX', identity: 'poc_alpha.poc_alpha_lookup', definition: 'false|false|true|true|CREATE INDEX poc_alpha_lookup ON public.poc_alpha USING btree (id)' },
  ]
}

function contractFor(rows, overrides = {}) {
  return {
    rows,
    expectedFingerprint: fingerprintPocOwnedSchema(rows),
    migratableFingerprints: new Set(),
    ...overrides,
  }
}

test('accepts exact Product-owned schema with and without a version receipt', () => {
  const rows = ownedSchemaRows()
  const contract = contractFor(rows)
  assert.equal(classifyPocPostgresOwnedSchema(contract).state, 'CURRENT_UNVERSIONED')
  assert.equal(classifyPocPostgresOwnedSchema({
    ...contract,
    receipt: {
      contract: 'DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V1',
      revision: 1,
      fingerprint: contract.expectedFingerprint,
    },
  }).state, 'CURRENT')
})

test('permits only an explicitly listed older Product-owned fingerprint', () => {
  const rows = ownedSchemaRows()
  const newerRows = [...rows, { kind: 'COLUMN', identity: 'poc_alpha.2.label', definition: 'text|false|||' }]
  assert.equal(classifyPocPostgresOwnedSchema({
    ...contractFor(newerRows),
    expectedFingerprint: fingerprintPocOwnedSchema(newerRows),
    rows,
    migratableFingerprints: new Set([fingerprintPocOwnedSchema(rows)]),
  }).state, 'KNOWN_OLDER_MIGRATABLE')
})

test('fails closed for missing columns, type drift, constraints and critical indexes', () => {
  const rows = ownedSchemaRows()
  const expectedFingerprint = fingerprintPocOwnedSchema(rows)
  const invalidCases = [
    rows.filter((row) => row.kind !== 'COLUMN'),
    rows.map((row) => row.kind === 'COLUMN' ? { ...row, definition: 'text|true|||' } : row),
    rows.filter((row) => row.kind !== 'CONSTRAINT'),
    rows.filter((row) => row.kind !== 'INDEX'),
  ]
  for (const invalidRows of invalidCases) {
    assert.throws(
      () => classifyPocPostgresOwnedSchema({
        rows: invalidRows,
        expectedFingerprint,
        migratableFingerprints: new Set(),
      }),
      { code: 'POC_POSTGRES_SCHEMA_INTEGRITY_FAILED' },
    )
  }
})

test('fails closed for a malformed, mismatched or newer schema receipt', () => {
  const contract = contractFor(ownedSchemaRows())
  assert.throws(
    () => classifyPocPostgresOwnedSchema({ ...contract, receipt: { revision: 1 } }),
    { code: 'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH' },
  )
  assert.throws(
    () => classifyPocPostgresOwnedSchema({
      ...contract,
      receipt: {
        contract: 'DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V1',
        revision: 2,
        fingerprint: contract.expectedFingerprint,
      },
    }),
    { code: 'POC_POSTGRES_SCHEMA_NEWER_UNSUPPORTED' },
  )
})

test('the bounded catalog contract excludes non-owned schemas, extensions and row data', () => {
  assert.match(POC_POSTGRES_OWNED_SCHEMA_QUERY, /namespace\.nspname = 'public'/)
  assert.match(POC_POSTGRES_OWNED_SCHEMA_QUERY, /relname LIKE 'poc\\_%'/)
  assert.match(POC_POSTGRES_OWNED_SCHEMA_QUERY, /proname LIKE 'poc\\_%'/)
  assert.match(POC_POSTGRES_OWNED_SCHEMA_QUERY, /typname LIKE 'poc\\_%'/)
  assert.match(POC_POSTGRES_OWNED_SCHEMA_QUERY, /LIMIT 5001/)
  assert.doesNotMatch(POC_POSTGRES_OWNED_SCHEMA_QUERY, /pg_catalog\.pg_extension/)
  assert.doesNotMatch(POC_POSTGRES_OWNED_SCHEMA_QUERY, /SELECT \* FROM poc_/)
})

test('schema canonicalization is deterministic and rejects duplicate owned identity', () => {
  const rows = ownedSchemaRows()
  assert.deepEqual(canonicalizePocOwnedSchemaRows([...rows].reverse()), canonicalizePocOwnedSchemaRows(rows))
  assert.equal(fingerprintPocOwnedSchema([...rows].reverse()), fingerprintPocOwnedSchema(rows))
  assert.throws(
    () => canonicalizePocOwnedSchemaRows([...rows, rows[0]]),
    { code: 'POC_POSTGRES_SCHEMA_INSPECTION_INVALID' },
  )
})
