import { test, mock } from 'node:test'
import assert from 'node:assert/strict'
import {
  createPocK9RefreshTask,
  createPocK9Scheduler,
  loadPocK9SchedulerConfig,
  currentScheduleBoundary,
  nextScheduleBoundary,
} from './poc-k9-scheduler.mjs'
import { createPocStateStore } from './poc-state-store.mjs'

function k9SchedulerDatabase(initialValue) {
  let value = initialValue
  const client = {
    query: mock.fn(async (statement, parameters = []) => {
      if (statement.includes('pg_try_advisory_lock')) return { rows: [{ acquired: true }] }
      if (statement.includes('SELECT value FROM poc_state')) {
        return { rows: value === undefined ? [] : [{ value }] }
      }
      if (statement.includes('INSERT INTO poc_state')) {
        const expectedLastSuccessful = parameters[2]
        const currentLastSuccessful = value?.last_successful_schedule ?? null
        if (currentLastSuccessful !== expectedLastSuccessful) return { rows: [] }
        value = JSON.parse(parameters[1])
        return { rows: [{ last_successful_schedule: value.last_successful_schedule }] }
      }
      if (statement.includes('pg_advisory_unlock')) return { rows: [{ pg_advisory_unlock: true }] }
      throw new Error('Unexpected scheduler test query')
    }),
    release: mock.fn(),
  }
  const pool = {
    query: mock.fn(async () => ({ rows: [] })),
    connect: mock.fn(async () => client),
  }
  return { pool, readValue: () => value }
}

test('K9 Scheduler Config reads correctly', () => {
  const env = {
    POC_K9_SCHEDULER_ENABLED: 'true',
    POC_K9_SYSTEM_SUBJECT_ID: 'hash123',
    POC_K9_WORKSPACE_ID: 'ws123',
    POC_K9_STUDIO_DATABASE_URL: 'postgres://studio-reader@example.test/studio',
    POC_K9_SCHEDULER_TIME_ZONE: 'Asia/Seoul'
  }
  const config = loadPocK9SchedulerConfig(env)
  assert.equal(config.enabled, true)
  assert.equal(config.refreshMode, 'DAILY')
  assert.equal(config.schedule, '02:00 Asia/Seoul')
  assert.equal(config.classificationCeiling, 'INTERNAL')
})

test('K9 Scheduler supports configured daily, hourly, and manual refresh policies', async () => {
  const common = {
    POC_K9_SCHEDULER_ENABLED: 'true',
    POC_K9_SYSTEM_SUBJECT_ID: 'hash123',
    POC_K9_WORKSPACE_ID: 'ws123',
    POC_K9_STUDIO_DATABASE_URL: 'postgres://studio-reader@example.test/studio',
  }
  const daily = loadPocK9SchedulerConfig({
    ...common,
    POC_K9_SCHEDULER_TIME_ZONE: 'UTC',
    POC_K9_SCHEDULE_HOUR: '5',
    POC_K9_SCHEDULE_MINUTE: '30',
    POC_K9_CLASSIFICATION_CEILING: 'CONFIDENTIAL',
  })
  assert.equal(daily.schedule, '05:30 UTC')
  assert.equal(daily.classificationCeiling, 'CONFIDENTIAL')
  assert.equal(currentScheduleBoundary(new Date('2026-08-24T06:00:00.000Z'), 'UTC', 5, 30).toISOString(), '2026-08-24T05:30:00.000Z')

  const hourly = loadPocK9SchedulerConfig({ ...common, POC_K9_REFRESH_MODE: 'HOURLY', POC_K9_SCHEDULE_MINUTE: '15' })
  assert.equal(hourly.enabled, true)
  assert.equal(hourly.schedule, 'hourly at minute 15 Asia/Seoul')
  assert.equal(nextScheduleBoundary(new Date('2026-08-24T10:22:00.000Z'), 'UTC', 2, 15, 'HOURLY').toISOString(), '2026-08-24T11:15:00.000Z')

  const manual = loadPocK9SchedulerConfig({ ...common, POC_K9_REFRESH_MODE: 'MANUAL' })
  assert.equal(manual.enabled, false)
  assert.equal(manual.requested, true)
  const stateStore = { configured: { postgres: true }, runK9Scheduler: mock.fn(async (opts, cb) => cb()) }
  const triggerK9Refresh = mock.fn(async () => ({ status: 'SUCCESS' }))
  const scheduler = createPocK9Scheduler({ config: manual, stateStore, triggerK9Refresh })
  assert.deepEqual(await scheduler.start(), { status: 'idle', mode: 'MANUAL' })
  assert.equal((await scheduler.triggerManual(new Date('2026-08-24T10:22:43.000Z'))).status, 'SUCCESS')
})

