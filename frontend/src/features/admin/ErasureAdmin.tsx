import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import type {
  AdminReadContext,
  ErasureRequest,
  ErasureRequestState,
  ErasureTargetType,
  RetentionExecutionEvidence,
} from '../../api/types'
import type { AssuranceActions } from '../../components/AssuranceNotice'
import { useAbortSignalChannel } from '../../components/common/useAbortSignalChannel'
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
  const [executionEvidence, setExecutionEvidence] = useState<{
    requestId: string
    value: RetentionExecutionEvidence
  }>()
  const [targetType, setTargetType] = useState<ErasureTargetType>('UPLOAD_OBJECT')
  const [targetId, setTargetId] = useState('')
  const [reviewTtlSeconds, setReviewTtlSeconds] = useState('')
  const [requestReason, setRequestReason] = useState('')
  const [decisionReason, setDecisionReason] = useState('')
  const [stateFilter, setStateFilter] = useState<ErasureRequestState | ''>('')
  const [cursor, setCursor] = useState<string>()
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [pageNumber, setPageNumber] = useState(1)
  const listGeneration = useRef(0)
  const listChannel = useAbortSignalChannel()
  const detailChannel = useAbortSignalChannel()
  const canRequest = context?.allowed_operations.includes('ERASURE_REQUEST') ?? false
  const canApprove = context?.allowed_operations.includes('ERASURE_APPROVE') ?? false

  const load = useCallback(async (pageCursor: string | undefined, signal?: AbortSignal) => {
    const generation = ++listGeneration.current
    try {
      const page = await api.listErasureRequestPage({
        state: stateFilter || undefined,
        cursor: pageCursor,
        limit: 25,
        signal,
      })
      if (generation !== listGeneration.current) return
      setRequests(page.items)
      setNextCursor(page.nextCursor)
      setSelectedId((current) => (
        current && page.items.some((request) => request.erasure_request_id === current)
          ? current
          : page.items[0]?.erasure_request_id || ''
      ))
    } catch (error) {
      if (!signal?.aborted && generation === listGeneration.current) reportError(error)
    }
  }, [api, reportError, stateFilter])

  const resetPage = () => {
    setCursor(undefined)
    setCursorHistory([])
    setNextCursor(null)
    setPageNumber(1)
  }
  const reloadFirstPage = async () => {
    const alreadyFirstPage = cursor === undefined
    resetPage()
    if (alreadyFirstPage) await load(undefined, listChannel.next())
  }

  const loadSelected = useCallback(async (requestId: string, signal?: AbortSignal) => {
    if (!requestId) {
      setSelected(undefined)
      return
    }
    try {
      const next = await api.getErasureRequest(requestId, signal)
      if (!signal?.aborted) setSelected(next)
    } catch (error) {
      if (!signal?.aborted) reportError(error)
    }
  }, [api, reportError])

  const loadExecutionEvidence = useCallback(async (requestId: string, signal?: AbortSignal) => {
    try {
      const value = await api.getErasureExecutionEvidence(requestId, signal)
      if (!signal?.aborted) setExecutionEvidence({ requestId, value })
    } catch (error) {
      if (!signal?.aborted) reportError(error)
    }
  }, [api, reportError])

  useEffect(() => {
    void load(cursor, listChannel.next())
    return () => { listGeneration.current += 1 }
  }, [cursor, listChannel, load])
  useEffect(() => {
    const signal = detailChannel.next()
    setSelected(undefined)
    setExecutionEvidence(undefined)
    if (selectedId) {
      void loadSelected(selectedId, signal)
      void loadExecutionEvidence(selectedId, signal)
    }
  }, [detailChannel, loadExecutionEvidence, loadSelected, selectedId])
  const current = selected?.erasure_request_id === selectedId ? selected : undefined
  const currentEvidence = executionEvidence?.requestId === selectedId
    && executionEvidence.value.erasure_request_id === selectedId
    ? executionEvidence.value
    : undefined

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
        await reloadFirstPage()
        setSelectedId(next.erasure_request_id)
      },
    })
  }

  const decide = (decision: 'APPROVED' | 'REJECTED') => {
    if (!current || !decisionReason.trim()) return
    const reason = decisionReason.trim()
    const targetRequestId = current.erasure_request_id
    const intent = `erasure-decision:${targetRequestId}:${current.etag}:${decision}:${reason}`
    requestConfirmation({
      title: `${messages.erasureDecision}: ${decision}`,
      summary: [current.target_type, current.target_id, current.payload_hash, current.etag],
      execute: async () => {
        if (targetRequestId !== selectedId) return
        const next = await api.decideErasure(
          current,
          decision,
          reason,
          keyFor(intent, 'erasure-decision'),
        )
        clearKey(intent)
        setDecisionReason('')
        await reloadFirstPage()
        setSelectedId(next.erasure_request_id)
      },
    })
  }

  const isOwner = current && (
    context?.subject_id === current.target_owner_id
    || (current.target_type === 'SUBJECT_DATA' && context?.subject_id === current.target_id)
  )
  const canDecide = Boolean(
    canApprove
    && current?.state === 'PENDING'
    && context
    && context.subject_id !== current.requester_id
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
        <div className="section-heading"><h3>{messages.erasureHistory}</h3><button className="button button-secondary" onClick={() => void load(cursor, listChannel.next())}>{messages.refresh}</button></div>
        <label>상태 필터<select value={stateFilter} onChange={(event) => { setStateFilter(event.target.value as ErasureRequestState | ''); resetPage() }}><option value="">전체</option><option>PENDING</option><option>APPROVED</option><option>REJECTED</option></select></label>
        <div className="compact-list">{requests.map((request) => <button key={request.erasure_request_id} className={selectedId === request.erasure_request_id ? 'selected' : ''} onClick={() => setSelectedId(request.erasure_request_id)}><span><strong>{request.target_type}</strong><small>{request.target_id}</small></span><span className="badge">{request.state}</span></button>)}</div>
        <nav className="action-row" aria-label="서버 페이지 탐색">
          <button
            type="button"
            className="button button-secondary"
            disabled={cursorHistory.length === 0}
            onClick={() => {
              const previous = cursorHistory.at(-1) ?? null
              setCursorHistory((history) => history.slice(0, -1))
              setCursor(previous ?? undefined)
              setPageNumber((page) => Math.max(1, page - 1))
            }}
          >이전</button>
          <span>페이지 {pageNumber}</span>
          <button
            type="button"
            className="button button-secondary"
            disabled={!nextCursor}
            onClick={() => {
              if (!nextCursor) return
              setCursorHistory((history) => [...history.slice(-49), cursor ?? null])
              setCursor(nextCursor)
              setPageNumber((page) => page + 1)
            }}
          >다음</button>
        </nav>
      </section>
    </div>
    {current && <section className="result-card governance-detail form-stack">
      <h3>{current.target_type} · {current.state}</h3>
      <dl className="summary-list">
        <div><dt>{messages.targetId}</dt><dd>{current.target_id}</dd></div>
        <div><dt>{messages.targetVersion}</dt><dd>{current.target_version}</dd></div>
        <div><dt>{messages.clearance}</dt><dd>{current.classification}</dd></div>
        <div><dt>maker</dt><dd>{current.requester_id}</dd></div>
        <div><dt>{messages.expiresAt}</dt><dd>{new Date(current.expires_at).toLocaleString()}</dd></div>
        <div><dt>ETag</dt><dd>{current.etag}</dd></div>
        <div><dt>{messages.payloadHash}</dt><dd>{current.payload_hash}</dd></div>
        <div><dt>policy hash</dt><dd>{current.retention_policy_hash}</dd></div>
        <div><dt>execution</dt><dd>{current.execution_state}</dd></div>
      </dl>
      <p>{current.request_reason}</p>
      {current.state === 'PENDING' && <label>{messages.reason}<textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} maxLength={4000} /></label>}
      <div className="action-row">
        {canDecide && <><button className="button" disabled={!decisionReason.trim()} onClick={() => decide('APPROVED')}>{messages.approve}</button><button className="button button-secondary" disabled={!decisionReason.trim()} onClick={() => decide('REJECTED')}>{messages.reject}</button></>}
        {current.state === 'PENDING' && !canDecide && <p className="callout">{messages.makerCannotCheck}</p>}
      </div>
      <p className="notice notice-error" role="note">{messages.erasureNonExecuting}</p>
      {currentEvidence && <section className="panel form-stack" aria-label="Archive execution evidence">
        <h4>Archive-only execution evidence</h4>
        <dl className="summary-list">
          <div><dt>availability</dt><dd>{currentEvidence.availability}</dd></div>
          <div><dt>archive only</dt><dd>{String(currentEvidence.archive_only)}</dd></div>
          <div><dt>deletion automation</dt><dd>{currentEvidence.deletion_automation_state}</dd></div>
        </dl>
        {currentEvidence.job && <>
          <dl className="summary-list">
            <div><dt>job state</dt><dd>{currentEvidence.job.state}</dd></div>
            <div><dt>destructive state</dt><dd>{currentEvidence.job.destructive_state}</dd></div>
            <div><dt>separation of duties</dt><dd>{currentEvidence.job.separation_of_duties_verified ? 'VERIFIED' : 'INVALID'}</dd></div>
            <div><dt>attempts</dt><dd>{currentEvidence.job.attempt_count} / {currentEvidence.job.maximum_attempts}</dd></div>
            <div><dt>archive retain until</dt><dd>{new Date(currentEvidence.job.archive_retain_until).toLocaleString()}</dd></div>
            <div><dt>command hash</dt><dd><code>{currentEvidence.job.command_hash}</code></dd></div>
          </dl>
          {currentEvidence.job.attempts.map((attempt) => <p key={attempt.attempt_no}>
            attempt {attempt.attempt_no} · {attempt.state} · destructive effects {attempt.destructive_effect_count}
          </p>)}
          {currentEvidence.job.events.map((event) => <p key={event.sequence}>
            event {event.sequence} · {event.event_type} · <code>{event.evidence_hash}</code>
          </p>)}
          {currentEvidence.job.receipt && <dl className="summary-list">
            <div><dt>receipt</dt><dd>{currentEvidence.job.receipt.receipt_id}</dd></div>
            <div><dt>manifest hash</dt><dd><code>{currentEvidence.job.receipt.manifest_hash}</code></dd></div>
            <div><dt>content hash</dt><dd><code>{currentEvidence.job.receipt.content_sha256}</code></dd></div>
            <div><dt>verified at</dt><dd>{new Date(currentEvidence.job.receipt.verified_at).toLocaleString()}</dd></div>
          </dl>}
        </>}
      </section>}
    </section>}
  </>
}
