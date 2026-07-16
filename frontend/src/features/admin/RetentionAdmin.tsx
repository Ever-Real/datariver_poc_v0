import { useCallback, useEffect, useState, type FormEvent } from 'react'
import type {
  AdminReadContext,
  LegalHold,
  LegalHoldScope,
  RetentionDataClass,
  RetentionPolicy,
  RetentionRules,
} from '../../api/types'
import type { AssuranceActions } from '../../components/AssuranceNotice'
import type { AdminApi } from './adminApi'
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

type RuleDraft = Record<keyof RetentionRules, string>

const emptyRules: RuleDraft = {
  completed_operation_days: '', chat_content_days: '', audit_online_months: '', immutable_archive_years: '',
}

export function RetentionPolicyAdmin(props: Props) {
  const { api, context, messages, requestConfirmation, keyFor, clearKey, reportError } = props
  const [policies, setPolicies] = useState<RetentionPolicy[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [rules, setRules] = useState<RuleDraft>(emptyRules)
  const [proposalReason, setProposalReason] = useState('')
  const [decisionReason, setDecisionReason] = useState('')

  const load = useCallback(async () => {
    try {
      const next = await api.listRetentionPolicies()
      setPolicies(next)
      setSelectedId((current) => current || next[0]?.policy_id || '')
    } catch (error) { reportError(error) }
  }, [api, reportError])
  useEffect(() => { void load() }, [load])

  const propose = (event: FormEvent) => {
    event.preventDefault()
    const payload: RetentionRules = {
      completed_operation_days: Number(rules.completed_operation_days),
      chat_content_days: Number(rules.chat_content_days),
      audit_online_months: Number(rules.audit_online_months),
      immutable_archive_years: Number(rules.immutable_archive_years),
    }
    const intent = `retention-propose:${JSON.stringify(payload)}:${proposalReason}`
    requestConfirmation({
      title: messages.policyProposal,
      summary: [JSON.stringify(payload), proposalReason],
      execute: async () => {
        const next = await api.proposeRetentionPolicy(payload, proposalReason.trim(), keyFor(intent, 'retention-propose'))
        clearKey(intent); setRules(emptyRules); setProposalReason('')
        setPolicies((current) => [next, ...current]); setSelectedId(next.policy_id)
      },
    })
  }

  const selected = policies.find((policy) => policy.policy_id === selectedId)
  const decide = (decision: 'APPROVED' | 'REJECTED') => {
    if (!selected || !decisionReason.trim()) return
    const intent = `retention-decision:${selected.policy_id}:${selected.version}:${decision}:${decisionReason}`
    requestConfirmation({
      title: `${messages.releaseDecision}: ${decision}`,
      summary: [`#${selected.policy_number}`, selected.payload_hash, `v${selected.version}`],
      execute: async () => {
        const next = await api.decideRetentionPolicy(selected, decision, decisionReason.trim(), keyFor(intent, 'retention-decision'))
        clearKey(intent); setDecisionReason('')
        setPolicies((current) => current.map((item) => item.policy_id === next.policy_id ? next : item))
        await load()
      },
    })
  }
  const canCheck = Boolean(
    selected?.state === 'DRAFT' && context && context.subject_id !== selected.requester_id,
  )

  return <>
    <div className="admin-two-column">
      <form className="panel form-stack" onSubmit={propose}>
        <h3>{messages.policyProposal}</h3>
        <RuleField label={messages.completedDays} value={rules.completed_operation_days} max={3650} onChange={(value) => setRules({ ...rules, completed_operation_days: value })} />
        <RuleField label={messages.chatDays} value={rules.chat_content_days} max={3650} onChange={(value) => setRules({ ...rules, chat_content_days: value })} />
        <RuleField label={messages.auditMonths} value={rules.audit_online_months} max={120} onChange={(value) => setRules({ ...rules, audit_online_months: value })} />
        <RuleField label={messages.archiveYears} value={rules.immutable_archive_years} max={100} onChange={(value) => setRules({ ...rules, immutable_archive_years: value })} />
        <label>{messages.reason}<textarea value={proposalReason} onChange={(event) => setProposalReason(event.target.value)} maxLength={4000} required /></label>
        <button className="button">{messages.propose}</button>
        <p className="callout">{messages.automationDisabled}</p>
      </form>
      <section className="panel"><div className="section-heading"><h3>{messages.policyHistory}</h3><button className="button button-secondary" onClick={() => void load()}>{messages.refresh}</button></div>
        <div className="compact-list">{policies.map((policy) => <button key={policy.policy_id} className={selectedId === policy.policy_id ? 'selected' : ''} onClick={() => setSelectedId(policy.policy_id)}><span><strong>#{policy.policy_number}</strong><small>{policy.request_reason}</small></span><span className="badge">{policy.state}</span></button>)}</div>
      </section>
    </div>
    {selected && <section className="result-card governance-detail form-stack">
      <h3>#{selected.policy_number} · {selected.state}</h3>
      <dl className="summary-list"><div><dt>completed days</dt><dd>{selected.rules.completed_operation_days}</dd></div><div><dt>chat days</dt><dd>{selected.rules.chat_content_days}</dd></div><div><dt>audit months</dt><dd>{selected.rules.audit_online_months}</dd></div><div><dt>archive years</dt><dd>{selected.rules.immutable_archive_years}</dd></div><div><dt>version</dt><dd>{selected.version}</dd></div><div><dt>maker</dt><dd>{selected.requester_id}</dd></div></dl>
      <p className="callout">{selected.partition_automation_state} · {selected.deletion_automation_state}</p>
      {selected.state === 'DRAFT' && <><label>{messages.reason}<textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} maxLength={4000} /></label><div className="action-row">{canCheck ? <><button className="button" disabled={!decisionReason.trim()} onClick={() => decide('APPROVED')}>{messages.approve}</button><button className="button button-secondary" disabled={!decisionReason.trim()} onClick={() => decide('REJECTED')}>{messages.reject}</button></> : <p className="callout">{messages.makerCannotCheck}</p>}</div></>}
      <code>{selected.payload_hash}</code>
    </section>}
    <p className="notice notice-error" role="note">{messages.noErasure}</p>
  </>
}

function RuleField({ label, value, max, onChange }: { label: string; value: string; max: number; onChange: (value: string) => void }) {
  return <label>{label}<input type="number" min={1} max={max} value={value} onChange={(event) => onChange(event.target.value)} required /></label>
}

export function LegalHoldAdmin(props: Props) {
  const { api, context, messages, requestConfirmation, keyFor, clearKey, reportError } = props
  const [holds, setHolds] = useState<LegalHold[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [dataClass, setDataClass] = useState<RetentionDataClass>('AUDIT_EVIDENCE')
  const [scope, setScope] = useState<LegalHoldScope>('WORKSPACE')
  const [scopeId, setScopeId] = useState('')
  const [placeReason, setPlaceReason] = useState('')
  const [releaseReason, setReleaseReason] = useState('')

  const load = useCallback(async () => {
    try {
      const next = await api.listLegalHolds()
      setHolds(next); setSelectedId((current) => current || next[0]?.hold_id || '')
    } catch (error) { reportError(error) }
  }, [api, reportError])
  useEffect(() => { void load() }, [load])

  const place = (event: FormEvent) => {
    event.preventDefault()
    const target = scope === 'WORKSPACE' ? null : scopeId.trim()
    const intent = `hold-place:${dataClass}:${scope}:${target}:${placeReason}`
    requestConfirmation({
      title: messages.placeHold,
      summary: [dataClass, `${scope}: ${target ?? 'workspace'}`, placeReason],
      execute: async () => {
        const next = await api.placeLegalHold(dataClass, scope, target, placeReason.trim(), keyFor(intent, 'legal-hold-place'))
        clearKey(intent); setPlaceReason(''); setScopeId('')
        setHolds((current) => [next, ...current]); setSelectedId(next.hold_id)
      },
    })
  }
  const selected = holds.find((hold) => hold.hold_id === selectedId)
  const releaseRequest = () => {
    if (!selected || !releaseReason.trim()) return
    const intent = `hold-release-request:${selected.hold_id}:${selected.version}:${releaseReason}`
    requestConfirmation({
      title: messages.requestRelease, summary: [selected.hold_id, `v${selected.version}`, releaseReason],
      execute: async () => {
        const next = await api.requestLegalHoldRelease(selected, releaseReason.trim(), keyFor(intent, 'legal-hold-release-request'))
        clearKey(intent); setReleaseReason(''); replaceHold(next)
      },
    })
  }
  const releaseDecision = (decision: 'APPROVED' | 'REJECTED') => {
    if (!selected || !releaseReason.trim()) return
    const intent = `hold-release-decision:${selected.hold_id}:${selected.version}:${decision}:${releaseReason}`
    requestConfirmation({
      title: `${messages.releaseDecision}: ${decision}`, summary: [selected.hold_id, `v${selected.version}`, selected.payload_hash],
      execute: async () => {
        const next = await api.decideLegalHoldRelease(selected, decision, releaseReason.trim(), keyFor(intent, 'legal-hold-release-decision'))
        clearKey(intent); setReleaseReason(''); replaceHold(next)
      },
    })
  }
  const replaceHold = (next: LegalHold) => setHolds((current) => current.map((hold) => hold.hold_id === next.hold_id ? next : hold))
  const canRequestRelease = selected && ['ACTIVE', 'RELEASE_REJECTED'].includes(selected.state)
  const canDecideRelease = Boolean(
    selected?.state === 'RELEASE_REQUESTED'
    && context
    && context.subject_id !== selected.release_requested_by,
  )

  return <>
    <div className="admin-two-column">
      <form className="panel form-stack" onSubmit={place}>
        <h3>{messages.holdPlacement}</h3>
        <label>{messages.dataClass}<select value={dataClass} onChange={(event) => setDataClass(event.target.value as RetentionDataClass)}><option>COMPLETED_OPERATIONS</option><option>CHAT_CONTENT</option><option>AUDIT_EVIDENCE</option><option>OBJECT_DATA</option></select></label>
        <label>{messages.scope}<select value={scope} onChange={(event) => setScope(event.target.value as LegalHoldScope)}><option>WORKSPACE</option><option>SUBJECT</option><option>RESOURCE</option></select></label>
        {scope !== 'WORKSPACE' && <label>{messages.scopeId}<input value={scopeId} onChange={(event) => setScopeId(event.target.value)} required pattern="[0-9a-fA-F-]{36}" /></label>}
        <label>{messages.reason}<textarea value={placeReason} onChange={(event) => setPlaceReason(event.target.value)} maxLength={4000} required /></label>
        <button className="button">{messages.placeHold}</button>
      </form>
      <section className="panel"><div className="section-heading"><h3>{messages.holdHistory}</h3><button className="button button-secondary" onClick={() => void load()}>{messages.refresh}</button></div>
        <div className="compact-list">{holds.map((hold) => <button key={hold.hold_id} className={selectedId === hold.hold_id ? 'selected' : ''} onClick={() => setSelectedId(hold.hold_id)}><span><strong>{hold.data_class}</strong><small>{hold.scope} · {hold.scope_id ?? 'workspace'}</small></span><span className="badge">{hold.state}</span></button>)}</div>
      </section>
    </div>
    {selected && <section className="result-card governance-detail form-stack">
      <h3>{selected.data_class} · {selected.state}</h3><p>{selected.reason}</p>
      <dl className="summary-list"><div><dt>hold_id</dt><dd>{selected.hold_id}</dd></div><div><dt>maker</dt><dd>{selected.created_by}</dd></div><div><dt>scope</dt><dd>{selected.scope_id ?? selected.scope}</dd></div><div><dt>version</dt><dd>{selected.version}</dd></div><div><dt>effect</dt><dd>{selected.deletion_effect}</dd></div><div><dt>hash</dt><dd>{selected.payload_hash}</dd></div></dl>
      {selected.state !== 'RELEASED' && <label>{messages.reason}<textarea value={releaseReason} onChange={(event) => setReleaseReason(event.target.value)} maxLength={4000} /></label>}
      <div className="action-row">
        {canRequestRelease && <button className="button button-secondary" disabled={!releaseReason.trim()} onClick={releaseRequest}>{messages.requestRelease}</button>}
        {canDecideRelease && <><button className="button" disabled={!releaseReason.trim()} onClick={() => releaseDecision('APPROVED')}>{messages.approve}</button><button className="button button-secondary" disabled={!releaseReason.trim()} onClick={() => releaseDecision('REJECTED')}>{messages.reject}</button></>}
        {selected.state === 'RELEASE_REQUESTED' && !canDecideRelease && <p className="callout">{messages.makerCannotCheck}</p>}
      </div>
      <div className="audit-grid"><div><h4>Actions</h4>{selected.actions.map((action) => <p key={action.action_id}><strong>{action.action}</strong><br /><small>{action.actor_id} · v{action.hold_version}</small></p>)}</div></div>
    </section>}
    <p className="notice notice-error" role="note">{messages.noErasure}</p>
  </>
}
