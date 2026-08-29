import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../../api/client'
import type { QualityCapability } from '../../api/types'
import type { QualityDashboard } from '../quality/qualityDashboardTypes'
import { DashboardPage } from './DashboardPage'

function summary(overrides: Record<string, unknown> = {}) {
  return {
    observed_at: '2026-07-18T00:00:00Z',
    changes_by_state: { REGISTERED: 2, IN_REVIEW: 3, APPLIED: 4 },
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

function renderDashboard(client: ApiClient, onNavigate = vi.fn()) {
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
      />
    </QueryClientProvider>,
  )
}

describe('DashboardPage', () => {
  it('renders source-derived catalog and quality dashboard facts', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary())
      if (path === '/quality/capability') return Promise.resolve(capability())
      if (path === '/quality/dashboard') return Promise.resolve(quality())
      throw new Error(`Unexpected request: ${path}`)
    })
    renderDashboard(apiClient(request))

    expect(await screen.findByText('설명 완성도 70%')).toBeInTheDocument()
    expect(screen.getAllByText('10')).toHaveLength(2)
    expect(screen.getByText('활성화된 서버 동기화 용어')).toBeInTheDocument()
    expect(await screen.findByText('룰셋 적용 7 / 10 테이블')).toBeInTheDocument()
    expect(screen.getAllByText('70')).toHaveLength(1)
    expect(screen.queryByText('94.2')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '1W' })).toBeDisabled()

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
    expect(screen.getByRole('heading', { name: 'Data Quality Dashboard' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Metadata Audit Summary' })).not.toBeInTheDocument()
    expect(request).not.toHaveBeenCalledWith('/capabilities')
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
      if (path === '/quality/capability') return Promise.resolve(capability())
      if (path === '/quality/dashboard') return Promise.resolve(quality())
      throw new Error(`Unexpected request: ${path}`)
    })
    renderDashboard(apiClient(request))

    fireEvent.click(await screen.findByRole('button', { name: /Platformpostgres0Assets/i }))

    expect(screen.getAllByText('UNKNOWN')).toHaveLength(3)
    const explanation = '태그 1개 이상 보유 자산(분자) 0개 / 현재 Workspace 내 이 항목의 활성·비삭제 자산(분모) 0개 · 분모가 0이므로 계산할 수 없습니다.'
    expect(screen.getByRole('group', { name: explanation })).toHaveAttribute('title', explanation)
  })

  it('states the bounded hierarchy result instead of silently omitting it', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary({ catalog_schema_metrics_truncated: true }))
      if (path === '/quality/capability') return Promise.resolve(capability())
      if (path === '/quality/dashboard') return Promise.resolve(quality())
      throw new Error(`Unexpected request: ${path}`)
    })
    renderDashboard(apiClient(request))

    expect(await screen.findByText(/안전한 화면 한도\(200개\)/)).toBeInTheDocument()
  })

  it('delegates Governance Center navigation to the SPA shell without a document navigation', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/operations/dashboard') return Promise.resolve(summary())
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
})
