import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type { ChangeRequestRecord } from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'

const nextStates: Record<string, string[]> = {
  REGISTERED: ['IN_REVIEW', 'CANCELLED'],
  IN_REVIEW: ['TESTING', 'FINAL_REVIEW', 'REJECTED', 'CANCELLED'],
  TESTING: ['IN_REVIEW', 'FINAL_REVIEW', 'REJECTED', 'CANCELLED'],
  FINAL_REVIEW: ['APPLY_QUEUED', 'REJECTED', 'CANCELLED'],
  APPLY_FAILED: ['APPLY_QUEUED', 'CANCELLED'],
}

export function GovernancePage({ client }: { client: ApiClient }) {
  const [title, setTitle] = useState('')
  const [targetRef, setTargetRef] = useState('')
  const [aspectName, setAspectName] = useState('datasetProperties')
  const [description, setDescription] = useState('')
  const [classification, setClassification] = useState('INTERNAL')
  const [documentText, setDocumentText] = useState('{\n  "description": ""\n}')
  const [requests, setRequests] = useState<ChangeRequestRecord[]>([])
  const [selected, setSelected] = useState<ChangeRequestRecord>()
  const [reason, setReason] = useState('검토 기준을 충족했습니다.')
  const [error, setError] = useState<unknown>()
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const value = await client.request<{ items: ChangeRequestRecord[] }>('/change-requests?limit=50')
      setRequests(value.items)
      setSelected((current) => current ? value.items.find((item) => item.id === current.id) ?? current : value.items[0])
    } catch (next) { setError(next) }
  }, [client])

  useEffect(() => { void load() }, [load])

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(undefined); setBusy(true)
    try {
      const parsed: unknown = JSON.parse(documentText)
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('Aspect 문서는 JSON 객체여야 합니다.')
      const next = await client.request<ChangeRequestRecord>('/change-requests', {
        method: 'POST',
        idempotencyKey: newIdempotencyKey('change-create'),
        body: JSON.stringify({
          request_type: 'CATALOG_METADATA', title, description, classification,
          items: [{
            target_type: 'DATAHUB_ASPECT', target_ref: targetRef, aspect_name: aspectName,
            operation: 'UPSERT', after_document: parsed,
          }],
        }),
      })
      setSelected(next); setRequests((current) => [next, ...current.filter((item) => item.id !== next.id)])
      setTitle(''); setDescription('')
    } catch (next) { setError(next) } finally { setBusy(false) }
  }

  const mutate = async (path: string, body: object) => {
    if (!selected) return
    setBusy(true); setError(undefined)
    try {
      const next = await client.request<ChangeRequestRecord>(path, {
        method: 'POST',
        idempotencyKey: newIdempotencyKey('change-action'),
        ifMatch: `"${selected.version}"`,
        body: JSON.stringify(body),
      })
      setSelected(next)
      setRequests((current) => current.map((item) => item.id === next.id ? next : item))
    } catch (next) { setError(next) } finally { setBusy(false) }
  }

  return (
    <section>
      <div className="page-heading"><div><p className="eyebrow">Four-eyes Governance</p><h2>변경 요청과 승인</h2></div><button className="button button-secondary" onClick={() => void load()}>새로고침</button></div>
      <div className="panel-grid governance-grid">
        <form className="panel form-stack" onSubmit={(event) => void submit(event)}>
          <h3>DataHub aspect 변경 제안</h3>
          <label>제목<input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={500} required /></label>
          <label>DataHub 대상 URN<input value={targetRef} onChange={(event) => setTargetRef(event.target.value)} placeholder="urn:li:dataset:..." pattern="urn:li:.*" required /></label>
          <label>Aspect 이름<input value={aspectName} onChange={(event) => setAspectName(event.target.value)} pattern="[A-Za-z][A-Za-z0-9]*" required /></label>
          <label>승인 대상 JSON<textarea className="code-editor" value={documentText} onChange={(event) => setDocumentText(event.target.value)} required /></label>
          <label>분류등급<select value={classification} onChange={(event) => setClassification(event.target.value)}><option>PUBLIC</option><option>INTERNAL</option><option>CONFIDENTIAL</option><option>RESTRICTED</option></select></label>
          <label>변경 사유<textarea value={description} onChange={(event) => setDescription(event.target.value)} maxLength={10000} /></label>
          <button className="button" disabled={busy}>{busy ? '처리 중…' : '변경 요청 생성'}</button>
        </form>
        <div className="panel">
          <h3>최근 요청</h3>
          <div className="compact-list">
            {requests.map((item) => <button className={selected?.id === item.id ? 'selected' : ''} key={item.id} onClick={() => setSelected(item)}><span><strong>{item.number}</strong><small>{item.title}</small></span><span className="badge">{item.state}</span></button>)}
            {!requests.length && <p className="muted">조회 가능한 요청이 없습니다.</p>}
          </div>
        </div>
      </div>
      <ErrorNotice error={error} />
      {selected && <article className="result-card governance-detail">
        <div><span className="badge">{selected.state}</span><span className="badge badge-soft">{selected.classification}</span></div>
        <h3>{selected.number} · {selected.title}</h3>
        <p>{selected.description || '설명 없음'} · 버전 {selected.version}</p>
        <label>판단 사유<input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={4000} /></label>
        <div className="action-row">
          {selected.state === 'IN_REVIEW' && <button className="button button-secondary" disabled={busy} onClick={() => void mutate(`/change-requests/${selected.id}/approvals`, { stage: 'REVIEW', decision: 'APPROVED', reason })}>검토 기록</button>}
          {selected.state === 'FINAL_REVIEW' && <button className="button" disabled={busy} onClick={() => void mutate(`/change-requests/${selected.id}/approvals`, { stage: 'FINAL', decision: 'APPROVED', reason })}>최종 승인</button>}
          {(nextStates[selected.state] ?? []).map((state) => <button className="button button-secondary" disabled={busy || (state === 'APPLY_QUEUED' && !selected.approvals.some((approval) => approval.stage === 'FINAL' && approval.decision === 'APPROVED'))} key={state} onClick={() => void mutate(`/change-requests/${selected.id}/transitions`, { target_state: state, reason })}>{state}</button>)}
        </div>
        <div className="audit-grid">
          <div><h4>승인</h4>{selected.approvals.map((item) => <p key={item.id}><strong>{item.stage} · {item.decision}</strong><br /><small>{item.actor_id}</small></p>)}</div>
          <div><h4>전이 이력</h4>{selected.transitions.map((item) => <p key={item.id}><strong>{item.from_state} → {item.to_state}</strong><br /><small>{item.reason}</small></p>)}</div>
        </div>
        <code>{selected.id}</code>
      </article>}
    </section>
  )
}
