import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import process from 'node:process'
import test from 'node:test'
import { URL } from 'node:url'
import pg from 'pg'

import {
  POC_POSTGRES_MIGRATABLE_FINGERPRINTS,
  POC_POSTGRES_OWNED_SCHEMA_QUERY,
  POC_POSTGRES_SCHEMA_CONTRACT,
  POC_POSTGRES_SCHEMA_FINGERPRINT,
  POC_POSTGRES_SCHEMA_RECEIPT_SCOPE,
  POC_POSTGRES_SCHEMA_REVISION,
  POC_POSTGRES_SCHEMA_V1_CONTRACT,
  POC_POSTGRES_SCHEMA_V1_FINGERPRINT,
  POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE,
  POC_POSTGRES_SCHEMA_V1_REVISION,
  POC_POSTGRES_SCHEMA_V2_CONTRACT,
  POC_POSTGRES_SCHEMA_V2_FINGERPRINT,
  POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE,
  POC_POSTGRES_SCHEMA_V2_REVISION,
  canonicalizePocOwnedSchemaRows,
  fingerprintPocOwnedSchema,
  inspectPocPostgresOwnedSchema,
  recordPocPostgresV1SchemaReceipt,
} from './poc-postgres-schema-integrity.mjs'
import {
  pocPostgresTestSkipReason,
  withDisposablePocPostgres,
} from './poc-postgres-test-fixture.mjs'
import { createPocStateStore } from './poc-state-store.mjs'

const { Pool } = pg
const knownOlderFingerprint = 'd96eab3a780b05349bbccdbf1e2ee25e0d9da4d4b8c63c5cfd9c4fe97935d30b'
const migrationNames = [
  '001-poc-state.sql',
  '002-poc-knowledge-ingestion.sql',
  '003-poc-k9-managed-graphs.sql',
  '004-poc-local-security-events.sql',
  '005-poc-mcp-read-receipts.sql',
]
const migrations = new Map(migrationNames.map((name) => [
  name,
  readFileSync(new URL(`../deploy/poc/postgres-init/${name}`, import.meta.url), 'utf8'),
]))
const v2Migration = migrations.get('004-poc-local-security-events.sql')
const v2DdlOnly = v2Migration.slice(
  v2Migration.indexOf('CREATE TABLE'),
  v2Migration.indexOf('INSERT INTO poc_state'),
)
const v3Migration = migrations.get('005-poc-mcp-read-receipts.sql')
const v3DdlOnly = v3Migration.slice(
  v3Migration.indexOf('CREATE OR REPLACE FUNCTION'),
  v3Migration.indexOf('INSERT INTO poc_state'),
)

const knownOlderCategoryConstraint = `
  ALTER TABLE poc_change_history_ledger_events
    DROP CONSTRAINT ck_poc_change_history_ledger_category_v3;
  ALTER TABLE poc_change_history_ledger_events
    ADD CONSTRAINT ck_poc_change_history_ledger_category_v2 CHECK (
      (category = 'TECHNICAL_SCHEMA' AND source_aspect = 'schemaMetadata')
      OR (category = 'DOCUMENTATION' AND source_aspect IN ('datasetProperties', 'editableSchemaMetadata'))
      OR (category = 'TAG' AND source_aspect IN ('globalTags', 'schemaMetadata', 'editableSchemaMetadata'))
      OR (category = 'GLOSSARY_TERM' AND source_aspect IN ('glossaryTerms', 'schemaMetadata', 'editableSchemaMetadata'))
      OR (category = 'OWNERSHIP' AND source_aspect = 'ownership')
      OR (category = 'LIFECYCLE' AND source_aspect IN ('status', 'entity'))
    )
`

function expectedReceipt({ contract, revision, fingerprint }) {
  return { contract, revision, fingerprint }
}

const exactV1Receipt = expectedReceipt({
  contract: POC_POSTGRES_SCHEMA_V1_CONTRACT,
  revision: POC_POSTGRES_SCHEMA_V1_REVISION,
  fingerprint: POC_POSTGRES_SCHEMA_V1_FINGERPRINT,
})
const exactV2Receipt = expectedReceipt({
  contract: POC_POSTGRES_SCHEMA_V2_CONTRACT,
  revision: POC_POSTGRES_SCHEMA_V2_REVISION,
  fingerprint: POC_POSTGRES_SCHEMA_V2_FINGERPRINT,
})
const exactV3Receipt = expectedReceipt({
  contract: POC_POSTGRES_SCHEMA_CONTRACT,
  revision: POC_POSTGRES_SCHEMA_REVISION,
  fingerprint: POC_POSTGRES_SCHEMA_FINGERPRINT,
})

