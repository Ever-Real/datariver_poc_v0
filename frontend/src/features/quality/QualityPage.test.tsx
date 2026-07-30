import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../api/client'
import type { QualityCapability, QualityOverview } from '../../api/types'
import { QualityPage } from './QualityPage'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  window.history.replaceState({}, '', '/?page=quality&workspace=workspace-one')
})

describe('QualityPage', () => {
  it('does not fetch any quality resource when read_access is denied', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(json(capability('DENIED'))))
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    expect(await screen.findByRole('heading', { name: '품질 데이터 열람이 허용되지 않았습니다' })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(requestPaths(fetchMock)).toEqual(['/api/v1/quality/capability'])
  })

  it('renders server KPIs and an equivalent accessible trend table', async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = requestUrl(input).pathname
      if (path.endsWith('/quality/capability')) return Promise.resolve(json(capability('AVAILABLE')))
      if (path.endsWith('/quality/overview')) return Promise.resolve(json(overview()))
      return Promise.reject(new Error(`unexpected request: ${requestUrl(input).href}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    expect(await screen.findByRole('heading', { name: '현재 품질 Snapshot' })).toBeInTheDocument()
    const tabs = screen.getByRole('tablist', { name: '품질관리 영역' })
    expect(within(tabs).getAllByRole('tab')).toHaveLength(4)
    expect(screen.getAllByText('98.75%')).toHaveLength(2)
    expect(screen.getByRole('img', { name: /품질 Score 추이/ })).toBeInTheDocument()
    expect(screen.getByRole('table', { name: '품질 Score 추이 차트와 동일한 서버 집계 수치' })).toBeInTheDocument()
  })

  it('supports roving keyboard tabs and fetches only the newly active tab resources', async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const url = requestUrl(input)
      if (url.pathname.endsWith('/quality/capability')) return Promise.resolve(json(capability('AVAILABLE')))
      if (url.pathname.endsWith('/quality/overview')) return Promise.resolve(json(overview()))
      if (url.pathname.endsWith('/quality/rule-definitions')) {
        return Promise.resolve(json({
          contract_version: 'QUALITY_TYPED_RULES_V1',
          items: [],
        }))
      }
      if (url.pathname.endsWith('/quality/rule-sets') || url.pathname.endsWith('/quality/assets')) {
        return Promise.resolve(json(emptyPage()))
      }
      return Promise.reject(new Error(`unexpected request: ${url.href}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    const overviewTab = await screen.findByRole('tab', { name: '현황' })
    fireEvent.keyDown(overviewTab, { key: 'ArrowRight' })
    expect(await screen.findByRole('heading', { name: 'Rule Set 관리' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Rule Sets' })).toHaveAttribute('aria-selected', 'true')
    await waitFor(() => {
      expect(requestPaths(fetchMock)).toEqual(expect.arrayContaining([
        '/api/v1/quality/rule-definitions',
        '/api/v1/quality/rule-sets',
        '/api/v1/quality/assets',
      ]))
    })
  })
})

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const client = new ApiClient('/api/v1', () => 'token', () => 'workspace-one')
  return render(
    <QueryClientProvider client={queryClient}>
      <QualityPage
        client={client}
        workspaceId="workspace-one"
        subjectId="subject-one"
        securityEpoch={7}
        authorizationRevision={11}
      />
    </QueryClientProvider>,
  )
}

function capability(readState: 'AVAILABLE' | 'DENIED'): QualityCapability {
  const axes = [
    'read_access',
    'profile_readiness',
  'rule_authoring',
  'review',
  'activation',
    'manual_execution',
    'scheduling',
    'operations',
  ] as const
  return {
    contract_version: 'QUALITY_CAPABILITY_V2',
    observed_at: '2026-07-30T00:00:00Z',
    valid_until: '2026-07-30T00:00:30Z',
    cache_scope: cacheScope,
    axes: axes.map((id) => ({
      id,
      state: id === 'read_access' ? readState : 'UNAVAILABLE',
      ...(id === 'read_access' && readState === 'DENIED' ? { reason_code: 'QUALITY_READ_DENIED' } : {}),
    })),
  }
}

function overview(): QualityOverview {
  return {
    availability: 'AVAILABLE',
    freshness: 'CURRENT',
    as_of: '2026-07-30T00:00:00Z',
    authorization_valid_until: '2026-07-30T00:00:30Z',
    overall_state: 'PASS',
    active_rule_set_count: 4,
    evaluated_rule_set_count: 3,
    unknown_rule_set_count: 1,
    passed_count: 79,
    advisory_failed_count: 0,
    blocking_failed_count: 1,
    evaluated_rule_count: 80,
    score_basis_points: 9_875,
    coverage_basis_points: 7_500,
    failure_code: null,
    trend: [{
      bucket_start: '2026-07-29T00:00:00Z',
      passed_count: 79,
      advisory_failed_count: 0,
      blocking_failed_count: 1,
      evaluated_rule_count: 80,
      score_basis_points: 9_875,
    }],
  }
}

function emptyPage() {
  return {
    items: [],
    page: { next_cursor: null, limit: 25 },
    cache_scope: cacheScope,
    observed_at: '2026-07-30T00:00:00Z',
    authorization_valid_until: '2026-07-30T00:00:30Z',
  }
}

function requestPaths(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls.map(([input]) => requestUrl(input as string | URL | Request).pathname)
}

function requestUrl(input: string | URL | Request): URL {
  if (typeof input === 'string') return new URL(input, 'https://example.test')
  if (input instanceof URL) return input
  return new URL(input.url)
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const cacheScope = 'a'.repeat(64)
