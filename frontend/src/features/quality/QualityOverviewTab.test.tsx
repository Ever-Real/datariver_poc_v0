import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { QualityOverview } from '../../api/types'
import { QualityOverviewTab } from './QualityOverviewTab'
import { QualityApi, type QualitySecurityBoundary } from './qualityApi'

describe('QualityOverviewTab', () => {
  it('renders server result counts as an accessible chart and equivalent table', async () => {
    renderOverview(overview())

    expect(await screen.findByRole('img', { name: /품질 Rule 결과 건수 추이/ })).toBeInTheDocument()
    const table = screen.getByRole('table', {
      name: '품질 Rule 결과 건수 추이 차트와 동일한 서버 집계 수치',
    })
    expect(within(table).getByRole('columnheader', { name: 'PASS' })).toBeInTheDocument()
    expect(within(table).getByRole('cell', { name: '73' })).toBeInTheDocument()
    expect(within(table).getByRole('cell', { name: '4' })).toBeInTheDocument()
    expect(within(table).getByRole('cell', { name: '3' })).toBeInTheDocument()
    expect(within(table).getByRole('cell', { name: '80' })).toBeInTheDocument()
  })

  it('renders current server coverage as a progressbar and equivalent table', async () => {
    renderOverview(overview())

    const progress = await screen.findByRole('progressbar', { name: '현재 Rule Set coverage' })
    expect(progress).toHaveAttribute('max', '10000')
    expect(progress).toHaveAttribute('value', '7500')
    const table = screen.getByRole('table', {
      name: '현재 Rule Set coverage 막대와 동일한 서버 집계 수치',
    })
    expect(within(table).getByRole('rowheader', { name: '75%' })).toBeInTheDocument()
    expect(within(table).getByRole('cell', { name: '4' })).toBeInTheDocument()
    expect(within(table).getByRole('cell', { name: '3' })).toBeInTheDocument()
    expect(within(table).getByRole('cell', { name: '1' })).toBeInTheDocument()
  })

  it('does not invent a progressbar when the server coverage is unavailable', async () => {
    renderOverview(overview({ coverage_basis_points: null }))

    expect(await screen.findByText('서버가 현재 coverage 비율을 제공하지 않았습니다.')).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    const table = screen.getByRole('table', {
      name: '현재 Rule Set coverage 막대와 동일한 서버 집계 수치',
    })
    expect(within(table).getByRole('rowheader', { name: '평가 없음' })).toBeInTheDocument()
  })
})

function renderOverview(value: QualityOverview) {
  const request = vi.fn().mockResolvedValue(value)
  const api = new QualityApi({ request })
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <QualityOverviewTab
        api={api}
        boundary={boundary}
        onBoundaryInvalid={vi.fn()}
      />
    </QueryClientProvider>,
  )
}

function overview(overrides: Partial<QualityOverview> = {}): QualityOverview {
  return {
    availability: 'AVAILABLE',
    freshness: 'CURRENT',
    as_of: '2026-07-30T00:00:00Z',
    authorization_valid_until: '2026-07-30T00:00:30Z',
    overall_state: 'PASS',
    active_rule_set_count: 4,
    evaluated_rule_set_count: 3,
    unknown_rule_set_count: 1,
    passed_count: 73,
    advisory_failed_count: 4,
    blocking_failed_count: 3,
    evaluated_rule_count: 80,
    score_basis_points: 9_125,
    coverage_basis_points: 7_500,
    trend: [{
      bucket_start: '2026-07-29T00:00:00Z',
      passed_count: 73,
      advisory_failed_count: 4,
      blocking_failed_count: 3,
      evaluated_rule_count: 80,
      score_basis_points: 9_125,
    }],
    failure_code: null,
    ...overrides,
  }
}

const boundary: QualitySecurityBoundary = {
  workspaceId: 'workspace-one',
  subjectId: 'subject-one',
  securityEpoch: 7,
  authorizationRevision: 11,
  cacheScope: 'a'.repeat(64),
}