async function applyMigrations(pool, names) {
  for (const name of names) await pool.query(migrations.get(name))
}

async function applyV1(pool) {
  await applyMigrations(pool, migrationNames.slice(0, 3))
}

async function applyV2(pool) {
  await applyMigrations(pool, migrationNames.slice(0, 4))
}

async function applyV3(pool) {
  await applyMigrations(pool, migrationNames)
}

function normalizeQuery(args) {
  const query = typeof args[0] === 'string' ? args[0] : args[0]?.text
  const parameters = typeof args[0] === 'string' ? args[1] : args[0]?.values
  return {
    sql: String(query).replace(/\s+/g, ' ').trim(),
    parameters: parameters ?? [],
  }
}

function createObservedPool(realPool) {
  const trace = []
  let injectedFailure
  async function query(target, args) {
    const observed = normalizeQuery(args)
    trace.push(observed)
    if (injectedFailure?.matcher(observed)) {
      const { code, message } = injectedFailure
      injectedFailure = undefined
      throw Object.assign(new Error(message), { code })
    }
    return target.query(...args)
  }
  return {
    pool: {
      on: (...args) => realPool.on(...args),
      query: (...args) => query(realPool, args),
      async connect() {
        const client = await realPool.connect()
        return {
          query: (...args) => query(client, args),
          release: () => client.release(),
        }
      },
    },
    injectFailure(failure) {
      injectedFailure = failure
    },
    trace,
  }
}

async function withSchemaIntegrityRequired(action) {
  const previous = process.env.POC_POSTGRES_SCHEMA_INTEGRITY_REQUIRED
  process.env.POC_POSTGRES_SCHEMA_INTEGRITY_REQUIRED = 'true'
  try {
    return await action()
  } finally {
    if (previous === undefined) delete process.env.POC_POSTGRES_SCHEMA_INTEGRITY_REQUIRED
    else process.env.POC_POSTGRES_SCHEMA_INTEGRITY_REQUIRED = previous
  }
}

async function initializeActualStore(observed) {
  return withSchemaIntegrityRequired(async () => {
    const store = createPocStateStore({ databasePool: observed.pool })
    try {
      return await store.read('synthetic-schema-probe')
    } finally {
      await store.close()
    }
  })
}

async function catalogSnapshot(pool) {
  const [catalog, receipts] = await Promise.all([
    pool.query(POC_POSTGRES_OWNED_SCHEMA_QUERY),
    pool.query(`
      SELECT scope, value, version::text
      FROM poc_state
      WHERE scope LIKE 'product-owned-schema-contract-v%'
      ORDER BY scope
    `),
  ])
  const rows = canonicalizePocOwnedSchemaRows(catalog.rows)
  return {
    rows,
    fingerprint: fingerprintPocOwnedSchema(rows),
    receipts: receipts.rows,
  }
}

function mutatingStatements(trace) {
  return trace.map(({ sql }) => sql).filter((sql) => (
    /^(?:CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|TRUNCATE|DO)\b/.test(sql)
  ))
}

async function insertReceipt(pool, scope, value) {
  await pool.query(
    'INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)',
    [scope, JSON.stringify(value)],
  )
}

test('fresh immutable migrations expose the exact current V3 catalog and restart without mutation', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('fresh_v2_catalog', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 2 })
  try {
    await applyV3(pool)
    const inspected = await inspectPocPostgresOwnedSchema(pool)
    assert.deepEqual(inspected, {
      state: 'CURRENT',
      fingerprint: POC_POSTGRES_SCHEMA_FINGERPRINT,
    })
    const snapshot = await catalogSnapshot(pool)
    assert.equal(snapshot.fingerprint, POC_POSTGRES_SCHEMA_FINGERPRINT)
    assert.deepEqual(snapshot.receipts, [
      { scope: POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE, value: exactV2Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_RECEIPT_SCOPE, value: exactV3Receipt, version: '1' },
    ])

    const restart = createObservedPool(pool)
    await initializeActualStore(restart)
    assert.deepEqual(mutatingStatements(restart.trace), [])
    assert.deepEqual(await catalogSnapshot(pool), snapshot)
  } finally {
    await pool.end()
  }
}))

