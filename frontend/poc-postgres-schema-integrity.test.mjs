import assert from 'node:assert/strict'
import test from 'node:test'

import {
  POC_POSTGRES_OWNED_SCHEMA_QUERY,
  POC_POSTGRES_SCHEMA_CONTRACT,
  POC_POSTGRES_SCHEMA_RECEIPT_SCOPE,
  POC_POSTGRES_SCHEMA_V1_CONTRACT,
  POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE,
  POC_POSTGRES_SCHEMA_V2_CONTRACT,
  POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE,
  POC_POSTGRES_SCHEMA_V3_CONTRACT,
  POC_POSTGRES_SCHEMA_V3_RECEIPT_SCOPE,
  POC_POSTGRES_SCHEMA_V4_CONTRACT,
  POC_POSTGRES_SCHEMA_V4_RECEIPT_SCOPE,
  POC_POSTGRES_SCHEMA_V5_CONTRACT,
  POC_POSTGRES_SCHEMA_V5_RECEIPT_SCOPE,
  POC_POSTGRES_SCHEMA_V6_CONTRACT,
  POC_POSTGRES_SCHEMA_V6_RECEIPT_SCOPE,
  POC_POSTGRES_SCHEMA_V7_CONTRACT,
  POC_POSTGRES_SCHEMA_V7_RECEIPT_SCOPE,
  canonicalizePocOwnedSchemaRows,
  classifyPocPostgresOwnedSchema,
  convergePocPostgresOwnedSchema,
  fingerprintPocOwnedSchema,
  recordPocPostgresOwnedSchemaReceipt,
  recordPocPostgresV1SchemaReceipt,
  recordPocPostgresV2SchemaReceipt,
  recordPocPostgresV3SchemaReceipt,
  recordPocPostgresV4SchemaReceipt,
  recordPocPostgresV5SchemaReceipt,
  recordPocPostgresV6SchemaReceipt,
  recordPocPostgresV7SchemaReceipt,
} from './poc-postgres-schema-integrity.mjs'

function ownedSchemaRows() {
  return [
    { kind: 'TABLE', identity: 'poc_alpha', definition: 'r' },
    { kind: 'COLUMN', identity: 'poc_alpha.1.id', definition: 'bigint|true|||' },
    { kind: 'CONSTRAINT', identity: 'poc_alpha.poc_alpha_pkey', definition: 'p|false|false|true|PRIMARY KEY (id)' },
    { kind: 'INDEX', identity: 'poc_alpha.poc_alpha_lookup', definition: 'false|false|true|true|CREATE INDEX poc_alpha_lookup ON public.poc_alpha USING btree (id)' },
  ]
}

function receipt(scope, contract, revision, fingerprint, extra = {}) {
  return { scope, value: { contract, revision, fingerprint, ...extra } }
}

function v1Receipt(fingerprint, overrides = {}) {
  return receipt(
    overrides.scope ?? POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE,
    overrides.contract ?? POC_POSTGRES_SCHEMA_V1_CONTRACT,
    overrides.revision ?? 1,
    overrides.fingerprint ?? fingerprint,
    overrides.extra,
  )
}

function v2Receipt(fingerprint, overrides = {}) {
  return receipt(
    overrides.scope ?? POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE,
    overrides.contract ?? POC_POSTGRES_SCHEMA_V2_CONTRACT,
    overrides.revision ?? 2,
    overrides.fingerprint ?? fingerprint,
    overrides.extra,
  )
}

function v3Receipt(fingerprint, overrides = {}) {
  return receipt(
    overrides.scope ?? POC_POSTGRES_SCHEMA_V3_RECEIPT_SCOPE,
    overrides.contract ?? POC_POSTGRES_SCHEMA_V3_CONTRACT,
    overrides.revision ?? 3,
    overrides.fingerprint ?? fingerprint,
    overrides.extra,
  )
}

