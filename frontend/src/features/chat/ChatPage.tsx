import { useState, type FormEvent } from 'react'
import type { ApiClient } from '../../api/client'
import type { ChatResponse } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { PageTitle } from '../../components/layout/PageTitle'

export function ChatPage({ client }: { client: ApiClient }) {
  const [question, setQuestion] = useState('')
  const [sessionId, setSessionId] = useState<string>()
  const [messages, setMessages] = useState<Array<{ role: string; text: string; evidence?: ChatResponse['evidence'] }>>([])
  const [error, setError] = useState<unknown>()
  const [loading, setLoading] = useState(false)

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
      <PageTitle icon="AI" eyebrow="Evidence-first Assistant" title="카탈로그 Chat" description="인가되고 버전이 고정된 근거만 사용하며 citation이 없으면 검증 불가로 종료합니다." />
      <p className="callout">현재 모드는 외부 LLM에 데이터를 보내지 않으며, ABAC 검증을 통과한 카탈로그 근거만 답변합니다.</p>
      <ErrorNotice error={error} />
      <div className="chat-log" aria-live="polite">
        {messages.map((message, index) => (
          <article className={`message message-${message.role}`} key={`${message.role}-${index}`}>
            <p>{message.text}</p>
            {message.evidence && message.evidence.length > 0 && (
              <ol className="citations">{message.evidence.map((item) => <li key={item.chunk_id}><strong>{item.name}</strong><code>{item.source_locator}</code></li>)}</ol>
            )}
          </article>
        ))}
        {messages.length === 0 && <div className="empty-state">접근 가능한 데이터셋, 소유권, 설명을 질문해 보세요.</div>}
      </div>
      <form className="chat-form" onSubmit={(event) => void submit(event)}>
        <textarea value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={4000} placeholder="예: Wafer yield 데이터는 어디에서 관리하나요?" />
        <button className="button" disabled={loading}>{loading ? '근거 확인 중…' : '질문'}</button>
      </form>
    </section>
  )
}
