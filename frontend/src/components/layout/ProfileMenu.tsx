interface ProfileMenuProps {
  displayName: string
  canAdminister: boolean
  onAdmin: () => void
  onEnrollSecurityKey: () => void
  onSignOut: () => void
}

export function ProfileMenu({
  displayName,
  canAdminister,
  onAdmin,
  onEnrollSecurityKey,
  onSignOut,
}: ProfileMenuProps) {
  const initial = displayName.trim().slice(0, 1).toUpperCase() || 'U'
  return (
    <details className="profile-menu">
      <summary aria-label={`${displayName} 사용자 메뉴`}>
        <span className="profile-avatar" aria-hidden="true">{initial}</span>
        <span className="profile-name" title={displayName}>{displayName}</span>
        <span aria-hidden="true">▾</span>
      </summary>
      <div className="profile-menu-panel" aria-label="사용자 작업">
        {canAdminister && <button type="button" onClick={onAdmin}>관리자</button>}
        <button type="button" onClick={onEnrollSecurityKey}>USB 보안키 등록</button>
        <button type="button" onClick={onSignOut}>로그아웃</button>
      </div>
    </details>
  )
}