function v4Receipt(fingerprint, overrides = {}) {
  return receipt(
    overrides.scope ?? POC_POSTGRES_SCHEMA_V4_RECEIPT_SCOPE,
    overrides.contract ?? POC_POSTGRES_SCHEMA_V4_CONTRACT,
    overrides.revision ?? 4,
    overrides.fingerprint ?? fingerprint,
    overrides.extra,
  )
}

function v5Receipt(fingerprint, overrides = {}) {
  return receipt(
    overrides.scope ?? POC_POSTGRES_SCHEMA_V5_RECEIPT_SCOPE,
    overrides.contract ?? POC_POSTGRES_SCHEMA_V5_CONTRACT,
    overrides.revision ?? 5,
    overrides.fingerprint ?? fingerprint,
    overrides.extra,
  )
}

function v6Receipt(fingerprint, overrides = {}) {
  return receipt(
    overrides.scope ?? POC_POSTGRES_SCHEMA_V6_RECEIPT_SCOPE,
    overrides.contract ?? POC_POSTGRES_SCHEMA_V6_CONTRACT,
    overrides.revision ?? 6,
    overrides.fingerprint ?? fingerprint,
    overrides.extra,
  )
}

function v7Receipt(fingerprint, overrides = {}) {
  return receipt(
    overrides.scope ?? POC_POSTGRES_SCHEMA_V7_RECEIPT_SCOPE,
    overrides.contract ?? POC_POSTGRES_SCHEMA_V7_CONTRACT,
    overrides.revision ?? 7,
    overrides.fingerprint ?? fingerprint,
    overrides.extra,
  )
}

function v8Receipt(fingerprint, overrides = {}) {
  return receipt(
    overrides.scope ?? POC_POSTGRES_SCHEMA_RECEIPT_SCOPE,
    overrides.contract ?? POC_POSTGRES_SCHEMA_CONTRACT,
    overrides.revision ?? 8,
    overrides.fingerprint ?? fingerprint,
    overrides.extra,
  )
}

function versionedSchemas() {
  const v1Rows = ownedSchemaRows()
  const v2Rows = [
    ...v1Rows,
    { kind: 'COLUMN', identity: 'poc_alpha.2.receipt', definition: 'uuid|true|||' },
  ]
  const v3Rows = [
    ...v2Rows,
    { kind: 'FUNCTION', identity: 'poc_reject_schema_receipt_mutation()', definition: 'trigger|plpgsql|volatile|unsafe|synthetic-v3' },
  ]
  const v4Rows = [
    ...v3Rows,
    { kind: 'CONSTRAINT', identity: 'poc_alpha.ck_audit_v4', definition: 'c|false|false|true|CHECK synthetic-v4' },
  ]
  const v5Rows = [
    ...v4Rows,
    { kind: 'COLUMN', identity: 'poc_alpha.3.discovery', definition: 'jsonb|false|||' },
  ]
  const v6Rows = [
    ...v5Rows,
    { kind: 'TABLE', identity: 'poc_k9_source_snapshots_v2', definition: 'r' },
  ]
  const v7Rows = [
    ...v6Rows,
    { kind: 'TABLE', identity: 'poc_change_history_gap_receipts', definition: 'r' },
  ]
  const v8Rows = [
    ...v7Rows,
    { kind: 'TABLE', identity: 'poc_k9_source_payload_chunks_v2', definition: 'r' },
  ]
  const olderRows = v1Rows.slice(0, -1)
  return {
    olderRows,
    v1Rows,
    v2Rows,
    v3Rows, v4Rows, v5Rows, v6Rows, v7Rows, v8Rows,
    olderFingerprint: fingerprintPocOwnedSchema(olderRows),
    v1Fingerprint: fingerprintPocOwnedSchema(v1Rows),
    v2Fingerprint: fingerprintPocOwnedSchema(v2Rows),
    v3Fingerprint: fingerprintPocOwnedSchema(v3Rows),
    v4Fingerprint: fingerprintPocOwnedSchema(v4Rows),
    v5Fingerprint: fingerprintPocOwnedSchema(v5Rows),
    v6Fingerprint: fingerprintPocOwnedSchema(v6Rows),
    v7Fingerprint: fingerprintPocOwnedSchema(v7Rows),
    v8Fingerprint: fingerprintPocOwnedSchema(v8Rows),
  }
}

