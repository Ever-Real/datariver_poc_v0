/* global setTimeout */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createPocChangeHistoryScheduler,
  currentScheduleBoundary,
  loadPocChangeHistorySchedulerConfig,
  nextScheduleBoundary,
} from './poc-change-history-scheduler.mjs'

const enabledConfig = {
  enabled: true,
  requested: true,
  disabledReason: null,
  timeZone: 'Asia/Seoul',
  lockName: 'scheduler-test',
}

test('keeps the existing server path inert when the scheduler is disabled or MCL config is missing', async () => {
  const disabled = loadPocChangeHistorySchedulerConfig({})
  const missingMcl = loadPocChangeHistorySchedulerConfig({ POC_CHANGE_HISTORY_SCHEDULER_ENABLED: 'true' })
  assert.equal(disabled.disabledReason, 'DISABLED')
  assert.equal(missingMcl.disabledReason, 'MCL_CONFIG_MISSING')
  let calls = 0
  const scheduler = createPocChangeHistoryScheduler({
    config: missingMcl,
    stateStore: { configured: { postgres: false }, async runChangeHistoryScheduler() { calls += 1 } },
  })
  assert.deepEqual(await scheduler.start(), { status: 'disabled', reason: 'MCL_CONFIG_MISSING' })
  assert.deepEqual(await scheduler.triggerManual(), { status: 'disabled', reason: 'MCL_CONFIG_MISSING' })
  await scheduler.stop()
  assert.equal(calls, 0)
})

test('startup catch-up rechecks an already successful KST boundary under the same owner lock', async () => {
  const calls = []
  const scheduler = createPocChangeHistoryScheduler({
    config: enabledConfig,
    stateStore: {
      configured: { postgres: true },
      async runChangeHistoryScheduler(command) {
        calls.push(command)
        return { status: 'succeeded', scheduledFor: command.scheduledFor, replayedSchedule: true }
      },
    },
    captureMcl: async () => { throw new Error('completed capture must not rerun') },
    reconcileCatalog: async () => { throw new Error('completed reconciliation must not rerun') },
    clock: () => new Date('2026-08-14T03:12:00.000Z'),
    setTimer: () => 1,
    clearTimer: () => undefined,
  })
  await scheduler.start()
  await scheduler.stop()
  assert.deepEqual(calls, [{
    lockName: 'scheduler-test',
    scheduledFor: '2026-08-13T15:00:00.000Z',
    trigger: 'startup',
  }])
})

test('runs bounded MCL capture before T05 reconciliation and exposes a boundary-checked manual trigger', async () => {
  const order = []
  const scheduler = createPocChangeHistoryScheduler({
    config: enabledConfig,
    stateStore: {
      configured: { postgres: true },
      async runChangeHistoryScheduler(command, task) {
        order.push(`lock:${command.trigger}`)
        const result = await task()
        order.push('receipt')
        return { status: 'succeeded', result }
      },
    },
    captureMcl: async () => {
      order.push('mcl')
      return {
        bounded: true, caughtUp: true, sourceIdentityHash: 'a'.repeat(64),
        partitions: [{ processedRecords: 1 }],
      }
    },
    reconcileCatalog: async () => { order.push('t05'); return { projection: true } },
    clock: () => new Date('2026-08-14T03:12:00.000Z'),
    setTimer: () => 1,
    clearTimer: () => undefined,
  })
  await scheduler.triggerManual('2026-08-13T15:00:00.000Z')
  assert.deepEqual(order, ['lock:manual', 'mcl', 't05', 'receipt'])
  assert.throws(
    () => scheduler.triggerManual('2026-08-13T15:00:01.000Z'),
    /exact configured-time-zone day boundary/,
  )
  await scheduler.stop()
})

test('startup catch-up repeats bounded captures, yields, then reconciles catalog once', async () => {
  const order = []
  const states = []
  const captures = [false, false, true]
  const scheduler = createPocChangeHistoryScheduler({
    config: enabledConfig,
    stateStore: {
      configured: { postgres: true },
      async runChangeHistoryScheduler(_command, task) {
        const result = await task()
        order.push('receipt')
        return { status: 'succeeded', result }
      },
    },
    captureMcl: async () => {
      const caughtUp = captures.shift()
      order.push(`capture:${caughtUp}`)
      return {
        bounded: true, caughtUp, sourceIdentityHash: 'a'.repeat(64),
        partitions: [{ processedRecords: 2 }],
      }
    },
    reconcileCatalog: async () => { order.push('catalog'); return { projection: true } },
    onCaptureState: async ({ state }) => { states.push(state) },
    yieldBetweenBatches: async () => { order.push('yield') },
    clock: () => new Date('2026-08-14T03:12:00.000Z'),
    setTimer: () => 1,
    clearTimer: () => undefined,
  })
  const result = await scheduler.triggerManual('2026-08-13T15:00:00.000Z')
  assert.equal(result.result.schedulerComplete, true)
  assert.deepEqual(order, [
    'capture:false', 'yield', 'capture:false', 'yield', 'capture:true', 'catalog', 'receipt',
  ])
  assert.deepEqual(states, [
    'CONTIGUOUS_CAPTURE_RECORDED', 'CAPTURE_CATCHING_UP',
    'CONTIGUOUS_CAPTURE_RECORDED', 'CAPTURE_CATCHING_UP',
    'CONTIGUOUS_CAPTURE_RECORDED', 'CAPTURE_CAUGHT_UP',
  ])
  await scheduler.stop()
})

