import { useEffect, useRef, useState } from 'react'
import { ChevronDown, KeyRound, LogOut, ShieldCheck, UserRound } from 'lucide-react'

export interface AdminMenuItem { id: string; label: string }

interface ProfileMenuProps {
  displayName: string
  adminMenuItems: AdminMenuItem[]
  onAdmin: (section: string) => void
  onEnrollSecurityKey: () => void
  onSignOut: () => void
}

export function ProfileMenu({
  displayName,
  adminMenuItems,
  onAdmin,
  onEnrollSecurityKey,
  onSignOut,
}: ProfileMenuProps) {
  const [open, setOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const initial = displayName.trim().slice(0, 1).toUpperCase() || 'U'

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
            <div><strong title={displayName}>{displayName}</strong><small>조직 계정</small></div>
          </header>
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
