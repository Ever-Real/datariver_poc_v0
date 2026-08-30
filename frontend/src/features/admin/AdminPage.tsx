import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CircleAlert, CircleCheck, CircleDashed, CircleX, PauseCircle } from 'lucide-react'
import { ApiError, newIdempotencyKey, type ApiClient } from '../../api/client'
import type { AdminReadContext, QualityCapability, QualityCapabilityAxis } from '../../api/types'
import { AssuranceNotice, type AssuranceActions } from '../../components/AssuranceNotice'
import { ErrorNotice } from '../../components/ErrorNotice'
import { GovernedUnavailable } from '../../components/common/GovernedUnavailable'
import { useRovingTabs } from '../../components/common/useRovingTabs'
import { PageTitle } from '../../components/layout/PageTitle'
import { AdminApi } from './adminApi'
import { AccountAccessAdmin } from './AccountAccessAdmin'
import { AdminMutationConfirmDialog, type PendingAdminMutation } from './AdminMutationConfirmDialog'
import { AuditLogsAdmin } from './AdminReadOnlySurfaces'
import { RetentionGovernanceAdmin } from './RetentionGovernanceAdmin'
import { SystemConfigurationAdmin } from './SystemConfigurationAdmin'
import { PocFeaturePermissionAdmin } from './PocFeaturePermissionAdmin'
import { SiteManagementAdmin } from './SiteManagementAdmin'
import { getAdminMessages } from './messages'
import { adminSectionFromLocation, allowedAdminSections, type AdminSection } from './adminSections'

