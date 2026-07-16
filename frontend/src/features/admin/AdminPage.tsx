import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type { AdminOperation, AdminReadContext } from '../../api/types'
import { AssuranceNotice, type AssuranceActions } from '../../components/AssuranceNotice'
import { ErrorNotice } from '../../components/ErrorNotice'
import { PageTitle } from '../../components/layout/PageTitle'
import { AdminApi } from './adminApi'
import { AdminMutationConfirmDialog, type PendingAdminMutation } from './AdminMutationConfirmDialog'
import {
  ClassificationPolicyAdmin,
  InferenceProviderProfileAdmin,
  RestrictedSearchGrantAdmin,
} from './ClassificationAccessAdmin'
import { ErasureAdmin } from './ErasureAdmin'
import { FallbackQueueAdmin, MembershipAccessAdmin } from './MembershipAdmin'
import { LegalHoldAdmin, RetentionPolicyAdmin } from './RetentionAdmin'
import { getAdminMessages } from './messages'

const sections = [
  'memberships', 'fallback', 'classification', 'providers', 'restrictedGrants',
  'retention', 'holds', 'erasure',
] as const
export type AdminSection = typeof sections[number]

const sectionOperations: Record<AdminSection, readonly AdminOperation[]> = {
  memberships: ['MEMBERSHIP_ACCESS_READ', 'MEMBERSHIP_ACCESS_UPDATE'],
  fallback: ['FALLBACK_REQUEST_READ', 'FALLBACK_REQUEST_CREATE', 'FALLBACK_REQUEST_DECIDE', 'FALLBACK_REQUEST_CONSUME'],
  classification: ['CLASSIFICATION_POLICY_READ', 'CLASSIFICATION_POLICY_PROPOSE', 'CLASSIFICATION_POLICY_DECIDE'],
  providers: ['INFERENCE_PROVIDER_PROFILE_READ', 'INFERENCE_PROVIDER_PROFILE_DECIDE', 'INFERENCE_PROVIDER_PROFILE_REVOKE'],
  restrictedGrants: ['RESTRICTED_SEARCH_GRANT_READ', 'RESTRICTED_SEARCH_GRANT_PROPOSE', 'RESTRICTED_SEARCH_GRANT_DECIDE', 'RESTRICTED_SEARCH_GRANT_REVOKE'],
  retention: ['RETENTION_POLICY_READ', 'RETENTION_POLICY_MANAGE'],
  holds: ['LEGAL_HOLD_READ', 'LEGAL_HOLD_PLACE', 'LEGAL_HOLD_RELEASE'],
  erasure: ['ERASURE_READ', 'ERASURE_REQUEST', 'ERASURE_APPROVE'],
}

export function allowedAdminSections(context: AdminReadContext): AdminSection[] {
  const allowed = new Set(context.allowed_operations)
  return sections.filter((section) => {
    const readOperation = sectionOperations[section][0]
    return readOperation ? allowed.has(readOperation) : false
  })
}

function sectionFromLocation(): AdminSection {
  const value = new URL(window.location.href).searchParams.get('adminSection')
  return sections.includes(value as AdminSection) ? value as AdminSection : 'memberships'
}

