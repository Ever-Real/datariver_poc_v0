import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type ApiClient } from '../../api/client'
import type { QualityCapability } from '../../api/types'
import type { QualityDashboard } from '../quality/qualityDashboardTypes'
import { DashboardPage } from './DashboardPage'

function summary(overrides: Record<string, unknown> = {}) {
  return {
    observed_at: '2026-07-18T00:00:00Z',
    changes_by_state: {
      REGISTERED: 1,
      IN_REVIEW: 1,
      TESTING: 1,
      FINAL_REVIEW: 1,
      APPLY_QUEUED: 1,
      APPLYING: 1,
      APPLIED: 1,
      APPLY_FAILED: 1,
      COMPLETED: 1,
      CHANGES_REQUESTED: 1,
      REJECTED: 1,
      CANCELLED: 1,
    },
    change_request_progress: {
      total: 12,
      groups: { REGISTERED: 1, IN_PROGRESS: 7, COMPLETED: 2, CLOSED: 2 },
      complete: true,
    },
    catalog_asset_count: 10,
    catalog_described_asset_count: 7,
    catalog_glossary_term_count: 6,
    catalog_schema_metrics: [{
      platform: 'postgres',
      database_name: 'warehouse',
      schema_name: 'core',
      asset_count: 10,
      described_asset_count: 7,
      tagged_asset_count: 0,
      term_asset_count: 4,
    }],
    catalog_schema_metrics_truncated: false,
    ...overrides,
  }
}

function quality(overrides: Partial<QualityDashboard> = {}): QualityDashboard {
  return {
    contract_version: 'QUALITY_DASHBOARD_V1',
    cache_scope: 'a'.repeat(64),
    observed_at: '2026-07-18T00:00:00Z',
    authorization_valid_until: '2026-07-18T00:00:30Z',
    as_of: '2026-07-18T00:00:00Z',
    schema_count: 2,
    table_count: 10,
    active_rule_set_count: 3,
    common_rule_template_count: 2,
    covered_table_count: 7,
    table_coverage_basis_points: 7_000,
    managed_rule_sets: [
      {
        indicator_id: 'ACCURACY',
        name: '정확성',
        definition: '서버 정의',
        calculation: '서버 계산식',
        target_grain: 'FIELD',
        rule_kinds: ['RANGE'],
        contract_version: 'QUALITY_MANAGED_INDICATORS_V1',
      },
      {
        indicator_id: 'COMPLETENESS',
        name: '완전성',
        definition: '서버 정의',
        calculation: '서버 계산식',
        target_grain: 'FIELD',
        rule_kinds: ['NOT_NULL'],
        contract_version: 'QUALITY_MANAGED_INDICATORS_V1',
      },
      {
        indicator_id: 'TIMELINESS',
        name: '적시성',
        definition: '서버 정의',
        calculation: '서버 계산식',
        target_grain: 'TABLE',
        rule_kinds: [],
        contract_version: 'QUALITY_MANAGED_INDICATORS_V1',
      },
    ],
    schemas: [],
    schemas_truncated: false,
    ...overrides,
  }
}

function currentWeekChangeSummary(weekStart: string, overrides: Record<string, unknown> = {}) {
  const weekEnd = new Date(`${weekStart}T00:00:00.000Z`)
  weekEnd.setUTCDate(weekEnd.getUTCDate() + 7)
  return {
    week_start: weekStart,
    week_end_exclusive: weekEnd.toISOString().slice(0, 10),
    timezone: 'Asia/Seoul',
    as_of: '2026-08-31T01:00:00.000Z',
    policy_version: 1,
    policy_hash: '4'.repeat(64),
    count_unit: 'DISTINCT_NORMALIZED_CHANGE_TRANSACTION',
    total_count: 9,
    unlinked_count: 9,
    received_count: 0,
    recheck_count: 0,
    testing_count: 0,
    final_review_count: 0,
    completed_count: 0,
    time_unknown_count: 0,
    schema_change_count: 4,
    metadata_change_count: 5,
    event_count: 11,
    distinct_asset_count: 6,
    precision_counts: {
      EXACT_TIMELINE: 0,
      EXACT_MCL: 9,
      DRIFT_DETECTED: 0,
      BACKFILLED_BEST_EFFORT: 0,
      INITIAL_BASELINE: 0,
    },
    category_counts: {
      TECHNICAL_SCHEMA: 4,
      DOCUMENTATION: 5,
      TAG: 0,
      GLOSSARY_TERM: 0,
      DOMAIN: 0,
      OWNERSHIP: 0,
      LIFECYCLE: 0,
    },
    operation_counts: { CREATE: 0, UPDATE: 9, UPSERT: 0, DELETE: 0, ADD: 0, REMOVE: 0 },
    capture_state: 'CONTIGUOUS_CAPTURE_RECORDED',
    sync_status: 'CONTIGUOUS_CAPTURE_RECORDED',
    capture_failure_classification: null,
    capture_failure_stage: null,
    capture_failure_detail_code: null,
    capture_failure_record_shape: null,
    source_generation: '5'.repeat(64),
    source_observed_at: '2026-08-31T01:00:00.000Z',
    source_occurred_at: '2026-08-31T00:30:00.000Z',
    detected_at: '2026-08-31T00:31:00.000Z',
    captured_at: '2026-08-31T00:32:00.000Z',
    effective_week_start: weekStart,
    history_available_from: null,
    ledger_guarantee_from: null,
    first_exact_capture_at: null,
    first_timeline_checkpoint: null,
    first_mcl_offsets: null,
    last_successful_capture_at: '2026-08-31T00:32:00.000Z',
    ...overrides,
  }
}

