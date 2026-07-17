import type { ReactNode } from 'react'
import type { AuthNotice } from '../../auth/AuthProvider'
import type { ExternalSystemLink } from '../../api/types'
import type { ApiClient } from '../../api/client'
import type { Page } from '../../app/navigation'
import { TopNavigation } from './TopNavigation'
import type { AdminMenuItem } from './ProfileMenu'

interface AppShellProps {
  page: Page
  client?: ApiClient
  workspace: string
  deploymentTier?: 'SINGLE_NODE_PILOT' | 'HA_CANDIDATE' | 'HA_ACCEPTED'
  displayName: string
  adminMenuItems: AdminMenuItem[]
  externalSystemLinks: ExternalSystemLink[]
  notice?: AuthNotice
  children: ReactNode
  onNavigate: (page: Page) => void
  onNavigateAdmin: (section: string) => void
  onSearch: (query: string) => void
  onWorkspaceChange: (workspace: string) => void
  onEnrollSecurityKey: () => void
  onSignOut: () => void
  onClearNotice: () => void
}

export function AppShell({
  page,
  client,
  workspace,
  deploymentTier = 'SINGLE_NODE_PILOT',
  displayName,
  adminMenuItems,
  externalSystemLinks,
  notice,
  children,
  onNavigate,
  onNavigateAdmin,
  onSearch,
  onWorkspaceChange,
  onEnrollSecurityKey,
  onSignOut,
  onClearNotice,
}: AppShellProps) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">본문으로 건너뛰기</a>
      <TopNavigation
        page={page}
        client={client}
        workspace={workspace}
        deploymentTier={deploymentTier}
        displayName={displayName}
        adminMenuItems={adminMenuItems}
        externalSystemLinks={externalSystemLinks}
        onNavigate={onNavigate}
        onNavigateAdmin={onNavigateAdmin}
        onSearch={onSearch}
        onWorkspaceChange={onWorkspaceChange}
        onEnrollSecurityKey={onEnrollSecurityKey}
        onSignOut={onSignOut}
      />
      <main className="workspace" id="main-content">
        {notice && (
          <div className={`notice shell-notice ${notice.kind === 'ERROR' ? 'notice-error' : ''}`} role="status">
            <span>{notice.message}</span>
            <button className="button button-secondary" type="button" onClick={onClearNotice}>확인</button>
          </div>
        )}
        <div className="page-content" key={workspace || 'workspace-unset'}>{children}</div>
      </main>
      <footer className="deployment-footer">{deploymentTier === 'SINGLE_NODE_PILOT' ? '[Environment: Single-node Pilot]' : `[Environment: ${deploymentTier === 'HA_CANDIDATE' ? 'HA Candidate' : 'HA Accepted'}]`}</footer>
    </div>
  )
}
