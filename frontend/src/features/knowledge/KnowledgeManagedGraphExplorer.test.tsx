import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../../api/client'
import type { KnowledgeRelease, KnowledgeSnapshot } from '../../api/types'
import { KnowledgeManagedGraphExplorer } from './KnowledgeManagedGraphExplorer'

const graphElements = {
  addClass: vi.fn().mockReturnThis(),
  removeClass: vi.fn().mockReturnThis(),
  unselect: vi.fn().mockReturnThis(),
}
vi.mock('cytoscape', () => ({ default: vi.fn(() => ({
  animate: vi.fn(),
  destroy: vi.fn(),
  elements: vi.fn(() => graphElements),
  fit: vi.fn(),
  getElementById: vi.fn(() => ({ length: 0, select: vi.fn() })),
  layout: vi.fn(() => ({ one: (_event: string, callback: () => void) => callback(), run: vi.fn() })),
  on: vi.fn(),
  removeAllListeners: vi.fn(),
  resize: vi.fn(),
  zoom: vi.fn(() => 1),
})) }))

const release: KnowledgeRelease = {
  id: 'release-6', graph_id: 'metadata-master', release_no: 6,
  ontology_version_id: 'ontology-6', content_hash: 'hash-6', node_count: 12_281,
  edge_count: 24_556, published_by: 'subject', published_at: '2026-08-24T00:00:00Z',
}

function snapshot(root: string, includeExpansion = false): KnowledgeSnapshot {
  const nodes = [
    { id: 'table-a', entity_type: 'class.table', properties: { name: 'Table A' }, classification: 1, provenance: [] },
    { id: 'term-a', entity_type: 'class.glossary_term', properties: { name: 'Term A' }, classification: 1, provenance: [] },
    ...(includeExpansion ? [{ id: 'column-a', entity_type: 'class.column', properties: { name: 'column_a' }, classification: 1, provenance: [] }] : []),
  ]
  return {
    release,
    nodes,
    edges: [
      { id: 'edge-table-term', source_id: 'table-a', target_id: 'term-a', edge_type: 'rel.has_term', properties: {}, classification: 1, provenance: [] },
      ...(includeExpansion ? [{ id: 'edge-table-column', source_id: 'table-a', target_id: 'column-a', edge_type: 'rel.contains', properties: {}, classification: 1, provenance: [] }] : []),
    ],
    filtered: true,
    bounds: {
      root_node_id: root,
      maximum_hops: 1,
      node_limit: 48,
      edge_limit: 96,
      returned_nodes: nodes.length,
      returned_edges: includeExpansion ? 2 : 1,
      total_authorized_nodes: 12_281,
      total_authorized_edges: 24_556,
      available_node_types: ['class.column', 'class.glossary_term', 'class.table'],
      available_edge_types: ['rel.contains', 'rel.has_term'],
      truncated: true,
    },
  }
}

describe('KnowledgeManagedGraphExplorer', () => {
  it('loads a root-focused bounded graph and expands by canonical node id', async () => {
    const request = vi.fn((path: string) => Promise.resolve(
      path.includes('root_node_id=table-a') ? snapshot('table-a', true) : snapshot('table-a'),
    ))
    render(<KnowledgeManagedGraphExplorer client={{ request } as unknown as ApiClient} graphId="metadata-master" graphType="METADATA_MASTER" releaseId="release-6" />)

    await screen.findByText(/Showing 2 \/ 12281 authorized nodes/)
    expect(request.mock.calls[0]?.[0]).toContain('maximum_nodes=48')
    expect(request.mock.calls[0]?.[0]).toContain('maximum_edges=96')
    expect(request.mock.calls[0]?.[0]).toContain('maximum_hops=1')
    expect(request.mock.calls[0]?.[0]).not.toContain('maximum_nodes=12281')

    screen.getAllByRole('button', { name: 'Upstream 2-level 확장' })[0]?.click()
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2))
    expect(request.mock.calls[1]?.[0]).toContain('root_node_id=table-a')
    expect(request.mock.calls[1]?.[0]).toContain('maximum_hops=2')
    expect(request.mock.calls[1]?.[0]).toContain('direction=UPSTREAM')
    expect(await screen.findByText(/UPSTREAM 2-level · 3 nodes \/ 2 edges를 권한 범위에서 확장/)).toBeInTheDocument()
  })

  it('reloads server-side type filters without exposing the full canonical graph', async () => {
    const request = vi.fn((path: string) => {
      void path
      return Promise.resolve(snapshot('table-a'))
    })
    render(<KnowledgeManagedGraphExplorer client={{ request } as unknown as ApiClient} graphId="metadata-master" graphType="METADATA_MASTER" releaseId="release-6" />)
    const filter = await screen.findByRole('button', { name: 'class.table' })
    fireEvent.click(filter)
    await waitFor(() => expect(request.mock.calls.some(([path]) => String(path).includes('node_type=class.table'))).toBe(true))
    expect(filter).toHaveAttribute('aria-pressed', 'true')
  })

  it('aborts the in-flight bounded query when the explorer unmounts', async () => {
    const request = vi.fn((path: string, options?: { signal?: AbortSignal }) => {
      void path
      void options
      return new Promise<KnowledgeSnapshot>(() => undefined)
    })
    const view = render(<KnowledgeManagedGraphExplorer client={{ request } as unknown as ApiClient} graphId="metadata-master" graphType="METADATA_MASTER" releaseId="release-6" />)
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
    const options = request.mock.calls[0]?.[1]
    expect(options?.signal?.aborted).toBe(false)

    view.unmount()

    expect(options?.signal?.aborted).toBe(true)
  })
})