test('actual convergence upgrades exact receipted V1 through V2 to V3 and preserves immutable receipts', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('receipted_v1_upgrade', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 2 })
  try {
    await applyV1(pool)
    assert.deepEqual(await inspectPocPostgresOwnedSchema(pool), {
      state: 'V1_RECEIPT_PENDING',
      fingerprint: POC_POSTGRES_SCHEMA_V1_FINGERPRINT,
    })
    await recordPocPostgresV1SchemaReceipt(pool)
    const before = await catalogSnapshot(pool)
    assert.deepEqual(before.receipts, [{
      scope: POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE,
      value: exactV1Receipt,
      version: '1',
    }])

    const upgrade = createObservedPool(pool)
    await initializeActualStore(upgrade)
    assert.ok(mutatingStatements(upgrade.trace).some((sql) => (
      sql.startsWith('CREATE TABLE IF NOT EXISTS poc_local_security_events')
    )))
    const after = await catalogSnapshot(pool)
    assert.equal(after.fingerprint, POC_POSTGRES_SCHEMA_FINGERPRINT)
    assert.deepEqual(after.receipts, [
      { scope: POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE, value: exactV1Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE, value: exactV2Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_RECEIPT_SCOPE, value: exactV3Receipt, version: '1' },
    ])
    assert.deepEqual(await inspectPocPostgresOwnedSchema(pool), {
      state: 'CURRENT',
      fingerprint: POC_POSTGRES_SCHEMA_FINGERPRINT,
    })

    const restart = createObservedPool(pool)
    await initializeActualStore(restart)
    assert.deepEqual(mutatingStatements(restart.trace), [])
    assert.deepEqual(await catalogSnapshot(pool), after)
  } finally {
    await pool.end()
  }
}))

test('actual convergence upgrades exact receipted V2 to V3 and rolls back a failed V3 receipt', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('receipted_v2_upgrade', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 2 })
  try {
    await applyV2(pool)
    assert.deepEqual(await inspectPocPostgresOwnedSchema(pool), {
      state: 'RECEIPTED_V2',
      fingerprint: POC_POSTGRES_SCHEMA_V2_FINGERPRINT,
    })
    const before = await catalogSnapshot(pool)
    const failed = createObservedPool(pool)
    failed.injectFailure({
      code: 'MCP_V3_RECEIPT_FAILURE',
      message: 'synthetic V3 receipt failure',
      matcher: ({ sql, parameters }) => sql.startsWith('INSERT INTO poc_state')
        && parameters[0] === POC_POSTGRES_SCHEMA_RECEIPT_SCOPE,
    })
    await assert.rejects(initializeActualStore(failed), { code: 'MCP_V3_RECEIPT_FAILURE' })
    assert.equal(failed.trace.at(-1)?.sql, 'ROLLBACK')
    assert.deepEqual(await catalogSnapshot(pool), before)

    const upgrade = createObservedPool(pool)
    await initializeActualStore(upgrade)
    assert.deepEqual((await catalogSnapshot(pool)).receipts, [
      { scope: POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE, value: exactV2Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_RECEIPT_SCOPE, value: exactV3Receipt, version: '1' },
    ])
  } finally {
    await pool.end()
  }
}))

test('PostgreSQL MCP read receipt survives restart, replays once and rejects mutation', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('mcp_receipt_restart', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 2 })
  const receipt = {
    contract: 'DATARIVER_MCP_READ_RECEIPT_V1', receipt_id: '1'.repeat(64),
    service_subject_hash: '2'.repeat(64), actor_subject_hash: '3'.repeat(64),
    workspace_hash: '4'.repeat(64), idempotency_key_hash: '5'.repeat(64),
    request_hash: '6'.repeat(64), authorization_hash: '7'.repeat(64), response_hash: '8'.repeat(64),
    tool_name: 'metadata_search', outcome: 'SUCCEEDED', reason_code: null,
    occurred_at: '2026-08-29T00:00:00.000Z',
  }
  try {
    await applyV3(pool)
    await withSchemaIntegrityRequired(async () => {
      const first = createPocStateStore({ databasePool: pool })
      assert.equal((await first.appendMcpReadReceipt(receipt)).created, true)
      await first.close()
      const restarted = createPocStateStore({ databasePool: pool })
      assert.deepEqual(await restarted.readMcpReadReceipt(receipt.receipt_id), receipt)
      assert.equal((await restarted.appendMcpReadReceipt(receipt)).created, false)
      await restarted.close()
    })
    const scope = `mcp-read-receipt-v1:${receipt.receipt_id}`
    await assert.rejects(pool.query('UPDATE poc_state SET value = value WHERE scope = $1', [scope]))
    await assert.rejects(pool.query('DELETE FROM poc_state WHERE scope = $1', [scope]))
    assert.equal((await pool.query('SELECT count(*)::integer AS count FROM poc_state WHERE scope = $1', [scope])).rows[0].count, 1)
  } finally {
    await pool.end()
  }
}))

