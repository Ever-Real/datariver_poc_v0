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
  Copy,
  GitBranch,
  MessageSquarePlus,
  PanelRight,
  Route,
  Send,
  Sparkles,
  Star,
} from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type {
  ChatEvidence,
  ChatMessage,
  ChatMode,
  ChatResponse,
  ChatRouteDecision,
  ChatSession,
  ChatWorkflowStep,
} from '../../api/types'
import { AccordionItem } from '../../components/common/Accordion'
import { ErrorNotice } from '../../components/ErrorNotice'
import { PageTitle } from '../../components/layout/PageTitle'
import { CatalogDetailPane } from '../catalog/CatalogDetailPane'
import { SafeMarkdown } from './SafeMarkdown'

const modeOptions: Array<{ value: ChatMode; label: string; description: string }> = [
  { value: 'AUTO', label: '자동', description: '서버가 질문 의도를 근거로 경로를 결정합니다.' },
  { value: 'GENERAL', label: '일반', description: '인가된 카탈로그 검색 근거를 사용합니다.' },
  { value: 'VECTOR', label: '벡터', description: '인가 후 의미 기반 검색 경로를 사용합니다.' },
  { value: 'GRAPH', label: '그래프', description: 'Asset Graph 어댑터가 없으면 명시적으로 거부됩니다.' },
]

const workflowLabels: Record<ChatWorkflowStep['stage'], string> = {
  AUTHORIZATION: '권한 확인',
  BUDGET_RESERVATION: '사용량 예산 예약',
  ROUTING: '질문 라우팅',
  RETRIEVAL: '근거 검색',
  RERANKING: '근거 정렬',
  COMPOSITION: '답변 작성',
  CITATION_VALIDATION: '인용 검증',
  PERSISTENCE: '대화 저장',
}

const modeLabels: Record<ChatMode, string> = {
  AUTO: '자동',
  GENERAL: '일반',
  VECTOR: '벡터',
  GRAPH: '그래프',
}

