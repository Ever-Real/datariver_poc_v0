import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { Edit3, Network, Plus, Trash2, X } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { KnowledgeGraph, KnowledgeRelease, KnowledgeSnapshot } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { AccordionItem } from '../../components/common/Accordion'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { FlowCanvas, type FlowCanvasEdge, type FlowCanvasNode } from '../../components/common/FlowCanvas'

function nodeLabel(properties: Record<string, unknown>, fallback: string): string {
  const candidate = properties.name ?? properties.display_name
  return typeof candidate === 'string' || typeof candidate === 'number' ? String(candidate) : fallback
}

export function KnowledgeRegistry({
  client,
  onCreate,
}: {
  client: ApiClient
  onCreate: () => void
}) {
  const [graphs, setGraphs] = useState<KnowledgeGraph[]>([])
  const [selectedId, setSelectedId] = useState<string>()
  const [releases, setReleases] = useState<KnowledgeRelease[]>([])
  const [snapshot, setSnapshot] = useState<KnowledgeSnapshot>()
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<unknown>()

  const refresh = useCallback(async () => {
    setLoading(true); setError(undefined)
    try {
      const result = await client.request<KnowledgeGraph[]>('/knowledge/graphs')
      setGraphs(result)
      setSelectedId((current) => (
        current && result.some((graph) => graph.id === current) ? current : undefined
      ))
    } catch (next) { setError(next) } finally { setLoading(false) }
  }, [client])
  useEffect(() => { void refresh() }, [refresh])

  const selected = graphs.find((graph) => graph.id === selectedId)
  useEffect(() => {
    if (!selected) { setReleases([]); setSnapshot(undefined); return }
    const controller = new AbortController()
    setDetailLoading(true); setError(undefined); setSnapshot(undefined)
    void client.request<KnowledgeRelease[]>(`/knowledge/graphs/${selected.id}/releases`, { signal: controller.signal })
      .then(async (nextReleases) => {
        if (controller.signal.aborted) return
        setReleases(nextReleases)
        const releaseId = selected.active_release_id ?? nextReleases.at(-1)?.id
        if (!releaseId) return
        const nextSnapshot = await client.request<KnowledgeSnapshot>(
          `/knowledge/graphs/${selected.id}/releases/${releaseId}/snapshot?maximum_nodes=200`,
          { signal: controller.signal },
        )
        if (!controller.signal.aborted) setSnapshot(nextSnapshot)
      })
      .catch((next) => { if (!controller.signal.aborted) setError(next) })
      .finally(() => { if (!controller.signal.aborted) setDetailLoading(false) })
    return () => controller.abort()
  }, [client, selected])

  const flowNodes = useMemo<FlowCanvasNode[]>(() => (snapshot?.nodes ?? []).map((node) => ({
    id: node.id,
    label: nodeLabel(node.properties, node.id),
    subtitle: `${node.entity_type} · 근거 ${node.provenance.length}`,
    kind: 'neutral',
  })), [snapshot])
  const flowEdges = useMemo<FlowCanvasEdge[]>(() => (snapshot?.edges ?? []).map((edge) => ({
    id: edge.id, source: edge.source_id, target: edge.target_id, label: edge.edge_type,
  })), [snapshot])

  const columns = useMemo<ColumnDef<KnowledgeGraph>[]>(() => [
    { accessorKey: 'id', header: 'ID', size: 250, enableSorting: false, cell: ({ row }) => <code className="text-[10px]">{row.original.id}</code> },
    { accessorKey: 'name', header: 'Name', size: 220, cell: ({ row }) => <strong>{row.original.name}</strong> },
    { accessorKey: 'graph_type', header: 'Domain', size: 170 },
    { accessorKey: 'status', header: 'Status', size: 110, cell: ({ row }) => <span className="badge badge-soft">{row.original.status}</span> },
    { accessorKey: 'version', header: 'Version', size: 80, cell: ({ row }) => `v${row.original.version}` },
    { id: 'actions', header: 'Actions', size: 120, enableSorting: false, cell: () => <div className="flex gap-1"><button type="button" className="button button-secondary" disabled title="지식 에셋 수정 API가 아직 없습니다." aria-label="에셋 편집"><Edit3 size={13} /></button><button type="button" className="button button-secondary" disabled title="불변 릴리스 보존 정책에 맞는 삭제 API가 아직 없습니다." aria-label="에셋 삭제"><Trash2 size={13} /></button></div> },
  ], [])

  return <div className="grid gap-4">
    <div className="grid gap-2 sm:grid-cols-3">
      {[['오늘 추가된 노드', '집계 API 미제공'], ['오늘 추가된 관계', '집계 API 미제공'], ['수행된 적재 작업', '작업 API 미제공']].map(([label, value]) => <article key={label} className="rounded-enterprise border border-slate-300 bg-white px-4 py-3 shadow-sm"><span className="block text-[10px] font-black tracking-wide text-slate-500 uppercase">{label}</span><strong className="mt-1 block text-sm text-navy-900">— <small className="font-normal text-slate-500">{value}</small></strong></article>)}
    </div>
    <section className="rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
      <header className="mb-3 flex flex-wrap items-center justify-between gap-3"><div><span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Asset list</span><h2 className="my-1 text-lg font-black text-navy-900">지식 레지스트리</h2></div><button className="button" type="button" onClick={onCreate}><Plus size={14} /> 에셋 추가</button></header>
      <ErrorNotice error={error} />
      <div className="grid gap-4">
        <DenseDataTable caption="지식 에셋 목록" columns={columns} data={graphs} getRowId={(graph) => graph.id} loading={loading} selectedRowId={selectedId} onRowActivate={(graph) => setSelectedId(graph.id)} />
        {!selected && <div className="grid min-h-36 place-items-center rounded-enterprise border border-dashed border-slate-300 bg-slate-50 text-center text-xs text-slate-500"><div><Network className="mx-auto mb-2" /><p>에셋을 선택하면 우측 상세 패널을 엽니다.</p></div></div>}
      </div>
    </section>

    {selected && <>
      <div className="fixed inset-0 z-40 bg-navy-950/35" aria-hidden="true" onClick={() => setSelectedId(undefined)} />
      <aside
        className="fixed right-3 top-[68px] bottom-3 z-50 w-[min(1080px,calc(100vw-312px))] min-w-[440px] overflow-y-auto rounded-enterprise border border-slate-400 bg-white p-5 shadow-2xl max-xl:w-[calc(100vw-24px)] max-xl:min-w-0"
        aria-label={`${selected.name} 지식 에셋 상세`}
      >
        <header className="mb-4 flex items-start justify-between gap-3 border-b border-slate-200 pb-4">
          <div className="min-w-0">
            <span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Authorized asset detail</span>
            <h2 className="my-1 truncate text-xl font-black text-navy-900">{selected.name}</h2>
            <p className="m-0 truncate text-xs text-slate-500">{selected.id}</p>
          </div>
          <button type="button" className="button button-secondary" aria-label="에셋 상세 닫기" onClick={() => setSelectedId(undefined)}>
            <X size={15} />
          </button>
        </header>
        <div className="grid gap-4">
          <dl className="grid grid-cols-2 gap-3 rounded-enterprise border border-slate-200 bg-slate-50 p-4 text-xs md:grid-cols-3">
            <div><dt className="text-[10px] font-black text-slate-500">Graph type</dt><dd className="m-0">{selected.graph_type}</dd></div>
            <div><dt className="text-[10px] font-black text-slate-500">Nodes</dt><dd className="m-0">{snapshot?.nodes.length ?? '—'}</dd></div>
            <div><dt className="text-[10px] font-black text-slate-500">Edges</dt><dd className="m-0">{snapshot?.edges.length ?? '—'}</dd></div>
            <div><dt className="text-[10px] font-black text-slate-500">Version</dt><dd className="m-0">v{selected.version}</dd></div>
            <div><dt className="text-[10px] font-black text-slate-500">Status</dt><dd className="m-0">{selected.status}</dd></div>
            <div><dt className="text-[10px] font-black text-slate-500">Classification</dt><dd className="m-0">{selected.classification}</dd></div>
          </dl>
          <AccordionItem itemId="version-history" title="버전 이력" summary={`${releases.length} releases`} expanded onToggle={() => undefined}>{releases.length ? <ol className="m-0 grid gap-2 pl-5 text-xs">{[...releases].reverse().map((release) => <li key={release.id}><strong>Release v{release.release_no}</strong><br /><span>{release.node_count} nodes · {release.edge_count} edges</span><br /><time className="text-[10px] text-slate-500" dateTime={release.published_at}>{new Date(release.published_at).toLocaleString('ko-KR')}</time></li>)}</ol> : <p className="m-0 text-xs text-slate-500">발행된 릴리스가 없습니다.</p>}</AccordionItem>
          <AccordionItem itemId="graph-preview" title="그래프 미리보기" summary={detailLoading ? '불러오는 중' : snapshot ? `${snapshot.nodes.length} nodes` : '미발행'} expanded onToggle={() => undefined}><FlowCanvas ariaLabel="선택 에셋 그래프 미리보기" nodes={flowNodes} edges={flowEdges} height={520} showMiniMap /></AccordionItem>
          <AccordionItem itemId="ingestion-history" title="Ingestion 기록과 연결 Source" summary="read API 연결 전" expanded={false} onToggle={() => undefined}><p className="m-0 text-xs text-slate-500">Version-pinned binding/run summary API가 연결된 뒤 표시합니다.</p></AccordionItem>
          <AccordionItem itemId="typed-api" title="Endpoint API" summary="capability 확인 필요" expanded={false} onToggle={() => undefined}><p className="m-0 text-xs text-slate-500">서버가 허용한 상대 경로만 표시하며 provider URL, credential 또는 Bolt 주소는 노출하지 않습니다.</p></AccordionItem>
        </div>
      </aside>
    </>}
  </div>
}
