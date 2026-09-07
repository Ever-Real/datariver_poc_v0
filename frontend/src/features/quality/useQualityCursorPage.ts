import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { QualityListResponse } from '../../api/types'
import {
  qualityQueryKey,
  type QualityResource,
  type QualitySecurityBoundary,
} from './qualityApi'
import { isAuthorizationBoundaryError } from './useBoundedQualityRunPolling'

class QualityCacheScopeDriftError extends Error {
  constructor() {
    super('품질 조회 권한 범위가 변경되었습니다.')
    this.name = 'QualityCacheScopeDriftError'
  }
}

export function useQualityCursorPage<T>({
  boundary,
  resource,
  load,
  onBoundaryInvalid,
  enabled = true,
  scope = [],
}: {
  boundary: QualitySecurityBoundary
  resource: QualityResource
  load: (cursor: string | undefined, signal: AbortSignal) => Promise<QualityListResponse<T>>
  onBoundaryInvalid: () => void
  enabled?: boolean
  scope?: readonly unknown[]
}) {
  const [cursors, setCursors] = useState<Array<string | undefined>>([undefined])
  const [pageIndex, setPageIndex] = useState(0)
  const boundaryKey = [
    boundary.workspaceId,
    boundary.subjectId,
    boundary.securityEpoch,
    boundary.authorizationRevision,
    boundary.cacheScope,
  ].join('|')
  const scopeKey = JSON.stringify(scope)

  useEffect(() => {
    setCursors([undefined])
    setPageIndex(0)
  }, [boundaryKey, scopeKey])

  const cursor = cursors[pageIndex]
  const query = useQuery({
    queryKey: qualityQueryKey(boundary, resource, ...scope, cursor, 25),
    queryFn: async ({ signal }) => {
      const page = await load(cursor, signal)
      if (page.cache_scope !== boundary.cacheScope) throw new QualityCacheScopeDriftError()
      return page
    },
    enabled,
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })

  useEffect(() => {
    if (
      query.error instanceof QualityCacheScopeDriftError
      || isAuthorizationBoundaryError(query.error)
    ) {
      onBoundaryInvalid()
    }
  }, [onBoundaryInvalid, query.error])

  return {
    ...query,
    pageIndex,
    pagination: {
      page: pageIndex + 1,
      pageSize: 25,
      pageSizeOptions: [25],
      canPrevious: pageIndex > 0,
      canNext: Boolean(query.data?.page.next_cursor),
      itemCount: query.data?.items.length,
      onPrevious: () => setPageIndex((current) => Math.max(0, current - 1)),
      onNext: () => {
        const next = query.data?.page.next_cursor
        if (!next) return
        setCursors((current) => [...current.slice(0, pageIndex + 1), next])
        setPageIndex((current) => current + 1)
      },
      onPageSizeChange: () => undefined,
    },
  }
}
