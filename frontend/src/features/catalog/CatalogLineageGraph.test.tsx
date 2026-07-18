import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { CatalogLineage } from '../../api/types'
import { CatalogLineageGraph, layoutLineage } from './CatalogLineageGraph'

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

describe('CatalogLineageGraph', () => {
  it('lays out authorized nodes deterministically by upstream, center and downstream roles', () => {
    const positioned = layoutLineage(lineage).nodes

    expect(positioned.map((node) => [node.asset.id, node.role])).toEqual([
      ['upstream', 'UPSTREAM'],
      ['center', 'CENTER'],
      ['downstream', 'DOWNSTREAM'],
    ])
  })

  it('opens an authorized local asset detail by opaque asset id only', () => {
    const onSelectAsset = vi.fn()
    render(<CatalogLineageGraph lineage={lineage} onSelectAsset={onSelectAsset} />)

    fireEvent.click(screen.getByRole('button', { name: /center_table/i }))

    expect(onSelectAsset).toHaveBeenCalledWith('center')
    expect(onSelectAsset).not.toHaveBeenCalledWith('urn:li:dataset:center')
  })
})
