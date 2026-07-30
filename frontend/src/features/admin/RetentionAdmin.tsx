import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import type {
  AdminReadContext,
  LegalHold,
  LegalHoldResourceType,
  LegalHoldScope,
  LegalHoldState,
  RetentionDataClass,
  RetentionArchiveDisposition,
  RetentionClassRule,
  RetentionContractVersion,
  RetentionPeriodUnit,
  RetentionPolicy,
  RetentionPolicyContract,
  RetentionPolicyState,
  RetentionRules,
} from '../../api/types'
import type { AssuranceActions } from '../../components/AssuranceNotice'
import { useAbortSignalChannel } from '../../components/common/useAbortSignalChannel'
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

type ClassRuleDraft = Omit<
  RetentionClassRule,
  'unit' | 'minimum' | 'maximum' | 'archive_disposition'
> & {
  unit: RetentionPeriodUnit | ''
  minimum: string
  maximum: string
  archive_disposition: RetentionArchiveDisposition | ''
}

const retentionClasses: Record<RetentionContractVersion, RetentionDataClass[]> = {
  POLICY_BOOK_V2: ['COMPLETED_OPERATIONS', 'CHAT_CONTENT', 'AUDIT_EVIDENCE', 'OBJECT_DATA'],
  POLICY_BOOK_V3: [
    'COMPLETED_OPERATIONS', 'CHAT_CONTENT', 'AUDIT_EVIDENCE', 'OBJECT_DATA',
    'QUALITY_RULE', 'QUALITY_RESULT', 'QUALITY_AUDIT',
  ],
  POLICY_BOOK_V4: [
    'COMPLETED_OPERATIONS', 'CHAT_CONTENT', 'AUDIT_EVIDENCE', 'OBJECT_DATA',
    'QUALITY_RULE', 'QUALITY_RESULT', 'QUALITY_AUDIT', 'QUALITY_PROFILE',
  ],
}

const holdResourceTypes: Record<RetentionDataClass, LegalHoldResourceType[]> = {
  COMPLETED_OPERATIONS: ['LEGACY_UNTYPED'],
  CHAT_CONTENT: ['CHAT_SESSION', 'LEGACY_UNTYPED'],
  AUDIT_EVIDENCE: ['LEGACY_UNTYPED'],
  OBJECT_DATA: ['UPLOAD_OBJECT', 'LEGACY_UNTYPED'],
  QUALITY_RULE: ['QUALITY_RULE_SET'],
  QUALITY_RESULT: ['QUALITY_VALIDATION_RUN'],
  QUALITY_AUDIT: ['QUALITY_RULE_SET', 'QUALITY_VALIDATION_RUN'],
  QUALITY_PROFILE: ['PROFILE_SNAPSHOT'],
}

const retentionDataClasses = retentionClasses.POLICY_BOOK_V4

function classRuleDrafts(
  contractVersion: RetentionContractVersion,
  current: ClassRuleDraft[] = [],
): ClassRuleDraft[] {
  return retentionClasses[contractVersion].map((dataClass) => (
    current.find((rule) => rule.data_class === dataClass) ?? {
      data_class: dataClass,
      unit: '',
      minimum: '',
      maximum: '',
      archive_disposition: '',
    }
  ))
}

