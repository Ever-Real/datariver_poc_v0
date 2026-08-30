import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { readFileSync } from 'node:fs'
import process from 'node:process'
import test from 'node:test'
import { URL } from 'node:url'
import pg from 'pg'

import {
  pocPostgresTestSkipReason,
  withDisposablePocPostgres,
} from './poc-postgres-test-fixture.mjs'
import { createPocStateStore } from './poc-state-store.mjs'

const { Pool } = pg
const migrations = [
  '001-poc-state.sql',
  '002-poc-knowledge-ingestion.sql',
  '003-poc-k9-managed-graphs.sql',
  '004-poc-local-security-events.sql',
].map((name) => readFileSync(new URL(`../deploy/poc/postgres-init/${name}`, import.meta.url), 'utf8'))

const oldPasswordHash = '$argon2id$v=19$m=65536,t=3,p=4$c3ludGhldGljLXNhbHQ$c3ludGhldGljLW9sZC1oYXNo'
const newPasswordHash = '$argon2id$v=19$m=65536,t=3,p=4$c3ludGhldGljLXNhbHQ$c3ludGhldGljLW5ldy1oYXNo'

async function applyFreshSchema(pool) {
  for (const migration of migrations) await pool.query(migration)
}

function normalizedQuery(args) {
  const query = typeof args[0] === 'string' ? args[0] : args[0]?.text
  const parameters = typeof args[0] === 'string' ? args[1] : args[0]?.values
  return {
    sql: String(query).replace(/\s+/g, ' ').trim(),
    parameters: parameters ?? [],
  }
}