const workflowDetailLabels: Partial<Record<string, string>> = {
  CHAT_QUERY_AUTHORIZED: '질문 실행 권한을 확인했습니다.',
  CHAT_RATE_AND_TOKEN_BUDGET_RESERVED: '요청 및 토큰 예산을 예약했습니다.',
  INFERENCE_PROVIDER_POLICY_BINDING_UNAVAILABLE: '승인된 추론 프로필 연결이 필요합니다.',
  GRAPH_ADAPTER_UNAVAILABLE: 'Asset Graph 어댑터가 아직 준비되지 않았습니다.',
  VECTOR_ADAPTER_UNAVAILABLE: '벡터 검색 어댑터가 아직 준비되지 않았습니다.',
  GENERAL_ROUTE_SELECTED: '일반 카탈로그 검색 경로를 선택했습니다.',
  VECTOR_ROUTE_SELECTED: '벡터 검색 경로를 선택했습니다.',
  GRAPH_ROUTE_SELECTED: 'Asset Graph 검색 경로를 선택했습니다.',
  GENERAL_RETRIEVAL_COMPLETED: '일반 카탈로그 근거 검색을 완료했습니다.',
  VECTOR_RETRIEVAL_COMPLETED: '벡터 근거 검색을 완료했습니다.',
  GRAPH_RETRIEVAL_COMPLETED: 'Asset Graph 근거 검색을 완료했습니다.',
  GENERAL_RETRIEVAL_FAILED: '일반 카탈로그 근거 검색에 실패했습니다.',
  VECTOR_RETRIEVAL_FAILED: '벡터 근거 검색에 실패했습니다.',
  GRAPH_RETRIEVAL_FAILED: 'Asset Graph 근거 검색에 실패했습니다.',
  RETRIEVAL_NOT_EXECUTED: '근거 검색을 실행하지 않았습니다.',
  RETRIEVAL_FAILED: '근거 검색에 실패했습니다.',
  RETRIEVAL_FAILURE_REFUSED: '근거 검색 실패로 답변 생성을 중단했습니다.',
  NO_RETRIEVED_EVIDENCE: '검색된 근거가 없어 정렬을 건너뛰었습니다.',
  RERANKER_NOT_CONFIGURED: '추가 근거 정렬 없이 검색 순위를 사용했습니다.',
  EVIDENCE_RERANKED: '인가된 근거의 순위를 다시 계산했습니다.',
  RERANKER_FAILED: '근거 순위 계산에 실패했습니다.',
  RERANKER_FAILURE_REFUSED: '근거 순위 검증 실패로 답변 생성을 중단했습니다.',
  NO_AUTHORIZED_EVIDENCE: '답변에 사용할 수 있는 인가된 근거가 없습니다.',
  COMPOSER_FAILED: '근거 기반 답변 작성에 실패했습니다.',
  GENERAL_KNOWLEDGE_COMPOSER_FAILED: '일반 지식 답변 작성에 실패했습니다.',
  INVALID_GENERAL_KNOWLEDGE_DRAFT: '일반 지식 답변 형식이 안전성 검증을 통과하지 못했습니다.',
  GROUNDED_DRAFT_COMPOSED: '인가된 근거로 답변 초안을 작성했습니다.',
  GENERAL_KNOWLEDGE_DRAFT_COMPOSED: '사내 근거와 분리된 일반 지식 답변을 작성했습니다.',
  NO_DRAFT: '검증할 답변 초안이 없습니다.',
  CITATIONS_VALIDATED: '인용 근거와 최종 권한을 검증했습니다.',
  NO_INTERNAL_CITATIONS_GENERAL_ANSWER: '일반 지식 답변이므로 사내 인용 근거가 없습니다.',
  UNAVAILABLE_ROUTE_REFUSED: '사용할 수 없는 검색 경로이므로 답변을 생성하지 않았습니다.',
  INVALID_REVOKED_OR_MISSING_CITATIONS: '인용 근거가 없거나 최종 권한 검증을 통과하지 못했습니다.',
  RETENTION_BOUND_EXCHANGE_PERSISTED: '보존정책에 따라 대화를 저장했습니다.',
  EPHEMERAL_NO_STORE: '활성 보존정책이 없어 이 대화를 저장하지 않았습니다.',
  AUTHORIZED: '질문 실행 권한을 확인했습니다.',
  BUDGET_RESERVED: '요청 및 토큰 예산을 예약했습니다.',
  VECTOR_SELECTED: '벡터 검색 경로를 선택했습니다.',
  EVIDENCE_FOUND: '인가된 근거를 찾았습니다.',
  RERANKED: '인가된 근거의 순위를 계산했습니다.',
  ANSWER_COMPOSED: '근거 기반 답변을 작성했습니다.',
  CITATIONS_VALID: '인용 근거를 검증했습니다.',
  PERSISTED: '보존정책에 따라 대화를 저장했습니다.',
}

function workflowDetailLabel(code: string): string {
  return workflowDetailLabels[code] ?? '서버가 반환한 처리 상태입니다.'
}

const workflowStatusLabels: Record<ChatWorkflowStep['status'], string> = {
  COMPLETED: '완료',
  SKIPPED: '건너뜀',
  UNAVAILABLE: '사용 불가',
  FAILED: '실패',
  REFUSED: '중단',
}

const routeReasonLabels: Record<ChatRouteDecision['reason'], string> = {
  EXPLICIT_SELECTION: '사용자 경로 선택',
  GRAPH_INTENT: '영향·계보 질문 감지',
  SEMANTIC_INTENT: '의미 검색 질문 감지',
  GENERAL_DEFAULT: '일반 검색 기본 경로',
}

const adapterStateLabels: Record<ChatRouteDecision['adapter_state'], string> = {
  READY: '준비됨',
  UNAVAILABLE: '사용 불가',
  FAILED: '실패',
}

interface ChatViewMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  evidence?: ChatEvidence[]
  route?: ChatRouteDecision
  workflow?: ChatWorkflowStep[]
}

interface CopyFeedback {
  messageId: string
  status: 'SUCCESS' | 'FAILED'
  label: string
}

