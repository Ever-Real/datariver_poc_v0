import { useEffect, useState, type FormEvent } from 'react'
import type { Page } from '../../app/navigation'
import { primaryNavigation } from '../../app/navigation'
import { GlobalCatalogSearch } from './GlobalCatalogSearch'
import { ProfileMenu } from './ProfileMenu'

interface TopNavigationProps {
  page: Page
  workspace: string
  displayName: string
  canAdminister: boolean
  onNavigate: (page: Page) => void
  onSearch: (query: string) => void
  onWorkspaceChange: (workspace: string) => void
  onEnrollSecurityKey: () => void
  onSignOut: () => void
}

export function TopNavigation({
  page,
  workspace,
  displayName,
  canAdminister,
  onNavigate,
  onSearch,
  onWorkspaceChange,
  onEnrollSecurityKey,
  onSignOut,
}: TopNavigationProps) {
  const [workspaceDraft, setWorkspaceDraft] = useState(workspace)
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
        {primaryNavigation.map(({ id, label }) => (
          <button
            type="button"
            key={id}
            className={page === id ? 'active' : ''}
            aria-current={page === id ? 'page' : undefined}
            onClick={() => onNavigate(id)}
          >
            {label}
          </button>
        ))}
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
      <ProfileMenu
        displayName={displayName}
        canAdminister={canAdminister}
        onAdmin={() => onNavigate('admin')}
        onEnrollSecurityKey={onEnrollSecurityKey}
        onSignOut={onSignOut}
      />
    </header>
  )
}
