import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  SystemAssigneeKey,
  SystemAssigneeCandidate,
  SystemAssigneeUpdate,
  SystemDirectoryAssignee,
  SystemDirectoryEntry,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import type { AdminSectionProps } from './MembershipAdmin'

type Responsibility = SystemAssigneeUpdate['responsibility']

interface AssignmentDraft extends SystemAssigneeUpdate {
  key: string
}

const responsibilities: Array<{ id: Responsibility; label: string }> = [
  { id: 'DEVELOPER', label: 'Developer' },
  { id: 'DATA_STEWARD', label: 'Data Steward' },
]

function assignmentKey(value: Pick<SystemAssigneeUpdate, 'subject_id' | 'responsibility'>) {
  return `${value.responsibility}:${value.subject_id}`
}

function toDraft(values: SystemDirectoryAssignee[]): AssignmentDraft[] {
  return values.map((assignment) => ({
    subject_id: assignment.subject_id,
    responsibility: assignment.responsibility,
    priority: assignment.priority,
    key: assignmentKey(assignment),
  }))
}

export function SystemDirectoryAdmin(props: AdminSectionProps) {
  const { api, context, requestConfirmation, keyFor, clearKey, reportError } = props
  const [systems, setSystems] = useState<SystemDirectoryEntry[]>([])
  const [systemQuery, setSystemQuery] = useState('')
  const [appliedSystemQuery, setAppliedSystemQuery] = useState('')
  const [systemCursor, setSystemCursor] = useState<string>()
  const [systemCursorHistory, setSystemCursorHistory] = useState<string[]>([])
  const [nextSystemCursor, setNextSystemCursor] = useState<string | null>(null)
  const [systemPageNumber, setSystemPageNumber] = useState(1)
  const [selectedId, setSelectedId] = useState('')
  const [assignees, setAssignees] = useState<SystemDirectoryAssignee[]>([])
  const [assigneeVersion, setAssigneeVersion] = useState(0)
  const [assigneeCursor, setAssigneeCursor] = useState<string>()
  const [assigneeCursorHistory, setAssigneeCursorHistory] = useState<string[]>([])
  const [nextAssigneeCursor, setNextAssigneeCursor] = useState<string | null>(null)
  const [assigneePageNumber, setAssigneePageNumber] = useState(1)
  const [assigneeReload, setAssigneeReload] = useState(0)
  const [candidates, setCandidates] = useState<Record<Responsibility, SystemAssigneeCandidate[]>>({
    DEVELOPER: [],
    DATA_STEWARD: [],
  })
  const [candidateQueries, setCandidateQueries] = useState<Record<Responsibility, string>>({
    DEVELOPER: '',
    DATA_STEWARD: '',
  })
  const [draft, setDraft] = useState<AssignmentDraft[]>([])
  const [editingAssignmentKeys, setEditingAssignmentKeys] = useState<Set<string>>(() => new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>()
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState({ code: '', name: '', description: '' })
  const [createValidationError, setCreateValidationError] = useState('')
  const systemGeneration = useRef(0)
  const assigneeGeneration = useRef(0)
  const candidateGeneration = useRef<Record<Responsibility, number>>({
    DEVELOPER: 0,
    DATA_STEWARD: 0,
  })

  const loadSystems = useCallback(async (signal?: AbortSignal) => {
    const generation = ++systemGeneration.current
    setLoading(true)
    setError(undefined)
    try {
      const page = await api.listSystemPage({
        query: appliedSystemQuery || undefined,
        cursor: systemCursor,
        signal,
      })
      if (signal?.aborted || generation !== systemGeneration.current) return
      setSystems(page.items)
      setNextSystemCursor(page.nextCursor)
      setSelectedId((current) => (
        current && page.items.some((item) => item.system_id === current)
          ? current
          : page.items[0]?.system_id ?? ''
      ))
    } catch (next) {
      if (!signal?.aborted && generation === systemGeneration.current) {
        setError(next)
        reportError(next)
      }
    } finally {
      if (generation === systemGeneration.current) setLoading(false)
    }
  }, [api, appliedSystemQuery, reportError, systemCursor])

  const loadAssignees = useCallback(async (signal?: AbortSignal) => {
    void assigneeReload
    if (!selectedId) {
      setAssignees([])
      setDraft([])
      setAssigneeVersion(0)
      return
    }
    const generation = ++assigneeGeneration.current
    try {
      const page = await api.listSystemAssigneePage(selectedId, {
        cursor: assigneeCursor,
        signal,
      })
      if (signal?.aborted || generation !== assigneeGeneration.current) return
      setAssignees(page.items)
      setDraft(toDraft(page.items))
      setEditingAssignmentKeys(new Set())
      setAssigneeVersion(page.system_version)
      setNextAssigneeCursor(page.page.next_cursor)
    } catch (next) {
      if (!signal?.aborted && generation === assigneeGeneration.current) {
        setError(next)
        reportError(next)
      }
    }
  }, [api, assigneeCursor, assigneeReload, reportError, selectedId])

  const loadCandidates = useCallback(async (
    responsibility: Responsibility,
    signal?: AbortSignal,
  ) => {
    const generation = ++candidateGeneration.current[responsibility]
    try {
      const page = await api.listSystemAssigneeCandidates(
        candidateQueries[responsibility].trim() || undefined,
        signal,
      )
      if (signal?.aborted || generation !== candidateGeneration.current[responsibility]) return
      setCandidates((current) => ({ ...current, [responsibility]: page.items }))
    } catch (next) {
      if (!signal?.aborted && generation === candidateGeneration.current[responsibility]) {
        reportError(next)
      }
    }
  }, [api, candidateQueries, reportError])

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
    void loadSystems(controller.signal)
    return () => {
      controller.abort()
      systemGeneration.current += 1
    }
  }, [loadSystems])
  useEffect(() => {
    setAssigneeCursor(undefined)
    setAssigneeCursorHistory([])
    setAssigneePageNumber(1)
  }, [selectedId])
  useEffect(() => {
    const controller = new AbortController()
    void loadAssignees(controller.signal)
    return () => {
      controller.abort()
      assigneeGeneration.current += 1
    }
  }, [loadAssignees])
  useEffect(() => {
    const generation = candidateGeneration.current
    const controllers = responsibilities.map(({ id }) => {
      const controller = new AbortController()
      const timer = window.setTimeout(
        () => void loadCandidates(id, controller.signal),
        candidateQueries[id] ? 250 : 0,
      )
      return { controller, id, timer }
    })
    return () => {
      controllers.forEach(({ controller, id, timer }) => {
        window.clearTimeout(timer)
        controller.abort()
        generation[id] += 1
      })
    }
  }, [candidateQueries, loadCandidates])

  const selected = useMemo(
    () => systems.find((system) => system.system_id === selectedId),
    [selectedId, systems],
  )
  const canUpdate = context?.allowed_operations.includes('SYSTEM_ASSIGNMENT_UPDATE') ?? false
  const originalByKey = useMemo(
    () => new Map(assignees.map((assignment) => [assignmentKey(assignment), assignment])),
    [assignees],
  )
  const draftByKey = useMemo(
    () => new Map(draft.filter((item) => item.subject_id).map((item) => [assignmentKey(item), item])),
    [draft],
  )
  const removals: SystemAssigneeKey[] = [...originalByKey.values()]
    .filter((assignment) => !draftByKey.has(assignmentKey(assignment)))
    .map((assignment) => ({
      subject_id: assignment.subject_id,
      responsibility: assignment.responsibility,
    }))
  const upserts: SystemAssigneeUpdate[] = [...draftByKey.values()]
    .filter((assignment) => (
      !originalByKey.has(assignmentKey(assignment))
      || originalByKey.get(assignmentKey(assignment))?.priority !== assignment.priority
    ))
    .map(({ subject_id, responsibility, priority }) => ({
      subject_id,
      responsibility,
      priority,
    }))
  const draftValid = draft.every((item) => (
    Boolean(item.subject_id)
    && Number.isInteger(item.priority)
    && item.priority >= 1
    && item.priority <= 999
  ))
    && new Set(draft.map(assignmentKey)).size === draft.length
    && responsibilities.every(({ id }) => {
      const priorities = draft.filter((item) => item.responsibility === id).map((item) => item.priority)
      return new Set(priorities).size === priorities.length
    })
  const changed = upserts.length > 0 || removals.length > 0

  const updateDraft = (
    key: string,
    patch: Partial<Pick<AssignmentDraft, 'subject_id' | 'priority'>>,
  ) => setDraft((current) => current.map((item) => (
    item.key === key ? { ...item, ...patch } : item
  )))
  const addAssignment = (responsibility: Responsibility) => {
    setDraft((current) => {
      const lane = current.filter((item) => item.responsibility === responsibility)
      return [...current, {
        key: `${responsibility}:new:${crypto.randomUUID()}`,
        subject_id: '',
        responsibility,
        priority: Math.max(0, ...lane.map((item) => item.priority)) + 1,
      }]
    })
  }
  const removeAssignment = (key: string) => {
    setDraft((current) => current.filter((value) => value.key !== key))
    setEditingAssignmentKeys((current) => {
      const next = new Set(current)
      next.delete(key)
      return next
    })
  }
  const save = () => {
    if (!canUpdate || !selected || !assigneeVersion || !draftValid || !changed) return
    const intent = `system-assignees-patch:${selected.system_id}:${assigneeVersion}:${JSON.stringify({ upserts, removals })}`
    requestConfirmation({
      title: '시스템 담당자 변경',
      summary: [
        `${selected.name} (${selected.code})`,
        `ETag ${assigneeVersion}`,
        `추가·변경 ${upserts.length}건 · 제거 ${removals.length}건`,
      ],
      execute: async () => {
        await api.patchSystemAssignees(
          selected.system_id,
          upserts,
          removals,
          assigneeVersion,
          keyFor(intent, 'admin-system-assignees-patch'),
        )
        clearKey(intent)
        setAssigneeCursor(undefined)
        setAssigneeCursorHistory([])
        setAssigneePageNumber(1)
        setAssigneeReload((current) => current + 1)
        await loadSystems()
      },
    })
  }

  const handleCreateSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    if (!canUpdate) return
    setCreateValidationError('')
    if (!/^[A-Za-z][A-Za-z0-9_-]{1,99}$/.test(createForm.code)) {
      setCreateValidationError('시스템 코드는 영문자로 시작하고 2~100자의 영숫자, -, _ 만 허용됩니다.')
      return
    }
    const payload = {
      code: createForm.code.trim(),
      name: createForm.name.trim(),
      description: createForm.description.trim(),
    }
    const intent = `system-create:${JSON.stringify(payload)}`
    requestConfirmation({
      title: '신규 시스템 생성',
      summary: [payload.code, payload.name, '현재 Workspace의 시스템 정본에 추가합니다.'],
      execute: async () => {
        await api.createSystem(payload, keyFor(intent, 'admin-system-create'))
        clearKey(intent)
        setCreateOpen(false)
        setCreateForm({ code: '', name: '', description: '' })
        await loadSystems()
      },
    })
  }

  return <section className="panel admin-system-directory">
    <div className="section-heading"><div><h3>시스템 권한 매핑</h3><p className="muted">시스템과 담당자를 각각 서버 페이지로 읽고, 버전 고정 delta로 변경합니다.</p></div><div className="action-row"><button className="button" disabled={!canUpdate} onClick={() => { setCreateOpen(true); setCreateValidationError('') }} type="button">시스템 추가</button><button className="button button-secondary" onClick={() => void loadSystems()} type="button">새로고침</button></div></div>
    <label className="mb-3 block max-w-md text-xs font-bold">시스템 검색<input type="search" value={systemQuery} onChange={(event) => setSystemQuery(event.target.value)} placeholder="시스템명 또는 코드" /></label>
    <DenseDataTable
      caption="워크스페이스 시스템 목록"
      columns={[
        { accessorKey: 'code', header: '코드', size: 125 },
        { accessorKey: 'name', header: '시스템명', size: 170, cell: ({ row }) => <strong>{row.original.name}</strong> },
        { accessorKey: 'description', header: '시스템 설명', size: 260, cell: ({ row }) => row.original.description || '설명 없음' },
        { accessorKey: 'assignee_count', header: '담당자 수', size: 100 },
        { id: 'schemas', header: 'Target Schemas', size: 160, cell: () => <button type="button" className="button button-secondary" disabled title="시스템-스키마 매핑 조회 API가 아직 없습니다.">스키마 조회</button> },
        { id: 'state', header: '상태', size: 76, cell: ({ row }) => <span className="badge">{row.original.active ? 'ACTIVE' : 'INACTIVE'}</span> },
      ]}
      data={systems}
      emptyMessage="현재 검색 페이지에 등록된 시스템이 없습니다."
      getRowId={(system) => system.system_id}
      loading={loading}
      onRowActivate={(system) => {
        setAssigneeCursor(undefined)
        setAssigneeCursorHistory([])
        setAssigneePageNumber(1)
        setSelectedId(system.system_id)
      }}
      selectedRowId={selectedId}
    />
    {(systemCursorHistory.length > 0 || nextSystemCursor) && <PageControls
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
    />}
    {selected && <section className="admin-system-assignment" aria-labelledby="system-assignment-title">
      <header><div><span className="eyebrow">{selected.code}</span><h4 id="system-assignment-title">{selected.name} 담당자</h4></div><span className="badge">v{assigneeVersion || selected.version}</span></header>
      <p className="muted">Engineer/Steward, Manager, Admin 프로필만 서버 검색 결과에 포함됩니다. 저장 시 현재 프로필과 활성 멤버십을 다시 검증합니다.</p>
      <div className="admin-system-assignment-grid">
        {responsibilities.map(({ id, label }) => {
          const assignments = draft.filter((item) => item.responsibility === id)
          return <fieldset key={id}><legend>{label}</legend>
            <div className="mb-2 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"><label className="grid gap-1 text-xs font-bold">{label} 검색<input type="search" value={candidateQueries[id]} onChange={(event) => setCandidateQueries((current) => ({ ...current, [id]: event.target.value }))} placeholder="이름 또는 이메일" /></label><button className="button button-secondary button-compact" disabled={!canUpdate || draft.length >= 100} onClick={() => addAssignment(id)} type="button">+ {label} 추가</button></div>
            {assignments.map((assignment) => <div className="admin-system-assignment-row" key={assignment.key}>
              <label><span className="sr-only">{label} 담당자</span><select disabled={!canUpdate || (originalByKey.has(assignment.key) && !editingAssignmentKeys.has(assignment.key))} onChange={(event) => updateDraft(assignment.key, { subject_id: event.target.value })} value={assignment.subject_id}>
                <option value="">멤버 선택</option>
                {candidates[id].map((candidate) => <option key={candidate.subject_id} value={candidate.subject_id}>{candidate.display_name} · {candidate.email ?? '이메일 없음'} · {candidate.tier}</option>)}
                {assignment.subject_id && !candidates[id].some((candidate) => candidate.subject_id === assignment.subject_id) && <option value={assignment.subject_id}>{assignees.find((item) => assignmentKey(item) === assignment.key)?.display_name ?? '현재 담당자'} · 현재 검색 결과 외</option>}
              </select></label>
              <label><span className="sr-only">{label} 우선순위</span><input disabled={!canUpdate} max={999} min={1} onChange={(event) => updateDraft(assignment.key, { priority: Number(event.target.value) })} type="number" value={assignment.priority} /></label>
              <div className="flex gap-1">{originalByKey.has(assignment.key) && <button aria-label={`${label} 담당자 변경`} className="button button-secondary button-compact" disabled={!canUpdate} onClick={() => setEditingAssignmentKeys((current) => new Set(current).add(assignment.key))} type="button">변경</button>}<button aria-label={`${label} 담당자 삭제`} className="button button-secondary button-compact" disabled={!canUpdate} onClick={() => removeAssignment(assignment.key)} type="button">삭제</button></div>
            </div>)}
          </fieldset>
        })}
      </div>
      {(assigneeCursorHistory.length > 0 || nextAssigneeCursor) && <PageControls
        pageNumber={assigneePageNumber}
        canPrevious={assigneeCursorHistory.length > 0}
        canNext={Boolean(nextAssigneeCursor)}
        previous={() => {
          const previous = assigneeCursorHistory.at(-1)
          setAssigneeCursorHistory((current) => current.slice(0, -1))
          setAssigneeCursor(previous || undefined)
          setAssigneePageNumber((current) => Math.max(1, current - 1))
        }}
        next={() => {
          if (!nextAssigneeCursor) return
          setAssigneeCursorHistory((current) => [...current.slice(-49), assigneeCursor ?? ''])
          setAssigneeCursor(nextAssigneeCursor)
          setAssigneePageNumber((current) => current + 1)
        }}
      />}
      {canUpdate ? <div className="action-row"><button className="button" disabled={!draftValid || !changed} onClick={() => void save()} type="button">변경사항 저장</button><button className="button button-danger" disabled title="시스템 정본 삭제 API와 참조 무결성 검토 계약이 아직 없습니다." type="button">시스템 삭제</button>{!draftValid && <small className="muted">담당자·우선순위가 중복되거나 유효하지 않습니다.</small>}</div> : <p className="callout">서버가 현재 세션에 시스템 담당자 변경 권한을 허용하지 않았습니다.</p>}
    </section>}
    <Dialog open={createOpen} title="시스템 추가" size="medium" onRequestClose={() => setCreateOpen(false)}>
      <form id="system-create-form" onSubmit={handleCreateSubmit} className="grid gap-3">
        <label className="block text-sm font-bold">시스템 코드
          <input className="mt-1 block w-full" maxLength={100} onChange={(e) => setCreateForm({ ...createForm, code: e.target.value })} pattern="^[A-Za-z][A-Za-z0-9_-]{1,99}$" required type="text" value={createForm.code} placeholder="예: system-code_123" />
        </label>
        {createValidationError && <div className="text-red-600 text-xs mt-[-8px]">{createValidationError}</div>}
        <label className="block text-sm font-bold">시스템 이름
          <input className="mt-1 block w-full" maxLength={255} onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })} required type="text" value={createForm.name} />
        </label>
        <label className="block text-sm font-bold">설명
          <textarea className="mt-1 block w-full h-24" maxLength={4000} onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })} value={createForm.description} />
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <button className="button button-secondary" onClick={() => setCreateOpen(false)} type="button">취소</button>
          <button className="button" type="submit">저장</button>
        </div>
      </form>
    </Dialog>
    <ErrorNotice error={error} />
  </section>
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
  return <div className="mt-3 flex items-center justify-end gap-2">
    <span className="text-xs text-slate-600">페이지 {pageNumber}</span>
    <button type="button" className="button button-secondary" disabled={!canPrevious} onClick={previous}>이전</button>
    <button type="button" className="button button-secondary" disabled={!canNext} onClick={next}>다음</button>
  </div>
}