export function AdminPage({
  client,
  initialContext,
  workspace,
  suspended = false,
  hardwareWebauthnEnabled = true,
  openAccess = false,
  ...assurance
}: {
  client: ApiClient
  initialContext?: AdminReadContext
  workspace: string
  suspended?: boolean
  hardwareWebauthnEnabled?: boolean
  openAccess?: boolean
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
    if (!context || hardwareWebauthnEnabled || openAccess) {
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
  }, [context, hardwareWebauthnEnabled, openAccess])
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
  const [mutationError, setMutationError] = useState<unknown>()
  const requestConfirmation = (pending: PendingAdminMutation) => {
    setMutationError(undefined)
    setMutation({ ...pending, contextEpoch })
  }
  const confirmMutation = async () => {
    if (!mutation || busy) return
    if (mutation.contextEpoch !== contextEpoch) {
      setMutation(undefined)
      setError(new Error('관리자 인증 또는 권한 컨텍스트가 변경되었습니다. 작업을 다시 검토하세요.'))
      return
    }
    setBusy(true); setError(undefined); setMutationError(undefined)
    try {
      await mutation.execute()
      setMutation(undefined)
    } catch (next) {
      setMutationError(next)
    } finally {
      setBusy(false)
    }
  }
  const shared = {
    api, context, messages, requestConfirmation, keyFor, clearKey, reportError,
    hardwareWebauthnEnabled: openAccess || hardwareWebauthnEnabled,
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
      description={openAccess
        ? '현재 POC는 서버 세션의 Role·capability와 System scope를 적용하며, provider 준비 상태는 별도 capability로 표시합니다.'
        : '서버가 허용한 관리 기능만 노출하며 고위험 변경은 보안키 인증과 독립 승인을 요구합니다.'}
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
    {!openAccess && <AssuranceNotice error={error} requiredAssurance={assuranceType} hardwareWebauthnEnabled={hardwareWebauthnEnabled} {...assurance} />}
    <ErrorNotice error={error} />
    {activeSection && <div {...primaryTabs.panelProps(activeSection)}>
      {activeSection === 'memberships' && <AccountAccessAdmin {...shared} />}
      {activeSection === 'siteManagement' && <SiteManagementAdmin {...shared} />}
      {activeSection === 'featurePermissions' && <PocFeaturePermissionAdmin {...shared} />}
      {activeSection === 'systemSettings' && <SystemConfigurationAdmin {...shared} />}
      {activeSection === 'systemSettings' && <QualityCapabilityConnection client={client} />}
      {activeSection === 'retention' && <RetentionGovernanceAdmin {...shared} />}
      {activeSection === 'auditLogs' && <AuditLogsAdmin />}
    </div>}
    <GovernedUnavailable
      compact
      title="Audit/Log·용어 승인 관리 API 미구현"
      description="실시간 DataHub 연결 용어 조회는 POC USER의 용어사전에서 제공합니다. Audit 내보내기와 용어 생성·승인 정본 관리는 별도 계약이 추가되기 전까지 비활성화합니다."
    />
    <AdminMutationConfirmDialog mutation={mutation} busy={busy} error={mutationError} messages={messages} onCancel={() => setMutation(undefined)} onConfirm={() => void confirmMutation()} />
  </section>
}

type QualityConnectionDisplayState = 'AVAILABLE' | 'DISABLED' | 'CHECKING' | 'FAILED' | 'NOT_CONFIGURED' | 'DEFERRED'

function QualityCapabilityConnection({ client }: { client: ApiClient }) {
  const [capability, setCapability] = useState<QualityCapability>()
  const [state, setState] = useState<QualityConnectionDisplayState>('CHECKING')
  const [detail, setDetail] = useState('Quality/GX capability를 확인하고 있습니다.')

  useEffect(() => {
    const controller = new AbortController()
    setState('CHECKING')
    setDetail('Quality/GX capability를 확인하고 있습니다.')
    void client.request<QualityCapability>('/quality/capability', { signal: controller.signal }).then(
      (next) => {
        if (controller.signal.aborted) return
        setCapability(next)
        const read = qualityAxis(next, 'read_access')
        if (read?.state === 'AVAILABLE') {
          setState('AVAILABLE')
          setDetail('Quality/GX 읽기 capability를 사용할 수 있습니다.')
          return
        }
        if (read?.reason_code === 'DATAHUB_NOT_CONFIGURED') {
          setState('NOT_CONFIGURED')
          setDetail('DataHub 기반 Quality/GX 읽기 source가 구성되지 않았습니다.')
          return
        }
        setState('DISABLED')
        setDetail(read?.reason_code ? `현재 capability: ${read.reason_code}` : '현재 사용자에게 Quality/GX 읽기 capability가 없습니다.')
      },
      (error: unknown) => {
        if (controller.signal.aborted) return
        if (error instanceof ApiError && [401, 403].includes(error.problem.status)) {
          setState('DISABLED')
          setDetail('현재 사용자에게 Quality/GX capability를 조회할 권한이 없습니다.')
          return
        }
        setState('FAILED')
        setDetail('Quality/GX capability를 확인하지 못했습니다. 연결 설정을 변경하지 않고 다시 시도할 수 있습니다.')
      },
    )
    return () => controller.abort()
  }, [client])

  const execution = qualityAxis(capability, 'manual_execution')
  const executionDeferred = state === 'AVAILABLE' && execution?.state !== 'AVAILABLE'
  return (
    <section className="panel admin-quality-capability" aria-label="Great Expectations 연결 상태">
      <header className="section-heading">
        <div>
          <h3>Great Expectations</h3>
          <p className="muted">Quality/GX 읽기 capability와 실행 제어 상태를 구분해 표시합니다.</p>
        </div>
        <QualityConnectionBadge state={state} />
      </header>
      <p className="m-0 text-sm text-slate-700">{detail}</p>
      {executionDeferred && (
        <p className="callout m-0" role="status">
          <PauseCircle size={16} aria-hidden="true" />
          <strong>실행 제어: 확인 보류</strong> · 현재 연결은 품질 정보를 읽을 수 있지만 실행 기능은 제공하지 않습니다.
        </p>
      )}
    </section>
  )
}

function qualityAxis(capability: QualityCapability | undefined, id: QualityCapabilityAxis['id']) {
  return capability?.axes.find((axis) => axis.id === id)
}

function QualityConnectionBadge({ state }: { state: QualityConnectionDisplayState }) {
  const presentation: Record<QualityConnectionDisplayState, { label: string; icon: typeof CircleCheck; className: string }> = {
    AVAILABLE: { label: '사용 가능', icon: CircleCheck, className: 'badge-connected' },
    DISABLED: { label: '사용 안 함', icon: PauseCircle, className: 'badge-soft' },
    CHECKING: { label: '확인 중', icon: CircleDashed, className: 'badge-connecting' },
    FAILED: { label: '연결 실패', icon: CircleX, className: 'badge-error' },
    NOT_CONFIGURED: { label: '설정 필요', icon: CircleAlert, className: 'badge-warning' },
    DEFERRED: { label: '확인 보류', icon: PauseCircle, className: 'badge-soft' },
  }
  const value = presentation[state]
  const Icon = value.icon
  return <span className={`badge connection-status-badge ${value.className}`} role="status"><Icon size={14} aria-hidden="true" />{value.label}</span>
}
