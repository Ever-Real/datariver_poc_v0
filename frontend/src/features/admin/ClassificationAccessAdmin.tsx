import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import type {
  AdminReadContext,
  Classification,
  ClassificationAccessPolicy,
  ClassificationAccessRule,
  ClassificationChatMode,
  ClassificationSearchMode,
  InferenceProviderProfile,
  RestrictedSearchGrant,
  RestrictedSearchGrantProposal,
  RestrictedSearchScope,
  WorkspaceMembershipSummary,
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

interface RuleDraft {
  classification: Classification
  search_mode: ClassificationSearchMode
  chat_mode: ClassificationChatMode
  provider_profile_version_id: string
}

const classifications = ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'] as const
const classificationRank: Record<Classification, number> = {
  PUBLIC: 0,
  INTERNAL: 1,
  CONFIDENTIAL: 2,
  RESTRICTED: 3,
}

function emptyPolicyRules(): RuleDraft[] {
  return classifications.map((classification) => ({
    classification,
    search_mode: 'DENY',
    chat_mode: 'DENY',
    provider_profile_version_id: '',
  }))
}

export function ClassificationPolicyAdmin(props: Props) {
  const { api, context, messages, requestConfirmation, keyFor, clearKey, reportError } = props
  const [policies, setPolicies] = useState<ClassificationAccessPolicy[]>([])
  const [currentPolicy, setCurrentPolicy] = useState<ClassificationAccessPolicy | null>(null)
  const [profiles, setProfiles] = useState<InferenceProviderProfile[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [requiredJurisdiction, setRequiredJurisdiction] = useState('')
  const [grantMaximumDays, setGrantMaximumDays] = useState('')
  const [rules, setRules] = useState<RuleDraft[]>(emptyPolicyRules)
  const [proposalReason, setProposalReason] = useState('')
  const [decisionReason, setDecisionReason] = useState('')

  const load = useCallback(async () => {
    try {
      const [nextPolicies, nextCurrent, nextProfiles] = await Promise.all([
        api.listClassificationAccessPolicies(),
        api.getCurrentClassificationAccessPolicy(),
        api.listInferenceProviderProfiles('APPROVED'),
      ])
      setPolicies(nextPolicies)
      setCurrentPolicy(nextCurrent)
      setProfiles(nextProfiles)
      setSelectedId((selected) => selected || nextCurrent?.policy_id || nextPolicies[0]?.policy_id || '')
    } catch (error) { reportError(error) }
  }, [api, reportError])
  useEffect(() => { void load() }, [load])

  const changeJurisdiction = (value: string) => {
    setRequiredJurisdiction(value)
    setRules((current) => current.map((rule) => ({ ...rule, provider_profile_version_id: '' })))
  }
  const changeRule = (classification: Classification, patch: Partial<RuleDraft>) => {
    setRules((current) => current.map((rule) => rule.classification === classification
      ? { ...rule, ...patch }
      : rule))
  }
  const changeChatMode = (classification: Classification, chatMode: ClassificationChatMode) => {
    changeRule(classification, { chat_mode: chatMode, provider_profile_version_id: '' })
  }
  const eligibleProfiles = (rule: RuleDraft) => profiles.filter((profile) => (
    profile.state === 'APPROVED'
    && requiredJurisdiction.trim() !== ''
    && profile.jurisdiction === requiredJurisdiction.trim()
    && classificationRank[profile.maximum_classification] >= classificationRank[rule.classification]
    && (rule.chat_mode !== 'INTERNAL_APPROVED_ONLY' || profile.kind === 'INTERNAL')
    && (rule.classification !== 'CONFIDENTIAL' || profile.kind === 'INTERNAL')
    && attestationsAreCurrent(profile)
  ))

  const propose = (event: FormEvent) => {
    event.preventDefault()
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
        setPolicies((current) => [next, ...current]); setSelectedId(next.policy_id)
      },
    })
  }

  const selected = policies.find((policy) => policy.policy_id === selectedId)
  const decide = (decision: 'APPROVED' | 'REJECTED') => {
    if (!selected || !decisionReason.trim()) return
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
        clearKey(intent); setDecisionReason(''); await load()
      },
    })
  }
  const canCheck = Boolean(
    selected?.state === 'PROPOSED' && context && context.subject_id !== selected.requester_id,
  )

  return <>
    {currentPolicy
      ? <section className="panel">
        <p className="eyebrow">{messages.currentPolicy}</p>
        <PolicySummary policy={currentPolicy} />
      </section>
      : <p className="callout">{messages.activePolicyRequired}</p>}
    <div className="admin-two-column">
      <form className="panel form-stack" onSubmit={propose}>
        <h3>{messages.classificationPolicyProposal}</h3>
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
        <fieldset className="action-matrix">
          <legend>{messages.classificationMatrix}</legend>
          {rules.map((rule) => {
            const candidates = eligibleProfiles(rule)
            return <section key={rule.classification} className="panel form-stack" aria-label={rule.classification}>
              <strong>{rule.classification}</strong>
              <label>{messages.searchMode}
                <select
                  aria-label={`${rule.classification} ${messages.searchMode}`}
                  value={rule.search_mode}
                  onChange={(event) => changeRule(rule.classification, { search_mode: event.target.value as ClassificationSearchMode })}
                >
                  {rule.classification === 'RESTRICTED'
                    ? <><option value="DENY">DENY</option><option value="EXPLICIT_GRANT_ONLY">EXPLICIT_GRANT_ONLY</option></>
                    : <><option value="DENY">DENY</option><option value="ABAC">ABAC</option></>}
                </select>
              </label>
              <label>{messages.chatMode}
                {rule.classification === 'RESTRICTED'
                  ? <><input aria-label={`RESTRICTED ${messages.chatMode}`} value="DENY" readOnly /><small>RESTRICTED Chat is always denied.</small></>
                  : <select
                    aria-label={`${rule.classification} ${messages.chatMode}`}
                    value={rule.chat_mode}
                    onChange={(event) => changeChatMode(rule.classification, event.target.value as ClassificationChatMode)}
                  >
                    <option value="DENY">DENY</option>
                    <option value="INTERNAL_APPROVED_ONLY">INTERNAL_APPROVED_ONLY</option>
                    {rule.classification !== 'CONFIDENTIAL' && <option value="APPROVED_PROVIDER_ONLY">APPROVED_PROVIDER_ONLY</option>}
                  </select>}
              </label>
              {rule.chat_mode !== 'DENY' && <label>{messages.providerProfile}
                <select
                  aria-label={`${rule.classification} ${messages.providerProfile}`}
                  value={rule.provider_profile_version_id}
                  onChange={(event) => changeRule(rule.classification, { provider_profile_version_id: event.target.value })}
                  required
                >
                  <option value="">{messages.chooseProvider}</option>
                  {candidates.map((profile) => <option key={profile.provider_profile_version_id} value={profile.provider_profile_version_id}>
                    {profile.profile_key} v{profile.profile_version} · {profile.kind} · {profile.region} · {profile.jurisdiction}
                  </option>)}
                </select>
                {candidates.length === 0 && <small>{messages.noEligibleProvider}</small>}
              </label>}
            </section>
          })}
        </fieldset>
        <label>{messages.reason}<textarea value={proposalReason} onChange={(event) => setProposalReason(event.target.value)} maxLength={4000} required /></label>
        <button className="button">{messages.propose}</button>
      </form>
      <section className="panel">
        <div className="section-heading"><h3>{messages.classificationPolicyHistory}</h3><button className="button button-secondary" onClick={() => void load()}>{messages.refresh}</button></div>
        <div className="compact-list">{policies.map((policy) => <button key={policy.policy_id} className={selectedId === policy.policy_id ? 'selected' : ''} onClick={() => setSelectedId(policy.policy_id)}>
          <span><strong>#{policy.policy_number} · {policy.required_jurisdiction}</strong><small>{policy.request_reason}</small></span><span className="badge">{policy.state}</span>
        </button>)}</div>
      </section>
    </div>
    {selected && <section className="result-card governance-detail form-stack">
      <PolicySummary policy={selected} />
      {selected.state === 'PROPOSED' && <>
        <label>{messages.reason}<textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} maxLength={4000} /></label>
        <div className="action-row">{canCheck
          ? <><button className="button" disabled={!decisionReason.trim()} onClick={() => decide('APPROVED')}>{messages.approve}</button><button className="button button-secondary" disabled={!decisionReason.trim()} onClick={() => decide('REJECTED')}>{messages.reject}</button></>
          : <p className="callout">{messages.makerCannotCheck}</p>}
        </div>
      </>}
    </section>}
  </>
}

