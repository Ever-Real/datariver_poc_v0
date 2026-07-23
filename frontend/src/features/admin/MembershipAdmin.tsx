import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  AccessRole,
  AdminAccessRequest,
  AdminReadContext,
  MembershipAccessDocument,
  MembershipRoleAssignmentEvidence,
  MembershipRenewalRequest,
  WorkspaceMembershipSummary,
} from '../../api/types'
import { sha256Text } from '../../api/client'
import type { AssuranceActions } from '../../components/AssuranceNotice'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import { GovernedUnavailable } from '../../components/common/GovernedUnavailable'
import { useRovingTabs } from '../../components/common/useRovingTabs'
import type { AdminApi } from './adminApi'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import type { AdminMessages } from './messages'

export interface AdminSectionProps extends AssuranceActions {
  api: AdminApi
  context?: AdminReadContext
  messages: AdminMessages
  requestConfirmation: (mutation: PendingAdminMutation) => void
  keyFor: (intent: string, prefix: string) => string
  clearKey: (intent: string) => void
  reportError: (error: unknown) => void
}

function lines(value: string): string[] {
  return [...new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean))]
}

function text(values: string[]): string {
  return values.join('\n')
}

const memberDetailTabs = ['CR', 'TABLES'] as const

export function MembershipAccessAdmin(props: AdminSectionProps) {
  const { api, context, messages, requestConfirmation, keyFor, clearKey, reportError } = props
  const [members, setMembers] = useState<WorkspaceMembershipSummary[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [etag, setEtag] = useState('')
  const [version, setVersion] = useState(0)
  const [loadedSubjectId, setLoadedSubjectId] = useState('')
  const [access, setAccess] = useState<MembershipAccessDocument>()
  const [roleAssignment, setRoleAssignment] = useState<MembershipRoleAssignmentEvidence>()
  const [groups, setGroups] = useState('')
  const [systems, setSystems] = useState('')
  const [domains, setDomains] = useState('')
  const [reason, setReason] = useState('')
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailTab, setDetailTab] = useState<'CR' | 'TABLES'>('CR')
  const [memberQuery, setMemberQuery] = useState('')
  const [appliedMemberQuery, setAppliedMemberQuery] = useState('')
  const [memberStatus, setMemberStatus] = useState<'ALL' | 'ACTIVE' | 'INACTIVE'>('ALL')
  const [membershipCursor, setMembershipCursor] = useState<string>()
  const [membershipCursorHistory, setMembershipCursorHistory] = useState<string[]>([])
  const [membershipPageNumber, setMembershipPageNumber] = useState(1)
  const [nextMembershipCursor, setNextMembershipCursor] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [createBusy, setCreateBusy] = useState(false)
  const [roles, setRoles] = useState<AccessRole[]>([])
  const [provisionRoleQuery, setProvisionRoleQuery] = useState('')
  const [provisionRoleTruncated, setProvisionRoleTruncated] = useState(false)
  const [newUser, setNewUser] = useState({
    username: '', email: '', firstName: '', lastName: '', departmentId: '',
    jobFunction: '', roleId: '', temporaryPassword: '', passwordConfirmation: '',
  })
  const detailTabs = useRovingTabs({
    ids: memberDetailTabs,
    activeId: detailTab,
    idPrefix: 'admin-member-detail',
    onSelect: setDetailTab,
  })
  const memberGeneration = useRef(0)
  const accessGeneration = useRef(0)
  const provisionRoleGeneration = useRef(0)

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
      setSelectedId((current) => (
        current && page.items.some((item) => item.subject_id === current)
          ? current
          : page.items[0]?.subject_id || ''
      ))
    } catch (error) {
      if (!signal?.aborted && generation === memberGeneration.current) reportError(error)
    }
  }, [api, appliedMemberQuery, memberStatus, membershipCursor, reportError])

  const loadAccess = useCallback(async (subjectId: string, signal?: AbortSignal) => {
    if (!subjectId) return
    const generation = ++accessGeneration.current
    try {
      const next = await api.getMembershipAccess(subjectId, signal)
      if (signal?.aborted || generation !== accessGeneration.current) return
      setLoadedSubjectId(subjectId)
      setEtag(next.etag)
      setVersion(next.membership_version)
      setAccess(next.access)
      setRoleAssignment(next.role_assignment)
      setGroups(text(next.access.groups))
      setSystems(text(next.access.allowed_system_ids))
      setDomains(text(next.access.allowed_domain_ids))
    } catch (error) {
      if (!signal?.aborted && generation === accessGeneration.current) reportError(error)
    }
  }, [api, reportError])

  const canRead = context?.allowed_operations.includes('MEMBERSHIP_ACCESS_READ') ?? false
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
    const controller = new AbortController()
    setLoadedSubjectId('')
    setAccess(undefined)
    setRoleAssignment(undefined)
    setEtag('')
    setVersion(0)
    setGroups('')
    setSystems('')
    setDomains('')
    if (selectedId) void loadAccess(selectedId, controller.signal)
    return () => {
      controller.abort()
      accessGeneration.current += 1
    }
  }, [loadAccess, selectedId])

  const loadedForSelection = loadedSubjectId === selectedId
  const manualAccessLocked = !loadedForSelection || roleAssignment?.status !== 'MANUAL'
  const document = (): MembershipAccessDocument | undefined => (
    access && loadedForSelection && !manualAccessLocked
  ) ? ({
    ...access,
    groups: lines(groups),
    allowed_system_ids: lines(systems),
    allowed_domain_ids: lines(domains),
  }) : undefined

  const setAction = (action: string, effect: 'NONE' | 'ALLOW' | 'DENY') => {
    setAccess((current) => current && ({
      ...current,
      allowed_actions: effect === 'ALLOW'
        ? [...new Set([...current.allowed_actions, action])]
        : current.allowed_actions.filter((value) => value !== action),
      denied_actions: effect === 'DENY'
        ? [...new Set([...current.denied_actions, action])]
        : current.denied_actions.filter((value) => value !== action),
    }))
  }

  const directUpdate = () => {
    const next = document()
    if (!next) return
    const targetSubjectId = loadedSubjectId
    const intent = `membership-direct:${targetSubjectId}:${etag}:${JSON.stringify(next)}`
    requestConfirmation({
      title: messages.directUpdate,
      summary: [`${targetSubjectId}`, `ETag ${etag}`, `${messages.clearance}: ${next.clearance}`],
      execute: async () => {
        if (targetSubjectId !== selectedId) return
        await api.updateMembership(
          targetSubjectId, next, etag, keyFor(intent, 'admin-direct'),
        )
        clearKey(intent)
        await Promise.all([loadMembers(), loadAccess(targetSubjectId)])
      },
    })
  }

  const createFallback = () => {
    const next = document()
    if (!next || !reason.trim()) return
    const targetSubjectId = loadedSubjectId
    const intent = `membership-fallback:${targetSubjectId}:${etag}:${reason}:${JSON.stringify(next)}`
    requestConfirmation({
      title: messages.fallbackRequest,
      summary: [`${targetSubjectId}`, `ETag ${etag}`, reason],
      execute: async () => {
        if (targetSubjectId !== selectedId) return
        await api.createFallbackRequest(
          targetSubjectId, reason.trim(), next, etag,
          keyFor(intent, 'admin-fallback-create'),
        )
        clearKey(intent)
        setReason('')
      },
    })
  }

  const canDirect = context?.allowed_operations.includes('MEMBERSHIP_ACCESS_UPDATE') ?? false
  const canFallback = context?.allowed_operations.includes('FALLBACK_REQUEST_CREATE') ?? false
  const canProvision = context?.allowed_operations.includes('IDENTITY_USER_PROVISION') ?? false
  const loadProvisionRoles = useCallback(async (signal?: AbortSignal) => {
    const generation = ++provisionRoleGeneration.current
    try {
      const page = await api.listAccessRolePage({
        query: provisionRoleQuery.trim() || undefined,
        status: 'ACTIVE',
        limit: 25,
        signal,
      })
      if (signal?.aborted || generation !== provisionRoleGeneration.current) return
      setRoles(page.items)
      setProvisionRoleTruncated(Boolean(page.nextCursor))
    } catch (error) {
      if (!signal?.aborted && generation === provisionRoleGeneration.current) {
        reportError(error)
      }
    }
  }, [api, provisionRoleQuery, reportError])
  useEffect(() => {
    if (canProvision) return
    setCreateOpen(false)
    setNewUser((value) => ({
      ...value,
      temporaryPassword: '',
      passwordConfirmation: '',
    }))
  }, [canProvision])
  useEffect(() => {
    if (!createOpen || !canProvision) return
    const controller = new AbortController()
    const timer = window.setTimeout(
      () => void loadProvisionRoles(controller.signal),
      provisionRoleQuery ? 250 : 0,
    )
    return () => {
      window.clearTimeout(timer)
      controller.abort()
      provisionRoleGeneration.current += 1
    }
  }, [canProvision, createOpen, loadProvisionRoles, provisionRoleQuery])
  const openCreate = () => {
    if (!canProvision) {
      if (context?.authentication_assurance !== 'HARDWARE_WEBAUTHN') void props.onStepUp()
      return
    }
    setRoles([])
    setProvisionRoleQuery('')
    setProvisionRoleTruncated(false)
    setCreateOpen(true)
  }
  const closeCreate = () => {
    if (createBusy) return
    setCreateOpen(false)
    setRoles([])
    setProvisionRoleQuery('')
    setProvisionRoleTruncated(false)
    setNewUser((value) => ({
      ...value,
      roleId: '',
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
      role_id: newUser.roleId || null,
      temporary_password: newUser.temporaryPassword,
    }
    setCreateBusy(true)
    try {
      const intent = `identity-user:${await sha256Text(JSON.stringify(payload))}`
      await api.provisionIdentityUser(payload, keyFor(intent, 'identity-user'))
      clearKey(intent)
      setNewUser({ username: '', email: '', firstName: '', lastName: '', departmentId: '', jobFunction: '', roleId: '', temporaryPassword: '', passwordConfirmation: '' })
      setCreateOpen(false)
      setRoles([])
      setProvisionRoleQuery('')
      setProvisionRoleTruncated(false)
      await loadMembers()
    } catch (error) { reportError(error) } finally { setCreateBusy(false) }
  }
  const selected = members.find((member) => member.subject_id === selectedId)
  return (<>
    <div className="admin-two-column admin-membership-workspace">
      <section className="panel">
        <div className="section-heading"><div><h3>User 관리</h3><p className="muted">인증된 사용자와 현재 Workspace 멤버십, 소유 테이블 및 CR 이력을 표시합니다.</p></div><div className="action-row"><button className="button button-secondary" disabled={context?.authentication_assurance === 'HARDWARE_WEBAUTHN' && !canProvision} title={canProvision ? '인증 계정과 Workspace 멤버십을 함께 생성합니다.' : context?.authentication_assurance === 'HARDWARE_WEBAUTHN' ? '이 배포에서는 계정 생성 연계가 비활성화되어 있습니다.' : '최근 WebAuthn 인증 후 계정을 생성할 수 있습니다.'} onClick={() => void openCreate()}>{canProvision ? '신규 사용자 등록' : context?.authentication_assurance === 'HARDWARE_WEBAUTHN' ? '신규 사용자 등록' : 'WebAuthn 후 사용자 등록'}</button><button className="button button-secondary" onClick={() => void loadMembers()}>{messages.refresh}</button></div></div>
        <div className="mb-3 grid gap-2 rounded-enterprise border border-slate-300 bg-slate-50 p-3 md:grid-cols-[minmax(220px,1fr)_170px_auto] md:items-end">
          <label className="grid gap-1 text-xs font-bold">사용자 검색<input type="search" value={memberQuery} onChange={(event) => setMemberQuery(event.target.value)} placeholder="사용자명, 이메일로 검색" /></label>
          <label className="grid gap-1 text-xs font-bold">상태 필터<select value={memberStatus} onChange={(event) => { setMemberStatus(event.target.value as typeof memberStatus); setMembershipCursor(undefined); setMembershipCursorHistory([]); setMembershipPageNumber(1) }}><option value="ALL">전체</option><option value="ACTIVE">활성</option><option value="INACTIVE">비활성</option></select></label>
          <button type="button" className="button button-secondary" disabled={!memberQuery && memberStatus === 'ALL'} onClick={() => { setMemberQuery(''); setAppliedMemberQuery(''); setMemberStatus('ALL'); setMembershipCursor(undefined); setMembershipCursorHistory([]); setMembershipPageNumber(1) }}>필터 초기화</button>
        </div>
        <DenseDataTable
          caption="워크스페이스 사용자 목록"
          columns={[
            { accessorKey: 'display_name', header: '사용자', size: 150, cell: ({ row }) => <strong>{row.original.display_name}</strong> },
            { accessorKey: 'email', header: 'Email', size: 210, cell: ({ row }) => row.original.email ?? '—' },
            { accessorKey: 'job_function', header: '역할', size: 110, cell: ({ row }) => row.original.job_function ?? '—' },
            { accessorKey: 'department_id', header: '부서', size: 160, cell: ({ row }) => row.original.department_id ?? '미할당' },
            { accessorKey: 'clearance', header: '등급', size: 110, cell: ({ row }) => <span className="badge badge-soft">{row.original.clearance}</span> },
            { accessorKey: 'owned_table_count', header: 'Owner 테이블', size: 105, cell: ({ row }) => row.original.owned_table_count },
            { accessorKey: 'change_request_count', header: 'CR 이력', size: 82, cell: ({ row }) => <span className="badge badge-soft">{row.original.change_request_count}</span> },
            { accessorKey: 'joined_at', header: '등록일', size: 120, cell: ({ row }) => row.original.joined_at ? new Date(row.original.joined_at).toLocaleDateString() : '—' },
            { accessorKey: 'access_expires_at', header: '갱신 필요일', size: 125, cell: ({ row }) => row.original.access_expires_at ? <span className={row.original.access_expired ? 'font-black text-red-700' : ''}>{new Date(row.original.access_expires_at).toLocaleDateString()}</span> : '운영자 관리' },
            { accessorKey: 'pending_renewal_request_id', header: '갱신 신청', size: 95, cell: ({ row }) => row.original.pending_renewal_request_id ? <span className="badge badge-soft">PENDING</span> : '—' },
            { accessorKey: 'last_login_at', header: '최근 접속', size: 165, cell: ({ row }) => row.original.last_login_at ? <span title={row.original.last_login_ip ?? undefined}>{new Date(row.original.last_login_at).toLocaleString()}</span> : '—' },
            { accessorKey: 'membership_active', header: '멤버십', size: 92, cell: ({ row }) => row.original.membership_active ? '활성' : '비활성' },
            { accessorKey: 'membership_version', header: '버전', size: 72, cell: ({ row }) => `v${row.original.membership_version}` },
          ]}
          data={members}
          emptyMessage={messages.empty}
          getRowId={(member) => member.subject_id}
          selectedRowId={selectedId}
          onRowActivate={(member) => { setSelectedId(member.subject_id); setDetailOpen(true); setDetailTab('CR') }}
        />
        <div className="action-row" aria-label="사용자 목록 페이지">
          <button type="button" className="button button-secondary" disabled={membershipCursorHistory.length === 0} onClick={() => { const previous = membershipCursorHistory.at(-1); setMembershipCursorHistory((current) => current.slice(0, -1)); setMembershipCursor(previous || undefined); setMembershipPageNumber((current) => Math.max(1, current - 1)) }}>이전 페이지</button>
          <span className="badge badge-soft">서버 페이지 {membershipPageNumber}</span>
          <button type="button" className="button button-secondary" disabled={!nextMembershipCursor} onClick={() => { setMembershipCursorHistory((current) => [...current.slice(-49), membershipCursor ?? '']); setMembershipCursor(nextMembershipCursor ?? undefined); setMembershipPageNumber((current) => current + 1) }}>다음 페이지</button>
        </div>
        <p className="muted">검색과 상태 필터는 서버에서 적용되며 한 번에 최대 25명만 브라우저에 유지합니다.</p>
        <p className="callout">계정 생성 연계가 활성화된 환경에서는 보안 관리자가 인증 계정과 Workspace 멤버십을 함께 생성할 수 있습니다. 임시 비밀번호는 인증 시스템으로만 전달되며 DataRiver DB·감사 로그에는 저장되지 않습니다.</p>
      </section>
      <section className="panel form-stack" aria-live="polite">
        <h3>{messages.accessDocument}</h3>
        {!access || !selected || !loadedForSelection ? <p className="muted">{messages.selectMember}</p> : <>
          <dl className="summary-list">
            <div><dt>subject_id</dt><dd>{selected.subject_id}</dd></div>
            <div><dt>display</dt><dd>{selected.display_name}</dd></div>
            <div><dt>version</dt><dd>{version} · {etag}</dd></div>
            <div><dt>subject</dt><dd>{selected.subject_active ? messages.active : messages.disabled}</dd></div>
            <div><dt>권한 증거</dt><dd>{roleAssignment?.status ?? 'UNKNOWN'}</dd></div>
          </dl>
          {manualAccessLocked && <p className="notice notice-error" role="note">{roleAssignment?.status === 'VERIFIED' ? '이 사용자는 서버 관리 Role에 연결되어 있습니다. 수동 권한을 편집하려면 Role 관리에서 먼저 Role을 해제하세요.' : 'Role 증거가 정규화되지 않았거나 현재 access 문서와 일치하지 않습니다. Role 관리에서 증거를 복구하기 전에는 수동 권한을 변경할 수 없습니다.'}</p>}
          <fieldset className="contents" disabled={manualAccessLocked}>
          <label className="checkbox-line"><input type="checkbox" checked={access.active} onChange={(event) => setAccess({ ...access, active: event.target.checked })} />{messages.active}</label>
          <label>{messages.clearance}<select value={access.clearance} onChange={(event) => setAccess({ ...access, clearance: event.target.value as MembershipAccessDocument['clearance'] })}><option>PUBLIC</option><option>INTERNAL</option><option>CONFIDENTIAL</option><option>RESTRICTED</option></select></label>
          <details className="rounded-enterprise border border-slate-300 bg-slate-50 p-3">
            <summary className="cursor-pointer text-xs font-black text-navy-900">고급 권한 항목 펼치기</summary>
            <div className="mt-3 grid gap-3">
              <p className="callout m-0">대부분의 사용자는 옆의 간편 Role을 사용하세요. 아래 값은 서버의 전체 ABAC 문서를 직접 조정해야 하는 예외 상황을 위한 고급 항목입니다.</p>
              <label>{messages.groups}<textarea value={groups} onChange={(event) => setGroups(event.target.value)} maxLength={10_000} /></label>
              <fieldset className="action-matrix"><legend>{messages.allowedActions} / {messages.deniedActions}</legend>
                {context?.action_vocabulary.map((action) => {
                  const effect = access.allowed_actions.includes(action) ? 'ALLOW' : access.denied_actions.includes(action) ? 'DENY' : 'NONE'
                  return <label key={action}><span>{action}</span><select aria-label={action} value={effect} onChange={(event) => setAction(action, event.target.value as 'NONE' | 'ALLOW' | 'DENY')}><option value="NONE">—</option><option value="ALLOW">ALLOW</option><option value="DENY">DENY</option></select></label>
                })}
              </fieldset>
              <label>{messages.systemScopes}<textarea value={systems} onChange={(event) => setSystems(event.target.value)} /></label>
              <label>{messages.domainScopes}<textarea value={domains} onChange={(event) => setDomains(event.target.value)} /></label>
            </div>
          </details>
          <label>{messages.reason}<textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={4000} /></label>
          <div className="action-row">
            {canDirect ? <button className="button" disabled={manualAccessLocked} onClick={directUpdate}>{messages.directUpdate}</button> : <button className="button button-secondary" disabled={manualAccessLocked} onClick={() => void props.onStepUp()}>{messages.hardwareAuth}</button>}
            {context?.fallback_enabled
              ? canFallback
                ? <button className="button button-secondary" disabled={manualAccessLocked || !reason.trim()} onClick={createFallback}>{messages.fallbackRequest}</button>
                : <button className="button button-secondary" disabled={manualAccessLocked} onClick={() => void props.onPasswordReauth()}>{messages.passwordReauth}</button>
              : null}
          </div>
          {!context?.fallback_enabled && <p className="callout">{messages.fallbackDisabled}</p>}
          </fieldset>
        </>}
      </section>
    </div>
    <Dialog open={detailOpen && Boolean(selected)} size="large" title={selected ? `${selected.display_name} · ${selected.email ?? 'Email 미제공'}` : '사용자 상세'} description="서버가 제공한 Workspace 멤버십 요약입니다." onRequestClose={() => setDetailOpen(false)} footer={<><button type="button" className="button button-secondary" onClick={() => setDetailOpen(false)}>닫기</button><button type="button" className="button" disabled title="IdP와 DataRiver 프로필의 정본·동기화 계약이 아직 정의되지 않았습니다.">Profile 편집 API 미구현</button></>}>
      {selected && <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="grid content-start gap-3 rounded-enterprise border border-slate-300 bg-slate-50 p-4">
          <dl className="grid gap-2 text-xs"><div><dt className="text-[10px] font-black text-slate-500">이름 · Email</dt><dd className="m-0">{selected.display_name}<br />{selected.email ?? '—'}</dd></div><div><dt className="text-[10px] font-black text-slate-500">권한</dt><dd className="m-0">{selected.job_function ?? '미지정'} · {selected.clearance}</dd></div><div><dt className="text-[10px] font-black text-slate-500">상태</dt><dd className="m-0">{selected.membership_active ? 'ACTIVE' : 'INACTIVE'}</dd></div></dl>
          <section className="border-t border-slate-300 pt-3"><h3 className="m-0 text-xs font-black text-navy-900">Assigned Systems</h3>{!loadedForSelection ? <p className="mb-0 text-xs text-slate-500">권한 정보를 불러오는 중입니다.</p> : access?.allowed_system_ids.length ? <ul className="mb-0 pl-5 text-xs">{access.allowed_system_ids.map((id) => <li key={id}><code>{id}</code></li>)}</ul> : <p className="mb-0 text-xs text-slate-500">할당된 시스템 범위가 없습니다.</p>}</section>
          <section className="border-t border-slate-300 pt-3"><h3 className="m-0 text-xs font-black text-navy-900">Account Stats</h3><dl className="mt-2 grid gap-2 text-xs"><div><dt>CR Participated</dt><dd className="m-0 text-lg font-black">{selected.change_request_count}</dd></div><div><dt>Entities Owned</dt><dd className="m-0 text-lg font-black">{selected.owned_table_count}</dd></div><div><dt>Joined Date</dt><dd className="m-0">{selected.joined_at ? new Date(selected.joined_at).toLocaleDateString() : '—'}</dd></div></dl></section>
        </aside>
        <main className="grid content-start gap-3"><div className="flex gap-2 border-b border-slate-300 pb-2" role="tablist" aria-label="사용자 활동 상세"><button {...detailTabs.tabProps('CR')} type="button" className={`button ${detailTab === 'CR' ? '' : 'button-secondary'}`} onClick={() => setDetailTab('CR')}>CR History</button><button {...detailTabs.tabProps('TABLES')} type="button" className={`button ${detailTab === 'TABLES' ? '' : 'button-secondary'}`} onClick={() => setDetailTab('TABLES')}>Owned Tables</button></div>{detailTab === 'CR' ? <div {...detailTabs.panelProps('CR')}><GovernedUnavailable title="사용자별 CR 상세 목록 API 미구현" description={`서버는 참여 건수 ${selected.change_request_count}건만 제공합니다. CR 번호·역할·상태가 포함된 권한 필터 목록 API 없이 항목을 추정하지 않습니다.`} /></div> : <div {...detailTabs.panelProps('TABLES')}><GovernedUnavailable title="사용자별 소유 테이블 목록 API 미구현" description={`서버는 소유 건수 ${selected.owned_table_count}건만 제공합니다. 자산 상세 목록은 전용 권한 필터 API가 추가된 뒤 표시합니다.`} /></div>}</main>
      </div>}
    </Dialog>
    <Dialog open={createOpen} title="신규 사용자 등록" description="인증 계정과 현재 Workspace 멤버십을 하나의 통제된 작업으로 생성합니다." onRequestClose={closeCreate} footer={<><button type="button" className="button button-secondary" disabled={createBusy} onClick={closeCreate}>취소</button><button type="button" className="button" disabled={createBusy || !newUser.username.trim() || !newUser.email.trim() || !newUser.firstName.trim() || !newUser.lastName.trim() || newUser.temporaryPassword.length < 12 || newUser.temporaryPassword !== newUser.passwordConfirmation} onClick={() => void provisionUser()}>{createBusy ? '등록 중…' : '계정 생성'}</button></>}>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="grid gap-1 text-xs font-bold">사용자명<input required minLength={3} maxLength={64} autoComplete="off" value={newUser.username} onChange={(event) => setNewUser({ ...newUser, username: event.target.value })} placeholder="예: hong.gildong" /></label>
        <label className="grid gap-1 text-xs font-bold">Email<input required type="email" maxLength={320} autoComplete="off" value={newUser.email} onChange={(event) => setNewUser({ ...newUser, email: event.target.value })} /></label>
        <label className="grid gap-1 text-xs font-bold">이름<input required maxLength={100} value={newUser.firstName} onChange={(event) => setNewUser({ ...newUser, firstName: event.target.value })} /></label>
        <label className="grid gap-1 text-xs font-bold">성<input required maxLength={100} value={newUser.lastName} onChange={(event) => setNewUser({ ...newUser, lastName: event.target.value })} /></label>
        <label className="grid gap-1 text-xs font-bold">부서 ID (선택)<input value={newUser.departmentId} onChange={(event) => setNewUser({ ...newUser, departmentId: event.target.value })} placeholder="UUID" /></label>
        <label className="grid gap-1 text-xs font-bold">업무 역할 (선택)<input maxLength={100} value={newUser.jobFunction} onChange={(event) => setNewUser({ ...newUser, jobFunction: event.target.value })} placeholder="예: DATA_ANALYST" /></label>
        <label className="grid gap-1 text-xs font-bold md:col-span-2">Role 검색<input type="search" value={provisionRoleQuery} onChange={(event) => setProvisionRoleQuery(event.target.value)} placeholder="활성 Role 이름 또는 Key" /></label>
        <label className="grid gap-1 text-xs font-bold md:col-span-2">간편 Role<select value={newUser.roleId} onChange={(event) => setNewUser({ ...newUser, roleId: event.target.value })}><option value="">Role 미할당 · 최소 권한</option>{newUser.roleId && !roles.some((role) => role.id === newUser.roleId) && <option value={newUser.roleId}>현재 선택 · {newUser.roleId}</option>}{roles.map((role) => <option key={role.id} value={role.id}>{role.name} · {role.clearance}</option>)}</select></label>
        <p className="muted m-0 md:col-span-2">활성 Role 검색 결과를 서버에서 최대 25개만 가져옵니다.{provisionRoleTruncated ? ' 결과가 더 있으므로 검색어를 구체화하세요.' : ''}</p>
        <label className="grid gap-1 text-xs font-bold">임시 비밀번호<input required type="password" minLength={12} maxLength={128} autoComplete="new-password" value={newUser.temporaryPassword} onChange={(event) => setNewUser({ ...newUser, temporaryPassword: event.target.value })} /></label>
        <label className="grid gap-1 text-xs font-bold">임시 비밀번호 확인<input required type="password" minLength={12} maxLength={128} autoComplete="new-password" value={newUser.passwordConfirmation} onChange={(event) => setNewUser({ ...newUser, passwordConfirmation: event.target.value })} /></label>
        {newUser.passwordConfirmation && newUser.temporaryPassword !== newUser.passwordConfirmation && <p className="m-0 text-xs font-bold text-red-700 md:col-span-2">임시 비밀번호가 일치하지 않습니다.</p>}
        <p className="callout m-0 md:col-span-2">사용자는 첫 로그인에서 임시 비밀번호를 반드시 변경합니다. 임시 비밀번호는 승인된 보안 채널로만 전달하세요.</p>
      </div>
    </Dialog>
  </>)
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
