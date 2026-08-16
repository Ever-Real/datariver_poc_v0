import { lazy, Suspense, useCallback, useEffect, useState, type FormEvent } from 'react'
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
import { knowledgeStudioUrl } from './features/knowledge/routes/knowledgeLocation'

const AdminPage = lazy(() => import('./features/admin/AdminPage').then((module) => ({ default: module.AdminPage })))
const CatalogPage = lazy(() => import('./features/catalog/CatalogPage').then((module) => ({ default: module.CatalogPage })))
const ChatPage = lazy(() => import('./features/chat/ChatPage').then((module) => ({ default: module.ChatPage })))
const DashboardPage = lazy(() => import('./features/dashboard/DashboardPage').then((module) => ({ default: module.DashboardPage })))
const GovernancePage = lazy(() => import('./features/governance/GovernancePage').then((module) => ({ default: module.GovernancePage })))
const PocGlossaryPage = lazy(() => import('./features/admin/PocGlossaryPage').then((module) => ({ default: module.PocGlossaryPage })))
const KnowledgeWorkspacePage = lazy(() => import('./features/knowledge/KnowledgeWorkspacePage').then((module) => ({ default: module.KnowledgeWorkspacePage })))
const MonitoringPage = lazy(() => import('./features/monitoring/MonitoringPage').then((module) => ({ default: module.MonitoringPage })))
const PolicyGovernancePage = lazy(() => import('./features/policy/PolicyGovernancePage').then((module) => ({ default: module.PolicyGovernancePage })))
const ProfilePage = lazy(() => import('./features/profile/ProfilePage').then((module) => ({ default: module.ProfilePage })))
const QualityPage = lazy(() => import('./features/quality/QualityPage').then((module) => ({ default: module.QualityPage })))
const RegistrationPage = lazy(() => import('./features/registration/RegistrationPage').then((module) => ({ default: module.RegistrationPage })))
const SharingPage = lazy(() => import('./features/sharing/SharingPage').then((module) => ({ default: module.SharingPage })))

interface LocalCredentialAuth {
  isLocalSession: true
  signInWithCredentials: (username: string, password: string) => Promise<void>
}

function localCredentialAuth(value: object): LocalCredentialAuth | undefined {
  const candidate = value as Partial<LocalCredentialAuth>
  return candidate.isLocalSession === true
    && typeof candidate.signInWithCredentials === 'function'
    ? candidate as LocalCredentialAuth
    : undefined
}

