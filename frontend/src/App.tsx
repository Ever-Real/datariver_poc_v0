import { useMemo, useState } from 'react'
import { ApiClient } from './api/client'
import { useAuth } from './auth/AuthProvider'
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
] as const
type Page = typeof pages[number][0]

export function App() {
  const auth = useAuth()
  const [page, setPage] = useState<Page>('dashboard')
  const [workspace, setWorkspace] = useState(() => window.localStorage.getItem('datariver.workspace') ?? '')
  const client = useMemo(() => new ApiClient(
    String(import.meta.env.VITE_API_BASE_URL || '/api/v1'),
    () => auth.user?.access_token,
    () => workspace,
  ), [auth.user?.access_token, workspace])

  if (auth.loading) return <main className="centered"><div className="loader" /><p>인증 상태를 확인하고 있습니다.</p></main>
  if (!auth.user) return (
    <main className="login-shell">
      <section className="login-card">
        <p className="eyebrow">Data governance, made navigable</p>
        <h1>DataRiver</h1>
        <p>DataHub 카탈로그, 변경관리, 지식그래프와 근거 기반 CHAT을 하나의 보안 경계 안에서 운영합니다.</p>
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
          {pages.map(([id, label]) => <button className={page === id ? 'active' : ''} key={id} onClick={() => setPage(id)}>{label}</button>)}
        </nav>
        <div className="sidebar-foot"><small>{auth.user.profile.name ?? auth.user.profile.sub}</small><button onClick={() => void auth.signOut()}>로그아웃</button></div>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <label>워크스페이스<input value={workspace} onChange={(event) => saveWorkspace(event.target.value)} placeholder="UUID" /></label>
          <span className="environment">ABAC enforced</span>
        </header>
        <div className="page-content">
          {page === 'dashboard' && <DashboardPage client={client} />}
          {page === 'catalog' && <CatalogPage client={client} />}
          {page === 'registration' && <RegistrationPage client={client} />}
          {page === 'governance' && <GovernancePage client={client} />}
          {page === 'knowledge' && <KnowledgePage client={client} />}
          {page === 'sharing' && <SharingPage client={client} />}
          {page === 'chat' && <ChatPage client={client} />}
        </div>
      </main>
    </div>
  )
}
