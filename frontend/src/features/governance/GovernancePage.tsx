import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type { ChangeRequestRecord } from '../../api/types'
import { AssuranceNotice, type AssuranceActions } from '../../components/AssuranceNotice'
import { ErrorNotice } from '../../components/ErrorNotice'
import { PageTitle } from '../../components/layout/PageTitle'

const nextStates: Record<string, string[]> = {
  REGISTERED: ['IN_REVIEW', 'CANCELLED'],
  IN_REVIEW: ['TESTING', 'FINAL_REVIEW', 'REJECTED', 'CANCELLED'],
  TESTING: ['IN_REVIEW', 'FINAL_REVIEW', 'REJECTED', 'CANCELLED'],
  FINAL_REVIEW: ['APPLY_QUEUED', 'REJECTED', 'CANCELLED'],
  APPLY_FAILED: ['APPLY_QUEUED', 'CANCELLED'],
}
const allowedAspects = [
  'datasetProperties', 'domains', 'globalTags', 'glossaryTerms', 'ownership', 'schemaMetadata',
] as const

export function GovernancePage({
  client,
  onStepUp,
  onPasswordReauth,
  onEnroll,
}: { client: ApiClient } & AssuranceActions) {
  const [title, setTitle] = useState('')
  const [targetRef, setTargetRef] = useState('')
  const [aspectName, setAspectName] = useState<(typeof allowedAspects)[number]>('datasetProperties')
  const [beforeHash, setBeforeHash] = useState('')
  const [description, setDescription] = useState('')
  const [classification, setClassification] = useState('INTERNAL')
  const [documentText, setDocumentText] = useState('{\n  "description": ""\n}')
  const [requests, setRequests] = useState<ChangeRequestRecord[]>([])
  const [selected, setSelected] = useState<ChangeRequestRecord>()
  const [reason, setReason] = useState('검토 기준을 충족했습니다.')
  const [error, setError] = useState<unknown>()
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  const controllers = useRef(new Set<AbortController>())

  const beginOperation = useCallback(() => {
    const controller = new AbortController()
    controllers.current.add(controller)
    return { controller, expectedGeneration: generation.current }
  }, [])

  const load = useCallback(async () => {
    const { controller, expectedGeneration } = beginOperation()
    try {
      const value = await client.request<{ items: ChangeRequestRecord[] }>('/change-requests?limit=50', {
        signal: controller.signal,
      })
      if (expectedGeneration !== generation.current) return
      setRequests(value.items)
      setSelected((current) => current ? value.items.find((item) => item.id === current.id) ?? current : value.items[0])
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    } finally { controllers.current.delete(controller) }
  }, [beginOperation, client])

  useEffect(() => {
    const activeControllers = controllers.current
    generation.current += 1
    activeControllers.forEach((controller) => controller.abort())
    activeControllers.clear()
    setRequests([]); setSelected(undefined); setError(undefined); setBusy(false)
    setTitle(''); setTargetRef(''); setAspectName('datasetProperties'); setBeforeHash('')
    setDescription(''); setClassification('INTERNAL')
    setDocumentText('{\n  "description": ""\n}')
    void load()
    return () => {
      generation.current += 1
      activeControllers.forEach((controller) => controller.abort())
      activeControllers.clear()
    }
  }, [client, load])

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(undefined); setBusy(true)
    const { controller, expectedGeneration } = beginOperation()
    try {
      const parsed: unknown = JSON.parse(documentText)
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('Aspect 문서는 JSON 객체여야 합니다.')
      const next = await client.request<ChangeRequestRecord>('/change-requests', {
        method: 'POST',
        idempotencyKey: newIdempotencyKey('change-create'),
        signal: controller.signal,
        body: JSON.stringify({
          request_type: 'CATALOG_METADATA', title, description, classification,
          items: [{
            target_type: 'DATAHUB_ASPECT', target_ref: targetRef, aspect_name: aspectName,
            operation: 'UPSERT', before_hash: beforeHash, after_document: parsed,
          }],
        }),
      })
      if (expectedGeneration !== generation.current) return
      setSelected(next); setRequests((current) => [next, ...current.filter((item) => item.id !== next.id)])
      setTitle(''); setDescription(''); setBeforeHash('')
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    } finally {
      controllers.current.delete(controller)
      if (expectedGeneration === generation.current) setBusy(false)
    }
  }

  const mutate = async (path: string, body: object) => {
    if (!selected) return
    const { controller, expectedGeneration } = beginOperation()
    setBusy(true); setError(undefined)
    try {
      const next = await client.request<ChangeRequestRecord>(path, {
        method: 'POST',
        idempotencyKey: newIdempotencyKey('change-action'),
        ifMatch: `"${selected.version}"`,
        signal: controller.signal,
        body: JSON.stringify(body),
      })
      if (expectedGeneration !== generation.current) return
      setSelected(next)
      setRequests((current) => current.map((item) => item.id === next.id ? next : item))
    } catch (next) {
      if (!controller.signal.aborted && expectedGeneration === generation.current) setError(next)
    } finally {
      controllers.current.delete(controller)
      if (expectedGeneration === generation.current) setBusy(false)
    }
  }

  return (
    <section>
      <PageTitle
        icon="CR"
        eyebrow="Four-eyes Governance"
        title="변경 요청과 승인"
        description="타입이 지정된 변경을 검토하고 Maker-Checker 상태 전이와 적용 증거를 관리합니다."
        actions={<button className="button button-secondary" onClick={() => void load()}>새로고침</button>}
      />
      <div className="panel-grid governance-grid">
        <form className="panel form-stack" onSubmit={(event) => void submit(event)}>
          <h3>DataHub aspect 변경 제안</h3>
          <p className="callout">이 화면은 현재 원본 hash를 알고 있는 통합·복구용 임시 제안 경로입니다. 일반 사용자의 typed 메타데이터 편집은 아직 잠겨 있습니다.</p>
          <label>제목<input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={500} required /></label>
          <label>DataHub 대상 URN<input value={targetRef} onChange={(event) => setTargetRef(event.target.value)} placeholder="urn:li:dataset:..." pattern="urn:li:dataset:.*" required /></label>
          <label>Aspect 이름<select value={aspectName} onChange={(event) => setAspectName(event.target.value as (typeof allowedAspects)[number])}>{allowedAspects.map((aspect) => <option key={aspect}>{aspect}</option>)}</select></label>
          <label>원본 Aspect SHA-256<input value={beforeHash} onChange={(event) => setBeforeHash(event.target.value)} pattern="[0-9a-f]{64}" minLength={64} maxLength={64} required /></label>
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
      <AssuranceNotice
        error={error}
        onStepUp={onStepUp}
        onPasswordReauth={onPasswordReauth}
        onEnroll={onEnroll}
      />
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
