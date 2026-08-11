import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  Archive,
  BookOpen,
  ChevronDown,
  FileText,
  KeyRound,
  LogOut,
  Network,
  Settings,
  ShieldCheck,
  UserRound,
} from 'lucide-react'

export interface AdminMenuItem { id: string; label: string }
export type AdminContextStatus = 'checking' | 'allowed' | 'denied' | 'reauth_required'

function adminIcon(id: string) {
  if (id === 'systemSettings') return <Network size={14} aria-hidden="true" />
  if (id === 'retention') return <Archive size={14} aria-hidden="true" />
  if (id === 'auditLogs') return <FileText size={14} aria-hidden="true" />
  if (id === 'dictionary') return <BookOpen size={14} aria-hidden="true" />
  return <ShieldCheck size={14} aria-hidden="true" />
}

interface ProfileMenuProps {
  displayName: string
  email?: string
  workspace: string
  workspaceSelectionEnabled?: boolean
  hardwareWebauthnEnabled?: boolean
  deploymentTier: 'SINGLE_NODE_PILOT' | 'HA_CANDIDATE' | 'HA_ACCEPTED'
  adminMenuItems: AdminMenuItem[]
  adminContextStatus?: AdminContextStatus
  onAdmin: (section: string) => void
  onProfile?: () => void
  onWorkspaceChange: (workspace: string) => void
  onPasswordReauth?: () => void
  onEnrollSecurityKey?: () => void
  onSignOut?: () => void
}

export function ProfileMenu({
  displayName,
  email,
  workspace,
  workspaceSelectionEnabled = true,
  hardwareWebauthnEnabled = true,
  deploymentTier,
  adminMenuItems,
  adminContextStatus = 'denied',
  onAdmin,
  onProfile,
  onWorkspaceChange,
  onPasswordReauth,
  onEnrollSecurityKey,
  onSignOut,
}: ProfileMenuProps) {
  const [open, setOpen] = useState(false)
  const [workspaceDraft, setWorkspaceDraft] = useState(workspace)
  const [workspaceEditorOpen, setWorkspaceEditorOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const workspaceRef = useRef<HTMLInputElement>(null)

  useEffect(() => setWorkspaceDraft(workspace), [workspace])

  useEffect(() => {
    if (!workspaceSelectionEnabled) setWorkspaceEditorOpen(false)
  }, [workspaceSelectionEnabled])

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

  const openWorkspaceEditor = () => {
    setWorkspaceEditorOpen(true)
    window.requestAnimationFrame(() => workspaceRef.current?.focus())
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
        <span className="profile-avatar" aria-hidden="true"><UserRound size={18} /></span>
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <div className="profile-menu-panel" role="menu" aria-label="사용자 작업">
          <header>
            <div><strong title={displayName}>{displayName}</strong><small title={email}>{email || `조직 계정 · ${deploymentTierLabel(deploymentTier)}`}</small></div>
          </header>
          {(onProfile || workspaceSelectionEnabled) && (
            <section className="legacy-profile-items" aria-label="프로필 설정">
              {onProfile && <button type="button" role="menuitem" onClick={() => perform(onProfile)}><UserRound size={14} aria-hidden="true" /><span>내 프로필</span></button>}
              {workspaceSelectionEnabled && <button type="button" role="menuitem" onClick={openWorkspaceEditor}><Settings size={14} aria-hidden="true" /><span>Workspace 전환</span></button>}
            </section>
          )}
          {workspaceSelectionEnabled && workspaceEditorOpen && <section className="profile-workspace-section" aria-label="프로필 Workspace 설정">
            <form className="profile-workspace" onSubmit={applyWorkspace}>
              <label htmlFor="profile-workspace-id">Workspace</label>
              <div><input ref={workspaceRef} id="profile-workspace-id" aria-label="Workspace ID" value={workspaceDraft} onChange={(event) => setWorkspaceDraft(event.target.value)} /><button type="submit">적용</button></div>
            </form>
          </section>}
          {adminContextStatus === 'reauth_required' && onPasswordReauth && (
            <section aria-label="관리자 인증">
              <p>관리자 인증</p>
              <small>관리자 메뉴를 확인하려면 현재 Workspace에 대해 비밀번호 재인증이 필요합니다.</small>
              <button type="button" role="menuitem" onClick={() => perform(onPasswordReauth)}>
                <KeyRound size={14} aria-hidden="true" /><span>관리자 재인증</span>
              </button>
            </section>
          )}
          {adminMenuItems.length > 0 && (
            <section className="legacy-admin-items" aria-label="Administration">
              <p>Administration</p>
              {adminMenuItems.map((item) => (
                <button key={item.id} type="button" role="menuitem" onClick={() => perform(() => onAdmin(item.id))}>
                  {adminIcon(item.id)}<span>{item.label}</span>
                </button>
              ))}
            </section>
          )}
          {(hardwareWebauthnEnabled && onEnrollSecurityKey || onSignOut) && (
            <div className="profile-menu-actions">
              {hardwareWebauthnEnabled && onEnrollSecurityKey && <button type="button" role="menuitem" onClick={() => perform(onEnrollSecurityKey)}><KeyRound size={14} aria-hidden="true" /><span>WebAuthn 보안키 등록</span></button>}
              {onSignOut && <button type="button" role="menuitem" className="danger" onClick={() => perform(onSignOut)}><LogOut size={14} aria-hidden="true" /><span>나가기</span></button>}
            </div>
          )}
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
