import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import process from 'node:process'
import test from 'node:test'
import { URL } from 'node:url'

import { createPocStateStore } from './poc-state-store.mjs'

const SOURCE_HASH = 'a'.repeat(64)
const SCHEMA_HASH = 'b'.repeat(64)
const POLICY_HASH = 'c'.repeat(64)
const BASIS_HASH = 'd'.repeat(64)

async function withEnvironment(values, action) {
  const previous = new Map(Object.keys(values).map((key) => [key, process.env[key]]))
  try {
    for (const [key, value] of Object.entries(values)) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
    return await action()
  } finally {
    for (const [key, value] of previous) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
  }
}

function capture(offset, events = [semanticEvent()]) {
  return {
    sourceIdentityHash: SOURCE_HASH,
    providerName: 'DataHub',
    providerVersion: 'contract-test',
    schemaContractHash: SCHEMA_HASH,
    topicContract: 'MetadataChangeLog_Versioned_v1',
    partition: 2,
    offset,
    events,
  }
}

function semanticEvent(overrides = {}) {
  return {
    assetUrn: 'urn:li:dataset:(urn:li:dataPlatform:postgres,db.schema.table,PROD)',
    entityKey: 'db.schema.table.column',
    category: 'TECHNICAL_SCHEMA',
    sourceAspect: 'schemaMetadata',
    operation: 'UPDATE',
    beforeData: { field_type: 'string', nullable: true },
    afterData: { field_type: 'integer', nullable: false },
    actorRef: 'urn:li:corpuser:test',
    sourceOccurredAt: '2026-08-13T15:00:00.000Z',
    detectedAt: '2026-08-13T15:00:01.000Z',
    ...overrides,
  }
}

function createDatabaseDouble({ failCheckpointInsertPartition } = {}) {
  const statements = []
  const sources = new Map()
  const checkpoints = new Map()
  const ledger = new Map()
  const links = []
  let failNextLedgerInsert = false
  let transactionSnapshot = null

  const restoreMap = (target, snapshot) => {
    target.clear()
    for (const [key, value] of snapshot) target.set(key, value)
  }

  const checkpointKey = (parameters) => parameters.slice(0, 3).join(':')
  const client = {
    async query(sql, parameters = []) {
      const normalized = String(sql).replace(/\s+/g, ' ').trim()
      statements.push({ sql: normalized, parameters })
      if (normalized === 'BEGIN') {
        transactionSnapshot = {
          sources: new Map(sources),
          checkpoints: new Map(checkpoints),
          ledger: new Map(ledger),
          links: links.map((link) => ({ ...link })),
        }
        return { rows: [] }
      }
      if (normalized.startsWith('SELECT pg_advisory_xact_lock')) return { rows: [] }
      if (normalized === 'COMMIT') {
        transactionSnapshot = null
        return { rows: [] }
      }
      if (normalized === 'ROLLBACK') {
        if (transactionSnapshot) {
          restoreMap(sources, transactionSnapshot.sources)
          restoreMap(checkpoints, transactionSnapshot.checkpoints)
          restoreMap(ledger, transactionSnapshot.ledger)
          links.splice(0, links.length, ...transactionSnapshot.links)
        }
        transactionSnapshot = null
        return { rows: [] }
      }
      if (normalized.startsWith('INSERT INTO poc_change_history_sources')) {
        if (sources.has(parameters[0])) return { rows: [] }
        sources.set(parameters[0], {
          provider_name: parameters[1],
          provider_version: parameters[2],
          schema_contract_hash: parameters[3],
        })
        return { rows: [{ source_identity_hash: parameters[0] }] }
      }
      if (normalized.startsWith('SELECT provider_name, provider_version, schema_contract_hash')) {
        return { rows: sources.has(parameters[0]) ? [sources.get(parameters[0])] : [] }
      }
      if (normalized.startsWith('SELECT source_partition, next_offset FROM poc_change_history_checkpoints')) {
        const prefix = `${parameters[0]}:${parameters[1]}:`
        return {
          rows: [...checkpoints.entries()]
            .filter(([key]) => key.startsWith(prefix))
            .map(([key, nextOffset]) => ({
              source_partition: Number(key.slice(prefix.length)),
              next_offset: nextOffset,
            }))
            .sort((left, right) => left.source_partition - right.source_partition),
        }
      }
      if (normalized.startsWith('INSERT INTO poc_change_history_checkpoints')) {
        if (parameters[2] === failCheckpointInsertPartition) {
          throw new Error('simulated boundary insert failure')
        }
        const key = checkpointKey(parameters)
        if (!checkpoints.has(key)) checkpoints.set(key, Number(parameters[3]))
        return { rows: [] }
      }
      if (normalized.startsWith('SELECT next_offset FROM poc_change_history_checkpoints')) {
        const nextOffset = checkpoints.get(checkpointKey(parameters))
        return { rows: nextOffset === undefined ? [] : [{ next_offset: nextOffset }] }
      }
      if (normalized.startsWith('INSERT INTO poc_change_history_ledger_events')) {
        if (failNextLedgerInsert) {
          failNextLedgerInsert = false
          throw new Error('simulated ledger insert failure')
        }
        if (ledger.has(parameters[0])) return { rows: [] }
        ledger.set(parameters[0], {
          event_hash: parameters[1],
          source_identity_hash: parameters[2],
          source_event_identity: parameters[3],
          ordinal: parameters[5],
          source_offset: parameters[8],
          entity_key: parameters[10],
          source_occurred_at: parameters[19],
          detected_at: parameters[20],
        })
        return { rows: [{ event_identity: parameters[0] }] }
      }
      if (normalized.startsWith('SELECT event_hash FROM poc_change_history_ledger_events')) {
        const row = [...ledger.values()].find((candidate) => (
          candidate.source_identity_hash === parameters[0]
          && candidate.source_event_identity === parameters[1]
          && candidate.ordinal === parameters[2]
        ))
        return { rows: row ? [{ event_hash: row.event_hash }] : [] }
      }
      if (normalized.startsWith('SELECT event_identity FROM poc_change_history_ledger_events')) {
        return { rows: ledger.has(parameters[0]) ? [{ event_identity: parameters[0] }] : [] }
      }
      if (normalized.startsWith('UPDATE poc_change_history_checkpoints')) {
        const key = checkpointKey(parameters)
        if (checkpoints.get(key) !== parameters[6]) return { rows: [] }
        checkpoints.set(key, parameters[3])
        return { rows: [{ next_offset: parameters[3] }] }
      }
      if (normalized.startsWith('SELECT link_event_identity, event_hash, request_hash, link_version')) {
        const row = links.find((candidate) => candidate.request_key_hash === parameters[0])
        return { rows: row ? [row] : [] }
      }
      if (normalized.startsWith('SELECT event_hash, link_version FROM poc_change_history_cr_link_events')) {
        const rows = links.filter((candidate) => candidate.ledger_event_identity === parameters[0])
          .sort((left, right) => right.link_version - left.link_version)
        return { rows: rows.slice(0, 1) }
      }
      if (normalized.startsWith('INSERT INTO poc_change_history_cr_link_events')) {
        links.push({
          link_event_identity: parameters[0],
          event_hash: parameters[1],
          request_key_hash: parameters[2],
          request_hash: parameters[3],
          ledger_event_identity: parameters[4],
          link_version: parameters[5],
        })
        return { rows: [] }
      }
      throw new Error(`Unexpected transaction SQL: ${normalized}`)
    },
    release() {},
  }
  const pool = {
    async query(sql, parameters = []) {
      const normalized = String(sql).replace(/\s+/g, ' ').trim()
      if (normalized.startsWith('SELECT next_offset FROM poc_change_history_checkpoints')) {
        return client.query(sql, parameters)
      }
      if (normalized.startsWith('SELECT link_event_identity, event_hash, request_hash, link_version')) {
        return client.query(sql, parameters)
      }
      statements.push({ sql: normalized, parameters })
      return { rows: [] }
    },
    async connect() { return client },
    async end() {},
  }
  return {
    pool,
    statements,
    sources,
    checkpoints,
    ledger,
    links,
    failLedgerInsert() { failNextLedgerInsert = true },
  }
}

