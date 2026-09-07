import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { QualityCapability, QualityCapabilityAxisId } from '../../api/types'
import type { QualityApi, QualitySecurityBoundary } from './qualityApi'

const MAX_AUTHORIZATION_LEASE_MS = 30_000

export interface QualityAuthorizationLease {
  capability?: QualityCapability
  boundary?: QualitySecurityBoundary
  loading: boolean
  error?: unknown
  axis: (id: QualityCapabilityAxisId) => QualityCapability['axes'][number] | undefined
  invalidate: () => void
  refresh: () => void
}

export function useQualityAuthorizationLease({
  api,
  workspaceId,
  subjectId,
  securityEpoch,
  authorizationRevision,
}: {
  api: QualityApi
  workspaceId: string
  subjectId: string
  securityEpoch: number
  authorizationRevision: number
}): QualityAuthorizationLease {
  const queryClient = useQueryClient()
  const [capability, setCapability] = useState<QualityCapability>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>()
  const [reloadRevision, setReloadRevision] = useState(0)
  const requestGeneration = useRef(0)

  const purge = useCallback(() => {
    setCapability(undefined)
    void queryClient.cancelQueries({ queryKey: ['quality'] })
    queryClient.removeQueries({ queryKey: ['quality'] })
  }, [queryClient])

  const invalidate = useCallback(() => {
    requestGeneration.current += 1
    purge()
    setError(undefined)
    setLoading(document.visibilityState !== 'hidden')
    setReloadRevision((current) => current + 1)
  }, [purge])

  useEffect(() => {
    let active = true
    let controller: AbortController | undefined
    let capabilityRequestInFlight = false
    let leaseTimer: ReturnType<typeof setTimeout> | undefined
    let hasCapability = false

    const clearLeaseTimer = () => {
      if (leaseTimer) clearTimeout(leaseTimer)
      leaseTimer = undefined
    }
    const load = () => {
      if (
        !active
        || document.visibilityState === 'hidden'
        || !workspaceId
        || !subjectId
        || capabilityRequestInFlight
      ) {
        if (!capabilityRequestInFlight) setLoading(false)
        return
      }
      clearLeaseTimer()
      controller?.abort()
      const requestController = new AbortController()
      controller = requestController
      capabilityRequestInFlight = true
      const requestStartedAt = performance.now()
      const generation = requestGeneration.current + 1
      requestGeneration.current = generation
      hasCapability = false
      setLoading(true)
      setError(undefined)
      void api.capability(requestController.signal)
        .then((next) => {
          if (
            !active
            || requestController.signal.aborted
            || requestGeneration.current !== generation
          ) {
            return
          }
          const serverLeaseMs = Math.min(
            MAX_AUTHORIZATION_LEASE_MS,
            Date.parse(next.valid_until) - Date.parse(next.observed_at),
          )
          const remainingLeaseMs = serverLeaseMs - (performance.now() - requestStartedAt)
          if (remainingLeaseMs <= 0) {
            throw new Error('품질 권한 lease가 이미 만료되었습니다.')
          }
          hasCapability = true
          setCapability(next)
          setLoading(false)
          leaseTimer = setTimeout(() => {
            if (!active || requestGeneration.current !== generation) return
            hasCapability = false
            purge()
            if (document.visibilityState === 'hidden') {
              setLoading(false)
              return
            }
            load()
          }, remainingLeaseMs)
        })
        .catch((next: unknown) => {
          if (
            !active
            || requestController.signal.aborted
            || requestGeneration.current !== generation
          ) {
            return
          }
          hasCapability = false
          setCapability(undefined)
          setError(next)
          setLoading(false)
        })
        .finally(() => {
          if (controller !== requestController) return
          controller = undefined
          capabilityRequestInFlight = false
        })
    }
    const revalidate = () => {
      if (
        !active
        || document.visibilityState === 'hidden'
        || hasCapability
        || capabilityRequestInFlight
      ) return
      hasCapability = false
      purge()
      load()
    }
    const visibilityChanged = () => {
      if (document.visibilityState === 'hidden') return
      if (!hasCapability && !capabilityRequestInFlight) load()
    }

    purge()
    load()
    window.addEventListener('focus', revalidate)
    document.addEventListener('visibilitychange', visibilityChanged)
    return () => {
      active = false
      requestGeneration.current += 1
      controller?.abort()
      clearLeaseTimer()
      window.removeEventListener('focus', revalidate)
      document.removeEventListener('visibilitychange', visibilityChanged)
    }
  }, [
    api,
    authorizationRevision,
    purge,
    reloadRevision,
    securityEpoch,
    subjectId,
    workspaceId,
  ])

  const boundary = useMemo<QualitySecurityBoundary | undefined>(() => (
    capability
      ? {
          workspaceId,
          subjectId,
          securityEpoch,
          authorizationRevision,
          cacheScope: capability.cache_scope,
        }
      : undefined
  ), [
    authorizationRevision,
    capability,
    securityEpoch,
    subjectId,
    workspaceId,
  ])
  const axes = useMemo(
    () => new Map(capability?.axes.map((item) => [item.id, item]) ?? []),
    [capability],
  )
  const axis = useCallback(
    (id: QualityCapabilityAxisId) => axes.get(id),
    [axes],
  )

  return {
    capability,
    boundary,
    loading,
    error,
    axis,
    invalidate,
    refresh: invalidate,
  }
}
