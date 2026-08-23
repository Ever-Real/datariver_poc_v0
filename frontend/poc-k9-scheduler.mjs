/* global clearTimeout, process, setTimeout */

const DEFAULT_TIME_ZONE = 'Asia/Seoul'
const DEFAULT_REFRESH_MODE = 'DAILY'
const DEFAULT_SCHEDULE_HOUR = 2
const DEFAULT_SCHEDULE_MINUTE = 0
const DEFAULT_LOCK_NAME = 'datariver:poc:k9-scheduler:v1'
const MAX_TIMER_DELAY_MS = 2_147_000_000
const supportedRefreshModes = new Set(['DAILY', 'HOURLY', 'MANUAL', 'EVENT_DRIVEN'])
const supportedClassificationCeilings = new Set(['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'])

export function loadPocK9SchedulerConfig(environment = process.env) {
  const requested = parseBoolean(environment.POC_K9_SCHEDULER_ENABLED, false)
  const systemSubjectId = environment.POC_K9_SYSTEM_SUBJECT_ID?.trim()
  const workspaceId = environment.POC_K9_WORKSPACE_ID?.trim()
  const studioDatabaseUrl = environment.POC_K9_STUDIO_DATABASE_URL?.trim()
  const timeZone = environment.POC_K9_SCHEDULER_TIME_ZONE?.trim() || DEFAULT_TIME_ZONE
  const refreshMode = (environment.POC_K9_REFRESH_MODE?.trim().toUpperCase() || DEFAULT_REFRESH_MODE)
  const scheduleHour = boundedInteger(environment.POC_K9_SCHEDULE_HOUR, DEFAULT_SCHEDULE_HOUR, 0, 23, 'POC_K9_SCHEDULE_HOUR')
  const scheduleMinute = boundedInteger(environment.POC_K9_SCHEDULE_MINUTE, DEFAULT_SCHEDULE_MINUTE, 0, 59, 'POC_K9_SCHEDULE_MINUTE')
  const classificationCeiling = environment.POC_K9_CLASSIFICATION_CEILING?.trim().toUpperCase() || 'INTERNAL'

  if (requested) {
    if (!systemSubjectId || !workspaceId || !studioDatabaseUrl) {
      throw new Error('K9 scheduler is enabled but required K9 subject, workspace, or read-only Studio database configuration is missing')
    }
  }

  validateTimeZone(timeZone)
  if (!supportedRefreshModes.has(refreshMode)) throw new Error('POC_K9_REFRESH_MODE must be DAILY, HOURLY, MANUAL, or EVENT_DRIVEN.')
  if (!supportedClassificationCeilings.has(classificationCeiling)) {
    throw new Error('POC_K9_CLASSIFICATION_CEILING must be PUBLIC, INTERNAL, CONFIDENTIAL, or RESTRICTED.')
  }

  const timerEnabled = requested && ['DAILY', 'HOURLY'].includes(refreshMode)
  const schedule = refreshMode === 'DAILY'
    ? `${String(scheduleHour).padStart(2, '0')}:${String(scheduleMinute).padStart(2, '0')} ${timeZone}`
    : refreshMode === 'HOURLY'
      ? `hourly at minute ${String(scheduleMinute).padStart(2, '0')} ${timeZone}`
      : refreshMode

  return Object.freeze({
    enabled: timerEnabled,
    requested,
    disabledReason: !requested ? 'DISABLED' : (!timerEnabled ? `${refreshMode}_ONLY` : null),
    refreshMode,
    scheduleHour,
    scheduleMinute,
    schedule,
    classificationCeiling,
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
  if (config.requested && (!stateStore.configured?.postgres || typeof triggerK9Refresh !== 'function')) {
    throw new Error('The configured POC K9 refresh policy requires PostgreSQL and the refresh trigger.')
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
    if (!config.requested) return Promise.resolve({ status: 'disabled', reason: config.disabledReason })
    const scheduledFor = options.scheduledFor === undefined
      ? currentScheduleBoundary(clock(), config.timeZone, config.scheduleHour, config.scheduleMinute, config.refreshMode)
      : validScheduleBoundary(options.scheduledFor, config)
    const triggerType = options.trigger === 'manual' ? 'manual' : 'scheduled'

    if (!activeRun) {
      activeRun = execute(scheduledFor, triggerType).finally(() => { activeRun = undefined })
    }
    return activeRun
  }

  const scheduleNext = () => {
    if (stopped || !config.enabled) return
    const now = clock()
    const next = nextScheduleBoundary(now, config.timeZone, config.scheduleHour, config.scheduleMinute, config.refreshMode)
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
      if (stopped || !config.requested) return { status: 'disabled', reason: config.disabledReason }
      if (!config.enabled) return { status: 'idle', mode: config.refreshMode }
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

export function currentScheduleBoundary(
  now,
  timeZone = DEFAULT_TIME_ZONE,
  hour = DEFAULT_SCHEDULE_HOUR,
  minute = DEFAULT_SCHEDULE_MINUTE,
  refreshMode = DEFAULT_REFRESH_MODE,
) {
  if (refreshMode === 'HOURLY') return hourlyBoundary(now, timeZone, minute)
  if (refreshMode !== 'DAILY') throw new Error('The configured refresh mode does not have a timer boundary.')
  const currentBoundary = boundaryOfZonedDate(zonedDate(now, timeZone), timeZone, hour, minute)
  if (now.getTime() < currentBoundary.getTime()) {
    // If it is before today's configured time, use yesterday's boundary.
    const yesterday = new Date(currentBoundary.getTime() - 24 * 60 * 60 * 1000)
    return boundaryOfZonedDate(zonedDate(yesterday, timeZone), timeZone, hour, minute)
  }
  return currentBoundary
}

export function nextScheduleBoundary(
  now,
  timeZone = DEFAULT_TIME_ZONE,
  hour = DEFAULT_SCHEDULE_HOUR,
  minute = DEFAULT_SCHEDULE_MINUTE,
  refreshMode = DEFAULT_REFRESH_MODE,
) {
  const current = currentScheduleBoundary(now, timeZone, hour, minute, refreshMode)
  if (refreshMode === 'HOURLY') return new Date(current.getTime() + 60 * 60 * 1000)
  // Resolve tomorrow in the configured zone rather than assuming a fixed DST day.
  const tomorrow = new Date(current.getTime() + 25 * 60 * 60 * 1000)
  return boundaryOfZonedDate(zonedDate(tomorrow, timeZone), timeZone, hour, minute)
}

function validScheduleBoundary(value, config) {
  const date = value instanceof Date ? new Date(value) : new Date(value)
  if (!Number.isFinite(date.getTime())) throw new Error('The manual scheduler timestamp is invalid.')
  if (['MANUAL', 'EVENT_DRIVEN'].includes(config.refreshMode)) return date
  const boundary = currentScheduleBoundary(
    date,
    config.timeZone,
    config.scheduleHour,
    config.scheduleMinute,
    config.refreshMode,
  )
  if (boundary.getTime() !== date.getTime()) {
    throw new Error('A manual scheduler timestamp must be an exact configured refresh boundary.')
  }
  return date
}

function boundaryOfZonedDate(target, timeZone, hour = DEFAULT_SCHEDULE_HOUR, minute = DEFAULT_SCHEDULE_MINUTE) {
  validateTimeZone(timeZone)
  const targetKey = dateKey(target)
  const center = Date.UTC(target.year, target.month - 1, target.day, hour)
  let low = center - 36 * 60 * 60 * 1000
  let high = center + 36 * 60 * 60 * 1000
  while (high - low > 1) {
    const middle = Math.floor((low + high) / 2)
    const zDate = zonedDate(new Date(middle), timeZone)
    const dKey = dateKey(zDate)
    const zTime = zonedTime(new Date(middle), timeZone)
    if (dKey < targetKey || (dKey === targetKey && (zTime.hour < hour || (zTime.hour === hour && zTime.minute < minute)))) low = middle
    else high = middle
  }
  const result = new Date(high)
  const resolvedTime = zonedTime(result, timeZone)
  if (dateKey(zonedDate(result, timeZone)) !== targetKey || resolvedTime.hour !== hour || resolvedTime.minute !== minute) {
    throw new Error('The configured time zone cannot resolve the requested schedule date.')
  }
  return result
}

function hourlyBoundary(value, timeZone, minute) {
  const parts = zonedDateTime(value, timeZone)
  let boundary = boundaryOfZonedDate(parts, timeZone, parts.hour, minute)
  if (boundary.getTime() > value.getTime()) boundary = new Date(boundary.getTime() - 60 * 60 * 1000)
  return boundary
}

function zonedTime(value, timeZone) {
  const parts = zonedDateTime(value, timeZone)
  return { hour: parts.hour, minute: parts.minute }
}

function zonedDateTime(value, timeZone) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: 'numeric',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(value)
  const get = (type) => Number(parts.find((part) => part.type === type)?.value)
  return {
    year: get('year'),
    month: get('month'),
    day: get('day'),
    hour: get('hour') % 24,
    minute: get('minute'),
  }
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

function boundedInteger(raw, fallback, minimum, maximum, name) {
  if (raw === undefined || raw === null || String(raw).trim() === '') return fallback
  const value = Number(raw)
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be an integer from ${minimum} through ${maximum}.`)
  }
  return value
}
