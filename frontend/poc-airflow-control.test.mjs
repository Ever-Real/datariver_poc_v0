/* global Response, fetch */
import assert from 'node:assert/strict'
import process from 'node:process'
import { test } from 'node:test'

import {
  AIRFLOW_DAGS,
  AIRFLOW_SYSTEM_ID,
  airflowConnectionProjection,
  collectAllowedAirflowDagStatuses,
  createAirflowControlStore,
} from './poc-airflow-control.mjs'
import { createPocStateStore } from './poc-state-store.mjs'

function response(value, status = 200) {
  return new Response(value === null ? null : JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function testAuthenticator(subjectId = 'airflow-admin') {
  return {
    async authenticate() { return { subjectId, tokenHash: 'f'.repeat(64) } },
    assertOrigin() {},
  }
}

async function configuredStore() {
  const memory = createPocStateStore()
  await memory.write('core', {
    adminSystems: [],
    adminSystemSchemaScopes: [],
    adminMemberships: [],
    adminSystemAssignees: [],
  })
  await memory.write('change-history-access-v1', {
    schema_version: 1,
    active_subject_id: 'airflow-admin',
    users: [{
      subject_id: 'airflow-admin',
      role: 'admin',
      active: true,
      provider_owner_refs: [],
    }],
    system_assignments: [],
  })
  return {
    ...memory,
    configured: { ...memory.configured, postgres: true },
  }
}

async function listen(server) {
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  assert.equal(typeof address, 'object')
  return `http://127.0.0.1:${address.port}`
}

async function close(server) {
  server.closeAllConnections()
  await new Promise((resolvePromise, reject) => server.close((error) => (
    error ? reject(error) : resolvePromise()
  )))
}

test('projects one exact Airflow System identity and secret references without raw credentials', () => {
  const provider = {
    url: 'https://airflow.example.internal',
    username: 'raw-airflow-user',
    password: 'raw-airflow-password',
  }
  const projection = airflowConnectionProjection(provider, 'v2')
  assert.deepEqual(projection, {
    system_id: AIRFLOW_SYSTEM_ID,
    state: 'CONFIGURED',
    base_url: 'https://airflow.example.internal',
    api_mode: 'V2',
    auth: {
      mode: 'SERVER_OWNED_PASSWORD',
      secret_references: ['env:AIRFLOW_USERNAME', 'env:AIRFLOW_PASSWORD'],
    },
  })
  const encoded = JSON.stringify(projection)
  assert.equal(encoded.includes(provider.username), false)
  assert.equal(encoded.includes(provider.password), false)
})

test('collects only the protocol DAG allowlist and one bounded latest run without provider transport', async () => {
  const dagCalls = []
  const runCalls = []
  const inventory = await collectAllowedAirflowDagStatuses(
    'v2',
    async (dagId) => {
      dagCalls.push(dagId)
      if (dagId === 'datariver_catalog_probe') return response(null, 404)
      return response({
        dag_id: dagId,
        is_paused: false,
        next_dagrun: '2026-08-30T00:00:00Z',
        provider_secret: 'ignored',
      })
    },
    async (dagId) => {
      runCalls.push(dagId)
      return response({
        dag_runs: [{
          dag_id: dagId,
          dag_run_id: `scheduled__${dagId}`,
          state: 'success',
          logical_date: '2026-08-29T00:00:00Z',
          conf: { secret: 'ignored' },
        }],
      })
    },
  )
  assert.deepEqual(dagCalls, AIRFLOW_DAGS)
  assert.deepEqual(runCalls, AIRFLOW_DAGS.filter((dagId) => dagId !== 'datariver_catalog_probe'))
  assert.equal(inventory.system_id, AIRFLOW_SYSTEM_ID)
  assert.equal(inventory.items.length, AIRFLOW_DAGS.length)
  assert.deepEqual(Object.keys(inventory.items[0].latest_run).sort(), [
    'dag_id', 'ended_at', 'logical_date', 'run_id', 'started_at', 'state', 'system_id',
  ])
  assert.equal(JSON.stringify(inventory).includes('secret'), false)
})

test('durably binds trigger replay, conflict, failure and reconciliation to subject and fixed System', async () => {
  let instant = Date.parse('2026-08-29T00:00:00Z')
  const stateStore = await configuredStore()
  const control = createAirflowControlStore(stateStore, {
    now: () => new Date(instant += 1000).toISOString(),
  })
  const first = await control.claimTrigger({
    subjectId: 'airflow-admin',
    dagId: 'datariver_quality_dispatch',
    idempotencyKey: 'airflow-trigger-key-0001',
  })
  assert.equal(first.action, 'TRIGGER')
  assert.equal(first.receipt.system_id, AIRFLOW_SYSTEM_ID)
  assert.match(first.receipt.run_id, /^datariver__[0-9a-f]{48}$/)

  const pendingReplay = await control.claimTrigger({
    subjectId: 'airflow-admin',
    dagId: 'datariver_quality_dispatch',
    idempotencyKey: 'airflow-trigger-key-0001',
  })
  assert.equal(pendingReplay.action, 'RECONCILE')

  const accepted = await control.acceptTrigger(first.receipt.operation_id, 'queued')
  assert.equal(accepted.state, 'ACCEPTED')
  const replay = await control.claimTrigger({
    subjectId: 'airflow-admin',
    dagId: 'datariver_quality_dispatch',
    idempotencyKey: 'airflow-trigger-key-0001',
  })
  assert.equal(replay.action, 'REPLAY')
  assert.equal(replay.receipt.run_id, first.receipt.run_id)
  await assert.rejects(
    control.claimTrigger({
      subjectId: 'airflow-admin',
      dagId: 'datariver_catalog_sync',
      idempotencyKey: 'airflow-trigger-key-0001',
    }),
    { code: 'AIRFLOW_IDEMPOTENCY_CONFLICT' },
  )
  await assert.rejects(
    control.claimDagTransition({
      subjectId: 'airflow-admin',
      dagId: 'datariver_quality_dispatch',
      idempotencyKey: 'airflow-trigger-key-0001',
      operation: 'PAUSE',
    }),
    { code: 'AIRFLOW_IDEMPOTENCY_CONFLICT' },
  )

  const uncertain = await control.claimTrigger({
    subjectId: 'airflow-admin',
    dagId: 'datariver_catalog_sync',
    idempotencyKey: 'airflow-trigger-key-0002',
  })
  const reconcile = await control.requireReconciliation(
    uncertain.receipt.operation_id,
    'AIRFLOW_TRIGGER_OUTCOME_UNKNOWN',
  )
  assert.equal(reconcile.state, 'RECONCILE_REQUIRED')
  assert.equal((await control.claimTrigger({
    subjectId: 'airflow-admin',
    dagId: 'datariver_catalog_sync',
    idempotencyKey: 'airflow-trigger-key-0002',
  })).action, 'RECONCILE')

  const failed = await control.claimTrigger({
    subjectId: 'airflow-admin',
    dagId: 'datariver_catalog_probe',
    idempotencyKey: 'airflow-trigger-key-0003',
  })
  await control.failTrigger(failed.receipt.operation_id, 'AIRFLOW_TRIGGER_REJECTED')
  assert.equal((await control.claimTrigger({
    subjectId: 'airflow-admin',
    dagId: 'datariver_catalog_probe',
    idempotencyKey: 'airflow-trigger-key-0003',
  })).receipt.state, 'FAILED')
  const pause = await control.claimDagTransition({
    subjectId: 'airflow-admin',
    dagId: 'datariver_quality_dispatch',
    idempotencyKey: 'airflow-pause-key-0001',
    operation: 'PAUSE',
  })
  assert.equal(pause.action, 'TRANSITION')
  assert.equal(pause.receipt.target_paused, true)
  assert.equal(pause.receipt.run_id, null)
  await control.acceptDagTransition(pause.receipt.operation_id)
  assert.equal((await control.claimDagTransition({
    subjectId: 'airflow-admin',
    dagId: 'datariver_quality_dispatch',
    idempotencyKey: 'airflow-pause-key-0001',
    operation: 'PAUSE',
  })).action, 'REPLAY')
  const durable = await stateStore.read('airflow-control-v1')
  assert.equal(JSON.stringify(durable.value).includes('airflow-trigger-key'), false)
  assert.equal(durable.value.receipts.length, 4)
})

test('denies arbitrary DAGs and replays accepted triggers without provider contact', async () => {
  Object.assign(process.env, {
    POC_ENV_FILE: 'poc-airflow-control.test.env.missing',
    POC_DATABASE_URL: '',
    POC_POSTGRES_HOST: '',
    POC_REDIS_URL: '',
  })
  const { createPocServer } = await import('./poc-server.mjs?airflow-control-route-contract')
  const stateStore = await configuredStore()
  const calls = { connection: 0, inventory: 0, readRun: 0, setPaused: 0, trigger: 0 }
  const provider = {
    async connection() {
      calls.connection += 1
      return airflowConnectionProjection({ url: 'https://airflow.example.internal' }, 'v2')
    },
    async inventory() {
      calls.inventory += 1
      throw new Error('inventory must not be called by deny/replay tests')
    },
    async readRun(dagId, runId) {
      calls.readRun += 1
      if (dagId !== 'datariver_catalog_sync') throw new Error('accepted replay must not reconcile')
      return {
        system_id: AIRFLOW_SYSTEM_ID,
        dag_id: dagId,
        run_id: runId,
        state: 'RUNNING',
        logical_date: null,
        started_at: null,
        ended_at: null,
      }
    },
    async setPaused(dagId, paused) {
      calls.setPaused += 1
      return {
        system_id: AIRFLOW_SYSTEM_ID,
        dag_id: dagId,
        state: 'READY',
        paused,
        next_run_at: null,
        last_parsed_at: null,
      }
    },
    async trigger(dagId, runId) {
      calls.trigger += 1
      if (dagId === 'datariver_catalog_sync') {
        throw Object.assign(new Error('sanitized unknown outcome'), {
          statusCode: 502,
          code: 'AIRFLOW_TRIGGER_OUTCOME_UNKNOWN',
          outcomeUnknown: true,
        })
      }
      if (dagId === 'datariver_catalog_probe') {
        throw Object.assign(new Error('sanitized rejection'), {
          statusCode: 502,
          code: 'AIRFLOW_TRIGGER_REJECTED',
        })
      }
      return {
        system_id: AIRFLOW_SYSTEM_ID,
        dag_id: dagId,
        run_id: runId,
        state: 'QUEUED',
        logical_date: null,
        started_at: null,
        ended_at: null,
      }
    },
  }
  const server = createPocServer({
    stateStore,
    authenticator: testAuthenticator(),
    airflowProvider: provider,
  })
  const origin = await listen(server)
  try {
    const arbitrary = await fetch(`${origin}/poc-api/airflow/dags/arbitrary/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'airflow-deny-key-0001' },
      body: JSON.stringify({ secret: 'must-not-be-parsed' }),
    })
    assert.equal(arbitrary.status, 400)
    assert.equal((await arbitrary.json()).code, 'DAG_NOT_ALLOWED')
    assert.deepEqual(calls, { connection: 0, inventory: 0, readRun: 0, setPaused: 0, trigger: 0 })

    const headers = { 'Content-Type': 'application/json', 'Idempotency-Key': 'airflow-replay-key-0001' }
    const first = await fetch(`${origin}/poc-api/airflow/dags/datariver_quality_dispatch/runs`, {
      method: 'POST', headers, body: '{}',
    })
    assert.equal(first.status, 202)
    const firstBody = await first.json()
    assert.equal(firstBody.receipt.system_id, AIRFLOW_SYSTEM_ID)
    const replay = await fetch(`${origin}/poc-api/airflow/dags/datariver_quality_dispatch/runs`, {
      method: 'POST', headers, body: '{}',
    })
    assert.equal(replay.status, 200)
    assert.equal((await replay.json()).replayed, true)
    assert.equal(calls.trigger, 1)
    assert.equal(calls.readRun, 0)

    const uncertainHeaders = {
      'Content-Type': 'application/json',
      'Idempotency-Key': 'airflow-reconcile-key-0001',
    }
    const uncertain = await fetch(`${origin}/poc-api/airflow/dags/datariver_catalog_sync/runs`, {
      method: 'POST', headers: uncertainHeaders, body: '{}',
    })
    assert.equal(uncertain.status, 502)
    assert.equal((await uncertain.json()).code, 'AIRFLOW_TRIGGER_OUTCOME_UNKNOWN')
    const reconciled = await fetch(`${origin}/poc-api/airflow/dags/datariver_catalog_sync/runs`, {
      method: 'POST', headers: uncertainHeaders, body: '{}',
    })
    assert.equal(reconciled.status, 200)
    assert.equal((await reconciled.json()).reconciled, true)
    assert.equal(calls.trigger, 2)
    assert.equal(calls.readRun, 1)

    const failureHeaders = {
      'Content-Type': 'application/json',
      'Idempotency-Key': 'airflow-failure-key-0001',
    }
    const failed = await fetch(`${origin}/poc-api/airflow/dags/datariver_catalog_probe/runs`, {
      method: 'POST', headers: failureHeaders, body: '{}',
    })
    assert.equal(failed.status, 502)
    const failureReplay = await fetch(`${origin}/poc-api/airflow/dags/datariver_catalog_probe/runs`, {
      method: 'POST', headers: failureHeaders, body: '{}',
    })
    assert.equal(failureReplay.status, 502)
    assert.equal((await failureReplay.json()).code, 'AIRFLOW_TRIGGER_REJECTED')
    assert.equal(calls.trigger, 3)
    assert.equal(calls.readRun, 1)

    const transition = await fetch(`${origin}/poc-api/airflow/dags/datariver_quality_dispatch`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'airflow-pause-key-0001' },
      body: JSON.stringify({ action: 'PAUSE' }),
    })
    assert.equal(transition.status, 202)
    assert.equal((await transition.json()).dag.paused, true)
    assert.equal(calls.setPaused, 1)
    const transitionReplay = await fetch(`${origin}/poc-api/airflow/dags/datariver_quality_dispatch`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'airflow-pause-key-0001' },
      body: JSON.stringify({ action: 'PAUSE' }),
    })
    assert.equal(transitionReplay.status, 200)
    assert.equal((await transitionReplay.json()).replayed, true)
    assert.equal(calls.setPaused, 1)
    const transitionTamper = await fetch(`${origin}/poc-api/airflow/dags/datariver_quality_dispatch`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'airflow-pause-key-0001' },
      body: JSON.stringify({ action: 'UNPAUSE' }),
    })
    assert.equal(transitionTamper.status, 409)
    assert.equal((await transitionTamper.json()).code, 'AIRFLOW_IDEMPOTENCY_CONFLICT')
    assert.equal(calls.setPaused, 1)
  } finally {
    await close(server)
    await stateStore.close()
  }
})