function createObservedPool(realPool) {
  const trace = []
  let failureMatcher
  async function query(target, args) {
    const observed = normalizedQuery(args)
    trace.push(observed)
    if (failureMatcher?.(observed)) {
      failureMatcher = undefined
      throw Object.assign(new Error('synthetic real PostgreSQL event insert failure'), {
        code: 'AC01_EVENT_INSERT_FAILURE',
      })
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
    armFailure(matcher) {
      failureMatcher = matcher
    },
    resetTrace() {
      trace.length = 0
    },
    trace,
  }
}

async function credentialTransactionSnapshot(pool, subjectId) {
  const [credential, sessions, events] = await Promise.all([
    pool.query(`
      SELECT subject_id, username_normalized, password_hash, login_enabled,
        must_change_password, failed_attempts, locked_until::text, version::text
      FROM poc_local_credentials WHERE subject_id = $1
    `, [subjectId]),
    pool.query(`
      SELECT token_hash, subject_id, created_at::text, expires_at::text, revoked_at::text
      FROM poc_local_sessions WHERE subject_id = $1 ORDER BY token_hash
    `, [subjectId]),
    pool.query(`
      SELECT event_id, event_type, subject_id, actor_subject_id, actor_kind,
        occurred_at, resulting_credential_version::text, revoked_session_count::text
      FROM poc_local_security_events WHERE subject_id = $1 ORDER BY occurred_at, event_id
    `, [subjectId]),
  ])
  return {
    credential: credential.rows,
    sessions: sessions.rows,
    events: events.rows,
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

test('actual changeOwnLocalPassword commits one event and rolls real credential/session writes back on event failure', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('password_atomicity', async ({ connectionString }) => {
  const realPool = new Pool({ connectionString, max: 3 })
  try {
    await applyFreshSchema(realPool)
    const subjectId = `synthetic-subject-${randomUUID()}`
    await realPool.query(`
      INSERT INTO poc_local_credentials (
        subject_id, username_normalized, password_hash, login_enabled,
        must_change_password, failed_attempts, locked_until, version
      ) VALUES ($1, $2, $3, true, true, 4, '2030-01-01T00:00:00Z', 7)
    `, [subjectId, `synthetic-${randomUUID()}@example.invalid`, oldPasswordHash])
    await realPool.query(`
      INSERT INTO poc_local_sessions (token_hash, subject_id, created_at, expires_at)
      VALUES ($1, $3, '2026-08-29T00:00:00Z', '2030-01-01T00:00:00Z'),
        ($2, $3, '2026-08-29T00:01:00Z', '2030-01-01T00:01:00Z')
    `, ['a'.repeat(64), 'b'.repeat(64), subjectId])

    await withSchemaIntegrityRequired(async () => {
      const observed = createObservedPool(realPool)
      const store = createPocStateStore({ databasePool: observed.pool })
      await store.read('synthetic-schema-start-probe')
      const before = await credentialTransactionSnapshot(realPool, subjectId)
      assert.equal(before.credential.length, 1)
      assert.equal(before.sessions.length, 2)
      assert.equal(before.events.length, 0)

      observed.resetTrace()
      observed.armFailure(({ sql }) => sql.startsWith('INSERT INTO poc_local_security_events'))
      await assert.rejects(store.changeOwnLocalPassword({
        subjectId,
        expectedVersion: 7,
        passwordHash: newPasswordHash,
      }), { code: 'AC01_EVENT_INSERT_FAILURE' })
      assert.deepEqual(await credentialTransactionSnapshot(realPool, subjectId), before)

      const failedSql = observed.trace.map(({ sql }) => sql)
      const credentialUpdate = failedSql.findIndex((sql) => sql.startsWith('UPDATE poc_local_credentials'))
      const sessionUpdate = failedSql.findIndex((sql) => sql.startsWith('UPDATE poc_local_sessions'))
      const eventInsert = failedSql.findIndex((sql) => sql.startsWith('INSERT INTO poc_local_security_events'))
      assert.ok(credentialUpdate > 0)
      assert.ok(sessionUpdate > credentialUpdate)
      assert.ok(eventInsert > sessionUpdate)
      assert.equal(failedSql.at(-1), 'ROLLBACK')

      observed.resetTrace()
      const result = await store.changeOwnLocalPassword({
        subjectId,
        expectedVersion: 7,
        passwordHash: newPasswordHash,
      })
      assert.deepEqual(result, { credentialVersion: 8, revokedSessionCount: 2 })
      const committed = await credentialTransactionSnapshot(realPool, subjectId)
      assert.equal(committed.credential[0].password_hash, newPasswordHash)
      assert.equal(committed.credential[0].version, '8')
      assert.equal(committed.credential[0].must_change_password, false)
      assert.equal(committed.credential[0].failed_attempts, 0)
      assert.equal(committed.credential[0].locked_until, null)
      assert.ok(committed.sessions.every(({ revoked_at: revokedAt }) => revokedAt !== null))
      assert.equal(committed.events.length, 1)
      assert.deepEqual({
        event_type: committed.events[0].event_type,
        subject_id: committed.events[0].subject_id,
        actor_subject_id: committed.events[0].actor_subject_id,
        actor_kind: committed.events[0].actor_kind,
        resulting_credential_version: committed.events[0].resulting_credential_version,
        revoked_session_count: committed.events[0].revoked_session_count,
      }, {
        event_type: 'SELF_PASSWORD_CHANGED_V1',
        subject_id: subjectId,
        actor_subject_id: subjectId,
        actor_kind: 'SELF',
        resulting_credential_version: '8',
        revoked_session_count: '2',
      })
      assert.equal(observed.trace.at(-1)?.sql, 'COMMIT')

      const eventColumns = await realPool.query(`
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'poc_local_security_events'
        ORDER BY ordinal_position
      `)
      assert.deepEqual(eventColumns.rows.map(({ column_name: columnName }) => columnName), [
        'event_id', 'event_type', 'subject_id', 'actor_subject_id', 'actor_kind',
        'occurred_at', 'resulting_credential_version', 'revoked_session_count',
      ])
      await store.close()
    })
  } finally {
    await realPool.end()
  }
}))

test('actual provisionLocalCredential atomically appends a secret-free actor/subject audit receipt', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('provision_audit', async ({ connectionString }) => {
  const realPool = new Pool({ connectionString, max: 3 })
  try {
    await applyFreshSchema(realPool)
    await withSchemaIntegrityRequired(async () => {
      const observed = createObservedPool(realPool)
      const store = createPocStateStore({ databasePool: observed.pool })
      await store.read('synthetic-schema-start-probe')
      observed.resetTrace()

      const subjectId = `created-subject-${randomUUID()}`
      const actorSubjectId = `admin-actor-${randomUUID()}`
      const usernameNormalized = `created-${randomUUID()}@example.invalid`
      const result = await store.provisionLocalCredential({
        expectedAccessVersion: 0,
        expectedCoreVersion: 0,
        actorSubjectId,
        accessValue: { schema_version: 1, active_subject_id: actorSubjectId, users: [] },
        coreValue: {},
        credential: {
          subjectId,
          usernameNormalized,
          passwordHash: oldPasswordHash,
          loginEnabled: true,
          mustChangePassword: true,
        },
      })
      assert.deepEqual(result, { credentialVersion: 1, accessVersion: 1, coreVersion: 1 })
      const committed = await credentialTransactionSnapshot(realPool, subjectId)
      assert.equal(committed.credential.length, 1)
      assert.equal(committed.events.length, 1)
      assert.deepEqual({
        event_type: committed.events[0].event_type,
        subject_id: committed.events[0].subject_id,
        actor_subject_id: committed.events[0].actor_subject_id,
        actor_kind: committed.events[0].actor_kind,
        resulting_credential_version: committed.events[0].resulting_credential_version,
        revoked_session_count: committed.events[0].revoked_session_count,
      }, {
        event_type: 'LOCAL_CREDENTIAL_PROVISIONED_V1',
        subject_id: subjectId,
        actor_subject_id: actorSubjectId,
        actor_kind: 'LOCAL_ADMIN',
        resulting_credential_version: '1',
        revoked_session_count: '0',
      })
      const serializedReceipt = JSON.stringify(committed.events[0])
      assert.equal(serializedReceipt.includes(usernameNormalized), false)
      assert.equal(serializedReceipt.includes(oldPasswordHash), false)
      assert.doesNotMatch(serializedReceipt, /password|email/i)
      const eventInsert = observed.trace.find(({ sql }) => (
        sql.startsWith('INSERT INTO poc_local_security_events')
      ))
      assert.ok(eventInsert)
      assert.equal(eventInsert.parameters.includes(usernameNormalized), false)
      assert.equal(eventInsert.parameters.includes(oldPasswordHash), false)
      assert.equal(observed.trace.at(-1)?.sql, 'COMMIT')

      const duplicateSubjectId = `duplicate-subject-${randomUUID()}`
      await realPool.query(`
        INSERT INTO poc_local_security_events (
          event_id, event_type, subject_id, actor_subject_id, actor_kind,
          resulting_credential_version, revoked_session_count
        ) VALUES ($1, 'LOCAL_CREDENTIAL_PROVISIONED_V1', $2, $3, 'LOCAL_ADMIN', 1, 0)
      `, [randomUUID(), duplicateSubjectId, actorSubjectId])
      const beforeAccess = await realPool.query(
        "SELECT value, version::text FROM poc_state WHERE scope IN ('change-history-access-v1', 'core') ORDER BY scope",
      )
      observed.resetTrace()
      await assert.rejects(store.provisionLocalCredential({
        expectedAccessVersion: 1,
        expectedCoreVersion: 1,
        actorSubjectId,
        accessValue: { changed: true },
        coreValue: { changed: true },
        credential: {
          subjectId: duplicateSubjectId,
          usernameNormalized: `duplicate-${randomUUID()}@example.invalid`,
          passwordHash: newPasswordHash,
          loginEnabled: true,
          mustChangePassword: false,
        },
      }), { code: '23505' })
      assert.equal((await realPool.query(
        'SELECT count(*)::integer AS count FROM poc_local_credentials WHERE subject_id = $1',
        [duplicateSubjectId],
      )).rows[0].count, 0)
      assert.deepEqual((await realPool.query(
        "SELECT value, version::text FROM poc_state WHERE scope IN ('change-history-access-v1', 'core') ORDER BY scope",
      )).rows, beforeAccess.rows)
      assert.equal(observed.trace.at(-1)?.sql, 'ROLLBACK')
      await store.close()
    })
  } finally {
    await realPool.end()
  }
}))

test('actual PostgreSQL triggers preserve ordinary state writes and reject receipt/event mutation', {
  skip: pocPostgresTestSkipReason,
}, async () => withDisposablePocPostgres('immutable_triggers', async ({ connectionString }) => {
  const pool = new Pool({ connectionString, max: 2 })
  try {
    await applyFreshSchema(pool)
    const ordinaryScope = `synthetic-ordinary-${randomUUID()}`
    await pool.query(
      'INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)',
      [ordinaryScope, JSON.stringify({ sequence: 1 })],
    )
    const updated = await pool.query(`
      UPDATE poc_state
      SET value = $2::jsonb, version = version + 1
      WHERE scope = $1 AND version = 1
      RETURNING value, version
    `, [ordinaryScope, JSON.stringify({ sequence: 2 })])
    assert.deepEqual(updated.rows, [{ value: { sequence: 2 }, version: '2' }])
    const deleted = await pool.query(
      'DELETE FROM poc_state WHERE scope = $1 RETURNING scope',
      [ordinaryScope],
    )
    assert.deepEqual(deleted.rows, [{ scope: ordinaryScope }])

    const immutableReceipt = (error) => error.message === 'POC Product schema receipts are immutable'
    await assert.rejects(pool.query(`
      UPDATE poc_state SET value = '{}'::jsonb
      WHERE scope = 'product-owned-schema-contract-v2'
    `), immutableReceipt)
    await assert.rejects(pool.query(`
      DELETE FROM poc_state WHERE scope = 'product-owned-schema-contract-v2'
    `), immutableReceipt)
    await assert.rejects(pool.query(`
      UPDATE poc_state SET scope = $1
      WHERE scope = 'product-owned-schema-contract-v2'
    `, [ordinaryScope]), immutableReceipt)
    await pool.query(
      'INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)',
      [ordinaryScope, JSON.stringify({ sequence: 3 })],
    )
    await assert.rejects(pool.query(`
      UPDATE poc_state SET scope = 'product-owned-schema-contract-v99'
      WHERE scope = $1
    `, [ordinaryScope]), immutableReceipt)

    const eventId = randomUUID()
    const subjectId = `synthetic-subject-${randomUUID()}`
    await pool.query(`
      INSERT INTO poc_local_security_events (
        event_id, event_type, subject_id, actor_subject_id, actor_kind,
        resulting_credential_version, revoked_session_count
      ) VALUES ($1, 'SELF_PASSWORD_CHANGED_V1', $2, $2, 'SELF', 2, 1)
    `, [eventId, subjectId])
    const immutableEvent = (error) => error.message === 'POC local security events are append-only'
    await assert.rejects(pool.query(`
      UPDATE poc_local_security_events SET revoked_session_count = 2 WHERE event_id = $1
    `, [eventId]), immutableEvent)
    await assert.rejects(pool.query(`
      DELETE FROM poc_local_security_events WHERE event_id = $1
    `, [eventId]), immutableEvent)
    assert.equal((await pool.query(`
      SELECT count(*)::integer AS row_count FROM poc_local_security_events WHERE event_id = $1
    `, [eventId])).rows[0].row_count, 1)
  } finally {
    await pool.end()
  }
}))
