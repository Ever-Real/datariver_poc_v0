import { useMemo, useState, type FormEvent } from 'react'
import { Bookmark, MessageSquarePlus, PanelRight, Send, Sparkles } from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type { ChatResponse } from '../../api/types'
import { AccordionItem } from '../../components/common/Accordion'
import { ErrorNotice } from '../../components/ErrorNotice'
import { PageTitle } from '../../components/layout/PageTitle'

export function ChatPage({ client }: { client: ApiClient }) {
  const [question, setQuestion] = useState('')
  const [sessionId, setSessionId] = useState<string>()
  const [messages, setMessages] = useState<Array<{ role: string; text: string; evidence?: ChatResponse['evidence'] }>>([])
  const [error, setError] = useState<unknown>()
  const [loading, setLoading] = useState(false)
  const [evidenceExpanded, setEvidenceExpanded] = useState(true)
  const latestEvidence = useMemo(() => [...messages].reverse().find((message) => message.evidence)?.evidence ?? [], [messages])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const text = question.trim()
    if (!text) return
    setMessages((current) => [...current, { role: 'user', text }])
    setQuestion(''); setLoading(true); setError(undefined)
    try {
      const result = await client.request<ChatResponse>('/chat/query', {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId, question: text, maximum_evidence: 5 }),
      })
      setSessionId(result.session_id)
      setMessages((current) => [...current, { role: 'assistant', text: result.answer, evidence: result.evidence }])
    } catch (next) { setError(next) } finally { setLoading(false) }
  }

  return (
    <section className="chat-page">
      <PageTitle icon="AI" eyebrow="Evidence-first Assistant" title="카탈로그 Chat" description="v0.3의 Chat·근거 패널 구성을 복원하되, 인가되고 버전이 고정된 근거만 답변에 사용합니다." actions={<button className="button button-secondary" type="button" disabled title="지속 세션 저장 계약은 아직 제공되지 않습니다."><MessageSquarePlus size={13} />새 세션</button>} />
      <p className="callout">현재 모드는 외부 LLM에 데이터를 보내지 않으며, ABAC 검증을 통과한 카탈로그 근거만 답변합니다.</p>
      <ErrorNotice error={error} />
      <div className="chat-workspace">
        <aside className="chat-session-panel panel"><header><span className="eyebrow">Session</span><h2>대화 이력</h2></header><button type="button" className="active"><Sparkles size={13} /><span><strong>{sessionId ? '현재 evidence 세션' : '새 질문 세션'}</strong><small>{messages.length ? `${messages.length} messages` : '질문을 시작하세요'}</small></span></button><p><Bookmark size={12} />즐겨찾기·이름변경·삭제는 서버 세션 계약이 준비되면 활성화됩니다.</p></aside>
        <main className="chat-conversation panel"><header><div><span className="eyebrow">AUTO · authorized evidence</span><h2>질문과 답변</h2></div><span>{loading ? '근거 검색 중' : 'READY'}</span></header><div className="chat-log" aria-live="polite">
          {messages.map((message, index) => <article className={`message message-${message.role}`} key={`${message.role}-${index}`}><p>{message.text}</p></article>)}
          {messages.length === 0 && <div className="empty-state">접근 가능한 데이터셋, 소유권, 설명을 질문해 보세요.</div>}
        </div><form className="chat-form" onSubmit={(event) => void submit(event)}><textarea value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={4000} placeholder="예: Wafer yield 데이터는 어디에서 관리하나요?" /><button className="button" disabled={loading}><Send size={14} />{loading ? '근거 확인 중…' : '질문'}</button></form></main>
        <aside className="chat-evidence-panel panel"><header><PanelRight size={15} /><div><span className="eyebrow">Evidence</span><h2>근거와 상태</h2></div></header><AccordionItem itemId="citations" title="인가된 인용 근거" summary={`${latestEvidence.length} items`} expanded={evidenceExpanded} onToggle={() => setEvidenceExpanded((value) => !value)}><ol className="chat-evidence-list">{latestEvidence.map((item) => <li key={item.chunk_id}><strong>{item.name}</strong><span>{item.classification} · {item.source_type}</span><code>{item.source_locator}</code><small>v{item.source_version} · {item.extraction_method}</small></li>)}{latestEvidence.length === 0 && <li className="chat-evidence-empty">답변이 생성되면 인가된 근거만 이 패널에 표시됩니다.</li>}</ol></AccordionItem></aside>
      </div>
    </section>
  )
}