test('represents the same fresh and existing PostgreSQL change-history schema contract', async () => {
  const database = createDatabaseDouble()
  const store = createPocStateStore({ databasePool: database.pool })
  await store.appendChangeHistoryCapture(capture(10))
  const startupSql = database.statements.map((entry) => entry.sql).join('\n')
  const initSql = readFileSync(new URL('../deploy/poc/postgres-init/001-poc-state.sql', import.meta.url), 'utf8')
  for (const table of [
    'poc_change_history_sources',
    'poc_change_history_ledger_events',
    'poc_change_history_checkpoints',
    'poc_change_history_cr_link_events',
    'poc_local_credentials',
    'poc_local_sessions',
  ]) {
    assert.match(startupSql, new RegExp(`CREATE TABLE IF NOT EXISTS ${table}`))
    assert.match(initSql, new RegExp(`CREATE TABLE IF NOT EXISTS ${table}`))
  }
  for (const contract of [
    'PRIMARY KEY (source_identity_hash, topic_contract, source_partition)',
    'UNIQUE (source_identity_hash, source_event_identity, deterministic_ordinal)',
    'uq_poc_change_history_source_position_ordinal',
    'REFERENCES poc_change_history_ledger_events(event_identity)',
    'trg_poc_change_history_ledger_append_only',
    'trg_poc_change_history_cr_link_append_only',
    "password_hash LIKE '$argon2id$v=19$%'",
    'expires_at > created_at',
  ]) {
    assert.ok(startupSql.includes(contract), contract)
    assert.ok(initSql.includes(contract), contract)
  }
})