test('actual convergence preserves the exact known-older unreceipted predecessor path through V1/V2 to V3', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('known_older_upgrade', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 2 })
  try {
    await applyV1(pool)
    await pool.query(knownOlderCategoryConstraint)
    const before = await catalogSnapshot(pool)
    assert.equal(before.fingerprint, knownOlderFingerprint)
    assert.equal(POC_POSTGRES_MIGRATABLE_FINGERPRINTS.has(before.fingerprint), true)
    assert.deepEqual(before.receipts, [])
    assert.deepEqual(await inspectPocPostgresOwnedSchema(pool), {
      state: 'KNOWN_OLDER_MIGRATABLE',
      fingerprint: knownOlderFingerprint,
    })

    const upgrade = createObservedPool(pool)
    await initializeActualStore(upgrade)
    const v1ReceiptIndex = upgrade.trace.findIndex(({ sql, parameters }) => (
      sql.startsWith('INSERT INTO poc_state')
      && parameters[0] === POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE
    ))
    const v2DdlIndex = upgrade.trace.findIndex(({ sql }) => (
      sql.startsWith('CREATE TABLE IF NOT EXISTS poc_local_security_events')
    ))
    const v2ReceiptIndex = upgrade.trace.findIndex(({ sql, parameters }) => (
      sql.startsWith('INSERT INTO poc_state')
      && parameters[0] === POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE
    ))
    const v3DdlIndex = upgrade.trace.findIndex(({ sql }, index) => (
      index > v2ReceiptIndex && sql.startsWith('CREATE OR REPLACE FUNCTION poc_reject_schema_receipt_mutation')
    ))
    const v3ReceiptIndex = upgrade.trace.findIndex(({ sql, parameters }) => (
      sql.startsWith('INSERT INTO poc_state') && parameters[0] === POC_POSTGRES_SCHEMA_RECEIPT_SCOPE
    ))
    assert.ok(v1ReceiptIndex > 0)
    assert.ok(v2DdlIndex > v1ReceiptIndex)
    assert.ok(v2ReceiptIndex > v2DdlIndex)
    assert.ok(v3DdlIndex > v2ReceiptIndex)
    assert.ok(v3ReceiptIndex > v3DdlIndex)
    const after = await catalogSnapshot(pool)
    assert.equal(after.fingerprint, POC_POSTGRES_SCHEMA_FINGERPRINT)
    assert.deepEqual(after.receipts, [
      { scope: POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE, value: exactV1Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE, value: exactV2Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_RECEIPT_SCOPE, value: exactV3Receipt, version: '1' },
    ])
    assert.deepEqual(await inspectPocPostgresOwnedSchema(pool), {
      state: 'CURRENT',
      fingerprint: POC_POSTGRES_SCHEMA_FINGERPRINT,
    })
  } finally {
    await pool.end()
  }
}))

