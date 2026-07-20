import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { FileUp, Lock, Plus, Search, Sparkles, Unlock, Workflow } from 'lucide-react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type { KnowledgeChangeOperationCreate, KnowledgeChangeSet, KnowledgeChangeSetPublish, KnowledgeGraph } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { FlowCanvas, type FlowCanvasEdge, type FlowCanvasNode } from '../../components/common/FlowCanvas'
import { GovernedUnavailable } from '../../components/common/GovernedUnavailable'
import { formatSafeCypherDraft, parseSafeCypherDraft } from './knowledgeCypherDraft'
import { KnowledgeSourceUpload } from './KnowledgeSourceUpload'

type Mode = 'A' | 'B'
type SourceTab = 'FILE' | 'DB'
type ModeATab = 'SOURCE' | 'DIRECT'
type DirectTab = 'CYPHER' | 'VISUAL'
type ModeBOption = 'EXISTING' | 'DYNAMIC'

interface DraftNode {
  id: string
  label: string
}

interface DraftEdge {
  id: string
  source: string
  target: string
  relation: string
}

function SourceConnection({ sourceTab, onSourceTab }: { sourceTab: SourceTab; onSourceTab: (tab: SourceTab) => void }) {
  const [intent, setIntent] = useState('')
  const [dbQuery, setDbQuery] = useState('')
  return <section className="grid gap-3 rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
    <div className="flex gap-2 border-b border-slate-200 pb-2" role="tablist" aria-label="데이터 소스 연결">
      <button type="button" role="tab" aria-selected={sourceTab === 'FILE'} className={`button ${sourceTab === 'FILE' ? '' : 'button-secondary'}`} onClick={() => onSourceTab('FILE')}>파일 업로드</button>
      <button type="button" role="tab" aria-selected={sourceTab === 'DB'} className={`button ${sourceTab === 'DB' ? '' : 'button-secondary'}`} onClick={() => onSourceTab('DB')}>DB 스키마</button>
    </div>
    {sourceTab === 'FILE' ? <>
      <label className="grid min-h-36 place-items-center rounded-enterprise border border-dashed border-enterprise-blue bg-blue-50 p-5 text-center text-xs font-bold text-enterprise-blue"><span><FileUp className="mx-auto mb-2" />파일을 드래그하거나 클릭하세요.<small className="mt-1 block font-normal text-slate-500">PDF, CSV, MD 등 · 현재는 선택만 가능</small></span><input className="sr-only" type="file" multiple accept=".pdf,.csv,.md,.txt" /></label>
      <label className="grid gap-1 text-xs font-black text-navy-900">추가 의도 · 옵션<textarea className="min-h-24 resize-y border border-slate-300 p-3 font-normal" value={intent} onChange={(event) => setIntent(event.target.value)} placeholder="예: 제조 공정과 관련된 장비, 자재, 레시피 위주로 노드를 추출해줘." /></label>
    </> : <label className="grid gap-1 text-xs font-black text-navy-900">DB 스키마 검색<div className="flex items-center gap-2 border border-slate-300 bg-white px-3"><Search size={14} /><input className="min-w-0 flex-1 border-0 py-2" value={dbQuery} onChange={(event) => setDbQuery(event.target.value)} placeholder="연결된 카탈로그 스키마 키워드" /></div><small className="font-normal text-slate-500">자동 추천·스키마 선택 계약은 아직 제공되지 않습니다.</small></label>}
  </section>
}

