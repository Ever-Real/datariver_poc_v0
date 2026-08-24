import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../../api/client'
import type { CatalogLineage } from '../../api/types'
import { CatalogLineageGraph } from './CatalogLineageGraph'

const cytoscape = vi.fn(() => ({
  destroy: vi.fn(),
  elements: vi.fn(() => ({ removeClass: vi.fn().mockReturnThis(), unselect: vi.fn().mockReturnThis() })),
  fit: vi.fn(),
  getElementById: vi.fn(() => ({ length: 0, select: vi.fn() })),
  layout: vi.fn(() => ({ one: (_event: string, callback: () => void) => callback(), run: vi.fn() })),
  on: vi.fn(),
  removeAllListeners: vi.fn(),
  resize: vi.fn(),
  zoom: vi.fn(() => 1),
}))

vi.mock('cytoscape', () => ({ default: cytoscape }))

const lineage: CatalogLineage = {
  center_asset_id: 'center',
  direction: 'BOTH',
  depth: 2,
  truncated: false,
  meta: { projection_version: 1, policy_version: 'policy', observed_at: '2026-07-17T00:00:00Z' },
  nodes: [
    { id: 'upstream', external_urn: 'urn:li:dataset:upstream', asset_type: 'DATASET', name: 'upstream_table', classification: 'INTERNAL', lifecycle: 'ACTIVE', observed_at: '2026-07-17T00:00:00Z', matches: [] },
    { id: 'center', external_urn: 'urn:li:dataset:center', asset_type: 'DATASET', name: 'center_table', classification: 'INTERNAL', lifecycle: 'ACTIVE', observed_at: '2026-07-17T00:00:00Z', matches: [] },
    { id: 'downstream', external_urn: 'urn:li:dataset:downstream', asset_type: 'DATASET', name: 'downstream_table', classification: 'INTERNAL', lifecycle: 'ACTIVE', observed_at: '2026-07-17T00:00:00Z', matches: [] },
  ],
  edges: [
    { source_asset_id: 'upstream', target_asset_id: 'center' },
    { source_asset_id: 'center', target_asset_id: 'downstream' },
  ],
}
const client = { request: vi.fn() } as unknown as ApiClient

describe('CatalogLineageGraph', () => {
  it('renders the authorized lineage through the dedicated Cytoscape read boundary', async () => {
    render(<CatalogLineageGraph client={client} lineage={lineage} onSelectAsset={vi.fn()} />)

    expect(screen.getByRole('img', { name: /권한 필터링된 DataHub Lineage 그래프 canvas/ })).toBeInTheDocument()
    expect(screen.getByLabelText('선택한 그래프 요소 상세')).toHaveTextContent('center_table')
    expect(screen.getByLabelText('그래프 범례')).toHaveTextContent('Upstream')
    await waitFor(() => expect(cytoscape).toHaveBeenCalledTimes(1))
  })

  it('shows truncation as an explicit bounded-result notice', () => {
    render(<CatalogLineageGraph client={client} lineage={{ ...lineage, truncated: true }} onSelectAsset={vi.fn()} />)
    expect(screen.getByText('서버 조회 한도에 따라 일부 관계가 생략되었습니다.')).toBeInTheDocument()
  })
})
