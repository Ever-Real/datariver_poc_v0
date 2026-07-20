import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { BookOpen, CheckCircle2, CircleDot, GitBranch, Network, Plus, RefreshCw, Workflow } from 'lucide-react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type {
  KnowledgeChangeOperationCreate,
  KnowledgeChangeSet,
  KnowledgeChangeSetPublish,
  KnowledgeGraph,
  KnowledgeRelease,
  KnowledgeSnapshot,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { AccordionItem } from '../../components/common/Accordion'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { PageTitle } from '../../components/layout/PageTitle'

type KnowledgeTab = 'REGISTRY' | 'STUDIO' | 'GRAPH'

const tabs: Array<{ id: KnowledgeTab; label: string; description: string; icon: typeof BookOpen }> = [
  { id: 'REGISTRY', label: '지식 레지스트리', description: '그래프·릴리스·상태 이력', icon: BookOpen },
  { id: 'STUDIO', label: '변경 스튜디오', description: '검증 가능한 changeset 검토', icon: Workflow },
  { id: 'GRAPH', label: '그래프 탐색', description: '권한 범위의 bounded snapshot', icon: Network },
]

const graphTypes = ['CATALOG_MIRROR', 'CURATED_KNOWLEDGE', 'ANALYTIC_PRODUCT'] as const
const graphClassifications = ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'] as const

function delimitedValues(value: string): string[] {
  return [...new Set(value.split(',').map((item) => item.trim()).filter(Boolean))]
}

function stateClass(value: string) {
  return value.toLowerCase().replaceAll('_', '-')
}

function graphNodeLabel(properties: Record<string, unknown>, fallback: string): string {
  const candidate = properties.name ?? properties.display_name
  return typeof candidate === 'string' || typeof candidate === 'number' ? String(candidate) : fallback
}

function GraphCanvas({ snapshot }: { snapshot?: KnowledgeSnapshot }) {
  const layout = useMemo(() => {
    const nodes = snapshot?.nodes ?? []
    return nodes.map((node, index) => ({
      node,
      x: 36 + (index % 4) * 190,
      y: 34 + Math.floor(index / 4) * 132,
    }))
  }, [snapshot])
  const height = Math.max(310, Math.ceil(layout.length / 4) * 132 + 56)
  const nodeById = useMemo(() => new Map(layout.map((entry) => [entry.node.id, entry])), [layout])

  if (!snapshot) return <div className="knowledge-canvas-empty"><Network size={28} /><p>릴리스를 선택하면 권한 범위에서 허용된 그래프 snapshot을 표시합니다.</p></div>
  return <div className="knowledge-canvas" style={{ minHeight: height }} aria-label="지식 그래프 snapshot">
    <svg aria-hidden="true" viewBox={`0 0 820 ${height}`} preserveAspectRatio="none">
      {snapshot.edges.map((edge) => {
        const source = nodeById.get(edge.source_id)
        const target = nodeById.get(edge.target_id)
        if (!source || !target) return null
        return <line key={edge.id} x1={source.x + 138} y1={source.y + 40} x2={target.x} y2={target.y + 40} />
      })}
    </svg>
    {layout.map(({ node, x, y }) => <article className="knowledge-canvas-node" key={node.id} style={{ left: x, top: y }} title={node.id}>
      <span>{node.entity_type}</span><strong>{graphNodeLabel(node.properties, node.id)}</strong>
      <small>분류 {node.classification} · 근거 {node.provenance.length}</small>
    </article>)}
    {snapshot.filtered && <p className="knowledge-canvas-note">표시 가능한 노드만 포함된 bounded snapshot입니다.</p>}
  </div>
}

