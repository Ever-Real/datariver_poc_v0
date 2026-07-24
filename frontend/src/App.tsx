import { lazy, Suspense, useEffect, useState } from 'react'
import { ArrowRight, ShieldCheck } from 'lucide-react'
import { remediationKind } from './api/client'
import type { AdminOperation, AdminReadContext, CapabilitiesResponse, ExternalSystemLink } from './api/types'
import { useStableApiClient } from './api/useStableApiClient'
import { pageFromLocation, pageUrl, type Page } from './app/navigation'
import { defaultWorkspaceSelection, workspaceFromLocation } from './app/workspace'
import { useAuth } from './auth/AuthProvider'
import { AppShell } from './components/layout/AppShell'
import { PageTitle } from './components/layout/PageTitle'
import { publicRuntimeConfig } from './runtimeConfig'
import { allowedAdminSections } from './features/admin/adminSections'
import { getAdminMessages } from './features/admin/messages'
import { catalogExportCapabilityEnabled } from './features/catalog/catalogExportApi'

const AdminPage = lazy(() => import('./features/admin/AdminPage').then((module) => ({ default: module.AdminPage })))
const CatalogPage = lazy(() => import('./features/catalog/CatalogPage').then((module) => ({ default: module.CatalogPage })))
const ChatPage = lazy(() => import('./features/chat/ChatPage').then((module) => ({ default: module.ChatPage })))
const DashboardPage = lazy(() => import('./features/dashboard/DashboardPage').then((module) => ({ default: module.DashboardPage })))
const GovernancePage = lazy(() => import('./features/governance/GovernancePage').then((module) => ({ default: module.GovernancePage })))
const KnowledgePage = lazy(() => import('./features/knowledge/KnowledgePage').then((module) => ({ default: module.KnowledgePage })))
const KnowledgeChatPage = lazy(() => import('./features/knowledge/KnowledgeChatPage').then((module) => ({ default: module.KnowledgeChatPage })))
const MonitoringPage = lazy(() => import('./features/monitoring/MonitoringPage').then((module) => ({ default: module.MonitoringPage })))
const PolicyGovernancePage = lazy(() => import('./features/policy/PolicyGovernancePage').then((module) => ({ default: module.PolicyGovernancePage })))
const ProfilePage = lazy(() => import('./features/profile/ProfilePage').then((module) => ({ default: module.ProfilePage })))
const QualityPage = lazy(() => import('./features/quality/QualityPage').then((module) => ({ default: module.QualityPage })))
const RegistrationPage = lazy(() => import('./features/registration/RegistrationPage').then((module) => ({ default: module.RegistrationPage })))
const SharingPage = lazy(() => import('./features/sharing/SharingPage').then((module) => ({ default: module.SharingPage })))

