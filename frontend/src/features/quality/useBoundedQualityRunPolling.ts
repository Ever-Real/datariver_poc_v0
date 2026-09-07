import { useCallback, useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import type { QualityRunState, QualityRunSummary } from '../../api/types'
import {
  qualityQueryKey,
} from './qualityApi'
import type { QualityApi, QualitySecurityBoundary } from './qualityApi'

const POLL_DELAYS_MS = [1_000, 2_000, 5_000, 10_000] as const
const MAX_POLL_READS = 20
const MAX_VISIBLE_ACTIVE_MS = 120_000
const terminalStates = new Set<QualityRunState>([
  'SUCCEEDED',
  'FAILED',
  'STALE',
  'CANCELLED',
])

export function qualityRunIsTerminal(state: QualityRunState): boolean {
  return terminalStates.has(state)
}

export function useBoundedQualityRunPolling({
  api,
  boundary,
  selectedRun,
  onBoundaryInvalid,
}: {
  api: QualityApi
  boundary: QualitySecurityBoundary
  selectedRun?: QualityRunSummary
  onBoundaryInvalid: () => void
}) {
  const queryClient = useQueryClient()
  const [currentRun, setCurrentRun] = useState(selectedRun)
  const [polling, setPolling] = useState(false)
  const [stopped, setStopped] = useState(false)
  const [attempts, setAttempts] = useState(0)
  const [error, setError] = useState<unknown>()
  const [pollRevision, setPollRevision] = useState(0)

  useEffect(() => {
    setCurrentRun(selectedRun)
  }, [selectedRun])

  useEffect(() => {
    const runId = selectedRun?.run_id
    if (!runId || qualityRunIsTerminal(selectedRun.state)) {
      setPolling(false)
      setStopped(false)
      setAttempts(0)
      return
    }

    let active = true
    let controller: AbortController | undefined
    let timeout: ReturnType<typeof setTimeout> | undefined
    let readCount = 0
    let visibleElapsedMs = 0
    let visibleStartedAt = document.visibilityState === 'hidden'
      ? undefined
      : performance.now()

    const elapsed = () => visibleElapsedMs + (
      visibleStartedAt === undefined ? 0 : performance.now() - visibleStartedAt
    )
    const clearTimer = () => {
      if (timeout) clearTimeout(timeout)
      timeout = undefined
    }
    const stop = (nextError?: unknown) => {
      clearTimer()
      controller?.abort()
      controller = undefined
      if (!active) return
      setPolling(false)
      setStopped(true)
      if (nextError !== undefined) setError(nextError)
    }
    const invalidateTerminalReads = () => {
      for (const resource of ['overview', 'runs', 'run-results'] as const) {
        void queryClient.invalidateQueries({
          queryKey: qualityQueryKey(boundary, resource),
        })
      }
    }
    const schedule = () => {
      if (!active || document.visibilityState === 'hidden') return
      const remaining = MAX_VISIBLE_ACTIVE_MS - elapsed()
      if (readCount >= MAX_POLL_READS || remaining <= 0) {
        stop()
        return
      }
      const delay = POLL_DELAYS_MS[Math.min(readCount - 1, POLL_DELAYS_MS.length - 1)] ?? 10_000
      if (delay >= remaining) {
        timeout = setTimeout(() => stop(), remaining)
        return
      }
      timeout = setTimeout(poll, delay)
    }
    const poll = () => {
      clearTimer()
      if (
        !active
        || document.visibilityState === 'hidden'
        || readCount >= MAX_POLL_READS
        || elapsed() >= MAX_VISIBLE_ACTIVE_MS
      ) {
        if (active && document.visibilityState !== 'hidden') stop()
        return
      }
      controller?.abort()
      controller = new AbortController()
      const request = controller
      readCount += 1
      setAttempts(readCount)
      setPolling(true)
      setStopped(false)
      setError(undefined)
      void api.run(runId, boundary.cacheScope, request.signal)
        .then((next) => {
          if (!active || request.signal.aborted || next.run_id !== runId) return
          setCurrentRun(next)
          if (qualityRunIsTerminal(next.state)) {
            clearTimer()
            setPolling(false)
            setStopped(false)
            invalidateTerminalReads()
            return
          }
          schedule()
        })
        .catch((next: unknown) => {
          if (!active || request.signal.aborted) return
          if (isAuthorizationBoundaryError(next)) onBoundaryInvalid()
          stop(next)
        })
    }
    const visibilityChanged = () => {
      if (!active) return
      if (document.visibilityState === 'hidden') {
        if (visibleStartedAt !== undefined) {
          visibleElapsedMs += performance.now() - visibleStartedAt
          visibleStartedAt = undefined
        }
        clearTimer()
        controller?.abort()
        controller = undefined
        setPolling(false)
        return
      }
      if (visibleStartedAt === undefined) visibleStartedAt = performance.now()
      poll()
    }

    setCurrentRun(selectedRun)
    setAttempts(0)
    setError(undefined)
    setStopped(false)
    if (document.visibilityState !== 'hidden') poll()
    else setPolling(false)
    document.addEventListener('visibilitychange', visibilityChanged)
    return () => {
      active = false
      clearTimer()
      controller?.abort()
      document.removeEventListener('visibilitychange', visibilityChanged)
    }
  }, [
    api,
    boundary,
    onBoundaryInvalid,
    pollRevision,
    queryClient,
    selectedRun,
  ])

  const refresh = useCallback(() => {
    setPollRevision((current) => current + 1)
  }, [])

  return { run: currentRun, polling, stopped, attempts, error, refresh }
}

export function isAuthorizationBoundaryError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false
  return (
    [401, 403, 404].includes(error.problem.status)
    || error.problem.code.includes('stale_cursor')
    || error.problem.code.includes('cache_scope')
  )
}
