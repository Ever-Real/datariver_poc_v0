import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../../api/client'
import type { CapabilitiesResponse } from '../../api/types'
import { MonitoringPage } from './MonitoringPage'

function response(overrides: Partial<CapabilitiesResponse> = {}): CapabilitiesResponse {
  return {
    items: [{
      name: 'DataHub',
      state: 'healthy',
      observed_at: '2026-07-18T00:00:00Z',
      latency_ms: 12,
    }],
    external_system_links: [{
      system_id: 'grafana',
      label: 'Grafana',
      url: 'https://grafana.example/dashboard',
    }],
    grafana_embed: { state: 'DISABLED' },
    monitoring_configuration: {
      version: 3,
      items: [
        {
          id: '11111111-1111-4111-8111-111111111111',
          label: 'Platform',
          url: 'https://grafana.example/d/platform',
          height_px: 840,
          embed_state: 'DISABLED',
        },
        {
          id: '22222222-2222-4222-8222-222222222222',
          label: 'DataHub',
          url: 'https://grafana.example/d/datahub',
          height_px: 1040,
          embed_state: 'AVAILABLE',
          embed_url: 'https://grafana.example/d/datahub',
        },
      ],
    },
    deployment_tier: 'SINGLE_NODE_PILOT',
    ...overrides,
  }
}

function apiClient(request: (path: string, options?: RequestInit) => Promise<unknown>): ApiClient {
  return {
    request: (path: string, options?: RequestInit) => {
      if (path.startsWith('/change-history/summary?')) {
        const weekStart = new URL(path, 'https://datariver.invalid').searchParams.get('week_start') ?? ''
        return Promise.resolve(changeHistorySummary(weekStart))
      }
      if (path.startsWith('/change-history/events?')) {
        return Promise.resolve({ items: [], next_cursor: null, limit: 50, total: 0 })
      }
      return request(path, options)
    },
    requestWithMeta: vi.fn(),
  } as unknown as ApiClient
}

describe('MonitoringPage', () => {
  it('omits the duplicate data-change tab and keeps every server-owned dashboard accessible', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/capabilities') return Promise.resolve(response())
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<MonitoringPage client={apiClient(request)} />)

    const platformTab = await screen.findByRole('tab', { name: 'Platform' })
    const dataHubTab = screen.getByRole('tab', { name: 'DataHub' })
    expect(screen.queryByRole('tab', { name: '데이터 변경현황' })).not.toBeInTheDocument()
    expect(platformTab).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('link', { name: 'Platform 열기' })).toHaveAttribute(
      'href',
      'https://grafana.example/d/platform',
    )
    fireEvent.keyDown(platformTab, { key: 'ArrowRight' })
    expect(dataHubTab).toHaveAttribute('aria-selected', 'true')
    expect(await screen.findByTitle('DataHub Monitoring Dashboard')).toHaveAttribute(
      'src',
      'https://grafana.example/d/datahub',
    )
    expect(screen.queryByText('Platform capability state')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '탭 수정' })).not.toBeInTheDocument()
  })

  it('uses the selected dashboard height for an available server-owned frame', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/capabilities') return Promise.resolve(response())
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<MonitoringPage client={apiClient(request)} />)

    fireEvent.click(await screen.findByRole('tab', { name: 'DataHub' }))
    const frame = await screen.findByTitle('DataHub Monitoring Dashboard')
    expect(frame).toHaveAttribute('src', 'https://grafana.example/d/datahub')
    expect(frame).toHaveAttribute('sandbox', 'allow-forms allow-same-origin allow-scripts')
    expect(frame).toHaveAttribute('referrerpolicy', 'no-referrer')
    expect(frame).toHaveAttribute('height', '1040')
    expect(frame).not.toHaveAttribute('style')
  })

  it('frames an administrator-approved non-Grafana dashboard link', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/capabilities') {
        return Promise.resolve(response({
          monitoring_configuration: {
            version: 4,
            items: [{
              id: '33333333-3333-4333-8333-333333333333',
              label: 'Vendor status',
              url: 'https://status.example.com/platform',
              height_px: 900,
              embed_state: 'AVAILABLE',
              embed_url: 'https://status.example.com/platform',
            }],
          },
        }))
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<MonitoringPage client={apiClient(request)} />)

    fireEvent.click(await screen.findByRole('tab', { name: 'Vendor status' }))
    const frame = await screen.findByTitle('Vendor status Monitoring Dashboard')
    expect(frame).toHaveAttribute('src', 'https://status.example.com/platform')
    expect(screen.getByText(/Admin이 승인한/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '새 창으로 열기' })).toHaveAttribute(
      'href',
      'https://status.example.com/platform',
    )
  })

  it('shows the existing empty-dashboard state without loading the removed native view', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/capabilities') {
        return Promise.resolve(response({
          monitoring_configuration: { items: [], version: 0 },
        }))
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<MonitoringPage client={apiClient(request)} />)

    expect(await screen.findByText('등록된 Dashboard 없음')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Monitoring Dashboard가 없습니다.' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '데이터 변경현황' })).not.toBeInTheDocument()
    expect(request).toHaveBeenCalledTimes(1)
    expect(request).toHaveBeenCalledWith('/capabilities', expect.any(Object))
  })

  it('allows an authorized administrator to edit and save the ordered tab configuration', async () => {
    const request = vi.fn((
      path: string,
      options?: RequestInit & { ifMatch?: string },
    ): Promise<unknown> => {
      if (path === '/capabilities') return Promise.resolve(response())
      if (path === '/admin/monitoring-configuration' && options?.method === 'PUT') {
        return Promise.resolve({
          items: [{
            ...response().monitoring_configuration.items[0],
            label: 'Core platform',
          }],
          version: 4,
        })
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    render(
      <MonitoringPage
        client={apiClient(request)}
        canManageTabs
        canUpdateTabs
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: '탭 수정' }))
    const linkInputs = screen.getAllByLabelText('Dashboard Link')
    expect(linkInputs).toHaveLength(2)
    expect(screen.queryByText('Grafana Dashboard URL')).not.toBeInTheDocument()
    const nameInputs = screen.getAllByLabelText('탭 이름')
    fireEvent.change(nameInputs[0]!, { target: { value: 'Core platform' } })
    fireEvent.change(linkInputs[0]!, {
      target: { value: 'https://status.example.com/platform' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'DataHub 탭 삭제' }))
    fireEvent.click(screen.getByRole('button', { name: '저장' }))

    await waitFor(() => expect(request.mock.calls.some(
      ([path]) => path === '/admin/monitoring-configuration',
    )).toBe(true))
    const updateCall = request.mock.calls.find(
      ([path]) => path === '/admin/monitoring-configuration',
    )
    const updateOptions = updateCall?.[1]
    expect(updateOptions?.method).toBe('PUT')
    expect(updateOptions?.ifMatch).toBe('"3"')
    expect(updateOptions?.body).toContain('"label":"Core platform"')
    expect(updateOptions?.body).toContain('"url":"https://status.example.com/platform"')
    expect(updateOptions?.body).not.toContain('data-change-status')
    expect(await screen.findByRole('tab', { name: 'Core platform' })).toBeInTheDocument()
  })

  it('keeps the admin edit surface visible but read-only until assurance is refreshed', async () => {
    const requestAssurance = vi.fn(() => Promise.resolve())
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/capabilities') return Promise.resolve(response())
      throw new Error(`Unexpected request: ${path}`)
    })
    render(
      <MonitoringPage
        client={apiClient(request)}
        canManageTabs
        onRequestAdminAssurance={requestAssurance}
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: '탭 수정' }))
    expect(screen.getAllByLabelText('탭 이름')[0]).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '관리자 재인증' }))
    expect(requestAssurance).toHaveBeenCalledOnce()
  })
})

