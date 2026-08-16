import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from 'react'
import type {
  SystemAssigneeKey,
  SystemAssigneeCandidate,
  SystemAssigneeUpdate,
  SystemDirectoryAssignee,
  SystemDirectoryEntry,
  TableSecurityGrade,
  TableSystemMappingCandidate,
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
  const [editOpen, setEditOpen] = useState(false)
  const [editForm, setEditForm] = useState({ name: '', description: '' })
  const [schemaOpen, setSchemaOpen] = useState(false)
  const [schemaSystem, setSchemaSystem] = useState<SystemDirectoryEntry>()
  const [schemaCandidates, setSchemaCandidates] = useState<TableSystemMappingCandidate[]>([])
  const [schemaSystemVersion, setSchemaSystemVersion] = useState(0)
  const [schemaQuery, setSchemaQuery] = useState('')
  const [appliedSchemaQuery, setAppliedSchemaQuery] = useState('')
  const [schemaFilter, setSchemaFilter] = useState('')
  const [systemFilter, setSystemFilter] = useState('')
  const [securityGradeFilter, setSecurityGradeFilter] = useState<TableSecurityGrade | ''>('')
  const [availableSchemas, setAvailableSchemas] = useState<string[]>([])
  const [selectedTableIds, setSelectedTableIds] = useState<Set<string>>(() => new Set())
  const [selectedSystemIds, setSelectedSystemIds] = useState<Set<string>>(() => new Set())
  const [mappingAction, setMappingAction] = useState<'ASSIGN' | 'REMOVE'>('ASSIGN')
  const [selectionComplete, setSelectionComplete] = useState(true)
  const [lastSelectedIndex, setLastSelectedIndex] = useState<number>()
  const [schemaReason, setSchemaReason] = useState('')
  const [schemaLoading, setSchemaLoading] = useState(false)
  const systemGeneration = useRef(0)
  const assigneeGeneration = useRef(0)
  const schemaCandidateGeneration = useRef(0)
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

  const loadSchemaCandidates = useCallback(async (signal?: AbortSignal) => {
    if (!schemaOpen || !schemaSystem) return
    const generation = ++schemaCandidateGeneration.current
    setSchemaLoading(true)
    try {
      const page = await api.listTableSystemMappings({
        query: appliedSchemaQuery || undefined,
        schema: schemaFilter || undefined,
        systemId: systemFilter || undefined,
        securityGrade: securityGradeFilter || undefined,
        signal,
      })
      if (signal?.aborted || generation !== schemaCandidateGeneration.current) return
      setSchemaCandidates(page.items)
      setSchemaSystemVersion(page.version)
      setAvailableSchemas(page.schemas)
      setSelectionComplete(page.selection_complete)
      setSelectedTableIds((current) => new Set([...current].filter((id) => page.items.some((item) => item.table_identity === id))))
      setLastSelectedIndex(undefined)
    } catch (next) {
      if (!signal?.aborted && generation === schemaCandidateGeneration.current) {
        setError(next)
        reportError(next)
      }
    } finally {
      if (generation === schemaCandidateGeneration.current) setSchemaLoading(false)
    }
  }, [api, appliedSchemaQuery, reportError, schemaFilter, schemaOpen, schemaSystem, securityGradeFilter, systemFilter])

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
  useEffect(() => {
    const timer = window.setTimeout(() => setAppliedSchemaQuery(schemaQuery.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [schemaQuery])
  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(
      () => void loadSchemaCandidates(controller.signal),
      appliedSchemaQuery ? 250 : 0,
    )
    return () => {
      window.clearTimeout(timer)
      controller.abort()
      schemaCandidateGeneration.current += 1
    }
  }, [appliedSchemaQuery, loadSchemaCandidates])

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
  const schemaChanged = selectedTableIds.size > 0 && selectedSystemIds.size > 0
  const schemaReasonValid = schemaReason.trim().length >= 10 && schemaReason.trim().length <= 1000

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

  const saveSchemaScopes = () => {
    if (
      !canUpdate
      || !schemaSystem
      || !schemaSystemVersion
      || !schemaChanged
      || !schemaReasonValid
    ) return
    const tableIds = [...selectedTableIds].sort()
    const systemIds = [...selectedSystemIds].sort()
    const intent = `table-system-mappings:${schemaSystemVersion}:${JSON.stringify({ mappingAction, tableIds, systemIds, reason: schemaReason.trim() })}`
    requestConfirmation({
      title: 'Table·System 연결 변경',
      summary: [
        `Table ${tableIds.length}개 · System ${systemIds.length}개`,
        `${mappingAction === 'ASSIGN' ? '연결' : '연결 제거'} ${tableIds.length * systemIds.length}개 pair`,
        '선택한 exact Table에만 적용되며 schema 자동 상속은 없습니다.',
      ],
      execute: async () => {
        await api.patchTableSystemMappings(
          mappingAction,
          tableIds,
          systemIds,
          schemaReason.trim(),
          schemaSystemVersion,
        )
        clearKey(intent)
        setSelectedTableIds(new Set())
        setSchemaReason('')
        await Promise.all([loadSchemaCandidates(), loadSystems()])
      },
    })
  }

  const openSchemaDirectory = useCallback((system: SystemDirectoryEntry) => {
    setSchemaSystem(system)
    setSchemaOpen(true)
    setSchemaCandidates([])
    setSchemaSystemVersion(0)
    setSchemaQuery('')
    setAppliedSchemaQuery('')
    setSchemaFilter('')
    setSystemFilter('')
    setSecurityGradeFilter('')
    setSelectedTableIds(new Set())
    setSelectedSystemIds(new Set(system.active ? [system.system_id] : []))
    setMappingAction('ASSIGN')
    setLastSelectedIndex(undefined)
    setSchemaReason('')
  }, [])

  const toggleTableSelection = (index: number, checked: boolean, shiftKey: boolean) => {
    setSelectedTableIds((current) => {
      const next = new Set(current)
      const start = shiftKey && lastSelectedIndex !== undefined ? Math.min(lastSelectedIndex, index) : index
      const end = shiftKey && lastSelectedIndex !== undefined ? Math.max(lastSelectedIndex, index) : index
      for (let candidateIndex = start; candidateIndex <= end; candidateIndex += 1) {
        const tableId = schemaCandidates[candidateIndex]?.table_identity
        if (!tableId) continue
        if (checked) next.add(tableId)
        else next.delete(tableId)
      }
      return next
    })
    setLastSelectedIndex(index)
  }

  const openSystemEdit = (system: SystemDirectoryEntry) => {
    setEditForm({ name: system.name, description: system.description })
    setEditOpen(true)
  }

  const saveSystemEdit = () => {
    if (!selected || !editForm.name.trim() || editForm.name.length > 255 || editForm.description.length > 2000) return
    const payload = { name: editForm.name.trim(), description: editForm.description.trim(), active: selected.active }
    const intent = `system-update:${selected.system_id}:${selected.version}:${JSON.stringify(payload)}`
    requestConfirmation({
      title: 'System 정보 변경',
      summary: [selected.code, payload.name, 'System 코드는 변경하지 않습니다.'],
      execute: async () => {
        await api.updateSystem(selected.system_id, payload, selected.version, keyFor(intent, 'admin-system-update'))
        clearKey(intent)
        setEditOpen(false)
        await loadSystems()
      },
    })
  }

  const changeSystemActive = (system: SystemDirectoryEntry, active: boolean) => {
    const intent = `system-active:${system.system_id}:${system.version}:${active}`
    requestConfirmation({
      title: active ? 'System 재활성' : 'System 아카이브',
      summary: active
        ? [`${system.name} (${system.code})`, '기존 exact Table 연결 이력은 보존됩니다.']
        : [`${system.name} (${system.code})`, '담당자와 legacy schema 연결은 비활성화하고 이력은 보존합니다.', 'exact Table 연결도 삭제하지 않으며 비활성 System에는 효력이 없습니다.'],
      execute: async () => {
        await api.updateSystem(system.system_id, {
          name: system.name,
          description: system.description,
          active,
        }, system.version, keyFor(intent, active ? 'admin-system-reactivate' : 'admin-system-archive'))
        clearKey(intent)
        await loadSystems()
      },
    })
  }

  const handleDirectoryAction = useCallback((event: MouseEvent<HTMLElement>) => {
    const target = (event.target as HTMLElement).closest<HTMLButtonElement>(
      'button[data-schema-system-id]',
    )
    if (!target) return
    const system = systems.find((item) => item.system_id === target.dataset.schemaSystemId)
    if (!system) return
    event.preventDefault()
    event.stopPropagation()
    openSchemaDirectory(system)
  }, [openSchemaDirectory, systems])

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

  return <section className="panel admin-system-directory" onClickCapture={handleDirectoryAction}>
    <div className="section-heading"><div><h3>System Master 및 Table 연결</h3><p className="muted">System 정본과 담당자는 기존 access authority를 사용하고, exact Table 연결은 독립 CAS 버전으로 관리합니다.</p></div><div className="action-row"><button className="button" disabled={!canUpdate} onClick={() => { setCreateOpen(true); setCreateValidationError('') }} type="button">시스템 추가</button><button className="button button-secondary" onClick={() => void loadSystems()} type="button">새로고침</button></div></div>
    <label className="mb-3 block max-w-md text-xs font-bold">시스템 검색<input type="search" value={systemQuery} onChange={(event) => setSystemQuery(event.target.value)} placeholder="시스템명 또는 코드" /></label>
    <DenseDataTable
      caption="워크스페이스 시스템 목록"
      columns={[
        { accessorKey: 'code', header: '코드', size: 125 },
        { accessorKey: 'name', header: '시스템명', size: 170, cell: ({ row }) => <strong>{row.original.name}</strong> },
        { accessorKey: 'description', header: '시스템 설명', size: 260, cell: ({ row }) => row.original.description || '설명 없음' },
        { accessorKey: 'assignee_count', header: '담당자 수', size: 100 },
        { id: 'tables', header: 'Table 연결', size: 160, cell: ({ row }) => <button className="button button-secondary" data-schema-system-id={row.original.system_id} type="button">Table 관리</button> },
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
      {canUpdate ? <div className="action-row"><button className="button" disabled={!draftValid || !changed} onClick={() => void save()} type="button">담당자 저장</button><button className="button button-secondary" onClick={() => openSystemEdit(selected)} type="button">System 정보 수정</button><button className={selected.active ? 'button button-danger' : 'button button-secondary'} onClick={() => changeSystemActive(selected, !selected.active)} type="button">{selected.active ? 'System 아카이브' : 'System 재활성'}</button>{!draftValid && <small className="muted">담당자·우선순위가 중복되거나 유효하지 않습니다.</small>}</div> : <p className="callout">서버가 현재 세션에 시스템 담당자 변경 권한을 허용하지 않았습니다.</p>}
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
    <Dialog open={editOpen} title="System 정보 수정" size="medium" onRequestClose={() => setEditOpen(false)}>
      <div className="grid gap-3">
        <p className="callout">System code와 ID는 stable identity이므로 변경하지 않습니다.</p>
        <label className="block text-sm font-bold">시스템 이름
          <input className="mt-1 block w-full" maxLength={255} onChange={(event) => setEditForm((current) => ({ ...current, name: event.target.value }))} required type="text" value={editForm.name} />
        </label>
        <label className="block text-sm font-bold">설명
          <textarea className="mt-1 block w-full h-24" maxLength={2000} onChange={(event) => setEditForm((current) => ({ ...current, description: event.target.value }))} value={editForm.description} />
        </label>
        <div className="flex justify-end gap-2">
          <button className="button button-secondary" onClick={() => setEditOpen(false)} type="button">취소</button>
          <button className="button" disabled={!editForm.name.trim()} onClick={saveSystemEdit} type="button">저장</button>
        </div>
      </div>
    </Dialog>
    <Dialog
      open={schemaOpen}
      title="Table ↔ System 연결"
      size="large"
      onRequestClose={() => setSchemaOpen(false)}
    >
      <div className="grid gap-4">
        <div className="callout">
          선택한 <strong>exact DataHub Table URN</strong>에만 System을 연결합니다.
          schema 필터와 전체 선택은 현재 검색 결과를 일괄 선택하는 UX이며 새 Table에 자동 상속되지 않습니다.
        </div>
        <section aria-labelledby="table-system-candidates-title">
          <div className="section-heading"><div><h4 id="table-system-candidates-title">현재 Catalog Table 선택</h4><p className="muted">mapping v{schemaSystemVersion} · {schemaCandidates.length.toLocaleString()}개 표시</p></div></div>
          <div className="grid gap-2 md:grid-cols-4">
            <label className="text-xs font-bold">Table 검색<input type="search" value={schemaQuery} onChange={(event) => setSchemaQuery(event.target.value)} placeholder="Table, schema 또는 URN" /></label>
            <label className="text-xs font-bold">Schema<select onChange={(event) => setSchemaFilter(event.target.value)} value={schemaFilter}><option value="">전체</option>{availableSchemas.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
            <label className="text-xs font-bold">System filter<select onChange={(event) => setSystemFilter(event.target.value)} value={systemFilter}><option value="">전체</option>{systems.filter((system) => system.active).map((system) => <option key={system.system_id} value={system.system_id}>{system.name}</option>)}</select></label>
            <label className="text-xs font-bold">Security grade<select onChange={(event) => setSecurityGradeFilter(event.target.value as TableSecurityGrade | '')} value={securityGradeFilter}><option value="">전체</option><option value="normal">normal</option><option value="restricted">restricted</option><option value="credential">credential</option></select></label>
          </div>
          <div className="my-3 flex flex-wrap items-center gap-2">
            <button className="button button-secondary button-compact" disabled={!selectionComplete || schemaCandidates.length === 0} onClick={() => setSelectedTableIds(new Set(schemaCandidates.map((item) => item.table_identity)))} type="button">현재 결과 전체 선택</button>
            <button className="button button-secondary button-compact" disabled={selectedTableIds.size === 0} onClick={() => setSelectedTableIds(new Set())} type="button">선택 해제</button>
            <span className="muted">선택 {selectedTableIds.size.toLocaleString()}개{!selectionComplete ? ' · 결과가 제한되어 전체 선택 비활성' : ''}</span>
          </div>
          <DenseDataTable
            caption="exact Table-System 연결 후보"
            columns={[
              { id: 'select', header: '선택', size: 64, cell: ({ row }) => <input aria-label={`${row.original.table_name} Table 선택`} checked={selectedTableIds.has(row.original.table_identity)} disabled={!canUpdate} onClick={(event) => toggleTableSelection(row.index, !selectedTableIds.has(row.original.table_identity), event.shiftKey)} readOnly type="checkbox" /> },
              { accessorKey: 'table_name', header: 'Table', size: 180 },
              { accessorKey: 'platform', header: 'Platform', size: 110 },
              { accessorKey: 'database_name', header: 'Database', size: 130 },
              { accessorKey: 'schema_name', header: 'Schema', size: 130 },
              { accessorKey: 'security_grade', header: 'Security grade', size: 110 },
              { id: 'mapping', header: '현재 System', size: 220, cell: ({ row }) => row.original.system_ids.length ? row.original.system_ids.map((id) => systems.find((system) => system.system_id === id)?.name ?? id).join(', ') : '미연결' },
            ]}
            data={schemaCandidates}
            emptyMessage="현재 조건에 맞는 TABLE이 없습니다."
            getRowId={(asset) => asset.table_identity}
            loading={schemaLoading}
          />
        </section>
        <fieldset className="grid gap-2"><legend className="text-sm font-bold">변경 대상 System</legend>
          <div className="flex flex-wrap gap-3">{systems.filter((system) => system.active).map((system) => <label className="flex items-center gap-2 text-sm" key={system.system_id}><input checked={selectedSystemIds.has(system.system_id)} onChange={(event) => setSelectedSystemIds((current) => { const next = new Set(current); if (event.target.checked) next.add(system.system_id); else next.delete(system.system_id); return next })} type="checkbox" />{system.name} ({system.code})</label>)}</div>
        </fieldset>
        <fieldset className="flex gap-4"><legend className="text-sm font-bold">작업</legend><label><input checked={mappingAction === 'ASSIGN'} onChange={() => setMappingAction('ASSIGN')} type="radio" /> 연결</label><label><input checked={mappingAction === 'REMOVE'} onChange={() => setMappingAction('REMOVE')} type="radio" /> 연결 제거</label></fieldset>
        <label className="block text-sm font-bold">변경 사유
          <textarea className="mt-1 block w-full" maxLength={1000} minLength={10} onChange={(event) => setSchemaReason(event.target.value)} placeholder="exact Table 연결 변경 사유를 10자 이상 입력" rows={3} value={schemaReason} />
        </label>
        {!canUpdate && <p className="callout">서버가 현재 세션에 Table·System 연결 변경 권한을 허용하지 않았습니다.</p>}
        <div className="flex justify-end gap-2">
          <button className="button button-secondary" onClick={() => setSchemaOpen(false)} type="button">취소</button>
          <button aria-label="Table System 연결 변경사항 저장" className="button" disabled={!canUpdate || !schemaChanged || !schemaReasonValid || schemaLoading} onClick={saveSchemaScopes} type="button">변경사항 저장</button>
        </div>
      </div>
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
