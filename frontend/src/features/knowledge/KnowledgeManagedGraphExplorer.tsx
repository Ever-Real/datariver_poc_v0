import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ApiClient } from '../../api/client'
import type { KnowledgeSnapshot } from '../../api/types'
import { CytoscapeReadGraph, type CytoscapeGraphMetrics } from '../../components/graph/CytoscapeReadGraph'
import {
  knowledgeSnapshotToReadGraph,
  mergeReadGraphs,
  type ReadGraphKind,
  type ReadGraphModel,
} from '../../components/graph/CytoscapeGraphAdapter'

const INITIAL_NODE_LIMIT = 48
const INITIAL_EDGE_LIMIT = 96
const MAXIMUM_MERGED_NODES = 160
const MAXIMUM_MERGED_EDGES = 320

function graphKind(graphType: string): ReadGraphKind {
  const normalized = graphType.toLocaleUpperCase()
  if (normalized.includes('LINEAGE') || normalized.includes('CATALOG_MIRROR')) return 'LINEAGE'
  if (normalized.includes('METADATA_MASTER') || normalized.includes('CURATED_KNOWLEDGE')) return 'METADATA_MASTER'
  return 'SEMANTIC'
}

function snapshotPath(
  graphId: string,
  releaseId: string,
  options: {
    depth: number
    rootNodeId?: string
    focusQuery?: string
    nodeTypes: string[]
    edgeTypes: string[]
  },
) {
  const parameters = new URLSearchParams({
    maximum_nodes: String(INITIAL_NODE_LIMIT),
    maximum_edges: String(INITIAL_EDGE_LIMIT),
    maximum_hops: String(options.depth),
  })
  if (options.rootNodeId) parameters.set('root_node_id', options.rootNodeId)
  if (options.focusQuery) parameters.set('focus_query', options.focusQuery)
  options.nodeTypes.forEach((value) => parameters.append('node_type', value))
  options.edgeTypes.forEach((value) => parameters.append('edge_type', value))
  return `/knowledge/graphs/${graphId}/releases/${releaseId}/snapshot?${parameters}`
}

function toggle(values: string[], value: string) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value]
}

