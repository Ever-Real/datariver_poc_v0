import { useCallback, useEffect, useMemo, useState } from 'react'
import type {
  AdminAccessRequest,
  AdminReadContext,
  MembershipAccessDocument,
  MembershipRenewalRequest,
  WorkspaceMembershipSummary,
} from '../../api/types'
import type { AssuranceActions } from '../../components/AssuranceNotice'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import { GovernedUnavailable } from '../../components/common/GovernedUnavailable'
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

export function MembershipAccessAdmin(props: AdminSectionProps) {
  const { api, context, messages, requestConfirmation, keyFor, clearKey, reportError } = props
  const [members, setMembers] = useState<WorkspaceMembershipSummary[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [etag, setEtag] = useState('')
  const [version, setVersion] = useState(0)
  const [access, setAccess] = useState<MembershipAccessDocument>()
  const [groups, setGroups] = useState('')
  const [systems, setSystems] = useState('')
  const [domains, setDomains] = useState('')
  const [reason, setReason] = useState('')
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailTab, setDetailTab] = useState<'CR' | 'TABLES'>('CR')
  const [memberQuery, setMemberQuery] = useState('')
  const [memberStatus, setMemberStatus] = useState<'ALL' | 'ACTIVE' | 'INACTIVE'>('ALL')

  const loadMembers = useCallback(async () => {
    try {
      const next = await api.listMemberships()
      setMembers(next)
      setSelectedId((current) => current || next[0]?.subject_id || '')
    } catch (error) { reportError(error) }
  }, [api, reportError])

  const loadAccess = useCallback(async (subjectId: string) => {
    if (!subjectId) return
    try {
      const next = await api.getMembershipAccess(subjectId)
      setEtag(next.etag)
      setVersion(next.membership_version)
      setAccess(next.access)
      setGroups(text(next.access.groups))
      setSystems(text(next.access.allowed_system_ids))
      setDomains(text(next.access.allowed_domain_ids))
    } catch (error) { reportError(error) }
  }, [api, reportError])

  const canRead = context?.allowed_operations.includes('MEMBERSHIP_ACCESS_READ') ?? false
  useEffect(() => { if (canRead) void loadMembers() }, [canRead, loadMembers])
  useEffect(() => { void loadAccess(selectedId) }, [loadAccess, selectedId])

  const document = (): MembershipAccessDocument | undefined => access && ({
    ...access,
    groups: lines(groups),
    allowed_system_ids: lines(systems),
    allowed_domain_ids: lines(domains),
  })

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
    const intent = `membership-direct:${selectedId}:${etag}:${JSON.stringify(next)}`
    requestConfirmation({
      title: messages.directUpdate,
      summary: [`${selectedId}`, `ETag ${etag}`, `${messages.clearance}: ${next.clearance}`],
      execute: async () => {
        await api.updateMembership(selectedId, next, etag, keyFor(intent, 'admin-direct'))
        clearKey(intent)
        await Promise.all([loadMembers(), loadAccess(selectedId)])
      },
    })
  }

  const createFallback = () => {
    const next = document()
    if (!next || !reason.trim()) return
    const intent = `membership-fallback:${selectedId}:${etag}:${reason}:${JSON.stringify(next)}`
    requestConfirmation({
      title: messages.fallbackRequest,
      summary: [`${selectedId}`, `ETag ${etag}`, reason],
      execute: async () => {
        await api.createFallbackRequest(
          selectedId, reason.trim(), next, etag, keyFor(intent, 'admin-fallback-create'),
        )
        clearKey(intent)
        setReason('')
      },
    })
  }

  const canDirect = context?.allowed_operations.includes('MEMBERSHIP_ACCESS_UPDATE') ?? false
  const canFallback = context?.allowed_operations.includes('FALLBACK_REQUEST_CREATE') ?? false
  const selected = members.find((member) => member.subject_id === selectedId)
  const filteredMembers = useMemo(() => {
    const normalizedQuery = memberQuery.trim().toLocaleLowerCase()
    return members.filter((member) => {
      const matchesText = !normalizedQuery || [member.display_name, member.email ?? '', member.department_id ?? '']
        .some((value) => value.toLocaleLowerCase().includes(normalizedQuery))
      const matchesStatus = memberStatus === 'ALL'
        || (memberStatus === 'ACTIVE' && member.membership_active)
        || (memberStatus === 'INACTIVE' && !member.membership_active)
      return matchesText && matchesStatus
    })
  }, [memberQuery, memberStatus, members])

  return (<>
    <div className="admin-two-column admin-membership-workspace">
      <section className="panel">
        <div className="section-heading"><div><h3>User 관리</h3><p className="muted">OIDC 주체와 현재 Workspace 멤버십, 소유 테이블 및 CR 이력을 표시합니다.</p></div><div className="action-row"><button className="button button-secondary" disabled title="사용자 계정 생성과 비밀번호는 조직 OIDC/IdP에서 관리합니다.">신규 사용자 등록</button><button className="button button-secondary" onClick={() => void loadMembers()}>{messages.refresh}</button></div></div>
        <div className="mb-3 grid gap-2 rounded-enterprise border border-slate-300 bg-slate-50 p-3 md:grid-cols-[minmax(220px,1fr)_170px_auto] md:items-end">
          <label className="grid gap-1 text-xs font-bold">사용자 검색<input type="search" value={memberQuery} onChange={(event) => setMemberQuery(event.target.value)} placeholder="사용자명, 이메일로 검색" /></label>
          <label className="grid gap-1 text-xs font-bold">상태 필터<select value={memberStatus} onChange={(event) => setMemberStatus(event.target.value as typeof memberStatus)}><option value="ALL">전체</option><option value="ACTIVE">활성</option><option value="INACTIVE">비활성</option></select></label>
          <button type="button" className="button button-secondary" disabled={!memberQuery && memberStatus === 'ALL'} onClick={() => { setMemberQuery(''); setMemberStatus('ALL') }}>필터 초기화</button>
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
          data={filteredMembers}
          emptyMessage={messages.empty}
          getRowId={(member) => member.subject_id}
          selectedRowId={selectedId}
          onRowActivate={(member) => { setSelectedId(member.subject_id); setDetailOpen(true); setDetailTab('CR') }}
        />
        <p className="callout">사용자 계정 생성과 비밀번호는 조직 OIDC/IdP의 책임입니다. 이 목록은 IdP 토큰에서 확인한 이메일과 최근 접속 정보만 기록하며, 비밀번호는 저장하거나 표시하지 않습니다.</p>
      </section>
      <section className="panel form-stack" aria-live="polite">
        <h3>{messages.accessDocument}</h3>
        {!access || !selected ? <p className="muted">{messages.selectMember}</p> : <>
          <dl className="summary-list">
            <div><dt>subject_id</dt><dd>{selected.subject_id}</dd></div>
            <div><dt>display</dt><dd>{selected.display_name}</dd></div>
            <div><dt>version</dt><dd>{version} · {etag}</dd></div>
            <div><dt>subject</dt><dd>{selected.subject_active ? messages.active : messages.disabled}</dd></div>
          </dl>
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
            {canDirect ? <button className="button" onClick={directUpdate}>{messages.directUpdate}</button> : <button className="button button-secondary" onClick={() => void props.onStepUp()}>{messages.hardwareAuth}</button>}
            {context?.fallback_enabled
              ? canFallback
                ? <button className="button button-secondary" disabled={!reason.trim()} onClick={createFallback}>{messages.fallbackRequest}</button>
                : <button className="button button-secondary" onClick={() => void props.onPasswordReauth()}>{messages.passwordReauth}</button>
              : null}
          </div>
          {!context?.fallback_enabled && <p className="callout">{messages.fallbackDisabled}</p>}
        </>}
      </section>
    </div>
    <Dialog open={detailOpen && Boolean(selected)} size="large" title={selected ? `${selected.display_name} · ${selected.email ?? 'Email 미제공'}` : '사용자 상세'} description="서버가 제공한 Workspace 멤버십 요약입니다." onRequestClose={() => setDetailOpen(false)} footer={<><button type="button" className="button button-secondary" onClick={() => setDetailOpen(false)}>닫기</button><button type="button" className="button" onClick={() => setDetailOpen(false)}>Edit Profile</button></>}>
      {selected && <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="grid content-start gap-3 rounded-enterprise border border-slate-300 bg-slate-50 p-4">
          <dl className="grid gap-2 text-xs"><div><dt className="text-[10px] font-black text-slate-500">이름 · Email</dt><dd className="m-0">{selected.display_name}<br />{selected.email ?? '—'}</dd></div><div><dt className="text-[10px] font-black text-slate-500">권한</dt><dd className="m-0">{selected.job_function ?? '미지정'} · {selected.clearance}</dd></div><div><dt className="text-[10px] font-black text-slate-500">상태</dt><dd className="m-0">{selected.membership_active ? 'ACTIVE' : 'INACTIVE'}</dd></div></dl>
          <section className="border-t border-slate-300 pt-3"><h3 className="m-0 text-xs font-black text-navy-900">Assigned Systems</h3>{access?.allowed_system_ids.length ? <ul className="mb-0 pl-5 text-xs">{access.allowed_system_ids.map((id) => <li key={id}><code>{id}</code></li>)}</ul> : <p className="mb-0 text-xs text-slate-500">할당된 시스템 범위가 없습니다.</p>}</section>
          <section className="border-t border-slate-300 pt-3"><h3 className="m-0 text-xs font-black text-navy-900">Account Stats</h3><dl className="mt-2 grid gap-2 text-xs"><div><dt>CR Participated</dt><dd className="m-0 text-lg font-black">{selected.change_request_count}</dd></div><div><dt>Entities Owned</dt><dd className="m-0 text-lg font-black">{selected.owned_table_count}</dd></div><div><dt>Joined Date</dt><dd className="m-0">{selected.joined_at ? new Date(selected.joined_at).toLocaleDateString() : '—'}</dd></div></dl></section>
        </aside>
        <main className="grid content-start gap-3"><div className="flex gap-2 border-b border-slate-300 pb-2" role="tablist" aria-label="사용자 활동 상세"><button type="button" role="tab" aria-selected={detailTab === 'CR'} className={`button ${detailTab === 'CR' ? '' : 'button-secondary'}`} onClick={() => setDetailTab('CR')}>CR History</button><button type="button" role="tab" aria-selected={detailTab === 'TABLES'} className={`button ${detailTab === 'TABLES' ? '' : 'button-secondary'}`} onClick={() => setDetailTab('TABLES')}>Owned Tables</button></div>{detailTab === 'CR' ? <GovernedUnavailable title="사용자별 CR 상세 목록 API 미구현" description={`서버는 참여 건수 ${selected.change_request_count}건만 제공합니다. CR 번호·역할·상태가 포함된 권한 필터 목록 API 없이 항목을 추정하지 않습니다.`} /> : <GovernedUnavailable title="사용자별 소유 테이블 목록 API 미구현" description={`서버는 소유 건수 ${selected.owned_table_count}건만 제공합니다. 자산 상세 목록은 전용 권한 필터 API가 추가된 뒤 표시합니다.`} />}</main>
      </div>}
    </Dialog>
  </>)
}

