import { useCallback, useEffect, useMemo, useState } from 'react'
import type {
  SystemAssigneeUpdate,
  SystemDirectoryEntry,
  WorkspaceMembershipSummary,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import type { AdminSectionProps } from './MembershipAdmin'

type Responsibility = SystemAssigneeUpdate['responsibility']

interface AssignmentDraft extends SystemAssigneeUpdate {
  key: string
}

const responsibilities: Array<{ id: Responsibility; label: string }> = [
  { id: 'DEVELOPER', label: 'Developer' },
  { id: 'DATA_STEWARD', label: 'Data Steward' },
]

function assigneesFor(system: SystemDirectoryEntry, responsibility: Responsibility) {
  const values = system.assignees.filter((value) => value.responsibility === responsibility)
  return values.length
    ? values.map((value) => `${value.priority}. ${value.display_name}${value.active ? '' : ' (inactive)'}`).join(', ')
    : '미배정'
}

function toDraft(system: SystemDirectoryEntry | undefined): AssignmentDraft[] {
  return (system?.assignees ?? []).map((assignment, index) => ({
    subject_id: assignment.subject_id,
    responsibility: assignment.responsibility,
    priority: assignment.priority,
    key: `${assignment.responsibility}:${assignment.subject_id}:${index}`,
  }))
}

function nextPriority(draft: AssignmentDraft[], responsibility: Responsibility) {
  return Math.max(0, ...draft.filter((item) => item.responsibility === responsibility).map((item) => item.priority)) + 1
}

function unique<T>(values: T[]) {
  return new Set(values).size === values.length
}

export function SystemDirectoryAdmin(props: AdminSectionProps) {
  const { api, context, requestConfirmation, keyFor, clearKey, reportError } = props
  const [systems, setSystems] = useState<SystemDirectoryEntry[]>([])
  const [members, setMembers] = useState<WorkspaceMembershipSummary[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [draft, setDraft] = useState<AssignmentDraft[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>()

  const load = useCallback(async () => {
    setLoading(true); setError(undefined)
    try {
      const [nextSystems, nextMembers] = await Promise.all([api.listSystems(), api.listMemberships()])
      setSystems(nextSystems)
      setMembers(nextMembers)
      setSelectedId((current) => current && nextSystems.some((item) => item.system_id === current)
        ? current
        : nextSystems[0]?.system_id ?? '')
    } catch (next) { setError(next); reportError(next) } finally { setLoading(false) }
  }, [api, reportError])

  useEffect(() => { void load() }, [load])
  const selected = useMemo(
    () => systems.find((system) => system.system_id === selectedId),
    [selectedId, systems],
  )
  useEffect(() => { setDraft(toDraft(selected)) }, [selected])

  const canUpdate = context?.allowed_operations.includes('SYSTEM_ASSIGNMENT_UPDATE') ?? false
  const eligibleMembers = useMemo(
    () => members.filter((member) => (
      member.subject_active && member.membership_active && member.job_function !== 'SERVICE_ACCOUNT'
    )),
    [members],
  )
  const valid = useMemo(() => responsibilities.every(({ id }) => {
    const items = draft.filter((item) => item.responsibility === id)
    const priorities = items.map((item) => item.priority)
    return items.length >= 1
      && priorities.every((priority) => Number.isInteger(priority) && priority >= 1 && priority <= 999)
      && Math.min(...priorities) === 1
      && unique(priorities)
      && unique(items.map((item) => item.subject_id))
      && items.every((item) => eligibleMembers.some((member) => member.subject_id === item.subject_id))
  }), [draft, eligibleMembers])

  const updateDraft = (key: string, patch: Partial<Pick<AssignmentDraft, 'subject_id' | 'priority'>>) => {
    setDraft((current) => current.map((item) => item.key === key ? { ...item, ...patch } : item))
  }
  const addAssignment = (responsibility: Responsibility) => {
    setDraft((current) => [...current, {
      key: `${responsibility}:new:${crypto.randomUUID()}`,
      subject_id: '',
      responsibility,
      priority: nextPriority(current, responsibility),
    }])
  }
  const removeAssignment = (key: string) => {
    setDraft((current) => {
      const item = current.find((value) => value.key === key)
      if (!item || current.filter((value) => value.responsibility === item.responsibility).length <= 1) return current
      return current.filter((value) => value.key !== key)
    })
  }
  const save = () => {
    if (!selected || !valid) return
    const assignees: SystemAssigneeUpdate[] = draft.map((assignment) => ({
      subject_id: assignment.subject_id,
      responsibility: assignment.responsibility,
      priority: assignment.priority,
    }))
    const intent = `system-assignees:${selected.system_id}:${selected.version}:${JSON.stringify(assignees)}`
    requestConfirmation({
      title: '시스템 담당자 배정 변경',
      summary: [
        `${selected.name} (${selected.code})`,
        `ETag ${selected.version}`,
        `Developer ${assignees.filter((item) => item.responsibility === 'DEVELOPER').length}명 · Data Steward ${assignees.filter((item) => item.responsibility === 'DATA_STEWARD').length}명`,
      ],
      execute: async () => {
        await api.updateSystemAssignees(
          selected.system_id,
          assignees,
          selected.version,
          keyFor(intent, 'admin-system-assignees'),
        )
        clearKey(intent)
        await load()
      },
    })
  }

  return <section className="panel admin-system-directory">
    <div className="section-heading"><div><h3>시스템 권한 매핑</h3><p className="muted">정본 시스템의 Developer·Data Steward 우선순위를 표시하고, WebAuthn 인증을 거쳐 변경합니다.</p></div><div className="action-row"><button className="button" disabled title="시스템 정본 생성 API가 아직 없습니다." type="button">신규 시스템 추가</button><button className="button button-secondary" onClick={() => void load()} type="button">새로고침</button></div></div>
    <DenseDataTable
      caption="워크스페이스 시스템 목록"
      columns={[
        { accessorKey: 'code', header: '코드', size: 125 },
        { accessorKey: 'name', header: '시스템', size: 190, cell: ({ row }) => <><strong>{row.original.name}</strong><small>{row.original.description || '설명 없음'}</small></> },
        { id: 'schemas', header: 'Target Schemas', size: 160, cell: () => <button type="button" className="button button-secondary" disabled title="시스템-스키마 매핑 조회 API가 아직 없습니다.">스키마 조회</button> },
        { id: 'developers', header: 'Developer', size: 260, cell: ({ row }) => assigneesFor(row.original, 'DEVELOPER') },
        { id: 'stewards', header: 'Data Steward', size: 260, cell: ({ row }) => assigneesFor(row.original, 'DATA_STEWARD') },
        { id: 'state', header: '상태', size: 76, cell: ({ row }) => <span className="badge">{row.original.active ? 'ACTIVE' : 'INACTIVE'}</span> },
      ]}
      data={systems}
      emptyMessage="현재 워크스페이스에 등록된 시스템이 없습니다."
      getRowId={(system) => system.system_id}
      loading={loading}
      onRowActivate={(system) => setSelectedId(system.system_id)}
      selectedRowId={selectedId}
    />
    {selected && <section className="admin-system-assignment" aria-labelledby="system-assignment-title">
      <header><div><span className="eyebrow">{selected.code}</span><h4 id="system-assignment-title">{selected.name} 담당자</h4></div><span className="badge">v{selected.version}</span></header>
      <p className="muted">각 역할은 최소 한 명이며, 우선순위는 역할별로 1부터 중복 없이 지정합니다. 활성 Workspace 멤버만 저장할 수 있습니다.</p>
      <div className="admin-system-assignment-grid">
        {responsibilities.map(({ id, label }) => {
          const assignments = draft.filter((item) => item.responsibility === id)
          return <fieldset key={id}><legend>{label}</legend>
            {assignments.map((assignment) => <div className="admin-system-assignment-row" key={assignment.key}>
              <label><span className="sr-only">{label} 담당자</span><select disabled={!canUpdate} onChange={(event) => updateDraft(assignment.key, { subject_id: event.target.value })} value={assignment.subject_id}>
                <option value="">멤버 선택</option>
                {members.map((member) => {
                  const isSelectedElsewhere = draft.some((item) => item.key !== assignment.key && item.responsibility === id && item.subject_id === member.subject_id)
                  const eligible = eligibleMembers.some((candidate) => candidate.subject_id === member.subject_id)
                  return <option disabled={!eligible || isSelectedElsewhere} key={member.subject_id} value={member.subject_id}>{member.display_name}{eligible ? '' : ' (비활성/서비스 계정)'}</option>
                })}
              </select></label>
              <label><span className="sr-only">{label} 우선순위</span><input disabled={!canUpdate} max={999} min={1} onChange={(event) => updateDraft(assignment.key, { priority: Number(event.target.value) })} type="number" value={assignment.priority} /></label>
              <button aria-label={`${label} 담당자 제거`} className="button button-secondary button-compact" disabled={!canUpdate || assignments.length <= 1} onClick={() => removeAssignment(assignment.key)} type="button">제거</button>
            </div>)}
            <button className="button button-secondary button-compact" disabled={!canUpdate || eligibleMembers.length === 0} onClick={() => addAssignment(id)} type="button">+ {label} 추가</button>
          </fieldset>
        })}
      </div>
      {canUpdate ? <div className="action-row"><button className="button" disabled={!valid} onClick={save} type="button">설정 저장</button><button className="button button-danger" disabled title="시스템 정본 삭제 API와 참조 무결성 검토 계약이 아직 없습니다." type="button">시스템 삭제</button>{!valid && <small className="muted">두 역할에 각각 활성 담당자와 유효한 우선순위가 필요합니다.</small>}</div> : <p className="callout">담당자 변경은 보안키 인증(HARDWARE_WEBAUTHN) 후에만 활성화됩니다.</p>}
    </section>}
    <ErrorNotice error={error} />
  </section>
}
