/* global clearTimeout, process, setTimeout */

const DEFAULT_TIME_ZONE = 'Asia/Seoul'
const DEFAULT_LOCK_NAME = 'datariver:poc:k9-scheduler:v1'
const MAX_TIMER_DELAY_MS = 2_147_000_000

export function loadPocK9SchedulerConfig(environment = process.env) {
  const requested = parseBoolean(environment.POC_K9_SCHEDULER_ENABLED, false)
  const systemSubjectId = environment.POC_K9_SYSTEM_SUBJECT_ID?.trim()
  const workspaceId = environment.POC_K9_WORKSPACE_ID?.trim()
  const studioDatabaseUrl = environment.POC_K9_STUDIO_DATABASE_URL?.trim()
  const timeZone = environment.POC_K9_SCHEDULER_TIME_ZONE?.trim() || DEFAULT_TIME_ZONE

  if (requested) {
    if (!systemSubjectId || !workspaceId || !studioDatabaseUrl) {
      throw new Error('K9 scheduler is enabled but required K9 subject, workspace, or read-only Studio database configuration is missing')
    }
  }

  if (timeZone !== 'Asia/Seoul') {
    throw new Error('K9 scheduler time zone must be Asia/Seoul')
  }

  return Object.freeze({
    enabled: requested,
    requested,
    disabledReason: !requested ? 'DISABLED' : null,
    timeZone,
    lockName: DEFAULT_LOCK_NAME,
    systemSubjectId,
    workspaceId,
  })
}

export function createPocK9Scheduler({
  config = loadPocK9SchedulerConfig(),
  stateStore,
  triggerK9Refresh,
  clock = () => new Date(),
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  onError = () => undefined,
} = {}) {
  if (!stateStore || typeof stateStore.runK9Scheduler !== 'function') {
    throw new Error('The POC K9 scheduler state store is unavailable.')
  }
  if (config.enabled && (!stateStore.configured?.postgres || typeof triggerK9Refresh !== 'function')) {
    throw new Error('The enabled POC K9 scheduler requires PostgreSQL and the refresh trigger.')
  }

  let timer
  let stopped = false
  let activeRun

  const execute = async (scheduledFor, trigger) => stateStore.runK9Scheduler({
    lockName: config.lockName,
    scheduledFor: scheduledFor.toISOString(),
    trigger,
  }, async () => {
    return await triggerK9Refresh({
      systemSubjectId: config.systemSubjectId,
      workspaceId: config.workspaceId,
    })
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
  const currentBoundary = boundaryOfZonedDate(zonedDate(now, timeZone), timeZone, 2)
  if (now.getTime() < currentBoundary.getTime()) {
    // If it's before 02:00 today, current is yesterday's 02:00
    const yesterday = new Date(currentBoundary.getTime() - 24 * 60 * 60 * 1000)
    return boundaryOfZonedDate(zonedDate(yesterday, timeZone), timeZone, 2)
  }
  return currentBoundary
}

export function nextScheduleBoundary(now, timeZone = DEFAULT_TIME_ZONE) {
  const current = currentScheduleBoundary(now, timeZone)
  // Next is exactly 1 day after current boundary
  const tomorrow = new Date(current.getTime() + 25 * 60 * 60 * 1000)
  return boundaryOfZonedDate(zonedDate(tomorrow, timeZone), timeZone, 2)
}

function validScheduleBoundary(value, timeZone) {
  const date = value instanceof Date ? new Date(value) : new Date(value)
  if (!Number.isFinite(date.getTime())) throw new Error('The manual scheduler timestamp is invalid.')
  const boundary = currentScheduleBoundary(date, timeZone)
  if (boundary.getTime() !== date.getTime()) {
    throw new Error('A manual scheduler timestamp must be an exact configured-time-zone 02:00 boundary.')
  }
  return date
}

function boundaryOfZonedDate(target, timeZone, hour = 2) {
  validateTimeZone(timeZone)
  const targetKey = dateKey(target)
  const center = Date.UTC(target.year, target.month - 1, target.day, hour)
  let low = center - 36 * 60 * 60 * 1000
  let high = center + 36 * 60 * 60 * 1000
  while (high - low > 1) {
    const middle = Math.floor((low + high) / 2)
    const zDate = zonedDate(new Date(middle), timeZone)
    const dKey = dateKey(zDate)
    const zHour = zonedHour(new Date(middle), timeZone)
    if (dKey < targetKey || (dKey === targetKey && zHour < hour)) low = middle
    else high = middle
  }
  const result = new Date(high)
  if (dateKey(zonedDate(result, timeZone)) !== targetKey || zonedHour(result, timeZone) !== hour) {
    throw new Error('The configured time zone cannot resolve the requested schedule date.')
  }
  return result
}

function zonedHour(value, timeZone) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone, hour: 'numeric', hour12: false
  }).formatToParts(value)
  return Number(parts.find((part) => part.type === 'hour')?.value) % 24
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
    throw new Error('POC_K9_SCHEDULER_TIME_ZONE must be a valid IANA time zone.')
  }
}

function parseBoolean(raw, fallback) {
  if (raw === undefined || raw === null || String(raw).trim() === '') return fallback
  if (String(raw).trim().toLowerCase() === 'true') return true
  if (String(raw).trim().toLowerCase() === 'false') return false
  throw new Error('POC_K9_SCHEDULER_ENABLED must be true or false.')
}
