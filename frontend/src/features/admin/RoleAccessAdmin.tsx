import { useCallback, useEffect, useMemo, useState } from 'react'
import type {
  AccessRole,
  AccessRoleWrite,
  SystemDirectoryEntry,
  WorkspaceMembershipSummary,
} from '../../api/types'
import type { AdminSectionProps } from './MembershipAdmin'

const emptyRole = (): AccessRoleWrite => ({
  role_key: '', name: '', description: '', clearance: 'PUBLIC', groups: [],
  allowed_actions: [], denied_actions: [], allowed_system_ids: [], allowed_domain_ids: [],
  active: true,
})

function lines(value: string): string[] {
  return [...new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean))]
}

function roleMarker(role: AccessRole) { return `datariver-role-${role.role_key}` }

/** Server-managed RBAC facade. The selected role is materialized through the existing
 * governed membership update service, so normal ABAC remains the enforcement point. */
export function RoleAccessAdmin(props: AdminSectionProps) {
  const { api, context, requestConfirmation, keyFor, clearKey, reportError } = props
  const [members, setMembers] = useState<WorkspaceMembershipSummary[]>([])
  const [roles, setRoles] = useState<AccessRole[]>([])
  const [systems, setSystems] = useState<SystemDirectoryEntry[]>([])
  const [selectedSubjectId, setSelectedSubjectId] = useState('')
  const [accessGroups, setAccessGroups] = useState<string[]>([])
  const [membershipEtag, setMembershipEtag] = useState('')
  const [assignmentRoleId, setAssignmentRoleId] = useState('')
  const [editingId, setEditingId] = useState('NEW')
  const [draft, setDraft] = useState<AccessRoleWrite>(emptyRole)
  const [groupText, setGroupText] = useState('')
  const [systemText, setSystemText] = useState('')
  const [domainText, setDomainText] = useState('')

  const loadDirectory = useCallback(async () => {
    try {
      const [nextMembers, nextRoles, nextSystems] = await Promise.all([
        api.listMemberships(), api.listAccessRoles(), api.listSystems(),
      ])
      setMembers(nextMembers); setRoles(nextRoles); setSystems(nextSystems)
      setSelectedSubjectId((current) => current || nextMembers[0]?.subject_id || '')
    } catch (error) { reportError(error) }
  }, [api, reportError])
  const loadAccess = useCallback(async (subjectId: string) => {
    if (!subjectId) return
    try {
      const value = await api.getMembershipAccess(subjectId)
      setAccessGroups(value.access.groups); setMembershipEtag(value.etag)
    } catch (error) { reportError(error) }
  }, [api, reportError])

  useEffect(() => { void loadDirectory() }, [loadDirectory])
  useEffect(() => { void loadAccess(selectedSubjectId) }, [loadAccess, selectedSubjectId])
  const selectedMember = members.find((member) => member.subject_id === selectedSubjectId)
  const assignedRole = roles.find((role) => accessGroups.includes(roleMarker(role)))
  useEffect(() => { setAssignmentRoleId(assignedRole?.id ?? '') }, [assignedRole?.id])

  const editingRole = roles.find((role) => role.id === editingId)
  const canUpdate = context?.allowed_operations.includes('MEMBERSHIP_ACCESS_UPDATE') ?? false
  const canAssign = canUpdate && selectedSubjectId !== context?.subject_id
  const securityLocked = Boolean(editingRole?.assigned_count)
  const knownActions = useMemo(() => new Set(context?.action_vocabulary ?? []), [context])

  const edit = (role: AccessRole) => {
    setEditingId(role.id)
    setDraft({
      role_key: role.role_key, name: role.name, description: role.description,
      clearance: role.clearance, groups: role.groups, allowed_actions: role.allowed_actions,
      denied_actions: role.denied_actions, allowed_system_ids: role.allowed_system_ids,
      allowed_domain_ids: role.allowed_domain_ids, active: role.active,
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
        clearKey(intent); await loadDirectory(); startNew()
      },
    })
  }
  const deactivate = (role: AccessRole) => {
    const intent = `access-role-deactivate:${role.id}:${role.version}`
    requestConfirmation({
      title: `${role.name} Role 비활성화`,
      summary: [role.role_key, `할당 사용자 ${role.assigned_count}명`, '사용 중 Role은 서버가 거부합니다.'],
      execute: async () => { await api.deactivateAccessRole(role); clearKey(intent); await loadDirectory(); startNew() },
    })
  }
  const assign = (roleId: string | null) => {
    if (!selectedMember || !canAssign || !membershipEtag) return
    const role = roles.find((item) => item.id === roleId)
    const intent = `membership-role:${selectedMember.subject_id}:${membershipEtag}:${roleId ?? 'none'}`
    requestConfirmation({
      title: `${selectedMember.display_name} Role ${role ? '할당' : '해제'}`,
      summary: [role?.name ?? 'Role 미할당', membershipEtag, role ? `${role.clearance} · ALLOW ${role.allowed_actions.length}개` : '권한 없음(PUBLIC)'],
      execute: async () => {
        await api.assignMembershipRole(selectedMember.subject_id, roleId, membershipEtag, keyFor(intent, 'membership-role'))
        clearKey(intent); await Promise.all([loadAccess(selectedMember.subject_id), loadDirectory()])
      },
    })
  }

  return <div className="grid gap-3">
    <section className="panel border-l-4 border-l-blue-700 bg-slate-50"><span className="eyebrow">Server-managed RBAC</span><h3 className="mb-1 mt-1">Role 정의 및 사용자 할당</h3><p className="m-0 text-xs leading-5 text-slate-600">Role은 서버에 저장되며 사용자에게 적용될 때 기존 ABAC Access 문서로 변환됩니다. 사용 중 Role의 보안 정의 변경·비활성화는 서버가 거부하므로 먼저 사용자를 다른 Role로 재할당하세요.</p></section>
    <div className="admin-two-column role-access-admin">
      <section className="panel form-stack">
        <div className="section-heading"><div><h3>사용자 Role 할당</h3><p className="muted">계정 생성은 조직 OIDC/IdP에서, 플랫폼 권한은 이 Role로 관리합니다.</p></div><button type="button" className="button button-secondary" onClick={() => void loadDirectory()}>새로고침</button></div>
        <label>사용자<select value={selectedSubjectId} onChange={(event) => setSelectedSubjectId(event.target.value)}>{members.map((member) => <option key={member.subject_id} value={member.subject_id}>{member.display_name} · {member.email ?? 'Email 미제공'}</option>)}</select></label>
        {selectedMember && <dl className="summary-list"><div><dt>현재 Role</dt><dd>{assignedRole?.name ?? '미할당'}</dd></div><div><dt>가입일</dt><dd>{selectedMember.joined_at ? new Date(selectedMember.joined_at).toLocaleDateString() : '—'}</dd></div><div><dt>상태</dt><dd>{selectedMember.membership_active ? 'ACTIVE' : 'INACTIVE'}</dd></div></dl>}
        <label>할당할 Role<select value={assignmentRoleId} onChange={(event) => setAssignmentRoleId(event.target.value)} disabled={!canAssign}><option value="">Role 미할당</option>{roles.filter((role) => role.active).map((role) => <option key={role.id} value={role.id}>{role.name} · {role.clearance}</option>)}</select></label>
        <div className="action-row"><button type="button" className="button" disabled={!canAssign || !assignmentRoleId || assignedRole?.id === assignmentRoleId} onClick={() => assign(assignmentRoleId)}>Role 할당</button><button type="button" className="button button-secondary" disabled={!canAssign || !assignedRole} onClick={() => assign(null)}>Role 해제</button></div>
        {selectedSubjectId === context?.subject_id && <p className="callout">관리자는 자신의 Role을 변경할 수 없습니다. 다른 적격 Admin이 변경해야 합니다.</p>}
      </section>
      <section className="panel form-stack">
        <div className="section-heading"><div><h3>Role 정의</h3><p className="muted">Workspace 공통 권한 그룹을 추가·편집·비활성화합니다.</p></div><button type="button" className="button button-secondary" onClick={startNew}>+ 신규 Role</button></div>
        <div className="compact-list" aria-label="서버 Role 정의">{roles.map((role) => <button type="button" key={role.id} className={editingId === role.id ? 'selected' : ''} onClick={() => edit(role)}><span><strong>{role.name}</strong><small>{role.role_key} · {role.clearance} · 사용자 {role.assigned_count}명</small></span><span className={`badge ${role.active ? '' : 'badge-soft'}`}>{role.active ? 'ACTIVE' : 'INACTIVE'}</span></button>)}{!roles.length && <p className="muted">등록된 Role이 없습니다.</p>}</div>
        <div className="grid gap-2 border-t border-slate-300 pt-3 md:grid-cols-2"><label>Role Key<input value={draft.role_key} onChange={(event) => setDraft({ ...draft, role_key: event.target.value })} pattern="[a-z][a-z0-9-]{1,79}" disabled={editingId !== 'NEW'} placeholder="catalog-reader" /></label><label>Role 이름<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} maxLength={255} /></label></div>
        <label>설명<textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} maxLength={4000} /></label>
        {securityLocked && <p className="callout">{editingRole?.assigned_count}명의 사용자에게 할당되어 보안 정의는 잠겼습니다. 이름·설명만 편집할 수 있습니다.</p>}
        <label>등급<select value={draft.clearance} disabled={securityLocked} onChange={(event) => setDraft({ ...draft, clearance: event.target.value as AccessRoleWrite['clearance'] })}><option>PUBLIC</option><option>INTERNAL</option><option>CONFIDENTIAL</option><option>RESTRICTED</option></select></label>
        <label>그룹<textarea value={groupText} disabled={securityLocked} onChange={(event) => setGroupText(event.target.value)} placeholder="security-administrators" /></label>
        <details className="rounded-enterprise border border-slate-300 bg-slate-50 p-3"><summary className="cursor-pointer text-xs font-black text-navy-900">권한 Action 및 접근 범위</summary><div className="mt-3 grid gap-3"><fieldset className="action-matrix"><legend>Action</legend>{context?.action_vocabulary.map((action) => { const effect = draft.allowed_actions.includes(action) ? 'ALLOW' : draft.denied_actions.includes(action) ? 'DENY' : 'NONE'; return <label key={action}><span>{action}</span><select aria-label={`Role ${action}`} disabled={securityLocked} value={effect} onChange={(event) => setAction(action, event.target.value as 'NONE' | 'ALLOW' | 'DENY')}><option value="NONE">—</option><option value="ALLOW">ALLOW</option><option value="DENY">DENY</option></select></label> })}</fieldset><fieldset className="grid gap-2"><legend>System 접근 범위</legend>{systems.map((system) => <label className="checkbox-line" key={system.system_id}><input type="checkbox" checked={lines(systemText).includes(system.system_id)} disabled={securityLocked || !system.active} onChange={(event) => setSystemScope(system.system_id, event.target.checked)} /><span><strong>{system.name}</strong> <small>{system.code}{system.active ? '' : ' · INACTIVE'}</small></span></label>)}{systems.length === 0 && <small className="muted">등록된 시스템이 없습니다.</small>}</fieldset><label>Domain IDs <small>Domain directory API가 추가되기 전에는 고급 UUID 범위로만 편집합니다.</small><textarea value={domainText} disabled={securityLocked} onChange={(event) => setDomainText(event.target.value)} /></label></div></details>
        <div className="action-row"><button type="button" className="button" disabled={!canUpdate || !draft.role_key || !draft.name.trim()} onClick={saveRole}>{editingRole ? 'Role 저장' : 'Role 생성'}</button>{editingRole && <button type="button" className="button button-secondary" disabled={!canUpdate || editingRole.assigned_count > 0 || !editingRole.active} onClick={() => deactivate(editingRole)}>비활성화</button>}</div>
      </section>
    </div>
  </div>
}
