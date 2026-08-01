import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import type {
  AdminReadContext,
  CatalogAsset,
  Classification,
  ClassificationAccessPolicy,
  ClassificationAccessRule,
  ClassificationAccessPolicyState,
  ClassificationChatMode,
  ClassificationPolicySummary,
  ClassificationPolicySummaryRule,
  ClassificationSearchMode,
  InferenceProviderProfile,
  InferenceProviderProfileState,
  RestrictedSearchGrant,
  RestrictedSearchGrantProposal,
  RestrictedSearchScope,
  RestrictedSearchGrantState,
  SystemDirectoryEntry,
  WorkspaceMembershipSummary,
} from '../../api/types'
import type { AssuranceActions } from '../../components/AssuranceNotice'
import { DenseDataTable } from '../../components/common/DenseDataTable'
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

interface RuleDraft {
  classification: Classification
  search_mode: ClassificationSearchMode
  chat_mode: ClassificationChatMode
  provider_profile_version_id: string
  embedding_provider_profile_version_id: string
  reranker_provider_profile_version_id: string
}

const classifications = ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'] as const
const classificationRank: Record<Classification, number> = {
  PUBLIC: 0,
  INTERNAL: 1,
  CONFIDENTIAL: 2,
  RESTRICTED: 3,
}

const classificationDescriptions: Record<Classification, string> = {
  PUBLIC: '고정 보안 계약에 남아 있는 공개 등급입니다. 현재 운영 프로파일의 주 사용 등급은 아닙니다.',
  INTERNAL: '고정 보안 계약에 남아 있는 내부 등급입니다. 현재 운영 프로파일의 주 사용 등급은 아닙니다.',
  CONFIDENTIAL: '대외비 데이터입니다. 승인된 내부 Provider와 ABAC 범위를 함께 요구할 수 있습니다.',
  RESTRICTED: '극비 데이터입니다. Search는 기간·대상 범위가 지정된 예외 승인만 가능하고 Chat은 항상 차단됩니다.',
}

function classificationLabel(classification: Classification) {
  if (classification === 'CONFIDENTIAL') return 'CONFIDENTIAL · 대외비'
  if (classification === 'RESTRICTED') return 'RESTRICTED · 극비'
  return classification
}

const summaryColumns: ColumnDef<ClassificationPolicySummaryRule>[] = [
  {
    accessorKey: 'classification',
    header: '분류 등급',
    cell: ({ row }) => <strong>{classificationLabel(row.original.classification)}</strong>,
  },
  { accessorKey: 'search_mode', header: 'Search 접근' },
  { accessorKey: 'chat_mode', header: 'Chat 접근' },
]

function ClassificationPolicySummaryView({ summary }: {
  summary: ClassificationPolicySummary
}) {
  return <>
    <p className="callout">
      {summary.state === 'GOVERNED'
        ? '승인된 정책의 현재 유효 모드입니다.'
        : '활성 정책을 안전하게 확인할 수 없어 정적 최소 접근 기준을 적용 중입니다.'}
    </p>
    <DenseDataTable
      caption="현재 유효 분류 정책 요약"
      columns={summaryColumns}
      data={summary.rules}
      getRowId={(rule) => rule.classification}
      emptyMessage="현재 유효 분류 정책이 없습니다."
    />
  </>
}

function emptyPolicyRules(): RuleDraft[] {
  return classifications.map((classification) => ({
    classification,
    search_mode: 'DENY',
    chat_mode: 'DENY',
    provider_profile_version_id: '',
    embedding_provider_profile_version_id: '',
    reranker_provider_profile_version_id: '',
  }))
}

