import { useEffect, useMemo, useState } from 'react'
import { ApiClient } from './api/client'
import { useAuth } from './auth/AuthProvider'
import { AdminPage } from './features/admin/AdminPage'
import { CatalogPage } from './features/catalog/CatalogPage'
import { ChatPage } from './features/chat/ChatPage'
import { DashboardPage } from './features/dashboard/DashboardPage'
import { GovernancePage } from './features/governance/GovernancePage'
import { KnowledgePage } from './features/knowledge/KnowledgePage'
import { RegistrationPage } from './features/registration/RegistrationPage'
import { SharingPage } from './features/sharing/SharingPage'

const pages = [
  ['dashboard', '운영'],
  ['catalog', '검색'],
  ['registration', '등록'],
  ['governance', '변경'],
  ['knowledge', '지식그래프'],
  ['sharing', 'API 공유'],
  ['chat', 'CHAT'],
  ['admin', '관리자'],
] as const
type Page = typeof pages[number][0]

function pageFromLocation(): Page {
  const candidate = new URL(window.location.href).searchParams.get('page')
  return pages.some(([id]) => id === candidate) ? candidate as Page : 'dashboard'
}

export function App() {
  const auth = useAuth()
  const [page, setPage] = useState<Page>(pageFromLocation)
  const [workspace, setWorkspace] = useState(() => window.localStorage.getItem('datariver.workspace') ?? '')
  const client = useMemo(() => new ApiClient(
    String(import.meta.env.VITE_API_BASE_URL || '/api/v1'),
    () => auth.user?.access_token,
    () => workspace,
  ), [auth.user?.access_token, workspace])

  useEffect(() => {
    const restore = () => setPage(pageFromLocation())
    window.addEventListener('popstate', restore)
    return () => window.removeEventListener('popstate', restore)
  }, [])

  const navigate = (next: Page) => {
    const url = new URL(window.location.href)
    url.searchParams.set('page', next)
    window.history.pushState({}, '', `${url.pathname}${url.search}${url.hash}`)
    setPage(next)
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
    window.localStorage.setItem('datariver.workspace', value)
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">DR</span><div><strong>DataRiver</strong><small>Governance Control Plane</small></div></div>
        <nav aria-label="주 메뉴">
          {pages.map(([id, label]) => <button className={page === id ? 'active' : ''} key={id} onClick={() => navigate(id)}>{label}</button>)}
        </nav>
        <div className="sidebar-foot"><small>{auth.user.profile.name ?? auth.user.profile.sub}</small><button onClick={() => void auth.beginWebAuthnEnrollment()}>USB 보안키 등록</button><button onClick={() => void auth.signOut()}>로그아웃</button></div>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <label>워크스페이스<input value={workspace} onChange={(event) => saveWorkspace(event.target.value)} placeholder="UUID" /></label>
          <span className="environment">ABAC enforced</span>
        </header>
        {auth.notice && <div className={`notice ${auth.notice.kind === 'ERROR' ? 'notice-error' : ''}`} role="status"><span>{auth.notice.message}</span><button className="button button-secondary" onClick={auth.clearNotice}>확인</button></div>}
        <div className="page-content">
          {page === 'dashboard' && <DashboardPage client={client} />}
          {page === 'catalog' && <CatalogPage client={client} />}
          {page === 'registration' && <RegistrationPage client={client} />}
          {page === 'governance' && <GovernancePage client={client} onStepUp={auth.beginStepUp} onPasswordReauth={auth.beginPasswordReauth} onEnroll={auth.beginWebAuthnEnrollment} />}
          {page === 'knowledge' && <KnowledgePage client={client} />}
          {page === 'sharing' && <SharingPage client={client} onStepUp={auth.beginStepUp} onPasswordReauth={auth.beginPasswordReauth} onEnroll={auth.beginWebAuthnEnrollment} />}
          {page === 'chat' && <ChatPage client={client} />}
          {page === 'admin' && <AdminPage client={client} onStepUp={auth.beginStepUp} onPasswordReauth={auth.beginPasswordReauth} onEnroll={auth.beginWebAuthnEnrollment} />}
        </div>
      </main>
    </div>
  )
}
