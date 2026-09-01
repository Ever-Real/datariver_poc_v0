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
  POC_POSTGRES_SCHEMA_V3_CONTRACT,
  POC_POSTGRES_SCHEMA_V3_FINGERPRINT,
  POC_POSTGRES_SCHEMA_V3_RECEIPT_SCOPE,
  POC_POSTGRES_SCHEMA_V3_REVISION,
  POC_POSTGRES_SCHEMA_V4_CONTRACT,
  POC_POSTGRES_SCHEMA_V4_FINGERPRINT,
  POC_POSTGRES_SCHEMA_V4_RECEIPT_SCOPE,
  POC_POSTGRES_SCHEMA_V4_REVISION,
  POC_POSTGRES_SCHEMA_V5_CONTRACT,
  POC_POSTGRES_SCHEMA_V5_FINGERPRINT,
  POC_POSTGRES_SCHEMA_V5_RECEIPT_SCOPE,
  POC_POSTGRES_SCHEMA_V5_REVISION,
  POC_POSTGRES_SCHEMA_V6_CONTRACT,
  POC_POSTGRES_SCHEMA_V6_FINGERPRINT,
  POC_POSTGRES_SCHEMA_V6_RECEIPT_SCOPE,
  POC_POSTGRES_SCHEMA_V6_REVISION,
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
  '006-poc-local-credential-provision-audit.sql',
  '007-poc-chat-discovery.sql',
]
const v6MigrationName = '008-poc-k9-lifecycle-v2.sql'
const v7MigrationName = '009-poc-change-history-retention-gap.sql'
const migrations = new Map([...migrationNames, v6MigrationName, v7MigrationName].map((name) => [
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
  contract: POC_POSTGRES_SCHEMA_V3_CONTRACT,
  revision: POC_POSTGRES_SCHEMA_V3_REVISION,
  fingerprint: POC_POSTGRES_SCHEMA_V3_FINGERPRINT,
})
const exactV4Receipt = expectedReceipt({
  contract: POC_POSTGRES_SCHEMA_V4_CONTRACT,
  revision: POC_POSTGRES_SCHEMA_V4_REVISION,
  fingerprint: POC_POSTGRES_SCHEMA_V4_FINGERPRINT,
})
const exactV5Receipt = expectedReceipt({
  contract: POC_POSTGRES_SCHEMA_V5_CONTRACT,
  revision: POC_POSTGRES_SCHEMA_V5_REVISION,
  fingerprint: POC_POSTGRES_SCHEMA_V5_FINGERPRINT,
})
const exactV6Receipt = expectedReceipt({
  contract: POC_POSTGRES_SCHEMA_V6_CONTRACT,
  revision: POC_POSTGRES_SCHEMA_V6_REVISION,
  fingerprint: POC_POSTGRES_SCHEMA_V6_FINGERPRINT,
})
const exactV7Receipt = expectedReceipt({
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
  await applyMigrations(pool, migrationNames.slice(0, 5))
}

async function applyV4(pool) {
  await applyMigrations(pool, migrationNames.slice(0, 6))
}

async function applyV5(pool) {
  await applyMigrations(pool, migrationNames)
}

async function applyV6(pool) {
  await applyMigrations(pool, [...migrationNames, v6MigrationName])
}

async function applyV7(pool) {
  await applyMigrations(pool, [...migrationNames, v6MigrationName, v7MigrationName])
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

const legacyRuntimeScopes = [
  ['catalog-inventory-v1:4cb18532b26324b7', 42],
  ['change-history-access-v1', 3],
  ['change-history-capture-status-v1', 4],
  ['change-history-runtime-status-v1', 24],
  ['core', 6],
  ['k0-scheduler-v1:datariver:poc:k9-scheduler:v1', 12],
  ['mcl-discovery-v1', 8],
]

async function seedExactPreReceiptV1Rows(pool) {
  for (const [scope, version] of legacyRuntimeScopes) {
    await pool.query(
      'INSERT INTO poc_state (scope, value, version) VALUES ($1, $2::jsonb, $3)',
      [scope, JSON.stringify({ legacy_marker: scope }), version],
    )
  }
  await pool.query(`
    INSERT INTO poc_catalog_embedding (
      binding_hash, asset_urn, source_hash, source_generation,
      content_text, metadata, embedding
    ) VALUES (
      repeat('1', 64), 'urn:li:dataset:(urn:li:dataPlatform:postgres,legacy.table,PROD)',
      repeat('2', 64), repeat('3', 64), 'legacy catalog content',
      '{"legacy":true}'::jsonb, '[0.1,0.2]'::vector
    )
  `)
  await pool.query(`
    INSERT INTO poc_local_credentials (
      subject_id, username_normalized, password_hash, version
    ) VALUES (
      'legacy-subject', 'legacy@example.com',
      '$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$dmVyaWZpZXI', 9
    )
  `)
  await pool.query(`
    INSERT INTO poc_local_sessions (
      token_hash, subject_id, created_at, expires_at
    ) VALUES (
      repeat('4', 64), 'legacy-subject',
      '2026-08-01T00:00:00Z', '2026-09-01T00:00:00Z'
    )
  `)
  await pool.query(`
    INSERT INTO poc_user_table_grants (
      subject_id, table_urn, version, created_by, updated_by
    ) VALUES (
      'legacy-subject',
      'urn:li:dataset:(urn:li:dataPlatform:postgres,legacy.table,PROD)',
      7, 'legacy-admin', 'legacy-admin'
    )
  `)
  await pool.query(`
    INSERT INTO poc_chat_sessions (
      session_id, owner_subject_id, title, version
    ) VALUES ('legacy-chat', 'legacy-subject', 'Legacy chat', 5)
  `)
  await pool.query(`
    INSERT INTO poc_chat_messages (
      message_id, session_id, owner_subject_id, ordinal, role, content,
      evidence_json, route_json, workflow_json
    ) VALUES (
      'legacy-message', 'legacy-chat', 'legacy-subject', 1, 'user',
      'legacy question', '[]'::jsonb, '{"route":"legacy"}'::jsonb, '[]'::jsonb
    )
  `)
  await pool.query(`
    INSERT INTO poc_change_history_sources (
      source_identity_hash, provider_name, provider_version, schema_contract_hash
    ) VALUES (repeat('5', 64), 'legacy-provider', '1', repeat('6', 64))
  `)
  await pool.query(`
    INSERT INTO poc_change_history_ledger_events (
      event_identity, event_hash, source_identity_hash, source_event_identity,
      normalized_change_transaction_id, deterministic_ordinal, topic_contract,
      source_partition, source_offset, asset_urn, normalized_entity_key,
      category, source_aspect, operation, detected_at
    ) VALUES (
      repeat('7', 64), repeat('8', 64), repeat('5', 64), repeat('9', 64),
      repeat('a', 64), 0, 'legacy-topic-v1', 0, 1,
      'urn:li:dataset:(urn:li:dataPlatform:postgres,legacy.table,PROD)',
      'legacy.table', 'TECHNICAL_SCHEMA', 'schemaMetadata', 'UPDATE',
      '2026-08-01T00:00:00Z'
    )
  `)
  await pool.query(`
    INSERT INTO poc_k9_managed_graph_policies (
      graph_id, name, status, classification, ontology_version_id,
      studio_release_id, publication_version, schedule, managed_intent,
      accepted_proposal_id, subject_id, workspace_id, policy_hash, tbox_hash,
      contract_hash, proposal_hash, source_hash, mapping_hash, created_at, updated_at
    ) VALUES (
      '11111111-1111-4111-8111-111111111111', 'Legacy graph', 'ACTIVE', 'INTERNAL',
      '22222222-2222-4222-8222-222222222222',
      '33333333-3333-4333-8333-333333333333', 1, '0 0 * * *',
      'LEGACY_METADATA', 'legacy-proposal', 'legacy-subject', 'legacy-workspace',
      repeat('b', 64), repeat('c', 64), repeat('d', 64), repeat('e', 64),
      repeat('f', 64), repeat('0', 64),
      '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z'
    )
  `)
  await pool.query(`
    INSERT INTO poc_k9_refresh_runs (
      run_id, graph_id, status, policy_hash, started_at
    ) VALUES (
      '44444444-4444-4444-8444-444444444444',
      '11111111-1111-4111-8111-111111111111', 'PREPARING', repeat('b', 64),
      '2026-08-01T00:00:00Z'
    )
  `)
}

async function preservedLegacyRows(pool) {
  const queries = {
    state: pool.query(`
      SELECT scope, value, version::text FROM poc_state
      WHERE scope = ANY($1::text[]) ORDER BY scope
    `, [legacyRuntimeScopes.map(([scope]) => scope)]),
    catalog: pool.query(`
      SELECT binding_hash, asset_urn, source_hash, source_generation,
        content_text, metadata, embedding::text
      FROM poc_catalog_embedding ORDER BY binding_hash, asset_urn
    `),
    credentials: pool.query(`
      SELECT subject_id, username_normalized, password_hash, login_enabled,
        must_change_password, failed_attempts, locked_until, version::text
      FROM poc_local_credentials ORDER BY subject_id
    `),
    sessions: pool.query(`
      SELECT token_hash, subject_id, created_at, expires_at, revoked_at
      FROM poc_local_sessions ORDER BY token_hash
    `),
    grants: pool.query(`
      SELECT subject_id, table_urn, active, version::text, created_by, updated_by
      FROM poc_user_table_grants ORDER BY subject_id, table_urn
    `),
    chatSessions: pool.query(`
      SELECT session_id, owner_subject_id, title, is_favorite, archived, version::text
      FROM poc_chat_sessions ORDER BY session_id
    `),
    chatMessages: pool.query(`
      SELECT message_id, session_id, owner_subject_id, ordinal::text, role,
        content, evidence_json, route_json, workflow_json
      FROM poc_chat_messages ORDER BY message_id
    `),
    changeSources: pool.query(`
      SELECT source_identity_hash, provider_name, provider_version, schema_contract_hash
      FROM poc_change_history_sources ORDER BY source_identity_hash
    `),
    changeEvents: pool.query(`
      SELECT event_identity, event_hash, source_identity_hash, source_event_identity,
        normalized_change_transaction_id, deterministic_ordinal, topic_contract,
        source_partition, source_offset::text, asset_urn, normalized_entity_key,
        category, source_aspect, operation
      FROM poc_change_history_ledger_events ORDER BY event_identity
    `),
    k9Policies: pool.query(`
      SELECT graph_id, status, policy_hash, active_release_pointer
      FROM poc_k9_managed_graph_policies ORDER BY graph_id
    `),
    k9Runs: pool.query(`
      SELECT run_id, graph_id, status, policy_hash, active_release_pointer
      FROM poc_k9_refresh_runs ORDER BY run_id
    `),
  }
  return Object.fromEntries(await Promise.all(Object.entries(queries).map(
    async ([key, query]) => [key, (await query).rows],
  )))
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

test('fresh immutable V5 migrations converge through V6 to V7 and then restart without mutation', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('fresh_v2_catalog', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 2 })
  try {
    await applyV5(pool)
    const inspected = await inspectPocPostgresOwnedSchema(pool)
    assert.deepEqual(inspected, {
      state: 'RECEIPTED_V5',
      fingerprint: POC_POSTGRES_SCHEMA_V5_FINGERPRINT,
    })
    const before = await catalogSnapshot(pool)
    assert.equal(before.fingerprint, POC_POSTGRES_SCHEMA_V5_FINGERPRINT)
    assert.deepEqual(before.receipts, [
      { scope: POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE, value: exactV2Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V3_RECEIPT_SCOPE, value: exactV3Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V4_RECEIPT_SCOPE, value: exactV4Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V5_RECEIPT_SCOPE, value: exactV5Receipt, version: '1' },
    ])

    const upgrade = createObservedPool(pool)
    await initializeActualStore(upgrade)
    assert.ok(mutatingStatements(upgrade.trace).some((sql) => (
      sql.startsWith('CREATE TABLE IF NOT EXISTS poc_k9_source_snapshots_v2')
    )))
    assert.ok(mutatingStatements(upgrade.trace).some((sql) => (
      sql.startsWith('CREATE TABLE IF NOT EXISTS poc_change_history_gap_receipts')
    )))
    const snapshot = await catalogSnapshot(pool)
    assert.equal(snapshot.fingerprint, POC_POSTGRES_SCHEMA_FINGERPRINT)
    assert.deepEqual(snapshot.receipts, [
      ...before.receipts,
      { scope: POC_POSTGRES_SCHEMA_V6_RECEIPT_SCOPE, value: exactV6Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_RECEIPT_SCOPE, value: exactV7Receipt, version: '1' },
    ])
    const restart = createObservedPool(pool)
    await initializeActualStore(restart)
    assert.deepEqual(mutatingStatements(restart.trace), [])
    assert.deepEqual(await catalogSnapshot(pool), snapshot)
  } finally {
    await pool.end()
  }
}))

test('canonical V7 migration matches runtime DDL, receipt and preserved Chat column ordinals', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('canonical_v6_catalog', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 2 })
  try {
    await applyV7(pool)
    assert.deepEqual(await inspectPocPostgresOwnedSchema(pool), {
      state: 'CURRENT', fingerprint: POC_POSTGRES_SCHEMA_FINGERPRINT,
    })
    const columns = await pool.query(`
      SELECT ordinal_position, column_name
      FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = 'poc_chat_messages'
      ORDER BY ordinal_position
    `)
    assert.deepEqual(columns.rows.slice(6), [
      { ordinal_position: 7, column_name: 'evidence_json' },
      { ordinal_position: 8, column_name: 'route_json' },
      { ordinal_position: 9, column_name: 'workflow_json' },
      { ordinal_position: 10, column_name: 'created_at' },
      { ordinal_position: 11, column_name: 'discovery_json' },
    ])
    const before = await catalogSnapshot(pool)
    const restart = createObservedPool(pool)
    await initializeActualStore(restart)
    assert.deepEqual(mutatingStatements(restart.trace), [])
    assert.deepEqual(await catalogSnapshot(pool), before)
  } finally {
    await pool.end()
  }
}))