function currentLocalMinute() {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

export function RetentionPolicyAdmin(props: Props) {
  const { api, context, messages, requestConfirmation, keyFor, clearKey, reportError } = props
  const [policies, setPolicies] = useState<RetentionPolicy[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [rules, setRules] = useState<RuleDraft>(emptyRules)
  const [contractVersion, setContractVersion] = useState<RetentionContractVersion | ''>('')
  const [classRules, setClassRules] = useState<ClassRuleDraft[]>([])
  const [effectiveFrom, setEffectiveFrom] = useState(currentLocalMinute)
  const [effectiveUntil, setEffectiveUntil] = useState('')
  const [executionAuthorizationHours, setExecutionAuthorizationHours] = useState('24')
  const [proposalReason, setProposalReason] = useState('')
  const [decisionReason, setDecisionReason] = useState('')
  const [stateFilter, setStateFilter] = useState<RetentionPolicyState | ''>('')
  const [cursor, setCursor] = useState<string>()
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [pageNumber, setPageNumber] = useState(1)
  const loadGeneration = useRef(0)
  const listChannel = useAbortSignalChannel()
  const canManage = context?.allowed_operations.includes('RETENTION_POLICY_MANAGE') ?? false

  const load = useCallback(async (pageCursor: string | undefined, signal?: AbortSignal) => {
    const generation = ++loadGeneration.current
    try {
      const page = await api.listRetentionPolicyPage({
        state: stateFilter || undefined,
        cursor: pageCursor,
        limit: 25,
        signal,
      })
      if (generation !== loadGeneration.current) return
      setPolicies(page.items)
      setNextCursor(page.nextCursor)
      setSelectedId((current) => (
        current && page.items.some((policy) => policy.policy_id === current)
          ? current
          : page.items[0]?.policy_id || ''
      ))
    } catch (error) {
      if (!signal?.aborted && generation === loadGeneration.current) reportError(error)
    }
  }, [api, reportError, stateFilter])
  useEffect(() => {
    void load(cursor, listChannel.next())
    return () => { loadGeneration.current += 1 }
  }, [cursor, listChannel, load])

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

  const propose = (event: FormEvent) => {
    event.preventDefault()
    if (!contractVersion) return
    const payload: RetentionRules = {
      completed_operation_days: Number(rules.completed_operation_days),
      chat_content_days: Number(rules.chat_content_days),
      audit_online_months: Number(rules.audit_online_months),
      immutable_archive_years: Number(rules.immutable_archive_years),
    }
    const contract: RetentionPolicyContract = {
      contract_version: contractVersion,
      effective_from: new Date(effectiveFrom).toISOString(),
      effective_until: effectiveUntil ? new Date(effectiveUntil).toISOString() : null,
      execution_authorization_hours: Number(executionAuthorizationHours),
      class_rules: classRules.map((rule) => ({
        data_class: rule.data_class,
        unit: rule.unit as RetentionPeriodUnit,
        minimum: Number(rule.minimum),
        maximum: Number(rule.maximum),
        archive_disposition: rule.archive_disposition as RetentionArchiveDisposition,
      })),
    }
    const intent = `retention-propose:${JSON.stringify(payload)}:${JSON.stringify(contract)}:${proposalReason}`
    requestConfirmation({
      title: messages.policyProposal,
      summary: [contractVersion, JSON.stringify(payload), JSON.stringify(contract), proposalReason],
      execute: async () => {
        const next = await api.proposeRetentionPolicy(payload, contract, proposalReason.trim(), keyFor(intent, 'retention-propose'))
        clearKey(intent); setRules(emptyRules); setProposalReason('')
        setContractVersion(''); setClassRules([])
        await reloadFirstPage()
        setSelectedId(next.policy_id)
      },
    })
  }

  const selected = policies.find((policy) => policy.policy_id === selectedId)
  const decide = (decision: 'APPROVED' | 'REJECTED') => {
    if (!selected || !decisionReason.trim()) return
    const intent = `retention-decision:${selected.policy_id}:${selected.version}:${decision}:${decisionReason}`
    requestConfirmation({
      title: `${messages.releaseDecision}: ${decision}`,
      summary: [
        `#${selected.policy_number}`,
        selected.contract_version,
        selected.contract ? JSON.stringify(selected.contract) : 'LEGACY CONTRACT — no class bounds',
        selected.payload_hash,
        `v${selected.version}`,
      ],
      execute: async () => {
        const next = await api.decideRetentionPolicy(selected, decision, decisionReason.trim(), keyFor(intent, 'retention-decision'))
        clearKey(intent); setDecisionReason('')
        setPolicies((current) => current.map((item) => item.policy_id === next.policy_id ? next : item))
        await reloadFirstPage()
      },
    })
  }
  const canCheck = Boolean(
    canManage && selected?.state === 'DRAFT' && context && context.subject_id !== selected.requester_id,
  )

  return <>
    <div className={canManage ? 'admin-two-column' : ''}>
      {canManage && <form className="panel form-stack" onSubmit={propose}>
        <h3>{messages.policyProposal}</h3>
        <RuleField label={messages.completedDays} value={rules.completed_operation_days} max={3650} onChange={(value) => setRules({ ...rules, completed_operation_days: value })} />
        <RuleField label={messages.chatDays} value={rules.chat_content_days} max={3650} onChange={(value) => setRules({ ...rules, chat_content_days: value })} />
        <RuleField label={messages.auditMonths} value={rules.audit_online_months} max={120} onChange={(value) => setRules({ ...rules, audit_online_months: value })} />
        <RuleField label={messages.archiveYears} value={rules.immutable_archive_years} max={100} onChange={(value) => setRules({ ...rules, immutable_archive_years: value })} />
        <h4>보존 시행 계약</h4>
        <label>계약 버전<select
          value={contractVersion}
          required
          onChange={(event) => {
            const value = event.target.value as RetentionContractVersion | ''
            setContractVersion(value)
            setClassRules(value ? classRuleDrafts(value, classRules) : [])
          }}
        ><option value="">승인할 계약 범위를 선택하세요</option><option>POLICY_BOOK_V2</option><option>POLICY_BOOK_V3</option><option>POLICY_BOOK_V4</option></select></label>
        <label>시행 시작<input type="datetime-local" value={effectiveFrom} onChange={(event) => setEffectiveFrom(event.target.value)} required /></label>
        <label>시행 종료 (선택)<input type="datetime-local" value={effectiveUntil} min={effectiveFrom} onChange={(event) => setEffectiveUntil(event.target.value)} /></label>
        <RuleField label="실행 승인 유효시간" value={executionAuthorizationHours} max={168} onChange={setExecutionAuthorizationHours} />
        {classRules.map((rule, index) => <fieldset className="form-stack" key={rule.data_class}>
          <legend>{rule.data_class}</legend>
          <label>단위<select required value={rule.unit} onChange={(event) => setClassRules((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, unit: event.target.value as RetentionPeriodUnit | '' } : item))}><option value="">선택</option><option>DAYS</option><option>MONTHS</option><option>YEARS</option></select></label>
          <RuleField label="최소 보존" value={rule.minimum} min={0} max={36500} onChange={(value) => setClassRules((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, minimum: value } : item))} />
          <RuleField label="최대 보존" value={rule.maximum} max={36500} onChange={(value) => setClassRules((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, maximum: value } : item))} />
          <label>만료 처리<select required value={rule.archive_disposition} onChange={(event) => setClassRules((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, archive_disposition: event.target.value as RetentionArchiveDisposition | '' } : item))}><option value="">선택</option><option>NO_ARCHIVE</option><option>EVIDENCE_ONLY</option><option>CONTENT_WORM</option></select></label>
        </fieldset>)}
        <label>{messages.reason}<textarea value={proposalReason} onChange={(event) => setProposalReason(event.target.value)} maxLength={4000} required /></label>
        <button className="button">{messages.propose}</button>
        <p className="callout">{messages.automationDisabled}</p>
      </form>}
      <section className="panel"><div className="section-heading"><h3>{messages.policyHistory}</h3><button className="button button-secondary" onClick={() => void load(cursor, listChannel.next())}>{messages.refresh}</button></div>
        <label>상태 필터<select value={stateFilter} onChange={(event) => { setStateFilter(event.target.value as RetentionPolicyState | ''); resetPage() }}><option value="">전체</option><option>DRAFT</option><option>ACTIVE</option><option>REJECTED</option><option>SUPERSEDED</option></select></label>
        <div className="compact-list">{policies.map((policy) => <button key={policy.policy_id} className={selectedId === policy.policy_id ? 'selected' : ''} onClick={() => setSelectedId(policy.policy_id)}><span><strong>#{policy.policy_number}</strong><small>{policy.request_reason} · {policy.contract_version}</small></span><span className="badge">{policy.state}</span></button>)}</div>
        <PageNavigation
          page={pageNumber}
          canPrevious={cursorHistory.length > 0}
          canNext={Boolean(nextCursor)}
          onPrevious={() => {
            const previous = cursorHistory.at(-1) ?? null
            setCursorHistory((history) => history.slice(0, -1))
            setCursor(previous ?? undefined)
            setPageNumber((page) => Math.max(1, page - 1))
          }}
          onNext={() => {
            if (!nextCursor) return
            setCursorHistory((history) => [...history.slice(-49), cursor ?? null])
            setCursor(nextCursor)
            setPageNumber((page) => page + 1)
          }}
        />
      </section>
    </div>
    {selected && <section className="result-card governance-detail form-stack">
      <h3>#{selected.policy_number} · {selected.state}</h3>
      <dl className="summary-list"><div><dt>completed days</dt><dd>{selected.rules.completed_operation_days}</dd></div><div><dt>chat days</dt><dd>{selected.rules.chat_content_days}</dd></div><div><dt>audit months</dt><dd>{selected.rules.audit_online_months}</dd></div><div><dt>archive years</dt><dd>{selected.rules.immutable_archive_years}</dd></div><div><dt>version</dt><dd>{selected.version}</dd></div><div><dt>maker</dt><dd>{selected.requester_id}</dd></div></dl>
      <h4>{selected.contract_version}</h4>
      {selected.contract
        ? <><p>{selected.contract.effective_from} → {selected.contract.effective_until ?? 'open-ended'} · execution authorization {selected.contract.execution_authorization_hours}h</p><ul>{selected.contract.class_rules.map((rule) => <li key={rule.data_class}>{rule.data_class}: {rule.minimum}–{rule.maximum} {rule.unit} · {rule.archive_disposition}</li>)}</ul></>
        : <p className="notice notice-warning">레거시 정책입니다. 최소/최대 보존 및 실행 승인 계약이 없으므로 신규 제안으로 대체해야 합니다.</p>}
      <p className="callout">{selected.partition_automation_state} · {selected.deletion_automation_state}</p>
      {selected.state === 'DRAFT' && <><label>{messages.reason}<textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} maxLength={4000} /></label><div className="action-row">{canCheck ? <><button className="button" disabled={!decisionReason.trim()} onClick={() => decide('APPROVED')}>{messages.approve}</button><button className="button button-secondary" disabled={!decisionReason.trim()} onClick={() => decide('REJECTED')}>{messages.reject}</button></> : <p className="callout">{messages.makerCannotCheck}</p>}</div></>}
      <code>{selected.payload_hash}</code>
    </section>}
    <p className="notice notice-error" role="note">{messages.noErasure}</p>
  </>
}

