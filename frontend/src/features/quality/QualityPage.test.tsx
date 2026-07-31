import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../api/client'
import type {
  QualityAsset,
  QualityCapability,
} from '../../api/types'
import { QualityPage } from './QualityPage'
import type { QualityAssetFieldWorkspace } from './qualityFieldTypes'

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
    window.history.replaceState(
      {},
      '',
      `/?page=quality&workspace=workspace-one&assetId=${qualityAsset.asset_id}`,
    )
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const url = requestUrl(input)
      const path = url.pathname
      if (path.endsWith('/quality/capability')) return Promise.resolve(json(capability('AVAILABLE')))
      if (path.endsWith('/quality/assets')) return Promise.resolve(json(assetPage()))
      if (path.endsWith('/catalog/tree/nodes')) return Promise.resolve(json(treePage()))
      if (path.endsWith(`/quality/assets/${qualityAsset.asset_id}/workspace`)) {
        return Promise.resolve(json({
          item: assetWorkspace(),
          cache_scope: cacheScope,
          observed_at: '2026-07-30T00:00:00Z',
          authorization_valid_until: '2026-07-30T00:00:30Z',
        }))
      }
      if (path.endsWith(`/quality/assets/${qualityAsset.asset_id}/fields/wafer_id/workspace`)) {
        return Promise.resolve(json({
          item: fieldWorkspace(),
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
    expect(within(tabs).getAllByRole('tab')).toHaveLength(3)
    expect(within(tabs).getByRole('tab', { name: '품질 대시보드' })).toBeInTheDocument()
    expect(screen.getByRole('search', { name: '품질 자산 검색' })).toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: 'Resource Tree' })).toBeInTheDocument()
    expect(screen.getAllByText('98.75%').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Not null checks')).toHaveLength(2)
    expect(screen.getByText('최근 품질 검사 이력')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '최근 30일 품질 점수 추이' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '필드별 품질 관리' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('row', { name: /wafer_id/ }))
    expect(await screen.findByRole('heading', { name: 'wafer_id' })).toBeInTheDocument()
    expect(await screen.findByText(/UNWEIGHTED_RULE_PASS_RATE_V1/)).toBeInTheDocument()
    expect(await screen.findByText('필드 검사 이력')).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '이슈' })).not.toBeInTheDocument()
    expect(screen.queryByText('승인 대기')).not.toBeInTheDocument()
  })

  it('supports roving keyboard tabs and fetches only the newly active tab resources', async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const url = requestUrl(input)
      if (url.pathname.endsWith('/quality/capability')) return Promise.resolve(json(capability('AVAILABLE')))
      if (url.pathname.endsWith('/quality/assets')) return Promise.resolve(json(emptyPage()))
      if (url.pathname.endsWith('/catalog/tree/nodes')) return Promise.resolve(json(treePage()))
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

  it('keeps a valid authorization lease and selected asset requests across focus events', async () => {
    window.history.replaceState(
      {},
      '',
      `/?page=quality&workspace=workspace-one&assetId=${qualityAsset.asset_id}`,
    )
    let resolveWorkspace!: (response: Response) => void
    let workspaceSignal: AbortSignal | undefined
    const workspaceResponse = new Promise<Response>((resolve) => {
      resolveWorkspace = resolve
    })
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = requestUrl(input).pathname
      if (path.endsWith('/quality/capability')) {
        return Promise.resolve(json(capability('AVAILABLE')))
      }
      if (path.endsWith('/quality/assets')) return Promise.resolve(json(emptyPage()))
      if (path.endsWith('/catalog/tree/nodes')) return Promise.resolve(json(treePage()))
      if (path.endsWith(`/quality/assets/${qualityAsset.asset_id}/workspace`)) {
        workspaceSignal = init?.signal ?? undefined
        return workspaceResponse
      }
      return Promise.reject(new Error(`unexpected request: ${requestUrl(input).href}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    await waitFor(() => {
      expect(requestCount(fetchMock, '/api/v1/quality/capability')).toBe(1)
      expect(requestCount(fetchMock, '/api/v1/catalog/tree/nodes')).toBe(1)
      expect(requestCount(
        fetchMock,
        `/api/v1/quality/assets/${qualityAsset.asset_id}/workspace`,
      )).toBe(1)
    })

    act(() => {
      window.dispatchEvent(new Event('focus'))
    })

    expect(requestCount(fetchMock, '/api/v1/quality/capability')).toBe(1)
    expect(requestCount(fetchMock, '/api/v1/catalog/tree/nodes')).toBe(1)
    expect(workspaceSignal?.aborted).toBe(false)

    await act(async () => {
      resolveWorkspace(json({
        item: assetWorkspace(),
        cache_scope: cacheScope,
        observed_at: '2026-07-30T00:00:00Z',
        authorization_valid_until: '2026-07-30T00:00:30Z',
      }))
      await Promise.resolve()
    })
    expect(await screen.findByRole('heading', { name: 'wafer_events' })).toBeInTheDocument()
  })

  it('coalesces repeated focus events while the capability request is in flight', async () => {
    let resolveCapability!: (response: Response) => void
    let capabilitySignal: AbortSignal | undefined
    const capabilityResponse = new Promise<Response>((resolve) => {
      resolveCapability = resolve
    })
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = requestUrl(input).pathname
      if (path.endsWith('/quality/capability')) {
        capabilitySignal = init?.signal ?? undefined
        return capabilityResponse
      }
      if (path.endsWith('/quality/assets')) return Promise.resolve(json(emptyPage()))
      if (path.endsWith('/catalog/tree/nodes')) return Promise.resolve(json(treePage()))
      return Promise.reject(new Error(`unexpected request: ${requestUrl(input).href}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    await waitFor(() => {
      expect(requestCount(fetchMock, '/api/v1/quality/capability')).toBe(1)
    })
    act(() => {
      window.dispatchEvent(new Event('focus'))
      window.dispatchEvent(new Event('focus'))
    })

    expect(requestCount(fetchMock, '/api/v1/quality/capability')).toBe(1)
    expect(capabilitySignal?.aborted).toBe(false)

    await act(async () => {
      resolveCapability(json(capability('AVAILABLE')))
      await Promise.resolve()
    })
    expect(await screen.findByRole('tab', {
      name: '자산별 품질 현황 및 이력',
    })).toBeInTheDocument()
  })

  it('keeps explicit refresh and security boundary changes fail closed', async () => {
    window.history.replaceState(
      {},
      '',
      `/?page=quality&workspace=workspace-one&assetId=${qualityAsset.asset_id}`,
    )
    const workspaceSignals: AbortSignal[] = []
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = requestUrl(input).pathname
      if (path.endsWith('/quality/capability')) {
        return Promise.resolve(json(capability('AVAILABLE')))
      }
      if (path.endsWith('/quality/assets')) return Promise.resolve(json(emptyPage()))
      if (path.endsWith('/catalog/tree/nodes')) return Promise.resolve(json(treePage()))
      if (path.endsWith(`/quality/assets/${qualityAsset.asset_id}/workspace`)) {
        if (init?.signal) workspaceSignals.push(init.signal)
        return new Promise<Response>(() => undefined)
      }
      return Promise.reject(new Error(`unexpected request: ${requestUrl(input).href}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    const page = renderPage()

    await waitFor(() => expect(workspaceSignals).toHaveLength(1))
    fireEvent.click(screen.getByRole('button', { name: '새로고침' }))
    await waitFor(() => {
      expect(workspaceSignals[0]?.aborted).toBe(true)
      expect(requestCount(fetchMock, '/api/v1/quality/capability')).toBe(2)
      expect(workspaceSignals).toHaveLength(2)
    })

    page.rerenderQuality({ securityEpoch: 8 })
    await waitFor(() => {
      expect(workspaceSignals[1]?.aborted).toBe(true)
      expect(requestCount(fetchMock, '/api/v1/quality/capability')).toBe(3)
    })
  })

  it('expires the bounded lease and cancels selected asset requests fail closed', async () => {
    vi.useFakeTimers()
    window.history.replaceState(
      {},
      '',
      `/?page=quality&workspace=workspace-one&assetId=${qualityAsset.asset_id}`,
    )
    const workspaceSignals: AbortSignal[] = []
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = requestUrl(input).pathname
      if (path.endsWith('/quality/capability')) {
        return Promise.resolve(json(capability('AVAILABLE', 100)))
      }
      if (path.endsWith('/quality/assets')) return Promise.resolve(json(emptyPage()))
      if (path.endsWith('/catalog/tree/nodes')) return Promise.resolve(json(treePage()))
      if (path.endsWith(`/quality/assets/${qualityAsset.asset_id}/workspace`)) {
        if (init?.signal) workspaceSignals.push(init.signal)
        return new Promise<Response>(() => undefined)
      }
      return Promise.reject(new Error(`unexpected request: ${requestUrl(input).href}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(requestCount(fetchMock, '/api/v1/quality/capability')).toBe(1)
    expect(workspaceSignals).toHaveLength(1)

    await act(async () => vi.advanceTimersByTimeAsync(101))

    expect(workspaceSignals[0]?.aborted).toBe(true)
    expect(requestCount(fetchMock, '/api/v1/quality/capability')).toBe(2)
  })
})

function renderPage(initial: {
  securityEpoch?: number
  authorizationRevision?: number
} = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const client = new ApiClient('/api/v1', () => 'token', () => 'workspace-one')
  let props = {
    securityEpoch: initial.securityEpoch ?? 7,
    authorizationRevision: initial.authorizationRevision ?? 11,
  }
  const value = () => (
    <QueryClientProvider client={queryClient}>
      <QualityPage
        client={client}
        workspaceId="workspace-one"
        subjectId="subject-one"
        securityEpoch={props.securityEpoch}
        authorizationRevision={props.authorizationRevision}
      />
    </QueryClientProvider>
  )
  const page = render(value())
  return {
    ...page,
    rerenderQuality(next: Partial<typeof props>) {
      props = { ...props, ...next }
      page.rerender(value())
    },
  }
}

function capability(
  readState: 'AVAILABLE' | 'DENIED',
  validForMilliseconds = 30_000,
): QualityCapability {
  const observedAt = '2026-07-30T00:00:00.000Z'
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
    observed_at: observedAt,
    valid_until: new Date(Date.parse(observedAt) + validForMilliseconds).toISOString(),
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

function assetWorkspace(): QualityAssetFieldWorkspace {
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
    authoring: {
      state: 'READY',
      reason_code: null,
      source_version: 'wafer-source-v1',
      schema_hash: 'c'.repeat(64),
      fields: [{
        field_identifier: 'wafer_id',
        display_path: 'wafer_id',
        logical_type: 'STRING',
        supported_rule_kinds: ['NOT_NULL'],
      }],
    },
    fields: [{
      field_identifier: 'wafer_id',
      display_path: 'wafer_id',
      logical_type: 'STRING',
      supported_rule_kinds: ['NOT_NULL'],
      configured_rule_count: 1,
      active_rule_count: 1,
      evaluated_rule_count: 1,
      passed_count: 1,
      advisory_failed_count: 0,
      blocking_failed_count: 0,
      latest_score_basis_points: 10_000,
      latest_quality_outcome: 'PASS',
      latest_evaluated_at: '2026-07-30T00:00:02Z',
    }],
    score_policy: scorePolicy(),
  }
}

function fieldWorkspace() {
  return {
    asset_id: qualityAsset.asset_id,
    field: assetWorkspace().authoring.fields[0],
    rules: [{
      rule_definition_id: 'definition-one',
      rule_set_id: 'rules-one',
      rule_set_name: 'Not null checks',
      version_id: 'version-one',
      version_number: 1,
      version_state: 'ACTIVE',
      kind: 'NOT_NULL',
      severity: 'BLOCKING',
      parameters: {},
    }],
    runs: [{
      run_id: 'run-one',
      rule_set_id: 'rules-one',
      rule_set_name: 'Not null checks',
      state: 'SUCCEEDED',
      run_quality_outcome: 'PASS',
      field_quality_outcome: 'PASS',
      score_basis_points: 10_000,
      passed_count: 1,
      advisory_failed_count: 0,
      blocking_failed_count: 0,
      evaluated_value_count: 80,
      missing_count: 0,
      unexpected_count: 0,
      created_at: '2026-07-30T00:00:00Z',
      completed_at: '2026-07-30T00:00:02Z',
      failure_code: null,
    }],
    trend: [{
      bucket_start: '2026-07-30T00:00:00Z',
      passed_count: 1,
      advisory_failed_count: 0,
      blocking_failed_count: 0,
      evaluated_rule_count: 1,
      score_basis_points: 10_000,
    }],
    score_policy: scorePolicy(),
  }
}

function scorePolicy() {
  return {
    policy_id: 'UNWEIGHTED_RULE_PASS_RATE_V1' as const,
    policy_version: 1 as const,
    policy_hash: 'd'.repeat(64),
    calculation: 'passed / (passed + advisory_failed + blocking_failed)',
    pass_condition: 'evaluated > 0 and advisory_failed = 0 and blocking_failed = 0',
    warn_condition: 'blocking_failed = 0 and advisory_failed > 0',
    fail_condition: 'blocking_failed > 0',
    unknown_condition: 'evaluated = 0',
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

function treePage() {
  return {
    items: [],
    page: { next_cursor: null, limit: 100 },
  }
}

function requestPaths(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls.map(([input]) => requestUrl(input as string | URL | Request).pathname)
}

function requestCount(fetchMock: ReturnType<typeof vi.fn>, path: string): number {
  return requestPaths(fetchMock).filter((value) => value === path).length
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
