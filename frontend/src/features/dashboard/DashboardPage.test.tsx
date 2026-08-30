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

  it('renders source-derived catalog and quality dashboard facts', async () => {
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
    expect(screen.getAllByText('10')).toHaveLength(1)
    expect(screen.getByText('현재 용어사전의 조회 가능한 용어')).toBeInTheDocument()
    expect(await screen.findByText('룰셋 적용 7 / 10 테이블')).toBeInTheDocument()
    expect(screen.getAllByText('70')).toHaveLength(1)
    expect(screen.queryByText('94.2')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '1W' })).toBeDisabled()

    const totalDatasets = screen.getByRole('button', { name: /Total Datasets.*10.*Assets/i })
    totalDatasets.focus()
    fireEvent.click(totalDatasets)
    expect(await screen.findByRole('dialog', { name: 'Asset Distribution & Health Metrics by Database' })).toBeInTheDocument()
    expect(screen.getAllByText('10')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: /Platformpostgres10Assets/i }))
    expect(await screen.findByText('warehouse / core')).toBeInTheDocument()
    expect(screen.getAllByText('70%')).toHaveLength(2)
    expect(screen.getByText('0%')).toBeInTheDocument()
    expect(screen.getByText('40%')).toBeInTheDocument()
    expect(screen.getByRole('group', { name: '태그 1개 이상 보유 자산(분자) 0개 / 현재 Workspace 내 이 항목의 활성·비삭제 자산(분모) 10개' })).toHaveAttribute(
      'title',
      '태그 1개 이상 보유 자산(분자) 0개 / 현재 Workspace 내 이 항목의 활성·비삭제 자산(분모) 10개',
    )
    expect(screen.getByRole('group', { name: '용어 1개 이상 연결 자산(분자) 4개 / 현재 Workspace 내 이 항목의 활성·비삭제 자산(분모) 10개' })).toHaveAttribute(
      'title',
      '용어 1개 이상 연결 자산(분자) 4개 / 현재 Workspace 내 이 항목의 활성·비삭제 자산(분모) 10개',
    )
    fireEvent.click(screen.getByRole('button', { name: '닫기' }))
    expect(totalDatasets).toHaveFocus()
    fireEvent.click(screen.getByRole('link', { name: /Business Glossary.*6.*Terms/i }))
    expect(navigate).toHaveBeenCalledWith('glossary')
    expect(screen.getByRole('heading', { name: 'Data Quality Dashboard' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Metadata Audit Summary' })).not.toBeInTheDocument()
    expect(request).not.toHaveBeenCalledWith('/capabilities')
    expect(screen.getByRole('link', { name: /접수 대기REGISTERED1/ })).toHaveAttribute(
      'href',
      '/?page=change-management&crStateGroup=REGISTERED',
    )
    expect(screen.getByRole('link', { name: /검토·진행검토, 테스트, 적용 진행·보완7/ })).toHaveAttribute(
      'href',
      '/?page=change-management&crStateGroup=IN_PROGRESS',
    )
    expect(screen.getByRole('link', { name: /적용·완료APPLIED, COMPLETED2/ })).toHaveAttribute(
      'href',
      '/?page=change-management&crStateGroup=COMPLETED',
    )
    expect(screen.getByRole('link', { name: /반려·종료REJECTED, CANCELLED2/ })).toHaveAttribute(
      'href',
      '/?page=change-management&crStateGroup=CLOSED',
    )
  })

  it('shows UNKNOWN only when the current active asset denominator is zero', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary({
        catalog_asset_count: 0,
        catalog_described_asset_count: 0,
        catalog_schema_metrics: [{
          platform: 'postgres',
          database_name: 'warehouse',
          schema_name: 'empty',
          asset_count: 0,
          described_asset_count: 0,
          tagged_asset_count: 0,
          term_asset_count: 0,
        }],
      }))
      if (path.startsWith('/change-history/summary?')) return Promise.resolve(changeSummaryForPath(path))
      if (path === '/quality/capability') return Promise.resolve(capability())
      if (path === '/quality/dashboard') return Promise.resolve(quality())
      throw new Error(`Unexpected request: ${path}`)
    })
    renderDashboard(apiClient(request))

    fireEvent.click(await screen.findByRole('button', { name: /Total Datasets.*0.*Assets/i }))
    fireEvent.click(screen.getByRole('button', { name: /Platformpostgres0Assets/i }))

    expect(screen.getAllByText('UNKNOWN')).toHaveLength(3)
    const explanation = '태그 1개 이상 보유 자산(분자) 0개 / 현재 Workspace 내 이 항목의 활성·비삭제 자산(분모) 0개 · 분모가 0이므로 계산할 수 없습니다.'
    expect(screen.getByRole('group', { name: explanation })).toHaveAttribute('title', explanation)
  })

  it('states the bounded hierarchy result instead of silently omitting it', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary({ catalog_schema_metrics_truncated: true }))
      if (path.startsWith('/change-history/summary?')) return Promise.resolve(changeSummaryForPath(path))
      if (path === '/quality/capability') return Promise.resolve(capability())
      if (path === '/quality/dashboard') return Promise.resolve(quality())
      throw new Error(`Unexpected request: ${path}`)
    })
    renderDashboard(apiClient(request))

    fireEvent.click(await screen.findByRole('button', { name: /Total Datasets.*10.*Assets/i }))
    expect(await screen.findByText(/안전한 화면 한도\(200개\)/)).toBeInTheDocument()
  })

  it('distinguishes a known zero CR snapshot from an unavailable progress contract', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary({
        changes_by_state: {},
        change_request_progress: {
          total: 0,
          groups: { REGISTERED: 0, IN_PROGRESS: 0, COMPLETED: 0, CLOSED: 0 },
          complete: true,
        },
      }))
      if (path.startsWith('/change-history/summary?')) return Promise.resolve(changeSummaryForPath(path))
      if (path === '/quality/capability') return Promise.resolve(capability())
      if (path === '/quality/dashboard') return Promise.resolve(quality())
      throw new Error(`Unexpected request: ${path}`)
    })
    const { rerender } = renderDashboard(apiClient(request))

    expect(await screen.findAllByText('0')).toHaveLength(5)

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    rerender(
      <QueryClientProvider client={queryClient}>
        <DashboardPage
          client={apiClient((path) => path === '/operations/dashboard'
            ? Promise.resolve(summary({
              changes_by_state: null,
              change_request_progress: {
                total: null,
                groups: { REGISTERED: null, IN_PROGRESS: null, COMPLETED: null, CLOSED: null },
                complete: false,
              },
            }))
            : path.startsWith('/change-history/summary?')
              ? Promise.resolve(changeSummaryForPath(path))
            : path === '/quality/capability'
              ? Promise.resolve(capability())
              : Promise.resolve(quality()))}
          workspaceId="workspace-two"
          subjectId="subject-two"
          securityEpoch={8}
          authorizationRevision={12}
          onNavigate={vi.fn()}
        />
      </QueryClientProvider>,
    )
    expect((await screen.findAllByText('UNKNOWN')).length).toBeGreaterThanOrEqual(5)
    expect(screen.getByText(/안전한 집계 한도를 초과해 전체성을 확인할 수 없습니다/)).toBeInTheDocument()
  })

  it('renders the canonical current KST week summary with its exact authorized Table scope and warnings', async () => {
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
    const heading = screen.getByRole('heading', { name: '이번 주 데이터 변경' })
    const section = heading.closest('section')
    expect(section).not.toBeNull()
    expect(within(section!).getByText(/현재 사용자가 열람할 수 있으며 시스템에 정확히 연결된 테이블만 집계합니다/)).toBeInTheDocument()
    expect(within(section!).getByText(/동일한 원본 변경에서 파생된 중복 항목은 한 건으로 계산합니다/)).toBeInTheDocument()
    expect(within(section!).getByText('[2026-08-31 00:00, 2026-09-07 00:00) KST (Asia/Seoul)')).toBeInTheDocument()
    expect(within(section!).getByText('전체 변경').parentElement).toHaveTextContent('9')
    expect(within(section!).getByText('스키마 변경').parentElement).toHaveTextContent('4')
    expect(within(section!).getByText('메타데이터 변경').parentElement).toHaveTextContent('5')
    expect(within(section!).getAllByText('연속 캡처 기록됨')).toHaveLength(2)
    expect(within(section!).getByText(/발생 시각 미확정 2건은 이번 주 합계에서 제외/)).toBeInTheDocument()
    expect(within(section!).getByText(/이 주의 시작부터 연속된 완전한 이력은 보장되지 않습니다/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '1W' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '1M' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '3M' })).toBeDisabled()
  })

  it('distinguishes a measured zero current-week summary from section-local unavailability', async () => {
    const zeroRequest = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary())
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

    const zeroHeading = await screen.findByRole('heading', { name: '이번 주 데이터 변경' })
    const zeroSection = zeroHeading.closest('section')
    await waitFor(() => expect(within(zeroSection!).getAllByText('0')).toHaveLength(3))
    expect(within(zeroSection!).queryByText('—')).not.toBeInTheDocument()
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

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('현재 사용자에게 이번 주 데이터 변경을 열람할 권한이 없습니다.')
    expect(within(alert).getAllByText('—')).toHaveLength(3)
    expect(screen.getByText('설명 완성도 70%')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Data Quality Dashboard' })).toBeInTheDocument()
    expect(deniedRequest.mock.calls.filter(([path]) => String(path).startsWith('/change-history/')).length).toBe(1)
  })

  it('delegates Governance Center navigation to the SPA shell without a document navigation', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary())
      if (path.startsWith('/change-history/summary?')) return Promise.resolve(changeSummaryForPath(path))
      if (path === '/quality/capability') return Promise.resolve(capability())
      if (path === '/quality/dashboard') return Promise.resolve(quality())
      throw new Error(`Unexpected request: ${path}`)
    })
    const navigate = vi.fn()
    renderDashboard(apiClient(request), navigate)

    const shortcuts = await screen.findByRole('navigation', { name: 'Governance shortcuts' })
    expect(Array.from(shortcuts.querySelectorAll('strong')).map((item) => item.textContent)).toEqual([
      'Catalog Search',
      'CR',
      'Governance',
      'Quality Management',
      'AI Copilot',
    ])
    expect(screen.queryByRole('link', { name: /Knowledge Graph/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Dataset Registration/i })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('link', { name: /CR변경요청/i }))
    expect(navigate).toHaveBeenCalledWith('change-management')
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

  it('retains asset distribution modal open state, drill-down subview, and back navigation', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary({
        catalog_asset_count: 500,
        catalog_schema_metrics: [{
          platform: 'postgres', database_name: 'MANUFACTURING', schema_name: 'QUALITY',
          asset_count: 500, described_asset_count: 100, tagged_asset_count: 50, term_asset_count: 10,
        }],
      }))
      if (path.startsWith('/change-history/summary?')) return Promise.resolve(changeSummaryForPath(path))
      if (path === '/quality/capability') return Promise.resolve(capability())
      if (path === '/quality/dashboard') return Promise.resolve(quality())
      throw new Error(`Unexpected request: ${path}`)
    })
    const navigate = vi.fn()
    renderDashboard(apiClient(request), navigate)

    fireEvent.click(await screen.findByRole('button', { name: /Total Datasets.*500.*Assets/i }))
    const dialog = screen.getByRole('dialog', { name: 'Asset Distribution & Health Metrics by Database' })
    fireEvent.click(within(dialog).getByRole('button', { name: /Platformpostgres500Assets/i }))
    const schemaCard = within(dialog).getByRole('button', { name: /MANUFACTURING \/ QUALITY.*500 Assets/ })
    fireEvent.click(schemaCard)

    expect(within(dialog).getByRole('heading', { name: '스키마 상세 정보' })).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: /Platformpostgres/ })).not.toBeInTheDocument()
    expect(within(dialog).getByRole('heading', { name: '스키마 상세 정보' }).parentElement).not.toHaveAttribute('style')
    fireEvent.click(within(dialog).getByRole('button', { name: '이전' }))

    expect(within(dialog).queryByRole('heading', { name: '스키마 상세 정보' })).not.toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: /Platformpostgres500Assets/i })).toBeInTheDocument()
    expect(navigate).not.toHaveBeenCalled()
  })
})