function classifyVersioned(rows, receipts = [], overrides = {}) {
  const versions = versionedSchemas()
  return classifyPocPostgresOwnedSchema({
    rows,
    receipts,
    expectedFingerprint: versions.v8Fingerprint,
    v1Fingerprint: versions.v1Fingerprint,
    v2Fingerprint: versions.v2Fingerprint,
    v3Fingerprint: versions.v3Fingerprint,
    v4Fingerprint: versions.v4Fingerprint,
    v5Fingerprint: versions.v5Fingerprint,
    v6Fingerprint: versions.v6Fingerprint,
    v7Fingerprint: versions.v7Fingerprint,
    migratableFingerprints: new Set([versions.olderFingerprint]),
    ...overrides,
  })
}

test('accepts only exact receipted V8 as current and identifies internal receipt boundaries', () => {
  const versions = versionedSchemas()
  assert.equal(classifyVersioned([], []).state, 'FRESH')
  assert.equal(classifyVersioned(versions.v8Rows, []).state, 'CURRENT_UNVERSIONED')
  assert.equal(classifyVersioned(
    versions.v2Rows,
    [v1Receipt(versions.v1Fingerprint)],
  ).state, 'V2_RECEIPT_PENDING')
  assert.equal(classifyVersioned(
    versions.v2Rows,
    [v2Receipt(versions.v2Fingerprint)],
  ).state, 'RECEIPTED_V2')
  assert.equal(classifyVersioned(versions.v3Rows, [
    v1Receipt(versions.v1Fingerprint),
    v2Receipt(versions.v2Fingerprint),
  ]).state, 'V3_RECEIPT_PENDING')
  assert.equal(classifyVersioned(versions.v3Rows, [v3Receipt(versions.v3Fingerprint)]).state, 'RECEIPTED_V3')
  assert.equal(classifyVersioned(versions.v4Rows, [
    v3Receipt(versions.v3Fingerprint),
  ]).state, 'V4_RECEIPT_PENDING')
  assert.equal(classifyVersioned(versions.v4Rows, [
    v4Receipt(versions.v4Fingerprint),
  ]).state, 'RECEIPTED_V4')
  assert.equal(classifyVersioned(versions.v5Rows, [
    v4Receipt(versions.v4Fingerprint),
  ]).state, 'V5_RECEIPT_PENDING')
  assert.equal(classifyVersioned(versions.v5Rows, [
    v5Receipt(versions.v5Fingerprint),
  ]).state, 'RECEIPTED_V5')
  assert.equal(classifyVersioned(versions.v6Rows, [
    v5Receipt(versions.v5Fingerprint),
  ]).state, 'V6_RECEIPT_PENDING')
  assert.equal(classifyVersioned(versions.v6Rows, [
    v6Receipt(versions.v6Fingerprint),
  ]).state, 'RECEIPTED_V6')
  assert.equal(classifyVersioned(versions.v7Rows, [
    v6Receipt(versions.v6Fingerprint),
  ]).state, 'V7_RECEIPT_PENDING')
  assert.equal(classifyVersioned(versions.v7Rows, [
    v7Receipt(versions.v7Fingerprint),
  ]).state, 'RECEIPTED_V7')
  assert.equal(classifyVersioned(versions.v8Rows, [
    v7Receipt(versions.v7Fingerprint),
  ]).state, 'V8_RECEIPT_PENDING')
  assert.equal(classifyVersioned(versions.v8Rows, [
    v8Receipt(versions.v8Fingerprint),
  ]).state, 'CURRENT')
})

