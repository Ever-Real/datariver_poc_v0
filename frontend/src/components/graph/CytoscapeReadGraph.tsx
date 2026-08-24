import { Crosshair, Maximize2, Minus, Plus, RotateCcw, Search } from 'lucide-react'
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
import type {
  Core,
  EdgeSingular,
  EventObjectNode,
  Layouts,
  NodeSingular,
  Position,
  StylesheetJson,
} from 'cytoscape'
import {
  cytoscapeLayout,
  lineageRoleGaps,
  toCytoscapeElements,
  type ReadGraphEdge,
  type ReadGraphModel,
  type ReadGraphNode,
  type ReadGraphRole,
} from './CytoscapeGraphAdapter'
import './CytoscapeReadGraph.css'

export type CytoscapeExpansionDirection = 'UPSTREAM' | 'DOWNSTREAM'

export interface CytoscapeExpandRequest {
  direction: CytoscapeExpansionDirection
  depth: 2
  source: 'BODY' | 'CONTROL'
}

export interface CytoscapeGraphMetrics {
  nodes: number
  edges: number
  transform_ms: number
  layout_ms: number
  first_usable_render_ms: number
  last_interaction_ms?: number
  last_settle_ms?: number
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
  onExpandNode?: (nodeId: string, request: CytoscapeExpandRequest) => void | Promise<void>
  onCollapseNode?: (nodeId: string) => void
  onResolveSearch?: (query: string) => Promise<string | undefined>
  onReset?: () => void
  onMetrics?: (metrics: CytoscapeGraphMetrics) => void
  boundNotice?: string
}

export const CYTOSCAPE_NODE_GEOMETRY = Object.freeze({
  width: 142,
  height: 42,
  padding: '6px',
  fontSize: 9,
  textMaxWidth: '122px',
  borderWidth: 2,
})

export const CYTOSCAPE_SELECTED_NODE_HIGHLIGHT = Object.freeze({
  borderWidth: CYTOSCAPE_NODE_GEOMETRY.borderWidth,
  underlayOpacity: 0.12,
  underlayPadding: 5,
})

const INTERACTION_PHYSICS_NODE_CAP = 90

export interface RetainedViewport {
  zoom: number
  pan: Position
  anchorId: string
  anchorRenderedPosition: Position
  selectedId?: string
}

function colorValue(element: HTMLElement, token: string, fallback: string): string {
  const value = getComputedStyle(element).getPropertyValue(token).trim()
  return value || fallback
}

