import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReadGraphModel } from './CytoscapeGraphAdapter'
import type { Core, NodeSingular } from 'cytoscape'
import {
  CYTOSCAPE_NODE_GEOMETRY,
  CYTOSCAPE_SELECTED_NODE_HIGHLIGHT,
  CytoscapeReadGraph,
  graphStyles,
  isRenderedLabelHit,
  restoreViewport,
} from './CytoscapeReadGraph'

const destroy = vi.fn()
const fit = vi.fn()
const zoom = vi.fn(() => 1)
const run = vi.fn()
const stop = vi.fn()
const layout = vi.fn((options?: unknown) => {
  void options
  return {
    one: (_event: string, callback: () => void) => callback(),
    run,
    stop,
  }
})
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
  pan: vi.fn(() => ({ x: 24, y: 36 })),
  removeAllListeners: vi.fn(),
  resize: vi.fn(),
  zoom,
}
const cytoscape = vi.fn((options: { container?: HTMLElement }) => ({
  ...cy,
  destroy: () => {
    destroy()
    options.container?.replaceChildren()
  },
}))

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
  it('keeps compact circular geometry identical when selected and preserves directional edges', () => {
    const styles = graphStyles(document.createElement('div'))
    const style = (selector: string) => (styles.find((entry) => entry.selector === selector) as unknown as {
      style: Record<string, unknown>
    }).style
    const base = style('node')
    const selected = style('node:selected')
    const edge = style('edge')

    expect(CYTOSCAPE_NODE_GEOMETRY).toMatchObject({ width: 36, height: 36, fontSize: 9 })
    expect(base).toMatchObject({ shape: 'ellipse', 'text-opacity': 0, 'background-color': 'data(groupColor)' })
    expect(selected['border-width']).toBe(base['border-width'])
    expect(selected['border-width']).toBe(CYTOSCAPE_SELECTED_NODE_HIGHLIGHT.borderWidth)
    expect(selected).not.toHaveProperty('width')
    expect(selected).not.toHaveProperty('height')
    expect(selected).not.toHaveProperty('padding')
    expect(selected).not.toHaveProperty('font-size')
    expect(edge).toMatchObject({ width: 2.1, 'arrow-scale': 1.15, 'target-arrow-shape': 'triangle' })
    expect(edge['line-color']).toBe('#a5b1bd')
  })

  it('applies the classic rectangular role and depth profile only when explicitly requested', () => {
    const styles = graphStyles(document.createElement('div'), 'SEARCH_LINEAGE_CLASSIC')
    const style = (selector: string) => (styles.filter((entry) => entry.selector === selector).at(-1) as unknown as {
      style: Record<string, unknown>
    }).style

    expect(style('node')).toMatchObject({
      shape: 'round-rectangle', width: 156, height: 52, 'text-opacity': 1,
    })
    expect(style('node[role = "UPSTREAM"][lineageDepth = 1]')).toMatchObject({
      'background-color': '#fff1cf',
    })
    expect(style('node[role = "DOWNSTREAM"][lineageDepth >= 2]')).toMatchObject({
      'background-color': '#effaf4',
    })
    expect(style('node:selected')).not.toHaveProperty('width')
    expect(style('edge')).toMatchObject({
      label: 'data(displayLabel)', 'text-opacity': 1, 'font-size': 8.5, 'text-rotation': 'autorotate',
    })
    expect(graphStyles(document.createElement('div')).filter((entry) => entry.selector === 'node')).toHaveLength(1)
  })

  it('distinguishes a rendered label hit from the node body without changing click cadence', () => {
    const node = {
      renderedBoundingBox: () => ({ x1: 20, x2: 80, y1: 30, y2: 50 }),
    } as unknown as NodeSingular
    expect(isRenderedLabelHit(node, { x: 42, y: 40 })).toBe(true)
    expect(isRenderedLabelHit(node, { x: 10, y: 40 })).toBe(false)
    expect(isRenderedLabelHit(node, { x: 42, y: 70 })).toBe(false)
  })

  it('restores zoom, pan, selection and the anchor rendered position after an incremental update', () => {
    let currentPan = { x: 0, y: 0 }
    let currentZoom = 1
    const select = vi.fn()
    const core = {
      zoom: vi.fn((value?: number) => {
        if (value !== undefined) currentZoom = value
        return currentZoom
      }),
      pan: vi.fn((value?: { x: number; y: number }) => {
        if (value) currentPan = value
        return currentPan
      }),
      getElementById: vi.fn((id: string) => id === 'anchor'
        ? { isNode: () => true, renderedPosition: () => ({ x: 80, y: 90 }), select }
        : { select }),
    } as unknown as Core

    restoreViewport(core, {
      zoom: 1.4,
      pan: { x: 20, y: 30 },
      anchorId: 'anchor',
      anchorRenderedPosition: { x: 100, y: 120 },
      selectedId: 'anchor',
    })
    expect(currentZoom).toBe(1.4)
    expect(currentPan).toEqual({ x: 40, y: 60 })
    expect(select).toHaveBeenCalled()
  })

  it('provides accessible DOM controls, legend, detail and render metrics', async () => {
    render(<CytoscapeReadGraph ariaLabel="Data lineage" graph={graph} selectedElementId="node-a" />)

    expect(screen.getByRole('img', { name: /Data lineage canvas/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '그래프 확대' })).toBeInTheDocument()
    expect(screen.getByLabelText('그래프 범례')).toHaveTextContent('TABLE')
    expect(screen.getByLabelText('선택한 그래프 요소 상세')).toHaveTextContent('Table A')
    await waitFor(() => expect(cytoscape).toHaveBeenCalledTimes(1))
    expect(screen.getByTestId('cytoscape-metrics')).toHaveTextContent('layout')
  })

  it('exposes selected relation inference and provenance evidence through DOM detail', () => {
    const evidenceGraph: ReadGraphModel = {
      ...graph,
      edges: [{
        ...graph.edges[0]!,
        properties: {
          explicit_or_inferred: 'INFERRED',
          confidence: 0.75,
          extraction_method: 'GENERIC_UNIT_MARKER',
        },
        provenance: [{ source: 'DataHub', source_aspect: 'structuredProperties' }],
      }],
    }
    render(<CytoscapeReadGraph ariaLabel="Evidence" graph={evidenceGraph} selectedElementId="edge-a-b" />)
    const detail = screen.getByLabelText('선택한 그래프 요소 상세')
    expect(detail).toHaveTextContent('Properties · 3')
    expect(detail).toHaveTextContent('Provenance evidence · 1')
    expect(detail).toHaveTextContent('confidence')
    expect(detail).toHaveTextContent('GENERIC_UNIT_MARKER')
    expect(detail).toHaveTextContent('structuredProperties')
  })

  it('keeps empty and query-failure states distinct from a rendered graph', () => {
    const { rerender } = render(<CytoscapeReadGraph ariaLabel="Empty" graph={{ kind: 'SEMANTIC', nodes: [], edges: [] }} emptyTitle="인가된 graph가 없습니다." />)
    expect(screen.getByText('인가된 graph가 없습니다.')).toBeInTheDocument()

    rerender(<CytoscapeReadGraph ariaLabel="Failed" graph={graph} errorMessage="GRAPH_QUERY_FAILED" />)
    expect(screen.getByRole('alert')).toHaveTextContent('GRAPH_QUERY_FAILED')
  })

  it('keeps React state overlays outside the renderer-owned canvas host', async () => {
    const view = render(<CytoscapeReadGraph ariaLabel="Transition" graph={graph} />)
    await waitFor(() => expect(cytoscape).toHaveBeenCalledTimes(1))

    view.rerender(<CytoscapeReadGraph ariaLabel="Transition" graph={graph} loading />)
    expect(screen.getByRole('status')).toHaveTextContent('불러오는 중')
    expect(screen.getByTestId('cytoscape-read-graph-canvas').querySelector('.cy-read-graph-canvas-host')).toBeInTheDocument()

    view.rerender(<CytoscapeReadGraph ariaLabel="Transition" graph={graph} />)
    await waitFor(() => expect(cytoscape).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('destroys each Cytoscape instance and its listeners across repeated open/close', async () => {
    const initialInstances = cytoscape.mock.calls.length
    const initialListenerCleanups = cy.removeAllListeners.mock.calls.length
    const initialDestroys = destroy.mock.calls.length
    for (let attempt = 1; attempt <= 4; attempt += 1) {
      const view = render(<CytoscapeReadGraph ariaLabel={`Lifecycle ${attempt}`} graph={graph} />)
      await waitFor(() => expect(cytoscape).toHaveBeenCalledTimes(initialInstances + attempt))
      act(() => view.unmount())
    }
    expect(cy.removeAllListeners).toHaveBeenCalledTimes(initialListenerCleanups + 4)
    expect(destroy).toHaveBeenCalledTimes(initialDestroys + 4)
  })

  it('resolves a missing local entity through the bounded server resolver', async () => {
    const resolve = vi.fn(() => Promise.resolve('node-c'))
    render(<CytoscapeReadGraph ariaLabel="Searchable" graph={graph} onResolveSearch={resolve} />)
    fireEvent.change(screen.getByLabelText('그래프 entity 검색'), { target: { value: 'remote root' } })
    fireEvent.click(screen.getByRole('button', { name: '그래프 검색' }))
    await waitFor(() => expect(resolve).toHaveBeenCalledWith('remote root'))
    expect(screen.getByText('새 bounded graph root를 불러왔습니다.')).toBeInTheDocument()
  })

  it('keeps accessible label navigation separate from bounded body expansion', async () => {
    const activate = vi.fn()
    const expand = vi.fn(() => Promise.resolve())
    render(<CytoscapeReadGraph ariaLabel="Split actions" graph={graph} onActivateNode={activate} onExpandNode={expand} />)

    fireEvent.click(screen.getByRole('button', { name: 'Table A 상세 열기' }))
    expect(activate).toHaveBeenCalledWith('node-a')
    expect(expand).not.toHaveBeenCalled()

    fireEvent.click(screen.getAllByRole('button', { name: 'Downstream 2-level 확장' })[0]!)
    await waitFor(() => expect(expand).toHaveBeenCalledWith('node-a', {
      direction: 'DOWNSTREAM', depth: 2, source: 'CONTROL',
    }))
    expect(activate).toHaveBeenCalledTimes(1)
  })

  it('resumes bounded physics on grab/free without enabling fit or recentering', async () => {
    render(<CytoscapeReadGraph ariaLabel="Physics" graph={graph} />)
    await waitFor(() => expect(cytoscape).toHaveBeenCalled())
    const grab = cy.on.mock.calls.find(([event]) => event === 'grab')?.[2] as ((event: {
      target: { id: () => string }
    }) => void) | undefined
    const free = cy.on.mock.calls.find(([event]) => event === 'free')?.[2] as typeof grab
    expect(grab).toBeTypeOf('function')
    expect(free).toBeTypeOf('function')

    act(() => grab?.({ target: { id: () => 'node-a' } }))
    expect(layout.mock.calls.at(-1)?.[0]).toMatchObject({
      name: 'cola', fit: false, centerGraph: false, randomize: false, maxSimulationTime: 900,
    })
    act(() => free?.({ target: { id: () => 'node-a' } }))
    expect(layout.mock.calls.at(-1)?.[0]).toMatchObject({
      name: 'cola', fit: false, centerGraph: false, randomize: false, maxSimulationTime: 700,
    })
    expect(cy.pan).toHaveBeenCalledWith({ x: 24, y: 36 })
  })

  it('uses transient hover classes without clearing persistent selection or path state', async () => {
    render(<CytoscapeReadGraph ariaLabel="Hover graph" graph={graph} />)
    await waitFor(() => expect(cytoscape).toHaveBeenCalled())
    const neighbors = {
      removeClass: vi.fn(() => neighbors),
      addClass: vi.fn(() => neighbors),
    }
    const connectedEdges = {
      removeClass: vi.fn(() => connectedEdges),
      addClass: vi.fn(() => connectedEdges),
    }
    const mouseover = cy.on.mock.calls.find(([event]) => event === 'mouseover')?.[2] as ((event: {
      target: {
        neighborhood: (selector: string) => typeof neighbors
        connectedEdges: () => typeof connectedEdges
        removeClass: ReturnType<typeof vi.fn>
        addClass: ReturnType<typeof vi.fn>
      }
    }) => void) | undefined
    const mouseout = cy.on.mock.calls.find(([event]) => event === 'mouseout')?.[2] as (() => void) | undefined
    const target = {
      neighborhood: vi.fn(() => neighbors),
      connectedEdges: vi.fn(() => connectedEdges),
      removeClass: vi.fn(() => target),
      addClass: vi.fn(() => target),
    }

    act(() => mouseover?.({ target }))
    expect(elements.addClass).toHaveBeenCalledWith('graph-hover-dim')
    expect(target.addClass).toHaveBeenCalledWith('graph-hover')
    expect(neighbors.addClass).toHaveBeenCalledWith('graph-hover-neighbor')
    expect(connectedEdges.addClass).toHaveBeenCalledWith('graph-hover-edge')

    act(() => mouseout?.())
    expect(elements.removeClass).toHaveBeenCalledWith('graph-hover graph-hover-neighbor graph-hover-edge graph-hover-dim')
    expect(elements.removeClass).not.toHaveBeenCalledWith(expect.stringContaining('graph-highlight'))
  })

  it('invokes bounded expand for the selected canonical node', async () => {
    const expand = vi.fn(() => Promise.resolve())
    render(<CytoscapeReadGraph ariaLabel="Expandable" graph={graph} onExpandNode={expand} selectedElementId="node-a" />)
    fireEvent.click(screen.getAllByRole('button', { name: 'Upstream 2-level 확장' })[0]!)
    await waitFor(() => expect(expand).toHaveBeenCalledWith('node-a', {
      direction: 'UPSTREAM', depth: 2, source: 'CONTROL',
    }))
  })
})
