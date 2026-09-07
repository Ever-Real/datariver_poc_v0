import type { ReactNode } from 'react'
import type { AuthNotice } from '../../auth/AuthProvider'
import type { ExternalSystemLink, PocCapability, PocRole } from '../../api/types'
import type { ApiClient } from '../../api/client'
import type { Page } from '../../app/navigation'
import { TopNavigation } from './TopNavigation'
import type { AdminContextStatus, AdminMenuItem } from './ProfileMenu'

interface AppShellProps {
  page: Page
  pocMode?: boolean
  client?: ApiClient
  workspace: string
  securityEpoch?: number
  workspaceSelectionEnabled?: boolean
  hardwareWebauthnEnabled?: boolean
  deploymentTier?: 'SINGLE_NODE_PILOT' | 'HA_CANDIDATE' | 'HA_ACCEPTED'
  displayName: string
  email?: string
  adminMenuItems: AdminMenuItem[]
  adminContextStatus?: AdminContextStatus
  externalSystemLinks: ExternalSystemLink[]
  pocCapabilities?: readonly PocCapability[]
  pocRole?: PocRole
  notice?: AuthNotice
  children: ReactNode
  onNavigate: (page: Page) => void
  onNavigateAdmin: (section: string) => void
  onProfile?: () => void
  onSearch: (query: string) => void
  onWorkspaceChange: (workspace: string) => void
  onPasswordReauth?: () => void
  onEnrollSecurityKey?: () => void
  onSignOut?: () => void
  onClearNotice: () => void
}

export function AppShell({
  page,
  pocMode = false,
  client,
  workspace,
  securityEpoch = 0,
  workspaceSelectionEnabled = true,
  hardwareWebauthnEnabled = true,
  deploymentTier = 'SINGLE_NODE_PILOT',
  displayName,
  email,
  adminMenuItems,
  adminContextStatus,
  externalSystemLinks,
  pocCapabilities,
  pocRole,
  notice,
  children,
  onNavigate,
  onNavigateAdmin,
  onProfile,
  onSearch,
  onWorkspaceChange,
  onPasswordReauth,
  onEnrollSecurityKey,
  onSignOut,
  onClearNotice,
}: AppShellProps) {
  const securityBoundaryKey = `${workspace || 'workspace-unset'}:${securityEpoch}`
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">본문으로 건너뛰기</a>
      <TopNavigation
        key={securityBoundaryKey}
        page={page}
        pocMode={pocMode}
        client={client}
        workspace={workspace}
        workspaceSelectionEnabled={workspaceSelectionEnabled}
        hardwareWebauthnEnabled={hardwareWebauthnEnabled}
        deploymentTier={deploymentTier}
        displayName={displayName}
        email={email}
        adminMenuItems={adminMenuItems}
        adminContextStatus={adminContextStatus}
        externalSystemLinks={externalSystemLinks}
        pocCapabilities={pocCapabilities}
        pocRole={pocRole}
        onNavigate={onNavigate}
        onNavigateAdmin={onNavigateAdmin}
        onProfile={onProfile}
        onSearch={onSearch}
        onWorkspaceChange={onWorkspaceChange}
        onPasswordReauth={onPasswordReauth}
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
        <div className="page-content" key={securityBoundaryKey}>{children}</div>
      </main>
    </div>
  )
}
