import { useCallback, useState, type FormEvent } from 'react'
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
import { GitBranch, Plus, Trash2 } from 'lucide-react'

type LocalSchemaNode = Node<{ label: string }>

interface GraphBuilderScaffoldProps {
  busy: boolean
  lifecycleState?: 'DRAFT' | 'REVIEW' | 'PUBLISHED' | 'DISCARDED'
  onContinue: () => void
}

const nodeStyle = {
  width: 180,
  border: '1px solid #004b87',
  borderRadius: 4,
  background: '#ffffff',
  color: '#0a192f',
  padding: '10px 12px',
  fontSize: 12,
  fontWeight: 800,
  boxShadow: '0 2px 8px rgba(7, 20, 38, .10)',
}

function localNode(label: string, ordinal: number): LocalSchemaNode {
  return {
    id: `local:${crypto.randomUUID()}`,
    position: {
      x: 60 + (ordinal % 3) * 240,
      y: 70 + Math.floor(ordinal / 3) * 150,
    },
    data: { label },
    ariaLabel: `${label}, 로컬 테스트 노드`,
    style: nodeStyle,
  }
}

export function GraphBuilderScaffold({
  busy,
  lifecycleState = 'DRAFT',
  onContinue,
}: GraphBuilderScaffoldProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<LocalSchemaNode>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [label, setLabel] = useState('')
  const [selectedNodeId, setSelectedNodeId] = useState<string>()
  const locked = lifecycleState !== 'DRAFT'

  const addLocalNode = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const canonicalLabel = label.trim()
    if (!canonicalLabel || locked || busy) return
    setNodes((current) => [...current, localNode(canonicalLabel, current.length)])
    setLabel('')
  }

  const connectLocalNodes = useCallback((connection: Connection) => {
    if (locked || !connection.source || !connection.target) return
    setEdges((current) => addEdge({
      ...connection,
      id: `local-edge:${crypto.randomUUID()}`,
      markerEnd: { type: MarkerType.ArrowClosed, color: '#526274' },
      style: { stroke: '#526274', strokeWidth: 1.5 },
    }, current))
  }, [locked, setEdges])

  const deleteSelectedNode = () => {
    if (!selectedNodeId || locked || busy) return
    setNodes((current) => current.filter((node) => node.id !== selectedNodeId))
    setEdges((current) => current.filter(
      (edge) => edge.source !== selectedNodeId && edge.target !== selectedNodeId,
    ))
    setSelectedNodeId(undefined)
  }

  return (
    <section className="grid min-h-[620px] gap-4 xl:grid-cols-[260px_minmax(0,1fr)]">
      <aside className="rounded-enterprise border border-slate-300 bg-white p-4">
        <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">
          Step 2 · T-Box
        </span>
        <h2 className="my-2 text-lg font-black text-navy-900">Graph Builder</h2>
        <p className="m-0 text-xs leading-5 text-slate-500">
          수동 상호작용을 확인하는 로컬 캔버스입니다. 이 화면의 노드와 관계선은 typed
          operation이나 Accepted schema가 아니며 서버에 저장되지 않습니다.
        </p>

        <div className="mt-4 rounded-enterprise border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-950">
          <strong>Accepted T-Box · 0개</strong>
          <br />
          새로고침하거나 Studio를 나가면 로컬 테스트 요소가 사라집니다.
        </div>

        <form className="mt-4 grid gap-2" onSubmit={addLocalNode}>
          <label className="text-xs font-bold text-slate-700" htmlFor="local-tbox-node-label">
            로컬 테스트 노드 이름
          </label>
          <input
            id="local-tbox-node-label"
            className="input"
            value={label}
            maxLength={80}
            disabled={locked || busy}
            placeholder="예: 테스트 클래스"
            onChange={(event) => setLabel(event.target.value)}
          />
          <button
            type="submit"
            className="button justify-center"
            disabled={!label.trim() || locked || busy}
          >
            <Plus size={14} aria-hidden="true" />
            로컬 노드 추가
          </button>
        </form>

        <button
          type="button"
          className="button button-secondary mt-2 w-full justify-center"
          disabled={!selectedNodeId || locked || busy}
          onClick={deleteSelectedNode}
        >
          <Trash2 size={14} aria-hidden="true" />
          선택 노드 삭제
        </button>

        <dl className="mt-4 grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-enterprise bg-slate-100 p-2">
            <dt className="text-slate-500">로컬 노드</dt>
            <dd className="m-0 font-black text-navy-900">{nodes.length}개</dd>
          </div>
          <div className="rounded-enterprise bg-slate-100 p-2">
            <dt className="text-slate-500">로컬 관계선</dt>
            <dd className="m-0 font-black text-navy-900">{edges.length}개</dd>
          </div>
        </dl>

        {locked && (
          <p role="status" className="mt-4 rounded-enterprise border border-blue-200 bg-blue-50 p-3 text-xs leading-5 text-blue-950">
            Studio lifecycle이 {lifecycleState}이므로 로컬 캔버스도 읽기 전용입니다.
          </p>
        )}

        <button
          type="button"
          className="button mt-4 w-full justify-center"
          disabled={busy || locked}
          onClick={onContinue}
        >
          {busy ? '확인 중…' : '서버 Accepted T-Box 확인'}
        </button>
        <p className="mb-0 mt-2 text-[11px] leading-4 text-slate-500">
          서버에 Accepted operation이 없으면 Data Enricher 전환은 실패하며 현재 캔버스는
          그대로 정본이 되지 않습니다.
        </p>
      </aside>

      <div className="relative min-h-[620px] overflow-hidden rounded-enterprise border border-slate-300 bg-slate-50">
        <header className="absolute left-4 top-4 z-10 rounded-enterprise border border-slate-200 bg-white/95 px-3 py-2 shadow-sm">
          <div className="flex items-center gap-2 text-xs font-black text-navy-900">
            <GitBranch size={14} aria-hidden="true" />
            로컬 상호작용 캔버스
          </div>
          <p className="m-0 mt-1 text-[11px] text-slate-500">
            노드를 드래그하거나 핸들을 이어 관계선을 시험할 수 있습니다.
          </p>
        </header>
        {nodes.length === 0 && (
          <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center p-8 text-center">
            <div className="max-w-sm rounded-enterprise border border-dashed border-slate-300 bg-white/95 p-6">
              <h3 className="m-0 text-sm font-black text-navy-900">Accepted schema가 없습니다.</h3>
              <p className="mb-0 mt-2 text-xs leading-5 text-slate-500">
                왼쪽에서 이름을 입력해야만 로컬 테스트 노드가 생성됩니다.
              </p>
            </div>
          </div>
        )}
        <ReactFlow
          aria-label="T-Box 로컬 테스트 캔버스"
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={connectLocalNodes}
          onNodeClick={(_, node) => setSelectedNodeId(node.id)}
          onPaneClick={() => setSelectedNodeId(undefined)}
          nodesDraggable={!locked}
          nodesConnectable={!locked}
          elementsSelectable
          deleteKeyCode={null}
          fitView
          minZoom={0.25}
          maxZoom={2}
          colorMode="light"
        >
          <Background color="#cbd5e1" gap={18} size={1} />
          <Controls showInteractive={!locked} />
          {nodes.length > 0 && (
            <MiniMap pannable zoomable nodeColor="#004b87" maskColor="rgba(248,250,252,.72)" />
          )}
        </ReactFlow>
      </div>
    </section>
  )
}