export function ClassificationPolicyAdmin(props: Props) {
  const { api, context, messages, requestConfirmation, keyFor, clearKey, reportError } = props
  const [policies, setPolicies] = useState<ClassificationAccessPolicy[]>([])
  const [summary, setSummary] = useState<ClassificationPolicySummary | null>(null)
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [currentPolicy, setCurrentPolicy] = useState<ClassificationAccessPolicy | null>(null)
  const [profiles, setProfiles] = useState<InferenceProviderProfile[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [requiredJurisdiction, setRequiredJurisdiction] = useState('')
  const [grantMaximumDays, setGrantMaximumDays] = useState('')
  const [rules, setRules] = useState<RuleDraft[]>(emptyPolicyRules)
  const [proposalReason, setProposalReason] = useState('')
  const [decisionReason, setDecisionReason] = useState('')
  const [stateFilter, setStateFilter] = useState<ClassificationAccessPolicyState | ''>('')
  const [cursor, setCursor] = useState<string>()
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [pageNumber, setPageNumber] = useState(1)
  const [profilesTruncated, setProfilesTruncated] = useState(false)
  const [providerKeyQuery, setProviderKeyQuery] = useState('')
  const [appliedProviderKeyQuery, setAppliedProviderKeyQuery] = useState('')
  const [providerCursor, setProviderCursor] = useState<string>()
  const [providerCursorHistory, setProviderCursorHistory] = useState<Array<string | null>>([])
  const [providerNextCursor, setProviderNextCursor] = useState<string | null>(null)
  const [providerPageNumber, setProviderPageNumber] = useState(1)
  const [selectedProfiles, setSelectedProfiles] = useState<
    Record<string, InferenceProviderProfile>
  >({})
  const loadGeneration = useRef(0)
  const auxiliaryGeneration = useRef(0)
  const summaryGeneration = useRef(0)
  const listChannel = useAbortSignalChannel()
  const auxiliaryChannel = useAbortSignalChannel()
  const summaryChannel = useAbortSignalChannel()
  const canPropose = context?.allowed_operations.includes(
    'CLASSIFICATION_POLICY_PROPOSE',
  ) ?? false
  const canDecide = context?.allowed_operations.includes(
    'CLASSIFICATION_POLICY_DECIDE',
  ) ?? false
  const canReadDetails = context?.allowed_operations.includes(
    'CLASSIFICATION_POLICY_READ',
  ) ?? false
  const hasFreshDetailAssurance = context?.authentication_assurance === 'HARDWARE_WEBAUTHN'
    || context?.authentication_assurance === 'PASSWORD_REAUTH'

  const clearDetails = useCallback(() => {
    loadGeneration.current += 1
    auxiliaryGeneration.current += 1
    listChannel.abort()
    auxiliaryChannel.abort()
    setDetailsOpen(false)
    setPolicies([])
    setCurrentPolicy(null)
    setProfiles([])
    setSelectedProfiles({})
    setSelectedId('')
    setNextCursor(null)
    setProviderNextCursor(null)
  }, [auxiliaryChannel, listChannel])

  const loadSummary = useCallback(async (signal?: AbortSignal) => {
    const generation = ++summaryGeneration.current
    setSummaryLoading(true)
    setSummary(null)
    try {
      const next = await api.getCurrentClassificationPolicySummary(signal)
      if (generation !== summaryGeneration.current) return
      setSummary(next)
    } catch (error) {
      if (!signal?.aborted && generation === summaryGeneration.current) reportError(error)
    } finally {
      if (generation === summaryGeneration.current) setSummaryLoading(false)
    }
  }, [api, reportError])

  const load = useCallback(async (pageCursor: string | undefined, signal?: AbortSignal) => {
    const generation = ++loadGeneration.current
    try {
      const policyPage = await api.listClassificationAccessPolicyPage({
        state: stateFilter || undefined,
        cursor: pageCursor,
        limit: 25,
        signal,
      })
      if (generation !== loadGeneration.current) return
      setPolicies(policyPage.items)
      setNextCursor(policyPage.nextCursor)
      setSelectedId((selected) => (
        selected && policyPage.items.some((policy) => policy.policy_id === selected)
          ? selected
          : policyPage.items[0]?.policy_id || ''
      ))
    } catch (error) {
      if (!signal?.aborted && generation === loadGeneration.current) {
        clearDetails()
        reportError(error)
      }
    }
  }, [api, clearDetails, reportError, stateFilter])

  const loadAuxiliary = useCallback(async (signal?: AbortSignal) => {
    const generation = ++auxiliaryGeneration.current
    try {
      const [nextCurrent, profilePage] = await Promise.all([
        api.getCurrentClassificationAccessPolicy(signal),
        api.listInferenceProviderProfilePage({
          profileKey: appliedProviderKeyQuery || undefined,
          state: 'APPROVED',
          cursor: providerCursor,
          limit: 25,
          signal,
        }),
      ])
      if (generation !== auxiliaryGeneration.current) return
      setCurrentPolicy(nextCurrent)
      setProfiles(profilePage.items)
      setProfilesTruncated(Boolean(profilePage.nextCursor))
      setProviderNextCursor(profilePage.nextCursor)
    } catch (error) {
      if (!signal?.aborted && generation === auxiliaryGeneration.current) {
        clearDetails()
        reportError(error)
      }
    }
  }, [api, appliedProviderKeyQuery, clearDetails, providerCursor, reportError])

  useEffect(() => {
    void loadSummary(summaryChannel.next())
    return () => { summaryGeneration.current += 1 }
  }, [loadSummary, summaryChannel])
  useEffect(() => {
    if (!detailsOpen) return undefined
    void load(cursor, listChannel.next())
    return () => { loadGeneration.current += 1 }
  }, [cursor, detailsOpen, listChannel, load])
  useEffect(() => {
    if (!detailsOpen) return undefined
    void loadAuxiliary(auxiliaryChannel.next())
    return () => { auxiliaryGeneration.current += 1 }
  }, [auxiliaryChannel, detailsOpen, loadAuxiliary])
  useEffect(() => {
    if (detailsOpen && (!canReadDetails || !hasFreshDetailAssurance)) clearDetails()
  }, [canReadDetails, clearDetails, detailsOpen, hasFreshDetailAssurance])
  useEffect(() => {
    const timer = window.setTimeout(
      () => {
        setAppliedProviderKeyQuery(providerKeyQuery.trim())
        setProviderCursor(undefined)
        setProviderCursorHistory([])
        setProviderNextCursor(null)
        setProviderPageNumber(1)
      },
      250,
    )
    return () => window.clearTimeout(timer)
  }, [providerKeyQuery])

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

  const changeJurisdiction = (value: string) => {
    setRequiredJurisdiction(value)
    setRules((current) => current.map((rule) => ({
      ...rule,
      provider_profile_version_id: '',
      embedding_provider_profile_version_id: '',
      reranker_provider_profile_version_id: '',
    })))
  }
  const changeRule = (classification: Classification, patch: Partial<RuleDraft>) => {
    setRules((current) => current.map((rule) => rule.classification === classification
      ? { ...rule, ...patch }
      : rule))
  }
  const changeChatMode = (classification: Classification, chatMode: ClassificationChatMode) => {
    changeRule(classification, {
      chat_mode: chatMode,
      provider_profile_version_id: '',
      embedding_provider_profile_version_id: '',
      reranker_provider_profile_version_id: '',
    })
  }
  const eligibleProfiles = (rule: RuleDraft) => [
    ...profiles,
    ...Object.values(selectedProfiles).filter((selectedProfile) => (
      !profiles.some((profile) => (
        profile.provider_profile_version_id === selectedProfile.provider_profile_version_id
      ))
    )),
  ].filter((profile) => (
    profile.state === 'APPROVED'
    && requiredJurisdiction.trim() !== ''
    && profile.jurisdiction === requiredJurisdiction.trim()
    && classificationRank[profile.maximum_classification] >= classificationRank[rule.classification]
    && (rule.chat_mode !== 'INTERNAL_APPROVED_ONLY' || profile.kind === 'INTERNAL')
    && (rule.classification !== 'CONFIDENTIAL' || profile.kind === 'INTERNAL')
    && attestationsAreCurrent(profile)
  ))
  const ruleColumns: ColumnDef<RuleDraft>[] = [
    {
      accessorKey: 'classification', header: '등급명', size: 180,
      cell: ({ row }) => <strong>{classificationLabel(row.original.classification)}</strong>,
    },
    {
      accessorKey: 'search_mode', header: messages.searchMode, size: 180,
      cell: ({ row }) => <select
        aria-label={`${row.original.classification} ${messages.searchMode}`}
        value={row.original.search_mode}
        onChange={(event) => changeRule(row.original.classification, { search_mode: event.target.value as ClassificationSearchMode })}
      >
        {row.original.classification === 'RESTRICTED'
          ? <><option value="DENY">DENY</option><option value="EXPLICIT_GRANT_ONLY">EXPLICIT_GRANT_ONLY</option></>
          : <><option value="DENY">DENY</option><option value="ABAC">ABAC</option></>}
      </select>,
    },
    {
      accessorKey: 'chat_mode', header: messages.chatMode, size: 300,
      cell: ({ row }) => {
        const rule = row.original
        const candidates = eligibleProfiles(rule)
        return <div className="grid min-w-64 gap-1">
          {rule.classification === 'RESTRICTED'
            ? <><input aria-label={`RESTRICTED ${messages.chatMode}`} value="DENY" readOnly /><small>RESTRICTED Chat은 정책상 항상 차단됩니다.</small></>
            : <select aria-label={`${rule.classification} ${messages.chatMode}`} value={rule.chat_mode} onChange={(event) => changeChatMode(rule.classification, event.target.value as ClassificationChatMode)}>
              <option value="DENY">DENY</option>
              <option value="INTERNAL_APPROVED_ONLY">INTERNAL_APPROVED_ONLY</option>
              {rule.classification !== 'CONFIDENTIAL' && <option value="APPROVED_PROVIDER_ONLY">APPROVED_PROVIDER_ONLY</option>}
            </select>}
          {rule.chat_mode !== 'DENY' && <>
            {([
              ['provider_profile_version_id', 'Composition profile', true],
              ['embedding_provider_profile_version_id', 'Embedding profile', false],
              ['reranker_provider_profile_version_id', 'Reranker profile', false],
            ] as const).map(([field, label, required]) => (
              <label key={field}>
                <span className="text-xs text-slate-600">{label}{required ? ' · 필수' : ' · 선택'}</span>
                <select
                  aria-label={`${rule.classification} ${required ? messages.providerProfile : label}`}
                  value={rule[field]}
                  onChange={(event) => {
                    const providerProfileVersionId = event.target.value
                    const selectedProfile = candidates.find((profile) => (
                      profile.provider_profile_version_id === providerProfileVersionId
                    ))
                    if (selectedProfile) {
                      setSelectedProfiles((current) => ({
                        ...current,
                        [selectedProfile.provider_profile_version_id]: selectedProfile,
                      }))
                    }
                    changeRule(rule.classification, { [field]: providerProfileVersionId })
                  }}
                  required={required}
                >
                  <option value="">{required ? messages.chooseProvider : '사용하지 않음'}</option>
                  {candidates.map((profile) => <option key={profile.provider_profile_version_id} value={profile.provider_profile_version_id}>{profile.profile_key} v{profile.profile_version} · {profile.kind} · {profile.region}</option>)}
                </select>
              </label>
            ))}
            {candidates.length === 0 && <small>{messages.noEligibleProvider}</small>}
          </>}
        </div>
      },
    },
    {
      id: 'description', header: '설명', size: 360,
      cell: ({ row }) => <span className="text-xs leading-5 text-slate-600">{classificationDescriptions[row.original.classification]}</span>,
    },
    {
      id: 'manage', header: '관리', size: 140, enableSorting: false,
      cell: () => <div className="flex gap-1"><span className="badge badge-soft">편집 중</span><button type="button" className="button button-secondary" disabled title="네 등급은 서버 보안 계약의 고정 vocabulary이므로 개별 삭제할 수 없습니다.">삭제</button></div>,
    },
  ]

  const propose = (event: FormEvent) => {
    event.preventDefault()
    if (!canPropose) return
    const jurisdiction = requiredJurisdiction.trim()
    const maximumDays = Number(grantMaximumDays)
    const invalidProviderBinding = rules.some((rule) => (
      rule.chat_mode !== 'DENY' && !rule.provider_profile_version_id
    ))
    if (!jurisdiction || !Number.isInteger(maximumDays) || maximumDays < 1
      || !proposalReason.trim() || invalidProviderBinding) return
    const proposalRules: ClassificationAccessRule[] = rules.map((rule) => ({
      classification: rule.classification,
      search_mode: rule.search_mode,
      chat_mode: rule.chat_mode,
      provider_profile_version_id: rule.chat_mode === 'DENY'
        ? null
        : rule.provider_profile_version_id,
      embedding_provider_profile_version_id: rule.chat_mode === 'DENY'
        ? null
        : rule.embedding_provider_profile_version_id || null,
      reranker_provider_profile_version_id: rule.chat_mode === 'DENY'
        ? null
        : rule.reranker_provider_profile_version_id || null,
    }))
    const payload = {
      required_jurisdiction: jurisdiction,
      restricted_search_grant_maximum_days: maximumDays,
      rules: proposalRules,
      reason: proposalReason.trim(),
    }
    const intent = `classification-policy-propose:${JSON.stringify(payload)}`
    requestConfirmation({
      title: messages.classificationPolicyProposal,
      summary: [
        `${messages.jurisdiction}: ${jurisdiction}`,
        `${messages.grantMaximumDays}: ${maximumDays}`,
        ...proposalRules.map(ruleSummary),
        proposalReason.trim(),
      ],
      execute: async () => {
        const next = await api.proposeClassificationAccessPolicy(
          payload,
          keyFor(intent, 'classification-policy-propose'),
        )
        clearKey(intent)
        setRequiredJurisdiction(''); setGrantMaximumDays('')
        setRules(emptyPolicyRules()); setProposalReason('')
        await Promise.all([
          reloadFirstPage(),
          loadAuxiliary(auxiliaryChannel.next()),
        ])
        setSelectedId(next.policy_id)
      },
    })
  }

  const selected = policies.find((policy) => policy.policy_id === selectedId)
  const decide = (decision: 'APPROVED' | 'REJECTED') => {
    if (!canDecide || !selected || !decisionReason.trim()) return
    const intent = `classification-policy-decision:${selected.policy_id}:${selected.version}:${decision}:${decisionReason}`
    requestConfirmation({
      title: `${messages.classificationPolicyProposal}: ${decision}`,
      summary: [
        `#${selected.policy_number}`,
        selected.payload_hash,
        `v${selected.version}`,
        decisionReason.trim(),
      ],
      execute: async () => {
        await api.decideClassificationAccessPolicy(
          selected,
          decision,
          decisionReason.trim(),
          keyFor(intent, 'classification-policy-decision'),
        )
        clearKey(intent); setDecisionReason('')
        await Promise.all([
          reloadFirstPage(),
          loadAuxiliary(auxiliaryChannel.next()),
        ])
      },
    })
  }
  const canCheck = Boolean(
    canDecide
    && selected?.state === 'PROPOSED'
    && context
    && context.subject_id !== selected.requester_id,
  )

  const showDetails = () => {
    if (!canReadDetails) return
    if (!hasFreshDetailAssurance) {
      void (props.hardwareWebauthnEnabled === false
        ? props.onPasswordReauth()
        : props.onStepUp())
      return
    }
    setDetailsOpen(true)
  }

  return <>
    <section className="panel form-stack">
      <div className="section-heading">
        <div>
          <p className="eyebrow">현재 유효 분류 정책</p>
          <h3>서비스별 데이터 접근 요약</h3>
        </div>
        <button
          type="button"
          className="button button-secondary"
          disabled={!canReadDetails}
          onClick={showDetails}
        >상세 이력 보기</button>
      </div>
      {summaryLoading
        ? <p className="callout">현재 유효 정책을 확인하고 있습니다.</p>
        : summary
          ? <ClassificationPolicySummaryView summary={summary} />
          : <p className="callout">현재 정책 요약을 표시할 수 없습니다.</p>}
    </section>
    {detailsOpen && <>
    <div className="action-row justify-end">
      <button type="button" className="button button-secondary" onClick={clearDetails}>상세 닫기</button>
    </div>
    {currentPolicy
      ? <section className="panel">
        <p className="eyebrow">{messages.currentPolicy}</p>
        <PolicySummary policy={currentPolicy} />
      </section>
      : <p className="callout">{messages.activePolicyRequired}</p>}
    <div className="admin-two-column">
      <form className="panel form-stack" onSubmit={propose}>
        <h3>{messages.classificationPolicyProposal}</h3>
        {!canPropose && <p className="callout">최근 WebAuthn 인증 후 정책을 제안할 수 있습니다. 인증 후 작업은 자동으로 실행되지 않습니다.</p>}
        <fieldset className="contents" disabled={!canPropose}>
        <p className="callout">네 등급의 계약은 유지하며, 현재 운영 프로파일은 CONFIDENTIAL(대외비)과 RESTRICTED(극비)를 중심으로 사용합니다. PUBLIC·INTERNAL을 삭제하거나 다른 등급으로 자동 변환하지 않습니다.</p>
        <label>{messages.jurisdiction}
          <input
            value={requiredJurisdiction}
            onChange={(event) => changeJurisdiction(event.target.value)}
            maxLength={64}
            autoComplete="off"
            required
          />
        </label>
        <label>{messages.grantMaximumDays}
          <input type="number" min={1} max={365} value={grantMaximumDays} onChange={(event) => setGrantMaximumDays(event.target.value)} required />
        </label>
        <fieldset className="grid gap-2">
          <legend className="mb-2 text-xs font-black text-navy-900">{messages.classificationMatrix}</legend>
          <DenseDataTable caption="데이터 분류 접근 정책" columns={ruleColumns} data={rules} getRowId={(rule) => rule.classification} emptyMessage="분류 정책 행이 없습니다." />
          <small>등급 행 삭제 대신 Search/Chat 모드를 DENY로 설정합니다. 네 등급과 RESTRICTED Chat 차단은 서버 보안 계약이며 정책 제안·독립 승인 후에만 활성화됩니다.</small>
          <label>승인 Provider profile key 검색<input type="search" value={providerKeyQuery} onChange={(event) => setProviderKeyQuery(event.target.value)} placeholder="정확한 profile key" /></label>
          <small>승인 Provider 선택지는 정확한 key 검색 결과를 서버 페이지 단위로 조회합니다.{profilesTruncated ? ' 다음 페이지에서 나머지 버전을 확인할 수 있습니다.' : ''}</small>
          <PageNavigation
            page={providerPageNumber}
            canPrevious={providerCursorHistory.length > 0}
            canNext={Boolean(providerNextCursor)}
            onPrevious={() => {
              const previous = providerCursorHistory.at(-1) ?? null
              setProviderCursorHistory((history) => history.slice(0, -1))
              setProviderCursor(previous ?? undefined)
              setProviderPageNumber((page) => Math.max(1, page - 1))
            }}
            onNext={() => {
              if (!providerNextCursor) return
              setProviderCursorHistory((history) => [...history.slice(-49), providerCursor ?? null])
              setProviderCursor(providerNextCursor)
              setProviderPageNumber((page) => page + 1)
            }}
          />
        </fieldset>
        <label>{messages.reason}<textarea value={proposalReason} onChange={(event) => setProposalReason(event.target.value)} maxLength={4000} required /></label>
        <button className="button">{messages.propose}</button>
        </fieldset>
      </form>
      <section className="panel">
        <div className="section-heading"><h3>{messages.classificationPolicyHistory}</h3><button className="button button-secondary" onClick={() => void Promise.all([load(cursor, listChannel.next()), loadAuxiliary(auxiliaryChannel.next())])}>{messages.refresh}</button></div>
        <label>상태 필터<select value={stateFilter} onChange={(event) => { setStateFilter(event.target.value as ClassificationAccessPolicyState | ''); resetPage() }}><option value="">전체</option><option>PROPOSED</option><option>ACTIVE</option><option>REJECTED</option><option>SUPERSEDED</option></select></label>
        <div className="compact-list">{policies.map((policy) => <button key={policy.policy_id} className={selectedId === policy.policy_id ? 'selected' : ''} onClick={() => setSelectedId(policy.policy_id)}>
          <span><strong>#{policy.policy_number} · {policy.required_jurisdiction}</strong><small>{policy.request_reason}</small></span><span className="badge">{policy.state}</span>
        </button>)}</div>
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
      <PolicySummary policy={selected} />
      {selected.state === 'PROPOSED' && <>
        <label>{messages.reason}<textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} maxLength={4000} /></label>
        <div className="action-row">{canCheck
          ? <><button className="button" disabled={!decisionReason.trim()} onClick={() => decide('APPROVED')}>{messages.approve}</button><button className="button button-secondary" disabled={!decisionReason.trim()} onClick={() => decide('REJECTED')}>{messages.reject}</button></>
          : <p className="callout">{canDecide ? messages.makerCannotCheck : '최근 WebAuthn 인증 후 독립 승인할 수 있습니다.'}</p>}
        </div>
      </>}
    </section>}
    </>}
  </>
}

