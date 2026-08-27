/* global clearTimeout, process, setTimeout */

const DEFAULT_TIME_ZONE = 'Asia/Seoul'
const DEFAULT_LOCK_NAME = 'datariver:poc:change-history-scheduler:v1'
const MAX_TIMER_DELAY_MS = 2_147_000_000

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

  const execute = async (scheduledFor, trigger) => stateStore.runChangeHistoryScheduler({
    lockName: config.lockName,
    scheduledFor: scheduledFor.toISOString(),
    trigger,
  }, async () => {
    const capture = await captureMcl()
    const catalog = await reconcileCatalog()
    return { capture, catalog }
  })

  const trigger = (options = {}) => {
    if (!config.enabled) return Promise.resolve({ status: 'disabled', reason: config.disabledReason })
    const scheduledFor = options.scheduledFor === undefined
      ? currentScheduleBoundary(clock(), config.timeZone)
      : validScheduleBoundary(options.scheduledFor, config.timeZone)
    const triggerType = options.trigger === 'manual' ? 'manual' : 'scheduled'
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
        onError(error)
      } finally {
        scheduleNext()
      }
    }, delay)
  }

  return {
    config,
    async start() {
      if (stopped || !config.enabled) return { status: 'disabled', reason: config.disabledReason }
      void trigger({ trigger: 'scheduled' }).catch(onError)
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
