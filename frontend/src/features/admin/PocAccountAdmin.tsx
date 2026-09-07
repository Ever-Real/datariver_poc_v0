import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  PocAdminUser,
  PocAdminUserPage,
  PocUserTableGrantCandidate,
  PocUserTableGrantPage,
  TableSecurityGrade,
} from '../../api/types'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import type { AdminSectionProps } from './MembershipAdmin'

const roles = ['viewer', 'developer', 'data_steward', 'manager', 'admin'] as const
const minimumPasswordCharacters = 8
const grades: Array<{ value: TableSecurityGrade; label: string }> = [
  { value: 'normal', label: '일반' },
  { value: 'credential', label: '대외비' },
  { value: 'restricted', label: '극비' },
]

const emptyCreateUser = () => ({
  username: '', password: '', display_name: '', email: '', role: 'viewer' as PocAdminUser['role'],
  max_security_grade: 'normal' as TableSecurityGrade, must_change_password: true,
})

function gradeLabel(value: TableSecurityGrade) {
  return grades.find((grade) => grade.value === value)?.label ?? value
}

function passwordInPolicy(value: string) {
  return Array.from(value).length >= minimumPasswordCharacters
    && new TextEncoder().encode(value).byteLength <= 1024
}

function userDraft(user: PocAdminUser) {
  return {
    display_name: user.display_name,
    email: user.email ?? '',
    role: user.role,
    active: user.active,
    max_security_grade: user.max_security_grade,
    responsible_systems: Object.fromEntries(user.responsible_systems.map((item) => [
      item.system_id,
      String(item.priority),
    ])),
  }
}

