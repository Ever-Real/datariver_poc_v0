import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../api/client'
import type {
  QualityAsset,
  QualityAssetWorkspace,
  QualityCapability,
} from '../../api/types'
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

    expect(await screen.findByRole('heading', { name: '품질 데이터 열람 권한이 없습니다' })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(requestPaths(fetchMock)).toEqual(['/api/v1/quality/capability'])
  })

  it('combines one asset rule sets, recent runs, and score trend in one inspector', async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = requestUrl(input).pathname
      if (path.endsWith('/quality/capability')) return Promise.resolve(json(capability('AVAILABLE')))
      if (path.endsWith('/quality/assets')) return Promise.resolve(json(assetPage()))
      if (path.endsWith(`/quality/assets/${qualityAsset.asset_id}/workspace`)) {
        return Promise.resolve(json({
          item: assetWorkspace(),
          cache_scope: cacheScope,
          observed_at: '2026-07-30T00:00:00Z',
          authorization_valid_until: '2026-07-30T00:00:30Z',
        }))
      }
      return Promise.reject(new Error(`unexpected request: ${requestUrl(input).href}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    expect(await screen.findByRole('heading', { name: 'wafer_events' })).toBeInTheDocument()
    const tabs = screen.getByRole('tablist', { name: '품질관리 영역' })
    expect(within(tabs).getAllByRole('tab')).toHaveLength(2)
    expect(screen.getAllByText('98.75%').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Not null checks')).toHaveLength(2)
    expect(screen.getByText('최근 품질 검사 이력')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '최근 30일 품질 점수 추이' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '이슈' })).not.toBeInTheDocument()
    expect(screen.queryByText('승인 대기')).not.toBeInTheDocument()
  })

  it('supports roving keyboard tabs and fetches only the newly active tab resources', async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const url = requestUrl(input)
      if (url.pathname.endsWith('/quality/capability')) return Promise.resolve(json(capability('AVAILABLE')))
      if (url.pathname.endsWith('/quality/assets')) return Promise.resolve(json(emptyPage()))
      if (url.pathname.endsWith('/quality/common-rule-templates')) {
        return Promise.resolve(json(emptyPage()))
      }
      return Promise.reject(new Error(`unexpected request: ${url.href}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    const assetsTab = await screen.findByRole('tab', { name: '자산별 품질 현황 및 이력' })
    fireEvent.keyDown(assetsTab, { key: 'ArrowRight' })
    expect(await screen.findByRole('heading', { name: '공통 룰셋 관리' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '공통 룰셋 관리' })).toHaveAttribute('aria-selected', 'true')
    await waitFor(() => {
      expect(requestPaths(fetchMock)).toEqual(expect.arrayContaining([
        '/api/v1/quality/assets',
        '/api/v1/quality/common-rule-templates',
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

const qualityAsset: QualityAsset = {
  asset_id: '00000000-0000-4000-8000-000000000201',
  name: 'wafer_events',
  platform: 'snowflake',
  database_name: 'analytics',
  schema_name: 'manufacturing',
  classification: 'INTERNAL',
  lifecycle: 'ACTIVE',
  profile_readiness: 'READY',
  profile_observed_at: '2026-07-30T00:00:00Z',
  active_rule_set_count: 1,
  latest_run_state: 'SUCCEEDED',
  latest_quality_outcome: 'PASS',
  latest_score_basis_points: 9_875,
}

function assetPage() {
  return {
    ...emptyPage(),
    items: [qualityAsset],
  }
}

function assetWorkspace(): QualityAssetWorkspace {
  return {
    asset: qualityAsset,
    rule_sets: [{
      rule_set_id: 'rules-one',
      asset_id: qualityAsset.asset_id,
      asset_name: qualityAsset.name,
      name: 'Not null checks',
      state: 'ACTIVE',
      active_version_id: 'version-one',
      active_version_number: 1,
      active_version_state: 'ACTIVE',
      rule_count: 2,
      created_at: '2026-07-29T00:00:00Z',
      updated_at: '2026-07-30T00:00:00Z',
      version: 1,
    }],
    runs: [{
      run_id: 'run-one',
      rule_set_id: 'rules-one',
      rule_set_name: 'Not null checks',
      asset_id: qualityAsset.asset_id,
      asset_name: qualityAsset.name,
      trigger_kind: 'SCHEDULED',
      state: 'SUCCEEDED',
      quality_outcome: 'PASS',
      passed_count: 79,
      advisory_failed_count: 0,
      blocking_failed_count: 1,
      score_basis_points: 9_875,
      created_at: '2026-07-30T00:00:00Z',
      completed_at: '2026-07-30T00:00:02Z',
      failure_code: null,
      version: 1,
    }],
    trend: [{
      bucket_start: '2026-07-30T00:00:00Z',
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