export function App() {
  const auth = useAuth()
  const localAuth = localCredentialAuth(auth)
  const runtimeConfig = publicRuntimeConfig()
  const pocMode = runtimeConfig.apiBaseUrl === 'poc-memory-only'
  const oidcAuthenticationEnabled = !pocMode
  const authenticationEnabled = oidcAuthenticationEnabled || Boolean(localAuth)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [page, setPage] = useState<Page>(pageFromLocation)
  const [locationRevision, setLocationRevision] = useState(0)
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
  const workspaceSelectionEnabled = auth.profile?.workspace_selection_enabled === true
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
      setLocationRevision((current) => current + 1)
    }
    window.addEventListener('popstate', restore)
    return () => window.removeEventListener('popstate', restore)
  }, [])

  useEffect(() => {
    if (!authenticatedSubject) return
    const routePage = pageFromLocation()
    setPage((current) => current === routePage ? current : routePage)
    setCatalogQuery(new URL(window.location.href).searchParams.get('q') ?? '')
    setLocationRevision((current) => current + 1)
  }, [authenticatedSubject])

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
    if (!activeWorkspace || !authenticatedSubject) return
    const currentAdminDecision = (
      adminAccess.workspace === activeWorkspace
      && adminAccess.subject === authenticatedSubject
      && adminAccess.securityEpoch === auth.securityEpoch
      && adminAccess.authorizationRevision === auth.authorizationRevision
    )
    if (page !== 'admin' || !currentAdminDecision || adminAccess.status !== 'denied') return

    const url = new URL(window.location.href)
    url.searchParams.set('page', 'dashboard')
    url.searchParams.delete('adminSection')
    url.searchParams.delete('adminView')
    url.searchParams.delete('adminDetail')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
    setPage('dashboard')
  }, [
    activeWorkspace,
    adminAccess,
    auth.authorizationRevision,
    auth.securityEpoch,
    authenticatedSubject,
    page,
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

  const navigate = useCallback((next: Page) => {
    window.history.pushState({}, '', pageUrl(next))
    setCatalogQuery('')
    setPage(next)
  }, [])

  const navigateKnowledgeStudio = useCallback((assetId?: string) => {
    window.history.pushState({}, '', knowledgeStudioUrl({ assetId }))
    setCatalogQuery('')
    setPage('knowledge-studio')
  }, [])

  const navigateAdmin = useCallback((adminSection: string) => {
    if (adminSection === 'poc-registration') return navigate('registration')
    if (adminSection === 'poc-quality') return navigate('quality')
    if (adminSection === 'poc-knowledge') return navigate('knowledge')
    if (adminSection === 'poc-glossary') return navigate('glossary')
    const url = new URL(window.location.href)
    url.searchParams.set('page', 'admin')
    url.searchParams.set('adminSection', adminSection)
    url.searchParams.delete('q')
    window.history.pushState({}, '', `${url.pathname}${url.search}${url.hash}`)
    setCatalogQuery('')
    setPage('admin')
  }, [navigate])

  const searchCatalog = useCallback((query: string) => {
    window.history.pushState({}, '', pageUrl('catalog', { query }))
    setCatalogQuery(query)
    setPage('catalog')
  }, [])

  const submitLocalLogin = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!localAuth || !username.trim() || !password) return
    const submittedPassword = password
    setPassword('')
    void localAuth.signInWithCredentials(username.trim(), submittedPassword)
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
        {localAuth ? (
          <form className="legacy-login-form" onSubmit={submitLocalLogin}>
            <label htmlFor="local-username">아이디</label>
            <input
              id="local-username"
              name="username"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
            />
            <label htmlFor="local-password">비밀번호</label>
            <input
              id="local-password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
            <button className="legacy-login-submit" type="submit" disabled={!username.trim() || !password}>
              Sign In <ArrowRight size={18} aria-hidden="true" />
            </button>
          </form>
        ) : (
          <button className="legacy-login-submit" onClick={() => void auth.signIn()}>Sign In <ArrowRight size={18} aria-hidden="true" /></button>
        )}
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
  const cachedAdminContext = (
    cachedAdminAccessMatches && adminAccess.context?.allowed_operations.length
  ) ? adminAccess.context : undefined
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
  const adminMenuItems: Array<{ id: string; label: string }> = pocMode
    ? [
        { id: 'poc-registration', label: '등록관리' },
        { id: 'poc-quality', label: '품질관리' },
        { id: 'poc-knowledge', label: '지식관리' },
        { id: 'poc-glossary', label: '용어사전' },
        ...(currentAdminContext ? [{ id: 'memberships', label: '관리자메뉴' }] : []),
      ]
    : currentAdminContext
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
      pocMode={pocMode}
      client={client}
      workspace={activeWorkspace}
      securityEpoch={auth.securityEpoch}
      workspaceSelectionEnabled={workspaceSelectionEnabled}
      hardwareWebauthnEnabled={oidcAuthenticationEnabled && auth.profile?.hardware_webauthn_enabled === true}
      deploymentTier={deploymentTier}
      displayName={auth.profile?.display_name ?? auth.user.profile.name ?? auth.user.profile.sub}
      email={auth.profile?.email}
      adminMenuItems={adminMenuItems}
      adminContextStatus={currentAdminStatus}
      externalSystemLinks={externalSystemLinks}
      notice={auth.notice}
      onNavigate={navigate}
      onNavigateAdmin={navigateAdmin}
      onProfile={oidcAuthenticationEnabled ? () => navigate('profile') : undefined}
      onSearch={searchCatalog}
      onWorkspaceChange={saveWorkspace}
      onPasswordReauth={oidcAuthenticationEnabled ? () => void auth.beginPasswordReauth() : undefined}
      onEnrollSecurityKey={oidcAuthenticationEnabled ? () => void auth.beginWebAuthnEnrollment() : undefined}
      onSignOut={authenticationEnabled ? () => void auth.signOut() : undefined}
      onClearNotice={auth.clearNotice}
    >
      <Suspense fallback={<main className="centered"><div className="loader" /><p>화면을 불러오고 있습니다.</p></main>}>
        {page === 'dashboard' && <DashboardPage
          client={client}
          workspaceId={activeWorkspace}
          subjectId={authenticatedSubject}
          securityEpoch={auth.securityEpoch}
          authorizationRevision={auth.authorizationRevision}
          onNavigate={navigate}
        />}
        {page === 'catalog' && <CatalogPage
          client={client}
          initialQuery={catalogQuery}
          onQueryChange={searchCatalog}
          catalogExportWorkerEnabled={catalogExportWorkerEnabled}
          workspaceId={activeWorkspace}
          subjectId={authenticatedSubject}
          securityEpoch={auth.securityEpoch}
          authorizationRevision={auth.authorizationRevision}
        />}
        {page === 'registration' && <RegistrationPage client={client} />}
        {page === 'glossary' && <PocGlossaryPage client={client} />}
        {page === 'change-management' && <GovernancePage client={client} requesterName={auth.profile?.display_name ?? auth.user.profile.name ?? auth.user.profile.sub} requesterEmail={auth.profile?.email} onNavigate={navigate} onStepUp={auth.beginStepUp} onPasswordReauth={auth.beginPasswordReauth} onEnroll={auth.beginWebAuthnEnrollment} hardwareWebauthnEnabled={oidcAuthenticationEnabled && auth.profile?.hardware_webauthn_enabled === true} />}
        {page === 'quality' && <QualityPage
          client={client}
          workspaceId={activeWorkspace}
          subjectId={authenticatedSubject}
          securityEpoch={auth.securityEpoch}
          authorizationRevision={auth.authorizationRevision}
        />}
        {(page === 'knowledge'
          || page === 'knowledge-chat'
          || page === 'knowledge-instances'
          || page === 'knowledge-profiles'
          || page === 'knowledge-studio') && (
          <KnowledgeWorkspacePage
            page={page}
            client={client}
            workspaceId={activeWorkspace}
            subjectId={authenticatedSubject}
            locationRevision={locationRevision}
            onNavigate={navigate}
            onOpenStudio={navigateKnowledgeStudio}
            onStepUp={oidcAuthenticationEnabled ? auth.beginStepUp : undefined}
            onPasswordReauth={oidcAuthenticationEnabled ? auth.beginPasswordReauth : undefined}
            onEnroll={oidcAuthenticationEnabled ? auth.beginWebAuthnEnrollment : undefined}
            hardwareWebauthnEnabled={oidcAuthenticationEnabled && auth.profile?.hardware_webauthn_enabled === true}
          />
        )}
        {page === 'monitoring' && (
          <MonitoringPage
            client={client}
            canManageTabs={
              currentAdminContext?.allowed_operations.includes(
                'MONITORING_CONFIGURATION_READ',
              ) ?? false
            }
            canUpdateTabs={
              currentAdminContext?.allowed_operations.includes(
                'MONITORING_CONFIGURATION_UPDATE',
              ) ?? false
            }
            onRequestAdminAssurance={oidcAuthenticationEnabled
              ? auth.profile?.hardware_webauthn_enabled === false
                ? auth.beginPasswordReauth
                : auth.beginStepUp
              : undefined
            }
          />
        )}
        {page === 'governance' && <PolicyGovernancePage client={client} mayReadPolicies={mayReadPolicyGovernance} allowedOperations={currentAdminContext?.allowed_operations} assurance={oidcAuthenticationEnabled ? { onStepUp: auth.beginStepUp, onPasswordReauth: auth.beginPasswordReauth, onEnroll: auth.beginWebAuthnEnrollment, hardwareWebauthnEnabled: auth.profile?.hardware_webauthn_enabled === true } : undefined} />}
        {page === 'sharing' && <SharingPage client={client} onStepUp={auth.beginStepUp} onPasswordReauth={auth.beginPasswordReauth} onEnroll={auth.beginWebAuthnEnrollment} hardwareWebauthnEnabled={oidcAuthenticationEnabled && auth.profile?.hardware_webauthn_enabled === true} />}
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
            openAccess={pocMode}
            hardwareWebauthnEnabled={auth.profile?.hardware_webauthn_enabled !== false}
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