test('atomically provisions a credential behind access/core CAS without storing authority in auth rows', async () => {
  const store = createPocStateStore()
  const accessValue = {
    schema_version: 1,
    active_subject_id: 'subject-one',
    users: [{ subject_id: 'subject-one', role: 'admin', active: true, provider_owner_refs: [] }],
    system_assignments: [],
  }
  const coreValue = { adminSystems: [], changeRecords: [] }
  const result = await store.provisionLocalCredential({
    expectedAccessVersion: 0,
    expectedCoreVersion: 0,
    accessValue,
    coreValue,
    credential: {
      subjectId: 'subject-one',
      usernameNormalized: 'person@example.com',
      passwordHash: '$argon2id$v=19$m=19456,t=2,p=1$c2FsdHNhbHRzYWx0c2FsdA$YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYQ',
      loginEnabled: true,
      mustChangePassword: true,
    },
  })
  assert.deepEqual(result, { credentialVersion: 1, accessVersion: 1, coreVersion: 1 })
  assert.deepEqual((await store.readChangeHistoryAccess()).access.value, accessValue)
  const credential = await store.readLocalCredential('person@example.com')
  assert.equal(credential.subjectId, 'subject-one')
  assert.equal(credential.mustChangePassword, true)
  assert.equal(Object.hasOwn(credential, 'role'), false)
  await assert.rejects(store.provisionLocalCredential({
    expectedAccessVersion: 1,
    expectedCoreVersion: 1,
    accessValue: { ...accessValue, active_subject_id: 'changed' },
    coreValue: { changed: true },
    credential: {
      subjectId: 'subject-two',
      usernameNormalized: 'person@example.com',
      passwordHash: credential.passwordHash,
      loginEnabled: true,
      mustChangePassword: false,
    },
  }), (error) => error.code === 'CREDENTIAL_EXISTS')
  assert.deepEqual((await store.readChangeHistoryAccess()).access.value, accessValue)
})

test('refuses inherited PostgreSQL settings in Node tests before a persistent connection is created', async () => {
  await withEnvironment({
    NODE_TEST_CONTEXT: 'child-v8',
    POC_DATABASE_URL: undefined,
    POC_POSTGRES_HOST: 'persistent-dev-postgres',
    POC_POSTGRES_PORT: '5432',
    POC_POSTGRES_DB: 'datariver_poc',
    POC_TEST_DATABASE_ISOLATED_ACK: undefined,
    POC_TEST_DATABASE_TARGET: undefined,
  }, async () => {
    assert.throws(() => createPocStateStore(), (error) => {
      assert.equal(error.code, 'POC_TEST_DATABASE_ISOLATION_REQUIRED')
      return true
    })
  })
})

test('allows explicit database doubles and an acknowledged isolated test target', async () => {
  await withEnvironment({
    NODE_TEST_CONTEXT: 'child-v8',
    POC_DATABASE_URL: undefined,
    POC_POSTGRES_HOST: 'persistent-dev-postgres',
    POC_POSTGRES_PORT: '5432',
    POC_POSTGRES_DB: 'datariver_poc',
    POC_TEST_DATABASE_ISOLATED_ACK: undefined,
    POC_TEST_DATABASE_TARGET: undefined,
  }, async () => {
    const database = createDatabaseDouble()
    const store = createPocStateStore({ databasePool: database.pool })
    assert.deepEqual(await store.read('core'), { value: null, version: 0 })
    assert.ok(database.statements.length > 0)
  })

  await withEnvironment({
    NODE_TEST_CONTEXT: 'child-v8',
    POC_DATABASE_URL: undefined,
    POC_POSTGRES_HOST: '127.0.0.1',
    POC_POSTGRES_PORT: '6543',
    POC_POSTGRES_DB: 'datariver_poc_isolated_test',
    POC_TEST_DATABASE_ISOLATED_ACK: 'TRUE',
    POC_TEST_DATABASE_TARGET: '127.0.0.1:6543/datariver_poc_isolated_test',
  }, async () => {
    const store = createPocStateStore()
    assert.equal(store.configured.postgres, true)
    await store.close()
  })
})

