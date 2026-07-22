import { Maximize2, Minus, Move, Plus } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CatalogLineage } from '../../api/types'
import {
  layoutLineage,
  LINEAGE_CANVAS_PADDING,
  LINEAGE_NODE_HEIGHT,
  LINEAGE_NODE_WIDTH,
  LINEAGE_ROLE_LABELS,
} from './CatalogLineageLayout'

// A depth-limited lineage can still contain many siblings.  The initial fit
// must always favour the detail pane's viewport over the canvas's intrinsic
// size; users can zoom in afterwards to inspect individual nodes.
const MINIMUM_SCALE = 0.05
const MAXIMUM_SCALE = 2.25

export function CatalogLineageGraph({
  lineage,
  onSelectAsset,
}: {
  lineage: CatalogLineage
  onSelectAsset: (assetId: string) => void
}) {
  const layout = useMemo(() => layoutLineage(lineage), [lineage])
  const viewportRef = useRef<HTMLDivElement>(null)
  const interactionRef = useRef<{
    kind: 'PAN' | 'NODE'
    pointerId: number
    nodeId?: string
    element: HTMLElement
    startX: number
    startY: number
    startViewportX: number
    startViewportY: number
    startNodeX?: number
    startNodeY?: number
    moved: boolean
  } | undefined>(undefined)
  const suppressSelectionRef = useRef<string | undefined>(undefined)
  const [viewport, setViewport] = useState({ x: 0, y: 0, scale: 1 })
  const [nodeOffsets, setNodeOffsets] = useState<Record<string, { x: number; y: number }>>({})
  const [viewportBounds, setViewportBounds] = useState({ height: 0, width: 0 })
  const viewportStateRef = useRef(viewport)

  useEffect(() => { viewportStateRef.current = viewport }, [viewport])

  useEffect(() => {
    const element = viewportRef.current
    if (!element) return
    const updateBounds = () => {
      const rectangle = element.getBoundingClientRect()
      setViewportBounds({ height: Math.round(rectangle.height), width: Math.round(rectangle.width) })
    }
    updateBounds()
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(updateBounds)
    observer?.observe(element)
    window.addEventListener('resize', updateBounds)
    return () => { observer?.disconnect(); window.removeEventListener('resize', updateBounds) }
  }, [])

  const fittingScale = useMemo(() => {
    if (!viewportBounds.width || !viewportBounds.height) return 1
    const horizontal = (viewportBounds.width - LINEAGE_CANVAS_PADDING * 2) / layout.width
    const vertical = (viewportBounds.height - LINEAGE_CANVAS_PADDING * 2) / layout.height
    const fittedScale = Math.max(MINIMUM_SCALE, Math.min(1, horizontal, vertical))
    return Math.min(MAXIMUM_SCALE, fittedScale * 1.2)
  }, [layout.height, layout.width, viewportBounds.height, viewportBounds.width])

  const resetViewport = useCallback(() => {
    setViewport({ x: 0, y: 0, scale: fittingScale })
    setNodeOffsets({})
  }, [fittingScale])

  useEffect(() => {
    resetViewport()
  }, [lineage.center_asset_id, resetViewport])

  const nodes = useMemo(() => layout.nodes.map((node) => {
    const offset = nodeOffsets[node.asset.id]
    return offset ? { ...node, x: node.x + offset.x, y: node.y + offset.y } : node
  }), [layout.nodes, nodeOffsets])
  const byId = useMemo(() => new Map(nodes.map((node) => [node.asset.id, node])), [nodes])

  const setScaleAt = useCallback((nextScale: number, clientX?: number, clientY?: number) => {
    setViewport((current) => {
      const scale = Math.min(MAXIMUM_SCALE, Math.max(MINIMUM_SCALE, nextScale))
      if (scale === current.scale) return current
      const rectangle = viewportRef.current?.getBoundingClientRect()
      if (!rectangle || clientX === undefined || clientY === undefined) return { ...current, scale }
      const localX = clientX - rectangle.left
      const localY = clientY - rectangle.top
      const ratio = scale / current.scale
      return {
        scale,
        x: localX - (localX - current.x) * ratio,
        y: localY - (localY - current.y) * ratio,
      }
    })
  }, [])

  useEffect(() => {
    const element = viewportRef.current
    if (!element) return
    const zoomWithWheel = (event: WheelEvent) => {
      if (!event.ctrlKey) return
      event.preventDefault()
      const current = viewportStateRef.current
      setScaleAt(current.scale * (event.deltaY < 0 ? 1.12 : 1 / 1.12), event.clientX, event.clientY)
    }
    element.addEventListener('wheel', zoomWithWheel, { passive: false })
    return () => element.removeEventListener('wheel', zoomWithWheel)
  }, [setScaleAt])

  const startPan = (event: React.PointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest('.catalog-lineage-node, .catalog-lineage-controls')) return
    event.currentTarget.setPointerCapture?.(event.pointerId)
    interactionRef.current = {
      kind: 'PAN', pointerId: event.pointerId, element: event.currentTarget,
      startX: event.clientX, startY: event.clientY,
      startViewportX: viewport.x, startViewportY: viewport.y, moved: false,
    }
  }

  const startNodeDrag = (event: React.PointerEvent<HTMLElement>, nodeId: string) => {
    event.currentTarget.setPointerCapture?.(event.pointerId)
    interactionRef.current = {
      kind: 'NODE', pointerId: event.pointerId, nodeId, element: event.currentTarget,
      startX: event.clientX, startY: event.clientY,
      startViewportX: viewport.x, startViewportY: viewport.y,
      startNodeX: nodeOffsets[nodeId]?.x ?? 0, startNodeY: nodeOffsets[nodeId]?.y ?? 0,
      moved: false,
    }
  }

  const moveInteraction = (event: React.PointerEvent<HTMLDivElement>) => {
    const interaction = interactionRef.current
    if (!interaction || interaction.pointerId !== event.pointerId) return
    const deltaX = event.clientX - interaction.startX
    const deltaY = event.clientY - interaction.startY
    if (Math.abs(deltaX) > 3 || Math.abs(deltaY) > 3) interaction.moved = true
    if (interaction.kind === 'PAN') {
      setViewport((current) => ({ ...current, x: interaction.startViewportX + deltaX, y: interaction.startViewportY + deltaY }))
      return
    }
    if (!interaction.nodeId) return
    setNodeOffsets((current) => ({
      ...current,
      [interaction.nodeId as string]: {
        x: (interaction.startNodeX ?? 0) + deltaX / viewport.scale,
        y: (interaction.startNodeY ?? 0) + deltaY / viewport.scale,
      },
    }))
  }

  const endInteraction = (event: React.PointerEvent<HTMLDivElement>) => {
    const interaction = interactionRef.current
    if (!interaction || interaction.pointerId !== event.pointerId) return
    if (interaction.element.hasPointerCapture?.(event.pointerId)) interaction.element.releasePointerCapture?.(event.pointerId)
    if (interaction.kind === 'NODE' && interaction.moved && interaction.nodeId) suppressSelectionRef.current = interaction.nodeId
    interactionRef.current = undefined
  }

  return (
    <div className="catalog-lineage-graph" aria-label="권한 필터링된 DataHub Lineage 그래프">
      <div className="catalog-lineage-controls" aria-label="계보 그래프 조작">
        <span><Move size={13} />드래그 이동 · Ctrl + 휠 확대/축소</span>
        <div><button aria-label="계보 확대" onClick={() => setScaleAt(viewport.scale * 1.2)} type="button"><Plus size={13} /></button><button aria-label="계보 축소" onClick={() => setScaleAt(viewport.scale / 1.2)} type="button"><Minus size={13} /></button><button aria-label="계보 위치와 배율 초기화" onClick={resetViewport} type="button"><Maximize2 size={13} /></button></div>
      </div>
      <div
        className="catalog-lineage-viewport"
        onPointerCancel={endInteraction}
        onPointerDown={startPan}
        onPointerMove={moveInteraction}
        onPointerUp={endInteraction}
        ref={viewportRef}
      >
        <div className="catalog-lineage-world">
          <div className="catalog-lineage-stage" style={{ height: layout.height, transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.scale})`, width: layout.width }}>
          <div className="catalog-lineage-canvas" style={{ height: layout.height, width: layout.width }}>
            <svg aria-hidden="true" className="catalog-lineage-edges" viewBox={`0 0 ${layout.width} ${layout.height}`}>
              <defs>
                <marker id="catalog-lineage-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
                  <path d="M0,0 L7,3.5 L0,7 Z" />
                </marker>
              </defs>
              {lineage.edges.map((edge) => {
                const source = byId.get(edge.source_asset_id)
                const target = byId.get(edge.target_asset_id)
                if (!source || !target) return null
                const sourceAboveTarget = source.y <= target.y
                const fromX = source.x + LINEAGE_NODE_WIDTH / 2
                const fromY = source.y + (sourceAboveTarget ? LINEAGE_NODE_HEIGHT : 0)
                const toX = target.x + LINEAGE_NODE_WIDTH / 2
                const toY = target.y + (sourceAboveTarget ? 0 : LINEAGE_NODE_HEIGHT)
                const bend = Math.max(32, Math.abs(toY - fromY) / 2)
                const sourceControlY = fromY + (sourceAboveTarget ? bend : -bend)
                const targetControlY = toY + (sourceAboveTarget ? -bend : bend)
                return <path key={`${edge.source_asset_id}-${edge.target_asset_id}`} d={`M ${fromX} ${fromY} C ${fromX} ${sourceControlY}, ${toX} ${targetControlY}, ${toX} ${toY}`} markerEnd="url(#catalog-lineage-arrow)" />
              })}
            </svg>
            {nodes.map((node) => (
              <article
                className={`catalog-lineage-node catalog-lineage-node-${node.role.toLowerCase()}`}
                key={node.asset.id}
                onPointerDown={(event) => startNodeDrag(event, node.asset.id)}
                style={{ left: node.x, top: node.y, width: LINEAGE_NODE_WIDTH, minHeight: LINEAGE_NODE_HEIGHT }}
              >
                <button
                  aria-label={`${node.asset.name} 선택`}
                  className="catalog-lineage-node-select"
                  onClick={() => {
                    if (suppressSelectionRef.current === node.asset.id) { suppressSelectionRef.current = undefined; return }
                    onSelectAsset(node.asset.id)
                  }}
                  title={`${node.asset.name} 상세 정보 열기`}
                  type="button"
                >
                  <span className="catalog-lineage-node-role">{LINEAGE_ROLE_LABELS[node.role]}</span>
                  <strong>{node.asset.name}</strong>
                  <small>{node.asset.platform ?? 'platform 미지정'} · {node.asset.schema_name ?? node.asset.asset_type}</small>
                </button>
              </article>
            ))}
          </div>
        </div>
        </div>
      </div>
    </div>
  )
}