export function KnowledgePage({ client, onNavigate }: { client: ApiClient; onNavigate: (page: 'chat') => void }) {
  const [graphs, setGraphs] = useState<KnowledgeGraph[]>([])
  const [tab, setTab] = useState<KnowledgeTab>('REGISTRY')
  const [selectedGraphId, setSelectedGraphId] = useState<string>()
  const [selectedReleaseId, setSelectedReleaseId] = useState<string>()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [graphType, setGraphType] = useState<(typeof graphTypes)[number]>('CURATED_KNOWLEDGE')
  const [graphClassification, setGraphClassification] = useState<(typeof graphClassifications)[number]>('INTERNAL')
  const [entityTypes, setEntityTypes] = useState('')
  const [edgeTypes, setEdgeTypes] = useState('')
  const [changeTitle, setChangeTitle] = useState('')
  const [changesets, setChangesets] = useState<KnowledgeChangeSet[]>([])
  const [releases, setReleases] = useState<KnowledgeRelease[]>([])
  const [snapshot, setSnapshot] = useState<KnowledgeSnapshot>()
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>()

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const value = await client.request<KnowledgeGraph[]>('/knowledge/graphs')
      setGraphs(value)
      setSelectedGraphId((current) => current && value.some((graph) => graph.id === current) ? current : value[0]?.id)
    }
    catch (next) { setError(next) }
    finally { setLoading(false) }
  }, [client])
  useEffect(() => { void refresh() }, [refresh])

  const selectedGraph = graphs.find((graph) => graph.id === selectedGraphId)
  const refreshGraphDetail = useCallback(async (graphId: string) => {
    setDetailLoading(true); setError(undefined); setSnapshot(undefined)
    try {
      const [nextChangesets, nextReleases] = await Promise.all([
        client.request<KnowledgeChangeSet[]>(`/knowledge/graphs/${graphId}/changesets`),
        client.request<KnowledgeRelease[]>(`/knowledge/graphs/${graphId}/releases`),
      ])
      setChangesets(nextChangesets); setReleases(nextReleases)
      setSelectedReleaseId((current) => current && nextReleases.some((release) => release.id === current)
        ? current
        : selectedGraph?.active_release_id ?? nextReleases.at(-1)?.id)
    } catch (next) { setError(next); setChangesets([]); setReleases([]) }
    finally { setDetailLoading(false) }
  }, [client, selectedGraph?.active_release_id])

  useEffect(() => {
    if (!selectedGraphId) { setChangesets([]); setReleases([]); setSnapshot(undefined); return }
    void refreshGraphDetail(selectedGraphId)
  }, [refreshGraphDetail, selectedGraphId])

  useEffect(() => {
    if (!selectedGraphId || !selectedReleaseId || tab !== 'GRAPH') return
    const controller = new AbortController()
    setDetailLoading(true); setError(undefined)
    void client.request<KnowledgeSnapshot>(`/knowledge/graphs/${selectedGraphId}/releases/${selectedReleaseId}/snapshot?maximum_nodes=200`, { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) setSnapshot(value) })
      .catch((next: unknown) => { if (!controller.signal.aborted) setError(next) })
      .finally(() => { if (!controller.signal.aborted) setDetailLoading(false) })
    return () => controller.abort()
  }, [client, selectedGraphId, selectedReleaseId, tab])

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(undefined)
    const nextEntityTypes = delimitedValues(entityTypes)
    const nextEdgeTypes = delimitedValues(edgeTypes)
    if (!nextEntityTypes.length || !nextEdgeTypes.length) {
      setError(new Error('엔터티 유형과 관계 유형을 각각 하나 이상 입력하세요.'))
      return
    }
    try {
      await client.request<KnowledgeGraph>('/knowledge/graphs', {
        method: 'POST', idempotencyKey: newIdempotencyKey('graph-create'),
        body: JSON.stringify({
          slug, name, graph_type: graphType, classification: graphClassification,
          ontology: {
            entity_types: nextEntityTypes,
            edge_types: nextEdgeTypes,
          },
        }),
      })
      setName(''); setSlug(''); setEntityTypes(''); setEdgeTypes(''); await refresh(); setTab('REGISTRY')
    } catch (next) { setError(next) }
  }

  const createChangeset = async (event: FormEvent) => {
    event.preventDefault()
    if (!selectedGraphId || !changeTitle.trim()) return
    setBusy(true); setError(undefined)
    try {
      await client.request<KnowledgeChangeSet>(`/knowledge/graphs/${selectedGraphId}/changesets`, {
        method: 'POST', idempotencyKey: newIdempotencyKey('knowledge-changeset'), body: JSON.stringify({ title: changeTitle.trim() }),
      })
      setChangeTitle(''); await refreshGraphDetail(selectedGraphId)
    } catch (next) { setError(next) } finally { setBusy(false) }
  }

  const appendChangeOperation = async (
    changeset: KnowledgeChangeSet,
    operation: KnowledgeChangeOperationCreate,
  ) => {
    if (!selectedGraphId) return
    setBusy(true); setError(undefined)
    try {
      await client.request<KnowledgeChangeSet>(
        `/knowledge/graphs/${selectedGraphId}/changesets/${changeset.id}/operations`,
        {
          method: 'POST',
          ifMatch: `"${changeset.version}"`,
          body: JSON.stringify(operation),
        },
      )
      await refreshGraphDetail(selectedGraphId)
    } catch (next) { setError(next) } finally { setBusy(false) }
  }

  const transitionChangeset = async (changeset: KnowledgeChangeSet, operation: 'submit' | 'approve' | 'reject' | 'publish') => {
    if (!selectedGraphId) return
    setBusy(true); setError(undefined)
    try {
      const path = `/knowledge/graphs/${selectedGraphId}/changesets/${changeset.id}/${operation === 'approve' || operation === 'reject' ? 'reviews' : operation}`
      const options = operation === 'publish'
        ? { method: 'POST' as const, idempotencyKey: newIdempotencyKey('knowledge-publish') }
        : {
          method: 'POST' as const,
          ifMatch: `"${changeset.version}"`,
          body: operation === 'approve' || operation === 'reject'
            ? JSON.stringify({ decision: operation === 'approve' ? 'APPROVED' : 'REJECTED', reason: '화면에서 현재 evidence와 validation 결과를 검토했습니다.' })
            : undefined,
        }
      await client.request<KnowledgeChangeSet | KnowledgeChangeSetPublish>(path, options)
      await refreshGraphDetail(selectedGraphId)
    } catch (next) { setError(next) } finally { setBusy(false) }
  }

  const activateRelease = async (release: KnowledgeRelease) => {
    if (!selectedGraph) return
    setBusy(true); setError(undefined)
    try {
      await client.request<KnowledgeGraph>(`/knowledge/graphs/${selectedGraph.id}/releases/${release.id}/activate`, {
        method: 'POST', ifMatch: `"${selectedGraph.version}"`,
      })
      await refresh()
      await refreshGraphDetail(selectedGraph.id)
    } catch (next) { setError(next) } finally { setBusy(false) }
  }

  return (
    <section className="knowledge-page">
      <PageTitle icon="KG" eyebrow="Knowledge Asset Management" title="지식관리" description="v0.3 레지스트리·스튜디오·GraphRAG 작업 구조를 불변 release와 변경 검토 흐름으로 연결합니다." actions={<button className="button button-secondary" type="button" onClick={() => void refresh()} disabled={loading || busy}><RefreshCw size={13} />새로고침</button>} />
      <div className="knowledge-workspace">
        <aside className="knowledge-sidebar panel">
          <span className="eyebrow">Knowledge menu</span>
          <div role="tablist" aria-label="지식관리 작업 영역" className="knowledge-tabs">
            {tabs.map(({ id, label, description, icon: Icon }) => <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}><Icon size={15} /><span><b>{label}</b><small>{description}</small></span></button>)}
            <button type="button" onClick={() => onNavigate('chat')}><BookOpen size={15} /><span><b>지식 챗</b><small>권한·근거 기반 GraphRAG 질의</small></span></button>
          </div>
          <label className="knowledge-graph-select"><span>대상 그래프</span><select value={selectedGraphId ?? ''} onChange={(event) => setSelectedGraphId(event.target.value || undefined)} disabled={loading || graphs.length === 0}><option value="">그래프 선택</option>{graphs.map((graph) => <option key={graph.id} value={graph.id}>{graph.name} · v{graph.version}</option>)}</select></label>
          {selectedGraph && <dl className="knowledge-graph-facts"><div><dt>상태</dt><dd><span className={`badge knowledge-state-${stateClass(selectedGraph.status)}`}>{selectedGraph.status}</span></dd></div><div><dt>분류</dt><dd>{selectedGraph.classification}</dd></div><div><dt>활성 릴리스</dt><dd><code>{selectedGraph.active_release_id ?? '미발행'}</code></dd></div></dl>}
        </aside>
        <main className="knowledge-main panel">
          <ErrorNotice error={error} />
          {tab === 'REGISTRY' && <>
            <header className="knowledge-panel-header"><div><span className="eyebrow">Registry</span><h2>지식 그래프 레지스트리</h2></div><span>{loading ? '불러오는 중' : `${graphs.length} graphs`}</span></header>
            <form className="knowledge-create-form" onSubmit={(event) => void submit(event)}>
              <label>그래프 이름<input value={name} onChange={(event) => setName(event.target.value)} required maxLength={255} /></label>
              <label>Slug<input value={slug} onChange={(event) => setSlug(event.target.value.toLowerCase())} pattern="[a-z][a-z0-9-]{2,99}" required /></label>
              <label>그래프 유형<select value={graphType} onChange={(event) => setGraphType(event.target.value as typeof graphType)}>{graphTypes.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
              <label>분류<select value={graphClassification} onChange={(event) => setGraphClassification(event.target.value as typeof graphClassification)}>{graphClassifications.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
              <label>엔터티 유형<input onChange={(event) => setEntityTypes(event.target.value)} placeholder="쉼표로 구분" required value={entityTypes} /></label>
              <label>관계 유형<input onChange={(event) => setEdgeTypes(event.target.value)} placeholder="쉼표로 구분" required value={edgeTypes} /></label>
              <button className="button" disabled={busy}><Plus size={13} />그래프 생성</button>
            </form>
            <DenseDataTable caption="지식 그래프 레지스트리" columns={[
              { accessorKey: 'name', header: '그래프명', size: 240, cell: ({ row }) => <strong>{row.original.name}</strong> },
              { accessorKey: 'graph_type', header: '유형', size: 180 },
              { accessorKey: 'classification', header: '분류', size: 120, cell: ({ row }) => <span className="badge badge-soft">{row.original.classification}</span> },
              { accessorKey: 'status', header: '상태', size: 120, cell: ({ row }) => <span className={`badge knowledge-state-${stateClass(row.original.status)}`}>{row.original.status}</span> },
              { accessorKey: 'version', header: '버전', size: 80, cell: ({ row }) => `v${row.original.version}` },
              { id: 'release', header: '활성 릴리스', size: 320, cell: ({ row }) => <code>{row.original.active_release_id ?? '아직 발행 없음'}</code> },
            ]} data={graphs} getRowId={(graph) => graph.id} loading={loading} selectedRowId={selectedGraphId} onRowActivate={(graph) => { setSelectedGraphId(graph.id); setTab('STUDIO') }} />
          </>}
          {tab === 'STUDIO' && <>
            <header className="knowledge-panel-header"><div><span className="eyebrow">T-Box / A-Box studio</span><h2>{selectedGraph ? `${selectedGraph.name} 변경 스튜디오` : '그래프를 선택하세요'}</h2></div><span>{detailLoading ? '동기화 중' : `${changesets.length} changesets`}</span></header>
            {!selectedGraph ? <EmptyKnowledgeState icon={<GitBranch size={29} />} text="왼쪽에서 변경할 지식 그래프를 선택하세요." /> : <>
              <form className="knowledge-create-form knowledge-changeset-form" onSubmit={(event) => void createChangeset(event)}><label>변경 제목<input value={changeTitle} onChange={(event) => setChangeTitle(event.target.value)} placeholder="예: 공급업체 관계 검토" required maxLength={500} /></label><button className="button" disabled={busy}><Plus size={13} />Changeset 생성</button></form>
              <div className="knowledge-changesets">{changesets.length === 0 && <EmptyKnowledgeState icon={<Workflow size={29} />} text="작성된 changeset이 없습니다. 검토 가능한 변경 단위를 먼저 생성하세요." />}{changesets.map((changeset) => <ChangeSetCard key={changeset.id} changeset={changeset} busy={busy} onAppendOperation={appendChangeOperation} onTransition={transitionChangeset} />)}</div>
            </>}
          </>}
          {tab === 'GRAPH' && <>
            <header className="knowledge-panel-header"><div><span className="eyebrow">Bounded Graph viewer</span><h2>{selectedGraph ? `${selectedGraph.name} 릴리스 탐색` : '그래프를 선택하세요'}</h2></div><span>{snapshot ? `${snapshot.nodes.length} nodes · ${snapshot.edges.length} edges` : '릴리스 선택'}</span></header>
            {!selectedGraph ? <EmptyKnowledgeState icon={<Network size={29} />} text="왼쪽에서 그래프를 선택하면 발행된 릴리스를 탐색할 수 있습니다." /> : <>
              <div className="knowledge-release-toolbar"><label>발행 릴리스<select value={selectedReleaseId ?? ''} onChange={(event) => setSelectedReleaseId(event.target.value || undefined)}><option value="">릴리스 선택</option>{releases.map((release) => <option key={release.id} value={release.id}>v{release.release_no} · {release.node_count} nodes · {new Date(release.published_at).toLocaleString()}</option>)}</select></label><button className="button button-secondary" type="button" disabled={busy || !selectedReleaseId} onClick={() => { const release = releases.find((item) => item.id === selectedReleaseId); if (release) void activateRelease(release) }}><CheckCircle2 size={13} />활성 릴리스 전환</button></div>
              {detailLoading && !snapshot ? <EmptyKnowledgeState icon={<CircleDot size={29} />} text="권한 필터링된 snapshot을 불러오는 중입니다." /> : <GraphCanvas snapshot={snapshot} />}
              {snapshot && <section className="knowledge-snapshot-detail"><AccordionItem itemId="nodes" title="노드 상세" summary={`${snapshot.nodes.length} nodes`} expanded onToggle={() => undefined}><div className="knowledge-node-list">{snapshot.nodes.map((node) => <article key={node.id}><strong>{graphNodeLabel(node.properties, node.id)}</strong><span>{node.entity_type} · 근거 {node.provenance.length}</span><code>{node.id}</code></article>)}</div></AccordionItem></section>}
            </>}
          </>}
        </main>
      </div>
    </section>
  )
}

