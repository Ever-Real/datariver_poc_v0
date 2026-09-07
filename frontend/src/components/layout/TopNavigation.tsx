import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { Page } from '../../app/navigation'
import type { ExternalSystemLink, PocCapability, PocRole } from '../../api/types'
import type { ApiClient } from '../../api/client'
import { pocNavigationForCapabilities, primaryNavigation } from '../../app/navigation'
import { GlobalCatalogSearch } from './GlobalCatalogSearch'
import { ExternalSystemLinks } from './ExternalSystemLinks'
import { ProfileMenu, type AdminContextStatus, type AdminMenuItem } from './ProfileMenu'
import { DataRiverMark } from './DataRiverMark'
import { useSiteBranding } from './SiteBranding'

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
  pocRole?: PocRole
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
  pocRole,
  onNavigate,
  onNavigateAdmin,
  onProfile,
  onSearch,
  onWorkspaceChange,
  onPasswordReauth,
  onEnrollSecurityKey,
  onSignOut,
}: TopNavigationProps) {
  const { branding } = useSiteBranding()
  const [navigation, setNavigation] = useState<HTMLElement | null>(null)
  const activePrimaryPage = page === 'knowledge-chat'
    || page === 'knowledge-instances'
    || page === 'knowledge-profiles'
    || page === 'knowledge-studio'
    ? 'knowledge'
    : page
  const navigationItems = (pocMode
    ? pocNavigationForCapabilities(pocCapabilities, pocRole)
    : primaryNavigation
  )

  return (
    <header className="top-navigation">
      <button className="top-brand" type="button" onClick={() => onNavigate('dashboard')} aria-label={`${branding.site_name} 홈`}>
        <span className="top-brand-mark" aria-hidden="true">{branding.logo
          ? <img className="site-branding-logo" src={branding.logo.data_url} alt="" />
          : <DataRiverMark />}</span>
        <span>{branding.site_name}</span>
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
      <nav className="site-custom-badge-links" aria-label="사이트 바로가기">
        {(branding.custom_badges ?? []).filter((badge) => badge.enabled).map((badge) => <a
          key={badge.badge_id}
          href={badge.url}
          target="_blank"
          rel="noopener noreferrer"
          title={badge.name}
          aria-label={`${badge.name} 새 창에서 열기`}
        >
          {badge.logo && <img src={badge.logo.data_url} alt="" />}
          <span>{badge.name}</span>
        </a>)}
      </nav>
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