test('actual PREP-shaped V6 history gap migrates to V7, preserves 357 events and replays once', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('v6_retention_gap_upgrade', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 2 })
  const sourceHash = 'a'.repeat(64)
  const schemaHash = 'b'.repeat(64)
  const topic = 'MetadataChangeLog_Versioned_v1'
  try {
    await applyV6(pool)
    assert.deepEqual(await inspectPocPostgresOwnedSchema(pool), {
      state: 'RECEIPTED_V6', fingerprint: POC_POSTGRES_SCHEMA_V6_FINGERPRINT,
    })
    await pool.query(`
      INSERT INTO poc_change_history_sources (
        source_identity_hash, provider_name, provider_version, schema_contract_hash
      ) VALUES ($1, 'DataHub', 'v1.6.0rc1', $2)
    `, [sourceHash, schemaHash])
    await pool.query(`
      INSERT INTO poc_change_history_ledger_events (
        event_identity, event_hash, source_identity_hash, source_event_identity,
        normalized_change_transaction_id, deterministic_ordinal, topic_contract,
        source_partition, source_offset, asset_urn, normalized_entity_key,
        category, source_aspect, operation, detected_at
      )
      SELECT
        repeat(md5('event-' || item), 2), repeat(md5('hash-' || item), 2), $1,
        repeat(md5('source-' || item), 2), repeat(md5('transaction-' || item), 2),
        0, $2, 0, item - 1,
        'urn:li:dataset:(urn:li:dataPlatform:postgres,synthetic.table,PROD)',
        'synthetic.table', 'TECHNICAL_SCHEMA', 'schemaMetadata', 'UPDATE',
        '2026-09-01T00:00:00.000Z'::timestamptz
      FROM generate_series(1, 357) AS item
    `, [sourceHash, topic])
    await pool.query(`
      INSERT INTO poc_change_history_checkpoints (
        source_identity_hash, topic_contract, source_partition,
        first_exact_offset, next_offset, last_contiguous_event_identity,
        last_captured_at, version
      ) VALUES ($1, $2, 0, 0, 357, repeat(md5('event-357'), 2),
        '2026-09-01T00:00:00.000Z', 358)
    `, [sourceHash, topic])

    await withSchemaIntegrityRequired(async () => {
      const store = createPocStateStore({ databasePool: pool })
      const command = {
        sourceIdentityHash: sourceHash,
        topicContract: topic,
        partition: 0,
        previousNextOffset: 357,
        lowWatermark: 400,
        highWatermark: 500,
        observedAt: '2026-09-01T01:00:00.000Z',
      }
      const first = await store.recordChangeHistoryRetentionGapAndAdvanceBoundary(command)
      const replay = await store.recordChangeHistoryRetentionGapAndAdvanceBoundary(command)
      assert.equal(first.replayed, false)
      assert.equal(replay.replayed, true)
      assert.equal(replay.receiptId, first.receiptId)
      await store.close()
    })

    assert.deepEqual(await inspectPocPostgresOwnedSchema(pool), {
      state: 'CURRENT', fingerprint: POC_POSTGRES_SCHEMA_FINGERPRINT,
    })
    assert.equal((await pool.query(
      'SELECT count(*)::integer AS count FROM poc_change_history_ledger_events',
    )).rows[0].count, 357)
    assert.equal((await pool.query(
      'SELECT count(*)::integer AS count FROM poc_change_history_gap_receipts',
    )).rows[0].count, 1)
    assert.equal(Number((await pool.query(
      'SELECT next_offset FROM poc_change_history_checkpoints WHERE source_identity_hash = $1',
      [sourceHash],
    )).rows[0].next_offset), 400)
  } finally {
    await pool.end()
  }
}))