function changeSummaryForPath(path: string, overrides: Record<string, unknown> = {}) {
  const weekStart = new URL(path, 'https://datariver.invalid').searchParams.get('week_start') ?? ''
  return currentWeekChangeSummary(weekStart, overrides)
}

function apiClient(request: (path: string) => Promise<unknown>): ApiClient {
  return { request } as unknown as ApiClient
}

function capability(): QualityCapability {
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
    observed_at: '2026-07-18T00:00:00Z',
    valid_until: '2026-07-18T00:00:30Z',
    cache_scope: 'a'.repeat(64),
    axes: axes.map((id) => ({
      id,
      state: id === 'read_access' ? 'AVAILABLE' : 'UNAVAILABLE',
      ...(id === 'read_access' ? {} : { reason_code: `${id.toUpperCase()}_UNAVAILABLE` }),
    })),
  }
}

function renderDashboard(client: ApiClient, onNavigate = vi.fn(), onStartChat?: (question: string) => void) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <DashboardPage
        client={client}
        workspaceId="workspace-one"
        subjectId="subject-one"
        securityEpoch={7}
        authorizationRevision={11}
        onNavigate={onNavigate}
        onStartChat={onStartChat}
      />
    </QueryClientProvider>,
  )
}

describe('DashboardPage', () => {
  afterEach(() => vi.useRealTimers())

  it('renders four compact summaries and four approved-source analytics without the legacy modal or Governance Center', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary())
      if (path.startsWith('/change-history/summary?')) return Promise.resolve(changeSummaryForPath(path))
      if (path === '/quality/capability') return Promise.resolve(capability())
      if (path === '/quality/dashboard') return Promise.resolve(quality())
      throw new Error(`Unexpected request: ${path}`)
    })
    const navigate = vi.fn()
    renderDashboard(apiClient(request), navigate)

    expect(await screen.findByText('설명 완성도 70%')).toBeInTheDocument()
    expect(screen.getByText('현재 용어사전의 조회 가능한 용어')).toBeInTheDocument()
    expect(await screen.findByText('룰셋 적용 7 / 10 테이블')).toBeInTheDocument()
    const totalDatasets = screen.getByRole('link', { name: /Total Datasets.*10.*Assets/i })
    fireEvent.click(totalDatasets)
    expect(navigate).toHaveBeenCalledWith('catalog')
    expect(screen.queryByRole('dialog', { name: /Asset Distribution/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', { name: /Business Glossary.*6.*Terms/i }))
    expect(navigate).toHaveBeenCalledWith('glossary')
    const summaryGrid = totalDatasets.parentElement
    expect(summaryGrid?.querySelectorAll('.dashboard-stat-card')).toHaveLength(4)
    expect(screen.getByRole('heading', { name: '전체 Dataset 1주 trend' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Schema별 metadata 등록 현황' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Data Quality Dashboard' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Schema별 최근 7일 변경요청' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Governance Center' })).not.toBeInTheDocument()
    expect(within(totalDatasets).getByText('Schema별 Dataset')).toBeInTheDocument()
    expect(within(totalDatasets).getByLabelText('Schema별 현재 Dataset 수 목록')).toHaveTextContent('warehouse / core10')

    const schemaSection = screen.getByRole('heading', { name: 'Schema별 metadata 등록 현황' }).closest('section')!
    expect(within(schemaSection).getByText('warehouse / core')).toBeInTheDocument()
    expect(within(schemaSection).getByRole('group', { name: /설명 보유 자산.*7개.*10개/ })).toHaveTextContent('70%')
    expect(within(schemaSection).getByRole('group', { name: /태그 1개 이상 보유 자산.*0개.*10개/ })).toHaveTextContent('0%')
    expect(within(schemaSection).getByRole('group', { name: /용어 1개 이상 연결 자산.*4개.*10개/ })).toHaveTextContent('40%')
    const qualitySection = screen.getByRole('heading', { name: 'Data Quality Dashboard' }).closest('section')!
    expect(within(qualitySection).getByText('70%')).toBeInTheDocument()
    expect(within(qualitySection).getByText('3')).toBeInTheDocument()
  })

  it('requests the canonical KST week summary and keeps CR and change-event meanings separate', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-08-30T15:30:00.000Z'))
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary())
      if (path.startsWith('/change-history/summary?')) {
        return Promise.resolve(changeSummaryForPath(path, { time_unknown_count: 2 }))
      }
      if (path === '/quality/capability') return Promise.resolve(capability())
      if (path === '/quality/dashboard') return Promise.resolve(quality())
      throw new Error(`Unexpected request: ${path}`)
    })
    renderDashboard(apiClient(request))

    await waitFor(() => expect(request.mock.calls.map(([path]) => path)).toContain(
      '/change-history/summary?week_start=2026-08-31',
    ))
    const crCard = screen.getByRole('link', { name: /Change Request Progress.*12.*Requests/ })
    expect(within(crCard).getByText('전체 변경').parentElement).toHaveTextContent('9')
    expect(within(crCard).getByText('스키마').parentElement).toHaveTextContent('4')
    expect(within(crCard).getByText('메타데이터').parentElement).toHaveTextContent('5')
    expect(crCard).toHaveTextContent('진행 7 · 완료 2')
  })

  it('distinguishes measured zero from unavailable CR and change facts', async () => {
    const zeroRequest = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary({
        change_request_progress: {
          total: 0,
          groups: { REGISTERED: 0, IN_PROGRESS: 0, COMPLETED: 0, CLOSED: 0 },
          complete: true,
        },
      }))
      if (path.startsWith('/change-history/summary?')) {
        return Promise.resolve(changeSummaryForPath(path, {
          total_count: 0,
          unlinked_count: 0,
          schema_change_count: 0,
          metadata_change_count: 0,
        }))
      }
      if (path === '/quality/capability') return Promise.resolve(capability())
      if (path === '/quality/dashboard') return Promise.resolve(quality())
      throw new Error(`Unexpected request: ${path}`)
    })
    const { unmount } = renderDashboard(apiClient(zeroRequest))

    const zeroCard = await screen.findByRole('link', { name: /Change Request Progress.*0.*Requests/ })
    await waitFor(() => expect(within(zeroCard).queryByText('—')).not.toBeInTheDocument())
    expect(zeroCard).not.toHaveTextContent('UNKNOWN')
    unmount()

    const denied = new ApiError({
      type: 'about:blank',
      title: 'Forbidden',
      status: 403,
      detail: 'change.read is required.',
      code: 'FORBIDDEN',
      request_id: 'request-denied',
    })
    const deniedRequest = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary())
      if (path.startsWith('/change-history/summary?')) return Promise.reject(denied)
      if (path === '/quality/capability') return Promise.resolve(capability())
      if (path === '/quality/dashboard') return Promise.resolve(quality())
      throw new Error(`Unexpected request: ${path}`)
    })
    renderDashboard(apiClient(deniedRequest))

    const deniedCard = await screen.findByRole('link', { name: /Change Request Progress.*12.*Requests/ })
    expect(within(deniedCard).getAllByText('—')).toHaveLength(3)
    expect(deniedCard).toHaveTextContent('현재 사용자에게 이번 주 데이터 변경을 열람할 권한이 없습니다.')
    expect(deniedRequest.mock.calls.filter(([path]) => String(path).startsWith('/change-history/')).length).toBe(1)
  })

  it('shows explicit unavailable contracts instead of fabricating historical trends', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary())
      if (path.startsWith('/change-history/summary?')) return Promise.resolve(changeSummaryForPath(path))
      if (path === '/quality/capability') return Promise.resolve(capability())
      if (path === '/quality/dashboard') return Promise.resolve(quality())
      throw new Error(`Unexpected request: ${path}`)
    })
    renderDashboard(apiClient(request))

    expect(await screen.findByText('HISTORICAL_DATASET_COUNT_SOURCE_UNAVAILABLE')).toBeInTheDocument()
    expect(screen.getByText('SCHEMA_CR_7_DAY_SOURCE_UNAVAILABLE')).toBeInTheDocument()
    expect(screen.getByText(/현재 수치를 과거 값으로 복제하지 않습니다/)).toBeInTheDocument()
    expect(screen.getByText(/Schema별 값으로 나누어 추정하지 않습니다/)).toBeInTheDocument()
  })

  it('starts a new Chat request from the compact home search without sending blank text', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary())
      if (path.startsWith('/change-history/summary?')) return Promise.resolve(changeSummaryForPath(path))
      if (path === '/quality/capability') return Promise.resolve(capability())
      if (path === '/quality/dashboard') return Promise.resolve(quality())
      throw new Error(`Unexpected request: ${path}`)
    })
    const startChat = vi.fn()
    renderDashboard(apiClient(request), vi.fn(), startChat)

    const input = await screen.findByRole('searchbox', { name: 'Chat에 질문하기' })
    const submit = screen.getByRole('button', { name: '새 Chat에서 질문하기' })
    expect(submit).toBeDisabled()
    fireEvent.change(input, { target: { value: '   current metadata를 찾아줘   ' } })
    expect(submit).toBeEnabled()
    fireEvent.click(submit)
    expect(startChat).toHaveBeenCalledWith('current metadata를 찾아줘')
  })

  it('states when the canonical schema aggregate itself is bounded', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary({
        catalog_schema_metrics_truncated: true,
      }))
      if (path.startsWith('/change-history/summary?')) return Promise.resolve(changeSummaryForPath(path))
      if (path === '/quality/capability') return Promise.resolve(capability())
      if (path === '/quality/dashboard') return Promise.resolve(quality())
      throw new Error(`Unexpected request: ${path}`)
    })
    renderDashboard(apiClient(request))

    expect(await screen.findByText(/서버가 제공한 bounded schema 집계 범위/)).toBeInTheDocument()
  })

  it('keeps every server-provided schema in compact, keyboard-scrollable lists rather than truncating to three', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary({
        catalog_schema_metrics: [
          { platform: 'postgres', database_name: 'warehouse', schema_name: 'alpha', asset_count: 4, described_asset_count: 2, tagged_asset_count: 1, term_asset_count: 1 },
          { platform: 'postgres', database_name: 'warehouse', schema_name: 'beta', asset_count: 3, described_asset_count: 1, tagged_asset_count: 2, term_asset_count: 1 },
          { platform: 'postgres', database_name: 'warehouse', schema_name: 'gamma', asset_count: 2, described_asset_count: 2, tagged_asset_count: 0, term_asset_count: 2 },
          { platform: 'postgres', database_name: 'warehouse', schema_name: 'delta', asset_count: 1, described_asset_count: 0, tagged_asset_count: 0, term_asset_count: 0 },
        ],
      }))
      if (path.startsWith('/change-history/summary?')) return Promise.resolve(changeSummaryForPath(path))
      if (path === '/quality/capability') return Promise.resolve(capability())
      if (path === '/quality/dashboard') return Promise.resolve(quality())
      throw new Error(`Unexpected request: ${path}`)
    })
    renderDashboard(apiClient(request))

    const schemaList = await screen.findByLabelText('Schema별 metadata 등록률 목록')
    expect(schemaList).toHaveAttribute('tabindex', '0')
    expect(screen.getByText(/Schema · 상하로 스크롤해 탐색/)).toBeInTheDocument()
    expect(schemaList).toHaveTextContent('warehouse / alpha')
    expect(schemaList).toHaveTextContent('warehouse / delta')
    const counts = screen.getByLabelText('Schema별 현재 Dataset 수 목록')
    expect(counts).toHaveAttribute('tabindex', '0')
    expect(counts).toHaveTextContent('warehouse / alpha4')
    expect(counts).toHaveTextContent('warehouse / delta1')
  })
})
