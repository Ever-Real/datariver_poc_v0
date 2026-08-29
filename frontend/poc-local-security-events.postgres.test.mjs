import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import process from 'node:process'
import test from 'node:test'
import pg from 'pg'

const { Pool } = pg
const databaseUrl = process.env.POC_LOCAL_SECURITY_POSTGRES_TEST_URL?.trim()
const isolated = process.env.POC_LOCAL_SECURITY_POSTGRES_TEST_CONFIRM_ISOLATED === '1'
const skipReason = databaseUrl && isolated
  ? false
  : 'requires POC_LOCAL_SECURITY_POSTGRES_TEST_URL and POC_LOCAL_SECURITY_POSTGRES_TEST_CONFIRM_ISOLATED=1'

test('real PostgreSQL preserves ordinary state mutation while protecting schema receipts', {
  skip: skipReason,
}, async (context) => {
  const pool = new Pool({ connectionString: databaseUrl, max: 1 })
  const ordinaryScope = `ac01-ordinary-state-${randomUUID()}`
  context.after(async () => {
    await pool.query('DELETE FROM poc_state WHERE scope = $1', [ordinaryScope]).catch(() => undefined)
    await pool.end()
  })

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

  const immutableFailure = (error) => (
    error.message === 'POC Product schema receipts are immutable'
  )
  await assert.rejects(pool.query(`
    UPDATE poc_state SET value = '{}'::jsonb
    WHERE scope = 'product-owned-schema-contract-v2'
  `), immutableFailure)
  await assert.rejects(pool.query(`
    DELETE FROM poc_state WHERE scope = 'product-owned-schema-contract-v2'
  `), immutableFailure)
  await assert.rejects(pool.query(`
    UPDATE poc_state SET scope = $1
    WHERE scope = 'product-owned-schema-contract-v2'
  `, [ordinaryScope]), immutableFailure)

  await pool.query(
    'INSERT INTO poc_state (scope, value) VALUES ($1, $2::jsonb)',
    [ordinaryScope, JSON.stringify({ sequence: 3 })],
  )
  await assert.rejects(pool.query(`
    UPDATE poc_state SET scope = 'product-owned-schema-contract-v99'
    WHERE scope = $1
  `, [ordinaryScope]), immutableFailure)
  assert.equal((await pool.query(`
    SELECT count(*)::integer AS row_count FROM poc_state
    WHERE scope IN ($1, 'product-owned-schema-contract-v2', 'product-owned-schema-contract-v99')
  `, [ordinaryScope])).rows[0].row_count, 2)
})

test('real PostgreSQL rejects UPDATE and DELETE of allowlisted local security events', {
  skip: skipReason,
}, async () => {
  const pool = new Pool({ connectionString: databaseUrl, max: 1 })
  try {
    const eventId = randomUUID()
    const subjectId = `synthetic-subject-${randomUUID()}`
    await pool.query(`
      INSERT INTO poc_local_security_events (
        event_id, event_type, subject_id, actor_subject_id, actor_kind,
        resulting_credential_version, revoked_session_count
      ) VALUES ($1, 'SELF_PASSWORD_CHANGED_V1', $2, $2, 'SELF', 2, 1)
    `, [eventId, subjectId])
    const immutableFailure = (error) => error.message === 'POC local security events are append-only'
    await assert.rejects(pool.query(`
      UPDATE poc_local_security_events SET revoked_session_count = 2 WHERE event_id = $1
    `, [eventId]), immutableFailure)
    await assert.rejects(pool.query(`
      DELETE FROM poc_local_security_events WHERE event_id = $1
    `, [eventId]), immutableFailure)
    assert.equal((await pool.query(`
      SELECT count(*)::integer AS row_count FROM poc_local_security_events WHERE event_id = $1
    `, [eventId])).rows[0].row_count, 1)
  } finally {
    await pool.end()
  }
})
