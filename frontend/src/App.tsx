import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, ShieldCheck } from 'lucide-react'
import { ApiClient, remediationKind } from './api/client'
import type { AdminOperation, AdminReadContext, CapabilitiesResponse, ExternalSystemLink } from './api/types'
import { pageFromLocation, pageUrl, type Page } from './app/navigation'
import { defaultWorkspaceSelection, workspaceFromLocation } from './app/workspace'
import { useAuth } from './auth/AuthProvider'
import { AppShell } from './components/layout/AppShell'
import { PageTitle } from './components/layout/PageTitle'
import { AdminPage } from './features/admin/AdminPage'
import { allowedAdminSections } from './features/admin/adminSections'
import { getAdminMessages } from './features/admin/messages'
import { CatalogPage } from './features/catalog/CatalogPage'
import { catalogExportCapabilityEnabled } from './features/catalog/catalogExportApi'
import { ChatPage } from './features/chat/ChatPage'
import { DashboardPage } from './features/dashboard/DashboardPage'
import { GovernancePage } from './features/governance/GovernancePage'
import { KnowledgePage } from './features/knowledge/KnowledgePage'
import { MonitoringPage } from './features/monitoring/MonitoringPage'
import { PolicyGovernancePage } from './features/policy/PolicyGovernancePage'
import { QualityPage } from './features/quality/QualityPage'
import { RegistrationPage } from './features/registration/RegistrationPage'
import { SharingPage } from './features/sharing/SharingPage'

