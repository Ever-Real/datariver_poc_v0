import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { Page } from '../../app/navigation'
import type { ExternalSystemLink, PocCapability } from '../../api/types'
import type { ApiClient } from '../../api/client'
import { pocNavigationForCapabilities, primaryNavigation } from '../../app/navigation'
import { GlobalCatalogSearch } from './GlobalCatalogSearch'
import { ExternalSystemLinks } from './ExternalSystemLinks'
import { ProfileMenu, type AdminContextStatus, type AdminMenuItem } from './ProfileMenu'
import { DataRiverMark } from './DataRiverMark'

interface TopNavigationProps {
  page: Page
  pocMode?: boolean
  client?: ApiClient
  workspace: string
  workspaceSelectionEnabled?: boolean
  hardwareWebauthnEnabled?: boolean
  deploymentTier: 'SINGLE_NODE_PILOT' | 'HA_CANDIDATE' | 'HA_ACCEPTED'
  displayName: string
  email?: string
  adminMenuItems: AdminMenuItem[]
  adminContextStatus?: AdminContextStatus
  externalSystemLinks: ExternalSystemLink[]
  pocCapabilities?: readonly PocCapability[]
  onNavigate: (page: Page) => void
  onNavigateAdmin: (section: string) => void
  onProfile?: () => void
  onSearch: (query: string) => void
  onWorkspaceChange: (workspace: string) => void
  onPasswordReauth?: () => void
  onEnrollSecurityKey?: () => void
  onSignOut?: () => void
}

export function TopNavigation({
  page,
  pocMode = false,
  client,
  workspace,
  workspaceSelectionEnabled = true,
  hardwareWebauthnEnabled = true,
  deploymentTier,
  displayName,
  email,
  adminMenuItems,
  adminContextStatus,
  externalSystemLinks,
  pocCapabilities = [],
  onNavigate,
  onNavigateAdmin,
  onProfile,
  onSearch,
  onWorkspaceChange,
  onPasswordReauth,
  onEnrollSecurityKey,
  onSignOut,
}: TopNavigationProps) {
  const [navigation, setNavigation] = useState<HTMLElement | null>(null)
  const activePrimaryPage = page === 'knowledge-chat'
    || page === 'knowledge-instances'
    || page === 'knowledge-profiles'
    || page === 'knowledge-studio'
    ? 'knowledge'
    : page
  const navigationItems = pocMode
    ? pocNavigationForCapabilities(pocCapabilities)
    : primaryNavigation

  return (
    <header className="top-navigation">
      <button className="top-brand" type="button" onClick={() => onNavigate('dashboard')} aria-label="DataRiver 홈">
        <span className="top-brand-mark" aria-hidden="true"><DataRiverMark /></span>
        <span>DataRiver</span>
      </button>
      <nav className="primary-navigation" aria-label="주 메뉴">
        <button className="navigation-scroll navigation-scroll-left" type="button" aria-label="이전 메뉴" onClick={() => navigation?.scrollBy({ left: -240, behavior: 'smooth' })}><ChevronLeft size={14} /></button>
        <div className="primary-navigation-track" ref={setNavigation}>
        {navigationItems.map(({ id, label, badge }) => (
          <button
            type="button"
            key={id}
            className={activePrimaryPage === id ? 'active' : ''}
            aria-current={activePrimaryPage === id ? 'page' : undefined}
            onClick={() => onNavigate(id)}
          >
            <span>{label}</span>
            {badge && <small>{badge}</small>}
          </button>
        ))}
        </div>
        <button className="navigation-scroll navigation-scroll-right" type="button" aria-label="다음 메뉴" onClick={() => navigation?.scrollBy({ left: 240, behavior: 'smooth' })}><ChevronRight size={14} /></button>
      </nav>
      <GlobalCatalogSearch
        key={workspace || 'workspace-unset'}
        client={client}
        onSearch={onSearch}
      />
      <ExternalSystemLinks links={externalSystemLinks} />
      <div className="top-navigation-profile-slot">
        <ProfileMenu
          pocMode={pocMode}
          displayName={displayName}
          workspace={workspace}
          workspaceSelectionEnabled={workspaceSelectionEnabled}
          hardwareWebauthnEnabled={hardwareWebauthnEnabled}
          deploymentTier={deploymentTier}
          adminMenuItems={adminMenuItems}
          email={email}
          adminContextStatus={adminContextStatus}
          onAdmin={onNavigateAdmin}
          onProfile={onProfile}
          onWorkspaceChange={onWorkspaceChange}
          onPasswordReauth={onPasswordReauth}
          onEnrollSecurityKey={onEnrollSecurityKey}
          onSignOut={onSignOut}
        />
        {pocMode && <span className="poc-navigation-badge" aria-label="POC mode">[poc]</span>}
      </div>
    </header>
  )
}
