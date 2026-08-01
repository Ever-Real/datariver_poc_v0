import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  AdminAccessRequest,
  AdminReadContext,
  MembershipRenewalRequest,
  WorkspaceMembershipSummary,
} from '../../api/types'
import { sha256Text } from '../../api/client'
import type { AssuranceActions } from '../../components/AssuranceNotice'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import type { AdminApi } from './adminApi'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import type { AdminMessages } from './messages'
import { UserProfileDialog } from './UserProfileDialog'

export interface AdminSectionProps extends AssuranceActions {
  api: AdminApi
  context?: AdminReadContext
  messages: AdminMessages
  requestConfirmation: (mutation: PendingAdminMutation) => void
  keyFor: (intent: string, prefix: string) => string
  clearKey: (intent: string) => void
  reportError: (error: unknown) => void
}

type MembershipAccessAdminProps = AdminSectionProps & {
  onOpenRoleManagement?: () => void
  onOpenRenewals?: () => void
}

export function MembershipAccessAdmin({
  onOpenRoleManagement,
  onOpenRenewals,
  ...props
}: MembershipAccessAdminProps) {
  const { api, context, messages, requestConfirmation, keyFor, clearKey, reportError } = props
  const [members, setMembers] = useState<WorkspaceMembershipSummary[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [memberQuery, setMemberQuery] = useState('')
  const [appliedMemberQuery, setAppliedMemberQuery] = useState('')
  const [memberStatus, setMemberStatus] = useState<'ALL' | 'ACTIVE' | 'INACTIVE'>('ALL')
  const [membershipCursor, setMembershipCursor] = useState<string>()
  const [membershipCursorHistory, setMembershipCursorHistory] = useState<string[]>([])
  const [membershipPageNumber, setMembershipPageNumber] = useState(1)
  const [nextMembershipCursor, setNextMembershipCursor] = useState<string | null>(null)
  const [profileOpen, setProfileOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [createBusy, setCreateBusy] = useState(false)
  const [newUser, setNewUser] = useState({
    username: '', email: '', firstName: '', lastName: '', departmentId: '',
    jobFunction: '', temporaryPassword: '', passwordConfirmation: '',
  })
  const memberGeneration = useRef(0)
  const canRead = context?.allowed_operations.includes('MEMBERSHIP_ACCESS_READ') ?? false
  const canProvision = context?.allowed_operations.includes('IDENTITY_USER_PROVISION') ?? false
  const loadMembers = useCallback(async (signal?: AbortSignal) => {
    const generation = ++memberGeneration.current
    try {
      const page = await api.listMembershipPage({
        query: appliedMemberQuery || undefined,
        status: memberStatus === 'ALL' ? undefined : memberStatus,
        cursor: membershipCursor,
        signal,
      })
      if (signal?.aborted || generation !== memberGeneration.current) return
      setMembers(page.items)
      setNextMembershipCursor(page.nextCursor)
      setSelectedId((current) => current && page.items.some((item) => item.subject_id === current)
        ? current : page.items[0]?.subject_id ?? '')
    } catch (error) {
      if (!signal?.aborted && generation === memberGeneration.current) reportError(error)
    }
  }, [
    api, appliedMemberQuery, memberStatus, membershipCursor, reportError,
    setMembers, setNextMembershipCursor, setSelectedId,
  ])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setAppliedMemberQuery(memberQuery.trim())
      setMembershipCursor(undefined)
      setMembershipCursorHistory([])
      setMembershipPageNumber(1)
    }, 250)
    return () => window.clearTimeout(timer)
  }, [memberQuery])
  useEffect(() => {
    if (!canRead) return
    const controller = new AbortController()
    void loadMembers(controller.signal)
    return () => {
      controller.abort()
      memberGeneration.current += 1
    }
  }, [canRead, loadMembers])
  useEffect(() => {
    if (canProvision) return
    setCreateOpen(false)
    setNewUser((current) => ({ ...current, temporaryPassword: '', passwordConfirmation: '' }))
  }, [canProvision])

  const selected = members.find((member) => member.subject_id === selectedId)
  const openProfile = (member: WorkspaceMembershipSummary) => {
    setSelectedId(member.subject_id)
    setProfileOpen(true)
  }
  const closeProfile = () => {
    setProfileOpen(false)
  }
  const openCreate = () => {
    if (!canProvision) return
    setCreateOpen(true)
  }
  const closeCreate = () => {
    if (createBusy) return
    setCreateOpen(false)
    setNewUser((current) => ({
      ...current,
      temporaryPassword: '',
      passwordConfirmation: '',
    }))
  }
  const provisionUser = async () => {
    if (!canProvision || createBusy || newUser.temporaryPassword !== newUser.passwordConfirmation) return
    const payload = {
      username: newUser.username.trim(), email: newUser.email.trim(),
      first_name: newUser.firstName.trim(), last_name: newUser.lastName.trim(),
      department_id: newUser.departmentId.trim() || null,
      job_function: newUser.jobFunction.trim() || null,
      role_id: null,
      temporary_password: newUser.temporaryPassword,
    }
    setCreateBusy(true)
    try {
      const intent = `identity-user:${await sha256Text(JSON.stringify(payload))}`
      await api.provisionIdentityUser(payload, keyFor(intent, 'identity-user'))
      clearKey(intent)
      setNewUser({
        username: '', email: '', firstName: '', lastName: '', departmentId: '',
        jobFunction: '', temporaryPassword: '', passwordConfirmation: '',
      })
      setCreateOpen(false)
      await loadMembers()
    } catch (error) {
      reportError(error)
    } finally {
      setCreateBusy(false)
    }
  }
  return <>
    <section className="panel">
      <div className="section-heading"><div><h3>User 관리</h3><p className="muted">사용자를 선택해 프로필, 데이터·화면 접근 Role, CR 활동과 인증 복구를 관리합니다.</p></div><div className="action-row"><button type="button" className="button button-secondary" onClick={() => void loadMembers()}>{messages.refresh}</button>{onOpenRenewals && <button type="button" className="button button-secondary" onClick={onOpenRenewals}>계정 갱신</button>}{onOpenRoleManagement && <button type="button" className="button button-secondary" onClick={onOpenRoleManagement}>Role 관리</button>}<button type="button" className="button" disabled={!canProvision} title={canProvision ? '인증 계정과 Workspace 멤버십을 함께 생성합니다.' : '서버가 현재 세션에 사용자 등록 권한을 허용하지 않았습니다.'} onClick={openCreate}>사용자 등록</button></div></div>
      <div className="mb-3 grid gap-2 rounded-enterprise border border-slate-300 bg-slate-50 p-3 md:grid-cols-[minmax(220px,1fr)_170px_auto] md:items-end"><label className="grid gap-1 text-xs font-bold">사용자 검색<input type="search" value={memberQuery} onChange={(event) => setMemberQuery(event.target.value)} placeholder="사용자명, 이메일로 검색" /></label><label className="grid gap-1 text-xs font-bold">상태 필터<select value={memberStatus} onChange={(event) => { setMemberStatus(event.target.value as typeof memberStatus); setMembershipCursor(undefined); setMembershipCursorHistory([]); setMembershipPageNumber(1) }}><option value="ALL">전체</option><option value="ACTIVE">활성</option><option value="INACTIVE">비활성</option></select></label><button type="button" className="button button-secondary" disabled={!memberQuery && memberStatus === 'ALL'} onClick={() => { setMemberQuery(''); setAppliedMemberQuery(''); setMemberStatus('ALL'); setMembershipCursor(undefined); setMembershipCursorHistory([]); setMembershipPageNumber(1) }}>필터 초기화</button></div>
      <DenseDataTable caption="워크스페이스 사용자 목록" columns={[
        { accessorKey: 'display_name', header: '사용자', size: 170, cell: ({ row }) => <strong>{row.original.display_name}</strong> },
        { accessorKey: 'email', header: 'Email', size: 220, cell: ({ row }) => row.original.email ?? '—' },
        { accessorKey: 'job_function', header: '업무 역할', size: 120, cell: ({ row }) => row.original.job_function ?? '—' },
        { accessorKey: 'effective_profile_role', header: '프로필 권한', size: 150, cell: ({ row }) => <span className="badge badge-soft">{row.original.effective_profile_role}</span> },
        { accessorKey: 'department_id', header: '부서', size: 150, cell: ({ row }) => row.original.department_id ?? '미할당' },
        { accessorKey: 'clearance', header: '등급', size: 110, cell: ({ row }) => <span className="badge badge-soft">{row.original.clearance}</span> },
        { accessorKey: 'access_expires_at', header: '갱신 필요일', size: 125, cell: ({ row }) => row.original.access_expires_at ? <span className={row.original.access_expired ? 'font-black text-red-700' : ''}>{new Date(row.original.access_expires_at).toLocaleDateString()}</span> : '운영자 관리' },
        { accessorKey: 'membership_active', header: '멤버십', size: 92, cell: ({ row }) => row.original.membership_active ? '활성' : '비활성' },
      ]} data={members} emptyMessage={messages.empty} getRowId={(member) => member.subject_id} selectedRowId={selectedId} onRowActivate={openProfile} />
      <div className="action-row" aria-label="사용자 목록 페이지"><button type="button" className="button button-secondary" disabled={membershipCursorHistory.length === 0} onClick={() => { const previous = membershipCursorHistory.at(-1); setMembershipCursorHistory((current) => current.slice(0, -1)); setMembershipCursor(previous || undefined); setMembershipPageNumber((current) => Math.max(1, current - 1)) }}>이전 페이지</button><span className="badge badge-soft">서버 페이지 {membershipPageNumber}</span><button type="button" className="button button-secondary" disabled={!nextMembershipCursor} onClick={() => { setMembershipCursorHistory((current) => [...current.slice(-49), membershipCursor ?? '']); setMembershipCursor(nextMembershipCursor ?? undefined); setMembershipPageNumber((current) => current + 1) }}>다음 페이지</button></div>
      <p className="muted">검색과 상태 필터는 서버에서 적용되며 한 번에 최대 25명만 브라우저에 유지합니다.</p>
    </section>
    <UserProfileDialog
      open={profileOpen && Boolean(selected)}
      member={selected}
      api={api}
      context={context}
      keyFor={keyFor}
      clearKey={clearKey}
      reportError={reportError}
      requestConfirmation={requestConfirmation}
      onRequestClose={closeProfile}
      onUpdated={loadMembers}
    />
    <Dialog open={createOpen} title="사용자 등록" description="인증 계정과 현재 Workspace 멤버십을 하나의 통제된 작업으로 생성합니다." onRequestClose={closeCreate} footer={<><button type="button" className="button button-secondary" disabled={createBusy} onClick={closeCreate}>취소</button><button type="button" className="button" disabled={createBusy || !newUser.username.trim() || !newUser.email.trim() || !newUser.firstName.trim() || !newUser.lastName.trim() || newUser.temporaryPassword.length < 12 || newUser.temporaryPassword !== newUser.passwordConfirmation} onClick={() => void provisionUser()}>{createBusy ? '등록 중…' : '사용자 등록'}</button></>}>
      <div className="grid gap-3 md:grid-cols-2"><p className="callout m-0 md:col-span-2"><strong>신규 Viewer 기본</strong> · 등록 즉시 Viewer 권한과 CONFIDENTIAL 데이터 조회 등급을 서버가 함께 부여합니다.</p><label className="grid gap-1 text-xs font-bold">사용자명<input required minLength={3} maxLength={64} autoComplete="off" value={newUser.username} onChange={(event) => setNewUser({ ...newUser, username: event.target.value })} placeholder="예: hong.gildong" /></label><label className="grid gap-1 text-xs font-bold">Email<input required type="email" maxLength={320} autoComplete="off" value={newUser.email} onChange={(event) => setNewUser({ ...newUser, email: event.target.value })} /></label><label className="grid gap-1 text-xs font-bold">이름<input required maxLength={100} value={newUser.firstName} onChange={(event) => setNewUser({ ...newUser, firstName: event.target.value })} /></label><label className="grid gap-1 text-xs font-bold">성<input required maxLength={100} value={newUser.lastName} onChange={(event) => setNewUser({ ...newUser, lastName: event.target.value })} /></label><label className="grid gap-1 text-xs font-bold">부서 UUID (선택)<input value={newUser.departmentId} onChange={(event) => setNewUser({ ...newUser, departmentId: event.target.value })} /></label><label className="grid gap-1 text-xs font-bold">업무 역할 (선택)<input maxLength={100} value={newUser.jobFunction} onChange={(event) => setNewUser({ ...newUser, jobFunction: event.target.value })} /></label><label className="grid gap-1 text-xs font-bold">임시 비밀번호<input required type="password" minLength={12} maxLength={128} autoComplete="new-password" value={newUser.temporaryPassword} onChange={(event) => setNewUser({ ...newUser, temporaryPassword: event.target.value })} /></label><label className="grid gap-1 text-xs font-bold">임시 비밀번호 확인<input required type="password" minLength={12} maxLength={128} autoComplete="new-password" value={newUser.passwordConfirmation} onChange={(event) => setNewUser({ ...newUser, passwordConfirmation: event.target.value })} /></label></div>
    </Dialog>
  </>
}

