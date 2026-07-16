import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type { AdminReadContext } from '../../api/types'
import { AssuranceNotice, type AssuranceActions } from '../../components/AssuranceNotice'
import { ErrorNotice } from '../../components/ErrorNotice'
import { AdminApi } from './adminApi'
import { AdminMutationConfirmDialog, type PendingAdminMutation } from './AdminMutationConfirmDialog'
import { ErasureAdmin } from './ErasureAdmin'
import { FallbackQueueAdmin, MembershipAccessAdmin } from './MembershipAdmin'
import { LegalHoldAdmin, RetentionPolicyAdmin } from './RetentionAdmin'
import { getAdminMessages } from './messages'

const sections = ['memberships', 'fallback', 'retention', 'holds', 'erasure'] as const
type AdminSection = typeof sections[number]

function sectionFromLocation(): AdminSection {
  const value = new URL(window.location.href).searchParams.get('adminSection')
  return sections.includes(value as AdminSection) ? value as AdminSection : 'memberships'
}

export function AdminPage({ client, ...assurance }: { client: ApiClient } & AssuranceActions) {
  const api = useMemo(() => new AdminApi(client), [client])
  const messages = useMemo(() => getAdminMessages(), [])
  const [section, setSection] = useState<AdminSection>(sectionFromLocation)
  const [context, setContext] = useState<AdminReadContext>()
  const [error, setError] = useState<unknown>()
  const [mutation, setMutation] = useState<PendingAdminMutation>()
  const [busy, setBusy] = useState(false)
  const keys = useRef(new Map<string, string>())

  const reportError = useCallback((next: unknown) => setError(next), [])
  const loadContext = useCallback(async () => {
    try { setContext(await api.getContext()) } catch (next) { reportError(next) }
  }, [api, reportError])
  useEffect(() => { void loadContext() }, [loadContext])
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
  const assuranceType = section === 'fallback' ? 'PASSWORD' as const : 'HARDWARE' as const

  return <section>
    <div className="page-heading"><div><p className="eyebrow">{messages.eyebrow}</p><h2>{messages.title}</h2></div><button className="button button-secondary" onClick={() => void loadContext()}>{messages.refresh}</button></div>
    <nav className="admin-tabs" aria-label={messages.title}>{sections.map((id) => <button key={id} className={section === id ? 'active' : ''} aria-current={section === id ? 'page' : undefined} onClick={() => navigate(id)}>{messages[id]}</button>)}</nav>
    {context && <section className="panel admin-context" aria-label={messages.adminContext}>
      <div><strong>{context.display_name}</strong><code>{context.subject_id}</code></div>
      <div><small>{messages.currentAssurance}</small><span className="badge">{context.authentication_assurance}</span></div>
      <div><small>{messages.fallbackState}</small><span className={`badge ${context.fallback_enabled ? '' : 'badge-soft'}`}>{context.fallback_enabled ? messages.enabled : messages.disabled}</span></div>
    </section>}
    <AssuranceNotice error={error} requiredAssurance={assuranceType} {...assurance} />
    <ErrorNotice error={error} />
    {section === 'memberships' && <MembershipAccessAdmin {...shared} />}
    {section === 'fallback' && <FallbackQueueAdmin {...shared} />}
    {section === 'retention' && <RetentionPolicyAdmin {...shared} />}
    {section === 'holds' && <LegalHoldAdmin {...shared} />}
    {section === 'erasure' && <ErasureAdmin {...shared} />}
    <AdminMutationConfirmDialog mutation={mutation} busy={busy} messages={messages} onCancel={() => setMutation(undefined)} onConfirm={() => void confirmMutation()} />
  </section>
}
