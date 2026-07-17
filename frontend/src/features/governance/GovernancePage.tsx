import { useCallback, useEffect, useRef, useState } from 'react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type { ChangeRequestRecord } from '../../api/types'
import { pageUrl } from '../../app/navigation'
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
export function GovernancePage({
  client,
  onStepUp,
  onPasswordReauth,
  onEnroll,
}: { client: ApiClient } & AssuranceActions) {
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
    void load()
    return () => {
      generation.current += 1
      activeControllers.forEach((controller) => controller.abort())
      activeControllers.clear()
    }
  }, [client, load])

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
        <aside className="panel governance-typed-entry">
          <h3>변경 요청 등록</h3>
          <p className="callout">
            새 메타데이터 변경은 자산별 검증 규칙과 원본 hash 미리보기가 적용되는 등록관리에서 제안합니다.
            이 화면은 생성된 요청의 검토·승인과 적용 상태 관리에 집중합니다.
          </p>
          <a className="button" href={pageUrl('registration')}>등록관리에서 설명 변경 제안</a>
        </aside>
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
