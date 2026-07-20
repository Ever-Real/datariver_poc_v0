import { useEffect, useMemo } from 'react'
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from '@xyflow/react'

export interface FlowCanvasNode {
  id: string
  label: string
  subtitle?: string
  kind?: 'source' | 'target' | 'neutral' | 'empty'
  x?: number
  y?: number
}

export interface FlowCanvasEdge {
  id: string
  source: string
  target: string
  label?: string
}

interface FlowCanvasProps {
  nodes: FlowCanvasNode[]
  edges: FlowCanvasEdge[]
  ariaLabel: string
  height?: number
  editable?: boolean
  locked?: boolean
  showMiniMap?: boolean
  emptyTitle?: string
  emptyDescription?: string
  onConnect?: (source: string, target: string) => void
  onNodeActivate?: (nodeId: string) => void
}

type CanvasNode = Node<{ label: string; subtitle?: string; kind: FlowCanvasNode['kind'] }>

const nodeColors: Record<NonNullable<FlowCanvasNode['kind']>, { background: string; border: string }> = {
  source: { background: '#e7f1f8', border: '#004b87' },
  target: { background: '#ecfdf5', border: '#047857' },
  neutral: { background: '#ffffff', border: '#64748b' },
  empty: { background: '#f8fafc', border: '#94a3b8' },
}

function mapNode(node: FlowCanvasNode, index: number): CanvasNode {
  const kind = node.kind ?? 'neutral'
  const color = nodeColors[kind]
  return {
    id: node.id,
    position: {
      x: node.x ?? 40 + (index % 4) * 220,
      y: node.y ?? 45 + Math.floor(index / 4) * 130,
    },
    data: { label: node.label, subtitle: node.subtitle, kind },
    style: {
      width: 180,
      border: `1px solid ${color.border}`,
      borderRadius: 4,
      background: color.background,
      color: '#0a192f',
      padding: '10px 12px',
      fontSize: 12,
      fontWeight: 800,
      boxShadow: '0 2px 8px rgba(7, 20, 38, .10)',
    },
    ariaLabel: node.subtitle ? `${node.label}, ${node.subtitle}` : node.label,
  }
}

function mapEdge(edge: FlowCanvasEdge): Edge {
  return {
    ...edge,
    markerEnd: { type: MarkerType.ArrowClosed, color: '#526274' },
    style: { stroke: '#526274', strokeWidth: 1.5 },
    labelStyle: { fill: '#334155', fontSize: 10, fontWeight: 700 },
  }
}

export function FlowCanvas({
  nodes: sourceNodes,
  edges: sourceEdges,
  ariaLabel,
  height = 420,
  editable = false,
  locked = false,
  showMiniMap = true,
  emptyTitle = '표시할 그래프 데이터가 없습니다.',
  emptyDescription = '소스 또는 에셋을 선택하면 실제 관계를 여기에 표시합니다.',
  onConnect,
  onNodeActivate,
}: FlowCanvasProps) {
  const visibleSourceNodes = useMemo<FlowCanvasNode[]>(() => sourceNodes.length > 0 ? sourceNodes : [{
    id: '__empty__',
    label: emptyTitle,
    subtitle: emptyDescription,
    kind: 'empty',
    x: 100,
    y: 110,
  }], [emptyDescription, emptyTitle, sourceNodes])
  const mappedNodes = useMemo(() => visibleSourceNodes.map(mapNode), [visibleSourceNodes])
  const mappedEdges = useMemo(() => sourceEdges.map(mapEdge), [sourceEdges])
  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>(mappedNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(mappedEdges)

  useEffect(() => setNodes(mappedNodes), [mappedNodes, setNodes])
  useEffect(() => setEdges(mappedEdges), [mappedEdges, setEdges])

  const connect = (connection: Connection) => {
    if (!editable || locked || !connection.source || !connection.target) return
    setEdges((current) => addEdge({
      ...connection,
      markerEnd: { type: MarkerType.ArrowClosed },
      id: `draft:${connection.source}:${connection.target}:${current.length}`,
    }, current))
    onConnect?.(connection.source, connection.target)
  }

  return (
    <section aria-label={ariaLabel} className="w-full overflow-hidden rounded-enterprise border border-slate-300 bg-slate-50" style={{ height }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={connect}
        onNodeClick={(_, node) => node.id !== '__empty__' && onNodeActivate?.(node.id)}
        nodesDraggable={!locked && sourceNodes.length > 0}
        nodesConnectable={editable && !locked && sourceNodes.length > 0}
        elementsSelectable={sourceNodes.length > 0}
        fitView
        minZoom={0.2}
        maxZoom={2}
        colorMode="light"
      >
        <Background color="#cbd5e1" gap={18} size={1} />
        <Controls showInteractive={editable} />
        {showMiniMap && sourceNodes.length > 0 && <MiniMap pannable zoomable nodeColor="#004b87" maskColor="rgba(248,250,252,.72)" />}
      </ReactFlow>
    </section>
  )
}