test('accepts exact V1 and the single known-older unreceipted predecessor only', () => {
  const versions = versionedSchemas()
  assert.equal(classifyVersioned(
    versions.v1Rows,
    [v1Receipt(versions.v1Fingerprint)],
  ).state, 'RECEIPTED_V1')
  assert.equal(classifyVersioned(versions.v1Rows).state, 'V1_RECEIPT_PENDING')
  assert.equal(classifyVersioned(versions.olderRows).state, 'KNOWN_OLDER_MIGRATABLE')
  assert.throws(
    () => classifyVersioned(versions.olderRows, [v1Receipt(versions.v1Fingerprint)]),
    { code: 'POC_POSTGRES_SCHEMA_INTEGRITY_FAILED' },
  )
  assert.throws(
    () => classifyVersioned(versions.olderRows, [], { migratableFingerprints: new Set() }),
    { code: 'POC_POSTGRES_SCHEMA_INTEGRITY_FAILED' },
  )
})

test('maps the legacy single receipt argument to V1 scope compatibility', () => {
  const versions = versionedSchemas()
  const legacyReceipt = v1Receipt(versions.v1Fingerprint).value
  assert.equal(classifyPocPostgresOwnedSchema({
    rows: versions.v1Rows,
    receipt: legacyReceipt,
    expectedFingerprint: versions.v7Fingerprint,
    v1Fingerprint: versions.v1Fingerprint,
    v2Fingerprint: versions.v2Fingerprint,
    v3Fingerprint: versions.v3Fingerprint,
    v4Fingerprint: versions.v4Fingerprint,
    v5Fingerprint: versions.v5Fingerprint,
    v6Fingerprint: versions.v6Fingerprint,
    migratableFingerprints: new Set(),
  }).state, 'RECEIPTED_V1')
  assert.equal(classifyPocPostgresOwnedSchema({
    rows: versions.v2Rows,
    receipt: legacyReceipt,
    expectedFingerprint: versions.v7Fingerprint,
    v1Fingerprint: versions.v1Fingerprint,
    v2Fingerprint: versions.v2Fingerprint,
    v3Fingerprint: versions.v3Fingerprint,
    v4Fingerprint: versions.v4Fingerprint,
    v5Fingerprint: versions.v5Fingerprint,
    v6Fingerprint: versions.v6Fingerprint,
    migratableFingerprints: new Set(),
  }).state, 'V2_RECEIPT_PENDING')
})

test('fails closed for missing, malformed, wrong, partial and newer receipt sets', () => {
  const versions = versionedSchemas()
  assert.throws(
    () => classifyVersioned([], [v1Receipt(versions.v1Fingerprint)]),
    { code: 'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH' },
  )
  for (const receipts of [
    [v1Receipt(versions.v1Fingerprint, { contract: 'WRONG' })],
    [v1Receipt(versions.v1Fingerprint, { fingerprint: '0'.repeat(64) })],
    [v1Receipt(versions.v1Fingerprint, { revision: 0 })],
    [v1Receipt(versions.v1Fingerprint, { extra: { unexpected: true } })],
    [{ scope: POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE }],
    [v1Receipt(versions.v1Fingerprint), v1Receipt(versions.v1Fingerprint)],
    [{ scope: 'product-owned-schema-contract-v0', value: {} }],
  ]) {
    assert.throws(
      () => classifyVersioned(versions.v1Rows, receipts),
      { code: 'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH' },
    )
  }
  assert.throws(
    () => classifyVersioned(versions.v1Rows, [v2Receipt(versions.v2Fingerprint)]),
    { code: 'POC_POSTGRES_SCHEMA_INTEGRITY_FAILED' },
  )
  assert.throws(
    () => classifyVersioned(versions.v3Rows, [
      v1Receipt(versions.v1Fingerprint),
      v3Receipt(versions.v3Fingerprint),
    ]),
    { code: 'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH' },
  )
  assert.throws(
    () => classifyVersioned(versions.v4Rows, [
      v1Receipt(versions.v1Fingerprint),
      v4Receipt(versions.v4Fingerprint),
    ]),
    { code: 'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH' },
  )
  assert.throws(
    () => classifyVersioned(versions.v1Rows, [
      v1Receipt(versions.v1Fingerprint),
      v2Receipt(versions.v2Fingerprint),
      v3Receipt(versions.v3Fingerprint),
    ]),
    { code: 'POC_POSTGRES_SCHEMA_INTEGRITY_FAILED' },
  )
  assert.throws(
    () => classifyVersioned(versions.olderRows, [v3Receipt(versions.v3Fingerprint)]),
    { code: 'POC_POSTGRES_SCHEMA_INTEGRITY_FAILED' },
  )
  assert.throws(
    () => classifyVersioned(versions.v3Rows, [v3Receipt(versions.v3Fingerprint, { revision: 9 })]),
    { code: 'POC_POSTGRES_SCHEMA_NEWER_UNSUPPORTED' },
  )
  assert.throws(
    () => classifyVersioned(versions.v2Rows, [{
      scope: 'product-owned-schema-contract-v9',
      value: { contract: 'DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V9', revision: 9, fingerprint: '0'.repeat(64) },
    }]),
    { code: 'POC_POSTGRES_SCHEMA_NEWER_UNSUPPORTED' },
  )
})