export function MembershipRenewalAdmin(props: AdminSectionProps) {
  const { api, context, requestConfirmation, keyFor, clearKey, reportError } = props
  const [requests, setRequests] = useState<MembershipRenewalRequest[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [reason, setReason] = useState('')
  const [state, setState] = useState<MembershipRenewalRequest['state'] | 'ALL'>('PENDING')
  const [cursor, setCursor] = useState<string>()
  const [cursorHistory, setCursorHistory] = useState<string[]>([])
  const [pageNumber, setPageNumber] = useState(1)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const loadGeneration = useRef(0)
  const canRead = context?.allowed_operations.includes('MEMBERSHIP_RENEWAL_READ') ?? false
  const canDecide = context?.allowed_operations.includes('MEMBERSHIP_RENEWAL_DECIDE') ?? false
  const load = useCallback(async (signal?: AbortSignal) => {
    if (!canRead) return
    const generation = ++loadGeneration.current
    try {
      const page = await api.listMembershipRenewalPage({
        state: state === 'ALL' ? undefined : state,
        cursor,
        signal,
      })
      if (signal?.aborted || generation !== loadGeneration.current) return
      setRequests(page.items)
      setNextCursor(page.nextCursor)
      setSelectedId((current) => current && page.items.some((item) => item.id === current)
        ? current : page.items[0]?.id ?? '')
    } catch (error) {
      if (!signal?.aborted && generation === loadGeneration.current) reportError(error)
    }
  }, [api, canRead, cursor, reportError, state])
  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => {
      controller.abort()
      loadGeneration.current += 1
    }
  }, [load])
  const selected = requests.find((item) => item.id === selectedId)
  const decide = (decision: 'APPROVED' | 'REJECTED') => {
    if (!selected || !reason.trim() || !canDecide) return
    const intent = `membership-renewal:${selected.id}:${selected.version}:${decision}:${reason.trim()}`
    requestConfirmation({
      title: decision === 'APPROVED' ? '계정 갱신 승인' : '계정 갱신 반려',
      summary: [selected.requester_display_name, `현재 ${new Date(selected.current_expires_at).toLocaleDateString()}`, `요청 ${new Date(selected.requested_expires_at).toLocaleDateString()}`],
      execute: async () => {
        await api.decideMembershipRenewal(
          selected, decision, reason.trim(), keyFor(intent, 'membership-renewal'),
        )
        clearKey(intent); setReason(''); await load()
      },
    })
  }
  return <section className="panel grid gap-3">
    <div className="section-heading"><div><h3>계정 갱신 승인</h3><p className="muted">가입 후 6개월 만료와 30일 전 신청 창을 서버가 계산합니다. 신청자 본인은 승인할 수 없습니다.</p></div><button type="button" className="button button-secondary" onClick={() => void load()}>새로고침</button></div>
    <label className="max-w-52 text-xs font-bold">상태<select value={state} onChange={(event) => { setState(event.target.value as typeof state); setCursor(undefined); setCursorHistory([]); setPageNumber(1) }}><option value="PENDING">승인 대기</option><option value="APPROVED">승인</option><option value="REJECTED">반려</option><option value="ALL">전체</option></select></label>
    <DenseDataTable
      caption="멤버십 갱신 요청"
      columns={[
        { accessorKey: 'requester_display_name', header: '사용자', size: 160 },
        { accessorKey: 'created_at', header: '신청일', size: 150, cell: ({ row }) => new Date(row.original.created_at).toLocaleString() },
        { accessorKey: 'current_expires_at', header: '현재 만료일', size: 130, cell: ({ row }) => new Date(row.original.current_expires_at).toLocaleDateString() },
        { accessorKey: 'requested_expires_at', header: '갱신 만료일', size: 130, cell: ({ row }) => new Date(row.original.requested_expires_at).toLocaleDateString() },
        { accessorKey: 'state', header: '상태', size: 100, cell: ({ row }) => <span className="badge badge-soft">{row.original.state}</span> },
        { accessorKey: 'checker_display_name', header: '승인자', size: 140, cell: ({ row }) => row.original.checker_display_name ?? '—' },
      ]}
      data={requests}
      getRowId={(item) => item.id}
      selectedRowId={selectedId}
      onRowActivate={(item) => setSelectedId(item.id)}
      emptyMessage="해당 상태의 갱신 요청이 없습니다."
    />
    <div className="flex items-center justify-end gap-2">
      <span className="text-xs text-slate-600">페이지 {pageNumber}</span>
      <button type="button" className="button button-secondary" disabled={cursorHistory.length === 0} onClick={() => {
        const previous = cursorHistory.at(-1)
        setCursorHistory((current) => current.slice(0, -1))
        setCursor(previous || undefined)
        setPageNumber((current) => Math.max(1, current - 1))
      }}>이전</button>
      <button type="button" className="button button-secondary" disabled={!nextCursor} onClick={() => {
        if (!nextCursor) return
        setCursorHistory((current) => [...current.slice(-49), cursor ?? ''])
        setCursor(nextCursor)
        setPageNumber((current) => current + 1)
      }}>다음</button>
    </div>
    {selected && <div className="grid gap-2 rounded-enterprise border border-slate-300 bg-slate-50 p-3">
      <p className="m-0 whitespace-pre-wrap text-xs"><strong>신청 사유</strong><br />{selected.reason}</p>
      {selected.state === 'PENDING' && <><label className="text-xs font-bold">승인·반려 사유<textarea className="mt-1 min-h-20" maxLength={4000} value={reason} onChange={(event) => setReason(event.target.value)} /></label><div className="flex justify-end gap-2">{canDecide ? <><button type="button" className="button button-danger" disabled={!reason.trim()} onClick={() => decide('REJECTED')}>반려</button><button type="button" className="button" disabled={!reason.trim()} onClick={() => decide('APPROVED')}>6개월 갱신 승인</button></> : <button type="button" className="button button-secondary" onClick={() => void props.onStepUp()}>WebAuthn 재인증</button>}</div></>}
    </div>}
  </section>
}

