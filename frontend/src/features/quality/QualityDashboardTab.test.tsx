import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../../api/client'
import { QualityApi, type QualitySecurityBoundary } from './qualityApi'
import type { QualityDashboard } from './qualityDashboardTypes'
import { QualityDashboardTab } from './QualityDashboardTab'

describe('QualityDashboardTab', () => {
  it('opens indicator analysis and expands a risk field inside the modal', async () => {
    const request = vi.fn().mockResolvedValue(dashboard)
    renderDashboard(request)

    expect(await screen.findByRole('heading', { name: '품질 대시보드' })).toBeInTheDocument()
    expect(screen.getByText('2 tables')).toBeInTheDocument()
    expect(screen.getByTitle('활성 룰셋이 하나 이상 적용된 테이블은 적용 완료(100%)로 세고, 적용 테이블 수를 전체 테이블 수로 나눕니다.')).toBeInTheDocument()

    fireEvent.click(screen.getByTitle('정확성 · 최근 성공 실행의 유효 값 수 ÷ 평가 값 수'))
    const dialog = await screen.findByRole('dialog', {
      name: 'snowflake / analytics / manufacturing · 품질 분석',
    })
    expect(within(dialog).getByText('평가결과 레포트')).toBeInTheDocument()
    expect(within(dialog).getByText('서버 사실 요약')).toBeInTheDocument()
    expect(within(dialog).getByText('wafer_events')).toBeInTheDocument()

    fireEvent.click(within(dialog).getByText('wafer_events'))
    expect(within(dialog).getByText('허용 범위를 벗어난 값 5건')).toBeInTheDocument()

    fireEvent.click(within(dialog).getByRole('button', { name: /완전성/ }))
    expect(within(dialog).getByRole('heading', { name: '완전성 분석' })).toBeInTheDocument()
  })

  it.each([
    [null, '평가 없음', 1],
    [0, '0%', 1],
    [5_000, '50%', 0.5],
    [10_000, '100%', 0],
  ] as const)('renders CSP-safe bounded gauge geometry for %s basis points', async (
    score,
    label,
    remainingFraction,
  ) => {
    const request = vi.fn().mockResolvedValue(dashboardWithAccuracyScore(score))
    renderDashboard(request)

    fireEvent.click(await screen.findByTitle('정확성 · 최근 성공 실행의 유효 값 수 ÷ 평가 값 수'))
    const dialog = await screen.findByRole('dialog', {
      name: 'snowflake / analytics / manufacturing · 품질 분석',
    })
    const gauge = within(dialog).getByLabelText(`정확성 품질 수치 ${label}`)
    expect(gauge).not.toHaveAttribute('style')
    const svg = gauge.querySelector('svg')
    expect(svg).toBeInTheDocument()
    expect(svg).toHaveAttribute('viewBox', '0 0 118 118')
    const circles = svg!.querySelectorAll('circle')
    expect(circles).toHaveLength(2)
    const progressCircle = circles[1]
    const dasharray = Number(progressCircle!.getAttribute('stroke-dasharray'))
    const dashoffset = Number(progressCircle!.getAttribute('stroke-dashoffset'))
    expect(dasharray).toBeGreaterThan(0)
    expect(dashoffset).toBeCloseTo(dasharray * remainingFraction, 5)
  })
})

function renderDashboard(request: ReturnType<typeof vi.fn>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const api = new QualityApi({
    request: request as unknown as ApiClient['request'],
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <QualityDashboardTab
        api={api}
        boundary={boundary}
        onOpenTemplates={vi.fn()}
        onBoundaryInvalid={vi.fn()}
      />
    </QueryClientProvider>,
  )
}

const boundary: QualitySecurityBoundary = {
  workspaceId: 'workspace-one',
  subjectId: 'subject-one',
  securityEpoch: 7,
  authorizationRevision: 11,
  cacheScope: 'a'.repeat(64),
}
const indicatorIds = ['ACCURACY', 'COMPLETENESS', 'TIMELINESS'] as const
const dashboard: QualityDashboard = {
  contract_version: 'QUALITY_DASHBOARD_V1',
  cache_scope: boundary.cacheScope,
  observed_at: '2026-07-30T00:00:00Z',
  authorization_valid_until: '2026-07-30T00:00:30Z',
  as_of: '2026-07-30T00:00:00Z',
  schema_count: 1,
  table_count: 2,
  active_rule_set_count: 3,
  common_rule_template_count: 2,
  covered_table_count: 1,
  table_coverage_basis_points: 5_000,
  managed_rule_sets: indicatorIds.map((indicatorId) => ({
    indicator_id: indicatorId,
    name: indicatorId === 'ACCURACY'
      ? '정확성'
      : indicatorId === 'COMPLETENESS'
        ? '완전성'
        : '적시성',
    definition: `${indicatorId} 정의`,
    calculation: indicatorId === 'ACCURACY'
      ? '최근 성공 실행의 유효 값 수 ÷ 평가 값 수'
      : `${indicatorId} 계산식`,
    target_grain: indicatorId === 'TIMELINESS' ? 'TABLE' : 'FIELD',
    rule_kinds: indicatorId === 'ACCURACY'
      ? ['RANGE']
      : indicatorId === 'COMPLETENESS'
        ? ['NOT_NULL']
        : [],
    contract_version: 'QUALITY_MANAGED_INDICATORS_V1',
  })),
  schemas: [{
    schema_id: 'b'.repeat(64),
    platform: 'snowflake',
    database_name: 'analytics',
    schema_name: 'manufacturing',
    table_count: 2,
    covered_table_count: 1,
    indicators: indicatorIds.map((indicatorId) => ({
      indicator_id: indicatorId,
      counted_target_count: 1,
      target_count: 2,
      coverage_basis_points: 5_000,
      score_basis_points: indicatorId === 'ACCURACY' ? 9_500 : 9_000,
      outcome: 'WARN',
      risk_count: indicatorId === 'ACCURACY' ? 1 : 0,
      evaluated_value_count: 100,
      report_state: 'FACTS_ONLY',
      report_reason_code: 'QUALITY_LLM_REPORT_ROUTE_UNAVAILABLE',
      report_summary: `${indicatorId} 서버 사실 요약`,
      risks: indicatorId === 'ACCURACY' ? [{
        risk_id: 'c'.repeat(64),
        asset_id: '00000000-0000-4000-8000-000000000201',
        asset_name: 'wafer_events',
        field_identifier: 'yield_rate',
        severity: 'ADVISORY',
        outcome: 'ADVISORY_FAIL',
        score_basis_points: 9_500,
        evaluated_count: 100,
        failed_count: 5,
        observed_at: '2026-07-30T00:00:00Z',
        detail: '허용 범위를 벗어난 값 5건',
      }] : [],
    })),
  }],
  schemas_truncated: false,
}

function dashboardWithAccuracyScore(score: number | null): QualityDashboard {
  return {
    ...dashboard,
    schemas: dashboard.schemas.map((schema) => ({
      ...schema,
      indicators: schema.indicators.map((indicator) => indicator.indicator_id === 'ACCURACY'
        ? { ...indicator, score_basis_points: score }
        : indicator),
    })),
  }
}