export function graphStyles(element: HTMLElement): StylesheetJson {
  const navy = colorValue(element, '--navy-900', '#0a192f')
  const blue = colorValue(element, '--blue-700', '#004b87')
  const line = colorValue(element, '--line-300', '#cbd5e1')
  const selection = colorValue(element, '--orange-700', '#c2410c')
  return [
    {
      selector: 'node',
      style: {
        'background-color': '#ffffff',
        'border-color': line,
        'border-width': CYTOSCAPE_NODE_GEOMETRY.borderWidth,
        color: navy,
        content: 'data(canvasLabel)',
        'font-family': 'Inter, Pretendard, system-ui, sans-serif',
        'font-size': CYTOSCAPE_NODE_GEOMETRY.fontSize,
        'font-weight': 650,
        height: CYTOSCAPE_NODE_GEOMETRY.height,
        label: 'data(canvasLabel)',
        'line-height': 1.18,
        padding: CYTOSCAPE_NODE_GEOMETRY.padding,
        shape: 'rectangle',
        'text-halign': 'center',
        'text-max-width': CYTOSCAPE_NODE_GEOMETRY.textMaxWidth,
        'text-overflow-wrap': 'anywhere',
        'text-wrap': 'wrap',
        'text-valign': 'center',
        width: CYTOSCAPE_NODE_GEOMETRY.width,
      },
    },
    { selector: 'node[shape = "round-rectangle"]', style: { shape: 'round-rectangle' } },
    { selector: 'node[shape = "diamond"]', style: { shape: 'diamond' } },
    { selector: 'node[shape = "hexagon"]', style: { shape: 'hexagon' } },
    { selector: 'node[role = "ROOT"]', style: { 'background-color': '#eaf4fa', 'border-color': blue } },
    { selector: 'node[role = "UPSTREAM"]', style: { 'background-color': '#fff8ea', 'border-color': '#9b6a29' } },
    { selector: 'node[role = "DOWNSTREAM"]', style: { 'background-color': '#ecfdf5', 'border-color': '#367a57' } },
    {
      selector: 'edge',
      style: {
        'arrow-scale': 1.25,
        'curve-style': 'bezier',
        'font-size': 8,
        label: 'data(label)',
        'line-color': '#526a80',
        'target-arrow-color': '#526a80',
        'target-arrow-shape': 'triangle',
        'text-background-color': '#ffffff',
        'text-background-opacity': 0.88,
        'text-background-padding': '2px',
        'text-rotation': 'autorotate',
        width: 2.2,
      },
    },
    { selector: 'edge[branch = "UPSTREAM"]', style: { 'line-color': '#8a5b1f', 'target-arrow-color': '#8a5b1f' } },
    { selector: 'edge[branch = "DOWNSTREAM"]', style: { 'line-color': '#276749', 'target-arrow-color': '#276749' } },
    {
      selector: 'node:selected',
      style: {
        'border-color': selection,
        'border-opacity': 1,
        'border-width': CYTOSCAPE_SELECTED_NODE_HIGHLIGHT.borderWidth,
        'underlay-color': selection,
        'underlay-opacity': CYTOSCAPE_SELECTED_NODE_HIGHLIGHT.underlayOpacity,
        'underlay-padding': CYTOSCAPE_SELECTED_NODE_HIGHLIGHT.underlayPadding,
      },
    },
    { selector: 'edge:selected', style: { 'line-color': selection, 'target-arrow-color': selection, width: 3 } },
    {
      selector: 'node.graph-highlight',
      style: {
        'border-color': blue,
        'border-width': CYTOSCAPE_NODE_GEOMETRY.borderWidth,
        'underlay-color': blue,
        'underlay-opacity': 0.1,
        'underlay-padding': 5,
      },
    },
    { selector: 'edge.graph-highlight', style: { 'line-color': blue, 'target-arrow-color': blue, opacity: 1, width: 3 } },
    { selector: '.graph-dim', style: { opacity: 0.18, 'text-opacity': 0.35 } },
  ]
}

