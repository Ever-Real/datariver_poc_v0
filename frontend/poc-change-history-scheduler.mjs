/* global clearTimeout, process, setTimeout */

import {
  mclCaptureFailure,
  mclRuntimeFailureDiagnostic,
} from './poc-mcl-runtime-failure.mjs'

export {
  mclCaptureFailure,
  mclRuntimeFailureDiagnostic,
} from './poc-mcl-runtime-failure.mjs'

const DEFAULT_TIME_ZONE = 'Asia/Seoul'
const DEFAULT_LOCK_NAME = 'datariver:poc:change-history-scheduler:v1'
const MAX_TIMER_DELAY_MS = 2_147_000_000

export async function persistMclRuntimeFailure({
  stateStore,
  error,
  observedAt = new Date().toISOString(),
  ...fallback
} = {}) {
  if (typeof stateStore?.writeChangeHistoryRuntimeStatus !== 'function') {
    throw new Error('The durable MCL runtime status writer is unavailable.')
  }
  const diagnostic = mclRuntimeFailureDiagnostic(error, fallback)
  const state = diagnostic.classification.startsWith('PREP_MCL_DISCOVERY_')
    ? 'DISCOVERY_FAILED'
    : 'CAPTURE_FAILED'
  const version = await stateStore.writeChangeHistoryRuntimeStatus({
    state,
    ...diagnostic,
    observedAt,
  })
  if (!Number.isSafeInteger(version) || version < 1) {
    throw new Error('The durable MCL runtime failure status was not verified.')
  }
  return { ...diagnostic, state, version }
}

export function loadPocChangeHistorySchedulerConfig(environment = process.env) {
  const requested = parseBoolean(environment.POC_CHANGE_HISTORY_SCHEDULER_ENABLED, false)
  // Topic, Registry subject/schema, provider version and source identity are
  // discovered from the configured DataHub/Kafka source at runtime.
  const hasMclConfig = Boolean(environment.POC_MCL_KAFKA_BROKERS?.trim())
  const timeZone = environment.POC_CHANGE_HISTORY_SCHEDULER_TIME_ZONE?.trim() || DEFAULT_TIME_ZONE
  validateTimeZone(timeZone)
  return Object.freeze({
    enabled: requested && hasMclConfig,
    requested,
    disabledReason: !requested ? 'DISABLED' : !hasMclConfig ? 'MCL_CONFIG_MISSING' : null,
    timeZone,
    lockName: environment.POC_CHANGE_HISTORY_SCHEDULER_LOCK_NAME?.trim() || DEFAULT_LOCK_NAME,
  })
}

export function createPocChangeHistoryScheduler({
  config = loadPocChangeHistorySchedulerConfig(),
  stateStore,
  captureMcl,
  reconcileCatalog,
  clock = () => new Date(),
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  onError = () => undefined,
  onCaptureState = () => undefined,
  yieldBetweenBatches = () => new Promise((resolve) => setTimeout(resolve, 0)),
} = {}) {
  if (!stateStore || typeof stateStore.runChangeHistoryScheduler !== 'function') {
    throw new Error('The POC change-history scheduler state store is unavailable.')
  }
  if (config.enabled && (!stateStore.configured?.postgres
    || typeof captureMcl !== 'function' || typeof reconcileCatalog !== 'function')) {
    throw new Error('The enabled POC change-history scheduler requires PostgreSQL and both ordered tasks.')
  }
  let timer
  let stopped = false
  let activeRun

  const recordCaptureState = async (state, capture, batchProcessedRecords = 0) => {
    try {
      await onCaptureState({
        state,
        batchProcessedRecords,
        observedAt: clock().toISOString(),
        caughtUp: capture?.caughtUp === true,
        sourceIdentityHash: capture?.sourceIdentityHash,
      })
    } catch (error) {
      throw mclCaptureFailure(error, {
        stage: 'CAPTURE_STATUS_PERSISTENCE',
        detailCode: 'STATUS_WRITE_REJECTED',
      })
    }
  }

  const executeTask = async () => {
    let capture
    let schedulerComplete = true
    while (true) {
      try {
        capture = await captureMcl()
      } catch (error) {
        if (error?.code === 'PREP_MCL_CAPTURE_HISTORY_GAP_BLOCKED') {
          try {
            await recordCaptureState('HISTORY_GAP_BLOCKED', {
              sourceIdentityHash: error.sourceIdentityHash,
            })
          } catch {
            // Preserve the primary retention classification. The runtime failure
            // writer remains the authoritative durable operator diagnostic.
          }
        }
        throw mclCaptureFailure(error, {
          stage: 'CAPTURE_EXECUTION',
          detailCode: 'UNCLASSIFIED_CAPTURE_ERROR',
        })
      }
      if (capture?.bounded !== true || typeof capture?.caughtUp !== 'boolean'
        || !Array.isArray(capture?.partitions)) {
        throw mclCaptureFailure(undefined, {
          stage: 'CAPTURE_RESULT_VALIDATION',
          detailCode: 'BOUNDED_RESULT_INVALID',
        })
      }
      const batchProcessedRecords = capture.partitions.reduce((sum, partition) => {
        const processed = Number(partition?.processedRecords)
        if (!Number.isSafeInteger(processed) || processed < 0) {
          throw mclCaptureFailure(undefined, {
            stage: 'CAPTURE_RESULT_VALIDATION',
            detailCode: 'PROCESSED_RECORD_COUNT_INVALID',
          })
        }
        return sum + processed
      }, 0)
      await recordCaptureState('CONTIGUOUS_CAPTURE_RECORDED', capture, batchProcessedRecords)
      if (capture.caughtUp) {
        await recordCaptureState('CAPTURE_CAUGHT_UP', capture, batchProcessedRecords)
        break
      }
      if (batchProcessedRecords === 0) {
        throw mclCaptureFailure(undefined, {
          stage: 'CAPTURE_PROGRESS_VALIDATION',
          detailCode: 'NO_DURABLE_PROGRESS',
        })
      }
      await recordCaptureState('CAPTURE_CATCHING_UP', capture, batchProcessedRecords)
      if (stopped) {
        schedulerComplete = false
        break
      }
      await yieldBetweenBatches()
      if (stopped) {
        schedulerComplete = false
        break
      }
    }
    let catalog
    try {
      catalog = await reconcileCatalog()
    } catch (error) {
      throw mclCaptureFailure(error, {
        stage: 'CATALOG_RECONCILIATION',
        detailCode: 'CATALOG_REFRESH_REJECTED',
      })
    }
    return { capture, catalog, schedulerComplete }
  }

  const execute = async (scheduledFor, trigger) => {
    try {
      return await stateStore.runChangeHistoryScheduler({
        lockName: config.lockName,
        scheduledFor: scheduledFor.toISOString(),
        trigger,
      }, executeTask)
    } catch (error) {
      throw mclCaptureFailure(error, {
        stage: 'SCHEDULER_STATE',
        detailCode: 'LOCK_OR_RECEIPT_REJECTED',
      })
    }
  }

  const trigger = (options = {}) => {
    if (!config.enabled) return Promise.resolve({ status: 'disabled', reason: config.disabledReason })
    const scheduledFor = options.scheduledFor === undefined
      ? currentScheduleBoundary(clock(), config.timeZone)
      : validScheduleBoundary(options.scheduledFor, config.timeZone)
    const triggerType = options.trigger === 'manual'
      ? 'manual'
      : options.trigger === 'startup' ? 'startup' : 'scheduled'
    if (!activeRun) {
      activeRun = execute(scheduledFor, triggerType).finally(() => { activeRun = undefined })
    }
    return activeRun
  }

  const scheduleNext = () => {
    if (stopped || !config.enabled) return
    const now = clock()
    const next = nextScheduleBoundary(now, config.timeZone)
    const delay = Math.min(Math.max(1, next.getTime() - now.getTime()), MAX_TIMER_DELAY_MS)
    timer = setTimer(async () => {
      timer = undefined
      try {
        if (delay < next.getTime() - clock().getTime()) return scheduleNext()
        await trigger({ scheduledFor: next, trigger: 'scheduled' })
      } catch (error) {
        await onError(error)
      } finally {
        scheduleNext()
      }
    }, delay)
  }

  return {
    config,
    async start() {
      if (stopped || !config.enabled) return { status: 'disabled', reason: config.disabledReason }
      void trigger({ trigger: 'startup' }).catch(onError)
      scheduleNext()
      return { status: 'started' }
    },
    triggerManual(scheduledFor) {
      return trigger({ scheduledFor, trigger: 'manual' })
    },
    async stop() {
      stopped = true
      if (timer !== undefined) clearTimer(timer)
      timer = undefined
      await activeRun
    },
  }
}