export function InferenceProviderProfileAdmin(props: Props) {
  const { api, context, messages, requestConfirmation, keyFor, clearKey, reportError } = props
  const [profiles, setProfiles] = useState<InferenceProviderProfile[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [decisionReason, setDecisionReason] = useState('')
  const [revocationReason, setRevocationReason] = useState('')

  const load = useCallback(async () => {
    try {
      const next = await api.listInferenceProviderProfiles()
      setProfiles(next)
      setSelectedId((current) => current || next[0]?.provider_profile_version_id || '')
    } catch (error) { reportError(error) }
  }, [api, reportError])
  useEffect(() => { void load() }, [load])

  const selected = profiles.find((profile) => profile.provider_profile_version_id === selectedId)
  const replace = (next: InferenceProviderProfile) => setProfiles((current) => current.map((profile) => (
    profile.provider_profile_version_id === next.provider_profile_version_id ? next : profile
  )))
  const decide = (decision: 'APPROVED' | 'REJECTED') => {
    if (!selected || !decisionReason.trim()) return
    const intent = `provider-profile-decision:${selected.provider_profile_version_id}:${selected.version}:${decision}:${decisionReason}`
    requestConfirmation({
      title: `${messages.providerDecision}: ${decision}`,
      summary: [selected.profile_key, `v${selected.profile_version}`, selected.payload_hash, `aggregate v${selected.version}`],
      execute: async () => {
        const next = await api.decideInferenceProviderProfile(
          selected, decision, decisionReason.trim(), keyFor(intent, 'provider-profile-decision'),
        )
        clearKey(intent); setDecisionReason(''); replace(next)
      },
    })
  }
  const revoke = () => {
    if (!selected || !revocationReason.trim()) return
    const intent = `provider-profile-revoke:${selected.provider_profile_version_id}:${selected.version}:${revocationReason}`
    requestConfirmation({
      title: messages.revoke,
      summary: [selected.profile_key, `v${selected.profile_version}`, selected.payload_hash, revocationReason.trim()],
      execute: async () => {
        const next = await api.revokeInferenceProviderProfile(
          selected, revocationReason.trim(), keyFor(intent, 'provider-profile-revoke'),
        )
        clearKey(intent); setRevocationReason(''); replace(next)
      },
    })
  }
  const canCheck = Boolean(selected?.state === 'PROPOSED' && context && context.subject_id !== selected.maker_id)

  return <>
    <p className="callout">{messages.providerReadOnly}</p>
    <div className="admin-two-column">
      <section className="panel">
        <div className="section-heading"><h3>{messages.providerHistory}</h3><button className="button button-secondary" onClick={() => void load()}>{messages.refresh}</button></div>
        <div className="compact-list">{profiles.map((profile) => <button key={profile.provider_profile_version_id} className={selectedId === profile.provider_profile_version_id ? 'selected' : ''} onClick={() => setSelectedId(profile.provider_profile_version_id)}>
          <span><strong>{profile.profile_key} · v{profile.profile_version}</strong><small>{profile.kind} · {profile.region} · {profile.jurisdiction}</small></span><span className="badge">{profile.state}</span>
        </button>)}</div>
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
            : <p className="callout">{messages.makerCannotCheck}</p>}
          </div>
        </>}
        {selected.state === 'APPROVED' && <>
          <label>{messages.revocationReason}<textarea value={revocationReason} onChange={(event) => setRevocationReason(event.target.value)} maxLength={4000} /></label>
          <button className="button button-secondary" disabled={!revocationReason.trim()} onClick={revoke}>{messages.revoke}</button>
        </>}
      </> : <p className="muted">{messages.empty}</p>}</section>
    </div>
  </>
}

