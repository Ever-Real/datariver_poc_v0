import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  AccessRole,
  AccessRoleCapabilityCatalog,
  AccessRoleDataRule,
  AccessRoleWrite,
  Classification,
  DataAccessLevel,
  DataProcessingPurpose,
} from '../../api/types'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import type { AdminSectionProps } from './MembershipAdmin'

const classifications: Classification[] = ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED']
const processingPurposes: DataProcessingPurpose[] = [
  'METADATA_READ', 'DATA_READ', 'EXPORT', 'ANALYTICS', 'MODEL_TRAINING',
]

const emptyRole = (): AccessRoleWrite => ({
  role_key: '', name: '', description: '', clearance: 'PUBLIC', groups: [],
  allowed_actions: [], denied_actions: [], allowed_system_ids: [], allowed_domain_ids: [],
  data_access_rules: [], active: true,
})

function lines(value: string): string[] {
  return [...new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean))]
}

function dataAccessSummary(role: AccessRole) {
  const rules = new Map(role.data_access_rules.map((rule) => [rule.classification, rule.access_level]))
  return classifications.map((classification) => `${classification}: ${rules.get(classification) ?? 'MISSING'}`).join(' · ')
}

function dataAccessLabel(level: DataAccessLevel | 'MISSING') {
  if (level === 'NO_ACCESS') return 'None'
  if (level === 'PARTIAL_ACCESS') return 'Partial'
  if (level === 'FULL_ACCESS') return 'Full'
  return 'MISSING'
}