export function InferenceProviderProfileAdmin(props: Props) {
  const { api, context, messages, requestConfirmation, keyFor, clearKey, reportError } = props
  const [profiles, setProfiles] = useState<InferenceProviderProfile[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [decisionReason, setDecisionReason] = useState('')
  const [revocationReason, setRevocationReason] = useState('')
  const [profileKeyInput, setProfileKeyInput] = useState('')
  const [profileKey, setProfileKey] = useState('')
  const [stateFilter, setStateFilter] = useState<InferenceProviderProfileState | ''>('')
  const [cursor, setCursor] = useState<string>()
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [pageNumber, setPageNumber] = useState(1)
  const loadGeneration = useRef(0)
  const listChannel = useAbortSignalChannel()
  const canDecide = context?.allowed_operations.includes(
    'INFERENCE_PROVIDER_PROFILE_DECIDE',
  ) ?? false
  const canRevoke = context?.allowed_operations.includes(
    'INFERENCE_PROVIDER_PROFILE_REVOKE',
  ) ?? false

  const load = useCallback(async (pageCursor: string | undefined, signal?: AbortSignal) => {
    const generation = ++loadGeneration.current
    try {
      const page = await api.listInferenceProviderProfilePage({
        profileKey: profileKey.trim() || undefined,
        state: stateFilter || undefined,
        cursor: pageCursor,
        limit: 25,
        signal,
      })
      if (generation !== loadGeneration.current) return
      setProfiles(page.items)
      setNextCursor(page.nextCursor)
      setSelectedId((current) => (
        current && page.items.some((profile) => profile.provider_profile_version_id === current)
          ? current
          : page.items[0]?.provider_profile_version_id || ''
      ))
    } catch (error) {
      if (!signal?.aborted && generation === loadGeneration.current) reportError(error)
    }
  }, [api, profileKey, reportError, stateFilter])
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

  const selected = profiles.find((profile) => profile.provider_profile_version_id === selectedId)
  const decide = (decision: 'APPROVED' | 'REJECTED') => {
    if (!canDecide || !selected || !decisionReason.trim()) return
    const intent = `provider-profile-decision:${selected.provider_profile_version_id}:${selected.version}:${decision}:${decisionReason}`
    requestConfirmation({
      title: `${messages.providerDecision}: ${decision}`,
      summary: [selected.profile_key, `v${selected.profile_version}`, selected.payload_hash, `aggregate v${selected.version}`],
      execute: async () => {
        const next = await api.decideInferenceProviderProfile(
          selected, decision, decisionReason.trim(), keyFor(intent, 'provider-profile-decision'),
        )
        clearKey(intent); setDecisionReason('')
        await reloadFirstPage()
        setSelectedId(next.provider_profile_version_id)
      },
    })
  }
  const revoke = () => {
    if (!canRevoke || !selected || !revocationReason.trim()) return
    const intent = `provider-profile-revoke:${selected.provider_profile_version_id}:${selected.version}:${revocationReason}`
    requestConfirmation({
      title: messages.revoke,
      summary: [selected.profile_key, `v${selected.profile_version}`, selected.payload_hash, revocationReason.trim()],
      execute: async () => {
        const next = await api.revokeInferenceProviderProfile(
          selected, revocationReason.trim(), keyFor(intent, 'provider-profile-revoke'),
        )
        clearKey(intent); setRevocationReason('')
        await reloadFirstPage()
        setSelectedId(next.provider_profile_version_id)
      },
    })
  }
  const canCheck = Boolean(
    canDecide
    && selected?.state === 'PROPOSED'
    && context
    && context.subject_id !== selected.maker_id,
  )

  return <>
    <p className="callout">{messages.providerReadOnly}</p>
    <div className="admin-two-column">
      <section className="panel">
        <div className="section-heading"><h3>{messages.providerHistory}</h3><button className="button button-secondary" onClick={() => void load(cursor, listChannel.next())}>{messages.refresh}</button></div>
        <form className="action-row" onSubmit={(event) => {
          event.preventDefault()
          const normalized = profileKeyInput.trim()
          resetPage()
          if (normalized === profileKey) void load(undefined, listChannel.next())
          else setProfileKey(normalized)
        }}>
          <label>프로파일 키 검색<input type="search" value={profileKeyInput} onChange={(event) => setProfileKeyInput(event.target.value)} placeholder="정확한 profile key" /></label>
          <button type="submit" className="button button-secondary">검색</button>
        </form>
        <label>상태 필터<select value={stateFilter} onChange={(event) => { setStateFilter(event.target.value as InferenceProviderProfileState | ''); resetPage() }}><option value="">전체</option><option>PROPOSED</option><option>APPROVED</option><option>REJECTED</option><option>REVOKED</option></select></label>
        <div className="compact-list">{profiles.map((profile) => <button key={profile.provider_profile_version_id} className={selectedId === profile.provider_profile_version_id ? 'selected' : ''} onClick={() => setSelectedId(profile.provider_profile_version_id)}>
          <span><strong>{profile.profile_key} · v{profile.profile_version}</strong><small>{profile.kind} · {profile.region} · {profile.jurisdiction}</small></span><span className="badge">{profile.state}</span>
        </button>)}</div>
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
      <section className="panel form-stack">{selected ? <>
        <h3>{selected.profile_key} · v{selected.profile_version}</h3>
        <dl className="summary-list">
          <div><dt>provider</dt><dd>{selected.provider_identity}</dd></div>
          <div><dt>model</dt><dd>{selected.model_identity}</dd></div>
          <div><dt>deployment</dt><dd>{selected.deployment_identity}</dd></div>
          <div><dt>kind</dt><dd>{selected.kind}</dd></div>
          <div><dt>{messages.jurisdiction}</dt><dd>{selected.jurisdiction}</dd></div>
          <div><dt>region</dt><dd>{selected.region}</dd></div>
          <div><dt>maximum classification</dt><dd>{selected.maximum_classification}</dd></div>
          <div><dt>maker</dt><dd>{selected.maker_id}</dd></div>
          <div><dt>version</dt><dd>{selected.version}</dd></div>
        </dl>
        <AttestationSummary label={messages.residencyAttestation} value={selected.residency_attestation} />
        <AttestationSummary label={messages.zeroRetentionAttestation} value={selected.zero_retention_attestation} />
        <code>{selected.payload_hash}</code>
        {selected.state === 'PROPOSED' && <>
          <label>{messages.reason}<textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} maxLength={4000} /></label>
          <div className="action-row">{canCheck
            ? <><button className="button" disabled={!decisionReason.trim()} onClick={() => decide('APPROVED')}>{messages.approve}</button><button className="button button-secondary" disabled={!decisionReason.trim()} onClick={() => decide('REJECTED')}>{messages.reject}</button></>
            : <p className="callout">{canDecide ? messages.makerCannotCheck : '최근 WebAuthn 인증 후 Provider 결정을 수행할 수 있습니다.'}</p>}
          </div>
        </>}
        {selected.state === 'APPROVED' && canRevoke && <>
          <label>{messages.revocationReason}<textarea value={revocationReason} onChange={(event) => setRevocationReason(event.target.value)} maxLength={4000} /></label>
          <button className="button button-secondary" disabled={!revocationReason.trim()} onClick={revoke}>{messages.revoke}</button>
        </>}
        {selected.state === 'APPROVED' && !canRevoke && <p className="callout">최근 WebAuthn 인증 후 Provider 승인을 철회할 수 있습니다.</p>}
      </> : <p className="muted">{messages.empty}</p>}</section>
    </div>
  </>
}