export function AdminPage({
  client,
  initialContext,
  ...assurance
}: { client: ApiClient; initialContext?: AdminReadContext } & AssuranceActions) {
  const api = useMemo(() => new AdminApi(client), [client])
  const messages = useMemo(() => getAdminMessages(), [])
  const [section, setSection] = useState<AdminSection>(sectionFromLocation)
  const [context, setContext] = useState<AdminReadContext | undefined>(initialContext)
  const [error, setError] = useState<unknown>()
  const [mutation, setMutation] = useState<PendingAdminMutation>()
  const [busy, setBusy] = useState(false)
  const keys = useRef(new Map<string, string>())

  const reportError = useCallback((next: unknown) => setError(next), [])
  const loadContext = useCallback(async () => {
    try { setContext(await api.getContext()) } catch (next) { reportError(next) }
  }, [api, reportError])
  useEffect(() => { if (!initialContext) void loadContext() }, [initialContext, loadContext])
  useEffect(() => { if (initialContext) setContext(initialContext) }, [initialContext])
  useEffect(() => {
    const restore = () => setSection(sectionFromLocation())
    window.addEventListener('popstate', restore)
    return () => window.removeEventListener('popstate', restore)
  }, [])

  const navigate = (next: AdminSection) => {
    const url = new URL(window.location.href)
    url.searchParams.set('page', 'admin')
    url.searchParams.set('adminSection', next)
    window.history.pushState({}, '', `${url.pathname}${url.search}${url.hash}`)
    setSection(next); setError(undefined)
  }
  const visibleSections = useMemo(() => context ? allowedAdminSections(context) : [], [context])
  const activeSection = visibleSections.includes(section) ? section : visibleSections[0]
  useEffect(() => {
    if (!activeSection || activeSection === section) return
    const url = new URL(window.location.href)
    url.searchParams.set('page', 'admin')
    url.searchParams.set('adminSection', activeSection)
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
    setSection(activeSection)
  }, [activeSection, section])
  const keyFor = (intent: string, prefix: string) => {
    const existing = keys.current.get(intent)
    if (existing) return existing
    const created = newIdempotencyKey(prefix)
    keys.current.set(intent, created)
    return created
  }
  const clearKey = (intent: string) => keys.current.delete(intent)
  const confirmMutation = async () => {
    if (!mutation || busy) return
    setBusy(true); setError(undefined)
    try { await mutation.execute() } catch (next) { setError(next) } finally {
      setBusy(false); setMutation(undefined)
    }
  }
  const shared = {
    api, context, messages, requestConfirmation: setMutation, keyFor, clearKey, reportError,
    ...assurance,
  }
  const assuranceType = activeSection === 'fallback' ? 'PASSWORD' as const : 'HARDWARE' as const

  return <section>
    <PageTitle
      icon="AD"
      eyebrow={messages.eyebrow}
      title={messages.title}
      description="서버가 허용한 관리 기능만 노출하며 고위험 변경은 보안키 인증과 독립 승인을 요구합니다."
      actions={<button className="button button-secondary" onClick={() => void loadContext()}>{messages.refresh}</button>}
    />
    <nav className="admin-tabs" aria-label={messages.title}>{visibleSections.map((id) => <button key={id} className={activeSection === id ? 'active' : ''} aria-current={activeSection === id ? 'page' : undefined} onClick={() => navigate(id)}>{messages[id]}</button>)}</nav>
    {context && <section className="panel admin-context" aria-label={messages.adminContext}>
      <div><strong>{context.display_name}</strong><code>{context.subject_id}</code></div>
      <div><small>{messages.currentAssurance}</small><span className="badge">{context.authentication_assurance}</span></div>
      <div><small>{messages.fallbackState}</small><span className={`badge ${context.fallback_enabled ? '' : 'badge-soft'}`}>{context.fallback_enabled ? messages.enabled : messages.disabled}</span></div>
    </section>}
    <AssuranceNotice error={error} requiredAssurance={assuranceType} {...assurance} />
    <ErrorNotice error={error} />
    {activeSection === 'memberships' && <MembershipAccessAdmin {...shared} />}
    {activeSection === 'fallback' && <FallbackQueueAdmin {...shared} />}
    {activeSection === 'classification' && <ClassificationPolicyAdmin {...shared} />}
    {activeSection === 'providers' && <InferenceProviderProfileAdmin {...shared} />}
    {activeSection === 'restrictedGrants' && <RestrictedSearchGrantAdmin {...shared} />}
    {activeSection === 'retention' && <RetentionPolicyAdmin {...shared} />}
    {activeSection === 'holds' && <LegalHoldAdmin {...shared} />}
    {activeSection === 'erasure' && <ErasureAdmin {...shared} />}
    <AdminMutationConfirmDialog mutation={mutation} busy={busy} messages={messages} onCancel={() => setMutation(undefined)} onConfirm={() => void confirmMutation()} />
  </section>
}