test('PostgreSQL constraint fingerprint casts internal char before text concatenation', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('constraint_contype_text_cast', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 2 })
  try {
    await applyV5(pool)
    const uncastStatement = `
      SELECT conrelid::regclass::text || '|' ||
        conname || '|' ||
        contype || '|' ||
        pg_get_constraintdef(oid, true) AS fingerprint_row
      FROM pg_catalog.pg_constraint
      WHERE conrelid = 'poc_state'::regclass
      ORDER BY conname
    `
    await assert.rejects(pool.query(uncastStatement), (error) => (
      error?.code === '42725'
      && /operator is not unique: text \|\| "char"/.test(error.message)
    ))

    const castStatement = uncastStatement.replace('contype ||', 'contype::text ||')
    const first = await pool.query(castStatement)
    const second = await pool.query(castStatement)
    assert.deepEqual(first.rows, [{
      fingerprint_row: 'poc_state|poc_state_pkey|p|PRIMARY KEY (scope)',
    }])
    assert.deepEqual(second.rows, first.rows)

    const snapshot = await catalogSnapshot(pool)
    assert.equal(snapshot.fingerprint, POC_POSTGRES_SCHEMA_V5_FINGERPRINT)
  } finally {
    await pool.end()
  }
}))

test('exact canonical pre-receipt V1 migrates transactionally to V7 and preserves runtime rows', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('pre_receipt_v1_upgrade', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 2 })
  try {
    await applyV1(pool)
    assert.deepEqual(await inspectPocPostgresOwnedSchema(pool), {
      state: 'V1_RECEIPT_PENDING',
      fingerprint: POC_POSTGRES_SCHEMA_V1_FINGERPRINT,
    })
    await seedExactPreReceiptV1Rows(pool)
    const beforeRows = await preservedLegacyRows(pool)

    const upgrade = createObservedPool(pool)
    await initializeActualStore(upgrade)
    const v1ReceiptIndex = upgrade.trace.findIndex(({ sql, parameters }) => (
      sql.startsWith('INSERT INTO poc_state')
      && parameters[0] === POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE
    ))
    const v2DdlIndex = upgrade.trace.findIndex(({ sql }) => (
      sql.startsWith('CREATE TABLE IF NOT EXISTS poc_local_security_events')
    ))
    assert.ok(v1ReceiptIndex > 0)
    assert.ok(v2DdlIndex > v1ReceiptIndex)

    const after = await catalogSnapshot(pool)
    assert.equal(after.fingerprint, POC_POSTGRES_SCHEMA_FINGERPRINT)
    assert.deepEqual(Object.fromEntries([
      'TABLE', 'COLUMN', 'CONSTRAINT', 'INDEX', 'TRIGGER', 'FUNCTION', 'TYPE',
    ].map((kind) => [kind, after.rows.filter((row) => row.kind === kind).length])), {
      TABLE: 25,
      COLUMN: 252,
      CONSTRAINT: 142,
      INDEX: 54,
      TRIGGER: 12,
      FUNCTION: 4,
      TYPE: 0,
    })
    assert.deepEqual(after.rows.filter((row) => row.kind === 'TRIGGER').map(({ identity }) => identity), [
      'poc_change_history_cr_link_events.trg_poc_change_history_cr_link_append_only',
      'poc_change_history_gap_receipts.trg_poc_change_history_gap_receipt_append_only',
      'poc_change_history_ledger_events.trg_poc_change_history_ledger_append_only',
      'poc_k9_projector_receipts_v2.trg_poc_k9_projector_receipts_v2_immutable',
      'poc_k9_semantic_batches_v2.trg_poc_k9_semantic_batches_v2_immutable',
      'poc_k9_semantic_desired_documents_v2.trg_poc_k9_semantic_desired_documents_v2_immutable',
      'poc_k9_semantic_manifests_v2.trg_poc_k9_semantic_manifests_v2_immutable',
      'poc_k9_semantic_staging_v2.trg_poc_k9_semantic_staging_v2_immutable',
      'poc_k9_source_payloads_v2.trg_poc_k9_source_payloads_v2_immutable',
      'poc_k9_source_snapshots_v2.trg_poc_k9_source_snapshots_v2_immutable',
      'poc_local_security_events.trg_poc_local_security_events_append_only',
      'poc_state.trg_poc_state_schema_receipts_immutable',
    ])
    assert.deepEqual(after.rows.filter((row) => row.kind === 'FUNCTION').map(({ identity }) => identity), [
      'poc_reject_change_history_mutation()',
      'poc_reject_k9_lifecycle_payload_mutation()',
      'poc_reject_local_security_event_mutation()',
      'poc_reject_schema_receipt_mutation()',
    ])
    assert.deepEqual(after.receipts, [
      { scope: POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE, value: exactV1Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE, value: exactV2Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V3_RECEIPT_SCOPE, value: exactV3Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V4_RECEIPT_SCOPE, value: exactV4Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V5_RECEIPT_SCOPE, value: exactV5Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V6_RECEIPT_SCOPE, value: exactV6Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_RECEIPT_SCOPE, value: exactV7Receipt, version: '1' },
    ])
    assert.deepEqual(await preservedLegacyRows(pool), beforeRows)
    assert.equal((await pool.query(
      'SELECT discovery_json FROM poc_chat_messages WHERE message_id = $1',
      ['legacy-message'],
    )).rows[0]?.discovery_json, null)
    assert.equal((await pool.query(
      'SELECT count(*)::integer AS count FROM poc_local_security_events',
    )).rows[0]?.count, 0)

    const restart = createObservedPool(pool)
    await initializeActualStore(restart)
    assert.deepEqual(mutatingStatements(restart.trace), [])
    assert.deepEqual(await catalogSnapshot(pool), after)
    assert.deepEqual(await preservedLegacyRows(pool), beforeRows)
  } finally {
    await pool.end()
  }
}))