export function RestrictedSearchGrantAdmin(props: Props) {
  const { api, context, messages, requestConfirmation, keyFor, clearKey, reportError } = props
  const [grants, setGrants] = useState<RestrictedSearchGrant[]>([])
  const [members, setMembers] = useState<WorkspaceMembershipSummary[]>([])
  const [systems, setSystems] = useState<SystemDirectoryEntry[]>([])
  const [currentPolicy, setCurrentPolicy] = useState<ClassificationAccessPolicy | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [subjectId, setSubjectId] = useState('')
  const [scope, setScope] = useState<RestrictedSearchScope | ''>('')
  const [scopeId, setScopeId] = useState('')
  const [targetQuery, setTargetQuery] = useState('')
  const [targetResults, setTargetResults] = useState<CatalogAsset[]>([])
  const [targetSearching, setTargetSearching] = useState(false)
  const [purpose, setPurpose] = useState('')
  const [validFrom, setValidFrom] = useState('')
  const [expiresAt, setExpiresAt] = useState('')
  const [proposalReason, setProposalReason] = useState('')
  const [decisionReason, setDecisionReason] = useState('')
  const [revocationReason, setRevocationReason] = useState('')
  const [stateFilter, setStateFilter] = useState<RestrictedSearchGrantState | ''>('')
  const [cursor, setCursor] = useState<string>()
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [pageNumber, setPageNumber] = useState(1)
  const [memberSelectorTruncated, setMemberSelectorTruncated] = useState(false)
  const [systemSelectorTruncated, setSystemSelectorTruncated] = useState(false)
  const [memberSelectorQuery, setMemberSelectorQuery] = useState('')
  const [appliedMemberSelectorQuery, setAppliedMemberSelectorQuery] = useState('')
  const [systemSelectorQuery, setSystemSelectorQuery] = useState('')
  const [appliedSystemSelectorQuery, setAppliedSystemSelectorQuery] = useState('')
  const loadGeneration = useRef(0)
  const auxiliaryGeneration = useRef(0)
  const listChannel = useAbortSignalChannel()
  const auxiliaryChannel = useAbortSignalChannel()
  const timeZone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, [])
  const canPropose = context?.allowed_operations.includes(
    'RESTRICTED_SEARCH_GRANT_PROPOSE',
  ) ?? false
  const canDecide = context?.allowed_operations.includes(
    'RESTRICTED_SEARCH_GRANT_DECIDE',
  ) ?? false
  const canRevoke = context?.allowed_operations.includes(
    'RESTRICTED_SEARCH_GRANT_REVOKE',
  ) ?? false

  const load = useCallback(async (pageCursor: string | undefined, signal?: AbortSignal) => {
    const generation = ++loadGeneration.current
    try {
      const grantPage = await api.listRestrictedSearchGrantPage({
        state: stateFilter || undefined,
        cursor: pageCursor,
        limit: 25,
        signal,
      })
      if (generation !== loadGeneration.current) return
      setGrants(grantPage.items)
      setNextCursor(grantPage.nextCursor)
      setSelectedId((current) => (
        current && grantPage.items.some((grant) => grant.grant_id === current)
          ? current
          : grantPage.items[0]?.grant_id || ''
      ))
    } catch (error) {
      if (!signal?.aborted && generation === loadGeneration.current) reportError(error)
    }
  }, [api, reportError, stateFilter])

  const loadAuxiliary = useCallback(async (signal?: AbortSignal) => {
    const generation = ++auxiliaryGeneration.current
    try {
      const [memberPage, systemPage, nextPolicy] = await Promise.all([
        api.listMembershipPage({
          query: appliedMemberSelectorQuery || undefined,
          status: 'ACTIVE',
          limit: 25,
          signal,
        }),
        api.listSystemPage({
          query: appliedSystemSelectorQuery || undefined,
          status: 'ACTIVE',
          limit: 25,
          signal,
        }),
        api.getCurrentClassificationAccessPolicy(signal),
      ])
      if (generation !== auxiliaryGeneration.current) return
      setMembers(memberPage.items)
      setSystems(systemPage.items)
      setMemberSelectorTruncated(Boolean(memberPage.nextCursor))
      setSystemSelectorTruncated(Boolean(systemPage.nextCursor))
      setCurrentPolicy(nextPolicy)
    } catch (error) {
      if (!signal?.aborted && generation === auxiliaryGeneration.current) reportError(error)
    }
  }, [
    api,
    appliedMemberSelectorQuery,
    appliedSystemSelectorQuery,
    reportError,
  ])

  useEffect(() => {
    void load(cursor, listChannel.next())
    return () => { loadGeneration.current += 1 }
  }, [cursor, listChannel, load])
  useEffect(() => {
    void loadAuxiliary(auxiliaryChannel.next())
    return () => { auxiliaryGeneration.current += 1 }
  }, [auxiliaryChannel, loadAuxiliary])
  useEffect(() => {
    const timer = window.setTimeout(
      () => setAppliedMemberSelectorQuery(memberSelectorQuery.trim()),
      250,
    )
    return () => window.clearTimeout(timer)
  }, [memberSelectorQuery])
  useEffect(() => {
    const timer = window.setTimeout(
      () => setAppliedSystemSelectorQuery(systemSelectorQuery.trim()),
      250,
    )
    return () => window.clearTimeout(timer)
  }, [systemSelectorQuery])

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
  const restrictedRule = currentPolicy?.rules.find((rule) => rule.classification === 'RESTRICTED')
  const grantEnabled = currentPolicy?.state === 'ACTIVE'
    && restrictedRule?.search_mode === 'EXPLICIT_GRANT_ONLY'
  const grantFormEnabled = grantEnabled && canPropose
  useEffect(() => {
    const normalized = targetQuery.trim()
    if (scope !== 'RESOURCE' || normalized.length < 2 || !grantFormEnabled) {
      setTargetResults([]); setTargetSearching(false); return
    }
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setTargetSearching(true)
      void api.searchRestrictedGrantTargets(normalized, controller.signal)
        .then((items) => { if (!controller.signal.aborted) setTargetResults(items) })
        .catch((error) => { if (!controller.signal.aborted) reportError(error) })
        .finally(() => { if (!controller.signal.aborted) setTargetSearching(false) })
    }, 220)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [api, grantFormEnabled, reportError, scope, targetQuery])
  const propose = (event: FormEvent) => {
    event.preventDefault()
    if (!canPropose || !currentPolicy || !grantEnabled || !subjectId || !scope || !scopeId.trim()
      || !purpose.trim() || !validFrom || !expiresAt || !proposalReason.trim()) return
    const validFromValue = Date.parse(validFrom)
    const expiresAtValue = Date.parse(expiresAt)
    const maximumMilliseconds = currentPolicy.restricted_search_grant_maximum_days * 86_400_000
    if (!Number.isFinite(validFromValue) || !Number.isFinite(expiresAtValue)
      || expiresAtValue <= validFromValue || expiresAtValue - validFromValue > maximumMilliseconds) {
      reportError(new Error(`${messages.grantMaximumHint}: ${currentPolicy.restricted_search_grant_maximum_days} days`))
      return
    }
    const payload: RestrictedSearchGrantProposal = {
      subject_id: subjectId,
      scope,
      scope_id: scopeId.trim(),
      purpose: purpose.trim(),
      valid_from: new Date(validFromValue).toISOString(),
      expires_at: new Date(expiresAtValue).toISOString(),
      reason: proposalReason.trim(),
    }
    const intent = `restricted-search-grant-propose:${JSON.stringify(payload)}`
    requestConfirmation({
      title: messages.restrictedGrantProposal,
      summary: [payload.subject_id, `${payload.scope}: ${payload.scope_id}`, payload.purpose, `${payload.valid_from} → ${payload.expires_at}`],
      execute: async () => {
        const next = await api.proposeRestrictedSearchGrant(
          payload,
          keyFor(intent, 'restricted-search-grant-propose'),
        )
        clearKey(intent); setSubjectId(''); setScope(''); setScopeId(''); setTargetQuery(''); setTargetResults([]); setPurpose('')
        setValidFrom(''); setExpiresAt(''); setProposalReason('')
        await reloadFirstPage()
        setSelectedId(next.grant_id)
      },
    })
  }

  const selected = grants.find((grant) => grant.grant_id === selectedId)
  const decide = (decision: 'APPROVED' | 'REJECTED') => {
    if (!canDecide || !selected || !decisionReason.trim()) return
    const intent = `restricted-search-grant-decision:${selected.grant_id}:${selected.version}:${decision}:${decisionReason}`
    requestConfirmation({
      title: `${messages.restrictedGrantProposal}: ${decision}`,
      summary: [selected.subject_id, `${selected.scope}: ${selected.scope_id}`, selected.payload_hash, `v${selected.version}`],
      execute: async () => {
        const next = await api.decideRestrictedSearchGrant(
          selected, decision, decisionReason.trim(), keyFor(intent, 'restricted-search-grant-decision'),
        )
        clearKey(intent); setDecisionReason('')
        await reloadFirstPage()
        setSelectedId(next.grant_id)
      },
    })
  }
  const revoke = () => {
    if (!canRevoke || !selected || !revocationReason.trim()) return
    const intent = `restricted-search-grant-revoke:${selected.grant_id}:${selected.version}:${revocationReason}`
    requestConfirmation({
      title: messages.revoke,
      summary: [selected.subject_id, `${selected.scope}: ${selected.scope_id}`, selected.payload_hash, revocationReason.trim()],
      execute: async () => {
        const next = await api.revokeRestrictedSearchGrant(
          selected, revocationReason.trim(), keyFor(intent, 'restricted-search-grant-revoke'),
        )
        clearKey(intent); setRevocationReason('')
        await reloadFirstPage()
        setSelectedId(next.grant_id)
      },
    })
  }
  const canCheck = Boolean(
    canDecide && selected?.state === 'PENDING' && context
    && context.subject_id !== selected.requester_id
    && context.subject_id !== selected.subject_id,
  )

  return <>
    {!currentPolicy && <p className="callout">{messages.activePolicyRequired}</p>}
    {currentPolicy && !grantEnabled && <p className="callout">{messages.restrictedGrantDisabled}</p>}
    {grantEnabled && !canPropose && <p className="callout">최근 WebAuthn 인증 후 RESTRICTED Search Grant를 제안할 수 있습니다.</p>}
    <div className="admin-two-column">
      <form className="panel form-stack" onSubmit={propose}>
        <h3>{messages.restrictedGrantProposal}</h3>
        {currentPolicy && <p className="callout">{messages.grantMaximumHint}: {currentPolicy.restricted_search_grant_maximum_days} days · #{currentPolicy.policy_number}</p>}
        <label>대상 사용자 검색<input type="search" value={memberSelectorQuery} onChange={(event) => setMemberSelectorQuery(event.target.value)} placeholder="이름 또는 이메일" disabled={!grantFormEnabled} /></label>
        <label>{messages.subject}<select value={subjectId} onChange={(event) => setSubjectId(event.target.value)} required disabled={!grantFormEnabled}>
          <option value="">{messages.select}</option>
          {subjectId && !members.some((member) => member.subject_id === subjectId) && <option value={subjectId}>{subjectId} · 현재 검색 결과 외 선택</option>}
          {members.filter((member) => member.subject_active && member.membership_active).map((member) => <option key={member.subject_id} value={member.subject_id}>{member.display_name} · {member.subject_id}</option>)}
        </select></label>
        <small>대상 사용자는 활성 멤버십 검색 결과 첫 25건입니다.{memberSelectorTruncated ? ' 결과가 더 있으면 이름 또는 이메일을 더 정확히 입력하세요.' : ''}</small>
        <label>{messages.scope}<select value={scope} onChange={(event) => { setScope(event.target.value as RestrictedSearchScope | ''); setScopeId(''); setTargetQuery(''); setTargetResults([]) }} required disabled={!grantFormEnabled}>
          <option value="">{messages.select}</option><option value="RESOURCE">RESOURCE</option><option value="SYSTEM">SYSTEM</option><option value="DOMAIN">DOMAIN</option>
        </select></label>
        {scope === 'RESOURCE' ? <div className="grid gap-2"><label>스키마·테이블 검색<input type="search" value={targetQuery} onChange={(event) => { setTargetQuery(event.target.value); setScopeId('') }} placeholder="플랫폼, 스키마 또는 테이블명" disabled={!grantFormEnabled} /></label>{targetSearching && <small>권한 범위의 카탈로그를 검색하는 중입니다.</small>}<div className="compact-list" aria-label="극비 접근 대상 검색 결과">{targetResults.map((asset) => <button type="button" key={asset.id} className={scopeId === asset.id ? 'selected' : ''} onClick={() => { setScopeId(asset.id); setTargetQuery(`${asset.platform ?? '—'} · ${asset.schema_name ?? '—'} · ${asset.name}`); setTargetResults([]) }}><span><strong>{asset.name}</strong><small>{asset.platform ?? '—'} · {asset.database_name ?? '—'} · {asset.schema_name ?? '—'} · {asset.asset_type}</small></span><span className="badge badge-soft">{asset.classification}</span></button>)}</div>{targetQuery.trim().length >= 2 && !targetSearching && targetResults.length === 0 && !scopeId && <small>현재 권한 범위에 일치하는 스키마·테이블이 없습니다.</small>}<input type="hidden" name="restricted-resource-id" value={scopeId} required /></div>
          : scope === 'SYSTEM' ? <><label>시스템 검색<input type="search" value={systemSelectorQuery} onChange={(event) => setSystemSelectorQuery(event.target.value)} placeholder="시스템명 또는 코드" disabled={!grantFormEnabled} /></label><label>{messages.scopeId}<select value={scopeId} onChange={(event) => setScopeId(event.target.value)} required disabled={!grantFormEnabled}><option value="">시스템 선택</option>{scopeId && !systems.some((system) => system.system_id === scopeId) && <option value={scopeId}>{scopeId} · 현재 검색 결과 외 선택</option>}{systems.filter((system) => system.active).map((system) => <option key={system.system_id} value={system.system_id}>{system.name} · {system.code}</option>)}</select></label></>
            : <label>{messages.scopeId}<input value={scopeId} onChange={(event) => setScopeId(event.target.value)} required pattern="[0-9a-fA-F-]{36}" disabled={!grantFormEnabled} /><small>DOMAIN 정본 ID 조회 UI는 아직 제공되지 않습니다. UUID를 임의 생성하지 마세요.</small></label>}
        <label>{messages.purpose}<textarea value={purpose} onChange={(event) => setPurpose(event.target.value)} maxLength={4000} required disabled={!grantFormEnabled} /></label>
        <label>{messages.validFrom}<input type="datetime-local" value={validFrom} onChange={(event) => setValidFrom(event.target.value)} required disabled={!grantFormEnabled} /></label>
        <label>{messages.expiresAt}<input type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} required disabled={!grantFormEnabled} /></label>
        <small>{messages.browserTimezone}: {timeZone}</small>
        <label>{messages.reason}<textarea value={proposalReason} onChange={(event) => setProposalReason(event.target.value)} maxLength={4000} required disabled={!grantFormEnabled} /></label>
        <button className="button" disabled={!grantFormEnabled}>{messages.propose}</button>
        <small>시스템 선택지는 활성 시스템 검색 결과 첫 25건입니다.{systemSelectorTruncated ? ' 결과가 더 있으면 시스템명 또는 코드를 더 정확히 입력하세요.' : ''}</small>
      </form>
      <section className="panel">
        <div className="section-heading"><h3>{messages.restrictedGrantHistory}</h3><button className="button button-secondary" onClick={() => void Promise.all([load(cursor, listChannel.next()), loadAuxiliary(auxiliaryChannel.next())])}>{messages.refresh}</button></div>
        <label>상태 필터<select value={stateFilter} onChange={(event) => { setStateFilter(event.target.value as RestrictedSearchGrantState | ''); resetPage() }}><option value="">전체</option><option>PENDING</option><option>ACTIVE</option><option>REJECTED</option><option>REVOKED</option></select></label>
        <div className="compact-list">{grants.map((grant) => <button key={grant.grant_id} className={selectedId === grant.grant_id ? 'selected' : ''} onClick={() => setSelectedId(grant.grant_id)}>
          <span><strong>{grant.subject_id}</strong><small>{grant.scope}: {grant.scope_id} · {formatDate(grant.expires_at)}</small></span><span className="badge">{grant.state}</span>
        </button>)}</div>
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
      <h3>{selected.state} · {selected.subject_id}</h3>
      <dl className="summary-list">
        <div><dt>{messages.scope}</dt><dd>{selected.scope}: {selected.scope_id}</dd></div>
        <div><dt>{messages.purpose}</dt><dd>{selected.purpose}</dd></div>
        <div><dt>{messages.validFrom}</dt><dd>{formatDate(selected.valid_from)}</dd></div>
        <div><dt>{messages.expiresAt}</dt><dd>{formatDate(selected.expires_at)}</dd></div>
        <div><dt>maker</dt><dd>{selected.requester_id}</dd></div>
        <div><dt>version</dt><dd>{selected.version}</dd></div>
        <div><dt>policy</dt><dd>{selected.classification_policy_id}</dd></div>
      </dl>
      <code>{selected.classification_policy_hash}</code><code>{selected.payload_hash}</code>
      {selected.state === 'PENDING' && <>
        <label>{messages.reason}<textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} maxLength={4000} /></label>
        <div className="action-row">{canCheck
          ? <><button className="button" disabled={!decisionReason.trim()} onClick={() => decide('APPROVED')}>{messages.approve}</button><button className="button button-secondary" disabled={!decisionReason.trim()} onClick={() => decide('REJECTED')}>{messages.reject}</button></>
          : <p className="callout">{canDecide ? messages.makerCannotCheck : '최근 WebAuthn 인증 후 Grant를 독립 승인할 수 있습니다.'}</p>}
        </div>
      </>}
      {selected.state === 'ACTIVE' && canRevoke && <>
        <label>{messages.revocationReason}<textarea value={revocationReason} onChange={(event) => setRevocationReason(event.target.value)} maxLength={4000} /></label>
        <button className="button button-secondary" disabled={!revocationReason.trim()} onClick={revoke}>{messages.revoke}</button>
      </>}
      {selected.state === 'ACTIVE' && !canRevoke && <p className="callout">최근 WebAuthn 인증 후 Grant를 철회할 수 있습니다.</p>}
    </section>}
  </>
}