export function RestrictedSearchGrantAdmin(props: Props) {
  const { api, context, messages, requestConfirmation, keyFor, clearKey, reportError } = props
  const [grants, setGrants] = useState<RestrictedSearchGrant[]>([])
  const [members, setMembers] = useState<WorkspaceMembershipSummary[]>([])
  const [currentPolicy, setCurrentPolicy] = useState<ClassificationAccessPolicy | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [subjectId, setSubjectId] = useState('')
  const [scope, setScope] = useState<RestrictedSearchScope | ''>('')
  const [scopeId, setScopeId] = useState('')
  const [purpose, setPurpose] = useState('')
  const [validFrom, setValidFrom] = useState('')
  const [expiresAt, setExpiresAt] = useState('')
  const [proposalReason, setProposalReason] = useState('')
  const [decisionReason, setDecisionReason] = useState('')
  const [revocationReason, setRevocationReason] = useState('')
  const timeZone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, [])

  const load = useCallback(async () => {
    try {
      const [nextGrants, nextMembers, nextPolicy] = await Promise.all([
        api.listRestrictedSearchGrants(),
        api.listMemberships(),
        api.getCurrentClassificationAccessPolicy(),
      ])
      setGrants(nextGrants); setMembers(nextMembers); setCurrentPolicy(nextPolicy)
      setSelectedId((current) => current || nextGrants[0]?.grant_id || '')
    } catch (error) { reportError(error) }
  }, [api, reportError])
  useEffect(() => { void load() }, [load])

  const restrictedRule = currentPolicy?.rules.find((rule) => rule.classification === 'RESTRICTED')
  const grantEnabled = currentPolicy?.state === 'ACTIVE'
    && restrictedRule?.search_mode === 'EXPLICIT_GRANT_ONLY'
  const propose = (event: FormEvent) => {
    event.preventDefault()
    if (!currentPolicy || !grantEnabled || !subjectId || !scope || !scopeId.trim()
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
        clearKey(intent); setSubjectId(''); setScope(''); setScopeId(''); setPurpose('')
        setValidFrom(''); setExpiresAt(''); setProposalReason('')
        setGrants((current) => [next, ...current]); setSelectedId(next.grant_id)
      },
    })
  }

  const selected = grants.find((grant) => grant.grant_id === selectedId)
  const replace = (next: RestrictedSearchGrant) => setGrants((current) => current.map((grant) => (
    grant.grant_id === next.grant_id ? next : grant
  )))
  const decide = (decision: 'APPROVED' | 'REJECTED') => {
    if (!selected || !decisionReason.trim()) return
    const intent = `restricted-search-grant-decision:${selected.grant_id}:${selected.version}:${decision}:${decisionReason}`
    requestConfirmation({
      title: `${messages.restrictedGrantProposal}: ${decision}`,
      summary: [selected.subject_id, `${selected.scope}: ${selected.scope_id}`, selected.payload_hash, `v${selected.version}`],
      execute: async () => {
        const next = await api.decideRestrictedSearchGrant(
          selected, decision, decisionReason.trim(), keyFor(intent, 'restricted-search-grant-decision'),
        )
        clearKey(intent); setDecisionReason(''); replace(next)
      },
    })
  }
  const revoke = () => {
    if (!selected || !revocationReason.trim()) return
    const intent = `restricted-search-grant-revoke:${selected.grant_id}:${selected.version}:${revocationReason}`
    requestConfirmation({
      title: messages.revoke,
      summary: [selected.subject_id, `${selected.scope}: ${selected.scope_id}`, selected.payload_hash, revocationReason.trim()],
      execute: async () => {
        const next = await api.revokeRestrictedSearchGrant(
          selected, revocationReason.trim(), keyFor(intent, 'restricted-search-grant-revoke'),
        )
        clearKey(intent); setRevocationReason(''); replace(next)
      },
    })
  }
  const canCheck = Boolean(
    selected?.state === 'PENDING' && context
    && context.subject_id !== selected.requester_id
    && context.subject_id !== selected.subject_id,
  )

  return <>
    {!currentPolicy && <p className="callout">{messages.activePolicyRequired}</p>}
    {currentPolicy && !grantEnabled && <p className="callout">{messages.restrictedGrantDisabled}</p>}
    <div className="admin-two-column">
      <form className="panel form-stack" onSubmit={propose}>
        <h3>{messages.restrictedGrantProposal}</h3>
        {currentPolicy && <p className="callout">{messages.grantMaximumHint}: {currentPolicy.restricted_search_grant_maximum_days} days · #{currentPolicy.policy_number}</p>}
        <label>{messages.subject}<select value={subjectId} onChange={(event) => setSubjectId(event.target.value)} required disabled={!grantEnabled}>
          <option value="">{messages.select}</option>
          {members.filter((member) => member.subject_active && member.membership_active).map((member) => <option key={member.subject_id} value={member.subject_id}>{member.display_name} · {member.subject_id}</option>)}
        </select></label>
        <label>{messages.scope}<select value={scope} onChange={(event) => setScope(event.target.value as RestrictedSearchScope | '')} required disabled={!grantEnabled}>
          <option value="">{messages.select}</option><option value="RESOURCE">RESOURCE</option><option value="SYSTEM">SYSTEM</option><option value="DOMAIN">DOMAIN</option>
        </select></label>
        <label>{messages.scopeId}<input value={scopeId} onChange={(event) => setScopeId(event.target.value)} required pattern="[0-9a-fA-F-]{36}" disabled={!grantEnabled} /></label>
        <label>{messages.purpose}<textarea value={purpose} onChange={(event) => setPurpose(event.target.value)} maxLength={4000} required disabled={!grantEnabled} /></label>
        <label>{messages.validFrom}<input type="datetime-local" value={validFrom} onChange={(event) => setValidFrom(event.target.value)} required disabled={!grantEnabled} /></label>
        <label>{messages.expiresAt}<input type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} required disabled={!grantEnabled} /></label>
        <small>{messages.browserTimezone}: {timeZone}</small>
        <label>{messages.reason}<textarea value={proposalReason} onChange={(event) => setProposalReason(event.target.value)} maxLength={4000} required disabled={!grantEnabled} /></label>
        <button className="button" disabled={!grantEnabled}>{messages.propose}</button>
      </form>
      <section className="panel">
        <div className="section-heading"><h3>{messages.restrictedGrantHistory}</h3><button className="button button-secondary" onClick={() => void load()}>{messages.refresh}</button></div>
        <div className="compact-list">{grants.map((grant) => <button key={grant.grant_id} className={selectedId === grant.grant_id ? 'selected' : ''} onClick={() => setSelectedId(grant.grant_id)}>
          <span><strong>{grant.subject_id}</strong><small>{grant.scope}: {grant.scope_id} · {formatDate(grant.expires_at)}</small></span><span className="badge">{grant.state}</span>
        </button>)}</div>
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
          : <p className="callout">{messages.makerCannotCheck}</p>}
        </div>
      </>}
      {selected.state === 'ACTIVE' && <>
        <label>{messages.revocationReason}<textarea value={revocationReason} onChange={(event) => setRevocationReason(event.target.value)} maxLength={4000} /></label>
        <button className="button button-secondary" disabled={!revocationReason.trim()} onClick={revoke}>{messages.revoke}</button>
      </>}
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
      {rule.provider_profile_version_id && <code>{rule.provider_profile_version_id}</code>}
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
  return `${rule.classification}: Search=${rule.search_mode}, Chat=${rule.chat_mode}, Provider=${rule.provider_profile_version_id ?? 'none'}`
}

function formatDate(value: string): string {
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString() : value
}
