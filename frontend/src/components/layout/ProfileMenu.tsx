import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ChevronDown, KeyRound, LogOut, ShieldCheck, UserRound } from 'lucide-react'

export interface AdminMenuItem { id: string; label: string }

interface ProfileMenuProps {
  displayName: string
  workspace: string
  deploymentTier: 'SINGLE_NODE_PILOT' | 'HA_CANDIDATE' | 'HA_ACCEPTED'
  adminMenuItems: AdminMenuItem[]
  onAdmin: (section: string) => void
  onWorkspaceChange: (workspace: string) => void
  onEnrollSecurityKey: () => void
  onSignOut: () => void
}

export function ProfileMenu({
  displayName,
  workspace,
  deploymentTier,
  adminMenuItems,
  onAdmin,
  onWorkspaceChange,
  onEnrollSecurityKey,
  onSignOut,
}: ProfileMenuProps) {
  const [open, setOpen] = useState(false)
  const [workspaceDraft, setWorkspaceDraft] = useState(workspace)
  const menuRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const initial = displayName.trim().slice(0, 1).toUpperCase() || 'U'

  useEffect(() => setWorkspaceDraft(workspace), [workspace])

  useEffect(() => {
    if (!open) return
    const closeOnOutside = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setOpen(false); triggerRef.current?.focus()
    }
    document.addEventListener('mousedown', closeOnOutside)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('mousedown', closeOnOutside)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])

  const perform = (action: () => void) => {
    setOpen(false); action()
  }

  const applyWorkspace = (event: FormEvent) => {
    event.preventDefault()
    const next = workspaceDraft.trim()
    if (!next) return
    setOpen(false)
    onWorkspaceChange(next)
  }

  return (
    <div className="profile-menu" ref={menuRef}>
      <button
        ref={triggerRef}
        type="button"
        className="profile-menu-trigger"
        aria-label={`${displayName} 사용자 메뉴`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="profile-avatar" aria-hidden="true">{initial}</span>
        <span className="profile-name" title={displayName}>{displayName}</span>
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <div className="profile-menu-panel" role="menu" aria-label="사용자 작업">
          <header>
            <UserRound size={16} aria-hidden="true" />
            <div><strong title={displayName}>{displayName}</strong><small>조직 계정 · {deploymentTierLabel(deploymentTier)}</small></div>
          </header>
          <form className="profile-workspace" onSubmit={applyWorkspace}>
            <label htmlFor="profile-workspace-id">Workspace</label>
            <div><input id="profile-workspace-id" aria-label="Workspace ID" value={workspaceDraft} onChange={(event) => setWorkspaceDraft(event.target.value)} /><button type="submit">적용</button></div>
          </form>
          {adminMenuItems.length > 0 && (
            <section aria-label="Administration">
              <p>Administration</p>
              {adminMenuItems.map((item) => (
                <button key={item.id} type="button" role="menuitem" onClick={() => perform(() => onAdmin(item.id))}>
                  <ShieldCheck size={14} aria-hidden="true" /><span>{item.label}</span>
                </button>
              ))}
            </section>
          )}
          <div className="profile-menu-actions">
            <button type="button" role="menuitem" onClick={() => perform(onEnrollSecurityKey)}><KeyRound size={14} aria-hidden="true" /><span>USB 보안키 등록</span></button>
            <button type="button" role="menuitem" className="danger" onClick={() => perform(onSignOut)}><LogOut size={14} aria-hidden="true" /><span>로그아웃</span></button>
          </div>
        </div>
      )}
    </div>
  )
}

export function deploymentTierLabel(tier: ProfileMenuProps['deploymentTier']): string {
  return ({
    SINGLE_NODE_PILOT: 'Environment: Single-node Pilot',
    HA_CANDIDATE: 'Environment: HA Candidate',
    HA_ACCEPTED: 'Environment: HA Accepted',
  } as const)[tier]
}