test('actual catalog convergence fails closed before mutation for missing, malformed, partial, newer and unrecognized receipts', {
  skip: pocPostgresTestSkipReason,
}, async () => {
  const cases = [
    {
      label: 'missing_v1_receipt',
      setup: applyV1,
      code: 'POC_POSTGRES_SCHEMA_INTEGRITY_FAILED',
    },
    {
      label: 'malformed_v1_receipt',
      setup: async (pool) => {
        await applyV1(pool)
        await insertReceipt(pool, POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE, { contract: 'MALFORMED' })
      },
      code: 'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
    },
    {
      label: 'partial_v2',
      setup: async (pool) => {
        await applyV1(pool)
        await recordPocPostgresV1SchemaReceipt(pool)
        await pool.query(v2DdlOnly)
      },
      code: 'POC_POSTGRES_SCHEMA_INTEGRITY_FAILED',
    },
    {
      label: 'newer_receipt',
      setup: async (pool) => {
        await applyV1(pool)
        await insertReceipt(pool, 'product-owned-schema-contract-v4', {
          contract: 'DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V4',
          revision: 4,
          fingerprint: '3'.repeat(64),
        })
      },
      code: 'POC_POSTGRES_SCHEMA_NEWER_UNSUPPORTED',
    },
    {
      label: 'unrecognized_receipt',
      setup: async (pool) => {
        await applyV1(pool)
        await insertReceipt(pool, 'product-owned-schema-contract-vpreview', {
          contract: 'DATARIVER_POC_POSTGRES_OWNED_SCHEMA_PREVIEW',
          revision: 2,
          fingerprint: '4'.repeat(64),
        })
      },
      code: 'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
    },
    {
      label: 'v1_v3_without_v2_receipt',
      setup: async (pool) => {
        await applyV1(pool)
        await recordPocPostgresV1SchemaReceipt(pool)
        await pool.query(v2DdlOnly)
        await pool.query(v3DdlOnly)
        await insertReceipt(pool, POC_POSTGRES_SCHEMA_RECEIPT_SCOPE, exactV3Receipt)
      },
      code: 'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
    },
    {
      label: 'v1_schema_with_v3_receipt',
      setup: async (pool) => {
        await applyV1(pool)
        await recordPocPostgresV1SchemaReceipt(pool)
        await insertReceipt(pool, POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE, exactV2Receipt)
        await insertReceipt(pool, POC_POSTGRES_SCHEMA_RECEIPT_SCOPE, exactV3Receipt)
      },
      code: 'POC_POSTGRES_SCHEMA_INTEGRITY_FAILED',
    },
    {
      label: 'known_older_with_v3_receipt',
      setup: async (pool) => {
        await applyV1(pool)
        await pool.query(knownOlderCategoryConstraint)
        await insertReceipt(pool, POC_POSTGRES_SCHEMA_RECEIPT_SCOPE, exactV3Receipt)
      },
      code: 'POC_POSTGRES_SCHEMA_INTEGRITY_FAILED',
    },
  ]

  for (const scenario of cases) {
    await withDisposablePocPostgres(scenario.label, async ({ connectionString }) => {
      const pool = new Pool({ connectionString, max: 2 })
      try {
        await scenario.setup(pool)
        const before = await catalogSnapshot(pool)
        const observed = createObservedPool(pool)
        await assert.rejects(initializeActualStore(observed), { code: scenario.code })
        assert.deepEqual(mutatingStatements(observed.trace), [])
        assert.equal(observed.trace.at(-1)?.sql, 'ROLLBACK')
        assert.deepEqual(await catalogSnapshot(pool), before)
      } finally {
        await pool.end()
      }
    })
  }
})

test('actual V1 transaction is restored exactly after injected V2 DDL or receipt failure', {
  skip: pocPostgresTestSkipReason,
}, async () => {
  const failures = [
    {
      label: 'v2_ddl_failure',
      code: 'AC01_V2_DDL_FAILURE',
      message: 'synthetic V2 DDL failure',
      matcher: ({ sql }) => sql.startsWith('CREATE TABLE IF NOT EXISTS poc_local_security_events'),
    },
    {
      label: 'v2_receipt_failure',
      code: 'AC01_V2_RECEIPT_FAILURE',
      message: 'synthetic V2 receipt failure',
      matcher: ({ sql, parameters }) => (
        sql.startsWith('INSERT INTO poc_state')
        && parameters[0] === POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE
      ),
    },
  ]

  for (const failure of failures) {
    await withDisposablePocPostgres(failure.label, async ({ connectionString }) => {
      const pool = new Pool({ connectionString, max: 2 })
      try {
        await applyV1(pool)
        await recordPocPostgresV1SchemaReceipt(pool)
        const before = await catalogSnapshot(pool)
        assert.equal(before.fingerprint, POC_POSTGRES_SCHEMA_V1_FINGERPRINT)
        assert.deepEqual(before.receipts, [{
          scope: POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE,
          value: exactV1Receipt,
          version: '1',
        }])

        const observed = createObservedPool(pool)
        observed.injectFailure(failure)
        await assert.rejects(initializeActualStore(observed), { code: failure.code })
        assert.equal(observed.trace.at(-1)?.sql, 'ROLLBACK')
        assert.ok(observed.trace.some(failure.matcher))
        if (failure.code === 'AC01_V2_RECEIPT_FAILURE') {
          const ddlIndex = observed.trace.findIndex(({ sql }) => (
            sql.startsWith('CREATE TABLE IF NOT EXISTS poc_local_security_events')
          ))
          const receiptIndex = observed.trace.findIndex(failure.matcher)
          assert.ok(ddlIndex > 0)
          assert.ok(receiptIndex > ddlIndex)
        }
        assert.deepEqual(await catalogSnapshot(pool), before)
        assert.equal((await pool.query(
          "SELECT to_regclass('public.poc_local_security_events') AS relation",
        )).rows[0].relation, null)
        assert.deepEqual(await inspectPocPostgresOwnedSchema(pool), {
          state: 'RECEIPTED_V1',
          fingerprint: POC_POSTGRES_SCHEMA_V1_FINGERPRINT,
        })
      } finally {
        await pool.end()
      }
    })
  }
})
