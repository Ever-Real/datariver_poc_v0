import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { CatalogLineage } from '../../api/types'
import { CatalogLineageGraph } from './CatalogLineageGraph'
import { layoutLineage } from './CatalogLineageLayout'

const lineage: CatalogLineage = {
  center_asset_id: 'center',
  direction: 'BOTH',
  depth: 2,
  truncated: false,
  meta: { projection_version: 1, policy_version: 'policy', observed_at: '2026-07-17T00:00:00Z' },
  nodes: [
    { id: 'upstream-two', external_urn: 'urn:li:dataset:upstream-two', asset_type: 'DATASET', name: 'upstream_two_table', classification: 'INTERNAL', lifecycle: 'ACTIVE', observed_at: '2026-07-17T00:00:00Z', matches: [] },
    { id: 'upstream', external_urn: 'urn:li:dataset:upstream', asset_type: 'DATASET', name: 'upstream_table', classification: 'INTERNAL', lifecycle: 'ACTIVE', observed_at: '2026-07-17T00:00:00Z', matches: [] },
    { id: 'center', external_urn: 'urn:li:dataset:center', asset_type: 'DATASET', name: 'center_table', classification: 'INTERNAL', lifecycle: 'ACTIVE', observed_at: '2026-07-17T00:00:00Z', matches: [] },
    { id: 'downstream', external_urn: 'urn:li:dataset:downstream', asset_type: 'DATASET', name: 'downstream_table', classification: 'INTERNAL', lifecycle: 'ACTIVE', observed_at: '2026-07-17T00:00:00Z', matches: [] },
    { id: 'downstream-two', external_urn: 'urn:li:dataset:downstream-two', asset_type: 'DATASET', name: 'downstream_two_table', classification: 'INTERNAL', lifecycle: 'ACTIVE', observed_at: '2026-07-17T00:00:00Z', matches: [] },
  ],
  edges: [
    { source_asset_id: 'upstream-two', target_asset_id: 'upstream' },
    { source_asset_id: 'upstream', target_asset_id: 'center' },
    { source_asset_id: 'center', target_asset_id: 'downstream' },
    { source_asset_id: 'downstream', target_asset_id: 'downstream-two' },
  ],
}

describe('CatalogLineageGraph', () => {
  it('lays out authorized nodes deterministically from upstream to downstream', () => {
    const positioned = layoutLineage(lineage).nodes

    expect(positioned.map((node) => [node.asset.id, node.role])).toEqual([
      ['upstream-two', 'UPSTREAM_2'],
      ['upstream', 'UPSTREAM_1'],
      ['center', 'CENTER'],
      ['downstream', 'DOWNSTREAM_1'],
      ['downstream-two', 'DOWNSTREAM_2'],
    ])
    expect(positioned.map((node) => node.y)).toEqual([...positioned.map((node) => node.y)].sort((left, right) => left - right))
  })

  it('wraps a lineage stage after three nodes without widening the graph indefinitely', () => {
    const expanded: CatalogLineage = {
      ...lineage,
      nodes: [
        ...lineage.nodes,
        ...['upstream_two_b', 'upstream_two_c', 'upstream_two_d'].map((name) => ({
          id: name,
          external_urn: `urn:li:dataset:${name}`,
          asset_type: 'DATASET',
          name,
          classification: 'INTERNAL',
          lifecycle: 'ACTIVE',
          observed_at: '2026-07-17T00:00:00Z',
          matches: [],
        })),
      ],
      edges: [
        ...lineage.edges,
        ...['upstream_two_b', 'upstream_two_c', 'upstream_two_d'].map((source_asset_id) => ({
          source_asset_id,
          target_asset_id: 'upstream',
        })),
      ],
    }

    const layout = layoutLineage(expanded)
    const upstreamTwo = layout.nodes.filter((node) => node.role === 'UPSTREAM_2')

    expect(upstreamTwo).toHaveLength(4)
    expect(new Set(upstreamTwo.slice(0, 3).map((node) => node.y)).size).toBe(1)
    expect(upstreamTwo[3]!.y).toBeGreaterThan(upstreamTwo[0]!.y)
    expect(layout.width).toBe(864)
  })

  it('opens an authorized local asset detail by opaque asset id only', () => {
    const onSelectAsset = vi.fn()
    render(<CatalogLineageGraph lineage={lineage} onSelectAsset={onSelectAsset} />)

    const tableName = screen.getByRole('button', { name: 'center_table 선택' })
    fireEvent.pointerDown(tableName, { clientX: 20, clientY: 20, pointerId: 7 })
    fireEvent.pointerUp(tableName, { clientX: 20, clientY: 20, pointerId: 7 })
    fireEvent.click(tableName)

    expect(onSelectAsset).toHaveBeenCalledWith('center')
    expect(onSelectAsset).not.toHaveBeenCalledWith('urn:li:dataset:center')
  })

  it('uses compact fixed-width lineage badges', () => {
    render(<CatalogLineageGraph lineage={lineage} onSelectAsset={vi.fn()} />)

    expect(screen.getByText('U·2')).toHaveClass('catalog-lineage-node-role')
    expect(screen.getByText('U·1')).toHaveClass('catalog-lineage-node-role')
    expect(screen.getByText('D·1')).toHaveClass('catalog-lineage-node-role')
    expect(screen.getByText('D·2')).toHaveClass('catalog-lineage-node-role')
  })

  it('supports canvas panning, zoom controls, and individual node body movement', () => {
    const onSelectAsset = vi.fn()
    render(<CatalogLineageGraph lineage={lineage} onSelectAsset={onSelectAsset} />)

    const viewport = document.querySelector<HTMLElement>('.catalog-lineage-viewport')
    const world = document.querySelector<HTMLElement>('.catalog-lineage-world')
    const stage = document.querySelector<HTMLElement>('.catalog-lineage-stage')
    const node = screen.getByRole('button', { name: 'center_table 선택' }).closest('article')
    expect(viewport).not.toBeNull()
    expect(world).toContainElement(stage)
    expect(stage).toHaveStyle('transform: translate(0px, 0px) scale(1)')
    expect(node).not.toBeNull()

    fireEvent.pointerDown(viewport as HTMLElement, { clientX: 20, clientY: 20, pointerId: 1 })
    fireEvent.pointerMove(viewport as HTMLElement, { clientX: 45, clientY: 50, pointerId: 1 })
    fireEvent.pointerUp(viewport as HTMLElement, { clientX: 45, clientY: 50, pointerId: 1 })
    expect(stage).toHaveStyle('transform: translate(25px, 30px) scale(1)')

    fireEvent.click(screen.getByRole('button', { name: '계보 확대' }))
    expect(stage).toHaveStyle('transform: translate(25px, 30px) scale(1.2)')
    fireEvent.wheel(viewport as HTMLElement, { clientX: 0, clientY: 0, ctrlKey: true, deltaY: -1 })
    expect(stage?.style.transform).toContain('scale(1.344')

    const initialLeft = (node as HTMLElement).style.left
    fireEvent.pointerDown(node as HTMLElement, { clientX: 100, clientY: 100, pointerId: 2 })
    fireEvent.pointerMove(viewport as HTMLElement, { clientX: 136, clientY: 112, pointerId: 2 })
    fireEvent.pointerUp(viewport as HTMLElement, { clientX: 136, clientY: 112, pointerId: 2 })
    expect((node as HTMLElement).style.left).not.toBe(initialLeft)
    expect(onSelectAsset).not.toHaveBeenCalled()
  })
})