function PolicySummary({ policy }: { policy: ClassificationAccessPolicy }) {
  return <>
    <h3>#{policy.policy_number} · {policy.state}</h3>
    <dl className="summary-list">
      <div><dt>jurisdiction</dt><dd>{policy.required_jurisdiction}</dd></div>
      <div><dt>grant maximum</dt><dd>{policy.restricted_search_grant_maximum_days} days</dd></div>
      <div><dt>maker</dt><dd>{policy.requester_id}</dd></div>
      <div><dt>version</dt><dd>{policy.version}</dd></div>
    </dl>
    <div className="compact-list">{policy.rules.map((rule) => <div className="panel" key={rule.classification}>
      <strong>{rule.classification}</strong><small>{rule.search_mode} · {rule.chat_mode}</small>
      {rule.provider_profile_version_id && <code>composition · {rule.provider_profile_version_id}</code>}
      {rule.embedding_provider_profile_version_id && <code>embedding · {rule.embedding_provider_profile_version_id}</code>}
      {rule.reranker_provider_profile_version_id && <code>reranker · {rule.reranker_provider_profile_version_id}</code>}
    </div>)}</div>
    <code>{policy.payload_hash}</code>
  </>
}

function AttestationSummary({ label, value }: {
  label: string
  value: InferenceProviderProfile['residency_attestation']
}) {
  return <section className="panel">
    <strong>{label}</strong>
    <dl className="summary-list">
      <div><dt>observed</dt><dd>{formatDate(value.observed_at)}</dd></div>
      <div><dt>expires</dt><dd>{formatDate(value.expires_at)}</dd></div>
    </dl>
    <code>{value.fingerprint}</code>
  </section>
}

function attestationsAreCurrent(profile: InferenceProviderProfile, now = Date.now()): boolean {
  return [profile.residency_attestation, profile.zero_retention_attestation].every((attestation) => {
    const observedAt = Date.parse(attestation.observed_at)
    const expiresAt = Date.parse(attestation.expires_at)
    return Number.isFinite(observedAt) && Number.isFinite(expiresAt)
      && observedAt <= now && now < expiresAt
  })
}

function ruleSummary(rule: ClassificationAccessRule): string {
  return `${rule.classification}: Search=${rule.search_mode}, Chat=${rule.chat_mode}, Composition=${rule.provider_profile_version_id ?? 'none'}, Embedding=${rule.embedding_provider_profile_version_id ?? 'none'}, Reranker=${rule.reranker_provider_profile_version_id ?? 'none'}`
}

function formatDate(value: string): string {
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString() : value
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