export function PocAccountAdmin({ api, reportError, requestConfirmation }: AdminSectionProps) {
  const [page, setPage] = useState<PocAdminUserPage>()
  const [loading, setLoading] = useState(false)
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [editOpen, setEditOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [createDiscardConfirmationOpen, setCreateDiscardConfirmationOpen] = useState(false)
  const [draft, setDraft] = useState<ReturnType<typeof userDraft>>()
  const [credential, setCredential] = useState({ username: '', password: '', login_enabled: true, must_change_password: true })
  const [create, setCreate] = useState(emptyCreateUser)
  const [grants, setGrants] = useState<PocUserTableGrantPage>()
  const [grantFilters, setGrantFilters] = useState({ query: '', schema: '', systemId: '', securityGrade: '' as TableSecurityGrade | '' })
  const [selectedTables, setSelectedTables] = useState<Set<string>>(new Set())
  const lastSelectedIndex = useRef<number | undefined>(undefined)

  const loadUsers = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    try {
      const next = await api.listPocAdminUsers(signal)
      if (signal?.aborted) return
      setPage(next)
      setSelectedId((current) => current && next.items.some((item) => item.subject_id === current)
        ? current : next.items[0]?.subject_id ?? '')
    } catch (error) {
      if (!signal?.aborted) reportError(error)
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [api, reportError])

  useEffect(() => {
    const controller = new AbortController()
    void loadUsers(controller.signal)
    return () => controller.abort()
  }, [loadUsers])

  const selectedUser = page?.items.find((item) => item.subject_id === selectedId)
  const visibleUsers = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    return (page?.items ?? []).filter((user) => !normalized || [
      user.username, user.display_name, user.email, user.role,
    ].filter(Boolean).join(' ').toLocaleLowerCase().includes(normalized))
  }, [page, query])

  const loadGrants = useCallback(async (subjectId: string, signal?: AbortSignal) => {
    try {
      const next = await api.listPocUserTableGrants(subjectId, {
        query: grantFilters.query.trim() || undefined,
        schema: grantFilters.schema || undefined,
        systemId: grantFilters.systemId || undefined,
        securityGrade: grantFilters.securityGrade || undefined,
        signal,
      })
      if (!signal?.aborted) {
        setGrants(next)
        setSelectedTables(new Set())
        lastSelectedIndex.current = undefined
      }
    } catch (error) {
      if (!signal?.aborted) reportError(error)
    }
  }, [api, grantFilters, reportError])

  const openUser = (user: PocAdminUser) => {
    setSelectedId(user.subject_id)
    setDraft(userDraft(user))
    setCredential({
      username: user.credential?.username ?? user.username ?? '',
      password: '',
      login_enabled: user.credential?.login_enabled ?? false,
      must_change_password: user.credential?.must_change_password ?? true,
    })
    setGrantFilters({ query: '', schema: '', systemId: '', securityGrade: '' })
    setEditOpen(true)
    void api.listPocUserTableGrants(user.subject_id).then((next) => {
      setGrants(next); setSelectedTables(new Set()); lastSelectedIndex.current = undefined
    }).catch(reportError)
  }

  const saveUser = () => {
    if (!page || !selectedUser || !draft) return
    const responsible = Object.entries(draft.responsible_systems).map(([system_id, rawPriority]) => ({
      system_id,
      priority: Number(rawPriority),
    }))
    requestConfirmation({
      title: `${selectedUser.display_name} 계정 권한 변경`,
      summary: [draft.role, gradeLabel(draft.max_security_grade), draft.active ? '활성' : '비활성'],
      execute: async () => {
        await api.updatePocAdminUser(selectedUser.subject_id, {
          display_name: draft.display_name.trim(), email: draft.email.trim(), role: draft.role,
          active: draft.active, max_security_grade: draft.max_security_grade,
          responsible_systems: responsible,
        }, page.version)
        await loadUsers()
        setEditOpen(false)
      },
    })
  }

  const saveCredential = () => {
    if (!selectedUser) return
    const existingVersion = selectedUser.credential?.version ?? 0
    if (!credential.username.trim()
      || (!selectedUser.credential && !passwordInPolicy(credential.password))
      || (credential.password && !passwordInPolicy(credential.password))) return
    requestConfirmation({
      title: `${selectedUser.display_name} 로그인 credential 변경`,
      summary: [credential.login_enabled ? '로그인 허용' : '로그인 중지', credential.password ? '비밀번호 재설정 및 기존 세션 종료' : '비밀번호 유지'],
      execute: async () => {
        await api.updatePocUserCredential(selectedUser.subject_id, {
          username: credential.username.trim(),
          ...(credential.password ? { password: credential.password } : {}),
          login_enabled: credential.login_enabled,
          must_change_password: credential.must_change_password,
        }, existingVersion)
        setCredential((current) => ({ ...current, password: '' }))
        await loadUsers()
      },
    })
  }

  const revokeSessions = () => {
    if (!selectedUser) return
    requestConfirmation({
      title: `${selectedUser.display_name} 세션 전체 해지`,
      summary: ['현재 활성 opaque session을 즉시 revoke', 'credential과 access user는 보존'],
      execute: async () => { await api.revokePocUserSessions(selectedUser.subject_id); await loadUsers() },
    })
  }

  const createUser = () => {
    if (!page || !passwordInPolicy(create.password)) return
    requestConfirmation({
      title: `${create.display_name || create.username} 로컬 human 계정 생성`,
      summary: [create.role, gradeLabel(create.max_security_grade), '서버가 stable subject_id 생성'],
      execute: async () => {
        await api.createPocAdminUser({ ...create, responsible_systems: [] }, page.version)
        setCreate(emptyCreateUser())
        setCreateOpen(false)
        await loadUsers()
      },
    })
  }

  const createDirty = Boolean(
    create.username || create.password || create.display_name || create.email
    || create.role !== 'viewer' || create.max_security_grade !== 'normal'
    || create.must_change_password !== true,
  )
  const discardCreate = () => {
    setCreate(emptyCreateUser())
    setCreateDiscardConfirmationOpen(false)
    setCreateOpen(false)
  }
  const requestCreateClose = () => {
    if (createDirty) {
      setCreateDiscardConfirmationOpen(true)
      return
    }
    discardCreate()
  }

  const toggleResponsibleSystem = (systemId: string, checked: boolean) => {
    if (!draft) return
    const next = { ...draft.responsible_systems }
    if (checked) next[systemId] = next[systemId] || '1'
    else delete next[systemId]
    setDraft({ ...draft, responsible_systems: next })
  }

  const toggleTable = (table: PocUserTableGrantCandidate, index: number, checked: boolean, shift: boolean) => {
    const next = new Set(selectedTables)
    if (shift && lastSelectedIndex.current !== undefined && grants) {
      const start = Math.min(lastSelectedIndex.current, index)
      const end = Math.max(lastSelectedIndex.current, index)
      grants.items.slice(start, end + 1).forEach((item) => checked
        ? next.add(item.table_identity) : next.delete(item.table_identity))
    } else if (checked) next.add(table.table_identity)
    else next.delete(table.table_identity)
    lastSelectedIndex.current = index
    setSelectedTables(next)
  }

  const mutateGrants = (action: 'GRANT' | 'REMOVE') => {
    if (!selectedUser || selectedTables.size === 0) return
    const tableIds = [...selectedTables]
    requestConfirmation({
      title: `${selectedUser.display_name} Table ${action === 'GRANT' ? '접근 허용' : '접근 제거'}`,
      summary: [`선택 Table ${tableIds.length.toLocaleString()}개`, 'Schema/System filter는 저장되지 않음'],
      execute: async () => {
        await api.patchPocUserTableGrants(selectedUser.subject_id, action, tableIds)
        await Promise.all([loadGrants(selectedUser.subject_id), loadUsers()])
      },
    })
  }

  const roleAllowsResponsibility = draft && ['developer', 'data_steward', 'manager'].includes(draft.role)

  return <div className="grid gap-3">
    <section className="panel">
      <div className="section-heading"><div><h3>Local human 계정</h3><p className="muted">Role/System authority는 access document, password/session은 authentication storage가 소유합니다.</p></div><div className="action-row"><button type="button" className="button button-secondary" onClick={() => void loadUsers()}>새로고침</button><button type="button" className="button" onClick={() => setCreateOpen(true)}>사용자 생성</button></div></div>
      <label className="grid max-w-md gap-1 text-xs font-bold">사용자 검색<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="username, 이름, email, role" /></label>
      <DenseDataTable caption="DataRiver local human 계정" loading={loading} data={visibleUsers} getRowId={(user) => user.subject_id} selectedRowId={selectedId} onRowActivate={openUser} columns={[
        { accessorKey: 'display_name', header: '사용자', size: 180, cell: ({ row }) => <strong>{row.original.display_name}</strong> },
        { accessorKey: 'username', header: 'Login', size: 180, cell: ({ row }) => row.original.credential?.username ?? 'credential 없음' },
        { accessorKey: 'role', header: 'Role', size: 120 },
        { accessorKey: 'max_security_grade', header: '최대 등급', size: 100, cell: ({ row }) => gradeLabel(row.original.max_security_grade) },
        { accessorKey: 'table_grant_count', header: 'Table grant', size: 90 },
        { accessorKey: 'active', header: '계정', size: 80, cell: ({ row }) => row.original.active ? '활성' : '비활성' },
        { id: 'login', header: '로그인', size: 90, cell: ({ row }) => row.original.credential?.login_enabled ? '허용' : '중지' },
      ]} />
    </section>

    <Dialog open={createOpen} dirty={createDirty} title="Local human 사용자 생성" description="로그인 계정과 기본 권한을 함께 만듭니다." onRequestClose={requestCreateClose} onRequestDiscardChanges={() => setCreateDiscardConfirmationOpen(true)} footer={<><button type="button" className="button button-secondary" onClick={requestCreateClose}>취소</button><button type="button" className="button" disabled={!create.username.trim() || !create.display_name.trim() || !create.email.trim() || !passwordInPolicy(create.password)} onClick={createUser}>생성 확인</button></>}>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="grid gap-1 text-xs font-bold">Username<input value={create.username} onChange={(event) => setCreate({ ...create, username: event.target.value })} autoComplete="off" /></label>
        <label className="grid gap-1 text-xs font-bold">초기 비밀번호<input type="password" minLength={minimumPasswordCharacters} aria-describedby="local-human-password-help" value={create.password} onChange={(event) => setCreate({ ...create, password: event.target.value })} autoComplete="new-password" /></label>
        <p className="m-0 text-xs text-slate-500 md:col-span-2" id="local-human-password-help">8자 이상 · UTF-8 기준 최대 1024바이트</p>
        <label className="grid gap-1 text-xs font-bold">표시 이름<input value={create.display_name} onChange={(event) => setCreate({ ...create, display_name: event.target.value })} /></label>
        <label className="grid gap-1 text-xs font-bold">Email<input type="email" value={create.email} onChange={(event) => setCreate({ ...create, email: event.target.value })} /></label>
        <label className="grid gap-1 text-xs font-bold">Role<select value={create.role} onChange={(event) => setCreate({ ...create, role: event.target.value as PocAdminUser['role'] })}>{roles.map((role) => <option key={role}>{role}</option>)}</select></label>
        <label className="grid gap-1 text-xs font-bold">최대 보안등급<select value={create.max_security_grade} onChange={(event) => setCreate({ ...create, max_security_grade: event.target.value as TableSecurityGrade })}>{grades.map((grade) => <option key={grade.value} value={grade.value}>{grade.label}</option>)}</select></label>
        <label className="flex items-center gap-2 text-xs font-bold"><input type="checkbox" checked={create.must_change_password} onChange={(event) => setCreate({ ...create, must_change_password: event.target.checked })} />초기 비밀번호 변경 요구</label>
      </div>
    </Dialog>

    <Dialog open={createDiscardConfirmationOpen} title="사용자 작성 취소" description="저장하지 않은 사용자 정보가 삭제됩니다." showCloseButton={false} onRequestClose={() => setCreateDiscardConfirmationOpen(false)} footer={<><button type="button" className="button button-secondary" onClick={() => setCreateDiscardConfirmationOpen(false)}>계속 작성</button><button type="button" className="button" onClick={discardCreate}>작성 취소</button></>}>
      <p className="m-0">작성 중인 Local human 사용자 정보를 취소할까요?</p>
    </Dialog>

    <Dialog open={editOpen && Boolean(selectedUser && draft)} size="workspace" compactHeight title="사용자 접근 관리" description="Explicit Table grant와 Responsible System은 서로 독립된 domain relation입니다." onRequestClose={() => setEditOpen(false)} footer={<button type="button" className="button button-secondary" onClick={() => setEditOpen(false)}>닫기</button>}>
      {selectedUser && draft && <div className="grid gap-4">
        <section className="panel grid gap-3">
          <div className="section-heading"><div><h3>Profile / authority</h3><p className="muted">{selectedUser.subject_id}</p></div><button type="button" className="button" onClick={saveUser}>사용자 변경 확인</button></div>
          <div className="grid gap-3 md:grid-cols-4">
            <label className="grid gap-1 text-xs font-bold">표시 이름<input value={draft.display_name} onChange={(event) => setDraft({ ...draft, display_name: event.target.value })} /></label>
            <label className="grid gap-1 text-xs font-bold">Email<input value={draft.email} onChange={(event) => setDraft({ ...draft, email: event.target.value })} /></label>
            <label className="grid gap-1 text-xs font-bold">Role<select value={draft.role} onChange={(event) => setDraft({ ...draft, role: event.target.value as PocAdminUser['role'], responsible_systems: {} })}>{roles.map((role) => <option key={role}>{role}</option>)}</select></label>
            <label className="grid gap-1 text-xs font-bold">최대 보안등급<select value={draft.max_security_grade} onChange={(event) => setDraft({ ...draft, max_security_grade: event.target.value as TableSecurityGrade })}>{grades.map((grade) => <option key={grade.value} value={grade.value}>{grade.label}</option>)}</select></label>
            <label className="flex items-center gap-2 text-xs font-bold"><input type="checkbox" checked={draft.active} onChange={(event) => setDraft({ ...draft, active: event.target.checked, responsible_systems: event.target.checked ? draft.responsible_systems : {} })} />Access user active</label>
          </div>
          <div><strong className="text-xs">Responsible Systems / priority</strong><p className="muted">업무 담당범위이며 Table read grant가 아닙니다.</p><div className="grid gap-2 md:grid-cols-3">{(page?.systems ?? []).map((system) => <label key={system.system_id} className="flex items-center gap-2 rounded border p-2 text-xs"><input type="checkbox" disabled={!roleAllowsResponsibility} checked={Object.hasOwn(draft.responsible_systems, system.system_id)} onChange={(event) => toggleResponsibleSystem(system.system_id, event.target.checked)} /><span className="min-w-0 flex-1"><strong>{system.code}</strong><br />{system.name}</span>{Object.hasOwn(draft.responsible_systems, system.system_id) && <input aria-label={`${system.code} priority`} className="w-16" type="number" min="1" value={draft.responsible_systems[system.system_id]} onChange={(event) => setDraft({ ...draft, responsible_systems: { ...draft.responsible_systems, [system.system_id]: event.target.value } })} />}</label>)}</div></div>
        </section>

        <section className="panel grid gap-3">
          <div className="section-heading"><div><h3>Credential / sessions</h3><p className="muted">Role/System/grade는 credential에 저장하지 않습니다.</p></div><div className="action-row"><button type="button" className="button button-secondary" onClick={revokeSessions}>세션 전체 해지</button><button type="button" className="button" onClick={saveCredential}>Credential 변경 확인</button></div></div>
          <div className="grid gap-3 md:grid-cols-4"><label className="grid gap-1 text-xs font-bold">Username<input value={credential.username} onChange={(event) => setCredential({ ...credential, username: event.target.value })} /></label><label className="grid gap-1 text-xs font-bold">새 비밀번호 (선택)<input type="password" minLength={minimumPasswordCharacters} value={credential.password} onChange={(event) => setCredential({ ...credential, password: event.target.value })} autoComplete="new-password" /></label><label className="flex items-center gap-2 text-xs font-bold"><input type="checkbox" checked={credential.login_enabled} onChange={(event) => setCredential({ ...credential, login_enabled: event.target.checked })} />로그인 허용</label><label className="flex items-center gap-2 text-xs font-bold"><input type="checkbox" checked={credential.must_change_password} onChange={(event) => setCredential({ ...credential, must_change_password: event.target.checked })} />비밀번호 변경 요구</label></div>
          <p className="muted">활성 session {selectedUser.credential?.active_session_count ?? 0}개 · credential version {selectedUser.credential?.version ?? 0}</p>
        </section>

        <section className="panel grid gap-3">
          <div className="section-heading"><div><h3>Explicit Table access</h3><p className="muted">실제 선택된 canonical dataset URN만 저장합니다.</p></div><div className="action-row"><button type="button" className="button button-secondary" disabled={selectedTables.size === 0} onClick={() => mutateGrants('REMOVE')}>Grant 제거</button><button type="button" className="button" disabled={selectedTables.size === 0} onClick={() => mutateGrants('GRANT')}>Grant 추가</button></div></div>
          <div className="grid gap-2 md:grid-cols-5"><label className="grid gap-1 text-xs font-bold">검색<input value={grantFilters.query} onChange={(event) => setGrantFilters({ ...grantFilters, query: event.target.value })} /></label><label className="grid gap-1 text-xs font-bold">Schema<select value={grantFilters.schema} onChange={(event) => setGrantFilters({ ...grantFilters, schema: event.target.value })}><option value="">전체</option>{grants?.schemas.map((schema) => <option key={schema}>{schema}</option>)}</select></label><label className="grid gap-1 text-xs font-bold">System<select value={grantFilters.systemId} onChange={(event) => setGrantFilters({ ...grantFilters, systemId: event.target.value })}><option value="">전체</option>{page?.systems.map((system) => <option key={system.system_id} value={system.system_id}>{system.code}</option>)}</select></label><label className="grid gap-1 text-xs font-bold">등급<select value={grantFilters.securityGrade} onChange={(event) => setGrantFilters({ ...grantFilters, securityGrade: event.target.value as TableSecurityGrade | '' })}><option value="">전체</option>{grades.map((grade) => <option key={grade.value} value={grade.value}>{grade.label}</option>)}</select></label><button type="button" className="button button-secondary self-end" onClick={() => void loadGrants(selectedUser.subject_id)}>필터 적용</button></div>
          <div className="action-row"><button type="button" className="button button-secondary" disabled={!grants?.selection_complete} onClick={() => setSelectedTables(new Set(grants?.items.map((item) => item.table_identity) ?? []))}>현재 필터 결과 전체 선택</button><button type="button" className="button button-secondary" onClick={() => setSelectedTables(new Set())}>선택 해제</button><span className="badge badge-soft">선택 {selectedTables.size.toLocaleString()} / 결과 {grants?.total.toLocaleString() ?? 0}</span></div>
          <div className="dense-table-frame max-h-96"><table className="dense-data-table"><thead><tr><th>선택</th><th>Table</th><th>Schema</th><th>System</th><th>등급</th><th>현재 Grant</th></tr></thead><tbody>{grants?.items.map((table, index) => <tr key={table.table_identity}><td><input type="checkbox" aria-label={`${table.table_name} 선택`} checked={selectedTables.has(table.table_identity)} onChange={(event) => toggleTable(table, index, event.target.checked, (event.nativeEvent as MouseEvent).shiftKey)} /></td><td><strong>{table.table_name}</strong><br /><small>{table.table_identity}</small></td><td>{table.schema_name}</td><td>{table.system_ids.map((systemId) => page?.systems.find((system) => system.system_id === systemId)?.code ?? systemId).join(', ') || '미매핑'}</td><td>{gradeLabel(table.security_grade)}</td><td>{table.granted ? '허용' : '없음'}</td></tr>)}</tbody></table></div>
        </section>
      </div>}
    </Dialog>
  </div>
}