function EmptyKnowledgeState({ icon, text }: { icon: React.ReactNode; text: string }) {
  return <div className="knowledge-empty-state">{icon}<p>{text}</p></div>
}

function ChangeSetCard({
  changeset,
  busy,
  onAppendOperation,
  onTransition,
}: {
  changeset: KnowledgeChangeSet
  busy: boolean
  onAppendOperation: (
    changeset: KnowledgeChangeSet,
    operation: KnowledgeChangeOperationCreate,
  ) => Promise<void>
  onTransition: (changeset: KnowledgeChangeSet, operation: 'submit' | 'approve' | 'reject' | 'publish') => Promise<void>
}) {
  const [expanded, setExpanded] = useState(false)
  const [operation, setOperation] = useState<'UPSERT' | 'DELETE'>('UPSERT')
  const [entityKind, setEntityKind] = useState<'NODE' | 'EDGE'>('NODE')
  const [stableEntityId, setStableEntityId] = useState('')
  const [entityType, setEntityType] = useState('')
  const [edgeType, setEdgeType] = useState('')
  const [sourceId, setSourceId] = useState('')
  const [targetId, setTargetId] = useState('')
  const [name, setName] = useState('')
  const [classification, setClassification] = useState('1')
  const [sourceRef, setSourceRef] = useState('')
  const [sourceLocator, setSourceLocator] = useState('')
  const [sourceVersion, setSourceVersion] = useState('')
  const [method, setMethod] = useState('')
  const [confidence, setConfidence] = useState('1')
  const actions = changeset.state === 'DRAFT'
    ? [{ id: 'submit' as const, label: '검증 제출' }]
    : changeset.state === 'SUBMITTED' || changeset.state === 'IN_REVIEW'
      ? [{ id: 'approve' as const, label: '승인' }, { id: 'reject' as const, label: '반려' }]
      : changeset.state === 'APPROVED'
        ? [{ id: 'publish' as const, label: '릴리스 발행' }]
        : []
  const append = (event: FormEvent) => {
    event.preventDefault()
    const document = operation === 'DELETE'
      ? {}
      : entityKind === 'NODE'
        ? { entity_type: entityType, properties: { name }, classification: Number(classification) }
        : { source_id: sourceId, target_id: targetId, edge_type: edgeType, properties: { name }, classification: Number(classification) }
    void onAppendOperation(changeset, {
      sequence: Math.max(0, ...changeset.operations.map((item) => item.sequence)) + 1,
      operation,
      entity_kind: entityKind,
      stable_entity_id: stableEntityId,
      document,
      provenance: [{ source_ref: sourceRef, source_locator: sourceLocator, source_version: sourceVersion, method, confidence: Number(confidence) }],
      confidence: Number(confidence),
    })
  }
  return <article className="knowledge-changeset-card"><header><div><span className={`badge knowledge-state-${stateClass(changeset.state)}`}>{changeset.state}</span><h3>{changeset.title}</h3><small>v{changeset.version} · {new Date(changeset.updated_at).toLocaleString()}</small></div><div className="knowledge-card-actions">{actions.map((action) => <button key={action.id} className={action.id === 'reject' ? 'button button-secondary' : 'button'} type="button" disabled={busy} onClick={() => void onTransition(changeset, action.id)}>{action.label}</button>)}</div></header>{changeset.state === 'DRAFT' && <form className="knowledge-operation-form" onSubmit={append}><div className="knowledge-operation-heading"><strong>Typed 변경 작업</strong><small>raw JSON/Cypher 없이 증거가 있는 Node/Edge 변경만 추가합니다.</small></div><label>작업<select value={operation} onChange={(event) => setOperation(event.target.value as 'UPSERT' | 'DELETE')}><option value="UPSERT">UPSERT</option><option value="DELETE">DELETE</option></select></label><label>대상<select value={entityKind} onChange={(event) => setEntityKind(event.target.value as 'NODE' | 'EDGE')}><option value="NODE">NODE</option><option value="EDGE">EDGE</option></select></label><label>Stable UUID<input value={stableEntityId} onChange={(event) => setStableEntityId(event.target.value)} required /></label>{operation === 'UPSERT' && <>{entityKind === 'NODE' ? <label>Entity type<input value={entityType} onChange={(event) => setEntityType(event.target.value)} required /></label> : <><label>Source UUID<input value={sourceId} onChange={(event) => setSourceId(event.target.value)} required /></label><label>Target UUID<input value={targetId} onChange={(event) => setTargetId(event.target.value)} required /></label><label>Edge type<input value={edgeType} onChange={(event) => setEdgeType(event.target.value)} required /></label></>}<label>표시 이름<input value={name} onChange={(event) => setName(event.target.value)} required /></label><label>분류<select value={classification} onChange={(event) => setClassification(event.target.value)}><option value="0">PUBLIC</option><option value="1">INTERNAL</option><option value="2">CONFIDENTIAL</option><option value="3">RESTRICTED</option></select></label></>}<label>Source ref<input value={sourceRef} onChange={(event) => setSourceRef(event.target.value)} required /></label><label>Source locator<input value={sourceLocator} onChange={(event) => setSourceLocator(event.target.value)} required /></label><label>Source version<input value={sourceVersion} onChange={(event) => setSourceVersion(event.target.value)} required /></label><label>방법<input value={method} onChange={(event) => setMethod(event.target.value)} required /></label><label>신뢰도<input value={confidence} onChange={(event) => setConfidence(event.target.value)} min="0" max="1" step="0.01" type="number" required /></label><button className="button button-secondary" disabled={busy} type="submit">변경 작업 추가</button></form>}<button type="button" className="knowledge-detail-toggle" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>{expanded ? '세부 접기' : '작업·검증 세부 보기'}</button>{expanded && <dl className="knowledge-changeset-detail"><div><dt>작업</dt><dd>{changeset.operations.length}건</dd></div><div><dt>검증</dt><dd>{changeset.validations.length}건</dd></div><div><dt>기준 릴리스</dt><dd><code>{changeset.base_release_id ?? 'none'}</code></dd></div>{changeset.validations.map((validation) => <div className="knowledge-validation" key={validation.id}><dt>{validation.severity} · {validation.code}</dt><dd>{validation.message}</dd></div>)}</dl>}</article>
}