test('locks singleton scheduling and records success only after the ordered task succeeds', async () => {
  let stored
  let failReceipt = false
  let omitReceiptWrite = false
  let receiptQueries = 0
  let unlocked = 0
  let released = 0
  const client = {
    async query(sql, parameters = []) {
      const normalized = String(sql).replace(/\s+/g, ' ').trim()
      if (normalized.startsWith('SELECT pg_try_advisory_lock')) return { rows: [{ acquired: true }] }
      if (normalized === 'SELECT value FROM poc_state WHERE scope = $1') {
        return { rows: stored ? [{ value: stored }] : [] }
      }
      if (normalized.startsWith('INSERT INTO poc_state')) {
        receiptQueries += 1
        assert.match(normalized, /WHERE poc_state\.value ->> 'last_successful_schedule' = \$3/)
        assert.match(normalized, /last_successful_schedule'\)::timestamptz < \$4::timestamptz/)
        assert.match(normalized, /RETURNING poc_state\.value ->> 'last_successful_schedule'/)
        if (failReceipt) throw new Error('receipt write failed')
        if (omitReceiptWrite) return { rows: [] }
        stored = JSON.parse(parameters[1])
        return { rows: [{ last_successful_schedule: stored.last_successful_schedule }] }
      }
      if (normalized.startsWith('SELECT pg_advisory_unlock')) {
        unlocked += 1
        return { rows: [{ pg_advisory_unlock: true }] }
      }
      throw new Error(`Unexpected scheduler SQL: ${normalized}`)
    },
    release() { released += 1 },
  }
  const pool = {
    async query() { return { rows: [] } },
    async connect() { return client },
  }
  const store = createPocStateStore({ databasePool: pool })
  const command = {
    lockName: 'scheduler-state-test',
    scheduledFor: '2026-08-13T15:00:00.000Z',
    trigger: 'scheduled',
  }
  await assert.rejects(
    store.runChangeHistoryScheduler(command, async () => { throw new Error('T05 failed') }),
    /T05 failed/,
  )
  assert.equal(stored, undefined, 'a task failure must not mark the schedule successful')
  failReceipt = true
  await assert.rejects(
    store.runChangeHistoryScheduler(command, async () => ({ ordered: true })),
    /receipt write failed/,
  )
  failReceipt = false
  assert.equal(stored, undefined, 'a receipt failure must not mark the schedule successful')
  omitReceiptWrite = true
  await assert.rejects(
    store.runChangeHistoryScheduler(command, async () => ({ ordered: true })),
    /receipt was not advanced/,
  )
  omitReceiptWrite = false
  assert.equal(stored, undefined, 'a conditional no-write must not be reported as success')
  let taskCalls = 0
  const success = await store.runChangeHistoryScheduler(command, async () => {
    taskCalls += 1
    return { ordered: true }
  })
  assert.equal(success.status, 'succeeded')
  assert.equal(stored.last_successful_schedule, command.scheduledFor)
  assert.equal(stored.trigger, 'scheduled')
  const receiptQueriesAfterSuccess = receiptQueries
  const olderCommand = {
    ...command,
    scheduledFor: '2026-08-12T15:00:00.000Z',
    trigger: 'manual',
  }
  const stale = await store.runChangeHistoryScheduler(olderCommand, async () => { taskCalls += 1 })
  assert.deepEqual(stale, { status: 'stale', scheduledFor: olderCommand.scheduledFor })
  assert.equal(stored.last_successful_schedule, command.scheduledFor)
  assert.equal(receiptQueries, receiptQueriesAfterSuccess)
  const replay = await store.runChangeHistoryScheduler(command, async () => { taskCalls += 1 })
  assert.equal(replay.status, 'already_completed')
  assert.equal(taskCalls, 1, 'newer success, older request, and exact replay run the task once')
  assert.equal(receiptQueries, receiptQueriesAfterSuccess)
  assert.equal(unlocked, 6)
  assert.equal(released, 6)
})

test('fails closed before scheduler work when the stored receipt boundary is malformed', async () => {
  let taskCalled = false
  let receiptQueried = false
  let unlocked = 0
  let released = 0
  const client = {
    async query(sql) {
      const normalized = String(sql).replace(/\s+/g, ' ').trim()
      if (normalized.startsWith('SELECT pg_try_advisory_lock')) return { rows: [{ acquired: true }] }
      if (normalized === 'SELECT value FROM poc_state WHERE scope = $1') {
        return { rows: [{ value: { last_successful_schedule: '2026-08-13T15:00:00Z' } }] }
      }
      if (normalized.startsWith('INSERT INTO poc_state')) {
        receiptQueried = true
        return { rows: [] }
      }
      if (normalized.startsWith('SELECT pg_advisory_unlock')) {
        unlocked += 1
        return { rows: [{ pg_advisory_unlock: true }] }
      }
      throw new Error(`Unexpected scheduler SQL: ${normalized}`)
    },
    release() { released += 1 },
  }
  const store = createPocStateStore({
    databasePool: {
      async query() { return { rows: [] } },
      async connect() { return client },
    },
  })
  await assert.rejects(
    store.runChangeHistoryScheduler({
      lockName: 'scheduler-state-test',
      scheduledFor: '2026-08-14T15:00:00.000Z',
      trigger: 'scheduled',
    }, async () => { taskCalled = true }),
    /stored last_successful_schedule must be an explicit UTC timestamp/,
  )
  assert.equal(taskCalled, false)
  assert.equal(receiptQueried, false)
  assert.equal(unlocked, 1)
  assert.equal(released, 1)
})

test('atomically inserts, replays, fans out, and advances a partition checkpoint', async () => {
  const database = createDatabaseDouble()
  const store = createPocStateStore({ databasePool: database.pool })
  const first = await store.appendChangeHistoryCapture(capture(10, [
    semanticEvent({ afterData: { field_type: 'integer', nullable: false } }),
    semanticEvent({ afterData: { field_type: 'bigint', nullable: false } }),
  ]))
  assert.equal(first.replayed, false)
  assert.equal(first.eventIdentities.length, 2)
  assert.equal(new Set(first.eventIdentities).size, 2)
  assert.equal(database.ledger.size, 2)
  assert.equal([...database.checkpoints.values()][0], 11)

  const replay = await store.appendChangeHistoryCapture(capture(10, [
    semanticEvent({ afterData: { field_type: 'bigint', nullable: false } }),
    semanticEvent({ afterData: { field_type: 'integer', nullable: false } }),
  ]))
  assert.deepEqual(replay.eventIdentities, first.eventIdentities)
  assert.equal(replay.replayed, true)
  assert.equal(database.ledger.size, 2)
  assert.equal([...database.checkpoints.values()][0], 11)

  const second = await store.appendChangeHistoryCapture(capture(11, [semanticEvent()]))
  assert.equal(second.replayed, false)
  assert.equal(database.ledger.size, 3)
  assert.equal([...database.checkpoints.values()][0], 12)
  assert.ok([...database.ledger.values()].every((row) => row.detected_at.endsWith('Z')))
})

test('rolls back and does not advance the checkpoint on a ledger failure or offset gap', async () => {
  const database = createDatabaseDouble()
  const store = createPocStateStore({ databasePool: database.pool })
  await store.appendChangeHistoryCapture(capture(20))
  database.failLedgerInsert()
  await assert.rejects(store.appendChangeHistoryCapture(capture(21)), /simulated ledger insert failure/)
  assert.equal([...database.checkpoints.values()][0], 21)
  assert.equal(database.ledger.size, 1)
  assert.equal(database.statements.at(-1).sql, 'ROLLBACK')

  await assert.rejects(store.appendChangeHistoryCapture(capture(22)), /stale or has an offset gap/)
  assert.equal([...database.checkpoints.values()][0], 21)
  assert.equal(database.ledger.size, 1)
  assert.equal(database.statements.at(-1).sql, 'ROLLBACK')
})

test('reads the durable resume offset and atomically acknowledges a zero-event source record', async () => {
  const database = createDatabaseDouble()
  const store = createPocStateStore({ databasePool: database.pool })
  const checkpoint = {
    sourceIdentityHash: SOURCE_HASH,
    topicContract: 'MetadataChangeLog_Versioned_v1',
    partition: 2,
  }
  assert.equal(await store.readChangeHistoryCheckpoint(checkpoint), null)

  const ignored = await store.appendChangeHistoryCapture(capture(50, []))
  assert.deepEqual(ignored.eventIdentities, [])
  assert.equal(ignored.nextOffset, 51)
  assert.equal(ignored.replayed, false)
  assert.equal(database.ledger.size, 0)
  assert.equal(database.statements.at(-1).sql, 'COMMIT')
  assert.equal(await store.readChangeHistoryCheckpoint(checkpoint), 51)
})

test('reads complete ledger, links, access, core, and current catalog in one repeatable snapshot', async () => {
  const statements = []
  const catalogScope = 'catalog-inventory-v1:test-scope'
  const client = {
    async query(sql, parameters = []) {
      const normalized = String(sql).replace(/\s+/g, ' ').trim()
      statements.push({ sql: normalized, parameters })
      if (normalized === 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY'
        || normalized === 'COMMIT' || normalized === 'ROLLBACK') return { rows: [] }
      if (normalized.startsWith('SELECT scope, value, version FROM poc_state')) return { rows: [
        { scope: 'change-history-access-v1', value: { schema_version: 1 }, version: 2 },
        { scope: 'core', value: { changeRecords: [] }, version: 3 },
        { scope: catalogScope, value: { items: [] }, version: 4 },
      ] }
      if (normalized.includes('FROM poc_change_history_ledger_events')) return { rows: [{ event_identity: 'e'.repeat(64) }] }
      if (normalized.includes('FROM poc_change_history_cr_link_events')) return { rows: [{ link_event_identity: 'f'.repeat(64) }] }
      if (normalized.includes('FROM poc_change_history_sources')) return { rows: [{
        source_identity_hash: SOURCE_HASH, provider_name: 'DataHub', provider_version: 'contract-test',
        schema_contract_hash: SCHEMA_HASH, created_at: '2026-08-13T00:00:00.000Z',
      }] }
      if (normalized.includes('FROM poc_change_history_checkpoints')) return { rows: [{
        source_identity_hash: SOURCE_HASH, topic_contract: 'MetadataChangeLog_Versioned_v1',
        source_partition: 0, first_exact_offset: 10, next_offset: 11,
        last_contiguous_event_identity: 'e'.repeat(64), last_source_occurred_at: '2026-08-13T00:00:00.000Z',
        last_captured_at: '2026-08-13T00:00:01.000Z', version: 2,
      }] }
      throw new Error(`Unexpected projection SQL: ${normalized}`)
    },
    release() {},
  }
  const store = createPocStateStore({ databasePool: {
    async query() { return { rows: [] } },
    async connect() { return client },
  } })
  const projection = await store.readChangeHistoryProjection({ catalogScope })
  assert.equal(projection.access.version, 2)
  assert.equal(projection.core.version, 3)
  assert.equal(projection.catalog.version, 4)
  assert.equal(projection.events.length, 1)
  assert.equal(projection.links.length, 1)
  assert.equal(projection.sources[0].provider_name, 'DataHub')
  assert.equal(projection.checkpoints[0].first_exact_offset, 10)
  assert.ok(statements.every(({ sql }) => !/\bLIMIT\b/.test(sql)), 'complete projection must not silently truncate')
  assert.equal(statements[0].sql, 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
  assert.equal(statements.at(-1).sql, 'COMMIT')
})

test('atomically fixes the initial partition boundary vector and rejects later topology changes', async () => {
  const database = createDatabaseDouble()
  const store = createPocStateStore({ databasePool: database.pool })
  const command = {
    sourceIdentityHash: SOURCE_HASH,
    providerName: 'DataHub',
    providerVersion: 'contract-test',
    schemaContractHash: SCHEMA_HASH,
    topicContract: 'MetadataChangeLog_Versioned_v1',
    partitions: [
      { partition: 1, boundary: 25 },
      { partition: 0, boundary: 100 },
    ],
  }
  assert.deepEqual(await store.initializeChangeHistoryCaptureBoundaries(command), [
    { partition: 0, nextOffset: 100 },
    { partition: 1, nextOffset: 25 },
  ])
  assert.deepEqual([...database.checkpoints.values()].sort((left, right) => left - right), [25, 100])

  assert.deepEqual(await store.initializeChangeHistoryCaptureBoundaries({
    ...command,
    partitions: [
      { partition: 0, boundary: 150 },
      { partition: 1, boundary: 30 },
    ],
  }), [
    { partition: 0, nextOffset: 100 },
    { partition: 1, nextOffset: 25 },
  ])
  await assert.rejects(store.initializeChangeHistoryCaptureBoundaries({
    ...command,
    partitions: [...command.partitions, { partition: 2, boundary: 0 }],
  }), /partition topology changed/)
  assert.equal(database.checkpoints.size, 2)
  assert.equal(database.statements.at(-1).sql, 'ROLLBACK')

  const duplicateDatabase = createDatabaseDouble()
  const duplicateStore = createPocStateStore({ databasePool: duplicateDatabase.pool })
  const duplicateResults = await Promise.all([
    duplicateStore.initializeChangeHistoryCaptureBoundaries(command),
    duplicateStore.initializeChangeHistoryCaptureBoundaries(command),
  ])
  assert.deepEqual(duplicateResults[0], duplicateResults[1])
  assert.equal(duplicateDatabase.checkpoints.size, 2)

  const failingDatabase = createDatabaseDouble({ failCheckpointInsertPartition: 1 })
  const failingStore = createPocStateStore({ databasePool: failingDatabase.pool })
  await assert.rejects(
    failingStore.initializeChangeHistoryCaptureBoundaries(command),
    /simulated boundary insert failure/,
  )
  assert.equal(failingDatabase.sources.size, 0)
  assert.equal(failingDatabase.checkpoints.size, 0)
  assert.equal(failingDatabase.statements.at(-1).sql, 'ROLLBACK')
})

test('appends CR candidate and primary link history with exact replay and stale-chain rejection', async () => {
  const database = createDatabaseDouble()
  const store = createPocStateStore({ databasePool: database.pool })
  const ledgerEventIdentity = (await store.appendChangeHistoryCapture(capture(30))).eventIdentities[0]
  const candidate = {
    idempotencyKey: 'candidate-command-1',
    ledgerEventIdentity,
    linkKind: 'CANDIDATE',
    action: 'ADD_CANDIDATE',
    changeRequestId: 'CR-100',
    changeRequestRound: 1,
    priorLinkHash: null,
    reason: 'Detected change candidate',
    policyHash: POLICY_HASH,
    basisHash: BASIS_HASH,
    actorRef: 'poc-server:test-subject',
    occurredAt: '2026-08-13T15:10:00.000Z',
  }
  const first = await store.appendChangeHistoryCrLink(candidate)
  assert.deepEqual(first, {
    linkEventIdentity: first.linkEventIdentity,
    eventHash: first.eventHash,
    linkVersion: 1,
    replayed: false,
  })
  assert.equal((await store.appendChangeHistoryCrLink(candidate)).replayed, true)
  assert.equal((await store.readChangeHistoryCrLinkReplay(candidate)).replayed, true)
  assert.equal(database.links.length, 1)

  await assert.rejects(
    store.appendChangeHistoryCrLink({ ...candidate, reason: 'conflict' }),
    /idempotency key conflicts/,
  )
  await assert.rejects(
    store.readChangeHistoryCrLinkReplay({ ...candidate, reason: 'conflict' }),
    /idempotency key conflicts/,
  )
  await assert.rejects(
    store.appendChangeHistoryCrLink({ ...candidate, idempotencyKey: 'candidate-command-2' }),
    /stale prior-link hash/,
  )
  const primary = await store.appendChangeHistoryCrLink({
    ...candidate,
    idempotencyKey: 'primary-command-1',
    linkKind: 'PRIMARY',
    action: 'SET_PRIMARY',
    priorLinkHash: first.eventHash,
  })
  assert.equal(primary.linkVersion, 2)
  assert.equal(database.links.length, 2)
})

test('rejects raw provider documents and non-UTC evidence before touching PostgreSQL', async () => {
  const database = createDatabaseDouble()
  const store = createPocStateStore({ databasePool: database.pool })
  await assert.rejects(store.appendChangeHistoryCapture(capture(40, [semanticEvent({
    afterData: { schemaMetadata: { fields: [] } },
  })])), /forbidden raw provider-document key/)
  await assert.rejects(store.appendChangeHistoryCapture(capture(40, [semanticEvent({
    detectedAt: '2026-08-14T00:00:00+09:00',
  })])), /explicit UTC timestamp/)
  assert.equal(database.statements.length, 0)
})

test('accepts only the extended field metadata and exact lifecycle category/aspect pairs', async () => {
  const database = createDatabaseDouble()
  const store = createPocStateStore({ databasePool: database.pool })
  const fieldTag = semanticEvent({
    entityKey: 'field:customer_id:tag_urn:urn:li:tag:curated', category: 'TAG', sourceAspect: 'schemaMetadata',
    operation: 'ADD', beforeData: null, afterData: { field_path: 'customer_id', tag_urn: 'urn:li:tag:curated' },
  })
  const editableTerm = semanticEvent({
    entityKey: 'field:customer_id:term_urn:urn:li:glossaryTerm:pii', category: 'GLOSSARY_TERM', sourceAspect: 'editableSchemaMetadata',
    operation: 'ADD', beforeData: null, afterData: { field_path: 'customer_id', term_urn: 'urn:li:glossaryTerm:pii' },
  })
  const removed = semanticEvent({
    entityKey: 'asset:lifecycle:removed', category: 'LIFECYCLE', sourceAspect: 'status', operation: 'DELETE',
    beforeData: { removed: false }, afterData: { removed: true },
  })
  const entityCreated = semanticEvent({
    entityKey: 'asset:lifecycle:entity', category: 'LIFECYCLE', sourceAspect: 'entity', operation: 'CREATE',
    beforeData: null, afterData: { entity_type: 'dataset' },
  })
  await store.appendChangeHistoryCapture(capture(44, [fieldTag, editableTerm, removed, entityCreated]))
  await assert.rejects(store.appendChangeHistoryCapture(capture(45, [semanticEvent({
    category: 'TAG', sourceAspect: 'status', operation: 'ADD', beforeData: null, afterData: { tag_urn: 'urn:li:tag:no' },
  })])), /sourceAspect is outside its closed vocabulary/)
  const initSql = readFileSync(new URL('../deploy/poc/postgres-init/001-poc-state.sql', import.meta.url), 'utf8')
  const startupSql = database.statements.map((entry) => entry.sql).join('\n')
  for (const contract of [
    "source_aspect IN ('globalTags', 'schemaMetadata', 'editableSchemaMetadata')",
    "category = 'LIFECYCLE' AND source_aspect IN ('status', 'entity')",
    'DROP CONSTRAINT ck_poc_change_history_ledger_category',
    'CONSTRAINT ck_poc_change_history_ledger_category_v2 CHECK',
    "WHERE conname = 'ck_poc_change_history_ledger_category_v2'",
  ]) {
    assert.ok(initSql.includes(contract), `init SQL: ${contract}`)
    assert.ok(startupSql.includes(contract), `startup SQL: ${contract}`)
  }
  assert.equal(initSql.includes('pg_get_constraintdef'), false, 'the v2 upgrade must not depend on deparsed CHECK text')
  assert.equal(startupSql.includes('pg_get_constraintdef'), false, 'the runtime upgrade must not depend on deparsed CHECK text')
  assert.match(initSql, /IF EXISTS \([\s\S]*ck_poc_change_history_ledger_category[\s\S]*DROP CONSTRAINT ck_poc_change_history_ledger_category;[\s\S]*IF NOT EXISTS \([\s\S]*ck_poc_change_history_ledger_category_v2/)
  assert.match(startupSql, /IF EXISTS \([\s\S]*ck_poc_change_history_ledger_category[\s\S]*DROP CONSTRAINT ck_poc_change_history_ledger_category;[\s\S]*IF NOT EXISTS \([\s\S]*ck_poc_change_history_ledger_category_v2/)
  const upgradeEffects = (initialConstraintNames) => {
    const names = new Set(initialConstraintNames)
    const effects = []
    if (names.delete('ck_poc_change_history_ledger_category')) effects.push('DROP_OLD')
    if (!names.has('ck_poc_change_history_ledger_category_v2')) {
      names.add('ck_poc_change_history_ledger_category_v2')
      effects.push('ADD_V2')
    }
    return effects
  }
  assert.deepEqual(upgradeEffects(['ck_poc_change_history_ledger_category']), ['DROP_OLD', 'ADD_V2'])
  assert.deepEqual(upgradeEffects(['ck_poc_change_history_ledger_category_v2']), [], 'second startup must issue no category CHECK DDL')
})

test('CAS-updates private access with its core projection and fences later generic core writes', async () => {
  const store = createPocStateStore()
  const originalChangeRecords = [{ id: 'request-from-core', state: 'IN_REVIEW', version: 7 }]
  assert.equal(await store.write('core', { changeRecords: originalChangeRecords, sequence: 11 }), 1)
  const initial = await store.readChangeHistoryAccess()
  assert.equal(initial.access.version, 0)
  assert.equal(initial.core.version, 1)

  const accessValue = {
    schema_version: 1,
    active_subject_id: 'subject-from-config',
    users: [{ subject_id: 'subject-from-config', role: 'admin', active: true, provider_owner_refs: [] }],
    system_assignments: [],
  }
  const projectedCore = {
    ...initial.core.value,
    adminMemberships: [{ subject_id: 'subject-from-config', subject_active: true }],
    adminSystems: [{ system_id: 'business-system', active: true }],
    adminSystemAssignees: [['business-system', []]],
    adminSystemSchemaScopes: [['business-system', []]],
  }
  assert.deepEqual(await store.writeChangeHistoryAccess({
    expectedAccessVersion: 0,
    expectedCoreVersion: 1,
    accessValue,
    coreValue: projectedCore,
  }), { accessVersion: 1, coreVersion: 2 })

  await assert.rejects(store.writeChangeHistoryAccess({
    expectedAccessVersion: 0,
    expectedCoreVersion: 1,
    accessValue,
    coreValue: projectedCore,
  }), (error) => error.code === 'ACCESS_VERSION_STALE' && error.statusCode === 409)

  await store.write('core', {
    changeRecords: [{ id: 'request-from-core', state: 'COMPLETED', version: 8 }],
    sequence: 12,
    adminMemberships: [],
    adminSystems: [],
    adminSystemAssignees: [],
    adminSystemSchemaScopes: [],
  })
  const fenced = await store.read('core')
  assert.equal(fenced.version, 3)
  assert.equal(fenced.value.changeRecords[0].state, 'COMPLETED')
  assert.deepEqual(fenced.value.adminSystems, projectedCore.adminSystems)
  assert.deepEqual(fenced.value.adminMemberships, projectedCore.adminMemberships)
  assert.deepEqual((await store.readChangeHistoryAccess()).access.value, accessValue)
})

test('serializes PostgreSQL core and access writes before missing-row locks and rolls back stale CAS', async () => {
  const statements = []
  const rows = new Map()
  const client = {
    async query(sql, parameters = []) {
      const normalized = String(sql).replace(/\s+/g, ' ').trim()
      statements.push({ sql: normalized, parameters })
      if (['BEGIN', 'COMMIT', 'ROLLBACK'].includes(normalized)) return { rows: [] }
      if (normalized.startsWith('SELECT pg_advisory_xact_lock')) return { rows: [] }
      if (normalized.includes('SELECT scope, value, version FROM poc_state') && normalized.includes('FOR UPDATE')) {
        return { rows: [...rows.entries()].map(([scope, row]) => ({ scope, ...row })) }
      }
      if (normalized.startsWith('INSERT INTO poc_state (scope, value)')) {
        const scope = parameters.length === 2 ? parameters[0] : 'core'
        const value = JSON.parse(parameters.at(-1))
        const version = (rows.get(scope)?.version ?? 0) + 1
        rows.set(scope, { value, version })
        return { rows: [{ version }] }
      }
      throw new Error(`Unexpected access CAS SQL: ${normalized}`)
    },
    release() {},
  }
  const store = createPocStateStore({
    databasePool: {
      async query() { return { rows: [] } },
      async connect() { return client },
    },
  })
  const assertTransactionOrder = (start, writePrefix) => {
    const transaction = statements.slice(start)
    const beginIndex = transaction.findIndex(({ sql }) => sql === 'BEGIN')
    const advisoryIndex = transaction.findIndex(({ sql }) => sql.startsWith('SELECT pg_advisory_xact_lock'))
    const rowSelectIndex = transaction.findIndex(({ sql }) => sql.includes('ORDER BY scope FOR UPDATE'))
    const writeIndex = transaction.findIndex(({ sql }) => sql.startsWith(writePrefix))
    assert.ok(beginIndex < advisoryIndex)
    assert.ok(advisoryIndex < rowSelectIndex)
    assert.ok(rowSelectIndex < writeIndex)
    assert.deepEqual(transaction[advisoryIndex].parameters, ['change-history-access-v1'])
  }

  const coreStart = statements.length
  assert.equal(await store.write('core', { changeRecords: [] }), 1)
  assertTransactionOrder(coreStart, "INSERT INTO poc_state (scope, value) VALUES ('core'")
  rows.clear()

  const accessValue = {
    schema_version: 1,
    active_subject_id: 'database-subject',
    users: [{ subject_id: 'database-subject', role: 'admin', active: true, provider_owner_refs: [] }],
    system_assignments: [],
  }
  const accessStart = statements.length
  assert.deepEqual(await store.writeChangeHistoryAccess({
    expectedAccessVersion: 0,
    expectedCoreVersion: 0,
    accessValue,
    coreValue: { changeRecords: [], adminSystems: [] },
  }), { accessVersion: 1, coreVersion: 1 })
  assertTransactionOrder(accessStart, 'INSERT INTO poc_state (scope, value)')

  const staleStart = statements.length
  await assert.rejects(store.writeChangeHistoryAccess({
    expectedAccessVersion: 0,
    expectedCoreVersion: 0,
    accessValue,
    coreValue: { changeRecords: [] },
  }), (error) => error.code === 'ACCESS_VERSION_STALE')
  const staleTransaction = statements.slice(staleStart)
  assert.ok(staleTransaction.findIndex(({ sql }) => sql === 'BEGIN')
    < staleTransaction.findIndex(({ sql }) => sql.startsWith('SELECT pg_advisory_xact_lock')))
  assert.ok(staleTransaction.findIndex(({ sql }) => sql.startsWith('SELECT pg_advisory_xact_lock'))
    < staleTransaction.findIndex(({ sql }) => sql.includes('ORDER BY scope FOR UPDATE')))
  assert.equal(statements.at(-1).sql, 'ROLLBACK')
})

test('CAS-replaces in-memory core state and rejects a stale retry without changing state', async () => {
  const store = createPocStateStore()
  assert.equal(await store.writeIfVersion('core', { sequence: 1 }, 0), 1)
  await assert.rejects(
    () => store.writeIfVersion('core', { sequence: 2 }, 0),
    { code: 'STATE_VERSION_STALE' },
  )
  assert.deepEqual(await store.read('core'), { value: { sequence: 1 }, version: 1 })
  assert.equal(await store.writeIfVersion('core', { sequence: 2 }, 1), 2)
})
