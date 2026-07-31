import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from 'react'
import {
  Bot,
  Boxes,
  ChevronRight,
  GitBranch,
  Loader2,
  Send,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type {
  KnowledgeGraph,
  KnowledgeNeighborAnalysis,
  KnowledgeRelease,
  KnowledgeSnapshot,
} from '../../api/types'
import type { Page } from '../../app/navigation'
import { ErrorNotice } from '../../components/ErrorNotice'
import {
  FlowCanvas,
  type FlowCanvasEdge,
  type FlowCanvasNode,
} from '../../components/common/FlowCanvas'
import { PageTitle } from '../../components/layout/PageTitle'
import { SafeMarkdown } from '../chat/SafeMarkdown'
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

export function KnowledgeChatContent({ client }: { client: ApiClient }) {
  const [graphs, setGraphs] = useState<KnowledgeGraph[]>([])
  const [graphId, setGraphId] = useState('')
  const [releases, setReleases] = useState<KnowledgeRelease[]>([])
  const [releaseId, setReleaseId] = useState('')
  const [snapshot, setSnapshot] = useState<KnowledgeSnapshot>()
  const [nodeId, setNodeId] = useState('')
  const [question, setQuestion] = useState('')
  const [submittedQuestion, setSubmittedQuestion] = useState('')
  const [direction, setDirection] = useState<'IN' | 'OUT' | 'BOTH'>('BOTH')
  const [maximumHops, setMaximumHops] = useState('1')
  const [analysis, setAnalysis] = useState<KnowledgeGraphRagAnswer>()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<unknown>()
  const requestVersion = useRef(0)
  const answerRef = useRef<HTMLElement>(null)

  const loadGraphs = useCallback(async () => {
    setError(undefined)
    try {
      const result = await client.request<KnowledgeGraph[]>('/knowledge/graphs')
      setGraphs(result)
      setGraphId((current) => (
        current && result.some((graph) => graph.id === current)
          ? current
          : result[0]?.id ?? ''
      ))
    } catch (next) {
      setError(next)
    }
  }, [client])

  useEffect(() => {
    void loadGraphs()
  }, [loadGraphs])

  useEffect(() => {
    requestVersion.current += 1
    setAnalysis(undefined)
    setSubmittedQuestion('')
    if (!graphId) {
      setReleases([])
      setReleaseId('')
      return
    }
    const controller = new AbortController()
    void client.request<KnowledgeRelease[]>(`/knowledge/graphs/${graphId}/releases`, {
      signal: controller.signal,
    })
      .then((result) => {
        if (controller.signal.aborted) return
        setReleases(result)
        const graph = graphs.find((item) => item.id === graphId)
        setReleaseId(graph?.active_release_id ?? result.at(-1)?.id ?? '')
      })
      .catch((next) => {
        if (!controller.signal.aborted) setError(next)
      })
    return () => controller.abort()
  }, [client, graphId, graphs])

  useEffect(() => {
    requestVersion.current += 1
    setAnalysis(undefined)
    setSubmittedQuestion('')
    if (!graphId || !releaseId) {
      setSnapshot(undefined)
      setNodeId('')
      return
    }
    const controller = new AbortController()
    setLoading(true)
    void client.request<KnowledgeSnapshot>(
      `/knowledge/graphs/${graphId}/releases/${releaseId}/snapshot?maximum_nodes=200`,
      { signal: controller.signal },
    )
      .then((result) => {
        if (controller.signal.aborted) return
        setSnapshot(result)
        setNodeId((current) => (
          current && result.nodes.some((node) => node.id === current)
            ? current
            : ''
        ))
      })
      .catch((next) => {
        if (!controller.signal.aborted) setError(next)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [client, graphId, releaseId])

  const query = async (event: FormEvent) => {
    event.preventDefault()
    const trimmedQuestion = question.trim()
    if (!graphId || !releaseId || trimmedQuestion.length < 2 || loading) return
    const version = ++requestVersion.current
    setSubmittedQuestion(trimmedQuestion)
    setAnalysis(undefined)
    setLoading(true)
    setError(undefined)
    try {
      const result = await client.request<KnowledgeGraphRagAnswer>(
        `/knowledge/graphs/${graphId}/releases/${releaseId}/graphrag`,
        {
          method: 'POST',
          body: JSON.stringify({
            question: trimmedQuestion,
            start_node_id: nodeId || null,
            direction,
            edge_types: [],
            maximum_hops: Number(maximumHops),
            maximum_nodes: 8,
          }),
        },
      )
      if (requestVersion.current !== version) return
      setAnalysis(result)
      globalThis.requestAnimationFrame(() => answerRef.current?.scrollIntoView?.({
        behavior: 'smooth',
        block: 'nearest',
      }))
    } catch (next) {
      if (requestVersion.current === version) setError(next)
    } finally {
      if (requestVersion.current === version) setLoading(false)
    }
  }

  const flowNodes = useMemo<FlowCanvasNode[]>(() => (
    analysis?.nodes ?? snapshot?.nodes ?? []
  ).map((node) => ({
    id: node.id,
    label: label(node.properties, node.id),
    subtitle: `${node.entity_type} · 근거 ${node.provenance.length}`,
    kind: node.id === nodeId ? 'target' : 'neutral',
  })), [analysis, nodeId, snapshot])

  const flowEdges = useMemo<FlowCanvasEdge[]>(() => (
    analysis?.edges ?? snapshot?.edges ?? []
  ).map((edge) => ({
    id: edge.id,
    source: edge.source_id,
    target: edge.target_id,
    label: edge.edge_type,
  })), [analysis, snapshot])

  const activeGraph = graphs.find((graph) => graph.id === graphId)
  const activeRelease = releases.find((release) => release.id === releaseId)
  const activeNode = snapshot?.nodes.find((node) => node.id === nodeId)

  return (
    <div className="knowledge-chat-shell">
          <form className="knowledge-chat-context" onSubmit={(event) => void query(event)}>
            <header>
              <span><Bot size={18} /></span>
              <div>
                <small>Query context</small>
                <h2>탐색 범위</h2>
              </div>
            </header>
            <label>
              지식 에셋
              <select value={graphId} onChange={(event) => setGraphId(event.target.value)}>
                <option value="">선택</option>
                {graphs.map((graph) => (
                  <option key={graph.id} value={graph.id}>{graph.name} · {graph.status}</option>
                ))}
              </select>
            </label>
            <label>
              버전 릴리스
              <select value={releaseId} onChange={(event) => setReleaseId(event.target.value)}>
                <option value="">선택</option>
                {releases.map((release) => (
                  <option key={release.id} value={release.id}>
                    Release v{release.release_no} · {release.node_count} nodes
                  </option>
                ))}
              </select>
            </label>
            <label>
              시작 노드
              <select value={nodeId} onChange={(event) => setNodeId(event.target.value)}>
                <option value="">자동 선택 · 의미 검색 또는 소형 그래프 bounded fallback</option>
                {(snapshot?.nodes ?? []).map((node) => (
                  <option key={node.id} value={node.id}>
                    {label(node.properties, node.id)} · {node.entity_type}
                  </option>
                ))}
              </select>
            </label>
            <div className="knowledge-chat-context-grid">
              <label>
                방향
                <select
                  value={direction}
                  onChange={(event) => setDirection(event.target.value as typeof direction)}
                >
                  <option value="BOTH">BOTH</option>
                  <option value="IN">IN</option>
                  <option value="OUT">OUT</option>
                </select>
              </label>
              <label>
                최대 Hop
                <select value={maximumHops} onChange={(event) => setMaximumHops(event.target.value)}>
                  <option value="1">1</option>
                  <option value="2">2</option>
                  <option value="3">3</option>
                </select>
              </label>
            </div>
            <label className="knowledge-chat-question">
              질문
              <textarea
                maxLength={4000}
                minLength={2}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="선택한 지식 릴리스에서 확인할 관계를 질문하세요."
                required
                value={question}
              />
            </label>
            <button
              className="knowledge-chat-submit"
              disabled={loading || !graphId || !releaseId || question.trim().length < 2}
              type="submit"
            >
              {loading ? <Loader2 className="animate-spin" size={15} /> : <Send size={15} />}
              {loading ? '근거 탐색 및 답변 생성 중…' : 'GraphRAG 질의'}
            </button>
            <p className="knowledge-chat-security">
              <ShieldCheck size={14} />
              시작 노드를 비우면 질문 의미 기반 또는 소형 그래프 bounded fallback으로
              선택합니다. 릴리스와 계정 권한은 서버에서 재검증하며 브라우저는 그래프 쿼리를
              직접 만들지 않습니다.
            </p>
          </form>

          <main className="knowledge-chat-results">
            <ErrorNotice error={error} />
            <section aria-live="polite" className="knowledge-chat-answer" ref={answerRef}>
              <header>
                <div>
                  <span><Sparkles size={16} /></span>
                  <div><small>Cited answer</small><h2>GraphRAG 응답</h2></div>
                </div>
                {analysis && <span className="knowledge-answer-status">근거 검증 완료</span>}
              </header>
              {loading && (
                <div className="knowledge-answer-loading">
                  <Loader2 className="animate-spin" size={26} />
                  <strong>인가된 경로와 근거를 탐색하고 있습니다.</strong>
                  <small>{submittedQuestion}</small>
                </div>
              )}
              {!loading && analysis && (
                <div className="knowledge-answer-body">
                  <p className="knowledge-answer-question">{submittedQuestion}</p>
                  <SafeMarkdown value={analysis.answer} />
                  <div aria-label="GraphRAG 인용 근거" className="knowledge-citation-chips">
                    {analysis.citations.map((citation, index) => (
                      <span key={citation.evidence_id} title={citation.source_locator}>
                        <b>{index + 1}</b>
                        {citation.source_locator}
                        {citation.page_number ? ` · p.${citation.page_number}` : ''}
                      </span>
                    ))}
                  </div>
                  <footer>
                    {analysis.model_audit.provider} · {analysis.model_audit.model}
                    {' · '}prompt {analysis.model_audit.prompt_version}
                  </footer>
                </div>
              )}
              {!loading && !analysis && (
                <div className="knowledge-answer-empty">
                  <span><Bot size={22} /></span>
                  <strong>질문을 입력하면 답변이 이곳에 표시됩니다.</strong>
                  <small>긴 그래프 캔버스 아래로 숨지 않고 응답 영역에 즉시 렌더링됩니다.</small>
                </div>
              )}
            </section>

            <div className="knowledge-evidence-grid">
              <section className="knowledge-graph-card">
                <header>
                  <div><GitBranch size={15} /><strong>근거 그래프</strong></div>
                  {analysis ? (
                    <small>
                      {analysis.nodes.length} nodes · {analysis.edges.length} edges · 답변 근거 경로
                    </small>
                  ) : snapshot ? (
                    <small>
                      {snapshot.nodes.length} nodes · {snapshot.edges.length} edges · 권한 내 bounded preview
                      {snapshot.filtered ? ' · filtered' : ''}
                    </small>
                  ) : null}
                </header>
                <FlowCanvas
                  ariaLabel="GraphRAG 근거 그래프"
                  edges={flowEdges}
                  emptyDescription="권한 범위의 선택된 릴리스에 표시 가능한 노드가 없습니다."
                  emptyTitle="표시할 릴리스 미리보기가 없습니다."
                  height={390}
                  nodes={flowNodes}
                  onNodeActivate={(selectedNodeId) => {
                    if (snapshot?.nodes.some((node) => node.id === selectedNodeId)) {
                      setNodeId(selectedNodeId)
                    }
                  }}
                />
              </section>
              <aside className="knowledge-evidence-list">
                <header><Boxes size={15} /><strong>Evidence</strong></header>
                {analysis ? (
                  <>
                    <div className="knowledge-context-path" aria-label="GraphRAG 선택 경로">
                      <span>{activeGraph?.name ?? 'Graph'}</span>
                      <ChevronRight size={12} />
                      <span>v{activeRelease?.release_no ?? '-'}</span>
                      <ChevronRight size={12} />
                      <strong>
                        {activeNode
                          ? label(activeNode.properties, activeNode.id)
                          : '자동 seed · 의미 검색 또는 소형 그래프 bounded fallback'}
                      </strong>
                    </div>
                    {analysis.truncated && (
                      <p className="knowledge-truncated">조회 한도로 일부 결과가 생략되었습니다.</p>
                    )}
                    <ul>
                      {analysis.nodes.map((node) => (
                        <li key={node.id}>
                          <span>{node.entity_type.slice(0, 2).toUpperCase()}</span>
                          <div>
                            <strong>{label(node.properties, node.id)}</strong>
                            <small>{node.entity_type} · provenance {node.provenance.length}</small>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <p className="knowledge-evidence-empty">응답과 함께 권한 내 근거가 표시됩니다.</p>
                )}
              </aside>
            </div>
          </main>
    </div>
  )
}

export function KnowledgeChatPage({
  client,
  onNavigate,
}: {
  client: ApiClient
  onNavigate: (page: Page) => void
}) {
  return (
    <section className="grid gap-4">
      <PageTitle
        description="불변 릴리스와 현재 계정의 분류 권한 안에서 탐색한 근거만 답변에 사용합니다."
        eyebrow="Independent Knowledge GraphRAG"
        icon="KG"
        title="지식 챗 · GraphRAG"
      />
      <KnowledgeWorkspaceLayout activeSection="CHAT" onNavigate={onNavigate}>
        <KnowledgeChatContent client={client} />
      </KnowledgeWorkspaceLayout>
    </section>
  )
}