test('fails closed for missing columns, type drift, constraints and critical indexes', () => {
  const versions = versionedSchemas()
  const invalidCases = [
    versions.v8Rows.filter((row) => row.kind !== 'COLUMN'),
    versions.v8Rows.map((row) => row.identity.endsWith('.discovery') ? { ...row, definition: 'text|true|||' } : row),
    versions.v8Rows.filter((row) => row.kind !== 'CONSTRAINT'),
    versions.v8Rows.filter((row) => row.kind !== 'INDEX'),
  ]
  for (const invalidRows of invalidCases) {
    assert.throws(
      () => classifyVersioned(invalidRows, [v8Receipt(versions.v8Fingerprint)]),
      { code: 'POC_POSTGRES_SCHEMA_INTEGRITY_FAILED' },
    )
  }
})

test('converges exact V1 through V7, known older and fresh schemas to durable V8 in order', async () => {
  const scenarios = [
    {
      states: ['V1_RECEIPT_PENDING', 'RECEIPTED_V1', 'V2_RECEIPT_PENDING', 'RECEIPTED_V2', 'V3_RECEIPT_PENDING', 'RECEIPTED_V3', 'V4_RECEIPT_PENDING', 'RECEIPTED_V4', 'V5_RECEIPT_PENDING', 'RECEIPTED_V5', 'V6_RECEIPT_PENDING', 'RECEIPTED_V6', 'V7_RECEIPT_PENDING', 'RECEIPTED_V7', 'V8_RECEIPT_PENDING', 'CURRENT', 'CURRENT'],
      actions: ['V1_RECEIPT', 'V2_DDL', 'V2_RECEIPT', 'V3_DDL', 'V3_RECEIPT', 'V4_DDL', 'V4_RECEIPT', 'V5_DDL', 'V5_RECEIPT', 'V6_DDL', 'V6_RECEIPT', 'V7_DDL', 'V7_RECEIPT', 'V8_DDL', 'V8_RECEIPT'],
    },
    {
      states: ['RECEIPTED_V5', 'V6_RECEIPT_PENDING', 'RECEIPTED_V6', 'V7_RECEIPT_PENDING', 'RECEIPTED_V7', 'V8_RECEIPT_PENDING', 'CURRENT', 'CURRENT'],
      actions: ['V6_DDL', 'V6_RECEIPT', 'V7_DDL', 'V7_RECEIPT', 'V8_DDL', 'V8_RECEIPT'],
    },
    {
      states: ['RECEIPTED_V6', 'V7_RECEIPT_PENDING', 'RECEIPTED_V7', 'V8_RECEIPT_PENDING', 'CURRENT', 'CURRENT'],
      actions: ['V7_DDL', 'V7_RECEIPT', 'V8_DDL', 'V8_RECEIPT'],
    },
    {
      states: ['RECEIPTED_V7', 'V8_RECEIPT_PENDING', 'CURRENT', 'CURRENT'],
      actions: ['V8_DDL', 'V8_RECEIPT'],
    },
    {
      states: ['KNOWN_OLDER_MIGRATABLE', 'V1_RECEIPT_PENDING', 'RECEIPTED_V1', 'V2_RECEIPT_PENDING', 'RECEIPTED_V2', 'V3_RECEIPT_PENDING', 'RECEIPTED_V3', 'V4_RECEIPT_PENDING', 'RECEIPTED_V4', 'V5_RECEIPT_PENDING', 'RECEIPTED_V5', 'V6_RECEIPT_PENDING', 'RECEIPTED_V6', 'V7_RECEIPT_PENDING', 'RECEIPTED_V7', 'V8_RECEIPT_PENDING', 'CURRENT', 'CURRENT'],
      actions: ['V1_DDL', 'V1_RECEIPT', 'V2_DDL', 'V2_RECEIPT', 'V3_DDL', 'V3_RECEIPT', 'V4_DDL', 'V4_RECEIPT', 'V5_DDL', 'V5_RECEIPT', 'V6_DDL', 'V6_RECEIPT', 'V7_DDL', 'V7_RECEIPT', 'V8_DDL', 'V8_RECEIPT'],
    },
    {
      states: ['FRESH', 'CURRENT_UNVERSIONED', 'CURRENT'],
      actions: ['FRESH_DDL', 'V8_RECEIPT'],
    },
  ]
  for (const scenario of scenarios) {
    const calls = []
    const states = [...scenario.states]
    const client = { async query(sql) { calls.push(sql); return { rows: [] } } }
    await convergePocPostgresOwnedSchema(client, {
      inspect: async () => ({ state: states.shift() }),
      applyFreshSchema: async () => { calls.push('FRESH_DDL') },
      applyKnownOlderSchema: async () => { calls.push('V1_DDL') },
      applyV2Schema: async () => { calls.push('V2_DDL') },
      applyV3Schema: async () => { calls.push('V3_DDL') },
      applyV4Schema: async () => { calls.push('V4_DDL') },
      applyV5Schema: async () => { calls.push('V5_DDL') },
      applyV6Schema: async () => { calls.push('V6_DDL') },
      applyV7Schema: async () => { calls.push('V7_DDL') },
      applyV8Schema: async () => { calls.push('V8_DDL') },
      recordV1Receipt: async () => { calls.push('V1_RECEIPT') },
      recordV2Receipt: async () => { calls.push('V2_RECEIPT') },
      recordV3Receipt: async () => { calls.push('V3_RECEIPT') },
      recordV4Receipt: async () => { calls.push('V4_RECEIPT') },
      recordV5Receipt: async () => { calls.push('V5_RECEIPT') },
      recordV6Receipt: async () => { calls.push('V6_RECEIPT') },
      recordV7Receipt: async () => { calls.push('V7_RECEIPT') },
      recordReceipt: async () => { calls.push('V8_RECEIPT') },
    })
    assert.deepEqual(calls, ['BEGIN', ...scenario.actions, 'COMMIT'])
    assert.equal(states.length, 0)
  }

  const restartCalls = []
  await convergePocPostgresOwnedSchema({
    async query(sql) { restartCalls.push(sql); return { rows: [] } },
  }, {
    inspect: async () => ({ state: 'CURRENT' }),
    applyFreshSchema: async () => { assert.fail('restart must not apply fresh DDL') },
    applyKnownOlderSchema: async () => { assert.fail('restart must not apply V1 DDL') },
    applyV2Schema: async () => { assert.fail('restart must not apply V2 DDL') },
    applyV3Schema: async () => { assert.fail('restart must not apply V3 DDL') },
    applyV4Schema: async () => { assert.fail('restart must not apply V4 DDL') },
    applyV5Schema: async () => { assert.fail('restart must not apply V5 DDL') },
    applyV6Schema: async () => { assert.fail('restart must not apply V6 DDL') },
    applyV7Schema: async () => { assert.fail('restart must not apply V7 DDL') },
    applyV8Schema: async () => { assert.fail('restart must not apply V8 DDL') },
    recordV1Receipt: async () => { assert.fail('restart must not insert a V1 receipt') },
    recordV2Receipt: async () => { assert.fail('restart must not insert a V2 receipt') },
    recordV3Receipt: async () => { assert.fail('restart must not insert a V3 receipt') },
    recordV4Receipt: async () => { assert.fail('restart must not insert a V4 receipt') },
    recordV5Receipt: async () => { assert.fail('restart must not insert a V5 receipt') },
    recordV6Receipt: async () => { assert.fail('restart must not insert a V6 receipt') },
    recordV7Receipt: async () => { assert.fail('restart must not insert a V7 receipt') },
    recordReceipt: async () => { assert.fail('restart must not insert another V8 receipt') },
  })
  assert.deepEqual(restartCalls, ['BEGIN', 'COMMIT'])
})

