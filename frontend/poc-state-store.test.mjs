import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { URL } from 'node:url'

import { createPocStateStore } from './poc-state-store.mjs'

const SOURCE_HASH = 'a'.repeat(64)
const SCHEMA_HASH = 'b'.repeat(64)
const POLICY_HASH = 'c'.repeat(64)
const BASIS_HASH = 'd'.repeat(64)

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

function createDatabaseDouble() {
  const statements = []
  const sources = new Map()
  const checkpoints = new Map()
  const ledger = new Map()
  const links = []
  let failNextLedgerInsert = false

  const checkpointKey = (parameters) => parameters.slice(0, 3).join(':')
  const client = {
    async query(sql, parameters = []) {
      const normalized = String(sql).replace(/\s+/g, ' ').trim()
      statements.push({ sql: normalized, parameters })
      if (['BEGIN', 'COMMIT', 'ROLLBACK'].includes(normalized)) return { rows: [] }
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
      if (normalized.startsWith('INSERT INTO poc_change_history_checkpoints')) {
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
    async query(sql) {
      statements.push({ sql: String(sql).replace(/\s+/g, ' ').trim(), parameters: [] })
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
  ]) {
    assert.ok(startupSql.includes(contract), contract)
    assert.ok(initSql.includes(contract), contract)
  }
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
  assert.equal(database.links.length, 1)

  await assert.rejects(
    store.appendChangeHistoryCrLink({ ...candidate, reason: 'conflict' }),
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
