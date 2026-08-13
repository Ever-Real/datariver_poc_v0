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

test('startup catch-up skips an already successful KST boundary', async () => {
  const calls = []
  const scheduler = createPocChangeHistoryScheduler({
    config: enabledConfig,
    stateStore: {
      configured: { postgres: true },
      async runChangeHistoryScheduler(command) {
        calls.push(command)
        return { status: 'already_completed', scheduledFor: command.scheduledFor }
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
    trigger: 'scheduled',
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
    captureMcl: async () => { order.push('mcl'); return { bounded: true } },
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