test('K9 Scheduler manual trigger runs triggerK9Refresh and fails if no-publish', async () => {
  const config = loadPocK9SchedulerConfig({
    POC_K9_SCHEDULER_ENABLED: 'true',
    POC_K9_SYSTEM_SUBJECT_ID: 'hash123',
    POC_K9_WORKSPACE_ID: 'ws123',
    POC_K9_STUDIO_DATABASE_URL: 'postgres://studio-reader@example.test/studio'
  })
  const stateStore = {
    configured: { postgres: true },
    runK9Scheduler: mock.fn(async (opts, cb) => cb())
  }
  const triggerK9Refresh = mock.fn(async () => ({ status: 'FAILURE', reason: 'Managed policy is missing' }))

  const scheduler = createPocK9Scheduler({ config, stateStore, triggerK9Refresh })

  const result = await scheduler.triggerManual(new Date(Date.UTC(2026, 7, 24, 17, 0, 0)))

  assert.equal(triggerK9Refresh.mock.calls.length, 1)
  assert.deepEqual(triggerK9Refresh.mock.calls[0].arguments[0], {
    systemSubjectId: 'hash123',
    workspaceId: 'ws123'
  })
  assert.equal(result.status, 'FAILURE')
})

test('K9 Scheduler durably records a first failure without a successful boundary', async () => {
  const database = k9SchedulerDatabase()
  const stateStore = createPocStateStore({ databasePool: database.pool })
  const scheduledFor = '2026-08-24T17:00:00.000Z'

  const result = await stateStore.runK9Scheduler({
    lockName: 'datariver:poc:k9-scheduler:v1',
    scheduledFor,
    trigger: 'scheduled',
  }, async () => ({
    status: 'FAILURE',
    reason: 'provider detail must not persist',
    failureCode: 'K9_SEMANTIC_INDEX_FAILED',
  }))

  const receipt = database.readValue()
  assert.equal(result.status, 'failed')
  assert.equal(receipt.last_successful_schedule, null)
  assert.deepEqual(receipt.last_attempt, {
    status: 'FAILURE',
    reason: 'K9_SEMANTIC_INDEX_FAILED',
    scheduled_for: scheduledFor,
    completed_at: receipt.last_attempt.completed_at,
    trigger: 'scheduled',
  })
  assert.ok(Number.isFinite(Date.parse(receipt.last_attempt.completed_at)))
  assert.equal(JSON.stringify(receipt).includes('provider detail'), false)
})

