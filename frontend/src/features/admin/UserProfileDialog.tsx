import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  AdminReadContext,
  Classification,
  MembershipChangeRequestActivity,
  MembershipOwnedTable,
  ProfileRolePolicy,
  WorkspaceMembershipSummary,
} from '../../api/types'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import type {
  AdminApi,
  VersionedIdentityUserProfile,
  VersionedMembershipAccess,
} from './adminApi'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'

type ProfileTab = 'profile' | 'access' | 'activity' | 'security'

interface UserProfileDialogProps {
  open: boolean
  member?: WorkspaceMembershipSummary
  api: AdminApi
  context?: AdminReadContext
  keyFor: (intent: string, prefix: string) => string
  clearKey: (intent: string) => void
  reportError: (error: unknown) => void
  requestConfirmation: (mutation: PendingAdminMutation) => void
  onRequestClose: () => void
  onUpdated: () => Promise<void>
}

const PROFILE_TABS: Array<{ id: ProfileTab; label: string }> = [
  { id: 'profile', label: '사용자 정보' },
  { id: 'access', label: '데이터·화면 접근' },
  { id: 'activity', label: 'CR·활동' },
  { id: 'security', label: '비밀번호 재설정' },
]

function displayTimestamp(value: string | null | undefined): string {
  if (!value) return '기록 없음'
  return new Intl.DateTimeFormat('ko-KR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export function UserProfileDialog({
  open,
  member,
  api,
  context,
  keyFor,
  clearKey,
  reportError,
  requestConfirmation,
  onRequestClose,
  onUpdated,
}: UserProfileDialogProps) {
  const [activeTab, setActiveTab] = useState<ProfileTab>('profile')
  const [loading, setLoading] = useState(false)
  const [profile, setProfile] = useState<VersionedIdentityUserProfile>()
  const [access, setAccess] = useState<VersionedMembershipAccess>()
  const [profileRolePolicy, setProfileRolePolicy] = useState<ProfileRolePolicy>()
  const [selectedTier, setSelectedTier] = useState<ProfileRolePolicy['items'][number]['tier']>()
  const [selectedClearance, setSelectedClearance] = useState<Classification>('CONFIDENTIAL')
  const [selectedAuthorityRole, setSelectedAuthorityRole] = useState<'admin' | 'data_steward' | 'developer' | 'manager' | 'viewer'>('viewer')
  const [selectedActive, setSelectedActive] = useState(true)
  const [accessReason, setAccessReason] = useState('')
  const [changeRequests, setChangeRequests] = useState<MembershipChangeRequestActivity[]>([])
  const [ownedTables, setOwnedTables] = useState<MembershipOwnedTable[]>([])
  const [activityTruncated, setActivityTruncated] = useState(false)
  const [profileDraft, setProfileDraft] = useState({
    email: '',
    firstName: '',
    lastName: '',
    departmentId: '',
    jobFunction: '',
  })
  const [temporaryPassword, setTemporaryPassword] = useState('')
  const [passwordConfirmation, setPasswordConfirmation] = useState('')
  const [passwordResetComplete, setPasswordResetComplete] = useState(false)
  const loadGeneration = useRef(0)
  const operations = new Set(context?.allowed_operations ?? [])
  const pocOpenAccess = context?.action_vocabulary.includes('POC_OPEN_ACCESS_V1') ?? false
  const canReadIdentity = operations.has('IDENTITY_USER_PROFILE_READ')
  const canUpdateIdentity = operations.has('IDENTITY_USER_PROFILE_UPDATE')
  const canResetPassword = operations.has('IDENTITY_USER_PASSWORD_RESET')
  const canUpdateAuthority = operations.has('MEMBERSHIP_ACCESS_UPDATE')
  const isServiceAccount = member?.job_function === 'SERVICE_ACCOUNT'
  const canAssignProfile = (
    operations.has('MEMBERSHIP_ACCESS_UPDATE')
    && member?.subject_id !== context?.subject_id
    && Boolean(access?.etag)
  )

  const loadDetails = useCallback(async (signal?: AbortSignal) => {
    if (!member) return
    const generation = ++loadGeneration.current
    setLoading(true)
    try {
      const [
        nextAccess,
        nextProfile,
        nextChangeRequests,
        nextOwnedTables,
        nextProfileRolePolicy,
      ] = await Promise.all([
        api.getMembershipAccess(member.subject_id, signal),
        canReadIdentity && !isServiceAccount
          ? api.getIdentityUserProfile(member.subject_id, signal)
          : Promise.resolve(undefined),
        api.listMembershipChangeRequestActivity(member.subject_id, undefined, signal),
        api.listMembershipOwnedTables(member.subject_id, undefined, signal),
        api.getProfileRolePolicy(signal),
      ])
      if (signal?.aborted || generation !== loadGeneration.current) return
      setAccess(nextAccess)
      setProfileRolePolicy(nextProfileRolePolicy)
      setSelectedTier(nextAccess.profile_role.tier ?? undefined)
      setSelectedClearance(nextAccess.access.clearance)
      setSelectedAuthorityRole(member.change_history_role ?? 'viewer')
      setSelectedActive(member.subject_active && member.membership_active)
      setProfile(nextProfile)
      setChangeRequests(nextChangeRequests.items)
      setOwnedTables(nextOwnedTables.items)
      setActivityTruncated(Boolean(nextChangeRequests.nextCursor || nextOwnedTables.nextCursor))
      if (nextProfile) {
        setProfileDraft({
          email: nextProfile.email,
          firstName: nextProfile.first_name,
          lastName: nextProfile.last_name,
          departmentId: nextProfile.department_id ?? '',
          jobFunction: nextProfile.job_function ?? '',
        })
      } else {
        setProfileDraft({
          email: member.email ?? '',
          firstName: '',
          lastName: '',
          departmentId: member.department_id ?? '',
          jobFunction: member.job_function ?? '',
        })
      }
    } catch (error) {
      if (!signal?.aborted && generation === loadGeneration.current) reportError(error)
    } finally {
      if (!signal?.aborted && generation === loadGeneration.current) setLoading(false)
    }
  }, [api, canReadIdentity, isServiceAccount, member, reportError])

  useEffect(() => {
    if (!open || !member) return
    setActiveTab('profile')
    setProfile(undefined)
    setAccess(undefined)
    setProfileRolePolicy(undefined)
    setSelectedTier(undefined)
    setAccessReason('')
    setChangeRequests([])
    setOwnedTables([])
    setTemporaryPassword('')
    setPasswordConfirmation('')
    setPasswordResetComplete(false)
    const controller = new AbortController()
    void loadDetails(controller.signal)
    return () => {
      controller.abort()
      loadGeneration.current += 1
    }
  }, [loadDetails, member, open])

  if (!member) return null
  const profileChanged = profile !== undefined && (
    profileDraft.email.trim() !== profile.email
    || profileDraft.firstName.trim() !== profile.first_name
    || profileDraft.lastName.trim() !== profile.last_name
    || (profileDraft.departmentId.trim() || null) !== profile.department_id
    || (profileDraft.jobFunction.trim() || null) !== profile.job_function
  )
  const profileValid = (
    profileDraft.email.includes('@')
    && profileDraft.firstName.trim().length > 0
    && profileDraft.lastName.trim().length > 0
  )

  const saveProfile = () => {
    if (!profile || !canUpdateIdentity || !profileChanged || !profileValid) return
    const payload = {
      email: profileDraft.email.trim(),
      first_name: profileDraft.firstName.trim(),
      last_name: profileDraft.lastName.trim(),
      department_id: profileDraft.departmentId.trim() || null,
      job_function: profileDraft.jobFunction.trim() || null,
    }
    const intent = `identity-profile:${member.subject_id}:${profile.etag}`
    requestConfirmation({
      title: `${member.display_name} 사용자 정보 수정`,
      summary: [
        `${payload.first_name} ${payload.last_name}`,
        payload.email,
        payload.job_function ?? '업무 역할 미지정',
      ],
      execute: async () => {
        await api.updateIdentityUserProfile(
          member.subject_id,
          payload,
          profile.etag,
          keyFor(intent, 'identity-profile'),
        )
        clearKey(intent)
        await Promise.all([loadDetails(), onUpdated()])
      },
    })
  }

  const saveProfileRole = () => {
    if (!access || !canAssignProfile || !selectedTier || !accessReason.trim()) return
    if (access.profile_role.tier === selectedTier && access.profile_role.status === 'VERIFIED') return
    const intent = `profile-role:${member.subject_id}:${access.etag}:${selectedTier}`
    requestConfirmation({
      title: `${member.display_name} 프로필 권한 변경`,
      summary: [
        `${access.profile_role.tier ?? access.profile_role.status} → ${selectedTier}`,
        '프로필 권한과 데이터 조회 등급은 별도로 관리됩니다.',
        accessReason.trim(),
      ],
      execute: async () => {
        await api.updateProfileRole(
          member.subject_id,
          selectedTier,
          access.canonical_admin_binding.binding_version ?? 0,
          accessReason.trim(),
          access.etag,
          keyFor(intent, 'profile-role'),
        )
        clearKey(intent)
        setAccessReason('')
        await Promise.all([loadDetails(), onUpdated()])
      },
    })
  }

  const saveClearance = () => {
    if (!access || !canAssignProfile || access.access.clearance === selectedClearance) return
    const intent = `membership-clearance:${member.subject_id}:${access.etag}:${selectedClearance}`
    requestConfirmation({
      title: `${member.display_name} 데이터 조회 등급 변경`,
      summary: [
        `${access.access.clearance} → ${selectedClearance}`,
        '프로필 권한은 변경하지 않습니다.',
      ],
      execute: async () => {
        await api.updateMembership(
          member.subject_id,
          { ...access.access, clearance: selectedClearance },
          access.etag,
          keyFor(intent, 'membership-clearance'),
        )
        clearKey(intent)
        await Promise.all([loadDetails(), onUpdated()])
      },
    })
  }

  const saveAccessAuthority = () => {
    if (!access || !canUpdateAuthority || !accessReason.trim()) return
    const unchanged = selectedActive === (member.subject_active && member.membership_active)
      && selectedAuthorityRole === (member.change_history_role ?? 'viewer')
    if (unchanged) return
    const intent = `access-authority:${member.subject_id}:${access.etag}:${selectedActive}:${selectedAuthorityRole}`
    requestConfirmation({
      title: `${member.display_name} access authority 변경`,
      summary: [
        `${member.change_history_role ?? 'viewer'} → ${selectedAuthorityRole}`,
        `${member.membership_active ? 'ACTIVE' : 'INACTIVE'} → ${selectedActive ? 'ACTIVE' : 'INACTIVE'}`,
        accessReason.trim(),
      ],
      execute: async () => {
        await api.updateAccessAuthorityUser(
          member.subject_id,
          selectedActive,
          selectedAuthorityRole,
          access.etag,
          keyFor(intent, 'access-authority-user'),
        )
        clearKey(intent)
        await Promise.all([loadDetails(), onUpdated()])
      },
    })
  }

  const resetPassword = () => {
    if (
      !profile
      || !canResetPassword
      || temporaryPassword.length < 12
      || temporaryPassword !== passwordConfirmation
    ) return
    const capturedPassword = temporaryPassword
    const intent = `identity-password-reset:${member.subject_id}:${profile.etag}`
    requestConfirmation({
      title: `${member.display_name} 임시 비밀번호 재설정`,
      summary: [
        '현재 로그인 세션 전체 종료',
        '다음 로그인 시 비밀번호 변경 필수',
        '임시 비밀번호는 저장하거나 감사 로그에 남기지 않음',
      ],
      execute: async () => {
        await api.resetIdentityTemporaryPassword(
          member.subject_id,
          capturedPassword,
          profile.etag,
          keyFor(intent, 'identity-password-reset'),
        )
        clearKey(intent)
        setTemporaryPassword('')
        setPasswordConfirmation('')
        setPasswordResetComplete(true)
        await loadDetails()
      },
    })
  }

  return <Dialog
    open={open}
    size="large"
    compactHeight
    title="사용자 프로필 수정"
    description={pocOpenAccess ? 'POC 사용자 정보, 향후 적용할 접근 Role과 실제 업무 활동을 관리합니다.' : '사용자 정보, 데이터·화면 접근 Role, 실제 업무 활동과 인증 복구를 한 곳에서 관리합니다.'}
    onRequestClose={onRequestClose}
    footer={<button type="button" className="button button-secondary" onClick={onRequestClose}>닫기</button>}
  >
    <div className="grid gap-3">
      <div className="grid gap-2 rounded-enterprise border border-slate-300 bg-slate-50 p-3 sm:grid-cols-2 lg:grid-cols-4">
        <div><span className="eyebrow">사용자</span><strong className="mt-1 block text-sm text-navy-900">{member.display_name}</strong></div>
        <div><span className="eyebrow">업무 역할</span><strong className="mt-1 block text-sm">{member.job_function ?? '미지정'}</strong></div>
        <div><span className="eyebrow">부서</span><strong className="mt-1 block text-sm">{member.department_id ?? '미할당'}</strong></div>
        <div><span className="eyebrow">상태</span><strong className="mt-1 block text-sm">{member.membership_active ? 'ACTIVE' : 'INACTIVE'} · {member.clearance}</strong></div>
      </div>
      <div className="flex flex-wrap gap-1 border-b border-slate-300" role="tablist" aria-label="사용자 프로필 관리">
        {PROFILE_TABS.filter((tab) => !pocOpenAccess || tab.id !== 'security').map((tab) => <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          className={`border border-b-0 px-3 py-2 text-xs font-black ${activeTab === tab.id ? 'border-navy-900 bg-navy-900 text-white' : 'border-slate-300 bg-white text-slate-600'}`}
          onClick={() => setActiveTab(tab.id)}
        >{tab.label}</button>)}
      </div>
      {loading && <p className="muted m-0">사용자 정보를 불러오는 중입니다.</p>}
      {!loading && activeTab === 'profile' && <section className="grid gap-3" aria-label="사용자 정보">
        <dl className="summary-list">
          <div><dt>사용자명</dt><dd>{profile?.username ?? '인증 시스템 관리 대상 아님'}</dd></div>
          <div><dt>Email 검증</dt><dd>{profile ? (profile.email_verified ? '검증됨' : '미검증') : '—'}</dd></div>
          <div><dt>마지막 로그인</dt><dd>{displayTimestamp(member.last_login_at)}</dd></div>
          <div><dt>마지막 로그인 IP</dt><dd>{member.last_login_ip ?? '기록 없음'}</dd></div>
          <div><dt>접근 만료</dt><dd>{displayTimestamp(member.access_expires_at)}</dd></div>
        </dl>
        {profile ? <div className="grid gap-3 md:grid-cols-2">
          <label className="grid gap-1 text-xs font-bold">이름<input value={profileDraft.firstName} maxLength={100} onChange={(event) => setProfileDraft({ ...profileDraft, firstName: event.target.value })} /></label>
          <label className="grid gap-1 text-xs font-bold">성<input value={profileDraft.lastName} maxLength={100} onChange={(event) => setProfileDraft({ ...profileDraft, lastName: event.target.value })} /></label>
          <label className="grid gap-1 text-xs font-bold">Email<input type="email" value={profileDraft.email} maxLength={320} onChange={(event) => setProfileDraft({ ...profileDraft, email: event.target.value })} /></label>
          <label className="grid gap-1 text-xs font-bold">부서 UUID<input value={profileDraft.departmentId} placeholder="미할당" onChange={(event) => setProfileDraft({ ...profileDraft, departmentId: event.target.value })} /></label>
          <label className="grid gap-1 text-xs font-bold md:col-span-2">업무 역할<input value={profileDraft.jobFunction} maxLength={100} placeholder="미지정" onChange={(event) => setProfileDraft({ ...profileDraft, jobFunction: event.target.value })} /></label>
          <div className="action-row md:col-span-2"><button type="button" className="button" disabled={!canUpdateIdentity || !profileChanged || !profileValid} onClick={saveProfile}>사용자 정보 저장</button></div>
        </div> : <p className="callout m-0">{isServiceAccount ? '서비스 계정은 사람 사용자용 프로필·비밀번호 변경 대상에서 제외됩니다.' : '이 배포에서는 인증 프로필 편집 기능을 사용할 수 없습니다.'}</p>}
      </section>}
      {!loading && activeTab === 'access' && <section className="grid gap-3" aria-label="데이터 및 화면 접근 관리">
        <p className="callout m-0">프로필 권한은 서비스 기능을, 데이터 조회 등급은 분류된 데이터의 조회 상한을 결정합니다. 두 값은 서로 암묵적으로 변경되지 않습니다.</p>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="grid gap-1 text-xs font-bold">변경이력 역할<select aria-label="변경이력 역할" value={selectedAuthorityRole} disabled={!canUpdateAuthority} onChange={(event) => setSelectedAuthorityRole(event.target.value as typeof selectedAuthorityRole)}><option value="admin">admin</option><option value="data_steward">data_steward</option><option value="developer">developer</option><option value="manager">manager</option><option value="viewer">viewer</option></select></label>
          <label className="grid gap-1 text-xs font-bold">계정 활성 상태<select aria-label="계정 활성 상태" value={selectedActive ? 'ACTIVE' : 'INACTIVE'} disabled={!canUpdateAuthority} onChange={(event) => setSelectedActive(event.target.value === 'ACTIVE')}><option value="ACTIVE">ACTIVE</option><option value="INACTIVE">INACTIVE</option></select></label>
          <label className="grid gap-1 text-xs font-bold">사용자 프로필 권한<select aria-label="사용자 프로필 권한" value={selectedTier ?? ''} disabled={!canAssignProfile || isServiceAccount} onChange={(event) => setSelectedTier(event.target.value as ProfileRolePolicy['items'][number]['tier'])}><option value="" disabled>{access?.profile_role.status === 'UNASSIGNED' ? '전환 필요 (기존 권한)' : '선택'}</option>{profileRolePolicy?.items.map((item) => <option key={item.tier} value={item.tier}>{item.label}</option>)}</select></label>
          <label className="grid gap-1 text-xs font-bold">데이터 조회 등급<select aria-label="데이터 조회 등급" value={selectedClearance} disabled={!canAssignProfile || isServiceAccount || access?.profile_role.tier === 'ADMIN'} onChange={(event) => setSelectedClearance(event.target.value as Classification)}><option value="PUBLIC">Public</option><option value="INTERNAL">Internal</option><option value="CONFIDENTIAL">Confidential (대외비)</option><option value="RESTRICTED">Restricted</option></select></label>
        </div>
        {selectedTier && <p className="callout m-0"><strong>{profileRolePolicy?.items.find((item) => item.tier === selectedTier)?.label}</strong> · {profileRolePolicy?.items.find((item) => item.tier === selectedTier)?.description}</p>}
        <label className="grid gap-1 text-xs font-bold">변경 사유<textarea value={accessReason} maxLength={4000} onChange={(event) => setAccessReason(event.target.value)} placeholder="프로필 권한 변경 사유" /></label>
        {member.subject_id === context?.subject_id && <p className="callout m-0">관리자는 자신의 접근 Role을 변경할 수 없습니다. 다른 적격 관리자가 변경해야 합니다.</p>}
        {access?.profile_role.status === 'STALE' && <p className="notice notice-error m-0">프로필 권한 증거가 현재 멤버십과 일치하지 않아 서버가 권한을 차단했습니다. 프로필 권한을 다시 저장해 복구하세요.</p>}
        {access?.profile_role.status === 'UNASSIGNED' && <p className="callout m-0">기존 사용자는 자동 추정하지 않습니다. 명시적으로 프로필 권한을 선택하면 해당 서버 정책으로 전환됩니다.</p>}
        <div className="action-row"><button type="button" className="button button-secondary" disabled={!canUpdateAuthority || !accessReason.trim() || (selectedActive === (member.subject_active && member.membership_active) && selectedAuthorityRole === (member.change_history_role ?? 'viewer'))} onClick={saveAccessAuthority}>계정/역할 저장</button><button type="button" className="button button-secondary" disabled={!canAssignProfile || access?.access.clearance === selectedClearance} onClick={saveClearance}>데이터 조회 등급 저장</button><button type="button" className="button" disabled={!canAssignProfile || !selectedTier || !accessReason.trim() || (access?.profile_role.tier === selectedTier && access?.profile_role.status === 'VERIFIED')} onClick={saveProfileRole}>프로필 권한 저장</button></div>
      </section>}
      {!loading && activeTab === 'activity' && <section className="grid gap-4" aria-label="CR 신청 및 사용자 활동">
        <div>
          <div className="section-heading"><div><h3>CR 신청·승인 참여</h3><p className="muted">요청자 또는 승인자로 직접 연결된 최근 변경요청입니다.</p></div><span className="badge badge-soft">{member.change_request_count}건</span></div>
          <DenseDataTable caption="사용자 변경요청 활동" columns={[
            { accessorKey: 'number', header: 'CR', size: 110 },
            { accessorKey: 'title', header: '제목', size: 250 },
            { accessorKey: 'relationship', header: '관계', size: 135 },
            { accessorKey: 'state', header: '상태', size: 100 },
            { accessorKey: 'updated_at', header: '최근 변경', size: 150, cell: ({ row }) => displayTimestamp(row.original.updated_at) },
          ]} data={changeRequests} emptyMessage="직접 연결된 변경요청이 없습니다." getRowId={(item) => item.change_request_id} />
        </div>
        <div>
          <div className="section-heading"><div><h3>소유 데이터</h3><p className="muted">현재 카탈로그에서 이 사용자가 소유자로 지정된 테이블입니다.</p></div><span className="badge badge-soft">{member.owned_table_count}개</span></div>
          <DenseDataTable caption="사용자 소유 테이블" columns={[
            { accessorKey: 'name', header: '테이블', size: 220 },
            { accessorKey: 'platform', header: '플랫폼', size: 120, cell: ({ row }) => row.original.platform ?? '—' },
            { accessorKey: 'database_name', header: 'DB', size: 150, cell: ({ row }) => row.original.database_name ?? '—' },
            { accessorKey: 'classification', header: '등급', size: 120 },
            { accessorKey: 'observed_at', header: '관측 시각', size: 150, cell: ({ row }) => displayTimestamp(row.original.observed_at) },
          ]} data={ownedTables} emptyMessage="소유자로 연결된 테이블이 없습니다." getRowId={(item) => item.asset_id} />
        </div>
        <p className="muted m-0">{activityTruncated ? '각 활동은 최근 25건까지만 표시됩니다. ' : ''}상세 감사 로그가 아니라 권한이 확인된 CR 참여·소유 데이터 조회입니다.</p>
      </section>}
      {!loading && activeTab === 'security' && <section className="grid gap-3" aria-label="비밀번호 재설정">
        {profile ? <>
          <div className="notice notice-warning m-0">새 비밀번호는 임시 자격 증명으로 설정됩니다. 저장 즉시 기존 로그인 세션이 종료되고, 사용자는 다음 로그인에서 비밀번호를 바꿔야 합니다.</div>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-1 text-xs font-bold">새 임시 비밀번호<input type="password" minLength={12} maxLength={128} autoComplete="new-password" value={temporaryPassword} onChange={(event) => { setTemporaryPassword(event.target.value); setPasswordResetComplete(false) }} /></label>
            <label className="grid gap-1 text-xs font-bold">임시 비밀번호 확인<input type="password" minLength={12} maxLength={128} autoComplete="new-password" value={passwordConfirmation} onChange={(event) => { setPasswordConfirmation(event.target.value); setPasswordResetComplete(false) }} /></label>
          </div>
          {passwordConfirmation && temporaryPassword !== passwordConfirmation && <p className="notice notice-error m-0">두 임시 비밀번호가 일치하지 않습니다.</p>}
          {passwordResetComplete && <p className="notice notice-success m-0">임시 비밀번호가 설정됐고 기존 세션이 종료됐습니다.</p>}
          <div className="action-row"><button type="button" className="button" disabled={!canResetPassword || temporaryPassword.length < 12 || temporaryPassword !== passwordConfirmation} onClick={resetPassword}>임시 비밀번호 재설정</button></div>
        </> : <p className="callout m-0">{isServiceAccount ? '서비스 계정의 자격 증명은 사람 사용자용 재설정 경로에서 변경할 수 없습니다.' : '이 배포에서는 비밀번호 재설정 기능을 사용할 수 없습니다.'}</p>}
      </section>}
    </div>
  </Dialog>
}