export function isRenderedLabelHit(node: NodeSingular, renderedPosition?: Position): boolean {
  if (!renderedPosition) return false
  const box = node.renderedBoundingBox({
    includeNodes: false,
    includeEdges: false,
    includeLabels: true,
    includeOverlays: false,
    includeUnderlays: false,
  })
  return renderedPosition.x >= box.x1 && renderedPosition.x <= box.x2
    && renderedPosition.y >= box.y1 && renderedPosition.y <= box.y2
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

function directionForRole(role: ReadGraphRole | undefined): CytoscapeExpansionDirection | undefined {
  return role === 'UPSTREAM' || role === 'DOWNSTREAM' ? role : undefined
}

function deterministicSeed(anchor: Position, index: number, direction?: CytoscapeExpansionDirection): Position {
  const angle = (index % 7) * (Math.PI * 2 / 7)
  const distance = 76 + Math.floor(index / 7) * 30
  const directionalOffset = direction === 'UPSTREAM' ? -110 : direction === 'DOWNSTREAM' ? 110 : 0
  return { x: anchor.x + directionalOffset + Math.cos(angle) * distance, y: anchor.y + Math.sin(angle) * distance }
}

function retainViewport(cy: Core, anchorId: string, selectedId?: string): RetainedViewport | undefined {
  const anchor = cy.getElementById(anchorId)
  if (!anchor || typeof anchor.isNode !== 'function' || !anchor.isNode()) return undefined
  return {
    zoom: cy.zoom(),
    pan: { ...cy.pan() },
    anchorId,
    anchorRenderedPosition: { ...anchor.renderedPosition() },
    selectedId,
  }
}

export function restoreViewport(cy: Core, retained?: RetainedViewport) {
  if (!retained) return
  cy.zoom(retained.zoom)
  cy.pan(retained.pan)
  const anchor = cy.getElementById(retained.anchorId)
  if (anchor?.isNode()) {
    const current = anchor.renderedPosition()
    const pan = cy.pan()
    cy.pan({
      x: pan.x + retained.anchorRenderedPosition.x - current.x,
      y: pan.y + retained.anchorRenderedPosition.y - current.y,
    })
  }
  if (retained.selectedId) cy.getElementById(retained.selectedId).select()
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
  const layoutRef = useRef<Layouts | undefined>(undefined)
  const selectedRef = useRef(selectedElementId)
  const directionRef = useRef<CytoscapeExpansionDirection | undefined>(undefined)
  const graphRef = useRef(graph)
  const pendingViewportRef = useRef<RetainedViewport | undefined>(undefined)
  const viewportFallbackFrameRef = useRef<number | undefined>(undefined)
  const initialFitRef = useRef(false)
  const callbacksRef = useRef({ onSelectNode, onSelectEdge, onActivateNode, onExpandNode, onMetrics })
  const [coreRevision, setCoreRevision] = useState(0)
  const [internalSelectedId, setInternalSelectedId] = useState(selectedElementId)
  const [directionContext, setDirectionContext] = useState<CytoscapeExpansionDirection>()
  const [query, setQuery] = useState('')
  const [searchNotice, setSearchNotice] = useState('')
  const [layoutError, setLayoutError] = useState('')
  const [busyAction, setBusyAction] = useState(false)
  const [metrics, setMetrics] = useState<CytoscapeGraphMetrics>()
  const searchId = useId()

  useEffect(() => {
    graphRef.current = graph
  }, [graph])

  useEffect(() => {
    callbacksRef.current = { onSelectNode, onSelectEdge, onActivateNode, onExpandNode, onMetrics }
  }, [onActivateNode, onExpandNode, onMetrics, onSelectEdge, onSelectNode])

  const adapted = useMemo(() => {
    try {
      return { elements: toCytoscapeElements(graph), error: '' }
    } catch (error) {
      return { elements: [], error: error instanceof Error ? error.message : '그래프 변환에 실패했습니다.' }
    }
  }, [graph])
  const renderable = !adapted.error && !loading && !errorMessage && graph.nodes.length > 0

  const stopLayout = useCallback(() => {
    layoutRef.current?.stop()
    layoutRef.current = undefined
  }, [])

  const runPhysics = useCallback((cy: Core, options: {
    initial?: boolean
    anchorId?: string
    lockExistingIds?: Set<string>
    retained?: RetainedViewport
    maximumMs?: number
    lockAnchor?: boolean
  } = {}) => {
    stopLayout()
    const started = performance.now()
    const anchor = options.anchorId ? cy.getElementById(options.anchorId) : undefined
    const locked = options.lockExistingIds && typeof cy.nodes === 'function'
      ? cy.nodes().filter((node) => Boolean(options.lockExistingIds?.has(node.id())))
      : undefined
    locked?.lock()
    const anchorLocked = Boolean(anchor?.isNode() && options.lockAnchor !== false)
    if (anchorLocked) anchor?.lock()
    const nodes = typeof cy.nodes === 'function' ? cy.nodes() : undefined
    const scope = nodes && nodes.length > INTERACTION_PHYSICS_NODE_CAP && anchor?.isNode()
      ? anchor.closedNeighborhood()
      : cy.elements()
    const layoutOwner = typeof scope.layout === 'function' ? scope : cy
    const scopedNodeIds = typeof scope.nodes === 'function'
      ? new Set(scope.nodes().map((node) => node.id()))
      : new Set<string>()
    const gapInequalities = lineageRoleGaps(graphRef.current)
      .filter(({ leftId, rightId }) => scopedNodeIds.has(leftId) && scopedNodeIds.has(rightId))
      .map(({ axis, leftId, rightId, gap }) => ({
        axis,
        left: cy.getElementById(leftId),
        right: cy.getElementById(rightId),
        gap,
      }))
    const layout = layoutOwner.layout({
      ...cytoscapeLayout(graphRef.current.kind),
      ...(gapInequalities.length > 0 ? { gapInequalities } : {}),
      maxSimulationTime: options.maximumMs ?? (options.initial ? 1_500 : 850),
      fit: false,
      randomize: false,
      centerGraph: false,
    } as never)
    layoutRef.current = layout
    layout.one('layoutstop', () => {
      locked?.unlock()
      if (anchorLocked) anchor?.unlock()
      restoreViewport(cy, options.retained)
      if (options.initial && !initialFitRef.current) {
        cy.fit(undefined, 28)
        initialFitRef.current = true
      }
      setMetrics((current) => {
        if (!current) return current
        return { ...current, last_settle_ms: performance.now() - started }
      })
      if (layoutRef.current === layout) layoutRef.current = undefined
    })
    layout.run()
  }, [stopLayout])

  const selectNode = useCallback((nodeId: string) => {
    const cy = cyRef.current
    const node = cy?.getElementById(nodeId)
    selectedRef.current = nodeId
    setInternalSelectedId(nodeId)
    callbacksRef.current.onSelectNode?.(nodeId)
    if (!cy || !node || typeof node.isNode !== 'function' || !node.isNode()) return true
    const zoom = cy.zoom()
    const pan = { ...cy.pan() }
    cy.elements().unselect()
    node.select()
    cy.zoom(zoom)
    cy.pan(pan)
    return true
  }, [])

  const performExpand = useCallback(async (
    nodeId: string,
    direction: CytoscapeExpansionDirection | undefined,
    source: CytoscapeExpandRequest['source'],
  ) => {
    const callback = callbacksRef.current.onExpandNode
    if (!callback) return
    if (!direction) {
      setSearchNotice('방향이 모호합니다. Upstream 또는 Downstream을 먼저 선택하세요.')
      return
    }
    const cy = cyRef.current
    if (cy) pendingViewportRef.current = retainViewport(cy, nodeId, selectedRef.current)
    setBusyAction(true)
    try {
      await callback(nodeId, { direction, depth: 2, source })
      setSearchNotice(`${direction} 2-level bounded neighborhood를 확장했습니다.`)
      if (viewportFallbackFrameRef.current !== undefined) cancelAnimationFrame(viewportFallbackFrameRef.current)
      viewportFallbackFrameRef.current = requestAnimationFrame(() => {
        const retained = pendingViewportRef.current
        if (retained && cyRef.current) restoreViewport(cyRef.current, retained)
        pendingViewportRef.current = undefined
        viewportFallbackFrameRef.current = undefined
      })
    } catch (error) {
      pendingViewportRef.current = undefined
      setSearchNotice(error instanceof Error ? error.message : '부분 graph 확장에 실패했습니다.')
    } finally {
      setBusyAction(false)
    }
  }, [])

  useEffect(() => {
    const container = containerRef.current
    if (!container || !renderable) return
    let disposed = false
    let instance: Core | undefined
    let resizeObserver: ResizeObserver | undefined
    const renderStarted = performance.now()
    setLayoutError('')
    setMetrics(undefined)
    initialFitRef.current = false
    void Promise.all([import('cytoscape'), import('cytoscape-cola')])
      .then(([{ default: cytoscape }, { default: cola }]) => {
        if (disposed) return
        // The production Cytoscape factory always exposes `use`; the guard also
        // keeps renderer unit doubles focused on Core lifecycle behavior.
        if (typeof cytoscape.use === 'function') cytoscape.use(cola)
        const transformStarted = performance.now()
        const current = graphRef.current
        const elements = toCytoscapeElements(current)
        const transformMs = performance.now() - transformStarted
        instance = cytoscape({
          container,
          elements,
          style: graphStyles(container),
          layout: { name: 'grid', animate: false, fit: false, padding: 0 },
          minZoom: 0.08,
          maxZoom: 3,
          boxSelectionEnabled: false,
          autoungrabify: false,
        })
        cyRef.current = instance
        setCoreRevision((value) => value + 1)
        const handleNodeTap = (event: EventObjectNode) => {
          const started = performance.now()
          const node = event.target
          if (isRenderedLabelHit(node, event.renderedPosition) && callbacksRef.current.onActivateNode) {
            callbacksRef.current.onActivateNode(node.id())
            return
          }
          selectNode(node.id())
          const role = node.data('role') as ReadGraphRole | undefined
          void performExpand(node.id(), directionForRole(role) ?? directionRef.current, 'BODY')
          setMetrics((value) => value ? { ...value, last_interaction_ms: performance.now() - started } : value)
        }
        const handleEdgeTap = (event: { target: EdgeSingular }) => {
          const started = performance.now()
          const id = event.target.id()
          const zoom = instance?.zoom()
          const pan = instance?.pan()
          instance?.elements().unselect()
          event.target.select()
          if (zoom !== undefined) instance?.zoom(zoom)
          if (pan) instance?.pan(pan)
          selectedRef.current = id
          setInternalSelectedId(id)
          callbacksRef.current.onSelectEdge?.(id)
          setMetrics((value) => value ? { ...value, last_interaction_ms: performance.now() - started } : value)
        }
        const preserveDuringDrag = (event: EventObjectNode) => {
          if (!instance) return
          const viewport = { zoom: instance.zoom(), pan: { ...instance.pan() } }
          runPhysics(instance, { anchorId: event.target.id(), lockAnchor: false, maximumMs: 900 })
          instance.zoom(viewport.zoom)
          instance.pan(viewport.pan)
        }
        const settleAfterDrag = (event: EventObjectNode) => {
          if (!instance) return
          const viewport = { zoom: instance.zoom(), pan: { ...instance.pan() } }
          runPhysics(instance, { anchorId: event.target.id(), lockAnchor: false, maximumMs: 700 })
          instance.zoom(viewport.zoom)
          instance.pan(viewport.pan)
        }
        instance.on('tap', 'node', handleNodeTap)
        instance.on('tap', 'edge', handleEdgeTap)
        instance.on('grab', 'node', preserveDuringDrag)
        instance.on('free', 'node', settleAfterDrag)
        const nextMetrics = {
          nodes: current.nodes.length,
          edges: current.edges.length,
          transform_ms: transformMs,
          layout_ms: 0,
          first_usable_render_ms: 0,
        }
        setMetrics(nextMetrics)
        runPhysics(instance, { initial: true, maximumMs: 1_500 })
        nextMetrics.layout_ms = performance.now() - renderStarted
        nextMetrics.first_usable_render_ms = performance.now() - renderStarted
        setMetrics(nextMetrics)
        callbacksRef.current.onMetrics?.(nextMetrics)
        if (selectedRef.current) instance.getElementById(selectedRef.current).select()
        if (typeof ResizeObserver !== 'undefined') {
          resizeObserver = new ResizeObserver(() => instance?.resize())
          resizeObserver.observe(container)
        }
      })
      .catch((error) => {
        if (!disposed) setLayoutError(error instanceof Error ? error.message : 'Cytoscape layout을 초기화하지 못했습니다.')
      })
    return () => {
      disposed = true
      resizeObserver?.disconnect()
      if (viewportFallbackFrameRef.current !== undefined) cancelAnimationFrame(viewportFallbackFrameRef.current)
      stopLayout()
      instance?.removeAllListeners()
      instance?.destroy()
      if (cyRef.current === instance) cyRef.current = undefined
    }
  }, [performExpand, renderable, runPhysics, selectNode, stopLayout])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy || !coreRevision) return
    if (typeof cy.elements().map !== 'function') return
    const nextIds = new Set(adapted.elements.map((definition) => String(definition.data.id)))
    const existingIds = new Set(cy.elements().map((element) => element.id()))
    const additions = adapted.elements.filter((definition) => !existingIds.has(String(definition.data.id)))
    const removed = cy.elements().filter((element) => !nextIds.has(element.id()))
    if (additions.length === 0 && removed.length === 0) {
      for (const definition of adapted.elements) cy.getElementById(String(definition.data.id)).data(definition.data)
      return
    }
    const retained = pendingViewportRef.current
      ?? (selectedRef.current ? retainViewport(cy, selectedRef.current, selectedRef.current) : undefined)
    const anchor = retained ? cy.getElementById(retained.anchorId) : undefined
    const anchorPosition = anchor?.isNode() ? anchor.position() : { x: 0, y: 0 }
    const existingNodeIds = new Set(cy.nodes().map((node) => node.id()))
    cy.batch(() => {
      removed.remove()
      additions.forEach((definition, index) => cy.add(definition.group === 'nodes'
        ? { ...definition, position: deterministicSeed(anchorPosition, index, directionRef.current) }
        : definition))
      for (const definition of adapted.elements) cy.getElementById(String(definition.data.id)).data(definition.data)
    })
    if (additions.some((definition) => definition.group === 'nodes')) {
      runPhysics(cy, {
        lockExistingIds: existingNodeIds,
        maximumMs: 950,
        ...(retained ? { anchorId: retained.anchorId, retained } : {}),
      })
    } else restoreViewport(cy, retained)
    pendingViewportRef.current = undefined
    if (viewportFallbackFrameRef.current !== undefined) {
      cancelAnimationFrame(viewportFallbackFrameRef.current)
      viewportFallbackFrameRef.current = undefined
    }
  }, [adapted.elements, coreRevision, runPhysics])

  useEffect(() => {
    if (selectedElementId === undefined) return
    selectedRef.current = selectedElementId
    setInternalSelectedId(selectedElementId)
    const cy = cyRef.current
    const element = cy?.getElementById(selectedElementId)
    if (!cy || !element?.length) return
    const zoom = cy.zoom()
    const pan = { ...cy.pan() }
    cy.elements().unselect()
    element.select()
    cy.zoom(zoom)
    cy.pan(pan)
  }, [selectedElementId, coreRevision])

  const search = async (event: FormEvent) => {
    event.preventDefault()
    const local = findNode(graph, query)
    if (local) {
      selectNode(local.id)
      setSearchNotice(`${local.label} 노드를 선택했습니다.`)
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
      if (!resolved) setSearchNotice('권한 범위에서 일치하는 entity를 찾지 못했습니다.')
      else {
        selectedRef.current = resolved
        setInternalSelectedId(resolved)
        setSearchNotice('새 bounded graph root를 불러왔습니다.')
      }
    } catch (error) {
      setSearchNotice(error instanceof Error ? error.message : 'Graph entity 검색에 실패했습니다.')
    } finally {
      setBusyAction(false)
    }
  }

  const highlight = (direction: CytoscapeExpansionDirection | 'PATH') => {
    if (direction !== 'PATH') {
      directionRef.current = direction
      setDirectionContext(direction)
    }
    const cy = cyRef.current
    const selected = selectedRef.current ? cy?.getElementById(selectedRef.current) : undefined
    if (!cy || !selected?.isNode()) {
      setSearchNotice('먼저 노드를 선택하세요.')
      return
    }
    const nodes = direction === 'UPSTREAM'
      ? selected.successors()
      : direction === 'DOWNSTREAM' ? selected.predecessors() : selected.closedNeighborhood()
    cy.elements().addClass('graph-dim').removeClass('graph-highlight')
    nodes.union(selected).removeClass('graph-dim').addClass('graph-highlight')
    setSearchNotice(direction === 'PATH' ? '선택 노드의 직접 관계를 강조했습니다.' : `${direction} 관계를 강조했습니다.`)
  }

  const reset = () => {
    const cy = cyRef.current
    stopLayout()
    cy?.elements().removeClass('graph-highlight graph-dim').unselect()
    directionRef.current = undefined
    setDirectionContext(undefined)
    selectedRef.current = graph.rootId
    setInternalSelectedId(graph.rootId)
    setSearchNotice('그래프 view를 초기화했습니다.')
    if (cy) {
      initialFitRef.current = false
      runPhysics(cy, { initial: true, maximumMs: 1_200 })
    }
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
  const selectedDirection = directionForRole(selectedNode?.role) ?? directionContext
  const collapseSelected = () => {
    const cy = cyRef.current
    if (!selectedNode || !onCollapseNode) return
    if (cy) pendingViewportRef.current = retainViewport(cy, selectedNode.id, selectedRef.current)
    onCollapseNode(selectedNode.id)
    if (viewportFallbackFrameRef.current !== undefined) cancelAnimationFrame(viewportFallbackFrameRef.current)
    viewportFallbackFrameRef.current = requestAnimationFrame(() => {
      const retained = pendingViewportRef.current
      if (retained && cyRef.current) restoreViewport(cyRef.current, retained)
      pendingViewportRef.current = undefined
      viewportFallbackFrameRef.current = undefined
    })
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
          <button aria-label="선택 노드 중앙 배치" disabled={!selectedNode} onClick={() => selectedNode && cyRef.current?.center(cyRef.current.getElementById(selectedNode.id))} type="button"><Crosshair size={13} /></button>
          <button aria-label="그래프 전체 맞춤" onClick={() => cyRef.current?.fit(undefined, 28)} type="button"><Maximize2 size={13} /></button>
          <button aria-label="그래프 view 초기화" onClick={reset} type="button"><RotateCcw size={13} /></button>
        </div>
      </div>
      <div className="cy-read-graph-relation-tools" aria-label="관계 강조 도구">
        <button aria-pressed={directionContext === 'UPSTREAM'} type="button" onClick={() => highlight('UPSTREAM')}>Upstream</button>
        <button aria-pressed={directionContext === 'DOWNSTREAM'} type="button" onClick={() => highlight('DOWNSTREAM')}>Downstream</button>
        <button type="button" onClick={() => highlight('PATH')}>직접 관계</button>
        {onExpandNode && <button disabled={!selectedNode || busyAction} onClick={() => selectedNode && void performExpand(selectedNode.id, selectedDirection, 'CONTROL')} type="button">선택 2-level 확장</button>}
        {onCollapseNode && <button disabled={!selectedNode} onClick={collapseSelected} type="button">선택 접기</button>}
      </div>
      <div
        aria-label={`${ariaLabel} canvas. +, -, 0 키로 확대, 축소, 초기화할 수 있습니다.`}
        className="cy-read-graph-canvas"
        data-testid="cytoscape-read-graph-canvas"
        onKeyDown={keyboardControl}
        role="img"
        style={{ height }}
        tabIndex={0}
      >
        <div aria-hidden="true" className="cy-read-graph-canvas-host" ref={containerRef} />
        {loading && <div className="cy-read-graph-state" role="status">권한 필터링된 graph를 불러오는 중입니다.</div>}
        {!loading && visibleError && <div className="cy-read-graph-state cy-read-graph-error" role="alert">Graph query 또는 layout 실패: {visibleError}</div>}
        {!loading && !visibleError && graph.nodes.length === 0 && <div className="cy-read-graph-state" role="status"><strong>{emptyTitle}</strong><span>{emptyDescription}</span></div>}
      </div>
      <div className="cy-read-graph-status" aria-live="polite">
        <span>{graph.nodes.length} nodes · {graph.edges.length} edges</span>
        {boundNotice && <strong>{boundNotice}</strong>}
        {metrics && <span data-testid="cytoscape-metrics">transform {metrics.transform_ms.toFixed(1)}ms · layout {metrics.layout_ms.toFixed(1)}ms · usable {metrics.first_usable_render_ms.toFixed(1)}ms{metrics.last_settle_ms === undefined ? '' : ` · settle ${metrics.last_settle_ms.toFixed(1)}ms`}</span>}
        {searchNotice && <span>{searchNotice}</span>}
      </div>
      <div className="cy-read-graph-legend" aria-label="그래프 범례">
        <strong>범례</strong>
        {graph.kind === 'LINEAGE' && <><span data-shape="root">현재</span><span data-shape="upstream">Upstream</span><span data-shape="downstream">Downstream</span></>}
        {entityTypes.map((entityType) => <span key={entityType} data-shape="entity">{entityType}</span>)}
      </div>
      {graph.nodes.length > 0 && <details className="cy-read-graph-entity-list">
        <summary>접근 가능한 bounded entity 목록 · {graph.nodes.length}</summary>
        <ul>{graph.nodes.map((node) => <li key={node.id}>
          {onActivateNode && <button aria-label={`${node.label} 상세 열기`} onClick={() => onActivateNode(node.id)} type="button"><strong>{node.label}</strong><span>{node.entityType}</span></button>}
          <button aria-label={`${node.label}, ${node.entityType} 선택 · 근거 ${node.provenance.length}`} aria-pressed={node.id === internalSelectedId} onClick={() => selectNode(node.id)} type="button">선택</button>
          {onExpandNode && <>
            <button disabled={busyAction} onClick={() => void performExpand(node.id, 'UPSTREAM', 'CONTROL')} type="button">Upstream 2-level 확장</button>
            <button disabled={busyAction} onClick={() => void performExpand(node.id, 'DOWNSTREAM', 'CONTROL')} type="button">Downstream 2-level 확장</button>
          </>}
        </li>)}</ul>
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