test('K9 refresh task finalizes both PENDING managed graphs when a shared pre-publish stage fails', async () => {
  const semanticFailure = Object.assign(new Error('private embedding provider detail'), {
    code: 'PROVIDER_PRIVATE_ERROR',
  })
  const managedGraphs = {
    recordRefreshFailure: mock.fn(async () => true),
    triggerLineagePublish: mock.fn(),
    triggerGlossaryPublish: mock.fn(),
  }
  const task = createPocK9RefreshTask({
    resolveAuthContext: async () => ({ authorityPin: { subject_id: 'k9' } }),
    currentInventory: async () => [{ urn: 'urn:li:dataset:test' }],
    inventoryProjection: () => ({ generation: 9 }),
    collectLineage: async () => ({ nodes: [], edges: [] }),
    collectMetadata: async () => ({ terms: [] }),
    runtimeIdentity: async () => ({ version: 'test' }),
    ensureSemanticIndex: async () => { throw semanticFailure },
    buildSourceSnapshot: () => { throw new Error('must not run after semantic failure') },
    managedGraphs,
  })

  const result = await task()

  assert.deepEqual(result, {
    status: 'FAILURE',
    reason: 'K9_SEMANTIC_INDEX_FAILED',
    failureCode: 'K9_SEMANTIC_INDEX_FAILED',
    lineage: undefined,
    glossary: undefined,
  })
  assert.deepEqual(managedGraphs.recordRefreshFailure.mock.calls[0].arguments, [
    'K9_SEMANTIC_INDEX_FAILED',
    ['metadata-lineage', 'data-glossary'],
  ])
  assert.equal(managedGraphs.triggerLineagePublish.mock.calls.length, 0)
  assert.equal(managedGraphs.triggerGlossaryPublish.mock.calls.length, 0)
  assert.equal(JSON.stringify(result).includes('private embedding provider detail'), false)
})

test('K9 Scheduler failure preserves and cannot advance the prior successful boundary', async () => {
  const priorSuccessfulSchedule = '2026-08-23T17:00:00.000Z'
  const database = k9SchedulerDatabase({
    version: 1,
    last_successful_schedule: priorSuccessfulSchedule,
    completed_at: '2026-08-23T17:00:01.000Z',
    trigger: 'scheduled',
  })
  const stateStore = createPocStateStore({ databasePool: database.pool })

  await stateStore.runK9Scheduler({
    lockName: 'datariver:poc:k9-scheduler:v1',
    scheduledFor: '2026-08-24T17:00:00.000Z',
    trigger: 'manual',
  }, async () => ({ status: 'FAILURE' }))

  const receipt = database.readValue()
  assert.equal(receipt.last_successful_schedule, priorSuccessfulSchedule)
  assert.equal(receipt.last_attempt.status, 'FAILURE')
  assert.notEqual(receipt.last_successful_schedule, receipt.last_attempt.scheduled_for)
})

test('K9 Scheduler timestamp boundaries - 02:00 KST', () => {
  const timeZone = 'Asia/Seoul'

  const d1 = new Date(Date.UTC(2026, 7, 24, 16, 0, 0))
  const cb1 = currentScheduleBoundary(d1, timeZone)
  assert.equal(cb1.toISOString(), '2026-08-23T17:00:00.000Z')
  const nb1 = nextScheduleBoundary(d1, timeZone)
  assert.equal(nb1.toISOString(), '2026-08-24T17:00:00.000Z')

  const d2 = new Date(Date.UTC(2026, 7, 24, 18, 0, 0))
  const cb2 = currentScheduleBoundary(d2, timeZone)
  assert.equal(cb2.toISOString(), '2026-08-24T17:00:00.000Z')
  const nb2 = nextScheduleBoundary(d2, timeZone)
  assert.equal(nb2.toISOString(), '2026-08-25T17:00:00.000Z')
})

test('K9 Scheduler rejects invalid manual boundaries like midnight', () => {
  const config = loadPocK9SchedulerConfig({
    POC_K9_SCHEDULER_ENABLED: 'true',
    POC_K9_SYSTEM_SUBJECT_ID: 'hash123',
    POC_K9_WORKSPACE_ID: 'ws123',
    POC_K9_STUDIO_DATABASE_URL: 'postgres://studio-reader@example.test/studio'
  })
  const stateStore = {
    configured: { postgres: true },
    runK9Scheduler: mock.fn()
  }
  const triggerK9Refresh = mock.fn()
  const scheduler = createPocK9Scheduler({ config, stateStore, triggerK9Refresh })

  const midnight = new Date(Date.UTC(2026, 7, 24, 15, 0, 0))
  assert.throws(() => scheduler.triggerManual(midnight), /configured refresh boundary/)
})