export function App() {
  const auth = useAuth()
  const [page, setPage] = useState<Page>(pageFromLocation)
  const [catalogQuery, setCatalogQuery] = useState(() => new URL(window.location.href).searchParams.get('q') ?? '')
  // The URL keeps the selected tenant across reloads without trusting it for
  // authorization; every request still binds it to server-side membership/RLS.
  const [workspace, setWorkspace] = useState(workspaceFromLocation)
  const [externalSystemLinks, setExternalSystemLinks] = useState<ExternalSystemLink[]>([])
  const [deploymentTier, setDeploymentTier] = useState<CapabilitiesResponse['deployment_tier']>('SINGLE_NODE_PILOT')
  const [catalogExportWorkerEnabled, setCatalogExportWorkerEnabled] = useState(false)
  const [adminAccess, setAdminAccess] = useState<{
    workspace: string
    status: 'checking' | 'allowed' | 'denied' | 'reauth_required'
    context?: AdminReadContext
  }>({ workspace: '', status: 'checking' })
  const client = useMemo(() => new ApiClient(
    String(import.meta.env.VITE_API_BASE_URL || '/api/v1'),
    () => auth.user?.access_token,
    () => workspace,
    auth.renewAccessToken,
  ), [auth.renewAccessToken, auth.user?.access_token, workspace])

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
    const defaultWorkspace = defaultWorkspaceSelection(
      workspace,
      auth.profile?.default_workspace_id,
    )
    if (!defaultWorkspace || defaultWorkspace === workspace) return
    const url = new URL(window.location.href)
    url.searchParams.set('workspace', defaultWorkspace)
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
    setWorkspace(defaultWorkspace)
  }, [auth.profile?.default_workspace_id, workspace])

  useEffect(() => {
    let active = true
    if (!workspace) {
      setAdminAccess({ workspace, status: 'denied' })
      return () => { active = false }
    }
    setAdminAccess({ workspace, status: 'checking' })
    void client.request<AdminReadContext>('/admin/me')
      .then((context) => {
        if (active) setAdminAccess({
          workspace,
          status: context.allowed_operations.length > 0 ? 'allowed' : 'denied',
          context,
        })
      })
      .catch((error: unknown) => {
        if (!active) return
        setAdminAccess({
          workspace,
          status: remediationKind(error) === 'REAUTH_REQUIRED' ? 'reauth_required' : 'denied',
        })
      })
    return () => { active = false }
  }, [client, workspace])

  useEffect(() => {
    let active = true
    if (!workspace) {
      setExternalSystemLinks([])
      setDeploymentTier('SINGLE_NODE_PILOT')
      return () => { active = false }
    }
    void client.request<CapabilitiesResponse>('/capabilities')
      .then((response) => {
        if (!active) return
        setExternalSystemLinks(response.external_system_links)
        setDeploymentTier(response.deployment_tier)
      })
      .catch(() => {
        if (!active) return
        setExternalSystemLinks([])
        setDeploymentTier('SINGLE_NODE_PILOT')
      })
    return () => { active = false }
  }, [client, workspace])

  useEffect(() => {
    let active = true
    setCatalogExportWorkerEnabled(false)
    if (!workspace) return () => { active = false }
    void catalogExportCapabilityEnabled(client)
      .then((enabled) => { if (active) setCatalogExportWorkerEnabled(enabled) })
    return () => { active = false }
  }, [client, workspace])

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

  const saveWorkspace = (value: string) => {
    const normalized = value.trim()
    const url = new URL(window.location.href)
    if (normalized) url.searchParams.set('workspace', normalized)
    else url.searchParams.delete('workspace')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
    setWorkspace(normalized)
  }

  const currentAdminContext = adminAccess.workspace === workspace && adminAccess.status === 'allowed'
    ? adminAccess.context
    : undefined
  const currentAdminStatus = adminAccess.workspace === workspace ? adminAccess.status : 'checking'
  const policyReadOperations: AdminOperation[] = [
    'CLASSIFICATION_POLICY_READ', 'RETENTION_POLICY_READ', 'LEGAL_HOLD_READ',
  ]
  const mayReadPolicyGovernance = Boolean(currentAdminContext && policyReadOperations
    .every((operation) => currentAdminContext.allowed_operations.includes(operation)))
  const adminMessages = getAdminMessages()
  const adminMenuItems = currentAdminContext
    ? allowedAdminSections(currentAdminContext).map((id) => ({ id, label: adminMessages[id] }))
    : []

  return (
    <AppShell
      page={page}
      client={client}
      workspace={workspace}
      deploymentTier={deploymentTier}
      displayName={auth.profile?.display_name ?? auth.user.profile.name ?? auth.user.profile.sub}
      email={auth.profile?.email}
      adminMenuItems={adminMenuItems}
      adminContextStatus={currentAdminStatus}
      externalSystemLinks={externalSystemLinks}
      notice={auth.notice}
      onNavigate={navigate}
      onNavigateAdmin={navigateAdmin}
      onSearch={searchCatalog}
      onWorkspaceChange={saveWorkspace}
      onPasswordReauth={() => void auth.beginPasswordReauth()}
      onEnrollSecurityKey={() => void auth.beginWebAuthnEnrollment()}
      onSignOut={() => void auth.signOut()}
      onClearNotice={auth.clearNotice}
    >
      {page === 'dashboard' && <DashboardPage client={client} onNavigate={navigate} />}
      {page === 'catalog' && <CatalogPage client={client} initialQuery={catalogQuery} onQueryChange={searchCatalog} catalogExportWorkerEnabled={catalogExportWorkerEnabled} />}
      {page === 'registration' && <RegistrationPage client={client} />}
      {page === 'change-management' && <GovernancePage client={client} onNavigate={navigate} onStepUp={auth.beginStepUp} onPasswordReauth={auth.beginPasswordReauth} onEnroll={auth.beginWebAuthnEnrollment} />}
      {page === 'quality' && <QualityPage />}
      {page === 'knowledge' && <KnowledgePage client={client} onNavigate={navigate} />}
      {page === 'monitoring' && <MonitoringPage client={client} />}
      {page === 'governance' && <PolicyGovernancePage client={client} mayReadPolicies={mayReadPolicyGovernance} allowedOperations={currentAdminContext?.allowed_operations} />}
      {page === 'sharing' && <SharingPage client={client} onStepUp={auth.beginStepUp} onPasswordReauth={auth.beginPasswordReauth} onEnroll={auth.beginWebAuthnEnrollment} />}
      {page === 'chat' && <ChatPage client={client} />}
      {page === 'admin' && currentAdminContext && <AdminPage client={client} initialContext={currentAdminContext} onStepUp={auth.beginStepUp} onPasswordReauth={auth.beginPasswordReauth} onEnroll={auth.beginWebAuthnEnrollment} />}
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
    </AppShell>
  )
}