test('rolls back unsupported, DDL-failed and receipt-failed convergence', async () => {
  const scenarios = [
    { states: ['CURRENT_UNVERSIONED'] },
    { states: ['V2_RECEIPT_PENDING'] },
    { states: ['V3_RECEIPT_PENDING'] },
    { states: ['V4_RECEIPT_PENDING'] },
    { states: ['V5_RECEIPT_PENDING'] },
    { states: ['V6_RECEIPT_PENDING'] },
    { states: ['V7_RECEIPT_PENDING'] },
    { states: ['V8_RECEIPT_PENDING'] },
    { states: ['RECEIPTED_V1'], ddlError: new Error('DDL failed') },
    { states: ['RECEIPTED_V4'], ddlError: new Error('V5 DDL failed') },
    { states: ['RECEIPTED_V5'], ddlError: new Error('V6 DDL failed') },
    { states: ['RECEIPTED_V6'], ddlError: new Error('V7 DDL failed') },
    { states: ['RECEIPTED_V7'], ddlError: new Error('V8 DDL failed') },
    { states: ['RECEIPTED_V1', 'CURRENT_UNVERSIONED'] },
    { states: ['RECEIPTED_V1', 'V2_RECEIPT_PENDING'], receiptError: new Error('receipt failed') },
    { states: ['RECEIPTED_V4', 'V5_RECEIPT_PENDING'], receiptError: new Error('V5 receipt failed') },
    { states: ['RECEIPTED_V5', 'V6_RECEIPT_PENDING'], receiptError: new Error('V6 receipt failed') },
    { states: ['RECEIPTED_V6', 'V7_RECEIPT_PENDING'], receiptError: new Error('V7 receipt failed') },
    { states: ['RECEIPTED_V7', 'V8_RECEIPT_PENDING'], receiptError: new Error('V8 receipt failed') },
    { states: ['RECEIPTED_V1', 'V2_RECEIPT_PENDING', 'V2_RECEIPT_PENDING'] },
    { states: ['KNOWN_OLDER_MIGRATABLE', 'CURRENT_UNVERSIONED'] },
    { states: ['V1_RECEIPT_PENDING'], v1ReceiptError: new Error('V1 receipt failed') },
    { states: ['KNOWN_OLDER_MIGRATABLE', 'V1_RECEIPT_PENDING'], v1ReceiptError: new Error('V1 receipt failed') },
  ]
  for (const scenario of scenarios) {
    const calls = []
    const states = [...scenario.states]
    const client = { async query(sql) { calls.push(sql); return { rows: [] } } }
    await assert.rejects(convergePocPostgresOwnedSchema(client, {
      inspect: async () => ({ state: states.shift() }),
      applyFreshSchema: async () => {},
      applyKnownOlderSchema: async () => {},
      applyV2Schema: async () => { if (scenario.ddlError) throw scenario.ddlError },
      applyV3Schema: async () => { if (scenario.ddlError) throw scenario.ddlError },
      applyV4Schema: async () => { if (scenario.ddlError) throw scenario.ddlError },
      applyV5Schema: async () => { if (scenario.ddlError) throw scenario.ddlError },
      applyV6Schema: async () => { if (scenario.ddlError) throw scenario.ddlError },
      applyV7Schema: async () => { if (scenario.ddlError) throw scenario.ddlError },
      applyV8Schema: async () => { if (scenario.ddlError) throw scenario.ddlError },
      recordV1Receipt: async () => { if (scenario.v1ReceiptError) throw scenario.v1ReceiptError },
      recordV2Receipt: async () => { if (scenario.receiptError) throw scenario.receiptError },
      recordV3Receipt: async () => { if (scenario.receiptError) throw scenario.receiptError },
      recordV4Receipt: async () => { if (scenario.receiptError) throw scenario.receiptError },
      recordV5Receipt: async () => { if (scenario.receiptError) throw scenario.receiptError },
      recordV6Receipt: async () => { if (scenario.receiptError) throw scenario.receiptError },
      recordV7Receipt: async () => { if (scenario.receiptError) throw scenario.receiptError },
      recordReceipt: async () => { if (scenario.receiptError) throw scenario.receiptError },
    }))
    assert.equal(calls[0], 'BEGIN')
    assert.equal(calls.at(-1), 'ROLLBACK')
    assert.equal(calls.includes('COMMIT'), false)
  }
})

