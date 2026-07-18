import { useCallback, useEffect, useMemo, useState } from 'react'
import type { MembershipAccessDocument, WorkspaceMembershipSummary } from '../../api/types'
import type { AdminSectionProps } from './MembershipAdmin'

type RoleTemplate = {
  id: string
  label: string
  clearance: MembershipAccessDocument['clearance']
  actions: readonly string[]
  description: string
}

const templates: readonly RoleTemplate[] = [
  {
    id: 'CATALOG_READER', label: '카탈로그 조회자', clearance: 'PUBLIC',
    actions: ['catalog.search', 'catalog.read', 'catalog.lineage.read'],
    description: '검색·상세·계보를 읽는 기본 역할입니다.',
  },
  {
    id: 'DATA_STEWARD', label: '데이터 스튜어드', clearance: 'INTERNAL',
    actions: ['catalog.search', 'catalog.read', 'catalog.lineage.read', 'registration.read', 'registration.create', 'registration.validate', 'change.create', 'change.read', 'change.edit'],
    description: '메타데이터 등록 제안과 변경 요청을 작성·보완합니다.',
  },
  {
    id: 'GOVERNANCE_REVIEWER', label: '거버넌스 검토자', clearance: 'CONFIDENTIAL',
    actions: ['catalog.search', 'catalog.read', 'catalog.lineage.read', 'change.read', 'change.review', 'change.approve'],
    description: '권한 범위 안의 변경 요청을 독립적으로 검토·승인합니다.',
  },
]

function roleGroup(id: string) { return `datariver:role:${id}` }

function templateFromAccess(access: MembershipAccessDocument): RoleTemplate | undefined {
  return templates.find((template) => access.groups.includes(roleGroup(template.id)))
}

/**
 * A small RBAC facade over the canonical membership access document.
 * It never exposes a provider credential or mutates DataHub policy directly;
 * the normal server-side ABAC decision remains the enforcement point.
 */