function changeHistorySummary(weekStart: string) {
  const weekEnd = new Date(`${weekStart}T00:00:00.000Z`)
  weekEnd.setUTCDate(weekEnd.getUTCDate() + 7)
  const timestamp = `${weekStart}T01:00:00.000Z`
  return {
    week_start: weekStart,
    week_end_exclusive: weekEnd.toISOString().slice(0, 10),
    timezone: 'Asia/Seoul',
    as_of: timestamp,
    policy_version: 1,
    policy_hash: '1'.repeat(64),
    count_unit: 'DISTINCT_NORMALIZED_CHANGE_TRANSACTION',
    total_count: 0,
    unlinked_count: 0,
    received_count: 0,
    recheck_count: 0,
    testing_count: 0,
    final_review_count: 0,
    completed_count: 0,
    time_unknown_count: 0,
    schema_change_count: 0,
    metadata_change_count: 0,
    event_count: 0,
    distinct_asset_count: 0,
    precision_counts: {
      EXACT_TIMELINE: 0,
      EXACT_MCL: 0,
      DRIFT_DETECTED: 0,
      BACKFILLED_BEST_EFFORT: 0,
      INITIAL_BASELINE: 0,
    },
    category_counts: {
      TECHNICAL_SCHEMA: 0,
      DOCUMENTATION: 0,
      TAG: 0,
      GLOSSARY_TERM: 0,
      DOMAIN: 0,
      OWNERSHIP: 0,
      LIFECYCLE: 0,
    },
    operation_counts: { CREATE: 0, UPDATE: 0, UPSERT: 0, DELETE: 0, ADD: 0, REMOVE: 0 },
    capture_state: 'CAPTURE_PENDING',
    sync_status: 'CAPTURE_PENDING',
    capture_failure_classification: null,
    capture_failure_stage: null,
    capture_failure_detail_code: null,
    capture_failure_record_shape: null,
    source_generation: '2'.repeat(64),
    source_observed_at: timestamp,
    source_occurred_at: null,
    detected_at: null,
    captured_at: null,
    effective_week_start: weekStart,
    history_available_from: null,
    ledger_guarantee_from: null,
    first_exact_capture_at: null,
    first_timeline_checkpoint: null,
    first_mcl_offsets: null,
    last_successful_capture_at: null,
  }
}
