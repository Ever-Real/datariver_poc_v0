import assert from 'node:assert/strict'
import process from 'node:process'
import test from 'node:test'
import pg from 'pg'

import {
  AIRFLOW_CONTROL_SCOPE,
  createAirflowControlStore,
} from './poc-airflow-control.mjs'
import { createPocStateStore } from './poc-state-store.mjs'

const { Pool } = pg
const databaseUrl = process.env.POC_AIRFLOW_POSTGRES_TEST_URL?.trim()
const isolated = process.env.POC_AIRFLOW_POSTGRES_TEST_CONFIRM_ISOLATED === '1'
const triggerKey = 'airflow-postgres-trigger-restart-0001'
const pauseKey = 'airflow-postgres-pause-restart-0001'
const skipReason = databaseUrl && isolated
  ? false
  : 'requires POC_AIRFLOW_POSTGRES_TEST_URL and POC_AIRFLOW_POSTGRES_TEST_CONFIRM_ISOLATED=1'

async function openProductStore() {
  const pool = new Pool({ connectionString: databaseUrl, max: 2 })
  const store = createPocStateStore({ databasePool: pool })
  assert.equal(store.configured.postgres, true)
  await store.read(AIRFLOW_CONTROL_SCOPE)
  return { pool, store, control: createAirflowControlStore(store) }
}

async function closeProductStore(instance) {
  await instance.store.close()
  await instance.pool.end()
}

test('real PostgreSQL preserves trigger and pause claim reconciliation and replay across store restarts', {
  skip: skipReason,
}, async (context) => {
  context.after(async () => {
    const cleanupPool = new Pool({ connectionString: databaseUrl, max: 1 })
    await cleanupPool.query('DELETE FROM poc_state WHERE scope = $1', [AIRFLOW_CONTROL_SCOPE])
      .catch(() => undefined)
    await cleanupPool.end()
  })
  const setupPool = new Pool({ connectionString: databaseUrl, max: 1 })
  await setupPool.query('CREATE EXTENSION IF NOT EXISTS vector')
  await setupPool.end()

  const first = await openProductStore()
  try {
    await first.pool.query('DELETE FROM poc_state WHERE scope = $1', [AIRFLOW_CONTROL_SCOPE])
    const trigger = await first.control.claimTrigger({
      subjectId: 'airflow-postgres-restart-admin',
      dagId: 'datariver_quality_dispatch',
      idempotencyKey: triggerKey,
    })
    const pause = await first.control.claimDagTransition({
      subjectId: 'airflow-postgres-restart-admin',
      dagId: 'datariver_quality_dispatch',
      idempotencyKey: pauseKey,
      operation: 'PAUSE',
    })
    assert.equal(trigger.action, 'TRIGGER')
    assert.equal(pause.action, 'TRANSITION')
  } finally {
    await closeProductStore(first)
  }

  const second = await openProductStore()
  try {
    const trigger = await second.control.claimTrigger({
      subjectId: 'airflow-postgres-restart-admin',
      dagId: 'datariver_quality_dispatch',
      idempotencyKey: triggerKey,
    })
    const pause = await second.control.claimDagTransition({
      subjectId: 'airflow-postgres-restart-admin',
      dagId: 'datariver_quality_dispatch',
      idempotencyKey: pauseKey,
      operation: 'PAUSE',
    })
    assert.equal(trigger.action, 'RECONCILE')
    assert.equal(pause.action, 'RECONCILE')
    await second.control.acceptTrigger(trigger.receipt.operation_id, 'QUEUED')
    await second.control.acceptDagTransition(pause.receipt.operation_id)
  } finally {
    await closeProductStore(second)
  }

  const third = await openProductStore()
  try {
    const trigger = await third.control.claimTrigger({
      subjectId: 'airflow-postgres-restart-admin',
      dagId: 'datariver_quality_dispatch',
      idempotencyKey: triggerKey,
    })
    const pause = await third.control.claimDagTransition({
      subjectId: 'airflow-postgres-restart-admin',
      dagId: 'datariver_quality_dispatch',
      idempotencyKey: pauseKey,
      operation: 'PAUSE',
    })
    assert.equal(trigger.action, 'REPLAY')
    assert.equal(pause.action, 'REPLAY')
    assert.equal(trigger.receipt.state, 'ACCEPTED')
    assert.equal(pause.receipt.state, 'ACCEPTED')
    const persisted = await third.store.read(AIRFLOW_CONTROL_SCOPE)
    assert.equal(JSON.stringify(persisted.value).includes(triggerKey), false)
    assert.equal(JSON.stringify(persisted.value).includes(pauseKey), false)
  } finally {
    await third.pool.query('DELETE FROM poc_state WHERE scope = $1', [AIRFLOW_CONTROL_SCOPE])
    await closeProductStore(third)
  }
})
