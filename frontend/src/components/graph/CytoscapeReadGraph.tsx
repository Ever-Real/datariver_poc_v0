import { Maximize2, Minus, Plus, RotateCcw, Search } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from 'react'
import type { Core, EdgeSingular, EventObjectNode, StylesheetJson } from 'cytoscape'
import {
  cytoscapeLayout,
  toCytoscapeElements,
  type ReadGraphEdge,
  type ReadGraphModel,
  type ReadGraphNode,
} from './CytoscapeGraphAdapter'
import './CytoscapeReadGraph.css'

export interface CytoscapeGraphMetrics {
  nodes: number
  edges: number
  transform_ms: number
  layout_ms: number
  first_usable_render_ms: number
  last_interaction_ms?: number
}

interface CytoscapeReadGraphProps {
  graph: ReadGraphModel
  ariaLabel: string
  height?: number
  loading?: boolean
  errorMessage?: string
  emptyTitle?: string
  emptyDescription?: string
  selectedElementId?: string
  onSelectNode?: (nodeId: string) => void
  onSelectEdge?: (edgeId: string) => void
  onActivateNode?: (nodeId: string) => void
  onExpandNode?: (nodeId: string) => void | Promise<void>
  onCollapseNode?: (nodeId: string) => void
  onResolveSearch?: (query: string) => Promise<string | undefined>
  onReset?: () => void
  onMetrics?: (metrics: CytoscapeGraphMetrics) => void
  boundNotice?: string
}

function colorValue(element: HTMLElement, token: string, fallback: string): string {
  const value = getComputedStyle(element).getPropertyValue(token).trim()
  return value || fallback
}

function graphStyles(element: HTMLElement): StylesheetJson {
  const navy = colorValue(element, '--navy-900', '#0a192f')
  const blue = colorValue(element, '--blue-700', '#004b87')
  const line = colorValue(element, '--line-300', '#cbd5e1')
  return [
    {
      selector: 'node',
      style: {
        'background-color': '#ffffff',
        'border-color': line,
        'border-width': 2,
        color: navy,
        content: 'data(canvasLabel)',
        'font-family': 'Inter, Pretendard, system-ui, sans-serif',
        'font-size': 10,
        'font-weight': 700,
        height: 52,
        label: 'data(canvasLabel)',
        'line-height': 1.25,
        padding: '10px',
        shape: 'rectangle',
        'text-halign': 'center',
        'text-max-width': '140px',
        'text-overflow-wrap': 'whitespace',
        'text-wrap': 'wrap',
        'text-valign': 'center',
        width: 170,
      },
    },
    { selector: 'node[shape = "round-rectangle"]', style: { shape: 'round-rectangle' } },
    { selector: 'node[shape = "diamond"]', style: { shape: 'diamond' } },
    { selector: 'node[shape = "hexagon"]', style: { shape: 'hexagon' } },
    { selector: 'node[role = "ROOT"]', style: { 'background-color': '#eaf4fa', 'border-color': blue, 'border-width': 4 } },
    { selector: 'node[role = "UPSTREAM"]', style: { 'background-color': '#fff8ea', 'border-color': '#9b6a29' } },
    { selector: 'node[role = "DOWNSTREAM"]', style: { 'background-color': '#ecfdf5', 'border-color': '#367a57' } },
    {
      selector: 'edge',
      style: {
        'curve-style': 'bezier',
        'font-size': 9,
        label: 'data(label)',
        'line-color': '#71869a',
        'target-arrow-color': '#71869a',
        'target-arrow-shape': 'triangle',
        'text-background-color': '#ffffff',
        'text-background-opacity': 0.9,
        'text-background-padding': '2px',
        'text-rotation': 'autorotate',
        width: 1.6,
      },
    },
    { selector: ':selected', style: { 'border-color': '#c2410c', 'border-width': 5, 'line-color': '#c2410c', 'target-arrow-color': '#c2410c', width: 3 } },
    { selector: '.graph-highlight', style: { 'border-color': blue, 'border-width': 5, 'line-color': blue, 'target-arrow-color': blue, opacity: 1, width: 3 } },
    { selector: '.graph-dim', style: { opacity: 0.18, 'text-opacity': 0.35 } },
  ]
}

