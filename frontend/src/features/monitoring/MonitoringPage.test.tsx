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
  return { request } as unknown as ApiClient
}

describe('MonitoringPage', () => {
  it('renders server-owned dashboards as accessible tabs without capability cards', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/capabilities') return Promise.resolve(response())
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<MonitoringPage client={apiClient(request)} />)

    expect(await screen.findByRole('tab', { name: 'Platform' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('tab', { name: 'DataHub' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Platform 열기' })).toHaveAttribute(
      'href',
      'https://grafana.example/d/platform',
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
    const frame = await screen.findByTitle('DataHub Grafana Dashboard')
    expect(frame).toHaveAttribute('src', 'https://grafana.example/d/datahub')
    expect(frame).toHaveAttribute('sandbox', 'allow-forms allow-same-origin allow-scripts')
    expect(frame).toHaveAttribute('referrerpolicy', 'no-referrer')
    expect(frame).toHaveStyle({ height: '1040px' })
  })

  it('shows an explicit empty state when no dashboard is configured', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/capabilities') {
        return Promise.resolve(response({
          monitoring_configuration: { items: [], version: 0 },
        }))
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<MonitoringPage client={apiClient(request)} />)

    expect(await screen.findByText('Monitoring Dashboard가 없습니다.')).toBeInTheDocument()
    expect(screen.getByText('등록된 Dashboard 없음')).toBeInTheDocument()
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
    const nameInputs = screen.getAllByLabelText('탭 이름')
    fireEvent.change(nameInputs[0]!, { target: { value: 'Core platform' } })
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
