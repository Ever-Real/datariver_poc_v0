import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { Page } from '../../app/navigation'
import type { ExternalSystemLink } from '../../api/types'
import type { ApiClient } from '../../api/client'
import { primaryNavigation } from '../../app/navigation'
import { GlobalCatalogSearch } from './GlobalCatalogSearch'
import { ExternalSystemLinks } from './ExternalSystemLinks'
import { ProfileMenu, type AdminMenuItem } from './ProfileMenu'
import { DataRiverMark } from './DataRiverMark'

interface TopNavigationProps {
  page: Page
  client?: ApiClient
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
  client,
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
  const [navigation, setNavigation] = useState<HTMLElement | null>(null)

  return (
    <header className="top-navigation">
      <button className="top-brand" type="button" onClick={() => onNavigate('dashboard')} aria-label="DataRiver 홈">
        <span className="top-brand-mark" aria-hidden="true"><DataRiverMark /></span>
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
      <GlobalCatalogSearch client={client} onSearch={onSearch} />
      <ExternalSystemLinks links={externalSystemLinks} />
      <ProfileMenu
        displayName={displayName}
        workspace={workspace}
        adminMenuItems={adminMenuItems}
        onAdmin={onNavigateAdmin}
        onWorkspaceChange={onWorkspaceChange}
        onEnrollSecurityKey={onEnrollSecurityKey}
        onSignOut={onSignOut}
      />
    </header>
  )
}