function historyMessage(message: ChatMessage): ChatViewMessage {
  return {
    id: message.id,
    role: message.role,
    text: message.content,
    evidence: message.evidence_json ?? undefined,
    route: message.route ?? undefined,
    workflow: message.workflow,
  }
}

function workflowTone(status: ChatWorkflowStep['status']): string {
  if (status === 'COMPLETED') return 'border-green-200 bg-green-50 text-green-800'
  if (status === 'SKIPPED') return 'border-slate-200 bg-slate-50 text-slate-600'
  if (status === 'UNAVAILABLE') return 'border-amber-200 bg-amber-50 text-amber-900'
  return 'border-red-200 bg-red-50 text-red-900'
}

export function ChatPage({ client }: { client: ApiClient }) {
  const [question, setQuestion] = useState('')
  const [mode, setMode] = useState<ChatMode>('AUTO')
  const [sessionId, setSessionId] = useState<string>()
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [persistence, setPersistence] = useState<ChatResponse['persistence']>()
  const [messages, setMessages] = useState<ChatViewMessage[]>([])
  const [error, setError] = useState<unknown>()
  const [loading, setLoading] = useState(false)
  const [favoriteSessionId, setFavoriteSessionId] = useState<string>()
  const [copyFeedback, setCopyFeedback] = useState<CopyFeedback>()
  const [evidenceExpanded, setEvidenceExpanded] = useState(true)
  const [selectedEvidenceAssetId, setSelectedEvidenceAssetId] = useState<string>()
  const historyRequestVersion = useRef(0)
  const evidenceDialogRef = useRef<HTMLDivElement>(null)
  const evidenceTriggerRef = useRef<HTMLButtonElement | null>(null)

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
    void refreshSessions(controller.signal)
    return () => controller.abort()
  }, [refreshSessions])

  const closeEvidence = useCallback(() => {
    setSelectedEvidenceAssetId(undefined)
    globalThis.requestAnimationFrame(() => evidenceTriggerRef.current?.focus())
  }, [])

  useEffect(() => {
    const dialog = evidenceDialogRef.current
    if (!selectedEvidenceAssetId || !dialog) return
    const focusable = dialog.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), '
      + 'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )
    ;(focusable[0] ?? dialog).focus()
    const containDialogFocus = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeEvidence()
        return
      }
      if (event.key !== 'Tab' || focusable.length === 0) return
      const first = focusable.item(0)
      const last = focusable.item(focusable.length - 1)
      if (!first || !last) return
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    dialog.addEventListener('keydown', containDialogFocus)
    return () => dialog.removeEventListener('keydown', containDialogFocus)
  }, [closeEvidence, selectedEvidenceAssetId])

  const latestAssistant = useMemo(
    () => [...messages].reverse().find((message) => message.role === 'assistant'),
    [messages],
  )
  const visibleAssistant = loading ? undefined : latestAssistant
  const providerPolicyUnavailable = visibleAssistant?.workflow?.some(
    (step) => step.detail_code === 'INFERENCE_PROVIDER_POLICY_BINDING_UNAVAILABLE',
  ) ?? false
  const latestEvidence = useMemo(
    () => [...(visibleAssistant?.evidence ?? [])].sort((left, right) => left.rank - right.rank),
    [visibleAssistant],
  )
  const selectedModeDescription = modeOptions.find((option) => option.value === mode)?.description ?? ''

  const loadSession = async (id: string) => {
    const requestVersion = ++historyRequestVersion.current
    setLoading(true)
    setError(undefined)
    setSelectedEvidenceAssetId(undefined)
    try {
      const history = await client.request<ChatMessage[]>(`/chat/sessions/${id}/messages?limit=200`)
      if (historyRequestVersion.current !== requestVersion) return
      setSessionId(id)
      setMessages(history.map(historyMessage))
      setPersistence(undefined)
    } catch (next) {
      if (historyRequestVersion.current === requestVersion) setError(next)
    } finally {
      if (historyRequestVersion.current === requestVersion) setLoading(false)
    }
  }

  const startNewSession = () => {
    historyRequestVersion.current += 1
    setSessionId(undefined)
    setQuestion('')
    setMode('AUTO')
    setMessages([])
    setPersistence(undefined)
    setSelectedEvidenceAssetId(undefined)
    setCopyFeedback(undefined)
    setError(undefined)
    setLoading(false)
  }

  const updateFavorite = async (session: ChatSession) => {
    if (favoriteSessionId) return
    setFavoriteSessionId(session.id)
    setError(undefined)
    try {
      const updated = await client.request<ChatSession>(`/chat/sessions/${session.id}/favorite`, {
        method: 'PATCH',
        body: JSON.stringify({
          is_favorite: !session.is_favorite,
          expected_version: session.version,
        }),
      })
      setSessions((current) => current.map((item) => item.id === updated.id ? updated : item))
    } catch (next) {
      await refreshSessions()
      setError(next)
    } finally {
      setFavoriteSessionId(undefined)
    }
  }

  const copyMessage = async (message: ChatViewMessage) => {
    const label = message.role === 'user' ? '질문' : '답변'
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable')
      await navigator.clipboard.writeText(message.text)
      setCopyFeedback({ messageId: message.id, status: 'SUCCESS', label })
    } catch {
      setCopyFeedback({ messageId: message.id, status: 'FAILED', label })
    }
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const text = question.trim()
    if (text.length < 2 || loading) return
    const pendingMessageId = `pending-${crypto.randomUUID()}`
    setMessages((current) => [...current, { id: pendingMessageId, role: 'user', text }])
    setQuestion('')
    setLoading(true)
    setError(undefined)
    setCopyFeedback(undefined)
    setPersistence(undefined)
    setSelectedEvidenceAssetId(undefined)
    try {
      const result = await client.request<ChatResponse>('/chat/query', {
        method: 'POST',
        body: JSON.stringify({
          session_id: sessionId,
          question: text,
          maximum_evidence: 5,
          mode,
        }),
      })
      setSessionId(result.session_id)
      setPersistence(result.persistence)
      setMessages((current) => [
        ...current.map((message) => message.id === pendingMessageId
          ? { ...message, id: result.request_message_id }
          : message),
        {
          id: result.response_message_id,
          role: 'assistant',
          text: result.answer,
          evidence: result.evidence,
          route: result.route,
          workflow: result.workflow,
        },
      ])
      await refreshSessions()
    } catch (next) {
      setMessages((current) => current.filter((message) => message.id !== pendingMessageId))
      setQuestion(text)
      setError(next)
    } finally {
      setLoading(false)
    }
  }

  const submitOnEnter = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key !== 'Enter'
      || event.shiftKey
      || event.nativeEvent.isComposing
    ) return
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
            <MessageSquarePlus size={13} />새 세션
          </button>
        )}
        description="인가·라우팅·검색·인용 검증 상태를 서버 응답 그대로 보여주는 근거 중심 카탈로그 Chat입니다."
        eyebrow="Evidence-first Assistant"
        icon="AI"
        title="카탈로그 Chat"
      />
      <p className="callout">브라우저는 모델이나 엔드포인트를 선택하지 않습니다. 배포 환경에서 활성화된 서버 어댑터와 인가된 카탈로그 근거만 사용합니다.</p>
      {persistence === 'EPHEMERAL_NO_STORE' && <p className="callout" role="status">개발 검증 세션입니다. 활성 보존정책이 없으므로 이 대화는 서버에 저장되지 않습니다.</p>}
      <ErrorNotice error={error} />
      <div className="chat-workspace">
        <aside className="chat-session-panel panel">
          <header><span className="eyebrow">Session</span><h2>대화 이력</h2></header>
          {!sessionId && (
            <button className="active" type="button">
              <Sparkles size={13} />
              <span>
                <strong>새 질문 세션</strong>
                <small>{messages.length ? `${messages.length} messages` : '질문을 시작하세요'}</small>
              </span>
            </button>
          )}
          <div aria-label="최근 대화 세션" className="chat-sessions-list" style={{ flex: 1, overflowY: 'auto' }}>
            {sessions.map((session) => (
              <div className="flex items-center gap-1 px-2 py-1" key={session.id}>
                <button
                  className={session.id === sessionId ? 'active min-w-0 flex-1' : 'min-w-0 flex-1'}
                  disabled={loading}
                  onClick={() => void loadSession(session.id)}
                  type="button"
                >
                  <Sparkles size={13} />
                  <span>
                    <strong>{session.title || '새 대화'}</strong>
                    <small>{session.message_count} messages</small>
                  </span>
                </button>
                <button
                  aria-label={`${session.title || '새 대화'} ${session.is_favorite ? '즐겨찾기 해제' : '즐겨찾기 추가'}`}
                  className="shrink-0 p-1"
                  disabled={favoriteSessionId === session.id}
                  onClick={() => void updateFavorite(session)}
                  title={session.is_favorite ? '즐겨찾기 해제' : '즐겨찾기 추가'}
                  type="button"
                >
                  <Star fill={session.is_favorite ? 'currentColor' : 'none'} size={13} />
                </button>
              </div>
            ))}
            {sessions.length === 0 && <p className="px-2">저장된 대화가 없습니다.</p>}
          </div>
          <p>최근 최대 50개 세션과 세션당 최대 200개 메시지만 조회합니다.</p>
        </aside>
        <main className="chat-conversation panel">
          <header>
            <div>
              <span className="eyebrow">
                {visibleAssistant?.route
                  ? `${modeLabels[visibleAssistant.route.selected_mode]} · ${adapterStateLabels[visibleAssistant.route.adapter_state]}`
                  : `${mode} · 서버 결정 대기`}
              </span>
              <h2>질문과 답변</h2>
            </div>
            <span>{loading ? '서버 응답 대기 중' : '준비됨'}</span>
          </header>
          <div className="chat-log" aria-live="polite">
            {messages.map((message) => (
              <article className={`message message-${message.role}`} key={message.id}>
                {message.role === 'assistant'
                  ? <SafeMarkdown value={message.text} />
                  : <p>{message.text}</p>}
                <button
                  aria-label={`${message.role === 'user' ? '질문' : '답변'} 복사`}
                  className="mt-2 inline-flex items-center gap-1 text-[10px] opacity-80"
                  onClick={() => void copyMessage(message)}
                  type="button"
                >
                  {copyFeedback?.messageId === message.id && copyFeedback.status === 'SUCCESS'
                    ? <Check size={11} />
                    : <Copy size={11} />}
                  복사
                </button>
              </article>
            ))}
            {messages.length === 0 && <div className="empty-state">접근 가능한 데이터셋, 소유권, 품질과 영향 관계를 질문해 보세요.</div>}
          </div>
          {copyFeedback && (
            <p className={copyFeedback.status === 'SUCCESS' ? 'notice' : 'notice notice-error'} role="status">
              {copyFeedback.label} {copyFeedback.status === 'SUCCESS' ? '복사 완료' : '복사 실패'}
            </p>
          )}
          <form className="chat-form" onSubmit={(event) => void submit(event)}>
            <div className="grid min-w-0 gap-2 md:grid-cols-[140px_minmax(0,1fr)]">
              <div className="grid content-start gap-1">
                <label className="text-xs font-bold" htmlFor="chat-route-mode">검색 경로</label>
                <select
                  disabled={loading}
                  id="chat-route-mode"
                  onChange={(event) => setMode(event.target.value as ChatMode)}
                  value={mode}
                >
                  {modeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
                <small>{selectedModeDescription}</small>
              </div>
              <div className="grid min-w-0 gap-1">
                <label className="sr-only" htmlFor="chat-question">카탈로그 질문</label>
                <textarea
                  aria-describedby="chat-keyboard-hint"
                  aria-keyshortcuts="Enter"
                  disabled={loading}
                  id="chat-question"
                  maxLength={4000}
                  onChange={(event) => setQuestion(event.target.value)}
                  onKeyDown={submitOnEnter}
                  placeholder="예: 고객 주문 데이터는 어떤 테이블에 있나요?"
                  value={question}
                />
                <small id="chat-keyboard-hint">Enter 전송 · Shift+Enter 줄바꿈</small>
              </div>
            </div>
            <button className="button" disabled={loading || question.trim().length < 2}>
              <Send size={14} />{loading ? '응답 대기 중…' : '질문'}
            </button>
          </form>
        </main>
        <aside className="chat-evidence-panel panel">
          <header><PanelRight size={15} /><div><span className="eyebrow">Evidence</span><h2>근거와 상태</h2></div></header>
          {visibleAssistant?.route && (
            <section className="grid gap-1 border-b border-slate-200 p-2 text-[10px]" aria-label="서버 라우팅 결정">
              <strong className="flex items-center gap-1 text-navy-900"><Route size={12} />서버 라우팅</strong>
              <span>요청 {modeLabels[visibleAssistant.route.requested_mode]} → 선택 {modeLabels[visibleAssistant.route.selected_mode]}</span>
              <span>
                {routeReasonLabels[visibleAssistant.route.reason]}
                {' · '}
                {adapterStateLabels[visibleAssistant.route.adapter_state]}
              </span>
            </section>
          )}
          {providerPolicyUnavailable && (
            <p
              className="m-2 border border-amber-200 bg-amber-50 p-2 text-[10px] text-amber-900"
              role="status"
            >
              모델 서버 상태와 별개로, 현재 분류 정책에 승인된 추론 프로필이 연결되지 않았습니다.
              관리자에게 provider-profile 승인 및 환경 설정 반영을 요청하세요.
            </p>
          )}
          {visibleAssistant?.workflow?.length ? (
            <ol aria-label="질문 응답 Workflow" className="grid gap-1 border-b border-slate-200 p-2">
              {visibleAssistant.workflow.map((step, index) => (
                <li className={`grid gap-1 border p-2 text-[9px] ${workflowTone(step.status)}`} key={`${step.stage}-${index}`}>
                  <strong>{index + 1}. {workflowLabels[step.stage]}</strong>
                  <span>{workflowStatusLabels[step.status]}</span>
                  <span title={step.detail_code}>{workflowDetailLabel(step.detail_code)}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="chat-evidence-empty p-2">서버가 응답하면 실제 처리 단계가 표시됩니다.</p>
          )}
          <AccordionItem
            expanded={evidenceExpanded}
            itemId="citations"
            onToggle={() => setEvidenceExpanded((value) => !value)}
            summary={`${latestEvidence.length} items`}
            title="인가된 인용 근거"
          >
            <ol className="chat-evidence-list">
              {latestEvidence.map((item) => (
                <li key={item.chunk_id}>
                  <button
                    aria-label={`근거 ${item.rank} ${item.name} 상세 열기`}
                    className="grid w-full gap-1 text-left"
                    onClick={(event) => {
                      evidenceTriggerRef.current = event.currentTarget
                      setSelectedEvidenceAssetId(item.resource_id)
                    }}
                    type="button"
                  >
                    <strong>#{item.rank} · {item.name}</strong>
                    <span>{item.classification} · {item.source_type}</span>
                    {item.description && <span>{item.description}</span>}
                    <span className="inline-flex items-center gap-1"><GitBranch size={10} />{item.retrieval_method}</span>
                    <code>{item.source_locator}</code>
                    <small>v{item.source_version} · {item.extraction_method}</small>
                  </button>
                </li>
              ))}
              {latestEvidence.length === 0 && <li className="chat-evidence-empty">답변이 생성되면 인가되고 인용 검증된 테이블만 표시됩니다.</li>}
            </ol>
          </AccordionItem>
        </aside>
      </div>
      {selectedEvidenceAssetId && (
        <div
          aria-label="근거 테이블 상세와 Lineage"
          aria-modal="true"
          ref={evidenceDialogRef}
          role="dialog"
          tabIndex={-1}
        >
          <CatalogDetailPane
            asOverlay
            assetId={selectedEvidenceAssetId}
            client={client}
            key={selectedEvidenceAssetId}
            onClose={closeEvidence}
            onSelectAsset={setSelectedEvidenceAssetId}
          />
        </div>
      )}
    </section>
  )
}