test('graceful stop finishes the current bounded batch without starting another', async () => {
  let releaseCapture
  let captureCalls = 0
  let taskResult
  const scheduler = createPocChangeHistoryScheduler({
    config: enabledConfig,
    stateStore: {
      configured: { postgres: true },
      async runChangeHistoryScheduler(_command, task) {
        taskResult = await task()
        return { status: taskResult.schedulerComplete ? 'succeeded' : 'incomplete', result: taskResult }
      },
    },
    captureMcl: async () => {
      captureCalls += 1
      await new Promise((resolve) => { releaseCapture = resolve })
      return {
        bounded: true, caughtUp: false, sourceIdentityHash: 'a'.repeat(64),
        partitions: [{ processedRecords: 1 }],
      }
    },
    reconcileCatalog: async () => ({ projection: true }),
    clock: () => new Date('2026-08-14T03:12:00.000Z'),
    setTimer: () => 1,
    clearTimer: () => undefined,
  })
  await scheduler.start()
  while (!releaseCapture) await new Promise((resolve) => setTimeout(resolve, 0))
  const stopping = scheduler.stop()
  releaseCapture()
  await stopping
  assert.equal(captureCalls, 1)
  assert.equal(taskResult.schedulerComplete, false)
})

test('graceful stop during the inter-batch yield starts no subsequent batch', async () => {
  let releaseYield
  let yieldStarted
  const yielded = new Promise((resolve) => { yieldStarted = resolve })
  let captureCalls = 0
  const scheduler = createPocChangeHistoryScheduler({
    config: enabledConfig,
    stateStore: {
      configured: { postgres: true },
      async runChangeHistoryScheduler(_command, task) {
        const result = await task()
        return { status: result.schedulerComplete ? 'succeeded' : 'incomplete', result }
      },
    },
    captureMcl: async () => {
      captureCalls += 1
      return {
        bounded: true, caughtUp: false, sourceIdentityHash: 'a'.repeat(64),
        partitions: [{ processedRecords: 1 }],
      }
    },
    reconcileCatalog: async () => ({ projection: true }),
    yieldBetweenBatches: async () => {
      yieldStarted()
      await new Promise((resolve) => { releaseYield = resolve })
    },
    clock: () => new Date('2026-08-14T03:12:00.000Z'),
    setTimer: () => 1,
    clearTimer: () => undefined,
  })
  await scheduler.start()
  await yielded
  const stopping = scheduler.stop()
  releaseYield()
  await stopping
  assert.equal(captureCalls, 1)
})

test('retention history gap is fail-closed and exposes a sanitized blocked state', async () => {
  const states = []
  const gap = Object.assign(new Error('retention gap'), {
    code: 'PREP_MCL_CAPTURE_HISTORY_GAP_BLOCKED', sourceIdentityHash: 'a'.repeat(64),
  })
  const scheduler = createPocChangeHistoryScheduler({
    config: enabledConfig,
    stateStore: {
      configured: { postgres: true },
      async runChangeHistoryScheduler(_command, task) { return task() },
    },
    captureMcl: async () => { throw gap },
    reconcileCatalog: async () => { throw new Error('catalog must not run after a gap') },
    onCaptureState: async (status) => { states.push(status.state) },
  })
  await assert.rejects(
    scheduler.triggerManual('2026-08-13T15:00:00.000Z'),
    (error) => error === gap,
  )
  assert.deepEqual(states, ['HISTORY_GAP_BLOCKED'])
  await scheduler.stop()
})

test('computes IANA day boundaries across DST without fixed UTC offsets', () => {
  assert.equal(
    currentScheduleBoundary(new Date('2026-03-08T16:00:00.000Z'), 'America/New_York').toISOString(),
    '2026-03-08T05:00:00.000Z',
  )
  assert.equal(
    nextScheduleBoundary(new Date('2026-03-08T16:00:00.000Z'), 'America/New_York').toISOString(),
    '2026-03-09T04:00:00.000Z',
  )
})