export function FallbackQueueAdmin(props: AdminSectionProps) {
  const { api, context, messages, requestConfirmation, keyFor, clearKey, reportError } = props
  const [requests, setRequests] = useState<AdminAccessRequest[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [reason, setReason] = useState('')
  const [cursor, setCursor] = useState<string>()
  const [cursorHistory, setCursorHistory] = useState<string[]>([])
  const [pageNumber, setPageNumber] = useState(1)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const loadGeneration = useRef(0)

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!context?.fallback_enabled || !context.allowed_operations.includes('FALLBACK_REQUEST_READ')) return
    const generation = ++loadGeneration.current
    try {
      const page = await api.listFallbackRequestPage({ cursor, signal })
      if (signal?.aborted || generation !== loadGeneration.current) return
      setRequests(page.items)
      setNextCursor(page.nextCursor)
      setSelectedId((current) => current && page.items.some((item) => item.id === current)
        ? current : page.items[0]?.id || '')
    } catch (error) {
      if (!signal?.aborted && generation === loadGeneration.current) reportError(error)
    }
  }, [api, context, cursor, reportError])
  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => {
      controller.abort()
      loadGeneration.current += 1
    }
  }, [load])

  if (!context?.fallback_enabled) return <div className="callout">{messages.fallbackDisabled}</div>
  const selected = requests.find((request) => request.id === selectedId)
  const decide = (decision: 'APPROVED' | 'REJECTED') => {
    if (!selected || !reason.trim()) return
    const intent = `fallback-decision:${selected.id}:${selected.version}:${decision}:${reason}`
    requestConfirmation({
      title: `${messages.releaseDecision}: ${decision}`,
      summary: [selected.id, `v${selected.version}`, selected.payload_hash],
      execute: async () => {
        await api.decideFallbackRequest(selected, decision, reason.trim(), keyFor(intent, 'admin-fallback-decision'))
        clearKey(intent); setReason('')
        await load()
      },
    })
  }
  const consume = () => {
    if (!selected) return
    const intent = `fallback-consume:${selected.id}:${selected.version}:${selected.payload_hash}`
    requestConfirmation({
      title: messages.consume,
      summary: [selected.command.target_subject_id, selected.payload_hash, `v${selected.version}`],
      execute: async () => {
        await api.consumeFallbackRequest(selected, keyFor(intent, 'admin-fallback-consume'))
        clearKey(intent)
        await load()
      },
    })
  }
  const actor = context.subject_id
  const canDecide = selected?.state === 'PENDING'
    && actor !== selected.requester_id && actor !== selected.command.target_subject_id
    && context.allowed_operations.includes('FALLBACK_REQUEST_DECIDE')
  const canConsume = selected?.state === 'APPROVED' && actor === selected.requester_id
    && context.allowed_operations.includes('FALLBACK_REQUEST_CONSUME')

  return <div className="admin-two-column">
    <section className="panel"><div className="section-heading"><h3>{messages.recentRequests}</h3><button className="button button-secondary" onClick={() => void load()}>{messages.refresh}</button></div>
      <div className="compact-list">{requests.map((request) => <button key={request.id} className={selectedId === request.id ? 'selected' : ''} onClick={() => setSelectedId(request.id)}><span><strong>{request.command.target_subject_id}</strong><small>{new Date(request.expires_at).toLocaleString()}</small></span><span className="badge">{request.state}</span></button>)}</div>
      <div className="mt-3 flex items-center justify-end gap-2">
        <span className="text-xs text-slate-600">페이지 {pageNumber}</span>
        <button type="button" className="button button-secondary" disabled={cursorHistory.length === 0} onClick={() => {
          const previous = cursorHistory.at(-1)
          setCursorHistory((current) => current.slice(0, -1))
          setCursor(previous || undefined)
          setPageNumber((current) => Math.max(1, current - 1))
        }}>이전</button>
        <button type="button" className="button button-secondary" disabled={!nextCursor} onClick={() => {
          if (!nextCursor) return
          setCursorHistory((current) => [...current.slice(-49), cursor ?? ''])
          setCursor(nextCursor)
          setPageNumber((current) => current + 1)
        }}>다음</button>
      </div>
    </section>
    <section className="panel form-stack">{selected ? <>
      <h3>{selected.state} · v{selected.version}</h3>
      <dl className="summary-list"><div><dt>maker</dt><dd>{selected.requester_id}</dd></div><div><dt>target</dt><dd>{selected.command.target_subject_id}</dd></div><div><dt>{messages.expiresAt}</dt><dd>{new Date(selected.expires_at).toLocaleString()}</dd></div><div><dt>{messages.payloadHash}</dt><dd>{selected.payload_hash}</dd></div></dl>
      <p>{selected.request_reason}</p><label>{messages.reason}<textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={4000} /></label>
      <div className="action-row">
        {canDecide && <><button className="button" disabled={!reason.trim()} onClick={() => decide('APPROVED')}>{messages.approve}</button><button className="button button-secondary" disabled={!reason.trim()} onClick={() => decide('REJECTED')}>{messages.reject}</button></>}
        {canConsume && <button className="button" onClick={consume}>{messages.consume}</button>}
        {selected.state === 'APPROVED' && actor === selected.requester_id && !canConsume && <button className="button button-secondary" onClick={() => void props.onPasswordReauth()}>{messages.passwordReauth}</button>}
      </div>
      {selected.state === 'PENDING' && !canDecide && <p className="callout">{messages.makerCannotCheck}</p>}
    </> : <p className="muted">{messages.empty}</p>}</section>
  </div>
}
