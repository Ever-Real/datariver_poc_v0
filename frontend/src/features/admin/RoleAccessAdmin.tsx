import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  AccessRole,
  AccessRoleDataRule,
  AccessRoleWrite,
  Classification,
  DataAccessLevel,
  DataProcessingPurpose,
  MembershipRoleAssignmentEvidence,
  SystemDirectoryEntry,
  WorkspaceMembershipSummary,
} from '../../api/types'
import type { AdminSectionProps } from './MembershipAdmin'

const emptyRole = (): AccessRoleWrite => ({
  role_key: '', name: '', description: '', clearance: 'PUBLIC', groups: [],
  allowed_actions: [], denied_actions: [], allowed_system_ids: [], allowed_domain_ids: [],
  data_access_rules: [],
  active: true,
})

const classifications: Classification[] = ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED']
const processingPurposes: DataProcessingPurpose[] = [
  'METADATA_READ', 'DATA_READ', 'EXPORT', 'ANALYTICS', 'MODEL_TRAINING',
]

function lines(value: string): string[] {
  return [...new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean))]
}

/** Server-managed RBAC facade. The selected role is materialized through the existing
 * governed membership update service, so normal ABAC remains the enforcement point. */
export function RoleAccessAdmin(props: AdminSectionProps) {
  const { api, context, requestConfirmation, keyFor, clearKey, reportError } = props
  const [members, setMembers] = useState<WorkspaceMembershipSummary[]>([])
  const [roles, setRoles] = useState<AccessRole[]>([])
  const [systems, setSystems] = useState<SystemDirectoryEntry[]>([])
  const [memberQuery, setMemberQuery] = useState('')
  const [appliedMemberQuery, setAppliedMemberQuery] = useState('')
  const [memberCursor, setMemberCursor] = useState<string>()
  const [memberCursorHistory, setMemberCursorHistory] = useState<string[]>([])
  const [nextMemberCursor, setNextMemberCursor] = useState<string | null>(null)
  const [memberPageNumber, setMemberPageNumber] = useState(1)
  const [roleQuery, setRoleQuery] = useState('')
  const [appliedRoleQuery, setAppliedRoleQuery] = useState('')
  const [roleCursor, setRoleCursor] = useState<string>()
  const [roleCursorHistory, setRoleCursorHistory] = useState<string[]>([])
  const [nextRoleCursor, setNextRoleCursor] = useState<string | null>(null)
  const [rolePageNumber, setRolePageNumber] = useState(1)
  const [systemQuery, setSystemQuery] = useState('')
  const [appliedSystemQuery, setAppliedSystemQuery] = useState('')
  const [systemCursor, setSystemCursor] = useState<string>()
  const [systemCursorHistory, setSystemCursorHistory] = useState<string[]>([])
  const [nextSystemCursor, setNextSystemCursor] = useState<string | null>(null)
  const [systemPageNumber, setSystemPageNumber] = useState(1)
  const [selectedSubjectId, setSelectedSubjectId] = useState('')
  const [loadedSubjectId, setLoadedSubjectId] = useState('')
  const [roleAssignment, setRoleAssignment] = useState<MembershipRoleAssignmentEvidence>()
  const [membershipEtag, setMembershipEtag] = useState('')
  const [assignmentRoleId, setAssignmentRoleId] = useState('')
  const [editingId, setEditingId] = useState('NEW')
  const [draft, setDraft] = useState<AccessRoleWrite>(emptyRole)
  const [groupText, setGroupText] = useState('')
  const [systemText, setSystemText] = useState('')
  const [domainText, setDomainText] = useState('')
  const memberGeneration = useRef(0)
  const roleGeneration = useRef(0)
  const systemGeneration = useRef(0)
  const accessGeneration = useRef(0)

  const loadMembers = useCallback(async (signal?: AbortSignal) => {
    const generation = ++memberGeneration.current
    try {
      const page = await api.listMembershipPage({
        query: appliedMemberQuery || undefined,
        cursor: memberCursor,
        limit: 25,
        signal,
      })
      if (signal?.aborted || generation !== memberGeneration.current) return
      setMembers(page.items)
      setNextMemberCursor(page.nextCursor)
      setSelectedSubjectId((current) => (
        current && page.items.some((member) => member.subject_id === current)
          ? current
          : page.items[0]?.subject_id || ''
      ))
    } catch (error) {
      if (!signal?.aborted && generation === memberGeneration.current) reportError(error)
    }
  }, [api, appliedMemberQuery, memberCursor, reportError])
  const loadRoles = useCallback(async (signal?: AbortSignal) => {
    const generation = ++roleGeneration.current
    try {
      const page = await api.listAccessRolePage({
        query: appliedRoleQuery || undefined,
        cursor: roleCursor,
        limit: 25,
        signal,
      })
      if (signal?.aborted || generation !== roleGeneration.current) return
      setRoles(page.items)
      setNextRoleCursor(page.nextCursor)
      setEditingId((current) => (
        current === 'NEW' || page.items.some((role) => role.id === current)
          ? current
          : 'NEW'
      ))
    } catch (error) {
      if (!signal?.aborted && generation === roleGeneration.current) reportError(error)
    }
  }, [api, appliedRoleQuery, reportError, roleCursor])
  const loadSystems = useCallback(async (signal?: AbortSignal) => {
    const generation = ++systemGeneration.current
    try {
      const page = await api.listSystemPage({
        query: appliedSystemQuery || undefined,
        cursor: systemCursor,
        limit: 25,
        signal,
      })
      if (signal?.aborted || generation !== systemGeneration.current) return
      setSystems(page.items)
      setNextSystemCursor(page.nextCursor)
    } catch (error) {
      if (!signal?.aborted && generation === systemGeneration.current) reportError(error)
    }
  }, [api, appliedSystemQuery, reportError, systemCursor])
  const loadAccess = useCallback(async (subjectId: string, signal?: AbortSignal) => {
    if (!subjectId) return
    const generation = ++accessGeneration.current
    try {
      const value = await api.getMembershipAccess(subjectId, signal)
      if (signal?.aborted || generation !== accessGeneration.current) return
      setLoadedSubjectId(subjectId)
      setRoleAssignment(value.role_assignment)
      setMembershipEtag(value.etag)
    } catch (error) {
      if (!signal?.aborted && generation === accessGeneration.current) reportError(error)
    }
  }, [api, reportError])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setAppliedMemberQuery(memberQuery.trim())
      setMemberCursor(undefined)
      setMemberCursorHistory([])
      setMemberPageNumber(1)
    }, 250)
    return () => window.clearTimeout(timer)
  }, [memberQuery])
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setAppliedRoleQuery(roleQuery.trim())
      setRoleCursor(undefined)
      setRoleCursorHistory([])
      setRolePageNumber(1)
    }, 250)
    return () => window.clearTimeout(timer)
  }, [roleQuery])
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setAppliedSystemQuery(systemQuery.trim())
      setSystemCursor(undefined)
      setSystemCursorHistory([])
      setSystemPageNumber(1)
    }, 250)
    return () => window.clearTimeout(timer)
  }, [systemQuery])
  useEffect(() => {
    const controller = new AbortController()
    void loadMembers(controller.signal)
    return () => {
      controller.abort()
      memberGeneration.current += 1
    }
  }, [loadMembers])
  useEffect(() => {
    const controller = new AbortController()
    void loadRoles(controller.signal)
    return () => {
      controller.abort()
      roleGeneration.current += 1
    }
  }, [loadRoles])
  useEffect(() => {
    const controller = new AbortController()
    void loadSystems(controller.signal)
    return () => {
      controller.abort()
      systemGeneration.current += 1
    }
  }, [loadSystems])
  useEffect(() => {
    const controller = new AbortController()
    setLoadedSubjectId('')
    setRoleAssignment(undefined)
    setMembershipEtag('')
    if (selectedSubjectId) void loadAccess(selectedSubjectId, controller.signal)
    return () => {
      controller.abort()
      accessGeneration.current += 1
    }
  }, [loadAccess, selectedSubjectId])
  const selectedMember = members.find((member) => member.subject_id === selectedSubjectId)
  const loadedForSelection = loadedSubjectId === selectedSubjectId
  const assignedRole = loadedForSelection
    ? roles.find((role) => role.id === roleAssignment?.role_id)
    : undefined
  useEffect(() => {
    setAssignmentRoleId(loadedForSelection ? roleAssignment?.role_id ?? '' : '')
  }, [loadedForSelection, roleAssignment?.role_id])

  const editingRole = roles.find((role) => role.id === editingId)
  const canUpdate = context?.allowed_operations.includes('MEMBERSHIP_ACCESS_UPDATE') ?? false
  const canAssign = (
    canUpdate
    && loadedForSelection
    && selectedSubjectId !== context?.subject_id
  )
  const securityLocked = Boolean(editingRole?.assigned_count)
  const knownActions = useMemo(() => new Set(context?.action_vocabulary ?? []), [context])

  const edit = (role: AccessRole) => {
    setEditingId(role.id)
    setDraft({
      role_key: role.role_key, name: role.name, description: role.description,
      clearance: role.clearance, groups: role.groups, allowed_actions: role.allowed_actions,
      denied_actions: role.denied_actions, allowed_system_ids: role.allowed_system_ids,
      allowed_domain_ids: role.allowed_domain_ids,
      data_access_rules: role.data_access_rules.map((rule) => ({
        ...rule,
        allowed_residency_regions: [...rule.allowed_residency_regions],
        allowed_processing_purposes: [...rule.allowed_processing_purposes],
      })),
      active: role.active,
    })
    setGroupText(role.groups.join('\n')); setSystemText(role.allowed_system_ids.join('\n'))
    setDomainText(role.allowed_domain_ids.join('\n'))
  }
  const startNew = () => {
    setEditingId('NEW'); setDraft(emptyRole()); setGroupText(''); setSystemText(''); setDomainText('')
  }
  const payload = (): AccessRoleWrite => ({
    ...draft,
    groups: lines(groupText),
    allowed_system_ids: lines(systemText),
    allowed_domain_ids: lines(domainText),
    allowed_actions: draft.allowed_actions.filter((action) => knownActions.has(action)),
    denied_actions: draft.denied_actions.filter((action) => knownActions.has(action)),
  })
  const setAction = (action: string, effect: 'NONE' | 'ALLOW' | 'DENY') => {
    setDraft((current) => ({
      ...current,
      allowed_actions: effect === 'ALLOW' ? [...new Set([...current.allowed_actions, action])] : current.allowed_actions.filter((value) => value !== action),
      denied_actions: effect === 'DENY' ? [...new Set([...current.denied_actions, action])] : current.denied_actions.filter((value) => value !== action),
    }))
  }
  const setSystemScope = (systemId: string, checked: boolean) => {
    const values = lines(systemText)
    setSystemText(checked
      ? [...new Set([...values, systemId])].join('\n')
      : values.filter((value) => value !== systemId).join('\n'))
  }
  const setDataAccessLevel = (
    classification: Classification,
    accessLevel: DataAccessLevel | 'MISSING',
  ) => {
    setDraft((current) => {
      const existing = current.data_access_rules.find(
        (rule) => rule.classification === classification,
      )
      const remaining = current.data_access_rules.filter(
        (rule) => rule.classification !== classification,
      )
      if (accessLevel === 'MISSING') return { ...current, data_access_rules: remaining }
      const next: AccessRoleDataRule = accessLevel === 'NO_ACCESS'
        ? {
            classification, access_level: accessLevel, partial_treatment: null,
            allowed_residency_regions: [], allowed_processing_purposes: [],
          }
        : {
            classification,
            access_level: accessLevel,
            partial_treatment: accessLevel === 'PARTIAL_ACCESS'
              ? existing?.partial_treatment ?? 'MASK'
              : null,
            allowed_residency_regions: existing?.allowed_residency_regions ?? [],
            allowed_processing_purposes: existing?.allowed_processing_purposes ?? [],
          }
      return {
        ...current,
        data_access_rules: classifications
          .map((value) => value === classification
            ? next
            : current.data_access_rules.find((rule) => rule.classification === value))
          .filter((rule): rule is AccessRoleDataRule => Boolean(rule)),
      }
    })
  }
  const updateDataRule = (
    classification: Classification,
    update: (rule: AccessRoleDataRule) => AccessRoleDataRule,
  ) => setDraft((current) => ({
    ...current,
    data_access_rules: current.data_access_rules.map((rule) => (
      rule.classification === classification ? update(rule) : rule
    )),
  }))
  const dataRulesValid = draft.data_access_rules.every((rule) => (
    rule.access_level === 'NO_ACCESS'
    || (
      rule.allowed_residency_regions.length > 0
      && rule.allowed_processing_purposes.length > 0
      && (
        rule.access_level !== 'PARTIAL_ACCESS'
        || rule.partial_treatment !== null
      )
    )
  ))
  const saveRole = () => {
    const next = payload()
    if (!canUpdate || !next.role_key || !next.name.trim()) return
    const intent = `access-role:${editingId}:${editingRole?.version ?? 0}:${JSON.stringify(next)}`
    requestConfirmation({
      title: editingRole ? `${editingRole.name} Role 편집` : '신규 Role 생성',
      summary: [next.role_key, next.clearance, `ALLOW ${next.allowed_actions.length}개`, `DENY ${next.denied_actions.length}개`],
      execute: async () => {
        if (editingRole) await api.updateAccessRole(editingRole, next)
        else await api.createAccessRole(next)
        clearKey(intent); await loadRoles(); startNew()
      },
    })
  }
  const deactivate = (role: AccessRole) => {
    const intent = `access-role-deactivate:${role.id}:${role.version}`
    requestConfirmation({
      title: `${role.name} Role 비활성화`,
      summary: [role.role_key, `할당 사용자 ${role.assigned_count}명`, '사용 중 Role은 서버가 거부합니다.'],
      execute: async () => {
        await api.deactivateAccessRole(role)
        clearKey(intent)
        await loadRoles()
        startNew()
      },
    })
  }
  const assign = (roleId: string | null) => {
    if (!selectedMember || !canAssign || !membershipEtag || !loadedForSelection) return
    const targetSubjectId = loadedSubjectId
    const role = roles.find((item) => item.id === roleId)
    const intent = `membership-role:${selectedMember.subject_id}:${membershipEtag}:${roleId ?? 'none'}`
    requestConfirmation({
      title: `${selectedMember.display_name} Role ${role ? '할당' : '해제'}`,
      summary: [role?.name ?? 'Role 미할당', membershipEtag, role ? `${role.clearance} · ALLOW ${role.allowed_actions.length}개` : '권한 없음(PUBLIC)'],
      execute: async () => {
        if (targetSubjectId !== selectedSubjectId) return
        await api.assignMembershipRole(
          targetSubjectId, roleId, membershipEtag, keyFor(intent, 'membership-role'),
        )
        clearKey(intent)
        await Promise.all([loadAccess(targetSubjectId), loadRoles()])
      },
    })
  }

  return <div className="grid gap-3">
    <section className="panel border-l-4 border-l-blue-700 bg-slate-50"><span className="eyebrow">Server-managed RBAC</span><h3 className="mb-1 mt-1">Role 정의 및 사용자 할당</h3><p className="m-0 text-xs leading-5 text-slate-600">Role은 서버에 저장되며 사용자에게 적용될 때 기존 ABAC Access 문서로 변환됩니다. 사용 중 Role의 보안 정의 변경·비활성화는 서버가 거부하므로 먼저 사용자를 다른 Role로 재할당하세요.</p></section>
    <div className="admin-two-column role-access-admin">
      <section className="panel form-stack">
        <div className="section-heading"><div><h3>사용자 Role 할당</h3><p className="muted">인증 계정은 User 관리에서 등록하고, 플랫폼 권한은 이 Role로 관리합니다.</p></div><button type="button" className="button button-secondary" onClick={() => void Promise.all([loadMembers(), loadRoles(), loadSystems()])}>새로고침</button></div>
        <label>사용자 검색<input type="search" value={memberQuery} onChange={(event) => setMemberQuery(event.target.value)} placeholder="이름 또는 이메일" /></label>
        <label>사용자<select value={selectedSubjectId} onChange={(event) => setSelectedSubjectId(event.target.value)}>{members.map((member) => <option key={member.subject_id} value={member.subject_id}>{member.display_name} · {member.email ?? 'Email 미제공'}</option>)}</select></label>
        <PageControls
          pageNumber={memberPageNumber}
          canPrevious={memberCursorHistory.length > 0}
          canNext={Boolean(nextMemberCursor)}
          previous={() => {
            const previous = memberCursorHistory.at(-1)
            setMemberCursorHistory((current) => current.slice(0, -1))
            setMemberCursor(previous || undefined)
            setMemberPageNumber((current) => Math.max(1, current - 1))
          }}
          next={() => {
            if (!nextMemberCursor) return
            setMemberCursorHistory((current) => [...current.slice(-49), memberCursor ?? ''])
            setMemberCursor(nextMemberCursor)
            setMemberPageNumber((current) => current + 1)
          }}
        />
        {selectedMember && <dl className="summary-list"><div><dt>현재 Role</dt><dd>{loadedForSelection ? assignedRole?.name ?? roleAssignment?.role_id ?? '미할당' : '불러오는 중…'}</dd></div><div><dt>Role 증거</dt><dd>{roleAssignment?.role_version ? `v${roleAssignment.role_version} · ${roleAssignment.status}` : roleAssignment?.status ?? 'LOADING'}</dd></div><div><dt>가입일</dt><dd>{selectedMember.joined_at ? new Date(selectedMember.joined_at).toLocaleDateString() : '—'}</dd></div><div><dt>상태</dt><dd>{selectedMember.membership_active ? 'ACTIVE' : 'INACTIVE'}</dd></div></dl>}
        {roleAssignment?.status === 'LEGACY_UNVERIFIED' && <p className="notice notice-error" role="note">레거시 Role 마커는 권한 증거가 아닙니다. 정규화된 Role을 다시 할당해 증거를 복구하세요.</p>}
        {roleAssignment?.status === 'EVIDENCE_MISMATCH' && <p className="notice notice-error" role="note">Role 할당 증거와 현재 access 문서가 일치하지 않습니다. 새 Role 할당 또는 해제로 복구하기 전에는 현재 표시를 권한 근거로 사용하지 마세요.</p>}
        <label>할당할 Role<select value={assignmentRoleId} onChange={(event) => setAssignmentRoleId(event.target.value)} disabled={!canAssign}><option value="">Role 미할당</option>{roleAssignment?.role_id && !roles.some((role) => role.id === roleAssignment.role_id) && <option value={roleAssignment.role_id}>{roleAssignment.role_id} · 현재 페이지 외 Role</option>}{roles.filter((role) => role.active).map((role) => <option key={role.id} value={role.id}>{role.name} · {role.clearance}</option>)}</select></label>
        <div className="action-row"><button type="button" className="button" disabled={!canAssign || !assignmentRoleId || roleAssignment?.role_id === assignmentRoleId} onClick={() => assign(assignmentRoleId)}>Role 할당</button><button type="button" className="button button-secondary" disabled={!canAssign || !roleAssignment?.role_id} onClick={() => assign(null)}>Role 해제</button></div>
        {selectedSubjectId === context?.subject_id && <p className="callout">관리자는 자신의 Role을 변경할 수 없습니다. 다른 적격 Admin이 변경해야 합니다.</p>}
      </section>
      <section className="panel form-stack">
        <div className="section-heading"><div><h3>Role 정의</h3><p className="muted">Workspace 공통 권한 그룹을 추가·편집·비활성화합니다.</p></div><button type="button" className="button button-secondary" onClick={startNew}>+ 신규 Role</button></div>
        <label>Role 검색<input type="search" value={roleQuery} onChange={(event) => setRoleQuery(event.target.value)} placeholder="Role 이름 또는 key" /></label>
        <div className="compact-list" aria-label="서버 Role 정의">{roles.map((role) => <button type="button" key={role.id} className={editingId === role.id ? 'selected' : ''} onClick={() => edit(role)}><span><strong>{role.name}</strong><small>{role.role_key} · {role.clearance} · 사용자 {role.assigned_count}명</small></span><span className={`badge ${role.active ? '' : 'badge-soft'}`}>{role.active ? 'ACTIVE' : 'INACTIVE'}</span></button>)}{!roles.length && <p className="muted">등록된 Role이 없습니다.</p>}</div>
        <PageControls
          pageNumber={rolePageNumber}
          canPrevious={roleCursorHistory.length > 0}
          canNext={Boolean(nextRoleCursor)}
          previous={() => {
            const previous = roleCursorHistory.at(-1)
            setRoleCursorHistory((current) => current.slice(0, -1))
            setRoleCursor(previous || undefined)
            setRolePageNumber((current) => Math.max(1, current - 1))
          }}
          next={() => {
            if (!nextRoleCursor) return
            setRoleCursorHistory((current) => [...current.slice(-49), roleCursor ?? ''])
            setRoleCursor(nextRoleCursor)
            setRolePageNumber((current) => current + 1)
          }}
        />
        <div className="grid gap-2 border-t border-slate-300 pt-3 md:grid-cols-2"><label>Role Key<input value={draft.role_key} onChange={(event) => setDraft({ ...draft, role_key: event.target.value })} pattern="[a-z][a-z0-9-]{1,79}" disabled={editingId !== 'NEW'} placeholder="catalog-reader" /></label><label>Role 이름<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} maxLength={255} /></label></div>
        <label>설명<textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} maxLength={4000} /></label>
        {securityLocked && <p className="callout">{editingRole?.assigned_count}명의 사용자에게 할당되어 보안 정의는 잠겼습니다. 이름·설명만 편집할 수 있습니다.</p>}
        <label>등급<select value={draft.clearance} disabled={securityLocked} onChange={(event) => setDraft({ ...draft, clearance: event.target.value as AccessRoleWrite['clearance'] })}><option>PUBLIC</option><option>INTERNAL</option><option>CONFIDENTIAL</option><option>RESTRICTED</option></select></label>
        <label>그룹<textarea value={groupText} disabled={securityLocked} onChange={(event) => setGroupText(event.target.value)} placeholder="security-administrators" /></label>
        <details className="rounded-enterprise border border-slate-300 bg-slate-50 p-3"><summary className="cursor-pointer text-xs font-black text-navy-900">권한 Action 및 접근 범위</summary><div className="mt-3 grid gap-3"><fieldset className="action-matrix"><legend>Action</legend>{context?.action_vocabulary.map((action) => { const effect = draft.allowed_actions.includes(action) ? 'ALLOW' : draft.denied_actions.includes(action) ? 'DENY' : 'NONE'; return <label key={action}><span>{action}</span><select aria-label={`Role ${action}`} disabled={securityLocked} value={effect} onChange={(event) => setAction(action, event.target.value as 'NONE' | 'ALLOW' | 'DENY')}><option value="NONE">—</option><option value="ALLOW">ALLOW</option><option value="DENY">DENY</option></select></label> })}</fieldset><fieldset className="grid gap-2"><legend>System 접근 범위</legend><label>System 검색<input type="search" value={systemQuery} onChange={(event) => setSystemQuery(event.target.value)} placeholder="시스템명 또는 코드" /></label>{systems.map((system) => <label className="checkbox-line" key={system.system_id}><input type="checkbox" checked={lines(systemText).includes(system.system_id)} disabled={securityLocked || !system.active} onChange={(event) => setSystemScope(system.system_id, event.target.checked)} /><span><strong>{system.name}</strong> <small>{system.code}{system.active ? '' : ' · INACTIVE'}</small></span></label>)}{systems.length === 0 && <small className="muted">현재 검색 페이지에 시스템이 없습니다.</small>}<PageControls
          pageNumber={systemPageNumber}
          canPrevious={systemCursorHistory.length > 0}
          canNext={Boolean(nextSystemCursor)}
          previous={() => {
            const previous = systemCursorHistory.at(-1)
            setSystemCursorHistory((current) => current.slice(0, -1))
            setSystemCursor(previous || undefined)
            setSystemPageNumber((current) => Math.max(1, current - 1))
          }}
          next={() => {
            if (!nextSystemCursor) return
            setSystemCursorHistory((current) => [...current.slice(-49), systemCursor ?? ''])
            setSystemCursor(nextSystemCursor)
            setSystemPageNumber((current) => current + 1)
          }}
        />{lines(systemText).filter((id) => !systems.some((system) => system.system_id === id)).length > 0 && <small className="muted">현재 페이지 외 선택 {lines(systemText).filter((id) => !systems.some((system) => system.system_id === id)).length}건을 유지합니다. 검색하거나 페이지를 이동해 해제할 수 있습니다.</small>}</fieldset><label>Domain IDs <small>Domain directory API가 추가되기 전에는 고급 UUID 범위로만 편집합니다.</small><textarea value={domainText} disabled={securityLocked} onChange={(event) => setDomainText(event.target.value)} /></label></div></details>
        <section className="grid gap-3 rounded-enterprise border border-slate-300 bg-white p-3" aria-labelledby="data-access-policy-title">
          <h3 className="m-0 text-sm" id="data-access-policy-title">데이터 접근 정책</h3>
          <p className="m-0 text-xs text-slate-600">등급별 No/Partial/Full 접근, 부분 처리, 상주 지역과 처리 목적을 명시합니다. 누락 등급은 서버에서 fail-closed 됩니다.</p>
          {classifications.map((classification) => {
            const rule = draft.data_access_rules.find(
              (value) => value.classification === classification,
            )
            return <fieldset className="grid gap-2 rounded-enterprise border border-slate-200 p-3" disabled={securityLocked} key={classification}>
              <legend className="px-1 text-xs font-black">{classification}</legend>
              <label>접근 수준<select aria-label={`${classification} 접근 수준`} value={rule?.access_level ?? 'MISSING'} onChange={(event) => setDataAccessLevel(classification, event.target.value as DataAccessLevel | 'MISSING')}><option value="MISSING">MISSING · fail-closed</option><option value="NO_ACCESS">NO_ACCESS</option><option value="PARTIAL_ACCESS">PARTIAL_ACCESS</option><option value="FULL_ACCESS">FULL_ACCESS</option></select></label>
              {rule && rule.access_level !== 'NO_ACCESS' && <>
                {rule.access_level === 'PARTIAL_ACCESS' && <label>부분 처리 방식<select aria-label={`${classification} 부분 처리 방식`} value={rule.partial_treatment ?? 'MASK'} onChange={(event) => updateDataRule(classification, (current) => ({ ...current, partial_treatment: event.target.value as AccessRoleDataRule['partial_treatment'] }))}><option>MASK</option><option>REDACT</option><option>TOKENIZE</option></select></label>}
                <label>상주 지역<textarea aria-label={`${classification} 상주 지역`} value={rule.allowed_residency_regions.join('\n')} placeholder="KR&#10;EU" onChange={(event) => updateDataRule(classification, (current) => ({ ...current, allowed_residency_regions: lines(event.target.value).map((value) => value.toUpperCase()) }))} /></label>
                <fieldset className="grid gap-1"><legend>처리 목적</legend>{processingPurposes.map((purpose) => <label className="checkbox-line" key={purpose}><input type="checkbox" aria-label={`${classification} ${purpose}`} checked={rule.allowed_processing_purposes.includes(purpose)} onChange={(event) => updateDataRule(classification, (current) => ({ ...current, allowed_processing_purposes: event.target.checked ? [...new Set([...current.allowed_processing_purposes, purpose])] : current.allowed_processing_purposes.filter((value) => value !== purpose) }))} />{purpose}</label>)}</fieldset>
              </>}
            </fieldset>
          })}
          {draft.data_access_rules.length < classifications.length && <p className="callout m-0">누락된 등급은 fail-closed 상태로 저장됩니다. 의도한 누락인지 확인하세요.</p>}
          {!dataRulesValid && <p className="notice notice-error m-0" role="note">Partial/Full 규칙에는 상주 지역과 하나 이상의 처리 목적이 필요합니다.</p>}
        </section>
        <div className="action-row"><button type="button" className="button" disabled={!canUpdate || !draft.role_key || !draft.name.trim() || !dataRulesValid} onClick={saveRole}>{editingRole ? 'Role 저장' : 'Role 생성'}</button>{editingRole && <button type="button" className="button button-secondary" disabled={!canUpdate || editingRole.assigned_count > 0 || !editingRole.active} onClick={() => deactivate(editingRole)}>비활성화</button>}</div>
      </section>
    </div>
  </div>
}

function PageControls({
  pageNumber,
  canPrevious,
  canNext,
  previous,
  next,
}: {
  pageNumber: number
  canPrevious: boolean
  canNext: boolean
  previous: () => void
  next: () => void
}) {
  return <div className="flex items-center justify-end gap-2">
    <span className="text-xs text-slate-600">페이지 {pageNumber}</span>
    <button type="button" className="button button-secondary" disabled={!canPrevious} onClick={previous}>이전</button>
    <button type="button" className="button button-secondary" disabled={!canNext} onClick={next}>다음</button>
  </div>
}
