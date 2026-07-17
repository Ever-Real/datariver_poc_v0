import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import {
  BellRing,
  BookOpen,
  ChevronDown,
  FileText,
  KeyRound,
  LogOut,
  Settings,
  ShieldCheck,
  UserRound,
} from 'lucide-react'

export interface AdminMenuItem { id: string; label: string }
export type AdminContextStatus = 'checking' | 'allowed' | 'denied' | 'reauth_required'

interface ProfileMenuProps {
  displayName: string
  email?: string
  workspace: string
  deploymentTier: 'SINGLE_NODE_PILOT' | 'HA_CANDIDATE' | 'HA_ACCEPTED'
  adminMenuItems: AdminMenuItem[]
  adminContextStatus?: AdminContextStatus
  onAdmin: (section: string) => void
  onWorkspaceChange: (workspace: string) => void
  onPasswordReauth?: () => void
  onEnrollSecurityKey: () => void
  onSignOut: () => void
}

export function ProfileMenu({
  displayName,
  email,
  workspace,
  deploymentTier,
  adminMenuItems,
  adminContextStatus = 'denied',
  onAdmin,
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
  const membership = adminMenuItems.find((item) => item.id === 'memberships')
  const remainingAdminItems = adminMenuItems.filter((item) => item.id !== 'memberships')

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
          <section className="legacy-profile-items" aria-label="프로필 설정">
            <button type="button" role="menuitem" onClick={openWorkspaceEditor}><UserRound size={14} aria-hidden="true" /><span>프로필</span></button>
            <button type="button" role="menuitem" onClick={openWorkspaceEditor}><Settings size={14} aria-hidden="true" /><span>설정</span></button>
          </section>
          {workspaceEditorOpen && <section className="profile-workspace-section" aria-label="프로필 Workspace 설정">
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
              {membership ? (
                <button type="button" role="menuitem" onClick={() => perform(() => onAdmin(membership.id))}>
                  <ShieldCheck size={14} aria-hidden="true" /><span>관리 (사용자관리)</span>
                </button>
              ) : (
                <LegacyUnavailable icon={<ShieldCheck size={14} aria-hidden="true" />} label="관리 (사용자관리)" />
              )}
              <LegacyUnavailable icon={<FileText size={14} aria-hidden="true" />} label="로그" />
              <LegacyUnavailable icon={<BellRing size={14} aria-hidden="true" />} label="알람규칙" />
              <LegacyUnavailable icon={<BookOpen size={14} aria-hidden="true" />} label="한글화 사전" />
              {remainingAdminItems.length > 0 && <p>Administration</p>}
              {remainingAdminItems.map((item) => (
                <button key={item.id} type="button" role="menuitem" onClick={() => perform(() => onAdmin(item.id))}>
                  <ShieldCheck size={14} aria-hidden="true" /><span>{item.label}</span>
                </button>
              ))}
            </section>
          )}
          <div className="profile-menu-actions">
            <button type="button" role="menuitem" onClick={() => perform(onEnrollSecurityKey)}><KeyRound size={14} aria-hidden="true" /><span>USB 보안키 등록</span></button>
            <button type="button" role="menuitem" className="danger" onClick={() => perform(onSignOut)}><LogOut size={14} aria-hidden="true" /><span>나가기</span></button>
          </div>
        </div>
      )}
    </div>
  )
}

function LegacyUnavailable({ icon, label }: { icon: ReactNode; label: string }) {
  return <button type="button" role="menuitem" disabled aria-disabled="true" title="v1 API 계약이 준비되지 않았습니다.">
    {icon}<span>{label}</span><small>준비 중</small>
  </button>
}

export function deploymentTierLabel(tier: ProfileMenuProps['deploymentTier']): string {
  return ({
    SINGLE_NODE_PILOT: 'Environment: Single-node Pilot',
    HA_CANDIDATE: 'Environment: HA Candidate',
    HA_ACCEPTED: 'Environment: HA Accepted',
  } as const)[tier]
}
