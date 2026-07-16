import { useCallback, useEffect, useState, type FormEvent } from 'react'
import type { AdminReadContext, ErasureRequest, ErasureTargetType } from '../../api/types'
import type { AssuranceActions } from '../../components/AssuranceNotice'
import type { AdminApi, VersionedErasureRequest } from './adminApi'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import type { AdminMessages } from './messages'

interface Props extends AssuranceActions {
  api: AdminApi
  context?: AdminReadContext
  messages: AdminMessages
  requestConfirmation: (mutation: PendingAdminMutation) => void
  keyFor: (intent: string, prefix: string) => string
  clearKey: (intent: string) => void
  reportError: (error: unknown) => void
}

export function ErasureAdmin({
  api,
  context,
  messages,
  requestConfirmation,
  keyFor,
  clearKey,
  reportError,
}: Props) {
  const [requests, setRequests] = useState<ErasureRequest[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [selected, setSelected] = useState<VersionedErasureRequest>()
  const [targetType, setTargetType] = useState<ErasureTargetType>('UPLOAD_OBJECT')
  const [targetId, setTargetId] = useState('')
  const [reviewTtlSeconds, setReviewTtlSeconds] = useState('')
  const [requestReason, setRequestReason] = useState('')
  const [decisionReason, setDecisionReason] = useState('')
  const canRequest = context?.allowed_operations.includes('ERASURE_REQUEST') ?? false
  const canApprove = context?.allowed_operations.includes('ERASURE_APPROVE') ?? false

  const load = useCallback(async () => {
    try {
      const next = await api.listErasureRequests()
      setRequests(next)
      setSelectedId((current) => current || next[0]?.erasure_request_id || '')
    } catch (error) { reportError(error) }
  }, [api, reportError])

  const loadSelected = useCallback(async (requestId: string) => {
    if (!requestId) {
      setSelected(undefined)
      return
    }
    try { setSelected(await api.getErasureRequest(requestId)) } catch (error) { reportError(error) }
  }, [api, reportError])

  useEffect(() => { void load() }, [load])
  useEffect(() => { void loadSelected(selectedId) }, [loadSelected, selectedId])

  const create = (event: FormEvent) => {
    event.preventDefault()
    const ttl = Number(reviewTtlSeconds)
    if (!Number.isInteger(ttl) || ttl < 300 || ttl > 604800) return
    const normalizedTarget = targetId.trim()
    const normalizedReason = requestReason.trim()
    const intent = `erasure-request:${targetType}:${normalizedTarget}:${ttl}:${normalizedReason}`
    requestConfirmation({
      title: messages.erasureRequest,
      summary: [targetType, normalizedTarget, `${messages.reviewTtlSeconds}: ${ttl}`],
      execute: async () => {
        const next = await api.requestErasure(
          targetType,
          normalizedTarget,
          normalizedReason,
          ttl,
          keyFor(intent, 'erasure-request'),
        )
        clearKey(intent)
        setTargetId('')
        setReviewTtlSeconds('')
        setRequestReason('')
        setRequests((current) => [next, ...current])
        setSelectedId(next.erasure_request_id)
        setSelected(next)
      },
    })
  }

  const decide = (decision: 'APPROVED' | 'REJECTED') => {
    if (!selected || !decisionReason.trim()) return
    const reason = decisionReason.trim()
    const intent = `erasure-decision:${selected.erasure_request_id}:${selected.etag}:${decision}:${reason}`
    requestConfirmation({
      title: `${messages.erasureDecision}: ${decision}`,
      summary: [selected.target_type, selected.target_id, selected.payload_hash, selected.etag],
      execute: async () => {
        const next = await api.decideErasure(
          selected,
          decision,
          reason,
          keyFor(intent, 'erasure-decision'),
        )
        clearKey(intent)
        setDecisionReason('')
        setSelected(next)
        setRequests((current) => current.map((item) => (
          item.erasure_request_id === next.erasure_request_id ? next : item
        )))
      },
    })
  }

  const isOwner = selected && (
    context?.subject_id === selected.target_owner_id
    || (selected.target_type === 'SUBJECT_DATA' && context?.subject_id === selected.target_id)
  )
  const canDecide = Boolean(
    canApprove
    && selected?.state === 'PENDING'
    && context
    && context.subject_id !== selected.requester_id
    && !isOwner,
  )

  return <>
    <div className={canRequest ? 'admin-two-column' : ''}>
      {canRequest && <form className="panel form-stack" onSubmit={create}>
        <h3>{messages.erasureRequest}</h3>
        <label>{messages.targetType}<select value={targetType} onChange={(event) => setTargetType(event.target.value as ErasureTargetType)}><option>SUBJECT_DATA</option><option>CHAT_SESSION</option><option>UPLOAD_OBJECT</option></select></label>
        <label>{messages.targetId}<input value={targetId} onChange={(event) => setTargetId(event.target.value)} required pattern="[0-9a-fA-F-]{36}" /></label>
        <label>{messages.reviewTtlSeconds}<input type="number" min={300} max={604800} value={reviewTtlSeconds} onChange={(event) => setReviewTtlSeconds(event.target.value)} required /></label>
        <label>{messages.reason}<textarea value={requestReason} onChange={(event) => setRequestReason(event.target.value)} maxLength={4000} required /></label>
        <button className="button">{messages.requestReview}</button>
        <p className="callout">{messages.erasureNonExecuting}</p>
      </form>}
      <section className="panel">
        <div className="section-heading"><h3>{messages.erasureHistory}</h3><button className="button button-secondary" onClick={() => void load()}>{messages.refresh}</button></div>
        <div className="compact-list">{requests.map((request) => <button key={request.erasure_request_id} className={selectedId === request.erasure_request_id ? 'selected' : ''} onClick={() => setSelectedId(request.erasure_request_id)}><span><strong>{request.target_type}</strong><small>{request.target_id}</small></span><span className="badge">{request.state}</span></button>)}</div>
      </section>
    </div>
    {selected && <section className="result-card governance-detail form-stack">
      <h3>{selected.target_type} · {selected.state}</h3>
      <dl className="summary-list">
        <div><dt>{messages.targetId}</dt><dd>{selected.target_id}</dd></div>
        <div><dt>{messages.targetVersion}</dt><dd>{selected.target_version}</dd></div>
        <div><dt>{messages.clearance}</dt><dd>{selected.classification}</dd></div>
        <div><dt>maker</dt><dd>{selected.requester_id}</dd></div>
        <div><dt>{messages.expiresAt}</dt><dd>{new Date(selected.expires_at).toLocaleString()}</dd></div>
        <div><dt>ETag</dt><dd>{selected.etag}</dd></div>
        <div><dt>{messages.payloadHash}</dt><dd>{selected.payload_hash}</dd></div>
        <div><dt>policy hash</dt><dd>{selected.retention_policy_hash}</dd></div>
        <div><dt>execution</dt><dd>{selected.execution_state}</dd></div>
      </dl>
      <p>{selected.request_reason}</p>
      {selected.state === 'PENDING' && <label>{messages.reason}<textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} maxLength={4000} /></label>}
      <div className="action-row">
        {canDecide && <><button className="button" disabled={!decisionReason.trim()} onClick={() => decide('APPROVED')}>{messages.approve}</button><button className="button button-secondary" disabled={!decisionReason.trim()} onClick={() => decide('REJECTED')}>{messages.reject}</button></>}
        {selected.state === 'PENDING' && !canDecide && <p className="callout">{messages.makerCannotCheck}</p>}
      </div>
      <p className="notice notice-error" role="note">{messages.erasureNonExecuting}</p>
    </section>}
  </>
}