export function App() {
  const auth = useAuth()
  const runtimeConfig = publicRuntimeConfig()
  const [page, setPage] = useState<Page>(pageFromLocation)
  const [catalogQuery, setCatalogQuery] = useState(() => new URL(window.location.href).searchParams.get('q') ?? '')
  // The URL keeps the selected tenant across reloads without trusting it for
  // authorization; every request still binds it to server-side membership/RLS.
  const [workspace, setWorkspace] = useState(workspaceFromLocation)
  const [externalSystemLinks, setExternalSystemLinks] = useState<ExternalSystemLink[]>([])
  const [capabilities, setCapabilities] = useState<CapabilitiesResponse['items']>([])
  const [deploymentTier, setDeploymentTier] = useState<CapabilitiesResponse['deployment_tier']>('SINGLE_NODE_PILOT')
  const [catalogExportWorkerEnabled, setCatalogExportWorkerEnabled] = useState(false)
  const [adminAccess, setAdminAccess] = useState<{
    workspace: string
    subject: string
    securityEpoch: number
    authorizationRevision: number
    status: 'checking' | 'allowed' | 'denied' | 'reauth_required'
    context?: AdminReadContext
  }>({
    workspace: '',
    subject: '',
    securityEpoch: 0,
    authorizationRevision: 0,
    status: 'checking',
  })
  const workspaceSelectionEnabled = auth.profile?.workspace_selection_enabled !== false
  const activeWorkspace = workspaceSelectionEnabled
    ? workspace
    : auth.profile?.default_workspace_id ?? ''
  const authenticatedSubject = auth.profile?.subject ?? ''
  const client = useStableApiClient(
    runtimeConfig.apiBaseUrl,
    auth.user?.access_token,
    activeWorkspace,
    auth.renewAccessToken,
    auth.readSecurityEpoch,
  )

  useEffect(() => {
    const restore = () => {
      setPage(pageFromLocation())
      setCatalogQuery(new URL(window.location.href).searchParams.get('q') ?? '')
      setWorkspace(workspaceFromLocation())
    }
    window.addEventListener('popstate', restore)
    return () => window.removeEventListener('popstate', restore)
  }, [])

  useEffect(() => {
    // The URL selection is only a convenience value; it never grants a
    // workspace.  When there is no such value, hydrate the verified server
    // default into React state immediately after the OIDC profile arrives.
    const defaultWorkspace = workspaceSelectionEnabled
      ? defaultWorkspaceSelection(workspace, auth.profile?.default_workspace_id)
      : auth.profile?.default_workspace_id ?? ''
    if (defaultWorkspace === workspace) return
    const url = new URL(window.location.href)
    if (defaultWorkspace) url.searchParams.set('workspace', defaultWorkspace)
    else url.searchParams.delete('workspace')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
    setWorkspace(defaultWorkspace)
  }, [auth.profile?.default_workspace_id, workspace, workspaceSelectionEnabled])

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const accessKey = {
      workspace: activeWorkspace,
      subject: authenticatedSubject,
      securityEpoch: auth.securityEpoch,
      authorizationRevision: auth.authorizationRevision,
    }
    if (!activeWorkspace || !authenticatedSubject) {
      setAdminAccess({
        ...accessKey, status: 'denied',
      })
      return () => {
        active = false
        controller.abort()
      }
    }
    setAdminAccess((current) => ({
      ...accessKey,
      status: 'checking',
      context: (
        current.workspace === activeWorkspace
        && current.subject === authenticatedSubject
        && current.securityEpoch === auth.securityEpoch
      ) ? current.context : undefined,
    }))
    void client.request<AdminReadContext>('/admin/me', {
      cache: 'no-store',
      signal: controller.signal,
    })
      .then((context) => {
        if (!active) return
        if (context.workspace_id !== activeWorkspace) {
          setAdminAccess({ ...accessKey, status: 'denied' })
          return
        }
        setAdminAccess({
          ...accessKey,
          status: context.allowed_operations.length > 0 ? 'allowed' : 'denied',
          context,
        })
      })
      .catch((error: unknown) => {
        if (!active) return
        setAdminAccess({
          ...accessKey,
          status: remediationKind(error) === 'REAUTH_REQUIRED' ? 'reauth_required' : 'denied',
        })
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [
    activeWorkspace,
    auth.authorizationRevision,
    auth.securityEpoch,
    authenticatedSubject,
    client,
  ])

  useEffect(() => {
    let active = true
    setExternalSystemLinks([])
    setCapabilities([])
    setDeploymentTier('SINGLE_NODE_PILOT')
    if (!activeWorkspace) {
      return () => { active = false }
    }
    void client.request<CapabilitiesResponse>('/capabilities')
      .then((response) => {
        if (!active) return
        setExternalSystemLinks(response.external_system_links)
        setCapabilities(response.items)
        setDeploymentTier(response.deployment_tier)
      })
      .catch(() => {
        if (!active) return
        setExternalSystemLinks([])
        setCapabilities([])
        setDeploymentTier('SINGLE_NODE_PILOT')
    })
    return () => { active = false }
  }, [
    activeWorkspace,
    auth.securityEpoch,
    authenticatedSubject,
    client,
  ])

  useEffect(() => {
    let active = true
    setCatalogExportWorkerEnabled(false)
    if (!activeWorkspace) return () => { active = false }
    void catalogExportCapabilityEnabled(client)
      .then((enabled) => { if (active) setCatalogExportWorkerEnabled(enabled) })
    return () => { active = false }
  }, [
    activeWorkspace,
    auth.securityEpoch,
    authenticatedSubject,
    client,
  ])

  const navigate = (next: Page) => {
    window.history.pushState({}, '', pageUrl(next))
    setCatalogQuery('')
    setPage(next)
  }

  const navigateAdmin = (adminSection: string) => {
    const url = new URL(window.location.href)
    url.searchParams.set('page', 'admin')
    url.searchParams.set('adminSection', adminSection)
    url.searchParams.delete('q')
    window.history.pushState({}, '', `${url.pathname}${url.search}${url.hash}`)
    setCatalogQuery('')
    setPage('admin')
  }

  const searchCatalog = (query: string) => {
    window.history.pushState({}, '', pageUrl('catalog', { query }))
    setCatalogQuery(query)
    setPage('catalog')
  }

  if (auth.loading) return <main className="centered"><div className="loader" /><p>인증 상태를 확인하고 있습니다.</p></main>
  if (!auth.user) return (
    <main className="legacy-login-shell">
      <section className="legacy-login-card" aria-labelledby="login-title">
        <header>
          <div className="legacy-login-mark"><ShieldCheck size={32} aria-hidden="true" /></div>
          <h1 id="login-title">DataRiver</h1>
          <p>Integrated Data Catalog Platform</p>
        </header>
        {auth.notice && <div className={`notice ${auth.notice.kind === 'ERROR' ? 'notice-error' : ''}`} role="alert"><span>{auth.notice.message}</span></div>}
        <p className="legacy-login-guidance">조직 계정으로 안전하게 로그인합니다. 인증 정보는 DataRiver 브라우저 코드에 저장되지 않습니다.</p>
        <button className="legacy-login-submit" onClick={() => void auth.signIn()}>Sign In <ArrowRight size={18} aria-hidden="true" /></button>
        <footer>DATARIVER · SECURE ENVIRONMENT</footer>
      </section>
    </main>
  )

  if (auth.profile?.workspace_selection_enabled === false && !auth.profile.default_workspace_id) {
    return (
      <main className="centered">
        <h1>기본 Workspace가 필요합니다.</h1>
        <p>단일 Workspace 모드에서는 서버가 검증한 기본 Workspace가 지정되어야 합니다. 운영 관리자에게 멤버십 기본값을 요청하세요.</p>
        <button className="button" type="button" onClick={() => void auth.signOut()}>나가기</button>
      </main>
    )
  }

  const saveWorkspace = (value: string) => {
    if (!workspaceSelectionEnabled) return
    const normalized = value.trim()
    const url = new URL(window.location.href)
    if (normalized) url.searchParams.set('workspace', normalized)
    else url.searchParams.delete('workspace')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
    setWorkspace(normalized)
  }

  const cachedAdminAccessMatches = (
    adminAccess.workspace === activeWorkspace
    && adminAccess.subject === authenticatedSubject
    && adminAccess.securityEpoch === auth.securityEpoch
  )
  const currentAdminAccessMatches = (
    cachedAdminAccessMatches
    && adminAccess.authorizationRevision === auth.authorizationRevision
  )
  const cachedAdminContext = cachedAdminAccessMatches ? adminAccess.context : undefined
  const currentAdminContext = currentAdminAccessMatches && adminAccess.status === 'allowed'
    ? adminAccess.context
    : undefined
  const currentAdminStatus = currentAdminAccessMatches ? adminAccess.status : 'checking'
  const policyReadOperations: AdminOperation[] = [
    'CLASSIFICATION_POLICY_READ', 'RETENTION_POLICY_READ', 'LEGAL_HOLD_READ',
  ]
  const mayReadPolicyGovernance = Boolean(currentAdminContext && policyReadOperations
    .every((operation) => currentAdminContext.allowed_operations.includes(operation)))
  const adminMessages = getAdminMessages()
  const adminMenuItems = currentAdminContext
    ? allowedAdminSections(currentAdminContext).map((id) => ({ id, label: adminMessages[id] }))
    : []
  const adminContextKey = cachedAdminContext
    ? [
        cachedAdminContext.workspace_id,
        cachedAdminContext.subject_id,
        cachedAdminContext.authentication_assurance,
        String(cachedAdminContext.fallback_enabled),
        [...cachedAdminContext.allowed_operations].sort().join(','),
        [...cachedAdminContext.action_vocabulary].sort().join(','),
      ].join('|')
    : ''

  return (
    <AppShell
      page={page}
      client={client}
      workspace={activeWorkspace}
      securityEpoch={auth.securityEpoch}
      workspaceSelectionEnabled={workspaceSelectionEnabled}
      hardwareWebauthnEnabled={auth.profile?.hardware_webauthn_enabled !== false}
      deploymentTier={deploymentTier}
      displayName={auth.profile?.display_name ?? auth.user.profile.name ?? auth.user.profile.sub}
      email={auth.profile?.email}
      adminMenuItems={adminMenuItems}
      adminContextStatus={currentAdminStatus}
      externalSystemLinks={externalSystemLinks}
      notice={auth.notice}
      onNavigate={navigate}
      onNavigateAdmin={navigateAdmin}
      onProfile={() => navigate('profile')}
      onSearch={searchCatalog}
      onWorkspaceChange={saveWorkspace}
      onPasswordReauth={() => void auth.beginPasswordReauth()}
      onEnrollSecurityKey={() => void auth.beginWebAuthnEnrollment()}
      onSignOut={() => void auth.signOut()}
      onClearNotice={auth.clearNotice}
    >
      <Suspense fallback={<main className="centered"><div className="loader" /><p>화면을 불러오고 있습니다.</p></main>}>
        {page === 'dashboard' && <DashboardPage client={client} onNavigate={navigate} />}
        {page === 'catalog' && <CatalogPage client={client} initialQuery={catalogQuery} onQueryChange={searchCatalog} catalogExportWorkerEnabled={catalogExportWorkerEnabled} />}
        {page === 'registration' && <RegistrationPage client={client} />}
        {page === 'change-management' && <GovernancePage client={client} requesterName={auth.profile?.display_name ?? auth.user.profile.name ?? auth.user.profile.sub} requesterEmail={auth.profile?.email} onNavigate={navigate} onStepUp={auth.beginStepUp} onPasswordReauth={auth.beginPasswordReauth} onEnroll={auth.beginWebAuthnEnrollment} />}
        {page === 'quality' && <QualityPage />}
        {page === 'knowledge' && <KnowledgePage client={client} onNavigate={navigate} />}
        {page === 'knowledge-chat' && <KnowledgeChatPage client={client} onNavigate={navigate} />}
        {page === 'monitoring' && <MonitoringPage client={client} />}
        {page === 'governance' && <PolicyGovernancePage client={client} mayReadPolicies={mayReadPolicyGovernance} allowedOperations={currentAdminContext?.allowed_operations} />}
        {page === 'sharing' && <SharingPage client={client} onStepUp={auth.beginStepUp} onPasswordReauth={auth.beginPasswordReauth} onEnroll={auth.beginWebAuthnEnrollment} />}
        {page === 'chat' && <ChatPage client={client} />}
        {page === 'profile' && auth.profile && <ProfilePage client={client} profile={auth.profile} workspace={activeWorkspace} capabilities={capabilities} externalSystemLinks={externalSystemLinks} onPasswordChange={() => void auth.beginPasswordChange()} onPasswordReauth={() => void auth.beginPasswordReauth()} />}
        {page === 'profile' && !auth.profile && <PageTitle icon="ME" eyebrow="Verified identity profile" title="내 프로필" description="서버에서 검증된 프로필을 불러오지 못했습니다." />}
        {page === 'admin' && cachedAdminContext && (
          <AdminPage
            key={adminContextKey}
            client={client}
            initialContext={cachedAdminContext}
            workspace={activeWorkspace}
            suspended={!currentAdminContext}
            onStepUp={auth.beginStepUp}
            onPasswordReauth={auth.beginPasswordReauth}
            onEnroll={auth.beginWebAuthnEnrollment}
          />
        )}
        {page === 'admin' && !currentAdminContext && (
          <PageTitle
            icon="AD"
            eyebrow="Governed administration"
            title="관리자 권한 확인"
            description={currentAdminStatus === 'checking'
              ? '서버에서 현재 Workspace의 관리 권한을 확인하고 있습니다.'
              : currentAdminStatus === 'reauth_required'
                ? '로컬 관리자 멤버십은 확인되었지만, 민감한 관리 컨텍스트를 표시하려면 최근 비밀번호 재인증이 필요합니다. 재인증 후 작업은 자동으로 실행되지 않습니다.'
                : '현재 사용자에게 노출 가능한 관리자 기능이 없습니다.'}
            actions={currentAdminStatus === 'reauth_required'
              ? <button className="button" type="button" onClick={() => void auth.beginPasswordReauth()}>관리자 재인증</button>
              : undefined}
          />
        )}
      </Suspense>
    </AppShell>
  )
}
