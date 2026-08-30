import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from 'react'
import {
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Database,
  History,
  MessageSquarePlus,
  Pencil,
  PanelLeftClose,
  PanelLeftOpen,
  Route,
  Send,
  Sparkles,
  Square,
  Star,
  Trash2,
} from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type {
  ChatAuthorizedDiscovery,
  ChatEvidence,
  ChatMessage,
  ChatMode,
  ChatRequestPerformance,
  ChatResponse,
  ChatRouteDecision,
  ChatSession,
  ChatWorkflowStep,
} from '../../api/types'
import { CytoscapeReadGraph } from '../../components/graph/CytoscapeReadGraph'
import type { ReadGraphModel } from '../../components/graph/CytoscapeGraphAdapter'
import { ErrorNotice } from '../../components/ErrorNotice'
import { PageTitle } from '../../components/layout/PageTitle'
import { ChatRouteMenu, type ChatRouteOption } from './ChatRouteMenu'
import { ChatWorkflowRail, type ChatWorkflowProgressStep } from './ChatWorkflowRail'
import { EvidenceModal } from './EvidenceModal'
import { SafeMarkdown } from './SafeMarkdown'

const modeOptions: ChatRouteOption[] = [
  { value: 'AUTO', label: '자동', description: '질문의 의도에 맞는 인가된 경로를 서버가 선택합니다.' },
  { value: 'GENERAL', label: '일반', description: '메타데이터를 검색하지 않고 일반 질문에 답변합니다.' },
  { value: 'VECTOR', label: '벡터', description: '권한 필터 후 의미 기반 검색과 재정렬을 사용합니다.' },
  { value: 'GRAPH', label: '그래프', description: '인가된 Knowledge Asset 또는 DataHub lineage 관계를 탐색합니다.' },
]

const maximumQuestionCharacters = 12_000
const evidencePreviewLimit = 5

const modeLabels: Record<ChatMode, string> = {
  AUTO: '자동',
  GENERAL: '일반',
  VECTOR: '벡터',
  GRAPH: '그래프',
}

const routeReasonLabels: Record<ChatRouteDecision['reason'], string> = {
  EXPLICIT_SELECTION: '사용자 경로 선택',
  GRAPH_INTENT: '영향·계보 질문 감지',
  GRAPH_ASSET_CAPABILITY: 'Graph Asset capability 선택',
  KNOWLEDGE_ASSET_POLICY: '지식 Asset 정책 일치',
  SEMANTIC_INTENT: '의미 검색 질문 감지',
  GENERAL_DEFAULT: '일반 대화 기본 경로',
}

const adapterStateLabels: Record<ChatRouteDecision['adapter_state'], string> = {
  READY: '준비됨',
  UNAVAILABLE: '사용 불가',
  FAILED: '실패',
}

const routeIntentLabels: Partial<Record<NonNullable<ChatRouteDecision['intent']>, string>> = {
  EXPLICIT_SELECTION: '사용자 선택',
  GENERAL_CONVERSATION: '일반 대화',
  EXACT_METADATA: '정확한 메타데이터 조회',
  SEMANTIC_DISCOVERY: '의미 기반 탐색',
  SEMANTIC_SIMILARITY: '유사 자산 탐색',
  LINEAGE: '계보 조회',
  IMPACT_ANALYSIS: '영향도 분석',
  RELATIONSHIP: '관계 탐색',
  KNOWLEDGE_RELATIONSHIP: '지식 Asset 관계 탐색',
  MIXED_DISCOVERY_GRAPH: '탐색 후 관계 분석',
  AMBIGUOUS: '추가 확인 필요',
}

interface ChatViewMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  evidence?: ChatEvidence[]
  discovery?: ChatAuthorizedDiscovery
  route?: ChatRouteDecision
  workflow?: ChatWorkflowStep[]
  performance?: ChatRequestPerformance
}

const workflowStages: ReadonlySet<ChatWorkflowProgressStep['stage']> = new Set([
  'AUTHORIZATION',
  'BUDGET_RESERVATION',
  'ROUTING',
  'RETRIEVAL',
  'RERANKING',
  'COMPOSITION',
  'CITATION_VALIDATION',
  'PERSISTENCE',
])

const workflowStatuses: ReadonlySet<ChatWorkflowProgressStep['status']> = new Set([
  'IN_PROGRESS',
  'COMPLETED',
  'SKIPPED',
  'UNAVAILABLE',
  'FAILED',
  'REFUSED',
])

function isWorkflowProgressStep(value: unknown): value is ChatWorkflowProgressStep {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.detail_code === 'string'
    && workflowStages.has(candidate.stage as ChatWorkflowProgressStep['stage'])
    && workflowStatuses.has(candidate.status as ChatWorkflowProgressStep['status'])
  )
}

function isAnswerDelta(value: unknown): value is { delta: string } {
  return Boolean(value && typeof value === 'object'
    && typeof (value as Record<string, unknown>).delta === 'string'
    && (value as { delta: string }).delta.length > 0
    && (value as { delta: string }).delta.length <= 1_000)
}

function mergeWorkflowProgress(
  current: ChatWorkflowProgressStep[],
  next: ChatWorkflowProgressStep,
): ChatWorkflowProgressStep[] {
  const existing = current.findIndex((item) => item.stage === next.stage)
  if (existing < 0) return [...current, next]
  const updated = [...current]
  updated[existing] = next
  return updated
}

interface CopyFeedback {
  messageId: string
  status: 'SUCCESS' | 'FAILED'
  label: string
}

const liveActivityLabels: Partial<Record<ChatWorkflowProgressStep['stage'], string>> = {
  AUTHORIZATION: '질문 분석 중',
  BUDGET_RESERVATION: '질문 분석 중',
  ROUTING: '질문 분석 중',
  RETRIEVAL: '검색 중',
  RERANKING: '관련 결과 정리 중',
  COMPOSITION: '답변 작성 중',
  CITATION_VALIDATION: '관련 결과 정리 중',
  PERSISTENCE: '대화 저장 중',
}