export function RoleManagementDialog({
  open,
  onRequestClose,
  ...props
}: { open: boolean; onRequestClose: () => void } & AdminSectionProps) {
  const { api, context, requestConfirmation, clearKey, reportError } = props
  const [roles, setRoles] = useState<AccessRole[]>([])
  const [query, setQuery] = useState('')
  const [appliedQuery, setAppliedQuery] = useState('')
  const [cursor, setCursor] = useState<string>()
  const [cursorHistory, setCursorHistory] = useState<string[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [pageNumber, setPageNumber] = useState(1)
  const [editingId, setEditingId] = useState<string>()
  const [draft, setDraft] = useState<AccessRoleWrite>(emptyRole)
  const [groupText, setGroupText] = useState('')
  const [systemText, setSystemText] = useState('')
  const [domainText, setDomainText] = useState('')
  const [capabilityCatalog, setCapabilityCatalog] = useState<AccessRoleCapabilityCatalog>()
  const [capabilityCatalogFailed, setCapabilityCatalogFailed] = useState(false)
  const generation = useRef(0)
  const canUpdate = context?.allowed_operations.includes('MEMBERSHIP_ACCESS_UPDATE') ?? false

  const loadRoles = useCallback(async (signal?: AbortSignal) => {
    const requestGeneration = ++generation.current
    try {
      const page = await api.listAccessRolePage({
        query: appliedQuery || undefined, cursor, limit: 25, signal,
      })
      if (signal?.aborted || requestGeneration !== generation.current) return
      setRoles(page.items)
      setNextCursor(page.nextCursor)
    } catch (error) {
      if (!signal?.aborted && requestGeneration === generation.current) reportError(error)
    }
  }, [api, appliedQuery, cursor, reportError])

  useEffect(() => {
    if (!open) return
    const timer = window.setTimeout(() => {
      setAppliedQuery(query.trim())
      setCursor(undefined)
      setCursorHistory([])
      setPageNumber(1)
    }, 250)
    return () => window.clearTimeout(timer)
  }, [open, query])
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    void loadRoles(controller.signal)
    return () => {
      controller.abort()
      generation.current += 1
    }
  }, [loadRoles, open])
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    setCapabilityCatalog(undefined)
    setCapabilityCatalogFailed(false)
    void api.getAccessRoleCapabilities(controller.signal)
      .then((catalog) => {
        if (!controller.signal.aborted) setCapabilityCatalog(catalog)
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setCapabilityCatalogFailed(true)
          reportError(error)
        }
      })
    return () => controller.abort()
  }, [api, open, reportError])

  const editingRole = roles.find((role) => role.id === editingId)
  const securityLocked = Boolean(editingRole?.assigned_count)
  const startNew = () => {
    setEditingId('NEW')
    setDraft(emptyRole())
    setGroupText('')
    setSystemText('')
    setDomainText('')
  }
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
    setGroupText(role.groups.join('\n'))
    setSystemText(role.allowed_system_ids.join('\n'))
    setDomainText(role.allowed_domain_ids.join('\n'))
  }
  const payload = (): AccessRoleWrite => ({
    ...draft,
    groups: lines(groupText),
    allowed_system_ids: lines(systemText),
    allowed_domain_ids: lines(domainText),
  })
  const updateDataRule = (
    classification: Classification,
    update: (rule: AccessRoleDataRule) => AccessRoleDataRule,
  ) => setDraft((current) => ({
    ...current,
    data_access_rules: current.data_access_rules.map((rule) => (
      rule.classification === classification ? update(rule) : rule
    )),
  }))
  const setDataAccessLevel = (
    classification: Classification,
    accessLevel: DataAccessLevel | 'MISSING',
  ) => setDraft((current) => {
    const existing = current.data_access_rules.find((rule) => rule.classification === classification)
    const remaining = current.data_access_rules.filter((rule) => rule.classification !== classification)
    if (accessLevel === 'MISSING') return { ...current, data_access_rules: remaining }
    const next: AccessRoleDataRule = accessLevel === 'NO_ACCESS'
      ? {
          classification, access_level: accessLevel, partial_treatment: null,
          allowed_residency_regions: [], allowed_processing_purposes: [],
        }
      : {
          classification, access_level: accessLevel,
          partial_treatment: accessLevel === 'PARTIAL_ACCESS'
            ? existing?.partial_treatment ?? 'MASK'
            : null,
          allowed_residency_regions: existing?.allowed_residency_regions ?? [],
          allowed_processing_purposes: existing?.allowed_processing_purposes ?? [],
        }
    return {
      ...current,
      data_access_rules: classifications.map((value) => (
        value === classification ? next : current.data_access_rules.find((rule) => rule.classification === value)
      )).filter((rule): rule is AccessRoleDataRule => Boolean(rule)),
    }
  })
  const setAction = (action: string, effect: 'NONE' | 'ALLOW' | 'DENY') => {
    setDraft((current) => ({
      ...current,
      allowed_actions: effect === 'ALLOW'
        ? [...new Set([...current.allowed_actions, action])]
        : current.allowed_actions.filter((value) => value !== action),
      denied_actions: effect === 'DENY'
        ? [...new Set([...current.denied_actions, action])]
        : current.denied_actions.filter((value) => value !== action),
    }))
  }
  const dataRulesValid = draft.data_access_rules.every((rule) => (
    rule.access_level === 'NO_ACCESS'
    || (rule.allowed_residency_regions.length > 0 && rule.allowed_processing_purposes.length > 0
      && (rule.access_level !== 'PARTIAL_ACCESS' || rule.partial_treatment !== null))
  ))
  const save = () => {
    if (!capabilityCatalog) return
    const next = payload()
    if (!canUpdate || !next.role_key || !next.name.trim() || !dataRulesValid) return
    const intent = `access-role:${editingId ?? 'NEW'}:${editingRole?.version ?? 0}:${JSON.stringify(next)}`
    requestConfirmation({
      title: editingRole ? `${editingRole.name} Role 편집` : '신규 Role 생성',
      summary: [next.role_key, next.clearance, dataAccessSummary({ ...next, id: '', assigned_count: 0, version: 0, created_at: '', updated_at: '' })],
      execute: async () => {
        if (editingRole) await api.updateAccessRole(editingRole, next)
        else await api.createAccessRole(next)
        clearKey(intent)
        await loadRoles()
        startNew()
      },
    })
  }
  const deactivate = () => {
    if (!editingRole || !canUpdate) return
    const intent = `access-role-deactivate:${editingRole.id}:${editingRole.version}`
    requestConfirmation({
      title: `${editingRole.name} Role 비활성화`,
      summary: [editingRole.role_key, `할당 사용자 ${editingRole.assigned_count}명`, '사용 중 Role은 서버가 거부합니다.'],
      execute: async () => {
        await api.deactivateAccessRole(editingRole)
        clearKey(intent)
        await loadRoles()
        startNew()
      },
    })
  }
  const close = () => {
    setEditingId(undefined)
    setDraft(emptyRole())
    setGroupText('')
    setSystemText('')
    setDomainText('')
    onRequestClose()
  }

  return <Dialog open={open} size="large" title="Role 관리" description="Role 정의와 데이터 접근 수준은 기존의 서버 관리 RBAC API에 저장됩니다." onRequestClose={close} footer={<><button type="button" className="button button-secondary" onClick={close}>취소</button><button type="button" className="button" disabled={!editingId || !canUpdate || !capabilityCatalog || !draft.role_key || !draft.name.trim() || !dataRulesValid} onClick={save}>저장</button></>}>
    <div className="grid gap-4">
      <section className="grid gap-3">
        <div className="section-heading"><div><h3>Role 목록</h3><p className="muted">서버 페이지 단위의 Role 정의입니다.</p></div><div className="action-row"><button type="button" className="button button-secondary" onClick={() => void loadRoles()}>새로고침</button><button type="button" className="button" disabled={!canUpdate} onClick={startNew}>+ Role 추가</button></div></div>
        <label className="max-w-md text-xs font-bold">Role 검색<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Role 이름 또는 key" /></label>
        <DenseDataTable
          caption="Role 목록"
          columns={[
            { accessorKey: 'name', header: 'Role 이름', size: 180, cell: ({ row }) => <><strong>{row.original.name}</strong><small>{row.original.role_key}</small></> },
            { accessorKey: 'description', header: '설명', size: 240, cell: ({ row }) => row.original.description || '—' },
            { accessorKey: 'clearance', header: '등급', size: 110, cell: ({ row }) => <span className="badge badge-soft">{row.original.clearance}</span> },
            { id: 'dataAccess', header: '데이터 접근 수준', size: 360, cell: ({ row }) => <small>{dataAccessSummary(row.original)}</small> },
          ]}
          data={roles}
          getRowId={(role) => role.id}
          selectedRowId={editingRole?.id}
          onRowActivate={edit}
          emptyMessage="등록된 Role이 없습니다."
        />
        <div className="flex items-center justify-end gap-2"><span className="text-xs text-slate-600">페이지 {pageNumber}</span><button type="button" className="button button-secondary" disabled={cursorHistory.length === 0} onClick={() => { const previous = cursorHistory.at(-1); setCursorHistory((current) => current.slice(0, -1)); setCursor(previous || undefined); setPageNumber((current) => Math.max(1, current - 1)) }}>이전</button><button type="button" className="button button-secondary" disabled={!nextCursor} onClick={() => { if (!nextCursor) return; setCursorHistory((current) => [...current.slice(-49), cursor ?? '']); setCursor(nextCursor); setPageNumber((current) => current + 1) }}>다음</button></div>
      </section>
      {editingId && <section className="grid gap-3 border-t border-slate-300 pt-4" aria-label="Role 편집">
        <div><h3 className="m-0">{editingRole ? 'Role 편집' : '신규 Role'}</h3><p className="muted">사용 중인 Role은 보안 정의를 변경하거나 비활성화할 수 없습니다.</p></div>
        <div className="grid gap-2 md:grid-cols-2"><label>Role Key<input value={draft.role_key} disabled={editingId !== 'NEW'} pattern="[a-z][a-z0-9-]{1,79}" onChange={(event) => setDraft({ ...draft, role_key: event.target.value })} /></label><label>Role 이름<input value={draft.name} maxLength={255} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label></div>
        <label>설명<textarea value={draft.description} maxLength={4000} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
        {securityLocked && <p className="callout m-0">{editingRole?.assigned_count}명의 사용자에게 할당되어 보안 정의는 잠겼습니다. 이름과 설명만 변경할 수 있습니다.</p>}
        <label className="max-w-xs">등급<select disabled={securityLocked} value={draft.clearance} onChange={(event) => setDraft({ ...draft, clearance: event.target.value as AccessRoleWrite['clearance'] })}><option>PUBLIC</option><option>INTERNAL</option><option>CONFIDENTIAL</option><option>RESTRICTED</option></select></label>
        <section className="grid gap-2 rounded-enterprise border border-slate-300 bg-slate-50 p-3" aria-labelledby="data-access-grid-title">
          <div><h4 className="m-0 text-sm" id="data-access-grid-title">데이터 접근 수준</h4><p className="mb-0 mt-1 text-xs text-slate-600">등급별 접근 수준을 가로 표에서 직접 설정합니다. API의 실제 정책 값만 사용하며, 누락은 fail-closed 입니다.</p></div>
          <div className="overflow-x-auto"><table className="admin-access-level-grid" aria-label="데이터 접근 수준"><thead><tr><th scope="col">분류</th>{classifications.map((classification) => <th scope="col" key={classification}>{classification[0]}{classification.slice(1).toLowerCase()}</th>)}</tr></thead><tbody><tr><th scope="row">접근 수준</th>{classifications.map((classification) => { const rule = draft.data_access_rules.find((item) => item.classification === classification); const level = rule?.access_level ?? 'MISSING'; return <td key={classification}><select aria-label={`${classification} 접근 수준`} disabled={securityLocked} value={level} onChange={(event) => setDataAccessLevel(classification, event.target.value as DataAccessLevel | 'MISSING')}><option value="MISSING">MISSING</option><option value="NO_ACCESS">None</option><option value="PARTIAL_ACCESS">Partial</option><option value="FULL_ACCESS">Full</option></select><small>{dataAccessLabel(level)}</small></td> })}</tr></tbody></table></div>
          {draft.data_access_rules.length < classifications.length && <p className="callout m-0">누락된 분류 등급은 서버에서 차단됩니다.</p>}
          {!dataRulesValid && <p className="notice notice-error m-0" role="note">Partial/Full 규칙에는 상주 지역과 하나 이상의 처리 목적이 필요합니다.</p>}
        </section>
        <details className="rounded-enterprise border border-slate-300 bg-slate-50 p-3"><summary className="cursor-pointer text-xs font-black text-navy-900">추가 정책 조건</summary><div className="mt-3 grid gap-3"><label>그룹<textarea disabled={securityLocked} value={groupText} onChange={(event) => setGroupText(event.target.value)} /></label><fieldset className="action-matrix"><legend>서비스별 Action</legend><p className="callout m-0">자기승인 표시는 향후 보호된 정책 바인딩을 위한 metadata이며, 현재 승인 동작을 활성화하지 않습니다.</p>{!capabilityCatalog && !capabilityCatalogFailed && <p role="status">서버 Action catalog를 불러오는 중입니다.</p>}{capabilityCatalogFailed && <p className="notice notice-error m-0" role="alert">서버 Action catalog를 불러오지 못해 Role 저장을 차단했습니다.</p>}{capabilityCatalog?.services.map((service) => <section className="grid gap-2 rounded-enterprise border border-slate-200 p-3" key={service.service_key} aria-labelledby={`capability-service-${service.service_key}`}><div><h5 className="m-0 text-sm" id={`capability-service-${service.service_key}`}>{service.label}</h5><p className="mb-0 mt-1 text-xs text-slate-600">{service.description}</p></div>{service.actions.map((capability) => { const effect = draft.allowed_actions.includes(capability.action) ? 'ALLOW' : draft.denied_actions.includes(capability.action) ? 'DENY' : 'NONE'; const serviceOnly = capability.assignability === 'SERVICE_PRINCIPAL_ONLY'; return <label key={capability.action}><span><strong>{capability.label}</strong> <code>{capability.action}</code><small>{capability.description} · assurance: {capability.assurance} · risk: {capability.risk}{capability.reason_policy === 'REQUIRED' ? ' · 사유 필수' : ''}{capability.self_approval_binding === 'PENDING_PROTECTED_BINDING' ? ' · 자기승인 보호 바인딩 대기' : ''}{serviceOnly ? ' · service principal 전용' : ''}</small></span><select aria-label={`Role ${capability.action}`} disabled={securityLocked || serviceOnly} value={effect} onChange={(event) => setAction(capability.action, event.target.value as 'NONE' | 'ALLOW' | 'DENY')}><option value="NONE">—</option><option value="ALLOW">ALLOW</option><option value="DENY">DENY</option></select></label> })}</section>)}</fieldset><label>System IDs<textarea disabled={securityLocked} value={systemText} onChange={(event) => setSystemText(event.target.value)} /></label><label>Domain IDs<textarea disabled={securityLocked} value={domainText} onChange={(event) => setDomainText(event.target.value)} /></label>{classifications.map((classification) => { const rule = draft.data_access_rules.find((item) => item.classification === classification); if (!rule || rule.access_level === 'NO_ACCESS') return null; return <fieldset className="grid gap-2 rounded-enterprise border border-slate-200 p-3" disabled={securityLocked} key={classification}><legend className="px-1 text-xs font-black">{classification} 추가 조건</legend>{rule.access_level === 'PARTIAL_ACCESS' && <label>부분 처리 방식<select value={rule.partial_treatment ?? 'MASK'} onChange={(event) => updateDataRule(classification, (current) => ({ ...current, partial_treatment: event.target.value as AccessRoleDataRule['partial_treatment'] }))}><option>MASK</option><option>REDACT</option><option>TOKENIZE</option></select></label>}<label>상주 지역<textarea value={rule.allowed_residency_regions.join('\n')} onChange={(event) => updateDataRule(classification, (current) => ({ ...current, allowed_residency_regions: lines(event.target.value).map((value) => value.toUpperCase()) }))} /></label><fieldset className="grid gap-1"><legend>처리 목적</legend>{processingPurposes.map((purpose) => <label className="checkbox-line" key={purpose}><input type="checkbox" checked={rule.allowed_processing_purposes.includes(purpose)} onChange={(event) => updateDataRule(classification, (current) => ({ ...current, allowed_processing_purposes: event.target.checked ? [...new Set([...current.allowed_processing_purposes, purpose])] : current.allowed_processing_purposes.filter((value) => value !== purpose) }))} />{purpose}</label>)}</fieldset></fieldset> })}</div></details>
        {editingRole && <div className="action-row"><button type="button" className="button button-danger" disabled={!canUpdate || editingRole.assigned_count > 0 || !editingRole.active} onClick={deactivate}>Role 삭제</button></div>}
      </section>}
    </div>
  </Dialog>
}