export function KnowledgeIngestionStudio({ client }: { client: ApiClient }) {
  const [mode, setMode] = useState<Mode>('A')
  const [modeATab, setModeATab] = useState<ModeATab>('SOURCE')
  const [sourceTab, setSourceTab] = useState<SourceTab>('FILE')
  const [directTab, setDirectTab] = useState<DirectTab>('VISUAL')
  const [modeBOption, setModeBOption] = useState<ModeBOption>('EXISTING')
  const [graphs, setGraphs] = useState<KnowledgeGraph[]>([])
  const [selectedGraphId, setSelectedGraphId] = useState('')
  const [changesets, setChangesets] = useState<KnowledgeChangeSet[]>([])
  const [selectedChangesetId, setSelectedChangesetId] = useState('')
  const [changeTitle, setChangeTitle] = useState('')
  const [reviewReason, setReviewReason] = useState('')
  const [nodeLabel, setNodeLabel] = useState('')
  const [relation, setRelation] = useState('RELATED_TO')
  const [draftNodes, setDraftNodes] = useState<DraftNode[]>([])
  const [draftEdges, setDraftEdges] = useState<DraftEdge[]>([])
  const [locked, setLocked] = useState(false)
  const [sourceRef, setSourceRef] = useState('')
  const [sourceLocator, setSourceLocator] = useState('')
  const [sourceVersion, setSourceVersion] = useState('')
  const [method, setMethod] = useState('')
  const [cypherSource, setCypherSource] = useState('// CREATE (p:Product)\n// CREATE (m:Material)\n// CREATE (p)-[:MADE_FROM]->(m)')
  const [cypherParseError, setCypherParseError] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>()

  const refreshGraphs = useCallback(async () => {
    try {
      const result = await client.request<KnowledgeGraph[]>('/knowledge/graphs')
      setGraphs(result)
      setSelectedGraphId((current) => current && result.some((graph) => graph.id === current) ? current : result[0]?.id ?? '')
    } catch (next) { setError(next) }
  }, [client])
  useEffect(() => { void refreshGraphs() }, [refreshGraphs])

  const refreshChangesets = useCallback(async (graphId: string) => {
    if (!graphId) { setChangesets([]); return }
    try {
      const result = await client.request<KnowledgeChangeSet[]>(`/knowledge/graphs/${graphId}/changesets`)
      setChangesets(result)
      setSelectedChangesetId((current) => current && result.some((item) => item.id === current && item.state === 'DRAFT') ? current : result.find((item) => item.state === 'DRAFT')?.id ?? '')
    } catch (next) { setError(next); setChangesets([]) }
  }, [client])
  useEffect(() => { void refreshChangesets(selectedGraphId) }, [refreshChangesets, selectedGraphId])

  const createChangeset = async (event: FormEvent) => {
    event.preventDefault()
    if (!selectedGraphId || !changeTitle.trim()) return
    setBusy(true); setError(undefined)
    try {
      const result = await client.request<KnowledgeChangeSet>(`/knowledge/graphs/${selectedGraphId}/changesets`, {
        method: 'POST', idempotencyKey: newIdempotencyKey('knowledge-changeset'), body: JSON.stringify({ title: changeTitle.trim() }),
      })
      setChangeTitle(''); await refreshChangesets(selectedGraphId); setSelectedChangesetId(result.id)
    } catch (next) { setError(next) } finally { setBusy(false) }
  }

  const addNode = () => {
    const label = nodeLabel.trim()
    if (!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(label)) {
      setError(new Error('노드 레이블은 영문자로 시작하고 영문·숫자·밑줄만 64자 이내로 입력하세요.'))
      return
    }
    setDraftNodes((current) => [...current, { id: crypto.randomUUID(), label }])
    setNodeLabel(''); setError(undefined)
  }
  const connect = (source: string, target: string) => {
    const edgeType = relation.trim()
    if (!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(edgeType)) {
      setError(new Error('관계 유형은 영문자로 시작하고 영문·숫자·밑줄만 64자 이내로 입력하세요.'))
      return
    }
    setDraftEdges((current) => [...current, { id: crypto.randomUUID(), source, target, relation: edgeType.toUpperCase() }])
  }

  const visualNodes = useMemo<FlowCanvasNode[]>(() => draftNodes.map((node) => ({ id: node.id, label: node.label, subtitle: 'T-Box draft node', kind: 'neutral' })), [draftNodes])
  const visualEdges = useMemo<FlowCanvasEdge[]>(() => draftEdges.map((edge) => ({ ...edge, label: edge.relation })), [draftEdges])
  const cypherPreview = useMemo(() => formatSafeCypherDraft(draftNodes, draftEdges)
    || '// 허용 예시:\n// CREATE (p:Product)\n// CREATE (m:Material)\n// CREATE (p)-[:MADE_FROM]->(m)', [draftEdges, draftNodes])

  useEffect(() => {
    if (directTab === 'VISUAL') setCypherSource(cypherPreview)
  }, [cypherPreview, directTab])

  const updateCypherDraft = (source: string) => {
    setCypherSource(source)
    const parsed = parseSafeCypherDraft(source)
    setCypherParseError(parsed.error ?? '')
    if (parsed.error) return
    setDraftNodes(parsed.nodes)
    setDraftEdges(parsed.edges)
  }

  const applyDraft = async () => {
    const initial = changesets.find((item) => item.id === selectedChangesetId && item.state === 'DRAFT')
    if (!initial || !selectedGraphId || !draftNodes.length) return
    if (![sourceRef, sourceLocator, sourceVersion, method].every((value) => value.trim())) {
      setError(new Error('Typed changeset에는 Source ref, locator, version, 방법 근거가 모두 필요합니다.'))
      return
    }
    setBusy(true); setError(undefined)
    try {
      let current = initial
      let sequence = Math.max(0, ...current.operations.map((item) => item.sequence))
      const provenance = [{ source_ref: sourceRef.trim(), source_locator: sourceLocator.trim(), source_version: sourceVersion.trim(), method: method.trim(), confidence: 1 }]
      const operations: KnowledgeChangeOperationCreate[] = [
        ...draftNodes.map((node) => ({ sequence: ++sequence, operation: 'UPSERT' as const, entity_kind: 'NODE' as const, stable_entity_id: node.id, document: { entity_type: node.label, properties: { name: node.label }, classification: 1 }, provenance, confidence: 1 })),
        ...draftEdges.map((edge) => ({ sequence: ++sequence, operation: 'UPSERT' as const, entity_kind: 'EDGE' as const, stable_entity_id: edge.id, document: { source_id: edge.source, target_id: edge.target, edge_type: edge.relation, properties: {}, classification: 1 }, provenance, confidence: 1 })),
      ]
      for (const operation of operations) {
        current = await client.request<KnowledgeChangeSet>(`/knowledge/graphs/${selectedGraphId}/changesets/${current.id}/operations`, {
          method: 'POST', ifMatch: `"${current.version}"`, body: JSON.stringify(operation),
        })
      }
      setDraftNodes([]); setDraftEdges([]); await refreshChangesets(selectedGraphId)
    } catch (next) { setError(next) } finally { setBusy(false) }
  }

  const transition = async (changeset: KnowledgeChangeSet, operation: 'submit' | 'approve' | 'reject' | 'publish') => {
    if (!selectedGraphId || ((operation === 'approve' || operation === 'reject') && !reviewReason.trim())) return
    setBusy(true); setError(undefined)
    try {
      const path = `/knowledge/graphs/${selectedGraphId}/changesets/${changeset.id}/${operation === 'approve' || operation === 'reject' ? 'reviews' : operation}`
      const options = operation === 'publish'
        ? { method: 'POST' as const, idempotencyKey: newIdempotencyKey('knowledge-publish') }
        : { method: 'POST' as const, ifMatch: `"${changeset.version}"`, body: operation === 'approve' || operation === 'reject' ? JSON.stringify({ decision: operation === 'approve' ? 'APPROVED' : 'REJECTED', reason: reviewReason.trim() }) : undefined }
      await client.request<KnowledgeChangeSet | KnowledgeChangeSetPublish>(path, options)
      setReviewReason(''); await refreshChangesets(selectedGraphId); if (operation === 'publish') await refreshGraphs()
    } catch (next) { setError(next) } finally { setBusy(false) }
  }

  const selectedGraph = graphs.find((graph) => graph.id === selectedGraphId)

  return <div className="grid gap-4">
    <section className="grid gap-3 rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm md:grid-cols-2">
      <button type="button" className={`rounded-enterprise border p-4 text-left transition-colors ${mode === 'A' ? 'border-enterprise-blue bg-blue-50' : 'border-slate-200 bg-slate-50 hover:bg-white'}`} onClick={() => setMode('A')}><strong className="block text-sm text-navy-900">MODE A · Ontology Builder</strong><small className="mt-1 block text-slate-500">T-Box 스키마 정의</small></button>
      <button type="button" className={`rounded-enterprise border p-4 text-left transition-colors ${mode === 'B' ? 'border-enterprise-blue bg-blue-50' : 'border-slate-200 bg-slate-50 hover:bg-white'}`} onClick={() => setMode('B')}><strong className="block text-sm text-navy-900">MODE B · Data Enricher</strong><small className="mt-1 block text-slate-500">A-Box 데이터 적재</small></button>
    </section>
    <ErrorNotice error={error} />

    {mode === 'A' && <>
      <div className="flex flex-wrap items-end justify-between gap-3 rounded-enterprise border border-slate-300 bg-white p-3 shadow-sm">
        <div className="flex gap-2" role="tablist" aria-label="Ontology Builder 방식"><button type="button" role="tab" aria-selected={modeATab === 'SOURCE'} className={`button ${modeATab === 'SOURCE' ? '' : 'button-secondary'}`} onClick={() => setModeATab('SOURCE')}>소스로부터 생성</button><button type="button" role="tab" aria-selected={modeATab === 'DIRECT'} className={`button ${modeATab === 'DIRECT' ? '' : 'button-secondary'}`} onClick={() => setModeATab('DIRECT')}>직접 정의</button></div>
        <label className="grid gap-1 text-xs font-black text-navy-900">대상 에셋<select value={selectedGraphId} onChange={(event) => setSelectedGraphId(event.target.value)}><option value="">에셋 선택</option>{graphs.map((graph) => <option key={graph.id} value={graph.id}>{graph.name} · v{graph.version}</option>)}</select></label>
      </div>
      {modeATab === 'SOURCE' ? <>
        <SourceConnection sourceTab={sourceTab} onSourceTab={setSourceTab} />
        <GovernedUnavailable title="LLM 스키마 자동 제안 API 미구현" description="파일/DB 소스의 서버 수집, 악성 파일 검사, 근거 바인딩, LLM 제안 검토 계약이 마련되기 전에는 브라우저가 파일을 업로드하거나 모델 호출을 하지 않습니다." />
        <div className="flex justify-end"><button type="button" className="button" disabled><Sparkles size={14} /> 스키마 자동 제안</button></div>
      </> : <>
        <section className="grid gap-4 rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
          <header><span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Ontology schema editor</span><h3 className="my-1 text-lg font-black text-navy-900">온톨로지 스키마 편집 · typed changeset 동기화</h3></header>
          <div className="flex gap-2" role="tablist" aria-label="온톨로지 편집 방식"><button type="button" role="tab" aria-selected={directTab === 'CYPHER'} className={`button ${directTab === 'CYPHER' ? '' : 'button-secondary'}`} onClick={() => { setCypherSource(cypherPreview); setCypherParseError(''); setDirectTab('CYPHER') }}>Cypher 입력</button><button type="button" role="tab" aria-selected={directTab === 'VISUAL'} className={`button ${directTab === 'VISUAL' ? '' : 'button-secondary'}`} onClick={() => setDirectTab('VISUAL')}>비주얼 그래프 편집</button></div>
          {directTab === 'CYPHER' ? <div className="grid gap-3 lg:grid-cols-2"><label className="grid gap-1 text-xs font-black text-navy-900">Cypher 입력 · 안전한 CREATE subset<textarea aria-invalid={Boolean(cypherParseError)} className="min-h-72 resize-y bg-navy-950 p-4 font-mono text-xs text-slate-100" maxLength={50_000} spellCheck={false} value={cypherSource} onChange={(event) => updateCypherDraft(event.target.value)} /></label><label className="grid gap-1 text-xs font-black text-navy-900">실시간 파싱 결과<textarea className={`min-h-72 resize-y p-4 font-mono text-xs ${cypherParseError ? 'bg-red-50 text-red-900' : 'bg-slate-100'}`} readOnly value={cypherParseError ? `파싱 오류: ${cypherParseError}` : cypherPreview} /></label></div> : <>
            <div className="flex flex-wrap items-end gap-2 rounded-enterprise border border-slate-300 bg-slate-50 p-3"><label className="grid gap-1 text-xs font-bold">노드 레이블<input value={nodeLabel} onChange={(event) => setNodeLabel(event.target.value)} placeholder="Product" /></label><button type="button" className="button" onClick={addNode}><Plus size={13} /> 노드 추가</button><span className="h-8 w-px bg-slate-300" /><label className="grid gap-1 text-xs font-bold">관계 유형<input value={relation} onChange={(event) => setRelation(event.target.value)} /></label><span className="pb-2 text-xs text-slate-500">노드 핸들을 드래그해 연결</span><button type="button" className="button button-secondary ml-auto" onClick={() => setLocked((current) => !current)}>{locked ? <Lock size={13} /> : <Unlock size={13} />} {locked ? '고정 해제' : '위치 고정'}</button></div>
            <FlowCanvas ariaLabel="온톨로지 비주얼 편집기" nodes={visualNodes} edges={visualEdges} editable locked={locked} height={480} onConnect={connect} emptyTitle="비주얼 스키마 초안이 비어 있습니다." emptyDescription="위 입력란에서 노드 레이블을 추가한 뒤 핸들을 드래그해 관계를 연결하세요." />
            <label className="grid gap-1 text-xs font-black text-navy-900">자동생성 Cypher 미리보기<textarea className="min-h-28 resize-y bg-slate-100 p-3 font-mono text-xs font-normal" readOnly value={cypherPreview} /></label>
          </>}
          <GovernedUnavailable compact title="CREATE subset은 로컬에서만 파싱되며 실행되지 않습니다" description="MATCH, 속성, 프로시저, 삭제와 임의 쿼리를 거부하고 Cypher 문자열 자체는 서버로 전송하지 않습니다. 저장 시 아래 출처 근거와 함께 typed NODE/EDGE operation만 changeset API로 전송합니다." />
          <form className="grid gap-3 rounded-enterprise border border-slate-300 bg-slate-50 p-3 md:grid-cols-[minmax(0,1fr)_auto]" onSubmit={(event) => void createChangeset(event)}><label className="grid gap-1 text-xs font-bold">새 Changeset 제목<input required maxLength={500} value={changeTitle} onChange={(event) => setChangeTitle(event.target.value)} /></label><button className="button self-end" disabled={busy || !selectedGraphId}><Plus size={13} /> Changeset 생성</button></form>
          <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-4"><label className="grid gap-1 text-xs font-bold">Source ref<input value={sourceRef} onChange={(event) => setSourceRef(event.target.value)} /></label><label className="grid gap-1 text-xs font-bold">Source locator<input value={sourceLocator} onChange={(event) => setSourceLocator(event.target.value)} /></label><label className="grid gap-1 text-xs font-bold">Source version<input value={sourceVersion} onChange={(event) => setSourceVersion(event.target.value)} /></label><label className="grid gap-1 text-xs font-bold">추출/작성 방법<input value={method} onChange={(event) => setMethod(event.target.value)} /></label></div>
          <div className="flex flex-wrap items-end gap-2"><label className="grid min-w-64 gap-1 text-xs font-bold">DRAFT changeset<select value={selectedChangesetId} onChange={(event) => setSelectedChangesetId(event.target.value)}><option value="">선택</option>{changesets.filter((item) => item.state === 'DRAFT').map((item) => <option key={item.id} value={item.id}>{item.title} · v{item.version}</option>)}</select></label><button type="button" className="button" disabled={busy || !selectedChangesetId || !draftNodes.length} onClick={() => void applyDraft()}><Workflow size={14} /> Typed changeset에 반영</button></div>
        </section>
        <section className="grid gap-3 rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm"><h3 className="m-0 text-sm font-black text-navy-900">Changeset 검토 및 릴리스</h3>{changesets.length === 0 ? <p className="m-0 text-xs text-slate-500">선택한 에셋에 changeset이 없습니다.</p> : <><label className="grid gap-1 text-xs font-bold">승인/반려 의견<textarea className="min-h-16 resize-y" value={reviewReason} onChange={(event) => setReviewReason(event.target.value)} /></label>{changesets.map((changeset) => <article key={changeset.id} className="flex flex-wrap items-center gap-3 border-t border-slate-200 pt-3 text-xs"><span className="badge badge-soft">{changeset.state}</span><div className="min-w-0 flex-1"><strong className="block truncate">{changeset.title}</strong><small>{changeset.operations.length} operations · {changeset.validations.length} validations · v{changeset.version}</small></div>{changeset.state === 'DRAFT' && <button type="button" className="button button-secondary" disabled={busy} onClick={() => void transition(changeset, 'submit')}>검증 제출</button>}{changeset.state === 'REVIEW' && <><button type="button" className="button" disabled={busy || !reviewReason.trim()} onClick={() => void transition(changeset, 'approve')}>승인</button><button type="button" className="button button-danger" disabled={busy || !reviewReason.trim()} onClick={() => void transition(changeset, 'reject')}>반려</button></>}{changeset.state === 'APPROVED' && <button type="button" className="button" disabled={busy} onClick={() => void transition(changeset, 'publish')}>릴리스 발행</button>}</article>)}</>}</section>
      </>}
    </>}

    {mode === 'B' && <>
      <section className="grid gap-3 rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm md:grid-cols-2"><button type="button" className={`rounded-enterprise border p-4 text-left ${modeBOption === 'EXISTING' ? 'border-enterprise-blue bg-blue-50' : 'border-slate-300'}`} onClick={() => setModeBOption('EXISTING')}><strong className="block text-sm text-navy-900">기존 스키마 활용</strong><small className="mt-1 block text-slate-500">Mode A 온톨로지에 강제 매핑</small></button><button type="button" className={`rounded-enterprise border p-4 text-left ${modeBOption === 'DYNAMIC' ? 'border-enterprise-blue bg-blue-50' : 'border-slate-300'}`} onClick={() => setModeBOption('DYNAMIC')}><strong className="block text-sm text-navy-900">동적 원패스 생성</strong><small className="mt-1 block text-slate-500">스키마와 인스턴스를 함께 제안</small></button></section>
      {modeBOption === 'EXISTING' ? <>
        <label className="grid gap-1 rounded-enterprise border border-slate-300 bg-white p-4 text-xs font-black text-navy-900">대상 지식 에셋<select value={selectedGraphId} onChange={(event) => setSelectedGraphId(event.target.value)}><option value="">에셋 선택</option>{graphs.map((graph) => <option key={graph.id} value={graph.id}>{graph.name} · {graph.classification}</option>)}</select></label>
        <section className="grid gap-3 rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm">
          <div className="flex gap-2 border-b border-slate-200 pb-2" role="tablist" aria-label="A-Box 데이터 소스 연결"><button type="button" role="tab" aria-selected={sourceTab === 'FILE'} className={`button ${sourceTab === 'FILE' ? '' : 'button-secondary'}`} onClick={() => setSourceTab('FILE')}>파일 업로드</button><button type="button" role="tab" aria-selected={sourceTab === 'DB'} className={`button ${sourceTab === 'DB' ? '' : 'button-secondary'}`} onClick={() => setSourceTab('DB')}>DB 스키마</button></div>
          {sourceTab === 'DB' && <GovernedUnavailable title="DB 스키마 A-Box 적재 계약 미구현" description="연결된 시스템의 스키마 snapshot, 행 범위, 분류와 provenance를 고정하는 typed source 계약이 마련되기 전에는 DB 검색이나 적재 성공을 표시하지 않습니다." />}
        </section>
        {sourceTab === 'FILE' && <KnowledgeSourceUpload client={client} graph={selectedGraph} onAnalysisCreated={() => refreshChangesets(selectedGraphId)} />}
      </> : <GovernedUnavailable title="동적 원패스 에셋 생성 계약 미구현" description="현재 구현된 PDF 파이프라인은 선택한 기존 에셋의 온톨로지에 맞춘 DRAFT changeset만 생성합니다. 새 에셋과 스키마를 모델 출력만으로 자동 발행하지 않습니다." />}
    </>}
  </div>
}