export function MembershipRenewalAdmin(props: AdminSectionProps) {
  const { api, context, requestConfirmation, keyFor, clearKey, reportError } = props
  const [requests, setRequests] = useState<MembershipRenewalRequest[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [reason, setReason] = useState('')
  const [state, setState] = useState<MembershipRenewalRequest['state'] | 'ALL'>('PENDING')
  const canRead = context?.allowed_operations.includes('MEMBERSHIP_RENEWAL_READ') ?? false
  const canDecide = context?.allowed_operations.includes('MEMBERSHIP_RENEWAL_DECIDE') ?? false
  const load = useCallback(async () => {
    if (!canRead) return
    try {
      const next = await api.listMembershipRenewals(state === 'ALL' ? undefined : state)
      setRequests(next)
      setSelectedId((current) => current && next.some((item) => item.id === current)
        ? current : next[0]?.id ?? '')
    } catch (error) { reportError(error) }
  }, [api, canRead, reportError, state])
  useEffect(() => { void load() }, [load])
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
    <label className="max-w-52 text-xs font-bold">상태<select value={state} onChange={(event) => setState(event.target.value as typeof state)}><option value="PENDING">승인 대기</option><option value="APPROVED">승인</option><option value="REJECTED">반려</option><option value="ALL">전체</option></select></label>
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

  const load = useCallback(async () => {
    if (!context?.fallback_enabled || !context.allowed_operations.includes('FALLBACK_REQUEST_READ')) return
    try {
      const next = await api.listFallbackRequests()
      setRequests(next)
      setSelectedId((current) => current || next[0]?.id || '')
    } catch (error) { reportError(error) }
  }, [api, context, reportError])
  useEffect(() => { void load() }, [load])

  if (!context?.fallback_enabled) return <div className="callout">{messages.fallbackDisabled}</div>
  const selected = requests.find((request) => request.id === selectedId)
  const decide = (decision: 'APPROVED' | 'REJECTED') => {
    if (!selected || !reason.trim()) return
    const intent = `fallback-decision:${selected.id}:${selected.version}:${decision}:${reason}`
    requestConfirmation({
      title: `${messages.releaseDecision}: ${decision}`,
      summary: [selected.id, `v${selected.version}`, selected.payload_hash],
      execute: async () => {
        const next = await api.decideFallbackRequest(selected, decision, reason.trim(), keyFor(intent, 'admin-fallback-decision'))
        clearKey(intent); setReason('')
        setRequests((current) => current.map((item) => item.id === next.id ? next : item))
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
        const result = await api.consumeFallbackRequest(selected, keyFor(intent, 'admin-fallback-consume'))
        clearKey(intent)
        setRequests((current) => current.map((item) => item.id === result.request.id ? result.request : item))
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