test('pre-receipt V1 receipt failure rolls back without schema or row mutation', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('pre_receipt_v1_rollback', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 2 })
  try {
    await applyV1(pool)
    await seedExactPreReceiptV1Rows(pool)
    const beforeCatalog = await catalogSnapshot(pool)
    const beforeRows = await preservedLegacyRows(pool)
    const failed = createObservedPool(pool)
    failed.injectFailure({
      code: 'LEGACY_V1_RECEIPT_FAILURE',
      message: 'synthetic pre-receipt V1 failure',
      matcher: ({ sql, parameters }) => sql.startsWith('INSERT INTO poc_state')
        && parameters[0] === POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE,
    })
    await assert.rejects(initializeActualStore(failed), { code: 'LEGACY_V1_RECEIPT_FAILURE' })
    assert.equal(failed.trace.at(-1)?.sql, 'ROLLBACK')
    assert.deepEqual(await catalogSnapshot(pool), beforeCatalog)
    assert.deepEqual(await preservedLegacyRows(pool), beforeRows)
    assert.equal((await pool.query(
      "SELECT to_regclass('public.poc_local_security_events') AS relation",
    )).rows[0]?.relation, null)
  } finally {
    await pool.end()
  }
}))

test('actual convergence upgrades exact receipted V1 through V7 and preserves immutable receipts', {
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
      { scope: POC_POSTGRES_SCHEMA_V3_RECEIPT_SCOPE, value: exactV3Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V4_RECEIPT_SCOPE, value: exactV4Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V5_RECEIPT_SCOPE, value: exactV5Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V6_RECEIPT_SCOPE, value: exactV6Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_RECEIPT_SCOPE, value: exactV7Receipt, version: '1' },
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

test('actual convergence upgrades exact receipted V2 through V7 and rolls back a failed intermediate receipt', {
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
        && parameters[0] === POC_POSTGRES_SCHEMA_V3_RECEIPT_SCOPE,
    })
    await assert.rejects(initializeActualStore(failed), { code: 'MCP_V3_RECEIPT_FAILURE' })
    assert.equal(failed.trace.at(-1)?.sql, 'ROLLBACK')
    assert.deepEqual(await catalogSnapshot(pool), before)

    const upgrade = createObservedPool(pool)
    await initializeActualStore(upgrade)
    assert.deepEqual((await catalogSnapshot(pool)).receipts, [
      { scope: POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE, value: exactV2Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V3_RECEIPT_SCOPE, value: exactV3Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V4_RECEIPT_SCOPE, value: exactV4Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V5_RECEIPT_SCOPE, value: exactV5Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V6_RECEIPT_SCOPE, value: exactV6Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_RECEIPT_SCOPE, value: exactV7Receipt, version: '1' },
    ])
  } finally {
    await pool.end()
  }
}))

