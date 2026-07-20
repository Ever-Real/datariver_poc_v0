import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { Edit3, Network, Plus, Trash2 } from 'lucide-react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type { KnowledgeGraph, KnowledgeRelease, KnowledgeSnapshot } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { AccordionItem } from '../../components/common/Accordion'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import { FlowCanvas, type FlowCanvasEdge, type FlowCanvasNode } from '../../components/common/FlowCanvas'
import { GovernedUnavailable } from '../../components/common/GovernedUnavailable'

const graphTypes = ['CATALOG_MIRROR', 'CURATED_KNOWLEDGE', 'ANALYTIC_PRODUCT'] as const
const classifications = ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'] as const

function values(input: string): string[] {
  return Array.from(new Set(input.split(',').map((item) => item.trim()).filter(Boolean)))
}

function nodeLabel(properties: Record<string, unknown>, fallback: string): string {
  const candidate = properties.name ?? properties.display_name
  return typeof candidate === 'string' || typeof candidate === 'number' ? String(candidate) : fallback
}

export function KnowledgeRegistry({ client }: { client: ApiClient }) {
  const [graphs, setGraphs] = useState<KnowledgeGraph[]>([])
  const [selectedId, setSelectedId] = useState<string>()
  const [releases, setReleases] = useState<KnowledgeRelease[]>([])
  const [snapshot, setSnapshot] = useState<KnowledgeSnapshot>()
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<unknown>()
  const [addOpen, setAddOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [domain, setDomain] = useState<(typeof graphTypes)[number]>('CURATED_KNOWLEDGE')
  const [classification, setClassification] = useState<(typeof classifications)[number]>('INTERNAL')
  const [entityTypes, setEntityTypes] = useState('')
  const [edgeTypes, setEdgeTypes] = useState('')

  const refresh = useCallback(async () => {
    setLoading(true); setError(undefined)
    try {
      const result = await client.request<KnowledgeGraph[]>('/knowledge/graphs')
      setGraphs(result)
      setSelectedId((current) => current && result.some((graph) => graph.id === current) ? current : result[0]?.id)
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

  const createGraph = async (event: FormEvent) => {
    event.preventDefault()
    const entities = values(entityTypes)
    const edges = values(edgeTypes)
    if (!entities.length || !edges.length) {
      setError(new Error('엔터티 유형과 관계 유형을 각각 하나 이상 입력하세요.'))
      return
    }
    setBusy(true); setError(undefined)
    try {
      const graph = await client.request<KnowledgeGraph>('/knowledge/graphs', {
        method: 'POST',
        idempotencyKey: newIdempotencyKey('knowledge-asset-create'),
        body: JSON.stringify({
          name: name.trim(), slug: slug.trim(), graph_type: domain, classification,
          ontology: { entity_types: entities, edge_types: edges },
        }),
      })
      setName(''); setSlug(''); setEntityTypes(''); setEdgeTypes(''); setAddOpen(false)
      await refresh(); setSelectedId(graph.id)
    } catch (next) { setError(next) } finally { setBusy(false) }
  }

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
      <header className="mb-3 flex flex-wrap items-center justify-between gap-3"><div><span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Asset list</span><h2 className="my-1 text-lg font-black text-navy-900">지식 레지스트리</h2></div><button className="button" type="button" onClick={() => setAddOpen(true)}><Plus size={14} /> 에셋 추가</button></header>
      <ErrorNotice error={error} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <DenseDataTable caption="지식 에셋 목록" columns={columns} data={graphs} getRowId={(graph) => graph.id} loading={loading} selectedRowId={selectedId} onRowActivate={(graph) => setSelectedId(graph.id)} />
        <aside className="rounded-enterprise border border-slate-300 bg-slate-50 p-3">
          {!selected ? <div className="grid min-h-56 place-items-center text-center text-xs text-slate-500"><div><Network className="mx-auto mb-2" /><p>에셋을 선택하면 상세와 버전 이력을 표시합니다.</p></div></div> : <div className="grid gap-3">
            <dl className="grid grid-cols-2 gap-2 text-xs"><div><dt className="text-[10px] font-black text-slate-500">#ID</dt><dd className="m-0 truncate" title={selected.id}>{selected.id}</dd></div><div><dt className="text-[10px] font-black text-slate-500">Domain</dt><dd className="m-0">{selected.graph_type}</dd></div><div><dt className="text-[10px] font-black text-slate-500">Nodes</dt><dd className="m-0">{snapshot?.nodes.length ?? '—'}</dd></div><div><dt className="text-[10px] font-black text-slate-500">Edges</dt><dd className="m-0">{snapshot?.edges.length ?? '—'}</dd></div><div><dt className="text-[10px] font-black text-slate-500">Version</dt><dd className="m-0">v{selected.version}</dd></div><div><dt className="text-[10px] font-black text-slate-500">Status</dt><dd className="m-0">{selected.status}</dd></div></dl>
            <AccordionItem itemId="version-history" title="버전 이력" summary={`${releases.length} releases`} expanded onToggle={() => undefined}>{releases.length ? <ol className="m-0 grid gap-2 pl-5 text-xs">{[...releases].reverse().map((release) => <li key={release.id}><strong>Release v{release.release_no}</strong><br /><span>{release.node_count} nodes · {release.edge_count} edges</span><br /><time className="text-[10px] text-slate-500" dateTime={release.published_at}>{new Date(release.published_at).toLocaleString('ko-KR')}</time></li>)}</ol> : <p className="m-0 text-xs text-slate-500">발행된 릴리스가 없습니다.</p>}</AccordionItem>
            <AccordionItem itemId="graph-preview" title="그래프 미리보기" summary={detailLoading ? '불러오는 중' : snapshot ? `${snapshot.nodes.length} nodes` : '미발행'} expanded onToggle={() => undefined}><FlowCanvas ariaLabel="선택 에셋 그래프 미리보기" nodes={flowNodes} edges={flowEdges} height={330} showMiniMap={false} /></AccordionItem>
          </div>}
        </aside>
      </div>
    </section>

    <Dialog open={addOpen} title="지식 에셋 추가" description="서버가 온톨로지와 분류를 검증해 새 지식 그래프를 생성합니다." onRequestClose={() => { if (!busy) setAddOpen(false) }} footer={<><button type="button" className="button button-secondary" disabled={busy} onClick={() => setAddOpen(false)}>Cancel</button><button type="submit" form="knowledge-asset-form" className="button" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button></>}>
      <form id="knowledge-asset-form" className="grid gap-3" onSubmit={(event) => void createGraph(event)}>
        <label className="grid gap-1 text-xs font-bold">Name<input required maxLength={255} value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label className="grid gap-1 text-xs font-bold">Slug<input required pattern="[a-z][a-z0-9-]{2,99}" value={slug} onChange={(event) => setSlug(event.target.value.toLowerCase())} /></label>
        <label className="grid gap-1 text-xs font-bold">Domain · Graph type<select value={domain} onChange={(event) => setDomain(event.target.value as typeof domain)}>{graphTypes.map((value) => <option key={value}>{value}</option>)}</select></label>
        <label className="grid gap-1 text-xs font-bold">Security classification<select value={classification} onChange={(event) => setClassification(event.target.value as typeof classification)}>{classifications.map((value) => <option key={value}>{value}</option>)}</select></label>
        <label className="grid gap-1 text-xs font-bold">Status<input readOnly value="서버 관리" /></label>
        <label className="grid gap-1 text-xs font-bold">Entity types · 쉼표 구분<input required value={entityTypes} onChange={(event) => setEntityTypes(event.target.value)} /></label>
        <label className="grid gap-1 text-xs font-bold">Edge types · 쉼표 구분<input required value={edgeTypes} onChange={(event) => setEdgeTypes(event.target.value)} /></label>
        <GovernedUnavailable compact title="상태는 직접 지정하지 않습니다" description="상태와 버전은 서버의 changeset/release 워크플로가 관리합니다." />
      </form>
    </Dialog>
  </div>
}
