import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { newIdempotencyKey, type ApiClient } from '../../api/client'
import type { AdminReadContext } from '../../api/types'
import { AssuranceNotice, type AssuranceActions } from '../../components/AssuranceNotice'
import { ErrorNotice } from '../../components/ErrorNotice'
import { GovernedUnavailable } from '../../components/common/GovernedUnavailable'
import { useRovingTabs } from '../../components/common/useRovingTabs'
import { PageTitle } from '../../components/layout/PageTitle'
import { AdminApi } from './adminApi'
import { AccountAccessAdmin } from './AccountAccessAdmin'
import { AdminMutationConfirmDialog, type PendingAdminMutation } from './AdminMutationConfirmDialog'
import { RetentionGovernanceAdmin } from './RetentionGovernanceAdmin'
import { SystemConfigurationAdmin } from './SystemConfigurationAdmin'
import { getAdminMessages } from './messages'
import { adminSectionFromLocation, allowedAdminSections, type AdminSection } from './adminSections'

export function AdminPage({
  client,
  initialContext,
  workspace,
  suspended = false,
  hardwareWebauthnEnabled = true,
  ...assurance
}: {
  client: ApiClient
  initialContext?: AdminReadContext
  workspace: string
  suspended?: boolean
  hardwareWebauthnEnabled?: boolean
} & AssuranceActions) {
  const api = useMemo(() => new AdminApi(client), [client])
  const messages = useMemo(() => getAdminMessages(), [])
  const [section, setSection] = useState<AdminSection>(adminSectionFromLocation)
  const [context, setContext] = useState<AdminReadContext | undefined>(initialContext)
  const [error, setError] = useState<unknown>()
  const [mutation, setMutation] = useState<PendingAdminMutation>()
  const [busy, setBusy] = useState(false)
  const [showWebauthnDisabledWarning, setShowWebauthnDisabledWarning] = useState(false)
  const contextRequest = useRef<{ generation: number; controller?: AbortController }>({
    generation: 0,
  })
  const contextEpoch = context
    ? [
        context.workspace_id,
        context.subject_id,
        context.authentication_assurance,
        String(context.fallback_enabled),
        [...context.allowed_operations].sort().join(','),
        [...context.action_vocabulary].sort().join(','),
      ].join('|')
    : ''
  const keys = useRef({ epoch: contextEpoch, values: new Map<string, string>() })

  const reportError = useCallback((next: unknown) => setError(next), [])
  const loadContext = useCallback(async () => {
    contextRequest.current.controller?.abort()
    const controller = new AbortController()
    const generation = contextRequest.current.generation + 1
    contextRequest.current = { generation, controller }
    setContext(undefined)
    setMutation(undefined)
    setError(undefined)
    try {
      const next = await api.getContext(controller.signal)
      if (next.workspace_id !== workspace) {
        throw new Error('관리자 컨텍스트의 Workspace가 현재 선택과 일치하지 않습니다.')
      }
      if (!controller.signal.aborted && contextRequest.current.generation === generation) {
        setContext(next)
      }
    } catch (next) {
      if (!controller.signal.aborted && contextRequest.current.generation === generation) {
        setContext(undefined)
        reportError(next)
      }
    }
  }, [api, reportError, workspace])
  useEffect(() => { if (!initialContext) void loadContext() }, [initialContext, loadContext])
  useEffect(() => {
    if (!initialContext) return
    contextRequest.current.controller?.abort()
    contextRequest.current = { generation: contextRequest.current.generation + 1 }
    setContext(initialContext)
  }, [initialContext])
  useEffect(() => () => contextRequest.current.controller?.abort(), [])
  useEffect(() => {
    keys.current = { epoch: contextEpoch, values: new Map() }
    setMutation(undefined)
  }, [contextEpoch])
  useEffect(() => {
    if (!context || hardwareWebauthnEnabled) {
      setShowWebauthnDisabledWarning(false)
      return
    }
    const key = `webAuthnWarningShown_${context.subject_id}`
    try {
      if (window.localStorage.getItem(key)) {
        setShowWebauthnDisabledWarning(false)
        return
      }
      window.localStorage.setItem(key, 'true')
      setShowWebauthnDisabledWarning(true)
    } catch {
      // Storage can be unavailable in hardened browser contexts. Keep this
      // session-only fallback without broadening who receives the notice.
      setShowWebauthnDisabledWarning(true)
    }
  }, [context, hardwareWebauthnEnabled])
  useEffect(() => {
    if (!showWebauthnDisabledWarning) return
    const timeoutId = window.setTimeout(() => setShowWebauthnDisabledWarning(false), 3_000)
    return () => window.clearTimeout(timeoutId)
  }, [showWebauthnDisabledWarning])
  useEffect(() => {
    const restore = () => setSection(adminSectionFromLocation())
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
  const primaryTabs = useRovingTabs({
    ids: visibleSections,
    activeId: activeSection,
    idPrefix: 'admin',
    onSelect: navigate,
  })
  useEffect(() => {
    if (!activeSection || activeSection === section) return
    const url = new URL(window.location.href)
    url.searchParams.set('page', 'admin')
    url.searchParams.set('adminSection', activeSection)
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
    setSection(activeSection)
  }, [activeSection, section])
  const keyFor = (intent: string, prefix: string) => {
    if (keys.current.epoch !== contextEpoch) {
      keys.current = { epoch: contextEpoch, values: new Map() }
    }
    const existing = keys.current.values.get(intent)
    if (existing) return existing
    const created = newIdempotencyKey(prefix)
    if (keys.current.values.size >= 100) {
      const oldest = keys.current.values.keys().next().value
      if (oldest) keys.current.values.delete(oldest)
    }
    keys.current.values.set(intent, created)
    return created
  }
  const clearKey = (intent: string) => keys.current.values.delete(intent)
  const requestConfirmation = (pending: PendingAdminMutation) => {
    setMutation({ ...pending, contextEpoch })
  }
  const confirmMutation = async () => {
    if (!mutation || busy) return
    if (mutation.contextEpoch !== contextEpoch) {
      setMutation(undefined)
      setError(new Error('관리자 인증 또는 권한 컨텍스트가 변경되었습니다. 작업을 다시 검토하세요.'))
      return
    }
    setBusy(true); setError(undefined)
    try { await mutation.execute() } catch (next) { setError(next) } finally {
      setBusy(false); setMutation(undefined)
    }
  }
  const shared = {
    api, context, messages, requestConfirmation, keyFor, clearKey, reportError,
    hardwareWebauthnEnabled,
    ...assurance,
  }
  const locationParameters = new URL(window.location.href).searchParams
  const assuranceType = (
    locationParameters.get('adminView') === 'recovery'
    || locationParameters.get('adminSection') === 'fallback'
  ) ? 'PASSWORD' as const : 'HARDWARE' as const

  return <section className="admin-page" hidden={suspended} aria-busy={suspended}>
    <PageTitle
      icon="AD"
      eyebrow={messages.eyebrow}
      title={messages.title}
      description="서버가 허용한 관리 기능만 노출하며 고위험 변경은 보안키 인증과 독립 승인을 요구합니다."
      actions={<button className="button button-secondary" onClick={() => void loadContext()}>{messages.refresh}</button>}
    />
    <div className="admin-tabs" role="tablist" aria-label={messages.title}>{visibleSections.map((id) => <button key={id} {...primaryTabs.tabProps(id)} type="button" className={activeSection === id ? 'active' : ''} onClick={() => navigate(id)}>{messages[id]}</button>)}</div>
    {context && <section className="panel admin-context" aria-label={messages.adminContext}>
      <div><strong>{context.display_name}</strong></div>
      <div><small>{messages.currentAssurance}</small><span className="badge">{context.authentication_assurance}</span></div>
      <div><small>{messages.fallbackState}</small><span className={`badge ${context.fallback_enabled ? '' : 'badge-soft'}`}>{context.fallback_enabled ? messages.enabled : messages.disabled}</span></div>
    </section>}
    {showWebauthnDisabledWarning && <div className="notice notice-error" role="alert">
      <strong>WebAuthn 보안키 인증이 필요합니다.</strong>
      <span>이 배포에서는 WebAuthn이 비활성화되어 있습니다. 개발 환경의 관리자 작업은 서버가 허용한 비밀번호 보증 예외가 있는 경우에만 실행할 수 있습니다.</span>
      <div className="action-row"><button type="button" className="button button-secondary" onClick={() => setShowWebauthnDisabledWarning(false)}>확인</button></div>
    </div>}
    <AssuranceNotice error={error} requiredAssurance={assuranceType} hardwareWebauthnEnabled={hardwareWebauthnEnabled} {...assurance} />
    <ErrorNotice error={error} />
    {activeSection && <div {...primaryTabs.panelProps(activeSection)}>
      {activeSection === 'memberships' && <AccountAccessAdmin {...shared} />}
      {activeSection === 'systemSettings' && <SystemConfigurationAdmin {...shared} />}
      {activeSection === 'retention' && <RetentionGovernanceAdmin {...shared} />}
    </div>}
    <GovernedUnavailable
      compact
      title="Audit/Log·전사 용어사전 관리자 API 미구현"
      description="레거시 관리자 URL은 실제 로그나 용어 데이터를 조회하지 않습니다. 민감 필드 마스킹·전용 읽기 권한·서버 페이지·감사 가능한 내보내기와 용어 정본 승인 계약이 추가되기 전까지 기능을 명시적으로 비활성화합니다."
    />
    <AdminMutationConfirmDialog mutation={mutation} busy={busy} messages={messages} onCancel={() => setMutation(undefined)} onConfirm={() => void confirmMutation()} />
  </section>
}
