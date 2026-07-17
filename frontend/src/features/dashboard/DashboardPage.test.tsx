import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../../api/client'
import type { OperationsSummary } from '../../api/types'
import { DashboardPage } from './DashboardPage'

function summary(overrides: Partial<OperationsSummary> = {}): OperationsSummary {
  return {
    observed_at: '2026-07-18T00:00:00Z',
    jobs_by_state: { SUCCEEDED: 2 },
    uploads_by_state: { ACCEPTED: 1 },
    changes_by_state: { REGISTERED: 2, IN_REVIEW: 3, APPLIED: 4 },
    catalog_asset_count: 10,
    catalog_described_asset_count: 7,
    catalog_schema_metrics: [{
      platform: 'postgres',
      database_name: 'warehouse',
      schema_name: 'core',
      asset_count: 10,
      described_asset_count: 7,
    }],
    catalog_schema_metrics_truncated: false,
    unpublished_outbox_events: 0,
    dead_lettered_outbox_events: 0,
    oldest_unpublished_age_seconds: undefined,
    retention_automation_state: 'DISABLED_NOT_READY',
    ...overrides,
  }
}

function apiClient(request: (path: string) => Promise<unknown>): ApiClient {
  return { request } as unknown as ApiClient
}

describe('DashboardPage', () => {
  it('renders source-derived DataHub coverage and makes absent legacy metrics explicit', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/capabilities') return Promise.resolve({ items: [{ name: 'DataHub', state: 'healthy', observed_at: '2026-07-18T00:00:00Z' }] })
      if (path === '/operations/summary') return Promise.resolve(summary())
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<DashboardPage client={apiClient(request)} />)

    expect(await screen.findByText('설명 완성도 70%')).toBeInTheDocument()
    expect(screen.getAllByText('10')).toHaveLength(2)
    expect(screen.getByText('현재 projection 계약에서는 집계하지 않음')).toBeInTheDocument()
    expect(screen.getByText('검증된 품질 점수 read model이 아직 없음')).toBeInTheDocument()
    expect(screen.queryByText('94.2')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '1W' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: /Platformpostgres10Assets/i }))
    expect(await screen.findByText('warehouse / core')).toBeInTheDocument()
    expect(screen.getByText('70%')).toBeInTheDocument()
    expect(screen.getAllByText('미수집')).toHaveLength(2)
    expect(screen.getByText(/감사 원장 요약은 별도 권한으로 보호됩니다/)).toBeInTheDocument()
  })

  it('states the bounded hierarchy result instead of silently omitting it', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/capabilities') return Promise.resolve({ items: [] })
      if (path === '/operations/summary') return Promise.resolve(summary({ catalog_schema_metrics_truncated: true }))
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<DashboardPage client={apiClient(request)} />)

    expect(await screen.findByText(/안전한 화면 한도\(200개\)/)).toBeInTheDocument()
  })
})