function findNode(graph: ReadGraphModel, query: string): ReadGraphNode | undefined {
  const normalized = query.trim().toLocaleLowerCase()
  if (!normalized) return undefined
  return graph.nodes.find((node) => node.id.toLocaleLowerCase() === normalized
    || node.label.toLocaleLowerCase() === normalized)
    ?? graph.nodes.find((node) => node.id.toLocaleLowerCase().includes(normalized)
      || node.label.toLocaleLowerCase().includes(normalized)
      || node.entityType.toLocaleLowerCase().includes(normalized))
}

function selectedDescription(node?: ReadGraphNode, edge?: ReadGraphEdge): string {
  if (node) return `${node.label}, ${node.entityType}, canonical id ${node.id}`
  if (edge) return `${edge.label}, ${edge.source}에서 ${edge.target} 관계`
  return '선택된 그래프 요소가 없습니다.'
}

export function CytoscapeReadGraph({
  graph,
  ariaLabel,
  height = 440,
  loading = false,
  errorMessage,
  emptyTitle = '표시할 그래프 데이터가 없습니다.',
  emptyDescription = '소스 또는 에셋을 선택하면 권한 범위의 실제 관계를 표시합니다.',
  selectedElementId,
  onSelectNode,
  onSelectEdge,
  onActivateNode,
  onExpandNode,
  onCollapseNode,
  onResolveSearch,
  onReset,
  onMetrics,
  boundNotice,
}: CytoscapeReadGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | undefined>(undefined)
  const selectedRef = useRef(selectedElementId)
  const callbacksRef = useRef({ onSelectNode, onSelectEdge, onMetrics })
  const [internalSelectedId, setInternalSelectedId] = useState(selectedElementId)
  const [query, setQuery] = useState('')
  const [searchNotice, setSearchNotice] = useState('')
  const [layoutError, setLayoutError] = useState('')
  const [busyAction, setBusyAction] = useState(false)
  const [metrics, setMetrics] = useState<CytoscapeGraphMetrics>()
  const searchId = useId()

  useEffect(() => {
    callbacksRef.current = { onSelectNode, onSelectEdge, onMetrics }
  }, [onMetrics, onSelectEdge, onSelectNode])

  useEffect(() => {
    if (selectedElementId === undefined) return
    setInternalSelectedId(selectedElementId)
    selectedRef.current = selectedElementId
    const element = cyRef.current?.getElementById(selectedElementId)
    if (element?.length) {
      cyRef.current?.elements().unselect()
      element.select()
    }
  }, [selectedElementId])

  const adapted = useMemo(() => {
    try {
      return { elements: toCytoscapeElements(graph), error: '' }
    } catch (error) {
      return {
        elements: [],
        error: error instanceof Error ? error.message : '그래프 변환에 실패했습니다.',
      }
    }
  }, [graph])

  useEffect(() => {
    const container = containerRef.current
    if (!container || adapted.error || loading || errorMessage || graph.nodes.length === 0) return
    let disposed = false
    let instance: Core | undefined
    let resizeObserver: ResizeObserver | undefined
    const renderStarted = performance.now()
    setLayoutError('')
    setMetrics(undefined)
    void import('cytoscape')
      .then(({ default: cytoscape }) => {
        if (disposed) return
        const transformStarted = performance.now()
        const elements = toCytoscapeElements(graph)
        const transformMs = performance.now() - transformStarted
        instance = cytoscape({
          container,
          elements,
          style: graphStyles(container),
          layout: { name: 'preset' },
          minZoom: 0.08,
          maxZoom: 3,
          boxSelectionEnabled: false,
          autoungrabify: false,
        })
        cyRef.current = instance
        const selectNode = (event: EventObjectNode) => {
          const started = performance.now()
          const id = event.target.id()
          selectedRef.current = id
          setInternalSelectedId(id)
          callbacksRef.current.onSelectNode?.(id)
          setMetrics((current) => current ? { ...current, last_interaction_ms: performance.now() - started } : current)
        }
        const selectEdge = (event: { target: EdgeSingular }) => {
          const started = performance.now()
          const id = event.target.id()
          selectedRef.current = id
          setInternalSelectedId(id)
          callbacksRef.current.onSelectEdge?.(id)
          setMetrics((current) => current ? { ...current, last_interaction_ms: performance.now() - started } : current)
        }
        instance.on('tap', 'node', selectNode)
        instance.on('tap', 'edge', selectEdge)
        const layoutStarted = performance.now()
        const layout = instance.layout(cytoscapeLayout(graph.kind))
        layout.one('layoutstop', () => {
          if (disposed || !instance) return
          instance.fit(undefined, 28)
          const nextMetrics = {
            nodes: graph.nodes.length,
            edges: graph.edges.length,
            transform_ms: transformMs,
            layout_ms: performance.now() - layoutStarted,
            first_usable_render_ms: performance.now() - renderStarted,
          }
          setMetrics(nextMetrics)
          callbacksRef.current.onMetrics?.(nextMetrics)
          const retained = selectedRef.current ? instance.getElementById(selectedRef.current) : undefined
          if (retained?.length) retained.select()
        })
        layout.run()
        if (typeof ResizeObserver !== 'undefined') {
          resizeObserver = new ResizeObserver(() => {
            instance?.resize()
          })
          resizeObserver.observe(container)
        }
      })
      .catch((error) => {
        if (!disposed) setLayoutError(error instanceof Error ? error.message : 'Cytoscape layout을 초기화하지 못했습니다.')
      })
    return () => {
      disposed = true
      resizeObserver?.disconnect()
      instance?.removeAllListeners()
      instance?.destroy()
      if (cyRef.current === instance) cyRef.current = undefined
    }
  }, [adapted.error, errorMessage, graph, loading])

  const focusElement = useCallback((id: string) => {
    const cy = cyRef.current
    const element = cy?.getElementById(id)
    if (!cy || !element?.length) return false
    cy.elements().unselect().removeClass('graph-highlight graph-dim')
    element.select().addClass('graph-highlight')
    cy.animate({ center: { eles: element }, zoom: Math.max(cy.zoom(), 1.15), duration: 220 })
    selectedRef.current = id
    setInternalSelectedId(id)
    return true
  }, [])

  const search = async (event: FormEvent) => {
    event.preventDefault()
    const local = findNode(graph, query)
    if (local) {
      focusElement(local.id)
      setSearchNotice(`${local.label} 노드를 선택했습니다.`)
      onSelectNode?.(local.id)
      return
    }
    if (!onResolveSearch) {
      setSearchNotice('현재 bounded graph에서 일치하는 노드를 찾지 못했습니다.')
      return
    }
    setBusyAction(true)
    setSearchNotice('권한 범위에서 root entity를 확인하는 중입니다.')
    try {
      const resolved = await onResolveSearch(query.trim())
      if (!resolved) {
        setSearchNotice('권한 범위에서 일치하는 entity를 찾지 못했습니다.')
        return
      }
      selectedRef.current = resolved
      setInternalSelectedId(resolved)
      setSearchNotice('새 bounded graph root를 불러왔습니다.')
    } catch (error) {
      setSearchNotice(error instanceof Error ? error.message : 'Graph entity 검색에 실패했습니다.')
    } finally {
      setBusyAction(false)
    }
  }

  const highlight = (direction: 'UPSTREAM' | 'DOWNSTREAM' | 'PATH') => {
    const cy = cyRef.current
    const selected = selectedRef.current ? cy?.getElementById(selectedRef.current) : undefined
    if (!cy || !selected?.isNode()) {
      setSearchNotice('먼저 노드를 선택하세요.')
      return
    }
    const nodes = direction === 'UPSTREAM'
      ? selected.predecessors()
      : direction === 'DOWNSTREAM'
        ? selected.successors()
        : selected.closedNeighborhood()
    cy.elements().addClass('graph-dim').removeClass('graph-highlight')
    nodes.union(selected).removeClass('graph-dim').addClass('graph-highlight')
    cy.fit(nodes.union(selected), 42)
    setSearchNotice(direction === 'PATH' ? '선택 노드의 직접 관계를 강조했습니다.' : `${direction} 관계를 강조했습니다.`)
  }

  const reset = () => {
    const cy = cyRef.current
    cy?.elements().removeClass('graph-highlight graph-dim').unselect()
    if (cy) {
      cy.layout(cytoscapeLayout(graph.kind)).run()
      cy.fit(undefined, 28)
    }
    selectedRef.current = graph.rootId
    setInternalSelectedId(graph.rootId)
    setSearchNotice('그래프 view를 초기화했습니다.')
    onReset?.()
  }

  const keyboardControl = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === '+' || event.key === '=') cyRef.current?.zoom(cyRef.current.zoom() * 1.18)
    else if (event.key === '-') cyRef.current?.zoom(cyRef.current.zoom() / 1.18)
    else if (event.key === '0') reset()
    else return
    event.preventDefault()
  }

  const selectedNode = graph.nodes.find((node) => node.id === internalSelectedId)
  const selectedEdge = graph.edges.find((edge) => edge.id === internalSelectedId)
  const visibleError = errorMessage || adapted.error || layoutError
  const entityTypes = [...new Set(graph.nodes.map((node) => node.entityType))].sort().slice(0, 8)
  const expandSelected = async () => {
    if (!selectedNode || !onExpandNode) return
    setBusyAction(true)
    try {
      await onExpandNode(selectedNode.id)
    } catch (error) {
      setSearchNotice(error instanceof Error ? error.message : '부분 graph 확장에 실패했습니다.')
    } finally {
      setBusyAction(false)
    }
  }

  return (
    <section className="cy-read-graph" aria-label={ariaLabel} data-graph-kind={graph.kind}>
      <div className="cy-read-graph-toolbar" aria-label="그래프 조작 도구">
        <form onSubmit={(event) => void search(event)} role="search">
          <label className="sr-only" htmlFor={searchId}>그래프 entity 검색</label>
          <input id={searchId} maxLength={240} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="현재 graph 또는 root 검색" />
          <button aria-label="그래프 검색" disabled={busyAction || !query.trim()} type="submit"><Search size={13} /></button>
        </form>
        <div className="cy-read-graph-tool-buttons">
          <button aria-label="그래프 확대" onClick={() => cyRef.current?.zoom(cyRef.current.zoom() * 1.18)} type="button"><Plus size={13} /></button>
          <button aria-label="그래프 축소" onClick={() => cyRef.current?.zoom(cyRef.current.zoom() / 1.18)} type="button"><Minus size={13} /></button>
          <button aria-label="그래프 전체 맞춤" onClick={() => cyRef.current?.fit(undefined, 28)} type="button"><Maximize2 size={13} /></button>
          <button aria-label="그래프 view 초기화" onClick={reset} type="button"><RotateCcw size={13} /></button>
        </div>
      </div>
      <div className="cy-read-graph-relation-tools" aria-label="관계 강조 도구">
        <button type="button" onClick={() => highlight('UPSTREAM')}>Upstream</button>
        <button type="button" onClick={() => highlight('DOWNSTREAM')}>Downstream</button>
        <button type="button" onClick={() => highlight('PATH')}>직접 관계</button>
        {onExpandNode && <button disabled={!selectedNode || busyAction} onClick={() => void expandSelected()} type="button">선택 확장</button>}
        {onCollapseNode && <button disabled={!selectedNode} onClick={() => selectedNode && onCollapseNode(selectedNode.id)} type="button">선택 접기</button>}
      </div>
      <div
        aria-label={`${ariaLabel} canvas. +, -, 0 키로 확대, 축소, 초기화할 수 있습니다.`}
        className="cy-read-graph-canvas"
        data-testid="cytoscape-read-graph-canvas"
        onKeyDown={keyboardControl}
        ref={containerRef}
        role="img"
        style={{ height }}
        tabIndex={0}
      >
        {loading && <div className="cy-read-graph-state" role="status">권한 필터링된 graph를 불러오는 중입니다.</div>}
        {!loading && visibleError && <div className="cy-read-graph-state cy-read-graph-error" role="alert">Graph query 또는 layout 실패: {visibleError}</div>}
        {!loading && !visibleError && graph.nodes.length === 0 && <div className="cy-read-graph-state" role="status"><strong>{emptyTitle}</strong><span>{emptyDescription}</span></div>}
      </div>
      <div className="cy-read-graph-status" aria-live="polite">
        <span>{graph.nodes.length} nodes · {graph.edges.length} edges</span>
        {boundNotice && <strong>{boundNotice}</strong>}
        {metrics && <span data-testid="cytoscape-metrics">transform {metrics.transform_ms.toFixed(1)}ms · layout {metrics.layout_ms.toFixed(1)}ms · usable {metrics.first_usable_render_ms.toFixed(1)}ms</span>}
        {searchNotice && <span>{searchNotice}</span>}
      </div>
      <div className="cy-read-graph-legend" aria-label="그래프 범례">
        <strong>범례</strong>
        {graph.kind === 'LINEAGE' && <><span data-shape="root">현재</span><span data-shape="upstream">Upstream</span><span data-shape="downstream">Downstream</span></>}
        {entityTypes.map((entityType) => <span key={entityType} data-shape="entity">{entityType}</span>)}
      </div>
      {graph.nodes.length > 0 && <details className="cy-read-graph-entity-list">
        <summary>접근 가능한 bounded entity 목록 · {graph.nodes.length}</summary>
        <ul>
          {graph.nodes.map((node) => <li key={node.id}><button
            aria-label={`${node.label}, ${node.entityType} · 근거 ${node.provenance.length}`}
            aria-pressed={node.id === internalSelectedId}
            onClick={() => {
              focusElement(node.id)
              onSelectNode?.(node.id)
            }}
            type="button"
          ><strong>{node.label}</strong><span>{node.entityType}</span></button></li>)}
        </ul>
      </details>}
      <article className="cy-read-graph-detail" aria-label="선택한 그래프 요소 상세" aria-live="polite">
        <header><strong>{selectedNode?.label ?? selectedEdge?.label ?? '선택된 요소 없음'}</strong><span>{selectedNode?.entityType ?? selectedEdge?.relationType ?? 'Canvas에서 노드 또는 관계를 선택하세요.'}</span></header>
        <p>{selectedDescription(selectedNode, selectedEdge)}</p>
        {(selectedNode || selectedEdge) && <dl>
          <div><dt>Canonical ID</dt><dd>{selectedNode?.id ?? selectedEdge?.id}</dd></div>
          {selectedEdge && <div><dt>Path</dt><dd>{selectedEdge.source} → {selectedEdge.target}</dd></div>}
          <div><dt>Provenance</dt><dd>{selectedNode?.provenance.length ?? selectedEdge?.provenance.length ?? 0} records</dd></div>
        </dl>}
        {selectedNode && onActivateNode && <button type="button" onClick={() => onActivateNode(selectedNode.id)}>선택 entity 상세 열기</button>}
      </article>
    </section>
  )
}