function RuleField({ label, value, min = 1, max, onChange }: { label: string; value: string; min?: number; max: number; onChange: (value: string) => void }) {
  return <label>{label}<input type="number" min={min} max={max} value={value} onChange={(event) => onChange(event.target.value)} required /></label>
}

export function LegalHoldAdmin(props: Props) {
  const { api, context, messages, requestConfirmation, keyFor, clearKey, reportError } = props
  const [holds, setHolds] = useState<LegalHold[]>([])
  const [selectedDetail, setSelectedDetail] = useState<LegalHold>()
  const [selectedId, setSelectedId] = useState('')
  const [dataClass, setDataClass] = useState<RetentionDataClass | ''>('')
  const [scope, setScope] = useState<LegalHoldScope>('WORKSPACE')
  const [scopeId, setScopeId] = useState('')
  const [resourceType, setResourceType] = useState<LegalHoldResourceType | ''>('')
  const [placeReason, setPlaceReason] = useState('')
  const [releaseReason, setReleaseReason] = useState('')
  const [stateFilter, setStateFilter] = useState<LegalHoldState | ''>('')
  const [cursor, setCursor] = useState<string>()
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [pageNumber, setPageNumber] = useState(1)
  const loadGeneration = useRef(0)
  const listChannel = useAbortSignalChannel()
  const detailChannel = useAbortSignalChannel()
  const canPlace = context?.allowed_operations.includes('LEGAL_HOLD_PLACE') ?? false
  const canRelease = context?.allowed_operations.includes('LEGAL_HOLD_RELEASE') ?? false

  const load = useCallback(async (pageCursor: string | undefined, signal?: AbortSignal) => {
    const generation = ++loadGeneration.current
    try {
      const page = await api.listLegalHoldPage({
        state: stateFilter || undefined,
        cursor: pageCursor,
        limit: 25,
        signal,
      })
      if (generation !== loadGeneration.current) return
      setHolds(page.items)
      setNextCursor(page.nextCursor)
      setSelectedId((current) => (
        current && page.items.some((hold) => hold.hold_id === current)
          ? current
          : page.items[0]?.hold_id || ''
      ))
    } catch (error) {
      if (!signal?.aborted && generation === loadGeneration.current) reportError(error)
    }
  }, [api, reportError, stateFilter])
  useEffect(() => {
    void load(cursor, listChannel.next())
    return () => { loadGeneration.current += 1 }
  }, [cursor, listChannel, load])
  useEffect(() => {
    const signal = detailChannel.next()
    setSelectedDetail(undefined)
    if (selectedId) {
      void api.getLegalHold(selectedId, signal)
        .then((hold) => { if (!signal.aborted) setSelectedDetail(hold) })
        .catch((error) => { if (!signal.aborted) reportError(error) })
    }
  }, [api, detailChannel, reportError, selectedId])

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

  const place = (event: FormEvent) => {
    event.preventDefault()
    if (!dataClass || (scope === 'RESOURCE' && !resourceType)) return
    const target = scope === 'WORKSPACE' ? null : scopeId.trim()
    const exactResourceType = scope === 'RESOURCE' ? resourceType as LegalHoldResourceType : null
    const intent = `hold-place:${dataClass}:${scope}:${target}:${exactResourceType}:${placeReason}`
    requestConfirmation({
      title: messages.placeHold,
      summary: [
        dataClass,
        `${scope}: ${target ?? 'workspace'}`,
        exactResourceType ?? 'no resource type',
        placeReason,
      ],
      execute: async () => {
        const next = await api.placeLegalHold(
          dataClass,
          scope,
          target,
          exactResourceType,
          placeReason.trim(),
          keyFor(intent, 'legal-hold-place'),
        )
        clearKey(intent); setPlaceReason(''); setScopeId(''); setResourceType('')
        await reloadFirstPage()
        setSelectedId(next.hold_id)
      },
    })
  }
  const selectedSummary = holds.find((hold) => hold.hold_id === selectedId)
  const selected = selectedDetail?.hold_id === selectedId ? selectedDetail : selectedSummary
  const releaseRequest = () => {
    if (!selected || !releaseReason.trim()) return
    const intent = `hold-release-request:${selected.hold_id}:${selected.version}:${releaseReason}`
    requestConfirmation({
      title: messages.requestRelease, summary: [selected.hold_id, `v${selected.version}`, releaseReason],
      execute: async () => {
        const next = await api.requestLegalHoldRelease(selected, releaseReason.trim(), keyFor(intent, 'legal-hold-release-request'))
        clearKey(intent); setReleaseReason('')
        await reloadFirstPage()
        setSelectedId(next.hold_id)
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
        clearKey(intent); setReleaseReason('')
        await reloadFirstPage()
        setSelectedId(next.hold_id)
      },
    })
  }
  const canRequestRelease = canRelease && selected && ['ACTIVE', 'RELEASE_REJECTED'].includes(selected.state)
  const canDecideRelease = Boolean(
    canRelease
    && selected?.state === 'RELEASE_REQUESTED'
    && context
    && context.subject_id !== selected.release_requested_by,
  )

  return <>
    <div className={canPlace ? 'admin-two-column' : ''}>
      {canPlace && <form className="panel form-stack" onSubmit={place}>
        <h3>{messages.holdPlacement}</h3>
        <label>{messages.dataClass}<select required value={dataClass} onChange={(event) => { setDataClass(event.target.value as RetentionDataClass | ''); setResourceType('') }}><option value="">보존 클래스를 선택하세요</option>{retentionDataClasses.map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>{messages.scope}<select value={scope} onChange={(event) => { setScope(event.target.value as LegalHoldScope); setResourceType('') }}><option>WORKSPACE</option><option>SUBJECT</option><option>RESOURCE</option></select></label>
        {scope !== 'WORKSPACE' && <label>{messages.scopeId}<input value={scopeId} onChange={(event) => setScopeId(event.target.value)} required pattern="[0-9a-fA-F-]{36}" /></label>}
        {scope === 'RESOURCE' && dataClass && <label>리소스 타입<select required value={resourceType} onChange={(event) => setResourceType(event.target.value as LegalHoldResourceType | '')}><option value="">정확한 리소스 타입을 선택하세요</option>{holdResourceTypes[dataClass].map((value) => <option key={value}>{value}</option>)}</select></label>}
        <label>{messages.reason}<textarea value={placeReason} onChange={(event) => setPlaceReason(event.target.value)} maxLength={4000} required /></label>
        <button className="button">{messages.placeHold}</button>
      </form>}
      <section className="panel"><div className="section-heading"><h3>{messages.holdHistory}</h3><button className="button button-secondary" onClick={() => void load(cursor, listChannel.next())}>{messages.refresh}</button></div>
        <label>상태 필터<select value={stateFilter} onChange={(event) => { setStateFilter(event.target.value as LegalHoldState | ''); resetPage() }}><option value="">전체</option><option>ACTIVE</option><option>RELEASE_REQUESTED</option><option>RELEASE_REJECTED</option><option>RELEASED</option></select></label>
        <div className="compact-list">{holds.map((hold) => <button key={hold.hold_id} className={selectedId === hold.hold_id ? 'selected' : ''} onClick={() => setSelectedId(hold.hold_id)}><span><strong>{hold.data_class}</strong><small>{hold.scope} · {hold.scope_id ?? 'workspace'}</small></span><span className="badge">{hold.state}</span></button>)}</div>
        <PageNavigation
          page={pageNumber}
          canPrevious={cursorHistory.length > 0}
          canNext={Boolean(nextCursor)}
          onPrevious={() => {
            const previous = cursorHistory.at(-1) ?? null
            setCursorHistory((history) => history.slice(0, -1))
            setCursor(previous ?? undefined)
            setPageNumber((page) => Math.max(1, page - 1))
          }}
          onNext={() => {
            if (!nextCursor) return
            setCursorHistory((history) => [...history.slice(-49), cursor ?? null])
            setCursor(nextCursor)
            setPageNumber((page) => page + 1)
          }}
        />
      </section>
    </div>
    {selected && <section className="result-card governance-detail form-stack">
      <h3>{selected.data_class} · {selected.state}</h3><p>{selected.reason}</p>
      <dl className="summary-list"><div><dt>hold_id</dt><dd>{selected.hold_id}</dd></div><div><dt>maker</dt><dd>{selected.created_by}</dd></div><div><dt>scope</dt><dd>{selected.scope_id ?? selected.scope}</dd></div><div><dt>resource type</dt><dd>{selected.resource_type ?? '—'}</dd></div><div><dt>version</dt><dd>{selected.version}</dd></div><div><dt>effect</dt><dd>{selected.deletion_effect}</dd></div><div><dt>hash</dt><dd>{selected.payload_hash}</dd></div></dl>
      {selected.state !== 'RELEASED' && <label>{messages.reason}<textarea value={releaseReason} onChange={(event) => setReleaseReason(event.target.value)} maxLength={4000} /></label>}
      <div className="action-row">
        {canRequestRelease && <button className="button button-secondary" disabled={!releaseReason.trim()} onClick={releaseRequest}>{messages.requestRelease}</button>}
        {canDecideRelease && <><button className="button" disabled={!releaseReason.trim()} onClick={() => releaseDecision('APPROVED')}>{messages.approve}</button><button className="button button-secondary" disabled={!releaseReason.trim()} onClick={() => releaseDecision('REJECTED')}>{messages.reject}</button></>}
        {selected.state === 'RELEASE_REQUESTED' && !canDecideRelease && <p className="callout">{messages.makerCannotCheck}</p>}
      </div>
      {selected.action_history_truncated && <p className="callout">작업 이력은 서버에서 최근 100건으로 제한되어 표시됩니다.</p>}
      <div className="audit-grid"><div><h4>Actions</h4>{selected.actions.map((action) => <p key={action.action_id}><strong>{action.action}</strong><br /><small>{action.actor_id} · v{action.hold_version}</small></p>)}</div></div>
    </section>}
    <p className="notice notice-error" role="note">{messages.noErasure}</p>
  </>
}

function PageNavigation({
  page,
  canPrevious,
  canNext,
  onPrevious,
  onNext,
}: {
  page: number
  canPrevious: boolean
  canNext: boolean
  onPrevious: () => void
  onNext: () => void
}) {
  return <nav className="action-row" aria-label="서버 페이지 탐색">
    <button type="button" className="button button-secondary" disabled={!canPrevious} onClick={onPrevious}>이전</button>
    <span>페이지 {page}</span>
    <button type="button" className="button button-secondary" disabled={!canNext} onClick={onNext}>다음</button>
  </nav>
}
