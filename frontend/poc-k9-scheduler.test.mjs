import { test, mock } from 'node:test'
import assert from 'node:assert/strict'
import {
  createPocK9RefreshTask,
  createPocK9Scheduler,
  k9SemanticReconciliationGeneration,
  loadPocK9SchedulerConfig,
  currentScheduleBoundary,
  nextScheduleBoundary,
} from './poc-k9-scheduler.mjs'
import {
  K9_METADATA_SOURCE_PROFILE_CONTRACT,
  sanitizeK9MetadataSourceProfile,
} from './poc-k9-metadata-collection.mjs'
import { createPocStateStore } from './poc-state-store.mjs'

function metadataSourceProfile(overrides = {}) {
  return sanitizeK9MetadataSourceProfile({
    contract: K9_METADATA_SOURCE_PROFILE_CONTRACT,
    source_generation: 'a'.repeat(64),
    inventory: { total_dataset_count: 2, table_count: 2, total_column_count: 3, non_empty: true },
    glossary_scroll: {
      provider_reported_total: 2,
      pages_fetched: 1,
      entities_fetched: 2,
      unique_term_count: 1,
      duplicate_term_observation_count: 1,
      cursor_progression_status: 'FAILED',
    },
    identity_resolution: {
      exact_duplicate_observation_count: 1,
      failure: {
        locus: 'DUPLICATE_TERM_IDENTITY',
        classification: 'EXACT_DUPLICATE',
        identity_hash: 'b'.repeat(64),
        shape_hash: 'c'.repeat(64),
        page_number: 1,
        ordinal: 1,
      },
    },
    ...overrides,
  })
}

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
        const expectedReconciliationGeneration = parameters[3] ?? null
        const currentLastSuccessful = value?.last_successful_schedule ?? null
        const currentReconciliationGeneration = value?.last_successful_reconciliation_generation ?? null
        if (currentLastSuccessful !== expectedLastSuccessful
          || currentReconciliationGeneration !== expectedReconciliationGeneration) return { rows: [] }
        value = JSON.parse(parameters[1])
        return { rows: [{
          last_successful_schedule: value.last_successful_schedule,
          last_successful_reconciliation_generation:
            value.last_successful_reconciliation_generation ?? null,
        }] }
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

