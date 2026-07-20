import { render, screen } from '@testing-library/react'
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
    deployment_tier: 'SINGLE_NODE_PILOT',
    ...overrides,
  }
}

function apiClient(request: (path: string) => Promise<unknown>): ApiClient {
  return { request } as unknown as ApiClient
}

describe('MonitoringPage', () => {
  it('uses only the server-provided Grafana link and current capability result', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/capabilities') return Promise.resolve(response())
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<MonitoringPage client={apiClient(request)} />)

    const links = await screen.findAllByRole('link', { name: 'Grafana 열기' })
    expect(links).toHaveLength(2)
    expect(links[0]).toHaveAttribute('href', 'https://grafana.example/dashboard')
    expect(links[0]).toHaveAttribute('target', '_blank')
    expect(screen.getByText('DataHub')).toBeInTheDocument()
    expect(screen.getByText('12 ms')).toBeInTheDocument()
    expect(screen.queryByTitle('Grafana Dashboard')).not.toBeInTheDocument()
    expect(document.querySelector('iframe')).toBeNull()
  })

  it('renders an explicit unavailable state when no approved Grafana descriptor exists', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/capabilities') return Promise.resolve(response({ external_system_links: [] }))
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<MonitoringPage client={apiClient(request)} />)

    expect(await screen.findByText('승인된 Grafana 링크가 없습니다.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Grafana 링크 없음' })).toBeDisabled()
  })

  it('frames Grafana only for an available server-owned embed descriptor', async () => {
    const request = vi.fn((path: string): Promise<unknown> => {
      if (path === '/capabilities') return Promise.resolve(response({
        grafana_embed: { state: 'AVAILABLE', url: 'https://grafana.example/dashboard' },
      }))
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<MonitoringPage client={apiClient(request)} />)

    const frame = await screen.findByTitle('Grafana Dashboard')
    expect(frame).toHaveAttribute('src', 'https://grafana.example/dashboard')
    expect(frame).toHaveAttribute('sandbox', 'allow-forms allow-same-origin allow-scripts')
    expect(frame).toHaveAttribute('referrerpolicy', 'no-referrer')
  })
})
