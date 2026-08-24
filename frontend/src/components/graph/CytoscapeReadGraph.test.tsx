import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReadGraphModel } from './CytoscapeGraphAdapter'
import { CytoscapeReadGraph } from './CytoscapeReadGraph'

const destroy = vi.fn()
const fit = vi.fn()
const zoom = vi.fn(() => 1)
const run = vi.fn()
const layout = vi.fn(() => ({
  one: (_event: string, callback: () => void) => callback(),
  run,
}))
const emptyElement = {
  length: 0,
  isNode: () => false,
  select: vi.fn(),
}
const elements = {
  addClass: vi.fn(() => elements),
  removeClass: vi.fn(() => elements),
  unselect: vi.fn(() => elements),
}
const cy = {
  animate: vi.fn(),
  destroy,
  elements: vi.fn(() => elements),
  fit,
  getElementById: vi.fn(() => emptyElement),
  layout,
  on: vi.fn(),
  removeAllListeners: vi.fn(),
  resize: vi.fn(),
  zoom,
}
const cytoscape = vi.fn(() => cy)

vi.mock('cytoscape', () => ({ default: cytoscape }))

const graph: ReadGraphModel = {
  kind: 'LINEAGE',
  rootId: 'node-a',
  nodes: [
    { id: 'node-a', label: 'Table A', entityType: 'TABLE', role: 'ROOT', properties: {}, provenance: [{ source: 'DataHub' }] },
    { id: 'node-b', label: 'Table B', entityType: 'TABLE', role: 'DOWNSTREAM', properties: {}, provenance: [] },
  ],
  edges: [
    { id: 'edge-a-b', source: 'node-a', target: 'node-b', label: 'LINEAGE', relationType: 'LINEAGE', properties: {}, provenance: [] },
  ],
}

afterEach(() => {
  vi.clearAllMocks()
})

describe('CytoscapeReadGraph', () => {
  it('provides accessible DOM controls, legend, detail and render metrics', async () => {
    render(<CytoscapeReadGraph ariaLabel="Data lineage" graph={graph} selectedElementId="node-a" />)

    expect(screen.getByRole('img', { name: /Data lineage canvas/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '그래프 확대' })).toBeInTheDocument()
    expect(screen.getByLabelText('그래프 범례')).toHaveTextContent('TABLE')
    expect(screen.getByLabelText('선택한 그래프 요소 상세')).toHaveTextContent('Table A')
    await waitFor(() => expect(cytoscape).toHaveBeenCalledTimes(1))
    expect(screen.getByTestId('cytoscape-metrics')).toHaveTextContent('layout')
  })

  it('keeps empty and query-failure states distinct from a rendered graph', () => {
    const { rerender } = render(<CytoscapeReadGraph ariaLabel="Empty" graph={{ kind: 'SEMANTIC', nodes: [], edges: [] }} emptyTitle="인가된 graph가 없습니다." />)
    expect(screen.getByText('인가된 graph가 없습니다.')).toBeInTheDocument()

    rerender(<CytoscapeReadGraph ariaLabel="Failed" graph={graph} errorMessage="GRAPH_QUERY_FAILED" />)
    expect(screen.getByRole('alert')).toHaveTextContent('GRAPH_QUERY_FAILED')
  })

  it('destroys each Cytoscape instance and its listeners across repeated open/close', async () => {
    for (let attempt = 1; attempt <= 4; attempt += 1) {
      const view = render(<CytoscapeReadGraph ariaLabel={`Lifecycle ${attempt}`} graph={graph} />)
      await waitFor(() => expect(cytoscape).toHaveBeenCalledTimes(attempt))
      act(() => view.unmount())
    }
    expect(cy.removeAllListeners).toHaveBeenCalledTimes(4)
    expect(destroy).toHaveBeenCalledTimes(4)
  })

  it('resolves a missing local entity through the bounded server resolver', async () => {
    const resolve = vi.fn(() => Promise.resolve('node-c'))
    render(<CytoscapeReadGraph ariaLabel="Searchable" graph={graph} onResolveSearch={resolve} />)
    fireEvent.change(screen.getByLabelText('그래프 entity 검색'), { target: { value: 'remote root' } })
    fireEvent.click(screen.getByRole('button', { name: '그래프 검색' }))
    await waitFor(() => expect(resolve).toHaveBeenCalledWith('remote root'))
    expect(screen.getByText('새 bounded graph root를 불러왔습니다.')).toBeInTheDocument()
  })

  it('invokes bounded expand for the selected canonical node', async () => {
    const expand = vi.fn(() => Promise.resolve())
    render(<CytoscapeReadGraph ariaLabel="Expandable" graph={graph} onExpandNode={expand} selectedElementId="node-a" />)
    fireEvent.click(screen.getByRole('button', { name: '선택 확장' }))
    await waitFor(() => expect(expand).toHaveBeenCalledWith('node-a'))
  })
})
