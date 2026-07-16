import { useEffect, useState, type FormEvent } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { Page } from '../../app/navigation'
import type { ExternalSystemLink } from '../../api/types'
import { primaryNavigation } from '../../app/navigation'
import { GlobalCatalogSearch } from './GlobalCatalogSearch'
import { ExternalSystemLinks } from './ExternalSystemLinks'
import { ProfileMenu, type AdminMenuItem } from './ProfileMenu'

interface TopNavigationProps {
  page: Page
  workspace: string
  displayName: string
  adminMenuItems: AdminMenuItem[]
  externalSystemLinks: ExternalSystemLink[]
  onNavigate: (page: Page) => void
  onNavigateAdmin: (section: string) => void
  onSearch: (query: string) => void
  onWorkspaceChange: (workspace: string) => void
  onEnrollSecurityKey: () => void
  onSignOut: () => void
}

export function TopNavigation({
  page,
  workspace,
  displayName,
  adminMenuItems,
  externalSystemLinks,
  onNavigate,
  onNavigateAdmin,
  onSearch,
  onWorkspaceChange,
  onEnrollSecurityKey,
  onSignOut,
}: TopNavigationProps) {
  const [workspaceDraft, setWorkspaceDraft] = useState(workspace)
  const [navigation, setNavigation] = useState<HTMLElement | null>(null)
  useEffect(() => setWorkspaceDraft(workspace), [workspace])

  const applyWorkspace = (event: FormEvent) => {
    event.preventDefault()
    onWorkspaceChange(workspaceDraft.trim())
  }

  return (
    <header className="top-navigation">
      <button className="top-brand" type="button" onClick={() => onNavigate('dashboard')} aria-label="DataRiver 홈">
        <span className="top-brand-mark" aria-hidden="true">DR</span>
        <span>DataRiver</span>
      </button>
      <nav className="primary-navigation" aria-label="주 메뉴">
        <button className="navigation-scroll navigation-scroll-left" type="button" aria-label="이전 메뉴" onClick={() => navigation?.scrollBy({ left: -240, behavior: 'smooth' })}><ChevronLeft size={14} /></button>
        <div className="primary-navigation-track" ref={setNavigation}>
        {primaryNavigation.map(({ id, label, badge }) => (
          <button
            type="button"
            key={id}
            className={page === id ? 'active' : ''}
            aria-current={page === id ? 'page' : undefined}
            onClick={() => onNavigate(id)}
          >
            <span>{label}</span>
            {badge && <small>{badge}</small>}
          </button>
        ))}
        </div>
        <button className="navigation-scroll navigation-scroll-right" type="button" aria-label="다음 메뉴" onClick={() => navigation?.scrollBy({ left: 240, behavior: 'smooth' })}><ChevronRight size={14} /></button>
      </nav>
      <GlobalCatalogSearch onSearch={onSearch} />
      <form className="workspace-control" onSubmit={applyWorkspace}>
        <label htmlFor="workspace-id">Workspace</label>
        <input
          id="workspace-id"
          value={workspaceDraft}
          onChange={(event) => setWorkspaceDraft(event.target.value)}
          placeholder="Workspace UUID"
          aria-label="Workspace ID"
        />
        <button type="submit">적용</button>
      </form>
      <div className="top-status" aria-label="배포 상태">
        <span title="현재 저장소의 단일 호스트 배포 등급">Single-node Pilot</span>
        <span title="서버가 최종 권한을 평가합니다">ABAC</span>
      </div>
      <ExternalSystemLinks links={externalSystemLinks} />
      <ProfileMenu
        displayName={displayName}
        adminMenuItems={adminMenuItems}
        onAdmin={onNavigateAdmin}
        onEnrollSecurityKey={onEnrollSecurityKey}
        onSignOut={onSignOut}
      />
    </header>
  )
}