function liveActivityLabel(
  workflow: ChatWorkflowProgressStep[],
  hasAnswerDelta: boolean,
): string {
  if (hasAnswerDelta) return '답변 표시 중'
  const active = [...workflow].reverse().find((step) => step.status === 'IN_PROGRESS')
  return active ? liveActivityLabels[active.stage] ?? '응답 준비 중' : '응답 준비 중'
}

async function copyVisibleMessageText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }

  if (typeof document.execCommand !== 'function') {
    throw new Error('Clipboard API unavailable')
  }
  const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : undefined
  const fallback = document.createElement('textarea')
  fallback.className = 'chat-copy-fallback'
  fallback.setAttribute('aria-hidden', 'true')
  fallback.readOnly = true
  // This contains only the message text the user can already see. It is
  // transient and gives older secure contexts a browser-native copy path.
  fallback.value = text
  document.body.append(fallback)
  fallback.focus()
  fallback.select()
  const copied = document.execCommand('copy')
  fallback.remove()
  activeElement?.focus()
  if (!copied) throw new Error('Clipboard fallback was denied')
}

function historyMessage(message: ChatMessage): ChatViewMessage {
  return {
    id: message.id,
    role: message.role,
    text: message.content,
    evidence: message.evidence_json ?? undefined,
    discovery: message.discovery_json ?? undefined,
    route: message.route ?? undefined,
    workflow: message.workflow,
  }
}

function lastAssistant(messages: ChatViewMessage[]): ChatViewMessage | undefined {
  return [...messages].reverse().find((message) => message.role === 'assistant')
}

function evidenceDescriptionForDisplay(description: string | null | undefined): string | undefined {
  if (!description) return undefined
  const display = description
    .replace(/\[\[[^\]\r\n]*\]\]/g, '')
    .replace(/\burn:[^\s\])]+/gi, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
  return display || undefined
}

function evidenceKindLabel(kind: ChatEvidence['asset_kind']): string {
  if (kind === 'CATALOG') return '카탈로그 집계'
  if (kind === 'VIEW') return '뷰'
  if (kind === 'MATERIALIZED_VIEW') return '구체화 뷰'
  return '테이블'
}

function evidenceSourceLabel(item: ChatEvidence, context: 'candidate' | 'evidence'): string {
  if (item.source_type === 'CATALOG_ASSET') return evidenceKindLabel(item.asset_kind)
  if (item.source_type === 'GOVERNANCE_DOCUMENT') return '거버넌스 문서'
  if (item.source_type === 'KNOWLEDGE_NODE' || item.source_type.startsWith('KNOWLEDGE_ASSET_')) {
    return context === 'candidate' ? '지식 그래프 후보' : '지식 그래프 근거'
  }
  return context === 'candidate' ? '기타 인가 후보' : '기타 인가 근거'
}

function canOpenCatalogEvidence(item: ChatEvidence): boolean {
  return item.source_type === 'CATALOG_ASSET'
}

function authorizedEvidenceGraph(evidence: ChatEvidence[]): ReadGraphModel | undefined {
  const nodes = new Map<string, NonNullable<ChatEvidence['graph_nodes']>[number]>()
  const edges = new Map<string, NonNullable<ChatEvidence['graph_edges']>[number]>()
  for (const item of evidence) {
    for (const node of item.graph_nodes ?? []) nodes.set(node.id, node)
    for (const edge of item.graph_edges ?? []) edges.set(edge.id, edge)
  }
  if (!nodes.size) return undefined
  const visibleEdges = [...edges.values()].filter((edge) => nodes.has(edge.source) && nodes.has(edge.target))
  const rootId = [...nodes.values()].find((node) => node.role === 'ROOT')?.id
  return {
    kind: 'LINEAGE',
    rootId,
    nodes: [...nodes.values()].map((node) => ({
      id: node.id,
      label: node.label,
      entityType: node.entity_type,
      role: node.role,
      properties: { source_locator: node.source_locator },
      provenance: [{ source_locator: node.source_locator }],
    })),
    edges: visibleEdges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.relation_type,
      relationType: edge.relation_type,
      properties: { source_locator: edge.source_locator },
      provenance: [{ source_locator: edge.source_locator }],
    })),
  }
}