export function KnowledgeManagedGraphExplorer({
  client,
  graphId,
  releaseId,
  graphType,
}: {
  client: ApiClient
  graphId: string
  releaseId: string
  graphType: string
}) {
  const kind = graphKind(graphType)
  const [base, setBase] = useState<KnowledgeSnapshot>()
  const [expansions, setExpansions] = useState<Record<string, KnowledgeSnapshot>>({})
  const [depth, setDepth] = useState(1)
  const [nodeTypes, setNodeTypes] = useState<string[]>([])
  const [edgeTypes, setEdgeTypes] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [requestMs, setRequestMs] = useState<number>()
  const [metrics, setMetrics] = useState<CytoscapeGraphMetrics>()
  const mountedRef = useRef(true)
  const pendingControllersRef = useRef(new Set<AbortController>())

  useEffect(() => {
    const pendingControllers = pendingControllersRef.current
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      pendingControllers.forEach((controller) => controller.abort())
      pendingControllers.clear()
    }
  }, [])

  const requestSnapshot = useCallback(async (options: {
    rootNodeId?: string
    focusQuery?: string
    requestDepth?: number
  } = {}) => {
    const started = performance.now()
    const controller = new AbortController()
    pendingControllersRef.current.add(controller)
    try {
      const result = await client.request<KnowledgeSnapshot>(snapshotPath(graphId, releaseId, {
        depth: options.requestDepth ?? depth,
        rootNodeId: options.rootNodeId,
        focusQuery: options.focusQuery,
        nodeTypes,
        edgeTypes,
      }), { cache: 'no-store', signal: controller.signal })
      if (controller.signal.aborted || !mountedRef.current) throw new DOMException('Managed graph request aborted.', 'AbortError')
      setRequestMs(performance.now() - started)
      return result
    } finally {
      pendingControllersRef.current.delete(controller)
    }
  }, [client, depth, edgeTypes, graphId, nodeTypes, releaseId])

  useEffect(() => {
    const pendingControllers = pendingControllersRef.current
    pendingControllers.forEach((pending) => pending.abort())
    pendingControllers.clear()
    const controller = new AbortController()
    setLoading(true)
    setErrorMessage('')
    setNotice('')
    setExpansions({})
    const started = performance.now()
    void client.request<KnowledgeSnapshot>(snapshotPath(graphId, releaseId, {
      depth,
      nodeTypes,
      edgeTypes,
    }), { cache: 'no-store', signal: controller.signal })
      .then((snapshot) => {
        if (controller.signal.aborted) return
        setBase(snapshot)
        setRequestMs(performance.now() - started)
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setBase(undefined)
          setErrorMessage(error instanceof Error ? error.message : 'Managed graph query에 실패했습니다.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => {
      controller.abort()
      pendingControllers.forEach((pending) => pending.abort())
      pendingControllers.clear()
    }
  }, [client, depth, edgeTypes, graphId, nodeTypes, releaseId])

  const graph = useMemo(() => {
    const empty: ReadGraphModel = { kind, nodes: [], edges: [] }
    if (!base) return empty
    const rootId = base.bounds?.root_node_id
    const initial = knowledgeSnapshotToReadGraph(base, kind, rootId)
    return mergeReadGraphs(initial, Object.values(expansions).map((snapshot) => (
      knowledgeSnapshotToReadGraph(snapshot, kind, snapshot.bounds?.root_node_id)
    )))
  }, [base, expansions, kind])

  const expand = async (nodeId: string) => {
    if (expansions[nodeId]) {
      setNotice('선택한 entity의 bounded neighborhood가 이미 열려 있습니다.')
      return
    }
    const snapshot = await requestSnapshot({ rootNodeId: nodeId, requestDepth: 1 })
    if (!mountedRef.current) return
    const candidate = mergeReadGraphs(graph, [knowledgeSnapshotToReadGraph(snapshot, kind, nodeId)])
    if (candidate.nodes.length > MAXIMUM_MERGED_NODES || candidate.edges.length > MAXIMUM_MERGED_EDGES) {
      setNotice(`현재 view 한도 ${MAXIMUM_MERGED_NODES} nodes / ${MAXIMUM_MERGED_EDGES} edges에 도달했습니다. 일부 관계를 임의로 자르지 않고 확장을 중단했습니다.`)
      return
    }
    setExpansions((current) => ({ ...current, [nodeId]: snapshot }))
    setNotice(`${snapshot.nodes.length} nodes / ${snapshot.edges.length} edges를 권한 범위에서 확장했습니다.`)
  }

  const collapse = (nodeId: string) => {
    setExpansions((current) => {
      if (!current[nodeId]) return current
      const next = { ...current }
      delete next[nodeId]
      return next
    })
    setNotice('선택한 entity의 확장 neighborhood를 접었습니다.')
  }

  const resolveSearch = async (query: string) => {
    try {
      const snapshot = await requestSnapshot({ focusQuery: query })
      if (!mountedRef.current) return undefined
      setBase(snapshot)
      setExpansions({})
      setErrorMessage('')
      setNotice('검색한 authorized entity를 새 bounded root로 열었습니다.')
      return snapshot.bounds?.root_node_id
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return undefined
      if (!mountedRef.current) return undefined
      setNotice('권한 범위에서 일치하는 graph entity를 찾지 못했습니다.')
      return undefined
    }
  }

  const bounds = base?.bounds
  const boundNotice = bounds
    ? `Showing ${graph.nodes.length} / ${bounds.total_authorized_nodes} authorized nodes · ${graph.edges.length} / ${bounds.total_authorized_edges} edges`
    : undefined

  return (
    <section className="grid gap-2" aria-label="Managed graph bounded explorer">
      <div className="flex flex-wrap items-end gap-2 rounded-enterprise border border-slate-200 bg-slate-50 p-2 text-[10px]">
        <label className="grid gap-1 font-black text-navy-900">Depth
          <select aria-label="그래프 조회 depth" className="border border-slate-300 bg-white px-2 py-1 font-normal" value={depth} onChange={(event) => setDepth(Number(event.target.value))}>
            <option value={1}>1-hop</option>
            <option value={2}>2-hop</option>
            <option value={3}>3-hop</option>
          </select>
        </label>
        <div className="grid gap-1"><strong className="text-navy-900">Node type filter</strong><div className="flex flex-wrap gap-1">
          {(bounds?.available_node_types ?? []).map((value) => <button aria-pressed={nodeTypes.includes(value)} className={nodeTypes.includes(value) ? 'button px-2 py-1 text-[9px]' : 'button button-secondary px-2 py-1 text-[9px]'} key={value} onClick={() => setNodeTypes((current) => toggle(current, value))} type="button">{value}</button>)}
        </div></div>
        <div className="grid gap-1"><strong className="text-navy-900">Relation filter</strong><div className="flex flex-wrap gap-1">
          {(bounds?.available_edge_types ?? []).map((value) => <button aria-pressed={edgeTypes.includes(value)} className={edgeTypes.includes(value) ? 'button px-2 py-1 text-[9px]' : 'button button-secondary px-2 py-1 text-[9px]'} key={value} onClick={() => setEdgeTypes((current) => toggle(current, value))} type="button">{value}</button>)}
        </div></div>
        {(nodeTypes.length > 0 || edgeTypes.length > 0) && <button className="button button-secondary px-2 py-1 text-[9px]" onClick={() => { setNodeTypes([]); setEdgeTypes([]) }} type="button">필터 전체 해제</button>}
      </div>
      <CytoscapeReadGraph
        ariaLabel={`${graphType} managed graph visualization`}
        boundNotice={boundNotice}
        emptyDescription="선택한 type/relation filter에 일치하는 authorized entity가 없습니다."
        emptyTitle="조회 가능한 bounded graph가 없습니다."
        errorMessage={errorMessage}
        graph={graph}
        height={440}
        loading={loading}
        onCollapseNode={collapse}
        onExpandNode={expand}
        onMetrics={setMetrics}
        onReset={() => setExpansions({})}
        onResolveSearch={resolveSearch}
        selectedElementId={base?.bounds?.root_node_id}
      />
      <div className="flex flex-wrap gap-2 text-[9px] text-slate-500" aria-live="polite">
        {requestMs !== undefined && <span>request {requestMs.toFixed(1)}ms</span>}
        {metrics && <span>transform {metrics.transform_ms.toFixed(1)}ms · layout {metrics.layout_ms.toFixed(1)}ms · usable {metrics.first_usable_render_ms.toFixed(1)}ms</span>}
        {notice && <strong className="text-amber-800">{notice}</strong>}
      </div>
    </section>
  )
}
