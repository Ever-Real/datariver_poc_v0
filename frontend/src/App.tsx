import { useEffect, useMemo, useState } from 'react'
import { ApiClient, remediationKind } from './api/client'
import type { AdminReadContext, CapabilitiesResponse, ExternalSystemLink } from './api/types'
import { pageFromLocation, pageUrl, type Page } from './app/navigation'
import { useAuth } from './auth/AuthProvider'
import { AppShell } from './components/layout/AppShell'
import { PageTitle } from './components/layout/PageTitle'
import { AdminPage, allowedAdminSections } from './features/admin/AdminPage'
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
  // A workspace selects a tenant/RLS boundary. Keep it in-memory so a prior
  // browser session cannot silently reuse a security context.
  const [workspace, setWorkspace] = useState('')
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
  ), [auth.user?.access_token, workspace])

  useEffect(() => {
    const restore = () => {
      setPage(pageFromLocation())
      setCatalogQuery(new URL(window.location.href).searchParams.get('q') ?? '')
    }
    window.addEventListener('popstate', restore)
    return () => window.removeEventListener('popstate', restore)
  }, [])

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
    <main className="login-shell">
      <section className="login-card">
        <p className="eyebrow">Data governance, made navigable</p>
        <h1>DataRiver</h1>
        <p>DataHub 카탈로그, 변경관리, 지식그래프와 근거 기반 CHAT을 하나의 보안 경계 안에서 운영합니다.</p>
        {auth.notice && <div className={`notice ${auth.notice.kind === 'ERROR' ? 'notice-error' : ''}`} role="alert"><span>{auth.notice.message}</span></div>}
        <button className="button" onClick={() => void auth.signIn()}>조직 계정으로 로그인</button>
      </section>
    </main>
  )

  const saveWorkspace = (value: string) => {
    setWorkspace(value)
  }

  const currentAdminContext = adminAccess.workspace === workspace && adminAccess.status === 'allowed'
    ? adminAccess.context
    : undefined
  const currentAdminStatus = adminAccess.workspace === workspace ? adminAccess.status : 'checking'
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
      displayName={auth.user.profile.name ?? auth.user.profile.sub}
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
      {page === 'dashboard' && <DashboardPage client={client} />}
      {page === 'catalog' && <CatalogPage client={client} initialQuery={catalogQuery} onQueryChange={searchCatalog} catalogExportWorkerEnabled={catalogExportWorkerEnabled} />}
      {page === 'registration' && <RegistrationPage client={client} />}
      {page === 'change-management' && <GovernancePage client={client} onStepUp={auth.beginStepUp} onPasswordReauth={auth.beginPasswordReauth} onEnroll={auth.beginWebAuthnEnrollment} />}
      {page === 'quality' && <QualityPage />}
      {page === 'knowledge' && <KnowledgePage client={client} />}
      {page === 'monitoring' && <MonitoringPage />}
      {page === 'governance' && <PolicyGovernancePage />}
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