export function ChatPage({
  client,
  initialQuestion,
  onInitialQuestionConsumed,
}: {
  client: ApiClient
  initialQuestion?: string
  onInitialQuestionConsumed?: () => void
}) {
  const [question, setQuestion] = useState(() => initialQuestion?.trim() ?? '')
  const [mode, setMode] = useState<ChatMode>('AUTO')
  const [sessionId, setSessionId] = useState<string>()
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [persistence, setPersistence] = useState<ChatResponse['persistence']>()
  const [messages, setMessages] = useState<ChatViewMessage[]>([])
  const [liveWorkflow, setLiveWorkflow] = useState<ChatWorkflowProgressStep[]>([])
  const [error, setError] = useState<unknown>()
  const [loading, setLoading] = useState(false)
  const [favoriteSessionId, setFavoriteSessionId] = useState<string>()
  const [deletingSessionId, setDeletingSessionId] = useState<string>()
  const [copyFeedback, setCopyFeedback] = useState<CopyFeedback>()
  const [historyTab, setHistoryTab] = useState<'RECENT' | 'FAVORITES'>('RECENT')
  const [historyCollapsed, setHistoryCollapsed] = useState(false)
  const [discoveryExpanded, setDiscoveryExpanded] = useState(false)
  const [evidenceExpanded, setEvidenceExpanded] = useState(false)
  const [selectedAssistantMessageId, setSelectedAssistantMessageId] = useState<string>()
  const [selectedEvidenceAssetId, setSelectedEvidenceAssetId] = useState<string>()
  const [streamingAssistantMessageId, setStreamingAssistantMessageId] = useState<string>()
  const historyRequestVersion = useRef(0)
  const evidenceTriggerRef = useRef<HTMLButtonElement | null>(null)
  const chatLogRef = useRef<HTMLDivElement | null>(null)
  const messageElementsRef = useRef(new Map<string, HTMLElement>())
  const answerFocusEnabledRef = useRef(false)
  const activeRequestRef = useRef<AbortController | undefined>(undefined)
  const initialQuestionHandledRef = useRef(false)
  const composerFormRef = useRef<HTMLFormElement | null>(null)
  const composerRef = useRef<HTMLTextAreaElement | null>(null)

  const refreshSessions = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await client.request<ChatSession[]>('/chat/sessions?limit=50', { signal })
      if (!signal?.aborted) setSessions(result)
    } catch (next) {
      if (!signal?.aborted) setError(next)
    }
  }, [client])

  useEffect(() => {
    const controller = new AbortController()
    activeRequestRef.current?.abort()
    historyRequestVersion.current += 1
    setSessions([])
    setSessionId(undefined)
    setMessages([])
    setLiveWorkflow([])
    setDiscoveryExpanded(false)
    setSelectedAssistantMessageId(undefined)
    setSelectedEvidenceAssetId(undefined)
    setPersistence(undefined)
    setCopyFeedback(undefined)
    setStreamingAssistantMessageId(undefined)
    answerFocusEnabledRef.current = false
    void refreshSessions(controller.signal)
    return () => {
      controller.abort()
      activeRequestRef.current?.abort()
    }
  }, [client, refreshSessions])

  useEffect(() => {
    const textarea = composerRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    const computed = getComputedStyle(textarea)
    const lineHeight = Number.parseFloat(computed.lineHeight) || 18
    const verticalPadding = Number.parseFloat(computed.paddingTop) + Number.parseFloat(computed.paddingBottom)
    const maximumHeight = lineHeight * 6 + verticalPadding
    textarea.style.height = `${Math.min(textarea.scrollHeight, maximumHeight)}px`
    textarea.style.overflowY = textarea.scrollHeight > maximumHeight ? 'auto' : 'hidden'
  }, [question])

  useEffect(() => {
    const normalized = initialQuestion?.trim()
    if (initialQuestionHandledRef.current || !normalized) return
    initialQuestionHandledRef.current = true
    onInitialQuestionConsumed?.()
    const frame = requestAnimationFrame(() => composerFormRef.current?.requestSubmit())
    return () => cancelAnimationFrame(frame)
  }, [initialQuestion, onInitialQuestionConsumed])

  const latestAssistant = useMemo(() => lastAssistant(messages), [messages])
  const selectedAssistant = useMemo(
    () => messages.find(
      (message) => message.role === 'assistant' && message.id === selectedAssistantMessageId,
    ),
    [messages, selectedAssistantMessageId],
  )
  const visibleAssistant = loading && !selectedAssistantMessageId
    ? undefined
    : selectedAssistant ?? latestAssistant
  const visibleWorkflow = loading && !selectedAssistantMessageId
    ? liveWorkflow
    : visibleAssistant?.workflow ?? []
  const providerPolicyUnavailable = visibleWorkflow.some(
    (step) => step.detail_code === 'INFERENCE_PROVIDER_POLICY_BINDING_UNAVAILABLE',
  ) ?? false
  const visibleEvidence = useMemo(
    () => [...(visibleAssistant?.evidence ?? [])].sort((left, right) => left.rank - right.rank),
    [visibleAssistant],
  )
  const displayedEvidence = evidenceExpanded
    ? visibleEvidence
    : visibleEvidence.slice(0, evidencePreviewLimit)
  const evidencePreviewTruncated = visibleEvidence.length > displayedEvidence.length
  const visibleDiscovery = visibleAssistant?.discovery
  const visiblePerformance = visibleAssistant?.performance
  const liveActivity = liveActivityLabel(liveWorkflow, Boolean(streamingAssistantMessageId))
  const canExploreCatalog = typeof visibleDiscovery?.catalog_search_query === 'string'
  const displayedDiscovery = discoveryExpanded
    ? visibleDiscovery?.items ?? []
    : visibleDiscovery?.items.slice(0, evidencePreviewLimit) ?? []
  const visibleEvidenceGraph = useMemo(
    () => visibleAssistant?.route?.selected_mode === 'GRAPH'
      ? authorizedEvidenceGraph(visibleEvidence)
      : undefined,
    [visibleAssistant?.route?.selected_mode, visibleEvidence],
  )
  const visibleSessions = useMemo(
    () => historyTab === 'FAVORITES'
      ? sessions.filter((session) => session.is_favorite)
      : sessions,
    [historyTab, sessions],
  )

  const loadSession = async (id: string) => {
    const requestVersion = ++historyRequestVersion.current
    setLoading(true)
    setError(undefined)
    setLiveWorkflow([])
    setSelectedEvidenceAssetId(undefined)
    try {
      const history = await client.request<ChatMessage[]>(`/chat/sessions/${id}/messages?limit=200`)
      if (historyRequestVersion.current !== requestVersion) return
      const restored = history.map(historyMessage)
      setSessionId(id)
      setMessages(restored)
      setSelectedAssistantMessageId(lastAssistant(restored)?.id)
      setDiscoveryExpanded(false)
      setEvidenceExpanded(false)
      setStreamingAssistantMessageId(undefined)
      answerFocusEnabledRef.current = false
      setPersistence(undefined)
    } catch (next) {
      if (historyRequestVersion.current === requestVersion) setError(next)
    } finally {
      if (historyRequestVersion.current === requestVersion) setLoading(false)
    }
  }

  const startNewSession = useCallback(() => {
    activeRequestRef.current?.abort()
    historyRequestVersion.current += 1
    setSessionId(undefined)
    setQuestion('')
    setMode('AUTO')
    setMessages([])
    setLiveWorkflow([])
    setPersistence(undefined)
    setSelectedAssistantMessageId(undefined)
    setDiscoveryExpanded(false)
    setEvidenceExpanded(false)
    setSelectedEvidenceAssetId(undefined)
    setCopyFeedback(undefined)
    setStreamingAssistantMessageId(undefined)
    answerFocusEnabledRef.current = false
    setError(undefined)
    setLoading(false)
  }, [])

  const updateFavorite = async (chatSession: ChatSession) => {
    if (favoriteSessionId) return
    setFavoriteSessionId(chatSession.id)
    setError(undefined)
    try {
      const updated = await client.request<ChatSession>(
        `/chat/sessions/${chatSession.id}/favorite`,
        {
          method: 'PATCH',
          body: JSON.stringify({
            is_favorite: !chatSession.is_favorite,
            expected_version: chatSession.version,
          }),
        },
      )
      setSessions((current) => current.map((item) => item.id === updated.id ? updated : item))
    } catch (next) {
      await refreshSessions()
      setError(next)
    } finally {
      setFavoriteSessionId(undefined)
    }
  }

  const deleteSession = async (chatSession: ChatSession) => {
    if (deletingSessionId) return
    setDeletingSessionId(chatSession.id)
    setError(undefined)
    try {
      await client.request<void>(
        `/chat/sessions/${chatSession.id}?expected_version=${chatSession.version}`,
        { method: 'DELETE' },
      )
      setSessions((current) => current.filter((item) => item.id !== chatSession.id))
      if (sessionId === chatSession.id) startNewSession()
    } catch (next) {
      await refreshSessions()
      setError(next)
    } finally {
      setDeletingSessionId(undefined)
    }
  }

  const copyMessage = async (message: ChatViewMessage) => {
    const label = message.role === 'user' ? '질문' : '답변'
    try {
      await copyVisibleMessageText(message.text)
      setCopyFeedback({ messageId: message.id, status: 'SUCCESS', label })
    } catch {
      setCopyFeedback({ messageId: message.id, status: 'FAILED', label })
    }
  }

  const editQuestion = (message: ChatViewMessage) => {
    if (message.role !== 'user') return
    setQuestion(message.text)
    requestAnimationFrame(() => composerRef.current?.focus())
  }

  const selectAssistantEvidence = (message: ChatViewMessage) => {
    if (message.role !== 'assistant') return
    setSelectedAssistantMessageId(message.id)
    setDiscoveryExpanded(false)
    setEvidenceExpanded(false)
  }

  const cancelAnswerFocus = useCallback(() => {
    answerFocusEnabledRef.current = false
  }, [])

  const syncAnswerFocus = useCallback(() => {
    const log = chatLogRef.current
    if (!log) return
    answerFocusEnabledRef.current = log.scrollHeight - log.scrollTop - log.clientHeight <= 56
  }, [])

  useEffect(() => {
    if (!answerFocusEnabledRef.current) return
    const target = streamingAssistantMessageId ? messageElementsRef.current.get(streamingAssistantMessageId) : undefined
    if (target && typeof target.scrollIntoView === 'function') {
      target.scrollIntoView({ behavior: 'smooth', block: 'end' })
      return
    }
    const log = chatLogRef.current
    if (log) log.scrollTo?.({ top: log.scrollHeight, behavior: 'smooth' })
  }, [liveWorkflow, loading, messages, streamingAssistantMessageId])

  const stopAnswer = () => {
    activeRequestRef.current?.abort()
    activeRequestRef.current = undefined
    setMessages((current) => current.filter((message) => message.id !== streamingAssistantMessageId))
    setStreamingAssistantMessageId(undefined)
    setLoading(false)
    setLiveWorkflow([])
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const text = question.trim()
    if (text.length < 2 || loading) return
    const pendingMessageId = `pending-${crypto.randomUUID()}`
    const pendingAssistantMessageId = `pending-answer-${crypto.randomUUID()}`
    setMessages((current) => [...current, { id: pendingMessageId, role: 'user', text }])
    setQuestion('')
    setLoading(true)
    setError(undefined)
    setCopyFeedback(undefined)
    setPersistence(undefined)
    setSelectedAssistantMessageId(undefined)
    setDiscoveryExpanded(false)
    setEvidenceExpanded(false)
    setSelectedEvidenceAssetId(undefined)
    setLiveWorkflow([])
    setStreamingAssistantMessageId(undefined)
    answerFocusEnabledRef.current = true
    const controller = new AbortController()
    activeRequestRef.current = controller
    try {
      const result = await client.requestEventStream<ChatResponse>(
        '/chat/query/stream',
        {
          method: 'POST',
          body: JSON.stringify({
            session_id: sessionId,
            question: text,
            maximum_evidence: 5,
            mode,
          }),
          signal: controller.signal,
        },
        (event) => {
          if (event.event === 'workflow' && isWorkflowProgressStep(event.data)) {
            const workflowProgress = event.data
            setLiveWorkflow((current) => mergeWorkflowProgress(current, workflowProgress))
            return
          }
          if (event.event !== 'answer_delta' || !isAnswerDelta(event.data)) return
          const delta = event.data.delta
          setStreamingAssistantMessageId(pendingAssistantMessageId)
          setMessages((current) => {
            const existing = current.find((message) => message.id === pendingAssistantMessageId)
            return existing
              ? current.map((message) => message.id === pendingAssistantMessageId
                ? { ...message, text: `${message.text}${delta}` }
                : message)
              : [...current, { id: pendingAssistantMessageId, role: 'assistant', text: delta }]
          })
        },
      )
      setSessionId(result.session_id)
      setPersistence(result.persistence)
      setLiveWorkflow(result.workflow)
      setSelectedAssistantMessageId(result.response_message_id)
      setStreamingAssistantMessageId(undefined)
      setMessages((current) => {
        const hasPendingAssistant = current.some((message) => message.id === pendingAssistantMessageId)
        const replaced = current.map((message) => {
          if (message.id === pendingMessageId) return { ...message, id: result.request_message_id }
          if (message.id === pendingAssistantMessageId) return {
            ...message,
            id: result.response_message_id,
            text: result.answer,
            evidence: result.evidence,
            discovery: result.discovery ?? undefined,
            route: result.route,
            workflow: result.workflow,
            performance: result.performance,
          }
          return message
        })
        return hasPendingAssistant ? replaced : [...replaced, {
          id: result.response_message_id,
          role: 'assistant' as const,
          text: result.answer,
          evidence: result.evidence,
          discovery: result.discovery ?? undefined,
          route: result.route,
          workflow: result.workflow,
          performance: result.performance,
        }]
      })
      await refreshSessions()
    } catch (next) {
      if (controller.signal.aborted || (next instanceof DOMException && next.name === 'AbortError')) {
        setMessages((current) => current.filter((message) => message.id !== pendingAssistantMessageId))
        setStreamingAssistantMessageId(undefined)
        setError(undefined)
      } else {
      setMessages((current) => current.filter((message) => (
        message.id !== pendingMessageId && message.id !== pendingAssistantMessageId
      )))
        setQuestion(text)
        setError(next)
      }
    } finally {
      if (activeRequestRef.current === controller) activeRequestRef.current = undefined
      setLoading(false)
    }
  }

  const submitOnEnter = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    event.currentTarget.form?.requestSubmit()
  }

  return (
    <section className="chat-page">
      <PageTitle
        actions={(
          <button
            className="button button-secondary"
            disabled={loading}
            onClick={startNewSession}
            title="새 세션을 시작합니다."
            type="button"
          >
            <MessageSquarePlus size={14} />새 대화
          </button>
        )}
        description="내 계정의 대화와 인가된 근거를 연결해 보여주는 카탈로그 Assistant입니다."
        eyebrow="Evidence-first Assistant"
        icon="AI"
        title="카탈로그 Chat"
      />
      {persistence === 'EPHEMERAL_NO_STORE' && (
        <p className="callout" role="status">
          개발 검증 세션입니다. 활성 보존정책이 없어 이 대화는 서버에 저장되지 않습니다.
        </p>
      )}
      <ErrorNotice error={error} />
      <div
        className={[
          'chat-workspace',
          historyCollapsed ? 'is-history-collapsed' : '',
        ].filter(Boolean).join(' ')}
      >
        <aside className="chat-session-panel panel">
          <header>
            <div className="chat-panel-heading">
              <History aria-hidden="true" size={16} />
              {!historyCollapsed && <div><h2>내 대화</h2></div>}
            </div>
            <button
              aria-label={historyCollapsed ? '대화 이력 펼치기' : '대화 이력 숨기기'}
              className="chat-panel-toggle"
              onClick={() => setHistoryCollapsed((current) => !current)}
              type="button"
            >
              {historyCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>
          </header>
          {!historyCollapsed && (
            <div className="chat-panel-content">
              <button className="chat-new-session" onClick={startNewSession} type="button">
                <MessageSquarePlus size={16} />
                <span><strong>새 대화</strong><small>새 질문을 시작하세요</small></span>
              </button>
              <div aria-label="대화 이력 보기" className="chat-history-tabs" role="tablist">
                <button
                  aria-selected={historyTab === 'RECENT'}
                  className={historyTab === 'RECENT' ? 'active' : ''}
                  onClick={() => setHistoryTab('RECENT')}
                  role="tab"
                  type="button"
                >
                  <History size={13} />최근
                </button>
                <button
                  aria-selected={historyTab === 'FAVORITES'}
                  className={historyTab === 'FAVORITES' ? 'active' : ''}
                  onClick={() => setHistoryTab('FAVORITES')}
                  role="tab"
                  type="button"
                >
                  <Star size={13} />즐겨찾기
                </button>
              </div>
              <div aria-label="현재 계정의 대화 세션" className="chat-sessions-list">
                {visibleSessions.map((chatSession) => (
                  <article
                    className={chatSession.id === sessionId ? 'chat-session-card active' : 'chat-session-card'}
                    key={chatSession.id}
                  >
                    <button
                      aria-label={`${chatSession.title || '새 대화'} 열기`}
                      className="chat-session-open"
                      disabled={loading}
                      onClick={() => void loadSession(chatSession.id)}
                      type="button"
                    >
                      <Sparkles size={14} />
                      <span>
                        <strong>{chatSession.title || '새 대화'}</strong>
                        <small>{chatSession.message_count}개 메시지</small>
                      </span>
                    </button>
                    <div className="chat-session-actions">
                      <button
                        aria-label={`${chatSession.title || '새 대화'} ${chatSession.is_favorite ? '즐겨찾기 해제' : '즐겨찾기 추가'}`}
                        disabled={favoriteSessionId === chatSession.id}
                        onClick={() => void updateFavorite(chatSession)}
                        title={chatSession.is_favorite ? '즐겨찾기 해제' : '즐겨찾기 추가'}
                        type="button"
                      >
                        <Star fill={chatSession.is_favorite ? 'currentColor' : 'none'} size={13} />
                      </button>
                      <button
                        aria-label={`${chatSession.title || '새 대화'} 삭제`}
                        className="danger"
                        disabled={deletingSessionId === chatSession.id}
                        onClick={() => void deleteSession(chatSession)}
                        title="내 대화 이력에서 삭제"
                        type="button"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </article>
                ))}
                {visibleSessions.length === 0 && (
                  <div className="chat-history-empty">
                    {historyTab === 'FAVORITES' ? <Star size={18} /> : <History size={18} />}
                    <strong>{historyTab === 'FAVORITES' ? '즐겨찾기가 없습니다.' : '저장된 대화가 없습니다.'}</strong>
                    <small>이 계정에서 만든 대화만 표시됩니다.</small>
                  </div>
                )}
              </div>
              <p className="chat-history-footnote">현재 로그인 계정 · 최근 50개 · 세션당 200개 메시지</p>
            </div>
          )}
        </aside>

        <main className="chat-conversation panel">
          <header>
            <div className="flex min-w-0 items-center gap-2">
              <div className="min-w-0">
                <span className="eyebrow">
                  {visibleAssistant?.route
                    ? `${modeLabels[visibleAssistant.route.selected_mode]} · ${adapterStateLabels[visibleAssistant.route.adapter_state]}`
                    : '새로운 대화'}
                </span>
                <h2>{sessions.find((item) => item.id === sessionId)?.title || '질문과 답변'}</h2>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className="chat-status-dot" data-loading={loading}>{loading ? liveActivity : '준비됨'}</span>
            </div>
          </header>
          <div
            aria-live="polite"
            className="chat-log"
            onKeyDown={(event) => {
              if (['PageUp', 'PageDown', 'Home', 'End', 'ArrowUp', 'ArrowDown', ' '].includes(event.key)) {
                cancelAnswerFocus()
              }
            }}
            onPointerDown={cancelAnswerFocus}
            onScroll={syncAnswerFocus}
            onTouchStart={cancelAnswerFocus}
            onWheel={(event) => {
              if (event.deltaY < 0) cancelAnswerFocus()
            }}
            ref={chatLogRef}
            tabIndex={0}
          >
            {messages.map((message) => (
              <article
                className={[
                  'message',
                  `message-${message.role}`,
                  message.id === visibleAssistant?.id ? 'is-evidence-selected' : '',
                  message.id === streamingAssistantMessageId ? 'is-revealing' : '',
                ].filter(Boolean).join(' ')}
                key={message.id}
                ref={(node) => {
                  if (node) messageElementsRef.current.set(message.id, node)
                  else messageElementsRef.current.delete(message.id)
                }}
              >
                {message.role === 'assistant' ? (
                  <div
                    aria-label="이 답변의 근거 다시 보기"
                    className="chat-answer-content"
                    onClick={() => selectAssistantEvidence(message)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        selectAssistantEvidence(message)
                      }
                    }}
                    role="button"
                    tabIndex={0}
                    title="클릭하면 이 답변에 사용된 근거를 엽니다."
                  >
                    <SafeMarkdown value={message.text} />
                  </div>
                ) : <div className="chat-user-bubble"><p className="chat-question-text">{message.text}</p></div>}
                <div
                  aria-label={message.role === 'user' ? '질문 작업' : '답변 작업'}
                  className={message.role === 'user' ? 'chat-message-actions chat-message-actions-user' : 'chat-message-actions'}
                  role="group"
                >
                  {message.role === 'assistant' && (
                    <button
                      aria-label="답변 근거 다시 보기"
                      onClick={() => selectAssistantEvidence(message)}
                      type="button"
                    >
                      <Database size={12} />근거 {message.evidence?.length ?? 0}
                    </button>
                  )}
                  <button
                    aria-label={`${message.role === 'user' ? '질문' : '답변'} 복사`}
                    onClick={() => void copyMessage(message)}
                    type="button"
                  >
                    {copyFeedback?.messageId === message.id && copyFeedback.status === 'SUCCESS'
                      ? <Check size={12} />
                      : <Copy size={12} />}
                    복사
                  </button>
                  {message.role === 'user' && (
                    <button
                      aria-label="질문을 입력창에서 편집"
                      onClick={() => editQuestion(message)}
                      type="button"
                    >
                      <Pencil size={12} />메시지 편집
                    </button>
                  )}
                </div>
              </article>
            ))}
            {loading && (
              <div aria-label="답변 생성 중" aria-live="polite" className="chat-thinking">
                <span /><span /><span />
              </div>
            )}
            {messages.length === 0 && (
              <div className="chat-empty-state">
                <span><Sparkles size={22} /></span>
                <h3>데이터를 이해하는 대화를 시작하세요</h3>
                <p>카탈로그, 소유권, 품질, 영향 관계를 질문하거나 일반 지식을 물어보세요.</p>
              </div>
            )}
          </div>
          {copyFeedback && (
            <p className={copyFeedback.status === 'SUCCESS' ? 'notice' : 'notice notice-error'} role="status">
              {copyFeedback.label} {copyFeedback.status === 'SUCCESS' ? '복사 완료' : '복사 실패'}
            </p>
          )}
          <form ref={composerFormRef} className="chat-composer" onSubmit={(event) => void submit(event)}>
            <ChatRouteMenu
              disabled={loading}
              onChange={setMode}
              options={modeOptions}
              value={mode}
            />
            <div className="chat-question-field">
              <label className="sr-only" htmlFor="chat-question">카탈로그 질문</label>
              <textarea
                aria-describedby="chat-keyboard-hint chat-question-count"
                aria-keyshortcuts="Enter"
                disabled={loading}
                id="chat-question"
                maxLength={maximumQuestionCharacters}
                onChange={(event) => setQuestion(event.target.value.slice(0, maximumQuestionCharacters))}
                onKeyDown={submitOnEnter}
                placeholder="예: 고객 주문 데이터는 어떤 테이블에 있나요?"
                ref={composerRef}
                rows={1}
                value={question}
              />
              <span className="chat-question-meta">
                <small id="chat-keyboard-hint">Enter 전송 · Shift+Enter 줄바꿈</small>
                <small aria-live="polite" id="chat-question-count">{question.length.toLocaleString()} / {maximumQuestionCharacters.toLocaleString()}</small>
              </span>
            </div>
            {loading ? (
              <button
                aria-label="답변 생성 중지"
                className="chat-send-button chat-stop-button"
                onClick={stopAnswer}
                type="button"
              >
                <Square size={15} />
              </button>
            ) : (
              <button
                aria-label="질문 전송"
                className="chat-send-button"
                disabled={question.trim().length < 2}
                type="submit"
              >
                <Send size={17} />
              </button>
            )}
          </form>
        </main>

        <aside className="chat-evidence-panel panel">
          <header>
            <div className="chat-panel-heading">
              <div><span className="eyebrow">Evidence</span><h2>근거와 처리 흐름</h2></div>
            </div>
          </header>
          <div className="chat-evidence-scroll">
              {visibleAssistant?.route && (
                <section aria-label="서버 라우팅 결정" className="chat-route-summary">
                  <strong><Route size={13} />서버 라우팅</strong>
                  <span>요청 {modeLabels[visibleAssistant.route.requested_mode]} → 선택 {modeLabels[visibleAssistant.route.selected_mode]}</span>
                  <small>
                    {visibleAssistant.route.intent
                      ? routeIntentLabels[visibleAssistant.route.intent] ?? routeReasonLabels[visibleAssistant.route.reason]
                      : routeReasonLabels[visibleAssistant.route.reason]}
                    {typeof visibleAssistant.route.confidence === 'number'
                      ? ` · 신뢰도 ${Math.round(visibleAssistant.route.confidence * 100)}%`
                      : ''}
                    {' · '}{adapterStateLabels[visibleAssistant.route.adapter_state]}
                  </small>
                  {visibleAssistant.route.knowledge_scope && (
                    <small>
                      지식 Asset {visibleAssistant.route.knowledge_scope.asset_name}
                      {' · '}version {visibleAssistant.route.knowledge_scope.release_id}
                    </small>
                  )}
                </section>
              )}
              {providerPolicyUnavailable && (
                <p className="chat-policy-warning" role="status">
                  모델 서버 상태와 별개로, 현재 분류 정책에 승인된 추론 프로필이 연결되지 않았습니다.
                </p>
              )}
              <section className="chat-workflow-section">
                <div className="chat-evidence-section-heading">
                  <span>Response workflow</span>
                  <small>{visibleWorkflow.length}단계</small>
                </div>
                <ChatWorkflowRail isStreaming={loading} steps={visibleWorkflow} />
              </section>
              {visiblePerformance && (
                <>
                  <dl className="chat-performance-summary" aria-label="현재 응답 처리 시간">
                    <div><dt>경로 선택</dt><dd>{visiblePerformance.routing_ms ?? '—'} ms</dd></div>
                    <div><dt>Catalog 탐색</dt><dd>{visiblePerformance.catalog_discovery_ms ?? '—'} ms</dd></div>
                    <div><dt>Vector</dt><dd>{visiblePerformance.vector_ms ?? '—'} ms</dd></div>
                    <div><dt>검색</dt><dd>{visiblePerformance.retrieval_ms ?? '—'} ms</dd></div>
                    <div><dt>재정렬</dt><dd>{visiblePerformance.reranking_ms ?? '—'} ms</dd></div>
                    <div><dt>답변 생성</dt><dd>{visiblePerformance.composition_ms ?? '—'} ms</dd></div>
                    <div><dt>전체</dt><dd>{visiblePerformance.total_ms} ms</dd></div>
                  </dl>
                  <details>
                    <summary>상세 처리 시간</summary>
                    <dl className="chat-performance-summary" aria-label="상세 처리 시간 항목">
                      <div><dt>문맥 준비</dt><dd>{visiblePerformance.contextualization_ms ?? '—'} ms</dd></div>
                      <div><dt>경로 로컬 준비</dt><dd>{visiblePerformance.routing_local_preparation_ms ?? '—'} ms</dd></div>
                      <div><dt>인가 그래프 조회</dt><dd>{visiblePerformance.routing_capability_lookup_ms ?? '—'} ms</dd></div>
                      <div><dt>경로 요청 직렬화</dt><dd>{visiblePerformance.routing_provider_request_serialization_ms ?? '—'} ms</dd></div>
                      <div><dt>경로 Provider 응답 대기</dt><dd>{visiblePerformance.routing_provider_response_wait_ms ?? '—'} ms</dd></div>
                      <div><dt>경로 응답 읽기</dt><dd>{visiblePerformance.routing_provider_response_body_ms ?? '—'} ms</dd></div>
                      <div><dt>경로 판정 검증</dt><dd>{visiblePerformance.routing_decision_parse_ms ?? '—'} ms</dd></div>
                      <div><dt>답변 프롬프트 조립</dt><dd>{visiblePerformance.prompt_assembly_ms ?? '—'} ms</dd></div>
                      <div><dt>답변 요청 직렬화</dt><dd>{visiblePerformance.provider_request_serialization_ms ?? '—'} ms</dd></div>
                      <div><dt>답변 Provider 응답 대기</dt><dd>{visiblePerformance.provider_response_wait_ms ?? '—'} ms</dd></div>
                      <div><dt>답변 응답 읽기</dt><dd>{visiblePerformance.provider_response_body_ms ?? '—'} ms</dd></div>
                    </dl>
                  </details>
                </>
              )}
              {visibleEvidenceGraph && (
                <section className="chat-graph-evidence" aria-label="답변에 사용된 인가 그래프 근거">
                  <div className="chat-evidence-section-heading">
                    <span>Authorized graph evidence</span>
                    <small>{visibleEvidenceGraph.nodes.length} nodes · {visibleEvidenceGraph.edges.length} edges</small>
                  </div>
                  <CytoscapeReadGraph
                    ariaLabel="답변에 사용된 인가 그래프"
                    boundNotice="답변 생성에 실제 사용된 권한 내 bounded subgraph입니다."
                    graph={visibleEvidenceGraph}
                    height={250}
                  />
                </section>
              )}
              {visibleDiscovery && (
                <section className="chat-citation-section" aria-label="인가된 검색 후보">
                  <button
                    aria-expanded={visibleDiscovery.items.length > evidencePreviewLimit ? discoveryExpanded : undefined}
                    className="chat-citation-header"
                    disabled={visibleDiscovery.items.length <= evidencePreviewLimit}
                    onClick={() => setDiscoveryExpanded((value) => !value)}
                    type="button"
                  >
                    <span>인가된 검색 후보</span>
                    <small>
                      {visibleDiscovery.total_exact && visibleDiscovery.total !== null
                        ? `전체 ${visibleDiscovery.total}개 중 ${visibleDiscovery.returned_count}개 조회`
                        : `상위 ${visibleDiscovery.returned_count}개 조회`}
                      {visibleDiscovery.truncated ? ' · 추가 결과 가능' : ' · 현재 범위 완료'}
                      {` · 검색 ${visibleDiscovery.retrieved_count} · 재정렬 ${visibleDiscovery.reranked_count} · 답변 입력 ${visibleDiscovery.answer_context_count}`}
                    </small>
                    {visibleDiscovery.items.length > evidencePreviewLimit && (
                      discoveryExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />
                    )}
                  </button>
                  <ol className="chat-evidence-list">
                    {displayedDiscovery.map((item) => {
                      const catalogEvidence = canOpenCatalogEvidence(item)
                      const content = <>
                        <span className="chat-evidence-rank">#{item.rank}</span>
                        <span className="chat-evidence-copy">
                          <strong>{item.name}</strong>
                          <small>{evidenceSourceLabel(item, 'candidate')}</small>
                        </span>
                      </>
                      return <li key={item.chunk_id}>
                        {catalogEvidence ? (
                          <button
                            aria-label={`검색 후보 ${item.rank} ${item.name} 상세 열기`}
                            onClick={(event) => {
                              evidenceTriggerRef.current = event.currentTarget
                              setSelectedEvidenceAssetId(item.resource_id)
                            }}
                            type="button"
                          >
                            {content}
                          </button>
                        ) : (
                          <div className="chat-evidence-static" aria-label={`검색 후보 ${item.rank} ${item.name}`}>
                            {content}
                          </div>
                        )}
                      </li>
                    })}
                  </ol>
                  {visibleDiscovery.items.length > evidencePreviewLimit && (
                    <button
                      aria-expanded={discoveryExpanded}
                      className="chat-citation-header"
                      onClick={() => setDiscoveryExpanded((value) => !value)}
                      type="button"
                    >
                      {discoveryExpanded
                        ? '검색 후보 처음 5개만 보기'
                        : `검색 후보 나머지 ${visibleDiscovery.items.length - evidencePreviewLimit}개 보기`}
                    </button>
                  )}
                  {canExploreCatalog && (
                    <button
                      className="chat-discovery-catalog-link"
                      onClick={() => {
                        const destination = new URL(window.location.href)
                        destination.searchParams.set('page', 'catalog')
                        destination.searchParams.set(
                          'q',
                          visibleDiscovery?.catalog_search_query ?? '',
                        )
                        if (visibleDiscovery?.catalog_search_fields.length) {
                          destination.searchParams.set(
                            'search_fields',
                            visibleDiscovery.catalog_search_fields.join(','),
                          )
                        } else {
                          destination.searchParams.delete('search_fields')
                        }
                        destination.searchParams.delete('catalogAsset')
                        window.history.pushState({}, '', destination)
                        window.dispatchEvent(new PopStateEvent('popstate'))
                      }}
                      type="button"
                    >
                      같은 카탈로그 후보 범위 전체 보기
                    </button>
                  )}
                </section>
              )}
              <section className="chat-citation-section">
                <button
                  aria-expanded={visibleEvidence.length > evidencePreviewLimit ? evidenceExpanded : undefined}
                  className="chat-citation-header"
                  disabled={visibleEvidence.length <= evidencePreviewLimit}
                  onClick={() => setEvidenceExpanded((value) => !value)}
                  type="button"
                >
                  <span>인가된 인용 근거</span>
                  <small>
                    {evidencePreviewTruncated
                      ? `총 ${visibleEvidence.length}개 중 ${displayedEvidence.length}개 표시 · 더 있음`
                      : `총 ${visibleEvidence.length}개 모두 표시`}
                  </small>
                  {visibleEvidence.length > evidencePreviewLimit && (
                    evidenceExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />
                  )}
                </button>
                <ol className="chat-evidence-list">
                  {displayedEvidence.map((item) => {
                    const description = evidenceDescriptionForDisplay(item.description)
                    const catalogEvidence = canOpenCatalogEvidence(item)
                    const content = <>
                      <span className="chat-evidence-rank">#{item.rank}</span>
                      <span className="chat-evidence-copy">
                        <strong>{item.name}</strong>
                        <small>{evidenceSourceLabel(item, 'evidence')}</small>
                        {description && <span>{description}</span>}
                        {!catalogEvidence && (
                          <code className="break-all text-[10px] text-slate-500">{item.source_locator}</code>
                        )}
                      </span>
                    </>
                    return (
                      <li key={item.chunk_id}>
                        {catalogEvidence ? (
                          <button
                            aria-label={`근거 ${item.rank} ${item.name} 상세 열기`}
                            onClick={(event) => {
                              evidenceTriggerRef.current = event.currentTarget
                              setSelectedEvidenceAssetId(item.resource_id)
                            }}
                            type="button"
                          >
                            {content}
                          </button>
                        ) : (
                          <div className="chat-evidence-static" aria-label={`근거 ${item.rank} ${item.name}`}>
                            {content}
                          </div>
                        )}
                      </li>
                    )
                  })}
                  {visibleEvidence.length === 0 && (
                    <li className="chat-evidence-empty">
                      {visibleAssistant
                        ? '이 답변에는 사내 인용 근거가 없습니다. 일반 지식 답변은 근거 없음 상태를 명확히 유지합니다.'
                        : '답변을 선택하면 해당 시점의 인가된 근거가 표시됩니다.'}
                    </li>
                  )}
                </ol>
                {visibleEvidence.length > evidencePreviewLimit && (
                  <button
                    aria-expanded={evidenceExpanded}
                    className="chat-citation-header"
                    onClick={() => setEvidenceExpanded((value) => !value)}
                    type="button"
                  >
                    {evidenceExpanded ? '처음 5개만 보기' : `나머지 ${visibleEvidence.length - evidencePreviewLimit}개 보기`}
                  </button>
                )}
              </section>
          </div>
        </aside>
      </div>
      {selectedEvidenceAssetId && (
        <EvidenceModal
          assetId={selectedEvidenceAssetId}
          client={client}
          onClose={() => setSelectedEvidenceAssetId(undefined)}
          onSelectAsset={setSelectedEvidenceAssetId}
          returnFocus={evidenceTriggerRef}
        />
      )}
    </section>
  )
}