test('actual convergence upgrades the accepted receipted V3 catalog through V7 without replacing ancestry', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('receipted_v3_upgrade', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 2 })
  try {
    await applyV3(pool)
    assert.deepEqual(await inspectPocPostgresOwnedSchema(pool), {
      state: 'RECEIPTED_V3',
      fingerprint: POC_POSTGRES_SCHEMA_V3_FINGERPRINT,
    })
    const upgrade = createObservedPool(pool)
    await initializeActualStore(upgrade)
    assert.ok(upgrade.trace.some(({ sql }) => sql.startsWith('DO $block$')))
    assert.deepEqual((await catalogSnapshot(pool)).receipts, [
      { scope: POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE, value: exactV2Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V3_RECEIPT_SCOPE, value: exactV3Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V4_RECEIPT_SCOPE, value: exactV4Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V5_RECEIPT_SCOPE, value: exactV5Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V6_RECEIPT_SCOPE, value: exactV6Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_RECEIPT_SCOPE, value: exactV7Receipt, version: '1' },
    ])
    assert.deepEqual(await inspectPocPostgresOwnedSchema(pool), {
      state: 'CURRENT',
      fingerprint: POC_POSTGRES_SCHEMA_FINGERPRINT,
    })
  } finally {
    await pool.end()
  }
}))

