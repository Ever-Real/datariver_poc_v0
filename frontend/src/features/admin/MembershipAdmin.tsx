import { useCallback, useEffect, useState } from 'react'
import type {
  AdminAccessRequest,
  AdminReadContext,
  MembershipAccessDocument,
  WorkspaceMembershipSummary,
} from '../../api/types'
import type { AssuranceActions } from '../../components/AssuranceNotice'
import type { AdminApi } from './adminApi'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import type { AdminMessages } from './messages'

export interface AdminSectionProps extends AssuranceActions {
  api: AdminApi
  context?: AdminReadContext
  messages: AdminMessages
  requestConfirmation: (mutation: PendingAdminMutation) => void
  keyFor: (intent: string, prefix: string) => string
  clearKey: (intent: string) => void
  reportError: (error: unknown) => void
}

function lines(value: string): string[] {
  return [...new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean))]
}

function text(values: string[]): string {
  return values.join('\n')
}

export function MembershipAccessAdmin(props: AdminSectionProps) {
  const { api, context, messages, requestConfirmation, keyFor, clearKey, reportError } = props
  const [members, setMembers] = useState<WorkspaceMembershipSummary[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [etag, setEtag] = useState('')
  const [version, setVersion] = useState(0)
  const [access, setAccess] = useState<MembershipAccessDocument>()
  const [groups, setGroups] = useState('')
  const [systems, setSystems] = useState('')
  const [domains, setDomains] = useState('')
  const [reason, setReason] = useState('')

  const loadMembers = useCallback(async () => {
    try {
      const next = await api.listMemberships()
      setMembers(next)
      setSelectedId((current) => current || next[0]?.subject_id || '')
    } catch (error) { reportError(error) }
  }, [api, reportError])

  const loadAccess = useCallback(async (subjectId: string) => {
    if (!subjectId) return
    try {
      const next = await api.getMembershipAccess(subjectId)
      setEtag(next.etag)
      setVersion(next.membership_version)
      setAccess(next.access)
      setGroups(text(next.access.groups))
      setSystems(text(next.access.allowed_system_ids))
      setDomains(text(next.access.allowed_domain_ids))
    } catch (error) { reportError(error) }
  }, [api, reportError])

  const canRead = context?.allowed_operations.includes('MEMBERSHIP_ACCESS_READ') ?? false
  useEffect(() => { if (canRead) void loadMembers() }, [canRead, loadMembers])
  useEffect(() => { void loadAccess(selectedId) }, [loadAccess, selectedId])

  const document = (): MembershipAccessDocument | undefined => access && ({
    ...access,
    groups: lines(groups),
    allowed_system_ids: lines(systems),
    allowed_domain_ids: lines(domains),
  })

  const setAction = (action: string, effect: 'NONE' | 'ALLOW' | 'DENY') => {
    setAccess((current) => current && ({
      ...current,
      allowed_actions: effect === 'ALLOW'
        ? [...new Set([...current.allowed_actions, action])]
        : current.allowed_actions.filter((value) => value !== action),
      denied_actions: effect === 'DENY'
        ? [...new Set([...current.denied_actions, action])]
        : current.denied_actions.filter((value) => value !== action),
    }))
  }

  const directUpdate = () => {
    const next = document()
    if (!next) return
    const intent = `membership-direct:${selectedId}:${etag}:${JSON.stringify(next)}`
    requestConfirmation({
      title: messages.directUpdate,
      summary: [`${selectedId}`, `ETag ${etag}`, `${messages.clearance}: ${next.clearance}`],
      execute: async () => {
        await api.updateMembership(selectedId, next, etag, keyFor(intent, 'admin-direct'))
        clearKey(intent)
        await Promise.all([loadMembers(), loadAccess(selectedId)])
      },
    })
  }

  const createFallback = () => {
    const next = document()
    if (!next || !reason.trim()) return
    const intent = `membership-fallback:${selectedId}:${etag}:${reason}:${JSON.stringify(next)}`
    requestConfirmation({
      title: messages.fallbackRequest,
      summary: [`${selectedId}`, `ETag ${etag}`, reason],
      execute: async () => {
        await api.createFallbackRequest(
          selectedId, reason.trim(), next, etag, keyFor(intent, 'admin-fallback-create'),
        )
        clearKey(intent)
        setReason('')
      },
    })
  }

  const canDirect = context?.allowed_operations.includes('MEMBERSHIP_ACCESS_UPDATE') ?? false
  const canFallback = context?.allowed_operations.includes('FALLBACK_REQUEST_CREATE') ?? false
  const selected = members.find((member) => member.subject_id === selectedId)

  return (
    <div className="admin-two-column">
      <section className="panel">
        <div className="section-heading"><h3>{messages.members}</h3><button className="button button-secondary" onClick={() => void loadMembers()}>{messages.refresh}</button></div>
        <div className="compact-list" aria-label={messages.members}>
          {members.map((member) => (
            <button className={selectedId === member.subject_id ? 'selected' : ''} key={member.subject_id} onClick={() => setSelectedId(member.subject_id)}>
              <span><strong>{member.display_name}</strong><small>{member.job_function ?? '—'} · {member.clearance}</small></span>
              <span className="badge badge-soft">v{member.membership_version}</span>
            </button>
          ))}
          {!members.length && <p className="muted">{messages.empty}</p>}
        </div>
      </section>
      <section className="panel form-stack" aria-live="polite">
        <h3>{messages.accessDocument}</h3>
        {!access || !selected ? <p className="muted">{messages.selectMember}</p> : <>
          <dl className="summary-list">
            <div><dt>subject_id</dt><dd>{selected.subject_id}</dd></div>
            <div><dt>display</dt><dd>{selected.display_name}</dd></div>
            <div><dt>version</dt><dd>{version} · {etag}</dd></div>
            <div><dt>subject</dt><dd>{selected.subject_active ? messages.active : messages.disabled}</dd></div>
          </dl>
          <label className="checkbox-line"><input type="checkbox" checked={access.active} onChange={(event) => setAccess({ ...access, active: event.target.checked })} />{messages.active}</label>
          <label>{messages.clearance}<select value={access.clearance} onChange={(event) => setAccess({ ...access, clearance: event.target.value as MembershipAccessDocument['clearance'] })}><option>PUBLIC</option><option>INTERNAL</option><option>CONFIDENTIAL</option><option>RESTRICTED</option></select></label>
          <label>{messages.groups}<textarea value={groups} onChange={(event) => setGroups(event.target.value)} maxLength={10_000} /></label>
          <fieldset className="action-matrix"><legend>{messages.allowedActions} / {messages.deniedActions}</legend>
            {context?.action_vocabulary.map((action) => {
              const effect = access.allowed_actions.includes(action) ? 'ALLOW' : access.denied_actions.includes(action) ? 'DENY' : 'NONE'
              return <label key={action}><span>{action}</span><select aria-label={action} value={effect} onChange={(event) => setAction(action, event.target.value as 'NONE' | 'ALLOW' | 'DENY')}><option value="NONE">—</option><option value="ALLOW">ALLOW</option><option value="DENY">DENY</option></select></label>
            })}
          </fieldset>
          <label>{messages.systemScopes}<textarea value={systems} onChange={(event) => setSystems(event.target.value)} /></label>
          <label>{messages.domainScopes}<textarea value={domains} onChange={(event) => setDomains(event.target.value)} /></label>
          <label>{messages.reason}<textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={4000} /></label>
          <div className="action-row">
            {canDirect ? <button className="button" onClick={directUpdate}>{messages.directUpdate}</button> : <button className="button button-secondary" onClick={() => void props.onStepUp()}>{messages.hardwareAuth}</button>}
            {context?.fallback_enabled
              ? canFallback
                ? <button className="button button-secondary" disabled={!reason.trim()} onClick={createFallback}>{messages.fallbackRequest}</button>
                : <button className="button button-secondary" onClick={() => void props.onPasswordReauth()}>{messages.passwordReauth}</button>
              : null}
          </div>
          {!context?.fallback_enabled && <p className="callout">{messages.fallbackDisabled}</p>}
        </>}
      </section>
    </div>
  )
}

export function FallbackQueueAdmin(props: AdminSectionProps) {
  const { api, context, messages, requestConfirmation, keyFor, clearKey, reportError } = props
  const [requests, setRequests] = useState<AdminAccessRequest[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [reason, setReason] = useState('')

  const load = useCallback(async () => {
    if (!context?.fallback_enabled || !context.allowed_operations.includes('FALLBACK_REQUEST_READ')) return
    try {
      const next = await api.listFallbackRequests()
      setRequests(next)
      setSelectedId((current) => current || next[0]?.id || '')
    } catch (error) { reportError(error) }
  }, [api, context, reportError])
  useEffect(() => { void load() }, [load])

  if (!context?.fallback_enabled) return <div className="callout">{messages.fallbackDisabled}</div>
  const selected = requests.find((request) => request.id === selectedId)
  const decide = (decision: 'APPROVED' | 'REJECTED') => {
    if (!selected || !reason.trim()) return
    const intent = `fallback-decision:${selected.id}:${selected.version}:${decision}:${reason}`
    requestConfirmation({
      title: `${messages.releaseDecision}: ${decision}`,
      summary: [selected.id, `v${selected.version}`, selected.payload_hash],
      execute: async () => {
        const next = await api.decideFallbackRequest(selected, decision, reason.trim(), keyFor(intent, 'admin-fallback-decision'))
        clearKey(intent); setReason('')
        setRequests((current) => current.map((item) => item.id === next.id ? next : item))
      },
    })
  }
  const consume = () => {
    if (!selected) return
    const intent = `fallback-consume:${selected.id}:${selected.version}:${selected.payload_hash}`
    requestConfirmation({
      title: messages.consume,
      summary: [selected.command.target_subject_id, selected.payload_hash, `v${selected.version}`],
      execute: async () => {
        const result = await api.consumeFallbackRequest(selected, keyFor(intent, 'admin-fallback-consume'))
        clearKey(intent)
        setRequests((current) => current.map((item) => item.id === result.request.id ? result.request : item))
      },
    })
  }
  const actor = context.subject_id
  const canDecide = selected?.state === 'PENDING'
    && actor !== selected.requester_id && actor !== selected.command.target_subject_id
    && context.allowed_operations.includes('FALLBACK_REQUEST_DECIDE')
  const canConsume = selected?.state === 'APPROVED' && actor === selected.requester_id
    && context.allowed_operations.includes('FALLBACK_REQUEST_CONSUME')

  return <div className="admin-two-column">
    <section className="panel"><div className="section-heading"><h3>{messages.recentRequests}</h3><button className="button button-secondary" onClick={() => void load()}>{messages.refresh}</button></div>
      <div className="compact-list">{requests.map((request) => <button key={request.id} className={selectedId === request.id ? 'selected' : ''} onClick={() => setSelectedId(request.id)}><span><strong>{request.command.target_subject_id}</strong><small>{new Date(request.expires_at).toLocaleString()}</small></span><span className="badge">{request.state}</span></button>)}</div>
    </section>
    <section className="panel form-stack">{selected ? <>
      <h3>{selected.state} · v{selected.version}</h3>
      <dl className="summary-list"><div><dt>maker</dt><dd>{selected.requester_id}</dd></div><div><dt>target</dt><dd>{selected.command.target_subject_id}</dd></div><div><dt>{messages.expiresAt}</dt><dd>{new Date(selected.expires_at).toLocaleString()}</dd></div><div><dt>{messages.payloadHash}</dt><dd>{selected.payload_hash}</dd></div></dl>
      <p>{selected.request_reason}</p><label>{messages.reason}<textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={4000} /></label>
      <div className="action-row">
        {canDecide && <><button className="button" disabled={!reason.trim()} onClick={() => decide('APPROVED')}>{messages.approve}</button><button className="button button-secondary" disabled={!reason.trim()} onClick={() => decide('REJECTED')}>{messages.reject}</button></>}
        {canConsume && <button className="button" onClick={consume}>{messages.consume}</button>}
        {selected.state === 'APPROVED' && actor === selected.requester_id && !canConsume && <button className="button button-secondary" onClick={() => void props.onPasswordReauth()}>{messages.passwordReauth}</button>}
      </div>
      {selected.state === 'PENDING' && !canDecide && <p className="callout">{messages.makerCannotCheck}</p>}
    </> : <p className="muted">{messages.empty}</p>}</section>
  </div>
}