export function RoleAccessAdmin(props: AdminSectionProps) {
  const { api, context, requestConfirmation, keyFor, clearKey, reportError } = props
  const [members, setMembers] = useState<WorkspaceMembershipSummary[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [access, setAccess] = useState<MembershipAccessDocument>()
  const [etag, setEtag] = useState('')

  const loadMembers = useCallback(async () => {
    try {
      const values = await api.listMemberships()
      setMembers(values)
      setSelectedId((current) => current || values[0]?.subject_id || '')
    } catch (error) { reportError(error) }
  }, [api, reportError])
  const loadAccess = useCallback(async (subjectId: string) => {
    if (!subjectId) return
    try {
      const value = await api.getMembershipAccess(subjectId)
      setAccess(value.access); setEtag(value.etag)
    } catch (error) { reportError(error) }
  }, [api, reportError])

  const canRead = context?.allowed_operations.includes('MEMBERSHIP_ACCESS_READ') ?? false
  const canUpdate = context?.allowed_operations.includes('MEMBERSHIP_ACCESS_UPDATE') ?? false
  useEffect(() => { if (canRead) void loadMembers() }, [canRead, loadMembers])
  useEffect(() => { void loadAccess(selectedId) }, [loadAccess, selectedId])
  const selected = useMemo(() => members.find((member) => member.subject_id === selectedId), [members, selectedId])
  const assigned = access ? templateFromAccess(access) : undefined

  const applyTemplate = (template: RoleTemplate) => {
    if (!access || !selected) return
    const knownActions = new Set(context?.action_vocabulary ?? [])
    const next: MembershipAccessDocument = {
      ...access,
      clearance: template.clearance,
      groups: [...access.groups.filter((group) => !group.startsWith('datariver:role:')), roleGroup(template.id)],
      // Only action names declared by the live server context are emitted.
      allowed_actions: template.actions.filter((action) => knownActions.has(action)),
      denied_actions: access.denied_actions.filter((action) => !template.actions.includes(action)),
    }
    const intent = `role-template:${selectedId}:${etag}:${template.id}:${JSON.stringify(next)}`
    requestConfirmation({
      title: `${template.label} 역할 적용`,
      summary: [selected.display_name, template.label, `ETag ${etag}`, `허용 Action ${next.allowed_actions.length}개`],
      execute: async () => {
        await api.updateMembership(selectedId, next, etag, keyFor(intent, 'role-template'))
        clearKey(intent)
        await Promise.all([loadMembers(), loadAccess(selectedId)])
      },
    })
  }

  const clearTemplate = () => {
    if (!access || !selected || !assigned) return
    const next: MembershipAccessDocument = {
      ...access,
      groups: access.groups.filter((group) => !group.startsWith('datariver:role:')),
    }
    const intent = `role-template-clear:${selectedId}:${etag}:${JSON.stringify(next)}`
    requestConfirmation({
      title: `${assigned.label} 역할 해제`,
      summary: [selected.display_name, 'Role 그룹만 해제', '세부 Access 문서는 유지', `ETag ${etag}`],
      execute: async () => {
        await api.updateMembership(selectedId, next, etag, keyFor(intent, 'role-template-clear'))
        clearKey(intent)
        await Promise.all([loadMembers(), loadAccess(selectedId)])
      },
    })
  }

  return <div className="admin-two-column role-access-admin">
    <section className="panel">
      <div className="section-heading"><div><h3>사용자 Role</h3><p className="muted">실제 워크스페이스 멤버십을 선택합니다.</p></div><button className="button button-secondary" onClick={() => void loadMembers()}>새로고침</button></div>
      <div className="compact-list" aria-label="Role 대상 사용자">
        {members.map((member) => <button key={member.subject_id} className={selectedId === member.subject_id ? 'selected' : ''} onClick={() => setSelectedId(member.subject_id)}><span><strong>{member.display_name}</strong><small>{member.job_function ?? '—'} · {member.clearance}</small></span><span className="badge badge-soft">v{member.membership_version}</span></button>)}
        {!members.length && <p className="muted">조회 가능한 멤버가 없습니다.</p>}
      </div>
    </section>
    <section className="panel form-stack" aria-live="polite">
      <div><span className="eyebrow">Role-based access</span><h3>간편 권한 관리</h3></div>
      {!access || !selected ? <p className="muted">사용자를 선택하면 서버에서 현재 Access 문서를 확인합니다.</p> : <>
        <dl className="summary-list"><div><dt>사용자</dt><dd>{selected.display_name}</dd></div><div><dt>현재 Role</dt><dd>{assigned?.label ?? '사용자 지정 Access'}</dd></div><div><dt>등급</dt><dd>{access.clearance}</dd></div><div><dt>허용 Action</dt><dd>{access.allowed_actions.length}개</dd></div></dl>
        <p className="callout">간편 Role은 멤버십 Access 문서에만 반영됩니다. DataHub Policy를 브라우저에서 직접 변경하지 않으며, 데이터 접근 판단은 서버 ABAC와 분류정책이 계속 수행합니다.</p>
        {assigned && <button type="button" className="button button-secondary" disabled={!canUpdate} onClick={clearTemplate}>현재 Role 해제</button>}
        <div className="role-template-grid">
          {templates.map((template) => <article key={template.id} className={assigned?.id === template.id ? 'selected' : ''}><span className="badge">{template.clearance}</span><h4>{template.label}</h4><p>{template.description}</p><small>{template.actions.filter((action) => context?.action_vocabulary.includes(action)).join(' · ') || '서버 Action 동기화 필요'}</small><button type="button" className="button button-secondary" disabled={!canUpdate} onClick={() => applyTemplate(template)}>이 Role 적용</button></article>)}
        </div>
        {!canUpdate && <p className="callout">현재 세션에는 Role 변경 권한이 없습니다. 서버가 발급한 관리자 권한으로 다시 인증하세요.</p>}
      </>}
    </section>
  </div>
}
