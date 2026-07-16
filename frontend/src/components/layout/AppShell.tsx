import type { ReactNode } from 'react'
import type { AuthNotice } from '../../auth/AuthProvider'
import type { Page } from '../../app/navigation'
import { TopNavigation } from './TopNavigation'

interface AppShellProps {
  page: Page
  workspace: string
  displayName: string
  canAdminister: boolean
  notice?: AuthNotice
  children: ReactNode
  onNavigate: (page: Page) => void
  onSearch: (query: string) => void
  onWorkspaceChange: (workspace: string) => void
  onEnrollSecurityKey: () => void
  onSignOut: () => void
  onClearNotice: () => void
}

export function AppShell({
  page,
  workspace,
  displayName,
  canAdminister,
  notice,
  children,
  onNavigate,
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
        workspace={workspace}
        displayName={displayName}
        canAdminister={canAdminister}
        onNavigate={onNavigate}
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
    </div>
  )
}
