import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Bot, Send, ShieldCheck } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { KnowledgeGraph, KnowledgeNeighborAnalysis, KnowledgeRelease, KnowledgeSnapshot } from '../../api/types'
import type { Page } from '../../app/navigation'
import { ErrorNotice } from '../../components/ErrorNotice'
import { FlowCanvas, type FlowCanvasEdge, type FlowCanvasNode } from '../../components/common/FlowCanvas'
import { PageTitle } from '../../components/layout/PageTitle'
import { KnowledgeWorkspaceLayout } from './KnowledgeWorkspaceLayout'

interface KnowledgeGraphRagAnswer extends KnowledgeNeighborAnalysis {
  answer: string
  citations: Array<{
    evidence_id: string
    source_locator: string
    source_version: string
    page_number: number | null
  }>
  model_audit: {
    provider: string
    model: string
    prompt_version: string
    tool_schema_version: string
  }
}

function label(properties: Record<string, unknown>, fallback: string): string {
  const value = properties.name ?? properties.display_name
  return typeof value === 'string' || typeof value === 'number' ? String(value) : fallback
}

export function KnowledgeChatPage({ client, onNavigate }: { client: ApiClient; onNavigate: (page: Page) => void }) {
  const [graphs, setGraphs] = useState<KnowledgeGraph[]>([])
  const [graphId, setGraphId] = useState('')
  const [releases, setReleases] = useState<KnowledgeRelease[]>([])
  const [releaseId, setReleaseId] = useState('')
  const [snapshot, setSnapshot] = useState<KnowledgeSnapshot>()
  const [nodeId, setNodeId] = useState('')
  const [question, setQuestion] = useState('')
  const [direction, setDirection] = useState<'IN' | 'OUT' | 'BOTH'>('BOTH')
  const [maximumHops, setMaximumHops] = useState('1')
  const [analysis, setAnalysis] = useState<KnowledgeGraphRagAnswer>()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<unknown>()

  const loadGraphs = useCallback(async () => {
    setError(undefined)
    try {
      const result = await client.request<KnowledgeGraph[]>('/knowledge/graphs')
      setGraphs(result)
      setGraphId((current) => current && result.some((graph) => graph.id === current) ? current : result[0]?.id ?? '')
    } catch (next) { setError(next) }
  }, [client])
  useEffect(() => { void loadGraphs() }, [loadGraphs])

  useEffect(() => {
    if (!graphId) { setReleases([]); setReleaseId(''); return }
    const controller = new AbortController()
    void client.request<KnowledgeRelease[]>(`/knowledge/graphs/${graphId}/releases`, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return
        setReleases(result)
        const graph = graphs.find((item) => item.id === graphId)
        setReleaseId(graph?.active_release_id ?? result.at(-1)?.id ?? '')
      })
      .catch((next) => { if (!controller.signal.aborted) setError(next) })
    return () => controller.abort()
  }, [client, graphId, graphs])

  useEffect(() => {
    if (!graphId || !releaseId) { setSnapshot(undefined); setNodeId(''); return }
    const controller = new AbortController()
    setLoading(true); setAnalysis(undefined)
    void client.request<KnowledgeSnapshot>(`/knowledge/graphs/${graphId}/releases/${releaseId}/snapshot?maximum_nodes=200`, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return
        setSnapshot(result)
        setNodeId((current) => current && result.nodes.some((node) => node.id === current) ? current : result.nodes[0]?.id ?? '')
      })
      .catch((next) => { if (!controller.signal.aborted) setError(next) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [client, graphId, releaseId])

  const query = async (event: FormEvent) => {
    event.preventDefault()
    if (!graphId || !releaseId || !nodeId || question.trim().length < 2) return
    setLoading(true); setError(undefined)
    try {
      const result = await client.request<KnowledgeGraphRagAnswer>(`/knowledge/graphs/${graphId}/releases/${releaseId}/graphrag`, {
        method: 'POST',
        body: JSON.stringify({ question: question.trim(), start_node_id: nodeId, direction, edge_types: [], maximum_hops: Number(maximumHops), maximum_nodes: 100 }),
      })
      setAnalysis(result)
    } catch (next) { setError(next) } finally { setLoading(false) }
  }

  const flowNodes = useMemo<FlowCanvasNode[]>(() => (analysis?.nodes ?? []).map((node) => ({ id: node.id, label: label(node.properties, node.id), subtitle: `${node.entity_type} · 근거 ${node.provenance.length}`, kind: node.id === nodeId ? 'target' : 'neutral' })), [analysis, nodeId])
  const flowEdges = useMemo<FlowCanvasEdge[]>(() => (analysis?.edges ?? []).map((edge) => ({ id: edge.id, source: edge.source_id, target: edge.target_id, label: edge.edge_type })), [analysis])

  return <section className="grid gap-4">
    <PageTitle icon="KG" eyebrow="Independent Knowledge GraphRAG" title="지식 챗 · GraphRAG 질의" description="일반 Chat 메뉴와 분리된 지식 에셋·불변 릴리스 기반 질의 화면입니다." />
    <KnowledgeWorkspaceLayout activeSection="CHAT" onNavigate={onNavigate}>
    <div className="grid gap-4 2xl:grid-cols-[360px_minmax(0,1fr)]">
      <form className="grid content-start gap-3 rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm" onSubmit={(event) => void query(event)}>
        <div className="flex items-center gap-2 text-sm font-black text-navy-900"><Bot size={18} className="text-enterprise-blue" /> Knowledge query context</div>
        <label className="grid gap-1 text-xs font-bold">지식 에셋<select value={graphId} onChange={(event) => setGraphId(event.target.value)}><option value="">선택</option>{graphs.map((graph) => <option key={graph.id} value={graph.id}>{graph.name} · {graph.status}</option>)}</select></label>
        <label className="grid gap-1 text-xs font-bold">버전 릴리스<select value={releaseId} onChange={(event) => setReleaseId(event.target.value)}><option value="">선택</option>{releases.map((release) => <option key={release.id} value={release.id}>Release v{release.release_no} · {release.node_count} nodes</option>)}</select></label>
        <label className="grid gap-1 text-xs font-bold">시작 노드<select value={nodeId} onChange={(event) => setNodeId(event.target.value)}><option value="">선택</option>{(snapshot?.nodes ?? []).map((node) => <option key={node.id} value={node.id}>{label(node.properties, node.id)} · {node.entity_type}</option>)}</select></label>
        <div className="grid grid-cols-2 gap-2"><label className="grid gap-1 text-xs font-bold">방향<select value={direction} onChange={(event) => setDirection(event.target.value as typeof direction)}><option value="BOTH">BOTH</option><option value="IN">IN</option><option value="OUT">OUT</option></select></label><label className="grid gap-1 text-xs font-bold">최대 Hop<select value={maximumHops} onChange={(event) => setMaximumHops(event.target.value)}><option value="1">1</option><option value="2">2</option><option value="3">3</option></select></label></div>
        <label className="grid gap-1 text-xs font-bold">질문<textarea className="min-h-28 resize-y" minLength={2} maxLength={4000} required value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="선택한 지식 에셋에서 확인할 관계를 질문하세요." /></label>
        <button type="submit" className="button" disabled={loading || !nodeId || question.trim().length < 2}><Send size={14} /> {loading ? '권한 범위 답변 생성 중…' : 'GraphRAG 질의'}</button>
        <p className="m-0 flex items-start gap-2 text-[10px] leading-5 text-slate-500"><ShieldCheck size={14} className="mt-0.5 shrink-0" />선택한 불변 릴리스와 현재 사용자의 분류 권한 안에서 조회한 근거만 LLM 답변에 전달합니다.</p>
      </form>
      <main className="grid content-start gap-4">
        <ErrorNotice error={error} />
        <FlowCanvas ariaLabel="GraphRAG 근거 그래프" nodes={flowNodes} edges={flowEdges} height={500} emptyTitle="아직 분석된 지식 근거가 없습니다." emptyDescription="왼쪽에서 에셋·릴리스·시작 노드와 질문을 선택해 근거 탐색을 실행하세요." />
        {analysis && <section className="rounded-enterprise border border-enterprise-blue bg-blue-50 p-4 shadow-sm"><span className="text-[10px] font-black tracking-[.14em] text-enterprise-blue uppercase">Cited GraphRAG answer</span><p className="whitespace-pre-wrap text-sm leading-6 text-slate-800">{analysis.answer}</p><div className="grid gap-1 text-[10px] text-slate-600">{analysis.citations.map((citation) => <span key={citation.evidence_id}>[{citation.evidence_id}] {citation.source_locator}{citation.page_number ? ` · p.${citation.page_number}` : ''} · {citation.source_version}</span>)}</div><small className="mt-3 block text-slate-500">{analysis.model_audit.provider} · {analysis.model_audit.model} · prompt {analysis.model_audit.prompt_version}</small></section>}
        {analysis && <section className="rounded-enterprise border border-slate-300 bg-white p-4 shadow-sm"><h2 className="mt-0 mb-3 text-sm font-black text-navy-900">권한 내 그래프 근거 · {analysis.nodes.length} nodes / {analysis.edges.length} edges</h2>{analysis.truncated && <p className="text-xs font-bold text-amber-800">조회 한도로 일부 결과가 생략되었습니다.</p>}<ul className="m-0 grid gap-2 pl-5 text-xs">{analysis.nodes.map((node) => <li key={node.id}><strong>{label(node.properties, node.id)}</strong> · {node.entity_type} · provenance {node.provenance.length}</li>)}</ul></section>}
      </main>
    </div>
    </KnowledgeWorkspaceLayout>
  </section>
}