test('actual convergence adds Chat discovery only after accepting the exact V4 receipt', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('receipted_v4_chat_discovery_upgrade', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 2 })
  try {
    await applyV4(pool)
    assert.deepEqual(await inspectPocPostgresOwnedSchema(pool), {
      state: 'RECEIPTED_V4',
      fingerprint: POC_POSTGRES_SCHEMA_V4_FINGERPRINT,
    })
    const upgrade = createObservedPool(pool)
    await initializeActualStore(upgrade)
    assert.ok(upgrade.trace.some(({ sql }) => sql.startsWith('ALTER TABLE poc_chat_messages')))
    const columns = await pool.query(`
      SELECT column_name FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = 'poc_chat_messages'
      ORDER BY ordinal_position
    `)
    assert.equal(columns.rows.some((row) => row.column_name === 'discovery_json'), true)
    assert.deepEqual(await inspectPocPostgresOwnedSchema(pool), {
      state: 'CURRENT',
      fingerprint: POC_POSTGRES_SCHEMA_FINGERPRINT,
    })
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

test('actual convergence preserves the exact known-older path through V1 to V7', {
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
      sql.startsWith('INSERT INTO poc_state') && parameters[0] === POC_POSTGRES_SCHEMA_V3_RECEIPT_SCOPE
    ))
    const v4DdlIndex = upgrade.trace.findIndex(({ sql }, index) => (
      index > v3ReceiptIndex && sql.startsWith('DO $block$')
    ))
    const v4ReceiptIndex = upgrade.trace.findIndex(({ sql, parameters }) => (
      sql.startsWith('INSERT INTO poc_state') && parameters[0] === POC_POSTGRES_SCHEMA_V4_RECEIPT_SCOPE
    ))
    const v5DdlIndex = upgrade.trace.findIndex(({ sql }, index) => (
      index > v4ReceiptIndex && sql.startsWith('ALTER TABLE poc_chat_messages')
    ))
    const v5ReceiptIndex = upgrade.trace.findIndex(({ sql, parameters }) => (
      sql.startsWith('INSERT INTO poc_state') && parameters[0] === POC_POSTGRES_SCHEMA_V5_RECEIPT_SCOPE
    ))
    assert.ok(v1ReceiptIndex > 0)
    assert.ok(v2DdlIndex > v1ReceiptIndex)
    assert.ok(v2ReceiptIndex > v2DdlIndex)
    assert.ok(v3DdlIndex > v2ReceiptIndex)
    assert.ok(v3ReceiptIndex > v3DdlIndex)
    assert.ok(v4DdlIndex > v3ReceiptIndex)
    assert.ok(v4ReceiptIndex > v4DdlIndex)
    assert.ok(v5DdlIndex > v4ReceiptIndex)
    assert.ok(v5ReceiptIndex > v5DdlIndex)
    const after = await catalogSnapshot(pool)
    assert.equal(after.fingerprint, POC_POSTGRES_SCHEMA_FINGERPRINT)
    assert.deepEqual(after.receipts, [
      { scope: POC_POSTGRES_SCHEMA_V1_RECEIPT_SCOPE, value: exactV1Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE, value: exactV2Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V3_RECEIPT_SCOPE, value: exactV3Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V4_RECEIPT_SCOPE, value: exactV4Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V5_RECEIPT_SCOPE, value: exactV5Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_V6_RECEIPT_SCOPE, value: exactV6Receipt, version: '1' },
      { scope: POC_POSTGRES_SCHEMA_RECEIPT_SCOPE, value: exactV7Receipt, version: '1' },
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
        await insertReceipt(pool, 'product-owned-schema-contract-v8', {
          contract: 'DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V8',
          revision: 8,
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
        await insertReceipt(pool, POC_POSTGRES_SCHEMA_V3_RECEIPT_SCOPE, exactV3Receipt)
      },
      code: 'POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH',
    },
    {
      label: 'v1_schema_with_v3_receipt',
      setup: async (pool) => {
        await applyV1(pool)
        await recordPocPostgresV1SchemaReceipt(pool)
        await insertReceipt(pool, POC_POSTGRES_SCHEMA_V2_RECEIPT_SCOPE, exactV2Receipt)
        await insertReceipt(pool, POC_POSTGRES_SCHEMA_V3_RECEIPT_SCOPE, exactV3Receipt)
      },
      code: 'POC_POSTGRES_SCHEMA_INTEGRITY_FAILED',
    },
    {
      label: 'known_older_with_v3_receipt',
      setup: async (pool) => {
        await applyV1(pool)
        await pool.query(knownOlderCategoryConstraint)
        await insertReceipt(pool, POC_POSTGRES_SCHEMA_V3_RECEIPT_SCOPE, exactV3Receipt)
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