function k9RefreshFixture(overrides = {}) {
  const { managedGraphs: managedGraphOverrides, ...dependencyOverrides } = overrides
  const managedGraphs = {
    recordRefreshFailure: mock.fn(async () => true),
    triggerLineagePublish: mock.fn(async () => ({ status: 'SUCCESS' })),
    triggerGlossaryPublish: mock.fn(async () => ({ status: 'SUCCESS' })),
    ...managedGraphOverrides,
  }
  const dependencies = {
    resolveAuthContext: mock.fn(async () => ({ authorityPin: { subject_id: 'k9' } })),
    currentInventory: mock.fn(async () => [{ urn: 'urn:li:dataset:test' }]),
    inventoryProjection: mock.fn(async () => ({ source_generation: 'a'.repeat(64) })),
    collectLineage: mock.fn(async () => ({ nodes: [], edges: [] })),
    collectMetadata: mock.fn(async () => ({ terms: [] })),
    runtimeIdentity: mock.fn(async () => ({ version: '1.0.0' })),
    ensureSemanticIndex: mock.fn(async () => ({ generation: 'a'.repeat(64), bindingHash: 'b'.repeat(64) })),
    sourceFingerprint: mock.fn(() => ({ source_fingerprint_id: 'd'.repeat(64) })),
    buildSourceSnapshot: mock.fn(() => ({ source_snapshot_id: 'c'.repeat(64) })),
    sourceRetryWait: mock.fn(async () => undefined),
    managedGraphs,
    ...dependencyOverrides,
  }
  return { task: createPocK9RefreshTask(dependencies), dependencies, managedGraphs }
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

test('K9 Scheduler exposes only the currently active retry attempt', async () => {
  const config = loadPocK9SchedulerConfig({
    POC_K9_SCHEDULER_ENABLED: 'true',
    POC_K9_SYSTEM_SUBJECT_ID: 'hash123',
    POC_K9_WORKSPACE_ID: 'ws123',
    POC_K9_STUDIO_DATABASE_URL: 'postgres://studio-reader@example.test/studio',
  })
  let releaseRefresh
  const refreshGate = new Promise((resolve) => { releaseRefresh = resolve })
  const stateStore = {
    configured: { postgres: true },
    runK9Scheduler: mock.fn(async (_command, task) => task()),
  }
  const scheduler = createPocK9Scheduler({
    config,
    stateStore,
    triggerK9Refresh: async () => {
      await refreshGate
      return { status: 'SUCCESS' }
    },
    setTimer: () => 1,
  })

  await scheduler.start()
  assert.deepEqual(scheduler.currentAttempt(), {
    status: 'RUNNING',
    scheduled_for: scheduler.currentAttempt().scheduled_for,
    trigger: 'scheduled',
  })
  assert.ok(Number.isFinite(Date.parse(scheduler.currentAttempt().scheduled_for)))

  releaseRefresh()
  await scheduler.stop()
  assert.equal(scheduler.currentAttempt(), null)
})

test('K9 semantic reconciliation detects only unaligned canonical managed graph generations', () => {
  const semanticGeneration = 'b'.repeat(64)
  const graph = (managedIntent, generation = semanticGeneration) => ({
    managed_intent: managedIntent,
    active_release_pointer: `k9_${managedIntent}`,
    active_manifest: { source_snapshot: { catalog_generation: generation } },
  })
  const aligned = [graph('metadata-lineage'), graph('data-glossary')]

  assert.equal(k9SemanticReconciliationGeneration(semanticGeneration, aligned), null)
  assert.equal(k9SemanticReconciliationGeneration(undefined, aligned), null)
  assert.equal(k9SemanticReconciliationGeneration(semanticGeneration, [
    graph('metadata-lineage', 'a'.repeat(64)),
    graph('data-glossary', 'a'.repeat(64)),
  ]), semanticGeneration)
  assert.equal(k9SemanticReconciliationGeneration(semanticGeneration, [graph('metadata-lineage')]), semanticGeneration)
})

test('K9 startup reconciles a newer semantic generation at an already successful daily boundary', async () => {
  const scheduledFor = '2026-08-30T02:00:00.000Z'
  const oldGeneration = 'a'.repeat(64)
  const newGeneration = 'b'.repeat(64)
  const database = k9SchedulerDatabase({
    version: 1,
    last_successful_schedule: scheduledFor,
    last_successful_reconciliation_generation: oldGeneration,
    completed_at: '2026-08-30T02:01:00.000Z',
    trigger: 'scheduled',
  })
  const config = loadPocK9SchedulerConfig({
    POC_K9_SCHEDULER_ENABLED: 'true',
    POC_K9_SYSTEM_SUBJECT_ID: 'hash123',
    POC_K9_WORKSPACE_ID: 'ws123',
    POC_K9_SCHEDULER_TIME_ZONE: 'UTC',
    POC_K9_SCHEDULE_HOUR: '2',
  })
  const triggerK9Refresh = mock.fn(async () => ({ status: 'SUCCESS' }))
  const scheduler = createPocK9Scheduler({
    config,
    stateStore: createPocStateStore({ databasePool: database.pool }),
    triggerK9Refresh,
    resolveReconciliationGeneration: mock.fn(async () => newGeneration),
    clock: () => new Date('2026-08-30T03:00:00.000Z'),
    setTimer: () => 1,
  })

  await scheduler.start()
  await scheduler.stop()

  assert.equal(triggerK9Refresh.mock.calls.length, 1)
  assert.equal(database.readValue().last_successful_schedule, scheduledFor)
  assert.equal(database.readValue().last_successful_reconciliation_generation, newGeneration)
  assert.equal(database.readValue().last_attempt.reconciliation_generation, newGeneration)
})

test('K9 startup performs no graph rebuild when semantic and graph generations are aligned', async () => {
  const scheduledFor = '2026-08-30T02:00:00.000Z'
  const database = k9SchedulerDatabase({
    version: 1,
    last_successful_schedule: scheduledFor,
    completed_at: '2026-08-30T02:01:00.000Z',
    trigger: 'scheduled',
  })
  const config = loadPocK9SchedulerConfig({
    POC_K9_SCHEDULER_ENABLED: 'true',
    POC_K9_SYSTEM_SUBJECT_ID: 'hash123',
    POC_K9_WORKSPACE_ID: 'ws123',
    POC_K9_SCHEDULER_TIME_ZONE: 'UTC',
    POC_K9_SCHEDULE_HOUR: '2',
  })
  const triggerK9Refresh = mock.fn(async () => ({ status: 'SUCCESS' }))
  const scheduler = createPocK9Scheduler({
    config,
    stateStore: createPocStateStore({ databasePool: database.pool }),
    triggerK9Refresh,
    resolveReconciliationGeneration: mock.fn(async () => null),
    clock: () => new Date('2026-08-30T03:00:00.000Z'),
    setTimer: () => 1,
  })

  await scheduler.start()
  await scheduler.stop()

  assert.equal(triggerK9Refresh.mock.calls.length, 0)
  assert.equal(database.readValue().last_successful_schedule, scheduledFor)
})

test('K9 same-generation concurrent reconciliation coalesces and the next daily boundary still runs', async () => {
  const firstBoundary = '2026-08-30T02:00:00.000Z'
  const nextBoundary = '2026-08-31T02:00:00.000Z'
  const generation = 'c'.repeat(64)
  const database = k9SchedulerDatabase({
    version: 1,
    last_successful_schedule: firstBoundary,
    completed_at: '2026-08-30T02:01:00.000Z',
    trigger: 'scheduled',
  })
  const stateStore = createPocStateStore({ databasePool: database.pool })
  const config = loadPocK9SchedulerConfig({
    POC_K9_SCHEDULER_ENABLED: 'true',
    POC_K9_SYSTEM_SUBJECT_ID: 'hash123',
    POC_K9_WORKSPACE_ID: 'ws123',
    POC_K9_SCHEDULER_TIME_ZONE: 'UTC',
    POC_K9_SCHEDULE_HOUR: '2',
  })
  let releaseRefresh
  const refreshGate = new Promise((resolve) => { releaseRefresh = resolve })
  const triggerK9Refresh = mock.fn(async () => {
    if (triggerK9Refresh.mock.calls.length === 1) await refreshGate
    return { status: 'SUCCESS' }
  })
  const scheduler = createPocK9Scheduler({
    config,
    stateStore,
    triggerK9Refresh,
    resolveReconciliationGeneration: async (candidate) => candidate,
    clock: () => new Date('2026-08-30T03:00:00.000Z'),
    setTimer: () => 1,
  })

  const first = scheduler.reconcileSemanticGeneration(generation)
  const concurrent = scheduler.reconcileSemanticGeneration(generation)
  releaseRefresh()
  await Promise.all([first, concurrent])
  const replay = await scheduler.reconcileSemanticGeneration(generation)

  assert.equal(triggerK9Refresh.mock.calls.length, 1)
  assert.equal(replay.status, 'already_completed')

  const nextScheduler = createPocK9Scheduler({
    config,
    stateStore,
    triggerK9Refresh,
    resolveReconciliationGeneration: async () => null,
    clock: () => new Date('2026-08-31T03:00:00.000Z'),
    setTimer: () => 1,
  })
  await nextScheduler.start()
  await nextScheduler.stop()

  assert.equal(triggerK9Refresh.mock.calls.length, 2)
  assert.equal(database.readValue().last_successful_schedule, nextBoundary)
})

test('K9 collapses distinct pending semantic generations to the latest and stop awaits it', async () => {
  const scheduledFor = '2026-08-30T02:00:00.000Z'
  const generationB = 'c'.repeat(64)
  const generationC = 'd'.repeat(64)
  const database = k9SchedulerDatabase()
  const persistentStateStore = createPocStateStore({ databasePool: database.pool })
  const commands = []
  const stateStore = {
    ...persistentStateStore,
    runK9Scheduler: mock.fn(async (command, task) => {
      commands.push(command)
      return persistentStateStore.runK9Scheduler(command, task)
    }),
  }
  const config = loadPocK9SchedulerConfig({
    POC_K9_SCHEDULER_ENABLED: 'true',
    POC_K9_SYSTEM_SUBJECT_ID: 'hash123',
    POC_K9_WORKSPACE_ID: 'ws123',
    POC_K9_SCHEDULER_TIME_ZONE: 'UTC',
    POC_K9_SCHEDULE_HOUR: '2',
  })
  let releaseActiveRun
  let releaseFollowUp
  let markFollowUpStarted
  let activeSemanticGeneration = null
  const activeRunGate = new Promise((resolve) => { releaseActiveRun = resolve })
  const followUpGate = new Promise((resolve) => { releaseFollowUp = resolve })
  const followUpStarted = new Promise((resolve) => { markFollowUpStarted = resolve })
  const triggerK9Refresh = mock.fn(async () => {
    if (triggerK9Refresh.mock.calls.length === 1) await activeRunGate
    else {
      markFollowUpStarted()
      await followUpGate
    }
    return { status: 'SUCCESS' }
  })
  const resolveReconciliationGeneration = mock.fn(async (candidate) => (
    candidate || activeSemanticGeneration
  ))
  const scheduler = createPocK9Scheduler({
    config,
    stateStore,
    triggerK9Refresh,
    resolveReconciliationGeneration,
    clock: () => new Date('2026-08-30T03:00:00.000Z'),
    setTimer: () => 1,
  })

  await scheduler.start()
  activeSemanticGeneration = generationB
  const generationBRequest = scheduler.reconcileSemanticGeneration(generationB)
  activeSemanticGeneration = generationC
  const firstGenerationCRequest = scheduler.reconcileSemanticGeneration(generationC)
  const duplicateGenerationCRequest = scheduler.reconcileSemanticGeneration(generationC)
  await Promise.resolve()

  let stopSettled = false
  const stopping = scheduler.stop().then(() => { stopSettled = true })
  await Promise.resolve()
  assert.equal(stopSettled, false)

  releaseActiveRun()
  await followUpStarted
  assert.equal(stopSettled, false)

  releaseFollowUp()
  await Promise.all([
    generationBRequest,
    firstGenerationCRequest,
    duplicateGenerationCRequest,
    stopping,
  ])

  assert.equal(triggerK9Refresh.mock.calls.length, 2)
  assert.deepEqual(commands.map((command) => command.reconciliationGeneration || null), [null, generationC])
  assert.deepEqual(commands.map((command) => command.scheduledFor), [scheduledFor, scheduledFor])
  assert.equal(database.readValue().last_successful_reconciliation_generation, generationC)
  assert.deepEqual(resolveReconciliationGeneration.mock.calls.at(-1).arguments, [])
  assert.equal(stopSettled, true)
})

test('K9 reconciliation failure preserves the successful daily schedule and prior generation receipt', async () => {
  const scheduledFor = '2026-08-30T02:00:00.000Z'
  const oldGeneration = 'd'.repeat(64)
  const newGeneration = 'e'.repeat(64)
  const database = k9SchedulerDatabase({
    version: 1,
    last_successful_schedule: scheduledFor,
    last_successful_reconciliation_generation: oldGeneration,
    completed_at: '2026-08-30T02:01:00.000Z',
    trigger: 'scheduled',
  })
  const stateStore = createPocStateStore({ databasePool: database.pool })

  const result = await stateStore.runK9Scheduler({
    lockName: 'datariver:poc:k9-scheduler:v1',
    scheduledFor,
    trigger: 'scheduled',
    reconciliationGeneration: newGeneration,
  }, async () => ({ status: 'FAILURE', failureCode: 'K9_SEMANTIC_INDEX_FAILED' }))

  assert.equal(result.status, 'failed')
  assert.equal(database.readValue().last_successful_schedule, scheduledFor)
  assert.equal(database.readValue().last_successful_reconciliation_generation, oldGeneration)
  assert.equal(database.readValue().last_attempt.reason, 'K9_SEMANTIC_INDEX_FAILED')
  assert.equal(database.readValue().last_attempt.reconciliation_generation, newGeneration)
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

test('K9 Scheduler durably records only bounded DataHub source diagnostics', async () => {
  const database = k9SchedulerDatabase()
  const stateStore = createPocStateStore({ databasePool: database.pool })
  const scheduledFor = '2026-08-24T17:00:00.000Z'

  await stateStore.runK9Scheduler({
    lockName: 'datariver:poc:k9-scheduler:v1', scheduledFor, trigger: 'scheduled',
  }, async () => ({
    status: 'FAILURE',
    reason: 'private provider body with urn:li:dataset:secret',
    failureCode: 'K9_DATAHUB_SOURCE_FAILED',
    failureStage: 'LINEAGE_COLLECTION',
    failureDetailCode: 'GRAPHQL',
  }))

  assert.deepEqual(database.readValue().last_attempt, {
    status: 'FAILURE',
    reason: 'K9_DATAHUB_SOURCE_FAILED',
    failure_stage: 'LINEAGE_COLLECTION',
    failure_detail_code: 'GRAPHQL',
    scheduled_for: scheduledFor,
    completed_at: database.readValue().last_attempt.completed_at,
    trigger: 'scheduled',
  })
  assert.equal(JSON.stringify(database.readValue()).includes('urn:li:'), false)
  assert.equal(JSON.stringify(database.readValue()).includes('private provider body'), false)
})

test('K9 source inventory contract failure is terminal and preserves semantic and graph LKG', async () => {
  const inventoryFailure = Object.assign(new Error('provider body must not persist'), {
    code: 'PREP_DATAHUB_INVENTORY_CONTRACT_FAILED',
  })
  const { task, dependencies, managedGraphs } = k9RefreshFixture({
    currentInventory: mock.fn(async () => { throw inventoryFailure }),
  })

  const result = await task()

  assert.deepEqual(result, {
    status: 'FAILURE',
    reason: 'K9_DATAHUB_SOURCE_FAILED',
    failureCode: 'K9_DATAHUB_SOURCE_FAILED',
    failureStage: 'INVENTORY',
    failureDetailCode: 'CONTRACT',
    lineage: undefined,
    glossary: undefined,
  })
  assert.deepEqual(managedGraphs.recordRefreshFailure.mock.calls[0].arguments, [
    'K9_DATAHUB_SOURCE_FAILED',
    ['metadata-lineage', 'data-glossary'],
    { failureStage: 'INVENTORY', failureDetailCode: 'CONTRACT' },
  ])
  assert.equal(dependencies.currentInventory.mock.calls.length, 1)
  assert.equal(dependencies.sourceRetryWait.mock.calls.length, 0)
  assert.equal(dependencies.ensureSemanticIndex.mock.calls.length, 0)
  assert.equal(managedGraphs.triggerLineagePublish.mock.calls.length, 0)
  assert.equal(managedGraphs.triggerGlossaryPublish.mock.calls.length, 0)
  assert.equal(JSON.stringify(result).includes('provider body'), false)
})

test('K9 source inventory projection failure has its own deterministic contract stage', async () => {
  const { task, dependencies } = k9RefreshFixture({
    inventoryProjection: mock.fn(async () => null),
  })

  const result = await task()

  assert.equal(result.failureStage, 'INVENTORY_PROJECTION')
  assert.equal(result.failureDetailCode, 'CONTRACT')
  assert.equal(dependencies.inventoryProjection.mock.calls.length, 1)
  assert.equal(dependencies.sourceRetryWait.mock.calls.length, 0)
  assert.equal(dependencies.ensureSemanticIndex.mock.calls.length, 0)
})

test('K9 source lineage GraphQL failure retains its exact non-retryable substage', async () => {
  const { task, dependencies, managedGraphs } = k9RefreshFixture({
    collectLineage: mock.fn(async () => {
      throw Object.assign(new Error('private GraphQL provider body'), { providerFailureKind: 'GRAPHQL' })
    }),
  })

  const result = await task()

  assert.equal(result.failureStage, 'LINEAGE_COLLECTION')
  assert.equal(result.failureDetailCode, 'GRAPHQL')
  assert.equal(dependencies.collectLineage.mock.calls.length, 1)
  assert.equal(dependencies.sourceRetryWait.mock.calls.length, 0)
  assert.deepEqual(managedGraphs.recordRefreshFailure.mock.calls[0].arguments[2], {
    failureStage: 'LINEAGE_COLLECTION', failureDetailCode: 'GRAPHQL',
  })
})

test('K9 source metadata GraphQL failure retains its exact non-retryable substage', async () => {
  const { task, dependencies } = k9RefreshFixture({
    collectMetadata: mock.fn(async () => {
      throw Object.assign(new Error('private glossary provider body'), { providerFailureKind: 'GRAPHQL' })
    }),
  })

  const result = await task()

  assert.equal(result.failureStage, 'METADATA_COLLECTION')
  assert.equal(result.failureDetailCode, 'GRAPHQL')
  assert.equal(dependencies.collectMetadata.mock.calls.length, 1)
  assert.equal(dependencies.sourceRetryWait.mock.calls.length, 0)
})

test('K9 source metadata invariant persists only its bounded local detail and preserves LKG promotion order', async () => {
  const profile = metadataSourceProfile()
  const { task, dependencies, managedGraphs } = k9RefreshFixture({
    collectMetadata: mock.fn(async () => {
      throw Object.assign(new Error('raw urn:li:tag:private and provider body'), {
        k9SourceFailureDetailCode: 'DUPLICATE_TERM_IDENTITY',
        k9MetadataSourceProfile: profile,
      })
    }),
  })

  const result = await task()

  assert.deepEqual(result, {
    status: 'FAILURE',
    reason: 'K9_DATAHUB_SOURCE_FAILED',
    failureCode: 'K9_DATAHUB_SOURCE_FAILED',
    failureStage: 'METADATA_COLLECTION',
    failureDetailCode: 'DUPLICATE_TERM_IDENTITY',
    metadataProfile: profile,
    lineage: undefined,
    glossary: undefined,
  })
  assert.deepEqual(managedGraphs.recordRefreshFailure.mock.calls[0].arguments, [
    'K9_DATAHUB_SOURCE_FAILED',
    ['metadata-lineage', 'data-glossary'],
    {
      failureStage: 'METADATA_COLLECTION',
      failureDetailCode: 'DUPLICATE_TERM_IDENTITY',
      metadataProfile: profile,
    },
  ])
  assert.equal(dependencies.ensureSemanticIndex.mock.calls.length, 0)
  assert.equal(managedGraphs.triggerLineagePublish.mock.calls.length, 0)
  assert.equal(managedGraphs.triggerGlossaryPublish.mock.calls.length, 0)
  assert.equal(JSON.stringify(result).includes('urn:li:'), false)
  assert.equal(JSON.stringify(managedGraphs.recordRefreshFailure.mock.calls).includes('provider body'), false)
})

test('K9 source runtime identity contract failure is deterministic and never retried', async () => {
  const { task, dependencies } = k9RefreshFixture({
    runtimeIdentity: mock.fn(async () => ({ commit: 'missing-version' })),
  })

  const result = await task()

  assert.equal(result.failureStage, 'RUNTIME_IDENTITY')
  assert.equal(result.failureDetailCode, 'CONTRACT')
  assert.equal(dependencies.runtimeIdentity.mock.calls.length, 1)
  assert.equal(dependencies.sourceRetryWait.mock.calls.length, 0)
})

test('K9 source retries one transient HTTP 5xx and then publishes both managed graphs READY', async () => {
  let attempts = 0
  const currentInventory = mock.fn(async () => {
    attempts += 1
    if (attempts === 1) {
      throw Object.assign(new Error('private transient provider body'), {
        providerFailureKind: 'HTTP', providerHttpClass: '5xx',
      })
    }
    return [{ urn: 'urn:li:dataset:test' }]
  })
  const { task, dependencies, managedGraphs } = k9RefreshFixture({ currentInventory })

  const result = await task()

  assert.equal(result.status, 'SUCCESS')
  assert.equal(currentInventory.mock.calls.length, 3)
  assert.deepEqual(dependencies.sourceRetryWait.mock.calls[0].arguments, [
    1_000,
    { failureStage: 'INVENTORY', failureDetailCode: 'HTTP_5XX', attempt: 1 },
  ])
  assert.equal(managedGraphs.recordRefreshFailure.mock.calls.length, 0)
  assert.equal(managedGraphs.triggerLineagePublish.mock.calls.length, 1)
  assert.equal(managedGraphs.triggerGlossaryPublish.mock.calls.length, 1)
})

test('K9 source fence retries one mixed observation and publishes only a stable successor', async () => {
  const fingerprints = ['1'.repeat(64), '2'.repeat(64), '2'.repeat(64)]
  const sourceFingerprint = mock.fn(() => ({
    source_fingerprint_id: fingerprints.shift(),
  }))
  const { task, dependencies, managedGraphs } = k9RefreshFixture({ sourceFingerprint })

  const result = await task()

  assert.equal(result.status, 'SUCCESS')
  assert.equal(dependencies.currentInventory.mock.calls.length, 3)
  assert.equal(sourceFingerprint.mock.calls.length, 3)
  assert.deepEqual(dependencies.sourceRetryWait.mock.calls[0].arguments, [
    1_000,
    { failureStage: 'SOURCE_CONSISTENCY', failureDetailCode: 'SOURCE_DRIFT', attempt: 1 },
  ])
  assert.equal(dependencies.ensureSemanticIndex.mock.calls.length, 1)
  assert.equal(managedGraphs.triggerLineagePublish.mock.calls.length, 1)
  assert.equal(managedGraphs.triggerGlossaryPublish.mock.calls.length, 1)
})

test('K9 source fence fails typed after repeated drift without semantic or graph promotion', async () => {
  const fingerprints = ['1'.repeat(64), '2'.repeat(64), '3'.repeat(64)]
  const sourceFingerprint = mock.fn(() => ({
    source_fingerprint_id: fingerprints.shift(),
  }))
  const { task, dependencies, managedGraphs } = k9RefreshFixture({ sourceFingerprint })

  const result = await task()

  assert.deepEqual(result, {
    status: 'FAILURE',
    reason: 'K9_SOURCE_DRIFT_RETRY_EXHAUSTED',
    failureCode: 'K9_SOURCE_DRIFT_RETRY_EXHAUSTED',
    lineage: undefined,
    glossary: undefined,
  })
  assert.equal(dependencies.currentInventory.mock.calls.length, 3)
  assert.equal(dependencies.ensureSemanticIndex.mock.calls.length, 0)
  assert.equal(dependencies.buildSourceSnapshot.mock.calls.length, 0)
  assert.equal(managedGraphs.triggerLineagePublish.mock.calls.length, 0)
  assert.equal(managedGraphs.triggerGlossaryPublish.mock.calls.length, 0)
  assert.deepEqual(managedGraphs.recordRefreshFailure.mock.calls[0].arguments, [
    'K9_SOURCE_DRIFT_RETRY_EXHAUSTED',
    ['metadata-lineage', 'data-glossary'],
  ])
})

test('K9 scheduler records source drift separately from collector pagination failures and preserves LKG', async () => {
  const priorSuccessfulSchedule = '2026-08-23T17:00:00.000Z'
  const database = k9SchedulerDatabase({
    version: 1,
    last_successful_schedule: priorSuccessfulSchedule,
    completed_at: '2026-08-23T17:00:01.000Z',
    trigger: 'scheduled',
  })
  const stateStore = createPocStateStore({ databasePool: database.pool })
  const scheduledFor = '2026-08-24T17:00:00.000Z'

  await stateStore.runK9Scheduler({
    lockName: 'datariver:poc:k9-scheduler:v1', scheduledFor, trigger: 'scheduled',
  }, async () => ({
    status: 'FAILURE',
    failureCode: 'K9_SOURCE_DRIFT_RETRY_EXHAUSTED',
  }))

  assert.equal(database.readValue().last_successful_schedule, priorSuccessfulSchedule)
  assert.equal(database.readValue().last_attempt.reason, 'K9_SOURCE_DRIFT_RETRY_EXHAUSTED')
  assert.notEqual(database.readValue().last_attempt.reason, 'K9_DATAHUB_SOURCE_FAILED')
})

test('K9 source successful refresh completes source reads before semantic promotion', async () => {
  const order = []
  const { task, managedGraphs } = k9RefreshFixture({
    collectLineage: mock.fn(async () => { order.push('lineage'); return { nodes: [], edges: [] } }),
    collectMetadata: mock.fn(async () => { order.push('metadata'); return { terms: [] } }),
    runtimeIdentity: mock.fn(async () => { order.push('identity'); return { version: '1.0.0' } }),
    ensureSemanticIndex: mock.fn(async () => {
      order.push('semantic')
      return { generation: 'a'.repeat(64), bindingHash: 'b'.repeat(64) }
    }),
  })

  const result = await task()

  assert.equal(result.status, 'SUCCESS')
  assert.ok(order.indexOf('semantic') > order.indexOf('lineage'))
  assert.ok(order.indexOf('semantic') > order.indexOf('metadata'))
  assert.ok(order.indexOf('semantic') > order.indexOf('identity'))
  assert.equal(managedGraphs.recordRefreshFailure.mock.calls.length, 0)
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
    sourceFingerprint: () => ({ source_fingerprint_id: 'd'.repeat(64) }),
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