test('inserts immutable V1 through V8 receipts without overwrite SQL', async () => {
  for (const [record, expectedScope] of [
    [recordPocPostgresV1SchemaReceipt, POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE],
    [recordPocPostgresV2SchemaReceipt, POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE],
    [recordPocPostgresV3SchemaReceipt, POC_POSTGRES_SCHEMA_V3_RECEIPT_SCOPE],
    [recordPocPostgresV4SchemaReceipt, POC_POSTGRES_SCHEMA_V4_RECEIPT_SCOPE],
    [recordPocPostgresV5SchemaReceipt, POC_POSTGRES_SCHEMA_V5_RECEIPT_SCOPE],
    [recordPocPostgresV6SchemaReceipt, POC_POSTGRES_SCHEMA_V6_RECEIPT_SCOPE],
    [recordPocPostgresV7SchemaReceipt, POC_POSTGRES_SCHEMA_V7_RECEIPT_SCOPE],
    [recordPocPostgresOwnedSchemaReceipt, POC_POSTGRES_SCHEMA_RECEIPT_SCOPE],
  ]) {
    const calls = []
    await record({
      async query(sql, parameters) {
        calls.push({ sql: String(sql).replace(/\s+/g, ' ').trim(), parameters })
        return { rows: [{ scope: expectedScope }] }
      },
    })
    assert.equal(calls.length, 1)
    assert.match(calls[0].sql, /^INSERT INTO poc_state/)
    assert.doesNotMatch(calls[0].sql, /ON CONFLICT|UPDATE|DELETE/)
    assert.equal(calls[0].parameters[0], expectedScope)
  }
})

test('the bounded catalog contract excludes non-owned schemas, extensions and row data', () => {
  assert.match(POC_POSTGRES_OWNED_SCHEMA_QUERY, /namespace\.nspname = 'public'/)
  assert.match(POC_POSTGRES_OWNED_SCHEMA_QUERY, /relname LIKE 'poc\\_%'/)
  assert.match(POC_POSTGRES_OWNED_SCHEMA_QUERY, /proname LIKE 'poc\\_%'/)
  assert.match(POC_POSTGRES_OWNED_SCHEMA_QUERY, /typname LIKE 'poc\\_%'/)
  assert.match(POC_POSTGRES_OWNED_SCHEMA_QUERY, /LIMIT 5001/)
  assert.doesNotMatch(POC_POSTGRES_OWNED_SCHEMA_QUERY, /pg_catalog\.pg_extension/)
  assert.doesNotMatch(POC_POSTGRES_OWNED_SCHEMA_QUERY, /SELECT \* FROM poc_/)
  assert.match(POC_POSTGRES_OWNED_SCHEMA_QUERY, /constraint_value\.contype::text/)
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