export function currentScheduleBoundary(now, timeZone = DEFAULT_TIME_ZONE) {
  const date = zonedDate(now, timeZone)
  return startOfZonedDate(date, timeZone)
}

export function nextScheduleBoundary(now, timeZone = DEFAULT_TIME_ZONE) {
  const current = zonedDate(now, timeZone)
  const tomorrow = new Date(Date.UTC(current.year, current.month - 1, current.day + 1))
  return startOfZonedDate({
    year: tomorrow.getUTCFullYear(), month: tomorrow.getUTCMonth() + 1, day: tomorrow.getUTCDate(),
  }, timeZone)
}

function validScheduleBoundary(value, timeZone) {
  const date = value instanceof Date ? new Date(value) : new Date(value)
  if (!Number.isFinite(date.getTime())) throw new Error('The manual scheduler timestamp is invalid.')
  const boundary = currentScheduleBoundary(date, timeZone)
  if (boundary.getTime() !== date.getTime()) {
    throw new Error('A manual scheduler timestamp must be an exact configured-time-zone day boundary.')
  }
  return date
}

function startOfZonedDate(target, timeZone) {
  validateTimeZone(timeZone)
  const targetKey = dateKey(target)
  const center = Date.UTC(target.year, target.month - 1, target.day)
  let low = center - 36 * 60 * 60 * 1000
  let high = center + 36 * 60 * 60 * 1000
  while (high - low > 1) {
    const middle = Math.floor((low + high) / 2)
    if (dateKey(zonedDate(new Date(middle), timeZone)) < targetKey) low = middle
    else high = middle
  }
  const result = new Date(high)
  if (dateKey(zonedDate(result, timeZone)) !== targetKey) {
    throw new Error('The configured time zone cannot resolve the requested schedule date.')
  }
  return result
}

function zonedDate(value, timeZone) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(value)
  const get = (type) => Number(parts.find((part) => part.type === type)?.value)
  return { year: get('year'), month: get('month'), day: get('day') }
}

function dateKey({ year, month, day }) {
  return year * 10_000 + month * 100 + day
}

function validateTimeZone(timeZone) {
  try {
    new Intl.DateTimeFormat('en-US', { timeZone }).format(new Date(0))
  } catch {
    throw new Error('POC_CHANGE_HISTORY_SCHEDULER_TIME_ZONE must be a valid IANA time zone.')
  }
}

function parseBoolean(raw, fallback) {
  if (raw === undefined || raw === null || String(raw).trim() === '') return fallback
  if (String(raw).trim().toLowerCase() === 'true') return true
  if (String(raw).trim().toLowerCase() === 'false') return false
  throw new Error('POC_CHANGE_HISTORY_SCHEDULER_ENABLED must be true or false.')
}
